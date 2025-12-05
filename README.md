# LLM-Eval

[![PyPI version](https://badge.fury.io/py/llm-eval.svg)](https://badge.fury.io/py/llm-eval)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Evaluate your LLM applications with just 3 lines of code.**

A fast, async evaluation framework built on [Langfuse](https://langfuse.com) for testing and benchmarking LLM applications.

## 🚀 Features

- **Simple API** - Get started in minutes with a clean, Pythonic interface
- **Async & Parallel** - Evaluate hundreds of items concurrently with 90%+ efficiency
- **Multi-Model Support** - Compare GPT-4, Claude, Llama side-by-side in one run
- **Real-Time Dashboard** - Terminal UI + Web UI with live progress, historical runs, model comparison, and charts
- **Framework Agnostic** - Works with LangChain, OpenAI, Anthropic, or any Python function
- **Auto-Save** - Automatically persist results to CSV/XLSX/JSON

## ⚡ Quick Start

### 1. Install

```bash
pip install llm-eval
```

### 2. Set up Langfuse

Create a `.env` file with your [Langfuse](https://langfuse.com) credentials:

```bash
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...
LANGFUSE_HOST=https://cloud.langfuse.com  # or your self-hosted instance
LANGFUSE_PROJECT_ID=your-project-id
```

### 3. Run Evaluation

```python
from llm_eval import Evaluator

# Define your LLM task
def my_llm_task(input_data):
    # Your LLM call here
    return "response"

# Run evaluation
evaluator = Evaluator(
    task=my_llm_task,
    dataset="my-langfuse-dataset",  # Dataset name in Langfuse
    metrics=["exact_match", "contains_expected"],
)

results = evaluator.run()
```

## 🔄 Multi-Model Comparison

Compare multiple models in parallel:

```python
from llm_eval import Evaluator

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
)
```

## 💻 Command Line Interface

```bash
# Single evaluation
llm-eval --task-file agent.py --task-function chat --dataset qa-set --metrics exact_match

# Multi-model from config
llm-eval --runs-config experiments.json
```

## 📊 Dashboard

LLM-Eval provides both a Terminal UI (TUI) and a Web UI for monitoring evaluations.

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
llm-eval dashboard
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

- [User Guide](docs/USER_GUIDE.md) - Complete guide for installation, tasks, metrics, and configuration
- [Metrics Guide](docs/METRICS_GUIDE.md) - Comprehensive metric store with 40+ metrics by use case
- [Examples](examples/) - Jupyter notebooks and scripts

## 📄 License

MIT
