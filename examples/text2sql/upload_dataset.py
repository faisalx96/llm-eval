"""
Upload text-to-SQL samples to Langfuse.

This script loads 100 samples from the sql-create-context dataset
(built from Spider + WikiSQL) and uploads them to Langfuse.

Each item includes:
- question: Natural language query
- context: SQL CREATE TABLE statements (schema)
- answer: Ground truth SQL query

Usage:
    python upload_dataset.py
"""

from datasets import load_dataset
from langfuse import Langfuse
from dotenv import load_dotenv

load_dotenv()

DATASET_NAME = "text2sql-100"
NUM_SAMPLES = 100
SEED = 42


def main():
    print("Loading sql-create-context dataset from HuggingFace...")

    # Load dataset (Spider + WikiSQL combined)
    ds = load_dataset("b-mc2/sql-create-context", split="train")

    print(f"Dataset loaded with {len(ds)} examples")

    # Shuffle and select samples
    ds_sampled = ds.shuffle(seed=SEED).select(range(min(NUM_SAMPLES, len(ds))))

    print(f"Selected {len(ds_sampled)} samples")

    # Initialize Langfuse client
    client = Langfuse()

    # Create or get dataset
    try:
        client.create_dataset(name=DATASET_NAME)
        print(f"Created new dataset: {DATASET_NAME}")
    except Exception as e:
        if "already exists" in str(e).lower():
            print(f"Dataset '{DATASET_NAME}' already exists.")
        else:
            raise e

    # Upload each sample
    print(f"\nUploading {len(ds_sampled)} items to Langfuse...")

    for i, item in enumerate(ds_sampled):
        question = item["question"]
        context = item["context"]  # CREATE TABLE statements
        answer = item["answer"]    # Ground truth SQL

        # Input structure for the task
        input_data = {
            "question": question,
            "schema": context  # SQL schema (CREATE TABLE statements)
        }

        # Metadata
        metadata = {
            "dataset_source": "sql-create-context",
        }

        # Create dataset item
        client.create_dataset_item(
            dataset_name=DATASET_NAME,
            input=input_data,
            expected_output=answer,
            metadata=metadata
        )

        if (i + 1) % 10 == 0:
            print(f"  Uploaded {i + 1}/{len(ds_sampled)} items...")

    print(f"\nSuccessfully uploaded {len(ds_sampled)} items to dataset '{DATASET_NAME}'")
    print(f"\nDataset structure:")
    print(f"  - input.question: Natural language question")
    print(f"  - input.schema: SQL CREATE TABLE statements")
    print(f"  - expected_output: Ground truth SQL query")

    client.flush()
    print("\nDone!")


if __name__ == "__main__":
    main()
