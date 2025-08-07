# API Reference - LLM-Eval v0.3.0

## Overview

This document provides comprehensive API reference for LLM-Eval, including all Sprint 1 features: Excel export, Smart search, Visualization system, and Templates.

## Core Classes

### Evaluator

The main evaluation class that orchestrates LLM evaluation workflows.

#### Constructor

```python
Evaluator(task, dataset, metrics, config=None)
```

**Parameters:**
- `task` (callable): Function to evaluate. Can be any Python function that takes input and returns output.
- `dataset` (str): Name of the Langfuse dataset to use for evaluation.
- `metrics` (List[Union[str, callable]]): List of metrics to compute. Can be metric names or custom functions.
- `config` (Dict[str, Any], optional): Configuration options for evaluation.

**Example:**
```python
evaluator = Evaluator(
    task=my_llm_function,
    dataset="qa-test-set",
    metrics=["exact_match", "answer_relevancy", my_custom_metric]
)
```

#### Methods

##### run()
```python
run(show_progress=True, show_table=True, auto_save=False, save_format="json") -> EvaluationResult
```

Execute the evaluation process.

**Parameters:**
- `show_progress` (bool): Display real-time progress updates. Default: True
- `show_table` (bool): Show detailed results table during evaluation. Default: True  
- `auto_save` (bool): Automatically save results after evaluation. Default: False
- `save_format` (str): Format for auto-save ("json", "csv", "excel"). Default: "json"

**Returns:** `EvaluationResult` object containing all evaluation data.

**Example:**
```python
# Basic usage
results = evaluator.run()

# With Excel auto-save (Sprint 1)
results = evaluator.run(auto_save=True, save_format="excel")
```

##### from_template() [Static Method - Sprint 1]
```python
@staticmethod
from_template(template, task, dataset, custom_metrics=None, config=None) -> Evaluator
```

Create an evaluator using a pre-built template.

**Parameters:**
- `template` (EvaluationTemplate): Template object from `get_template()`
- `task` (callable): Function to evaluate
- `dataset` (str): Dataset name
- `custom_metrics` (List, optional): Additional metrics to include
- `config` (Dict, optional): Override template configuration

**Returns:** Configured `Evaluator` instance.

**Example:**
```python
qa_template = get_template('qa')
evaluator = Evaluator.from_template(
    qa_template,
    task=my_qa_function,
    dataset="qa-test"
)
```

### EvaluationResult

Container for evaluation results with analysis and export capabilities.

#### Properties

- `total_items` (int): Total number of evaluation items
- `success_rate` (float): Percentage of successful evaluations (0.0-1.0)
- `avg_time` (float): Average processing time per item in seconds
- `avg_scores` (Dict[str, float]): Average scores for each metric
- `results` (Dict): Detailed results for each evaluation item
- `errors` (Dict): Error information for failed evaluations
- `metrics` (List[str]): List of metric names used
- `duration` (float): Total evaluation time in seconds

#### Methods

##### save_excel() [Sprint 1]
```python
save_excel(filepath=None) -> str
```

Export evaluation results to Excel format with professional formatting and embedded charts.

**Parameters:**
- `filepath` (str, optional): Target file path. If None, generates timestamped filename.

**Returns:** Path to the created Excel file.

**Features:**
- Multiple worksheets (Results, Summary, Charts)
- Professional formatting with colors and borders
- Embedded charts for visual analysis
- Statistical summaries

**Example:**
```python
# Auto-generated filename
excel_path = results.save_excel()

# Custom filename  
excel_path = results.save_excel("evaluation_report.xlsx")
```

##### save_json()
```python
save_json(filepath=None) -> str
```

Export results to JSON format.

**Parameters:**
- `filepath` (str, optional): Target file path.

**Returns:** Path to the created JSON file.

##### save_csv()
```python
save_csv(filepath=None) -> str
```

Export results to CSV format.

**Parameters:**
- `filepath` (str, optional): Target file path.

