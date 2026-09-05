from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from qym_platform.db.models import RunItem
from qym_platform.services.analysis_aggregation import aggregate_analysis_categories
from qym_platform.services.llm_analyzer import (
    AnalysisResult,
    _rule_writer_correction_payload,
    build_analysis_prompt,
    parse_llm_response,
)
from qym_platform.services.root_cause_categories import (
    analysis_root_cause_issues,
    normalize_root_cause_issues,
    project_root_cause_issues,
)


def test_issue_helpers_preserve_independent_issues_and_project_the_primary() -> None:
    issues = normalize_root_cause_issues(
        [
            {
                "category": " Agent ",
                "subcategory": " Retrieval failure ",
                "finding": "The value search omitted status A.",
            },
            {
                "category": "Agent",
                "subcategory": "Predicate construction",
                "finding": "The filter also used the wrong boolean operator.",
            },
        ]
    )

    assert len(issues) == 2
    assert issues[0] == {
        "category": "Agent",
        "subcategory": "Retrieval failure",
        "finding": "The value search omitted status A.",
    }
    assert issues[1]["subcategory"] == "Predicate construction"
    assert project_root_cause_issues(issues) == {
        "root_cause": "Agent",
        "root_causes": ["Agent"],
        "root_cause_detail": "Retrieval failure",
        "root_cause_note": "The value search omitted status A.",
    }


def test_legacy_analysis_projects_one_issue_per_category() -> None:
    issues = analysis_root_cause_issues(
        {
            "root_causes": ["Agent", "Data"],
            "root_cause_detail": "Missing value",
            "root_cause_note": "The expected value was unavailable.",
        }
    )

    assert issues == [
        {
            "category": "Agent",
            "subcategory": "Missing value",
            "finding": "The expected value was unavailable.",
        },
        {
            "category": "Data",
            "subcategory": "Missing value",
            "finding": "The expected value was unavailable.",
        },
    ]
    assert (
        analysis_root_cause_issues(
            {
                "root_cause_issues": [],
                "root_cause": "Legacy must not override an explicit empty list",
            }
        )
        == []
    )


def test_parser_accepts_issue_objects_and_keeps_legacy_projections() -> None:
    response = json.dumps(
        {
            "root_cause_issues": [
                {
                    "category": "Agent",
                    "subcategory": "Retrieval failure",
                    "finding": "The value search omitted status A.",
                },
                {
                    "category": "Agent",
                    "subcategory": "Predicate construction",
                    "finding": "The filter then used OR instead of AND.",
                },
            ],
            "root_cause_reason": "Both failures occurred in agent behavior.",
            "confidence": 0.9,
        }
    )

    result = parse_llm_response(
        response,
        "item-1",
        allowed_categories=["Agent"],
        known_taxonomy={
            "Agent": {
                "description": "The evaluated agent caused the failure.",
                "when_to_use": "Use when agent behavior directly caused the result.",
            }
        },
    )

    assert result.error is None
    assert len(result.root_cause_issues or []) == 2
    assert result.root_causes == ["Agent"]
    assert result.root_cause == "Agent"
    assert result.root_cause_detail == "Retrieval failure"
    assert result.root_cause_note == "The value search omitted status A."
    assert result.root_cause_issues[1]["finding"] == (
        "The filter then used OR instead of AND."
    )


def test_parser_limits_issue_records_even_when_categories_repeat() -> None:
    response = json.dumps(
        {
            "root_cause_issues": [
                {
                    "category": "Agent",
                    "subcategory": f"Failure {index}",
                    "finding": f"Independent finding {index}.",
                }
                for index in range(3)
            ],
            "confidence": 0.8,
        }
    )

    result = parse_llm_response(
        response,
        "item-1",
        max_categories=2,
    )

    assert result.error == "too_many_root_causes"
    assert result.root_cause_issues == []
    assert "3 root-cause issues" in result.root_cause_note


def test_explicit_empty_issues_clear_stale_legacy_projections() -> None:
    result = AnalysisResult(
        item_id="item-1",
        root_cause="Stale category",
        root_cause_issues=[],
        root_cause_detail="Stale subcategory",
        root_cause_reason="Stale rationale",
        root_cause_note="Stale finding",
        confidence=0.7,
    )

    assert result.root_cause_issues == []
    assert result.root_cause == ""
    assert result.root_causes == []
    assert result.root_cause_detail == ""
    assert result.root_cause_reason == ""
    assert result.root_cause_note == ""


def test_error_without_explicit_issues_keeps_diagnostic_note() -> None:
    result = AnalysisResult(
        item_id="item-1",
        root_cause="",
        root_cause_note="The diagnosis was discarded.",
        confidence=0.0,
        error="too_many_root_causes",
    )

    assert result.root_cause_issues == []
    assert result.root_cause_note == "The diagnosis was discarded."


