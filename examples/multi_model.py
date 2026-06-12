"""Run multiple Evaluators in parallel from Python.

Each entry in ``Evaluator.run_parallel`` is a normal evaluator definition;
qym runs them concurrently and renders a combined dashboard.

Task signatures: the dataset's ``input`` column is a plain string, so each
task receives it as its single positional parameter. Parameters named
``model``/``model_name`` and ``trace_id`` are reserved and injected by qym.

Run it (no API keys required):

    python examples/multi_model.py
"""

from __future__ import annotations

import random
import time
from pathlib import Path

from qym import CsvDataset, Evaluator

DATASET_PATH = Path(__file__).resolve().parent / "datasets" / "qa.csv"


def gpt_like(question: str) -> str:
    time.sleep(random.uniform(0.05, 0.15))
    return f"[gpt] {question}"


def llama_like(question: str) -> str:
    time.sleep(random.uniform(0.02, 0.1))
    return f"[llama] {question}"


def make_dataset() -> CsvDataset:
    # Each run needs its own dataset object (runs execute concurrently).
    return CsvDataset(DATASET_PATH, input_col="question", expected_col="answer")


if __name__ == "__main__":
    Evaluator.run_parallel(
        [
            {
                "name": "gpt-4o-mini",
                "task": gpt_like,
                "dataset": make_dataset(),
                "metrics": ["exact_match"],
                "config": {"run_metadata": {"model": "gpt-4o-mini"}},
            },
            {
                "name": "llama-3.1",
                "task": llama_like,
                "dataset": make_dataset(),
                "metrics": ["exact_match"],
                "config": {"run_metadata": {"model": "llama-3.1"}},
            },
        ],
        show_tui=True,
        auto_save=False,
    )
