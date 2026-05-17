from __future__ import annotations

import json
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
from qym_platform.db.models import ApiKey, Project, ProjectMembership, ProjectRole, Run, RunItem, RunItemScore, RunWorkflowStatus, User, UserRole
from qym_platform.deps import get_db
from qym_platform.security import api_key_prefix, hash_api_key


@pytest.fixture()
def session_factory(monkeypatch):
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("QYM_AUTH_MODE", "proxy_headers")
    monkeypatch.setenv("QYM_ALLOW_LEGACY_EMPTY_API_KEY_SCOPES", "true")
    monkeypatch.setenv("QYM_RUN_STALE_TIMEOUT_SECONDS", "60")
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


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _ui_headers(email: str) -> dict[str, str]:
    return {"X-User-Email": email}


def _seed_run(session: Session, *, token: str = "test-token", run_id: str = "run-1") -> Run:
    suffix = run_id.split("-")[-1].replace("_", "")
    owner = User(id=f"user-{suffix}", email="owner@example.com", role=UserRole.MEMBER)
    admin = User(id=f"admin-{suffix}", email="admin@example.com", role=UserRole.ADMIN)
    project = Project(id=f"project-{suffix}", name="Project 1", slug=f"project-{suffix}", created_by_user_id=owner.id)
    membership = ProjectMembership(project_id=project.id, user_id=owner.id, role=ProjectRole.MANAGER)
    api_key = ApiKey(
        id=f"key-{suffix}",
        user_id=owner.id,
        project_id=project.id,
        name="test",
        prefix=api_key_prefix(token),
        key_hash=hash_api_key(token),
        scopes=[],
    )
    run = Run(
        id=run_id,
        project_id=project.id,
        created_by_user_id=owner.id,
        owner_user_id=owner.id,
        task="task-1",
        dataset="dataset-1",
        metrics=[],
        status=RunWorkflowStatus.RUNNING,
        run_metadata={},
        run_config={},
        started_at=utc_now_naive(),
        last_event_at=utc_now_naive(),
    )
    session.add_all([owner, admin, project, membership, api_key, run])
    session.commit()
    return run


def _post_events(client: TestClient, run_id: str, token: str, events: list[dict]) -> None:
    body = "\n".join(json.dumps(event) for event in events)
    response = client.post(
        f"/v1/runs/{run_id}/events",
        content=body,
        headers=_auth_headers(token),
    )
    assert response.status_code == 200, response.text


def _event(*, event_id: str, sequence: int, run_id: str, type_: str, payload: dict, sent_at: str = "2026-04-10T00:00:00Z") -> dict:
    return {
        "schema_version": 1,
        "event_id": event_id,
        "sequence": sequence,
        "sent_at": sent_at,
        "type": type_,
        "run_id": run_id,
        "payload": payload,
    }


def test_late_run_started_does_not_reopen_explicitly_stopped_run(client, session_factory) -> None:
    run_id = "00000000-0000-0000-0000-000000000101"
    token = "test-token"
    with session_factory() as session:
        _seed_run(session, token=token, run_id=run_id)

    _post_events(
        client,
        run_id,
        token,
        [
            _event(
                event_id="00000000-0000-0000-0000-000000000001",
                sequence=2,
                run_id=run_id,
                type_="run_completed",
                payload={"ended_at": "2026-04-10T00:00:05Z", "summary": {}, "final_status": "STOPPED"},
            )
        ],
    )
    _post_events(
        client,
        run_id,
        token,
        [
            _event(
                event_id="00000000-0000-0000-0000-000000000002",
                sequence=1,
                run_id=run_id,
                type_="run_started",
                payload={
                    "external_run_id": "late-start",
                    "task": "task-1",
                    "dataset": "dataset-1",
                    "model": None,
                    "metrics": [],
                    "run_metadata": {},
                    "run_config": {},
                    "started_at": "2026-04-10T00:00:00Z",
                },
            )
        ],
    )

    with session_factory() as session:
        run = session.query(Run).filter(Run.id == run_id).first()
        assert run is not None
        assert run.status == RunWorkflowStatus.STOPPED
        assert run.status_reason is None


