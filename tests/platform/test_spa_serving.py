"""SPA serving tests: shell injection, route takeover, catch-all, redirects.

The SPA build (``qym_platform/_static/app``) is gitignored output of
``npm run build`` in ``packages/platform/frontend``; every test that needs the
shell is skipped when the build is absent so CI without a frontend build stays
green.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("QYM_AUTH_MODE", "none")
ROOT = Path(__file__).resolve().parents[2]
PLATFORM_SRC = ROOT / "packages" / "platform"
if str(PLATFORM_SRC) not in sys.path:
    sys.path.insert(0, str(PLATFORM_SRC))
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

from qym_platform.app import create_app
from qym_platform.db.base import Base
from qym_platform.db.models import Project, Run, RunWorkflowStatus, User, UserRole
from qym_platform.deps import get_db
from qym_platform.spa import SPA_ASSETS_DIR, SPA_INDEX

spa_built = pytest.mark.skipif(
    not SPA_INDEX.exists(),
    reason="SPA assets not built (run npm run build in packages/platform/frontend)",
)


@pytest.fixture()
def session_factory(monkeypatch):
    # Pin every auth-relevant env var: a repo-root .env with real values exists
    # and PlatformSettings loads it from cwd, so nothing may leak in.
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("QYM_AUTH_MODE", "none")
    monkeypatch.setenv("QYM_ENVIRONMENT", "test")
    monkeypatch.setenv("QYM_PROXY_SHARED_SECRET", "")
    monkeypatch.setenv("QYM_AUTH_LOCAL_ENABLED", "false")
    monkeypatch.setenv("QYM_AUTH_SESSION_SECRET", "")
    monkeypatch.setenv("QYM_AUTO_PROVISION_USERS", "false")
    monkeypatch.setenv("QYM_ADMIN_BOOTSTRAP_TOKEN", "")
    monkeypatch.setenv("QYM_AUTH_GOOGLE_CLIENT_ID", "")
    monkeypatch.setenv("QYM_AUTH_GOOGLE_CLIENT_SECRET", "")
    monkeypatch.setenv("QYM_AUTH_GITHUB_CLIENT_ID", "")
    monkeypatch.setenv("QYM_AUTH_GITHUB_CLIENT_SECRET", "")
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


def _seed(session_factory) -> None:
    with session_factory() as session:
        admin = User(id="u-admin", email="admin@example.com", role=UserRole.ADMIN)
        project = Project(id="proj-a", name="Alpha", slug="alpha", created_by_user_id=admin.id)
        run = Run(
            id="run-spa-1",
            project_id=project.id,
            created_by_user_id=admin.id,
            owner_user_id=admin.id,
            task="qa",
            dataset="ds1",
            model="openai/gpt-4o",
            metrics=["judge"],
            status=RunWorkflowStatus.COMPLETED,
            run_metadata={},
            run_config={},
        )
        session.add_all([admin, project, run])
        session.commit()


@pytest.fixture()
def app(session_factory):
    application = create_app()
    _seed(session_factory)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    application.dependency_overrides[get_db] = override_get_db
    try:
        yield application
    finally:
        application.dependency_overrides.clear()


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def _assert_spa_shell(resp) -> None:
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "__QYM_BOOT__" in resp.text
    assert "app-assets" in resp.text
    # No un-rewritten relative asset URLs may survive.
    assert '"./assets/' not in resp.text


@spa_built
def test_root_serves_spa_shell(client):
    resp = client.get("/")
    _assert_spa_shell(resp)
    assert '"auth_mode": "none"' in resp.text or '"auth_mode":"none"' in resp.text


@spa_built
def test_project_page_serves_spa_shell_even_for_unknown_slug(client):
    _assert_spa_shell(client.get("/projects/anything"))


@spa_built
def test_project_run_page_serves_spa_shell(client):
    _assert_spa_shell(client.get("/projects/alpha/runs/run-spa-1"))


@spa_built
def test_profile_and_admin_serve_spa_shell(client):
    _assert_spa_shell(client.get("/profile"))
    _assert_spa_shell(client.get("/admin"))


@spa_built
def test_spa_only_route_served_by_catch_all(client):
    _assert_spa_shell(client.get("/projects/x/analysis"))


def test_healthz_still_json(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["ok"] is True


def test_v1_projects_still_json(client):
    resp = client.get("/v1/projects")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert isinstance(body["projects"], list)


def test_unknown_api_path_is_404_not_spa(client):
    for path in ("/api/zzz", "/v1/zzz", "/static/zzz.js", "/ui/zzz", "/app-assets/zzz.js"):
        resp = client.get(path)
        assert resp.status_code == 404, path
        assert "__QYM_BOOT__" not in resp.text, path


def test_file_like_paths_are_404_not_spa(client):
    # A dot in the final segment is never a client route (traversal probes,
    # favicons, stray asset URLs) — the catch-all must not answer 200.
    for path in ("/secret.env", "/favicon.ico", "/projects/x/notes.txt"):
        resp = client.get(path)
        assert resp.status_code == 404, path
        assert "__QYM_BOOT__" not in resp.text, path


def test_docs_unaffected_by_catch_all(client):
    resp = client.get("/docs/", follow_redirects=True)
    # Docs are served when built; either way the SPA never swallows /docs.
    assert "__QYM_BOOT__" not in resp.text
    assert resp.status_code in (200, 404)


def test_run_redirects_to_canonical_project_url(client):
    resp = client.get("/run/run-spa-1", follow_redirects=False)
    assert resp.status_code == 308
    assert resp.headers["location"] == "/projects/alpha/runs/run-spa-1"


def test_run_redirect_unknown_run_is_404(client):
    assert client.get("/run/nope", follow_redirects=False).status_code == 404


@spa_built
def test_legacy_charts_page_still_serves_legacy_html(client):
    resp = client.get("/projects/alpha/charts")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "__QYM_BOOT__" not in resp.text  # legacy page, not the SPA shell
    assert "/static/" in resp.text


@spa_built
def test_root_path_injected_into_shell(app):
    with TestClient(app, root_path="/qym") as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "/qym/app-assets/" in resp.text
        assert 'window.__QYM_ROOT_PATH__="/qym"' in resp.text


@spa_built
def test_assets_served_with_immutable_cache_header(client):
    asset = next(p for p in SPA_ASSETS_DIR.iterdir() if p.suffix == ".js")
    resp = client.get(f"/app-assets/assets/{asset.name}")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"


@spa_built
def test_unhashed_mount_files_not_marked_immutable(client):
    # index.html (unhashed) is reachable through the mount but must never be
    # cached for a year — only content-hashed assets/ files are immutable.
    resp = client.get("/app-assets/index.html")
    assert resp.status_code == 200
    assert "immutable" not in resp.headers.get("cache-control", "")


@spa_built
def test_shell_rewrites_relative_assets_to_app_assets_assets(client):
    # vite renderBuiltUrl runtime chunks load from /app-assets/assets/<file>,
    # so the shell's rewritten URLs must point into the same tree.
    resp = client.get("/")
    assert '"/app-assets/assets/' in resp.text
