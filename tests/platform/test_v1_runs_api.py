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
    ApiKey,
    Approval,
    Project,
    ProjectMembership,
    ProjectRole,
    Run,
    RunItem,
    RunItemScore,
    RunWorkflowStatus,
    User,
    UserRole,
)
from qym_platform.deps import get_db
from qym_platform.security import api_key_prefix, hash_api_key

API_TOKEN_A = "v1-test-token-a"


@pytest.fixture()
def session_factory(monkeypatch):
    # Pin every auth-relevant env var: a repo-root .env with real values exists
    # and PlatformSettings loads it from cwd, so nothing may leak in.
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("QYM_AUTH_MODE", "proxy_headers")
    monkeypatch.setenv("QYM_ENVIRONMENT", "test")
    monkeypatch.setenv("QYM_PROXY_SHARED_SECRET", "")
    monkeypatch.setenv("QYM_AUTH_LOCAL_ENABLED", "false")
    monkeypatch.setenv("QYM_AUTH_SESSION_SECRET", "")
    monkeypatch.setenv("QYM_AUTO_PROVISION_USERS", "false")
    monkeypatch.setenv("QYM_ADMIN_BOOTSTRAP_TOKEN", "")
    monkeypatch.setenv("QYM_AUTH_GOOGLE_CLIENT_ID", "")
    monkeypatch.setenv("QYM_AUTH_GOOGLE_CLIENT_SECRET", "")
    monkeypatch.setenv("QYM_AUTH_GITHUB_CLIENT_ID", "")
    monkeypatch.setenv("QYM_AUTH_GITHUB_CLIENT_SECRET", "")
    monkeypatch.setenv("QYM_HIDDEN_TASKS", "")
    monkeypatch.setenv("QYM_ALLOW_LEGACY_EMPTY_API_KEY_SCOPES", "true")
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


