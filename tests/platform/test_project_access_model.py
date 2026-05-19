from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("QYM_AUTH_MODE", "proxy_headers")
os.environ.setdefault("QYM_LLM_CONFIG_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
ROOT = Path(__file__).resolve().parents[2]
PLATFORM_SRC = ROOT / "packages" / "platform"
SDK_SRC = ROOT / "packages" / "sdk"
for src in (PLATFORM_SRC, SDK_SRC):
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

from qym_platform.app import create_app
from qym_platform.db.base import Base
from qym_platform.db.models import (
    ApiKey,
    Approval,
    ApprovalDecision,
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


@pytest.fixture()
def session_factory(monkeypatch):
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("QYM_AUTH_MODE", "proxy_headers")
    monkeypatch.setenv("QYM_LLM_CONFIG_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
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


def _headers(email: str) -> dict[str, str]:
    return {"X-User-Email": email, "Origin": "http://localhost:8000"}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_project_world(session: Session) -> dict[str, str]:
    admin = User(id="admin-1", email="admin@example.com", role=UserRole.ADMIN)
    manager = User(id="manager-1", email="manager@example.com", role=UserRole.MEMBER)
    member = User(id="member-1", email="member@example.com", role=UserRole.MEMBER)
    outsider = User(id="outsider-1", email="outsider@example.com", role=UserRole.MEMBER)
    candidate = User(id="candidate-1", email="candidate@example.com", role=UserRole.MEMBER)

    project_one = Project(
        id="project-1",
        name="Project One",
        slug="project-one",
        description="Primary project",
        created_by_user_id=admin.id,
        is_active=True,
    )
    project_two = Project(
        id="project-2",
        name="Project Two",
        slug="project-two",
        description="Other project",
        created_by_user_id=admin.id,
        is_active=True,
    )

    session.add_all([admin, manager, member, outsider, candidate, project_one, project_two])
    session.flush()

    session.add_all(
        [
            ProjectMembership(project_id=project_one.id, user_id=manager.id, role=ProjectRole.MANAGER, added_by_user_id=admin.id),
            ProjectMembership(project_id=project_one.id, user_id=member.id, role=ProjectRole.MEMBER, added_by_user_id=admin.id),
            ProjectMembership(project_id=project_two.id, user_id=outsider.id, role=ProjectRole.MANAGER, added_by_user_id=admin.id),
        ]
    )

    editable_run = Run(
        id="run-editable",
        project_id=project_one.id,
        created_by_user_id=member.id,
        owner_user_id=member.id,
        task="task-a",
        dataset="dataset-a",
        metrics=["judge"],
        run_metadata={},
        run_config={"run_name": "Editable Run"},
        status=RunWorkflowStatus.COMPLETED,
    )
    submitted_run = Run(
        id="run-submitted",
        project_id=project_one.id,
        created_by_user_id=member.id,
        owner_user_id=member.id,
        task="task-a",
        dataset="dataset-a",
        metrics=["judge"],
        run_metadata={},
        run_config={"run_name": "Submitted Run"},
        status=RunWorkflowStatus.SUBMITTED,
    )
    manager_owned_run = Run(
        id="run-manager-owned",
        project_id=project_one.id,
        created_by_user_id=manager.id,
        owner_user_id=manager.id,
        task="task-a",
        dataset="dataset-a",
        metrics=["judge"],
        run_metadata={},
        run_config={"run_name": "Manager Owned"},
        status=RunWorkflowStatus.SUBMITTED,
    )
    deletable_run = Run(
        id="run-delete",
        project_id=project_one.id,
        created_by_user_id=member.id,
        owner_user_id=member.id,
        task="task-a",
        dataset="dataset-a",
        metrics=["judge"],
        run_metadata={},
        run_config={"run_name": "Delete Me"},
        status=RunWorkflowStatus.COMPLETED,
    )
    rejected_run = Run(
        id="run-rejected",
        project_id=project_one.id,
        created_by_user_id=member.id,
        owner_user_id=member.id,
        task="task-a",
        dataset="dataset-a",
        metrics=["judge"],
        run_metadata={},
        run_config={"run_name": "Rejected Run"},
        status=RunWorkflowStatus.REJECTED,
    )

    session.add_all(
        [
            editable_run,
            submitted_run,
            manager_owned_run,
            deletable_run,
            rejected_run,
            RunItem(
                run_id=editable_run.id,
                item_id="item-1",
                index=0,
                input={"prompt": "hello"},
                expected={"answer": "world"},
                output={"answer": "nope"},
                item_metadata={},
            ),
            RunItemScore(
                run_id=editable_run.id,
                item_id="item-1",
                metric_name="judge",
                score_numeric=0.2,
                score_raw=0.2,
                meta={},
            ),
            Approval(run_id=submitted_run.id, submitted_by_user_id=member.id),
            Approval(run_id=manager_owned_run.id, submitted_by_user_id=manager.id),
            Approval(
                run_id=rejected_run.id,
                submitted_by_user_id=member.id,
                decision_by_user_id=manager.id,
                decision=ApprovalDecision.REJECTED,
                comment="needs changes",
            ),
        ]
    )

    token = "project-one-token"
    session.add(
        ApiKey(
            id="key-1",
            user_id=member.id,
            project_id=project_one.id,
            name="project-one",
            prefix=api_key_prefix(token),
            key_hash=hash_api_key(token),
            scopes=["runs:write", "runs:read"],
        )
    )
    session.commit()
    return {"project_one_id": project_one.id, "token": token, "candidate_id": candidate.id}


def test_project_member_visibility_and_mutation_are_project_scoped(client, session_factory):
    with session_factory() as session:
        _seed_project_world(session)

    member_resp = client.post(
        "/api/runs/update_metric",
        headers=_headers("member@example.com"),
        json={"file_path": "run-editable", "row_index": 0, "metric_name": "judge", "new_score": 0.9},
    )
    assert member_resp.status_code == 200

    manager_resp = client.post(
        "/api/runs/update_metric",
        headers=_headers("manager@example.com"),
        json={"file_path": "run-editable", "row_index": 0, "metric_name": "judge", "new_score": 0.7},
    )
    assert manager_resp.status_code == 200

    outsider_resp = client.post(
        "/api/runs/update_metric",
        headers=_headers("outsider@example.com"),
        json={"file_path": "run-editable", "row_index": 0, "metric_name": "judge", "new_score": 0.1},
    )
    assert outsider_resp.status_code == 403

    owner_delete = client.post(
        "/api/runs/delete",
        headers=_headers("member@example.com"),
        json={"file_path": "run-delete"},
    )
    assert owner_delete.status_code == 200


def test_project_approval_rules_allow_manager_self_approval_and_last_manager_guard(client, session_factory):
    with session_factory() as session:
        seed = _seed_project_world(session)

    member_approve = client.post(
        "/v1/runs/run-submitted/approve",
        headers=_headers("member@example.com"),
        json={"comment": "ship it"},
    )
    assert member_approve.status_code == 403

    manager_self_approve = client.post(
        "/v1/runs/run-manager-owned/approve",
        headers=_headers("manager@example.com"),
        json={"comment": "self approve"},
    )
    assert manager_self_approve.status_code == 200

    admin_approve = client.post(
        "/v1/runs/run-submitted/approve",
        headers=_headers("admin@example.com"),
        json={"comment": "approved"},
    )
    assert admin_approve.status_code == 200

    add_member = client.post(
        f"/v1/projects/{seed['project_one_id']}/members",
        headers=_headers("manager@example.com"),
        json={"user_id": seed["candidate_id"], "role": "MEMBER"},
    )
    assert add_member.status_code == 200

    remove_last_manager = client.delete(
        f"/v1/projects/{seed['project_one_id']}/members/manager-1",
        headers=_headers("manager@example.com"),
    )
    assert remove_last_manager.status_code == 400


def test_project_manager_or_admin_can_clear_review_decision_to_completed(client, session_factory):
    with session_factory() as session:
        _seed_project_world(session)

    approve_response = client.post(
        "/v1/runs/run-submitted/approve",
        headers=_headers("admin@example.com"),
        json={"comment": "approved"},
    )
    assert approve_response.status_code == 200

    member_unapprove = client.post(
        "/v1/runs/run-submitted/unapprove",
        headers=_headers("member@example.com"),
        json={},
    )
    assert member_unapprove.status_code == 403

    manager_unapprove = client.post(
        "/v1/runs/run-submitted/unapprove",
        headers=_headers("manager@example.com"),
        json={},
    )
    assert manager_unapprove.status_code == 200
    assert manager_unapprove.json()["status"] == "COMPLETED"

    with session_factory() as session:
        run = session.get(Run, "run-submitted")
        approval = session.query(Approval).filter(Approval.run_id == "run-submitted").one()
        assert run.status == RunWorkflowStatus.COMPLETED
        assert approval.decision is None
        assert approval.decision_by_user_id is None
        assert approval.decision_at is None
        assert approval.comment == ""

    member_unreject = client.post(
        "/v1/runs/run-rejected/unreject",
        headers=_headers("member@example.com"),
        json={},
    )
    assert member_unreject.status_code == 403

    manager_unreject = client.post(
        "/v1/runs/run-rejected/unreject",
        headers=_headers("manager@example.com"),
        json={},
    )
    assert manager_unreject.status_code == 200
    assert manager_unreject.json()["status"] == "COMPLETED"

    with session_factory() as session:
        run = session.get(Run, "run-rejected")
        approval = session.query(Approval).filter(Approval.run_id == "run-rejected").one()
        assert run.status == RunWorkflowStatus.COMPLETED
        assert approval.decision is None
        assert approval.decision_by_user_id is None
        assert approval.decision_at is None
        assert approval.comment == ""


def test_project_runs_can_be_filtered_to_approved_status(client, session_factory):
    with session_factory() as session:
        _seed_project_world(session)

    approve_response = client.post(
        "/v1/runs/run-submitted/approve",
        headers=_headers("admin@example.com"),
        json={"comment": "approved"},
    )
    assert approve_response.status_code == 200

    response = client.get(
        "/api/runs?project_slug=project-one&status=APPROVED",
        headers=_headers("member@example.com"),
    )
    assert response.status_code == 200
    payload = response.json()
    runs = [
        run
        for models in payload["tasks"].values()
        for run_list in models.values()
        for run in run_list
    ]
    assert payload["total_count"] == 1
    assert [run["run_id"] for run in runs] == ["run-submitted"]
    assert runs[0]["status"] == "APPROVED"


def test_rejected_run_can_be_resubmitted_and_clears_previous_decision(client, session_factory):
    with session_factory() as session:
        _seed_project_world(session)

    response = client.post(
        "/v1/runs/run-rejected/submit",
        headers=_headers("member@example.com"),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "SUBMITTED"

    with session_factory() as session:
        run = session.get(Run, "run-rejected")
        approval = session.query(Approval).filter(Approval.run_id == "run-rejected").one()
        assert run.status == RunWorkflowStatus.SUBMITTED
        assert approval.decision is None
        assert approval.decision_by_user_id is None
        assert approval.decision_at is None
        assert approval.comment == ""


def test_project_scoped_api_key_creates_project_bound_run(client, session_factory):
    with session_factory() as session:
        seed = _seed_project_world(session)

    create_resp = client.post(
        "/v1/runs",
        headers=_bearer(seed["token"]),
        json={
            "external_run_id": "sdk-run-1",
            "task": "sdk-task",
            "dataset": "sdk-dataset",
            "model": "openai/gpt-4.1-mini",
            "metrics": ["accuracy"],
            "run_metadata": {},
            "run_config": {"run_name": "SDK Run"},
        },
    )
    assert create_resp.status_code == 200
    payload = create_resp.json()
    assert "/projects/project-one/runs/" in payload["live_url"]

    with session_factory() as session:
        created = session.query(Run).filter(Run.external_run_id == "sdk-run-1").first()
        assert created is not None
        assert created.project_id == seed["project_one_id"]
        assert created.owner_user_id == "member-1"


def test_projects_and_me_include_project_summary_fields(client, session_factory):
    with session_factory() as session:
        seed = _seed_project_world(session)

    projects_response = client.get("/v1/projects", headers=_headers("manager@example.com"))
    assert projects_response.status_code == 200
    projects = projects_response.json()["projects"]
    assert len(projects) == 1
    project = projects[0]
    assert project["id"] == seed["project_one_id"]
    assert project["description"] == "Primary project"
    assert project["member_count"] == 2
    assert project["run_count"] == 4
    assert project["role"] == "MANAGER"

    me_response = client.get("/v1/me", headers=_headers("manager@example.com"))
    assert me_response.status_code == 200
    me = me_response.json()
    assert me["projects"][0]["description"] == "Primary project"
    assert me["projects"][0]["member_count"] == 2
    assert me["projects"][0]["run_count"] == 4
    assert me["default_project"]["slug"] == "project-one"
