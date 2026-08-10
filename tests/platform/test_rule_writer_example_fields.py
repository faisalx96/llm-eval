"""Tests for selecting approved-example fields in rule-writer prompts."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from qym_platform.services import llm_analyzer as llm_analyzer_service


def test_rule_writer_example_fields_are_filtered(monkeypatch) -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content='{"rules":[{"title":"Evidence","instruction":"Use evidence."}]}'
                )
            )
        ]
    )
    create_completion = AsyncMock(return_value=completion)
    monkeypatch.setattr(
        llm_analyzer_service,
        "create_chat_completion_compat",
        create_completion,
    )

    correction = SimpleNamespace(
        input_snapshot={"question": "What happened?"},
        expected_snapshot={"answer": "Expected"},
        output_snapshot={"answer": "Actual"},
        ai_root_cause="Reasoning Error",
        human_root_cause="Reasoning Error",
        human_root_cause_detail="Evidence gap",
        human_root_cause_note="The answer was not supported.",
    )
    fields = {
        "input": True,
        "expected": False,
        "output": False,
        "previous_ai_root_cause": False,
        "previous_ai_root_causes": False,
        "previous_ai_category_taxonomy": False,
        "approved_root_cause": True,
        "approved_root_causes": False,
        "approved_category_taxonomy": False,
        "approved_detail": False,
        "reviewer_reasoning": False,
    }

    asyncio.run(
        llm_analyzer_service.infer_analysis_rules(
            SimpleNamespace(),
            "test-model",
            reference_documents=[],
            corrections=[correction],
            include_fields=fields,
        )
    )

    user_prompt = next(
        message["content"]
        for message in create_completion.await_args.kwargs["messages"]
        if message["role"] == "user"
    )
    payload = json.loads(user_prompt[user_prompt.index("{") :])
    assert payload["approved_correction_examples"] == [
        {"input": {"question": "What happened?"}, "approved_root_cause": "Reasoning Error"}
    ]
