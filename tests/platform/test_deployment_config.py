from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_base_compose_is_production_safe() -> None:
    compose = (ROOT / "docker" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "QYM_AUTH_MODE: ${QYM_AUTH_MODE:-proxy_headers}" in compose
    assert "QYM_PROXY_SHARED_SECRET: ${QYM_PROXY_SHARED_SECRET:-}" in compose
    assert "QYM_LLM_CONFIG_ENCRYPTION_KEY" in compose
    assert "../packages/platform/qym_platform/api" not in compose
    assert "../packages/platform/qym_platform/_static" not in compose


def test_base_compose_binds_postgres_to_loopback() -> None:
    compose = (ROOT / "docker" / "docker-compose.yml").read_text(encoding="utf-8")
    assert '"127.0.0.1:${POSTGRES_PORT:-5432}:5432"' in compose


def test_dev_override_restores_reload_and_bind_mounts() -> None:
    compose = (ROOT / "docker" / "docker-compose.dev.yml").read_text(encoding="utf-8")
    assert "QYM_AUTH_MODE: ${QYM_AUTH_MODE:-none}" in compose
    assert "QYM_ENVIRONMENT: ${QYM_ENVIRONMENT:-dev}" in compose
    assert "QYM_PROXY_SHARED_SECRET: ${QYM_PROXY_SHARED_SECRET:-}" in compose
    assert "../packages/platform:/app/packages/platform" in compose
    assert "../packages/sdk:/app/packages/sdk" in compose
    assert "--reload" in compose


def test_entrypoint_defaults_to_non_reload_uvicorn() -> None:
    entrypoint = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "--reload" not in entrypoint
    assert 'if [ "$#" -gt 0 ]; then' in entrypoint
