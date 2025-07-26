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

results = evaluator.run()
print(results.summary())
```

## Features

- 🚀 **Simple API** - Get started in minutes, not hours
- 🔌 **Framework Agnostic** - Works with LangChain, LangGraph, OpenAI, or any Python function
- 📊 **Built on Langfuse** - All evaluations tracked and visible in your Langfuse dashboard
- 🎯 **Professional Metrics** - Powered by DeepEval's evaluation suite (included)
- ⚡ **Async Support** - Evaluate hundreds of examples in parallel
- 🛡️ **Production Ready** - Comprehensive error handling and recovery

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

## License

MIT