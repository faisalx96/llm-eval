from qym import Evaluator, CsvDataset

# Point qym at the CSV (uses the `input` / `expected_output` columns)
data = CsvDataset("examples/qa.csv")


# Your task: take the input, return your system's answer (a plain string)
def task(question):
    if question == "What is 2 + 2?":
        return "4"
    if question == "Capital of France?":
        return "Nice"  # intentionally wrong
    return "I do not know"


def main():
    # Score it against a built-in metric
    result = Evaluator(task, data, metrics=["exact_match"]).run(show_tui=False)
    print(result.success_rate)


if __name__ == "__main__":
    main()
