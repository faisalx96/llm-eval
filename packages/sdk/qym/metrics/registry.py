"""Metric registry for looking up metrics by name."""

import logging
from typing import Callable, Dict, Optional

from . import builtin_metrics

logger = logging.getLogger(__name__)

# Global registry for custom metrics
_custom_metrics: Dict[str, Callable] = {}

# Lazy-loaded judge metrics (populated on first access)
_judge_metrics: Optional[Dict[str, Callable]] = None


def _load_judge_metrics() -> Dict[str, Callable]:
    """Lazy-load judge metrics from the judges package."""
    global _judge_metrics
    if _judge_metrics is not None:
        return _judge_metrics
    _judge_metrics = {}
    try:
        # Use importlib to load submodules directly — avoids name collisions
        # with the factory functions re-exported by judges/__init__.py.
        import importlib
        _module_names = [
            "faithfulness", "relevance", "toxicity", "correctness_llm",
            "conciseness", "hallucination", "tool_calling",
        ]
        _modules = []
        for mod_name in _module_names:
            mod = importlib.import_module(f".judges.{mod_name}", package=__package__)
            _modules.append(mod)

        for mod in _modules:
            metric = getattr(mod, "_default_metric", None)
            if metric is not None:
                name = getattr(metric, "__name__", None) or getattr(metric, "__qualname__", "")
                if name:
                    _judge_metrics[name] = metric
    except ImportError:
        # openai not installed — judge metrics unavailable
        logger.debug("Judge metrics unavailable (openai not installed)")
    return _judge_metrics


def register_metric(name: str, metric_func: Callable):
    """
    Register a custom metric.

    Args:
        name: Name to register the metric under
        metric_func: Callable that computes the metric
    """
    _custom_metrics[name] = metric_func


def get_metric(name: str) -> Callable:
    """
    Get a metric by name.

    Lookup order: custom -> builtin -> judges.

    Args:
        name: Metric name

    Returns:
        Metric function

    Raises:
        ValueError: If metric not found
    """
    # Check custom metrics first
    if name in _custom_metrics:
        return _custom_metrics[name]

    # Check built-in metrics
    if name in builtin_metrics:
        return builtin_metrics[name]

    # Check judge metrics (lazy-loaded)
    judges = _load_judge_metrics()
    if name in judges:
        return judges[name]

    # Not found
    available = sorted(
        set(list(_custom_metrics.keys()) + list(builtin_metrics.keys()) + list(judges.keys()))
    )
    raise ValueError(
        f"Metric '{name}' not found. "
        f"Available metrics: {', '.join(available)}"
    )


def list_available_metrics() -> Dict[str, str]:
    """Return a dict of all available metric names to their descriptions."""
    result: Dict[str, str] = {}
    for name, func in sorted(builtin_metrics.items()):
        doc = getattr(func, "__doc__", None) or "No description"
        result[name] = doc.strip().split("\n")[0]
    for name, func in sorted(_load_judge_metrics().items()):
        doc = getattr(func, "__doc__", None) or "LLM judge metric"
        result[name] = doc.strip().split("\n")[0]
    return result
