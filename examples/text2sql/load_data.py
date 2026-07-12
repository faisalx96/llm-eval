from pathlib import Path

from datasets import load_dataset


DATA_DIR = Path(__file__).resolve().parent

dataset = load_dataset("gretelai/synthetic_text_to_sql")

dataset["train"].to_csv(DATA_DIR / "synthetic_text_to_sql_train.csv", index=False)
dataset["test"].to_csv(DATA_DIR / "synthetic_text_to_sql_test.csv", index=False)

print("CSV files downloaded successfully.")
