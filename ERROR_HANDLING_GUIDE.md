# Error Handling and Edge Cases Guide

## Overview
This document outlines error handling strategies and edge cases for the LLM evaluation framework.

## Common Error Scenarios

### 1. Langfuse Connection Errors

#### Scenario: API Key Issues
```python
class LangfuseConnectionError(Exception):
    """Raised when Langfuse connection fails."""
    pass

def handle_langfuse_auth():
    try:
        client = Langfuse()
        # Test connection
        client.get_dataset("test")
    except Exception as e:
        if "401" in str(e) or "unauthorized" in str(e).lower():
            raise LangfuseConnectionError(
                "Invalid Langfuse credentials. Please check LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY"
            )
        elif "404" in str(e):
            # This is okay - dataset doesn't exist
            pass
        else:
            raise LangfuseConnectionError(f"Failed to connect to Langfuse: {e}")
```

#### Scenario: Network Issues
```python
import time
from typing import Optional

def retry_langfuse_operation(func, max_retries: int = 3, backoff: float = 1.0):
    """Retry Langfuse operations with exponential backoff."""
    last_error: Optional[Exception] = None
    
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(backoff * (2 ** attempt))
            continue
    
    raise RuntimeError(f"Failed after {max_retries} attempts: {last_error}")
```

### 2. Dataset Errors

#### Scenario: Dataset Not Found
```python
def safe_get_dataset(client: Langfuse, dataset_name: str):
    """Safely retrieve dataset with helpful error messages."""
    try:
        return client.get_dataset(dataset_name)
    except Exception as e:
        if "404" in str(e) or "not found" in str(e).lower():
            # List available datasets
            available = client.get_datasets()
            names = [d.name for d in available.items[:5]]
            raise ValueError(
                f"Dataset '{dataset_name}' not found. "
                f"Available datasets: {', '.join(names)}{'...' if len(available.items) > 5 else ''}"
            )
        raise
```

#### Scenario: Empty Dataset
```python
def validate_dataset(dataset):
    """Ensure dataset has items before evaluation."""
    if not dataset.items or len(dataset.items) == 0:
        raise ValueError(
            f"Dataset '{dataset.name}' is empty. "
            "Please add items to the dataset before running evaluation."
        )
    return dataset
```

#### Scenario: Malformed Dataset Items
```python
def validate_dataset_item(item, index: int):
    """Validate individual dataset item structure."""
    errors = []
    
    if not hasattr(item, 'input') or item.input is None:
        errors.append(f"Item {index}: Missing or null 'input' field")
    
    if not isinstance(item.input, (dict, str, list)):
        errors.append(f"Item {index}: Invalid input type {type(item.input)}")
    
    # Check for expected_output if metrics require it
    if hasattr(item, 'expected_output') and item.expected_output is not None:
        if not isinstance(item.expected_output, (dict, str, list, int, float, bool)):
            errors.append(f"Item {index}: Invalid expected_output type")
    
    return errors
```

### 3. Task Execution Errors

#### Scenario: Task Timeout
```python
import asyncio
from concurrent.futures import TimeoutError

async def run_with_timeout(task, input_data, timeout_seconds: float = 30.0):
    """Run task with timeout protection."""
    try:
        return await asyncio.wait_for(
            asyncio.create_task(task(input_data)),
            timeout=timeout_seconds
        )
    except asyncio.TimeoutError:
        raise TimeoutError(
            f"Task execution exceeded {timeout_seconds}s timeout. "
            "Consider increasing timeout or optimizing the task."
        )
```

#### Scenario: Task Raises Exception
```python
def safe_task_execution(task, input_data, item_id: str):
    """Execute task with comprehensive error handling."""
    try:
        return task(input_data), None
    except Exception as e:
        error_info = {
            "error_type": type(e).__name__,
            "error_message": str(e),
            "item_id": item_id,
            "input_preview": str(input_data)[:100] + "..." if len(str(input_data)) > 100 else str(input_data)
        }
        return None, error_info
```

