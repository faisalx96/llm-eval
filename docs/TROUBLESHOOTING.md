# Troubleshooting Guide

## Common Issues and Solutions

### Installation Issues

**Problem**: Import errors when importing llm_eval
```
ModuleNotFoundError: No module named 'llm_eval'
```
**Solution**:
```bash
pip install -e .
# or
pip install llm-eval
```

**Problem**: Missing dependencies for visualizations
```
ModuleNotFoundError: No module named 'plotly'
```
**Solution**:
```bash
pip install llm-eval[viz]
# or manually
pip install plotly openpyxl pandas
```

### Langfuse Connection Issues

**Problem**: Authentication errors
```
langfuse.api.core.api_error.UnauthorizedError
```
**Solution**:
1. Check environment variables:
```bash
export LANGFUSE_SECRET_KEY="your_secret_key"
export LANGFUSE_PUBLIC_KEY="your_public_key" 
export LANGFUSE_HOST="https://cloud.langfuse.com"
```
2. Verify credentials in Langfuse dashboard
3. Check network connectivity

**Problem**: Dataset not found
```
Dataset 'my-dataset' not found in Langfuse
```
**Solution**:
1. Verify dataset exists in Langfuse UI
2. Check dataset name spelling
3. Ensure correct project/workspace

### Database Storage Issues

**Problem**: SQLAlchemy DetachedInstanceError
```
Instance <EvaluationRun> is not bound to a Session
```
**Solution**: This should be fixed in latest version. If still occurring:
```python
# Use memory-only mode temporarily
evaluator = Evaluator(
    task=task,
    dataset="dataset", 
    metrics=["exact_match"]
    # Remove config parameter to disable storage
)
```

**Problem**: Database connection errors
```
sqlite3.OperationalError: database is locked
```
**Solution**:
1. Close other connections to database
2. Restart API server
3. Delete `llm_eval_runs.db` to reset (loses data)

**Problem**: Permission denied creating database
```
PermissionError: [Errno 13] Permission denied: 'llm_eval_runs.db'
```
**Solution**:
1. Check write permissions in current directory
2. Run from a writable location
3. Set custom database path:
```python
config = {
    "project_id": "my-project",
    "database_url": "sqlite:///path/to/writable/location/runs.db"
}
```

### API Server Issues

**Problem**: Port 8000 already in use
```
error while attempting to bind on address ('127.0.0.1', 8000)
```
**Solution**:
1. Kill existing server: `pkill -f "llm_eval.api.main"`
2. Use different port:
```python
from llm_eval.api.main import run_server
run_server(port=8001)
```

**Problem**: CORS errors in frontend
```
Access to XMLHttpRequest blocked by CORS policy
```
**Solution**: CORS is configured for localhost:3000. If using different port:
```python
# Add your frontend URL to CORS origins in main.py
allow_origins=["http://localhost:3001"]  # Add your port
```

### Evaluation Issues

**Problem**: Task function errors
```
TypeError: my_task() missing 1 required positional argument
```
**Solution**: Ensure task function accepts string input:
```python
def my_task(question: str) -> str:  # Must accept string
    return "answer"
```

**Problem**: Metric calculation errors
```
ValueError: Metric 'exact_match' failed
```
**Solution**:
1. Check metric function signature
2. Verify output types match expected inputs
3. Use custom error handling:
```python
def safe_metric(output, expected):
    try:
        return your_metric_logic(output, expected)
    except Exception as e:
        return {"error": str(e)}
```

**Problem**: Timeout errors
```
asyncio.TimeoutError: Evaluation timed out after 300s
```
**Solution**:
```python
evaluator = Evaluator(
    task=task,
    dataset="dataset",
    metrics=["exact_match"],
    timeout=600  # Increase timeout to 10 minutes
)
```

### Performance Issues

