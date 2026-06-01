# SDK Integration Guide

Use this guide when you are embedding the qym SDK into an application, queue worker, notebook, CI harness, internal evaluation service, or model comparison workflow.

The guide starts with the call pattern, then defines the input shapes, output shapes, progress events, observer hooks, and run configuration options you can pass.

## Direction Board

Use this table as the reader path through the guide.

| If you need to... | Go to |
| --- | --- |
| Run the SDK for the first time from Python | [How To Call The SDK](#how-to-call-the-sdk) |
| Understand the minimum mental model before coding | [Integration Flow](#integration-flow) |
| Choose between single run, async run, multi-model, and multi-run | [How To Call The SDK](#how-to-call-the-sdk) |
| Know exactly what `Evaluator(...)` accepts | [Evaluator Constructor](#evaluator-constructor) |
| Shape CSV rows, dataset items, task inputs, and expected outputs | [Input Shapes](#input-shapes) |
| Write a task function with scalar, structured, async, or model-aware input | [Task Function Shape](#task-function-shape) |
| Add built-in metrics or custom metric callables | [Metric Shape](#metric-shape) |
| Read the returned result object or serialize it | [Output Shapes](#output-shapes) |
| Know what gets written to CSV, JSON, or XLSX artifacts | [Saved Artifacts](#saved-artifacts) |
| Compute Pass@K, Avg@K, consistency, or reliability from SDK results | [Group Run Analysis](#group-run-analysis) |
| Update your own job table, websocket, notebook, or CI status | [Live Progress Events](#live-progress-events) |
| Implement named lifecycle hooks instead of one callback | [Observer Integration](#observer-integration) |
| Make runs appear in the shared qym dashboard | [Platform Streaming](#platform-streaming) |
| Tune concurrency, retries, timeouts, artifacts, tracing, models, and platform settings | [Run Configs](#run-configs) |
| Copy a realistic service wrapper pattern | [Complete Service Wrapper Example](#complete-service-wrapper-example) |
| Check whether an integration is production-ready | [Integration Checklist](#integration-checklist) |

## Integration Flow

At a high level, qym evaluates one task over one dataset and scores every output with one or more metrics.

```text
dataset item -> task function -> output -> metrics -> EvaluationResult
                                      -> local artifacts
                                      -> optional platform stream
                                      -> optional local progress events
```

The SDK entrypoint is `Evaluator`.

```python
from qym import CsvDataset, Evaluator


def answer_question(question: str) -> str:
    return call_your_model(question)


dataset = CsvDataset(
    "datasets/qa.csv",
    input_col="question",
    expected_col="answer",
    id_col="id",
    metadata_cols=["domain", "difficulty"],
)

result = Evaluator(
    task=answer_question,
    dataset=dataset,
    metrics=["exact_match"],
    config={
        "run_name": "qa-smoke",
        "task_name": "answer-question",
        "max_concurrency": 4,
        "max_retries": 1,
        "run_metadata": {
            "prompt_version": "v3",
            "dataset_version": "2026-04-30",
        },
    },
).run(show_tui=False)

print(result.total_items)
print(result.success_rate)
print(result.last_saved_path)
```

Most integrations should start with this shape:

| Component | You provide | qym does |
| --- | --- | --- |
| Task | A Python callable or supported framework object. | Calls it once per dataset item input. |
| Dataset | A `CsvDataset`, Langfuse dataset name, or compatible dataset object. | Loads items with `id`, `input`, `expected_output`, and `metadata`. |
| Metrics | Built-in metric names or metric callables. | Scores every task output. |
| Config | A dict or `EvaluatorConfig`. | Applies concurrency, retries, timeouts, output, tracing, model, and platform settings. |
| Progress | Optional `progress_callback` or `EvaluationObserver`. | Emits local lifecycle updates for your wrapper. |

## How To Call The SDK

### Single Run

Use `run()` from normal scripts, services, workers, and notebooks.

```python
from qym import Evaluator

result = Evaluator(
    task=my_task,
    dataset=my_dataset,
    metrics=["exact_match", "contains"],
).run(show_tui=False)
```

`run()` returns one `EvaluationResult` for a single model.

Useful `run()` arguments:

| Argument | Default | Meaning |
| --- | --- | --- |
| `show_tui` | `True` | Show the terminal progress UI. Set `False` when another system owns status display. |
| `auto_save` | `True` | Save result artifacts after the run. |
| `save_format` | `"csv"` | Auto-save format: `"csv"`, `"json"`, or `"xlsx"`. |
| `max_parallel_runs` | `None` | Only applies to multi-model runs. `None` runs all models in parallel, `1` runs sequentially, `N` limits active model runs. |

### Async Run

Use `arun()` when your caller is already async and should await the evaluation.

```python
result = await Evaluator(
    task=my_async_task,
    dataset=my_dataset,
    metrics=["exact_match"],
).arun(show_tui=False, auto_save=True)
```

Async task functions are preferred for high-throughput LLM calls. Sync task functions are still supported.

### Multi-Model Run

Use `model=[...]` when the task, dataset, and metrics are the same and only model routing changes.

```python
def answer(question: str, model_name: str = "gpt-4o-mini") -> str:
    return call_llm(model=model_name, prompt=question)


results = Evaluator(
    task=answer,
    dataset=dataset,
    metrics=["exact_match", "relevance"],
    model=["gpt-4o-mini", "gpt-4.1-mini"],
    config={"run_name": "qa-model-compare"},
).run(show_tui=False, max_parallel_runs=2)
```

`run()` returns `list[EvaluationResult]` for multi-model runs.

qym passes the model into your task when your task accepts `model_name` or `model`. If your task ignores that parameter or hardcodes a provider model, all model runs may call the same model.

### Multi-Run Specs

Use `Evaluator.run_parallel(...)` when tasks, datasets, metrics, or config values differ between runs.

```python
from qym import Evaluator, ProgressCallbackObserver


results = Evaluator.run_parallel(
    [
        {
            "name": "baseline",
            "display_name": "Baseline Prompt",
            "task": baseline_task,
            "dataset": dataset,
            "metrics": ["exact_match"],
            "config": {
                "run_name": "baseline",
                "task_name": "support-rag",
                "max_concurrency": 4,
            },
            "metadata": {"prompt_version": "v1"},
            "output_path": "qym_results/baseline.csv",
        },
        {
            "name": "candidate",
            "display_name": "Candidate Prompt",
            "task": candidate_task,
            "dataset": dataset,
            "metrics": ["exact_match", "relevance"],
            "config": {
                "run_name": "candidate",
                "task_name": "support-rag",
                "max_concurrency": 4,
            },
            "metadata": {"prompt_version": "v2"},
            "output_path": "qym_results/candidate.csv",
        },
    ],
    show_tui=False,
    max_parallel_runs=2,
)
```

Each run spec has this shape:

```python
{
    "name": "required-stable-run-key",
    "display_name": "optional human label",
    "task": callable_or_adapter,
    "dataset": "langfuse-dataset-name or dataset object",
    "metrics": ["metric_name", custom_metric],
    "config": {"run_name": "optional", "max_concurrency": 4},
    "metadata": {"optional": "non-secret labels"},
    "output_path": "optional/file.csv",
}
```

For `Evaluator.run_parallel(...)`, pass `observer=ProgressCallbackObserver(on_progress)` if you need progress snapshots. For a normal `Evaluator(...).run()`, you can use either `progress_callback=on_progress` or `observer=ProgressCallbackObserver(on_progress)`. The `progress_callback=` shortcut exists on `Evaluator(...)`, not on `run_parallel(...)`.

## Input Shapes

### Evaluator Constructor

`Evaluator(...)` accepts:

```python
Evaluator(
    task=my_task,
    dataset=my_dataset,
    metrics=["exact_match"],
    config={"max_concurrency": 4},
    observer=None,
    model=None,
    langfuse_client=None,
    progress_callback=None,
)
```

| Argument | Type | Required | Shape |
| --- | --- | --- | --- |
| `task` | `Any` | Yes | Callable or supported framework object. |
| `dataset` | `str` or dataset object | Yes | Langfuse dataset name, `CsvDataset`, or object with `get_items()`. |
| `metrics` | `list[str or Callable]` | Yes | Built-in metric names and/or metric callables. |
| `config` | `dict` or `EvaluatorConfig` | No | Run config fields described below. |
| `observer` | `EvaluationObserver` | No | Advanced lifecycle hook object. |
| `model` | `str` or `Sequence[str]` | No | Single model label or multi-model list. |
| `langfuse_client` | `Any` | No | Injected Langfuse client for Langfuse datasets. |
| `progress_callback` | `Callable[[ProgressSnapshot], None]` | No | Simple progress event callback. |

### Dataset Item Shape

Every dataset item should resolve to:

```python
{
    "id": "qa-001",
    "input": "What is qym?",
    "expected_output": "An evaluation framework",
    "metadata": {
        "domain": "docs",
        "difficulty": "easy"
    },
}
```

Field meanings:

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | Recommended | Stable item identity for resume, comparison, review, and artifact rows. |
| `input` | Yes | Value passed into your task function. Can be scalar, dict, list, number, boolean, or string. |
| `expected_output` | Metric-dependent | Reference answer or target behavior. Deterministic metrics usually need it. |
| `metadata` | Optional | Non-secret tags used for filtering, grouping, debugging, and platform analysis. |

### CSV Dataset Shape

Use `CsvDataset` when data lives in a local CSV.

```python
from qym import CsvDataset

dataset = CsvDataset(
    "datasets/qa.csv",
    input_col="question",
    expected_col="answer",
    id_col="id",
    metadata_cols=["domain", "difficulty"],
)
```

Example CSV:

```csv
id,question,answer,domain,difficulty
qa-001,What is qym?,An evaluation framework,docs,easy
qa-002,What is 2+2?,4,math,easy
```

`CsvDataset` parses cells that start with `{` or `[` as JSON. This lets you pass structured input into the task.

```csv
id,input,expected_output,difficulty
case-1,"{""question"": ""What is qym?"", ""context"": ""LLM eval""}","An evaluation framework",easy
```

### Task Function Shape

The task is the code being evaluated. It receives the item input and returns the output to score.

Scalar input:

```python
def task(question: str) -> str:
    return call_llm(question)
```

Structured input:

```python
def task(question: str, context: str) -> str:
    return call_llm(f"Context: {context}\nQuestion: {question}")
```

Async task:

```python
async def task(question: str, model_name: str = "gpt-4o-mini") -> str:
    return await call_llm_async(model=model_name, prompt=question)
```

Optional task parameters qym may provide when your function accepts them:

| Parameter | Meaning |
| --- | --- |
| `model_name` | Current model label or provider-prefixed model ID for model-routed runs. |
| `model` | Alias for model-aware task functions. |
| `trace_id` | Trace context when available. |

### Metric Shape

Metrics can be built-in names:

```python
metrics=["exact_match", "contains", "fuzzy_match"]
```

Or custom callables:

```python
def has_citation(output, expected=None, input_data=None):
    passed = "[" in str(output) and "]" in str(output)
    return {
        "score": 1.0 if passed else 0.0,
        "label": "pass" if passed else "fail",
        "explanation": "Output includes a bracketed citation" if passed else "Missing citation",
        "metadata": {"checked": "citation"},
    }


metrics=[has_citation]
```

Metric call signatures can be:

```python
def metric(output): ...
def metric(output, expected): ...
def metric(output, expected, input_data): ...
def metric(output=None, expected=None, input_data=None): ...
```

Metric return values can be:

| Return value | Meaning |
| --- | --- |
| `bool` | Converted to `1.0` or `0.0`. |
| `int` or `float` | Used as the numeric score. |
| `dict` | Recommended rich shape with `score`, `label`, `explanation`, and `metadata`. |
| `MetricResult` | Structured metric result object. |

Recommended rich metric result:

```python
{
    "score": 0.82,
    "label": "pass",
    "explanation": "Answer is semantically correct but omits one detail.",
    "metadata": {
        "threshold": 0.8,
        "judge_model": "gpt-4o-mini"
    },
}
```

## Output Shapes

### Single-Run Return Value

For a single run:

```python
result = Evaluator(...).run(show_tui=False)
```

`result` is an `EvaluationResult`.

Common fields and properties:

| Field | Shape | Meaning |
| --- | --- | --- |
| `dataset_name` | `str` | Dataset name recorded for the run. |
| `run_name` | `str` | Run identifier used in artifacts and platform records. |
| `metrics` | `list[str]` | Metric names used for scoring. |
| `run_metadata` | `dict` | Non-secret run metadata, plus SDK-discovered metadata. |
| `run_config` | `dict` | Run config recorded with artifacts. |
| `start_time` | `datetime` | Run start time. |
| `end_time` | optional `datetime` | Run completion time. |
| `last_saved_path` | optional `str` | Last artifact path written by qym. |
| `langfuse_url` | optional `str` | Langfuse dataset run URL when available. |
| `inputs` | `dict[item_id, Any]` | Input values by item ID. |
| `metadatas` | `dict[item_id, dict]` | Item metadata by item ID. |
| `results` | `dict[item_id, dict]` | Successful item results by item ID. |
| `errors` | `dict[item_id, dict]` | Failed item details by item ID. |
| `total_items` | `int` | Number of completed plus failed items. |
| `success_rate` | `float` | Successful item ratio from `0.0` to `1.0`. |
| `duration` | optional `float` | Run duration in seconds. |

### `EvaluationResult.to_dict()`

Use `to_dict()` when your integration needs a JSON-like result payload.

```python
payload = result.to_dict()
```

Shape:

```json
{
  "dataset_name": "qa.csv",
  "run_name": "qa-smoke",
  "start_time": "2026-04-30T10:00:00.000000",
  "end_time": "2026-04-30T10:00:12.000000",
  "duration": 12.0,
  "total_items": 2,
  "success_rate": 1.0,
  "metrics": ["exact_match"],
  "metric_stats": {
    "exact_match": {
      "mean": 1.0,
      "std": 0.0,
      "min": 1.0,
      "max": 1.0,
      "success_rate": 1.0
    }
  },
  "langfuse_url": null,
  "inputs": {
    "qa-001": "What is qym?"
  },
  "metadatas": {
    "qa-001": {"domain": "docs"}
  },
  "results": {
    "qa-001": {
      "input": "What is qym?",
      "output": "An evaluation framework",
      "expected": "An evaluation framework",
      "scores": {
        "exact_match": true
      },
      "time": 0.41,
      "task_started_at_ms": 1777532400000,
      "trace_id": "trace-id",
      "trace_url": "https://..."
    }
  },
  "errors": {}
}
```

The exact item result fields can include timing and tracing fields such as `trace_id`, `trace_url`, and `task_started_at_ms`. Rich metric returns are stored under `scores`.

### Per-Item Success Shape

A successful item result usually looks like:

```json
{
  "input": "What is qym?",
  "output": "An evaluation framework",
  "expected": "An evaluation framework",
  "scores": {
    "exact_match": true,
    "relevance": {
      "score": 0.93,
      "label": "pass",
      "explanation": "Answer is relevant.",
      "metadata": {"judge_model": "gpt-4o-mini"}
    }
  },
  "time": 0.412,
  "task_started_at_ms": 1777532400000,
  "trace_id": "trace-id",
  "trace_url": "https://..."
}
```

### Per-Item Error Shape

Failed items are stored in `result.errors`.

```json
{
  "qa-009": {
    "error": "TaskExecutionTimeoutError: task timed out",
    "trace_id": "trace-id",
    "task_started_at_ms": 1777532400000,
    "time": 300.0
  }
}
```

### Saved Artifacts

`run(auto_save=True)` saves artifacts under `qym_results/` by default.

```python
path = result.last_saved_path
json_path = result.save(format="json")
csv_path = result.save(format="csv")
xlsx_path = result.save(format="xlsx")
```

CSV and XLSX artifacts include:

| Column | Meaning |
| --- | --- |
| `dataset_name` | Dataset name. |
| `run_name` | Run name. |
| `run_metadata` | JSON-encoded run metadata. |
| `run_config` | JSON-encoded run config. |
| `trace_id` | Trace identifier when available. |
| `item_id` | Dataset item ID. |
| `input` | Item input. |
| `item_metadata` | JSON or string item metadata. |
| `output` | Task output or error marker. |
| `expected_output` | Reference answer. |
| `time` | Task latency in seconds. |
| `task_started_at_ms` | Task start timestamp in milliseconds. |
| `<metric>_score` | Main metric score. |
| `<metric>__meta__<key>` | Flattened metric metadata fields. |

## Group Run Analysis

Use SDK group analysis when you have multiple `EvaluationResult` objects and want the same group metrics the platform dashboard shows: `Pass@K`, `Pass^K`, `Avg@K`, `Max@K`, consistency, and reliability.

This works directly with results returned by multi-model or multi-run SDK calls.

```python
from qym import Evaluator, analyze_group_runs, compare_group_runs


baseline_results = Evaluator(
    task=baseline_task,
    dataset=dataset,
    metrics=["accuracy"],
    model=["model-a", "model-b", "model-c"],
).run(show_tui=False)

candidate_results = Evaluator(
    task=candidate_task,
    dataset=dataset,
    metrics=["accuracy"],
    model=["model-a", "model-b", "model-c"],
).run(show_tui=False)

baseline_summary = analyze_group_runs(
    baseline_results,
    metric="accuracy",
    threshold=0.8,
)

comparison = compare_group_runs(
    baseline_results,
    candidate_results,
    metric="accuracy",
    threshold=0.8,
)
```

`analyze_group_runs(...)` returns item-level group metrics over the union of item IDs across the runs. Missing or null scores are excluded for that item. Error rows score as `0`.

```json
{
  "metric": "accuracy",
  "threshold": 0.8,
  "k": 3,
  "total_items": 100,
  "total_score_count": 300,
  "pass_at_k": 0.91,
  "pass_hat_k": 0.68,
  "avg_at_k": 0.77,
  "max_at_k": 0.93,
  "consistency": 0.84,
  "reliability": 0.72,
  "failed_count": 2,
  "items": []
}
```

`compare_group_runs(...)` uses stricter cohort comparison semantics. An item is eligible only when every run on both sides has a non-null score for that item.

```json
{
  "eligible_items": 100,
  "left_run_count": 3,
  "right_run_count": 3,
  "left": {
    "pass_at_k": 0.88,
    "pass_hat_k": 0.62,
    "avg_at_k": 0.74,
    "consistency": 0.81,
    "reliability": 0.70
  },
  "right": {
    "pass_at_k": 0.93,
    "pass_hat_k": 0.66,
    "avg_at_k": 0.79,
    "consistency": 0.86,
    "reliability": 0.75
  },
  "deltas": {
    "pass_at_k": 0.05,
    "avg_at_k": 0.05,
    "consistency": 0.05,
    "reliability": 0.05
  },
  "buckets": {
    "a_sweeps_b": {"count": 0, "percentage": 0.0, "item_ids": []},
    "b_sweeps_a": {"count": 0, "percentage": 0.0, "item_ids": []},
    "both_pass": {"count": 0, "percentage": 0.0, "item_ids": []},
    "both_fail": {"count": 0, "percentage": 0.0, "item_ids": []}
  }
}
```

Metric definitions:

| Metric | Meaning |
| --- | --- |
| `pass_at_k` | Fraction of items where at least one run passes `score >= threshold`. |
| `pass_hat_k` | Fraction of items where all included runs pass. |
| `avg_at_k` | Mean over all included item-run scores. |
| `max_at_k` | Mean of the best score per item. |
| `consistency` | Average pass/fail agreement for items with more than one score: `2 * max(pass_count, fail_count) / score_count - 1`. |
| `reliability` | Average pass frequency for items that can be solved: `pass_count / score_count`, only for items with at least one passing run. |

These SDK formulas follow the platform dashboard's shared metrics utility. Use stable dataset item IDs, especially for CSV datasets, so runs align by item identity instead of accidental row position.

## Live Progress Events

Progress events are local SDK events for your wrapper. They are different from platform streaming.

Use `progress_callback` for most integrations:

```python
from qym import Evaluator, ProgressSnapshot


def on_progress(snapshot: ProgressSnapshot) -> None:
    publish_status(
        run_id=snapshot.run_id,
        event=snapshot.event,
        finished=snapshot.finished,
        total=snapshot.total_items,
        failed=snapshot.failed,
        percent=snapshot.percent_complete,
    )


result = Evaluator(
    task=my_task,
    dataset=dataset,
    metrics=["exact_match"],
    progress_callback=on_progress,
).run(show_tui=False)
```

### ProgressSnapshot Shape

`ProgressSnapshot` has this shape:

```python
ProgressSnapshot(
    run_id="qa-smoke",
    event="item_complete",
    total_items=100,
    completed=42,
    failed=1,
    in_progress=4,
    pending=53,
    metrics=["exact_match", "relevance"],
    item_index=41,
    metric_name=None,
    score=None,
    error=None,
    message=None,
    payload=None,
    metadata=None,
    result={},
    run_info={},
    run_matrix=None,
    total_runs=0,
    result_summary=None,
)
```

Computed properties:

| Property | Meaning |
| --- | --- |
| `finished` | `completed + failed`. |
| `percent_complete` | `finished / total_items * 100`, or `0.0` when total is unknown. |

Common fields:

| Field | Event use | Meaning |
| --- | --- | --- |
| `run_id` | All events | qym run identifier, or matrix ID for `run_matrix`. |
| `event` | All events | Event name. |
| `total_items` | Run and item events | Dataset item count when known. |
| `completed` | Item and run events | Successful item count. |
| `failed` | Item and run events | Failed item count. |
| `in_progress` | Item events | Items currently running. |
| `pending` | Item events | Items not started yet. |
| `metrics` | Run and metric events | Metric names for the run. |
| `item_index` | Item and metric events | Zero-based dataset item index. |
| `metric_name` | `metric_result` | Metric that just finished. |
| `score` | `metric_result` | Raw metric return value. |
| `error` | `item_error` | Error string for a failed item. |
| `message` | `warning` | Warning message. |
| `payload` | `item_start` | Item start payload. |
| `metadata` | `metric_result` | Metric timing and status metadata. |
| `result` | `item_complete` | Output, scores, latency, retry, and trace details. |
| `run_info` | `run_start` and later | Run metadata and platform URLs when available. |
| `run_matrix` | `run_matrix` | Planned rows for multi-model or multi-run evaluations. |
| `total_runs` | `run_matrix` | Number of planned runs. |
| `result_summary` | `run_complete` | Final run summary. |

### Event Lifecycle

Typical single-run event sequence:

```text
run_start
item_start
metric_result
item_complete
...
run_complete
```

If an item fails:

```text
item_start
item_error
```

If qym detects an integration problem:

```text
warning
```

For multi-model and multi-run evaluations, qym first emits:

```text
run_matrix
run_start
...
```

### `run_matrix` Event Shape

`run_matrix` tells wrappers the full planned run shape before individual runs start.

```json
{
  "event": "run_matrix",
  "run_id": "matrix-id",
  "total_runs": 2,
  "run_matrix": [
    {
      "run_id": "qa-gpt-4o-mini-260430-1000",
      "name": "qa-gpt-4o-mini-260430-1000",
      "display_name": "qa [gpt-4o-mini]",
      "task": "answer-question",
      "dataset": "qa.csv",
      "model": "gpt-4o-mini",
      "metrics": ["exact_match"],
      "total_items": 100,
      "status": "pending",
      "platform_run_id": null,
      "qym_url": null
    }
  ]
}
```

Use this event to create pending rows in your own UI. Platform URLs are usually `null` here because the platform run is created when the individual run starts.

### `run_start` Event Shape

`run_start` initializes a specific run.

```json
{
  "event": "run_start",
  "run_id": "qa-smoke",
  "total_items": 100,
  "completed": 0,
  "failed": 0,
  "metrics": ["exact_match"],
  "run_info": {
    "dataset_name": "qa.csv",
    "run_name": "qa-smoke",
    "model": "gpt-4o-mini",
    "version": "0.9.0",
    "git_sha": "abc123",
    "git_branch": "main",
    "metric_names": ["exact_match"],
    "qym_url": "https://qym.example.com/runs/...",
    "html_url": "https://qym.example.com/runs/...",
    "platform_run_id": "platform-run-id",
    "resume_completed": 0,
    "resume_failed": 0,
    "trace": {
      "destinations": {
        "phoenix": false,
        "langfuse": false,
        "platform": true
      },
      "instrumentors": []
    }
  }
}
```

When platform streaming is enabled, `run_info` includes `qym_url`, `html_url`, and `platform_run_id`.

### `item_start` Event Shape

```json
{
  "event": "item_start",
  "run_id": "qa-smoke",
  "item_index": 0,
  "payload": {
    "input": "What is qym?",
    "expected": "An evaluation framework"
  },
  "completed": 0,
  "failed": 0,
  "in_progress": 1,
  "pending": 99
}
```

### `metric_result` Event Shape

```json
{
  "event": "metric_result",
  "run_id": "qa-smoke",
  "item_index": 0,
  "metric_name": "exact_match",
  "score": {
    "score": 1.0,
    "label": "pass",
    "metadata": {}
  },
  "metadata": {
    "input": "What is qym?",
    "expected": "An evaluation framework",
    "duration_ms": 12.4,
    "duration_seconds": 0.0124,
    "started_at_ms": 1777532400000,
    "completed_at_ms": 1777532400012,
    "status": "completed"
  }
}
```

Metric `metadata.status` can be `completed`, `timeout`, or `error`.

### `item_complete` Event Shape

```json
{
  "event": "item_complete",
  "run_id": "qa-smoke",
  "item_index": 0,
  "completed": 1,
  "failed": 0,
  "result": {
    "output": "An evaluation framework",
    "scores": {
      "exact_match": true
    },
    "task_time": 0.412,
    "task_time_ms": 412.0,
    "time": 0.412,
    "latency_ms": 412.0,
    "item_time": 0.430,
    "item_time_ms": 430.0,
    "total_time": 0.430,
    "total_time_ms": 430.0,
    "task_started_at_ms": 1777532400000,
    "task_completed_at_ms": 1777532400412,
    "item_started_at_ms": 1777532399990,
    "item_completed_at_ms": 1777532400430,
    "trace_id": "trace-id",
    "trace_url": "https://...",
    "retry_count": 0
  }
}
```

Use `task_time_ms` for model/task latency and `total_time_ms` for total item latency including metric work.

### `item_error` Event Shape

```json
{
  "event": "item_error",
  "run_id": "qa-smoke",
  "item_index": 8,
  "completed": 7,
  "failed": 1,
  "error": "TaskExecutionTimeoutError: task timed out"
}
```

### `warning` Event Shape

```json
{
  "event": "warning",
  "run_id": "qa-smoke",
  "message": "Async metric 'judge' appears to block the event loop..."
}
```

### `run_complete` Event Shape

```json
{
  "event": "run_complete",
  "run_id": "qa-smoke",
  "completed": 98,
  "failed": 2,
  "total_items": 100,
  "result_summary": {
    "success_rate": 0.98,
    "total_items": 100,
    "metrics": ["exact_match"],
    "run_metadata": {
      "task_name": "answer-question",
      "prompt_version": "v3"
    }
  }
}
```

## Observer Integration

`progress_callback` is easiest when you want one function that receives `ProgressSnapshot` events.

Use `EvaluationObserver` when you want named lifecycle hooks.

```python
from qym import EvaluationObserver, Evaluator


class JobObserver(EvaluationObserver):
    def on_run_matrix(self, matrix_id, runs, total_runs):
        jobs.create_matrix(matrix_id=matrix_id, runs=runs, total_runs=total_runs)

    def on_run_start(self, run_id, run_info, total_items, metrics):
        jobs.mark_running(
            run_id=run_id,
            total_items=total_items,
            metrics=metrics,
            qym_url=run_info.get("qym_url"),
            platform_run_id=run_info.get("platform_run_id"),
        )

    def on_item_start(self, run_id, item_index, payload=None):
        jobs.mark_item_running(run_id, item_index, payload)

    def on_metric_result(self, run_id, item_index, metric_name, score, metadata=None):
        jobs.record_metric(run_id, item_index, metric_name, score, metadata)

    def on_item_complete(self, run_id, item_index, result):
        jobs.record_item_result(run_id, item_index, result)

    def on_item_error(self, run_id, item_index, error):
        jobs.record_item_error(run_id, item_index, error)

    def on_warning(self, run_id, message):
        jobs.record_warning(run_id, message)

    def on_run_complete(self, run_id, result_summary):
        jobs.mark_complete(run_id, result_summary)


result = Evaluator(
    task=my_task,
    dataset=dataset,
    metrics=["exact_match"],
    observer=JobObserver(),
).run(show_tui=False)
```

Observer hook signatures:

| Hook | Signature | When it fires |
| --- | --- | --- |
| `on_run_matrix` | `(matrix_id, runs, total_runs)` | Multi-model or multi-run shape is known. |
| `on_run_start` | `(run_id, run_info, total_items, metrics)` | A run is starting. |
| `on_item_start` | `(run_id, item_index, payload=None)` | An item begins processing. |
| `on_metric_result` | `(run_id, item_index, metric_name, score, metadata=None)` | A metric finishes for an item. |
| `on_item_complete` | `(run_id, item_index, result)` | An item completes successfully. |
| `on_item_error` | `(run_id, item_index, error)` | An item fails. |
| `on_warning` | `(run_id, message)` | qym detects a warning. |
| `on_run_complete` | `(run_id, result_summary)` | A run finishes. |

Observer rules for reliable integrations:

- Keep callbacks fast. If publishing to another service can block, enqueue work and return.
- Treat progress as status, not the durable source of evaluation results.
- Store final evidence from `EvaluationResult` or saved artifacts.
- Do not put secrets in progress payloads, run metadata, item metadata, or callback logs.
- Use `show_tui=False` when your wrapper owns progress display.

## Platform Streaming

Platform streaming is separate from local progress callbacks.

Set platform credentials when the run should appear in the shared qym dashboard:

```bash
export QYM_BASE_URL=https://qym.example.com
export QYM_API_KEY=<platform-api-key>
```

Or pass them in config when embedding qym in a service:

```python
result = Evaluator(
    task=my_task,
    dataset=dataset,
    metrics=["exact_match"],
    config={
        "platform_url": "https://qym.example.com",
        "platform_api_key": platform_api_key,
    },
    progress_callback=on_progress,
).run(show_tui=False)
```

Use both features when needed:

| Need | Use |
| --- | --- |
| Shared qym dashboard, review UI, platform item rows, platform comparison | Platform streaming. |
| Your service job table, websocket, queue status, notebook cell, CI annotations | `progress_callback` or `EvaluationObserver`. |

When streaming is enabled, the SDK creates a platform run and sends run, item, metric, trace, heartbeat, metadata, and completion events. The local SDK still returns `EvaluationResult` and writes artifacts.

## Run Configs

Pass run config as either a dict:

```python
config = {
    "run_name": "nightly-support-rag",
    "task_name": "support-rag",
    "max_concurrency": 8,
    "max_metric_concurrency": 2,
    "timeout": 300,
    "metric_timeout": 90,
    "max_retries": 2,
    "output_dir": "qym_results/nightly",
    "run_metadata": {
        "owner": "evals",
        "prompt_version": "v12",
        "dataset_version": "2026-04-30",
    },
}
```

Or as an `EvaluatorConfig`:

```python
from qym.core.config import EvaluatorConfig

config = EvaluatorConfig(
    run_name="nightly-support-rag",
    task_name="support-rag",
    max_concurrency=8,
    timeout=300,
    max_retries=2,
    run_metadata={"prompt_version": "v12"},
)
```

### Identity And Metadata

| Field | Type | Default | Use |
| --- | --- | --- | --- |
| `run_name` | optional `str` | `None` | Human-readable run name for artifacts and platform runs. |
| `task_name` | optional `str` | Auto-derived | Stable task identity when code moves or functions are renamed. |
| `run_metadata` | `dict` | `{}` | Non-secret labels such as job ID, owner, prompt version, dataset version, release. |
| `git_branch` | optional `str` | Auto-detected | Override branch metadata, useful in CI. |
| `git_commit` | optional `str` | Auto-detected | Override commit SHA metadata, useful in detached HEAD states. |

Recommended metadata:

```python
"run_metadata": {
    "owner": "search-team",
    "job_id": "eval-123",
    "prompt_version": "support-rag-v12",
    "dataset_version": "support-regression-2026-04-30",
    "release": "2026.04.30",
}
```

Do not put API keys, prompts with secrets, customer PII, or credentials in `run_metadata`.

### Execution Controls

| Field | Type | Default | Use |
| --- | --- | --- | --- |
| `max_concurrency` | `int` | `10` | Concurrent dataset item executions. Lower for provider rate limits. |
| `max_metric_concurrency` | `int` | `1` | Concurrent metrics per item. Raise carefully for judge metrics. |
| `timeout` | optional `float` | `300` | Wall-clock task timeout per item in seconds. |
| `metric_timeout` | optional `float` | `60.0` | Wall-clock timeout per metric call in seconds. |
| `max_retries` | `int` | `2` | Task retries after failure. |
| `interrupt_grace_seconds` | `float` | `2.0` | Grace period for interruption cleanup and final platform status. |

Start small for provider-backed tasks:

```python
"max_concurrency": 2,
"max_metric_concurrency": 1,
"timeout": 120,
"metric_timeout": 60,
"max_retries": 0,
```

Then scale after the task, dataset, and metrics are stable.

### Output And Recovery

| Field | Type | Default | Use |
| --- | --- | --- | --- |
| `output_dir` | `str` | `"qym_results"` | Base directory for saved artifacts and checkpoints. |
| `checkpoint_enabled` | `bool` | `True` | Incrementally write checkpoint rows during a run. |
| `checkpoint_format` | `str` | `"csv"` | Checkpoint serialization format. |
| `checkpoint_flush_each_item` | `bool` | `True` | Flush checkpoint after each item. |
| `checkpoint_fsync` | `bool` | `False` | Force filesystem sync for high-value long runs. |
| `resume_from` | optional `str` | `None` | Resume from checkpoint or saved result file. |
| `resume_rerun_errors` | `bool` | `False` | Rerun errored rows instead of preserving previous failures. |

Long-running service config:

```python
"checkpoint_enabled": True,
"checkpoint_flush_each_item": True,
"output_dir": "qym_results/nightly",
```

Resume config:

```python
"resume_from": "qym_results/support-rag/gpt-4o-mini/2026-04-30/run.csv",
"resume_rerun_errors": True,
```

### Model Routing

| Field | Type | Default | Use |
| --- | --- | --- | --- |
| `model` | optional `str` | `None` | Single model label. Also available through `Evaluator(model="...")`. |
| `models` | optional `list[str]` | `None` | Multi-model list. Also available through `Evaluator(model=[...])`. |
| `model_full` | optional `str` | `None` | Provider-prefixed model ID when display and API names differ. |
| `force_model_override` | `bool` | `False` | Replace hardcoded OpenAI chat completion model at the SDK boundary. Use deliberately. |

Use constructor-level `model` for the common path:

```python
Evaluator(
    task=task,
    dataset=dataset,
    metrics=["exact_match"],
    model=["openai/gpt-4o-mini", "qwen/qwen3.5-397b"],
)
```

qym stores stripped display names for platform display while preserving provider-prefixed names for task routing where supported.

### Platform connection fields

| Field | Type | Default | Use |
| --- | --- | --- | --- |
| `platform_url` | optional `str` | Env | qym platform base URL. |
| `platform_api_key` | optional `str` | Env | Platform API key. Prefer environment variables for secrets. |
| `platform_timeout` | `float` | `5.0` | HTTP timeout for platform calls. |
| `live_mode` | `str` | `"platform"` | Streaming policy. `platform` is the default; `local` opts out. |

Preferred service pattern:

```python
"platform_url": os.environ["QYM_BASE_URL"],
"platform_api_key": os.environ["QYM_API_KEY"],
```

### Tracing

| Field | Type | Default | Use |
| --- | --- | --- | --- |
| `otel_enabled` | `bool` | `True` | Enable OpenTelemetry auto-instrumentation when installed. |
| `phoenix_enabled` | `bool` | `False` | Export traces to Phoenix. |
| `phoenix_endpoint` | optional `str` | Env | Phoenix collector endpoint. |

### Langfuse

| Field | Type | Default | Use |
| --- | --- | --- | --- |
| `langfuse_public_key` | optional `str` | Env | Langfuse public key override. |
| `langfuse_secret_key` | optional `str` | Env | Langfuse secret key override. |
| `langfuse_host` | optional `str` | Env | Langfuse host override. |
| `langfuse_project_id` | optional `str` | Env | Project ID for URL construction and trace links. |

You only need Langfuse credentials when `dataset` is a Langfuse dataset name or when your workflow depends on Langfuse trace links. `CsvDataset` does not require Langfuse.

### UI And CLI Metadata

| Field | Type | Default | Use |
| --- | --- | --- | --- |
| `ui_port` | `int` | `0` | Local UI port. `0` chooses automatically. |
| `cli_invocation` | optional `str` | CLI-set | Records the command used to launch the run. |

## Complete Service Wrapper Example

This example shows a realistic service integration: local job progress, platform visibility, durable artifacts, and non-secret run metadata.

```python
import os
from qym import CsvDataset, Evaluator, ProgressSnapshot


def launch_eval(job):
    dataset = CsvDataset(
        job.dataset_path,
        input_col="question",
        expected_col="answer",
        id_col="id",
        metadata_cols=["domain", "difficulty"],
    )

    def on_progress(snapshot: ProgressSnapshot) -> None:
        if snapshot.event == "run_matrix":
            for row in snapshot.run_matrix or []:
                jobs.create_pending_child(job.id, row)
            return

        update = {
            "qym_run_id": snapshot.run_id,
            "event": snapshot.event,
            "finished": snapshot.finished,
            "completed": snapshot.completed,
            "failed": snapshot.failed,
            "total": snapshot.total_items,
            "percent": snapshot.percent_complete,
        }

        if snapshot.event == "run_start":
            update["qym_url"] = (snapshot.run_info or {}).get("qym_url")
            update["platform_run_id"] = (snapshot.run_info or {}).get("platform_run_id")

        if snapshot.event == "item_complete":
            update["last_item_ms"] = (snapshot.result or {}).get("total_time_ms")

        jobs.update(job.id, **update)

    result = Evaluator(
        task=job.task,
        dataset=dataset,
        metrics=["exact_match", "relevance"],
        model=job.models,
        config={
            "run_name": job.name,
            "task_name": job.task_name,
            "max_concurrency": job.max_concurrency,
            "max_metric_concurrency": 1,
            "timeout": 300,
            "metric_timeout": 90,
            "max_retries": 2,
            "output_dir": "qym_results/jobs",
            "platform_url": os.environ.get("QYM_BASE_URL"),
            "platform_api_key": os.environ.get("QYM_API_KEY"),
            "run_metadata": {
                "job_id": job.id,
                "owner": job.owner,
                "prompt_version": job.prompt_version,
                "dataset_version": job.dataset_version,
            },
        },
        progress_callback=on_progress,
    ).run(show_tui=False, max_parallel_runs=job.max_parallel_runs)

    jobs.finish(
        job.id,
        result_count=len(result) if isinstance(result, list) else 1,
        artifact_paths=[
            r.last_saved_path for r in result
        ] if isinstance(result, list) else [result.last_saved_path],
    )
    return result
```

## Integration Checklist

1. Prove the task works on a tiny CSV with `show_tui=False`.
2. Add one deterministic metric before adding judge metrics.
3. Give every dataset row a stable ID.
4. Add `task_name`, `run_name`, and non-secret `run_metadata`.
5. Start with low concurrency and scale from evidence.
6. Keep checkpoints enabled for long runs.
7. Use `progress_callback` or `EvaluationObserver` for your own job state.
8. Use platform credentials when shared qym dashboard visibility is required.
9. Read final evidence from `EvaluationResult` or saved artifacts, not from progress events alone.
10. Keep secrets out of metadata, progress logs, dataset metadata, and artifacts.

## Related Docs

- [Python API](docs_portal/docs/sdk/python-api.mdx)
- [SDK Configuration](docs_portal/docs/sdk/configuration.mdx)
- [Dataset Authoring](docs_portal/docs/sdk/dataset-authoring.mdx)
- [Progress, Observers, And Wrappers](docs_portal/docs/sdk/progress-observers-wrappers.mdx)
- [Platform Streaming](docs_portal/docs/sdk/platform-streaming.mdx)
- [Run Artifacts](docs_portal/docs/sdk/run-artifacts.mdx)
