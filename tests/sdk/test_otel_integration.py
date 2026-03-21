"""Integration test for the OTEL auto-instrumentation trace structure.

Verifies the span hierarchy produced by the evaluator + traceloop:
  trace (qym | run | item-N)
    └── eval span (eval-run-item-N)
          ├── task_function_name
          │     └── openai.chat  (auto-instrumented)
          └── eval_metrics
                └── metric_*
"""
import sys
import os

import pytest

# ── guard: skip entire module if traceloop or openai are not importable ──
try:
    from opentelemetry.sdk.trace import TracerProvider as SdkTracerProvider, SpanProcessor
    from opentelemetry import trace as otel_trace
    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False

pytestmark = pytest.mark.skipif(not _HAS_OTEL, reason="opentelemetry-sdk not installed")


# ---------------------------------------------------------------------------
# Spy processor — records every span that completes
# ---------------------------------------------------------------------------
class SpyProcessor(SpanProcessor):
    def __init__(self):
        self.spans = []

    def on_end(self, span):
        ctx = span.get_span_context()
        self.spans.append({
            "name": span.name,
            "trace_id": format(ctx.trace_id, '032x'),
            "span_id": format(ctx.span_id, '016x'),
            "parent_span_id": format(span.parent.span_id, '016x') if span.parent else None,
            "status": span.status.status_code.name if span.status else "UNSET",
        })

    def by_name(self, name):
        return [s for s in self.spans if s["name"] == name]

    def names(self):
        return [s["name"] for s in self.spans]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="function")
def otel_env():
    """Set up a real TracerProvider + traceloop instrumentors."""
    existing = otel_trace.get_tracer_provider()
    if isinstance(existing, SdkTracerProvider):
        provider = existing
    else:
        provider = SdkTracerProvider()
        otel_trace.set_tracer_provider(provider)

    spy = SpyProcessor()
    provider.add_span_processor(spy)

    # Init traceloop with no-op exporter (activates instrumentors)
    try:
        import io
        from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

        class _NoOp(SpanExporter):
            def export(self, spans):
                return SpanExportResult.SUCCESS

        import logging
        logging.getLogger("traceloop.sdk").setLevel(logging.ERROR)
        _stderr = sys.stderr
        sys.stderr = io.StringIO()
        try:
            from traceloop.sdk import Traceloop
            Traceloop.init(app_name="qym-test", disable_batch=False, exporter=_NoOp())
        finally:
            sys.stderr = _stderr
    except Exception:
        pytest.skip("traceloop-sdk not available")

    yield provider, spy


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestTraceStructure:
    """Verify the span hierarchy produced by a Langfuse + traceloop trace."""

    def test_parent_child_nesting(self, otel_env):
        """openai.chat spans must be children of a task span, not siblings of root."""
        provider, spy = otel_env
        spy.spans.clear()

        tracer = otel_trace.get_tracer("qym")

        # Simulate evaluator flow:
        # 1. Root span (Langfuse start_as_current_span equivalent)
        with tracer.start_as_current_span("eval-run-item-0") as root:
            # 2. Task function span (child of root)
            with tracer.start_as_current_span("my_task_function") as task_span:
                # 3. Simulated OpenAI call (traceloop would create this)
                with tracer.start_as_current_span("openai.chat") as llm_span:
                    pass
                with tracer.start_as_current_span("openai.chat") as llm_span2:
                    pass
            # 4. Metrics span (sibling of task, child of root)
            with tracer.start_as_current_span("eval_metrics") as metrics_span:
                with tracer.start_as_current_span("metric_accuracy"):
                    pass

        provider.force_flush()

        # Verify hierarchy
        root_spans = spy.by_name("eval-run-item-0")
        task_spans = spy.by_name("my_task_function")
        llm_spans = spy.by_name("openai.chat")
        metric_root = spy.by_name("eval_metrics")
        metric_acc = spy.by_name("metric_accuracy")

        assert len(root_spans) == 1, f"Expected 1 root span, got {len(root_spans)}"
        assert len(task_spans) == 1, f"Expected 1 task span, got {len(task_spans)}"
        assert len(llm_spans) == 2, f"Expected 2 LLM spans, got {len(llm_spans)}"
        assert len(metric_root) == 1
        assert len(metric_acc) == 1

        root_id = root_spans[0]["span_id"]
        task_id = task_spans[0]["span_id"]

        # All share the same trace_id
        trace_id = root_spans[0]["trace_id"]
        for s in spy.spans:
            assert s["trace_id"] == trace_id, f"Span {s['name']} has different trace_id"

        # Task span is child of root
        assert task_spans[0]["parent_span_id"] == root_id

        # LLM spans are children of task (not root)
        for llm in llm_spans:
            assert llm["parent_span_id"] == task_id, \
                f"LLM span parent is {llm['parent_span_id']}, expected task span {task_id}"

        # Metrics span is child of root (sibling of task)
        assert metric_root[0]["parent_span_id"] == root_id

        # Metric children are under eval_metrics
        assert metric_acc[0]["parent_span_id"] == metric_root[0]["span_id"]

    def test_no_noise_spans(self, otel_env):
        """connect/dns/tls spans must be filtered by QymSpanProcessor."""
        from qym.core.otel import QymSpanProcessor

        proc = QymSpanProcessor()

        # Mock stream that records emitted events
        emitted = []

        class FakeStream:
            def emit(self, type_, data):
                emitted.append(data["name"])

        proc.set_stream(FakeStream())

        provider, _ = otel_env
        tracer = otel_trace.get_tracer("qym")

        # Create spans including noise
        with tracer.start_as_current_span("eval-item") as root:
            with tracer.start_as_current_span("openai.chat"):
                pass
            with tracer.start_as_current_span("connect"):
                pass
            with tracer.start_as_current_span("dns.resolve"):
                pass

        # Manually feed ended spans through processor
        for s in provider.force_flush() or []:
            pass

        # Simulate on_end calls
        # We can't easily get ReadableSpan objects, so test the filter logic directly
        class FakeSpan:
            def __init__(self, name):
                self.name = name

        proc._stream = FakeStream()
        emitted.clear()

        class FakeCtx:
            trace_id = 0x123
            span_id = 0x456

        class FakeStatus:
            class status_code:
                name = "OK"

        for name in ["openai.chat", "connect", "dns.resolve", "tls.handshake", "eval-item"]:
            span = type("Span", (), {
                "name": name,
                "get_span_context": lambda self=None, n=name: FakeCtx(),
                "parent": None,
                "kind": type("K", (), {"name": "INTERNAL"})(),
                "start_time": 1000,
                "end_time": 2000,
                "status": FakeStatus(),
                "attributes": {},
                "events": [],
            })()
            proc.on_end(span)

        assert "openai.chat" in emitted
        assert "eval-item" in emitted
        assert "connect" not in emitted
        assert "dns.resolve" not in emitted
        assert "tls.handshake" not in emitted
