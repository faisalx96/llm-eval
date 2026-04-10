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
import importlib
import inspect
import json as _json
import logging
import os
import pkgutil
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from ..utils.env import load_cwd_dotenv

logger = logging.getLogger(__name__)

_initialized = False
_registered_instrumentors: List[str] = []
_phoenix_enabled: bool = False
_phoenix_endpoint: Optional[str] = None

# Track emitted tool_call_ids per trace context to avoid duplicates
_emitted_tool_ids: contextvars.ContextVar[Set[str]] = contextvars.ContextVar(
    "_emitted_tool_ids", default=None,
)

# Timestamp (ns) recorded after the last LLM call returned.
# Used as the approximate start time for tool execution spans.
_last_llm_end_ns: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "_last_llm_end_ns", default=None,
)

_active_qym_stream: contextvars.ContextVar[Optional[Any]] = contextvars.ContextVar(
    "_active_qym_stream", default=None,
)

_forced_llm_model: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "_forced_llm_model", default=None,
)


class NullOtelManager:
    """No-op fallback when OTEL is disabled or no instrumentors are available."""

    enabled = False
    qym_processor = None
    registered_instrumentors: List[str] = []
    phoenix_enabled: bool = False
    phoenix_endpoint: Optional[str] = None

    def shutdown(self):
        pass

    def bind_stream(self, stream):
        return None

    def reset_stream(self, token) -> None:
        pass

    def bind_forced_model(self, model: Optional[str]):
        return None

    def reset_forced_model(self, token) -> None:
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
            # Track LLM span IDs seen during on_start so on_end can detect
            # nested LLM spans (provider inside framework = duplicate).
            self._llm_span_ids: set = set()

        def set_stream(self, stream):
            self._stream = stream

        def activate_stream(self, stream=None):
            target = self._stream if stream is None else stream
            return _active_qym_stream.set(target)

        def reset_stream(self, token) -> None:
            _active_qym_stream.reset(token)

        def on_start(self, span, parent_context=None):
            # Record LLM spans at start time so on_end can detect nested
            # duplicates.  Check both attributes and span name since
            # attributes may not be set yet at start time.
            is_llm = False
            attrs = span.attributes or {}
            kind = str(attrs.get("openinference.span.kind", "") or
                       attrs.get("ai.openinference.span.kind", "")).upper()
            if kind == "LLM":
                is_llm = True
            elif span.name in ("ChatCompletion", "Completion"):
                is_llm = True
            if is_llm:
                ctx = span.get_span_context()
                self._llm_span_ids.add(format(ctx.span_id, '016x'))
                if len(self._llm_span_ids) > 10000:
                    self._llm_span_ids.clear()

        _NOISE_SPAN_NAMES = frozenset({"connect", "dns.resolve", "tls.handshake"})

        def _is_llm_span(self, span):
            """Check if a span is an LLM span (from any instrumentor)."""
            attrs = span.attributes or {}
            kind = str(attrs.get("openinference.span.kind", "") or
                       attrs.get("ai.openinference.span.kind", "")).upper()
            return kind == "LLM"

        def on_end(self, span):
            if not self._stream:
                return
            if _active_qym_stream.get(None) is not self._stream:
                return
            if span.name in self._NOISE_SPAN_NAMES:
                return

            # Deduplicate nested LLM spans: when both a framework instrumentor
            # (LangChain) and a provider instrumentor (OpenAI) are active, the
            # same LLM call produces two nested LLM spans.  Keep the outer one
            # (framework), skip the inner one (provider).
            if self._is_llm_span(span):
                parent_id = format(span.parent.span_id, '016x') if span.parent else None
                if parent_id and parent_id in self._llm_span_ids:
                    # Parent is also an LLM span — this is a provider duplicate
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

    def __init__(
        self,
        tracer,
        qym_processor: Optional[QymSpanProcessor] = None,
        *,
        registered_instrumentors: Optional[List[str]] = None,
        phoenix_enabled: bool = False,
        phoenix_endpoint: Optional[str] = None,
    ):
        self._tracer = tracer
        self.qym_processor = qym_processor
        self.registered_instrumentors = list(registered_instrumentors or [])
        self.phoenix_enabled = phoenix_enabled
        self.phoenix_endpoint = phoenix_endpoint

    def bind_stream(self, stream):
        if not self.qym_processor:
            return None
        return self.qym_processor.activate_stream(stream)

    def reset_stream(self, token) -> None:
        if not self.qym_processor or token is None:
            return
        self.qym_processor.reset_stream(token)

    def bind_forced_model(self, model: Optional[str]):
        return _forced_llm_model.set(model or None)

    def reset_forced_model(self, token) -> None:
        if token is None:
            return
        _forced_llm_model.reset(token)

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

