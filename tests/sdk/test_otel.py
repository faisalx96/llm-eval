import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SDK_SRC = ROOT / "packages" / "sdk"
if str(SDK_SRC) not in sys.path:
    sys.path.insert(0, str(SDK_SRC))

from qym.core.otel import QymSpanProcessor


class _FakeStream:
    def __init__(self) -> None:
        self.events = []

    def emit(self, event_type, payload):
        self.events.append((event_type, payload))


class _FakeSpan:
    name = "eval-span"
    parent = None
    kind = SimpleNamespace(name="INTERNAL")
    status = SimpleNamespace(status_code=SimpleNamespace(name="OK"))
    attributes = {"openinference.span.kind": "CHAIN"}
    events = []
    links = []
    start_time = 1_000
    end_time = 2_000

    def get_span_context(self):
        return SimpleNamespace(trace_id=0xABC, span_id=0x123)


def test_qym_span_processor_emits_only_for_active_stream():
    processor_a = QymSpanProcessor()
    processor_b = QymSpanProcessor()
    stream_a = _FakeStream()
    stream_b = _FakeStream()
    span = _FakeSpan()

    processor_a.set_stream(stream_a)
    processor_b.set_stream(stream_b)

    token_a = processor_a.activate_stream()
    try:
        processor_a.on_end(span)
        processor_b.on_end(span)
    finally:
        processor_a.reset_stream(token_a)

    assert [event[0] for event in stream_a.events] == ["span_completed"]
    assert stream_b.events == []

    token_b = processor_b.activate_stream()
    try:
        processor_a.on_end(span)
        processor_b.on_end(span)
    finally:
        processor_b.reset_stream(token_b)

    assert [event[0] for event in stream_b.events] == ["span_completed"]
    assert len(stream_a.events) == 1
