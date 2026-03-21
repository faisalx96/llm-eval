"""
Optional OpenTelemetry auto-instrumentation via OpenLLMetry (traceloop-sdk).

When traceloop-sdk is installed, this module auto-instruments installed LLM SDKs
(OpenAI, Anthropic, Cohere, etc.) so that LLM calls inside user task functions
appear as child spans under qym's per-item evaluation spans.

In the Langfuse v3 architecture, Langfuse's LangfuseSpanProcessor is added to the
same TracerProvider that traceloop creates, so all spans (both auto-instrumented
and manually created via Langfuse SDK) flow through a single provider.

A QymSpanProcessor captures completed spans for local DB storage via the platform
event stream.

If traceloop-sdk is not installed, a no-op fallback is used transparently.
"""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_initialized = False


class NullOtelManager:
    """No-op fallback when traceloop-sdk is not installed or OTEL is disabled."""

    enabled = False
    qym_processor = None

    def shutdown(self):
        pass


def _make_qym_span_processor_class():
    """Create QymSpanProcessor, inheriting from the SDK base class if available."""
    try:
        from opentelemetry.sdk.trace import SpanProcessor as _Base
    except ImportError:
        _Base = object

    class QymSpanProcessor(_Base):
        """Captures completed OTEL spans and streams them to the qym platform for DB storage.

        Inherits from the SDK's SpanProcessor so all required methods
        (_on_ending, on_start, on_end, etc.) are provided.
        """

        def __init__(self):
            self._stream = None

        def set_stream(self, stream):
            """Set the PlatformEventStream to emit span data to."""
            self._stream = stream

        def on_start(self, span, parent_context=None):
            pass

        # Noise spans to skip (HTTPX connection, DNS, TLS handshake)
        _NOISE_SPAN_NAMES = frozenset({"connect", "dns.resolve", "tls.handshake"})

        def on_end(self, span):
            if not self._stream:
                return
            if span.name in self._NOISE_SPAN_NAMES:
                return
            try:
                ctx = span.get_span_context()
                self._stream.emit("span_completed", {
                    "trace_id": format(ctx.trace_id, '032x'),
                    "span_id": format(ctx.span_id, '016x'),
                    "parent_span_id": format(span.parent.span_id, '016x') if span.parent else None,
                    "name": span.name,
                    "kind": span.kind.name if span.kind else "INTERNAL",
                    "start_time_ns": span.start_time,
                    "end_time_ns": span.end_time,
                    "duration_ms": (span.end_time - span.start_time) / 1e6 if span.end_time and span.start_time else None,
                    "status": span.status.status_code.name if span.status else "UNSET",
                    "attributes": dict(span.attributes) if span.attributes else {},
                    "events": [
                        {
                            "name": e.name,
                            "timestamp_ns": e.timestamp,
                            "attributes": dict(e.attributes) if e.attributes else {},
                        }
                        for e in (span.events or [])
                    ],
                })
            except Exception:
                pass  # Non-blocking, best-effort

        def shutdown(self):
            pass

        def force_flush(self, timeout_millis=30000):
            return True

    return QymSpanProcessor

QymSpanProcessor = _make_qym_span_processor_class()


class OtelManager:
    """Manages OpenLLMetry auto-instrumentation lifecycle."""

    enabled = True

    def __init__(self, tracer, qym_processor: Optional[QymSpanProcessor] = None):
        self._tracer = tracer
        self.qym_processor = qym_processor

    def shutdown(self):
        try:
            from opentelemetry import trace
            provider = trace.get_tracer_provider()
            if hasattr(provider, "shutdown"):
                provider.shutdown()
        except Exception as e:
            logger.debug(f"OTEL shutdown error: {e}")


# ---------------------------------------------------------------------------
# Reasoning field capture
# ---------------------------------------------------------------------------