def test_late_run_completed_does_not_override_explicit_product_eval_stop(
    client, session_factory
) -> None:
    run_id = "00000000-0000-0000-0000-000000000111"
    token = "test-token"
    with session_factory() as session:
        run = _seed_run(session, token=token, run_id=run_id)
        run.status = RunWorkflowStatus.STOPPED
        run.status_reason = "product_eval_stopped"
        session.commit()

    _post_events(
        client,
        run_id,
        token,
        [
            _event(
                event_id="00000000-0000-0000-0000-000000000011",
                sequence=2,
                run_id=run_id,
                type_="run_completed",
                payload={
                    "ended_at": "2026-04-10T00:00:05Z",
                    "summary": {},
                    "final_status": "COMPLETED",
                },
            )
        ],
    )

    with session_factory() as session:
        run = session.query(Run).filter(Run.id == run_id).first()
        assert run is not None
        assert run.status == RunWorkflowStatus.STOPPED
        assert run.status_reason == "product_eval_stopped"


def test_stale_running_run_is_reconciled_to_stopped_in_list_api(client, session_factory) -> None:
    run_id = "00000000-0000-0000-0000-000000000102"
    with session_factory() as session:
        run = _seed_run(session, run_id=run_id)
        old_time = utc_now_naive() - timedelta(minutes=5)
        run.started_at = old_time
        run.last_event_at = old_time
        session.commit()

    response = client.get("/api/runs", headers=_ui_headers("admin@example.com"))
    assert response.status_code == 200
    payload = response.json()
    summaries = payload["tasks"]["task-1"]["nomodel"]
    assert summaries[0]["status"] == "STOPPED"

    with session_factory() as session:
        run = session.query(Run).filter(Run.id == run_id).first()
        assert run is not None
        assert run.status == RunWorkflowStatus.STOPPED
        assert run.status_reason == "lease_timeout"


def test_runs_list_includes_median_latency(client, session_factory) -> None:
    run_id = "00000000-0000-0000-0000-000000000104"
    with session_factory() as session:
        _seed_run(session, run_id=run_id)
        session.add_all([
            RunItem(run_id=run_id, item_id="item-1", index=0, input={}, latency_ms=100.0, output="ok"),
            RunItem(run_id=run_id, item_id="item-2", index=1, input={}, latency_ms=400.0, output="ok"),
            RunItem(run_id=run_id, item_id="item-3", index=2, input={}, latency_ms=900.0, output="ok"),
        ])
        session.commit()

    response = client.get("/api/runs", headers=_ui_headers("admin@example.com"))
    assert response.status_code == 200
    payload = response.json()
    summaries = payload["tasks"]["task-1"]["nomodel"]
    summary = next(item for item in summaries if item["run_id"] == run_id)
    assert summary["avg_latency_ms"] == pytest.approx((100.0 + 400.0 + 900.0) / 3)
    assert summary["median_latency_ms"] == pytest.approx(400.0)


def test_runs_list_includes_total_retries(client, session_factory) -> None:
    run_id = "00000000-0000-0000-0000-000000000105"
    with session_factory() as session:
        _seed_run(session, run_id=run_id)
        session.add_all([
            RunItem(run_id=run_id, item_id="item-1", index=0, input={}, retry_count=0, output="ok"),
            RunItem(run_id=run_id, item_id="item-2", index=1, input={}, retry_count=2, output="ok"),
            RunItem(run_id=run_id, item_id="item-3", index=2, input={}, retry_count=3, error="boom"),
        ])
        session.commit()

    response = client.get("/api/runs", headers=_ui_headers("admin@example.com"))
    assert response.status_code == 200
    payload = response.json()
    summaries = payload["tasks"]["task-1"]["nomodel"]
    summary = next(item for item in summaries if item["run_id"] == run_id)
    assert summary["total_retries"] == 5


