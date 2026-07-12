"""
Run Text-to-SQL Evaluation.

This script runs the evaluation using:
- Dataset: text2sql-100 (uploaded to Langfuse)
- Task: Text-to-SQL using OpenRouter
- Metrics:
  1. valid_sql: Is the generated SQL syntactically valid?
  2. execution_accuracy: Does it return the same results as the gold SQL?

Usage:
    # First, download the local CSV dataset
    python load_data.py

    # Then run the evaluation
    python run_eval.py
"""
from dotenv import load_dotenv

load_dotenv()

from metrics import valid_sql, execution_accuracy
from qym import CsvDataset, Evaluator
from task import text2sql_task

data = CsvDataset(
    "examples/text2sql/synthetic_text_to_sql_test.csv",
    input_col=["sql_prompt", "sql_context"],
    expected_col="sql",
    id_col="id",
    metadata_cols=[
        "domain",
        "sql_complexity",
        "sql_task_type",
    ],
)


def main():
    evaluator = Evaluator(
        task=text2sql_task,
        dataset=data,
        metrics=[valid_sql, execution_accuracy],
        model="openai/gpt-4o-mini",
        config={
            "max_concurrency": 10,
            "run_name": "text2sql-eval",
        },
        input_mapping={
            "sql_prompt": "question",
            "sql_context": "schema",
        },
    )

    evaluator.run()


if __name__ == "__main__":
    main()
