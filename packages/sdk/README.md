<p align="center">
  <img src="https://raw.githubusercontent.com/faisalx96/qym/main/docs/images/qym_logo.png" alt="qym logo" width="400" />
</p>

<!-- <h1 align="center">qym</h1>
<p align="center"><em>قيِّم • evaluate</em></p> -->
---

<h3 align="center">A Fast, Async Framework for LLM Evaluation</h3>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.9+-3776AB.svg" alt="Python 3.9+" /></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License: MIT" /></a>
</p>

<p align="center">
  <a href="#overview">Overview</a> |
  <a href="#quick-start">Installation</a> |
  <a href="#features">Features</a> |
  <a href="#command-line-interface">CLI</a> |
  <a href="docs/USER_GUIDE.md">User Guide</a> |
  <a href="docs/METRICS_GUIDE.md">Metrics</a>
</p>

## Overview

Evaluate your LLM applications with just 3 lines of code. qym is a fast, async evaluation framework for testing and benchmarking LLM applications. It provides a structured approach to evaluation, ensuring consistency and high-quality outputs while reducing the trial-and-error typically associated with manual testing.

All runs are automatically streamed to the **qym platform** at [qym.sa](https://qym.sa) — a central dashboard where you can browse run history, compare models side-by-side, visualize metrics, and collaborate with your team.

The framework supports [Langfuse](https://langfuse.com) datasets (with full tracing) or local CSV files, and includes 40+ built-in metrics for RAG, agents, safety, and more.

## Features

- **Platform Integration** - Runs stream live to [qym.sa](https://qym.sa) for centralized history, comparison, charts, and team collaboration
- **Simple API** - Get started in minutes with a clean, Pythonic interface
- **Async & Parallel** - Evaluate hundreds of items concurrently with 90%+ efficiency
- **Multi-Model Support** - Compare GPT-4, Claude, Llama side-by-side in one run
- **Real-Time Dashboard** - Terminal UI + Web UI with live progress and metrics
- **Framework Agnostic** - Works with LangChain, OpenAI, Anthropic, or any Python function
- **Flexible Datasets** - Use Langfuse datasets (with tracing) or local CSV files (custom column names supported)
- **Auto-Save** - Automatically persist results to CSV/XLSX/JSON
- **Resume Runs** - Checkpoint partial results and resume interrupted evaluations

## Quick Start

### 1. Install

```bash
pip install qym
```

### 2. Set up environment variables

Create a `.env` file:

```bash
# Langfuse (required for Langfuse datasets, optional for CSV)
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...
LANGFUSE_HOST=https://cloud.langfuse.com  # or your self-hosted instance

# qym Platform (optional — syncs runs to a central dashboard)
QYM_API_KEY=your-api-key
QYM_PLATFORM_URL=https://qym.sa
```

**To get your API key:** Open [qym.sa](https://qym.sa), go to **Profile** (`/profile`), and create a new API key under the **API Keys** section. The token is shown only once — copy it and set it as `QYM_API_KEY`. When set, your evaluation runs are automatically streamed to the platform in real time.

> **Using CSV datasets?** Langfuse credentials are optional. Without them, evaluations still run but without tracing.

### 3. Run Evaluation

You need three things:
1. **Task function** - Takes input (and optionally `model_name`), returns output
2. **Dataset** - Langfuse dataset name or a local CSV file
3. **Metrics** - Built-in (`exact_match`, `contains_expected`, `fuzzy_match`) or custom functions

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

## Multi-Model Comparison

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

## Command Line Interface

```bash
# Single evaluation
qym --task-file agent.py --task-function chat --dataset qa-set --metrics exact_match

# Single evaluation from a local CSV (no Langfuse dataset required)
qym --task-file agent.py --task-function chat --dataset-csv datasets/qa.csv \
  --csv-input-col question --csv-expected-col answer --csv-metadata-cols category,difficulty \
  --metrics exact_match

# Multi-model from config
qym --runs-config experiments.json

# Resume a partially completed run
qym resume --run-file qym_results/task/model/date/run-id.csv \
  --task-file agent.py --task-function chat --dataset qa-set --metrics exact_match
```

## Dashboard

qym provides both a Terminal UI (TUI) and a Web UI for monitoring evaluations.

### Terminal UI

Track multiple parallel evaluations with real-time progress, latency histograms, and metrics:

### Web Dashboard

#### Live Evaluation UI (Per-Run)

A web interface is automatically launched for each evaluation run. Click the **"Open Web UI"** link printed at startup to monitor live progress.

**Features:**
- Real-time progress tracking
- Live metric scores and latency statistics
- Search and filter results
- Export to CSV

#### Platform Dashboard

The **qym platform** at [qym.sa](https://qym.sa) stores all your runs centrally with history, comparison, and team workflows.

**Step 1: Get your API key**

1. Open [qym.sa](https://qym.sa)
2. Go to your **Profile** page (`/profile`)
3. Under **API Keys**, click **Create New Key**
4. Copy the generated token — it is shown only once

**Step 2: Configure your environment**

Add to your `.env`:

```bash
QYM_API_KEY=your-api-key
QYM_PLATFORM_URL=https://qym.sa
```

**Step 3: Run as usual**

No code changes needed. When `QYM_API_KEY` is set, the SDK automatically streams events to the platform in real time as your evaluation runs. Each item start, metric score, and completion is sent as it happens — you can watch the run live on the platform dashboard.

Results are still saved locally to `qym_results/` as well.

**Browse runs on the platform:**

```bash
qym dashboard   # Opens the platform dashboard in your browser
```

**Upload a previous run:**

```bash
qym submit --file qym_results/.../run.csv --task my_task --dataset my-dataset
```

**Platform features:**
- Filter by task, model, dataset, or time range
- Compare multiple runs side-by-side
- View charts and metrics visualizations
- Approval workflows and team visibility controls

## Built-in Metrics

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

## Documentation

- [User Guide](docs/USER_GUIDE.md) - Tasks, metrics, datasets, configuration, and troubleshooting
- [Metrics Guide](docs/METRICS_GUIDE.md) - 40+ metrics organized by use case (RAG, agents, safety, etc.)

## License

MIT
