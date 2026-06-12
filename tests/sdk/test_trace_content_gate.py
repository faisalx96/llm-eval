"""DOC-3 — the documented trace-content privacy control must actually work.

Docs promise `TRACELOOP_TRACE_CONTENT=false` disables prompt/response capture
(`QYM_TRACE_CONTENT` is the qym-native alias). When disabled, every
content-write site in qym.core.otel must omit/redact message, prompt,
response, and reasoning text while keeping counts, latency, model names, and
error classification metadata.
"""
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SDK_SRC = ROOT / "packages" / "sdk"
if str(SDK_SRC) not in sys.path:
    sys.path.insert(0, str(SDK_SRC))

import qym.core.otel as otel_module  # noqa: E402
from qym.core.otel import (  # noqa: E402
    _REDACTED,
    _emit_tool_spans,
    _enrich_openai_span_io,
    _enrich_with_reasoning,
    _read_trace_content_env,
    _refresh_trace_content_gate,
    _set_message_span_attrs,
)


@pytest.fixture(autouse=True)
def restore_gate():
    saved = otel_module._trace_content_enabled
    yield
    otel_module._trace_content_enabled = saved


@pytest.fixture()
def content_disabled(monkeypatch):
    monkeypatch.setenv("TRACELOOP_TRACE_CONTENT", "false")
    _refresh_trace_content_gate()
    yield
    monkeypatch.delenv("TRACELOOP_TRACE_CONTENT", raising=False)
    _refresh_trace_content_gate()


class _RecordingSpan:
    def __init__(self):
        self.attributes = {}

    def is_recording(self):
        return True

    def set_attribute(self, key, value):
        self.attributes[key] = value


# ---------------------------------------------------------------------------
# Env parsing
# ---------------------------------------------------------------------------
class TestGateEnvParsing:
    def test_default_is_enabled(self, monkeypatch):
        monkeypatch.delenv("TRACELOOP_TRACE_CONTENT", raising=False)
        monkeypatch.delenv("QYM_TRACE_CONTENT", raising=False)
        assert _read_trace_content_env() is True

    @pytest.mark.parametrize("value", ["false", "FALSE", "False ", "0", "no", "off"])
    def test_traceloop_var_disables(self, monkeypatch, value):
        monkeypatch.setenv("TRACELOOP_TRACE_CONTENT", value)
        assert _read_trace_content_env() is False

    def test_qym_alias_disables(self, monkeypatch):
        monkeypatch.delenv("TRACELOOP_TRACE_CONTENT", raising=False)
        monkeypatch.setenv("QYM_TRACE_CONTENT", "false")
        assert _read_trace_content_env() is False

    def test_true_values_keep_capture_enabled(self, monkeypatch):
        monkeypatch.setenv("TRACELOOP_TRACE_CONTENT", "true")
        monkeypatch.delenv("QYM_TRACE_CONTENT", raising=False)
        assert _read_trace_content_env() is True

    def test_refresh_updates_module_gate(self, monkeypatch):
        monkeypatch.setenv("TRACELOOP_TRACE_CONTENT", "false")
        assert _refresh_trace_content_gate() is False
        assert otel_module._capture_content() is False
        monkeypatch.setenv("TRACELOOP_TRACE_CONTENT", "true")
        assert _refresh_trace_content_gate() is True
        assert otel_module._capture_content() is True


