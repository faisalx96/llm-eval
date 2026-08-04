from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from qym_platform.services.analysis_aggregation import (
    AGGREGATION_SYSTEM_PROMPT,
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


def _response(payload: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(payload),
                )
            )
        ]
    )


def _client_with_label_mappings(
    *,
    categories: dict[str, str | None] | None = None,
    details: dict[str, str | None] | None = None,
    solutions: dict[str, str | None] | None = None,
    delay: float = 0,
) -> SimpleNamespace:
    configured = {
        "category": categories or {},
        "detail": details or {},
        "solution": solutions or {},
    }
    plural = {
        "category": "categories",
        "detail": "details",
        "solution": "solutions",
    }

    async def create(**kwargs: object) -> SimpleNamespace:
        if delay:
            await asyncio.sleep(delay)
        messages = kwargs["messages"]
        assert isinstance(messages, list)
        prompt = json.loads(messages[1]["content"])
        response_payload: dict[str, object] = {}
        for field_name in prompt["requested_fields"]:
            entries = prompt[plural[field_name]]
            id_by_label = {entry["label"]: entry["id"] for entry in entries}
            source_label_by_id = {
                entry["id"]: entry["label"]
                for entry in entries
                if entry["count"] > 0
            }
            members_by_target: dict[str, list[str]] = {}
            for entry in entries:
                if entry["count"] <= 0:
                    continue
                target_label = configured[field_name].get(
                    entry["label"], entry["label"]
                )
                if target_label is None:
                    continue
                members_by_target.setdefault(target_label, []).append(entry["id"])
            clusters: list[dict[str, object]] = []
            for target_label, member_ids in members_by_target.items():
                is_identity_singleton = (
                    len(member_ids) == 1
                    and source_label_by_id[member_ids[0]] == target_label
                )
                if is_identity_singleton:
                    continue
                cluster: dict[str, object] = {"member_ids": member_ids}
                target_id = id_by_label.get(target_label)
                if target_id:
                    cluster["canonical_id"] = target_id
                else:
                    cluster["canonical_label"] = target_label
                clusters.append(cluster)
            response_payload[f"{field_name}_clusters"] = clusters
        return _response(response_payload)

    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(side_effect=create))
        )
    )


@pytest.mark.asyncio
async def test_aggregation_uses_one_joint_label_only_pass() -> None:
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
    client = _client_with_label_mappings(
        categories={
            "dataset": "Dataset Issue",
            "other data": "Dataset Issue",
        },
        details={
            "Expected SQL uses non-SQLite function": (
                "Expected SQL is not SQLite-compatible"
            ),
            "Expected SQL uses MONTH() not in SQLite": (
                "Expected SQL is not SQLite-compatible"
            ),
            "Expected SQL not SQLite-compatible": (
                "Expected SQL is not SQLite-compatible"
            ),
        },
        solutions={
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

    client.chat.completions.create.assert_awaited_once()
    call = client.chat.completions.create.await_args
    payload = json.loads(call.kwargs["messages"][1]["content"])
    assert payload["requested_fields"] == ["category", "detail", "solution"]
    assert [
        (entry["label"], entry["count"], entry["preferred"])
        for entry in payload["categories"]
    ] == [
        ("dataset", 2, False),
        ("other data", 1, False),
        ("Dataset Issue", 0, True),
    ]
    assert "analysis_results" not in payload
    assert "Feedback specific" not in call.kwargs["messages"][1]["content"]
    assert "item-specific wording" in AGGREGATION_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_deterministic_variants_do_not_need_an_llm_pass() -> None:
    results = [
        _result("Dataset Issue", "expected SQL uses non-SQLite function"),
        _result("dataset issue", "Expected SQL uses non-SQLite functions"),
        _result("DATASET ISSUE", " expected  SQL uses non-SQLite function "),
    ]
    client = _client_with_label_mappings()

    categories = await aggregate_analysis_categories(
        client,
        "test-model",
        results,
        known_categories=["Dataset Issue"],
        known_category_details={
            "Dataset Issue": ["Expected SQL uses non-SQLite functions"]
        },
    )

    assert categories == {"Dataset Issue": 3}
    assert [result.root_cause for result in results] == ["Dataset Issue"] * 3
    assert [result.root_cause_detail for result in results] == [
        "Expected SQL uses non-SQLite functions"
    ] * 3
    client.chat.completions.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_singleton_label_fields_skip_redundant_llm_passes() -> None:
    result = _result("Context Missing", "Missing schema")
    client = _client_with_label_mappings()

    await aggregate_analysis_categories(
        client,
        "test-model",
        [result],
        known_categories=["Context Missing"],
    )

    client.chat.completions.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_mapping_id_keeps_that_semantic_group_unchanged() -> None:
    results = [_result("dataset"), _result("other data")]
    client = _client_with_label_mappings(
        categories={
            "dataset": "Dataset Issue",
            "other data": None,
        }
    )

    await aggregate_analysis_categories(
        client, "test-model", results, known_categories=["Dataset Issue"]
    )

    assert [result.root_cause for result in results] == [
        "Dataset Issue",
        "other data",
    ]


@pytest.mark.asyncio
async def test_failed_or_empty_results_do_not_call_the_aggregator() -> None:
    results = [_result("Unknown", error="analysis failed"), _result("   ")]
    client = _client_with_label_mappings()

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
            [_result("dataset"), _result("other data")],
            known_categories=["Dataset Issue"],
            timeout_seconds=0.01,
        )


@pytest.mark.asyncio
async def test_invalid_joint_mapping_response_is_reported() -> None:
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"groups": []}'))]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(return_value=response))
        )
    )

    with pytest.raises(
        AnalysisAggregationError, match="requested cluster array"
    ):
        await aggregate_analysis_categories(
            client,
            "test-model",
            [_result("dataset"), _result("other data")],
            known_categories=["Dataset Issue"],
        )


