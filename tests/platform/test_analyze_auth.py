"""Auth tests for POST /api/runs/{run_id}/analyze.

Verifies the analyze endpoint accepts Bearer API-key auth (used by the CLI)
in addition to UI session/proxy-header principals, and that project-scoped
keys are confined to their own project's runs.

The endpoint needs a configured LLM connection to actually run analysis, so
"got past auth" is asserted as a 400 complaining about the missing LLM
connection rather than a 401/403.
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
os.environ.setdefault("QYM_AUTH_MODE", "proxy_headers")
# The repo .env may enable local session auth, which adds a same-origin write
# guard for non-Bearer requests; disable it so proxy-header auth is exercised.
os.environ["QYM_AUTH_LOCAL_ENABLED"] = "false"
os.environ.setdefault("QYM_LLM_CONFIG_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
ROOT = Path(__file__).resolve().parents[2]
for src in (ROOT / "packages" / "platform", ROOT / "packages" / "sdk"):
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

from qym_platform.app import create_app
from qym_platform.db.base import Base
from qym_platform.db.models import (
    ApiKey,
    Project,
    ProjectMembership,
    ProjectRole,
    Run,
    RunItem,
    User,
    UserRole,
)
from qym_platform.deps import get_db
from qym_platform.security import api_key_prefix, hash_api_key


def _seed(session: Session) -> None:
    member = User(id="member-1", email="member@example.com", display_name="Member", role=UserRole.MEMBER)
    admin = User(id="admin-1", email="admin@example.com", display_name="Admin", role=UserRole.ADMIN)
    outsider = User(id="outsider-1", email="outsider@example.com", display_name="Outsider", role=UserRole.MEMBER)
    project_a = Project(id="project-a", name="Project A", slug="project-a", created_by_user_id=admin.id)
    project_b = Project(id="project-b", name="Project B", slug="project-b", created_by_user_id=admin.id)
    run = Run(
        id="run-1",
        project_id=project_a.id,
        created_by_user_id=member.id,
        owner_user_id=member.id,
        task="task-1",
        dataset="dataset-1",
        metrics=["exact_match"],
        run_metadata={},
        run_config={},
    )
    item = RunItem(
        run_id=run.id,
        item_id="item-1",
        index=0,
        input="hello",
        expected="world",
        output="nope",
        item_metadata={},
    )
    session.add_all(
        [
            member,
            admin,
            outsider,
            project_a,
            project_b,
            run,
            item,
            ProjectMembership(project_id=project_a.id, user_id=member.id, role=ProjectRole.MEMBER),
            # Project-scoped key for project A, owned by a regular member.
            ApiKey(
                id="key-a",
                user_id=member.id,
                project_id=project_a.id,
                name="key-a",
                prefix=api_key_prefix("token-a"),
                key_hash=hash_api_key("token-a"),
                scopes=["runs:write"],
            ),
            # Key scoped to project B but owned by an ADMIN: project scoping
            # must still confine it to project B's runs.
            ApiKey(
                id="key-b",
                user_id=admin.id,
                project_id=project_b.id,
                name="key-b",
                prefix=api_key_prefix("token-b"),
                key_hash=hash_api_key("token-b"),
                scopes=["runs:write"],
            ),
        ]
    )
    session.commit()


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("QYM_AUTH_MODE", "proxy_headers")
    monkeypatch.setenv("QYM_AUTH_LOCAL_ENABLED", "false")
    monkeypatch.setenv("QYM_ALLOW_LEGACY_EMPTY_API_KEY_SCOPES", "true")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with SessionLocal() as session:
        _seed(session)

    app = create_app()

    def override_get_db():
        db = SessionLocal()
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
        engine.dispose()


ANALYZE_URL = "/api/runs/run-1/analyze"
ANALYZE_BODY = {"item_filter": "all"}


def test_analyze_without_credentials_is_401(client):
    response = client.post(ANALYZE_URL, json=ANALYZE_BODY)
    assert response.status_code == 401


def test_analyze_with_project_api_key_gets_past_auth(client):
    response = client.post(
        ANALYZE_URL,
        headers={"Authorization": "Bearer token-a"},
        json=ANALYZE_BODY,
    )
    # Auth must succeed; the request then fails on the missing LLM connection.
    assert response.status_code not in (401, 403), response.text
    assert response.status_code == 400
    assert "LLM connection" in response.json()["detail"]


def test_analyze_with_invalid_api_key_is_401(client):
    response = client.post(
        ANALYZE_URL,
        headers={"Authorization": "Bearer not-a-real-key"},
        json=ANALYZE_BODY,
    )
    assert response.status_code == 401


def test_analyze_with_key_scoped_to_other_project_is_403(client):
    response = client.post(
        ANALYZE_URL,
        headers={"Authorization": "Bearer token-b"},
        json=ANALYZE_BODY,
    )
    assert response.status_code == 403
    assert "project" in response.json()["detail"].lower()


def test_analyze_with_session_principal_still_works(client):
    response = client.post(
        ANALYZE_URL,
        headers={"X-User-Email": "member@example.com"},
        json=ANALYZE_BODY,
    )
    # Proxy-header (UI) auth still gets past auth to the LLM-connection check.
    assert response.status_code not in (401, 403), response.text
    assert response.status_code == 400
    assert "LLM connection" in response.json()["detail"]


def test_analyze_with_session_principal_without_project_access_is_403(client):
    response = client.post(
        ANALYZE_URL,
        headers={"X-User-Email": "outsider@example.com"},
        json=ANALYZE_BODY,
    )
    assert response.status_code == 403