# ---------------------------------------------------------------------------
# OpenAI-path content sites
# ---------------------------------------------------------------------------
class TestOpenAiIoGate:
    def _result(self):
        return {
            "choices": [
                {"message": {"role": "assistant", "content": "SECRET ANSWER"}}
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }

    def test_content_present_by_default(self):
        _refresh_trace_content_gate()
        span = _RecordingSpan()
        messages = [{"role": "user", "content": "SECRET PROMPT"}]
        _enrich_openai_span_io(
            span, messages=messages, kwargs={"model": "gpt-x"}, result=self._result()
        )
        assert "SECRET PROMPT" in span.attributes["input.value"]
        assert "SECRET ANSWER" in span.attributes["output.value"]
        assert (
            span.attributes["llm.input_messages.0.message.content"] == "SECRET PROMPT"
        )
        assert span.attributes["llm.token_count.total"] == 8

    def test_content_redacted_when_disabled(self, content_disabled):
        span = _RecordingSpan()
        messages = [{"role": "user", "content": "SECRET PROMPT"}]
        _enrich_openai_span_io(
            span, messages=messages, kwargs={"model": "gpt-x"}, result=self._result()
        )

        # No prompt/response text anywhere in the captured attributes.
        blob = " ".join(str(v) for v in span.attributes.values())
        assert "SECRET PROMPT" not in blob
        assert "SECRET ANSWER" not in blob

        # Redaction markers replace content; structure + counts are intact.
        assert span.attributes["input.value"] == _REDACTED
        assert span.attributes["output.value"] == _REDACTED
        assert span.attributes["llm.input_messages.0.message.content"] == _REDACTED
        assert span.attributes["llm.input_messages.0.message.role"] == "user"
        assert span.attributes["llm.token_count.prompt"] == 5
        assert span.attributes["llm.token_count.completion"] == 3
        assert span.attributes["llm.token_count.total"] == 8

    def test_message_tool_call_arguments_redacted(self, content_disabled):
        span = _RecordingSpan()
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "lookup",
                            "arguments": '{"q": "SECRET ARG"}',
                        },
                    }
                ],
            }
        ]
        _set_message_span_attrs(span, "llm.input_messages", messages)
        base = "llm.input_messages.0.message.tool_calls.0.tool_call"
        assert span.attributes[f"{base}.id"] == "call_1"
        assert span.attributes[f"{base}.function.name"] == "lookup"
        assert span.attributes[f"{base}.function.arguments"] == _REDACTED

    def test_reasoning_redacted_but_presence_kept(self, content_disabled, monkeypatch):
        span = _RecordingSpan()
        span.attributes["openinference.span.kind"] = "LLM"
        import opentelemetry.trace as otel_trace_api

        monkeypatch.setattr(otel_trace_api, "get_current_span", lambda: span)

        result = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    index=0,
                    message={
                        "role": "assistant",
                        "content": "x",
                        "reasoning": "SECRET CHAIN OF THOUGHT",
                    },
                )
            ]
        )
        _enrich_with_reasoning(result)
        assert span.attributes["gen_ai.completion.0.reasoning"] == _REDACTED

    def test_reasoning_captured_by_default(self, monkeypatch):
        _refresh_trace_content_gate()
        span = _RecordingSpan()
        span.attributes["openinference.span.kind"] = "LLM"
        import opentelemetry.trace as otel_trace_api

        monkeypatch.setattr(otel_trace_api, "get_current_span", lambda: span)

        result = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    index=0,
                    message={
                        "role": "assistant",
                        "content": "x",
                        "reasoning": "visible thought",
                    },
                )
            ]
        )
        _enrich_with_reasoning(result)
        assert span.attributes["gen_ai.completion.0.reasoning"] == "visible thought"


# ---------------------------------------------------------------------------
# Tool spans
# ---------------------------------------------------------------------------
class _FakeToolSpan:
    def __init__(self, name):
        self.name = name
        self.attributes = {}
        self.ended = False

    def set_attribute(self, key, value):
        self.attributes[key] = value

    def set_status(self, *a, **k):
        pass

    def add_event(self, *a, **k):
        pass

    def end(self, end_time=None):
        self.ended = True


class _FakeTracer:
    def __init__(self):
        self.spans = []

    def start_span(self, name, start_time=None):
        span = _FakeToolSpan(name)
        self.spans.append(span)
        return span


class TestToolSpanGate:
    def _messages(self, suffix):
        return [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": f"call_{suffix}",
                        "function": {
                            "name": "search",
                            "arguments": '{"q": "SECRET ARG"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": f"call_{suffix}",
                "content": "SECRET TOOL OUTPUT",
            },
        ]

    def test_tool_content_redacted_when_disabled(self, content_disabled):
        tracer = _FakeTracer()
        token = otel_module._emitted_tool_ids.set(set())
        try:
            _emit_tool_spans(tracer, self._messages("redacted"))
        finally:
            otel_module._emitted_tool_ids.reset(token)

        assert len(tracer.spans) == 1
        span = tracer.spans[0]
        assert span.attributes["tool.name"] == "search"
        assert span.attributes["input.value"] == _REDACTED
        assert span.attributes["output.value"] == _REDACTED
        assert span.ended

    def test_tool_content_present_by_default(self):
        _refresh_trace_content_gate()
        tracer = _FakeTracer()
        token = otel_module._emitted_tool_ids.set(set())
        try:
            _emit_tool_spans(tracer, self._messages("visible"))
        finally:
            otel_module._emitted_tool_ids.reset(token)

        assert len(tracer.spans) == 1
        span = tracer.spans[0]
        assert "SECRET ARG" in span.attributes["input.value"]
        assert span.attributes["output.value"] == "SECRET TOOL OUTPUT"


