"""
Optional OpenTelemetry auto-instrumentation for LLM calls.

Uses OpenInference instrumentors (the same library Phoenix uses) so traces
render properly in both Phoenix and Langfuse. Langfuse explicitly maps
OpenInference attributes (input.value, output.value, llm.*, etc.) to its
own data model.

Architecture:
  - One shared TracerProvider
  - OpenInference instrumentors register on it
  - LangfuseSpanProcessor exports to Langfuse (added later by _init_langfuse)
  - Optional OTLP exporter for Phoenix dual export
  - QymSpanProcessor captures spans for local DB storage

Enrichments (applied before instrumentors patch the SDK):
  - Tool call spans: reconstructed from message history (role=tool messages)
  - Reasoning capture: non-standard 'reasoning' field added to span attributes
"""
import contextvars
import functools
import json as _json
import logging
import time
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_initialized = False

# Track emitted tool_call_ids per trace context to avoid duplicates
_emitted_tool_ids: contextvars.ContextVar[Set[str]] = contextvars.ContextVar(
    "_emitted_tool_ids", default=None,
)

# Timestamp (ns) recorded after the last LLM call returned.
# Used as the approximate start time for tool execution spans.
_last_llm_end_ns: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "_last_llm_end_ns", default=None,
)


class NullOtelManager:
    """No-op fallback when OTEL is disabled or no instrumentors are available."""

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
        """Captures completed OTEL spans and streams them to the qym platform."""

        def __init__(self):
            self._stream = None

        def set_stream(self, stream):
            self._stream = stream

        def on_start(self, span, parent_context=None):
            pass

        _NOISE_SPAN_NAMES = frozenset({"connect", "dns.resolve", "tls.handshake"})

        def on_end(self, span):
            if not self._stream:
                return
            if span.name in self._NOISE_SPAN_NAMES:
                return
            try:
                ctx = span.get_span_context()
                # Extract span links (used by retry/coupled span detection)
                links = []
                for lnk in (getattr(span, 'links', None) or []):
                    lctx = lnk.context
                    if lctx and lctx.is_valid:
                        links.append({
                            "trace_id": format(lctx.trace_id, '032x'),
                            "span_id": format(lctx.span_id, '016x'),
                            "attributes": dict(lnk.attributes) if lnk.attributes else {},
                        })

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
                    "links": links,
                })
            except Exception:
                pass

        def shutdown(self):
            pass

        def force_flush(self, timeout_millis=30000):
            return True

    return QymSpanProcessor

QymSpanProcessor = _make_qym_span_processor_class()


