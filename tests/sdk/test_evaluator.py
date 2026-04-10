import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import asyncio
from qym.core.dashboard import RunDashboard
from qym.core.evaluator import Evaluator, ItemSpans, TaskAttemptResult, _graceful_interrupt_signals
from qym.core.dataset import CsvDataset
import signal

class TestEvaluator:
    def test_graceful_interrupt_signals_translate_sigterm_to_keyboard_interrupt(self):
        previous = signal.getsignal(signal.SIGTERM)
        with _graceful_interrupt_signals():
            handler = signal.getsignal(signal.SIGTERM)
            assert callable(handler)
            with pytest.raises(KeyboardInterrupt):
                handler(signal.SIGTERM, None)
        assert signal.getsignal(signal.SIGTERM) == previous

    def test_init(self, mock_task, mock_langfuse, mock_dataset):
        """Test basic initialization of Evaluator with DI."""
        with patch("qym.core.evaluator.auto_detect_task"):
            evaluator = Evaluator(
                task=mock_task,
                dataset=mock_dataset,  # Injected dataset
                metrics=["exact_match"],
                config={"run_name": "test-run"},
                langfuse_client=mock_langfuse  # Injected client
            )
            
            assert evaluator.dataset == mock_dataset
            assert evaluator.client == mock_langfuse
            # Evaluator appends a timestamp suffix for uniqueness
            assert evaluator.run_name.startswith("test-run")
            assert "exact_match" in evaluator.metrics

    @pytest.mark.asyncio
    async def test_evaluate_item_success(self, mock_task, mock_langfuse, mock_dataset):
        """Test _evaluate_item method success path."""
        with patch("qym.core.evaluator.auto_detect_task"):
            evaluator = Evaluator(
                task=mock_task,
                dataset=mock_dataset,
                metrics=[],
                config={"run_name": "test-run"},
                langfuse_client=mock_langfuse
            )
            
            # Mock internal components
            evaluator.task_adapter = MagicMock()
            evaluator.task_adapter.arun = AsyncMock(return_value="test_output")
            evaluator._notify_observer = MagicMock()
            evaluator._compute_metric = AsyncMock(return_value=1.0)
            evaluator.model_name = "test-model"
            
            # Mock item
            item = MagicMock()
            item.input = "test_input"
            item.run.return_value.__enter__.return_value = MagicMock()
            
            tracker = MagicMock()
            
            result = await evaluator._evaluate_item(0, item, tracker)
            
            assert result["success"] is True
            assert result["output"] == "test_output"
            tracker.start_item.assert_called_once_with(0)
            tracker.complete_item.assert_called_once_with(0)

    @pytest.mark.asyncio
    async def test_csv_dataset_without_langfuse_credentials_does_not_require_client(self, tmp_path, mock_task, monkeypatch):
        p = tmp_path / "qa.csv"
        p.write_text("q,a\nhello,world\n", encoding="utf-8")
        ds = CsvDataset(p, input_col="q", expected_col="a")

        # Ensure a deterministic no-credentials environment even if the developer machine has Langfuse env vars.
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

        with patch("qym.core.evaluator.auto_detect_task"):
            evaluator = Evaluator(
                task=mock_task,
                dataset=ds,
                metrics=[],
                config={"run_name": "csv-run"},
                langfuse_client=None,
            )

        assert evaluator.client is None

        evaluator.task_adapter = MagicMock()
        evaluator.task_adapter.arun = AsyncMock(return_value="ok")
        evaluator._notify_observer = MagicMock()
        evaluator.model_name = "test-model"

        item = ds.get_items()[0]
        tracker = MagicMock()
        res = await evaluator._evaluate_item(0, item, tracker)
        assert res["success"] is True
        assert res["output"] == "ok"

    @pytest.mark.asyncio
    async def test_run_single_task_attempt_emits_item_attempt_started(self, mock_task, mock_langfuse, mock_dataset):
        with patch("qym.core.evaluator.auto_detect_task"):
            evaluator = Evaluator(
                task=mock_task,
                dataset=mock_dataset,
                metrics=[],
                config={"run_name": "attempt-start"},
                langfuse_client=mock_langfuse,
            )

        evaluator.task_adapter = MagicMock()
        evaluator.task_adapter.arun = AsyncMock(return_value="ok")
        evaluator.model_name_full = "test-model"
        evaluator._platform_stream = MagicMock()
        evaluator._create_item_spans = MagicMock(return_value=ItemSpans(trace_id="trace-1", trace_url="url-1"))

        item = MagicMock()
        item.input = "test_input"
        item.id = "item-1"

        result = await evaluator._run_single_task_attempt(0, item, 1)

        assert result.success is True
        assert result.spans.trace_id == "trace-1"
        emitted = [call.args for call in evaluator._platform_stream.emit.call_args_list]
        started = [payload for event_type, payload in emitted if event_type == "item_attempt_started"]
        assert len(started) == 1
        assert started[0]["item_id"] == "item-1"
        assert started[0]["attempt_number"] == 1
        assert started[0]["trace_id"] == "trace-1"
        assert started[0]["trace_url"] == "url-1"
        assert started[0]["task_started_at_ms"] is not None

    @pytest.mark.asyncio
    async def test_evaluate_item_uses_last_attempt_trace_and_time(self, mock_task, mock_langfuse, mock_dataset):
        with patch("qym.core.evaluator.auto_detect_task"):
            evaluator = Evaluator(
                task=mock_task,
                dataset=mock_dataset,
                metrics=[],
                config={"run_name": "retry-last-attempt"},
                langfuse_client=mock_langfuse,
            )

        evaluator._notify_observer = MagicMock()
        evaluator._compute_metrics = AsyncMock(return_value={})
        evaluator._platform_stream = MagicMock()

        attempt_one = TaskAttemptResult(
            attempt_number=1,
            spans=ItemSpans(trace_id="trace-1", trace_url="url-1"),
            task_started_at_ms=1111,
            latency_s=0.75,
            error="boom",
        )
        attempt_two = TaskAttemptResult(
            attempt_number=2,
            spans=ItemSpans(trace_id="trace-2", trace_url="url-2"),
            task_started_at_ms=2222,
            latency_s=0.25,
            output="final-output",
        )
        evaluator._execute_task = AsyncMock(return_value=(attempt_two, [attempt_one, attempt_two], 1))

        item = MagicMock()
        item.input = "test_input"
        item.expected_output = "expected"
        item.id = "item-1"

        tracker = MagicMock()
        result = await evaluator._evaluate_item(0, item, tracker)

        assert result["success"] is True
        assert result["trace_id"] == "trace-2"
        assert result["time"] == pytest.approx(0.25)
        assert result["retry_count"] == 1

        emitted = [call.args for call in evaluator._platform_stream.emit.call_args_list]
        completed = [payload for event_type, payload in emitted if event_type == "item_completed"]
        attempt_events = [payload for event_type, payload in emitted if event_type == "item_attempt_finished"]
        assert completed[0]["trace_id"] == "trace-2"
        assert completed[0]["latency_ms"] == pytest.approx(250.0)
        assert attempt_events[0]["attempt_number"] == 2
        assert attempt_events[0]["is_last_attempt"] is True

    @pytest.mark.asyncio
    async def test_evaluate_item_failure_uses_last_failed_attempt_trace_and_time(self, mock_task, mock_langfuse, mock_dataset):
        with patch("qym.core.evaluator.auto_detect_task"):
            evaluator = Evaluator(
                task=mock_task,
                dataset=mock_dataset,
                metrics=[],
                config={"run_name": "retry-last-failure"},
                langfuse_client=mock_langfuse,
            )

        evaluator._notify_observer = MagicMock()
        evaluator._platform_stream = MagicMock()

        attempt_one = TaskAttemptResult(
            attempt_number=1,
            spans=ItemSpans(trace_id="trace-1", trace_url="url-1"),
            task_started_at_ms=1111,
            latency_s=0.75,
            error="boom-1",
        )
        attempt_two = TaskAttemptResult(
            attempt_number=2,
            spans=ItemSpans(trace_id="trace-2", trace_url="url-2"),
            task_started_at_ms=2222,
            latency_s=0.25,
            error="boom-2",
        )
        evaluator._execute_task = AsyncMock(return_value=(None, [attempt_one, attempt_two], 1))

        item = MagicMock()
        item.input = "test_input"
        item.expected_output = "expected"
        item.id = "item-1"

        tracker = MagicMock()
        result = await evaluator._evaluate_item(0, item, tracker)

        assert result["_trace_id"] == "trace-2"
        assert result["task_started_at_ms"] == 2222

        emitted = [call.args for call in evaluator._platform_stream.emit.call_args_list]
        failed = [payload for event_type, payload in emitted if event_type == "item_failed"]
        attempt_events = [payload for event_type, payload in emitted if event_type == "item_attempt_finished"]
        assert failed[0]["trace_id"] == "trace-2"
        assert failed[0]["latency_ms"] == pytest.approx(250.0)
        assert failed[0]["retry_count"] == 1
        assert attempt_events[0]["trace_id"] == "trace-2"
        assert attempt_events[0]["is_last_attempt"] is True


    def test_sync_threadpool_advisory_emitted_for_high_effective_concurrency(self, tmp_path, mock_task, monkeypatch):
        p = tmp_path / "qa.csv"
        p.write_text("q,a\nhello,world\n", encoding="utf-8")
        ds = CsvDataset(p, input_col="q", expected_col="a")

        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

        fake_adapter = MagicMock()
        fake_adapter.execution_mode.return_value = "sync-threadpool"
        fake_adapter._warning_callback = None

        with patch("qym.core.evaluator.auto_detect_task", return_value=fake_adapter):
            evaluator = Evaluator(
                task=mock_task,
                dataset=ds,
                metrics=[],
                config={"run_name": "sync-advisory", "max_concurrency": 5, "otel_enabled": False},
            )

        evaluator._notify_observer = MagicMock()
        evaluator._maybe_emit_sync_threadpool_advisory(parallel_runs=4)

        evaluator._notify_observer.assert_called_once()
        method = evaluator._notify_observer.call_args.args[0]
        message = evaluator._notify_observer.call_args.kwargs["message"]
        assert method == "on_warning"
        assert "sync-threadpool" in message
        assert "mock_task" in message
        assert "20" in message
        assert "AsyncOpenAI" in message

    def test_sync_threadpool_advisory_not_emitted_below_threshold(self, tmp_path, mock_task, monkeypatch):
        p = tmp_path / "qa.csv"
        p.write_text("q,a\nhello,world\n", encoding="utf-8")
        ds = CsvDataset(p, input_col="q", expected_col="a")

        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

        fake_adapter = MagicMock()
        fake_adapter.execution_mode.return_value = "sync-threadpool"
        fake_adapter._warning_callback = None

        with patch("qym.core.evaluator.auto_detect_task", return_value=fake_adapter):
            evaluator = Evaluator(
                task=mock_task,
                dataset=ds,
                metrics=[],
                config={"run_name": "sync-advisory-low", "max_concurrency": 5, "otel_enabled": False},
            )

        evaluator._notify_observer = MagicMock()
        evaluator._maybe_emit_sync_threadpool_advisory(parallel_runs=2)

        evaluator._notify_observer.assert_not_called()

    def test_sync_threadpool_advisory_not_emitted_for_async_mode(self, tmp_path, mock_task, monkeypatch):
        p = tmp_path / "qa.csv"
        p.write_text("q,a\nhello,world\n", encoding="utf-8")
        ds = CsvDataset(p, input_col="q", expected_col="a")

        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

        fake_adapter = MagicMock()
        fake_adapter.execution_mode.return_value = "async"
        fake_adapter._warning_callback = None

        with patch("qym.core.evaluator.auto_detect_task", return_value=fake_adapter):
            evaluator = Evaluator(
                task=mock_task,
                dataset=ds,
                metrics=[],
                config={"run_name": "async-mode", "max_concurrency": 5, "otel_enabled": False},
            )

        evaluator._notify_observer = MagicMock()
        evaluator._maybe_emit_sync_threadpool_advisory(parallel_runs=4)

        evaluator._notify_observer.assert_not_called()

    def test_sync_threadpool_advisory_emitted_once_per_unique_task(self, tmp_path, mock_task, monkeypatch):
        p = tmp_path / "qa.csv"
        p.write_text("q,a\nhello,world\n", encoding="utf-8")
        ds = CsvDataset(p, input_col="q", expected_col="a")

        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

        fake_adapter = MagicMock()
        fake_adapter.execution_mode.return_value = "sync-threadpool"
        fake_adapter._warning_callback = None

        with patch("qym.core.evaluator.auto_detect_task", return_value=fake_adapter):
            evaluator_one = Evaluator(
                task=mock_task,
                dataset=ds,
                metrics=[],
                config={"run_name": "sync-advisory-one", "max_concurrency": 5, "otel_enabled": False},
            )
            evaluator_two = Evaluator(
                task=mock_task,
                dataset=ds,
                metrics=[],
                config={"run_name": "sync-advisory-two", "max_concurrency": 5, "otel_enabled": False},
            )

        advisory_registry = set()
        evaluator_one._sync_threadpool_advisory_registry = advisory_registry
        evaluator_two._sync_threadpool_advisory_registry = advisory_registry
        evaluator_one._notify_observer = MagicMock()
        evaluator_two._notify_observer = MagicMock()

        evaluator_one._maybe_emit_sync_threadpool_advisory(parallel_runs=4)
        evaluator_two._maybe_emit_sync_threadpool_advisory(parallel_runs=4)

        evaluator_one._notify_observer.assert_called_once()
        evaluator_two._notify_observer.assert_not_called()
        assert advisory_registry == {"mock_task"}

    def test_sync_threadpool_advisory_emitted_per_distinct_task(self, tmp_path, monkeypatch):
        p = tmp_path / "qa.csv"
        p.write_text("q,a\nhello,world\n", encoding="utf-8")
        ds = CsvDataset(p, input_col="q", expected_col="a")

        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

        def task_one(_input):
            return "ok"

        def task_two(_input):
            return "ok"

        fake_adapter = MagicMock()
        fake_adapter.execution_mode.return_value = "sync-threadpool"
        fake_adapter._warning_callback = None

        with patch("qym.core.evaluator.auto_detect_task", return_value=fake_adapter):
            evaluator_one = Evaluator(
                task=task_one,
                dataset=ds,
                metrics=[],
                config={"run_name": "sync-task-one", "max_concurrency": 5, "otel_enabled": False},
            )
            evaluator_two = Evaluator(
                task=task_two,
                dataset=ds,
                metrics=[],
                config={"run_name": "sync-task-two", "max_concurrency": 5, "otel_enabled": False},
            )

        advisory_registry = set()
        evaluator_one._sync_threadpool_advisory_registry = advisory_registry
        evaluator_two._sync_threadpool_advisory_registry = advisory_registry
        evaluator_one._notify_observer = MagicMock()
        evaluator_two._notify_observer = MagicMock()

        evaluator_one._maybe_emit_sync_threadpool_advisory(parallel_runs=4)
        evaluator_two._maybe_emit_sync_threadpool_advisory(parallel_runs=4)

        evaluator_one._notify_observer.assert_called_once()
        evaluator_two._notify_observer.assert_called_once()
        assert advisory_registry == {"task_one", "task_two"}

    def test_sync_threadpool_advisory_stays_in_tui_when_dashboard_observer_attached(self, tmp_path, mock_task, monkeypatch):
        p = tmp_path / "qa.csv"
        p.write_text("q,a\nhello,world\n", encoding="utf-8")
        ds = CsvDataset(p, input_col="q", expected_col="a")

        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

        fake_adapter = MagicMock()
        fake_adapter.execution_mode.return_value = "sync-threadpool"
        fake_adapter._warning_callback = None

        with patch("qym.core.evaluator.auto_detect_task", return_value=fake_adapter):
            evaluator = Evaluator(
                task=mock_task,
                dataset=ds,
                metrics=[],
                config={"run_name": "sync-advisory-tui", "max_concurrency": 5, "otel_enabled": False},
            )

        dashboard = RunDashboard([{"run_id": evaluator.run_name}], enabled=True)
        evaluator.observer = dashboard.create_observer(evaluator.run_name)

        with patch("qym.core.evaluator.logger.warning") as mock_warning:
            evaluator._maybe_emit_sync_threadpool_advisory(parallel_runs=4)

        mock_warning.assert_not_called()
        assert len(dashboard._warnings) == 1
        assert "sync-threadpool" in dashboard._warnings[0]

    def test_sync_threadpool_advisory_logs_when_no_tui_dashboard_is_attached(self, tmp_path, mock_task, monkeypatch):
        p = tmp_path / "qa.csv"
        p.write_text("q,a\nhello,world\n", encoding="utf-8")
        ds = CsvDataset(p, input_col="q", expected_col="a")

        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

        fake_adapter = MagicMock()
        fake_adapter.execution_mode.return_value = "sync-threadpool"
        fake_adapter._warning_callback = None

        with patch("qym.core.evaluator.auto_detect_task", return_value=fake_adapter):
            evaluator = Evaluator(
                task=mock_task,
                dataset=ds,
                metrics=[],
                config={"run_name": "sync-advisory-log", "max_concurrency": 5, "otel_enabled": False},
            )

        evaluator._notify_observer = MagicMock()

        with patch("qym.core.evaluator.logger.warning") as mock_warning:
            evaluator._maybe_emit_sync_threadpool_advisory(parallel_runs=4)

        mock_warning.assert_called_once()
        evaluator._notify_observer.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_cancellation_emits_stopped_to_platform(self, tmp_path, monkeypatch):
        p = tmp_path / "qa.csv"
        p.write_text("q,a\nhello,world\n", encoding="utf-8")
        ds = CsvDataset(p, input_col="q", expected_col="a")

        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

        class FakeHandle:
            run_id = "run-123"
            live_url = "http://example/live/run-123"

        class FakePlatformClient:
            def __init__(self, platform_url=None, api_key=None):
                self.platform_url = platform_url
                self.api_key = api_key

            def create_run(self, **kwargs):
                return FakeHandle()

        class FakePlatformEventStream:
            instances = []

            def __init__(self, platform_url=None, api_key=None, run_id=None):
                self.platform_url = platform_url
                self.api_key = api_key
                self.run_id = run_id
                self.events = []
                FakePlatformEventStream.instances.append(self)

            def emit(self, event_type, payload, sync=False):
                self.events.append((event_type, payload, sync))

            def close(self):
                return None

        async def slow_task(_input):
            await asyncio.sleep(5)
            return "ok"

        monkeypatch.setattr("qym.core.evaluator.PlatformClient", FakePlatformClient)
        monkeypatch.setattr("qym.core.evaluator.PlatformEventStream", FakePlatformEventStream)

        evaluator = Evaluator(
            task=slow_task,
            dataset=ds,
            metrics=[],
            config={
                "run_name": "async-cancel",
                "max_concurrency": 1,
                "otel_enabled": False,
                "platform_api_key": "test-key",
                "platform_url": "http://example",
            },
        )

        task = asyncio.create_task(evaluator.arun(show_tui=False, auto_save=False))
        await asyncio.sleep(0.05)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert FakePlatformEventStream.instances
        events = FakePlatformEventStream.instances[-1].events
        completed = [payload for event_type, payload, _sync in events if event_type == "run_completed"]
        assert completed
        assert completed[-1]["final_status"] == "STOPPED"
