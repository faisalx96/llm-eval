from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_base_compose_is_production_safe() -> None:
    compose = (ROOT / "docker" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "QYM_AUTH_MODE: ${QYM_AUTH_MODE:-proxy_headers}" in compose
    assert "QYM_LLM_CONFIG_ENCRYPTION_KEY" in compose
    assert "../packages/platform/qym_platform/api" not in compose
    assert "../packages/platform/qym_platform/_static" not in compose


def test_dev_override_restores_reload_and_bind_mounts() -> None:
    compose = (ROOT / "docker" / "docker-compose.dev.yml").read_text(encoding="utf-8")
    assert "QYM_AUTH_MODE: none" in compose
    assert "../packages/platform/qym_platform/api:/app/packages/platform/qym_platform/api" in compose
    assert "../packages/platform/qym_platform/_static:/app/packages/platform/qym_platform/_static" in compose
    assert "--reload" in compose


def test_entrypoint_defaults_to_non_reload_uvicorn() -> None:
    entrypoint = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "--reload" not in entrypoint
    assert 'if [ "$#" -gt 0 ]; then' in entrypoint
