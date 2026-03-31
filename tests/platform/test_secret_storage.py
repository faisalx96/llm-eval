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
from qym_platform.db.models import User, UserRole
from qym_platform.deps import get_db


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


def _seed_user(session_factory, *, llm_config: dict | None = None) -> None:
    with session_factory() as session:
        session.add(
            User(
                id="user-1",
                email="user@example.com",
                role=UserRole.EMPLOYEE,
                llm_config=llm_config or {},
            )
        )
        session.commit()


def test_llm_config_is_encrypted_and_masked(client, session_factory, monkeypatch) -> None:
    _seed_user(session_factory)

    update_response = client.put(
        "/v1/me/llm-config",
        headers=_headers("user@example.com"),
        json={
            "llm_base_url": "https://api.openai.com/v1",
            "llm_api_key": "sk-secret-1234",
            "llm_model": "gpt-4o-mini",
        },
    )
    assert update_response.status_code == 200

    with session_factory() as session:
        user = session.query(User).filter(User.email == "user@example.com").first()
        assert user is not None
        assert "llm_api_key" not in user.llm_config
        assert user.llm_config["llm_api_key_encrypted"]
        assert user.llm_config["llm_api_key_last4"] == "1234"

    get_response = client.get("/v1/me/llm-config", headers=_headers("user@example.com"))
    assert get_response.status_code == 200
    assert get_response.json()["llm_config_storage_ready"] is True
    assert get_response.json()["llm_api_key_set"] is True
    assert get_response.json()["llm_api_key_hint"] == "••••1234"

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
    test_response = client.post("/v1/me/llm-config/test", headers=_headers("user@example.com"))
    assert test_response.status_code == 200
    assert captured["api_key"] == "sk-secret-1234"
    calls = captured["calls"]
    assert isinstance(calls, list)
    assert len(calls) == 2
    assert calls[0]["max_tokens"] == 4
    assert calls[1]["max_completion_tokens"] == 4
    assert "max_tokens" not in calls[1]


def test_legacy_plaintext_llm_config_is_readable_and_rewritten_on_update(client, session_factory) -> None:
    _seed_user(
        session_factory,
        llm_config={
            "llm_base_url": "https://api.openai.com/v1",
            "llm_api_key": "legacy-secret-9999",
            "llm_model": "gpt-4o-mini",
        },
    )

    get_response = client.get("/v1/me/llm-config", headers=_headers("user@example.com"))
    assert get_response.status_code == 200
    assert get_response.json()["llm_config_storage_ready"] is True
    assert get_response.json()["llm_api_key_set"] is True
    assert get_response.json()["llm_api_key_hint"] == "••••9999"

    update_response = client.put(
        "/v1/me/llm-config",
        headers=_headers("user@example.com"),
        json={
            "llm_base_url": "https://api.openai.com/v1",
            "llm_api_key": "__KEEP__",
            "llm_model": "gpt-4o-mini",
        },
    )
    assert update_response.status_code == 200

    with session_factory() as session:
        user = session.query(User).filter(User.email == "user@example.com").first()
        assert user is not None
        assert "llm_api_key" not in user.llm_config
        assert user.llm_config["llm_api_key_encrypted"]
        assert user.llm_config["llm_api_key_last4"] == "9999"


def test_llm_config_reports_missing_encryption_key(monkeypatch, session_factory) -> None:
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("QYM_AUTH_MODE", "proxy_headers")
    monkeypatch.delenv("QYM_LLM_CONFIG_ENCRYPTION_KEY", raising=False)
    _seed_user(session_factory)

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
            get_response = client.get("/v1/me/llm-config", headers=_headers("user@example.com"))
            assert get_response.status_code == 200
            assert get_response.json()["llm_config_storage_ready"] is False

            update_response = client.put(
                "/v1/me/llm-config",
                headers=_headers("user@example.com"),
                json={
                    "llm_base_url": "https://api.openai.com/v1",
                    "llm_api_key": "sk-secret-1234",
                    "llm_model": "gpt-4o-mini",
                },
            )
            assert update_response.status_code == 400
            assert update_response.json()["detail"] == "LLM config encryption is not configured"
    finally:
        app.dependency_overrides.clear()
