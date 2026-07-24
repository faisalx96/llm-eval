<p align="center">
  <img src="docs/images/qym_logo.png" alt="qym logo" width="400" />
</p>

---

<h3 align="center">Evaluate LLM Systems With A Python SDK And Shared Review Platform</h3>

<p align="center">
  <img src="docs/images/qym_icon.png" alt="" height="20" />
  &nbsp;
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.9+-3776AB.svg" alt="Python 3.9+" /></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License: MIT" /></a>
</p>

## What Is qym?

qym (قيِّم) is an evaluation operating system for LLM products. It combines a fast Python SDK for running evaluations with a centralized platform for monitoring runs, comparing results, diagnosing failures, and managing review workflows.

At the core, qym gives teams a simple evaluation workflow: define a task, choose a dataset, apply metrics, run the evaluation, then inspect the results locally or in the shared platform.

## What Problem It Solves

LLM evaluation is often fragmented across scripts, notebooks, spreadsheets, and disconnected dashboards. Teams can generate scores, but usually cannot do so consistently, at scale, or with enough visibility into why systems fail.

qym solves this by making evaluation structured, repeatable, observable, and team-ready.

## What qym Adds

- A simple evaluation workflow built around tasks, datasets, and metrics
- High-throughput async execution for large-scale evaluation runs
- Multi-model benchmarking in the same workflow
- Support for platform datasets and local CSV/JSONL datasets, including multi-column CSV inputs
- Built-in metrics, custom metrics, and LLM-as-judge evaluation
- Automatic tracing of LLM calls, tools, reasoning steps, latency, tokens, and errors
- A live platform for run history, comparison, charts, and version tracking
- AI-powered root cause analysis for understanding failure patterns
- Human review, approval, and correction workflows for governance and continuous improvement

## Why It Matters

- It reduces manual evaluation effort
- It makes model and prompt iteration faster
- It improves confidence in quality before deployment
- It gives teams a clear view of regressions, failure causes, and performance trends
- It turns evaluation from an isolated developer activity into a managed organizational capability

## Platform Value

qym is not just a scoring tool. The platform adds operational visibility and collaboration through:

- Live run streaming
- Side-by-side run and model comparison
- Embedded trace viewer
- Version-aware dashboards
- Role-based access and approval workflows
- Review queues and reusable correction history

## Bottom Line

qym turns LLM evaluation from scattered testing into a centralized, observable, and reviewable system for improving LLM quality at scale.

## Packages

| Package | What it is for | Install / Access |
|---------|-----------------|------------------|
| **SDK** (`packages/sdk`) | Run evaluations from Python or CLI | `pip install qym` |
| **Platform** (`packages/platform`) | Shared dashboard, review, analysis, admin, and history | Self-host with Docker / `pip install -e packages/platform`, or use a hosted deployment if you have one |

## Choose Your Path

- **I want to run evaluations**: start with the [SDK README](packages/sdk/README.md)
- **I want to operate or self-host the platform**: see the [Platform README](packages/platform/README.md)
- **I want deployment and admin docs**: use the docs linked below
- **I want to contribute to the repo**: use the development setup below

## Quick Start

### Run an evaluation with the SDK

```bash
pip install qym
```

```python
from qym import Evaluator


def my_task(question):
    return call_your_llm(question)


results = Evaluator(
    task=my_task,
    dataset="my-dataset",
    metrics=["exact_match", "contains"],
).run()

# Stochastic task? Add samples=8 to run every item 8x as ONE run and get
# Pass@k / Pass^k consistency metrics — see "Repeat Runs" in the SDK guide.
```

Tasks can also return hidden metadata for custom metrics:

```python
def rag_task(question):
    docs = retrieve(question)
    return {
        "output": call_your_llm(question, docs),
        "metadata": {"retrieved_context": docs},
    }

def faithfulness(output, expected):
    return judge(output["output"], output["metadata"]["retrieved_context"])
```

When a task returns a dict, qym requires exactly `output` and `metadata`; malformed dict outputs are reported as item errors.

### Use the platform

- **Hosted**: use your team's hosted qym platform URL and API key, if you have one
- **Self-hosted**: run the platform locally with Docker or install `qym-platform` from `packages/platform`

## Repository Layout

```text
packages/
  sdk/        qym SDK package
  platform/   qym-platform web application
docker/       Docker Compose and container assets
docs/         Product and operator documentation
examples/     Runnable examples
tests/        SDK and platform tests
```

## Development Setup

Install both packages in editable mode:

```bash
pip install -e packages/sdk[dev] -e packages/platform
```

Useful commands:

```bash
pytest -q
black .
isort .
mypy packages/sdk/qym
```

Run the platform with Docker:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml up --build
```

For non-Docker platform setup and admin operations, see the [Platform README](packages/platform/README.md).

## Documentation

**SDK**

- [SDK README](packages/sdk/README.md) - installation, Python API, CLI, and metrics overview
- [User Guide](packages/sdk/docs/USER_GUIDE.md) - tasks, datasets, configuration, and troubleshooting
- [Metric Bank](packages/sdk/docs/METRIC_BANK.md) - metric reference and usage patterns

**Platform**

- [Platform README](packages/platform/README.md) - local setup and operator overview
- [Platform User Guide](packages/platform/docs/USER_GUIDE.md) - dashboard workflows and analysis features

## License

MIT