def _ui(email: str) -> dict[str, str]:
    return {"X-User-Email": email}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_world(session: Session) -> None:
    now = utc_now_naive()
    admin = User(id="u-admin", email="admin@example.com", role=UserRole.ADMIN)
    owner = User(id="u-owner", email="owner@example.com", display_name="Owner One", role=UserRole.MEMBER)
    member = User(id="u-member", email="member@example.com", display_name="Member Two", role=UserRole.MEMBER)
    manager = User(id="u-manager", email="manager@example.com", display_name="Manager Three", role=UserRole.MEMBER)
    owner_b = User(id="u-owner-b", email="owner-b@example.com", display_name="Owner Bee", role=UserRole.MEMBER)
    project_a = Project(id="proj-a", name="Alpha", slug="alpha", created_by_user_id=admin.id)
    project_b = Project(id="proj-b", name="Beta", slug="beta", created_by_user_id=admin.id)
    session.add_all([
        admin, owner, member, manager, owner_b, project_a, project_b,
        ProjectMembership(project_id=project_a.id, user_id=owner.id, role=ProjectRole.MEMBER),
        ProjectMembership(project_id=project_a.id, user_id=member.id, role=ProjectRole.MEMBER),
        ProjectMembership(project_id=project_a.id, user_id=manager.id, role=ProjectRole.MANAGER),
        ProjectMembership(project_id=project_b.id, user_id=owner_b.id, role=ProjectRole.MEMBER),
        ApiKey(
            id="key-a",
            user_id=owner.id,
            project_id=project_a.id,
            name="spa-test",
            prefix=api_key_prefix(API_TOKEN_A),
            key_hash=hash_api_key(API_TOKEN_A),
            scopes=[],
        ),
    ])

    long_text = "lorem ipsum " * 40  # ~480 chars, forces preview truncation

    run_a1 = Run(
        id="run-a1",
        project_id=project_a.id,
        created_by_user_id=owner.id,
        owner_user_id=owner.id,
        task="qa",
        dataset="ds1",
        model="openai/gpt-4o",
        metrics=["judge"],
        status=RunWorkflowStatus.COMPLETED,
        run_metadata={"total_items": 3},
        run_config={"run_name": "Baseline Run", "git_branch": "main", "git_commit": "abc123def456"},
        created_at=now - timedelta(hours=3),
        started_at=now - timedelta(hours=3),
        ended_at=now - timedelta(hours=3) + timedelta(minutes=5),
    )
    run_a2 = Run(
        id="run-a2",
        project_id=project_a.id,
        created_by_user_id=owner.id,
        owner_user_id=owner.id,
        task="qa",
        dataset="ds1",
        model="openai/gpt-4o",
        metrics=["judge"],
        status=RunWorkflowStatus.COMPLETED,
        run_metadata={"total_items": 2},
        run_config={"run_name": "Improved Run"},
        created_at=now - timedelta(hours=2),
        started_at=now - timedelta(hours=2),
        ended_at=now - timedelta(hours=2) + timedelta(minutes=4),
    )
    run_a3 = Run(
        id="run-a3",
        project_id=project_a.id,
        created_by_user_id=owner.id,
        owner_user_id=owner.id,
        task="qa",
        dataset="ds1",
        model="openai/gpt-4o",
        metrics=["judge"],
        status=RunWorkflowStatus.SUBMITTED,
        run_metadata={},
        run_config={"run_name": "Candidate Run"},
        created_at=now - timedelta(hours=1),
        started_at=now - timedelta(hours=1),
        ended_at=now - timedelta(hours=1) + timedelta(minutes=3),
    )
    run_a4 = Run(
        id="run-a4",
        project_id=project_a.id,
        created_by_user_id=member.id,
        owner_user_id=member.id,
        task="summarize",
        dataset="ds2",
        model=None,
        metrics=[],
        status=RunWorkflowStatus.RUNNING,
        run_metadata={},
        run_config={},
        created_at=now - timedelta(minutes=30),
        started_at=now - timedelta(minutes=30),
        last_event_at=now,
    )
    run_b1 = Run(
        id="run-b1",
        project_id=project_b.id,
        created_by_user_id=owner_b.id,
        owner_user_id=owner_b.id,
        task="qa",
        dataset="ds1",
        model="gpt-4o",
        metrics=["judge"],
        status=RunWorkflowStatus.COMPLETED,
        run_metadata={},
        run_config={"run_name": "Beta Run"},
        created_at=now - timedelta(hours=1),
    )
    session.add_all([run_a1, run_a2, run_a3, run_a4, run_b1])
    session.add_all([
        RunItem(
            run_id="run-a1", item_id="i1", index=0,
            input={"q": "What is 2+2"}, expected={"a": "4"}, output={"a": "4"},
            latency_ms=120.0, trace_id="trace-1", trace_url="http://lf/t/1",
        ),
        RunItem(
            run_id="run-a1", item_id="i2", index=1,
            input=long_text, expected="short", output=long_text,
            latency_ms=80.0,
            item_metadata={"root_cause": "Wrong Format", "root_cause_source": "human"},
        ),
        RunItem(
            run_id="run-a1", item_id="i3", index=2,
            input={"q": "boom"}, error="ValueError: boom\nstack details",
            retry_count=2,
        ),
        RunItem(run_id="run-a2", item_id="j1", index=0, input={"q": "a"}, output="ok", latency_ms=50.0),
        RunItem(run_id="run-a2", item_id="j2", index=1, input={"q": "b"}, output="ok", latency_ms=60.0),
        RunItem(run_id="run-a3", item_id="k1", index=0, input={"q": "c"}, output="ok", latency_ms=70.0),
        RunItem(run_id="run-b1", item_id="x1", index=0, input={"q": "z"}, output="ok"),
        RunItemScore(run_id="run-a1", item_id="i1", metric_name="judge", score_numeric=1.0, score_raw=1.0),
        RunItemScore(run_id="run-a1", item_id="i2", metric_name="judge", score_numeric=0.5, score_raw=0.5),
        RunItemScore(run_id="run-a2", item_id="j1", metric_name="judge", score_numeric=1.0, score_raw=1.0),
        RunItemScore(run_id="run-a2", item_id="j2", metric_name="judge", score_numeric=1.0, score_raw=1.0),
        RunItemScore(run_id="run-a3", item_id="k1", metric_name="judge", score_numeric=0.75, score_raw=0.75),
        RunItemScore(run_id="run-b1", item_id="x1", metric_name="judge", score_numeric=1.0, score_raw=1.0),
        Approval(run_id="run-a3", submitted_by_user_id=owner.id),
    ])
    session.commit()


