"""Regression tests for Tier 1 + T2.1 hardening fixes.

These tests cover the exact failure modes that corrupted run
``d8882026-2adb-4a20-afcd-5115047dcc02`` item 408:
  * T1.1 — judge calls hung for 30+ minutes on slow-streaming providers
  * T1.2 — one hung metric blocked ``asyncio.gather`` in ``_compute_metrics``
  * T1.3 — ``_item_finished`` race produced phantom item_failed events
  * T1.4 — platform stream dropped buffered metric_scored events on shutdown
  * T2.1 — a fresh ``AsyncOpenAI`` client was created per item (no pool reuse)

Each test is small, self-contained, and uses in-process mocks only.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# T1.1 — judge wall-clock timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t11_judge_timeout_cancels_hung_create_call():
    """A judge call against a provider that hangs forever must be cancelled
    by ``asyncio.wait_for`` within ``cfg.timeout`` on each attempt, retried
    with exponential backoff, and raise ``asyncio.TimeoutError`` after all
    attempts are exhausted. Regression for T1.1."""
    # Need a real(ish) openai module so _call_with_retry's imports work.
    # Build a tiny shim that exposes the classes the retry code checks against.
    class _FakeOpenAIShim:
        class RateLimitError(Exception):
            pass

        class APIConnectionError(Exception):
            pass

        class APITimeoutError(Exception):
            pass

        class APIStatusError(Exception):
            pass

        class AsyncOpenAI:  # never actually instantiated in this test
            pass

    shim = MagicMock()
    shim.__path__ = []
    shim.RateLimitError = _FakeOpenAIShim.RateLimitError
    shim.APIConnectionError = _FakeOpenAIShim.APIConnectionError
    shim.APITimeoutError = _FakeOpenAIShim.APITimeoutError
    shim.APIStatusError = _FakeOpenAIShim.APIStatusError
    shim.AsyncOpenAI = _FakeOpenAIShim.AsyncOpenAI
    sys.modules.setdefault("openai", shim)

    from qym.metrics.judges.base import _call_with_retry

    class FakeResp:
        choices = []

    class HangingClient:
        class chat:
            class completions:
                @staticmethod
                async def create(**kw):
                    # Simulate a trickle-streaming provider that never actually
                    # returns. Real httpx would only fire a per-read timeout if
                    # chunks stopped arriving — with asyncio.wait_for we don't
                    # care what the transport is doing.
                    await asyncio.sleep(60)
                    return FakeResp()

    t0 = time.monotonic()
    with pytest.raises(asyncio.TimeoutError):
        await _call_with_retry(
            HangingClient(),
            model="test",
            messages=[],
            temperature=0,
            max_tokens=16,
            max_attempts=3,
            timeout=0.3,
        )
    elapsed = time.monotonic() - t0

    # 3 attempts × 0.3s timeout + 2 backoffs (1s, 2s + jitter) ≈ 3.9 – 6s
    assert elapsed < 15.0, f"_call_with_retry took {elapsed:.1f}s (expected <15s)"
    # Must have actually waited at least until 3 × timeout — if it returned
    # too early the wait_for wasn't firing.
    assert elapsed >= 0.9, f"_call_with_retry returned in {elapsed:.3f}s (too fast)"


@pytest.mark.asyncio
async def test_t11_judge_fast_path_returns_without_timeout_wrapper():
    """When the create() call resolves quickly, `_call_with_retry` should
    return the response without waiting for the timeout budget. Makes sure
    the wait_for wrapper doesn't introduce an artificial floor on latency."""
    # Reuse the shim installed above
    sys.modules.setdefault("openai", MagicMock())
    from qym.metrics.judges.base import _call_with_retry

    class FakeResp:
        choices = [MagicMock()]

    class FastClient:
        class chat:
            class completions:
                @staticmethod
                async def create(**kw):
                    return FakeResp()

    t0 = time.monotonic()
    result = await _call_with_retry(
        FastClient(),
        model="test",
        messages=[],
        temperature=0,
        max_tokens=16,
        timeout=5.0,
    )
    elapsed = time.monotonic() - t0

    assert result.choices
    assert elapsed < 0.5, f"fast path took {elapsed:.3f}s (expected <0.5s)"


# ---------------------------------------------------------------------------
# T1.2 — per-metric timeout in _run_single_metric
# ---------------------------------------------------------------------------


def _make_single_item_csv() -> str:
    fd, path = tempfile.mkstemp(suffix=".csv", prefix="hardening_t1_")
    with os.fdopen(fd, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "input", "expected"])
        w.writerow(["item_regression", '{"question": "what is 6 times 7?"}', '"42"'])
    return path


