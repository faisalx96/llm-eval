from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker

from qym_platform.app import create_app
from qym_platform.auth import Principal, require_ui_principal
from qym_platform.db.base import Base
from qym_platform.db.models import (
    CorrectionStatus,
    Project,
    ProjectMembership,
    ReviewCorrection,
    ProjectRole,
    Run,
    RunItem,
    RunItemScore,
    RunMetricSpec,
    RunWorkflowStatus,
    User,
    UserRole,
)
from qym_platform.services.root_cause_dashboard import (
    DashboardFilters,
    build_compare_payload,
    build_dashboard_payload,
    build_occurrences_payload,
)
from qym_platform.deps import get_db


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed(session: Session) -> tuple[Project, list[Run]]:
    user = User(id="user-1", email="user@example.com", role=UserRole.ADMIN)
    project = Project(
        id="project-1",
        name="Dashboard project",
        slug="dashboard-project",
        created_by_user_id=user.id,
    )
    session.add_all([user, project])
    session.flush()
    session.add(
        ProjectMembership(
            project_id=project.id,
            user_id=user.id,
            role=ProjectRole.MANAGER,
            added_by_user_id=user.id,
        )
    )
    base = datetime(2026, 1, 1)
    runs: list[Run] = []
    for index, score, category in [
        (1, 0.7, "Dataset-Issue"),
        (2, 0.9, "dataset issue"),
    ]:
        run = Run(
            id=f"run-{index}",
            project_id=project.id,
            created_by_user_id=user.id,
            owner_user_id=user.id,
            task="qa",
            dataset="eval",
            model="openai/model-x",
            metrics=["accuracy"],
            status=RunWorkflowStatus.COMPLETED,
            created_at=base + timedelta(days=index),
        )
        item = RunItem(
            run_id=run.id,
            item_id=f"item-{index}",
            index=0,
            input={"q": index},
            output={"a": index},
            item_metadata=(
                {
                    "root_cause": "legacy duplicate",
                    "root_cause_source": "ai",
                    "metric_analyses": {
                        "accuracy": {
                            "root_cause": category,
                            "root_cause_detail": "Missing value",
                            "source": "ai",
                        }
                    },
                }
                if index == 1
                else {
                    "root_cause": category,
                    "root_cause_detail": "Missing value",
                    "root_cause_source": "human",
                    "root_cause_metric_name": "accuracy",
                }
            ),
        )
        session.add_all(
            [
                run,
                item,
                RunItemScore(
                    run_id=run.id,
                    item_id=item.item_id,
                    metric_name="accuracy",
                    score_numeric=score,
                ),
                RunMetricSpec(
                    run_id=run.id,
                    metric_name="accuracy",
                    score_type="numeric",
                    direction="maximize",
                    pass_threshold=0.8,
                    precision=2,
                ),
            ]
        )
        session.add(
            ReviewCorrection(
                run_id=run.id,
                item_id=item.item_id,
                metric_name="accuracy" if index == 1 else None,
                task=run.task,
                ai_root_cause=category,
                ai_root_causes=[category],
                human_root_cause=category,
                human_root_causes=[category],
                human_root_cause_detail="Missing value",
                status=CorrectionStatus.APPROVED,
                is_active=True,
            )
        )
        runs.append(run)
    session.commit()
    return project, runs


def test_dashboard_uses_metric_scoped_state_and_normalizes_only_typography() -> None:
    session = _session()
    try:
        project, _ = _seed(session)
        payload = build_dashboard_payload(session, project, DashboardFilters())

        assert payload["summary"]["diagnosis_occurrences"] == 2
        assert payload["summary"]["affected_run_item_pairs"] == 2
        assert payload["summary"]["categories"] == 1
        assert payload["facets"]["score_metrics"] == ["accuracy"]
        assert payload["groups"]["by_category"][0]["category"] in {
            "Dataset-Issue",
            "dataset issue",
        }
        assert payload["groups"]["by_category"][0]["count"] == 2
        assert payload["scores"]["metric_name"] == "accuracy"
        assert payload["scores"]["runs"][0]["average"] == 0.9
        assert payload["scores"]["runs"][1]["average"] == 0.7

        empty_scope = build_dashboard_payload(
            session, project, DashboardFilters(outcome=("error",))
        )
        assert empty_scope["summary"]["diagnosis_occurrences"] == 0
        assert empty_scope["facets"]["score_metrics"] == ["accuracy"]
    finally:
        session.close()


def test_dashboard_filters_outcomes_and_paginates_occurrences() -> None:
    session = _session()
    try:
        project, _ = _seed(session)
        failed = build_occurrences_payload(
            session,
            project,
            DashboardFilters(outcome=("failed",)),
            limit=1,
        )
        assert failed["total"] == 1
        assert len(failed["occurrences"]) == 1
        assert failed["occurrences"][0]["run_id"] == "run-1"
    finally:
        session.close()


def test_compare_marks_direction_aware_improvement() -> None:
    session = _session()
    try:
        project, runs = _seed(session)
        payload = build_compare_payload(
            session,
            project,
            [run.id for run in runs],
            DashboardFilters(),
            score_metric="accuracy",
            baseline_run_id="run-1",
        )
        comparison = {row["run_id"]: row for row in payload["score_comparison"]}
        assert comparison["run-1"]["comparison_status"] == "baseline"
        assert comparison["run-2"]["comparison_status"] == "improved"
        assert comparison["run-2"]["raw_delta"] == pytest.approx(0.2)
        assert payload["summary"]["best_run_id"] == "run-2"
        assert payload["category_matrix"][0]["total_count"] == 2
        assert payload["metric_matrix"][0]["metric_name"] == "accuracy"
        assert payload["metric_matrix"][0]["runs"]["run-1"]["count"] == 1
        assert payload["run_summary"][0]["run_id"] == "run-1"
        assert payload["run_summary"][0]["share"] == pytest.approx(0.5)
    finally:
        session.close()


