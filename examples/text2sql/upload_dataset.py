"""Upload text-to-SQL samples to the qym platform.

This script loads samples from the sql-create-context dataset (built from
Spider + WikiSQL), converts them to qym dataset items, and uploads them to
the qym platform as a published dataset named ``text2sql-100``.

Each item's input is a JSON object with:
- question: Natural language query
- schema: SQL CREATE TABLE statements

and the expected_output is the ground-truth SQL query.

Requirements:
    pip install -r requirements.txt
    export QYM_API_KEY=...       # qym platform API key (datasets:write scope)
    export QYM_BASE_URL=...      # optional, defaults to http://localhost:8000

Usage:
    python upload_dataset.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

DATASET_NAME = "text2sql-100"
NUM_SAMPLES = 100
SEED = 42


def main():
    api_key = os.getenv("QYM_API_KEY")
    if not api_key:
        sys.exit(
            "QYM_API_KEY is not set. Create an API key in the qym platform and\n"
            "export QYM_API_KEY (and QYM_BASE_URL if not http://localhost:8000)."
        )

    try:
        from datasets import load_dataset
    except ImportError:
        sys.exit(
            "The HuggingFace 'datasets' package is required to download the source data.\n"
            "Install the example dependencies first: pip install -r requirements.txt"
        )

    from qym.platform.client import PlatformClient
    from qym.platform.defaults import DEFAULT_PLATFORM_URL

    print("Loading sql-create-context dataset from HuggingFace...")
    ds = load_dataset("b-mc2/sql-create-context", split="train")
    print(f"Dataset loaded with {len(ds)} examples")

    ds_sampled = ds.shuffle(seed=SEED).select(range(min(NUM_SAMPLES, len(ds))))
    print(f"Selected {len(ds_sampled)} samples")

    # Write items to a temporary JSONL file in qym's dataset item format.
    fd, jsonl_path = tempfile.mkstemp(prefix="text2sql_", suffix=".jsonl")
    os.close(fd)
    try:
        with open(jsonl_path, "w", encoding="utf-8") as handle:
            for item in ds_sampled:
                handle.write(
                    json.dumps(
                        {
                            "input": {
                                "question": item["question"],
                                "schema": item["context"],  # CREATE TABLE statements
                            },
                            "expected_output": item["answer"],  # ground-truth SQL
                            "metadata": {"dataset_source": "sql-create-context"},
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        platform_url = DEFAULT_PLATFORM_URL
        print(f"\nUploading {len(ds_sampled)} items to {platform_url} as '{DATASET_NAME}'...")
        client = PlatformClient(platform_url=platform_url, api_key=api_key)
        response = client.upload_dataset(
            path=jsonl_path,
            name=DATASET_NAME,
            version="v1",
            publish=True,
            set_alias="production",
        )
    finally:
        Path(jsonl_path).unlink(missing_ok=True)

    version = response.get("version") or {}
    print(f"\nSuccessfully uploaded dataset '{DATASET_NAME}'")
    print(f"  version: {version.get('version')} (status: {version.get('status')})")
    print(f"  items:   {version.get('item_count')}")
    print("\nDataset structure:")
    print("  - input.question:  Natural language question")
    print("  - input.schema:    SQL CREATE TABLE statements")
    print("  - expected_output: Ground-truth SQL query")
    print("\nRun the evaluation next: python run_eval.py")


if __name__ == "__main__":
    main()
