from __future__ import annotations

import json

from qym_platform.services.llm_analyzer import (
    ROOT_CAUSE_CATEGORIES,
    _extract_json_from_reasoning,
    parse_llm_response,
)
from qym_platform.services.root_cause_categories import (
    DEFAULT_MAX_ROOT_CAUSE_CATEGORIES,
    DEFAULT_ROOT_CAUSE_TAXONOMY,
    analysis_root_causes,
)
from qym_platform.services.root_cause_changes import (
    apply_human_patch,
    build_ai_state,
    build_item_metadata,
)


def test_analyzer_rejects_responses_over_the_default_category_cap() -> None:
    response = json.dumps(
        {
            "root_causes": [
                "Reasoning Error",
                "Hallucination",
                "Incomplete Answer",
                "Wrong Format",
            ],
            "root_cause_detail": "unsupported answer",
            "root_cause_note": "The response both invented a fact and used invalid reasoning.",
            "confidence": 0.9,
        }
    )

    result = parse_llm_response(
        response,
        "item-1",
        allowed_categories=ROOT_CAUSE_CATEGORIES,
        known_taxonomy=DEFAULT_ROOT_CAUSE_TAXONOMY,
    )

    assert result.error == "too_many_root_causes"
    assert result.root_causes == []
    assert result.root_cause == ""
    assert result.confidence == 0.0


def test_analyzer_honors_an_explicit_higher_category_limit() -> None:
    response = json.dumps(
        {
            "root_causes": [
                "Reasoning Error",
                "Hallucination",
                "Incomplete Answer",
                "Wrong Format",
            ],
            "root_cause_detail": "unsupported answer",
            "root_cause_note": "The response has several independent failures.",
            "confidence": 0.9,
        }
    )

    result = parse_llm_response(
        response,
        "item-1",
        allowed_categories=ROOT_CAUSE_CATEGORIES,
        max_categories=4,
        known_taxonomy=DEFAULT_ROOT_CAUSE_TAXONOMY,
    )

    assert result.error is None
    assert len(result.root_causes) == 4
    assert len(result.root_causes) > DEFAULT_MAX_ROOT_CAUSE_CATEGORIES


def test_reasoning_path_cannot_bypass_the_category_cap() -> None:
    response = json.dumps(
        {
            "root_causes": [
                "Reasoning Error",
                "Hallucination",
                "Incomplete Answer",
                "Wrong Format",
            ],
            "root_cause_note": "The response has several independent failures.",
        }
    )
    result = _extract_json_from_reasoning(
        "The model reasoned first, then returned: " + response,
        "item-1",
        allowed_categories=ROOT_CAUSE_CATEGORIES,
        known_taxonomy=DEFAULT_ROOT_CAUSE_TAXONOMY,
    )

    assert result is not None
    assert result.error == "too_many_root_causes"


def test_human_and_metadata_paths_store_unlimited_plural_categories() -> None:
    before = {"root_cause": "Reasoning Error", "root_causes": ["Reasoning Error"]}
    after = apply_human_patch(
        before,
        {
            "root_causes": [
                "Reasoning Error",
                "Hallucination",
                "Incomplete Answer",
                "Wrong Format",
            ]
        },
    )
    assert after["root_cause"] == "Reasoning Error"
    assert after["root_causes"] == [
        "Reasoning Error",
        "Hallucination",
        "Incomplete Answer",
        "Wrong Format",
    ]

    state = build_ai_state(
        root_cause="Reasoning Error",
        root_causes=after["root_causes"],
        root_cause_detail="unsupported answer",
    )
    metadata = build_item_metadata({"custom": "value"}, state)
    assert analysis_root_causes(metadata) == after["root_causes"]
    assert metadata["root_cause"] == "Reasoning Error"
    assert metadata["custom"] == "value"


def test_legacy_plural_alias_is_read_as_the_canonical_category_list() -> None:
    assert analysis_root_causes(
        {"root_cause_categories": ["Reasoning Error", "Hallucination"]}
    ) == ["Reasoning Error", "Hallucination"]
