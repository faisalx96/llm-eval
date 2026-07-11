import json
import ssl
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

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
        # Path objects are coerced via str(), which is platform-native
        # ("/tmp/result.json" on POSIX, "\\tmp\\result.json" on Windows).
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
        metric_specs={"quality": {"score_type": "percentage"}},
        run_metadata={},
        run_config={},
    )

    assert handle.run_id == "run-123"
    assert calls[0][3] == client_module.PlatformClient.CREATE_RUN_TIMEOUT
    assert calls[0][1]["metric_specs"]["quality"]["score_type"] == "percentage"


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


def test_platform_event_stream_batches_many_events_into_few_posts(monkeypatch):
    posts = []

    def fake_post_ndjson(url: str, ndjson: str, api_key: str, *, timeout: float = 30) -> None:
        posts.append([json.loads(line) for line in ndjson.splitlines() if line.strip()])

    monkeypatch.setattr(client_module, "_post_ndjson", fake_post_ndjson)

    stream = client_module.PlatformEventStream(
        platform_url="https://platform.example",
        api_key="secret-token",
        run_id="run-123",
    )
    try:
        for i in range(60):
            stream.emit("item_started", {"item_id": f"item-{i}", "index": i})
    finally:
        stream.close()

    events = [evt for post in posts for evt in post if evt["type"] == "item_started"]
    assert len(events) == 60
    assert stream.dropped_events == 0
    # The old 5-events-per-POST cap would need >= 12 requests here.
    assert len(posts) <= 10


def test_platform_event_stream_respects_batch_event_cap(monkeypatch):
    posts = []

    def fake_post_ndjson(url: str, ndjson: str, api_key: str, *, timeout: float = 30) -> None:
        posts.append([json.loads(line) for line in ndjson.splitlines() if line.strip()])

    monkeypatch.setattr(client_module, "_post_ndjson", fake_post_ndjson)
    monkeypatch.setattr(client_module.PlatformEventStream, "MAX_BATCH_EVENTS", 3)

    stream = client_module.PlatformEventStream(
        platform_url="https://platform.example",
        api_key="secret-token",
        run_id="run-123",
    )
    try:
        for i in range(10):
            stream.emit("item_started", {"item_id": f"item-{i}", "index": i})
    finally:
        stream.close()

    assert all(len(post) <= 3 for post in posts)
    events = [evt for post in posts for evt in post if evt["type"] == "item_started"]
    assert len(events) == 10


def test_platform_event_stream_respects_batch_byte_cap(monkeypatch):
    post_sizes = []
    event_count = 0

    def fake_post_ndjson(url: str, ndjson: str, api_key: str, *, timeout: float = 30) -> None:
        nonlocal event_count
        post_sizes.append(len(ndjson.encode("utf-8")))
        event_count += sum(1 for line in ndjson.splitlines() if line.strip())

    monkeypatch.setattr(client_module, "_post_ndjson", fake_post_ndjson)
    monkeypatch.setattr(client_module.PlatformEventStream, "MAX_BATCH_BYTES", 5_000)

    stream = client_module.PlatformEventStream(
        platform_url="https://platform.example",
        api_key="secret-token",
        run_id="run-123",
    )
    try:
        for i in range(20):
            stream.emit(
                "item_completed",
                {"item_id": f"item-{i}", "index": i, "output": "x" * 1000},
            )
    finally:
        stream.close()

    assert event_count == 20
    # The cap is checked before appending, so a batch may overshoot by at
    # most one event (~1.3KB here with the event envelope) — never two.
    assert all(size <= 5_000 + 1_500 for size in post_sizes)
    assert len(post_sizes) >= 4


