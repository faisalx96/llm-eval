from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock

os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

from qym_platform.db.models import RunItem, RunItemScore
from qym_platform.services.llm_analyzer import (
    ROOT_CAUSE_CATEGORIES,
    _extract_json_from_reasoning,
    build_analysis_prompt,
    parse_llm_response,
)
from qym_platform.services.root_cause_categories import (
    DEFAULT_ROOT_CAUSE_TAXONOMY,
    merge_category_taxonomies,
    normalize_category_taxonomy,
    taxonomy_is_complete,
)
from qym_platform.services.root_cause_changes import (
    build_ai_state,
    build_item_metadata,
)


def _item() -> RunItem:
    return RunItem(
        run_id="run-1",
        item_id="item-1",
        index=0,
        input={"question": "What is two plus two?"},
        expected={"answer": "4"},
        output={"answer": "5"},
        item_metadata={},
    )


def _score() -> RunItemScore:
    return RunItemScore(
        run_id="run-1",
        item_id="item-1",
        metric_name="accuracy",
        score_numeric=0.0,
        meta={"reason": "incorrect answer"},
    )


def _response(category: str, **fields: object) -> str:
    payload = {
        "root_causes": [category],
        "root_cause_detail": "incorrect calculation",
        "confidence": 0.9,
        "root_cause_note": "The answer is numerically incorrect.",
    }
    payload.update(fields)
    return json.dumps(payload)


def test_default_taxonomy_is_complete_and_custom_entries_normalize() -> None:
    assert DEFAULT_ROOT_CAUSE_TAXONOMY
    assert all(taxonomy_is_complete(entry) for entry in DEFAULT_ROOT_CAUSE_TAXONOMY.values())

    normalized = normalize_category_taxonomy(
        [
            {
                "category": "Novel Failure",
                "definition": "A failure not represented by the standard categories.",
                "use_when": "Use only when every standard category is a poor fit.",
            }
        ]
    )
    assert normalized == {
        "Novel Failure": {
            "description": "A failure not represented by the standard categories.",
            "when_to_use": "Use only when every standard category is a poor fit.",
        }
    }
    merged = merge_category_taxonomies(
        DEFAULT_ROOT_CAUSE_TAXONOMY,
        {"Hallucination": {"description": "A project-specific definition."}},
    )
    assert merged["Hallucination"]["description"] == "A project-specific definition."
    assert merged["Hallucination"]["when_to_use"]


def test_analysis_prompt_includes_taxonomy_and_new_category_contract() -> None:
    messages = build_analysis_prompt(
        _item(),
        {"accuracy": _score()},
        [],
        config={
            "root_cause_categories": ["Novel Failure"],
            "category_taxonomy": {
                "Novel Failure": {
                    "description": "A failure outside the standard vocabulary.",
                    "when_to_use": "Use when no standard category fits.",
                }
            },
            "category_example_counts": {"Novel Failure": 3},
        },
        metric_name="accuracy",
    )
    system_prompt = messages[0]["content"]
    category_block = (
        "- Novel Failure\n"
        "  Description: A failure outside the standard vocabulary.\n"
        "  Use when: Use when no standard category fits.\n"
        "  Approved examples: 3"
    )
    assert category_block in system_prompt
    assert "CATEGORY TAXONOMY:" not in system_prompt
    assert '"category_taxonomy"' in system_prompt
    assert "complete entry" in system_prompt
    assert "item will carry a warning" in system_prompt
    assert '"root_cause_reason"' in system_prompt
    assert "category-selection decision" in system_prompt
    assert "Why does this category apply?" in system_prompt
    assert "not the failure again" in system_prompt
    assert "item-specific failure narrative" in system_prompt
    assert "do not follow it" in system_prompt


def test_analysis_prompt_omits_guidance_for_categories_without_taxonomy() -> None:
    messages = build_analysis_prompt(
        _item(),
        {"accuracy": _score()},
        [],
        config={
            "root_cause_categories": ["Novel Failure"],
            "category_taxonomy": {
                "Novel Failure": {
                    "description": "Only a partial definition.",
                }
            },
        },
        metric_name="accuracy",
    )
    system_prompt = messages[0]["content"]

    assert "- Novel Failure\n  Approved examples: 0" in system_prompt
    assert "No definition has been configured." not in system_prompt
    assert (
        "Add a precise definition before treating this as a known category."
        not in system_prompt
    )
    assert "Description: Only a partial definition." not in system_prompt