**Returns:** Path to the created CSV file.

##### summary()
```python
summary() -> str
```

Generate a human-readable summary of evaluation results.

**Returns:** Formatted summary string.

**Example:**
```python
print(results.summary())
# Output:
# Evaluation Summary
# ==================
# Dataset: qa-test-set
# Total Items: 100
# Success Rate: 95.0%
# Average Processing Time: 1.2s
# ...
```

## Search System [Sprint 1]

### SearchEngine

Natural language query interface for filtering evaluation results.

#### Constructor
```python
SearchEngine(query_parser=None)
```

**Parameters:**
- `query_parser` (SearchQueryParser, optional): Custom query parser instance.

#### Methods

##### search()
```python
search(evaluation_result, query) -> Dict
```

Filter evaluation results using natural language queries.

**Parameters:**
- `evaluation_result` (EvaluationResult): Results to search
- `query` (str): Natural language query

**Returns:** Dictionary with search results and metadata.

**Result Structure:**
```python
{
    'total_matches': int,
    'matched_items': List[str],      # IDs of matching successful items
    'matched_errors': List[str],     # IDs of matching failed items  
    'query_info': {
        'original_query': str,
        'parsed': bool,
        'filters': List[Dict]        # Applied filters
    }
}
```

**Supported Query Types:**
- Status queries: "failures", "successes", "errors"
- Metric comparisons: "accuracy > 0.8", "high relevancy scores"
- Performance filters: "slow responses", "took more than 3 seconds"
- Range queries: "between 1 and 3 seconds"

**Example:**
```python
search = SearchEngine()

# Find failures
failures = search.search(results, "show me failures")
print(f"Found {failures['total_matches']} failed items")

# Find high-performing items
high_acc = search.search(results, "accuracy above 0.8")

# Complex queries
slow_accurate = search.search(results, "accuracy > 0.9 and took more than 2 seconds")
```

##### get_suggestions()
```python
get_suggestions(evaluation_result) -> List[str]
```

Generate intelligent query suggestions based on evaluation data.

**Parameters:**
- `evaluation_result` (EvaluationResult): Results to analyze

**Returns:** List of suggested query strings.

**Example:**
```python
suggestions = search.get_suggestions(results)
for suggestion in suggestions:
    print(f"• {suggestion}")
# Output:
# • Show me failures
# • Find accuracy scores above 0.8  
# • Show me slow responses (>3.0s)
# • Find perfect exact matches
```

### SearchQueryParser

Low-level query parsing functionality.

#### Constructor
```python
SearchQueryParser(default_thresholds=None, metric_aliases=None)
```

**Parameters:**
- `default_thresholds` (Dict, optional): Custom threshold values
- `metric_aliases` (Dict, optional): Custom metric name mappings

#### Properties
- `default_thresholds` (Dict): Threshold values for natural language terms
- `metric_aliases` (Dict): Metric name variations and aliases

## Template System [Sprint 1]

### Template Functions

#### get_template()
```python
get_template(template_name) -> EvaluationTemplate
```

Retrieve a pre-built evaluation template.

**Parameters:**
- `template_name` (str): Template identifier ("qa", "summarization", "classification", "general")

**Returns:** `EvaluationTemplate` instance.

**Available Templates:**
- `"qa"`: Question-answering systems
- `"summarization"`: Text summarization  
- `"classification"`: Text classification
- `"general"`: General-purpose evaluation

**Example:**
```python
qa_template = get_template('qa')
print(qa_template.config.description)
print(qa_template.get_metrics())
```

#### recommend_template()
```python
recommend_template(description) -> List[Dict]
```

Get template recommendations based on use case description.

**Parameters:**
- `description` (str): Description of your evaluation needs

**Returns:** List of recommendations ordered by confidence score.

**Recommendation Structure:**
```python
[
    {
        'name': str,           # Template name
        'confidence': float,   # Confidence score (0.0-1.0)
        'metrics': List[str],  # Included metrics
        'reason': str         # Why this template was recommended
    }
]
```

