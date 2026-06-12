"""Endpoint authorization matrix for the project-based access model.

Covers, per router family, a representative endpoint for:
- unauthenticated requests -> 401
- authenticated non-members -> 403/404 on other projects' resources
- member vs project-manager vs platform-admin permission boundaries
- proxy_headers hardening: shared proxy secret and opt-in auto-provisioning
"""

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
    Dataset,
    Project,
    ProjectLlmConnection,
    ProjectMembership,
    ProjectRole,
    Run,
    RunItem,
    RunItemScore,
    RunWorkflowStatus,
    User,
    UserRole,
)
from qym_platform.datetime_utils import utc_now_naive
from qym_platform.deps import get_db
from qym_platform.security import api_key_prefix, hash_api_key

ADMIN = "admin@example.com"
MANAGER = "manager@example.com"
MEMBER = "member@example.com"
OUTSIDER = "outsider@example.com"

PROJECT_ONE = "project-1"
PROJECT_TWO = "project-2"


@pytest.fixture()
def session_factory(monkeypatch):
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("QYM_AUTH_MODE", "proxy_headers")
    monkeypatch.setenv("QYM_LLM_CONFIG_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
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
    return {"X-User-Email": email}


def _seed_world(session: Session) -> None:
    """Two projects: outsider manages project-2 but has no role in project-1."""
    admin = User(id="admin-1", email=ADMIN, role=UserRole.ADMIN)
    manager = User(id="manager-1", email=MANAGER, role=UserRole.MEMBER)
    member = User(id="member-1", email=MEMBER, role=UserRole.MEMBER)
    outsider = User(id="outsider-1", email=OUTSIDER, role=UserRole.MEMBER)
    candidate = User(id="candidate-1", email="candidate@example.com", role=UserRole.MEMBER)

    project_one = Project(
        id=PROJECT_ONE,
        name="Project One",
        slug="project-one",
        created_by_user_id=admin.id,
    )
    project_two = Project(
        id=PROJECT_TWO,
        name="Project Two",
        slug="project-two",
        created_by_user_id=admin.id,
    )
    session.add_all([admin, manager, member, outsider, candidate, project_one, project_two])
    session.flush()

    session.add_all(
        [
            ProjectMembership(project_id=PROJECT_ONE, user_id=manager.id, role=ProjectRole.MANAGER),
            ProjectMembership(project_id=PROJECT_ONE, user_id=member.id, role=ProjectRole.MEMBER),
            ProjectMembership(project_id=PROJECT_TWO, user_id=outsider.id, role=ProjectRole.MANAGER),
        ]
    )

    run = Run(
        id="run-a",
        project_id=PROJECT_ONE,
        created_by_user_id=member.id,
        owner_user_id=member.id,
        task="task-a",
        dataset="dataset-a",
        metrics=["judge"],
        run_metadata={},
        run_config={"run_name": "Run A"},
        status=RunWorkflowStatus.COMPLETED,
    )
    submitted_run = Run(
        id="run-sub",
        project_id=PROJECT_ONE,
        created_by_user_id=member.id,
        owner_user_id=member.id,
        task="task-a",
        dataset="dataset-a",
        metrics=["judge"],
        run_metadata={},
        run_config={"run_name": "Submitted"},
        status=RunWorkflowStatus.SUBMITTED,
    )
    deleted_run = Run(
        id="run-trash",
        project_id=PROJECT_ONE,
        created_by_user_id=member.id,
        owner_user_id=member.id,
        task="task-a",
        dataset="dataset-a",
        metrics=["judge"],
        run_metadata={},
        run_config={"run_name": "Trashed"},
        status=RunWorkflowStatus.COMPLETED,
        deleted_at=utc_now_naive(),
        deleted_by_user_id=member.id,
    )
    session.add_all(
        [
            run,
            submitted_run,
            deleted_run,
            RunItem(
                run_id=run.id,
                item_id="item-1",
                index=0,
                input={"prompt": "hi"},
                expected={"answer": "yes"},
                output={"answer": "no"},
                item_metadata={},
            ),
            RunItemScore(
                run_id=run.id,
                item_id="item-1",
                metric_name="judge",
                score_numeric=0.2,
                score_raw=0.2,
                meta={},
            ),
            Approval(run_id=submitted_run.id, submitted_by_user_id=member.id),
            Dataset(
                id="ds-1",
                project_id=PROJECT_ONE,
                name="Golden Set",
                slug="golden-set",
                created_by_user_id=manager.id,
            ),
            ApiKey(
                id="key-manager",
                user_id=manager.id,
                project_id=PROJECT_ONE,
                name="manager-key",
                prefix=api_key_prefix("manager-token"),
                key_hash=hash_api_key("manager-token"),
                scopes=["runs:write"],
            ),
            ApiKey(
                id="key-member",
                user_id=member.id,
                project_id=PROJECT_ONE,
                name="member-key",
                prefix=api_key_prefix("member-token"),
                key_hash=hash_api_key("member-token"),
                scopes=["runs:write"],
            ),
            ProjectLlmConnection(
                id="conn-1",
                project_id=PROJECT_ONE,
                name="default",
                llm_base_url="https://api.openai.com/v1",
                llm_model="gpt-4o-mini",
                is_default=True,
                created_by_user_id=manager.id,
            ),
        ]
    )
    session.commit()


@pytest.fixture()
def seeded_client(client, session_factory):
    with session_factory() as session:
        _seed_world(session)
    return client


# --- (a) unauthenticated -> 401 ----------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/runs", None),  # runs read
        ("GET", "/v1/me", None),  # web
        ("GET", "/v1/projects", None),  # projects
        ("GET", f"/v1/projects/{PROJECT_ONE}/members", None),  # members
        ("GET", f"/v1/projects/{PROJECT_ONE}/api-keys", None),  # api keys
        ("GET", f"/v1/projects/{PROJECT_ONE}/llm-connections", None),  # llm connections
        ("GET", "/v1/datasets", None),  # datasets read
        ("POST", "/v1/datasets", {"name": "x", "project_slug": "project-one"}),  # datasets write
        ("GET", "/api/runs/run-a/corrections", None),  # corrections/analysis
        ("GET", "/v1/admin/users", None),  # admin
        ("GET", "/api/runs/trash", None),  # trash
        ("POST", "/api/runs/update_metric", {"file_path": "run-a", "row_index": 0, "metric_name": "judge", "new_score": 0.9}),  # runs modify
        ("POST", "/api/runs/delete", {"file_path": "run-a"}),  # runs delete
        ("POST", "/v1/runs", {"task": "t", "dataset": "d"}),  # SDK ingest (bearer only)
    ],
)
def test_unauthenticated_requests_are_rejected(seeded_client, method, path, body):
    response = seeded_client.request(method, path, json=body)
    assert response.status_code == 401


