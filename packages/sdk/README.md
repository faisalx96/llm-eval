<p align="center">
  <img src="https://raw.githubusercontent.com/faisalx96/qym/main/docs/images/qym_logo.png" alt="qym logo" width="400" />
</p>

<!-- <h1 align="center">qym</h1>
<p align="center"><em>قيِّم • evaluate</em></p> -->
---

<h3 align="center">Run Repeatable LLM Evaluations From Python Or The CLI</h3>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.9+-3776AB.svg" alt="Python 3.9+" /></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License: MIT" /></a>
</p>

<p align="center">
  <a href="#overview">Overview</a> |
  <a href="#quick-start">Quick Start</a> |
  <a href="#features">Features</a> |
  <a href="#command-line-interface">CLI</a> |
  <a href="docs/USER_GUIDE.md">User Guide</a> |
  <a href="docs/METRIC_BANK.md">Metrics</a>
</p>

## Overview

qym is the Python SDK for evaluating LLM applications with repeatable datasets, metrics, and run history. It is designed for prompts, RAG pipelines, and agent workflows that need something more disciplined than manual spot-checking.

You can run evaluations from Python or the CLI, score outputs with built-in and LLM-as-judge metrics, and optionally stream runs to a qym platform deployment for shared review and comparison.

The SDK supports [Langfuse](https://langfuse.com) datasets with tracing or local CSV files for lightweight offline evaluation.

## Features

- **Platform Integration** — Runs can stream to a qym platform deployment for centralized history, comparison, charts, and team collaboration
- **Simple API** — Get started in minutes with a clean, Pythonic interface
- **Async & Parallel** — Evaluate hundreds of items concurrently with 90%+ efficiency
- **Multi-Model Support** — Compare GPT-4, Claude, Llama side-by-side in one run
- **LLM-as-Judge Metrics** — Built-in judges for relevance, faithfulness, correctness, hallucination, toxicity, conciseness, and tool calling, plus a `create_judge()` factory for custom judges
- **Auto-Instrumentation** — Instrumentation support is included in the base install so supported LLM calls can be traced without a separate extra
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
QYM_BASE_URL=https://your-qym-platform.example.com
```

**To get your API key:** Use the API key flow provided by your qym platform deployment. Set `QYM_API_KEY` and `QYM_BASE_URL` to enable automatic streaming of evaluation runs.

For an internal/self-signed platform certificate, point the SDK at the issuing CA:

```bash
QYM_PLATFORM_CA_BUNDLE=/path/to/internal-ca.pem
```

For local development only, certificate verification can be disabled with `QYM_PLATFORM_SSL_VERIFY=false`.

> **Using CSV datasets?** Langfuse credentials are optional. Without them, evaluations still run but without tracing.

### 3. Run Evaluation

You need three things:
1. **Task function** - Takes input (and optionally `model_name`), returns output
2. **Dataset** - Langfuse dataset name or a local CSV file
3. **Metrics** - Built-in (`exact_match`, `contains`, `fuzzy_match`) or custom functions

```python
from qym import Evaluator

# Your task: receives the 'input' field from each dataset item
def my_llm_task(question):
    return call_your_llm(question)

# Run evaluation with a Langfuse dataset
evaluator = Evaluator(
    task=my_llm_task,
    dataset="my-langfuse-dataset",  # Dataset name in Langfuse
    metrics=["exact_match", "contains"],
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

## Run Progress Hooks

Wrappers can subscribe to evaluation progress with `progress_callback`. The callback receives a structured `ProgressSnapshot` whenever the run starts, an item starts or finishes, a metric result is produced, a warning is emitted, or the run completes.

```python
from qym import Evaluator, ProgressSnapshot


def on_progress(snapshot: ProgressSnapshot):
    print(
        f"{snapshot.run_id}: {snapshot.finished}/{snapshot.total_items} "
        f"({snapshot.percent_complete:.1f}%)"
    )


evaluator = Evaluator(
    task=my_llm_task,
    dataset="my-langfuse-dataset",
    metrics=["exact_match"],
    progress_callback=on_progress,
)

results = evaluator.run(show_tui=False)
```

For integrations that prefer explicit composition, pass `observer=ProgressCallbackObserver(on_progress)`. For lower-level integrations, subclass `EvaluationObserver` and implement the lifecycle methods you need:

```python
from qym import EvaluationObserver


class MyObserver(EvaluationObserver):
    def on_item_complete(self, run_id, item_index, result):
        send_to_my_system(run_id=run_id, item_index=item_index, result=result)
```

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
        {"name": "Summary Task", "task": summarize, "dataset": "docs", "metrics": ["contains"], "models": ["gpt-4"]},
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
qym run list --user USER # List recent runs, optionally filtered by owner
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

The **qym platform** stores runs centrally. When `QYM_API_KEY` and `QYM_BASE_URL` are set, runs stream automatically with no code changes needed.

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

**Setup:** Set `QYM_BASE_URL` to your deployment, create an API key there, and add `QYM_API_KEY=...` to your `.env`. Results are also saved locally to `qym_results/`.

If `qym config check` or live run streaming fails with an SSL certificate verification error, configure `QYM_PLATFORM_CA_BUNDLE=/path/to/internal-ca.pem` on the machine running the SDK/CLI. Use `QYM_PLATFORM_SSL_VERIFY=false` only for local/dev troubleshooting.

**Upload a previous run:**

```bash
qym submit --file qym_results/.../run.csv --task my_task --dataset my-dataset
```

## Built-in Metrics

### String Metrics

| Metric | Description |
|--------|-------------|
| `exact_match` | Exact string match between output and expected |
| `contains` | Check if output contains expected text |
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

Create custom judges with `create_judge()` or pairwise comparison judges with `create_pairwise_judge()`. See the [User Guide](docs/USER_GUIDE.md#llm-judge-metrics) for full API details, or the [Metric Bank](docs/METRIC_BANK.md) for all available metrics by use case.

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
- [Metric Bank](docs/METRIC_BANK.md) — metric reference organized by use case, including LLM-as-judge
- [Platform User Guide](../../packages/platform/docs/USER_GUIDE.md) — Dashboard, trace viewer, AI analysis, corrections review

## License

MIT
