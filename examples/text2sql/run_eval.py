"""
Run Text-to-SQL Evaluation.

This script runs the evaluation using:
- Dataset: text2sql-100 (uploaded to Langfuse)
- Task: Text-to-SQL using OpenRouter
- Metrics:
  1. valid_sql: Is the generated SQL syntactically valid?
  2. execution_accuracy: Does it return the same results as the gold SQL?

Usage:
    # First, upload the dataset
    python upload_dataset.py

    # Then run the evaluation
    python run_eval.py
"""

from dotenv import load_dotenv

load_dotenv()

from llm_eval import Evaluator
from task import text2sql_task
from metrics import valid_sql, execution_accuracy


def main():
    evaluator = Evaluator(
        task=text2sql_task,
        dataset="text2sql-100",
        metrics=[valid_sql, execution_accuracy],
        model="openai/gpt-4o-mini",
        config={
            "max_concurrency": 10,
            "run_name": "text2sql-eval",
        }
    )

    results = evaluator.run()


if __name__ == "__main__":
    main()