def test_invalid_api_key_is_rejected(seeded_client):
    response = seeded_client.post(
        "/v1/runs",
        headers={"Authorization": "Bearer not-a-real-token"},
        json={"task": "t", "dataset": "d"},
    )
    assert response.status_code == 401


# --- (b) authenticated non-member -> 403/404 on other project's resources ----


def test_non_member_cannot_read_or_modify_other_projects_resources(seeded_client):
    # Project metadata and sub-resources
    assert seeded_client.get(f"/v1/projects/{PROJECT_ONE}", headers=_headers(OUTSIDER)).status_code == 403
    assert seeded_client.get(f"/v1/projects/{PROJECT_ONE}/members", headers=_headers(OUTSIDER)).status_code == 403
    assert seeded_client.get(f"/v1/projects/{PROJECT_ONE}/api-keys", headers=_headers(OUTSIDER)).status_code == 403
    assert seeded_client.get(f"/v1/projects/{PROJECT_ONE}/llm-connections", headers=_headers(OUTSIDER)).status_code == 403
    assert seeded_client.get("/v1/datasets?project_slug=project-one", headers=_headers(OUTSIDER)).status_code == 403
    assert seeded_client.get("/api/runs/run-a/corrections", headers=_headers(OUTSIDER)).status_code == 403

    # Run mutations in a project the caller is not a member of
    update = seeded_client.post(
        "/api/runs/update_metric",
        headers=_headers(OUTSIDER),
        json={"file_path": "run-a", "row_index": 0, "metric_name": "judge", "new_score": 0.1},
    )
    assert update.status_code == 403
    delete = seeded_client.post(
        "/api/runs/delete",
        headers=_headers(OUTSIDER),
        json={"file_path": "run-a"},
    )
    assert delete.status_code == 403

    # Unknown project -> 404 (no resource enumeration beyond existence)
    assert seeded_client.get("/v1/projects/does-not-exist", headers=_headers(OUTSIDER)).status_code == 404

    # Listing only surfaces the caller's own projects
    projects = seeded_client.get("/v1/projects", headers=_headers(OUTSIDER))
    assert projects.status_code == 200
    assert [p["id"] for p in projects.json()["projects"]] == [PROJECT_TWO]


