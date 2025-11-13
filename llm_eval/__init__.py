"""
LLM-Eval: Simple, automated LLM evaluation framework built on Langfuse.

Evaluate any LLM task with just 3 lines of code:
    evaluator = Evaluator(task, dataset, metrics)
    results = evaluator.run()
"""

from .core.evaluator import Evaluator
from .core.multi_runner import MultiModelRunner
from .core.results import EvaluationResult
from .core.run_spec import RunSpec
from .metrics import builtin_metrics, list_available_metrics

__version__ = "0.1.0"
__all__ = [
    "Evaluator",
    "EvaluationResult",
    "MultiModelRunner",
    "RunSpec",
    "builtin_metrics",
    "list_available_metrics",
]
