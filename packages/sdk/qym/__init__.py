"""
قيِّم (qym): Simple, automated LLM evaluation framework.

Evaluate any LLM task with just 3 lines of code:
    evaluator = Evaluator(task, dataset, metrics)
    results = evaluator.run()
"""

__version__ = "0.9.0"

# Load .env from the caller's CWD as early as possible, so module-level reads of
# os.environ (e.g. qym.platform.defaults.DEFAULT_PLATFORM_URL) see the right values.
from .utils.env import load_cwd_dotenv as _load_cwd_dotenv

_load_cwd_dotenv()

from .core.evaluator import Evaluator
from .core.group_analysis import (
    GroupRunAnalysis,
    analyze_group_runs,
    compare_group_runs,
)
from .core.multi_runner import MultiModelRunner
from .core.observers import (
    EvaluationObserver,
    ProgressCallbackObserver,
    ProgressSnapshot,
)
from .core.results import EvaluationResult
from .core.config import RunSpec
from .core.dataset import CsvDataset, InMemoryDataset, JsonlDataset, QymDataset
from .metrics import Metric, MetricSpec, builtin_metrics, list_available_metrics

__all__ = [
    "Evaluator",
    "EvaluationObserver",
    "EvaluationResult",
    "GroupRunAnalysis",
    "MultiModelRunner",
    "Metric",
    "MetricSpec",
    "ProgressCallbackObserver",
    "ProgressSnapshot",
    "RunSpec",
    "CsvDataset",
    "InMemoryDataset",
    "JsonlDataset",
    "QymDataset",
    "analyze_group_runs",
    "builtin_metrics",
    "compare_group_runs",
    "list_available_metrics",
]
