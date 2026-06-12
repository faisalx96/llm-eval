"""Lifecycle tests for qym's OTel integration.

OT-1 — Evaluator shutdown must not kill the global TracerProvider:
  * a host application's span processor keeps receiving spans after qym's
    shutdown(), and is never shutdown by qym;
  * repeated Evaluator otel setups re-use the same QymSpanProcessor (the
    provider never accumulates more than one qym processor).

OT-2 — Anthropic enrichment creates a dedicated child LLM span:
  * exactly one new LLM span per Messages.create call, carrying the
    openinference.span.kind == "LLM" attribute trace-stats counting keys on;
  * success leaves the parent/item span status UNSET;
  * a malformed/refusal-style response marks ONLY the LLM span as ERROR.
"""
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SDK_SRC = ROOT / "packages" / "sdk"
if str(SDK_SRC) not in sys.path:
    sys.path.insert(0, str(SDK_SRC))

otel_sdk_trace = pytest.importorskip("opentelemetry.sdk.trace")
from opentelemetry import trace as otel_trace_api  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider as SdkTracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import (  # noqa: E402
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)

import qym.core.otel as otel_module  # noqa: E402


class _ListExporter(SpanExporter):
    def __init__(self):
        self.spans = []

    def export(self, spans):
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self):
        pass


class _SentinelProcessor(otel_sdk_trace.SpanProcessor):
    """Stand-in for a host application's own span processor."""

    def __init__(self):
        self.span_names = []
        self.shutdown_called = False
        self.force_flush_calls = 0

    def on_start(self, span, parent_context=None):
        pass

    def on_end(self, span):
        self.span_names.append(span.name)

    def shutdown(self):
        self.shutdown_called = True

    def force_flush(self, timeout_millis=30000):
        self.force_flush_calls += 1
        return True


@pytest.fixture()
def fresh_otel_state(monkeypatch):
    """Isolate qym's module-level otel state and the global tracer provider."""
    saved = {
        "_initialized": otel_module._initialized,
        "_registered_instrumentors": list(otel_module._registered_instrumentors),
        "_phoenix_enabled": otel_module._phoenix_enabled,
        "_phoenix_endpoint": otel_module._phoenix_endpoint,
        "_qym_owned_provider": otel_module._qym_owned_provider,
        "_qym_owned_processors": list(otel_module._qym_owned_processors),
        "_shared_qym_processor": otel_module._shared_qym_processor,
        "_trace_content_enabled": otel_module._trace_content_enabled,
    }
    otel_module._initialized = False
    otel_module._registered_instrumentors = []
    otel_module._phoenix_enabled = False
    otel_module._phoenix_endpoint = None
    otel_module._qym_owned_provider = None
    otel_module._qym_owned_processors.clear()
    otel_module._shared_qym_processor = None
    otel_module._trace_content_enabled = True

    # Keep the test hermetic: no instrumentor registration, no SDK patching,
    # no .env loading, no Phoenix export.
    monkeypatch.setattr(otel_module, "_register_instrumentors", lambda provider: [])
    monkeypatch.setattr(otel_module, "_patch_openai_enrichments", lambda: None)
    monkeypatch.setattr(otel_module, "_patch_anthropic_enrichments", lambda: None)
    monkeypatch.setattr(otel_module, "load_cwd_dotenv", lambda **kw: None)
    for var in ("PHOENIX_ENDPOINT", "PHOENIX_COLLECTOR_ENDPOINT", "PHOENIX_ENABLED"):
        monkeypatch.delenv(var, raising=False)

    yield

    otel_module._initialized = saved["_initialized"]
    otel_module._registered_instrumentors = saved["_registered_instrumentors"]
    otel_module._phoenix_enabled = saved["_phoenix_enabled"]
    otel_module._phoenix_endpoint = saved["_phoenix_endpoint"]
    otel_module._qym_owned_provider = saved["_qym_owned_provider"]
    otel_module._qym_owned_processors.clear()
    otel_module._qym_owned_processors.extend(saved["_qym_owned_processors"])
    otel_module._shared_qym_processor = saved["_shared_qym_processor"]
    otel_module._trace_content_enabled = saved["_trace_content_enabled"]


