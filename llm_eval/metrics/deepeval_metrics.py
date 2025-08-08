"""DeepEval metric wrappers for LLM evaluation."""

import inspect
from typing import Any, Dict, Callable


def create_deepeval_wrapper(metric_class, **metric_kwargs):
    """Create a wrapper function for DeepEval metrics."""
    
    async def wrapper(output: Any, expected: Any = None, input_data: Any = None) -> float:
        """Wrapper function that adapts DeepEval metrics to our interface."""
        try:
            from deepeval.test_case import LLMTestCase
            
            # Create test case for DeepEval
            test_case = LLMTestCase(
                input=str(input_data) if input_data is not None else str(output),
                actual_output=str(output),
                expected_output=str(expected) if expected is not None else None
            )
            
            # Create metric instance
            metric = metric_class(**metric_kwargs)
            
            # Evaluate (suppress DeepEval's CLI output but not the actual execution)
            import os
            import sys
            
            # Temporarily disable DeepEval's progress bars and CLI output
            old_env = os.environ.get('DEEPEVAL_TELEMETRY_OPT_OUT')
            old_stderr = sys.stderr
            
            try:
                # Disable DeepEval telemetry and progress
                os.environ['DEEPEVAL_TELEMETRY_OPT_OUT'] = 'YES'
                os.environ['DEEPEVAL_DISABLE_PROGRESS_BAR'] = 'true'
                
                # Only suppress stderr where DeepEval writes its progress
                import io
                sys.stderr = io.StringIO()
                
                metric.measure(test_case)
            finally:
                # Restore original settings
                sys.stderr = old_stderr
                if old_env is None:
                    os.environ.pop('DEEPEVAL_TELEMETRY_OPT_OUT', None)
                else:
                    os.environ['DEEPEVAL_TELEMETRY_OPT_OUT'] = old_env
                os.environ.pop('DEEPEVAL_DISABLE_PROGRESS_BAR', None)
            
            # Return score
            score = float(metric.score)
            return score
            
        except Exception as e:
            # Handle common DeepEval errors with helpful messages
            error_msg = str(e)
            if "api_key" in error_msg.lower() and "openai" in error_msg.lower():
                raise RuntimeError(
                    f"DeepEval metric '{metric_class.__name__}' requires OpenAI API key. "
                    "Please set OPENAI_API_KEY environment variable or add it to your .env file."
                )
            elif "anthropic" in error_msg.lower() and "api_key" in error_msg.lower():
                raise RuntimeError(
                    f"DeepEval metric '{metric_class.__name__}' requires Anthropic API key. "
                    "Please set ANTHROPIC_API_KEY environment variable or add it to your .env file."
                )
            else:
                raise RuntimeError(f"DeepEval metric '{metric_class.__name__}' failed: {error_msg}")
    
    # Add metadata to the wrapper
    wrapper.__name__ = metric_class.__name__.replace('Metric', '').lower()
    wrapper.__doc__ = getattr(metric_class, '__doc__', f"DeepEval {metric_class.__name__}")
    
    return wrapper


def discover_deepeval_metrics() -> Dict[str, Callable]:
    """Automatically discover all available DeepEval metrics."""
    metrics = {}
    
    try:
        import deepeval.metrics as deepeval_metrics
        
        # Get all classes from deepeval.metrics
        for name, obj in inspect.getmembers(deepeval_metrics, inspect.isclass):
            # Check if it's a metric class
            is_metric_class = (
                (name.endswith('Metric') or name in ['GEval', 'ArenaGEval', 'ConversationalGEval', 'MultimodalGEval']) and
                hasattr(obj, 'measure') and 
                not name.startswith('Base') and  # Exclude all base classes
                name != 'BaseMetric'
            )
            
            if is_metric_class:
                # Convert class name to snake_case
                import re
                
                # Handle special cases first
                if name == 'GEval':
                    metric_name = 'geval'
                elif name == 'ArenaGEval':
                    metric_name = 'arena_geval'
                elif name == 'ConversationalGEval':
                    metric_name = 'conversational_geval'
                elif name == 'MultimodalGEval':
                    metric_name = 'multimodal_geval'
                else:
                    # Remove 'Metric' suffix and convert to snake_case
                    clean_name = name.replace('Metric', '')
                    # Insert underscore before capital letters (except first)
                    metric_name = re.sub('([a-z0-9])([A-Z])', r'\1_\2', clean_name).lower()
                
                # Create the actual wrapper function directly
                wrapper = create_deepeval_wrapper(obj)
                wrapper.__name__ = metric_name
                
                # Generate better descriptions
                descriptions = {
                    'answer_relevancy': 'Measures how relevant the answer is to the input question',
                    'faithfulness': 'Measures how faithful the answer is to the provided context',
                    'contextual_precision': 'Measures the precision of retrieved context',
                    'contextual_recall': 'Measures the recall of retrieved context',
                    'contextual_relevancy': 'Measures how relevant the context is to the question',
                    'hallucination': 'Detects hallucinations in the output',
                    'toxicity': 'Measures toxicity/harmfulness in the output',
                    'bias': 'Detects bias in the output',
                    'summarization': 'Evaluates summarization quality',
                    'geval': 'Generic evaluation using G-Eval framework',
                    'json_correctness': 'Validates JSON format correctness',
                    'tool_correctness': 'Evaluates tool usage correctness',
                }
                
                wrapper.__doc__ = descriptions.get(metric_name, f"DeepEval {obj.__name__} metric")
                
                metrics[metric_name] = wrapper
                
    except ImportError:
        raise ImportError(
            "DeepEval is required for advanced evaluation metrics.\n"
            "For air-gapped environments, you can use built-in metrics only.\n"
            "To install DeepEval: pip install llm-eval[deepeval]\n"
            "Or use only built-in metrics: exact_match, contains, fuzzy_match"
        )
    except Exception as e:
        # Log but don't fail - some metrics might have issues
        print(f"Warning: Error discovering some DeepEval metrics: {e}")
    
    return metrics


def get_deepeval_metrics() -> Dict[str, Callable]:
    """Get all available DeepEval metrics plus our custom ones."""
    metrics = discover_deepeval_metrics()
    
    # Add exact match for backward compatibility
    def exact_match(output: Any, expected: Any) -> float:
        """Simple exact match comparison."""
        if output is None or expected is None:
            return 0.0
        return 1.0 if str(output).strip() == str(expected).strip() else 0.0
    
    metrics['exact_match'] = exact_match
    
    return metrics


# Get all available metrics at module load time
_available_metrics = get_deepeval_metrics()

# Make metrics available at module level
globals().update(_available_metrics)