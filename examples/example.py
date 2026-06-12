"""Metrics showcase: built-in metrics, custom metrics, and result stats.

Demonstrates:
- Listing the built-in metric registry (``list_available_metrics``)
- Mixing built-in metrics (by name) with custom metric callables
- Custom metrics returning either a float or a {"score", "metadata"} dict
- Smart argument resolution (``model`` is injected by the Evaluator)
- Reading per-metric statistics off the EvaluationResult

Run it (no API keys required):

    python examples/example.py

Set QYM_API_KEY / QYM_BASE_URL to stream live results to the qym platform.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from qym import CsvDataset, Evaluator, list_available_metrics

DATASET_PATH = Path(__file__).resolve().parent / "datasets" / "qa.csv"

ANSWERS = {
    "capital of france": "Paris",
    "2 + 2": "4",
    "capital of japan": "Tokyo",
    "romeo and juliet": "William Shakespeare",
    "symbol for gold": "Au",
    # Deliberate mistake so the metrics have something to catch:
    "capital of australia": "Sydney",
}


def ai_assistant(question: str, model: Optional[str] = None) -> str:
    """A deterministic stand-in for an LLM call.

    ``model`` is automatically populated by the Evaluator (from the
    ``model=`` argument), so the same task can be reused across models.
    """
    time.sleep(0.05)  # simulate a tiny bit of latency
    question_lower = question.lower()
    for key, answer in ANSWERS.items():
        if key in question_lower:
            return answer
    return "I'm not sure about that one."


def response_length_check(output: str) -> float:
    """Custom metric (float return): is the response a sensible length?"""
    length = len(str(output))
    if length < 1:
        return 0.0  # empty
    if length > 200:
        return 0.5  # too long
    return 1.0


def starts_with_capital(output: str, expected: str) -> dict:
    """Custom metric (dict return): score plus metadata for the results table."""
    text = str(output).strip()
    score = 1.0 if text[:1].isupper() or text[:1].isdigit() else 0.0
    return {"score": score, "metadata": {"first_char": text[:1]}}


def main() -> None:
    # See every metric you can reference by name.
    list_available_metrics()

    evaluator = Evaluator(
        task=ai_assistant,
        dataset=CsvDataset(
            DATASET_PATH,
            input_col="question",
            expected_col="answer",
            metadata_cols=["category", "difficulty"],
        ),
        metrics=[
            "exact_match",  # built-in, referenced by name
            "fuzzy_match",  # built-in similarity metric
            response_length_check,  # custom float metric
            starts_with_capital,  # custom dict metric
        ],
        model="demo-model",
        config={"run_name": "metrics-showcase", "max_concurrency": 5},
    )

    result = evaluator.run(auto_save=False)

    exact = result.get_metric_stats("exact_match")
    print(f"\nExact match accuracy: {exact['mean']:.1%}")
    print(f"Items evaluated: {result.total_items}, success rate: {result.success_rate:.1%}")


if __name__ == "__main__":
    main()
