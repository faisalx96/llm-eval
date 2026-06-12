from __future__ import annotations

import os
import socket
import sys
import types
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
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

from qym_platform.app import create_app
from qym_platform.db.base import Base
from qym_platform.db.models import (
    Project,
    ProjectLlmConnection,
    ProjectMembership,
    ProjectRole,
    User,
    UserRole,
)
from qym_platform.deps import get_db

PROJECT_ID = "proj-llm-sec"
CONNECTIONS_URL = f"/v1/projects/{PROJECT_ID}/llm-connections"
MANAGER = "manager@example.com"
MEMBER = "member@example.com"


@pytest.fixture()
def session_factory(monkeypatch):
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("QYM_AUTH_MODE", "proxy_headers")
    monkeypatch.setenv("QYM_LLM_CONFIG_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
    # Pin a dev environment baseline; individual tests flip to production.
    monkeypatch.setenv("QYM_ENVIRONMENT", "dev")
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


def _seed_project(session_factory) -> None:
    """One project with a MANAGER-role member and a plain MEMBER-role member."""
    with session_factory() as session:
        manager = User(id="mgr-1", email=MANAGER, role=UserRole.MEMBER)
        member = User(id="mem-1", email=MEMBER, role=UserRole.MEMBER)
        project = Project(id=PROJECT_ID, name="Proj", slug="proj-llm-sec", created_by_user_id="mgr-1")
        session.add_all([manager, member, project])
        session.flush()
        session.add_all(
            [
                ProjectMembership(
                    project_id=PROJECT_ID, user_id="mgr-1", role=ProjectRole.MANAGER, added_by_user_id="mgr-1"
                ),
                ProjectMembership(
                    project_id=PROJECT_ID, user_id="mem-1", role=ProjectRole.MEMBER, added_by_user_id="mgr-1"
                ),
            ]
        )
        session.commit()


def _create_connection(client, *, name: str = "OpenAI", api_key: str = "sk-secret-1234") -> str:
    resp = client.post(
        CONNECTIONS_URL,
        headers=_headers(MANAGER),
        json={
            "name": name,
            "llm_base_url": "https://api.openai.com/v1",
            "llm_model": "gpt-4o-mini",
            "llm_api_key": api_key,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _fake_getaddrinfo(ip: str, calls: list[str]):
    def fake(host, port, *args, **kwargs):
        calls.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port or 443))]

    return fake


def _patch_resolver(monkeypatch, ip: str) -> list[str]:
    """Replace url_guard's resolver so validation never touches real DNS."""
    import qym_platform.url_guard as url_guard

    calls: list[str] = []
    monkeypatch.setattr(
        url_guard,
        "socket",
        types.SimpleNamespace(getaddrinfo=_fake_getaddrinfo(ip, calls), IPPROTO_TCP=socket.IPPROTO_TCP),
    )
    return calls


# ── Authorization: only project managers (or admins) may manage connections ──


def test_non_manager_member_cannot_manage_connections(client, session_factory) -> None:
    _seed_project(session_factory)
    connection_id = _create_connection(client)

    create = client.post(
        CONNECTIONS_URL,
        headers=_headers(MEMBER),
        json={"name": "evil", "llm_base_url": "https://example.com/v1", "llm_api_key": "sk-x"},
    )
    assert create.status_code == 403

    update = client.put(
        f"{CONNECTIONS_URL}/{connection_id}",
        headers=_headers(MEMBER),
        json={"name": "OpenAI", "llm_base_url": "https://evil.example.com/v1", "llm_api_key": "__KEEP__"},
    )
    assert update.status_code == 403

    delete = client.delete(f"{CONNECTIONS_URL}/{connection_id}", headers=_headers(MEMBER))
    assert delete.status_code == 403

    set_default = client.post(f"{CONNECTIONS_URL}/{connection_id}/set-default", headers=_headers(MEMBER))
    assert set_default.status_code == 403

    test_conn = client.post(f"{CONNECTIONS_URL}/{connection_id}/test", headers=_headers(MEMBER))
    assert test_conn.status_code == 403

    # Plain members keep read access to the (key-masked) connection list.
    listing = client.get(CONNECTIONS_URL, headers=_headers(MEMBER))
    assert listing.status_code == 200

    # Nothing was mutated by the rejected calls.
    with session_factory() as session:
        conn = session.query(ProjectLlmConnection).filter_by(id=connection_id).one()
        assert conn.llm_base_url == "https://api.openai.com/v1"
        assert conn.llm_api_key_last4 == "1234"
        assert session.query(ProjectLlmConnection).count() == 1


# ── __KEEP__ sentinel: stored key must not follow a new base URL ──


def test_keep_sentinel_with_changed_base_url_is_rejected(client, session_factory) -> None:
    _seed_project(session_factory)
    connection_id = _create_connection(client)

    update = client.put(
        f"{CONNECTIONS_URL}/{connection_id}",
        headers=_headers(MANAGER),
        json={
            "name": "OpenAI",
            "llm_base_url": "https://attacker.example.com/v1",
            "llm_model": "gpt-4o-mini",
            "llm_api_key": "__KEEP__",
        },
    )
    assert update.status_code == 400
    assert update.json()["detail"] == "Re-enter the API key when changing the base URL"

    # The stored connection is untouched: old URL, old key.
    with session_factory() as session:
        conn = session.query(ProjectLlmConnection).filter_by(id=connection_id).one()
        assert conn.llm_base_url == "https://api.openai.com/v1"
        assert conn.llm_api_key_last4 == "1234"


