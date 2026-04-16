from __future__ import annotations

import sys
from pathlib import Path

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (REPO_ROOT, REPO_ROOT / "packages" / "sdk", REPO_ROOT / "packages" / "platform"):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)

from qym_platform.app import create_app


def _configure_env(monkeypatch) -> None:
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("QYM_AUTH_MODE", "none")
    monkeypatch.setenv("QYM_LLM_CONFIG_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))


def test_docs_portal_is_served(monkeypatch) -> None:
    _configure_env(monkeypatch)
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/docs/")
        assert response.status_code == 200
        assert "qym" in response.text.lower()
        assert ("Developer Portal" in response.text) or ("qym Docs" in response.text)
        assert "First Success" in response.text

        openapi = client.get("/docs/openapi.json")
        assert openapi.status_code == 200
        assert openapi.json()["info"]["title"] == "qym-platform"


def test_docs_deep_links_fallback_to_index(monkeypatch) -> None:
    _configure_env(monkeypatch)
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/docs/cli/reference/run/create/")
        assert response.status_code == 200
        assert "qym" in response.text.lower()
        assert "Run Create" in response.text


def test_api_docs_moved_off_docs_route(monkeypatch) -> None:
    _configure_env(monkeypatch)
    app = create_app()

    with TestClient(app) as client:
        swagger = client.get("/api-docs")
        assert swagger.status_code == 200
        assert "Swagger UI" in swagger.text

        openapi = client.get("/openapi.json")
        assert openapi.status_code == 200
        assert openapi.json()["info"]["title"] == "qym-platform"


def test_docs_root_path_works(monkeypatch) -> None:
    _configure_env(monkeypatch)
    monkeypatch.setenv("QYM_ROOT_PATH", "/qym")
    app = create_app()

    with TestClient(app, root_path="/qym", base_url="http://testserver/qym") as client:
        response = client.get("/docs/")
        assert response.status_code == 200
        assert "qym" in response.text.lower()
        assert 'window.__QYM_DOCS_BASE_URL__' in response.text

        data = client.get("/docs/openapi.json")
        assert data.status_code == 200
        assert data.json()["info"]["title"] == "qym-platform"
