# Phoenix Tracing Integration for qym — Handoff

## Goal

Add Arize Phoenix as a pluggable tracing backend in qym, so that **any** user task function automatically gets full observability (LLM calls, tokens, cost, latency, tool calls) without writing any tracing code.

## Context

qym currently uses **Langfuse** as its only tracing/observability backend. Traces are created per evaluation item in `_evaluate_item()` via `self.client.start_span(...)` (Langfuse SDK). We want to add **Arize Phoenix** as an alternative, leveraging its OpenTelemetry-based auto-instrumentation.

### Why Phoenix is a good fit
- `phoenix.otel.register(auto_instrument=True)` automatically instruments OpenAI, Anthropic, LangChain, LlamaIndex, etc. — zero user code needed
- Uses standard OpenTelemetry, so it's vendor-neutral
- Captures tokens, cost, messages, tool calls, latency per LLM call automatically
- Parent/child span nesting works via OTel context propagation — if qym creates a parent span, all LLM calls inside the user's function nest under it automatically

### How it works today (in sql_eval, outside qym)
See `/Users/faisalbh/sql_eval/tracing.py` and `/Users/faisalbh/sql_eval/task.py` for a working reference implementation:

1. `tracing.py` calls `phoenix.otel.register(auto_instrument=True)` and gets a `tracer`
2. `task.py` wraps the task execution in `tracer.start_as_current_span("sql_agent_task", openinference_span_kind="agent")`
3. All OpenAI SDK calls inside the function automatically appear as child spans
4. Tool calls are wrapped in `tracer.start_as_current_span("tool:name", openinference_span_kind="tool")`

The user currently has to do steps 2-4 manually. The goal is for qym to do this automatically.

## What to build

### 1. Tracer abstraction

Create a pluggable tracer interface so qym can support both Langfuse and Phoenix (and potentially others). Location: `packages/sdk/qym/tracing/` or extend existing adapter pattern.

```python
# Conceptual interface
class TracingBackend:
    def create_span(self, name, input_data, metadata) -> SpanContext
    def end_span(self, span, output) -> None
    def score(self, span, name, value) -> None
```

Implementations:
- `LangfuseBackend` — wraps current `self.client.start_span(...)` logic
- `PhoenixBackend` — wraps `tracer.start_as_current_span(...)` with openinference attributes
- `NullBackend` — no-op (current `NullTrace` behavior)

### 2. Phoenix backend specifics

When Phoenix is the backend:

**Initialization** (once, before any imports):
```python
from phoenix.otel import register
tracer_provider = register(
    project_name="...",
    endpoint="http://localhost:6006/v1/traces",
    auto_instrument=True,  # THIS is the magic — instruments OpenAI/Anthropic/etc automatically
    batch=True,
)
tracer = tracer_provider.get_tracer("qym")
```

**Per-item span** (in `_evaluate_item` or `FunctionAdapter.arun`):
```python
with tracer.start_as_current_span(
    f"eval-{run_name}-item-{index}",
    openinference_span_kind="agent",  # groups all LLM calls under this
) as span:
    span.set_attribute("input.value", json.dumps(input_data))
    span.set_attribute("metadata.item_index", index)
    span.set_attribute("metadata.model", model_name)

    output = user_task_function(...)  # all OpenAI calls inside auto-traced as children

    span.set_attribute("output.value", json.dumps(output))
```

**Per-metric scoring** (after metrics run):
```python
# Phoenix uses span events or attributes for scores
span.set_attribute(f"eval.{metric_name}", score_value)
```

### 3. Where to hook in

Key files to modify:

| File | What to change |
|---|---|
| `packages/sdk/qym/core/evaluator.py` | `__init__`: detect tracing backend from config. `_evaluate_item` (line ~1276-1314): use backend to create spans instead of hardcoded Langfuse |
| `packages/sdk/qym/adapters/base.py` | `FunctionAdapter.arun` (line ~145-233): optionally wrap task call in Phoenix span |
| `packages/sdk/qym/core/evaluator.py` | Metric scoring (after line ~1328): send scores to Phoenix if that's the backend |

### 4. User-facing API

Option A — config-driven (recommended):
```python
evaluator = Evaluator(
    task=my_task,
    dataset=dataset,
    metrics=metrics,
    model="gpt-4o",
    config={
        "tracing": "phoenix",  # or "langfuse" (default) or "none"
        "phoenix_endpoint": "http://localhost:6006/v1/traces",
        "phoenix_project": "my-eval",
    },
)
```

Option B — env-driven (simpler, works with CLI too):
```
QYM_TRACER=phoenix
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006/v1/traces
PHOENIX_PROJECT=my-eval
```

### 5. Dependencies

Add as optional extras in `pyproject.toml`:
```toml
[project.optional-dependencies]
phoenix = [
    "arize-phoenix-otel>=0.10.0",
    "openinference-instrumentation-openai>=0.1.0",
]
```

Users install with `pip install qym[phoenix]`.

## Key architectural notes

- Phoenix auto-instrumentation MUST be initialized before any OpenAI/Anthropic imports. In qym, this means the tracer setup should happen early in `Evaluator.__init__` or even at import time via config.
- `auto_instrument=True` handles all the per-LLM-call tracing. qym only needs to create the **parent span** per item — everything else nests automatically via OTel context propagation.
- Langfuse and Phoenix can coexist (both use OTel under the hood), but for simplicity start with one-or-the-other.
- The sync task path (`run_in_executor`) propagates OTel context into thread pools automatically in newer versions of `opentelemetry-api`. Verify this works — if not, manually copy context with `opentelemetry.context.attach()`.

## Reference files

- Working Phoenix + sql-agent integration: `/Users/faisalbh/sql_eval/tracing.py`, `/Users/faisalbh/sql_eval/task.py`
- Current Langfuse tracing in qym: `packages/sdk/qym/core/evaluator.py` lines 1276-1330
- Task adapter (where user function is called): `packages/sdk/qym/adapters/base.py` lines 145-233
- Phoenix docs on auto-instrumentation: https://docs.arize.com/phoenix/tracing/integrations-tracing
- OpenInference semantic conventions: `openinference_span_kind` values are `"agent"`, `"chain"`, `"tool"`, `"llm"`, `"embedding"`
