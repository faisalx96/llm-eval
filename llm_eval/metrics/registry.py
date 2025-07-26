"""Metric registry for looking up metrics by name."""

from typing import Callable, Optional
from . import builtin_metrics


# Global registry for custom metrics
_custom_metrics = {}


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