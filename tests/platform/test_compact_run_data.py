"""Logical parity, isolation and payload bounds for lazy run detail APIs."""

from __future__ import annotations

import json
import random

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from qym_platform.api.runs import (
    _build_run_data,
    legacy_compare,
    legacy_run_data,
    run_item_details,
    search_run_items,
)
from qym_platform.auth import Principal
from qym_platform.db.base import Base
from qym_platform.db.models import (
    Project,
    ProjectMembership,
    Run,
    RunEvent,
    RunItem,
    RunItemAttempt,
    RunItemPassScore,
    RunItemScore,
    RunWorkflowStatus,
    User,
    UserRole,
)


@pytest.fixture
def data():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as db:
        user = User(id="owner", email="owner@example.invalid", role=UserRole.MEMBER)
        project = Project(
            id="project", slug="project", name="Project", created_by_user_id=user.id
        )
        db.add_all([user, project])
        db.flush()
        db.add(ProjectMembership(project_id=project.id, user_id=user.id))
        run = Run(
            id="run",
            project_id=project.id,
            owner_user_id=user.id,
            created_by_user_id=user.id,
            task="task",
            dataset="dataset",
            metrics=["quality", "count"],
            status=RunWorkflowStatus.COMPLETED,
            run_metadata={},
            run_config={},
        )
        db.add(run)
        db.commit()
        yield db, run, Principal(user=user, auth_type="local_password")
    engine.dispose()


def add_rows(db, run, count=8, body_size=100):
    rng = random.Random(927)
    outputs = [
        None,
        "",
        False,
        0,
        {"عربي": "قيمة", "nested": [1, 2]},
        "line one\nline two",
        "İSTANBUL",
        "needle",
    ]
    for index in range(count):
        item_id = str(index)  # Exercise generated identity and duplicate occurrences.
        error = "Failure NEEDLE" if index == 2 else None
        db.add(
            RunItem(
                run_id=run.id,
                item_id=item_id,
                index=index,
                input={"same": "x" * body_size},
                expected="same expected",
                output=outputs[index % len(outputs)],
                error=error,
                latency_ms=100 + index,
                retry_count=index % 3,
                item_metadata={
                    "domain": ["a", "b"],
                    "task_started_at_ms": 1000,
                    "metric_analyses": {
                        "quality": {
                            "root_cause": "Reasoning",
                            "root_cause_detail": "Keep full logical analysis",
                        }
                    },
                },
            )
        )
        for metric in run.metrics:
            db.add(
                RunItemScore(
                    run_id=run.id,
                    item_id=item_id,
                    metric_name=metric,
                    score_numeric=rng.choice([None, 0, 0.2, 0.8, 1]),
                    score_raw="unscored",
                    meta={"modified": True, "original_score": 0.2},
                    explanation="Long judge explanation " * body_size,
                    label="judge label",
                )
            )
    db.commit()


def test_compact_hydration_preserves_every_logical_field_and_duplicate_identity(data):
    db, run, principal = data
    add_rows(db, run)
    original = _build_run_data(db, run)
    compact = legacy_run_data(run.id, db, principal, view="compact")
    assert compact["run"] == original["run"]
    assert compact["snapshot"]["stats"] == original["snapshot"]["stats"]
    assert compact["snapshot"]["detail_mode"] == "lazy"
    assert len({row["compare_item_id"] for row in compact["snapshot"]["rows"]}) == 8
    for row, full in zip(compact["snapshot"]["rows"], original["snapshot"]["rows"]):
        assert "input_full" not in row and "output" not in row
        assert row["metric_values"] == full["metric_values"]
        assert row["item_metadata"] == full["item_metadata"]
        assert row["error"] == full["error"]
        assert row["metric_meta"]["quality"]["modified"] is True
        detail = run_item_details(
            run.id, {"item_ids": [row["item_id"]]}, db, principal
        )["rows"][0]
        assert "compare_item_id" not in detail
        hydrated = {**row, **detail}
        assert {key: hydrated[key] for key in full} == full