@pytest.mark.asyncio
async def test_omitted_empty_cluster_field_does_not_discard_useful_merges() -> None:
    results = [
        _result("dataset", "Missing Customers table"),
        _result("other data", "Missing Orders table"),
    ]
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(
                    return_value=_response(
                        {
                            "detail_clusters": [
                                {
                                    "canonical_label": "Missing schema table",
                                    "member_ids": ["d0", "d1"],
                                }
                            ]
                        }
                    )
                )
            )
        )
    )

    await aggregate_analysis_categories(client, "test-model", results)

    assert [result.root_cause_detail for result in results] == [
        "Missing schema table"
    ] * 2


@pytest.mark.asyncio
async def test_screenshot_style_semantic_detail_families_are_consolidated() -> None:
    details = [
        "Expected SQL uses non-SQLite functions",
        "Expected SQL uses non-SQLite function",
        "Expected SQL uses MONTH() not in SQLite",
        "Expected SQL not SQLite-compatible",
        "expected SQL uses MySQL syntax, not SQLite",
        "expected SQL uses YEAR function",
        "expected SQL uses CURDATE",
        "Expected SQL includes unnecessary column",
        "Expected SQL includes unnecessary columns",
        "Expected output includes extra column",
        "expected SQL includes unrequested column",
        "expected SQL over-selects columns",
        "Expected SQL mismatches request",
        "expected SQL misinterprets request",
        "expected SQL misinterprets question",
        "Expected SQL references missing column",
        "expected SQL missing column",
        "expected SQL uses missing column",
    ]
    feedback = [f"Item-specific feedback {index}" for index in range(len(details))]
    results = [
        _result("Dataset Issue", detail, note)
        for detail, note in zip(details, feedback)
    ]
    client = _client_with_label_mappings(
        details={
            "Expected SQL uses non-SQLite functions": (
                "Unsupported SQLite function"
            ),
            "Expected SQL uses MONTH() not in SQLite": (
                "Unsupported SQLite function"
            ),
            "Expected SQL not SQLite-compatible": (
                "Unsupported SQLite function"
            ),
            "expected SQL uses MySQL syntax, not SQLite": (
                "Unsupported SQLite function"
            ),
            "expected SQL uses YEAR function": "Unsupported SQLite function",
            "expected SQL uses CURDATE": "Unsupported SQLite function",
            "Expected SQL includes unnecessary column": (
                "Extra output columns"
            ),
            "Expected output includes extra column": (
                "Extra output columns"
            ),
            "expected SQL includes unrequested column": (
                "Extra output columns"
            ),
            "expected SQL over-selects columns": "Extra output columns",
            "Expected SQL mismatches request": "Request interpretation mismatch",
            "expected SQL misinterprets request": "Request interpretation mismatch",
            "expected SQL misinterprets question": "Request interpretation mismatch",
            "Expected SQL references missing column": "Missing required column",
            "expected SQL missing column": "Missing required column",
            "expected SQL uses missing column": "Missing required column",
        }
    )

    await aggregate_analysis_categories(
        client,
        "test-model",
        results,
        known_categories=["Dataset Issue"],
    )

    assert [result.root_cause_detail for result in results] == [
        *(["Unsupported SQLite function"] * 7),
        *(["Extra output columns"] * 5),
        *(["Request interpretation mismatch"] * 3),
        *(["Missing required column"] * 3),
    ]
    assert [result.root_cause_note for result in results] == feedback
    client.chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_dashboard_scale_one_offs_collapse_into_recurring_mechanisms() -> None:
    families = {
        "Unsupported SQLite dialect": [
            ("Tool Use Error", "Non-SQLite DATE_SUB/GETDATE"),
            ("Tool Use Error", "SQLite function MONTH unsupported"),
            ("Tool Use Error", "Unsupported CURDATE() in SQLite"),
            ("Tool Use Error", "YEAR function unsupported"),
            ("Tool Use Error", "Unsupported YEAR function"),
            ("Wrong Format", "SQLite unsupported function"),
            ("Wrong Format", "SQLite NOW() date function"),
            ("Wrong Format", "SQLite interval syntax unsupported"),
            ("Wrong Format", "DATEADD/GETDATE not SQLite"),
            ("Wrong Format", "DATE_TRUNC unsupported in SQLite"),
            ("Metric Limitation", "SQLite DATE_SUB syntax error"),
            ("Metric Limitation", "SQLite function dialect mismatch"),
            ("Metric Limitation", "Dialect mismatch in date SQL"),
            ("Metric Limitation", "SQLite function unsupported"),
            ("Metric Limitation", "SQLite function YEAR unsupported"),
            ("Context Missing", "SQLite MONTH function unsupported"),
            ("Reasoning Error", "SQL dialect/date function mismatch"),
        ],
        "Missing schema table": [
            ("Context Missing", "Missing districts table reference"),
            ("Context Missing", "Missing brands table"),
            ("Context Missing", "Table not created in SQLite"),
            ("Context Missing", "missing referenced country table"),
            ("Context Missing", "setup schema table missing"),
            ("Context Missing", "No table open_data"),
            ("Context Missing", "Missing qualified table name"),
        ],
        "Missing required column": [
            ("Context Missing", "Missing BookingDate column"),
            ("Context Missing", "Missing therapist_id column"),
            ("Context Missing", "Missing application_name column"),
            ("Context Missing", "Missing ocean column"),
            ("Context Missing", "Expected SQL references year"),
            ("Context Missing", "Expected query uses port_name"),
            ("Incomplete Answer", "Missing treatment_approach column"),
            ("Incomplete Answer", "Missing max depth column"),
        ],
        "Incorrect aggregation semantics": [
            ("Reasoning Error", "Used COUNT instead of SUM"),
            ("Reasoning Error", "Wrong aggregation semantics"),
            ("Reasoning Error", "Missing aggregation (SUM)"),
            ("Reasoning Error", "Wrong max aggregation semantics"),
            ("Reasoning Error", "Missing/extra aggregation logic"),
            ("Reasoning Error", "Wrong aggregation projection"),
            ("Reasoning Error", "Wrong severity averaging logic"),
            ("Aggregation failure", "Grouped SUM differs ordering"),
        ],
        "Incorrect grouping logic": [
            ("Reasoning Error", "Wrong grouping key"),
            ("Reasoning Error", "Missing join and grouping"),
            ("Reasoning Error", "Missing per-country grouping"),
            ("Reasoning Error", "Window vs GROUP BY"),
            ("Reasoning Error", "Grouping level mismatch"),
            ("Aggregation failure", "Missing grouping and filters"),
            ("Aggregation failure", "Missing GROUP BY country"),
            ("Aggregation failure", "Missing GROUP BY output"),
        ],
        "Projection mismatch": [
            ("Context Missing", "Missing expected column projection"),
            ("Context Missing", "Selected wrong columns"),
            ("Wrong Format", "SQL includes extra columns"),
            ("Wrong Format", "Projection mismatch vs expected"),
            ("Metric Limitation", "projection mismatch not penalized"),
            ("Metric Limitation", "Projection mismatch ignored"),
            ("Incomplete Answer", "Projection mismatch in SELECT"),
            ("Incomplete Answer", "Missing projected result columns"),
            ("Reasoning Error", "Swapped SELECT projection columns"),
        ],
        "Missing filter constraint": [
            ("Reasoning Error", "Missing rural-location intent"),
            ("Reasoning Error", "EU filter logic missing"),
            ("Reasoning Error", "Missing Texas/state predicate"),
            ("Reasoning Error", "Omitted Texas predicate"),
            ("Reasoning Error", "Missing date constraint"),
            ("Reasoning Error", "Added unintended source filter"),
            ("Reasoning Error", "Incorrect public-services filter"),
            ("Incomplete Answer", "Missing Q2 2022 filter"),
            ("Instruction Following", "Missing European filter"),
        ],
        "Request interpretation mismatch": [
            ("Reasoning Error", "Wrong semantics for query"),
            ("Reasoning Error", "Does not match requested output"),
            ("Metric Limitation", "output and expected mismatch"),
            ("Metric Limitation", "Topical mismatch by metric"),
            ("Metric Limitation", "execution mismatch by semantics"),
            ("Incomplete Answer", "Missing intent/matched output"),
            ("Instruction Following", "SQL-only intent mismatch"),
            ("Instruction Following", "Metric judges relevance mismatch"),
            ("Instruction Following", "Missing requested numeric result"),
        ],
        "Missing literal binding": [
            ("Wrong Format", "Missing bound literal values"),
            ("Instruction Following", "Missing literal values bind"),
        ],
        "Multiple SQL statements": [
            ("Wrong Format", "Multiple SQL statements"),
            ("Wrong Format", "Multiple statements returned"),
        ],
        "Invalid SQL syntax": [
            ("Wrong Format", "Invalid generated SQL syntax"),
            ("Wrong Format", "SQLite FETCH syntax error"),
            ("Wrong Format", "Invalid UPDATE syntax"),
        ],
        "Conflicting DDL statement": [
            ("Metric Limitation", "CREATE VIEW already exists"),
            ("Aggregation failure", "CREATE TABLE already exists"),
        ],
    }
    results = [
        _result(category, detail)
        for members in families.values()
        for category, detail in members
    ]
    client = _client_with_label_mappings(
        details={
            detail: canonical
            for canonical, members in families.items()
            for _category, detail in members
        }
    )

    await aggregate_analysis_categories(
        client,
        "test-model",
        results,
        known_categories=[
            "Reasoning Error",
            "Context Missing",
            "Wrong Format",
            "Metric Limitation",
            "Incomplete Answer",
            "Aggregation failure",
            "Tool Use Error",
            "Instruction Following",
        ],
    )

    assert {result.root_cause_detail for result in results} == set(families)
    assert len(results) == 84
    assert len(families) == 12
    for canonical, members in families.items():
        matching = [
            result for result in results if result.root_cause_detail == canonical
        ]
        assert len(matching) == len(members)
        assert len({result.root_cause for result in matching}) == 1
    client.chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_large_no_op_response_gets_one_quality_retry() -> None:
    results = [
        _result("Reasoning Error", f"Item-specific failure {index}")
        for index in range(20)
    ]
    calls = 0

    async def create(**kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        messages = kwargs["messages"]
        assert isinstance(messages, list)
        payload = json.loads(messages[1]["content"])
        detail_ids = [
            entry["id"]
            for entry in payload["details"]
            if entry["count"] > 0
        ]
        if calls == 1:
            return _response({"detail_clusters": []})
        assert payload["quality_review"]["first_pass_reduction"] == 0
        return _response(
            {
                "detail_clusters": [
                    {
                        "canonical_label": f"Recurring mechanism {group_index}",
                        "member_ids": detail_ids[start : start + 5],
                    }
                    for group_index, start in enumerate(range(0, 20, 5))
                ]
            }
        )

    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(side_effect=create))
        )
    )

    await aggregate_analysis_categories(
        client,
        "test-model",
        results,
        known_categories=["Reasoning Error"],
    )

    assert client.chat.completions.create.await_count == 2
    assert {result.root_cause_detail for result in results} == {
        "Recurring mechanism 0",
        "Recurring mechanism 1",
        "Recurring mechanism 2",
        "Recurring mechanism 3",
    }


