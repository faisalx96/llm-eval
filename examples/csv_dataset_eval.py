from __future__ import annotations

from qym import CsvDataset, Evaluator


def my_task(question, model_name=None, trace_id=None):
    # Minimal example task: echo.
    # If Langfuse credentials are configured, trace_id will be populated.
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
        "examples/datasets/qa.csv",
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

    evaluator.run()


