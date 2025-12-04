"""Built-in metrics for LLM evaluation."""

# Try to import DeepEval metrics, fall back to built-in only if not available
try:
    from .deepeval_metrics import get_deepeval_metrics
    builtin_metrics = get_deepeval_metrics()
    _has_deepeval = True
except ImportError:
    # DeepEval not available, use only built-in metrics
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
    _has_deepeval = False


def list_available_metrics():
    """List all available metrics with descriptions."""
    print("Available Metrics:")
    print("=" * 50)
    
    if not _has_deepeval:
        print("🔸 Note: Using built-in metrics only (DeepEval not installed)")
        print("   To get advanced metrics, install with: pip install llm-eval[deepeval]")
        print()
    
    for name, metric in sorted(builtin_metrics.items()):
        if hasattr(metric, '__doc__') and metric.__doc__:
            description = metric.__doc__.strip().split('\n')[0]
        else:
            description = "No description available"
        
        print(f"• {name:20} - {description}")
    
    total_msg = f"Total: {len(builtin_metrics)} metrics available"
    if _has_deepeval:
        total_msg += " (including DeepEval metrics)"
    else:
        total_msg += " (built-in only)"
    print(f"\n{total_msg}")


def has_deepeval() -> bool:
    """Check if DeepEval is available."""
    return _has_deepeval


__all__ = ["builtin_metrics", "list_available_metrics", "has_deepeval"]