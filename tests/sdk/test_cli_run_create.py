"""End-to-end test for `qym run create` (the documented CLI happy path).

Runs a tiny 2-item local CSV eval with a pure-python task loaded from a temp
task file, using the builtin exact_match metric. No network: QYM_API_KEY is
unset, so the evaluator skips platform streaming entirely (evaluator.arun only
creates a platform run when an API key is configured).
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from qym.cli.app import app

TASK_SOURCE = '''
def my_task(question, model_name=None, trace_id=None):
    """Echo task so exact_match scores 1.0 for every item."""
    if isinstance(question, dict):
        question = question.get("question", question)
    return str(question).strip()
'''

CSV_SOURCE = "input,expected_output\nhello,hello\nworld,world\n"


@pytest.fixture()
def offline_env(monkeypatch, tmp_path):
    """Isolate the CLI from any platform: no API key, no base URL, temp cwd."""
    monkeypatch.delenv("QYM_API_KEY", raising=False)
    monkeypatch.delenv("QYM_BASE_URL", raising=False)
    monkeypatch.delenv("QYM_PLATFORM_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write_inputs(tmp_path):
    task_file = tmp_path / "my_task.py"
    task_file.write_text(TASK_SOURCE, encoding="utf-8")
    csv_file = tmp_path / "qa.csv"
    csv_file.write_text(CSV_SOURCE, encoding="utf-8")
    return task_file, csv_file


def test_run_create_local_csv_with_output_file(offline_env):
    tmp_path = offline_env
    task_file, csv_file = _write_inputs(tmp_path)
    output_file = tmp_path / "results.json"

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "create",
            "--task-file",
            str(task_file),
            "--task-function",
            "my_task",
            "--dataset-file",
            str(csv_file),
            "--metrics",
            "exact_match",
            "--no-ui",
            "--no-open",
            "--no-progress",
            "--output",
            str(output_file),
        ],
    )

    assert result.exit_code == 0, result.output

    # The CLI saved the results explicitly to --output.
    assert output_file.exists()
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["total_items"] == 2
    results = payload.get("results") or []
    assert len(results) == 2


def test_run_create_local_csv_default_save(offline_env):
    """Without --output the evaluator persists results itself (no crash, exit 0)."""
    tmp_path = offline_env
    task_file, csv_file = _write_inputs(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "create",
            "--task-file",
            str(task_file),
            "--task-function",
            "my_task",
            "--dataset-file",
            str(csv_file),
            "--metrics",
            "exact_match",
            "--no-ui",
            "--no-open",
            "--no-progress",
            "--quiet",
        ],
    )

    assert result.exit_code == 0, result.output

    # Default config saves a results CSV under qym_results/<task>/<model>/<date>/
    # in the cwd (checkpoint/auto-save path) - exactly one save, no duplicates.
    results_dir = tmp_path / "qym_results"
    assert results_dir.exists()
    saved = list(results_dir.rglob("*.csv"))
    assert len(saved) == 1


class _FakeResult:
    """Minimal stand-in for EvaluationResult covering what run_create touches."""

    run_name = "fake-run"
    success_rate = 1.0
    total_items = 2
    interrupted = False
    html_url = None
    last_saved_path = None

    def to_dict(self):
        return {"run_name": self.run_name, "total_items": self.total_items, "results": []}

    def print_summary(self):
        pass

    def get_metric_stats(self, name):
        return {"mean": 1.0}


def test_run_create_calls_evaluator_run_with_show_tui(offline_env, monkeypatch):
    """HP-1: run-create must call Evaluator.run() with kwargs the real signature
    accepts (show_tui) — never the removed show_table/show_progress kwargs."""
    import inspect

    import qym.core.evaluator as evaluator_module

    real_run_signature = inspect.signature(evaluator_module.Evaluator.run)
    captured: dict = {}

    class _FakeEvaluator:
        def __init__(self, **kwargs):
            captured["init"] = kwargs

        def run(self, **kwargs):
            captured["run"] = kwargs
            return _FakeResult()

    monkeypatch.setattr(evaluator_module, "Evaluator", _FakeEvaluator)

    tmp_path = offline_env
    task_file, csv_file = _write_inputs(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "create",
            "--task-file",
            str(task_file),
            "--task-function",
            "my_task",
            "--dataset-file",
            str(csv_file),
            "--metrics",
            "exact_match",
            "--no-ui",
            "--no-open",
            "--no-progress",
            "--quiet",
        ],
    )

    assert result.exit_code == 0, result.output
    run_kwargs = captured["run"]
    assert "show_table" not in run_kwargs
    assert "show_progress" not in run_kwargs
    # --quiet/--no-progress/--no-ui all disable the TUI
    assert run_kwargs["show_tui"] is False
    # Whatever the CLI passes must bind to the real Evaluator.run signature.
    real_run_signature.bind(None, **run_kwargs)
