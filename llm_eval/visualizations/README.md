# LLM Evaluation Visualization System

A comprehensive visualization system for LLM evaluation results, designed for executive reports and data analysis.

## Overview

The visualization system provides:

- **Interactive Charts**: Plotly-based charts for web viewing and exploration
- **Excel Reports**: Professional Excel exports with embedded charts  
- **Executive Dashboard**: Comprehensive overview charts for presentations
- **Statistical Analysis**: Distribution, correlation, and performance visualizations

## Quick Start

### Basic Usage

```python
from llm_eval import Evaluator

# Run evaluation
evaluator = Evaluator(task, dataset, metrics)
results = evaluator.run()

# Create dashboard
dashboard = results.create_dashboard()
dashboard.show()  # Display in browser

# Create comprehensive report
reports = results.create_evaluation_report(
    output_dir="./reports",
    formats=["html", "excel"],
    include_charts=["dashboard", "distributions", "timeline"]
)
```

### Advanced Visualization

```python
# Individual chart types
accuracy_dist = results.create_metric_distribution_chart("accuracy", "histogram")
timeline = results.create_performance_timeline_chart()
correlation = results.create_correlation_chart("accuracy", "relevance")

# Export to Excel with charts
excel_path = results.export_to_excel_with_charts("evaluation_report.xlsx")

# Quick utilities
from llm_eval.visualizations.utils import quick_chart
quick_chart(results, "dashboard", save_path="quick_dash.html")
```

## Chart Types

### 1. Executive Dashboard
- **Purpose**: Comprehensive overview for presentations
- **Contains**: Success rates, performance timeline, metric comparison, key statistics
- **Best for**: Executive summaries, stakeholder reports

```python
dashboard = results.create_dashboard()
```

### 2. Metric Distribution Charts
- **Purpose**: Analyze score distributions for individual metrics
- **Types**: Histogram, box plot, violin plot
- **Best for**: Understanding metric behavior, identifying outliers

```python
# Histogram
dist_chart = results.create_metric_distribution_chart("accuracy", "histogram")

# Box plot for outlier detection
box_chart = results.create_metric_distribution_chart("response_time", "box")
```

### 3. Performance Timeline
- **Purpose**: Track response times over evaluation sequence
- **Features**: Moving averages, mean lines, performance trends
- **Best for**: Identifying performance degradation, system load analysis

```python
timeline = results.create_performance_timeline_chart()
```

### 4. Correlation Analysis
- **Purpose**: Explore relationships between metrics
- **Features**: Scatter plots, trend lines, correlation coefficients
- **Best for**: Understanding metric interdependencies

```python
correlation = results.create_correlation_chart("accuracy", "relevance")
```

### 5. Multi-Metric Comparison
- **Purpose**: Compare performance across all metrics
- **Types**: Radar chart, bar chart, line chart
- **Best for**: Holistic performance assessment

```python
# Radar chart for comprehensive view
radar = results.create_multi_metric_comparison_chart("radar")

# Bar chart for direct comparison
bars = results.create_multi_metric_comparison_chart("bar")
```

## Excel Integration

### Features
- **Multiple Worksheets**: Summary, detailed results, charts
- **Professional Styling**: Executive-ready formatting
- **Embedded Charts**: Native Excel charts with data
- **Conditional Formatting**: Success/failure highlighting

### Usage

```python
# Method 1: Direct Excel export
excel_path = results.export_to_excel_with_charts(
    "evaluation_report.xlsx",
    include_raw_data=True,
    include_charts=True
)

# Method 2: Using ExcelChartExporter directly
from llm_eval.visualizations import ExcelChartExporter

exporter = ExcelChartExporter()
excel_path = exporter.create_excel_report(results, "report.xlsx")
```

## Comprehensive Reports

### HTML Reports
- **Interactive Charts**: Full Plotly functionality
- **Professional Styling**: Executive-ready presentation
- **Responsive Design**: Works on all devices

### Multi-Format Export

```python
reports = results.create_evaluation_report(
    output_dir="./reports",
    formats=["html", "excel", "png", "pdf"],
    include_charts=[
        "dashboard",      # Executive overview
        "distributions",  # All metric distributions
        "timeline",       # Performance timeline
        "correlations"    # All metric correlations
    ]
)

# Returns: {"html": "path/to/report.html", "excel": "path/to/report.xlsx", ...}
```

