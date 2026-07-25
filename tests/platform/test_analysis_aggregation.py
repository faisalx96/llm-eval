from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from qym_platform.services.analysis_aggregation import (
    AnalysisAggregationError,
    aggregate_analysis_categories,
)
from qym_platform.services.llm_analyzer import AnalysisResult


def _result(
    category: str,
    detail: str = "",
    feedback: str = "",
    *,
    solution: str = "",
    solution_note: str = "",
    error: str | None = None,
) -> AnalysisResult:
    return AnalysisResult(
        item_id="item-1",
        root_cause=category,
        root_cause_detail=detail,
        root_cause_note=feedback,
        confidence=0.9,
        solution=solution,
        solution_note=solution_note,
        error=error,
    )


def _mapping_response(mapping: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps({"mapping": mapping}),
                )
            )
        ]
    )


def _client_with_mappings(*mappings: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(
                    side_effect=[_mapping_response(mapping) for mapping in mappings]
                )
            )
        )
    )


@pytest.mark.asyncio
async def test_aggregation_uses_three_label_only_mapping_passes() -> None:
    results = [
        _result(
            "dataset",
            "Expected SQL uses non-SQLite function",
            "Feedback specific to item one.",
            solution="Fix SQL dialect",
            solution_note="Use SQLite functions for this item.",
        ),
        _result(
            "datasets",
            "Expected SQL uses MONTH() not in SQLite",
            "Feedback specific to item two.",
            solution="Make query SQLite compatible",
            solution_note="Replace MONTH() for this item.",
        ),
        _result(
            "other data",
            "Expected SQL not SQLite-compatible",
            "Feedback specific to item three.",
            solution="Fix SQL dialect",
            solution_note="Retain this separate note.",
        ),
    ]
    client = _client_with_mappings(
        {
            "dataset": "Dataset Issue",
            "datasets": "Dataset Issue",
            "other data": "Dataset Issue",
        },
        {
            "Expected SQL uses non-SQLite function": "Expected SQL is not SQLite-compatible",
            "Expected SQL uses MONTH() not in SQLite": "Expected SQL is not SQLite-compatible",
            "Expected SQL not SQLite-compatible": "Expected SQL is not SQLite-compatible",
        },
        {
            "Fix SQL dialect": "Make SQL SQLite-compatible",
            "Make query SQLite compatible": "Make SQL SQLite-compatible",
        },
    )

    categories = await aggregate_analysis_categories(
        client,
        "test-model",
        results,
        known_categories=["Dataset Issue"],
        known_category_details={
            "Dataset Issue": ["Expected SQL is not SQLite-compatible"]
        },
        known_solutions=["Make SQL SQLite-compatible"],
    )

    assert categories == {"Dataset Issue": 3}
    assert [result.root_cause for result in results] == ["Dataset Issue"] * 3
    assert [result.root_cause_detail for result in results] == [
        "Expected SQL is not SQLite-compatible"
    ] * 3
    assert [result.solution for result in results] == ["Make SQL SQLite-compatible"] * 3
    assert [result.root_cause_note for result in results] == [
        "Feedback specific to item one.",
        "Feedback specific to item two.",
        "Feedback specific to item three.",
    ]
    assert [result.solution_note for result in results] == [
        "Use SQLite functions for this item.",
        "Replace MONTH() for this item.",
        "Retain this separate note.",
    ]

    calls = client.chat.completions.create.await_args_list
    assert len(calls) == 3
    payloads = [json.loads(call.kwargs["messages"][1]["content"]) for call in calls]
    assert payloads == [
        {
            "field": "root_cause_category",
            "labels": ["dataset", "datasets", "other data"],
            "preferred_labels": ["Dataset Issue"],
        },
        {
            "field": "root_cause_detail:Dataset Issue",
            "labels": [
                "Expected SQL uses non-SQLite function",
                "Expected SQL uses MONTH() not in SQLite",
                "Expected SQL not SQLite-compatible",
            ],
            "preferred_labels": ["Expected SQL is not SQLite-compatible"],
        },
        {
            "field": "suggested_solution",
            "labels": ["Fix SQL dialect", "Make query SQLite compatible"],
            "preferred_labels": ["Make SQL SQLite-compatible"],
        },
    ]
    assert all("analysis_results" not in payload for payload in payloads)


