# LLM-Eval: Simple LLM Evaluation Framework

**Evaluate your LLM applications with just 3 lines of code.**

Built on [Langfuse](https://langfuse.com) for seamless integration with your existing observability stack, `llm-eval` is a developer-friendly framework for testing, benchmarking, and validating Large Language Models.

## 🚀 Key Features

- **Simple API**: Get started in minutes with a clean, Pythonic interface.
- **Async & Fast**: Evaluate hundreds of examples in parallel using `asyncio`.
- **Multi-Model Support**: Compare models (e.g., GPT-4 vs Llama 3) side-by-side.
- **Rich Dashboard**: Real-time terminal UI (TUI) showing progress, metrics, and latency.
- **Framework Agnostic**: Works with LangChain, OpenAI, Anthropic, or any Python function.
- **Auto-Save**: Automatically persist results to JSON or CSV for analysis.

## ⚡ Quick Start

### 1. Install
```bash
pip install llm-eval
```

### 2. Run Evaluation
```python
from llm_eval import Evaluator

# 1. Define your task
def my_llm_function(input_text):
    return "Model response"

# 2. Run evaluation
evaluator = Evaluator(
    task=my_llm_function,
    dataset="my-langfuse-dataset",
    metrics=["exact_match", "faithfulness"]
)

results = evaluator.run()
print(results.summary())
```

## 📖 Three Ways to Run

`llm-eval` supports three main execution modes to fit your workflow:

1.  **[Python API](docs/USER_GUIDE.md#option-1-python-api)**: Ideal for notebooks, debugging, and custom scripts.
2.  **[Command Line (CLI)](docs/USER_GUIDE.md#option-2-command-line-interface-cli)**: Perfect for CI/CD pipelines and quick checks.
    ```bash
    llm-eval --task-file agent.py --task-function chat --dataset qa-set --metrics exact_match
    ```
3.  **[Multi-Model Config](docs/USER_GUIDE.md#option-3-multi-model-configuration)**: Best for benchmarking multiple models in parallel.
    ```bash
    llm-eval --runs-config experiments.json
    ```

## 📚 Documentation

- **[User Guide](docs/USER_GUIDE.md)**: Comprehensive guide on installation, usage, and configuration.
- **[Metrics Guide](docs/METRICS_GUIDE.md)**: Details on all available metrics and how to create custom ones.
- **[Langfuse Guide](docs/LANGFUSE_GUIDE.md)**: Advanced integration details.
- **[Examples](examples/)**: Jupyter notebooks and example scripts.

## License

MIT