# --- (c) member vs manager vs admin boundaries --------------------------------


def test_member_cannot_manage_members_but_manager_can(seeded_client):
    add_as_member = seeded_client.post(
        f"/v1/projects/{PROJECT_ONE}/members",
        headers=_headers(MEMBER),
        json={"user_id": "candidate-1", "role": "MEMBER"},
    )
    assert add_as_member.status_code == 403

    change_role_as_member = seeded_client.patch(
        f"/v1/projects/{PROJECT_ONE}/members/member-1",
        headers=_headers(MEMBER),
        json={"role": "MANAGER"},
    )
    assert change_role_as_member.status_code == 403

    remove_as_member = seeded_client.delete(
        f"/v1/projects/{PROJECT_ONE}/members/manager-1",
        headers=_headers(MEMBER),
    )
    assert remove_as_member.status_code == 403

    add_as_manager = seeded_client.post(
        f"/v1/projects/{PROJECT_ONE}/members",
        headers=_headers(MANAGER),
        json={"user_id": "candidate-1", "role": "MEMBER"},
    )
    assert add_as_manager.status_code == 200


def test_llm_connections_are_manager_only_to_mutate(seeded_client):
    # Members may read connections...
    listing = seeded_client.get(f"/v1/projects/{PROJECT_ONE}/llm-connections", headers=_headers(MEMBER))
    assert listing.status_code == 200

    payload = {"name": "secondary", "llm_base_url": "https://api.openai.com/v1", "llm_model": "gpt-4o-mini", "llm_api_key": "sk-test"}

    # ...but only managers may create/update/delete them.
    assert (
        seeded_client.post(
            f"/v1/projects/{PROJECT_ONE}/llm-connections", headers=_headers(MEMBER), json=payload
        ).status_code
        == 403
    )
    assert (
        seeded_client.put(
            f"/v1/projects/{PROJECT_ONE}/llm-connections/conn-1",
            headers=_headers(MEMBER),
            json={**payload, "llm_api_key": "__KEEP__"},
        ).status_code
        == 403
    )
    assert (
        seeded_client.delete(
            f"/v1/projects/{PROJECT_ONE}/llm-connections/conn-1", headers=_headers(MEMBER)
        ).status_code
        == 403
    )

    created = seeded_client.post(
        f"/v1/projects/{PROJECT_ONE}/llm-connections", headers=_headers(MANAGER), json=payload
    )
    assert created.status_code == 200
    assert created.json()["name"] == "secondary"


def test_api_key_revocation_requires_owner_manager_or_admin(seeded_client):
    # A member cannot revoke someone else's key...
    as_member = seeded_client.delete(
        f"/v1/projects/{PROJECT_ONE}/api-keys/key-manager", headers=_headers(MEMBER)
    )
    assert as_member.status_code == 403

    # ...but can revoke their own.
    own = seeded_client.delete(
        f"/v1/projects/{PROJECT_ONE}/api-keys/key-member", headers=_headers(MEMBER)
    )
    assert own.status_code == 200

    # Managers can revoke any project key.
    as_manager = seeded_client.delete(
        f"/v1/projects/{PROJECT_ONE}/api-keys/key-manager", headers=_headers(MANAGER)
    )
    assert as_manager.status_code == 200


def test_run_approval_requires_manager_or_admin(seeded_client):
    as_member = seeded_client.post(
        "/v1/runs/run-sub/approve", headers=_headers(MEMBER), json={"comment": "lgtm"}
    )
    assert as_member.status_code == 403

    as_manager = seeded_client.post(
        "/v1/runs/run-sub/approve", headers=_headers(MANAGER), json={"comment": "approved"}
    )
    assert as_manager.status_code == 200
    assert as_manager.json()["status"] == "APPROVED"


