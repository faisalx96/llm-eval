# Auto-Instrumentation Guide

Automatically capture every LLM call, tool use, and timing detail inside your evaluation tasks — without changing a single line of your task code.

## Table of Contents

1. [What Is Auto-Instrumentation?](#1-what-is-auto-instrumentation)
2. [Setup](#2-setup)
3. [What Gets Captured](#3-what-gets-captured)
4. [How It Works](#4-how-it-works)
5. [Viewing Your Traces](#5-viewing-your-traces)
6. [Supported Providers & Frameworks](#6-supported-providers--frameworks)
7. [Working With Agents & Multi-Step Tasks](#7-working-with-agents--multi-step-tasks)
8. [Passing Your Own Trace ID](#8-passing-your-own-trace-id)
9. [What Is NOT Captured](#9-what-is-not-captured)
10. [Configuration](#10-configuration)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. What Is Auto-Instrumentation?

When you run an evaluation, qym treats your task function as a **black box** — it passes input in and gets output back. By default, you only see the final result.

Auto-instrumentation opens that black box. It automatically detects and records:

- Every LLM API call your task makes (model, prompt, response, token count)
- Every tool/function call the LLM invokes
- How long each step took
- The full chain of calls if your task uses agents or multi-step workflows

All of this appears as a **trace** — a tree of nested spans showing exactly what happened inside your task for each evaluation item.

**You do not need to modify your task function.** The instrumentation happens at the SDK level, intercepting calls to OpenAI, Anthropic, and other providers transparently.

---

## 2. Setup

### Step 1: Install the tracing extra

```bash
pip install "qym[otel]"
```

This installs [traceloop-sdk](https://github.com/traceloop/openllmetry), which handles the automatic detection of LLM calls.

### Step 2: Set up Langfuse credentials

Traces are sent to your Langfuse instance. If you already have Langfuse configured for your datasets, you're done — the same credentials are used.

```bash
# .env
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://your-langfuse-host.com
```

### Step 3: Run your evaluation

```python
from qym import Evaluator

evaluator = Evaluator(
    task=my_task,
    dataset="my-dataset",
    metrics=["correctness"],
)
results = evaluator.run()
```

That's it. No decorators, no wrappers, no callbacks. Every LLM call inside `my_task` is automatically captured and sent to Langfuse.

---

## 3. What Gets Captured

For each evaluation item, you get a trace containing:

| What | Details |
|------|---------|
| **LLM calls** | Model name, full prompt/messages, completion response, token usage (prompt + completion), latency |
| **Tool/function calls** | Function name, arguments passed, result returned |
| **Timing** | Start time, end time, and duration of each operation |
| **Nesting** | Parent-child relationships (e.g., agent makes 3 LLM calls, each with tool calls) |
| **Errors** | If an LLM call or tool call fails, the error is captured on the span |
| **Metric scores** | Each metric evaluation appears as a child span with its score |

### Example trace structure

For a task that uses an OpenAI agent with tool calls:

```
eval-my-run-item-0                          [root span, 4.2s]
├── my_task                                 [task execution]
│   ├── openai.chat                         [LLM call, gpt-4o, 1.1s]
│   │   └── tool: search_database           [tool call, 0.3s]
│   ├── openai.chat                         [LLM call, gpt-4o, 0.8s]
│   │   └── tool: calculate_score           [tool call, 0.1s]
│   └── openai.chat                         [LLM call, gpt-4o, 0.6s]
└── eval_metrics                            [metric evaluation]
    ├── metric_correctness                  [score: 0.85]
    └── metric_completeness                 [score: 0.90]
```

---

## 4. How It Works

Auto-instrumentation uses [OpenTelemetry](https://opentelemetry.io/) — the industry standard for distributed tracing. Here's what happens when you run an evaluation:

1. **On startup**, qym activates traceloop-sdk, which patches the installed LLM SDKs (OpenAI, Anthropic, etc.) to emit tracing spans.

2. **For each evaluation item**, qym creates a root span. This span becomes the parent for everything that happens inside your task function.

3. **When your task calls an LLM**, the patched SDK automatically creates a child span under the root, capturing the full request and response.

4. **When the LLM uses tools**, those tool calls are captured as their own spans nested under the LLM call.

5. **All spans flow to Langfuse** via its span processor — no separate OTLP endpoint configuration needed.

6. **Spans are also stored locally** in the qym platform database, so you can query them via the API even without Langfuse.

The key insight: your task function runs exactly the same code it always did. The instrumentation is applied to the LLM client libraries themselves, not to your code.

### Deduplication

When both a framework instrumentor (e.g., LangChain) and a provider instrumentor (e.g., OpenAI) are active, they can both fire for the same LLM call. qym's `QymSpanProcessor` automatically **deduplicates** these spans so you never see the same call twice in your traces.

### Noise Filtering

Low-value infrastructure spans (`connect`, `dns.resolve`, `tls.handshake`) are automatically filtered out before storage to keep traces clean and focused on meaningful operations.

---

## 5. Viewing Your Traces

### In the Embedded Trace Viewer (Recommended)

The qym platform includes a **built-in trace viewer** embedded directly in run and compare pages. Click the trace icon on any item row to see the full span tree.

**What you get:**

- **Span tree** with typed SVG icons for each span kind — LLM (chat bubble), TOOL (wrench), AGENT (person), CHAIN (link), EVALUATOR (star), RETRIEVER (search), EMBED (matrix) — color-coded by type
- **Waterfall duration bars** showing each span's relative timeline position and duration
- **Tabbed detail panel** — Messages (LLM chat bubbles), Response (model/tokens/cost), Input/Output (tool args/results), Metrics, Scores, Raw attributes (syntax-highlighted JSON)
- **"Show Thinking" sections** on LLM assistant messages for reasoning content (Anthropic, DeepSeek, etc.)
- **Message enrichment** — flat OTEL attributes are reconstructed into structured chat bubbles with role, content, tool calls, and tool results
- **Red L-shaped error connectors** — error paths are immediately visible in the tree, and the first error span auto-expands on load
- **Framework noise auto-collapse** — LangChain/LangGraph internal wrapper spans (ChannelRead, ChannelWrite, RunnableLambda, routing nodes) are collapsed while preserving meaningful user-defined graph nodes
- **Keyboard navigation** — `j`/`k` or arrow keys to move, `/` to focus search, Enter/Escape to expand/collapse
- **Shareable URLs** — `?trace=itemId` query parameter for direct linking to a specific item's trace
- **Resizable panels** — drag the divider between tree and detail panel

### In Langfuse

After your evaluation completes, open your Langfuse instance and look for traces named `eval-{run_name}-item-{index}`. Each evaluation item gets its own trace.

From the qym dashboard, click the **trace link** on any item row to jump directly to its trace in Langfuse.

### Via the qym API

Query stored spans directly:

```bash
# All spans for a run
GET /api/runs/{run_id}/spans

# Spans for a specific item
GET /api/runs/{run_id}/items/{item_id}/spans

# Full trace with summary (span count, error count, duration)
GET /api/runs/{run_id}/items/{item_id}/trace
```

Response:

```json
{
  "spans": [
    {
      "trace_id": "abc123...",
      "span_id": "def456...",
      "parent_span_id": null,
      "name": "eval-my-run-item-0",
      "duration_ms": 4200.5,
      "status": "OK",
      "attributes": {
        "gen_ai.request.model": "gpt-4o",
        "gen_ai.usage.prompt_tokens": 150,
        "gen_ai.usage.completion_tokens": 80
      }
    }
  ]
}
```

---

## 6. Supported Providers & Frameworks

### LLM Providers

Auto-instrumentation works with these providers out of the box — if you have their SDK installed, calls are captured automatically:

| Provider | SDK | Captured |
|----------|-----|----------|
| OpenAI | `openai` | Model, messages, completion, tokens, tool calls |
| Anthropic | `anthropic` | Model, messages, completion, tokens, tool use |
| Azure OpenAI | `openai` (Azure config) | Same as OpenAI |
| AWS Bedrock | `boto3` | Model, prompt, response |
| Google Generative AI | `google-generativeai` | Model, prompt, response |
| Google Vertex AI | `google-cloud-aiplatform` | Model, prompt, response |
| Cohere | `cohere` | Model, prompt, response |
| Mistral AI | `mistralai` | Model, messages, response |
| Groq | `groq` | Model, messages, response |
| Ollama | `ollama` | Model, prompt, response |
| HuggingFace | `huggingface_hub` | Model, prompt, response |
| Replicate | `replicate` | Model, prompt, response |
| Together AI | `together` | Model, prompt, response |
| IBM Watsonx | `ibm-watsonx-ai` | Model, prompt, response |
| Aleph Alpha | `aleph_alpha_client` | Model, prompt, response |

### Frameworks

If your task function uses a framework, the framework's internal LLM calls are also captured:

| Framework | What's captured |
|-----------|-----------------|
| LangChain | Chain/agent steps, LLM calls within chains, tool invocations |
| LangGraph | Graph node executions, LLM calls within nodes |
| LlamaIndex | Query engine calls, retrieval steps, LLM calls |
| CrewAI | Agent tasks, crew orchestration, LLM calls |
| Haystack | Pipeline components, LLM calls |
| LiteLLM | Proxied LLM calls to any provider |
| OpenAI Agents | Agent runs, tool calls, handoffs |

### Vector Databases

If your task performs retrieval, these vector DB calls are also captured:

| Vector DB | What's captured |
|-----------|-----------------|
| Pinecone | Query, upsert operations |
| Chroma | Query, add operations |
| Qdrant | Search, upsert operations |
| Weaviate | Query operations |
| Milvus | Search operations |

---

## 7. Working With Agents & Multi-Step Tasks

Auto-instrumentation works naturally with agent-based tasks — no special configuration needed.

### Simple function wrapping an agent

Most users wrap their agent logic in a plain function. This is the recommended pattern:

```python
from openai import OpenAI

client = OpenAI()

def my_agent_task(question, model="gpt-4o"):
    messages = [{"role": "user", "content": question}]
    tools = [{"type": "function", "function": {...}}]

    # Agent loop — all iterations are captured
    while True:
        response = client.chat.completions.create(
            model=model, messages=messages, tools=tools
        )
        choice = response.choices[0]
        if choice.finish_reason == "stop":
            return choice.message.content

        # Tool call handling — captured automatically
        for tc in choice.message.tool_calls:
            result = execute_tool(tc.function.name, tc.function.arguments)
            messages.append({"role": "tool", "content": result, "tool_call_id": tc.id})
```

The trace will show every iteration of the agent loop, every LLM call, and every tool execution.

### LangGraph agents

```python
from langgraph.graph import StateGraph

def my_langgraph_task(question):
    graph = build_my_graph()  # Your LangGraph setup
    result = graph.invoke({"question": question})
    return result["answer"]
```

LangGraph node executions and the LLM calls within them are all captured.

### Async tasks

Async functions work the same way:

```python
from openai import AsyncOpenAI

client = AsyncOpenAI()

async def my_async_task(question, model="gpt-4o"):
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": question}],
    )
    return response.choices[0].message.content
```

Context propagation works correctly for both sync and async tasks. qym handles this automatically.

---

## 8. Passing Your Own Trace ID

If you already have tracing in your application and want to link qym evaluation spans to your existing traces, add a `trace_id` parameter to your task function:

```python
def my_task(question, model="gpt-4o", trace_id=None):
    # trace_id is automatically injected by qym
    # You can pass it to your own observability system
    print(f"Running under trace: {trace_id}")

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": question}],
    )
    return response.choices[0].message.content
```

qym detects the `trace_id` parameter by name and injects the current trace's ID automatically. This is opt-in — if your function doesn't have a `trace_id` parameter, nothing changes.

---

## 9. What Is NOT Captured

Be aware of these limitations:

### Not captured

- **HTTP calls that aren't LLM APIs** — If your task calls a REST API, database, or web service directly (e.g., `requests.get()`), those calls are not traced. Only LLM SDK calls and supported vector DB calls are instrumented.

- **Custom Python logic** — Time spent in your own Python code (string processing, calculations, file I/O) is not broken out into separate spans. It's included in the parent span's duration but not individually visible.

- **Prompt template rendering** — If you build prompts from templates, the template logic itself isn't captured. You'll see the final rendered prompt in the LLM call span.

- **Streaming token-by-token** — The full response is captured, but individual streaming chunks are not shown as separate events. Time-to-first-token is captured if the provider SDK reports it.

### Privacy considerations

By default, **full prompt and completion content is captured** in traces. This includes any sensitive data in your evaluation dataset or LLM responses.

To disable content capture (only metadata and timing are recorded):

```bash
export TRACELOOP_TRACE_CONTENT=false
```

---

## 10. Configuration

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TRACELOOP_TRACE_CONTENT` | `true` | Set to `false` to hide prompt/completion content in traces |

### Evaluator config

```python
from qym import Evaluator
from qym.core.config import EvaluatorConfig

config = EvaluatorConfig(
    otel_enabled=True,   # Enable auto-instrumentation (default: True)
)

evaluator = Evaluator(task=my_task, dataset=ds, metrics=metrics, config=config)
```

Setting `otel_enabled=False` disables auto-instrumentation entirely. No spans are created, no LLM calls are captured. Your evaluation still runs normally.

### Disabling instrumentation for specific libraries

If a particular instrumentation is causing issues, you can block it via traceloop's configuration:

```python
from traceloop.sdk import Traceloop
from traceloop.sdk.instruments import Instruments

Traceloop.init(
    app_name="qym",
    block_instruments={Instruments.REQUESTS, Instruments.URLLIB3},
)
```

> Note: qym already blocks `REQUESTS` and `URLLIB3` by default to reduce noise from HTTP connection spans.

---

## 11. Troubleshooting

### "I don't see any traces in Langfuse"

1. **Check that traceloop-sdk is installed:**
   ```bash
   pip show traceloop-sdk
   ```
   If not installed, run `pip install "qym[otel]"`.

2. **Check your Langfuse credentials.** Traces go to the same Langfuse instance configured via `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`.

3. **Check the logs.** Look for:
   - `"OTEL auto-instrumentation initialized via traceloop-sdk"` — means it's working
   - `"traceloop-sdk not installed"` — means the extra isn't installed
   - `"Failed to initialize OTEL auto-instrumentation"` — something went wrong during setup

4. **Flush delay.** Traces are batched and sent in the background. If your script exits immediately after `evaluator.run()`, some traces may not be flushed. qym calls `flush()` automatically at the end of a run, but if you're debugging, add a short delay or call `evaluator.client.flush()` manually.

### "I see traces but no LLM call details"

- Make sure the LLM provider's SDK is installed **before** the evaluation starts. traceloop instruments libraries at import time. If you install a provider SDK mid-script, it won't be instrumented.

- Check that you're using the provider's official SDK, not a custom HTTP wrapper. Auto-instrumentation patches the SDK's client classes — if you call the API via raw `requests.post()`, it won't be captured.

### "Traces are too noisy"

If you're seeing many small spans from HTTP libraries or other non-LLM sources, set:

```bash
export TRACELOOP_TRACE_CONTENT=false
```

Or block specific instrumentations as described in [Configuration](#10-configuration).

### "I'm using a provider not in the supported list"

If your LLM provider isn't supported by traceloop, its calls won't be auto-instrumented. You have two options:

1. **Use LiteLLM** as a proxy — LiteLLM is instrumented, so any provider routed through it will be captured.
2. **Wait for support** — traceloop regularly adds new providers. Check their [supported integrations](https://www.traceloop.com/docs/openllmetry/integrations) for updates.

---

## Related Guides

- [User Guide](./USER_GUIDE.md) — Getting started with qym
- [Metrics Guide](./METRICS_GUIDE.md) — Available metrics and how to use them
- [Platform User Guide](../../../docs/PLATFORM_USER_GUIDE.md) — Dashboard features including the embedded trace viewer
