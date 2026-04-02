import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from qym.core.evaluator import Evaluator
from qym.core.dataset import CsvDataset

class TestEvaluator:
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
