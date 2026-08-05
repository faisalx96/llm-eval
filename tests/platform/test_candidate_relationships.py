from __future__ import annotations

from datetime import datetime, timedelta
import os
import time
import tracemalloc
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from qym_platform.app import create_app
from qym_platform.auth import Principal, require_ui_principal
from qym_platform.db.base import Base
from qym_platform.db.models import (
    Project,
    ProjectMembership,
    ProjectRole,
    Run,
    RunItem,
    RunItemScore,
    RunMetricSpec,
    RunWorkflowStatus,
    User,
    UserRole,
)
from qym_platform.deps import get_db
from qym_platform.services.candidate_relationships import (
    _Predicate,
    _generate_candidate_specs,
    build_relationship_analysis,
    build_relationship_occurrences,
)


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _project(db: Session) -> tuple[Project, User]:
    owner = User(id="owner", email="owner@example.com", role=UserRole.ADMIN)
    project = Project(
        id="project",
        name="Relationships",
        slug="relationships",
        created_by_user_id=owner.id,
    )
    db.add_all(
        [
            owner,
            project,
            ProjectMembership(
                project_id=project.id,
                user_id=owner.id,
                role=ProjectRole.MANAGER,
                added_by_user_id=owner.id,
            ),
        ]
    )
    db.flush()
    return project, owner


def _run(
    db: Session,
    project: Project,
    owner: User,
    run_id: str,
    model: str,
    labels: list[str],
    *,
    diagnosed: bool = True,
    category: str = "Retrieval issue",
    detail: str | None = "Missed documents",
    categories: list[str] | None = None,
) -> Run:
    started = datetime(2026, 1, 1) + timedelta(days=int(run_id.removeprefix("run-")))
    run = Run(
        id=run_id,
        project_id=project.id,
        created_by_user_id=owner.id,
        owner_user_id=owner.id,
        task="qa",
        dataset="support",
        model=model,
        metrics=["accuracy"],
        status=RunWorkflowStatus.COMPLETED,
        run_config={"run_name": run_id, "git_branch": "main"},
        run_metadata={},
        started_at=started,
        created_at=started,
    )
    db.add(run)
    db.flush()
    for index, label in enumerate(labels):
        metadata = {"bucket": label}
        if diagnosed:
            analysis = {"root_cause": category}
            if categories is not None:
                analysis["root_cause"] = categories[index]
            if detail is not None:
                analysis["root_cause_detail"] = detail
            metadata["metric_analyses"] = {"accuracy": analysis}
        item_id = f"item-{index}"
        db.add(
            RunItem(
                run_id=run.id,
                item_id=item_id,
                index=index,
                input={"question": index},
                expected={"answer": index},
                output={"answer": index},
                item_metadata=metadata,
            )
        )
        db.add(
            RunItemScore(
                run_id=run.id,
                item_id=item_id,
                metric_name="accuracy",
                score_numeric=1.0,
                score_raw=1.0,
            )
        )
    db.add(
        RunMetricSpec(
            run_id=run.id,
            metric_name="accuracy",
            position=0,
            score_type="numeric",
            direction="maximize",
            pass_threshold=0.8,
        )
    )
    return run


def test_constant_model_is_excluded_and_ten_is_the_category_threshold() -> None:
    db = _session()
    try:
        project, owner = _project(db)
        _run(
            db,
            project,
            owner,
            "run-0",
            "provider/only-model",
            ["hot"] * 10 + ["cold"] * 10,
            categories=["Retrieval issue"] * 10 + ["Other issue"] * 10,
        )
        db.commit()

        payload = build_relationship_analysis(db, project)
        assert payload["counts"]["total"] == 20
        assert payload["counts"]["diagnosed"] == 20
        assert payload["gates"]["target_support"]["survived"] >= 1
        relationships = [
            relationship
            for category in payload["categories"]
            for relationship in category["relationships"]
        ]
        assert relationships
        assert all(
            factor["field"] != "run.model"
            for relationship in relationships
            for factor in relationship["factors"]
        )
        assert any(
            factor["field"] == "item.metadata.bucket"
            for relationship in relationships
            for factor in relationship["factors"]
        )
    finally:
        db.close()


def test_nine_diagnoses_do_not_create_a_category_target() -> None:
    db = _session()
    try:
        project, owner = _project(db)
        _run(
            db,
            project,
            owner,
            "run-0",
            "provider/model",
            ["hot"] * 9,
            diagnosed=True,
        )
        _run(
            db,
            project,
            owner,
            "run-1",
            "provider/model",
            ["cold"] * 11,
            diagnosed=False,
        )
        db.commit()

        payload = build_relationship_analysis(db, project)
        assert payload["counts"]["diagnosed"] == 9
        assert payload["empty_state"] == "diagnoses_below_threshold"
        assert payload["categories"] == []
        assert payload["gates"]["target_support"]["reasons"]["below_category_threshold"] == 1
    finally:
        db.close()