**Example:**
```python
recs = recommend_template("I want to evaluate my Q&A chatbot")
best_template = get_template(recs[0]['name'])
```

#### print_available_templates()
```python
print_available_templates() -> None
```

Display all available templates with descriptions.

**Example:**
```python
print_available_templates()
# Output:
# Available Evaluation Templates:
# ==============================
# 
# qa - Question & Answer Evaluation
#   Description: Comprehensive evaluation for question-answering systems
#   Metrics: answer_relevancy, faithfulness, exact_match, response_time
#   Use Cases: Chatbots, FAQ systems, virtual assistants
# ...
```

### EvaluationTemplate

Base class for evaluation templates.

#### Properties
- `config` (TemplateConfig): Template configuration and metadata
- `name` (str): Template name
- `description` (str): Template description

#### Methods

##### get_metrics()
```python
get_metrics() -> List[Union[str, callable]]
```

Get the list of metrics included in this template.

**Returns:** List of metric names and/or functions.

##### get_sample_data()
```python
get_sample_data() -> List[Dict]
```

Get sample evaluation data for testing (if available).

**Returns:** List of sample data items.

## Visualization System [Sprint 1]

### ChartGenerator

Professional chart and dashboard creation for evaluation results.

#### Constructor
```python
ChartGenerator(theme="plotly", primary_color=None, secondary_color=None)
```

**Parameters:**
- `theme` (str): Chart theme ("plotly", "plotly_white", "plotly_dark", "ggplot2")
- `primary_color` (str, optional): Primary color for charts
- `secondary_color` (str, optional): Secondary color for charts

#### Methods

##### create_dashboard()
```python
create_dashboard(evaluation_result, title=None) -> plotly.graph_objects.Figure
```

Create comprehensive executive dashboard.

**Parameters:**
- `evaluation_result` (EvaluationResult): Results to visualize
- `title` (str, optional): Dashboard title

**Returns:** Interactive Plotly figure.

**Dashboard Components:**
- Success rate overview
- Metric score distributions
- Performance timeline
- Error analysis
- Statistical summaries

**Example:**
```python
charts = ChartGenerator()
dashboard = charts.create_dashboard(results)
dashboard.show()  # Display in browser
dashboard.write_html("dashboard.html")  # Save to file
```

##### create_metric_distribution_chart()
```python
create_metric_distribution_chart(evaluation_result, metric_name) -> plotly.graph_objects.Figure
```

Create distribution chart for a specific metric.

**Parameters:**
- `evaluation_result` (EvaluationResult): Results to analyze
- `metric_name` (str): Name of metric to visualize

**Returns:** Plotly histogram/distribution chart.

##### create_performance_timeline_chart()
```python
create_performance_timeline_chart(evaluation_result) -> plotly.graph_objects.Figure
```

Create timeline showing evaluation performance over time.

**Parameters:**
- `evaluation_result` (EvaluationResult): Results to visualize

**Returns:** Plotly timeline chart.

##### create_metric_correlation_chart()
```python
create_metric_correlation_chart(evaluation_result, metric1, metric2) -> plotly.graph_objects.Figure
```

Analyze correlation between two metrics.

**Parameters:**
- `evaluation_result` (EvaluationResult): Results to analyze
- `metric1` (str): First metric name
- `metric2` (str): Second metric name

**Returns:** Plotly scatter plot with correlation analysis.

##### create_multi_metric_comparison_chart()
```python
create_multi_metric_comparison_chart(evaluation_result, chart_type="radar") -> plotly.graph_objects.Figure
```

Compare performance across multiple metrics.

**Parameters:**
- `evaluation_result` (EvaluationResult): Results to analyze
- `chart_type` (str): Chart type ("radar", "bar", "heatmap")

**Returns:** Plotly comparison chart.

### ExcelChartExporter

