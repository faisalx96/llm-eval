# LLM-Eval: Simple LLM Evaluation Framework

Evaluate your LLM applications with just 3 lines of code! Built on [Langfuse](https://langfuse.com) for seamless integration with your existing observability stack.

## Quick Start

```python
from llm_eval import Evaluator

# That's it! Just provide your task, dataset name, and metrics
evaluator = Evaluator(
    task=my_llm_function,
    dataset="my-langfuse-dataset",
    metrics=["answer_relevancy", "faithfulness", "hallucination"]
)

# Run evaluation with auto-save
results = evaluator.run(auto_save=True, save_format="json")
print(results.summary())

# Or save manually in different formats
results.save_json("my_results.json")  # Complete results
results.save_csv("my_results.csv")    # For Excel analysis
```

## Features

- 🚀 **Simple API** - Get started in minutes, not hours
- 🔌 **Framework Agnostic** - Works with LangChain, LangGraph, OpenAI, or any Python function
- 📊 **Built on Langfuse** - All evaluations tracked and visible in your Langfuse dashboard
- 🎯 **Professional Metrics** - Powered by DeepEval's evaluation suite (included)
- ⚡ **Async Support** - Evaluate hundreds of examples in parallel
- 🛡️ **Production Ready** - Comprehensive error handling and recovery
- 📺 **Live Progress Display** - Real-time status updates showing inputs, outputs, and metrics
- 🧮 **Multi-Model Dashboard** - Evaluate multiple models in parallel with per-run KPIs
- ⏱️ **Performance Tracking** - Detailed timing statistics for each evaluation
- 💾 **Export Results** - Save as JSON or CSV for further analysis
- 🔄 **Auto-save** - Automatically save results after evaluation

## Installation

```bash
pip install llm-eval
```

For LangChain support:
```bash
pip install llm-eval[langchain]
```

## Documentation

- [User Guide](docs/USER_GUIDE.md) - Friendly introduction and common patterns
- [API Reference](docs/API.md) - Detailed technical documentation
- [Examples](examples/) - Jupyter notebooks with real-world scenarios

## Requirements

- Python 3.8+
- Langfuse account (free tier available)
- Your evaluation datasets stored in Langfuse
- OpenAI API key (for DeepEval metrics)

## Multi-Model Runs & TUI Dashboard

Evaluate several models or configurations simultaneously with the new Rich-powered dashboard:

```json
[
  {
    "name": "gpt-4o-mini",
    "task_file": "examples/agent.py",
    "task_function": "chat",
    "dataset": "qa-set",
    "metrics": ["exact_match", "fuzzy_match"],
    "config": {
      "max_concurrency": 5,
      "run_metadata": {"model": "gpt-4o-mini"}
    }
  },
  {
    "name": "llama-3.1",
    "task_file": "examples/agent.py",
    "task_function": "chat",
    "dataset": "qa-set",
    "metrics": "exact_match,fuzzy_match",
    "metadata": {"model": "llama-3.1"},
    "output": "eval_results/llama.json"
  }
]
```

Run them all in parallel:

```bash
llm-eval --runs-config runs.json
```

Each run gets its own progress bar, KPIs (success rate, throughput, latency), and live metric averages in the TUI.
Configs may be JSON or YAML, and relative paths are resolved relative to the config file. Optional `metadata` blocks merge into each run's `run_metadata`, and `output` lets you persist run-specific JSON/CSV results automatically.

Prefer scripting? Call it directly from Python:

```python
from llm_eval import Evaluator

results = Evaluator.run_parallel(
    [
        {"name": "gpt-4o-mini", "task": my_fn, "dataset": "qa-set", "metrics": ["exact_match"]},
        {"name": "llama-3.1", "task": my_other_fn, "dataset": "qa-set", "metrics": ["exact_match"]},
    ],
    show_tui=True,
)
```

For simple scripts you can also pass `model` (string or comma-separated list) directly to `Evaluator(...)`. Your task function can optionally accept a `model` or `model_name` keyword argument; llm-eval injects it automatically so you can dispatch to the right backend without custom glue.

## License

MIT