def _normalize_message_content(content: Any) -> str:
    """Best-effort text extraction from plain or structured message content."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (int, float, bool)):
        return str(content)
    if isinstance(content, list):
        parts = [_normalize_message_content(item) for item in content]
        text_parts = [part for part in parts if part]
        if text_parts:
            return "\n\n".join(text_parts)
        try:
            return _json.dumps(content, default=str)
        except Exception:
            return str(content)
    if isinstance(content, dict):
        type_ = content.get("type")
        if type_ in {"text", "input_text", "output_text"}:
            text = content.get("text")
            if isinstance(text, dict):
                return _normalize_message_content(text.get("value") or text.get("text"))
            return _normalize_message_content(text)
        if type_ in {"tool_result", "tool_output"}:
            return _normalize_message_content(content.get("content"))
        if "content" in content:
            inner = _normalize_message_content(content.get("content"))
            if inner:
                return inner
        if "text" in content:
            inner = _normalize_message_content(content.get("text"))
            if inner:
                return inner
        if "value" in content:
            inner = _normalize_message_content(content.get("value"))
            if inner:
                return inner
        try:
            return _json.dumps(content, default=str)
        except Exception:
            return str(content)
    return str(content)


def _obj_get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _serialize_span_value(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return _json.dumps(_json.loads(text), ensure_ascii=False, default=str)
            except Exception:
                return value
        return value

    try:
        return _json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def _block_type(block: Any) -> str:
    return str(_obj_get(block, "type", "") or "")


def _extract_tool_calls_from_message(msg: Any) -> List[Tuple[str, str, str]]:
    """Return (tool_call_id, tool_name, arguments_json) tuples from assistant messages."""
    if isinstance(msg, dict):
        role = msg.get("role")
        tool_calls = msg.get("tool_calls")
        content = msg.get("content")
    else:
        role = getattr(msg, "role", None)
        tool_calls = getattr(msg, "tool_calls", None)
        content = getattr(msg, "content", None)
    if role != "assistant":
        return []

    found: List[Tuple[str, str, str]] = []
    if tool_calls:
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
            if tc_id:
                found.append((tc_id, str(name or "unknown"), str(args or "")))

    if isinstance(content, list):
        for block in content:
            if _block_type(block) not in {"tool_use", "tool_call"}:
                continue
            tc_id = str(_obj_get(block, "id") or _obj_get(block, "tool_use_id") or _obj_get(block, "tool_call_id") or "")
            name = str(_obj_get(block, "name") or _obj_get(block, "tool_name") or "unknown")
            raw_args = _obj_get(block, "input")
            if raw_args is None:
                raw_args = _obj_get(block, "arguments")
            if isinstance(raw_args, str):
                args = raw_args
            elif raw_args is None:
                args = ""
            else:
                try:
                    args = _json.dumps(raw_args, default=str)
                except Exception:
                    args = str(raw_args)
            if tc_id:
                found.append((tc_id, name, args))

    return found


def _extract_tool_results_from_message(msg: Any) -> List[Tuple[str, str]]:
    """Return (tool_call_id, text_content) tuples from tool result messages."""
    if isinstance(msg, dict):
        role = msg.get("role")
        tool_call_id = msg.get("tool_call_id")
        content = msg.get("content")
    else:
        role = getattr(msg, "role", None)
        tool_call_id = getattr(msg, "tool_call_id", "")
        content = getattr(msg, "content", None)

    results: List[Tuple[str, str]] = []
    if role == "tool":
        text = _normalize_message_content(content)
        if tool_call_id or text:
            results.append((str(tool_call_id or ""), text))

    if role == "user" and isinstance(content, list):
        for block in content:
            if _block_type(block) not in {"tool_result", "tool_output"}:
                continue
            tc_id = str(_obj_get(block, "tool_use_id") or _obj_get(block, "tool_call_id") or _obj_get(block, "id") or "")
            text = _normalize_message_content(_obj_get(block, "content"))
            if tc_id or text:
                results.append((tc_id, text))

    return results


def _extract_reasoning_text(message: Any) -> str:
    if isinstance(message, dict):
        reasoning = message.get("reasoning")
        content = message.get("content")
    else:
        reasoning = getattr(message, "reasoning", None)
        content = getattr(message, "content", None)
    if reasoning:
        return str(reasoning)
    if isinstance(content, list):
        parts = []
        for block in content:
            type_ = _block_type(block)
            if type_ not in {"reasoning", "thinking"}:
                continue
            summary = _obj_get(block, "summary")
            text = _normalize_message_content(summary if summary is not None else _obj_get(block, "thinking", _obj_get(block, "text")))
            if text:
                parts.append(text)
        if parts:
            return "\n\n".join(parts)
    return ""

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
        for tc_id, name, args in _extract_tool_calls_from_message(msg):
            id_to_info[tc_id] = {"name": name, "arguments": args}

    # Collect unseen tool messages
    new_tools = []
    for msg in messages:
        for tc_id, content in _extract_tool_results_from_message(msg):
            seen_key = tc_id or f"tool-result-{len(new_tools)}-{hash(content)}"
            if seen_key in seen:
                continue
            seen.add(seen_key)
            new_tools.append((tc_id, content))

    if not new_tools:
        return

    # Approximate timing: tool execution happened between the last LLM
    # response and now (the start of the next LLM call).
    now_ns = time.time_ns()
    range_start_ns = _last_llm_end_ns.get(None) or now_ns
    # Divide the time window evenly among tool calls
    count = len(new_tools)
    slot_ns = max((now_ns - range_start_ns) // count, 1) if count else 1

    for i, (tc_id, content) in enumerate(new_tools):
        info = id_to_info.get(tc_id, {})
        tool_name = info.get("name", "unknown")
        tool_args = info.get("arguments", "")

        tool_start = range_start_ns + i * slot_ns
        tool_end = range_start_ns + (i + 1) * slot_ns

        span = tracer.start_span(f"tool:{tool_name}", start_time=tool_start)
        span.set_attribute("openinference.span.kind", "TOOL")
        span.set_attribute("tool.name", tool_name)
        if tool_args:
            span.set_attribute("input.value", _serialize_span_value(tool_args))
        if content:
            span.set_attribute("output.value", _serialize_span_value(content))

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
            reasoning = _extract_reasoning_text(msg)
            if reasoning:
                span.set_attribute(
                    f"gen_ai.completion.{choice.index}.reasoning",
                    str(reasoning)[:16000],
                )
    except Exception:
        pass


def _apply_forced_model(span: Any, kwargs: Dict[str, Any]) -> Optional[str]:
    """Override the outgoing model when the evaluator requested it."""
    forced_model = _forced_llm_model.get(None)
    if not forced_model:
        return None

    kwargs["model"] = forced_model
    try:
        if span and span.is_recording():
            span.set_attribute("llm.model_name", forced_model)
            span.set_attribute("gen_ai.request.model", forced_model)
    except Exception:
        pass
    return forced_model


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
        _apply_forced_model(otel_trace.get_current_span(), kwargs)
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
        _apply_forced_model(otel_trace.get_current_span(), kwargs)
        result = await _real_acreate(self, *args, **kwargs)
        _last_llm_end_ns.set(time.time_ns())
        _enrich_with_reasoning(result)
        return result

    mod.AsyncCompletions.create = _enriched_acreate
    logger.debug("OpenAI enrichments (tool spans + reasoning) installed")


def _patch_anthropic_enrichments():
    """Wrap Anthropic SDK message creation so tool spans and reasoning are captured."""
    try:
        import anthropic.resources.messages as mod
        from opentelemetry import trace as otel_trace
    except ImportError:
        return

    tracer = otel_trace.get_tracer("qym.enrichments")

    _real_create = mod.Messages.create

    @functools.wraps(_real_create)
    def _enriched_create(self, *args, **kwargs):
        messages = kwargs.get("messages")
        if messages:
            _emit_tool_spans(tracer, messages)
        result = _real_create(self, *args, **kwargs)
        _last_llm_end_ns.set(time.time_ns())
        if hasattr(result, "content"):
            _enrich_with_reasoning(type("AnthropicResult", (), {
                "choices": [type("Choice", (), {"index": 0, "message": result})()]
            })())
        return result

    mod.Messages.create = _enriched_create

    _real_acreate = mod.AsyncMessages.create

    @functools.wraps(_real_acreate)
    async def _enriched_acreate(self, *args, **kwargs):
        messages = kwargs.get("messages")
        if messages:
            _emit_tool_spans(tracer, messages)
        result = await _real_acreate(self, *args, **kwargs)
        _last_llm_end_ns.set(time.time_ns())
        if hasattr(result, "content"):
            _enrich_with_reasoning(type("AnthropicResult", (), {
                "choices": [type("Choice", (), {"index": 0, "message": result})()]
            })())
        return result

    mod.AsyncMessages.create = _enriched_acreate
    logger.debug("Anthropic enrichments (tool spans + reasoning) installed")


# ---------------------------------------------------------------------------
# Instrumentor registration
# ---------------------------------------------------------------------------

# OpenInference instrumentors qym treats as first-class built-ins.
#
# Keep this list intentionally small. Other integrations can still show up via
# direct OTel instrumentor discovery when installed in the environment.

_FRAMEWORK_INSTRUMENTORS: List[Tuple[str, str]] = [
    ("openinference.instrumentation.langchain", "LangChainInstrumentor"),
    ("openinference.instrumentation.litellm", "LiteLLMInstrumentor"),
]

_PROVIDER_INSTRUMENTORS: List[Tuple[str, str]] = [
    ("openinference.instrumentation.openai", "OpenAIInstrumentor"),
]

# Do not auto-register official OTel instrumentors when qym already registers
# an OpenInference equivalent for the same surface area; that creates redundant
# spans for the same logical operation.
_OTEL_DISCOVERY_SKIP: Set[str] = {
    "anthropic",
    "langchain",
    "openai",
    "openai_v2",
}

def _register_instrumentors(provider):
    """Register all available OpenInference instrumentors on the given TracerProvider."""
    # Suppress noisy DependencyConflict errors from instrumentors
    # whose provider SDKs aren't installed.
    _instrumentor_logger = logging.getLogger("opentelemetry.instrumentation.instrumentor")
    _prev_level = _instrumentor_logger.level
    _instrumentor_logger.setLevel(logging.CRITICAL)

    registered: List[str] = []

    def _record_registered(name: str) -> None:
        if name and name not in registered:
            registered.append(name)

    def _display_name(module_path: str) -> str:
        leaf = module_path.rsplit(".", 1)[-1].strip().lower()
        aliases = {
            "llama_index": "llama-index",
            "openai_v2": "openai",
            "openai_agents_v2": "openai-agents",
            "google_genai": "google-genai",
            "mistralai": "mistral",
        }
        return aliases.get(leaf, leaf.replace("_", "-"))

    def _try_register(module_path, class_name):
        try:
            mod = __import__(module_path, fromlist=[class_name])
            instrumentor_cls = getattr(mod, class_name)
            instrumentor = instrumentor_cls()
            if not getattr(instrumentor, '_is_instrumented_by_opentelemetry', False):
                instrumentor.instrument(tracer_provider=provider)
                _record_registered(_display_name(module_path))
                return True
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"Failed to register {class_name}: {e}")
        return False

    def _try_register_first_instrumentor(module_path):
        try:
            mod = importlib.import_module(module_path)
        except ImportError:
            return False
        except Exception as e:
            logger.debug(f"Failed to import {module_path}: {e}")
            return False

        classes = []
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if obj.__module__ != mod.__name__:
                continue
            if not obj.__name__.endswith("Instrumentor"):
                continue
            if obj.__name__ == "BaseInstrumentor":
                continue
            if not hasattr(obj, "instrument"):
                continue
            classes.append(obj)
        for instrumentor_cls in classes:
            try:
                instrumentor = instrumentor_cls()
                if not getattr(instrumentor, "_is_instrumented_by_opentelemetry", False):
                    instrumentor.instrument(tracer_provider=provider)
                    _record_registered(_display_name(module_path))
                    return True
            except Exception as e:
                logger.debug(f"Failed to register {instrumentor_cls.__name__}: {e}")
        return False

    # Provider instrumentors MUST register first so framework instrumentors
    # wrap on top.  When LangChain's callback fires, it sets
    # SUPPRESS_LANGUAGE_MODEL_INSTRUMENTATION_KEY before the provider
    # instrumentor's wrapper executes, preventing duplicate LLM spans.
    for module_path, class_name in _PROVIDER_INSTRUMENTORS:
        _try_register(module_path, class_name)

    for module_path, class_name in _FRAMEWORK_INSTRUMENTORS:
        _try_register(module_path, class_name)

    # Register any installed official OTel instrumentors as a catch-all for
    # libraries qym doesn't explicitly know about yet (e.g. chromadb).
    try:
        instr_pkg = importlib.import_module("opentelemetry.instrumentation")
        for mod_info in pkgutil.iter_modules(instr_pkg.__path__):
            name = mod_info.name
            if name.startswith("_") or name in _OTEL_DISCOVERY_SKIP:
                continue
            module_path = f"opentelemetry.instrumentation.{name}"
            _try_register_first_instrumentor(module_path)
    except Exception as e:
        logger.debug(f"OTel instrumentor discovery failed: {e}")

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
    global _initialized, _registered_instrumentors, _phoenix_enabled, _phoenix_endpoint

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

            # Register instrumentors — framework instrumentors first so we
            # know whether to skip provider-level enrichments.
            registered = _register_instrumentors(provider)
            _registered_instrumentors = list(registered)
            if not registered:
                logger.debug("No OpenInference instrumentors found — auto-instrumentation inactive")

            # Apply provider SDK enrichments (tool span emission, reasoning
            # capture).  These wrap SDK methods AFTER instrumentors so the
            # enrichment spans nest inside the instrumentor's span context.
            # When a framework instrumentor (LangChain, etc.) is also active,
            # the trace viewer collapses any duplicate tool spans.
            _patch_openai_enrichments()
            _patch_anthropic_enrichments()

            # Optional: Phoenix OTLP export for dual tracing.
            # Auto-enable if an endpoint is configured, matching the
            # "auto-detect when creds/config exist" pattern used for Langfuse.
            load_cwd_dotenv()

            phoenix_endpoint = (
                getattr(config, "phoenix_endpoint", None)
                or os.environ.get("PHOENIX_ENDPOINT")
                or os.environ.get("PHOENIX_COLLECTOR_ENDPOINT")
            )
            phoenix_enabled = (
                getattr(config, "phoenix_enabled", False)
                or os.environ.get("PHOENIX_ENABLED", "").lower() == "true"  # legacy compatibility
                or bool(phoenix_endpoint)
            )
            _phoenix_enabled = bool(phoenix_enabled and phoenix_endpoint)
            _phoenix_endpoint = phoenix_endpoint
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
    return OtelManager(
        tracer,
        qym_processor,
        registered_instrumentors=_registered_instrumentors,
        phoenix_enabled=_phoenix_enabled,
        phoenix_endpoint=_phoenix_endpoint,
    )