@pytest.mark.asyncio
async def test_t12_hung_metric_times_out_retries_and_errors(tmp_path):
    """Mix a hung metric and a fast metric on a single item and assert that
    (a) the whole eval finishes within the retry budget,
    (b) the hung metric retries metric_max_retries times, then lands in the
        ordinary metric-error path: score=0 with an error text,
    (c) the fast metric returns its real score.
    Regression for T1.2 — without the fix, the eval would hang indefinitely."""
    from qym import Evaluator
    from qym.core.dataset import CsvDataset

    async def fast_metric(output, expected, input_data):
        return {"score": 0.75}

    async def hung_metric(output, expected, input_data):
        await asyncio.sleep(600)
        return {"score": 1.0}

    async def dummy_task(question: str):
        # bare dicts are no longer valid task outputs (envelope required)
        return "42"

    csv_path = _make_single_item_csv()
    try:
        dataset = CsvDataset(csv_path, input_col="input", expected_col="expected", id_col="id")
        ev = Evaluator(
            task=dummy_task,
            metrics=[fast_metric, hung_metric],
            dataset=dataset,
            config={
                "max_concurrency": 1,
                "max_metric_concurrency": 2,
                "metric_timeout": 1.5,
                "metric_max_retries": 1,
                "live_mode": "local",
                "otel_enabled": False,
                # short name + tmp dir: the derived checkpoint path would
                # otherwise exceed Windows' 260-char limit
                "task_name": "t12_task",
                "output_dir": str(tmp_path / "results"),
            },
        )

        t0 = time.monotonic()
        result = await ev.arun(auto_save=False, show_tui=False)
        elapsed = time.monotonic() - t0

        assert elapsed < 10.0, f"arun took {elapsed:.1f}s with metric_timeout=1.5s"

        # `.results` is a dict keyed by item id on EvaluationResult
        items_map = getattr(result, "results", {})
        assert items_map, "no per-item results returned"
        first = next(iter(items_map.values()))
        scores = first.get("scores") if isinstance(first, dict) else getattr(first, "scores", {})
        assert scores, "no scores recorded"

        assert "fast_metric" in scores
        assert "hung_metric" in scores
        fast = scores["fast_metric"]
        hung = scores["hung_metric"]

        fast_score = fast.get("score") if isinstance(fast, dict) else getattr(fast, "score", None)
        hung_score = hung.get("score") if isinstance(hung, dict) else getattr(hung, "score", None)
        hung_error = hung.get("error") if isinstance(hung, dict) else getattr(hung, "error", None)

        assert fast_score == 0.75
        assert hung_score == 0.0
        assert hung_error and "metric timeout" in str(hung_error), (
            f"expected an ordinary metric error mentioning the timeout, got {hung_error!r}"
        )
    finally:
        os.unlink(csv_path)


