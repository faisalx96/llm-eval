import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from qym.platform import client as client_module


@dataclass
class ExamplePayload:
    label: str


def test_platform_event_stream_sanitizes_non_json_payloads(monkeypatch):
    sent_chunks = []

    def fake_post_ndjson(url: str, ndjson: str, api_key: str, *, timeout: float = 30) -> None:
        sent_chunks.append((url, ndjson, api_key))

    monkeypatch.setattr(client_module, "_post_ndjson", fake_post_ndjson)

    stream = client_module.PlatformEventStream(
        platform_url="https://platform.example",
        api_key="secret-token",
        run_id="run-123",
    )
    try:
        stream.emit(
            "item_completed",
            {
                "item_id": "item-1",
                "index": 0,
                "output": {
                    "payload": ExamplePayload(label="ok"),
                    "path": Path("/tmp/result.json"),
                    "nan_value": float("nan"),
                },
                "latency_ms": 12.3,
                "trace_id": "trace-1",
            },
        )
        stream.emit(
            "metric_scored",
            {
                "item_id": "item-1",
                "metric_name": "judge",
                "score_numeric": 0.5,
                "score_raw": {
                    "score": 0.5,
                    "metadata": {"infinite_value": float("inf")},
                },
                "meta": {"raw_payload": ExamplePayload(label="meta")},
            },
        )
    finally:
        stream.close()

    events = []
    for _, ndjson, _ in sent_chunks:
        for line in ndjson.splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))

    assert [evt["type"] for evt in events] == ["item_completed", "metric_scored"]

    completed_payload = events[0]["payload"]
    assert completed_payload["output"] == {
        "payload": {"label": "ok"},
        "path": "/tmp/result.json",
        "nan_value": None,
    }

    metric_payload = events[1]["payload"]
    assert metric_payload["score_raw"] == {
        "score": 0.5,
        "metadata": {"infinite_value": None},
    }
    assert metric_payload["meta"] == {"raw_payload": {"label": "meta"}}


def test_platform_event_stream_sends_late_events_during_shutdown(monkeypatch):
    sent_events = []
    first_post_started = threading.Event()
    allow_first_post = threading.Event()

    def fake_post_ndjson(url: str, ndjson: str, api_key: str, *, timeout: float = 30) -> None:
        events = [json.loads(line) for line in ndjson.splitlines() if line.strip()]
        sent_events.extend(events)
        if any(evt["type"] == "item_started" for evt in events):
            first_post_started.set()
            allow_first_post.wait(timeout=5)

    monkeypatch.setattr(client_module, "_post_ndjson", fake_post_ndjson)

    stream = client_module.PlatformEventStream(
        platform_url="https://platform.example",
        api_key="secret-token",
        run_id="run-123",
    )
    stream.emit("item_started", {"item_id": "item-1", "index": 0})

    closer = threading.Thread(target=stream.close)
    closer.start()
    assert first_post_started.wait(timeout=5)

    stream.emit(
        "item_completed",
        {
            "item_id": "item-1",
            "index": 0,
            "output": {"answer": "ok"},
            "latency_ms": 1.0,
            "trace_id": "trace-1",
        },
    )

    allow_first_post.set()
    closer.join(timeout=5)
    assert not closer.is_alive()

    # Give the direct-send path a brief moment to finish if it is using
    # the shutdown fallback instead of the background queue.
    deadline = time.time() + 1.0
    while time.time() < deadline and len(sent_events) < 2:
        time.sleep(0.01)

    assert [evt["type"] for evt in sent_events] == ["item_started", "item_completed"]


def test_platform_event_stream_close_is_bounded_when_flush_is_stuck(monkeypatch):
    entered_post = threading.Event()
    release_post = threading.Event()

    def fake_post_ndjson(url: str, ndjson: str, api_key: str, *, timeout: float = 30) -> None:
        entered_post.set()
        release_post.wait(timeout=1)

    monkeypatch.setattr(client_module, "_post_ndjson", fake_post_ndjson)
    monkeypatch.setattr(client_module.PlatformEventStream, "CLOSE_JOIN_TIMEOUT", 0.05)

    stream = client_module.PlatformEventStream(
        platform_url="https://platform.example",
        api_key="secret-token",
        run_id="run-123",
    )
    try:
        assert stream._thread.daemon is True
        stream.emit("item_started", {"item_id": "item-1", "index": 0})
        assert entered_post.wait(timeout=1)

        start = time.time()
        stream.close()
        elapsed = time.time() - start

        assert elapsed < 0.5
    finally:
        release_post.set()
