"""
LLM-Eval: Simple, automated LLM evaluation framework built on Langfuse.

Evaluate any LLM task with just 3 lines of code:
    evaluator = Evaluator(task, dataset, metrics)
    results = evaluator.run()
"""

from .core.evaluator import Evaluator
from .core.results import EvaluationResult
from .metrics import builtin_metrics, list_available_metrics
from .templates import (
    get_template,
    list_templates,
    print_available_templates,
    recommend_template,
)

__version__ = "0.1.1"
__all__ = [
    "Evaluator",
    "EvaluationResult",
    "builtin_metrics",
    "list_available_metrics",
    "get_template",
    "list_templates",
    "recommend_template",
    "print_available_templates",
]
