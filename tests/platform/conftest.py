"""Shared fixtures for platform tests.

A repo-root ``.env`` file with real deployment values (OIDC credentials,
``QYM_AUTH_LOCAL_ENABLED=true``, a Postgres ``QYM_DATABASE_URL``, ...) is
loaded by ``PlatformSettings`` at runtime. Every auth-relevant variable is
therefore pinned here so tests are deterministic and order-independent
regardless of what the ambient environment or ``.env`` contains.

``QYM_AUTH_MODE`` is intentionally *not* pinned globally: individual test
modules pick their own mode (none / proxy_headers / oidc) via their own
fixtures, which run after this autouse fixture and override it.
"""

from __future__ import annotations

import os

import pytest

# qym_platform.db.session builds its engine at import time, so the database
# URL must be safe before the first qym_platform import (the .env value
# points at an unreachable Postgres host).
os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")


@pytest.fixture(autouse=True)
def _pin_platform_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("QYM_ENVIRONMENT", "test")
    monkeypatch.setenv("QYM_PROXY_SHARED_SECRET", "")
    monkeypatch.setenv("QYM_AUTO_PROVISION_USERS", "false")
    monkeypatch.setenv("QYM_ADMIN_BOOTSTRAP_TOKEN", "")
    monkeypatch.setenv("QYM_AUTH_LOCAL_ENABLED", "false")
    monkeypatch.setenv("QYM_AUTH_SESSION_SECRET", "")
    monkeypatch.setenv("QYM_AUTH_GOOGLE_CLIENT_ID", "")
    monkeypatch.setenv("QYM_AUTH_GOOGLE_CLIENT_SECRET", "")
    monkeypatch.setenv("QYM_AUTH_GITHUB_CLIENT_ID", "")
    monkeypatch.setenv("QYM_AUTH_GITHUB_CLIENT_SECRET", "")