@pytest.mark.asyncio
async def test_semantic_details_converge_across_existing_categories() -> None:
    results = [
        _result("Context Missing", "Missing table in context"),
        _result("Context Missing", "Missing table in context"),
        _result("Dataset Issue", "Missing table definition"),
    ]
    client = _client_with_label_mappings(
        details={
            "Missing table in context": "Missing table in context",
            "Missing table definition": "Missing table in context",
        }
    )

    categories = await aggregate_analysis_categories(
        client,
        "test-model",
        results,
        known_categories=["Context Missing", "Dataset Issue"],
    )

    assert categories == {"Context Missing": 3}
    assert [result.root_cause for result in results] == ["Context Missing"] * 3
    assert [result.root_cause_detail for result in results] == [
        "Missing table in context"
    ] * 3
    client.chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_aggregation_rejects_invented_target_ids() -> None:
    results = [_result("dataset"), _result("other data")]
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(
                    return_value=_response(
                        {
                            "category_clusters": [
                                {
                                    "canonical_id": "invented",
                                    "member_ids": ["c0", "c1"],
                                }
                            ]
                        }
                    )
                )
            )
        )
    )

    await aggregate_analysis_categories(client, "test-model", results)

    assert [result.root_cause for result in results] == ["dataset", "other data"]


