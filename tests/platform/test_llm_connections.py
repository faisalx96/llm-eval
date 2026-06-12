"""SEC-2 regression tests: LLM-connection hardening.

Covers the audit finding "Provider API-key exfiltration via SSRF on LLM
connections" (AUDIT_REPORT.md 1.2 / OVERHAUL_PLAN.md SEC-2):
- validate_llm_base_url rejects non-https / credentialed / private-address URLs
  outside dev environments,
- connection writes (create/update/delete/set-default/test) are manager-only,
- the "__KEEP__" key sentinel is rejected when the base URL changes.
"""

from __future__ import annotations

import os
import socket
import sys
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

import qym_platform.url_guard as url_guard
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
from qym_platform.url_guard import validate_llm_base_url

PROJECT_ID = "proj-1"
CONNECTIONS_URL = f"/v1/projects/{PROJECT_ID}/llm-connections"
MANAGER_EMAIL = "manager@example.com"
MEMBER_EMAIL = "member@example.com"
OPENAI_URL = "https://api.openai.com/v1"


# ── A) URL-guard unit tests ──────────────────────────────────────────────────
# Every rejection below short-circuits before DNS resolution (bad scheme,
# embedded credentials, or a literal IP), so none of these depend on the network.


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/v1",  # https required outside dev
        "https://127.0.0.1:8080/v1",  # loopback
        "https://[::1]/v1",  # IPv6 loopback
        "https://[::ffff:127.0.0.1]/v1",  # IPv4-mapped IPv6 loopback
        "https://169.254.169.254/latest/meta-data",  # cloud metadata (link-local)
        "https://10.0.0.5/v1",  # private 10/8
        "https://192.168.1.10/v1",  # private 192.168/16
        "https://user:pass@api.example.com/v1",  # embedded credentials
        "ftp://api.example.com/v1",  # non-http(s) scheme
        "",  # empty
    ],
)
def test_production_rejects_unsafe_url(url: str) -> None:
    with pytest.raises(ValueError):
        validate_llm_base_url(url, environment="production")


def test_production_accepts_literal_public_ip() -> None:
    # Literal public IPs are validated without any DNS lookup.
    validate_llm_base_url("https://8.8.8.8/v1", environment="production")


def test_dev_accepts_local_http() -> None:
    validate_llm_base_url("http://localhost:11434", environment="dev")


def _fake_getaddrinfo(address: str):
    def fake(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port or 443))]

    return fake


def test_production_rejects_hostname_resolving_to_private_ip(monkeypatch) -> None:
    # A public-looking hostname whose DNS answer is internal (DNS-rebinding style).
    monkeypatch.setattr(url_guard.socket, "getaddrinfo", _fake_getaddrinfo("10.20.30.40"))
    with pytest.raises(ValueError, match="private or internal"):
        validate_llm_base_url("https://innocent-looking.example.com/v1", environment="production")