def _qym_processor_count(provider) -> int:
    procs = provider._active_span_processor._span_processors
    return sum(1 for p in procs if isinstance(p, otel_module.QymSpanProcessor))


# ---------------------------------------------------------------------------
# OT-1 — shutdown lifecycle
# ---------------------------------------------------------------------------
class TestShutdownLifecycle:
    def _make_host_provider(self, monkeypatch):
        """A 'host application' provider with its own sentinel processor."""
        provider = SdkTracerProvider(shutdown_on_exit=False)
        sentinel = _SentinelProcessor()
        provider.add_span_processor(sentinel)
        # qym resolves the global provider via opentelemetry.trace; point it
        # at the host's provider without touching real process-global state.
        monkeypatch.setattr(
            otel_trace_api, "get_tracer_provider", lambda: provider
        )
        monkeypatch.setattr(
            otel_trace_api, "set_tracer_provider", lambda p: None
        )
        return provider, sentinel

    def test_host_processor_survives_two_setup_shutdown_cycles(
        self, fresh_otel_state, monkeypatch
    ):
        provider, sentinel = self._make_host_provider(monkeypatch)
        config = SimpleNamespace(otel_enabled=True)

        mgr1 = otel_module.create_otel_manager(config)
        assert mgr1.enabled
        mgr1.shutdown()

        mgr2 = otel_module.create_otel_manager(config)
        assert mgr2.enabled
        mgr2.shutdown()

        # qym never shut down the host's processor or provider.
        assert sentinel.shutdown_called is False

        # The host's processor still receives spans after qym's shutdowns.
        tracer = provider.get_tracer("host-app")
        with tracer.start_as_current_span("host-span-after-qym-shutdown"):
            pass
        assert "host-span-after-qym-shutdown" in sentinel.span_names

    def test_repeated_setups_do_not_stack_qym_processors(
        self, fresh_otel_state, monkeypatch
    ):
        provider, _sentinel = self._make_host_provider(monkeypatch)
        config = SimpleNamespace(otel_enabled=True)

        mgr1 = otel_module.create_otel_manager(config)
        mgr1.shutdown()
        mgr2 = otel_module.create_otel_manager(config)
        mgr2.shutdown()
        mgr3 = otel_module.create_otel_manager(config)
        mgr3.shutdown()

        assert _qym_processor_count(provider) <= 1
        # The same processor instance is re-used across constructions.
        assert mgr1.qym_processor is mgr2.qym_processor is mgr3.qym_processor

    def test_shutdown_flushes_qym_owned_processors_only(
        self, fresh_otel_state, monkeypatch
    ):
        provider, sentinel = self._make_host_provider(monkeypatch)
        config = SimpleNamespace(otel_enabled=True)

        flushed = []

        mgr = otel_module.create_otel_manager(config)
        for proc in otel_module._qym_owned_processors:
            orig = proc.force_flush
            proc.force_flush = (
                lambda timeout_millis=30000, _orig=orig, _p=proc: (
                    flushed.append(_p),
                    _orig(timeout_millis),
                )[1]
            )

        host_flush_count_before = sentinel.force_flush_calls
        mgr.shutdown()

        # Every qym-owned processor got flushed; the host's sentinel did not.
        assert flushed, "expected qym-owned processors to be flushed"
        assert set(flushed) == set(otel_module._qym_owned_processors)
        assert sentinel.force_flush_calls == host_flush_count_before

    def test_qym_creates_and_records_provider_when_none_exists(
        self, fresh_otel_state, monkeypatch
    ):
        created = {}

        class _NonSdkProvider:  # what trace.get_tracer_provider() returns pre-init
            pass

        monkeypatch.setattr(
            otel_trace_api, "get_tracer_provider", lambda: created.get(
                "provider", _NonSdkProvider()
            )
        )

        def _capture_set(provider):
            created["provider"] = provider

        monkeypatch.setattr(otel_trace_api, "set_tracer_provider", _capture_set)

        config = SimpleNamespace(otel_enabled=True)
        mgr = otel_module.create_otel_manager(config)
        assert mgr.enabled

        # qym created the provider and recorded ownership of it.
        assert isinstance(created.get("provider"), SdkTracerProvider)
        assert otel_module._qym_owned_provider is created["provider"]
        # Shutdown still must not shut the provider down (later runs reuse it).
        mgr.shutdown()
        tracer = created["provider"].get_tracer("after-shutdown")
        with tracer.start_as_current_span("still-alive"):
            pass


