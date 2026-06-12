"""docker/.env.template completeness checks (HP-3).

Parses the compose files for ``${VAR}`` interpolations and asserts every
referenced variable is defined in docker/.env.template, so the template can
never silently drift behind the compose stack again.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = ROOT / "docker" / ".env.template"

_VAR_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)")
_VAR_DEF = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=", re.MULTILINE)


def _compose_var_refs(*filenames: str) -> set[str]:
    refs: set[str] = set()
    for filename in filenames:
        text = (ROOT / "docker" / filename).read_text(encoding="utf-8")
        refs.update(_VAR_REF.findall(text))
    return refs


def _template_var_defs() -> set[str]:
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    return set(_VAR_DEF.findall(text))


def test_template_exists() -> None:
    assert TEMPLATE_PATH.exists(), "docker/.env.template is missing"


def test_template_covers_every_compose_variable() -> None:
    referenced = _compose_var_refs("docker-compose.yml", "docker-compose.dev.yml")
    defined = _template_var_defs()
    missing = sorted(referenced - defined)
    assert not missing, (
        f"docker/.env.template is missing variables referenced by compose: {missing}"
    )


def test_template_documents_usage_and_safe_defaults() -> None:
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    # Compose reads .env from the current directory: both supported workflows
    # must be documented at the top of the template.
    assert "--env-file" in text
    assert "docker/.env" in text
    # Key vars called out by the deployment docs.
    defined = _template_var_defs()
    for var in (
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "POSTGRES_PORT",
        "QYM_ENVIRONMENT",
        "QYM_BASE_URL",
        "QYM_DATABASE_URL",
        "QYM_ADMIN_BOOTSTRAP_TOKEN",
        "QYM_AUTH_MODE",
        "QYM_AUTH_SESSION_SECRET",
        "QYM_LLM_CONFIG_ENCRYPTION_KEY",
        "QYM_PROXY_SHARED_SECRET",
        "QYM_AUTH_GOOGLE_CLIENT_ID",
        "QYM_AUTH_GOOGLE_CLIENT_SECRET",
        "QYM_AUTH_GITHUB_CLIENT_ID",
        "QYM_AUTH_GITHUB_CLIENT_SECRET",
        "BACKUP_KEEP_DAYS",
        "BACKUP_INTERVAL_HOURS",
    ):
        assert var in defined, f"docker/.env.template must define {var}"
    # The Fernet generation one-liner must ship with the encryption key.
    assert "Fernet.generate_key()" in text
    # The in-network database URL must point at the `db` compose service.
    assert "@db:5432" in text


def test_template_secrets_are_placeholders() -> None:
    """Secret-bearing variables must ship empty or as CHANGE_ME placeholders."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    values = dict(re.findall(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", text, re.MULTILINE))
    for var in (
        "QYM_ADMIN_BOOTSTRAP_TOKEN",
        "QYM_AUTH_SESSION_SECRET",
        "QYM_PROXY_SHARED_SECRET",
        "QYM_LLM_CONFIG_ENCRYPTION_KEY",
        "QYM_AUTH_GOOGLE_CLIENT_SECRET",
        "QYM_AUTH_GITHUB_CLIENT_SECRET",
    ):
        value = values[var].strip()
        assert value == "" or value.startswith("CHANGE_ME"), (
            f"{var} in docker/.env.template must stay a placeholder, got {value!r}"
        )


def test_stale_langfuse_block_removed() -> None:
    for path in (TEMPLATE_PATH, ROOT / ".env.template"):
        text = path.read_text(encoding="utf-8")
        assert "LANGFUSE" not in text, f"{path} still references Langfuse"


def test_root_template_points_to_docker_template() -> None:
    text = (ROOT / ".env.template").read_text(encoding="utf-8")
    assert "docker/.env.template" in text
