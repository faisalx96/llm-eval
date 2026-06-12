"""Evaluate a task against a local CSV dataset.

Demonstrates:
- CsvDataset with custom column mapping and metadata columns
- A custom metric returning either a float or a {"score", "metadata"} dict
- Smart argument resolution (model_name / trace_id are injected by qym)

Run it (no API keys required):

    python examples/csv_dataset_eval.py

Set QYM_API_KEY / QYM_BASE_URL to stream live results to the qym platform.
"""

from __future__ import annotations

from pathlib import Path

from qym import CsvDataset, Evaluator

DATASET_PATH = Path(__file__).resolve().parent / "datasets" / "qa.csv"


def my_task(question, model_name=None, trace_id=None):
    # Minimal example task: echo. model_name and trace_id are filled in by
    # qym's argument resolution when available.
    if isinstance(question, dict):
        q = question.get("question", question)
    else:
        q = question
    return f"Q: {q} (model={model_name}, trace_id={trace_id})"


def exact_match(output, expected):
    if expected is None:
        return {"score": 0.0, "metadata": {"reason": "No expected_output provided"}}
    return 1.0 if str(output).strip() == str(expected).strip() else 0.0


if __name__ == "__main__":
    dataset = CsvDataset(
        DATASET_PATH,
        input_col="question",
        expected_col="answer",
        metadata_cols=["category", "difficulty"],
    )

    evaluator = Evaluator(
        task=my_task,
        dataset=dataset,
        metrics=[exact_match],
        config={"run_name": "csv-example", "max_concurrency": 5},
        model="demo-model",
    )

    evaluator.run(auto_save=False)
