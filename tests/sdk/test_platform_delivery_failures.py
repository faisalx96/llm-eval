"""A drained queue is successful only if every admitted event was delivered."""

import asyncio
import json
from urllib.error import HTTPError

import pytest
from qym import Evaluator, InMemoryDataset
from qym.platform import client as client_module
from qym.platform.client import PlatformEventStream, PlatformRunHandle


def _limits(monkeypatch, *, batch=3):
    monkeypatch.setattr(PlatformEventStream, "MAX_BATCH_EVENTS", batch)
    monkeypatch.setattr(PlatformEventStream, "FLUSH_INTERVAL", 60)
    monkeypatch.setattr(PlatformEventStream, "HEARTBEAT_INTERVAL", 60)
    monkeypatch.setattr(PlatformEventStream, "CLOSE_GIVEUP_FAILURES", 2)
    monkeypatch.setattr(PlatformEventStream, "CLOSE_JOIN_TIMEOUT", 3)
    monkeypatch.setattr(PlatformEventStream, "RETRY_BACKOFF_BASE", 0.001)
    monkeypatch.setattr(PlatformEventStream, "RETRY_BACKOFF_MAX", 0.001)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 422])
async def test_queued_permanent_failure_does_not_report_successful_flush(
    monkeypatch, status
):
    _limits(monkeypatch)
    batches, delivered = [], []

    def post(url, payload, key, **kwargs):
        events = [json.loads(line) for line in payload.splitlines()]
        batches.append(events)
        if any(row["payload"].get("reject") for row in events):
            raise HTTPError(url, status, "permanent rejection", None, None)
        delivered.extend(events)

    monkeypatch.setattr(client_module, "_post_ndjson", post)
    stream = PlatformEventStream("http://unused.invalid", "test-only", "run-test")
    for i in range(3):
        await stream.aemit("item_completed", {"index": i, "reject": i == 1})
    await asyncio.wait_for(stream.aclose(), 4)
    assert len(batches[0]) == 3
    assert [row["payload"]["index"] for row in delivered] == [0, 2]
    assert stream.sent_events == 2
    assert stream.dropped_events == 1
    assert stream._q.unfinished_tasks == 0
    assert stream.flush(0) is False
    assert await stream.aflush(0) is False
    assert not stream._thread.is_alive()


@pytest.mark.asyncio
async def test_shutdown_giveup_marks_drained_queue_unsuccessful(monkeypatch):
    _limits(monkeypatch, batch=2)
    attempts = []

    def post(url, payload, key, **kwargs):
        attempts.append(payload)
        raise OSError("endpoint unavailable")

    monkeypatch.setattr(client_module, "_post_ndjson", post)
    stream = PlatformEventStream("http://unused.invalid", "test-only", "run-test")
    await stream.aemit("item_started", {"index": 0})
    await stream.aemit("item_completed", {"index": 0})
    await asyncio.wait_for(stream.aclose(), 4)
    assert len(attempts) >= 2
    assert stream.sent_events == 0
    assert stream.dropped_events == 2
    assert stream._q.unfinished_tasks == 0
    assert stream.flush(0) is False
    assert await stream.aflush(0) is False
    assert not stream._thread.is_alive()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["permanent", "shutdown"])
async def test_evaluator_withholds_terminal_when_item_upload_is_lost(
    monkeypatch, tmp_path, failure
):
    _limits(monkeypatch, batch=100)
    delivered, attempted = [], []

    def post(url, payload, key, **kwargs):
        events = [json.loads(line) for line in payload.splitlines()]
        attempted.extend(row["type"] for row in events)
        if failure == "shutdown":
            raise OSError("endpoint unavailable")
        if any(row["type"] == "item_completed" for row in events):
            raise HTTPError(url, 422, "item rejected", None, None)
        delivered.extend(events)

    monkeypatch.setattr(client_module, "_post_ndjson", post)
    monkeypatch.setattr(
        client_module.PlatformClient,
        "create_run",
        lambda self, **kwargs: PlatformRunHandle(
            kwargs["external_run_id"], "http://unused.invalid/run"
        ),
    )

    async def task(value):
        return value

    evaluator = Evaluator(
        task,
        InMemoryDataset([{"input": "answer", "expected_output": "answer"}]),
        ["exact_match"],
        config={
            "run_name": "delivery-failure",
            "otel_enabled": False,
            "checkpoint_enabled": False,
            "platform_api_key": "test-only",
            "platform_url": "http://unused.invalid",
            "output_dir": str(tmp_path),
        },
    )
    result = await asyncio.wait_for(evaluator.arun(show_tui=False, auto_save=False), 5)
    assert result.total_items == 1
    assert evaluator._platform_stream.dropped_events > 0
    assert evaluator._platform_stream._q.unfinished_tasks == 0
    assert evaluator._run_completed is False
    assert "run_completed" not in attempted
    assert not any(row["type"] == "run_completed" for row in delivered)