# ---------------------------------------------------------------------------
# T1.3 — shielded finalizer / _item_finished ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t13_cancel_mid_finalize_does_not_emit_item_failed(tmp_path):
    """Cancel the eval while the finalizer is running and verify:
      * ``_emit_item_completed`` still fires (shielded)
      * the finally block does NOT emit ``item_failed``
      * ``CancelledError`` still propagates to the caller
    Regression for T1.3 — without the fix, cancellation would clobber the
    item's output with ``error="Cancelled"`` while the score rows remained."""
    from qym import Evaluator
    from qym.core.dataset import CsvDataset

    async def slow_metric(output, expected, input_data):
        await asyncio.sleep(0.2)
        return {"score": 1.0}

    async def dummy_task(question: str):
        # bare dicts are no longer valid task outputs (envelope required)
        return "42"

    csv_path = _make_single_item_csv()
    try:
        dataset = CsvDataset(csv_path, input_col="input", expected_col="expected", id_col="id")
        ev = Evaluator(
            task=dummy_task,
            metrics=[slow_metric],
            dataset=dataset,
            config={
                "max_concurrency": 1,
                "metric_timeout": 10.0,
                "live_mode": "local",
                "otel_enabled": False,
                # short name + tmp dir: the derived checkpoint path would
                # otherwise exceed Windows' 260-char limit
                "task_name": "t13_task",
                "output_dir": str(tmp_path / "results"),
            },
        )

        # Patch finalize to block briefly so we can cancel mid-finalize.
        # arun() resets _platform_stream to None on startup (evaluator.py:932),
        # so we can't spy on the stream directly — we patch _emit_item_completed
        # and track whether the finally-block's fail_item path runs by spying
        # on tracker.fail_item.
        finalize_entered = {"value": False}
        emit_completed_called = {"value": False}
        fail_item_called = {"value": False}
        original_finalize = ev._finalize_item
        original_emit_completed = ev._emit_item_completed

        async def spy_finalize(*args, **kwargs):
            finalize_entered["value"] = True
            await asyncio.sleep(0.25)  # window for the cancel to land
            return await original_finalize(*args, **kwargs)

        def spy_emit_completed(*args, **kwargs):
            emit_completed_called["value"] = True
            return original_emit_completed(*args, **kwargs)

        ev._finalize_item = spy_finalize
        ev._emit_item_completed = spy_emit_completed

        # Intercept the tracker's fail_item call (only invoked from the
        # _item_finished == False path in the finally block)
        import qym.core.progress as progress_mod
        original_fail_item = progress_mod.ProgressTracker.fail_item

        def spy_fail_item(self, *args, **kwargs):
            if args and "Cancelled" in str(args[1] if len(args) > 1 else kwargs.get("error_msg", "")):
                fail_item_called["value"] = True
            return original_fail_item(self, *args, **kwargs)

        progress_mod.ProgressTracker.fail_item = spy_fail_item  # type: ignore[method-assign]

        try:
            # Run arun as a task so we can cancel it when finalize is mid-flight
            arun_task = asyncio.create_task(ev.arun(auto_save=False, show_tui=False))
            # Wait until the finalizer is reached
            for _ in range(100):
                if finalize_entered["value"]:
                    break
                await asyncio.sleep(0.02)
            assert finalize_entered["value"], "finalizer was never entered"
            await asyncio.sleep(0.05)  # partway through the 0.25s sleep

            arun_task.cancel()
            with pytest.raises((asyncio.CancelledError, BaseException)):
                await arun_task

            # Give the shielded finalizer a tick to complete
            await asyncio.sleep(0.5)

            assert emit_completed_called["value"], (
                "_emit_item_completed should fire under asyncio.shield "
                "even when the outer coroutine is cancelled"
            )
            assert not fail_item_called["value"], (
                "fail_item should NOT fire when the work was already done "
                "(_item_finished=True was set before the emits). "
                "This was the exact item 408 failure mode."
            )
        finally:
            progress_mod.ProgressTracker.fail_item = original_fail_item  # type: ignore[method-assign]
    finally:
        os.unlink(csv_path)


# ---------------------------------------------------------------------------
# T1.4 — PlatformEventStream.flush()
# ---------------------------------------------------------------------------


class _CaptureHandler(BaseHTTPRequestHandler):
    events_lock = threading.Lock()
    events: List[Dict[str, Any]] = []

    def log_message(self, format, *args):  # noqa: A002 — silence default logs
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        with _CaptureHandler.events_lock:
            for line in body.strip().split("\n"):
                if line.strip():
                    _CaptureHandler.events.append(json.loads(line))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')