def test_runs_list_metric_average_excludes_in_flight_unscored_items(client, session_factory) -> None:
    run_id = "00000000-0000-0000-0000-000000000106"
    with session_factory() as session:
        run = _seed_run(session, run_id=run_id)
        run.metrics = ["judge"]
        session.add_all([
            RunItem(run_id=run_id, item_id="item-1", index=0, input={}, output="ok"),
            RunItem(run_id=run_id, item_id="item-2", index=1, input={"q": "still running"}),
            RunItem(run_id=run_id, item_id="item-3", index=2, input={}, error="boom"),
            RunItemScore(run_id=run_id, item_id="item-1", metric_name="judge", score_numeric=1.0, score_raw=1.0),
        ])
        session.commit()

    response = client.get("/api/runs", headers=_ui_headers("admin@example.com"))
    assert response.status_code == 200
    payload = response.json()
    summaries = payload["tasks"]["task-1"]["nomodel"]
    summary = next(item for item in summaries if item["run_id"] == run_id)
    assert summary["metric_averages"]["judge"] == pytest.approx(0.5)


def test_runs_list_can_filter_by_owner_user(client, session_factory) -> None:
    with session_factory() as session:
        owner_a = User(id="owner-a", email="owner-a@example.com", display_name="Owner A", role=UserRole.MEMBER)
        owner_b = User(id="owner-b", email="owner-b@example.com", display_name="Owner B", role=UserRole.MEMBER)
        admin = User(id="admin-filter", email="admin-filter@example.com", role=UserRole.ADMIN)
        project = Project(id="project-filter", name="Project Filter", slug="project-filter", created_by_user_id=admin.id)
        session.add_all([
            owner_a,
            owner_b,
            admin,
            project,
            ProjectMembership(project_id=project.id, user_id=owner_a.id, role=ProjectRole.MEMBER),
            ProjectMembership(project_id=project.id, user_id=owner_b.id, role=ProjectRole.MEMBER),
            Run(
                id="run-owner-a",
                project_id=project.id,
                created_by_user_id=owner_a.id,
                owner_user_id=owner_a.id,
                task="task-a",
                dataset="dataset",
                metrics=[],
                status=RunWorkflowStatus.COMPLETED,
                run_metadata={},
                run_config={},
            ),
            Run(
                id="run-owner-b",
                project_id=project.id,
                created_by_user_id=owner_b.id,
                owner_user_id=owner_b.id,
                task="task-b",
                dataset="dataset",
                metrics=[],
                status=RunWorkflowStatus.COMPLETED,
                run_metadata={},
                run_config={},
            ),
        ])
        session.commit()

    by_email = client.get(
        "/api/runs?project_slug=project-filter&user=owner-b@example.com",
        headers=_ui_headers("admin-filter@example.com"),
    )
    assert by_email.status_code == 200
    email_payload = by_email.json()
    assert email_payload["total_count"] == 1
    assert list(email_payload["tasks"].keys()) == ["task-b"]
    assert email_payload["tasks"]["task-b"]["nomodel"][0]["owner"]["id"] == "owner-b"

    by_id = client.get(
        "/api/runs?project_slug=project-filter&owner_user_id=owner-a",
        headers=_ui_headers("admin-filter@example.com"),
    )
    assert by_id.status_code == 200
    id_payload = by_id.json()
    assert id_payload["total_count"] == 1
    assert list(id_payload["tasks"].keys()) == ["task-a"]
    assert id_payload["tasks"]["task-a"]["nomodel"][0]["owner"]["email"] == "owner-a@example.com"


