from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("QYM_AUTH_MODE", "oidc")
os.environ.setdefault("QYM_AUTH_SESSION_SECRET", "test-session-secret")
os.environ.setdefault("QYM_BASE_URL", "http://testserver")
os.environ.setdefault("QYM_AUTH_GOOGLE_CLIENT_ID", "google-client")
os.environ.setdefault("QYM_AUTH_GOOGLE_CLIENT_SECRET", "google-secret")
os.environ.setdefault("QYM_AUTH_GITHUB_CLIENT_ID", "github-client")
os.environ.setdefault("QYM_AUTH_GITHUB_CLIENT_SECRET", "github-secret")
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
from qym_platform.auth_oidc import ProviderIdentity
from qym_platform.db.base import Base
from qym_platform.db.models import User, UserIdentity, UserRole
from qym_platform.deps import get_db


@pytest.fixture()
def session_factory(monkeypatch):
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("QYM_AUTH_MODE", "oidc")
    monkeypatch.setenv("QYM_AUTH_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("QYM_BASE_URL", "http://testserver")
    monkeypatch.setenv("QYM_AUTH_GOOGLE_CLIENT_ID", "google-client")
    monkeypatch.setenv("QYM_AUTH_GOOGLE_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv("QYM_AUTH_GITHUB_CLIENT_ID", "github-client")
    monkeypatch.setenv("QYM_AUTH_GITHUB_CLIENT_SECRET", "github-secret")
    monkeypatch.setenv("QYM_ADMIN_BOOTSTRAP_TOKEN", "bootstrap-secret")
    monkeypatch.setenv("QYM_ENVIRONMENT", "test")
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


def test_unauthenticated_html_redirects_to_login(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/"


def test_unauthenticated_json_returns_401(client):
    response = client.get("/v1/me")
    assert response.status_code == 401


def test_google_callback_provisions_user(client, session_factory, monkeypatch):
    from qym_platform.api import auth as auth_api

    async def fake_exchange(request, provider, settings):
        return ProviderIdentity(
            provider=provider,
            subject="google-sub",
            email="user@example.com",
            email_verified=True,
            display_name="Google User",
            raw_claims={"sub": "google-sub"},
        )

    monkeypatch.setattr(auth_api, "exchange_provider_identity", fake_exchange)

    response = client.get("/v1/auth/callback/google", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"

    me = client.get("/v1/me")
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "user@example.com"
    assert body["auth_type"] == "oidc"
    assert body["auth_provider"] == "google"

    with session_factory() as session:
        user = session.query(User).filter(User.email == "user@example.com").first()
        assert user is not None
        assert user.role == UserRole.EMPLOYEE
        assert session.query(UserIdentity).filter(UserIdentity.user_id == user.id, UserIdentity.provider == "google").count() == 1


def test_github_callback_provisions_user(client, session_factory, monkeypatch):
    from qym_platform.api import auth as auth_api

    async def fake_exchange(request, provider, settings):
        return ProviderIdentity(
            provider=provider,
            subject="github-sub",
            email="octo@example.com",
            email_verified=True,
            display_name="Octo Cat",
            raw_claims={"id": "github-sub"},
        )

    monkeypatch.setattr(auth_api, "exchange_provider_identity", fake_exchange)

    response = client.get("/v1/auth/callback/github", follow_redirects=False)
    assert response.status_code == 303

    with session_factory() as session:
        user = session.query(User).filter(User.email == "octo@example.com").first()
        assert user is not None
        assert session.query(UserIdentity).filter(UserIdentity.user_id == user.id, UserIdentity.provider == "github").count() == 1


def test_google_then_github_link_to_same_user(client, session_factory, monkeypatch):
    from qym_platform.api import auth as auth_api

    async def fake_exchange(request, provider, settings):
        return ProviderIdentity(
            provider=provider,
            subject=f"{provider}-subject",
            email="linked@example.com",
            email_verified=True,
            display_name="Linked User",
            raw_claims={"provider": provider},
        )

    monkeypatch.setattr(auth_api, "exchange_provider_identity", fake_exchange)

    assert client.get("/v1/auth/callback/google", follow_redirects=False).status_code == 303
    assert client.get("/v1/auth/callback/github", follow_redirects=False).status_code == 303

    with session_factory() as session:
        users = session.query(User).filter(User.email == "linked@example.com").all()
        assert len(users) == 1
        identities = session.query(UserIdentity).filter(UserIdentity.user_id == users[0].id).all()
        assert sorted(identity.provider for identity in identities) == ["github", "google"]


def test_github_missing_verified_email_fails(client, monkeypatch):
    from qym_platform.api import auth as auth_api

    async def fake_exchange(request, provider, settings):
        raise HTTPException(status_code=401, detail="GitHub account must provide a verified email")

    monkeypatch.setattr(auth_api, "exchange_provider_identity", fake_exchange)
    response = client.get("/v1/auth/callback/github", follow_redirects=False)
    assert response.status_code == 401


def test_logout_clears_session(client, monkeypatch):
    from qym_platform.api import auth as auth_api

    async def fake_exchange(request, provider, settings):
        return ProviderIdentity(
            provider=provider,
            subject="google-sub",
            email="logout@example.com",
            email_verified=True,
            display_name="Logout User",
            raw_claims={},
        )

    monkeypatch.setattr(auth_api, "exchange_provider_identity", fake_exchange)
    assert client.get("/v1/auth/callback/google", follow_redirects=False).status_code == 303
    assert client.get("/v1/me").status_code == 200

    response = client.post("/v1/auth/logout", headers={"Origin": "http://testserver"})
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert client.get("/v1/me").status_code == 401


def test_bootstrap_admin_promotes_first_authenticated_user(client, session_factory, monkeypatch):
    from qym_platform.api import auth as auth_api

    async def fake_exchange(request, provider, settings):
        return ProviderIdentity(
            provider=provider,
            subject="google-sub",
            email="bootstrap@example.com",
            email_verified=True,
            display_name="Bootstrap User",
            raw_claims={},
        )

    monkeypatch.setattr(auth_api, "exchange_provider_identity", fake_exchange)
    assert client.get("/v1/auth/callback/google", follow_redirects=False).status_code == 303

    response = client.post(
        "/v1/auth/bootstrap-admin",
        json={"bootstrap_token": "bootstrap-secret"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    assert response.json()["role"] == "ADMIN"

    with session_factory() as session:
        user = session.query(User).filter(User.email == "bootstrap@example.com").first()
        assert user is not None
        assert user.role == UserRole.ADMIN

    second = client.post(
        "/v1/auth/bootstrap-admin",
        json={"bootstrap_token": "bootstrap-secret"},
        headers={"Origin": "http://testserver"},
    )
    assert second.status_code == 200
    assert second.json()["role"] == "ADMIN"