class OtelManager:
    """Manages auto-instrumentation lifecycle."""

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
# OpenAI enrichments (tool spans + reasoning capture)
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

    # Build tool_call_id -> {name, arguments} map from assistant messages
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

    # Collect unseen tool messages
    new_tools = []
    for msg in messages:
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
        if role != "tool":
            continue
        tc_id = msg.get("tool_call_id") if isinstance(msg, dict) else getattr(msg, "tool_call_id", "")
        if tc_id in seen:
            continue
        seen.add(tc_id)
        new_tools.append((tc_id, msg))

    if not new_tools:
        return

    # Approximate timing: tool execution happened between the last LLM
    # response and now (the start of the next LLM call).
    now_ns = time.time_ns()
    range_start_ns = _last_llm_end_ns.get(None) or now_ns
    # Divide the time window evenly among tool calls
    count = len(new_tools)
    slot_ns = max((now_ns - range_start_ns) // count, 1) if count else 1

    for i, (tc_id, msg) in enumerate(new_tools):
        info = id_to_info.get(tc_id, {})
        tool_name = info.get("name", "unknown")
        tool_args = info.get("arguments", "")
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")

        tool_start = range_start_ns + i * slot_ns
        tool_end = range_start_ns + (i + 1) * slot_ns

        span = tracer.start_span(f"tool:{tool_name}", start_time=tool_start)
        span.set_attribute("openinference.span.kind", "TOOL")
        span.set_attribute("tool.name", tool_name)
        if tool_args:
            span.set_attribute("input.value", str(tool_args)[:4000])
        if content:
            span.set_attribute("output.value", str(content)[:4000])

        # Detect error results in tool output and flag the span.
        # Common patterns: {"error": ...} JSON or plain error strings.
        _tool_has_error = False
        if content:
            content_str = str(content).strip()
            if content_str.startswith("{"):
                try:
                    parsed = _json.loads(content_str)
                    if isinstance(parsed, dict) and parsed.get("error"):
                        _tool_has_error = True
                        err_type = str(parsed.get("error", "ToolError"))
                        err_msg = str(parsed.get("message", ""))
                        span.add_event("exception", attributes={
                            "exception.type": err_type,
                            "exception.message": err_msg,
                        })
                except (ValueError, TypeError):
                    pass
        if _tool_has_error:
            try:
                from opentelemetry.trace import StatusCode
                span.set_status(StatusCode.ERROR, err_msg or err_type)
            except Exception:
                pass

        span.end(end_time=tool_end)


def _enrich_with_reasoning(result):
    """Add reasoning field to current span if present in response."""
    try:
        from opentelemetry import trace as otel_trace
        span = otel_trace.get_current_span()
        if not span or not span.is_recording():
            return
        for choice in result.choices:
            msg = choice.message
            reasoning = getattr(msg, "reasoning", None)
            if reasoning:
                span.set_attribute(
                    f"gen_ai.completion.{choice.index}.reasoning",
                    str(reasoning)[:16000],
                )
    except Exception:
        pass


def _patch_openai_enrichments():
    """Wrap OpenAI SDK methods BEFORE instrumentors patch them.

    The instrumentor's wrapper calls our wrapper (which is the 'wrapped'
    function from its perspective) inside its span context. This means:
    - Tool span emission runs inside the instrumentor's span -> correct parenting
    - Reasoning capture runs inside the instrumentor's span -> can set attributes

    Single wrapper handles both enrichments.
    """
    try:
        import openai.resources.chat.completions as mod
        from opentelemetry import trace as otel_trace
    except ImportError:
        return

    tracer = otel_trace.get_tracer("qym.enrichments")

    # Sync
    _real_create = mod.Completions.create

    @functools.wraps(_real_create)
    def _enriched_create(self, *args, **kwargs):
        messages = kwargs.get("messages") or (args[0] if args else None)
        if messages:
            _emit_tool_spans(tracer, messages)
        result = _real_create(self, *args, **kwargs)
        _last_llm_end_ns.set(time.time_ns())
        _enrich_with_reasoning(result)
        return result

    mod.Completions.create = _enriched_create

    # Async
    _real_acreate = mod.AsyncCompletions.create

    @functools.wraps(_real_acreate)
    async def _enriched_acreate(self, *args, **kwargs):
        messages = kwargs.get("messages") or (args[0] if args else None)
        if messages:
            _emit_tool_spans(tracer, messages)
        result = await _real_acreate(self, *args, **kwargs)
        _last_llm_end_ns.set(time.time_ns())
        _enrich_with_reasoning(result)
        return result

    mod.AsyncCompletions.create = _enriched_acreate
    logger.debug("OpenAI enrichments (tool spans + reasoning) installed")


# ---------------------------------------------------------------------------
# Instrumentor registration
# ---------------------------------------------------------------------------

# OpenInference instrumentors (same library Phoenix uses).
_KNOWN_INSTRUMENTORS: List[Tuple[str, str]] = [
    ("openinference.instrumentation.openai", "OpenAIInstrumentor"),
    ("openinference.instrumentation.anthropic", "AnthropicInstrumentor"),
    ("openinference.instrumentation.bedrock", "BedrockInstrumentor"),
    ("openinference.instrumentation.google_generativeai", "GoogleGenerativeAIInstrumentor"),
    ("openinference.instrumentation.mistralai", "MistralAIInstrumentor"),
    ("openinference.instrumentation.groq", "GroqInstrumentor"),
    ("openinference.instrumentation.cohere", "CohereInstrumentor"),
    ("openinference.instrumentation.litellm", "LiteLLMInstrumentor"),
    ("openinference.instrumentation.langchain", "LangChainInstrumentor"),
    ("openinference.instrumentation.llama_index", "LlamaIndexInstrumentor"),
    ("openinference.instrumentation.crewai", "CrewAIInstrumentor"),
    ("openinference.instrumentation.haystack", "HaystackInstrumentor"),
    ("openinference.instrumentation.dspy", "DSPyInstrumentor"),
]


def _register_instrumentors(provider):
    """Register all available OpenInference instrumentors on the given TracerProvider."""
    # Suppress noisy DependencyConflict errors from instrumentors
    # whose provider SDKs aren't installed.
    _instrumentor_logger = logging.getLogger("opentelemetry.instrumentation.instrumentor")
    _prev_level = _instrumentor_logger.level
    _instrumentor_logger.setLevel(logging.CRITICAL)

    registered = []
    for module_path, class_name in _KNOWN_INSTRUMENTORS:
        try:
            mod = __import__(module_path, fromlist=[class_name])
            instrumentor_cls = getattr(mod, class_name)
            instrumentor = instrumentor_cls()
            if not getattr(instrumentor, '_is_instrumented_by_opentelemetry', False):
                instrumentor.instrument(tracer_provider=provider)
                registered.append(class_name)
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"Failed to register {class_name}: {e}")

    _instrumentor_logger.setLevel(_prev_level)

    if registered:
        logger.info(f"Auto-instrumentation registered: {', '.join(registered)}")
    return registered


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_otel_manager(config) -> Any:
    """Create an OtelManager with OpenInference auto-instrumentation.

    Sets up a real TracerProvider, registers available instrumentors,
    and optionally adds a Phoenix OTLP exporter for dual tracing.

    Langfuse adds its own LangfuseSpanProcessor to the same provider
    later (in _init_langfuse), so all spans reach both destinations.
    """
    global _initialized

    if not getattr(config, "otel_enabled", True):
        return NullOtelManager()

    try:
        from opentelemetry.sdk.trace import TracerProvider as SdkTracerProvider
        from opentelemetry import trace
    except ImportError:
        logger.debug("opentelemetry-sdk not installed — auto-instrumentation disabled")
        return NullOtelManager()

    qym_processor = QymSpanProcessor()

    if not _initialized:
        try:
            # Create a real TracerProvider
            existing = trace.get_tracer_provider()
            if not isinstance(existing, SdkTracerProvider):
                provider = SdkTracerProvider()
                trace.set_tracer_provider(provider)
            else:
                provider = existing

            # Wrap OpenAI methods BEFORE instrumentors patch them
            # so enrichments (tool spans, reasoning) run inside the
            # instrumentor's span context.
            _patch_openai_enrichments()

            # Register all available OpenInference instrumentors
            registered = _register_instrumentors(provider)
            if not registered:
                logger.debug("No OpenInference instrumentors found — auto-instrumentation inactive")

            # Optional: Phoenix OTLP export for dual tracing
            import os
            phoenix_enabled = getattr(config, "phoenix_enabled", False) or os.environ.get("PHOENIX_ENABLED", "").lower() == "true"
            phoenix_endpoint = getattr(config, "phoenix_endpoint", None) or os.environ.get("PHOENIX_ENDPOINT")
            if phoenix_enabled and phoenix_endpoint:
                try:
                    from opentelemetry.sdk.trace.export import BatchSpanProcessor
                    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

                    phoenix_exporter = OTLPSpanExporter(endpoint=phoenix_endpoint)
                    provider.add_span_processor(BatchSpanProcessor(phoenix_exporter))
                    logger.info(f"Phoenix trace export enabled -> {phoenix_endpoint}")
                except ImportError:
                    logger.warning("opentelemetry-exporter-otlp not installed — Phoenix export disabled")

            _initialized = True
            logger.info("OTEL auto-instrumentation initialized")

        except Exception as e:
            logger.warning(f"Failed to initialize OTEL auto-instrumentation: {e}")
            return NullOtelManager()

    # Register QymSpanProcessor on the provider
    provider = trace.get_tracer_provider()
    if hasattr(provider, 'add_span_processor'):
        provider.add_span_processor(qym_processor)

    tracer = trace.get_tracer("qym")
    return OtelManager(tracer, qym_processor)