#### Scenario: Non-Traced Task
```python
def ensure_traced_task(task, client: Langfuse):
    """Wrap task with Langfuse tracing if not already traced."""
    # Check if task already has Langfuse integration
    if hasattr(task, '__wrapped__') and hasattr(task, 'langfuse_trace'):
        return task
    
    # Check for LangChain with existing callbacks
    if hasattr(task, 'invoke') and hasattr(task, 'callbacks'):
        return task
    
    # Wrap with manual tracing
    @functools.wraps(task)
    def traced_task(input_data):
        trace = client.trace(
            name=f"{task.__name__ if hasattr(task, '__name__') else 'unknown_task'}_eval",
            input=input_data
        )
        try:
            output = task(input_data)
            trace.update(output=output)
            return output
        except Exception as e:
            trace.update(output={"error": str(e)})
            raise
        finally:
            trace.end()
    
    traced_task.langfuse_trace = True
    return traced_task
```

### 4. Metric Errors

#### Scenario: Metric Computation Fails
```python
def safe_metric_computation(metric, output, expected, metric_name: str):
    """Safely compute metric with fallback."""
    try:
        # Handle different metric signatures
        import inspect
        sig = inspect.signature(metric)
        params = list(sig.parameters.keys())
        
        if len(params) == 1:
            return metric(output)
        elif len(params) == 2:
            return metric(output, expected)
        else:
            raise ValueError(f"Metric {metric_name} has unsupported signature")
            
    except Exception as e:
        # Log detailed error
        error_msg = f"Metric '{metric_name}' failed: {type(e).__name__}: {str(e)}"
        print(f"Warning: {error_msg}")
        
        # Return None or default score
        return None
```

#### Scenario: Invalid Metric Output
```python
def validate_metric_output(value, metric_name: str):
    """Ensure metric returns valid score."""
    if value is None:
        return 0.0, "NUMERIC"
    
    # Handle different types
    if isinstance(value, bool):
        return value, "BOOLEAN"
    elif isinstance(value, (int, float)):
        # Ensure numeric scores are in valid range
        if 0 <= value <= 1:
            return float(value), "NUMERIC"
        else:
            print(f"Warning: Metric '{metric_name}' returned {value}, clamping to [0,1]")
            return max(0.0, min(1.0, float(value))), "NUMERIC"
    elif isinstance(value, str):
        return value, "CATEGORICAL"
    else:
        raise ValueError(
            f"Metric '{metric_name}' returned invalid type {type(value)}. "
            "Expected float, bool, or str."
        )
```

### 5. Async/Parallel Execution Errors

#### Scenario: Partial Batch Failure
```python
async def run_evaluation_batch(items, task, metrics, max_concurrent: int = 10):
    """Run evaluations with controlled concurrency."""
    semaphore = asyncio.Semaphore(max_concurrent)
    results = []
    
    async def process_item(item, index):
        async with semaphore:
            try:
                output = await task(item.input)
                scores = {}
                for metric_name, metric_func in metrics.items():
                    try:
                        score = await metric_func(output, item.expected_output)
                        scores[metric_name] = score
                    except Exception as e:
                        scores[metric_name] = {"error": str(e)}
                
                return {"index": index, "success": True, "output": output, "scores": scores}
            except Exception as e:
                return {"index": index, "success": False, "error": str(e)}
    
    # Process all items
    tasks = [process_item(item, i) for i, item in enumerate(items)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Summary statistics
    successful = sum(1 for r in results if isinstance(r, dict) and r.get("success"))
    failed = len(results) - successful
    
    if failed > 0:
        print(f"Warning: {failed}/{len(items)} evaluations failed")
    
    return results
```

### 6. Edge Cases

#### Empty or None Outputs
```python
def handle_empty_output(output, metrics: dict):
    """Handle cases where task returns empty or None output."""
    if output is None or output == "":
        # Return failure scores for all metrics
        return {name: 0.0 for name in metrics}
    return None  # Continue normal processing
```

#### Very Large Outputs
```python
def truncate_large_output(output, max_chars: int = 10000):
    """Truncate very large outputs to prevent memory issues."""
    if isinstance(output, str) and len(output) > max_chars:
        return output[:max_chars] + f"\n... (truncated {len(output) - max_chars} chars)"
    return output
```

