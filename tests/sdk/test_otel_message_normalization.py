import json
import sys
from types import ModuleType

from qym.core.otel import (
    _classify_response,
    _extract_reasoning_text,
    _extract_tool_calls_from_message,
    _extract_tool_results_from_message,
    _normalize_message_content,
    _serialize_span_value,
)


def test_normalize_message_content_from_structured_blocks():
    content = [
        {"type": "text", "text": "First block"},
        {"type": "tool_result", "tool_use_id": "toolu_123", "content": [{"type": "text", "text": "Tool output"}]},
    ]

    assert _normalize_message_content(content) == "First block\n\nTool output"


def test_extract_tool_calls_from_structured_assistant_content():
    message = {
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_123",
                "name": "sql_query",
                "input": {"query": "select 1"},
            }
        ],
    }

    assert _extract_tool_calls_from_message(message) == [
        ("toolu_123", "sql_query", '{"query": "select 1"}')
    ]


def test_extract_tool_results_from_structured_user_content():
    message = {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_123",
                "content": [{"type": "text", "text": "rows returned"}],
            }
        ],
    }

    assert _extract_tool_results_from_message(message) == [
        ("toolu_123", "rows returned")
    ]


def test_extract_reasoning_text_from_structured_content_blocks():
    message = type(
        "Msg",
        (),
        {
            "reasoning": None,
            "content": [
                {"type": "reasoning", "summary": [{"type": "text", "text": "Thought 1"}]},
                {"type": "reasoning", "summary": [{"type": "text", "text": "Thought 2"}]},
            ],
        },
    )()

    assert _extract_reasoning_text(message) == "Thought 1\n\nThought 2"


def test_extract_reasoning_text_from_structured_dict_message():
    message = {
        "reasoning": None,
        "content": [
            {"type": "reasoning", "summary": [{"type": "text", "text": "Dict thought"}]},
        ],
    }

    assert _extract_reasoning_text(message) == "Dict thought"


def test_extract_tool_calls_from_anthropic_style_object_blocks():
    ToolUse = type("ToolUse", (), {"type": "tool_use", "id": "toolu_obj", "name": "sql_query", "input": {"query": "select 1"}})
    message = {
        "role": "assistant",
        "content": [ToolUse()],
    }

    assert _extract_tool_calls_from_message(message) == [
        ("toolu_obj", "sql_query", '{"query": "select 1"}')
    ]


def test_extract_reasoning_text_from_anthropic_thinking_blocks():
    Thinking = type("Thinking", (), {"type": "thinking", "thinking": "Hidden chain summary"})
    message = type("Msg", (), {"reasoning": None, "content": [Thinking()]})()

    assert _extract_reasoning_text(message) == "Hidden chain summary"


def test_extract_reasoning_text_from_object_payload_content():
    ReasoningPayload = type(
        "ReasoningPayload",
        (),
        {
            "__str__": lambda self: "<ReasoningPayload>",
            "content": [{"type": "text", "text": "<tool_call>call_tool()</tool_call>"}],
        },
    )
    message = type("Msg", (), {"reasoning": ReasoningPayload(), "content": None})()

    assert _extract_reasoning_text(message) == "<tool_call>call_tool()</tool_call>"


def test_classify_response_flags_reasoning_tool_call_leak_without_content(monkeypatch):
    class FakeSpan:
        def __init__(self):
            self.attributes = {}
            self.status = None

        def is_recording(self):
            return True

        def set_attribute(self, key, value):
            self.attributes[key] = value

        def set_status(self, status_code, description=None):
            self.status = (status_code, description)

        def add_event(self, *_args, **_kwargs):
            pass

    fake_span = FakeSpan()

    trace_mod = ModuleType("opentelemetry.trace")

    class FakeStatusCode:
        ERROR = "ERROR"

    trace_mod.StatusCode = FakeStatusCode
    trace_mod.get_current_span = lambda: fake_span

    otel_mod = ModuleType("opentelemetry")
    otel_mod.trace = trace_mod

    monkeypatch.setitem(sys.modules, "opentelemetry", otel_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", trace_mod)

    ReasoningPayload = type(
        "ReasoningPayload",
        (),
        {
            "__str__": lambda self: "<ReasoningPayload>",
            "content": [{"type": "text", "text": "<tool_call>call_tool()</tool_call>"}],
        },
    )

    result = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "reasoning": ReasoningPayload(),
                    "tool_calls": [],
                }
            }
        ]
    }

    _classify_response(result)

    assert fake_span.attributes["qym.response.classification"] == "malformed_tool_call"
    assert fake_span.attributes["qym.response.where"] == "reasoning"
    assert fake_span.attributes["qym.response.evidence"] == "</tool_call>,<tool_call>"
    assert fake_span.status == (FakeStatusCode.ERROR, "malformed tool call")


def test_serialize_span_value_keeps_large_sql_results_intact():
    payload = {
        "columns": ["School Name", "Street"],
        "rows": [[f"School {i}", "313 West Winton Avenue" * 6] for i in range(200)],
    }

    serialized = _serialize_span_value(json.dumps(payload))
    parsed = json.loads(serialized)

    assert parsed == payload