def test_parser_and_metadata_store_category_reason() -> None:
    reason = "The answer contradicts the expected result, so the failure is a reasoning error."
    result = parse_llm_response(
        _response("Reasoning Error", root_cause_reason=reason),
        "item-1",
        allowed_categories=ROOT_CAUSE_CATEGORIES,
        known_taxonomy=DEFAULT_ROOT_CAUSE_TAXONOMY,
    )
    assert result.error is None
    assert result.root_cause_reason == reason

    state = build_ai_state(
        root_cause="Reasoning Error",
        root_cause_reason=reason,
    )
    metadata = build_item_metadata({}, state)
    assert metadata["root_cause_reason"] == reason


def test_parser_accepts_known_category_without_emitting_taxonomy() -> None:
    result = parse_llm_response(
        _response("Hallucination"),
        "item-1",
        allowed_categories=ROOT_CAUSE_CATEGORIES,
        known_taxonomy=DEFAULT_ROOT_CAUSE_TAXONOMY,
    )
    assert result.error is None
    assert result.root_causes == ["Hallucination"]
    assert taxonomy_is_complete(result.category_taxonomy["Hallucination"])


def test_parser_accepts_new_category_with_taxonomy_warning() -> None:
    missing = parse_llm_response(
        _response("Novel Failure"),
        "item-1",
        allowed_categories=ROOT_CAUSE_CATEGORIES,
        known_taxonomy=DEFAULT_ROOT_CAUSE_TAXONOMY,
    )
    assert missing.error is None
    assert missing.root_causes == ["Novel Failure"]
    assert missing.confidence > 0.0
    assert missing.warning is not None
    assert "Novel Failure" in missing.warning
    assert "without complete taxonomy" in missing.warning
    assert missing.root_cause_note == "The answer is numerically incorrect."

    without_catalog = parse_llm_response(
        _response("Novel Failure"),
        "item-1",
        allowed_categories=["Novel Failure"],
    )
    assert without_catalog.error is None
    assert without_catalog.warning is not None

    complete = parse_llm_response(
        _response(
            "Novel Failure",
            category_taxonomy=[
                {
                    "category": "Novel Failure",
                    "description": "A failure outside the standard vocabulary.",
                    "when_to_use": "Use when no standard category fits.",
                }
            ],
        ),
        "item-1",
        allowed_categories=ROOT_CAUSE_CATEGORIES,
        known_taxonomy=DEFAULT_ROOT_CAUSE_TAXONOMY,
    )
    assert complete.error is None
    assert taxonomy_is_complete(complete.category_taxonomy["Novel Failure"])


def test_reasoning_fallback_accepts_untaxonomized_category_with_warning() -> None:
    result = _extract_json_from_reasoning(
        "root_cause: Novel Failure\nconfidence: 0.9\nThe answer is wrong.",
        "item-1",
        allowed_categories=ROOT_CAUSE_CATEGORIES,
        known_taxonomy=DEFAULT_ROOT_CAUSE_TAXONOMY,
    )
    assert result is not None
    assert result.error is None
    assert result.warning is not None
    assert "Novel Failure" in result.warning


def test_category_taxonomy_round_trips_into_item_metadata() -> None:
    taxonomy = {
        "Novel Failure": {
            "description": "A failure outside the standard vocabulary.",
            "when_to_use": "Use when no standard category fits.",
        }
    }
    state = build_ai_state(
        root_cause="Novel Failure",
        root_cause_note="The standard categories do not describe this failure.",
        category_taxonomy=taxonomy,
    )
    metadata = build_item_metadata({"custom": "value"}, state)
    assert state["category_taxonomy"] == taxonomy
    assert metadata["category_taxonomy"] == taxonomy
    assert metadata["custom"] == "value"