# ---------------------------------------------------------------------------
# OT-2 — Anthropic enrichment creates a dedicated LLM span
# ---------------------------------------------------------------------------
def _install_fake_anthropic(monkeypatch, create_fn):
    """Install a fake anthropic.resources.messages module into sys.modules."""

    class Messages:
        create = create_fn

    class AsyncMessages:
        async def create(self, *args, **kwargs):  # pragma: no cover - unused
            return create_fn(self, *args, **kwargs)

    fake_mod = ModuleType("anthropic.resources.messages")
    fake_mod.Messages = Messages
    fake_mod.AsyncMessages = AsyncMessages

    monkeypatch.setitem(sys.modules, "anthropic", ModuleType("anthropic"))
    monkeypatch.setitem(
        sys.modules, "anthropic.resources", ModuleType("anthropic.resources")
    )
    monkeypatch.setitem(sys.modules, "anthropic.resources.messages", fake_mod)
    return fake_mod


def _fake_anthropic_message(content_blocks, *, stop_reason="end_turn"):
    usage = SimpleNamespace(input_tokens=11, output_tokens=7)
    msg = SimpleNamespace(
        role="assistant",
        model="claude-opus-4-8",
        content=content_blocks,
        stop_reason=stop_reason,
        usage=usage,
    )
    msg.model_dump = lambda mode="json": {
        "role": "assistant",
        "model": "claude-opus-4-8",
        "content": content_blocks,
        "stop_reason": stop_reason,
        "usage": {"input_tokens": 11, "output_tokens": 7},
    }
    return msg


@pytest.fixture()
def isolated_tracing(monkeypatch):
    """A private TracerProvider + in-memory exporter wired into qym's otel."""
    provider = SdkTracerProvider(shutdown_on_exit=False)
    exporter = _ListExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        otel_trace_api, "get_tracer", lambda name, *a, **k: provider.get_tracer(name)
    )
    return provider, exporter


