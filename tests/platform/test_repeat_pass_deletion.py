from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")
ROOT = Path(__file__).resolve().parents[2]
PLATFORM_SRC = ROOT / "packages" / "platform"
if str(PLATFORM_SRC) not in sys.path:
    sys.path.insert(0, str(PLATFORM_SRC))
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

from qym_platform.app import create_app
from qym_platform.db.base import Base
from qym_platform.db.models import (
    AuditLog,
    Project,
    ProjectMembership,
    Run,
    RunEvent,
    RunItem,
    RunItemAttempt,
    RunItemPassScore,
    RunItemScore,
    RunMetricAnalysis,
    RunWorkflowStatus,
    User,
    UserRole,
)
from qym_platform.deps import get_db


RUN_ID = "repeat-pass-delete-run"
HEADERS = {
    "X-User-Email": "owner@example.com",
    "Origin": "http://localhost:8000",
}


@pytest.fixture(autouse=True)
def _auth_mode(monkeypatch):
    monkeypatch.setenv("QYM_AUTH_MODE", "proxy_headers")


def _make_env():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    app = create_app()

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return app, SessionLocal


def _seed(session: Session) -> None:
    user = User(id="user-1", email="owner@example.com", role=UserRole.MEMBER)
    project = Project(
        id="project-1",
        name="Project 1",
        slug="project-1",
        created_by_user_id=user.id,
    )
    session.add_all(
        [
            user,
            project,
            ProjectMembership(user_id=user.id, project_id=project.id),
            Run(
                id=RUN_ID,
                project_id=project.id,
                created_by_user_id=user.id,
                owner_user_id=user.id,
                task="task",
                dataset="dataset",
                metrics=["accuracy"],
                samples=3,
                run_config={"samples": 3, "report_k": 3},
                run_metadata={"samples": 3, "last_completed_pass": 3},
                status=RunWorkflowStatus.COMPLETED,
            ),
            RunItem(
                run_id=RUN_ID,
                item_id="item-1",
                index=0,
                input="question",
                output="out-pass-2",
                error="boom",
                trace_id="trace-pass-3",
                item_metadata={"task_started_at_ms": 3000},
            ),
            RunItemScore(
                run_id=RUN_ID,
                item_id="item-1",
                metric_name="accuracy",
                score_numeric=1.0 / 3.0,
                score_raw=1.0 / 3.0,
                meta={
                    "sample_reducer": "mean",
                    "samples_observed": 3,
                    "modified": "true",
                    "pass_2_original": 0.0,
                    "pass_3_original": 0.25,
                },
            ),
            RunMetricAnalysis(
                run_id=RUN_ID,
                metric_name="accuracy",
                threshold_micros=500_000,
                source_signature="cached",
                payload={"stale": True},
            ),
        ]
    )
    for pass_number, score in ((1, 1.0), (2, 0.0), (3, 0.0)):
        session.add(
            RunItemPassScore(
                run_id=RUN_ID,
                item_id="item-1",
                metric_name="accuracy",
                pass_number=pass_number,
                score_numeric=score,
                label="error" if pass_number == 3 else None,
            )
        )
    session.add_all(
        [
            RunItemAttempt(
                run_id=RUN_ID,
                item_id="item-1",
                pass_number=1,
                attempt_number=1,
                status="completed",
                output=None,
                trace_id="trace-pass-1",
                task_started_at_ms=1000,
                is_last_attempt=True,
            ),
            RunItemAttempt(
                run_id=RUN_ID,
                item_id="item-1",
                pass_number=2,
                attempt_number=1,
                status="completed",
                output="out-pass-2",
                trace_id="trace-pass-2",
                task_started_at_ms=2000,
                is_last_attempt=True,
            ),
            RunItemAttempt(
                run_id=RUN_ID,
                item_id="item-1",
                pass_number=3,
                attempt_number=1,
                status="failed",
                error="boom",
                trace_id="trace-pass-3",
                task_started_at_ms=3000,
                is_last_attempt=True,
            ),
        ]
    )
    sequence = 0
    for pass_number, event_type, output in (
        (1, "item_completed", "out-pass-1"),
        (2, "item_completed", "out-pass-2"),
        (3, "item_failed", None),
    ):
        sequence += 1
        payload = {
            "item_id": "item-1",
            "pass_number": pass_number,
            "trace_id": f"trace-pass-{pass_number}",
        }
        if output is not None:
            payload["output"] = output
        session.add(
            RunEvent(
                run_id=RUN_ID,
                event_id=f"event-{sequence}",
                sequence=sequence,
                type=event_type,
                sent_at=datetime(2026, 8, 9),
                payload=payload,
            )
        )
    session.commit()


