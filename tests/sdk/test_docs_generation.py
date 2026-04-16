from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (REPO_ROOT, REPO_ROOT / "packages" / "sdk", REPO_ROOT / "packages" / "platform"):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)

from tools.docs.generate import generate


def test_generate_docs_payload_and_sources(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("QYM_AUTH_MODE", "none")
    monkeypatch.setenv("QYM_LLM_CONFIG_ENCRYPTION_KEY", "test-key")

    docs_root = tmp_path / "docs_portal"
    static_root = tmp_path / "portal_static"
    payload = generate(docs_root, static_root)

    assert payload["sections"]
    assert any(page["slug"] == "deploy-operate/reference/sdk-environment" for page in payload["pages"])
    assert any(page["slug"] == "api/reference/index" for page in payload["pages"])

    openapi_path = docs_root / "static" / "openapi.json"
    portal_data_path = static_root / "portal-data.json"
    cli_page = docs_root / "docs" / "cli" / "reference" / "run" / "create.mdx"
    config_page = docs_root / "docs" / "deploy-operate" / "reference" / "sdk-environment.mdx"
    example_page = docs_root / "docs" / "examples" / "catalog" / "example.mdx"
    api_group_page = docs_root / "docs" / "api" / "reference" / "runs.mdx"

    assert openapi_path.exists()
    assert portal_data_path.exists()
    assert cli_page.exists()
    assert config_page.exists()
    assert example_page.exists()
    assert api_group_page.exists()

    openapi = json.loads(openapi_path.read_text(encoding="utf-8"))
    portal_data = json.loads(portal_data_path.read_text(encoding="utf-8"))

    assert openapi["info"]["title"] == "qym-platform"
    assert any(page["slug"] == "cli/reference/run/create" for page in portal_data["pages"])
    assert any(page["slug"] == "examples/catalog/example" for page in portal_data["pages"])