def test_existing_full_api_and_comparison_remain_unchanged(data):
    db, run, principal = data
    add_rows(db, run)
    full = legacy_run_data(run.id, db, principal)
    assert full == legacy_run_data(run.id, db, principal, view="full")
    assert "detail_mode" not in full["snapshot"]
    # Explicit keywords preserve the established callable signature.
    compared = legacy_compare(
        files=[run.id], db=db, principal=principal, view="compact"
    )
    assert (
        compared["runs"][0]["run"]["compare_alignment_status"]
        == full["run"]["compare_alignment_status"]
    )
    assert [
        row["compare_item_id"] for row in compared["runs"][0]["snapshot"]["rows"]
    ] == [row["compare_item_id"] for row in full["snapshot"]["rows"]]


def test_hydration_is_bounded_and_returns_missing_ids_without_other_rows(data):
    db, run, principal = data
    add_rows(db, run, count=205, body_size=1)
    statements = []

    def record(conn, cursor, statement, params, context, many):
        statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", record)
    try:
        result = run_item_details(
            run.id, {"item_ids": ["200", "missing", "204", "200"]}, db, principal
        )
    finally:
        event.remove(db.bind, "before_cursor_execute", record)
    assert [row["item_id"] for row in result["rows"]] == ["200", "204"]
    assert result["missing_item_ids"] == ["missing"]
    item_reads = [sql for sql in statements if "FROM run_items" in sql]
    score_reads = [sql for sql in statements if "FROM run_item_scores" in sql]
    assert item_reads and score_reads
    assert all("item_id IN" in sql for sql in item_reads + score_reads)


@pytest.mark.parametrize(
    "payload",
    [
        {"item_ids": []},
        {"item_ids": ["x"] * 101},
        {"item_ids": [None]},
        {"item_ids": "x"},
        {"item_ids": [""]},
    ],
)
def test_invalid_hydration_requests_are_rejected(data, payload):
    db, run, principal = data
    with pytest.raises(HTTPException) as error:
        run_item_details(run.id, payload, db, principal)
    assert error.value.status_code == 422


def test_initial_payload_does_not_grow_with_input_or_explanation_bodies(data):
    db, run, principal = data
    add_rows(db, run, count=20, body_size=10000)
    full = _build_run_data(db, run)
    compact = _build_run_data(db, run, compact=True)
    assert len(json.dumps(compact)) < len(json.dumps(full)) / 20


@pytest.mark.parametrize(
    "term", ["NEEDLE", "قيمة", '"same":', "line one\nline two", "0", "", "i̇stanbul"]
)
def test_server_text_search_matches_full_response_for_all_items(data, term):
    db, run, principal = data
    add_rows(db, run)
    full = _build_run_data(db, run)
    result = search_run_items(
        run.id,
        {
            "conditions": [
                {"id": "all", "field": "all", "value": term},
                {"id": "output", "field": "output", "value": term},
            ]
        },
        db,
        principal,
    )
    expected_all, expected_output = [], []
    for row in full["snapshot"]["rows"]:
        fields = [
            str(row["item_id"] or row["index"] or ""),
            row["input"],
            row["expected"],
            row["output"],
        ]
        if any(term.lower() in value.lower() for value in fields):
            expected_all.append(row["item_id"])
        if term.lower() in row["output"].lower():
            expected_output.append(row["item_id"])
    assert result["matches"] == {"all": expected_all, "output": expected_output}


