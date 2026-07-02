from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker

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
    CorrectionStatus,
    Project,
    ProjectMembership,
    ProjectRole,
    ReviewCorrection,
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


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_platform_data(session: Session) -> None:
    manager_a = User(id="manager-a", email="manager-a@example.com", role=UserRole.MEMBER)
    manager_b = User(id="manager-b", email="manager-b@example.com", role=UserRole.MEMBER)
    owner = User(id="owner-1", email="owner@example.com", role=UserRole.MEMBER)
    other = User(id="other-1", email="other@example.com", role=UserRole.MEMBER)
    nonmember = User(id="nonmember-1", email="nonmember@example.com", role=UserRole.MEMBER)
    admin = User(id="admin-1", email="admin@example.com", role=UserRole.ADMIN)

    project_a = Project(id="project-a", name="Project A", slug="project-a", created_by_user_id=admin.id)
    project_b = Project(id="project-b", name="Project B", slug="project-b", created_by_user_id=admin.id)
    memberships = [
        ProjectMembership(project_id=project_a.id, user_id=manager_a.id, role=ProjectRole.MANAGER, added_by_user_id=admin.id),
        ProjectMembership(project_id=project_a.id, user_id=owner.id, role=ProjectRole.MEMBER, added_by_user_id=admin.id),
        ProjectMembership(project_id=project_b.id, user_id=manager_b.id, role=ProjectRole.MANAGER, added_by_user_id=admin.id),
        ProjectMembership(project_id=project_b.id, user_id=other.id, role=ProjectRole.MEMBER, added_by_user_id=admin.id),
    ]

    run = Run(
        id="run-1",
        project_id=project_a.id,
        created_by_user_id=owner.id,
        owner_user_id=owner.id,
        task="task-1",
        dataset="dataset-1",
        metrics=["judge"],
        status=RunWorkflowStatus.COMPLETED,
        run_metadata={},
        run_config={},
    )
    item = RunItem(
        run_id=run.id,
        item_id="item-1",
        index=0,
        input={"prompt": "hello"},
        expected={"answer": "world"},
        output={"answer": "nope"},
        item_metadata={},
    )
    score = RunItemScore(
        run_id=run.id,
        item_id=item.item_id,
        metric_name="judge",
        score_numeric=0.2,
        score_raw=0.2,
        meta={},
    )
    correction = ReviewCorrection(
        run_id=run.id,
        item_id=item.item_id,
        task=run.task,
        input_snapshot=item.input,
        expected_snapshot=item.expected,
        output_snapshot=item.output,
        scores_snapshot={"judge": 0.2},
        ai_root_cause="Wrong Format",
        ai_root_cause_note="AI guess",
        human_root_cause="Wrong Format",
        human_root_cause_note="Human review",
        status=CorrectionStatus.PENDING,
        is_active=True,
    )
    session.add_all([manager_a, manager_b, owner, other, nonmember, admin, project_a, project_b])
    session.add_all(memberships)
    session.add_all([run, item, score, correction])
    session.commit()


def _seed_api_key(session: Session, *, token: str, scopes: list[str]) -> None:
    user = User(id=f"user-{token}", email=f"{token}@example.com", role=UserRole.MEMBER)
    project = Project(
        id=f"project-{token}",
        name=f"Project {token}",
        slug=f"project-{token}",
        created_by_user_id=user.id,
    )
    membership = ProjectMembership(
        project_id=project.id,
        user_id=user.id,
        role=ProjectRole.MEMBER,
        added_by_user_id=user.id,
    )
    api_key = ApiKey(
        id=f"key-{token}",
        user_id=user.id,
        project_id=project.id,
        name=token,
        prefix=api_key_prefix(token),
        key_hash=hash_api_key(token),
        scopes=scopes,
    )
    session.add_all([user, project, membership, api_key])
    session.commit()


