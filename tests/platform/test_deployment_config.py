from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_base_compose_is_production_safe() -> None:
    compose = (ROOT / "docker" / "docker-compose.yml").read_text(encoding="utf-8")
    # auth mode is env-driven — never hardcoded off
    assert "QYM_AUTH_MODE: ${QYM_AUTH_MODE}" in compose
    assert "QYM_AUTH_MODE: none" not in compose
    assert "QYM_LLM_CONFIG_ENCRYPTION_KEY" in compose
    # production image must not bind-mount source
    assert "../packages/platform" not in compose


def test_dev_override_restores_reload_and_bind_mounts() -> None:
    compose = (ROOT / "docker" / "docker-compose.dev.yml").read_text(encoding="utf-8")
    assert "QYM_AUTH_MODE: ${QYM_AUTH_MODE}" in compose
    assert "../packages/platform:/app/packages/platform" in compose
    assert "../packages/sdk:/app/packages/sdk" in compose
    assert "--reload" in compose


def test_entrypoint_defaults_to_non_reload_uvicorn() -> None:
    entrypoint = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "--reload" not in entrypoint
    assert 'if [ "$#" -gt 0 ]; then' in entrypoint
