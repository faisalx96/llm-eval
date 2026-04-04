import json

from qym.core.otel import (
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


def test_serialize_span_value_keeps_large_sql_results_intact():
    payload = {
        "columns": ["School Name", "Street"],
        "rows": [[f"School {i}", "313 West Winton Avenue" * 6] for i in range(200)],
    }

    serialized = _serialize_span_value(json.dumps(payload))
    parsed = json.loads(serialized)

    assert parsed == payload
