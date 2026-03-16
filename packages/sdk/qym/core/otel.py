"""
Optional OpenTelemetry auto-instrumentation via OpenLLMetry (traceloop-sdk).

When traceloop-sdk is installed, this module auto-instruments installed LLM SDKs
(OpenAI, Anthropic, Cohere, etc.) so that LLM calls inside user task functions
appear as child spans under qym's per-item evaluation spans.

Additionally, tool call results are surfaced as explicit spans between LLM calls
via a lightweight monkey-patch on the OpenAI SDK.

If traceloop-sdk is not installed, a no-op fallback is used transparently.
"""
import contextlib
import contextvars
import functools
import logging
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)

_initialized = False

# Track which tool_call_ids have already been emitted as spans (per-context)
_emitted_tool_ids: contextvars.ContextVar[Set[str]] = contextvars.ContextVar(
    "_emitted_tool_ids", default=None,
)


class NullOtelManager:
    """No-op fallback when traceloop-sdk is not installed or OTEL is disabled."""

    enabled = False

    def span(self, name: str, attributes: Optional[Dict[str, Any]] = None,
             trace_id: Optional[str] = None):
        return contextlib.nullcontext()

    def get_current_trace_id(self) -> Optional[str]:
        return None

    def get_current_span_id(self) -> Optional[str]:
        return None

    def shutdown(self):
        pass


class OtelManager:
    """Manages OpenLLMetry auto-instrumentation lifecycle."""

    enabled = True

    def __init__(self, tracer):
        self._tracer = tracer

    def span(self, name: str, attributes: Optional[Dict[str, Any]] = None,
             trace_id: Optional[str] = None):
        if attributes or trace_id:
            return _SpanWithAttributes(self._tracer, name, attributes or {}, trace_id)
        return self._tracer.start_as_current_span(name)

    def get_current_trace_id(self) -> Optional[str]:
        """Get the trace ID of the currently active OTEL span."""
        try:
            from opentelemetry import trace
            current = trace.get_current_span()
            ctx = current.get_span_context()
            if ctx and ctx.trace_id:
                return format(ctx.trace_id, '032x')
        except Exception:
            pass
        return None

    def get_current_span_id(self) -> Optional[str]:
        """Get the span ID of the currently active OTEL span."""
        try:
            from opentelemetry import trace
            current = trace.get_current_span()
            ctx = current.get_span_context()
            if ctx and ctx.span_id:
                return format(ctx.span_id, '016x')
        except Exception:
            pass
        return None

    def shutdown(self):
        try:
            from opentelemetry import trace
            provider = trace.get_tracer_provider()
            if hasattr(provider, "shutdown"):
                provider.shutdown()
        except Exception as e:
            logger.debug(f"OTEL shutdown error: {e}")


class _SpanWithAttributes:
    """Context manager that creates a span and sets attributes on entry.

    If trace_id is provided (as a hex string), the span is created under that
    foreign trace — used to attach OTEL spans to a Langfuse trace.
    """

    def __init__(self, tracer, name: str, attributes: Dict[str, Any],
                 trace_id: Optional[str] = None):
        self._tracer = tracer
        self._name = name
        self._attributes = attributes
        self._trace_id = trace_id
        self._span = None
        self._token = None

    def __enter__(self):
        from opentelemetry import context, trace

        parent_ctx = None
        if self._trace_id:
            # Create a remote parent context with the given trace_id
            # so this OTEL span joins the Langfuse trace
            parent_span_ctx = trace.SpanContext(
                trace_id=int(self._trace_id.replace("-", ""), 16),
                span_id=trace.INVALID_SPAN_ID,
                is_remote=True,
                trace_flags=trace.TraceFlags(0x01),
            )
            parent_ctx = trace.set_span_in_context(
                trace.NonRecordingSpan(parent_span_ctx)
            )

        self._span = self._tracer.start_span(self._name, context=parent_ctx)
        for k, v in self._attributes.items():
            self._span.set_attribute(k, v)
        self._token = context.attach(trace.set_span_in_context(self._span))
        # Reset emitted tool IDs for this eval item
        _emitted_tool_ids.set(set())
        return self._span

    def __exit__(self, exc_type, exc_val, exc_tb):
        from opentelemetry import context
        try:
            if self._span is not None:
                self._span.end()
        finally:
            if self._token is not None:
                context.detach(self._token)
        return False


# ---------------------------------------------------------------------------
# Tool call span injection
# ---------------------------------------------------------------------------

