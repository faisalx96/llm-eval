# LLM-Eval User Guide

A step-by-step guide to evaluating your LLM applications. Follow this guide carefully to avoid common errors.

## Table of Contents

1. [Installation & Setup](#1-installation--setup)
2. [Understanding the Basics](#2-understanding-the-basics)
3. [Writing Your Task Function](#3-writing-your-task-function)
4. [Using Metrics](#4-using-metrics)
5. [Setting Up Your Dataset](#5-setting-up-your-dataset)
6. [Running Your First Evaluation](#6-running-your-first-evaluation)
7. [Multi-Model Comparison](#7-multi-model-comparison)
8. [Command Line Interface](#8-command-line-interface)
9. [Understanding Results](#9-understanding-results)
10. [Configuration Options](#10-configuration-options)
11. [Common Errors & Solutions](#11-common-errors--solutions)

---

## 1. Installation & Setup

### Step 1: Install the package

```bash
pip install llm-eval
```

### Step 2: Set up Langfuse credentials

LLM-Eval uses [Langfuse](https://langfuse.com) for dataset storage and tracing. You need an account.

Create a `.env` file in your project root:

```bash
# .env
LANGFUSE_PUBLIC_KEY=pk-lf-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
LANGFUSE_SECRET_KEY=sk-lf-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
LANGFUSE_HOST=https://cloud.langfuse.com
```

> ⚠️ **Common Error**: If you see `"Missing Langfuse public key"`, your `.env` file is not being loaded. Make sure:
> - The file is named exactly `.env` (not `env` or `.env.txt`)
> - It's in the same directory where you run your script
> - You have `python-dotenv` installed (`pip install python-dotenv`)

### Step 3: Verify setup

```python
from langfuse import Langfuse

client = Langfuse()
print("Connected to Langfuse!")  # If no error, you're ready
```

---

## 2. Understanding the Basics

### How LLM-Eval Works

```
┌─────────────────────────────────────────────────────────────┐
│                        LLM-Eval                             │
│                                                             │
│   Dataset          Your Task         Metrics                │
│   (Langfuse)   →   Function    →    (Scoring)   →  Results  │
│                                                             │
│   100 items        Runs on each      Compares output        │
│   with input       item in parallel  to expected            │
│   & expected                                                │
└─────────────────────────────────────────────────────────────┘
```

### Key Concepts

| Concept | Description |
|---------|-------------|
| **Task** | Your function that takes input and returns output (e.g., calls an LLM) |
| **Dataset** | Collection of test items stored in Langfuse |
| **Metrics** | Functions that score your output |
| **Trace** | Langfuse observability object for logging |

---

## 3. Writing Your Task Function

Your task function is the code being evaluated. LLM-Eval uses **smart argument resolution** to call your function flexibly.

### How Input is Passed to Your Task

The evaluator looks at your function signature and passes arguments intelligently:

| Your Function | How Evaluator Calls It |
|---------------|------------------------|
| `def task(question)` | `task(question=input_data)` |
| `def task(input_data)` | `task(input_data=input_data)` |
| `def task(x)` | `task(x=input_data)` |
| `def task(q, context)` | `task(q=input["q"], context=input["context"])` if input is dict |
| `def task(**kwargs)` | `task(**input_data)` if input is dict |

### Basic Task (Any Parameter Name Works)

```python
def my_task(question):
    """
    Args:
        question: The 'input' field from your dataset item.
                  Name it whatever you want!

    Returns:
        Any: The output to be evaluated (type depends on your metrics)
    """
    response = call_your_llm(question)
    return response
```

### Task with Dict Input (Auto-Unpacking)

If your dataset input is a dict, parameters are matched by key name:

```python
# Dataset item: {"input": {"question": "What is 2+2?", "context": "Math quiz"}}

def my_task(question, context):
    """Parameters matched to dict keys automatically."""
    prompt = f"Context: {context}\nQuestion: {question}"
    return call_llm(prompt)
```

### Task with Model Routing (For Multi-Model)

When comparing multiple models, add a `model_name` or `model` parameter:

```python
def my_task(question, model_name="gpt-4"):
    """
    Args:
        question: The input
        model_name: Which model to use (passed automatically by Evaluator)
    """
    if model_name == "gpt-4":
        return call_openai(question, model="gpt-4")
    elif model_name == "claude-3":
        return call_anthropic(question)
    else:
        return call_default(question)
```

The evaluator detects `model_name` or `model` parameters and passes the model automatically.

### Async Task (Recommended for LLM Calls)

Async tasks enable better concurrency:

```python
async def my_task(question, model_name="gpt-4"):
    """Async tasks are automatically awaited."""
    response = await openai_client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": question}]
    )
    return response.choices[0].message.content
```

### Task Returning Non-String (For Custom Metrics)

Your task can return any type if you use custom metrics:

```python
def my_task(question):
    """Return a structured response for custom metrics."""
    result = call_llm(question)
    return {
        "answer": result,
        "tokens_used": 150,
        "latency_ms": 230,
    }

# Custom metric that understands the dict
def token_efficiency(output, expected):
    return 1.0 if output["tokens_used"] < 200 else 0.5
```

### ⚠️ Common Task Mistakes

```python
# ❌ WRONG: Returns None (forgot return statement)
def bad_task(question):
    result = call_llm(question)
    # Missing return!

# ❌ WRONG: Exception not handled
def bad_task(question):
    return call_llm(question)  # If this throws, item fails

# ✅ CORRECT: Clear return, handles errors gracefully
def good_task(question, model_name="gpt-4"):
    try:
        result = call_llm(question, model=model_name)
        return str(result)
    except Exception as e:
        return f"Error: {e}"  # Or raise to mark as failed
```

---

## 4. Using Metrics

Metrics determine how well your task performs.

### Built-in Metrics

| Metric Name | What It Does | Returns |
|-------------|--------------|---------|
| `"exact_match"` | Checks if output equals expected exactly | 1.0 or 0.0 |
| `"contains_expected"` | Checks if expected is substring of output | 1.0 or 0.0 |
| `"fuzzy_match"` | Similarity score (Levenshtein-based) | 0.0 to 1.0 |

```python
evaluator = Evaluator(
    task=my_task,
    dataset="my-dataset",
    metrics=["exact_match", "contains_expected"],  # Use strings for built-in
)
```

> ⚠️ **Important**: Built-in metrics compare your task's output to the `expected_output` field in your dataset. If your dataset has no `expected_output`, these metrics will receive `None` and may not work as expected.

### Custom Metrics

A custom metric is a function you define. The evaluator **automatically detects** how many parameters your metric accepts and calls it accordingly.

#### Metric Signatures

```python
# 1-parameter metric: only receives output
def my_metric(output):
    return 1.0 if len(output) > 10 else 0.0

# 2-parameter metric: receives output and expected
def my_metric(output, expected):
    return 1.0 if output == expected else 0.0

# 3-parameter metric: receives output, expected, and input
def my_metric(output, expected, input_data):
    # Can use the original input for evaluation
    return 1.0 if input_data["category"] in output else 0.0
```

#### Parameter Names (Important!)

The parameter **names matter** for keyword argument matching. Use these exact names:

| Position | Parameter Name | What It Contains |
|----------|---------------|------------------|
| 1st | `output` | What your task returned |
| 2nd | `expected` | The `expected_output` from dataset (or `None`) |
| 3rd | `input_data` | The original `input` from dataset |

```python
# ✅ CORRECT: Using standard parameter names
def my_metric(output, expected, input_data):
    ...

# ✅ ALSO CORRECT: Positional matching works with any names
def my_metric(result, ground_truth, question):
    # Works! Matched by position: result=output, ground_truth=expected, question=input_data
    ...

# ⚠️ BE CAREFUL: If using keyword-style, names must match
def my_metric(output, expected):  # OK
def my_metric(output, exp):       # OK (positional)

# ❌ WRONG: Parameters in wrong order
def bad_metric(expected, output):  # Should be (output, expected)!
    return 1.0 if output == expected else 0.0
# This will compare the wrong values!

# ❌ WRONG: Missing expected
def bad_metric(output, input_data):  # Should be (output, expected, input_data)!
    return 1.0 if input_data in output else 0.0
# Do this even if expected is not needed!
```

#### Metric Return Values

Your metric can return:

```python
# Option 1: Just a score (float)
def simple_metric(output, expected):
    return 0.85

# Option 2: Boolean (converted to 1.0 or 0.0)
def bool_metric(output, expected):
    return output == expected  # True/False

# Option 3: Dict with score and metadata (recommended for debugging)
def detailed_metric(output, expected):
    return {
        "score": 0.85,
        "metadata": {
            "output_length": len(output),
            "match_type": "partial",
            "reason": "Missing key details"
        }
    }
```

The metadata appears in your CSV results and Langfuse traces for debugging.

#### Using Custom Metrics with Any Task Output

When using **only custom metrics**, your task can return **any type** (not just strings):

```python
# Task returns a dict
def my_task(question):
    return {
        "answer": "Paris",
        "confidence": 0.95,
        "sources": ["wikipedia"]
    }

# Custom metric handles the dict
def confidence_metric(output, expected):
    # output is the dict returned by the task
    return output["confidence"]  # Returns 0.95

def answer_match(output, expected):
    return 1.0 if output["answer"] == expected else 0.0

evaluator = Evaluator(
    task=my_task,
    dataset="my-dataset",
    metrics=[confidence_metric, answer_match],  # Works with dict output!
)
```

> ⚠️ **Note**: Built-in metrics like `exact_match` expect string outputs. If your task returns non-strings, use custom metrics.

#### Async Metrics

Metrics can be async (useful for LLM-as-judge):

```python
async def llm_judge_metric(output, expected, input_data):
    response = await openai_client.chat.completions.create(
        model="gpt-4",
        messages=[{
            "role": "user",
            "content": f"Rate this answer 0-1:\nQuestion: {input_data}\nAnswer: {output}"
        }]
    )
    return float(response.choices[0].message.content)
```

### Mixing Built-in and Custom Metrics

```python
def has_greeting(output, expected):
    greetings = ["hello", "hi", "hey"]
    return 1.0 if any(g in output.lower() for g in greetings) else 0.0

evaluator = Evaluator(
    task=my_task,
    dataset="my-dataset",
    metrics=["exact_match", has_greeting],  # Mix strings and functions
)
```

### ⚠️ Common Metric Mistakes

```python
# ❌ WRONG: Metric name doesn't exist
metrics=["faithfulness"]  # Not a built-in! Will error.

# ❌ WRONG: Returns wrong type
def bad_metric(output, expected):
    return "good"  # Should return float, bool, or dict with 'score'

# ❌ WRONG: Metric doesn't handle None expected
def bad_metric(output, expected):
    return output == expected  # Crashes if expected is None

# ✅ CORRECT: Right order and handles edge cases
def good_metric(output, expected):
    if expected is None:
        return 1.0 if len(str(output)) > 0 else 0.0
    return 1.0 if output == expected else 0.0
```

---

## 5. Setting Up Your Dataset

### Dataset Structure in Langfuse

Each dataset item must have:

| Field | Required | Description |
|-------|----------|-------------|
| `input` | ✅ Yes | The input to your task (string, dict, or any JSON type) |
| `expected_output` | ⚠️ For built-in metrics | The correct answer for comparison |
| `metadata` | Optional | Extra info (user_id, category, etc.) |

### Creating a Dataset in Langfuse UI

1. Go to your Langfuse project
2. Click **Datasets** → **New Dataset**
3. Name it (e.g., `qa-test-set`)
4. Add items with this structure:

**Simple string input:**
```json
{
  "input": "What is the capital of France?",
  "expected_output": "Paris"
}
```

**Dict input (keys match your task parameters):**
```json
{
  "input": {
    "question": "What is the capital of France?",
    "context": "France is a country in Western Europe."
  },
  "expected_output": "Paris"
}
```

### Creating a Dataset via Python

```python
from langfuse import Langfuse

client = Langfuse()

# Create dataset
dataset = client.create_dataset(name="my-qa-dataset")

# Add items - string input
client.create_dataset_item(
    dataset_name="my-qa-dataset",
    input="What is 2 + 2?",
    expected_output="4"
)

# Add items - dict input
client.create_dataset_item(
    dataset_name="my-qa-dataset",
    input={"question": "Capital of Japan?", "hint": "Starts with T"},
    expected_output="Tokyo"
)
```

### ⚠️ Common Dataset Mistakes

```python
# ❌ WRONG: Dataset name doesn't exist (case-sensitive!)
evaluator = Evaluator(
    dataset="my-dataset",  # Typo! Actual name is "my_dataset"
    ...
)
# Error: "Dataset 'my-dataset' not found"

# ❌ WRONG: Empty dataset
# Error: "Dataset 'test' is empty. Please add items before evaluation."

# ❌ WRONG: Using built-in metrics without expected_output
# exact_match will receive None and may not work as expected
```

---

## 6. Running Your First Evaluation

### Complete Working Example

```python
# example.py
from dotenv import load_dotenv
load_dotenv()  # Load .env file FIRST - this is critical!

from llm_eval import Evaluator

# 1. Define your task (parameter name can be anything)
def simple_task(question, model_name=None):
    """A simple task that echoes the input."""
    # Replace this with your actual LLM call
    return f"You asked: {question}"

# 2. Define a custom metric
def length_check(output, expected):
    """Check if output has reasonable length."""
    return 1.0 if len(str(output)) > 10 else 0.0

# 3. Create evaluator
evaluator = Evaluator(
    task=simple_task,
    dataset="my-qa-dataset",  # Must exist in Langfuse
    metrics=["exact_match", length_check],  # Mix built-in and custom
    config={
        "max_concurrency": 5,  # Run 5 items in parallel
        "run_name": "my-first-eval",
    }
)

# 4. Run evaluation
results = evaluator.run()

# 5. Results are auto-saved to eval_results/ directory
print(f"Success rate: {results.success_rate:.1%}")
print(f"Total items: {results.total_items}")
```

### What Happens When You Run

1. **Dataset loads** from Langfuse
2. **Dashboard appears** showing live progress (TUI + Web UI)
3. **Items run in parallel** (controlled by `max_concurrency`)
4. **Metrics score** each output
5. **Results save** to CSV automatically
6. **Traces appear** in Langfuse for debugging

### The Dashboard

When you run, you'll see:

```
┌─────────────────────────────────────────────────────────────┐
│ LLM-Eval Dashboard                       Web UI: http://... │
├─────────────────────────────────────────────────────────────┤
│ Run: my-first-eval                                          │
│ Dataset: my-qa-dataset (100 items)                          │
│ Progress: ████████████████████░░░░░░░░░░ 67/100 (67%)       │
│                                                             │
│ Metrics:                                                    │
│   exact_match: 0.45 avg                                     │
│   length_check: 0.98 avg                                    │
│                                                             │
│ Latency: p50=1.2s, p95=3.4s                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 7. Multi-Model Comparison

### Option A: Single Evaluator with Multiple Models

```python
from llm_eval import Evaluator

async def my_task(question, model_name="gpt-4"):
    # model_name is automatically passed by the Evaluator
    return await call_llm(model_name, question)

evaluator = Evaluator(
    task=my_task,
    dataset="my-dataset",
    metrics=["exact_match"],
    model=["gpt-4", "gpt-3.5-turbo", "claude-3-sonnet"],  # List of models
)

# Runs all 3 models in parallel on the same dataset
results = evaluator.run()  # Returns list of 3 EvaluationResult objects
```

### Option B: run_parallel for Different Tasks

```python
from llm_eval import Evaluator

results = Evaluator.run_parallel(
    runs=[
        {
            "name": "QA Evaluation",
            "task": qa_task,
            "dataset": "qa-dataset",
            "metrics": ["exact_match"],
            "models": ["gpt-4", "claude-3"],  # 2 models × this task
            "config": {"max_concurrency": 10},
        },
        {
            "name": "Summarization",
            "task": summarize_task,
            "dataset": "docs-dataset",
            "metrics": ["contains_expected"],
            "models": ["gpt-4"],  # 1 model × this task
        },
    ],
    show_tui=True,  # Show live dashboard
    auto_save=True,  # Save results to CSV
)

# Total runs: 2 + 1 = 3 parallel evaluations
```

### Model Parameter in Your Task

When using `model=["gpt-4", "claude-3"]`, the evaluator calls your task with:

```python
# For first model:
my_task(question, model_name="gpt-4")

# For second model:
my_task(question, model_name="claude-3")
```

Make sure your task accepts `model_name` or `model` parameter!

---

## 8. Command Line Interface

### Basic Usage

```bash
# Evaluate a function from a file
llm-eval --task-file agent.py --task-function my_task \
         --dataset qa-dataset \
         --metrics exact_match
```

### All CLI Options

```bash
llm-eval \
    --task-file agent.py \           # Python file containing your task
    --task-function my_task \         # Function name to call
    --dataset qa-dataset \            # Langfuse dataset name
    --metrics exact_match,fuzzy_match \ # Comma-separated metrics
    --model gpt-4 \                   # Optional: tag with model name
    --concurrency 10 \                # Max parallel items (default: 10)
    --output results.csv \            # Custom output path
    --no-tui \                        # Disable terminal dashboard
    --quiet                           # Only show final summary
```

### Multi-Run Config File

Create `experiments.json`:

```json
[
  {
    "name": "gpt4-qa",
    "task_file": "agent.py",
    "task_function": "answer_question",
    "dataset": "qa-dataset",
    "metrics": ["exact_match"],
    "config": {
      "model": "gpt-4",
      "max_concurrency": 5
    }
  },
  {
    "name": "claude-qa",
    "task_file": "agent.py",
    "task_function": "answer_question",
    "dataset": "qa-dataset",
    "metrics": ["exact_match"],
    "config": {
      "model": "claude-3",
      "max_concurrency": 5
    }
  }
]
```

Run all experiments:

```bash
llm-eval --runs-config experiments.json
```

---

## 9. Understanding Results

### Output Files

Results are saved to `eval_results/{task}/{model}/{date}/`:

```
eval_results/
└── my_task/
    └── gpt-4/
        └── 2024-01-15/
            └── my_task-qa-dataset-gpt-4-240115-1430.csv
```

### CSV Columns

| Column | Description |
|--------|-------------|
| `item_id` | Unique identifier for the dataset item |
| `input` | The input sent to your task |
| `output` | What your task returned |
| `expected_output` | The expected answer from dataset |
| `{metric}_score` | Score for each metric (e.g., `exact_match_score`) |
| `time` | Latency in seconds |
| `trace_id` | Langfuse trace ID for debugging |

### Programmatic Access

```python
results = evaluator.run()

# Overall stats
print(f"Total: {results.total_items}")
print(f"Success rate: {results.success_rate:.1%}")
print(f"Duration: {results.duration:.1f}s")

# Per-metric stats
for metric in results.metrics:
    stats = results.get_metric_stats(metric)
    print(f"{metric}: mean={stats['mean']:.3f}, std={stats['std']:.3f}")

# Timing stats
timing = results.get_timing_stats()
print(f"Avg latency: {timing['mean']:.2f}s")
```

---

## 10. Configuration Options

### Full Config Reference

```python
evaluator = Evaluator(
    task=my_task,
    dataset="my-dataset",
    metrics=["exact_match"],
    model="gpt-4",  # Or list: ["gpt-4", "claude-3"]
    config={
        # Execution
        "max_concurrency": 10,     # Parallel items (default: 10)
        "timeout": 30.0,           # Seconds per item (default: 30)

        # Naming
        "run_name": "experiment-1", # Custom run name
        "run_metadata": {           # Extra metadata for traces
            "version": "1.0",
            "environment": "staging",
        },

        # Output
        "output_dir": "./results",  # Where to save files

        # Langfuse (override env vars)
        "langfuse_public_key": "pk-...",
        "langfuse_secret_key": "sk-...",
        "langfuse_host": "https://cloud.langfuse.com",
    }
)
```

### run() Options

```python
results = evaluator.run(
    show_progress=True,   # Show TUI dashboard (default: True)
    show_table=True,      # Show live table (default: True)
    auto_save=True,       # Save to CSV (default: True)
    save_format="csv",    # "csv" or "json" (default: "csv")
)
```

### run_parallel() Options

```python
results = Evaluator.run_parallel(
    runs=[...],
    show_tui=True,         # Show multi-run dashboard
    auto_save=True,        # Save each run's results
    save_format="csv",     # Output format
    print_summary=True,    # Print summary table at end
    keep_server_alive=True, # Keep Web UI running after completion
)
```

---

## 11. Common Errors & Solutions

### "Dataset 'X' not found"

```
DatasetNotFoundError: Dataset 'my-dataset' not found.
Available datasets: qa-set, test-data, ...
```

**Solution**: Check the exact dataset name in Langfuse. Names are case-sensitive.

### "Missing Langfuse public key"

```
LangfuseConnectionError: Missing Langfuse public key.
```

**Solution**:
1. Create `.env` file with credentials
2. Add `from dotenv import load_dotenv; load_dotenv()` at the **top** of your script
3. Or export environment variables directly

### "Metric 'X' not found"

```
ValueError: Unknown metric: 'faithfulness'
```

**Solution**: Use only built-in metrics: `exact_match`, `contains_expected`, `fuzzy_match`. Or pass a custom function.

### "Task returned None"

Your task function doesn't return anything.

**Solution**: Add `return` statement to your task.

### "Rate limit exceeded" / Timeouts

Your LLM provider is throttling requests.

**Solution**:
```python
config={
    "max_concurrency": 3,  # Reduce from 10
    "timeout": 60.0,       # Increase timeout
}
```

### Results show all zeros / ERROR

Metric is failing silently.

**Solution**: Check your metric handles `None` expected values:
```python
def my_metric(output, expected):
    if expected is None:
        return 1.0  # Or whatever makes sense
    return 1.0 if output == expected else 0.0
```

---

## Quick Reference

```python
from dotenv import load_dotenv
load_dotenv()

from llm_eval import Evaluator

# Minimal example
evaluator = Evaluator(
    task=lambda x: f"Response: {x}",
    dataset="my-dataset",
    metrics=["exact_match"],
)
results = evaluator.run()

# Multi-model example
evaluator = Evaluator(
    task=my_task,
    dataset="my-dataset",
    metrics=["exact_match", my_custom_metric],
    model=["gpt-4", "claude-3"],
    config={"max_concurrency": 5},
)
results = evaluator.run()

# Parallel runs example
results = Evaluator.run_parallel(
    runs=[
        {"name": "Run1", "task": task1, "dataset": "ds1", "metrics": ["exact_match"]},
        {"name": "Run2", "task": task2, "dataset": "ds2", "metrics": ["fuzzy_match"]},
    ],
    auto_save=True,
)
```

---

**Need help?** Check the [examples/](../examples/) directory for complete working scripts.
