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

- **Platform Integration** — Runs stream live to [qym.sa](https://qym.sa) for centralized history, comparison, charts, and team collaboration
- **Simple API** — Get started in minutes with a clean, Pythonic interface
- **Async & Parallel** — Evaluate hundreds of items concurrently with 90%+ efficiency
- **Multi-Model Support** — Compare GPT-4, Claude, Llama side-by-side in one run
- **LLM-as-Judge Metrics** — 7 built-in judges (relevance, faithfulness, correctness, hallucination, toxicity, conciseness, tool calling) plus a `create_judge()` factory for custom judges
- **Auto-Instrumentation** — `pip install "qym[otel]"` to automatically trace every LLM call across 15+ providers and 6+ frameworks, viewable in the embedded trace viewer
- **Real-Time Dashboard** — Terminal UI + platform dashboard with live progress, metrics, trace viewer, AI root cause analysis, and corrections review
- **Version Tracking** — Auto-detects git branch and commit per run for version leaderboards
- **Framework Agnostic** — Works with LangChain, LangGraph, LlamaIndex, CrewAI, Haystack, OpenAI Agents, or any Python function
- **Flexible Datasets** — Use Langfuse datasets (with tracing) or local CSV files (custom column names supported)
- **Auto-Save & Retry** — Automatically persist results to CSV/XLSX/JSON, with exponential backoff retries on failure (default: 2 retries, 300s timeout)
- **Resume Runs** — Checkpoint partial results and resume interrupted evaluations; Ctrl+C sends STOPPED status instead of leaving runs stuck

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

The CLI uses noun-verb command groups. All commands support `--json` for structured output.

```bash
# Run an evaluation
qym run create --task-file agent.py --task-function chat --dataset qa-set --metrics exact_match

# Run from a local CSV (no Langfuse dataset required)
qym run create --task-file agent.py --task-function chat \
  --dataset-csv datasets/qa.csv \
  --csv-input-col question --csv-expected-col answer --csv-metadata-cols category,difficulty \
  --metrics exact_match

# Multi-model from config
qym run create --runs-config experiments.json

# Resume a partially completed run
qym run create --task-file agent.py --task-function chat \
  --dataset qa-set --metrics exact_match \
  --resume-from qym_results/task/model/date/run-id.csv

# Other commands
qym run list             # List recent runs
qym run tasks            # List distinct task names
qym analyze run <id>     # Trigger AI root-cause analysis
qym analyze summary <id> # Get analysis summary
qym metric list          # List available metrics
qym config check         # Validate platform connectivity
qym dashboard            # Open platform in browser
qym submit --file ...    # Upload a saved results file
```

> Legacy invocations (`qym --task-file ...`, `qym resume --run-file ...`) are automatically rewritten.

## Dashboard

### Terminal UI

Track multiple parallel evaluations with real-time progress, latency histograms, and metrics in your terminal.

### Platform Dashboard

The **qym platform** at [qym.sa](https://qym.sa) stores all your runs centrally. When `QYM_API_KEY` is set, runs stream automatically — no code changes needed.

```bash
qym dashboard   # Opens the platform in your browser
```

**Platform features:**
- **Runs view** — paginated listing with smart grouping, version tracking (git branch/commit), metric visibility controls, and status filtering
- **Single run view** — metadata breakdown, interactive metric drill-down, category chip selectors, HTML export for offline sharing
- **Compare view** — side-by-side item comparison with winner badges, score range filters, root-cause/solution breakdown with Sankey visualization
- **Charts view** — per-task cards with dataset tabs, Run/Version/Model grouping, and version leaderboard
- **Trace viewer** — embedded per-item span tree with LLM message reconstruction, reasoning display, error path highlighting, and framework noise collapsing
- **AI analysis** — one-click root cause analysis with an interactive playground for prompt editing, category catalogs, and correction bank
- **Corrections review** — dedicated approval queue with bulk moderation and revision history
- **Team workflows** — role-based visibility, approval workflows, and org-level access controls

**Setup:** Open [qym.sa](https://qym.sa), go to **Profile** (`/profile`), create an API key, and add `QYM_API_KEY=...` to your `.env`. Results are also saved locally to `qym_results/`.

**Upload a previous run:**

```bash
qym submit --file qym_results/.../run.csv --task my_task --dataset my-dataset
```

## Built-in Metrics

### String Metrics

| Metric | Description |
|--------|-------------|
| `exact_match` | Exact string match between output and expected |
| `contains_expected` | Check if output contains expected text |
| `fuzzy_match` | Similarity score using sequence matching |

### LLM Judge Metrics

Use as metric names directly. Configure via env vars or Python API:

| Metric | What It Evaluates |
|--------|-------------------|
| `relevance` | Is the response relevant to the question? |
| `faithfulness_llm` | Is the response grounded in the context? |
| `correctness_llm` | Does the response match the expected answer? |
| `hallucination` | Does the response contain hallucinated content? |
| `toxicity` | Does the response contain harmful content? |
| `conciseness` | Is the response concise or verbose? |
| `tool_calling` | Are the tool calls correct? |

**Configuration** — add to your `.env` file:
```bash
QYM_JUDGE_MODEL=gpt-4o-mini      # Required: model name
QYM_JUDGE_API_KEY=sk-...         # Required: API key (or set OPENAI_API_KEY)
QYM_JUDGE_BASE_URL=http://...    # Optional: for vLLM, Ollama, etc.
```

Or pass directly when creating a judge in Python:
```python
from qym.metrics.judges import create_judge

my_judge = create_judge(
    name="my_judge",
    prompt="Is this response helpful?\n[Question]: {question}\n[Response]: {output}",
    choices={"helpful": 1.0, "unhelpful": 0.0},
    judge_model="gpt-4o-mini",
    judge_api_key="sk-...",
    judge_base_url="http://localhost:8000/v1",  # Optional
)
```

Create custom judges with `create_judge()` or pairwise comparison judges with `create_pairwise_judge()`. See the [User Guide](docs/USER_GUIDE.md#llm-judge-metrics) for full API details, or the [Metrics Guide](docs/METRICS_GUIDE.md) for all available metrics by use case.

### Custom Metrics

```python
def my_metric(output, expected):
    score = evaluate_somehow(output, expected)
    return {"score": score, "metadata": {"details": "..."}}

evaluator = Evaluator(
    task=my_task,
    dataset="my-dataset",
    metrics=[my_metric, "exact_match", "relevance"],  # Mix custom, string, and judge metrics
)
```

## Documentation

- [User Guide](docs/USER_GUIDE.md) — Tasks, metrics, datasets, CLI, configuration, and troubleshooting
- [Metrics Guide](docs/METRICS_GUIDE.md) — 40+ metrics organized by use case, including LLM-as-judge
- [Auto-Instrumentation Guide](docs/AUTO_INSTRUMENTATION_GUIDE.md) — Automatic LLM call tracing across 15+ providers and 6+ frameworks
- [Platform User Guide](../../docs/PLATFORM_USER_GUIDE.md) — Dashboard, trace viewer, AI analysis, corrections review

## License

MIT
