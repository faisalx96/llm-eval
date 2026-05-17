# qym (قيِّم) User Guide

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
9. [Auto-Instrumentation & Tracing](#9-auto-instrumentation--tracing)
10. [Dashboard & Web UI](#10-dashboard--web-ui)
11. [Understanding Results](#11-understanding-results)
12. [Pause/Resume & Checkpointing](#12-pause-resume--checkpointing)
13. [Configuration Options](#13-configuration-options)
14. [Common Errors & Solutions](#14-common-errors--solutions)

---

## 1. Installation & Setup

### Step 1: Install the package

```bash
pip install qym
```

### Step 2: Set up Langfuse credentials (optional for CSV datasets)

qym integrates with [Langfuse](https://langfuse.com) for dataset storage and tracing. If you're using a **local CSV file** as your dataset, Langfuse credentials are optional—evaluations will run without tracing.

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

### Step 3: Connect to a qym platform deployment

The qym platform is the central dashboard where evaluation runs can be stored, compared, and shared.

To connect, you need an API key:

1. Open your qym platform deployment in a browser
2. Go to the profile or settings page
3. Find the API key management section
4. Create a new key
5. Copy the generated token if it is shown only once

Add the key to your `.env` file:

```bash
QYM_API_KEY=your-api-key
QYM_PLATFORM_URL=https://your-qym-platform.example.com
```

When `QYM_API_KEY` is set, your evaluation runs are automatically streamed to the platform in real time — no code changes needed. You can watch runs live on the dashboard, browse history, and compare results across models.

### Step 4: Verify setup

```python
from langfuse import Langfuse

client = Langfuse()
print("Connected to Langfuse!")  # If no error, you're ready
```

---

## 2. Understanding the Basics

### How qym Works

```
┌─────────────────────────────────────────────────────────────┐
│                        qym (قيِّم)                            │
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
| **Dataset** | Collection of test items (Langfuse dataset or local CSV file) |
| **Metrics** | Functions that score your output |
| **Trace** | Langfuse observability object for logging (optional) |

---

## 3. Writing Your Task Function

Your task function is the code being evaluated. qym uses **smart argument resolution** to call your function flexibly.

### How Input is Passed to Your Task

The evaluator looks at your function signature and passes arguments intelligently:

| Your Function | How Evaluator Calls It |
|---------------|------------------------|
| `def task(question)` | `task(question=input_data)` |
| `def task(input_data)` | `task(input_data=input_data)` |
| `def task(x)` | `task(x=input_data)` |
| `def task(q, context)` | `task(q=input["q"], context=input["context"])` if input is dict |
| `def task(q, model_name)` | `task(q=input_data, model_name="gpt-4")` |
| `def task(q, trace_id)` | `task(q=input_data, trace_id="abc-123...")` |
| `def task(**kwargs)` | `task(**input_data, model="gpt-4", trace_id="...")` if input is dict |

**Special parameters** automatically populated by the evaluator:
- `model` or `model_name`: The current model being evaluated
- `trace_id`: The Langfuse trace ID for the current item

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

### Task with Trace ID (For Observability)

If you need the Langfuse trace ID for logging or debugging, add a `trace_id` parameter:

```python
def my_task(question, trace_id=None):
    """
    Args:
        question: The input
        trace_id: Langfuse trace ID (passed automatically by Evaluator)
    """
    # Use trace_id for custom logging, linking to external systems, etc.
    print(f"Processing with trace: {trace_id}")

    # You can also pass it to sub-systems for tracing
    result = call_llm(question, metadata={"trace_id": trace_id})
    return result
```

The evaluator automatically detects the `trace_id` parameter and passes the current Langfuse trace ID. This is useful for:
- Linking evaluation results to external logging systems
- Debugging specific items in Langfuse
- Correlating traces across services

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
| `"contains"` | Checks if expected is substring of output | 1.0 or 0.0 |
| `"fuzzy_match"` | Similarity score (Levenshtein-based) | 0.0 to 1.0 |

```python
evaluator = Evaluator(
    task=my_task,
    dataset="my-dataset",
    metrics=["exact_match", "contains"],  # Use strings for built-in
)
```

> ⚠️ **Important**: Built-in metrics compare your task's output to the `expected_output` field in your dataset. If your dataset has no `expected_output`, these metrics will receive `None` and may not work as expected.

Use the [Metric Bank](METRIC_BANK.md) for a broader catalog of metric ideas, tradeoffs, and use-case-driven recommendations. This section focuses on how metrics work in qym rather than acting as the full metric reference.

### LLM Judge Metrics

qym includes built-in LLM-as-judge metrics that use an OpenAI-compatible API. Install with `pip install openai`.

| Metric Name | What It Evaluates | Required Input Fields |
|-------------|-------------------|----------------------|
| `"relevance"` | Is the response relevant? | `question` |
| `"faithfulness_llm"` | Is it grounded in context? | `context`, `question` |
| `"correctness_llm"` | Does it match expected? | `question` |
| `"hallucination"` | Contains hallucinated content? | `context` |
| `"toxicity"` | Contains harmful content? | _(none)_ |
| `"conciseness"` | Is it concise or verbose? | `question` |
| `"tool_calling"` | Are tool calls correct? | `tool_definitions`, `tool_calls` |

```python
evaluator = Evaluator(
    task=my_task,
    dataset="my-dataset",
    metrics=["exact_match", "relevance", "faithfulness_llm"],
)
```

The "Required Input Fields" column shows what keys your dataset's `input` dict should contain. For example, `relevance` expects `input_data["question"]`.

**Configuration** — you must configure your LLM provider before using judge metrics. Add to your `.env` file:

```bash
QYM_JUDGE_MODEL=gpt-4o-mini      # Required: model name
QYM_JUDGE_API_KEY=sk-...         # Required: API key (or set OPENAI_API_KEY)
QYM_JUDGE_BASE_URL=http://...    # Optional: for vLLM, Ollama, etc.
```

Or pass directly when creating a custom judge in Python:

```python
from qym.metrics.judges import create_judge

my_judge = create_judge(
    name="my_judge",
    prompt="Is this response correct?\n[Expected]: {expected}\n[Response]: {output}",
    choices={"correct": 1.0, "incorrect": 0.0},
    judge_model="gpt-4o-mini",
    judge_api_key="sk-...",
    judge_base_url="http://localhost:8000/v1",  # Optional
)
```

You can also set a global default for all judges:

```python
from qym.metrics import JudgeConfig, set_default_judge_config

set_default_judge_config(JudgeConfig(
    model="gpt-4o-mini",
    api_key="sk-...",
    base_url="http://localhost:8000/v1",  # Optional
))
```

If no configuration is provided (neither `.env`, nor per-judge params, nor global default), qym will show a clear error message explaining what's needed.

**Custom judges** — create your own with `create_judge()`:

```python
from qym.metrics.judges import create_judge

# Binary judge (pass/fail)
helpfulness = create_judge(
    name="helpfulness",
    prompt="Is this response helpful?\n[Question]: {question}\n[Response]: {output}",
    choices={"helpful": 1.0, "unhelpful": 0.0},
)

# Multi-level judge (graded scale)
answer_quality = create_judge(
    name="answer_quality",
    prompt="""\
Rate the quality of this response.
- excellent: Fully correct, well-structured, and comprehensive
- good: Mostly correct with minor gaps
- poor: Partially correct but missing key information
- bad: Incorrect or completely off-topic

[Question]: {question}
[Response]: {output}""",
    choices={"excellent": 1.0, "good": 0.7, "poor": 0.3, "bad": 0.0},
)

evaluator = Evaluator(
    task=my_task,
    dataset="my-dataset",
    metrics=["exact_match", helpfulness, answer_quality],
)
```

**How it works:** The LLM responds with structured JSON like:

```json
{"verdict": "good", "explanation": "The response covers the main points but misses edge cases."}
```

qym parses this into a `MetricResult` with:
- `score` — mapped from the `choices` dict (e.g. `"good"` → `0.7`)
- `label` — the verdict string (e.g. `"good"`)
- `explanation` — the LLM's reasoning

Labels and explanations are stored in the platform and visible per-item in the dashboard.

**Per-judge LLM override** — use a different model for a specific judge:

```python
toxicity_local = create_judge(
    name="toxicity_local",
    prompt="Is this response toxic or non-toxic?\n[Response]: {output}",
    choices={"non-toxic": 1.0, "toxic": 0.0},
    judge_model="llama-3.1-8b",
    judge_base_url="http://localhost:11434/v1",
    judge_api_key="ollama",
)
```

**Pairwise comparison judges** — instead of scoring one output on an absolute scale, compare two outputs and decide which is better. Research shows LLMs are more reliable at relative comparison than absolute scoring.

```python
from qym.metrics.judges import create_pairwise_judge

compare_quality = create_pairwise_judge(
    name="compare_quality",
    prompt="""\
Compare these two responses to the same question.

[Question]: {question}
[Response A]: {output_a}
[Response B]: {output_b}

Which response is better? Consider accuracy, completeness, and clarity.
Answer A, B, or tie.""",
)

evaluator = Evaluator(
    task=my_task,
    dataset="my-dataset",
    metrics=[compare_quality],
)
```

The pairwise judge returns:
- `score` — `1.0` (A wins), `0.5` (tie), `0.0` (B wins)
- `label` — `"A"`, `"B"`, or `"tie"`
- `explanation` — the LLM's reasoning

**Where do A and B come from?**
- `{output_a}` is always your task's output (the thing being evaluated)
- `{output_b}` comes from one of two places:
  1. **Default:** the dataset's `expected` field — useful for comparing your model's output against a gold-standard answer
  2. **Explicit:** `input_data["output_b"]` — useful for comparing two models' outputs on the same input. Add an `output_b` column to your CSV dataset with the baseline model's response.

```python
# Example CSV dataset for pairwise comparison:
# id, question, expected, output_b
# 1, "What is 2+2?", "4", "The answer is four."
#
# Your task produces output_a. The CSV provides output_b.
# The judge compares them.
```

**Factory options for `create_judge()` and `create_pairwise_judge()`:**
- `choices` — dict mapping verdict labels to scores. Binary (2 labels) or multi-level (any number). Scores should be between 0.0 and 1.0.
- `judge_model`, `judge_api_key`, `judge_base_url` — per-judge LLM provider override
- `langfuse_prompt` — fetch prompt template from Langfuse prompt management instead of using the `prompt` parameter
- `system_prompt` — override the default system prompt

**Reliability:** LLM judge calls include **exponential backoff with jitter** (3 attempts) so transient API failures don't cause metric errors. Template variables are substituted safely — missing variables produce a clear error rather than a silent failure.

### Structured Results (MetricResult)

Every LLM judge returns a `MetricResult` with:

| Field | Example | Description |
|-------|---------|-------------|
| `score` | `0.7` | Numeric value mapped from the verdict via `choices` |
| `label` | `"good"` | The verdict label chosen by the LLM |
| `explanation` | `"Covers main points but..."` | The LLM's reasoning for its verdict |
| `kind` | `"llm"` | Always `"llm"` for judge metrics |

Labels and explanations are stored in the platform database and visible per-item in the dashboard. This lets you see not just the score but *why* the judge gave that score. Custom metrics can also return `MetricResult` for the same structured storage.

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

### CSV Datasets (Local)

If you already have test cases in a spreadsheet or CSV, you can run evaluations directly from a local `.csv` file—**no Langfuse dataset required**.

**You can use any column names** — you map them when constructing the dataset (Python) or via CLI flags.

#### Required columns

- A column containing the task **input** (you choose its name, then pass it as `input_col` / `--csv-input-col`).

#### Optional columns

- **Expected output** column (for built-in metrics like `exact_match`): pass as `expected_col` / `--csv-expected-col`
- **ID** column: pass as `id_col` / `--csv-id-col` (otherwise IDs are generated as `row_000000`, `row_000001`, ...)
- **Metadata** columns: pass as `metadata_cols` / `--csv-metadata-cols` (we convert them into a JSON object/dict per row)

#### Cell parsing rules (minimal, predictable)

- If a cell starts with `{` or `[`, it is parsed as JSON (dict/list).
- Otherwise it is treated as a string.
- If a `{...}` or `[...]` cell contains invalid JSON, you get a clear error including file, row, and column.

#### Example CSV

Create `datasets/qa.csv`:

```csv
question,answer,category,difficulty
What is 2+2?,4,math,easy
"{""question"":""Capital of Japan?"",""hint"":""Starts with T""}",Tokyo,geo,easy
```

Notes:
- The first row's `question` is a plain string.
- The second row's `question` is a JSON object (so your task can accept dict input).

#### Run via CLI

```bash
qym --task-file agent.py --task-function my_task \
  --dataset-csv datasets/qa.csv \
  --csv-input-col question \
  --csv-expected-col answer \
  --csv-metadata-cols category,difficulty \
  --metrics exact_match
```

#### Run via Python API

```python
from qym import Evaluator, CsvDataset

dataset = CsvDataset(
    "datasets/qa.csv",
    input_col="question",
    expected_col="answer",
    metadata_cols=["category", "difficulty"],
)

evaluator = Evaluator(
    task=my_task,
    dataset=dataset,
    metrics=["exact_match"],
)

results = evaluator.run()
```

**Tracing behavior:** If your Langfuse credentials are set, runs created from CSV will still emit Langfuse traces (useful if your task expects `trace_id`). If credentials are not set, evaluation still runs (without tracing).

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

from qym import Evaluator

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

# 5. Results are auto-saved to qym_results/ directory
print(f"Success rate: {results.success_rate:.1%}")
print(f"Total items: {results.total_items}")
```

### What Happens When You Run

1. **Dataset loads** (from Langfuse or local CSV)
2. **Version captured** — git branch and commit are auto-detected
3. **Dashboard appears** showing live progress (TUI + platform streaming)
4. **Items run in parallel** (controlled by `max_concurrency`), with automatic retries on failure (up to `max_retries`, default 2)
5. **LLM calls traced** — supported LLM calls are captured as spans when tracing is enabled
6. **Metrics score** each output
7. **Results save** to CSV automatically and stream to the platform (if `QYM_API_KEY` is set)
8. **Traces viewable** in the embedded trace viewer and Langfuse (if configured)

### The Dashboard

When you run, you'll see:

```
┌─────────────────────────────────────────────────────────────┐
│ qym Dashboard                               Web UI: http://... │
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

### Progress Hooks For Wrappers

If you are building a wrapper, notebook integration, web UI, job runner, or orchestration layer on top of qym, pass `progress_callback` to `Evaluator`. The callback receives a structured `ProgressSnapshot`.

For multi-run work, qym first emits a `run_matrix` snapshot so your UI can render the full expected shape before individual runs start. Matrix entries include each run's `run_id`, display name, task, dataset, model, metrics, `total_items` when known, initial `status`, `platform_run_id=None`, and `qym_url=None`. When a run is created on the qym platform, that run's later `run_start` snapshot includes `run_info["qym_url"]` and `run_info["platform_run_id"]`.

```python
from qym import Evaluator, ProgressSnapshot


def on_progress(snapshot: ProgressSnapshot):
    if snapshot.event == "run_matrix":
        for run in snapshot.run_matrix or []:
            create_pending_row(
                run_id=run["run_id"],
                model=run.get("model"),
                total_items=run.get("total_items"),
                qym_url=run.get("qym_url"),  # None until that run starts
            )
        return

    if snapshot.event == "run_start":
        update_run_link(
            run_id=snapshot.run_id,
            qym_url=(snapshot.run_info or {}).get("qym_url"),
        )

    print(
        f"{snapshot.run_id}: {snapshot.finished}/{snapshot.total_items} "
        f"done, {snapshot.in_progress} running, {snapshot.failed} failed"
    )


evaluator = Evaluator(
    task=simple_task,
    dataset="my-qa-dataset",
    metrics=["exact_match"],
    progress_callback=on_progress,
)

results = evaluator.run(show_tui=False)
```

`ProgressSnapshot` includes:

| Field | Description |
|-------|-------------|
| `event` | Event name such as `run_start`, `item_start`, `metric_result`, `item_complete`, `item_error`, `warning`, or `run_complete` |
| `run_matrix`, `total_runs` | Present on `run_matrix` events for multi-run evaluations; each matrix row describes a pending run and includes `total_items` when the dataset is already resolved |
| `run_info` | Run metadata on `run_start`; includes `qym_url`, `html_url`, and `platform_run_id` when platform streaming is enabled |
| `total_items` | Number of dataset items in the run |
| `completed`, `failed`, `in_progress`, `pending` | Current item counts |
| `finished` | Convenience property: `completed + failed` |
| `percent_complete` | Convenience property from 0.0 to 100.0 |
| `item_index`, `metric_name`, `score`, `error`, `message`, `payload`, `metadata` | Event-specific details when available |

Metric result snapshots include live score values as metrics finish. Their `metadata` includes `duration_ms`, `duration_seconds`, `started_at_ms`, `completed_at_ms`, and `status` when qym measured the metric call. Item completion snapshots include `result["task_time"]`, `result["task_time_ms"]`, `result["total_time"]`, `result["total_time_ms"]`, `result["latency_ms"]`, item/task start and completion timestamps, and the final `scores` map.

You can also pass `observer=ProgressCallbackObserver(on_progress)` if you want to compose it with other observers yourself.
For `Evaluator.run_parallel(...)`, use `observer=ProgressCallbackObserver(on_progress)` because `progress_callback` is an `Evaluator(...)` constructor shortcut.

For advanced integrations, subclass `EvaluationObserver` and implement only the hooks you need:

```python
from qym import EvaluationObserver


class MyObserver(EvaluationObserver):
    def on_run_matrix(self, matrix_id, runs, total_runs):
        create_pending_runs(matrix_id=matrix_id, runs=runs, total_runs=total_runs)

    def on_run_start(self, run_id, run_info, total_items, metrics):
        update_qym_link(run_id, run_info.get("qym_url"))

    def on_metric_result(self, run_id, item_index, metric_name, score, metadata=None):
        send_metric(run_id, item_index, metric_name, score)
```

---

## 7. Multi-Model Comparison

### Option A: Single Evaluator with Multiple Models

```python
from qym import Evaluator

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
from qym import Evaluator

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
            "metrics": ["contains"],
            "models": ["gpt-4"],  # 1 model × this task
        },
    ],
    show_tui=True,  # Show live dashboard
    auto_save=True,  # Save results to CSV
)

# Total runs: 2 + 1 = 3 parallel evaluations.
# Pass observer=ProgressCallbackObserver(on_progress) to receive one run_matrix
# event for these 3 runs before per-run run_start/item/metric events begin.
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

The qym CLI uses **noun-verb command groups**. All commands support `--json` for structured, automation-friendly output.

### Running an Evaluation

```bash
# Run an evaluation (recommended)
qym run create --task-file agent.py --task-function my_task \
  --dataset qa-dataset --metrics exact_match

# With version tracking (auto-detected by default)
qym run create --task-file agent.py --task-function my_task \
  --dataset qa-dataset --metrics exact_match \
  --git-branch main --git-commit abc1234
```

### `qym run create` Options

```bash
qym run create \
    --task-file agent.py \            # Python file containing your task
    --task-function my_task \          # Function name to call
    --dataset qa-dataset \             # Langfuse dataset name
    --metrics exact_match,fuzzy_match \ # Comma-separated metrics
    --model gpt-4 \                    # Optional: tag with model name
    --concurrency 10 \                 # Max parallel items (default: 10)
    --output results.csv \             # Custom output path
    --no-tui \                         # Disable terminal dashboard
    --quiet \                          # Only show final summary
    --git-branch main \                # Override auto-detected git branch
    --git-commit abc1234               # Override auto-detected git commit
```

### Other Run Commands

```bash
qym run list [--user USER] # List recent evaluation runs from the platform
qym run get <run_id>   # Get detailed data for a specific run
qym run tasks          # List distinct task names from the platform
qym run failed <run_id> # Get only failed/error items from a run
qym run compare        # Compare multiple runs side-by-side
```

### Analysis Commands

```bash
qym analyze run <run_id>      # Trigger AI root-cause analysis on a run’s items
qym analyze summary <run_id>  # Get aggregated root-cause analysis summary
```

### Other Commands

```bash
qym metric list    # List all available evaluation metrics
qym config show    # Show resolved platform configuration
qym config check   # Validate connectivity to the platform API
qym dashboard      # Open the platform dashboard in your browser
qym submit         # Upload a saved results file to the platform
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
qym run create --runs-config experiments.json
```

### Resume a Partial Run

If a run is interrupted (Ctrl+C), the SDK sends a **STOPPED** status to the platform instead of leaving the run stuck in RUNNING. qym writes a checkpoint CSV as items complete. Resume by pointing to the checkpoint file:

```bash
qym run create --task-file agent.py --task-function my_task \
  --dataset my-dataset --metrics exact_match \
  --resume-from qym_results/.../run.csv
```

Resume requirements:
- Use the same dataset and metrics as the original run.
- Point to the exact checkpoint CSV for that run.
- `resume_from` automatically reuses the checkpoint run_id (no need to set `run_name`).

Where to find the checkpoint file:
- The checkpoint is the same CSV under `qym_results/...` and is updated as items finish.
- On interrupt, qym prints the checkpoint path and a resume command in the terminal.

Resume via Python API:

```python
from qym import Evaluator

evaluator = Evaluator(
    task=my_task,
    dataset="my-dataset",
    metrics=["exact_match"],
    config={
        "resume_from": "qym_results/.../run.csv",
    },
)

results = evaluator.run()
```

Multi-model resume:
- Resume is per-run. Use the specific run CSV for the model you want to resume.
- If using a `--runs-config`, set `resume_from` inside each run’s config block.

### Legacy Compatibility

Old-style invocations are automatically rewritten:
- `qym --task-file ...` → `qym run create --task-file ...`
- `qym resume --run-file ...` → `qym run create --resume-from ...`

---

## 9. Auto-Instrumentation & Tracing

qym can automatically capture every LLM call, tool use, and timing detail inside your task functions — without changing your code.

### Quick Setup

```bash
pip install qym
```

Instrumentation support is included in the base install. When you run an evaluation, LLM calls from supported providers and frameworks are automatically captured and stored as traces.

### What Gets Captured

- Every LLM API call (model, prompt, response, tokens, latency)
- Every tool/function call the LLM invokes
- Full chain of calls for agents and multi-step workflows
- Errors on any span
- Works with LangChain, LangGraph, LlamaIndex, CrewAI, Haystack, OpenAI Agents, and more

### Viewing Traces

Traces appear in two places:

1. **Embedded Trace Viewer** — click the trace icon on any item in the run or compare view to see a full span tree with LLM message reconstruction, reasoning display, error highlighting, and duration waterfall. See the [Platform User Guide](../../../packages/platform/docs/USER_GUIDE.md#trace-viewer).

2. **Langfuse** — if Langfuse credentials are configured, traces are also sent there. Click the trace link on any item row to jump directly to Langfuse.

3. **API** — query stored spans via `GET /api/runs/{run_id}/spans` or `GET /api/runs/{run_id}/items/{item_id}/trace`.

### Privacy

By default, full prompt and completion content is captured. To disable, add to your `.env`:

```bash
TRACELOOP_TRACE_CONTENT=false
```

### Disabling

```python
config = EvaluatorConfig(otel_enabled=False)
```

---

## 10. Dashboard & Web UI

qym provides two interfaces for monitoring evaluations: a Terminal UI (TUI) for quick command-line monitoring, and a full-featured platform dashboard for detailed analysis, comparison, and root cause investigation.

### Terminal UI (TUI)

When you run an evaluation, the TUI shows real-time progress in your terminal:

![Terminal UI](../../../docs/images/tui-progress.png)

**Features:**
- Multiple parallel evaluation tracking
- Progress bars with completion percentage
- Live latency histograms (P50, P90, P99)
- Real-time metric scores
- ETA estimation
- Items per second throughput

Control the TUI with the `show_tui` parameter:

```python
results = evaluator.run(
    show_tui=True,   # Show terminal dashboard (default)
    auto_save=True,
)
```

### Platform Dashboard

The platform dashboard at your configured `QYM_PLATFORM_URL` provides the full evaluation management experience. Open it with:

```bash
qym dashboard
```

The platform dashboard includes:

- **Runs view** — paginated listing with smart grouping, version tracking (git branch/commit), metric visibility controls, sticky columns, and status filtering (RUNNING, PENDING, COMPLETED, FAILED, STOPPED, DRAFT, SUBMITTED, APPROVED, REJECTED)
- **Single run view** — detailed results with metadata breakdown cards, interactive metric drill-down, category chip selectors, embedded trace viewer, root cause analysis, and self-contained HTML export for offline sharing
- **Compare view** — side-by-side item comparison with winner badges, score range filters, domain AND-matching, root-cause/solution breakdown with Sankey visualization, and approval filtering
- **Charts view** — per-task cards with dataset tabs, inline Run/Version/Model grouping, and a version leaderboard aggregating performance by git commit
- **Trace viewer** — embedded per-item span tree with LLM message reconstruction, reasoning display, error path highlighting, framework noise collapsing, and keyboard navigation
- **AI analysis** — one-click root cause analysis with a playground for prompt editing, category/detail catalogs, few-shot correction bank, and test runs
- **Corrections review** — dedicated approval queue with bulk moderation, revision history, and synced metadata

See the [Platform User Guide](../../../packages/platform/docs/USER_GUIDE.md) for full details on every feature.

### Dashboard Data Storage

The platform dashboard stores all runs in a central database. When you run evaluations with platform streaming enabled (`QYM_API_KEY`), runs are automatically stored on the platform.

For local development, results are also saved to `qym_results/` directory in your **current working directory**:

```
my-project/                    # Run from here!
├── qym_results/               # Results saved here
│   └── {task}/
│       └── {model}/
│           └── {date}/
│               └── {run_name}.csv
├── my_task.py
└── .env
```

You can upload saved results to the platform using:

```bash
qym submit --file path/to/results.csv --task my_task --dataset my-dataset
```

> **Note**: Uploaded files are parsed and ingested into the database. Raw uploaded files are NOT stored persistently.

### Publishing

Confluence publishing has been removed. Share results by linking to the dashboard/compare views and exporting results (CSV/JSON) as needed.

---

## 11. Understanding Results

### Output Files

Results are saved to `qym_results/{task}/{model}/{date}/` in your **current working directory**:

```
qym_results/
└── my_task/
    └── gpt-4/
        └── 2024-01-15/
            └── my_task-qa-dataset-gpt-4-240115-1430.csv
```

> **Tip**: Always run your evaluation scripts from your project root so results and dashboard stay in sync.

### CSV/Excel Columns

| Column | Description |
|--------|-------------|
| `item_id` | Unique identifier for the dataset item |
| `input` | The input sent to your task |
| `item_metadata` | Metadata from the dataset item (JSON) |
| `output` | What your task returned |
| `expected_output` | The expected answer from dataset |
| `{metric}_score` | Score for each metric (e.g., `exact_match_score`) |
| `time` | Latency in seconds |
| `trace_id` | Langfuse trace ID for debugging |

### Export Formats

Results can be saved in three formats:
- **CSV** (default): Standard comma-separated values
- **JSON**: Full structured data with all metadata
- **XLSX**: Excel spreadsheet

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

## 12. Pause/Resume & Checkpointing

qym can persist **partial results** while a run is in progress and resume later if the process stops (Ctrl+C, crash, or kill).

### How it works

- A checkpoint CSV is written **per completed item** (append-only).
- The checkpoint file is also a normal run file, so it appears in the dashboard.
- Resume skips any `item_id` already present in the checkpoint file.

### CLI behavior on interrupt

On Ctrl+C, qym prints a resume command with the checkpoint path:

```
Partial results saved to qym_results/.../run.csv
Resume with: qym resume --run-file qym_results/.../run.csv ...
```

### Configuration fields

```python
config = {
    "checkpoint_enabled": True,
    "checkpoint_format": "csv",
    "checkpoint_flush_each_item": True,
    "checkpoint_fsync": False,   # Set True for extra durability (slower)
    "resume_from": "qym_results/.../run.csv",
    "interrupt_grace_seconds": 2.0,
}
```

### Notes

- Resume appends to the **same run file** and **same run_id**.
- Completed items (including errors) are skipped on resume.
- `resume_rerun_errors` is not supported when appending to the same run file.

## 13. Configuration Options

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
        "timeout": 300.0,          # Seconds per item (default: 300)
        "max_retries": 2,          # Retry failed items (default: 2, exponential backoff + jitter)

        # Naming
        "run_name": "experiment-1", # Custom run name
        "run_metadata": {           # Extra metadata for traces
            "version": "1.0",
            "environment": "staging",
        },

        # Version tracking (auto-detected from git by default)
        "git_branch": "main",       # Override auto-detected git branch
        "git_commit": "abc1234",    # Override auto-detected git commit

        # Tracing
        "otel_enabled": True,       # Enable auto-instrumentation (default: True)

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
    show_tui=True,           # Show terminal UI dashboard (default: True)
    auto_save=True,          # Save results automatically (default: True)
    save_format="csv",       # "csv", "json", or "xlsx" (default: "csv")
    max_parallel_runs=None,  # For multi-model: control parallel execution (see below)
)
```

> **Note**: The Web UI is always available at the URL printed at startup.

### run_parallel() Options

```python
results = Evaluator.run_parallel(
    runs=[...],
    show_tui=True,          # Show terminal UI dashboard (default: True)
    auto_save=True,         # Save each run's results
    save_format="csv",      # "csv", "json", or "xlsx"
    max_parallel_runs=None, # Control how many runs execute at once (see below)
    observer=None,          # Optional observer for run_matrix and per-run events
)
```

> **Note**: The Web UI is always available at the URL printed at startup.

### Controlling Parallel Runs (Queue Mode)

When running many evaluations (e.g., 5 tasks × 6 models = 30 runs), you may want to limit how many run at once to avoid overwhelming your API or system.

```python
# Run all at once (default behavior)
results = Evaluator.run_parallel(runs=runs_config)

# Run sequentially - one at a time (queue mode)
results = Evaluator.run_parallel(runs=runs_config, max_parallel_runs=1)

# Run 3 at a time (balanced)
results = Evaluator.run_parallel(runs=runs_config, max_parallel_runs=3)
```

| `max_parallel_runs` | Behavior |
|---------------------|----------|
| `None` (default) | All runs execute simultaneously |
| `1` | Sequential queue - one run at a time |
| `N` | Up to N runs execute at once |

> **Tip**: Use `max_parallel_runs=1` for overnight batch jobs where you want predictable, sequential execution without overwhelming API rate limits.

---

## 14. Common Errors & Solutions

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
ValueError: Unknown metric: 'my_metric'
```

**Solution**: Use a built-in metric name (`exact_match`, `contains`, `fuzzy_match`, `relevance`, `faithfulness_llm`, `correctness_llm`, `hallucination`, `toxicity`, `conciseness`, `tool_calling`) or pass a custom function. Note: LLM judge metrics (like `relevance`) require configuring `QYM_JUDGE_MODEL` and `QYM_JUDGE_API_KEY`.

### "Task returned None"

Your task function doesn't return anything.

**Solution**: Add `return` statement to your task.

### "Rate limit exceeded" / Timeouts

Your LLM provider is throttling requests. Note: qym already retries failed items up to 2 times with exponential backoff + jitter by default.

**Solution**:
```python
config={
    "max_concurrency": 3,  # Reduce from 10
    "timeout": 600.0,      # Increase timeout (default is 300s)
    "max_retries": 3,      # Increase retries (default is 2)
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
load_dotenv()  # Optional for CSV datasets

from qym import Evaluator, CsvDataset

# Minimal example (Langfuse dataset)
evaluator = Evaluator(
    task=lambda x: f"Response: {x}",
    dataset="my-dataset",
    metrics=["exact_match"],
)
results = evaluator.run()

# CSV dataset example (no Langfuse required)
evaluator = Evaluator(
    task=my_task,
    dataset=CsvDataset("data.csv", input_col="question", expected_col="answer"),
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

**Need help?** Check the [examples/](../../../examples/) directory for complete working scripts.
