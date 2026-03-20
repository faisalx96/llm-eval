"""
قيِّم (qym): Simple, automated LLM evaluation framework built on Langfuse.

Evaluate any LLM task with just 3 lines of code:
    evaluator = Evaluator(task, dataset, metrics)
    results = evaluator.run()
"""

__version__ = "0.8.1.3"

from .core.evaluator import Evaluator
from .core.multi_runner import MultiModelRunner
from .core.results import EvaluationResult
from .core.config import RunSpec
from .core.dataset import CsvDataset
from .metrics import builtin_metrics, list_available_metrics
from .metrics.result import MetricResult
from .metrics.judge_config import JudgeConfig, get_default_judge_config, set_default_judge_config

__all__ = [
    "Evaluator",
    "EvaluationResult",
    "MultiModelRunner",
    "RunSpec",
    "CsvDataset",
    "MetricResult",
    "JudgeConfig",
    "get_default_judge_config",
    "set_default_judge_config",
    "builtin_metrics",
    "list_available_metrics",
]
