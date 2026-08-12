from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("QYM_AUTH_MODE", "proxy_headers")
ROOT = Path(__file__).resolve().parents[2]
PLATFORM_SRC = ROOT / "packages" / "platform"
if str(PLATFORM_SRC) not in sys.path:
    sys.path.insert(0, str(PLATFORM_SRC))
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

from qym_platform.app import create_app
from qym_platform.datetime_utils import utc_now_naive
from qym_platform.db.base import Base
from qym_platform.db.models import (
    Dataset,
    DatasetVersion,
    DatasetVersionStatus,
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


@pytest.fixture()
def session_factory(monkeypatch):
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("QYM_AUTH_MODE", "proxy_headers")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    try:
        yield SessionLocal
    finally:
        engine.dispose()


@pytest.fixture()
def client(session_factory):
    app = create_app()

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def _headers(email: str = "owner@example.com") -> dict[str, str]:
    return {"X-User-Email": email}


def _add_run(
    session: Session,
    *,
    run_id: str,
    project: Project,
    owner: User,
    version: DatasetVersion,
    started_days_ago: int,
    model: str,
    scores: list[float | None],
    errors: list[str | None],
    latencies: list[float],
) -> Run:
    started_at = utc_now_naive() - timedelta(days=started_days_ago)
    run = Run(
        id=run_id,
        project_id=project.id,
        created_by_user_id=owner.id,
        owner_user_id=owner.id,
        task="answer-support",
        dataset="support-cases",
        dataset_id=version.dataset_id,
        dataset_version_id=version.id,
        model=model,
        metrics=["correctness", "helpfulness"],
        status=RunWorkflowStatus.COMPLETED,
        run_metadata={},
        run_config={"run_name": "Run " + run_id[-1]},
        started_at=started_at,
        ended_at=started_at + timedelta(seconds=3),
        created_at=started_at,
    )
    session.add(run)
    session.flush()
    for index, (score, error, latency) in enumerate(zip(scores, errors, latencies)):
        item_id = f"item-{index}"
        session.add(
            RunItem(
                run_id=run.id,
                item_id=item_id,
                index=index,
                input={"question": str(index)},
                expected={"answer": str(index)},
                output=None if error else {"answer": str(index)},
                error=error,
                item_metadata={},
                latency_ms=latency,
                retry_count=index,
            )
        )
        if score is not None:
            session.add(
                RunItemScore(
                    run_id=run.id,
                    item_id=item_id,
                    metric_name="correctness",
                    score_numeric=score,
                    score_raw=score,
                    meta={},
                )
            )
    for position, metric_name in enumerate(run.metrics):
        session.add(
            RunMetricSpec(
                run_id=run.id,
                metric_name=metric_name,
                position=position,
                score_type="percentage",
                direction="maximize",
                pass_threshold=0.8,
                sample_reducer="mean",
                run_reducer="mean",
                unit=None,
                precision=2,
            )
        )
    return run


def _seed(session: Session) -> None:
    owner = User(id="owner", email="owner@example.com", role=UserRole.MEMBER)
    outsider = User(id="outsider", email="outsider@example.com", role=UserRole.MEMBER)
    project = Project(id="project", name="Support", slug="support", created_by_user_id=owner.id)
    membership = ProjectMembership(project_id=project.id, user_id=owner.id, role=ProjectRole.MANAGER)
    dataset = Dataset(
        id="dataset",
        project_id=project.id,
        name="Support cases",
        slug="support-cases",
        created_by_user_id=owner.id,
    )
    version = DatasetVersion(
        id="version-2",
        dataset_id=dataset.id,
        version="v2",
        status=DatasetVersionStatus.PUBLISHED,
        created_by_user_id=owner.id,
    )
    session.add_all([owner, outsider, project, membership, dataset, version])
    session.flush()
    _add_run(
        session,
        run_id="run-1",
        project=project,
        owner=owner,
        version=version,
        started_days_ago=4,
        model="openai/gpt-5",
        scores=[1.0, 0.0],
        errors=[None, None],
        latencies=[100.0, 300.0],
    )
    _add_run(
        session,
        run_id="run-2",
        project=project,
        owner=owner,
        version=version,
        started_days_ago=2,
        model="openai/gpt-5.1",
        scores=[0.8, None],
        errors=[None, "timeout"],
        latencies=[200.0, 400.0],
    )
    session.commit()


def test_insights_returns_oldest_to_latest_aggregated_run_points(client, session_factory) -> None:
    with session_factory() as session:
        _seed(session)

    response = client.get("/api/projects/support/insights?period=all", headers=_headers())
    assert response.status_code == 200, response.text
    payload = response.json()

    assert [run["run_id"] for run in payload["runs"]] == ["run-1", "run-2"]
    assert payload["runs"][0]["metric_averages"]["correctness"] == pytest.approx(0.5)
    # Errored items are included as zero in the metric denominator.
    assert payload["runs"][1]["metric_averages"]["correctness"] == pytest.approx(0.4)
    assert payload["runs"][1]["metric_counts"]["correctness"] == 2
    assert payload["runs"][0]["median_latency_ms"] == pytest.approx(200.0)
    assert payload["runs"][1]["success_rate"] == pytest.approx(0.5)
    assert payload["runs"][1]["total_retries"] == 1
    assert payload["facets"]["dataset_versions"] == [{"value": "version-2", "label": "v2"}]
    assert payload["facets"]["models"] == [
        {"value": "openai/gpt-5", "label": "gpt-5"},
        {"value": "openai/gpt-5.1", "label": "gpt-5.1"},
    ]


def test_insights_filters_models_and_enforces_project_access(client, session_factory) -> None:
    with session_factory() as session:
        _seed(session)

    filtered = client.get(
        "/api/projects/support/insights?period=all&model=openai%2Fgpt-5.1",
        headers=_headers(),
    )
    assert filtered.status_code == 200, filtered.text
    assert [run["run_id"] for run in filtered.json()["runs"]] == ["run-2"]

    denied = client.get(
        "/api/projects/support/insights?period=all",
        headers=_headers("outsider@example.com"),
    )
    assert denied.status_code == 403

    invalid = client.get(
        "/api/projects/support/insights?period=all&status=RUNNING",
        headers=_headers(),
    )
    assert invalid.status_code == 400