def _patch_reasoning_capture():
    """Patch OpenAI SDK to capture the 'reasoning' field from model responses.

    Reasoning models (Qwen 3.x, OpenAI o1/o3, etc.) return chain-of-thought
    in a non-standard 'reasoning' extra field. traceloop doesn't capture it.

    Strategy: wrap on top of traceloop's wrapper. After traceloop's span ends,
    the response is stored in a contextvar. Then we immediately re-open the
    span's attributes via the provider's internal span reference — but that's
    fragile. Instead, we take the simpler approach: our wrapper runs outside
    traceloop's, gets the result, and creates a tiny sibling span with the
    reasoning content.

    Actually simplest: use wrapt's callback mechanism. traceloop uses wrapt
    BoundFunctionWrapper. We can register a post-call hook via wrapt.
    """
    try:
        import functools
        import openai.resources.chat.completions as mod
        from opentelemetry import trace as otel_trace
    except ImportError:
        return

    def _add_reasoning_span(response, parent_tracer):
        """Create a brief span capturing reasoning content from the response."""
        try:
            for choice in response.choices:
                msg = choice.message
                reasoning = getattr(msg, "reasoning", None)
                if not reasoning:
                    continue
                # Create a child span under the current context (the parent task span)
                span = parent_tracer.start_span(f"reasoning (step {choice.index})")
                span.set_attribute("gen_ai.reasoning", str(reasoning)[:16000])
                # If content was None, also note that
                content = getattr(msg, "content", None)
                if content:
                    span.set_attribute("gen_ai.content", str(content)[:4000])
                span.end()
        except Exception:
            pass

    tracer = otel_trace.get_tracer("qym.reasoning")

    # Wrap sync create (on top of traceloop's wrapper)
    _original_create = mod.Completions.create

    @functools.wraps(_original_create)
    def _patched_create(self, *args, **kwargs):
        result = _original_create(self, *args, **kwargs)
        _add_reasoning_span(result, tracer)
        return result

    mod.Completions.create = _patched_create

    # Wrap async create
    _original_acreate = mod.AsyncCompletions.create

    @functools.wraps(_original_acreate)
    async def _patched_acreate(self, *args, **kwargs):
        result = await _original_acreate(self, *args, **kwargs)
        _add_reasoning_span(result, tracer)
        return result

    mod.AsyncCompletions.create = _patched_acreate
    logger.debug("Reasoning field capture patched onto OpenAI SDK")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_otel_manager(config) -> Any:
    """
    Create an OtelManager if traceloop-sdk is installed and otel_enabled is True.
    Returns NullOtelManager otherwise.

    Does NOT configure an OTEL exporter — Langfuse SDK v3 adds its own
    LangfuseSpanProcessor to the TracerProvider when initialized with
    tracer_provider=<this provider>. This avoids dual-export.
    """
    global _initialized

    if not getattr(config, "otel_enabled", True):
        return NullOtelManager()

    try:
        from traceloop.sdk import Traceloop
        from opentelemetry import trace
    except Exception:
        logger.debug("traceloop-sdk not available — OTEL auto-instrumentation disabled")
        return NullOtelManager()

    qym_processor = QymSpanProcessor()

    if not _initialized:
        try:
            # Suppress noisy "Metrics are disabled" log from traceloop
            logging.getLogger("traceloop.sdk").setLevel(logging.WARNING)

            # Create a real SDK TracerProvider BEFORE Traceloop.init().
            # Without this, traceloop (which requires an API key or exporter)
            # falls back to a NoOp ProxyTracerProvider that creates
            # non-recording spans.  By setting a real provider first,
            # traceloop's instrumentors attach to it and produce real spans.
            # Langfuse later adds its LangfuseSpanProcessor to the same
            # provider, so all spans (auto-instrumented + manual) reach
            # Langfuse without a separate OTLP exporter.
            from opentelemetry.sdk.trace import TracerProvider as SdkTracerProvider

            existing = trace.get_tracer_provider()
            if not isinstance(existing, SdkTracerProvider):
                provider = SdkTracerProvider()
                trace.set_tracer_provider(provider)

            # Provide a no-op exporter so traceloop fully initializes
            # (without an API key or exporter, it skips instrumentor registration).
            # The actual export to Langfuse is handled by LangfuseSpanProcessor
            # which is added to the same provider later.
            from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

            class _NoOpExporter(SpanExporter):
                def export(self, spans):
                    return SpanExportResult.SUCCESS
                def shutdown(self):
                    pass

            init_kwargs = {
                "app_name": "qym",
                "disable_batch": False,
                "exporter": _NoOpExporter(),
            }

            # Block noisy HTTP connection spans
            try:
                from traceloop.sdk.instruments import Instruments
                init_kwargs["block_instruments"] = {Instruments.REQUESTS, Instruments.URLLIB3}
            except ImportError:
                pass

            # Suppress traceloop's stderr output (it may still print warnings).
            import sys, io
            _stderr = sys.stderr
            sys.stderr = io.StringIO()
            try:
                Traceloop.init(**init_kwargs)
            finally:
                sys.stderr = _stderr
            _initialized = True
            logger.info("OTEL auto-instrumentation initialized via traceloop-sdk")

            # Patch OpenAI SDK to capture 'reasoning' field from model responses.
            # traceloop only captures standard fields (content, role, tool_calls).
            # Reasoning models (Qwen, o1, etc.) return thinking in a non-standard
            # 'reasoning' extra field that traceloop ignores.
            _patch_reasoning_capture()

        except Exception as e:
            logger.warning(f"Failed to initialize OTEL auto-instrumentation: {e}")
            return NullOtelManager()

    # Register QymSpanProcessor on the same provider
    provider = trace.get_tracer_provider()
    if hasattr(provider, 'add_span_processor'):
        provider.add_span_processor(qym_processor)

    tracer = trace.get_tracer("qym")
    return OtelManager(tracer, qym_processor)