def test_proxy_headers_auto_provisions_new_user(client, session_factory):
    response = client.get("/api/runs", headers=_headers("new.user@example.com"))
    assert response.status_code == 200

    with session_factory() as session:
        user = session.query(User).filter(User.email == "new.user@example.com").first()
        assert user is not None
        assert user.role == UserRole.MEMBER
        assert user.display_name == "New User"


def test_run_mutation_permissions_enforced(client, session_factory) -> None:
    with session_factory() as session:
        _seed_platform_data(session)

    owner_metric = client.post(
        "/api/runs/update_metric",
        headers=_headers("owner@example.com"),
        json={"file_path": "run-1", "row_index": 0, "metric_name": "judge", "new_score": 0.9},
    )
    assert owner_metric.status_code == 200

    manager_metric = client.post(
        "/api/runs/update_metric",
        headers=_headers("manager-a@example.com"),
        json={"file_path": "run-1", "row_index": 0, "metric_name": "judge", "new_score": 0.7},
    )
    assert manager_metric.status_code == 200

    other_metric = client.post(
        "/api/runs/update_metric",
        headers=_headers("other@example.com"),
        json={"file_path": "run-1", "row_index": 0, "metric_name": "judge", "new_score": 0.1},
    )
    assert other_metric.status_code == 403

    nonmember_root_cause = client.post(
        "/api/runs/update_root_cause",
        headers=_headers("nonmember@example.com"),
        json={"run_id": "run-1", "item_id": "item-1", "root_cause": "Hallucination"},
    )
    assert nonmember_root_cause.status_code == 403

    denied_analyze = client.post(
        "/api/runs/run-1/analyze",
        headers=_headers("other@example.com"),
        json={"item_filter": "all"},
    )
    assert denied_analyze.status_code == 403


def test_correction_review_permissions_and_filtering(client, session_factory) -> None:
    with session_factory() as session:
        _seed_platform_data(session)

    manager_list = client.get("/api/corrections", headers=_headers("manager-a@example.com"))
    assert manager_list.status_code == 200
    assert len(manager_list.json()["corrections"]) == 1

    outsider_list = client.get("/api/corrections", headers=_headers("other@example.com"))
    assert outsider_list.status_code == 200
    assert outsider_list.json()["corrections"] == []

    denied_get = client.get("/api/corrections/1", headers=_headers("other@example.com"))
    assert denied_get.status_code == 403

    denied_update = client.put(
        "/api/corrections/1",
        headers=_headers("other@example.com"),
        json={"human_root_cause_note": "should fail"},
    )
    assert denied_update.status_code == 403

    allowed_approve = client.post(
        "/api/corrections/1/approve",
        headers=_headers("manager-a@example.com"),
        json={"comment": "approved"},
    )
    assert allowed_approve.status_code == 200
    assert allowed_approve.json()["status"] == "approved"

    denied_bulk = client.post(
        "/api/corrections/bulk",
        headers=_headers("manager-b@example.com"),
        json={"ids": [1], "action": "reject", "comment": "nope"},
    )
    assert denied_bulk.status_code == 403


def test_api_key_scopes_are_not_enforced(client, session_factory) -> None:
    # Scope enforcement is intentionally disabled: any valid, non-revoked key has full
    # access to its project regardless of the scopes recorded on the key. Authentication
    # and project membership still gate access; per-key scopes are no longer checked.
    with session_factory() as session:
        _seed_api_key(session, token="write-token", scopes=["runs:write"])
        _seed_api_key(session, token="read-token", scopes=["runs:read"])
        _seed_api_key(session, token="legacy-token", scopes=[])

    for token in ("write-token", "read-token", "legacy-token"):
        response = client.post(
            "/v1/runs",
            headers=_auth_headers(token),
            json={"task": "task", "dataset": "dataset", "metrics": [], "run_metadata": {}, "run_config": {}},
        )
        assert response.status_code == 200, (token, response.text)