@pytest.fixture()
def seeded(session_factory):
    with session_factory() as session:
        _seed_world(session)


# ---------------------------------------------------------------------------
# 1. List: pagination + filters + q + needs_review
# ---------------------------------------------------------------------------

def test_list_runs_default_sort_and_summary_shape(client, seeded) -> None:
    response = client.get("/v1/runs?project_slug=alpha", headers=_ui("owner@example.com"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 4
    assert payload["limit"] == 50
    assert payload["offset"] == 0
    assert [run["id"] for run in payload["runs"]] == ["run-a4", "run-a3", "run-a2", "run-a1"]

    a1 = next(run for run in payload["runs"] if run["id"] == "run-a1")
    assert a1["name"] == "Baseline Run"
    assert a1["task"] == "qa"
    assert a1["dataset"] == "ds1"
    assert a1["model"] == "gpt-4o"
    assert a1["status"] == "COMPLETED"
    assert a1["total_items"] == 3
    assert a1["completed_items"] == 3
    assert a1["error_items"] == 1
    assert a1["progress_pct"] == pytest.approx(1.0)
    # Errored item counts as 0: (1.0 + 0.5 + 0) / 3
    assert a1["metric_averages"]["judge"] == pytest.approx(0.5)
    assert a1["version"] == {"branch": "main", "commit": "abc123def456"}
    assert a1["group_key"] == "qa|ds1|gpt-4o"
    assert a1["duration_ms"] == pytest.approx(5 * 60 * 1000.0)
    assert a1["owner"]["email"] == "owner@example.com"


def test_list_runs_pagination(client, seeded) -> None:
    page1 = client.get("/v1/runs?project_id=proj-a&limit=2&offset=0", headers=_ui("owner@example.com"))
    page2 = client.get("/v1/runs?project_id=proj-a&limit=2&offset=2", headers=_ui("owner@example.com"))
    assert page1.status_code == 200 and page2.status_code == 200
    ids1 = [run["id"] for run in page1.json()["runs"]]
    ids2 = [run["id"] for run in page2.json()["runs"]]
    assert ids1 == ["run-a4", "run-a3"]
    assert ids2 == ["run-a2", "run-a1"]
    assert page1.json()["total"] == 4


def test_list_runs_filters(client, seeded) -> None:
    by_status = client.get("/v1/runs?project_slug=alpha&status=COMPLETED", headers=_ui("owner@example.com"))
    assert by_status.status_code == 200
    assert {run["id"] for run in by_status.json()["runs"]} == {"run-a1", "run-a2"}

    multi_status = client.get(
        "/v1/runs?project_slug=alpha&status=COMPLETED,SUBMITTED", headers=_ui("owner@example.com")
    )
    assert multi_status.status_code == 200
    assert multi_status.json()["total"] == 3

    invalid_status = client.get("/v1/runs?project_slug=alpha&status=BOGUS", headers=_ui("owner@example.com"))
    assert invalid_status.status_code == 400

    by_task = client.get("/v1/runs?project_slug=alpha&task=summarize", headers=_ui("owner@example.com"))
    assert [run["id"] for run in by_task.json()["runs"]] == ["run-a4"]

    by_dataset = client.get("/v1/runs?project_slug=alpha&dataset=ds2", headers=_ui("owner@example.com"))
    assert [run["id"] for run in by_dataset.json()["runs"]] == ["run-a4"]

    by_model = client.get("/v1/runs?project_slug=alpha&model=gpt-4o", headers=_ui("owner@example.com"))
    assert {run["id"] for run in by_model.json()["runs"]} == {"run-a1", "run-a2", "run-a3"}

    by_owner = client.get(
        "/v1/runs?project_slug=alpha&owner=member@example.com", headers=_ui("owner@example.com")
    )
    assert [run["id"] for run in by_owner.json()["runs"]] == ["run-a4"]

    by_q = client.get("/v1/runs?project_slug=alpha&q=improved", headers=_ui("owner@example.com"))
    assert [run["id"] for run in by_q.json()["runs"]] == ["run-a2"]

    needs_review = client.get("/v1/runs?project_slug=alpha&needs_review=true", headers=_ui("owner@example.com"))
    assert [run["id"] for run in needs_review.json()["runs"]] == ["run-a3"]

    sort_asc = client.get("/v1/runs?project_slug=alpha&sort=created_at", headers=_ui("owner@example.com"))
    assert [run["id"] for run in sort_asc.json()["runs"]] == ["run-a1", "run-a2", "run-a3", "run-a4"]

    invalid_sort = client.get("/v1/runs?project_slug=alpha&sort=bogus", headers=_ui("owner@example.com"))
    assert invalid_sort.status_code == 400

    missing_project = client.get("/v1/runs", headers=_ui("owner@example.com"))
    assert missing_project.status_code == 400


def test_list_runs_negative_limit_rejected(client, seeded) -> None:
    response = client.get("/v1/runs?project_slug=alpha&limit=-5", headers=_ui("owner@example.com"))
    assert response.status_code == 422

    too_big = client.get("/v1/runs?project_slug=alpha&limit=201", headers=_ui("owner@example.com"))
    assert too_big.status_code == 422


# ---------------------------------------------------------------------------
# Cross-project access denied for every endpoint
# ---------------------------------------------------------------------------

def test_cross_project_access_denied_everywhere(client, seeded) -> None:
    headers = _ui("member@example.com")  # member of project A only
    cases = [
        ("GET", "/v1/runs?project_slug=beta", None),
        ("GET", "/v1/runs?project_id=proj-b", None),
        ("GET", "/v1/runs/run-b1", None),
        ("GET", "/v1/runs/run-b1/items", None),
        ("GET", "/v1/runs/run-b1/items/x1", None),
        ("PATCH", "/v1/runs/run-b1", {"display_name": "Hijack"}),
        ("GET", "/v1/projects/proj-b/overview-stats", None),
        ("GET", "/v1/projects/proj-b/trends?task=qa", None),
        ("GET", "/v1/reviews/queue?project_slug=beta", None),
    ]
    for method, url, body in cases:
        response = client.request(method, url, json=body, headers=headers)
        assert response.status_code == 403, f"{method} {url} -> {response.status_code}: {response.text}"


def test_api_key_principal_is_project_bound(client, seeded) -> None:
    ok = client.get("/v1/runs?project_id=proj-a", headers=_bearer(API_TOKEN_A))
    assert ok.status_code == 200
    assert ok.json()["total"] == 4

    denied = client.get("/v1/runs?project_id=proj-b", headers=_bearer(API_TOKEN_A))
    assert denied.status_code == 403

    run_denied = client.get("/v1/runs/run-b1", headers=_bearer(API_TOKEN_A))
    assert run_denied.status_code == 403


# ---------------------------------------------------------------------------
# Rename
# ---------------------------------------------------------------------------

def test_rename_permission_matrix(client, seeded, session_factory) -> None:
    owner_ok = client.patch(
        "/v1/runs/run-a1", json={"display_name": "Renamed by owner"}, headers=_ui("owner@example.com")
    )
    assert owner_ok.status_code == 200, owner_ok.text
    assert owner_ok.json() == {"id": "run-a1", "name": "Renamed by owner"}

    member_denied = client.patch(
        "/v1/runs/run-a1", json={"display_name": "Renamed by member"}, headers=_ui("member@example.com")
    )
    assert member_denied.status_code == 403

    manager_ok = client.patch(
        "/v1/runs/run-a1", json={"display_name": "Renamed by manager"}, headers=_ui("manager@example.com")
    )
    assert manager_ok.status_code == 200

    # Rename persists to run_config.run_name, so it is visible everywhere.
    with session_factory() as session:
        run = session.query(Run).filter(Run.id == "run-a1").first()
        assert run is not None
        assert run.run_config.get("run_name") == "Renamed by manager"

    listed = client.get("/v1/runs?project_slug=alpha&q=manager", headers=_ui("owner@example.com"))
    assert [run["id"] for run in listed.json()["runs"]] == ["run-a1"]

    legacy = client.get("/api/runs/run-a1", headers=_ui("owner@example.com"))
    assert legacy.status_code == 200
    assert legacy.json()["run"]["run_name"] == "Renamed by manager"


def test_rename_validation(client, seeded) -> None:
    too_long = client.patch(
        "/v1/runs/run-a1", json={"display_name": "x" * 201}, headers=_ui("owner@example.com")
    )
    assert too_long.status_code == 422

    empty = client.patch("/v1/runs/run-a1", json={"display_name": ""}, headers=_ui("owner@example.com"))
    assert empty.status_code == 422

    blank = client.patch("/v1/runs/run-a1", json={"display_name": "   "}, headers=_ui("owner@example.com"))
    assert blank.status_code == 422


# ---------------------------------------------------------------------------
# Run detail + approval context
# ---------------------------------------------------------------------------

def test_run_detail_shape(client, seeded) -> None:
    response = client.get("/v1/runs/run-a1", headers=_ui("owner@example.com"))
    assert response.status_code == 200
    detail = response.json()
    assert detail["id"] == "run-a1"
    assert detail["name"] == "Baseline Run"
    assert detail["metrics"] == ["judge"]
    assert detail["run_config"]["run_name"] == "Baseline Run"
    assert detail["error_summary"]["task_errors"] == 1
    assert detail["error_summary"]["types"] == {"ValueError: boom": 1}
    judge_stats = next(stat for stat in detail["metric_stats"] if stat["name"] == "judge")
    assert judge_stats["avg"] == pytest.approx(0.5)
    assert judge_stats["pass_count"] == 2  # 1.0 and 0.5 both >= 0.5
    assert judge_stats["fail_count"] == 1  # the errored item
    assert sum(bucket["count"] for bucket in judge_stats["distribution"]) == 2
    assert detail["approval"] is None

    missing = client.get("/v1/runs/does-not-exist", headers=_ui("owner@example.com"))
    assert missing.status_code == 404


def test_run_detail_metadata_is_sanitized(client, seeded, session_factory) -> None:
    with session_factory() as session:
        run = session.query(Run).filter(Run.id == "run-a1").first()
        run.run_metadata = {
            "total_items": 3,
            "openai_api_key": "sk-secret",
            "auth_token": "abc",
            "langfuse_url": "https://lf/project/p1",
        }
        session.commit()

    response = client.get("/v1/runs/run-a1", headers=_ui("owner@example.com"))
    assert response.status_code == 200
    metadata = response.json()["run_metadata"]
    assert "openai_api_key" not in metadata
    assert "auth_token" not in metadata
    assert metadata["langfuse_url"] == "https://lf/project/p1"


def test_approval_context_after_reject_and_approve(client, seeded) -> None:
    # Owner submits run-a2, manager rejects with a reason.
    submitted = client.post("/v1/runs/run-a2/submit", headers=_ui("owner@example.com"))
    assert submitted.status_code == 200, submitted.text
    rejected = client.post(
        "/v1/runs/run-a2/reject", json={"comment": "needs more data"}, headers=_ui("manager@example.com")
    )
    assert rejected.status_code == 200, rejected.text

    detail = client.get("/v1/runs/run-a2", headers=_ui("owner@example.com")).json()
    assert detail["status"] == "REJECTED"
    approval = detail["approval"]
    assert approval["status"] == "REJECTED"
    assert approval["comment"] == "needs more data"
    assert approval["decided_by"]["email"] == "manager@example.com"
    assert approval["decided_at"]
    assert approval["submitted_by"]["email"] == "owner@example.com"

    # run-a3 is seeded as SUBMITTED; manager approves it.
    approved = client.post(
        "/v1/runs/run-a3/approve", json={"comment": "lgtm"}, headers=_ui("manager@example.com")
    )
    assert approved.status_code == 200, approved.text
    detail3 = client.get("/v1/runs/run-a3", headers=_ui("owner@example.com")).json()
    assert detail3["approval"]["status"] == "APPROVED"
    assert detail3["approval"]["comment"] == "lgtm"


# ---------------------------------------------------------------------------
# Items: slim shape, filters, sorting
# ---------------------------------------------------------------------------

def test_items_slim_shape(client, seeded) -> None:
    response = client.get("/v1/runs/run-a1/items", headers=_ui("owner@example.com"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["limit"] == 100
    assert [item["item_id"] for item in payload["items"]] == ["i1", "i2", "i3"]

    first = payload["items"][0]
    # Slim rows must not carry full bodies.
    for forbidden in ("input", "output", "expected", "input_full", "output_full", "item_metadata"):
        assert forbidden not in first
    assert first["has_trace"] is True
    assert first["metric_values"] == {"judge": 1.0}
    assert first["status"] == "completed"

    truncated = payload["items"][1]
    assert len(truncated["input_preview"]) <= 200
    assert len(truncated["output_preview"]) <= 200
    assert truncated["root_cause"] == "Wrong Format"
    assert truncated["root_cause_source"] == "human"

    failed = payload["items"][2]
    assert failed["status"] == "failed"
    assert failed["retry_count"] == 2
    assert failed["has_trace"] is False


def test_items_filters_and_sorting(client, seeded) -> None:
    failed_only = client.get("/v1/runs/run-a1/items?failed_only=true", headers=_ui("owner@example.com"))
    assert failed_only.status_code == 200
    assert [item["item_id"] for item in failed_only.json()["items"]] == ["i3"]
    assert failed_only.json()["total"] == 1

    completed = client.get("/v1/runs/run-a1/items?status=completed", headers=_ui("owner@example.com"))
    assert {item["item_id"] for item in completed.json()["items"]} == {"i1", "i2"}

    invalid_status = client.get("/v1/runs/run-a1/items?status=bogus", headers=_ui("owner@example.com"))
    assert invalid_status.status_code == 400

    by_q = client.get("/v1/runs/run-a1/items?q=2%2B2", headers=_ui("owner@example.com"))
    assert [item["item_id"] for item in by_q.json()["items"]] == ["i1"]

    below = client.get(
        "/v1/runs/run-a1/items?metric=judge&below=0.6", headers=_ui("owner@example.com")
    )
    assert [item["item_id"] for item in below.json()["items"]] == ["i2"]

    below_without_metric = client.get("/v1/runs/run-a1/items?below=0.6", headers=_ui("owner@example.com"))
    assert below_without_metric.status_code == 400

    by_latency_desc = client.get("/v1/runs/run-a1/items?sort=-latency", headers=_ui("owner@example.com"))
    assert [item["item_id"] for item in by_latency_desc.json()["items"]] == ["i1", "i2", "i3"]

    by_score = client.get(
        "/v1/runs/run-a1/items?sort=score&metric=judge&status=completed", headers=_ui("owner@example.com")
    )
    assert [item["item_id"] for item in by_score.json()["items"]] == ["i2", "i1"]

    score_without_metric = client.get("/v1/runs/run-a1/items?sort=score", headers=_ui("owner@example.com"))
    assert score_without_metric.status_code == 400

    paged = client.get("/v1/runs/run-a1/items?limit=1&offset=1", headers=_ui("owner@example.com"))
    assert [item["item_id"] for item in paged.json()["items"]] == ["i2"]
    assert paged.json()["total"] == 3

    negative_limit = client.get("/v1/runs/run-a1/items?limit=-1", headers=_ui("owner@example.com"))
    assert negative_limit.status_code == 422


# ---------------------------------------------------------------------------
# Item detail
# ---------------------------------------------------------------------------

def test_item_detail_full_bodies(client, seeded) -> None:
    response = client.get("/v1/runs/run-a1/items/i2", headers=_ui("owner@example.com"))
    assert response.status_code == 200
    detail = response.json()
    assert detail["item_id"] == "i2"
    assert len(detail["input"]) > 200  # full body, not a preview
    assert detail["expected"] == "short"
    assert detail["metric_values"] == {"judge": 0.5}
    assert detail["item_metadata"]["root_cause"] == "Wrong Format"
    assert detail["trace"]["has_trace"] is False

    with_trace = client.get("/v1/runs/run-a1/items/i1", headers=_ui("owner@example.com")).json()
    assert with_trace["trace"] == {"has_trace": True, "trace_id": "trace-1", "trace_url": "http://lf/t/1"}


def test_item_detail_404_for_wrong_run(client, seeded) -> None:
    response = client.get("/v1/runs/run-a2/items/i1", headers=_ui("owner@example.com"))
    assert response.status_code == 404

    missing = client.get("/v1/runs/run-a1/items/nope", headers=_ui("owner@example.com"))
    assert missing.status_code == 404


# ---------------------------------------------------------------------------
# Overview stats
# ---------------------------------------------------------------------------

def test_overview_stats_counts_match_seeded(client, seeded) -> None:
    response = client.get("/v1/projects/proj-a/overview-stats", headers=_ui("owner@example.com"))
    assert response.status_code == 200
    stats = response.json()
    assert stats["project_id"] == "proj-a"
    assert stats["total_runs"] == 4
    assert stats["by_status"] == {"COMPLETED": 2, "SUBMITTED": 1, "RUNNING": 1}
    assert stats["models"] == ["gpt-4o"]
    assert stats["total_items"] == 6
    # Avg over scored non-error items of finished runs: (1.0 + 0.5 + 1.0 + 1.0) / 4
    assert stats["metric_averages"]["judge"] == pytest.approx(0.875)
    assert stats["last_run_at"]

    by_slug = client.get("/v1/projects/alpha/overview-stats", headers=_ui("owner@example.com"))
    assert by_slug.status_code == 200
    assert by_slug.json() == stats


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------

def test_trends_returns_ordered_points(client, seeded) -> None:
    response = client.get("/v1/projects/proj-a/trends?task=qa", headers=_ui("owner@example.com"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["task"] == "qa"
    assert payload["group_by"] == "model"
    assert len(payload["series"]) == 1
    series = payload["series"][0]
    assert series["group"] == "gpt-4o"
    assert series["metric"] == "judge"
    # Only finished runs (a1, a2) in chronological order; SUBMITTED a3 excluded.
    assert [point["run_id"] for point in series["points"]] == ["run-a1", "run-a2"]
    assert [point["value"] for point in series["points"]] == [pytest.approx(0.5), pytest.approx(1.0)]
    assert [point["n_items"] for point in series["points"]] == [3, 2]
    dates = [point["date"] for point in series["points"]]
    assert dates == sorted(dates)

    filtered = client.get(
        "/v1/projects/proj-a/trends?task=qa&dataset=other", headers=_ui("owner@example.com")
    )
    assert filtered.status_code == 200
    assert filtered.json()["series"] == []

    invalid_group = client.get(
        "/v1/projects/proj-a/trends?task=qa&group_by=bogus", headers=_ui("owner@example.com")
    )
    assert invalid_group.status_code == 400

    missing_task = client.get("/v1/projects/proj-a/trends", headers=_ui("owner@example.com"))
    assert missing_task.status_code == 422


# ---------------------------------------------------------------------------
# Reviews queue
# ---------------------------------------------------------------------------

def test_reviews_queue_lists_submitted_with_baseline_delta(client, seeded) -> None:
    response = client.get("/v1/reviews/queue?project_slug=alpha", headers=_ui("manager@example.com"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    entry = payload["entries"][0]
    assert entry["run"]["id"] == "run-a3"
    assert entry["run"]["status"] == "SUBMITTED"
    # Baseline = latest finished run with same task+dataset+model = run-a2 (avg 1.0).
    assert entry["baseline_run_id"] == "run-a2"
    assert entry["baseline_delta"]["judge"] == pytest.approx(0.75 - 1.0)

    empty = client.get("/v1/reviews/queue?project_slug=beta", headers=_ui("owner-b@example.com"))
    assert empty.status_code == 200
    assert empty.json() == {"entries": [], "total": 0}
