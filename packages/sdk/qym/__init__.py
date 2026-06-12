"""
قيِّم (qym): Simple, automated LLM evaluation framework.

Evaluate any LLM task with just 3 lines of code:
    evaluator = Evaluator(task, dataset, metrics)
    results = evaluator.run()
"""

def _resolve_version() -> str:
    """Resolve the package version from installed distribution metadata.

    Falls back to the adjacent pyproject.toml (editable/uninstalled source
    checkouts), then to a literal as a last resort. Keeping a single source
    of truth in pyproject.toml prevents the version drift that previously
    made runs report a stale hardcoded __version__.
    """
    try:
        from importlib.metadata import version as _dist_version

        return _dist_version("qym")
    except Exception:
        pass
    try:
        import re as _re
        from pathlib import Path as _Path

        _pyproject = _Path(__file__).resolve().parent.parent / "pyproject.toml"
        _match = _re.search(
            r'^version\s*=\s*"([^"]+)"',
            _pyproject.read_text(encoding="utf-8"),
            _re.MULTILINE,
        )
        if _match:
            return _match.group(1)
    except Exception:
        pass
    return "1.1.0"  # last resort — keep in sync with pyproject.toml


__version__ = _resolve_version()

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
from .metrics import builtin_metrics, list_available_metrics

__all__ = [
    "Evaluator",
    "EvaluationObserver",
    "EvaluationResult",
    "GroupRunAnalysis",
    "MultiModelRunner",
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
