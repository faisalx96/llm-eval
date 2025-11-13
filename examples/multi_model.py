"""
Example showing how to run multiple Evaluators in parallel from Python.
"""

from __future__ import annotations

import random
import time

from llm_eval import Evaluator


def gpt_like(question: str) -> str:
    time.sleep(random.uniform(0.2, 0.6))
    return f"[gpt] {question['question']}"


def llama_like(question: str) -> str:
    time.sleep(random.uniform(0.1, 0.4))
    return f"[llama] {question['question']}"


if __name__ == "__main__":
    Evaluator.run_parallel(
        [
            {
                "name": "gpt-4o-mini",
                "task": gpt_like,
                "dataset": "saudi-qa-verification-v1",
                "metrics": ["exact_match"],
                "config": {"run_metadata": {"model": "gpt-4o-mini"}},
            },
            {
                "name": "llama-3.1",
                "task": llama_like,
                "dataset": "saudi-qa-verification-v1",
                "metrics": ["exact_match"],
                "config": {"run_metadata": {"model": "llama-3.1"}},
            },
        ],
        show_tui=True,
        auto_save=False,
    )
