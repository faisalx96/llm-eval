"""Run Text-to-SQL Evaluation.

This script runs the evaluation using:
- Dataset: text2sql-100 (uploaded to the qym platform — see upload_dataset.py)
- Task: Text-to-SQL using OpenRouter (OpenAI-compatible API)
- Metrics:
  1. valid_sql: Is the generated SQL syntactically valid?
  2. execution_accuracy: Does it return the same results as the gold SQL?

Requirements:
    pip install -r requirements.txt
    export QYM_API_KEY=...          # to resolve the platform dataset
    export QYM_BASE_URL=...         # optional, defaults to http://localhost:8000
    export OPENROUTER_API_KEY=...   # for the model under evaluation

Usage:
    # First, upload the dataset
    python upload_dataset.py

    # Then run the evaluation
    python run_eval.py
"""

import os
import sys

from qym import Evaluator

from task import text2sql_task
from metrics import valid_sql, execution_accuracy


def main():
    missing = [name for name in ("QYM_API_KEY", "OPENROUTER_API_KEY") if not os.getenv(name)]
    if missing:
        print(
            f"[skip] run_eval.py needs {', '.join(missing)}.\n"
            "       Set them (see the module docstring) and re-run."
        )
        sys.exit(0)

    evaluator = Evaluator(
        task=text2sql_task,
        dataset="text2sql-100",
        metrics=[valid_sql, execution_accuracy],
        model="openai/gpt-4o-mini",
        config={
            "max_concurrency": 10,
            "run_name": "text2sql-eval",
        },
    )

    evaluator.run()


if __name__ == "__main__":
    main()
