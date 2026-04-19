from pathlib import Path
import csv

from qym.core.results import EvaluationResult


def test_default_save_path_preserves_user_provided_run_name():
    result = EvaluationResult(
        dataset_name="saudi-qa-verification-v1",
        run_name="blablabla-gpt-4o-mini-260208-1613",
        metrics=["exact_match"],
        run_metadata={"task_name": "ai_assistant", "model": "gpt-4o-mini"},
        run_config={"user_provided_run_name": True},
    )

    out_path = Path(result._default_save_path("csv", "qym_results"))
    assert out_path.name == "blablabla-gpt-4o-mini-260208-1613.csv"


def test_default_save_path_auto_run_name_has_no_duplicate_model_timestamp():
    result = EvaluationResult(
        dataset_name="saudi-qa-verification-v1",
        run_name="ai_assistant-gpt-4o-mini-260208-1613-1",
        metrics=["exact_match"],
        run_metadata={"task_name": "ai_assistant", "model": "gpt-4o-mini"},
        run_config={"user_provided_run_name": False},
    )

    out_path = Path(result._default_save_path("csv", "qym_results"))
    assert out_path.name == (
        "ai_assistant-saudi-qa-verification-v1-gpt-4o-mini-260208-1613-1.csv"
    )


def test_failed_rows_preserve_recorded_time_when_saved_csv(tmp_path):
    result = EvaluationResult(
        dataset_name="dataset",
        run_name="run",
        metrics=["exact_match"],
    )

    result.add_input("item-1", "hello")
    result.add_error(
        "item-1",
        "Task timed out after 1800s",
        trace_id="trace-1",
        task_started_at_ms=1234,
        time_seconds=1800.0,
    )

    output_path = tmp_path / "results.csv"
    result.save_csv(filepath=output_path)

    with output_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 1
    assert rows[0]["output"] == "ERROR: Task timed out after 1800s"
    assert float(rows[0]["time"]) == 1800.0
    assert rows[0]["task_started_at_ms"] == "1234"
