from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (REPO_ROOT, REPO_ROOT / "packages" / "sdk", REPO_ROOT / "packages" / "platform"):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)

from qym_platform.app import create_app
from qym_platform import docs_site


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


def test_docs_slashless_routes_redirect_to_asset_safe_paths(monkeypatch) -> None:
    _configure_env(monkeypatch)
    app = create_app()

    with TestClient(app, follow_redirects=False) as client:
        root = client.get("/docs")
        assert root.status_code == 307
        assert root.headers["location"].endswith("/docs/")

        section = client.get("/docs/sdk")
        assert section.status_code == 307
        assert section.headers["location"].endswith("/docs/sdk/")

        index = client.get("/docs/")
        assert index.status_code == 200
        assert 'rel="icon"' in index.text
        css_match = re.search(r'href="([^"]+\.css)"', index.text)
        assert css_match

        icon = client.get("/docs/img/qym_icon.png")
        assert icon.status_code == 200
        assert "image/png" in icon.headers.get("content-type", "")

        css_url = urljoin("http://testserver/docs/", css_match.group(1))
        css = client.get(urlparse(css_url).path)
        assert css.status_code == 200
        assert "text/css" in css.headers.get("content-type", "")

        js_match = re.search(r'src="([^"]+\.js)"', index.text)
        assert js_match

        js_url = urljoin("http://testserver/docs/", js_match.group(1))
        js = client.get(urlparse(js_url).path)
        assert js.status_code == 200
        assert "javascript" in js.headers.get("content-type", "")

        nested_js = client.get("/docs/sdk/" + js_match.group(1).lstrip("./"))
        assert nested_js.status_code == 200
        assert "javascript" in nested_js.headers.get("content-type", "")

        missing_js = client.get("/docs/assets/js/does-not-exist.js")
        assert missing_js.status_code == 404


def test_packaged_docs_portal_assets_resolve_from_deep_links(monkeypatch) -> None:
    _configure_env(monkeypatch)
    monkeypatch.setattr(docs_site, "docs_build_dir", lambda: REPO_ROOT / ".missing-docs-build")
    app = create_app()

    with TestClient(app) as client:
        page = client.get("/docs/cli/reference/dashboard/")
        assert page.status_code == 200
        assert "./qym_icon.png" in page.text
        assert "./portal.css" in page.text
        assert "./portal.js" in page.text

        data = client.get("/docs/cli/reference/dashboard/portal-data.json")
        assert data.status_code == 200
        assert data.headers.get("cache-control") == "no-store"
        assert data.json()["pages"][0]["body_mdx"]

        icon = client.get("/docs/cli/reference/dashboard/qym_icon.png")
        assert icon.status_code == 200
        assert "image/png" in icon.headers.get("content-type", "")

        css = client.get("/docs/cli/reference/dashboard/portal.css")
        assert css.status_code == 200
        assert "text/css" in css.headers.get("content-type", "")
        assert css.headers.get("cache-control") == "no-store"

        script = client.get("/docs/cli/reference/dashboard/portal.js")
        assert script.status_code == 200
        assert "javascript" in script.headers.get("content-type", "")
        assert script.headers.get("cache-control") == "no-store"
        assert "body_mdx" in script.text
        assert "history.pushState" in script.text
        assert "popstate" in script.text


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
