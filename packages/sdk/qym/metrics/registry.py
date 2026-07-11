"""Metric registry for looking up metrics by name."""

from typing import Callable, Optional
from . import builtin_metrics
from .spec import MetricSpec, ScoreType


# Global registry for custom metrics
_custom_metrics = {}
_custom_metric_specs = {}


def register_metric(
    name: str,
    metric_func: Callable,
    *,
    spec: Optional[MetricSpec] = None,
    score_type: Optional[ScoreType] = None,
    **spec_kwargs,
):
    """
    Register a custom metric.

    Args:
        name: Name to register the metric under
        metric_func: Callable that computes the metric
    """
    if spec is not None and score_type is not None:
        raise ValueError("Pass either spec= or score_type=, not both")
    if spec is None and score_type is not None:
        spec = MetricSpec(score_type=score_type, **spec_kwargs)
    elif spec_kwargs:
        raise ValueError("Metric spec options require score_type=")
    _custom_metrics[name] = metric_func
    _custom_metric_specs[name] = spec or MetricSpec(score_type="legacy")


def get_metric(name: str) -> Callable:
    """
    Get a metric by name.

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

    # Not found
    available = list(_custom_metrics.keys()) + list(builtin_metrics.keys())
    raise ValueError(
        f"Metric '{name}' not found. "
        f"Available metrics: {', '.join(sorted(available))}"
    )


def get_metric_spec(name: str) -> MetricSpec:
    """Return registered score semantics, or the built-in specification."""
    if name in _custom_metric_specs:
        return _custom_metric_specs[name]
    from . import builtin_metric_specs

    if name in builtin_metric_specs:
        return builtin_metric_specs[name]
    raise ValueError(f"Metric '{name}' not found")
