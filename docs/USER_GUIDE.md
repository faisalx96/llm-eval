# LLM-Eval User Guide

Welcome to LLM-Eval! This guide provides comprehensive instructions for evaluating your LLM applications using Python scripts, the Command Line Interface (CLI), or complex multi-model configurations.

## Table of Contents

1. [Getting Started](#getting-started)
2. [Three Ways to Run](#three-ways-to-run)
    - [Option 1: Python API](#option-1-python-api)
    - [Option 2: Command Line Interface (CLI)](#option-2-command-line-interface-cli)
    - [Option 3: Multi-Model Configuration](#option-3-multi-model-configuration)
3. [Defining Your Task](#defining-your-task)
4. [Metrics](#metrics)
5. [Understanding Results](#understanding-results)
6. [Advanced Configuration](#advanced-configuration)

---

## Getting Started

### 1. Installation

```bash
pip install llm-eval
```

### 2. Prerequisites

LLM-Eval uses **Langfuse** for dataset management. You need:
1.  A Langfuse account (cloud or self-hosted).
2.  API Keys set as environment variables:

```bash
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_HOST="https://cloud.langfuse.com"  # or your self-hosted URL
```

### 3. Prepare a Dataset

Create a dataset in Langfuse named `qa-test-set` (or any name you prefer) with items containing:
- `input`: The prompt or question.
- `expected_output`: The correct answer (optional, but needed for correctness metrics).

---

## Three Ways to Run

### Option 1: Python API

Best for **notebooks**, **debugging**, and **custom workflows**.

```python
from llm_eval import Evaluator

# 1. Define your task (the function to test)
def my_llm_task(input_text):
    # Call your LLM here (e.g., OpenAI, Anthropic, local model)
    return "Paris" 

# 2. Run evaluation
evaluator = Evaluator(
    task=my_llm_task,
    dataset="qa-test-set",
    metrics=["exact_match", "faithfulness"]
)

results = evaluator.run(auto_save=True)
print(results.summary())
```

### Option 2: Command Line Interface (CLI)

Best for **CI/CD pipelines** and **quick checks**.

You can evaluate a function directly from your terminal without writing a runner script.

**Syntax:**
```bash
llm-eval --task-file <FILE> --task-function <FUNCTION_NAME> --dataset <DATASET> --metrics <METRICS>
```

**Example:**
Assuming you have a file `agent.py`:
```python
# agent.py
def chat(input_text):
    return "I am a bot."
```

Run:
```bash
llm-eval --task-file agent.py --task-function chat \
         --dataset qa-test-set \
         --metrics exact_match,contains
```

**Common Flags:**
- `--model`: Tag the run with a model name (e.g., `--model gpt-4`).
- `--output`: Save results to a specific JSON file (e.g., `--output results.json`).
- `--no-ui`: Disable the local web dashboard.
- `--quiet`: Show only the final summary.

### Option 3: Multi-Model Configuration

Best for **benchmarking** and **comparing models** (e.g., GPT-4 vs Llama 3).

Define your experiments in a JSON or YAML file (e.g., `experiments.json`):

```json
[
  {
    "name": "gpt-4-run",
    "task_file": "agent.py",
    "task_function": "chat_gpt4",
    "dataset": "qa-test-set",
    "metrics": "exact_match,faithfulness",
    "metadata": { "model": "gpt-4" }
  },
  {
    "name": "llama-3-run",
    "task_file": "agent.py",
    "task_function": "chat_llama",
    "dataset": "qa-test-set",
    "metrics": "exact_match,faithfulness",
    "metadata": { "model": "llama-3" }
  }
]
```

**Run all experiments in parallel:**
```bash
llm-eval --runs-config experiments.json
```

This will launch a **Rich TUI dashboard** showing progress bars and live metrics for all runs simultaneously.

---

## Defining Your Task

Your task function is the unit being tested. It must accept the input from your dataset and return a string.

### Basic Contract
```python
def my_task(input_data):
    # input_data is the 'input' field from your Langfuse dataset item
    # It can be a string, dict, or any JSON-serializable object
    return "Model response string"
```

### Async Support
LLM-Eval runs natively on `asyncio`. If your task is async, it will be awaited automatically.

```python
async def my_async_task(input_text):
    response = await openai.ChatCompletion.acreate(...)
    return response.choices[0].message.content
```

### Accessing Full Dataset Item
If you need more than just the `input` field (e.g., metadata), accept a second argument named `item`:

```python
def task_with_context(input_text, item):
    # item is the LangfuseDatasetItem object
    user_id = item.metadata.get("user_id")
    return f"Processed for {user_id}"
```

---

## Metrics

Metrics determine "goodness". You can use built-in strings or custom functions.

### Built-in Metrics
- **`exact_match`**: String equality (1.0 or 0.0).
- **`contains`**: Checks if expected output is a substring of actual output.
- **`fuzzy_match`**: Levenshtein distance similarity (0.0 to 1.0).

### Custom Metrics
A metric is a simple function:

```python
def my_custom_metric(output, expected):
    # Return a float between 0.0 and 1.0
    # Or return a dict: {"score": 0.8, "reason": "Good grammar"}
    return 1.0 if "success" in output else 0.0
```

Pass it to the evaluator:
```python
evaluator = Evaluator(..., metrics=[my_custom_metric])
```

---

## Understanding Results

### Console Output
After a run, you get a summary table:
```
Evaluation Results: gpt-4-run
┏━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━┳━━━━━━━┓
┃ Metric      ┃  Mean ┃ Std Dev ┃ Success ┃
┡━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━╇━━━━━━━┩
│ exact_match │ 0.850 │   0.120 │  100%   │
└─────────────┴───────┴─────────┴───────┘
```

### Saved Files
Results are auto-saved (if enabled) to `eval_results_<dataset>_<timestamp>.json` (or `.csv`).

- **CSV**: Great for Excel/Sheets. Columns: `input`, `output`, `expected`, `metric_score`, `latency`.
- **JSON**: Full fidelity, including full prompts and metadata.

---

## Advanced Configuration

### Concurrency & Timeouts
Control execution speed and limits via the `config` dictionary:

```python
evaluator = Evaluator(
    ...,
    config={
        "max_concurrency": 5,  # Limit parallel requests (default: 10)
        "timeout": 60.0,       # Seconds per item (default: 30)
        "run_name": "nightly-build-v1"
    }
)
```

### Parallel Execution in Python
You can also run multi-model evaluations programmatically:

```python
from llm_eval import Evaluator

results = Evaluator.run_parallel([
    {"name": "model-a", "task": task_a, "dataset": "ds", "metrics": ["exact_match"]},
    {"name": "model-b", "task": task_b, "dataset": "ds", "metrics": ["exact_match"]},
])
```

---

## Troubleshooting

- **"Dataset not found"**: Check your Langfuse project and dataset name.
- **"Missing credentials"**: Ensure `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set.
- **Rate Limits**: If your LLM provider errors out, reduce `max_concurrency` in config.