def test_compare_scopes_aggregate_statistics_to_selected_metric() -> None:
    session = _session()
    try:
        project, runs = _seed(session)
        for index, run in enumerate(runs, start=1):
            run.metrics = ["accuracy", "relevance"]
            item = session.query(RunItem).filter(RunItem.run_id == run.id).one()
            item.item_metadata = {
                "metric_analyses": {
                    "accuracy": {
                        "root_cause": "Accuracy issue",
                        "root_cause_detail": "Incorrect answer",
                        "source": "ai",
                    },
                    "relevance": {
                        "root_cause": "Relevance issue",
                        "root_cause_detail": "Off topic",
                        "source": "ai",
                    },
                }
            }
            session.add_all(
                [
                    RunItemScore(
                        run_id=run.id,
                        item_id=item.item_id,
                        metric_name="relevance",
                        score_numeric=0.1 * index,
                    ),
                    RunMetricSpec(
                        run_id=run.id,
                        metric_name="relevance",
                        score_type="numeric",
                        direction="maximize",
                        pass_threshold=0.8,
                        precision=2,
                    ),
                ]
            )
            correction = (
                session.query(ReviewCorrection)
                .filter(
                    ReviewCorrection.run_id == run.id,
                    ReviewCorrection.item_id == item.item_id,
                )
                .one()
            )
            correction.metric_name = "accuracy"
            correction.ai_root_cause = "Accuracy issue"
            correction.ai_root_causes = ["Accuracy issue"]
            correction.human_root_cause = "Accuracy issue"
            correction.human_root_causes = ["Accuracy issue"]
            correction.human_root_cause_detail = "Incorrect answer"
            session.add(
                ReviewCorrection(
                    run_id=run.id,
                    item_id=item.item_id,
                    metric_name="relevance",
                    task=run.task,
                    ai_root_cause="Relevance issue",
                    ai_root_causes=["Relevance issue"],
                    human_root_cause="Relevance issue",
                    human_root_causes=["Relevance issue"],
                    human_root_cause_detail="Off topic",
                    status=CorrectionStatus.APPROVED,
                    is_active=True,
                )
            )
        session.commit()

        accuracy = build_compare_payload(
            session,
            project,
            [run.id for run in runs],
            DashboardFilters(),
            score_metric="accuracy",
        )
        assert accuracy["summary"]["occurrences"] == 2
        assert [row["category"] for row in accuracy["category_matrix"]] == [
            "Accuracy issue"
        ]
        assert [row["metric_name"] for row in accuracy["metric_matrix"]] == ["accuracy"]
        assert [row["count"] for row in accuracy["run_summary"]] == [1, 1]

        relevance = build_compare_payload(
            session,
            project,
            [run.id for run in runs],
            DashboardFilters(),
            score_metric="relevance",
        )
        assert relevance["summary"]["occurrences"] == 2
        assert [row["category"] for row in relevance["category_matrix"]] == [
            "Relevance issue"
        ]
        assert [row["metric_name"] for row in relevance["metric_matrix"]] == [
            "relevance"
        ]
        assert [row["count"] for row in relevance["run_summary"]] == [1, 1]

        all_metrics = build_compare_payload(
            session,
            project,
            [run.id for run in runs],
            DashboardFilters(),
            score_metric="__all__",
        )
        assert all_metrics["score_metric"] == "__all__"
        assert all_metrics["score_comparison"] == []
        assert all_metrics["summary"]["occurrences"] == 4
        assert [row["metric_name"] for row in all_metrics["metric_matrix"]] == [
            "accuracy",
            "relevance",
        ]
    finally:
        session.close()


def test_root_cause_dashboard_routes_are_temporarily_disabled() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        project, _ = _seed(session)
        user = session.get(User, "user-1")
        app = create_app()
        app.dependency_overrides[get_db] = lambda: session
        app.dependency_overrides[require_ui_principal] = lambda: Principal(
            user=user,
            auth_type="none",
        )
        with TestClient(app) as client:
            response = client.get(f"/api/projects/{project.slug}/root-cause-dashboard")
            assert response.status_code == 404
            occurrences = client.get(
                f"/api/projects/{project.slug}/root-cause-dashboard/occurrences"
            )
            assert occurrences.status_code == 404
            compare = client.get(
                f"/api/projects/{project.slug}/root-cause-dashboard/compare",
                params=[("run_id", "run-1"), ("run_id", "run-2")],
            )
            assert compare.status_code == 404
            # The public schema works with both flattened and deferred routers.
            registered_paths = app.openapi()["paths"]
            for suffix in ("", "/occurrences", "/compare"):
                path = "/api/projects/{project_slug}/root-cause-dashboard" + suffix
                assert "get" in registered_paths[path]
        assert session.query(RunItem).count() == 2
    finally:
        session.close()


def test_compare_rejects_conflicting_metric_semantics() -> None:
    session = _session()
    try:
        project, _ = _seed(session)
        session.query(RunMetricSpec).filter(
            RunMetricSpec.run_id == "run-2", RunMetricSpec.metric_name == "accuracy"
        ).update({"direction": "minimize"})
        session.commit()
        payload = build_compare_payload(
            session,
            project,
            ["run-1", "run-2"],
            DashboardFilters(),
            score_metric="accuracy",
        )
        assert payload["score_compatibility"]["comparable"] is False
        assert all(
            row["comparison_status"] == "unavailable"
            for row in payload["score_comparison"]
        )
        assert payload["summary"]["best_run_id"] is None
    finally:
        session.close()