def test_repeat_pass_bodies_and_search_keep_pass_identity(data):
    db, run, principal = data
    run.samples = 3
    add_rows(db, run, count=2)
    for item in ["0", "1"]:
        for number in [1, 2]:
            db.add(
                RunItemAttempt(
                    run_id=run.id,
                    item_id=item,
                    pass_number=number,
                    attempt_number=1,
                    is_last_attempt=True,
                    status="completed",
                    output=f"only pass {number}",
                    latency_ms=number * 10,
                )
            )
            db.add(
                RunItemPassScore(
                    run_id=run.id,
                    item_id=item,
                    metric_name="quality",
                    pass_number=number,
                    score_numeric=number / 3,
                    meta={"custom": "retained"},
                    explanation=f"pass {number} explanation",
                )
            )
    db.commit()
    full = _build_run_data(db, run)
    compact = _build_run_data(db, run, compact=True)
    for row, expected in zip(compact["snapshot"]["rows"], full["snapshot"]["rows"]):
        assert row["pass_scores"] == expected["pass_scores"]
        assert row["pass_attempts"][2] is None
        assert "output" not in row["pass_attempts"][0]
        assert row["pass_metric_meta"]["quality"][0]["custom"] == "retained"
        patch = run_item_details(run.id, {"item_ids": [row["item_id"]]}, db, principal)[
            "rows"
        ][0]
        assert patch["pass_attempts"] == expected["pass_attempts"]
        assert patch["pass_metric_meta"] == expected["pass_metric_meta"]
    for number in [1, 2, 3]:
        found = search_run_items(
            run.id,
            {
                "pass_number": number,
                "conditions": [{"id": "q", "field": "output", "value": "only pass 1"}],
            },
            db,
            principal,
        )
        assert found["matches"]["q"] == (["0", "1"] if number == 1 else [])


def test_new_routes_enforce_project_visibility_and_soft_deletion(data):
    db, run, principal = data
    other = User(id="other", email="other@example.invalid", role=UserRole.MEMBER)
    db.add(other)
    db.commit()
    unauthorized = Principal(user=other, auth_type="local_password")
    for endpoint, payload in [
        (run_item_details, {"item_ids": ["0"]}),
        (search_run_items, {"conditions": [{"id": "q", "field": "all", "value": "x"}]}),
    ]:
        with pytest.raises(HTTPException) as error:
            endpoint(run.id, payload, db, unauthorized)
        assert error.value.status_code == 403
    from datetime import datetime, timezone

    run.deleted_at = datetime.now(timezone.utc)
    db.commit()
    with pytest.raises(HTTPException) as error:
        run_item_details(run.id, {"item_ids": ["0"]}, db, principal)
    assert error.value.status_code == 404


def test_repeat_search_streams_scoped_detail_batches(data, monkeypatch):
    from datetime import datetime

    from qym_platform.api import runs as runs_api

    db, run, principal = data
    run.samples = 2
    add_rows(db, run, count=251, body_size=30)
    for index in range(250):
        db.add(
            RunItemAttempt(
                run_id=run.id,
                item_id=str(index),
                pass_number=1,
                attempt_number=1,
                is_last_attempt=True,
                status="completed",
                output=f"pass-one-{index}" if index < 249 else None,
            )
        )
    # Last batch includes both final-attempt output recovery and a legacy SDK
    # outcome with no attempt row. Both must remain searchable.
    for index in (249, 250):
        db.add(
            RunEvent(
                run_id=run.id,
                event_id=f"recovered-{index}",
                sequence=index,
                sent_at=datetime.now(),
                type="item_completed",
                payload={
                    "item_id": str(index),
                    "pass_number": 1,
                    "output": f"pass-one-{index}",
                },
            )
        )
    db.commit()
    original = runs_api._build_run_data
    scopes = []

    def bounded(db, run, *, item_ids=None, **kwargs):
        assert item_ids is not None, "repeat search loaded the entire run payload"
        assert len(item_ids) <= 100
        scopes.append(list(item_ids))
        return original(db, run, item_ids=item_ids, **kwargs)

    monkeypatch.setattr(runs_api, "_build_run_data", bounded)
    result = runs_api.search_run_items(
        run.id,
        {
            "pass_number": 1,
            "conditions": [{"id": "q", "field": "output", "value": "pass-one"}],
        },
        db,
        principal,
    )
    assert result["matches"]["q"] == [str(index) for index in range(251)]
    assert len(scopes) >= 2
    assert sum(map(len, scopes)) == 251
