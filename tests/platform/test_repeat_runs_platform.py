"""Repeat runs (samples=k) platform integration: ingest, reduction, endpoints."""

from __future__ import annotations

import json
import os
import sys
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
from qym_platform.api.runs import (
    _build_run_data,
    legacy_list_runs,
    run_group_metrics,
    run_passes,
)
from qym_platform.auth import Principal
from qym_platform.db.base import Base
from qym_platform.db.models import (
    ApiKey,
    Project,
    ProjectMembership,
    Run,
    RunItem,
    RunItemAttempt,
    RunItemPassScore,
    RunItemScore,
    RunWorkflowStatus,
    User,
    UserRole,
)
from qym_platform.deps import get_db
from qym_platform.security import api_key_prefix, hash_api_key


@pytest.fixture(autouse=True)
def _auth_mode(monkeypatch):
    monkeypatch.setenv("QYM_AUTH_MODE", "proxy_headers")


RUN_ID = "00000000-0000-0000-0000-00000000ab01"


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


def _seed(session: Session, *, token: str, samples: int) -> tuple[User, Project, Run]:
    user = User(id="user-1", email="owner@example.com", role=UserRole.MEMBER)
    project = Project(
        id="project-1", name="Project 1", slug="project-1", created_by_user_id=user.id
    )
    api_key = ApiKey(
        id="key-1",
        user_id=user.id,
        project_id=project.id,
        name="test",
        prefix=api_key_prefix(token),
        key_hash=hash_api_key(token),
        scopes=[],
    )
    run = Run(
        id=RUN_ID,
        project_id=project.id,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        task="sampled-task",
        dataset="dataset-1",
        status=RunWorkflowStatus.RUNNING,
        metrics=["accuracy"],
        run_metadata={},
        run_config={"samples": samples},
        samples=samples,
    )
    membership = ProjectMembership(user_id=user.id, project_id=project.id)
    session.add_all([user, project, api_key, membership, run])
    session.commit()
    return user, project, run


def _event(seq: int, type_: str, payload: dict) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "event_id": f"00000000-0000-0000-0000-0000000010{seq:02d}",
            "sequence": seq,
            "sent_at": "2026-07-04T00:00:00Z",
            "type": type_,
            "run_id": RUN_ID,
            "payload": payload,
        }
    )


def _sampled_run_events() -> str:
    """item-1: pass 1 scores 1.0, pass 2 scores 0.0, pass 3 FAILS entirely."""
    lines = [
        _event(1, "item_started", {
            "item_id": "item-1", "index": 0, "pass_number": 1, "input": {"q": "hi"},
        }),
        _event(2, "item_attempt_finished", {
            "item_id": "item-1", "pass_number": 1, "attempt_number": 1,
            "status": "completed", "latency_ms": 100.0, "is_last_attempt": True,
        }),
        _event(3, "metric_scored", {
            "item_id": "item-1", "pass_number": 1, "metric_name": "accuracy",
            "score_numeric": 1.0,
        }),
        _event(4, "item_completed", {
            "item_id": "item-1", "index": 0, "pass_number": 1,
            "is_final_pass": False, "output": "out-pass-1", "latency_ms": 100.0,
        }),
        _event(5, "pass_completed", {
            "pass_number": 1, "samples": 3, "metrics": {"accuracy": 1.0},
        }),
        _event(6, "item_attempt_finished", {
            "item_id": "item-1", "pass_number": 2, "attempt_number": 1,
            "status": "completed", "latency_ms": 120.0, "is_last_attempt": True,
        }),
        _event(7, "metric_scored", {
            "item_id": "item-1", "pass_number": 2, "metric_name": "accuracy",
            "score_numeric": 0.0,
        }),
        _event(8, "item_completed", {
            "item_id": "item-1", "index": 0, "pass_number": 2,
            "is_final_pass": False, "output": "out-pass-2", "latency_ms": 120.0,
        }),
        _event(9, "pass_completed", {
            "pass_number": 2, "samples": 3, "metrics": {"accuracy": 0.5},
        }),
        _event(10, "item_failed", {
            "item_id": "item-1", "index": 0, "pass_number": 3, "error": "boom",
        }),
        _event(11, "pass_completed", {
            "pass_number": 3, "samples": 3, "metrics": {"accuracy": 1.0 / 3.0},
        }),
    ]
    return "\n".join(lines) + "\n"


