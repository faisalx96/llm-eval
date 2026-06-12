"""Scale example: run a (tasks x models) matrix of evaluations.

``Evaluator.run_parallel`` expands the ``models`` list of each run definition
into individual runs, so 2 tasks x 2 models = 4 evaluations. Use
``max_parallel_runs`` to control how many evaluations execute at a time.

Run it (no API keys required):

    python examples/scale_example.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from qym import CsvDataset, Evaluator

DATASET_PATH = Path(__file__).resolve().parent / "datasets" / "qa.csv"


def response_length_check(output: Any, expected: Any) -> float:
    return 1.0 if len(str(output)) > 0 else 0.0


# 1. Define your tasks. The dataset input is a plain string, so each task
#    takes it as its single data parameter; ``model_name`` is injected by qym.
async def task_1(question: str, model_name: str = "gpt-4o-mini") -> str:
    """Simulate Task 1."""
    await asyncio.sleep(0.05)
    return f"Task 1 result for {question} using {model_name}"


async def task_2(question: str, model_name: str = "gpt-4o-mini") -> str:
    """Simulate Task 2."""
    await asyncio.sleep(0.1)
    return f"Task 2 result for {question} using {model_name}"


def main() -> None:
    # 2. Define the list of models you want to run against.
    models = ["gpt-4o", "llama-3.1"]

    # 3. Define the configuration for each task. ``models`` is expanded into
    #    one run per model; each run needs its own dataset object.
    runs_config = [
        {
            "name": "Task 1 Analysis",
            "task": task_1,
            "dataset": CsvDataset(DATASET_PATH, input_col="question", expected_col="answer"),
            "metrics": ["exact_match"],
            "models": models,
            "config": {"max_concurrency": 5},
        },
        {
            "name": "Task 2 Summary",
            "task": task_2,
            "dataset": CsvDataset(DATASET_PATH, input_col="question", expected_col="answer"),
            "metrics": [response_length_check],
            "models": models,
            "config": {"max_concurrency": 5},
        },
    ]

    print(f"Starting {len(runs_config) * len(models)} evaluations...")

    # 4. Run evaluations:
    #    max_parallel_runs=None -> all runs in parallel
    #    max_parallel_runs=1    -> sequential (queue mode)
    #    max_parallel_runs=2    -> two at a time (balanced)
    Evaluator.run_parallel(
        runs=runs_config,
        show_tui=True,
        auto_save=False,
        max_parallel_runs=2,
    )

    print("All evaluations complete!")


if __name__ == "__main__":
    main()