def test_prompt_renders_subcategory_definitions_and_issue_schema() -> None:
    item = RunItem(
        run_id="run-1",
        item_id="item-1",
        index=0,
        input={"question": "Find active records"},
        expected={"count": 3},
        output={"count": 1},
        item_metadata={},
    )

    prompt = build_analysis_prompt(
        item,
        {},
        [],
        config={
            "root_cause_categories": ["Agent"],
            "category_taxonomy": {
                "Agent": {
                    "description": "The evaluated agent caused the failure.",
                    "when_to_use": "Use when agent behavior directly caused the result.",
                }
            },
            "subcategory_taxonomy": {
                "Agent": {
                    "Retrieval failure": {
                        "description": "Retrieval omits information needed downstream.",
                        "when_to_use": "Use when the source had the missing information.",
                    }
                }
            },
        },
    )[0]["content"]

    assert '"root_cause_issues": [' in prompt
    assert '"subcategory": "<reusable failure mechanism, 2-6 words>"' in prompt
    assert "    - Retrieval failure" in prompt
    assert "Description: Retrieval omits information needed downstream." in prompt
    assert "Use when: Use when the source had the missing information." in prompt


def test_prompt_does_not_leak_previous_structured_diagnosis_as_metadata() -> None:
    item = RunItem(
        run_id="run-1",
        item_id="item-1",
        index=0,
        input={"question": "Find active records"},
        expected={"count": 3},
        output={"count": 1},
        item_metadata={
            "locale": "ar-SA",
            "root_cause_issues": [
                {
                    "category": "Old category",
                    "subcategory": "Old subcategory",
                    "finding": "Old finding must not bias reanalysis.",
                }
            ],
            "root_causes": ["Old category"],
            "category_taxonomy": {
                "Old category": {
                    "description": "Old description",
                    "when_to_use": "Old guidance",
                }
            },
        },
    )

    prompt = build_analysis_prompt(item, {}, [])[0]["content"]

    assert '"locale": "ar-SA"' in prompt
    assert "Old category" not in prompt
    assert "Old finding must not bias reanalysis." not in prompt


def test_rule_writer_payload_includes_all_approved_issues() -> None:
    approved_issues = [
        {
            "category": "Agent",
            "subcategory": "Retrieval failure",
            "finding": "The search omitted a valid value.",
        },
        {
            "category": "Data",
            "subcategory": "Ambiguous reference",
            "finding": "The expected record conflicts with the source.",
        },
    ]
    correction = SimpleNamespace(
        input_snapshot={},
        expected_snapshot={},
        output_snapshot={},
        ai_root_cause="Agent",
        ai_root_causes=["Agent"],
        ai_root_cause_issues=None,
        ai_root_cause_detail="Retrieval failure",
        ai_root_cause_note="The search omitted a valid value.",
        human_root_cause="Agent",
        human_root_causes=["Agent", "Data"],
        human_root_cause_issues=approved_issues,
        human_root_cause_detail="Retrieval failure",
        human_root_cause_note="The search omitted a valid value.",
    )

    payload = _rule_writer_correction_payload(correction)

    assert payload["approved_root_cause_issues"] == approved_issues
    assert payload["previous_ai_root_cause_issues"] == [
        {
            "category": "Agent",
            "subcategory": "Retrieval failure",
            "finding": "The search omitted a valid value.",
        }
    ]


@pytest.mark.asyncio
async def test_aggregation_maps_each_issue_without_moving_or_merging_it() -> None:
    result = AnalysisResult(
        item_id="item-1",
        root_cause="",
        root_cause_note="",
        confidence=0.9,
        root_cause_issues=[
            {
                "category": "dataset issue",
                "subcategory": "Missing values",
                "finding": "The dataset omitted the expected row.",
            },
            {
                "category": "Context Missing",
                "subcategory": "missing value",
                "finding": "The retrieval response omitted a required status.",
            },
        ],
    )

    counts = await aggregate_analysis_categories(
        object(),
        "unused-model",
        [result],
        known_categories=["Dataset Issue", "Context Missing"],
        known_details=["Missing value"],
    )

    assert counts == {"Dataset Issue": 1, "Context Missing": 1}
    assert result.root_cause_issues == [
        {
            "category": "Dataset Issue",
            "subcategory": "Missing value",
            "finding": "The dataset omitted the expected row.",
        },
        {
            "category": "Context Missing",
            "subcategory": "Missing value",
            "finding": "The retrieval response omitted a required status.",
        },
    ]
    assert result.root_causes == ["Dataset Issue", "Context Missing"]
    assert result.root_cause_detail == "Missing value"
    assert result.root_cause_note == "The dataset omitted the expected row."