def _ingest(client: TestClient, body: str, token: str) -> None:
    response = client.post(
        f"/v1/runs/{RUN_ID}/events",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-ndjson",
        },
        content=body,
    )
    assert response.status_code == 200


def test_sampled_run_ingest_stores_passes_and_reduces_mean():
    app, SessionLocal = _make_env()
    with SessionLocal() as session:
        _seed(session, token="test-token", samples=3)

    with TestClient(app) as client:
        _ingest(client, _sampled_run_events(), "test-token")

    with SessionLocal() as session:
        # attempts carry pass_number; pass-1 attempt stores its pass output
        attempts = (
            session.query(RunItemAttempt)
            .filter(RunItemAttempt.run_id == RUN_ID)
            .order_by(RunItemAttempt.pass_number)
            .all()
        )
        assert [a.pass_number for a in attempts] == [1, 2]
        assert attempts[0].output == "out-pass-1"
        assert attempts[1].output == "out-pass-2"

        # per-pass scores: 1.0, 0.0, and 0.0 (failed pass zero-fill)
        pass_scores = (
            session.query(RunItemPassScore)
            .filter(RunItemPassScore.run_id == RUN_ID)
            .order_by(RunItemPassScore.pass_number)
            .all()
        )
        assert [(p.pass_number, p.score_numeric) for p in pass_scores] == [
            (1, 1.0),
            (2, 0.0),
            (3, 0.0),
        ]
        assert pass_scores[2].label == "error"

        # reduced score = mean over passes; RunItem stays ONE row
        score = (
            session.query(RunItemScore)
            .filter(RunItemScore.run_id == RUN_ID)
            .one()
        )
        assert score.score_numeric == pytest.approx(1.0 / 3.0)
        assert (
            session.query(RunItem).filter(RunItem.run_id == RUN_ID).count() == 1
        )

        run = session.query(Run).filter(Run.id == RUN_ID).one()
        assert run.samples == 3
        assert run.run_metadata.get("last_completed_pass") == 3


def test_detail_passes_and_group_metrics_endpoints():
    app, SessionLocal = _make_env()
    with SessionLocal() as session:
        user, project, _ = _seed(session, token="test-token", samples=3)

    with TestClient(app) as client:
        _ingest(client, _sampled_run_events(), "test-token")

    with SessionLocal() as session:
        run = session.query(Run).filter(Run.id == RUN_ID).one()
        user = session.query(User).filter(User.id == "user-1").one()
        principal = Principal(
            user=user, auth_type="api_key", scopes=(), project_id="project-1"
        )

        # detail payload: samples + per-row pass_scores for the dot strips
        payload = _build_run_data(session, run)
        assert payload["run"]["samples"] == 3
        assert payload["run"]["last_completed_pass"] == 3
        row = payload["snapshot"]["rows"][0]
        assert row["pass_scores"] == {"accuracy": [1.0, 0.0, 0.0]}

        # lazy per-pass endpoint (runs-list expansion)
        passes = run_passes(RUN_ID, db=session, principal=principal)
        assert passes["samples"] == 3
        assert [p["status"] for p in passes["passes"]] == ["completed"] * 3
        assert passes["passes"][0]["metric_means"]["accuracy"] == pytest.approx(1.0)
        assert passes["passes"][2]["metric_means"]["accuracy"] == pytest.approx(0.0)

        # on-demand group metrics + full k-band (no reducer lock-in)
        gm = run_group_metrics(
            RUN_ID, metric=None, threshold=0.8, db=session, principal=principal
        )
        assert gm["group"]["k"] == 3
        assert gm["group"]["pass_at_k"] == pytest.approx(1.0)
        assert gm["group"]["pass_hat_k"] == pytest.approx(0.0)
        assert set(gm["band"].keys()) == {1, 2, 3}
        assert gm["band"][1]["pass_at_k"] == pytest.approx(1.0 / 3.0)
        assert gm["band"][3]["pass_at_k"] == pytest.approx(1.0)


