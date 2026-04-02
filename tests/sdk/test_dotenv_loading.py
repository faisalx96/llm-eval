import os
from unittest.mock import patch

import pytest

from qym.core.config import EvaluatorConfig
from qym.core.dataset import CsvDataset
from qym.core.evaluator import Evaluator
import qym.core.otel as otel_module
from qym.utils.env import load_cwd_dotenv


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


def test_evaluator_loads_langfuse_credentials_from_cwd_dotenv(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    (workspace / ".env").write_text(
        "LANGFUSE_PUBLIC_KEY=pk-test\nLANGFUSE_SECRET_KEY=sk-test\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    csv_path = workspace / "qa.csv"
    csv_path.write_text("q,a\nhello,world\n", encoding="utf-8")
    dataset = CsvDataset(csv_path, input_col="q", expected_col="a")
    sentinel_client = object()

    with patch("qym.core.evaluator.auto_detect_task"), patch.object(
        Evaluator, "_init_langfuse", autospec=True, return_value=sentinel_client
    ) as init_langfuse:
        evaluator = Evaluator(
            task=lambda x: x,
            dataset=dataset,
            metrics=[],
            config={"run_name": "dotenv-langfuse", "otel_enabled": False},
            langfuse_client=None,
        )

    assert evaluator.client is sentinel_client
    assert evaluator.langfuse_enabled is True
    init_langfuse.assert_called_once()


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
