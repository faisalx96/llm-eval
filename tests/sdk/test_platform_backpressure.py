"""Adversarial coverage for bounded uploads and asynchronous finalization."""

import asyncio
import json
import os
import threading
import time
from queue import Full

import pytest

from qym.core.dataset import InMemoryDataset
from qym.core.evaluator import Evaluator
from qym.platform import client as client_module
from qym.platform._backlog import EventBacklog
from qym.platform.client import PlatformEventStream, PlatformRunHandle


def test_backlog_spills_fifo_unicode_with_strict_caps_and_private_file():
    queue = EventBacklog(180, 2000)
    events = [{"i": i, "text": "قيّم " * 8} for i in range(10)]
    for event in events:
        queue.put(event)
    assert queue.spilled_events > 0
    assert queue.peak_memory_bytes <= 180
    assert queue.peak_disk_bytes <= 2000
    path = queue.spool_path
    assert os.stat(path).st_mode & 0o077 == 0
    assert not queue.wait_drained(0)
    queue.dispose()
    assert os.path.exists(path), "pending evidence must not be deleted"
    for event in events:
        assert queue.get_nowait() == event
        queue.task_done()
    assert queue.wait_drained(0)
    queue.dispose()
    assert not os.path.exists(path)


def test_disk_cap_backpressures_until_spool_drains_without_loss():
    queue = EventBacklog(1, 100)
    first = {"text": "a" * 40}
    second = {"text": "b" * 40}
    queue.put(first)
    done = threading.Event()
    worker = threading.Thread(target=lambda: (queue.put(second), done.set()))
    worker.start()
    assert not done.wait(0.03)
    assert queue.disk_bytes <= 100
    assert queue.get() == first
    queue.task_done()
    assert done.wait(1)
    assert queue.get() == second
    queue.task_done()
    worker.join(1)
    queue.dispose()


def test_nonblocking_enqueue_does_no_disk_io(monkeypatch):
    queue = EventBacklog(1, 1024)
    monkeypatch.setattr(
        "qym.platform._backlog.tempfile.NamedTemporaryFile",
        lambda **kw: pytest.fail("disk I/O on fast path"),
    )
    with pytest.raises(Full):
        queue.put({"message": "spill"}, block=False)
    assert queue.unfinished_tasks == 0
    with pytest.raises(Full):
        queue.put({"message": "spill"}, block=False, timeout=0)


def test_oversized_event_rejected_before_spool_or_counter_mutation():
    queue = EventBacklog(16, 32)
    with pytest.raises(ValueError, match="exceeds"):
        queue.put({"message": "x" * 100})
    assert queue.unfinished_tasks == queue.memory_bytes == queue.disk_bytes == 0
    assert queue.spool_path is None


def configure_stream(monkeypatch, post, *, memory=1024, disk=4096):
    monkeypatch.setattr(client_module, "_post_ndjson", post)
    monkeypatch.setattr(PlatformEventStream, "MAX_PENDING_MEMORY_BYTES", memory)
    monkeypatch.setattr(PlatformEventStream, "MAX_PENDING_DISK_BYTES", disk)
    monkeypatch.setattr(PlatformEventStream, "MAX_BATCH_EVENTS", 2)
    monkeypatch.setattr(PlatformEventStream, "FLUSH_INTERVAL", 0.005)
    return PlatformEventStream("http://unused.invalid", "test-only", "run-test")


@pytest.mark.asyncio
async def test_async_spill_and_backpressure_keep_loop_alive_and_preserve_events(
    monkeypatch,
):
    sent = []

    def post(url, ndjson, key, **kwargs):
        time.sleep(0.015)
        sent.extend(json.loads(line) for line in ndjson.splitlines())

    stream = configure_stream(monkeypatch, post, memory=1024, disk=2048)
    ticks = []
    running = True

    async def heartbeat():
        while running:
            ticks.append(time.monotonic())
            await asyncio.sleep(0.005)

    hb = asyncio.create_task(heartbeat())
    try:
        for i in range(50):
            await stream.aemit("item_completed", {"i": i, "output": "x" * 250})
        await stream.aclose()
    finally:
        running = False
        await hb
    assert [e["payload"]["i"] for e in sent] == list(range(50))
    assert stream.sent_events == 50
    assert stream.dropped_events == 0
    assert stream._q.peak_memory_bytes <= 1024
    assert stream._q.peak_disk_bytes <= 2048
    assert stream._q.spilled_events > 0
    assert stream._q.spool_path is None
    assert max(b - a for a, b in zip(ticks, ticks[1:])) < 0.1


