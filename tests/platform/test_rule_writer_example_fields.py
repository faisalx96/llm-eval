"""Tests for selecting approved-example fields in rule-writer prompts."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qym_platform.services import llm_analyzer as llm_analyzer_service


def test_rule_writer_example_fields_are_filtered(monkeypatch) -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=(
                        '{"rules":[{"title":"Evidence","instruction":"Use evidence.",'
                        '"inferred_from":"Approved example.",'
                        '"explanation":"It demonstrates the evidence requirement."}]}'
                    )
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
        "approved_root_cause": True,
        "approved_root_causes": False,
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
        {
            "input": {"question": "What happened?"},
            "approved_root_cause": "Reasoning Error",
        }
    ]


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize(
    "include_detail, include_reason", [(False, False), (True, False), (False, True)]
)
def test_rule_writer_filters_nested_issue_fields(
    structured: bool, include_detail: bool, include_reason: bool
) -> None:
    correction = SimpleNamespace(
        input_snapshot={},
        expected_snapshot={},
        output_snapshot={},
        ai_root_cause="Agent",
        ai_root_cause_detail="AI_DETAIL",
        ai_root_cause_note="AI_REASON",
        human_root_cause="Agent",
        human_root_cause_detail="APPROVED_DETAIL",
        human_root_cause_note="REVIEWER_REASON",
    )
    if structured:
        correction.human_root_cause_issues = [
            {
                "category": "Agent",
                "subcategory": "APPROVED_DETAIL",
                "finding": "REVIEWER_REASON",
            },
            {
                "category": "Agent",
                "subcategory": "SECOND_DETAIL",
                "finding": "SECOND_REASON",
            },
        ]
    payload = llm_analyzer_service._rule_writer_correction_payload(
        correction,
        {
            "approved_root_causes": True,
            "approved_detail": include_detail,
            "reviewer_reasoning": include_reason,
        },
    )

    issues = payload["approved_root_cause_issues"]
    assert len(issues) == (2 if structured else 1)
    for issue in issues:
        assert ("subcategory" in issue) is include_detail
        assert ("finding" in issue) is include_reason
    serialized = json.dumps(payload)
    if not include_detail:
        assert "APPROVED_DETAIL" not in serialized
        assert "SECOND_DETAIL" not in serialized
    if not include_reason:
        assert "REVIEWER_REASON" not in serialized
        assert "SECOND_REASON" not in serialized
    assert "AI_DETAIL" not in serialized
    assert "AI_REASON" not in serialized
