# قيِّم (qym)

[![PyPI version](https://badge.fury.io/py/qym.svg)](https://badge.fury.io/py/qym)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Evaluate your LLM applications with just 3 lines of code.**

A fast, async evaluation framework for testing and benchmarking LLM applications. Supports [Langfuse](https://langfuse.com) datasets or local CSV files.

**📚 Docs:**
- [User Guide](docs/USER_GUIDE.md) — Tasks, datasets, configuration, and troubleshooting
- [Metrics Guide](docs/METRICS_GUIDE.md) — 40+ metrics organized by use case

## 🚀 Features

- **Simple API** - Get started in minutes with a clean, Pythonic interface
- **Async & Parallel** - Evaluate hundreds of items concurrently with 90%+ efficiency
- **Multi-Model Support** - Compare GPT-4, Claude, Llama side-by-side in one run
- **Real-Time Dashboard** - Terminal UI + Web UI with live progress, historical runs, model comparison, and charts
- **Framework Agnostic** - Works with LangChain, OpenAI, Anthropic, or any Python function
- **Flexible Datasets** - Use Langfuse datasets (with tracing) or local CSV files (custom column names supported)
- **Auto-Save** - Automatically persist results to CSV/XLSX/JSON

## ⚡ Quick Start

### 1. Install

```bash
pip install qym
```

### 2. Set up Langfuse (optional for CSV datasets)

Create a `.env` file with your [Langfuse](https://langfuse.com) credentials:

```bash
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...
LANGFUSE_HOST=https://cloud.langfuse.com  # or your self-hosted instance
```

> **Using CSV datasets?** Langfuse credentials are optional. Without them, evaluations still run but without tracing.

### 3. Run Evaluation

You need three things:
1. **[Task function](docs/USER_GUIDE.md#3-writing-your-task-function)** - Takes input (and optionally `model_name`), returns output
2. **[Dataset](docs/USER_GUIDE.md#5-setting-up-your-dataset)** - Langfuse dataset name or a [local CSV file](docs/USER_GUIDE.md#csv-datasets-local)
3. **[Metrics](docs/USER_GUIDE.md#4-using-metrics)** - Built-in (`exact_match`, `contains_expected`, `fuzzy_match`) or custom functions

```python
from qym import Evaluator

# Your task: receives the 'input' field from each dataset item
def my_llm_task(question):
    return call_your_llm(question)

# Run evaluation with a Langfuse dataset
evaluator = Evaluator(
    task=my_llm_task,
    dataset="my-langfuse-dataset",  # Dataset name in Langfuse
    metrics=["exact_match", "contains_expected"],
)
results = evaluator.run()
```

**Using a local CSV instead of Langfuse:**

```python
from qym import Evaluator, CsvDataset

dataset = CsvDataset("qa.csv", input_col="question", expected_col="answer")

evaluator = Evaluator(
    task=my_llm_task,
    dataset=dataset,
    metrics=["exact_match"],
)
results = evaluator.run()
```

> CSV datasets work without Langfuse credentials. If credentials are set, traces are still recorded.

## 🔄 Multi-Model Comparison

Compare multiple models in parallel:

```python
from qym import Evaluator

async def my_task(question, trace=None, model_name="gpt-4"):
    # Use model_name to route to different models
    return call_llm(model_name, question)

evaluator = Evaluator(
    task=my_task,
    dataset="my-dataset",
    metrics=["exact_match"],
    model=["gpt-4", "gpt-3.5-turbo", "claude-3-sonnet"],  # Compare 3 models
)

results = evaluator.run()  # Runs all models in parallel
```

Or use `run_parallel` for different tasks:

```python
results = Evaluator.run_parallel(
    runs=[
        {"name": "QA Task", "task": qa_task, "dataset": "qa-set", "metrics": ["exact_match"], "models": ["gpt-4", "claude-3"]},
        {"name": "Summary Task", "task": summarize, "dataset": "docs", "metrics": ["contains_expected"], "models": ["gpt-4"]},
    ],
    show_tui=True,
    auto_save=True,
    max_parallel_runs=2,  # Run 2 at a time (None=all at once, 1=sequential)
)
```

## 💻 Command Line Interface

```bash
# Single evaluation
qym --task-file agent.py --task-function chat --dataset qa-set --metrics exact_match

# Single evaluation from a local CSV (no Langfuse dataset required)
qym --task-file agent.py --task-function chat --dataset-csv datasets/qa.csv \
  --csv-input-col question --csv-expected-col answer --csv-metadata-cols category,difficulty \
  --metrics exact_match

# Multi-model from config
qym --runs-config experiments.json
```

## 📊 Dashboard

قيِّم provides both a Terminal UI (TUI) and a Web UI for monitoring evaluations.

### Terminal UI

Track multiple parallel evaluations with real-time progress, latency histograms, and metrics:

![Terminal UI](docs/images/tui-progress.png)

### Web Dashboard

#### Live Evaluation UI (Per-Run)

A web interface is automatically launched for each evaluation run. Click the **"Open Web UI"** link printed at startup to monitor live progress:

![Dashboard Live](docs/images/dashboard-live.png)

#### Historical Dashboard

Browse all past runs with the CLI command:

```bash
qym dashboard
```

![Dashboard Runs](docs/images/dashboard-runs.png)

**Features:**
- Filter by task, model, dataset, or time range
- Compare multiple runs side-by-side
- View charts and metrics visualizations
- **Publish to Confluence** - Share approved runs with stakeholders

![Dashboard Compare](docs/images/dashboard-compare.png)

![Dashboard Charts](docs/images/dashbaord-charts.png)

## 📈 Built-in Metrics

| Metric | Description |
|--------|-------------|
| `exact_match` | Exact string match between output and expected |
| `contains_expected` | Check if output contains expected text |
| `fuzzy_match` | Similarity score using sequence matching |

Custom metrics are simple functions:

```python
def my_metric(output, expected):
    score = evaluate_somehow(output, expected)
    return {"score": score, "metadata": {"details": "..."}}

evaluator = Evaluator(
    task=my_task,
    dataset="my-dataset",
    metrics=[my_metric, "exact_match"],  # Mix custom and built-in
)
```

## 📚 Documentation

- [User Guide](docs/USER_GUIDE.md) - Tasks, metrics, datasets, configuration, and troubleshooting
- [Metrics Guide](docs/METRICS_GUIDE.md) - 40+ metrics organized by use case (RAG, agents, safety, etc.)
- [Examples](examples/) - Runnable scripts and Jupyter notebooks

## 📄 License

MIT