def test_keep_sentinel_with_same_base_url_still_works(client, session_factory) -> None:
    _seed_project(session_factory)
    connection_id = _create_connection(client)

    # Same URL (modulo trailing-slash normalization) keeps the stored key.
    update = client.put(
        f"{CONNECTIONS_URL}/{connection_id}",
        headers=_headers(MANAGER),
        json={
            "name": "OpenAI renamed",
            "llm_base_url": "https://api.openai.com/v1/",
            "llm_model": "gpt-4o",
            "llm_api_key": "__KEEP__",
        },
    )
    assert update.status_code == 200, update.text
    payload = update.json()
    assert payload["name"] == "OpenAI renamed"
    assert payload["llm_api_key_set"] is True
    assert payload["llm_api_key_hint"] == "••••1234"

    with session_factory() as session:
        conn = session.query(ProjectLlmConnection).filter_by(id=connection_id).one()
        assert conn.llm_model == "gpt-4o"
        assert conn.llm_api_key_last4 == "1234"


# ── SSRF guard: base URL validation outside dev/test/local environments ──


def test_private_and_metadata_urls_rejected_outside_dev(client, session_factory, monkeypatch) -> None:
    _seed_project(session_factory)
    connection_id = _create_connection(client)
    monkeypatch.setenv("QYM_ENVIRONMENT", "production")

    def attempt_update(base_url: str):
        return client.put(
            f"{CONNECTIONS_URL}/{connection_id}",
            headers=_headers(MANAGER),
            json={
                "name": "OpenAI",
                "llm_base_url": base_url,
                "llm_model": "gpt-4o-mini",
                "llm_api_key": "sk-new-key-0001",
            },
        )

    # Plain http is rejected in production.
    resp = attempt_update("http://169.254.169.254/latest")
    assert resp.status_code == 400
    assert "https" in resp.json()["detail"]

    # Literal internal addresses are rejected even over https.
    for bad in (
        "https://169.254.169.254/v1",  # cloud metadata
        "https://127.0.0.1/v1",
        "https://10.0.0.5/v1",
        "https://172.16.0.9/v1",
        "https://192.168.1.10/v1",
        "https://[::1]/v1",
        "https://[fe80::1]/v1",
        "https://[fc00::1]/v1",
    ):
        resp = attempt_update(bad)
        assert resp.status_code == 400, bad
        assert resp.json()["detail"] == "LLM base URL must not point at a private or internal address"

    # Embedded credentials are rejected before any DNS resolution.
    resp = attempt_update("https://user:pass@api.example.com/v1")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "LLM base URL must not contain embedded credentials"

    # A hostname that resolves to a private address is rejected too.
    _patch_resolver(monkeypatch, "10.1.2.3")
    resp = attempt_update("https://internal.example.com/v1")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "LLM base URL must not point at a private or internal address"

    # Nothing got through; the stored connection is unchanged.
    with session_factory() as session:
        conn = session.query(ProjectLlmConnection).filter_by(id=connection_id).one()
        assert conn.llm_base_url == "https://api.openai.com/v1"
        assert conn.llm_api_key_last4 == "1234"


def test_create_validates_base_url_outside_dev(client, session_factory, monkeypatch) -> None:
    _seed_project(session_factory)
    monkeypatch.setenv("QYM_ENVIRONMENT", "production")

    resp = client.post(
        CONNECTIONS_URL,
        headers=_headers(MANAGER),
        json={
            "name": "internal",
            "llm_base_url": "https://192.168.1.10/v1",
            "llm_model": "gpt-4o-mini",
            "llm_api_key": "sk-secret-1234",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "LLM base URL must not point at a private or internal address"

    with session_factory() as session:
        assert session.query(ProjectLlmConnection).count() == 0


def test_https_public_url_accepted_outside_dev(client, session_factory, monkeypatch) -> None:
    _seed_project(session_factory)
    connection_id = _create_connection(client)
    monkeypatch.setenv("QYM_ENVIRONMENT", "production")
    calls = _patch_resolver(monkeypatch, "93.184.216.34")  # public address

    update = client.put(
        f"{CONNECTIONS_URL}/{connection_id}",
        headers=_headers(MANAGER),
        json={
            "name": "OpenAI",
            "llm_base_url": "https://llm.example.com/v1",
            "llm_model": "gpt-4o-mini",
            "llm_api_key": "sk-new-key-5678",  # base URL changed, so a fresh key is required
        },
    )
    assert update.status_code == 200, update.text
    payload = update.json()
    assert payload["llm_base_url"] == "https://llm.example.com/v1"
    assert payload["llm_api_key_hint"] == "••••5678"
    assert calls == ["llm.example.com"]  # validation resolved DNS exactly once, no real connection


def test_http_and_local_urls_allowed_in_dev(client, session_factory) -> None:
    _seed_project(session_factory)

    resp = client.post(
        CONNECTIONS_URL,
        headers=_headers(MANAGER),
        json={
            "name": "local ollama",
            "llm_base_url": "http://localhost:11434/v1",
            "llm_model": "llama3",
            "llm_api_key": "sk-local",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["llm_base_url"] == "http://localhost:11434/v1"
