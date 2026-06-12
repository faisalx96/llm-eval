from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest
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
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

from qym_platform.app import create_app
from qym_platform.db.base import Base
from qym_platform.db.models import User, UserRole
from qym_platform.deps import get_db


def _configure_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    auth_mode: str,
    environment: str = "dev",
    proxy_shared_secret: str = "",
    auth_session_secret: str = "",
    auto_provision_users: bool = False,
) -> None:
    """Pin every auth-relevant setting so values from a local .env cannot leak in."""
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("QYM_AUTH_MODE", auth_mode)
    monkeypatch.setenv("QYM_ENVIRONMENT", environment)
    monkeypatch.setenv("QYM_PROXY_SHARED_SECRET", proxy_shared_secret)
    monkeypatch.setenv("QYM_AUTH_SESSION_SECRET", auth_session_secret)
    monkeypatch.setenv("QYM_AUTO_PROVISION_USERS", "true" if auto_provision_users else "false")
    monkeypatch.setenv("QYM_AUTH_LOCAL_ENABLED", "false")
    monkeypatch.setenv("QYM_ADMIN_BOOTSTRAP_TOKEN", "")
    monkeypatch.setenv("QYM_AUTH_GOOGLE_CLIENT_ID", "")
    monkeypatch.setenv("QYM_AUTH_GOOGLE_CLIENT_SECRET", "")
    monkeypatch.setenv("QYM_AUTH_GITHUB_CLIENT_ID", "")
    monkeypatch.setenv("QYM_AUTH_GITHUB_CLIENT_SECRET", "")


@pytest.fixture()
def session_factory():
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


@contextmanager
def _client(session_factory):
    app = create_app()

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _seed_user(session_factory, email: str) -> None:
    with session_factory() as session:
        session.add(User(email=email, display_name=email, role=UserRole.MEMBER))
        session.commit()


# --- SEC-3: startup validation ---


def test_auth_none_in_production_fails_startup(monkeypatch):
    _configure_env(monkeypatch, auth_mode="none", environment="production")
    with pytest.raises(RuntimeError, match="QYM_AUTH_MODE=none is only allowed"):
        create_app()


@pytest.mark.parametrize("environment", ["dev", "development", "test", "testing", "local"])
def test_auth_none_in_dev_like_environment_boots(monkeypatch, session_factory, environment):
    _configure_env(monkeypatch, auth_mode="none", environment=environment)
    with _client(session_factory) as client:
        assert client.get("/healthz").status_code == 200
        # Dev principal still works without headers (and without auto-provisioning).
        assert client.get("/api/runs").status_code == 200


def test_empty_auth_mode_fails_startup(monkeypatch):
    _configure_env(monkeypatch, auth_mode="", environment="dev")
    with pytest.raises(RuntimeError, match="QYM_AUTH_MODE must be one of"):
        create_app()


@pytest.mark.parametrize("environment", ["dev", "production"])
def test_unknown_auth_mode_fails_startup(monkeypatch, environment):
    _configure_env(monkeypatch, auth_mode="saml", environment=environment)
    with pytest.raises(RuntimeError, match="QYM_AUTH_MODE must be one of"):
        create_app()


def test_proxy_headers_without_shared_secret_fails_startup_outside_dev(monkeypatch):
    _configure_env(monkeypatch, auth_mode="proxy_headers", environment="production")
    with pytest.raises(RuntimeError, match="QYM_PROXY_SHARED_SECRET is required"):
        create_app()


def test_proxy_headers_with_shared_secret_boots_in_production(monkeypatch):
    _configure_env(
        monkeypatch,
        auth_mode="proxy_headers",
        environment="production",
        proxy_shared_secret="proxy-secret",
    )
    create_app()


# --- SEC-4: proxy-header identity binding ---


def test_proxy_headers_rejects_spoofed_email_without_secret_header(monkeypatch, session_factory):
    _configure_env(monkeypatch, auth_mode="proxy_headers", proxy_shared_secret="proxy-secret")
    _seed_user(session_factory, "victim@example.com")
    with _client(session_factory) as client:
        response = client.get("/api/runs", headers={"X-User-Email": "victim@example.com"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid proxy secret"


def test_proxy_headers_rejects_wrong_secret_header(monkeypatch, session_factory):
    _configure_env(monkeypatch, auth_mode="proxy_headers", proxy_shared_secret="proxy-secret")
    _seed_user(session_factory, "victim@example.com")
    with _client(session_factory) as client:
        response = client.get(
            "/api/runs",
            headers={"X-User-Email": "victim@example.com", "X-Qym-Proxy-Secret": "wrong"},
        )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid proxy secret"


def test_proxy_headers_authenticates_with_correct_secret(monkeypatch, session_factory):
    _configure_env(monkeypatch, auth_mode="proxy_headers", proxy_shared_secret="proxy-secret")
    _seed_user(session_factory, "victim@example.com")
    with _client(session_factory) as client:
        response = client.get(
            "/api/runs",
            headers={"X-User-Email": "victim@example.com", "X-Qym-Proxy-Secret": "proxy-secret"},
        )
    assert response.status_code == 200


def test_proxy_headers_does_not_auto_provision_by_default(monkeypatch, session_factory):
    _configure_env(monkeypatch, auth_mode="proxy_headers", proxy_shared_secret="proxy-secret")
    with _client(session_factory) as client:
        response = client.get(
            "/api/runs",
            headers={"X-User-Email": "stranger@example.com", "X-Qym-Proxy-Secret": "proxy-secret"},
        )
    assert response.status_code == 401
    with session_factory() as session:
        assert session.query(User).filter(User.email == "stranger@example.com").first() is None


def test_proxy_headers_auto_provisions_when_opted_in(monkeypatch, session_factory):
    _configure_env(
        monkeypatch,
        auth_mode="proxy_headers",
        proxy_shared_secret="proxy-secret",
        auto_provision_users=True,
    )
    with _client(session_factory) as client:
        response = client.get(
            "/api/runs",
            headers={"X-User-Email": "newcomer@example.com", "X-Qym-Proxy-Secret": "proxy-secret"},
        )
    assert response.status_code == 200
    with session_factory() as session:
        assert session.query(User).filter(User.email == "newcomer@example.com").first() is not None


def test_oidc_mode_ignores_identity_headers(monkeypatch, session_factory):
    _configure_env(monkeypatch, auth_mode="oidc", auth_session_secret="test-session-secret")
    _seed_user(session_factory, "victim@example.com")
    with _client(session_factory) as client:
        response = client.get("/api/runs", headers={"X-User-Email": "victim@example.com"})
    assert response.status_code == 401