**Problem**: Slow evaluation performance
**Solution**:
1. Reduce concurrency if hitting API limits:
```python
evaluator = Evaluator(
    task=task,
    dataset="dataset", 
    metrics=["exact_match"],
    max_concurrency=5  # Reduce from default
)
```

2. Use faster metrics:
```python
# Fast metrics
metrics = ["exact_match", "response_time"]
# Avoid slow metrics like deep semantic similarity
```

**Problem**: Memory usage too high
**Solution**:
1. Process smaller batches
2. Disable detailed result storage:
```python
config = {
    "project_id": "my-project",
    "store_items": False  # Only store run metadata
}
```

### Visualization Issues

**Problem**: Charts not displaying properly
```
ValueError: Plotly figure contains invalid data
```
**Solution**:
1. Verify results contain metric data:
```python
print(results.get_metric_stats("exact_match"))
```

2. Check for missing or invalid scores
3. Use error handling:
```python
try:
    chart = charts.create_dashboard(results)
    chart.write_html("dashboard.html")
except Exception as e:
    print(f"Visualization error: {e}")
    # Fall back to basic charts
```

**Problem**: Excel export fails
```
ImportError: Missing optional dependency 'openpyxl'
```
**Solution**:
```bash
pip install openpyxl xlsxwriter
```

### Dashboard Issues

**Problem**: Frontend not connecting to API
```
Failed to fetch runs: Network error
```
**Solution**:
1. Verify API server is running:
```bash
curl http://localhost:8000/api/health/
```

2. Check CORS configuration
3. Verify correct API URL in frontend config

**Problem**: Runs not appearing in dashboard
**Solution**:
1. Verify runs are stored in database:
```python
from llm_eval.storage.run_repository import RunRepository
repo = RunRepository()
runs = repo.list_runs()
print(f"Found {len(runs)} runs")
```

2. Check browser console for errors
3. Clear browser cache

## Debug Mode

Enable detailed logging:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("llm_eval")
logger.setLevel(logging.DEBUG)
```

## Database Schema Reference

### evaluation_runs
- `id` (UUID): Primary key
- `name` (String): Run name  
- `status` (String): running|completed|failed|cancelled
- `dataset_name` (String): Source dataset
- `project_id` (String): Project identifier
- `created_at` (DateTime): Creation timestamp
- `metrics_used` (JSON): List of metrics evaluated

### evaluation_items  
- `id` (UUID): Primary key
- `run_id` (UUID): Foreign key to evaluation_runs
- `item_id` (String): Original dataset item ID
- `input_data` (JSON): Item input
- `actual_output` (Text): Model output
- `expected_output` (Text): Ground truth
- `scores` (JSON): Metric scores for this item
- `status` (String): completed|failed|skipped

### run_metrics
- `id` (UUID): Primary key  
- `run_id` (UUID): Foreign key to evaluation_runs
- `metric_name` (String): Metric identifier
- `mean_score` (Float): Average score
- `std_dev` (Float): Standard deviation
- `min_score` (Float): Minimum score
- `max_score` (Float): Maximum score
- `success_rate` (Float): Percentage of successful evaluations

## Getting Help

1. **Check logs**: Enable debug mode for detailed error information
2. **Verify setup**: Ensure all dependencies and credentials are configured
3. **Minimal reproduction**: Create a simple test case that reproduces the issue
4. **GitHub Issues**: Report bugs with full error traces and environment details

## Performance Benchmarks

**Typical performance expectations:**

| Dataset Size | Metrics | Expected Time | Memory Usage |
|--------------|---------|---------------|--------------|
| 10 items     | 2 basic | 5-10 seconds  | 50MB        |
| 100 items    | 2 basic | 30-60 seconds | 100MB       |
| 1000 items   | 2 basic | 5-10 minutes  | 200MB       |
| 100 items    | 5 complex| 2-5 minutes   | 150MB       |

**When performance is slower than expected:**
1. Check internet connectivity (for API-based metrics)
2. Verify API rate limits aren't being hit
3. Consider reducing concurrency
4. Profile task function performance