from __future__ import annotations

import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (REPO_ROOT, REPO_ROOT / "packages" / "sdk", REPO_ROOT / "packages" / "platform"):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)

from qym_platform import docs_site
from qym_platform.app import create_app


def _configure_env(monkeypatch) -> None:
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("QYM_AUTH_MODE", "none")
    monkeypatch.setenv("QYM_LLM_CONFIG_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))


@pytest.fixture
def tmp_docs_root(monkeypatch, tmp_path):
    """Point the docs site at an isolated tmp tree so traversal targets a known-secret outside it."""
    docs_root = tmp_path / "docs_build"
    (docs_root / "assets" / "js").mkdir(parents=True)
    (docs_root / "index.html").write_text("<html><body>qym Developer Portal</body></html>", encoding="utf-8")
    (docs_root / "assets" / "js" / "app.js").write_text("console.log('ok');", encoding="utf-8")

    # A secret file that lives OUTSIDE the docs root; traversal must never reach it.
    secret = tmp_path / "secret.env"
    secret.write_text("SECRET_TOKEN=should-never-leak", encoding="utf-8")

    monkeypatch.setattr(docs_site, "docs_build_dir", lambda: docs_root)
    monkeypatch.setattr(docs_site, "docs_static_dir", lambda: docs_root)
    return docs_root


# ---------------------------------------------------------------------------
# Unit-level checks against the candidate-path generator and helpers.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw_path",
    [
        "../secret.env",
        "../../secret.env",
        "assets/../../secret.env",
        "assets/../../../secret.env",
        "assets/..%2f..%2f..%2f..%2f.env",  # literal (un-decoded) form
        "a/../../secret.env",
        "\\windows\\system32",
        "assets\\..\\..\\secret.env",
    ],
)
def test_unsafe_paths_yield_no_candidates(tmp_docs_root, raw_path) -> None:
    candidates = list(docs_site._candidate_paths(raw_path))
    docs_root_resolved = tmp_docs_root.resolve()
    for candidate in candidates:
        assert docs_site._contained(candidate, tmp_docs_root)
        assert "secret.env" not in candidate.name


def test_assets_branch_traversal_yields_no_escape(tmp_docs_root) -> None:
    # The previously-vulnerable assets branch: every yielded candidate must stay contained.
    candidates = list(docs_site._candidate_paths("assets/../../../../secret.env"))
    for candidate in candidates:
        assert docs_site._contained(candidate, tmp_docs_root)


def test_legitimate_asset_yields_contained_candidate(tmp_docs_root) -> None:
    candidates = list(docs_site._candidate_paths("assets/js/app.js"))
    assert candidates, "expected the real asset to produce candidates"
    assert all(docs_site._contained(c, tmp_docs_root) for c in candidates)
    assert any(c.name == "app.js" for c in candidates)


def test_is_unsafe_request_path_flags() -> None:
    assert docs_site._is_unsafe_request_path("../x")
    assert docs_site._is_unsafe_request_path("a/../../x")
    assert docs_site._is_unsafe_request_path("a\\b")
    assert docs_site._is_unsafe_request_path("/etc/passwd")
    assert not docs_site._is_unsafe_request_path("assets/js/app.js")
    assert not docs_site._is_unsafe_request_path("cli/reference/run/")
    assert not docs_site._is_unsafe_request_path("")


# ---------------------------------------------------------------------------
# End-to-end checks through the FastAPI app / TestClient.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "/docs/assets/..%2f..%2f..%2f..%2f.env",  # the exact documented exploit
        "/docs/assets/%2e%2e%2f%2e%2e%2fsecret.env",
        "/docs/..%2f..%2fsecret.env",
        "/docs/assets/..%5c..%5csecret.env",  # backslash variant (urlencoded)
        "/docs/%2fetc%2fpasswd",  # absolute path
    ],
)
def test_traversal_attempts_return_404(monkeypatch, tmp_docs_root, url) -> None:
    _configure_env(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        response = client.get(url)
        assert response.status_code == 404, (url, response.status_code, response.text[:200])
        assert "SECRET_TOKEN" not in response.text


def test_raw_dotdot_traversal_does_not_leak(monkeypatch, tmp_docs_root) -> None:
    _configure_env(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        # Starlette may collapse some raw "../" segments at the routing layer; whatever
        # reaches the handler must not leak the secret. Asset-shaped path -> 404.
        response = client.get("/docs/assets/../../../secret.env")
        assert "SECRET_TOKEN" not in response.text
        assert response.status_code in (404, 307)


def test_legitimate_asset_serves_200(monkeypatch, tmp_docs_root) -> None:
    _configure_env(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/docs/assets/js/app.js")
        assert response.status_code == 200
        assert "console.log" in response.text