@pytest.mark.asyncio
async def test_cancelling_aclose_waits_for_drain_and_removes_spool(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    sent = []

    def post(url, ndjson, key, **kwargs):
        entered.set()
        release.wait(2)
        sent.extend(json.loads(line) for line in ndjson.splitlines())

    stream = configure_stream(monkeypatch, post, memory=1, disk=4096)
    await stream.aemit("item_completed", {"i": 1})
    assert await asyncio.to_thread(entered.wait, 1)
    closer = asyncio.create_task(stream.aclose())
    await asyncio.sleep(0.01)
    closer.cancel()
    await asyncio.sleep(0.02)
    assert not closer.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await closer
    assert len(sent) == 1
    assert not stream._thread.is_alive()
    assert stream._q.spool_path is None


@pytest.mark.asyncio
async def test_cancelling_backpressured_producer_does_not_strand_close(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    sent = []

    def post(url, ndjson, key, **kwargs):
        entered.set()
        release.wait(2)
        sent.extend(json.loads(line) for line in ndjson.splitlines())

    stream = configure_stream(monkeypatch, post, memory=1, disk=800)
    await stream.aemit("item_completed", {"i": 0, "text": "x" * 200})
    assert await asyncio.to_thread(entered.wait, 1)
    await stream.aemit("item_completed", {"i": 1, "text": "x" * 200})
    producer = asyncio.create_task(
        stream.aemit("item_completed", {"i": 2, "text": "x" * 200})
    )
    await asyncio.sleep(0.02)
    producer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await producer
    release.set()
    await asyncio.wait_for(stream.aclose(), 2)
    # The cancelled append may already have been accepted by its worker, but
    # every accepted event must receive exactly one verdict and appear once.
    ids = [e["payload"]["i"] for e in sent]
    assert ids[:2] == [0, 1]
    assert len(ids) == len(set(ids))
    assert stream._active_emitters == stream._q.unfinished_tasks == 0


@pytest.mark.asyncio
async def test_late_async_emit_after_close_offloads_network(monkeypatch):
    def post(*args, **kwargs):
        time.sleep(0.12)

    stream = configure_stream(monkeypatch, post)
    await stream.aclose()
    task = asyncio.create_task(stream.aemit("late", {}))
    await asyncio.sleep(0.02)
    assert not task.done()
    await task
    assert stream.sent_events == 1


def evaluator(monkeypatch, task, *, concurrency=2):
    monkeypatch.setattr(
        client_module.PlatformClient,
        "create_run",
        lambda self, **kw: PlatformRunHandle(
            kw["external_run_id"], "http://unused.invalid/run"
        ),
    )
    return Evaluator(
        task,
        InMemoryDataset([{"input": "hello", "expected": "hello"}]),
        ["exact_match"],
        config={
            "run_name": task.__name__,
            "otel_enabled": False,
            "checkpoint_enabled": False,
            "platform_api_key": "test-only",
            "platform_url": "http://unused.invalid",
            "max_concurrency": concurrency,
        },
    )


@pytest.mark.asyncio
async def test_evaluator_terminal_order_and_sibling_progress_during_shutdown(
    monkeypatch,
):
    import qym.core.evaluator as evaluator_module

    events = []
    release_upload = threading.Event()
    upload_timed_out = threading.Event()
    closing = asyncio.Event()
    original_close = evaluator_module._close_platform_stream

    async def observe_close(stream):
        closing.set()
        return await original_close(stream)

    monkeypatch.setattr(evaluator_module, "_close_platform_stream", observe_close)

    def post(url, ndjson, key, **kwargs):
        if not release_upload.wait(5):
            upload_timed_out.set()
        events.extend(json.loads(line) for line in ndjson.splitlines())

    monkeypatch.setattr(client_module, "_post_ndjson", post)
    sibling_finished = asyncio.Event()

    async def quick(input):
        await asyncio.sleep(0.01)
        return input

    async def sibling(input):
        await closing.wait()
        sibling_finished.set()
        return input

    first = evaluator(monkeypatch, quick)
    second = evaluator(monkeypatch, sibling)
    tasks = [asyncio.create_task(ev.arun(show_tui=False)) for ev in (first, second)]
    try:
        await asyncio.wait_for(sibling_finished.wait(), 10)
        # The sibling must run while shutdown still awaits the held upload.
        # This checks ordering without a machine-speed-dependent timing bound.
        assert not upload_timed_out.is_set()
        assert not tasks[0].done()
    finally:
        release_upload.set()
    await asyncio.gather(*tasks)
    for run in (first._platform_stream.run_id, second._platform_stream.run_id):
        own = [event for event in events if event["run_id"] == run]
        assert own[-1]["type"] == "run_completed"
        assert own[-1]["payload"]["final_status"] == "COMPLETED"
        kinds = [event["type"] for event in own]
        assert (
            kinds.index("item_attempt_finished")
            < kinds.index("item_completed")
            < kinds.index("run_completed")
        )
        assert len({event["event_id"] for event in own}) == len(own)


@pytest.mark.asyncio
async def test_drain_timeout_never_publishes_completion_ahead_of_items(monkeypatch):
    release = threading.Event()
    events = []

    def post(url, ndjson, key, **kwargs):
        release.wait(2)
        events.extend(json.loads(line) for line in ndjson.splitlines())

    monkeypatch.setattr(client_module, "_post_ndjson", post)
    monkeypatch.setattr(PlatformEventStream, "CLOSE_JOIN_TIMEOUT", 0.03)

    async def quick(input):
        return input

    ev = evaluator(monkeypatch, quick)
    try:
        await asyncio.wait_for(ev.arun(show_tui=False), 1)
        assert not ev._run_completed
        assert not any(e["type"] == "run_completed" for e in events)
    finally:
        release.set()
        await asyncio.to_thread(ev._platform_stream._thread.join, 2)
    assert not any(e["type"] == "run_completed" for e in events)


def test_partial_spool_write_failure_keeps_previous_records_readable():
    queue = EventBacklog(1, 1024)
    queue.put({"accepted": True})
    original = queue._file

    class BrokenWriter:
        def __getattr__(self, name):
            return getattr(original, name)

        def write(self, data):
            original.write(data[:5])
            original.flush()
            raise OSError("disk full")

    queue._file = BrokenWriter()
    with pytest.raises(OSError):
        queue.put({"rejected": True})
    assert queue.unfinished_tasks == queue.qsize() == 1
    assert queue.get() == {"accepted": True}
    queue.task_done()
    queue.dispose()


@pytest.mark.asyncio
async def test_disk_write_error_is_visible_and_never_reports_successful_flush(
    monkeypatch, capsys
):
    stream = configure_stream(monkeypatch, lambda *a, **kw: None, memory=1)
    monkeypatch.setattr(
        "qym.platform._backlog.tempfile.NamedTemporaryFile",
        lambda **kw: (_ for _ in ()).throw(OSError("disk full")),
    )
    try:
        with pytest.raises(OSError):
            await stream.aemit("item_completed", {"i": 1})
        assert not await stream.aflush(0)
        assert "ERROR" in capsys.readouterr().err
        assert stream._delivery_error is not None
        assert (
            stream.dropped_events == 0
        ), "rejection is reported separately from accepted-event drops"
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_nonblocking_fast_path_does_not_wait_for_disk_lock(monkeypatch):
    stream = configure_stream(monkeypatch, lambda *a, **kw: None)
    locked, release = threading.Event(), threading.Event()

    def hold_lock():
        with stream._q._cv:
            locked.set()
            release.wait(1)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert await asyncio.to_thread(locked.wait, 1)
    emit = asyncio.create_task(stream.aemit("item_completed", {}))
    start = time.monotonic()
    await asyncio.sleep(0.02)
    assert time.monotonic() - start < 0.1
    assert not emit.done()
    release.set()
    await emit
    holder.join(1)
    await stream.aclose()


def test_direct_delivery_accounting_includes_success_and_exhausted_failure(
    monkeypatch, capsys
):
    stream = configure_stream(monkeypatch, lambda *a, **kw: None)
    stream.close()
    stream.emit("late_success", {}, sync=True)
    assert stream.sent_events == 1
    monkeypatch.setattr(PlatformEventStream, "SYNC_SEND_RETRIES", 1)

    def fail(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(client_module, "_post_ndjson", fail)
    stream.emit("late_failure", {}, sync=True)
    assert stream.dropped_events == 1
    assert "failed to upload" in capsys.readouterr().err