## Professional Styling

### Color Palette
- **Primary**: Professional blue (#2E86AB)
- **Secondary**: Accent purple (#A23B72)  
- **Success**: Warm orange (#F18F01)
- **Warning**: Alert red (#C73E1D)
- **Neutral**: Professional gray (#6C757D)

### Typography
- **Font Family**: Arial, sans-serif
- **Headers**: Bold, appropriately sized
- **Data**: Clear, readable formatting

### Layout
- **Executive Focus**: Clean, uncluttered design
- **Consistent Spacing**: Professional appearance
- **Responsive**: Works across devices and formats

## Integration Examples

### Jupyter Notebooks

```python
# Display charts inline
results.show_dashboard()

# Save for presentation
dashboard = results.create_dashboard()
dashboard.write_html("presentation_dashboard.html")
```

### Automated Reporting

```python
def generate_weekly_report(evaluation_results):
    """Generate standardized weekly evaluation report."""
    
    reports = evaluation_results.create_evaluation_report(
        output_dir=f"./reports/week_{datetime.now().strftime('%Y_%U')}",
        formats=["html", "excel"],
        include_charts=["dashboard", "distributions", "timeline"]
    )
    
    return reports

# Use in automated pipelines
weekly_reports = generate_weekly_report(results)
send_email_with_attachments(weekly_reports)
```

### Custom Chart Styling

```python
# Custom theme
from llm_eval.visualizations import ChartGenerator

chart_gen = ChartGenerator(theme='minimal')
custom_dashboard = chart_gen.create_dashboard(results)

# Save with custom dimensions
chart_gen.save_chart(
    custom_dashboard, 
    "custom_report.png",
    format="png",
    width=1920, 
    height=1080
)
```

## Dependencies

### Required
- **Core**: Built into llm_eval package

### Optional (for full functionality)
- **plotly**: Interactive charts (`pip install plotly`)
- **openpyxl**: Excel export (`pip install openpyxl`)
- **pandas**: Enhanced data handling (`pip install pandas`)

### Installation

```bash
# Minimal (basic functionality)
pip install llm-eval

# Full visualization support
pip install llm-eval[viz]
# or
pip install plotly openpyxl pandas
```

## Error Handling

The system gracefully handles missing dependencies:

```python
try:
    dashboard = results.create_dashboard()
except ImportError as e:
    print(f"Install plotly for visualizations: {e}")
    # Fallback to text summary
    print(results.summary())
```

## Performance Considerations

### Large Datasets
- **Automatic Sampling**: Charts automatically sample large datasets
- **Aggregation**: Statistical summaries for performance
- **Lazy Loading**: Dependencies loaded only when needed

### Memory Usage
- **Efficient Rendering**: Optimized for large evaluation runs
- **Streaming**: Large Excel exports use streaming
- **Cleanup**: Automatic resource cleanup

## Troubleshooting

### Common Issues

1. **Import Error**: Install required dependencies
   ```bash
   pip install plotly openpyxl
   ```

2. **Empty Charts**: Ensure evaluation results contain valid data
   ```python
   print(f"Results: {len(results.results)}, Errors: {len(results.errors)}")
   ```

3. **Excel Errors**: Check file permissions and disk space

4. **Display Issues**: For Jupyter, ensure widgets are enabled
   ```bash
   jupyter nbextension enable --py widgetsnbextension
   ```

## API Reference

### EvaluationResult Methods
- `create_dashboard(**kwargs)` - Executive dashboard
- `create_metric_distribution_chart(metric, type)` - Distribution analysis
- `create_performance_timeline_chart()` - Response time timeline
- `create_correlation_chart(metric1, metric2)` - Correlation analysis
- `create_multi_metric_comparison_chart(type)` - Multi-metric comparison
- `create_evaluation_report(**kwargs)` - Comprehensive reports
- `export_to_excel_with_charts(filename)` - Excel export
- `show_dashboard()` - Display dashboard immediately

### Utilities
- `quick_chart(results, type, **kwargs)` - Quick chart generation
- `create_evaluation_report(results, **kwargs)` - Multi-format reports

For detailed API documentation, see the docstrings in each module.