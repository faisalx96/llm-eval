from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")
ROOT = Path(__file__).resolve().parents[2]
PLATFORM_SRC = ROOT / "packages" / "platform"
SDK_SRC = ROOT / "packages" / "sdk"
for src in (PLATFORM_SRC, SDK_SRC):
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

from qym_platform.app import create_app
from qym_platform.db.base import Base
from qym_platform.db.models import Project, ProjectLlmConnection, User, UserRole
from qym_platform.deps import get_db

PROJECT_ID = "proj-1"
CONNECTIONS_URL = f"/v1/projects/{PROJECT_ID}/llm-connections"


@pytest.fixture()
def session_factory(monkeypatch):
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("QYM_AUTH_MODE", "proxy_headers")
    # Pin base_url so the same-origin write guard matches the Origin header below even
    # when another test module has leaked QYM_BASE_URL into the process environment.
    monkeypatch.setenv("QYM_BASE_URL", "http://localhost:8000")
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
    # Origin matches the default base_url so the same-origin write guard allows POST/PUT/DELETE.
    return {"X-User-Email": email, "Origin": "http://localhost:8000"}


def _seed_admin_and_project(session_factory) -> None:
    """Admins have access to every project, so no membership rows are needed."""
    with session_factory() as session:
        session.add(
            User(id="user-1", email="user@example.com", role=UserRole.ADMIN)
        )
        session.add(
            Project(id=PROJECT_ID, name="Proj", slug="proj", created_by_user_id="user-1")
        )
        session.commit()


def test_connection_key_is_encrypted_and_masked(client, session_factory, monkeypatch) -> None:
    _seed_admin_and_project(session_factory)

    create = client.post(
        CONNECTIONS_URL,
        headers=_headers("user@example.com"),
        json={
            "name": "OpenAI prod",
            "llm_base_url": "https://api.openai.com/v1",
            "llm_api_key": "sk-secret-1234",
            "llm_model": "gpt-4o-mini",
        },
    )
    assert create.status_code == 200
    created = create.json()
    connection_id = created["id"]
    # First connection becomes the default; the raw key is never echoed back.
    assert created["is_default"] is True
    assert created["llm_api_key_set"] is True
    assert created["llm_api_key_hint"] == "••••1234"
    assert "llm_api_key" not in created
    assert "llm_api_key_encrypted" not in created

    with session_factory() as session:
        conn = session.query(ProjectLlmConnection).filter_by(id=connection_id).first()
        assert conn is not None
        assert conn.llm_api_key_encrypted
        assert conn.llm_api_key_last4 == "1234"

    listing = client.get(CONNECTIONS_URL, headers=_headers("user@example.com"))
    assert listing.status_code == 200
    conns = listing.json()["connections"]
    assert len(conns) == 1
    assert conns[0]["llm_api_key_hint"] == "••••1234"

    # ── Test connection: decrypts the real key and falls back max_tokens → max_completion_tokens
    captured: dict[str, object] = {"calls": []}

    class FakeAsyncOpenAI:
        def __init__(self, *, base_url: str, api_key: str):
            captured["base_url"] = base_url
            captured["api_key"] = api_key
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=self._create)
            )

        async def _create(self, **kwargs):
            captured["calls"].append(kwargs)
            if "max_tokens" in kwargs:
                raise Exception(
                    "Error code: 400 - {'error': {'message': "
                    "\"Unsupported parameter: 'max_tokens' is not supported with this model. "
                    "Use 'max_completion_tokens' instead.\", 'type': 'invalid_request_error', "
                    "'param': 'max_tokens', 'code': 'unsupported_parameter'}}"
                )
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="ok"))]
            )

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI))
    test_response = client.post(
        f"{CONNECTIONS_URL}/{connection_id}/test", headers=_headers("user@example.com")
    )
    assert test_response.status_code == 200
    assert captured["api_key"] == "sk-secret-1234"
    calls = captured["calls"]
    assert len(calls) == 2
    assert calls[0]["max_tokens"] == 4
    assert calls[1]["max_completion_tokens"] == 4
    assert "max_tokens" not in calls[1]


def test_update_with_keep_preserves_key(client, session_factory) -> None:
    _seed_admin_and_project(session_factory)
    create = client.post(
        CONNECTIONS_URL,
        headers=_headers("user@example.com"),
        json={"name": "c1", "llm_api_key": "sk-secret-9999", "llm_model": "gpt-4o-mini"},
    )
    connection_id = create.json()["id"]

    update = client.put(
        f"{CONNECTIONS_URL}/{connection_id}",
        headers=_headers("user@example.com"),
        json={"name": "c1 renamed", "llm_api_key": "__KEEP__", "llm_model": "gpt-4o"},
    )
    assert update.status_code == 200
    assert update.json()["name"] == "c1 renamed"

    with session_factory() as session:
        conn = session.query(ProjectLlmConnection).filter_by(id=connection_id).first()
        assert conn.llm_model == "gpt-4o"
        assert conn.llm_api_key_last4 == "9999"  # key preserved across the rename


def test_create_reports_missing_encryption_key(client, session_factory, monkeypatch) -> None:
    # The repo .env supplies an encryption key, so simulate "not configured" at the guard.
    import qym_platform.api.projects as projects_api

    monkeypatch.setattr(projects_api, "encryption_available", lambda *a, **k: False)
    _seed_admin_and_project(session_factory)

    resp = client.post(
        CONNECTIONS_URL,
        headers=_headers("user@example.com"),
        json={"name": "c1", "llm_api_key": "sk-secret-1234", "llm_model": "gpt-4o-mini"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "LLM config encryption is not configured"
