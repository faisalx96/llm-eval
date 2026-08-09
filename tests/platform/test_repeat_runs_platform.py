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
    update_metric,
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
    RunMetricAnalysis,
    RunTraceAggregate,
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
        # SDK <=1.5.2 emitted item_completed before item_attempt_finished.
        # Keep that production order here to verify order-independent ingest.
        _event(2, "metric_scored", {
            "item_id": "item-1", "pass_number": 1, "metric_name": "accuracy",
            "score_numeric": 1.0, "meta": {"verdict": "correct"},
        }),
        _event(3, "item_completed", {
            "item_id": "item-1", "index": 0, "pass_number": 1,
            "is_final_pass": False, "output": "out-pass-1", "latency_ms": 100.0,
        }),
        _event(4, "item_attempt_finished", {
            "item_id": "item-1", "pass_number": 1, "attempt_number": 1,
            "status": "completed", "latency_ms": 100.0, "is_last_attempt": True,
        }),
        _event(5, "pass_completed", {
            "pass_number": 1, "samples": 3, "metrics": {"accuracy": 1.0},
        }),
        _event(6, "metric_scored", {
            "item_id": "item-1", "pass_number": 2, "metric_name": "accuracy",
            "score_numeric": 0.0, "meta": {"verdict": "incorrect"},
        }),
        _event(7, "item_completed", {
            "item_id": "item-1", "index": 0, "pass_number": 2,
            "is_final_pass": False, "output": "out-pass-2", "latency_ms": 120.0,
        }),
        _event(8, "item_attempt_finished", {
            "item_id": "item-1", "pass_number": 2, "attempt_number": 1,
            "status": "completed", "latency_ms": 120.0, "is_last_attempt": True,
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
        assert score.score_raw == pytest.approx(1.0 / 3.0)
        assert score.meta == {"sample_reducer": "mean", "samples_observed": 3}
        assert score.label is None
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

        stored_attempts = (
            session.query(RunItemAttempt)
            .filter(RunItemAttempt.run_id == RUN_ID)
            .order_by(RunItemAttempt.pass_number)
            .all()
        )
        for index, attempt in enumerate(stored_attempts, start=1):
            attempt.task_started_at_ms = 1_700_000_000_000 + index * 1_000
            attempt.trace_id = f"trace-pass-{index}"
            tokens = index * 1_000
            session.add(
                RunTraceAggregate(
                    run_id=RUN_ID,
                    trace_id=attempt.trace_id,
                    span_count=1,
                    tokens=tokens,
                    llm_calls=index,
                    tool_calls=index + 1,
                    raw_bucket={
                        "span_count": 1,
                        "tokens": tokens,
                        "llm_calls": index,
                        "tool_calls": index + 1,
                    },
                )
            )
        session.commit()

        # detail payload: samples + per-row pass_scores for the dot strips
        payload = _build_run_data(session, run)
        assert payload["run"]["samples"] == 3
        assert payload["run"]["last_completed_pass"] == 3
        row = payload["snapshot"]["rows"][0]
        assert row["pass_scores"] == {"accuracy": [1.0, 0.0, 0.0]}
        assert row["pass_metric_meta"] == {
            "accuracy": [
                {"verdict": "correct"},
                {"verdict": "incorrect"},
                {"label": "error"},
            ]
        }
        assert row["metric_meta"]["accuracy"] == {
            "sample_reducer": "mean",
            "samples_observed": 3,
        }

        # every pass's final attempt ships with the row — output, latency,
        # status — so the UI can show each attempt, not just the last one.
        # Pass 3 failed without an attempt event, so its slot is null and the
        # item-level error remains the source of truth for it.
        attempts_payload = row["pass_attempts"]
        assert [a and a["status"] for a in attempts_payload] == [
            "completed",
            "completed",
            None,
        ]
        assert attempts_payload[0]["output"] == "out-pass-1"
        assert attempts_payload[1]["output"] == "out-pass-2"
        assert attempts_payload[0]["latency_ms"] == pytest.approx(100.0)

        # lazy per-pass endpoint (runs-list expansion)
        passes = run_passes(RUN_ID, db=session, principal=principal)
        assert passes["samples"] == 3
        assert [p["status"] for p in passes["passes"]] == ["completed"] * 3
        assert passes["passes"][0]["metric_means"]["accuracy"] == pytest.approx(1.0)
        assert passes["passes"][2]["metric_means"]["accuracy"] == pytest.approx(0.0)
        assert passes["passes"][0]["started_at"] == "2023-11-14T22:13:21Z"
        assert passes["passes"][0]["duration_ms"] == pytest.approx(100.0)
        assert passes["passes"][0]["trace_stats"]["avg_tokens"] == pytest.approx(
            1000.0
        )
        assert passes["passes"][1]["trace_stats"]["avg_llm_calls"] == pytest.approx(
            2.0
        )
        assert passes["passes"][2]["started_at"] is None
        assert passes["passes"][2]["trace_stats"] is None

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
        assert gm["band"][1]["cumulative_avg"] == pytest.approx(1.0)
        assert gm["band"][2]["cumulative_avg"] == pytest.approx(0.5)
        assert gm["band"][3]["cumulative_avg"] == pytest.approx(1.0 / 3.0)
        assert gm["band"][1]["uncertainty"]["pass_at_k"] is None
        assert gm["uncertainty"] == {
            "confidence": 0.95,
            "bootstrap_iterations": 2000,
            "minimum_items": 20,
            "method": "item_bootstrap",
            "method_version": 1,
        }


def test_attempt_finished_stores_output_without_item_completed():
    """New SDKs make the attempt event self-contained for pass output."""
    app, SessionLocal = _make_env()
    with SessionLocal() as session:
        _seed(session, token="test-token", samples=2)

    body = _event(
        1,
        "item_attempt_finished",
        {
            "item_id": "item-1",
            "pass_number": 1,
            "attempt_number": 1,
            "status": "completed",
            "output": "direct-output",
            "latency_ms": 25.0,
            "is_last_attempt": True,
        },
    ) + "\n"
    with TestClient(app) as client:
        _ingest(client, body, "test-token")

    with SessionLocal() as session:
        attempt = session.query(RunItemAttempt).filter(
            RunItemAttempt.run_id == RUN_ID
        ).one()
        assert attempt.output == "direct-output"


def test_detail_recovers_outputs_from_stored_completion_events():
    """Already-affected runs render outputs without requiring a migration."""
    app, SessionLocal = _make_env()
    with SessionLocal() as session:
        _seed(session, token="test-token", samples=3)

    with TestClient(app) as client:
        _ingest(client, _sampled_run_events(), "test-token")

    with SessionLocal() as session:
        attempts = (
            session.query(RunItemAttempt)
            .filter(RunItemAttempt.run_id == RUN_ID)
            .all()
        )
        for attempt in attempts:
            attempt.output = None
        session.commit()

        run = session.query(Run).filter(Run.id == RUN_ID).one()
        row = _build_run_data(session, run)["snapshot"]["rows"][0]
        assert [attempt and attempt["output"] for attempt in row["pass_attempts"]] == [
            "out-pass-1",
            "out-pass-2",
            None,
        ]


def test_update_metric_with_pass_number_edits_pass_and_rereduces_mean():
    """Editing from a ?pass=N page targets that pass's score; the run-level
    score becomes the mean over passes again. The response row carries
    pass_scores/pass_attempts so the client keeps its per-pass detail."""
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

        # pass scores start at [1.0, 0.0, 0.0], reduced mean 1/3
        result = update_metric(
            request={
                "file_path": RUN_ID,
                "row_index": 0,
                "metric_name": "accuracy",
                "new_score": "1.0",
                "pass_number": 2,
            },
            db=session,
            principal=principal,
        )

        pass_two = (
            session.query(RunItemPassScore)
            .filter(
                RunItemPassScore.run_id == RUN_ID,
                RunItemPassScore.pass_number == 2,
            )
            .one()
        )
        assert pass_two.score_numeric == pytest.approx(1.0)

        reduced = (
            session.query(RunItemScore).filter(RunItemScore.run_id == RUN_ID).one()
        )
        assert reduced.score_numeric == pytest.approx(2.0 / 3.0)
        assert reduced.meta["modified"] == "true"
        assert reduced.meta["original_score"] == pytest.approx(1.0 / 3.0)
        assert reduced.meta["pass_2_original"] == pytest.approx(0.0)

        row = result["row"]
        assert row["pass_scores"]["accuracy"] == [1.0, 1.0, 0.0]
        assert row["pass_metric_meta"]["accuracy"][1]["modified"] == "true"
        assert row["pass_metric_meta"]["accuracy"][1]["original_score"] == pytest.approx(0.0)
        assert [a and a["status"] for a in row["pass_attempts"]] == [
            "completed",
            "completed",
            None,
        ]
        assert row["metric_values"] == [pytest.approx(2.0 / 3.0)]

        # out-of-range pass rejected
        with pytest.raises(Exception) as exc:
            update_metric(
                request={
                    "file_path": RUN_ID,
                    "row_index": 0,
                    "metric_name": "accuracy",
                    "new_score": "1.0",
                    "pass_number": 4,
                },
                db=session,
                principal=principal,
            )
        assert getattr(exc.value, "status_code", None) == 400


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


def test_runs_list_omits_uncertainty_from_scan_oriented_summary():
    app, SessionLocal = _make_env()
    with SessionLocal() as session:
        _seed(session, token="test-token", samples=3)
        # Two items x 3 passes, internally consistent (worst case for pooling):
        # item-1 always 1.0, item-2 always 0.0.
        for item_id, score in (("item-1", 1.0), ("item-2", 0.0)):
            session.add(
                RunItem(run_id=RUN_ID, item_id=item_id, index=0, input={"q": "x"})
            )
            for pass_number in (1, 2, 3):
                session.add(
                    RunItemPassScore(
                        run_id=RUN_ID,
                        item_id=item_id,
                        metric_name="accuracy",
                        pass_number=pass_number,
                        score_numeric=score,
                    )
                )
        session.commit()

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
        assert "metric_cis" not in summary


def test_group_metrics_respects_report_k_from_run_config():
    """run_config.report_k publishes pass@k estimated from all samples: the
    endpoint reports it, and group stats use the unbiased subset estimator."""
    app, SessionLocal = _make_env()
    with SessionLocal() as session:
        _seed(session, token="test-token", samples=3)
        run = session.query(Run).filter(Run.id == RUN_ID).one()
        run.run_config = {"samples": 3, "report_k": 2}
        session.commit()

    with TestClient(app) as client:
        _ingest(client, _sampled_run_events(), "test-token")

    with SessionLocal() as session:
        user = session.query(User).filter(User.id == "user-1").one()
        principal = Principal(
            user=user, auth_type="api_key", scopes=(), project_id="project-1"
        )
        gm = run_group_metrics(
            RUN_ID, metric=None, threshold=0.8, db=session, principal=principal
        )
        assert gm["report_k"] == 2
        # item-1: c=1 of n=3 -> unbiased pass@2 = 1 - C(2,2)/C(3,2) = 2/3
        assert gm["group"]["pass_at_k"] == pytest.approx(2.0 / 3.0)
        assert gm["group"]["report_k"] == 2


def test_group_metrics_bootstrap_is_cached_and_invalidated_by_score_changes():
    app, SessionLocal = _make_env()
    with SessionLocal() as session:
        _seed(session, token="test-token", samples=3)
        for index in range(20):
            item_id = f"item-{index}"
            session.add(
                RunItem(run_id=RUN_ID, item_id=item_id, index=index, input={"q": index})
            )
            for pass_number in (1, 2, 3):
                session.add(
                    RunItemPassScore(
                        run_id=RUN_ID,
                        item_id=item_id,
                        metric_name="accuracy",
                        pass_number=pass_number,
                        score_numeric=float((index + pass_number) % 2),
                    )
                )
        session.commit()
        principal = Principal(
            user=session.query(User).filter(User.id == "user-1").one(),
            auth_type="api_key", scopes=(), project_id="project-1",
        )

        first = run_group_metrics(
            RUN_ID, metric="accuracy", threshold=0.8, db=session, principal=principal
        )
        interval = first["band"][1]["uncertainty"]["cumulative_avg"]
        assert interval is not None
        assert interval["low"] < first["band"][1]["cumulative_avg"] < interval["high"]
        assert session.query(RunMetricAnalysis).count() == 1
        signature = session.query(RunMetricAnalysis.source_signature).scalar()

        second = run_group_metrics(
            RUN_ID, metric="accuracy", threshold=0.8, db=session, principal=principal
        )
        assert second["band"] == first["band"]
        assert session.query(RunMetricAnalysis).count() == 1

        score = session.query(RunItemPassScore).first()
        score.score_numeric = 1.0 - float(score.score_numeric or 0.0)
        session.commit()
        run_group_metrics(
            RUN_ID, metric="accuracy", threshold=0.8, db=session, principal=principal
        )
        assert session.query(RunMetricAnalysis).count() == 1
        assert session.query(RunMetricAnalysis.source_signature).scalar() != signature
