"""Built-in metrics for LLM evaluation."""

from .builtin import (
    exact_match, contains_expected, fuzzy_match, response_time, token_count,
    correctness, faithfulness
)

builtin_metrics = {
    'exact_match': exact_match,
    'contains': contains_expected,
    'fuzzy_match': fuzzy_match,
    'response_time': response_time,
    'token_count': token_count,
    'correctness': correctness,
    'faithfulness': faithfulness,
}

# Try to import LLM judge metrics (requires openai)
try:
    from .judges import judge_metrics, create_judge
    from .judge_config import JudgeConfig, get_default_judge_config, set_default_judge_config
    from .result import MetricResult
    builtin_metrics.update(judge_metrics)
    _has_judges = True
except ImportError:
    _has_judges = False


def list_available_metrics():
    """List all available metrics with descriptions."""
    print("Available Metrics:")
    print("=" * 50)

    for name, metric in sorted(builtin_metrics.items()):
        if hasattr(metric, '__doc__') and metric.__doc__:
            description = metric.__doc__.strip().split('\n')[0]
        else:
            description = "No description available"
        
        print(f"• {name:20} - {description}")

    total_msg = f"Total: {len(builtin_metrics)} metrics available"
    if _has_judges:
        total_msg += " (including judge metrics)"
    print(f"\n{total_msg}")


def has_judges() -> bool:
    """Check if LLM judge metrics are available (requires openai)."""
    return _has_judges


__all__ = ["builtin_metrics", "list_available_metrics", "has_judges"]
