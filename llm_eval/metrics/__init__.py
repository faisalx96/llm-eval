"""Built-in metrics for LLM evaluation using DeepEval."""

from .deepeval_metrics import get_deepeval_metrics

# Automatically discover and register all DeepEval metrics
builtin_metrics = get_deepeval_metrics()


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
    
    print(f"\nTotal: {len(builtin_metrics)} metrics available")


__all__ = ["builtin_metrics", "list_available_metrics"]