Export evaluation results to Excel with embedded charts.

#### Methods

##### create_excel_report()
```python
create_excel_report(evaluation_result, filepath, include_raw_data=True, include_charts=True) -> str
```

Create comprehensive Excel report with embedded visualizations.

**Parameters:**
- `evaluation_result` (EvaluationResult): Results to export
- `filepath` (str): Output Excel file path
- `include_raw_data` (bool): Include raw data worksheet
- `include_charts` (bool): Include charts worksheet

**Returns:** Path to created Excel file.

**Excel Structure:**
- **Summary** worksheet: Key statistics and overview
- **Results** worksheet: Detailed evaluation data
- **Charts** worksheet: Embedded visualizations (if enabled)

### Utility Functions

#### create_evaluation_report()
```python
create_evaluation_report(evaluation_result, output_dir, formats=["html"], include_charts=["dashboard"]) -> Dict[str, str]
```

Generate comprehensive evaluation reports in multiple formats.

**Parameters:**
- `evaluation_result` (EvaluationResult): Results to report
- `output_dir` (str): Output directory for reports
- `formats` (List[str]): Export formats ("html", "excel", "png", "pdf")
- `include_charts` (List[str]): Chart types to include

**Returns:** Dictionary mapping format names to file paths.

#### quick_chart()
```python
quick_chart(evaluation_result, chart_type, metric=None, save_path=None, format="html") -> str
```

Rapidly create and save a single chart.

**Parameters:**
- `evaluation_result` (EvaluationResult): Results to visualize
- `chart_type` (str): Type of chart ("dashboard", "distribution", "timeline", "correlation")
- `metric` (str, optional): Metric name (required for "distribution")
- `save_path` (str, optional): Output file path
- `format` (str): Output format ("html", "png", "pdf")

**Returns:** Path to created chart file.

## Metrics

### Built-in Metrics

#### Built-in String Metrics
- `"exact_match"`: Perfect string matching
- `"response_time"`: Processing time measurement
- `"success_rate"`: Success/failure tracking

#### DeepEval Integration
When `deepeval` is installed, additional metrics are available:
- `"answer_relevancy"`: How relevant is the answer to the question
- `"faithfulness"`: Faithfulness to provided context
- `"hallucination"`: Detection of hallucinated content
- `"bias"`: Bias detection in responses
- `"toxicity"`: Toxicity assessment

### Custom Metrics

#### Function-Based Metrics
```python
def my_custom_metric(output: str, expected: str = None, input_data: str = None) -> float:
    """
    Custom metric function.
    
    Args:
        output: Generated output from your task
        expected: Expected/reference output (if available)
        input_data: Original input to the task (if needed)
        
    Returns:
        float: Score between 0.0 and 1.0
    """
    # Your metric logic here
    return score

# Use in evaluator
evaluator = Evaluator(
    task=my_function,
    dataset="test-set", 
    metrics=["exact_match", my_custom_metric]
)
```

#### Class-Based Metrics
```python
class MyComplexMetric:
    def __init__(self, threshold=0.5):
        self.threshold = threshold
    
    def __call__(self, output: str, expected: str = None, input_data: str = None) -> float:
        # Complex metric logic
        return self.calculate_score(output, expected, input_data)
    
    def calculate_score(self, output, expected, input_data):
        # Implementation
        pass

# Use in evaluator
complex_metric = MyComplexMetric(threshold=0.7)
evaluator = Evaluator(
    task=my_function,
    dataset="test-set",
    metrics=["exact_match", complex_metric]
)
```

## Configuration

### Evaluator Configuration
```python
config = {
    "batch_size": 10,           # Process items in batches
    "max_concurrent": 5,        # Maximum concurrent evaluations
    "timeout": 30.0,           # Timeout per evaluation (seconds)
    "retry_attempts": 3,        # Retry failed evaluations
    "save_intermediate": True,  # Save results during evaluation
    "progress_update_interval": 1.0  # Progress update frequency
}

evaluator = Evaluator(
    task=my_function,
    dataset="test-set",
    metrics=["exact_match"],
    config=config
)
```