#### Circular References
```python
import json

def safe_serialize(obj):
    """Safely serialize objects that might have circular references."""
    try:
        return json.dumps(obj)
    except (TypeError, ValueError):
        # Fallback to string representation
        return str(obj)
```

## Error Recovery Strategies

### 1. Graceful Degradation
```python
class EvaluationResult:
    def __init__(self):
        self.successful_items = []
        self.failed_items = []
        self.partial_scores = {}
    
    def add_result(self, item_id, scores=None, error=None):
        if error:
            self.failed_items.append({"id": item_id, "error": error})
        else:
            self.successful_items.append({"id": item_id, "scores": scores})
    
    @property
    def success_rate(self):
        total = len(self.successful_items) + len(self.failed_items)
        return len(self.successful_items) / total if total > 0 else 0
```

### 2. Checkpoint/Resume
```python
def save_evaluation_checkpoint(results, checkpoint_file: str):
    """Save intermediate results for resume capability."""
    import pickle
    with open(checkpoint_file, 'wb') as f:
        pickle.dump({
            'results': results,
            'timestamp': time.time(),
            'version': '1.0'
        }, f)

def resume_from_checkpoint(checkpoint_file: str):
    """Resume evaluation from checkpoint."""
    if os.path.exists(checkpoint_file):
        with open(checkpoint_file, 'rb') as f:
            data = pickle.load(f)
            return data['results']
    return None
```

### 3. Error Reporting
```python
def generate_error_report(failed_items: list):
    """Generate comprehensive error report."""
    error_summary = {}
    
    for item in failed_items:
        error_type = item.get('error_type', 'Unknown')
        error_summary[error_type] = error_summary.get(error_type, 0) + 1
    
    report = {
        'total_failures': len(failed_items),
        'error_types': error_summary,
        'sample_errors': failed_items[:5],  # First 5 errors
        'recommendations': generate_recommendations(error_summary)
    }
    
    return report

def generate_recommendations(error_summary: dict):
    """Generate recommendations based on error patterns."""
    recommendations = []
    
    if 'TimeoutError' in error_summary:
        recommendations.append("Consider increasing timeout or optimizing task performance")
    
    if 'ConnectionError' in error_summary:
        recommendations.append("Check network connectivity and API endpoints")
    
    if 'ValueError' in error_summary:
        recommendations.append("Validate dataset format and input types")
    
    return recommendations
```

## Best Practices

1. **Always validate inputs** before processing
2. **Use specific exception types** for different error scenarios
3. **Log errors with context** for debugging
4. **Provide actionable error messages** to users
5. **Implement retry logic** for transient failures
6. **Save partial results** for long-running evaluations
7. **Set reasonable timeouts** for all operations
8. **Handle edge cases explicitly** rather than failing silently

## Integration Example

```python
class RobustEvaluator:
    def __init__(self, task, dataset_name, metrics, config=None):
        self.config = config or {}
        self.max_retries = self.config.get('max_retries', 3)
        self.timeout = self.config.get('timeout', 30.0)
        
        # Initialize with error handling
        try:
            self.client = self._init_langfuse()
            self.dataset = self._load_dataset(dataset_name)
            self.task = ensure_traced_task(task, self.client)
            self.metrics = self._validate_metrics(metrics)
        except Exception as e:
            raise RuntimeError(f"Initialization failed: {e}")
    
    def run(self):
        """Run evaluation with comprehensive error handling."""
        results = EvaluationResult()
        
        for i, item in enumerate(self.dataset.items):
            try:
                # Validate item
                errors = validate_dataset_item(item, i)
                if errors:
                    results.add_result(f"item_{i}", error="; ".join(errors))
                    continue
                
                # Execute task
                output, error = safe_task_execution(self.task, item.input, f"item_{i}")
                if error:
                    results.add_result(f"item_{i}", error=error)
                    continue
                
                # Compute metrics
                scores = {}
                for name, metric in self.metrics.items():
                    score = safe_metric_computation(
                        metric, output, 
                        getattr(item, 'expected_output', None), 
                        name
                    )
                    if score is not None:
                        scores[name] = score
                
                results.add_result(f"item_{i}", scores=scores)
                
            except Exception as e:
                results.add_result(f"item_{i}", error=str(e))
        
        return results
```