def _start_capture_server() -> tuple[HTTPServer, int]:
    # Reset captured events per test
    with _CaptureHandler.events_lock:
        _CaptureHandler.events.clear()
    server = HTTPServer(("127.0.0.1", 0), _CaptureHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, server.server_address[1]


def test_t14_flush_drains_buffered_events_before_returning():
    """After emit(..) is called N times, flush() must block until every event
    has been POSTed (or dropped) before returning. Regression for T1.4 — the
    item 408 bug where fast metric emits were lost on shutdown."""
    from qym.platform.client import PlatformEventStream

    server, port = _start_capture_server()
    try:
        stream = PlatformEventStream(
            platform_url=f"http://127.0.0.1:{port}",
            api_key="test-key",
            run_id="test-run",
        )

        # Emit 20 metric_scored events as a realistic mid-run burst
        for i in range(20):
            stream.emit("metric_scored", {"item_id": f"item_{i}", "score": i / 20.0})

        t0 = time.monotonic()
        ok = stream.flush(timeout=5.0)
        elapsed = time.monotonic() - t0

        # Give the server thread a beat to finalize the last dispatch
        time.sleep(0.1)

        with _CaptureHandler.events_lock:
            metric_events = [
                e for e in _CaptureHandler.events
                if e["type"] == "metric_scored"
            ]

        assert ok, f"flush() returned False after {elapsed*1000:.0f}ms"
        assert len(metric_events) == 20, (
            f"expected 20 metric_scored events durable after flush(), "
            f"got {len(metric_events)}"
        )
        assert elapsed < 3.0, f"flush() took {elapsed:.2f}s (expected <3s)"

        stream.close()
    finally:
        server.shutdown()


def test_t14_close_flushes_late_events_cleanly():
    """close() must call flush() before joining so late-emitted events make
    it to the platform before the stream is torn down."""
    from qym.platform.client import PlatformEventStream

    server, port = _start_capture_server()
    try:
        stream = PlatformEventStream(
            platform_url=f"http://127.0.0.1:{port}",
            api_key="test-key",
            run_id="test-run",
        )

        for i in range(5):
            stream.emit("metric_scored", {"item_id": f"late_{i}", "score": 1.0})
        stream.close()

        # Server thread has a beat to finalize dispatches after close() returns
        time.sleep(0.1)
        with _CaptureHandler.events_lock:
            late = [
                e for e in _CaptureHandler.events
                if e["type"] == "metric_scored" and "late_" in str(e.get("payload", {}).get("item_id", ""))
            ]

        assert len(late) == 5, f"expected 5 late events drained by close(), got {len(late)}"
    finally:
        server.shutdown()


# ---------------------------------------------------------------------------
# T2.1 — shared AsyncOpenAI client in sql_eval/task_v2_async.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t21_shared_client_reused_across_task_invocations():
    """With set_shared_client() set, sql_agent_task_async must reuse the same
    AsyncOpenAI instance across every invocation and never close it (the
    runner owns the lifetime). Without set_shared_client(), each invocation
    constructs its own client and closes it. Regression for T2.1."""
    # sql_eval lives in a sibling directory; add it to path
    sql_eval_path = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "sql_eval",
    ))
    if not os.path.isdir(sql_eval_path):
        pytest.skip(f"sql_eval not found at {sql_eval_path}")
    sys.path.insert(0, sql_eval_path)

    os.environ.setdefault("OPENROUTER_API_KEY", "test-key")

    # aiosqlite is imported at the top of task_v2_async but is not a
    # dependency of this test — stub it out if missing so the shared-client
    # logic can be exercised in any environment.
    if "aiosqlite" not in sys.modules:
        try:
            import aiosqlite  # noqa: F401
        except ImportError:
            sys.modules["aiosqlite"] = MagicMock()

    try:
        import task_v2_async  # type: ignore
    except Exception as e:
        pytest.skip(f"task_v2_async import failed: {e}")

    # Patch at task_v2_async's own bound reference to AsyncOpenAI so we don't
    # depend on the real `openai` package having a class-level `close` method.
    # The test_judges.py module in this directory installs a MagicMock for
    # `openai` at import time, which makes `openai.AsyncOpenAI` unreliable.
    construct_count = {"value": 0}
    close_count = {"value": 0}
    original_AsyncOpenAI = task_v2_async.AsyncOpenAI  # type: ignore[attr-defined]

    class CountingFakeClient:
        def __init__(self, *args, **kwargs):
            construct_count["value"] += 1

        async def close(self):
            close_count["value"] += 1

        # Any attribute access returns a MagicMock (for chat.completions etc.)
        def __getattr__(self, name):
            return MagicMock()

    # Stub _instrumented_respond so no real network traffic happens
    original_respond = task_v2_async._instrumented_respond

    async def fake_respond(client, *args, **kwargs):
        return "SELECT 1", {"steps": 1, "total_tokens": 10, "cost_usd": 0.0, "provider": None}

    try:
        task_v2_async.AsyncOpenAI = CountingFakeClient  # type: ignore[attr-defined]
        task_v2_async._instrumented_respond = fake_respond

        # --- Scenario A: no shared client ---
        construct_count["value"] = 0
        close_count["value"] = 0
        task_v2_async.set_shared_client(None)
        for i in range(3):
            await task_v2_async.sql_agent_task_async(
                question=f"q{i}",
                db_id="california_schools",
                evidence="",
                model_name="openai/gpt-4o-mini",
            )
        assert construct_count["value"] == 3, (
            f"without shared client, each task should construct its own: "
            f"got {construct_count['value']} constructions"
        )
        assert close_count["value"] == 3, (
            f"without shared client, each task should close its own: "
            f"got {close_count['value']} closes"
        )

        # --- Scenario B: shared client ---
        construct_count["value"] = 0
        close_count["value"] = 0
        shared = CountingFakeClient()
        task_v2_async.set_shared_client(shared)
        assert construct_count["value"] == 1  # the `shared` we just built

        for i in range(5):
            await task_v2_async.sql_agent_task_async(
                question=f"q{i}",
                db_id="california_schools",
                evidence="",
                model_name="openai/gpt-4o-mini",
            )

        assert construct_count["value"] == 1, (
            f"with shared client, only the `shared` instance should be constructed: "
            f"got {construct_count['value']}"
        )
        assert close_count["value"] == 0, (
            f"with shared client, task must not close it: "
            f"got {close_count['value']} closes"
        )

        task_v2_async.set_shared_client(None)
        await shared.close()
        assert close_count["value"] == 1, (
            "explicit shared.close() should fire exactly once"
        )
    finally:
        task_v2_async.AsyncOpenAI = original_AsyncOpenAI  # type: ignore[attr-defined]
        task_v2_async._instrumented_respond = original_respond
        task_v2_async.set_shared_client(None)