def test_project_creation_requires_admin_or_existing_manager(seeded_client):
    as_member = seeded_client.post(
        "/v1/projects", headers=_headers(MEMBER), json={"name": "Member Project"}
    )
    assert as_member.status_code == 403

    as_manager = seeded_client.post(
        "/v1/projects", headers=_headers(MANAGER), json={"name": "Manager Project"}
    )
    assert as_manager.status_code == 200


def test_admin_endpoints_reject_non_admins(seeded_client):
    for email in (MEMBER, MANAGER, OUTSIDER):
        assert seeded_client.get("/v1/admin/users", headers=_headers(email)).status_code == 403
        assert (
            seeded_client.post(
                "/v1/admin/projects", headers=_headers(email), json={"name": "Nope"}
            ).status_code
            == 403
        )

    as_admin = seeded_client.get("/v1/admin/users", headers=_headers(ADMIN))
    assert as_admin.status_code == 200
    created = seeded_client.post("/v1/admin/projects", headers=_headers(ADMIN), json={"name": "Compliance"})
    assert created.status_code == 200


def test_trash_listing_and_restore_are_admin_only(seeded_client):
    for email in (MEMBER, MANAGER):
        assert seeded_client.get("/api/runs/trash", headers=_headers(email)).status_code == 403
        assert (
            seeded_client.post(
                "/api/runs/restore", headers=_headers(email), json={"run_id": "run-trash"}
            ).status_code
            == 403
        )

    listing = seeded_client.get("/api/runs/trash", headers=_headers(ADMIN))
    assert listing.status_code == 200
    assert [r["id"] for r in listing.json()] == ["run-trash"]

    restored = seeded_client.post("/api/runs/restore", headers=_headers(ADMIN), json={"run_id": "run-trash"})
    assert restored.status_code == 200


def test_member_can_read_and_write_datasets_in_own_project(seeded_client):
    listing = seeded_client.get("/v1/datasets?project_slug=project-one", headers=_headers(MEMBER))
    assert listing.status_code == 200
    assert [ds["id"] for ds in listing.json()["datasets"]] == ["ds-1"]

    created = seeded_client.post(
        "/v1/datasets",
        headers=_headers(MEMBER),
        json={"name": "Edge Cases", "project_slug": "project-one"},
    )
    assert created.status_code == 200


# --- (d) proxy_headers hardening ----------------------------------------------


def test_proxy_secret_is_required_when_configured(seeded_client, monkeypatch):
    monkeypatch.setenv("QYM_PROXY_SHARED_SECRET", "proxy-secret")

    no_secret = seeded_client.get("/v1/me", headers=_headers(MEMBER))
    assert no_secret.status_code == 401

    wrong_secret = seeded_client.get(
        "/v1/me", headers={**_headers(MEMBER), "X-Qym-Proxy-Secret": "wrong"}
    )
    assert wrong_secret.status_code == 401

    with_secret = seeded_client.get(
        "/v1/me", headers={**_headers(MEMBER), "X-Qym-Proxy-Secret": "proxy-secret"}
    )
    assert with_secret.status_code == 200
    assert with_secret.json()["email"] == MEMBER


def test_auto_provision_only_when_explicitly_enabled(seeded_client, session_factory, monkeypatch):
    # Default (QYM_AUTO_PROVISION_USERS=false): unknown identities are rejected.
    rejected = seeded_client.get("/v1/me", headers=_headers("stranger@example.com"))
    assert rejected.status_code == 401
    with session_factory() as session:
        assert session.query(User).filter(User.email == "stranger@example.com").first() is None

    monkeypatch.setenv("QYM_AUTO_PROVISION_USERS", "true")
    provisioned = seeded_client.get("/v1/me", headers=_headers("stranger@example.com"))
    assert provisioned.status_code == 200
    assert provisioned.json()["role"] == "MEMBER"
    with session_factory() as session:
        created = session.query(User).filter(User.email == "stranger@example.com").first()
        assert created is not None
        assert created.role == UserRole.MEMBER