def _emit_tool_spans(tracer, messages):
    """Create spans for tool results found in the messages array.

    Scans messages for role=tool entries, correlates them with the preceding
    assistant message's tool_calls to resolve function names, and emits a
    short OTEL span for each. Already-emitted tool_call_ids are skipped.
    """
    seen = _emitted_tool_ids.get(None)
    if seen is None:
        seen = set()
        _emitted_tool_ids.set(seen)

    # Build tool_call_id → (function_name, arguments) map from assistant messages
    id_to_info: Dict[str, Dict[str, str]] = {}
    for msg in messages:
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
        if role != "assistant":
            continue
        tool_calls = msg.get("tool_calls") if isinstance(msg, dict) else getattr(msg, "tool_calls", None)
        if not tool_calls:
            continue
        for tc in tool_calls:
            if isinstance(tc, dict):
                tc_id = tc.get("id", "")
                fn = tc.get("function", {})
                name = fn.get("name", "unknown") if isinstance(fn, dict) else getattr(fn, "name", "unknown")
                args = fn.get("arguments", "") if isinstance(fn, dict) else getattr(fn, "arguments", "")
            else:
                tc_id = getattr(tc, "id", "")
                fn = getattr(tc, "function", None)
                name = getattr(fn, "name", "unknown") if fn else "unknown"
                args = getattr(fn, "arguments", "") if fn else ""
            id_to_info[tc_id] = {"name": name, "arguments": args}

    # Emit a span for each unseen tool message
    for msg in messages:
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
        if role != "tool":
            continue
        tc_id = msg.get("tool_call_id") if isinstance(msg, dict) else getattr(msg, "tool_call_id", "")
        if tc_id in seen:
            continue
        seen.add(tc_id)

        info = id_to_info.get(tc_id, {})
        tool_name = info.get("name", "unknown")
        tool_args = info.get("arguments", "")
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")

        span = tracer.start_span(f"tool:{tool_name}")
        span.set_attribute("tool.name", tool_name)
        span.set_attribute("tool.call_id", tc_id or "")
        # Input: tool arguments; Output: tool result
        if tool_args:
            span.set_attribute("input.value", str(tool_args)[:4000])
        if content:
            span.set_attribute("output.value", str(content)[:4000])
        span.end()


def _patch_tool_spans(tracer):
    """Monkey-patch OpenAI SDK to emit tool spans between LLM calls.

    This runs after traceloop has already patched the SDK, so our wrapper
    sits on top of traceloop's instrumentation.
    """
    try:
        import openai.resources.chat.completions as mod
    except ImportError:
        return

    # Patch sync create
    original_create = mod.Completions.create

    @functools.wraps(original_create)
    def patched_create(self, *args, **kwargs):
        messages = kwargs.get("messages") or (args[0] if args else None)
        if messages:
            _emit_tool_spans(tracer, messages)
        return original_create(self, *args, **kwargs)

    mod.Completions.create = patched_create

    # Patch async create
    original_acreate = mod.AsyncCompletions.create

    @functools.wraps(original_acreate)
    async def patched_acreate(self, *args, **kwargs):
        messages = kwargs.get("messages") or (args[0] if args else None)
        if messages:
            _emit_tool_spans(tracer, messages)
        return await original_acreate(self, *args, **kwargs)

    mod.AsyncCompletions.create = patched_acreate

    logger.debug("Tool call span injection patched onto OpenAI SDK")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_otel_manager(config) -> Any:
    """
    Create an OtelManager if traceloop-sdk is installed and otel_enabled is True.
    Returns NullOtelManager otherwise.
    """
    global _initialized

    if not getattr(config, "otel_enabled", True):
        return NullOtelManager()

    try:
        from traceloop.sdk import Traceloop
        from opentelemetry import trace
    except ImportError:
        logger.debug("traceloop-sdk not installed — OTEL auto-instrumentation disabled")
        return NullOtelManager()

    if not _initialized:
        try:
            # Suppress noisy "Metrics are disabled" log from traceloop
            logging.getLogger("traceloop.sdk").setLevel(logging.WARNING)

            init_kwargs = {"app_name": "qym", "disable_batch": False}

            endpoint = getattr(config, "otel_endpoint", None)
            headers = getattr(config, "otel_headers", None)

            # Auto-derive OTEL endpoint from Langfuse credentials if not explicitly set
            if not endpoint:
                import os
                lf_host = getattr(config, "langfuse_host", None) or os.environ.get("LANGFUSE_HOST")
                lf_pk = getattr(config, "langfuse_public_key", None) or os.environ.get("LANGFUSE_PUBLIC_KEY")
                lf_sk = getattr(config, "langfuse_secret_key", None) or os.environ.get("LANGFUSE_SECRET_KEY")
                if lf_pk and lf_sk:
                    import base64
                    lf_host = (lf_host or "https://cloud.langfuse.com").rstrip("/")
                    endpoint = f"{lf_host}/api/public/otel/v1/traces"
                    token = base64.b64encode(f"{lf_pk}:{lf_sk}".encode()).decode()
                    headers = {"Authorization": f"Basic {token}"}
                    logger.debug(f"OTEL exporter auto-configured from Langfuse credentials → {endpoint}")

            if endpoint:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                exporter_kwargs = {"endpoint": endpoint}
                if headers:
                    exporter_kwargs["headers"] = headers
                init_kwargs["exporter"] = OTLPSpanExporter(**exporter_kwargs)

            # Block noisy HTTP connection spans
            try:
                from traceloop.sdk.instruments import Instruments
                init_kwargs["block_instruments"] = {Instruments.REQUESTS, Instruments.URLLIB3}
            except ImportError:
                pass

            Traceloop.init(**init_kwargs)
            _initialized = True
            logger.info("OTEL auto-instrumentation initialized via traceloop-sdk")

            # Add tool call span injection on top of traceloop's patches
            tracer = trace.get_tracer("qym")
            _patch_tool_spans(tracer)

        except Exception as e:
            logger.warning(f"Failed to initialize OTEL auto-instrumentation: {e}")
            return NullOtelManager()

    tracer = trace.get_tracer("qym")
    return OtelManager(tracer)
