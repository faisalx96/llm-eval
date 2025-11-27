"""
LLM-Eval: Simple, automated LLM evaluation framework built on Langfuse.

Evaluate any LLM task with just 3 lines of code:
    evaluator = Evaluator(task, dataset, metrics)
    results = evaluator.run()
"""

__version__ = "0.3.0"

from .core.evaluator import Evaluator
from .core.multi_runner import MultiModelRunner
from .core.results import EvaluationResult
from .core.config import RunSpec
from .metrics import builtin_metrics, list_available_metrics

__all__ = [
    "Evaluator",
    "EvaluationResult",
    "MultiModelRunner",
    "RunSpec",
    "builtin_metrics",
    "list_available_metrics",
]