def test_directional_relationship_ids_and_occurrences_are_deterministic() -> None:
    db = _session()
    try:
        project, owner = _project(db)
        _run(db, project, owner, "run-0", "provider/x", ["hot"] * 10, category="Retrieval issue")
        _run(db, project, owner, "run-1", "provider/x", ["cold"] * 10, category="Other issue")
        _run(db, project, owner, "run-2", "provider/x", ["hot"] * 10, category="Retrieval issue")
        _run(db, project, owner, "run-3", "provider/y", ["cold"] * 10, category="Other issue")
        _run(db, project, owner, "run-4", "provider/y", ["cold"] * 10, category="Retrieval issue")
        _run(db, project, owner, "run-5", "provider/y", ["hot"] * 10, category="Other issue")
        db.commit()

        first = build_relationship_analysis(db, project)
        second = build_relationship_analysis(db, project)
        first_ids = [
            relationship["relationship_id"]
            for category in first["categories"]
            for relationship in category["relationships"]
        ]
        second_ids = [
            relationship["relationship_id"]
            for category in second["categories"]
            for relationship in category["relationships"]
        ]
        assert first_ids == second_ids
        assert first_ids
        relationship_id = first_ids[0]
        evidence = build_relationship_occurrences(
            db,
            project,
            relationship_id,
            limit=3,
            offset=0,
        )
        assert evidence is not None
        assert evidence["total"] >= 10
        assert len(evidence["occurrences"]) == 3
        assert all("prompt" not in str(row).lower() for row in evidence["occurrences"])
    finally:
        db.close()


def test_three_factor_interaction_survives_when_simpler_subsets_do_not() -> None:
    db = _session()
    try:
        project, owner = _project(db)
        # A parity target keeps every one- and two-factor subset at the same
        # rate while the 1/1/1 interaction is strongly associated.
        for run_index, bits in enumerate(
            [(0, 0, 0), (0, 0, 1), (0, 1, 0), (0, 1, 1),
             (1, 0, 0), (1, 0, 1), (1, 1, 0), (1, 1, 1)]
        ):
            run = Run(
                id=f"run-{run_index}",
                project_id=project.id,
                created_by_user_id=owner.id,
                owner_user_id=owner.id,
                task="qa",
                dataset="support",
                model="provider/model",
                metrics=["accuracy"],
                status=RunWorkflowStatus.COMPLETED,
                run_config={},
                run_metadata={},
            )
            db.add(run)
            db.flush()
            target = sum(bits) % 2 == 1
            for index in range(10):
                item_id = f"item-{index}"
                db.add(
                    RunItem(
                        run_id=run.id,
                        item_id=item_id,
                        index=index,
                        input={"question": index},
                        expected={},
                        output={},
                        item_metadata={
                            "a": bool(bits[0]),
                            "b": bool(bits[1]),
                            "c": bool(bits[2]),
                            "metric_analyses": {
                                "accuracy": {
                                    "root_cause": "Interaction" if target else "Other"
                                }
                            },
                        },
                    )
                )
                db.add(
                    RunItemScore(
                        run_id=run.id,
                        item_id=item_id,
                        metric_name="accuracy",
                        score_numeric=1.0,
                    )
                )
            db.add(
                RunMetricSpec(
                    run_id=run.id,
                    metric_name="accuracy",
                    score_type="numeric",
                    direction="maximize",
                    pass_threshold=0.8,
                )
            )
        db.commit()

        payload = build_relationship_analysis(db, project)
        relationships = [
            relationship
            for category in payload["categories"]
            for relationship in category["relationships"]
            if category["category"] == "Interaction"
        ]
        triple = [relationship for relationship in relationships if relationship["arity"] == 3]
        assert triple
        assert {factor["field"] for factor in triple[0]["factors"]} == {
            "item.metadata.a",
            "item.metadata.b",
            "item.metadata.c",
        }
    finally:
        db.close()


def test_relationship_routes_are_read_only_project_scoped_and_stale_safe() -> None:
    db = _session()
    try:
        project, owner = _project(db)
        _run(db, project, owner, "run-0", "provider/x", ["hot"] * 10, category="Retrieval issue")
        _run(db, project, owner, "run-1", "provider/y", ["cold"] * 10, category="Other issue")
        db.commit()
        app = create_app()
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[require_ui_principal] = lambda: Principal(
            user=owner,
            auth_type="none",
        )
        with TestClient(app) as client:
            response = client.get("/api/projects/relationships/insights/relationships")
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["schema_version"] == 1
            relationship_id = payload["categories"][0]["relationships"][0]["relationship_id"]
            evidence = client.get(
                f"/api/projects/relationships/insights/relationships/{relationship_id}/occurrences",
                params={"limit": 1},
            )
            assert evidence.status_code == 200, evidence.text
            assert len(evidence.json()["occurrences"]) == 1
            stale = client.get(
                "/api/projects/relationships/insights/relationships/rel_missing/occurrences"
            )
            assert stale.status_code == 410
            assert stale.json()["code"] == "stale_relationship"
        assert db.query(RunItem).count() == 20
    finally:
        db.close()


@pytest.mark.skipif(
    os.getenv("QYM_RUN_RELATIONSHIP_BENCHMARK") != "1",
    reason="opt-in 100,000-observation relationship generation benchmark",
)
def test_benchmark_100k_observations_three_factor_generation() -> None:
    """Record a bounded synthetic generation run for combinatorial regressions."""

    observations = [SimpleNamespace(index=index) for index in range(100_000)]
    predicates = [
        _Predicate(f"{field}|equals|true", field, "equals", True, field, "item_metadata", 2, "boolean", 1)
        for field in ("a", "b", "c")
    ]
    bits = {
        predicate.key: sum(
            1 << index
            for index in range(100_000)
            if (index % 8) in {4, 5, 6, 7} if predicate.field == "a"
        )
        for predicate in predicates
    }
    bits["b|equals|true"] = sum(
        1 << index for index in range(100_000) if (index % 4) in {2, 3}
    )
    bits["c|equals|true"] = sum(
        1 << index for index in range(100_000) if (index % 2) == 1
    )
    tracemalloc.start()
    started = time.perf_counter()
    candidates = _generate_candidate_specs(observations, predicates, bits)
    elapsed = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert any(len(candidate[0]) == 3 for candidate in candidates)
    print(f"relationship benchmark: {elapsed:.3f}s, peak={peak / (1024 * 1024):.1f}MiB")