def test_runs_list_payload_includes_pass_summaries_for_dot_strip():
    """The list payload carries per-pass summaries so the runs-list pass-dot
    strip renders without a per-row /passes fetch."""
    app, SessionLocal = _make_env()
    with SessionLocal() as session:
        _seed(session, token="test-token", samples=3)

    with TestClient(app) as client:
        _ingest(client, _sampled_run_events(), "test-token")

    with SessionLocal() as session:
        user = session.query(User).filter(User.id == "user-1").one()
        principal = Principal(
            user=user, auth_type="api_key", scopes=(), project_id="project-1"
        )
        payload = legacy_list_runs(
            limit=100,
            offset=0,
            project_slug="project-1",
            status=None,
            exclude_live=False,
            user=None,
            user_id=None,
            owner_user_id=None,
            db=session,
            principal=principal,
        )
        summaries = [
            s
            for models in payload["tasks"].values()
            for run_list in models.values()
            for s in run_list
        ]
        summary = next(s for s in summaries if s["run_id"] == RUN_ID)
        assert summary["samples"] == 3

        ps = summary["pass_summaries"]
        assert [p["pass_number"] for p in ps] == [1, 2, 3]
        # last_completed_pass == 3, so every pass reads completed
        assert [p["status"] for p in ps] == ["completed"] * 3
        # primary metric (accuracy) means per pass: 1.0, 0.0, 0.0 (zero-filled
        # failed pass) — these drive the dot colors
        assert ps[0]["primary_score"] == pytest.approx(1.0)
        assert ps[1]["primary_score"] == pytest.approx(0.0)
        assert ps[2]["primary_score"] == pytest.approx(0.0)
        # pass 3 failed via item_failed (no attempt row), so attempt-derived
        # error_count stays 0 — the zero-filled score already colors the dot
        assert [p["error_count"] for p in ps] == [0, 0, 0]


def test_old_sdk_events_without_pass_number_still_ingest():
    """Pre-samples SDKs omit pass_number entirely — everything defaults to 1."""
    app, SessionLocal = _make_env()
    with SessionLocal() as session:
        _seed(session, token="test-token", samples=1)

    legacy = "\n".join(
        [
            _event(1, "item_started", {
                "item_id": "item-1", "index": 0, "input": {"q": "hi"},
            }),
            _event(2, "item_attempt_finished", {
                "item_id": "item-1", "attempt_number": 1,
                "status": "completed", "latency_ms": 90.0, "is_last_attempt": True,
            }),
            _event(3, "metric_scored", {
                "item_id": "item-1", "metric_name": "accuracy", "score_numeric": 0.75,
            }),
            _event(4, "item_completed", {
                "item_id": "item-1", "index": 0, "output": "legacy-out",
                "latency_ms": 90.0,
            }),
        ]
    ) + "\n"

    with TestClient(app) as client:
        _ingest(client, legacy, "test-token")

    with SessionLocal() as session:
        score = (
            session.query(RunItemScore).filter(RunItemScore.run_id == RUN_ID).one()
        )
        assert score.score_numeric == pytest.approx(0.75)  # raw, no reduction
        # classic runs never touch the pass-score table
        assert (
            session.query(RunItemPassScore)
            .filter(RunItemPassScore.run_id == RUN_ID)
            .count()
            == 0
        )
        attempt = (
            session.query(RunItemAttempt)
            .filter(RunItemAttempt.run_id == RUN_ID)
            .one()
        )
        assert attempt.pass_number == 1