def test_production_accepts_hostname_resolving_to_public_ip(monkeypatch) -> None:
    monkeypatch.setattr(url_guard.socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    validate_llm_base_url("https://api.example.com/v1", environment="production")


def test_production_rejects_unresolvable_hostname(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise socket.gaierror("name or service not known")

    monkeypatch.setattr(url_guard.socket, "getaddrinfo", boom)
    with pytest.raises(ValueError, match="could not be resolved"):
        validate_llm_base_url("https://api.example.com/v1", environment="production")


# ── B) Endpoint tests (dev-mode app, proxy_headers auth) ─────────────────────


@pytest.fixture()
def session_factory(monkeypatch):
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("QYM_AUTH_MODE", "proxy_headers")
    monkeypatch.setenv("QYM_ENVIRONMENT", "dev")
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


def _seed_project_with_roles(session_factory) -> None:
    """One MANAGER and one plain MEMBER on the project; neither is a platform admin."""
    with session_factory() as session:
        session.add(User(id="manager-1", email=MANAGER_EMAIL, role=UserRole.MEMBER))
        session.add(User(id="member-1", email=MEMBER_EMAIL, role=UserRole.MEMBER))
        session.add(
            Project(id=PROJECT_ID, name="Proj", slug="proj", created_by_user_id="manager-1")
        )
        session.add(
            ProjectMembership(project_id=PROJECT_ID, user_id="manager-1", role=ProjectRole.MANAGER)
        )
        session.add(
            ProjectMembership(project_id=PROJECT_ID, user_id="member-1", role=ProjectRole.MEMBER)
        )
        session.commit()


def _create_connection(
    client,
    *,
    name: str = "conn",
    api_key: str = "sk-secret-1234",
    base_url: str = OPENAI_URL,
) -> dict:
    resp = client.post(
        CONNECTIONS_URL,
        headers=_headers(MANAGER_EMAIL),
        json={
            "name": name,
            "llm_base_url": base_url,
            "llm_api_key": api_key,
            "llm_model": "gpt-4o-mini",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_member_gets_403_on_connection_writes(client, session_factory) -> None:
    _seed_project_with_roles(session_factory)
    connection_id = _create_connection(client)["id"]

    member = _headers(MEMBER_EMAIL)
    payload = {
        "name": "hijacked",
        "llm_base_url": OPENAI_URL,
        "llm_api_key": "sk-other-5678",
        "llm_model": "gpt-4o-mini",
    }

    create = client.post(CONNECTIONS_URL, headers=member, json=payload)
    assert create.status_code == 403
    assert create.json()["detail"] == "Project manager access required"
    assert client.put(f"{CONNECTIONS_URL}/{connection_id}", headers=member, json=payload).status_code == 403
    assert client.post(f"{CONNECTIONS_URL}/{connection_id}/set-default", headers=member).status_code == 403
    assert client.post(f"{CONNECTIONS_URL}/{connection_id}/test", headers=member).status_code == 403
    assert client.delete(f"{CONNECTIONS_URL}/{connection_id}", headers=member).status_code == 403

    # Read access for plain members is unchanged.
    listing = client.get(CONNECTIONS_URL, headers=member)
    assert listing.status_code == 200
    assert len(listing.json()["connections"]) == 1


def test_manager_can_manage_connections(client, session_factory) -> None:
    _seed_project_with_roles(session_factory)
    first = _create_connection(client, name="primary")
    second = _create_connection(client, name="secondary", api_key="sk-secret-5678")
    assert first["is_default"] is True
    assert second["is_default"] is False

    manager = _headers(MANAGER_EMAIL)
    update = client.put(
        f"{CONNECTIONS_URL}/{second['id']}",
        headers=manager,
        json={
            "name": "secondary renamed",
            "llm_base_url": OPENAI_URL,
            "llm_api_key": "__KEEP__",
            "llm_model": "gpt-4o",
        },
    )
    assert update.status_code == 200
    assert update.json()["name"] == "secondary renamed"

    set_default = client.post(f"{CONNECTIONS_URL}/{second['id']}/set-default", headers=manager)
    assert set_default.status_code == 200
    assert set_default.json()["is_default"] is True

    delete = client.delete(f"{CONNECTIONS_URL}/{second['id']}", headers=manager)
    assert delete.status_code == 200
    # The remaining connection is promoted back to default.
    listing = client.get(CONNECTIONS_URL, headers=manager).json()["connections"]
    assert [c["id"] for c in listing] == [first["id"]]
    assert listing[0]["is_default"] is True


def test_keep_sentinel_rejected_when_base_url_changes(client, session_factory) -> None:
    _seed_project_with_roles(session_factory)
    connection_id = _create_connection(client)["id"]

    resp = client.put(
        f"{CONNECTIONS_URL}/{connection_id}",
        headers=_headers(MANAGER_EMAIL),
        json={
            "name": "conn",
            "llm_base_url": "https://attacker.example.com/v1",
            "llm_api_key": "__KEEP__",
            "llm_model": "gpt-4o-mini",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Re-enter the API key when changing the base URL"

    # Neither the destination nor the stored key was touched.
    with session_factory() as session:
        conn = session.query(ProjectLlmConnection).filter_by(id=connection_id).first()
        assert conn.llm_base_url == OPENAI_URL
        assert conn.llm_api_key_last4 == "1234"


def test_keep_sentinel_with_same_base_url_preserves_key(client, session_factory) -> None:
    _seed_project_with_roles(session_factory)
    connection_id = _create_connection(client)["id"]
    with session_factory() as session:
        before = session.query(ProjectLlmConnection).filter_by(id=connection_id).first()
        encrypted_before = before.llm_api_key_encrypted
    assert encrypted_before

    resp = client.put(
        f"{CONNECTIONS_URL}/{connection_id}",
        headers=_headers(MANAGER_EMAIL),
        json={
            "name": "conn renamed",
            "llm_base_url": OPENAI_URL,
            "llm_api_key": "__KEEP__",
            "llm_model": "gpt-4o",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["llm_api_key_set"] is True

    with session_factory() as session:
        conn = session.query(ProjectLlmConnection).filter_by(id=connection_id).first()
        assert conn.llm_api_key_encrypted == encrypted_before
        assert conn.llm_api_key_last4 == "1234"
        assert conn.llm_model == "gpt-4o"


def test_create_rejects_unsafe_url_outside_dev(client, session_factory, monkeypatch) -> None:
    _seed_project_with_roles(session_factory)
    # PlatformSettings is constructed per request, so flipping the environment after
    # app startup exercises the production URL guard inside the endpoint.
    monkeypatch.setenv("QYM_ENVIRONMENT", "production")

    resp = client.post(
        CONNECTIONS_URL,
        headers=_headers(MANAGER_EMAIL),
        json={
            "name": "metadata",
            "llm_base_url": "https://169.254.169.254/latest",
            "llm_api_key": "sk-secret-1234",
            "llm_model": "gpt-4o-mini",
        },
    )
    assert resp.status_code == 400
    assert "private or internal" in resp.json()["detail"]
