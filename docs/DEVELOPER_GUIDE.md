# LLM-Eval Developer Guide

This guide covers technical implementation details for developers working with LLM-Eval.

## Quick Start

```python
from llm_eval import Evaluator

# Basic evaluation
evaluator = Evaluator(
    task=your_function,
    dataset="your-dataset",
    metrics=["exact_match", "f1_score"]
)
results = evaluator.run()

# With UI storage (Sprint 2)
evaluator = Evaluator(
    task=your_function,
    dataset="your-dataset", 
    metrics=["exact_match", "f1_score"],
    config={"project_id": "your-project"}
)
results = evaluator.run()
```

## Langfuse Integration

### Dataset Setup
1. Create datasets in Langfuse UI
2. Add items with `input` and `expected_output` fields
3. Reference by name in Evaluator

### Tracing
All evaluations are automatically traced to Langfuse with:
- Individual item traces
- Metric scores
- Performance timing
- Error tracking

### Environment Variables
```bash
LANGFUSE_SECRET_KEY=your_secret_key
LANGFUSE_PUBLIC_KEY=your_public_key
LANGFUSE_HOST=https://cloud.langfuse.com  # or self-hosted
```

## Available Metrics

### Built-in Metrics
- `exact_match` - Exact string matching
- `f1_score` - Token-level F1 score
- `response_time` - Execution timing

### DeepEval Integration
- `answer_relevancy` - Answer relevance scoring
- `faithfulness` - Response faithfulness
- `contextual_recall` - Context utilization
- `contextual_precision` - Context accuracy

### Custom Metrics
```python
def my_custom_metric(output, expected):
    # Your scoring logic
    return score

evaluator = Evaluator(
    task=task,
    dataset="dataset",
    metrics=["exact_match", my_custom_metric]
)
```

## Template System

### Using Templates
```python
from llm_eval import get_template, recommend_template

# Get specific template
qa_template = get_template('qa')
evaluator = Evaluator.from_template(qa_template, task=your_task, dataset="dataset")

# AI recommendations
templates = recommend_template("I need to evaluate my chatbot")
```

### Available Templates
- `qa` - Question answering evaluation
- `rag` - RAG system evaluation
- `summarization` - Text summarization
- `classification` - Classification tasks

## Search & Filtering

### Smart Search
```python
from llm_eval.core.search import SearchEngine

search = SearchEngine()
results = search.search(evaluation_result, "failures")
results = search.search(evaluation_result, "f1_score > 0.8")
results = search.search(evaluation_result, "took more than 3 seconds")
```

### Query Syntax
- `failures` - Find failed items
- `metric > value` - Numeric comparisons
- `metric = value` - Exact matches
- `took more than X seconds` - Response time filters

## Visualizations

### Chart Generation
```python
from llm_eval.visualizations import ChartGenerator

charts = ChartGenerator()
dashboard = charts.create_dashboard(results)
distribution = charts.create_metric_distribution_chart(results, "f1_score")
timeline = charts.create_performance_timeline_chart(results)
```

### Excel Export
```python
from llm_eval.visualizations import ExcelChartExporter

exporter = ExcelChartExporter()
filepath = exporter.create_excel_report(
    results, 
    "evaluation_report.xlsx",
    include_charts=True
)
```

### Supported Chart Types
- Executive dashboards
- Metric distributions
- Performance timelines
- Correlation analysis
- Multi-metric comparisons

## Database Storage (Sprint 2)

### Enable Storage
```python
evaluator = Evaluator(
    task=task,
    dataset="dataset",
    metrics=["exact_match"],
    config={
        "project_id": "my-project",      # Required for storage
        "run_name": "test_run",          # Optional
        "tags": ["experiment", "v1"],    # Optional
        "created_by": "username"         # Optional
    }
)
```

### Database Schema
- **evaluation_runs**: Run metadata and statistics  
- **evaluation_items**: Individual item results
- **run_metrics**: Aggregated metric statistics
- **run_comparisons**: Cached comparison results

### Configuration Options
```python
config = {
    "project_id": "required",           # Enables storage
    "run_name": "optional",            # Custom run name
    "run_metadata": {"model": "gpt-4"}, # Custom metadata
    "tags": ["tag1", "tag2"],          # Organization tags
    "created_by": "username",          # User tracking
    "description": "Run description"    # Optional description
}
```

## API Reference

### REST Endpoints
- `GET /api/runs/` - List evaluation runs
- `GET /api/runs/{id}` - Get specific run
- `POST /api/runs/` - Create new run
- `PUT /api/runs/{id}` - Update run
- `DELETE /api/runs/{id}` - Delete run

### WebSocket Events
- `/ws` - General dashboard updates
- `/ws/{run_id}` - Run-specific progress

### Example API Usage
```bash
# List runs
curl http://localhost:8000/api/runs/

# Get specific run
curl http://localhost:8000/api/runs/{run_id}

# Filter runs
curl "http://localhost:8000/api/runs/?status=completed&project_id=my-project"
```

## Performance Optimization

### Async Evaluation
```python
# Automatic async handling
evaluator = Evaluator(task=async_task, dataset="dataset", metrics=["exact_match"])
results = evaluator.run()  # Handles async automatically
```

### Batch Processing
- Evaluations run in parallel by default
- Configurable concurrency limits
- Automatic timeout handling
- Progress tracking

### Memory Management
- Streaming results for large datasets
- Automatic cleanup of temporary data
- Efficient metric calculation

## Error Handling

### Common Issues
1. **Dataset not found**: Verify Langfuse dataset exists
2. **Metric errors**: Check metric function signatures
3. **Storage failures**: Verify database permissions
4. **API timeouts**: Adjust timeout configurations

### Debug Mode
```python
import logging
logging.getLogger("llm_eval").setLevel(logging.DEBUG)
```

### Error Recovery
- Automatic retry on transient failures
- Graceful handling of missing data
- Detailed error reporting with context

## Contributing

### Code Structure
```
llm_eval/
├── core/           # Core evaluation engine
├── metrics/        # Metric implementations  
├── templates/      # Evaluation templates
├── storage/        # Database storage
├── api/           # REST API endpoints
├── visualizations/ # Charts and reporting
└── utils/         # Utilities and helpers
```

### Development Setup
```bash
pip install -e .
pip install -e ".[dev]"  # Development dependencies
```

### Testing
```bash
pytest tests/
python -m pytest tests/unit/
python -m pytest tests/integration/
```