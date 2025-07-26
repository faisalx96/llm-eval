"""
LLM-Eval: Simple, automated LLM evaluation framework built on Langfuse.

Evaluate any LLM task with just 3 lines of code:
    evaluator = Evaluator(task, dataset, metrics)
    results = evaluator.run()
"""

from .core.evaluator import Evaluator
from .core.results import EvaluationResult
from .metrics import builtin_metrics, list_available_metrics

__version__ = "0.1.0"
__all__ = ["Evaluator", "EvaluationResult", "builtin_metrics", "list_available_metrics"]