### Environment Variables
```bash
# Langfuse configuration
LANGFUSE_PUBLIC_KEY=your_public_key
LANGFUSE_SECRET_KEY=your_secret_key
LANGFUSE_HOST=https://cloud.langfuse.com  # Optional, defaults to cloud

# OpenAI (for DeepEval metrics)
OPENAI_API_KEY=your_openai_key

# Evaluation settings
LLM_EVAL_DEFAULT_BATCH_SIZE=10
LLM_EVAL_DEFAULT_TIMEOUT=30
LLM_EVAL_CACHE_RESULTS=true
```

## Error Handling

### Common Exceptions

#### LangfuseConnectionError
Raised when connection to Langfuse fails.

```python
from llm_eval.utils.errors import LangfuseConnectionError

try:
    evaluator = Evaluator(task=my_function, dataset="test-set", metrics=["exact_match"])
    results = evaluator.run()
except LangfuseConnectionError as e:
    print(f"Langfuse connection failed: {e}")
    # Handle connection issues
```

#### DatasetNotFoundError
Raised when specified dataset doesn't exist in Langfuse.

```python
from llm_eval.utils.errors import DatasetNotFoundError

try:
    evaluator = Evaluator(task=my_function, dataset="nonexistent-dataset", metrics=["exact_match"])
    results = evaluator.run()
except DatasetNotFoundError as e:
    print(f"Dataset not found: {e}")
    # Handle missing dataset
```

#### MetricError
Raised when metric computation fails.

```python
try:
    results = evaluator.run()
except Exception as e:
    if "metric" in str(e).lower():
        print(f"Metric computation failed: {e}")
        # Handle metric errors
```

### Best Practices

1. **Always handle connection errors** when working with Langfuse
2. **Validate dataset existence** before running large evaluations
3. **Test custom metrics** with sample data before full evaluation
4. **Use timeouts** for evaluations that might hang
5. **Enable auto-save** for long-running evaluations

## Migration Guide

### From v0.2.x to v0.3.0

#### New Features Available
- Excel export with `save_excel()`
- Template system with `get_template()` and `Evaluator.from_template()`
- Smart search with `SearchEngine`
- Visualization system with `ChartGenerator`

#### Breaking Changes
None. All v0.2.x code continues to work unchanged.

#### Recommended Updates
```python
# OLD: Basic CSV export
results = evaluator.run()
results.save_csv("results.csv")

# NEW: Professional Excel reports
results = evaluator.run(auto_save=True, save_format="excel")

# OLD: Manual metric selection
evaluator = Evaluator(
    task=my_qa_function,
    dataset="qa-test",
    metrics=["exact_match", "answer_relevancy"]
)

# NEW: Template-based setup
qa_template = get_template('qa')
evaluator = Evaluator.from_template(qa_template, task=my_qa_function, dataset="qa-test")
```

#### Installation Updates
```bash
# OLD: Basic installation
pip install llm-eval

# NEW: With visualization features
pip install llm-eval[viz]

# Or full installation
pip install llm-eval[all]
```

## Performance Considerations

### Large Datasets
- Use `batch_size` configuration for memory management
- Enable `save_intermediate` for crash recovery
- Consider `max_concurrent` limits for API rate limits

### Memory Usage
- Excel export uses ~92KB per 1000 evaluation items
- Visualization charts cache data - call `clear_cache()` for large datasets
- Search operations are optimized for datasets up to 100K items

### Processing Speed
- Excel export: ~6,500 items/second
- Search queries: <100ms for most datasets
- Chart generation: 1-5 seconds depending on complexity

This API reference covers all major functionality in LLM-Eval v0.3.0. For additional examples and tutorials, see the [Examples](../examples/) directory and [User Guide](USER_GUIDE.md).