class TestAnthropicLlmSpan:
    def test_success_creates_one_llm_span_and_leaves_item_span_clean(
        self, monkeypatch, isolated_tracing
    ):
        provider, exporter = isolated_tracing

        def _create(self, *args, **kwargs):
            return _fake_anthropic_message([{"type": "text", "text": "hello there"}])

        fake_mod = _install_fake_anthropic(monkeypatch, _create)
        otel_module._patch_anthropic_enrichments()

        item_tracer = provider.get_tracer("qym")
        with item_tracer.start_as_current_span("eval-run-item-0"):
            result = fake_mod.Messages().create(
                model="claude-opus-4-8",
                max_tokens=64,
                messages=[{"role": "user", "content": "hi"}],
            )

        assert result.stop_reason == "end_turn"

        llm_spans = [
            s
            for s in exporter.spans
            if (s.attributes or {}).get("openinference.span.kind") == "LLM"
        ]
        item_spans = [s for s in exporter.spans if s.name == "eval-run-item-0"]
        assert len(llm_spans) == 1, "expected exactly one dedicated LLM span"
        assert len(item_spans) == 1

        llm_span = llm_spans[0]
        item_span = item_spans[0]

        # The LLM span is a child of the item span, not a sibling/root.
        assert llm_span.parent is not None
        assert llm_span.parent.span_id == item_span.context.span_id

        # LLM-call attributes used by platform trace-stats aggregation.
        attrs = dict(llm_span.attributes or {})
        assert attrs["openinference.span.kind"] == "LLM"
        assert attrs["llm.model_name"] == "claude-opus-4-8"
        assert attrs["llm.token_count.prompt"] == 11
        assert attrs["llm.token_count.completion"] == 7
        assert attrs["llm.token_count.total"] == 18
        assert attrs["llm.stop_reason"] == "end_turn"
        assert "hello there" in attrs["output.value"]
        assert attrs["llm.input_messages.0.message.content"] == "hi"

        # Success: neither span carries an ERROR status.
        assert llm_span.status.status_code.name in ("UNSET", "OK")
        assert item_span.status.status_code.name in ("UNSET", "OK")

    def test_malformed_response_marks_only_the_llm_span(
        self, monkeypatch, isolated_tracing
    ):
        provider, exporter = isolated_tracing

        # Leaked tool-call syntax with no structured tool_use blocks: the
        # classifier flags this as a fatal malformed_tool_call.
        def _create(self, *args, **kwargs):
            return _fake_anthropic_message(
                [{"type": "text", "text": "<tool_call>do_thing()</tool_call>"}],
                stop_reason="end_turn",
            )

        fake_mod = _install_fake_anthropic(monkeypatch, _create)
        otel_module._patch_anthropic_enrichments()

        item_tracer = provider.get_tracer("qym")
        with item_tracer.start_as_current_span("eval-run-item-1"):
            fake_mod.Messages().create(
                model="claude-opus-4-8",
                max_tokens=64,
                messages=[{"role": "user", "content": "go"}],
            )

        llm_spans = [
            s
            for s in exporter.spans
            if (s.attributes or {}).get("openinference.span.kind") == "LLM"
        ]
        item_spans = [s for s in exporter.spans if s.name == "eval-run-item-1"]
        assert len(llm_spans) == 1
        assert len(item_spans) == 1

        llm_span, item_span = llm_spans[0], item_spans[0]
        llm_attrs = dict(llm_span.attributes or {})
        item_attrs = dict(item_span.attributes or {})

        # Classification + error status land on the LLM span ...
        assert llm_attrs["qym.response.classification"] == "malformed_tool_call"
        assert llm_span.status.status_code.name == "ERROR"

        # ... and ONLY on the LLM span; the item span stays clean.
        assert "qym.response.classification" not in item_attrs
        assert item_span.status.status_code.name in ("UNSET", "OK")

    def test_provider_exception_marks_llm_span_and_propagates(
        self, monkeypatch, isolated_tracing
    ):
        provider, exporter = isolated_tracing

        def _create(self, *args, **kwargs):
            raise RuntimeError("anthropic API blew up")

        fake_mod = _install_fake_anthropic(monkeypatch, _create)
        otel_module._patch_anthropic_enrichments()

        item_tracer = provider.get_tracer("qym")
        with item_tracer.start_as_current_span("eval-run-item-2"):
            with pytest.raises(RuntimeError, match="anthropic API blew up"):
                fake_mod.Messages().create(
                    model="claude-opus-4-8",
                    messages=[{"role": "user", "content": "go"}],
                )

        llm_spans = [
            s
            for s in exporter.spans
            if (s.attributes or {}).get("openinference.span.kind") == "LLM"
        ]
        item_spans = [s for s in exporter.spans if s.name == "eval-run-item-2"]
        assert len(llm_spans) == 1
        assert llm_spans[0].status.status_code.name == "ERROR"
        # Item span ends cleanly (the exception is re-raised to the caller,
        # which is the eval harness's concern, not the tracer's).
        assert len(item_spans) == 1

    def test_classification_noops_on_non_llm_ambient_span(self, monkeypatch):
        """_classify_response must not write onto a non-LLM (item) span."""

        class FakeItemSpan:
            name = "eval-run-item-3"
            attributes = {"openinference.span.kind": "CHAIN"}

            def __init__(self):
                self.written = {}
                self.status = None

            def is_recording(self):
                return True

            def set_attribute(self, key, value):
                self.written[key] = value

            def set_status(self, *a, **k):
                self.status = a

            def add_event(self, *a, **k):
                pass

        fake_span = FakeItemSpan()
        monkeypatch.setattr(otel_trace_api, "get_current_span", lambda: fake_span)

        result = {
            "choices": [
                {
                    "message": {
                        "content": "<tool_call>leak()</tool_call>",
                        "tool_calls": [],
                    }
                }
            ]
        }
        otel_module._classify_response(result)
        otel_module._enrich_with_reasoning(SimpleNamespace(choices=[]))

        assert fake_span.written == {}
        assert fake_span.status is None