def test_live_runs_endpoint_supports_project_and_admin_views(client, session_factory) -> None:
    with session_factory() as session:
        admin = User(id="admin-live", email="admin-live@example.com", role=UserRole.ADMIN)
        owner_a = User(id="owner-live-a", email="owner-live-a@example.com", display_name="Owner A", role=UserRole.MEMBER)
        owner_b = User(id="owner-live-b", email="owner-live-b@example.com", display_name="Owner B", role=UserRole.MEMBER)
        project_a = Project(id="project-live-a", name="Live A", slug="live-a", created_by_user_id=admin.id)
        project_b = Project(id="project-live-b", name="Live B", slug="live-b", created_by_user_id=admin.id)
        now = utc_now_naive()
        session.add_all([
            admin,
            owner_a,
            owner_b,
            project_a,
            project_b,
            ProjectMembership(project_id=project_a.id, user_id=owner_a.id, role=ProjectRole.MEMBER),
            ProjectMembership(project_id=project_b.id, user_id=owner_b.id, role=ProjectRole.MEMBER),
            Run(
                id="run-live-a",
                project_id=project_a.id,
                created_by_user_id=owner_a.id,
                owner_user_id=owner_a.id,
                task="task-live",
                dataset="dataset",
                metrics=[],
                status=RunWorkflowStatus.RUNNING,
                run_metadata={"total_items": 2},
                run_config={"run_name": "Project A Live"},
                started_at=now,
                last_event_at=now,
            ),
            Run(
                id="run-live-b",
                project_id=project_b.id,
                created_by_user_id=owner_b.id,
                owner_user_id=owner_b.id,
                task="task-live",
                dataset="dataset",
                metrics=[],
                status=RunWorkflowStatus.PENDING,
                run_metadata={},
                run_config={"run_name": "Project B Pending"},
                started_at=now,
                last_event_at=now,
            ),
            Run(
                id="run-complete-a",
                project_id=project_a.id,
                created_by_user_id=owner_a.id,
                owner_user_id=owner_a.id,
                task="task-live",
                dataset="dataset",
                metrics=[],
                status=RunWorkflowStatus.COMPLETED,
                run_metadata={},
                run_config={"run_name": "Complete"},
                started_at=now,
                last_event_at=now,
            ),
            RunItem(run_id="run-live-a", item_id="item-1", index=0, input={}, output="ok"),
            RunItem(run_id="run-live-a", item_id="item-2", index=1, input={}),
        ])
        session.commit()

    project_response = client.get("/api/runs/live?project_slug=live-a", headers=_ui_headers("owner-live-a@example.com"))
    assert project_response.status_code == 200
    project_payload = project_response.json()
    assert project_payload["total_count"] == 1
    assert [run["run_id"] for run in project_payload["runs"]] == ["run-live-a"]
    assert project_payload["runs"][0]["progress_completed"] == 1
    assert project_payload["runs"][0]["progress_total"] == 2
    assert project_payload["runs"][0]["project"]["slug"] == "live-a"
    assert project_payload["runs"][0]["owner"]["display_name"] == "Owner A"

    denied_response = client.get("/api/runs/live?all_projects=true", headers=_ui_headers("owner-live-a@example.com"))
    assert denied_response.status_code == 403

    admin_response = client.get("/api/runs/live?all_projects=true", headers=_ui_headers("admin-live@example.com"))
    assert admin_response.status_code == 200
    admin_payload = admin_response.json()
    assert admin_payload["total_count"] == 2
    assert {run["run_id"] for run in admin_payload["runs"]} == {"run-live-a", "run-live-b"}
    assert {run["project"]["slug"] for run in admin_payload["runs"]} == {"live-a", "live-b"}
    assert {run["owner"]["display_name"] for run in admin_payload["runs"]} == {"Owner A", "Owner B"}


def test_heartbeat_reopens_run_stopped_by_lease_timeout(client, session_factory) -> None:
    run_id = "00000000-0000-0000-0000-000000000103"
    token = "test-token"
    with session_factory() as session:
        run = _seed_run(session, token=token, run_id=run_id)
        run.status = RunWorkflowStatus.STOPPED
        run.status_reason = "lease_timeout"
        run.ended_at = utc_now_naive()
        old_time = utc_now_naive() - timedelta(minutes=5)
        run.last_event_at = old_time
        session.commit()

    _post_events(
        client,
        run_id,
        token,
        [
            _event(
                event_id="00000000-0000-0000-0000-000000000003",
                sequence=10,
                run_id=run_id,
                type_="run_heartbeat",
                payload={"heartbeat_at": "2026-04-10T00:05:00Z"},
                sent_at="2026-04-10T00:05:00Z",
            )
        ],
    )

    with session_factory() as session:
        run = session.query(Run).filter(Run.id == run_id).first()
        assert run is not None
        assert run.status == RunWorkflowStatus.RUNNING
        assert run.status_reason is None
        assert run.ended_at is None