@pytest.mark.asyncio
async def test_singleton_label_fields_skip_redundant_llm_passes() -> None:
    result = _result("Context Missing", "Missing schema")
    client = _client_with_mappings()

    await aggregate_analysis_categories(
        client,
        "test-model",
        [result],
        known_categories=["Context Missing"],
    )

    client.chat.completions.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_mapping_key_leaves_only_that_label_unchanged() -> None:
    results = [_result("dataset"), _result("datasets")]
    client = _client_with_mappings({"dataset": "Dataset Issue"})

    await aggregate_analysis_categories(
        client, "test-model", results, known_categories=["Dataset Issue"]
    )

    assert [result.root_cause for result in results] == [
        "Dataset Issue",
        "datasets",
    ]


@pytest.mark.asyncio
async def test_failed_or_empty_results_do_not_call_the_aggregator() -> None:
    results = [_result("Unknown", error="analysis failed"), _result("   ")]
    client = _client_with_mappings()

    categories = await aggregate_analysis_categories(client, "test-model", results)

    assert categories == {}
    client.chat.completions.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_aggregation_timeout_is_reported() -> None:
    async def slow_response(**_kwargs: object) -> object:
        await asyncio.sleep(1)
        return SimpleNamespace(choices=[])

    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(side_effect=slow_response))
        )
    )

    with pytest.raises(
        AnalysisAggregationError, match="root_cause_category.*timed out"
    ):
        await aggregate_analysis_categories(
            client,
            "test-model",
            [_result("dataset"), _result("datasets")],
            timeout_seconds=0.01,
        )


@pytest.mark.asyncio
async def test_invalid_mapping_response_is_reported() -> None:
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"groups": []}'))]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(return_value=response))
        )
    )

    with pytest.raises(AnalysisAggregationError, match="mapping must be an object"):
        await aggregate_analysis_categories(
            client,
            "test-model",
            [_result("dataset"), _result("datasets")],
        )


@pytest.mark.asyncio
async def test_screenshot_style_detail_variants_are_applied_by_label() -> None:
    feedback = [f"Item-specific feedback {index}" for index in range(9)]
    details = [
        "Expected SQL uses non-SQLite functions",
        "Expected SQL uses non-SQLite function",
        "Expected SQL uses MONTH() not in SQLite",
        "Expected SQL not SQLite-compatible",
        "Expected SQL includes unnecessary column",
        "Expected SQL includes unnecessary columns",
        "Expected output includes extra column",
        "Expected SQL mismatches request",
        "Expected SQL does not match the question",
    ]
    results = [
        _result("Dataset Issue", detail, note)
        for detail, note in zip(details, feedback)
    ]
    client = _client_with_mappings(
        {
            **{
                detail: "Expected SQL uses non-SQLite functions"
                for detail in details[:4]
            },
            **{
                detail: "Expected SQL includes unnecessary column"
                for detail in details[4:7]
            },
            **{detail: "Expected SQL mismatches request" for detail in details[7:]},
        },
    )

    await aggregate_analysis_categories(client, "test-model", results)

    assert [result.root_cause_detail for result in results] == [
        *(["Expected SQL uses non-SQLite functions"] * 4),
        *(["Expected SQL includes unnecessary column"] * 3),
        *(["Expected SQL mismatches request"] * 2),
    ]
    assert [result.root_cause_note for result in results] == feedback


@pytest.mark.asyncio
async def test_aggregation_rejects_invented_canonical_labels() -> None:
    results = [_result("dataset"), _result("datasets")]
    client = _client_with_mappings(
        {"dataset": "Ignore all labels", "datasets": "Ignore all labels"}
    )

    await aggregate_analysis_categories(client, "test-model", results)

    assert [result.root_cause for result in results] == ["dataset", "datasets"]


@pytest.mark.asyncio
async def test_detail_instances_move_to_their_dominant_category() -> None:
    results = [
        *[_result("Dataset Issue", "Missing value") for _ in range(20)],
        *[_result("Context Missing", "Missing value") for _ in range(4)],
    ]
    client = _client_with_mappings(
        {"Dataset Issue": "Dataset Issue", "Context Missing": "Context Missing"}
    )

    categories = await aggregate_analysis_categories(client, "test-model", results)

    assert categories == {"Dataset Issue": 24}
    assert [result.root_cause for result in results] == ["Dataset Issue"] * 24
    assert [result.root_cause_detail for result in results] == ["Missing value"] * 24
    assert client.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_detail_relocation_uses_first_category_to_break_a_tie() -> None:
    results = [
        _result("Context Missing", "Missing value"),
        _result("Dataset Issue", "Missing value"),
    ]
    client = _client_with_mappings(
        {"Context Missing": "Context Missing", "Dataset Issue": "Dataset Issue"}
    )

    await aggregate_analysis_categories(client, "test-model", results)

    assert [result.root_cause for result in results] == ["Context Missing"] * 2