def test_delete_repeat_pass_reindexes_and_repairs_run_state():
    app, SessionLocal = _make_env()
    with SessionLocal() as session:
        _seed(session)

    with TestClient(app) as client:
        response = client.delete(f"/api/runs/{RUN_ID}/passes/2", headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "run_id": RUN_ID,
        "deleted_pass": 2,
        "samples": 2,
        "deleted_attempts": 1,
        "deleted_scores": 1,
    }

    with SessionLocal() as session:
        run = session.get(Run, RUN_ID)
        assert run.samples == 2
        assert run.run_config == {"samples": 2, "report_k": 2}
        assert run.run_metadata["samples"] == 2
        assert run.run_metadata["last_completed_pass"] == 2

        pass_scores = (
            session.query(RunItemPassScore)
            .filter(RunItemPassScore.run_id == RUN_ID)
            .order_by(RunItemPassScore.pass_number)
            .all()
        )
        assert [(row.pass_number, row.score_numeric) for row in pass_scores] == [
            (1, 1.0),
            (2, 0.0),
        ]
        score = session.query(RunItemScore).filter(RunItemScore.run_id == RUN_ID).one()
        assert score.score_numeric == pytest.approx(0.5)
        assert score.score_raw == pytest.approx(0.5)
        assert score.meta == {
            "sample_reducer": "mean",
            "samples_observed": 2,
            "modified": "true",
            "pass_2_original": 0.25,
        }

        attempts = (
            session.query(RunItemAttempt)
            .filter(RunItemAttempt.run_id == RUN_ID)
            .order_by(RunItemAttempt.pass_number)
            .all()
        )
        assert [attempt.pass_number for attempt in attempts] == [1, 2]
        assert attempts[0].output == "out-pass-1"
        assert attempts[1].status == "failed"
        item = session.query(RunItem).filter(RunItem.run_id == RUN_ID).one()
        assert item.output == "out-pass-1"
        assert item.error == "boom"
        assert item.trace_id == "trace-pass-3"

        event_passes = [
            int(event.payload["pass_number"])
            for event in session.query(RunEvent).filter(RunEvent.run_id == RUN_ID)
        ]
        assert event_passes == [1, 2]
        assert session.query(RunMetricAnalysis).count() == 0
        audit = (
            session.query(AuditLog).filter(AuditLog.action == "run.pass_deleted").one()
        )
        assert audit.before == {"samples": 3, "pass_number": 2}
        assert audit.after["samples"] == 2


def test_delete_multiple_passes_uses_original_numbers_and_is_atomic():
    app, SessionLocal = _make_env()
    with SessionLocal() as session:
        _seed(session)

    with TestClient(app) as client:
        response = client.request(
            "DELETE",
            f"/api/runs/{RUN_ID}/passes",
            headers=HEADERS,
            json={"pass_numbers": [2, 3]},
        )
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "run_id": RUN_ID,
        "deleted_passes": [2, 3],
        "samples": 1,
    }

    with SessionLocal() as session:
        run = session.get(Run, RUN_ID)
        assert run.samples == 1
        attempts = session.query(RunItemAttempt).filter_by(run_id=RUN_ID).all()
        assert [(attempt.pass_number, attempt.output) for attempt in attempts] == [
            (1, "out-pass-1")
        ]
        score = session.query(RunItemScore).filter_by(run_id=RUN_ID).one()
        assert score.score_numeric == pytest.approx(1.0)
        assert session.query(AuditLog).filter_by(action="run.pass_deleted").count() == 2

    app, SessionLocal = _make_env()
    with SessionLocal() as session:
        _seed(session)
    with TestClient(app) as client:
        rejected = client.request(
            "DELETE",
            f"/api/runs/{RUN_ID}/passes",
            headers=HEADERS,
            json={"pass_numbers": [1, 2, 3]},
        )
    assert rejected.status_code == 400
    assert rejected.json()["detail"] == "A run must retain at least one pass"
    with SessionLocal() as session:
        assert session.get(Run, RUN_ID).samples == 3
        assert session.query(RunItemAttempt).filter_by(run_id=RUN_ID).count() == 3


def test_delete_repeat_pass_rejects_active_run_and_last_pass():
    app, SessionLocal = _make_env()
    with SessionLocal() as session:
        _seed(session)
        run = session.get(Run, RUN_ID)
        run.status = RunWorkflowStatus.RUNNING
        session.commit()

    with TestClient(app) as client:
        active = client.delete(f"/api/runs/{RUN_ID}/passes/2", headers=HEADERS)
        assert active.status_code == 409

        with SessionLocal() as session:
            run = session.get(Run, RUN_ID)
            run.status = RunWorkflowStatus.COMPLETED
            run.samples = 1
            run.run_config = {"samples": 1}
            session.commit()

        last = client.delete(f"/api/runs/{RUN_ID}/passes/1", headers=HEADERS)
        assert last.status_code == 400
        assert last.json()["detail"] == "A run must retain at least one pass"
