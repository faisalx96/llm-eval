import os
from unittest.mock import patch

import pytest

from qym.core.config import EvaluatorConfig
from qym.core.dataset import CsvDataset
from qym.core.evaluator import Evaluator
import qym.core.otel as otel_module
from qym.utils.env import get_langfuse_host_env, get_platform_url_env, load_cwd_dotenv


def test_load_cwd_dotenv_only_reads_exact_cwd_file(tmp_path, monkeypatch):
    parent = tmp_path / "parent"
    child = parent / "child"
    parent.mkdir()
    child.mkdir()
    (parent / ".env").write_text("DOTENV_SCOPE=parent\n", encoding="utf-8")

    monkeypatch.chdir(child)
    monkeypatch.delenv("DOTENV_SCOPE", raising=False)

    loaded = load_cwd_dotenv()

    assert loaded is None
    assert os.getenv("DOTENV_SCOPE") is None


def test_evaluator_loads_cwd_dotenv_without_langfuse_client(tmp_path, monkeypatch):
    """Evaluator.__init__ loads the caller's cwd .env into the environment.

    Langfuse client initialization was removed (qym uses platform/OTel
    tracing), so no client is created from credentials — but the dotenv
    loading side effect must still happen for provider keys etc.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    (workspace / ".env").write_text(
        "QYM_TEST_DOTENV_SENTINEL=from-cwd\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("QYM_TEST_DOTENV_SENTINEL", raising=False)

    csv_path = workspace / "qa.csv"
    csv_path.write_text("q,a\nhello,world\n", encoding="utf-8")
    dataset = CsvDataset(csv_path, input_col="q", expected_col="a")

    try:
        with patch("qym.core.evaluator.auto_detect_task"):
            evaluator = Evaluator(
                task=lambda x: x,
                dataset=dataset,
                metrics=[],
                config={"run_name": "dotenv-load", "otel_enabled": False},
                langfuse_client=None,
            )

        assert os.getenv("QYM_TEST_DOTENV_SENTINEL") == "from-cwd"
        assert evaluator.client is None
        assert evaluator.langfuse_enabled is False
    finally:
        # load_cwd_dotenv mutates os.environ directly; monkeypatch cannot
        # restore a key it never saw, so clean up explicitly.
        os.environ.pop("QYM_TEST_DOTENV_SENTINEL", None)


def test_langfuse_base_url_alias_is_used_for_host(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    (workspace / ".env").write_text(
        "LANGFUSE_BASE_URL=https://lf.example.com\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    load_cwd_dotenv()
    assert get_langfuse_host_env() == "https://lf.example.com"


def test_qym_base_url_is_used_for_platform_url(monkeypatch):
    monkeypatch.setenv("QYM_BASE_URL", "https://platform.example.com")
    assert get_platform_url_env() == "https://platform.example.com"


def test_create_otel_manager_reads_phoenix_endpoint_from_cwd_dotenv(tmp_path, monkeypatch):
    pytest.importorskip("opentelemetry.sdk.trace")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    (workspace / ".env").write_text(
        "PHOENIX_ENDPOINT=http://localhost:6006/v1/traces\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("PHOENIX_ENDPOINT", raising=False)
    monkeypatch.delenv("PHOENIX_COLLECTOR_ENDPOINT", raising=False)
    monkeypatch.delenv("PHOENIX_ENABLED", raising=False)

    monkeypatch.setattr(otel_module, "_initialized", False)
    monkeypatch.setattr(otel_module, "_registered_instrumentors", [])
    monkeypatch.setattr(otel_module, "_phoenix_enabled", False)
    monkeypatch.setattr(otel_module, "_phoenix_endpoint", None)
    monkeypatch.setattr(otel_module, "_register_instrumentors", lambda provider: [])
    monkeypatch.setattr(otel_module, "_patch_openai_enrichments", lambda: None)
    monkeypatch.setattr(otel_module, "_patch_anthropic_enrichments", lambda: None)

    manager = otel_module.create_otel_manager(EvaluatorConfig())

    assert manager.phoenix_enabled is True
    assert manager.phoenix_endpoint == "http://localhost:6006/v1/traces"
