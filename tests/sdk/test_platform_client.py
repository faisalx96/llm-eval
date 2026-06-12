import json
import ssl
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib import request as urlrequest

from qym.platform import client as client_module
from qym.platform import tls as tls_module


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
        # Path objects are sanitized via str(); the separator is OS-specific.
        "path": str(Path("/tmp/result.json")),
        "nan_value": None,
    }

    metric_payload = events[1]["payload"]
    assert metric_payload["score_raw"] == {
        "score": 0.5,
        "metadata": {"infinite_value": None},
    }
    assert metric_payload["meta"] == {"raw_payload": {"label": "meta"}}


def test_platform_client_create_run_uses_bounded_timeout(monkeypatch):
    calls = []

    def fake_post_json(
        url: str, payload: dict, api_key: str, *, timeout: float = 30
    ) -> dict:
        calls.append((url, payload, api_key, timeout))
        return {
            "run_id": "run-123",
            "live_url": "https://platform.example/runs/run-123",
        }

    monkeypatch.setattr(client_module, "_post_json", fake_post_json)

    client = client_module.PlatformClient(
        platform_url="https://platform.example",
        api_key="secret-token",
    )
    handle = client.create_run(
        external_run_id="external-1",
        task="task",
        dataset="dataset",
        model=None,
        metrics=[],
        run_metadata={},
        run_config={},
    )

    assert handle.run_id == "run-123"
    assert calls[0][3] == client_module.PlatformClient.CREATE_RUN_TIMEOUT


def test_platform_tls_uses_custom_ca_bundle(monkeypatch):
    contexts = []

    def fake_create_default_context(*, cafile=None):
        contexts.append(cafile)
        return "custom-context"

    monkeypatch.setenv("QYM_PLATFORM_CA_BUNDLE", "/etc/qym/internal-ca.pem")
    monkeypatch.delenv("QYM_CA_BUNDLE", raising=False)
    monkeypatch.setattr(ssl, "create_default_context", fake_create_default_context)

    assert tls_module.ssl_context() == "custom-context"
    assert contexts == ["/etc/qym/internal-ca.pem"]


def test_platform_tls_can_disable_verification_for_local_dev(monkeypatch):
    context = object()

    monkeypatch.setenv("QYM_PLATFORM_SSL_VERIFY", "false")
    monkeypatch.setattr(ssl, "_create_unverified_context", lambda: context)

    assert tls_module.ssl_context() is context


def test_platform_tls_urlopen_applies_context(monkeypatch):
    opened = []
    req = urlrequest.Request("https://platform.example/healthz")
    sentinel_response = object()

    monkeypatch.setenv("QYM_PLATFORM_SSL_VERIFY", "false")

    def fake_urlopen(request, *, timeout, context=None):
        opened.append((request, timeout, context))
        return sentinel_response

    monkeypatch.setattr(urlrequest, "urlopen", fake_urlopen)

    result = tls_module.urlopen(req, timeout=3)

    assert result is sentinel_response
    assert opened[0][0] is req
    assert opened[0][1] == 3
    assert isinstance(opened[0][2], ssl.SSLContext)


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


def test_platform_event_stream_emits_heartbeat_while_idle(monkeypatch):
    sent_events = []

    def fake_post_ndjson(url: str, ndjson: str, api_key: str, *, timeout: float = 30) -> None:
        for line in ndjson.splitlines():
            line = line.strip()
            if line:
                sent_events.append(json.loads(line))

    monkeypatch.setattr(client_module, "_post_ndjson", fake_post_ndjson)
    monkeypatch.setattr(client_module.PlatformEventStream, "HEARTBEAT_INTERVAL", 0.05)

    stream = client_module.PlatformEventStream(
        platform_url="https://platform.example",
        api_key="secret-token",
        run_id="run-123",
    )
    try:
        deadline = time.time() + 1.0
        while time.time() < deadline and not any(evt["type"] == "run_heartbeat" for evt in sent_events):
            time.sleep(0.01)
    finally:
        stream.close()

    assert any(evt["type"] == "run_heartbeat" for evt in sent_events)
