# Future Phases — Phoenix-Inspired Features

Design specs for Phases 3 and 4, deferred from the initial implementation.

## Phase 3: Post-Hoc Trace Evaluation

**Goal**: Allow users to run LLM judges against existing Langfuse traces
without re-running the original task.

### Design

- New `TraceEvaluator` class that accepts a Langfuse dataset run (or list of
  trace IDs) and a set of judge metrics.
- Fetches trace spans from Langfuse API, extracts input/output/context.
- Runs judge metrics against extracted data.
- Writes scores back to Langfuse as trace scores and to the qym platform.

### Key Decisions

- Should support both batch and streaming evaluation.
- Needs a span-selector mechanism (e.g., "evaluate the last generation span").
- Must handle large traces efficiently (pagination, selective span loading).

### API Sketch

```python
from qym import TraceEvaluator
from qym.metrics.judges import faithfulness_llm

evaluator = TraceEvaluator(
    dataset_run="my-run-name",
    metrics=[faithfulness_llm()],
    span_selector="generation",  # or custom callable
)
results = evaluator.run()
```

---

## Phase 4: Multi-Agent Evaluation Framework

**Goal**: First-class support for evaluating multi-agent systems where multiple
LLM calls collaborate on a task.

### Design

- New `AgentEvaluator` that understands agent graphs (langgraph, autogen, etc.).
- Per-agent metrics: evaluate each agent's contribution independently.
- Handoff quality metrics: evaluate the quality of inter-agent communication.
- Trajectory metrics: evaluate the overall agent workflow path.

### Key Decisions

- Agent graph format should be framework-agnostic (adapter pattern).
- Need a standard way to extract per-agent spans from traces.
- Should integrate with existing `MetricResult` and judge infrastructure.

### API Sketch

```python
from qym import AgentEvaluator
from qym.metrics.judges import faithfulness_llm, relevance

evaluator = AgentEvaluator(
    task=multi_agent_task,
    dataset="agent-eval-dataset",
    agent_metrics={
        "retriever": [faithfulness_llm()],
        "synthesizer": [relevance()],
    },
    trajectory_metrics=["handoff_quality"],
)
results = evaluator.run()
```

### Per-Agent Metrics

Each agent in the graph gets its own set of metrics evaluated against its
specific input/output. Results are grouped by agent name in the dashboard.

### Trajectory Metrics

Evaluate the overall path taken by the agent system:
- Was the routing optimal?
- Were unnecessary agents invoked?
- Did the system converge to an answer efficiently?