# ---------------------------------------------------------------------------
# Anthropic wrapper end-to-end
# ---------------------------------------------------------------------------
class TestAnthropicWrapperGate:
    def _setup(self, monkeypatch):
        pytest.importorskip("opentelemetry.sdk.trace")
        import opentelemetry.trace as otel_trace_api
        from opentelemetry.sdk.trace import TracerProvider as SdkTracerProvider
        from opentelemetry.sdk.trace.export import (
            SimpleSpanProcessor,
            SpanExporter,
            SpanExportResult,
        )

        class _ListExporter(SpanExporter):
            def __init__(self):
                self.spans = []

            def export(self, spans):
                self.spans.extend(spans)
                return SpanExportResult.SUCCESS

            def shutdown(self):
                pass

        provider = SdkTracerProvider(shutdown_on_exit=False)
        exporter = _ListExporter()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        monkeypatch.setattr(
            otel_trace_api,
            "get_tracer",
            lambda name, *a, **k: provider.get_tracer(name),
        )

        def _create(self, *args, **kwargs):
            usage = SimpleNamespace(input_tokens=21, output_tokens=9)
            msg = SimpleNamespace(
                role="assistant",
                model="claude-opus-4-8",
                content=[{"type": "text", "text": "SECRET ANSWER"}],
                stop_reason="end_turn",
                usage=usage,
            )
            msg.model_dump = lambda mode="json": {
                "role": "assistant",
                "model": "claude-opus-4-8",
                "content": [{"type": "text", "text": "SECRET ANSWER"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 21, "output_tokens": 9},
            }
            return msg

        class Messages:
            create = _create

        class AsyncMessages:
            async def create(self, *args, **kwargs):  # pragma: no cover
                return _create(self, *args, **kwargs)

        fake_mod = ModuleType("anthropic.resources.messages")
        fake_mod.Messages = Messages
        fake_mod.AsyncMessages = AsyncMessages
        monkeypatch.setitem(sys.modules, "anthropic", ModuleType("anthropic"))
        monkeypatch.setitem(
            sys.modules, "anthropic.resources", ModuleType("anthropic.resources")
        )
        monkeypatch.setitem(sys.modules, "anthropic.resources.messages", fake_mod)

        otel_module._patch_anthropic_enrichments()
        return fake_mod, exporter

    def test_no_content_in_llm_span_when_disabled(self, monkeypatch, content_disabled):
        fake_mod, exporter = self._setup(monkeypatch)

        fake_mod.Messages().create(
            model="claude-opus-4-8",
            messages=[{"role": "user", "content": "SECRET PROMPT"}],
        )

        llm_spans = [
            s
            for s in exporter.spans
            if (s.attributes or {}).get("openinference.span.kind") == "LLM"
        ]
        assert len(llm_spans) == 1
        attrs = dict(llm_spans[0].attributes or {})

        blob = " ".join(str(v) for v in attrs.values())
        assert "SECRET PROMPT" not in blob
        assert "SECRET ANSWER" not in blob

        # Counts / model / stop_reason metadata survive redaction.
        assert attrs["llm.model_name"] == "claude-opus-4-8"
        assert attrs["llm.token_count.prompt"] == 21
        assert attrs["llm.token_count.completion"] == 9
        assert attrs["llm.token_count.total"] == 30
        assert attrs["llm.stop_reason"] == "end_turn"
        assert attrs["input.value"] == _REDACTED
        assert attrs["output.value"] == _REDACTED

    def test_content_present_by_default(self, monkeypatch):
        _refresh_trace_content_gate()
        fake_mod, exporter = self._setup(monkeypatch)

        fake_mod.Messages().create(
            model="claude-opus-4-8",
            messages=[{"role": "user", "content": "SECRET PROMPT"}],
        )

        llm_spans = [
            s
            for s in exporter.spans
            if (s.attributes or {}).get("openinference.span.kind") == "LLM"
        ]
        assert len(llm_spans) == 1
        attrs = dict(llm_spans[0].attributes or {})
        assert "SECRET PROMPT" in attrs["input.value"]
        assert "SECRET ANSWER" in attrs["output.value"]
        assert attrs["llm.input_messages.0.message.content"] == "SECRET PROMPT"
        assert attrs["llm.token_count.total"] == 30