@pytest.mark.asyncio
async def test_detail_instances_move_to_their_dominant_curated_category() -> None:
    results = [
        *[_result("Dataset Issue", "Missing value") for _ in range(20)],
        *[_result("Context Missing", "Missing value") for _ in range(4)],
    ]
    client = _client_with_label_mappings()

    categories = await aggregate_analysis_categories(
        client,
        "test-model",
        results,
        known_categories=["Dataset Issue", "Context Missing"],
    )

    assert categories == {"Dataset Issue": 24}
    assert [result.root_cause for result in results] == ["Dataset Issue"] * 24
    assert [result.root_cause_detail for result in results] == ["Missing value"] * 24
    client.chat.completions.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_detail_relocation_uses_first_category_to_break_a_tie() -> None:
    results = [
        _result("Context Missing", "Missing value"),
        _result("Dataset Issue", "Missing value"),
    ]
    client = _client_with_label_mappings()

    await aggregate_analysis_categories(
        client,
        "test-model",
        results,
        known_categories=["Context Missing", "Dataset Issue"],
    )

    assert [result.root_cause for result in results] == ["Context Missing"] * 2
    client.chat.completions.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_many_categories_still_use_one_model_round_trip() -> None:
    categories = [f"Category {index}" for index in range(8)]
    results = [
        _result(
            category,
            f"Failure mechanism {index} variant {variant}",
            solution=f"Remedy variant {index}",
        )
        for index, category in enumerate(categories)
        for variant in range(2)
    ]
    client = _client_with_label_mappings(
        details={
            f"Failure mechanism {index} variant {variant}": (
                f"Failure mechanism {index}"
            )
            for index in range(8)
            for variant in range(2)
        },
        delay=0.05,
    )

    started = time.perf_counter()
    await aggregate_analysis_categories(
        client,
        "test-model",
        results,
        known_categories=categories,
    )
    elapsed = time.perf_counter() - started

    client.chat.completions.create.assert_awaited_once()
    assert elapsed < 0.15