def test_platform_event_stream_retries_transient_errors_without_dropping(monkeypatch):
    attempts = []
    sent_events = []

    def fake_post_ndjson(url: str, ndjson: str, api_key: str, *, timeout: float = 30) -> None:
        attempts.append(ndjson)
        if len(attempts) <= 3:
            raise URLError("connection refused")
        for line in ndjson.splitlines():
            if line.strip():
                sent_events.append(json.loads(line))

    monkeypatch.setattr(client_module, "_post_ndjson", fake_post_ndjson)
    monkeypatch.setattr(client_module.PlatformEventStream, "RETRY_BACKOFF_BASE", 0.01)
    monkeypatch.setattr(client_module.PlatformEventStream, "RETRY_BACKOFF_MAX", 0.05)

    stream = client_module.PlatformEventStream(
        platform_url="https://platform.example",
        api_key="secret-token",
        run_id="run-123",
    )
    try:
        stream.emit("item_started", {"item_id": "item-1", "index": 0})
        assert stream.flush(timeout=10)
    finally:
        stream.close()

    assert [evt["type"] for evt in sent_events] == ["item_started"]
    assert stream.dropped_events == 0
    assert len(attempts) >= 4


def test_platform_event_stream_isolates_poison_batches_per_event(monkeypatch):
    delivered = []

    def fake_post_ndjson(url: str, ndjson: str, api_key: str, *, timeout: float = 30) -> None:
        lines = [line for line in ndjson.splitlines() if line.strip()]
        if any("poison-marker" in line for line in lines):
            raise HTTPError(url, 400, "Bad Request", None, None)
        delivered.extend(json.loads(line) for line in lines)

    monkeypatch.setattr(client_module, "_post_ndjson", fake_post_ndjson)

    stream = client_module.PlatformEventStream(
        platform_url="https://platform.example",
        api_key="secret-token",
        run_id="run-123",
    )
    try:
        stream.emit("item_started", {"item_id": "item-1", "index": 0})
        stream.emit("item_started", {"item_id": "poison-marker", "index": 1})
        stream.emit("item_started", {"item_id": "item-3", "index": 2})
    finally:
        stream.close()

    delivered_ids = [evt["payload"]["item_id"] for evt in delivered]
    assert "item-1" in delivered_ids
    assert "item-3" in delivered_ids
    assert "poison-marker" not in delivered_ids
    assert stream.dropped_events == 1
    assert stream.sent_events == 2


def test_platform_event_stream_close_drains_backlog(monkeypatch):
    release = threading.Event()
    delivered = []

    def fake_post_ndjson(url: str, ndjson: str, api_key: str, *, timeout: float = 30) -> None:
        release.wait(timeout=5)
        delivered.extend(
            json.loads(line) for line in ndjson.splitlines() if line.strip()
        )

    monkeypatch.setattr(client_module, "_post_ndjson", fake_post_ndjson)

    stream = client_module.PlatformEventStream(
        platform_url="https://platform.example",
        api_key="secret-token",
        run_id="run-123",
    )
    for i in range(300):
        stream.emit("item_started", {"item_id": f"item-{i}", "index": i})
    # Everything above is stuck behind the blocked first POST until close.
    release.set()
    stream.close()

    assert len(delivered) == 300
    assert stream.dropped_events == 0


def test_platform_event_stream_gives_up_on_dead_endpoint_at_close(monkeypatch, capsys):
    def fake_post_ndjson(url: str, ndjson: str, api_key: str, *, timeout: float = 30) -> None:
        raise URLError("connection refused")

    monkeypatch.setattr(client_module, "_post_ndjson", fake_post_ndjson)
    monkeypatch.setattr(client_module.PlatformEventStream, "RETRY_BACKOFF_BASE", 0.01)
    monkeypatch.setattr(client_module.PlatformEventStream, "RETRY_BACKOFF_MAX", 0.05)
    monkeypatch.setattr(client_module.PlatformEventStream, "CLOSE_GIVEUP_FAILURES", 2)
    monkeypatch.setattr(client_module.PlatformEventStream, "CLOSE_JOIN_TIMEOUT", 10.0)

    stream = client_module.PlatformEventStream(
        platform_url="https://platform.example",
        api_key="secret-token",
        run_id="run-123",
    )
    for i in range(5):
        stream.emit("item_started", {"item_id": f"item-{i}", "index": i})

    start = time.time()
    stream.close()
    elapsed = time.time() - start

    assert elapsed < 8
    assert stream.dropped_events == 5
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "dropped" in err or "not delivered" in err


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
