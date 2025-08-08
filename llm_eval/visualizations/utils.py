"""Utility functions for visualization integration."""

import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .charts import ChartGenerator
from .excel_export import ExcelChartExporter

# EvaluationResult will be passed as parameter to avoid circular imports


def create_evaluation_report(
    results,  # EvaluationResult object
    output_dir: str = "./reports",
    formats: List[str] = ["html", "excel"],
    include_charts: List[str] = [
        "dashboard",
        "distributions",
        "timeline",
        "correlations",
    ],
) -> Dict[str, str]:
    """
    Create comprehensive evaluation report with charts.

    Args:
        results: EvaluationResult object
        output_dir: Output directory for reports
        formats: List of output formats ("html", "excel", "png", "pdf")
        include_charts: List of chart types to include

    Returns:
        Dictionary mapping format to output file path
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate base filename
    safe_run_name = "".join(
        c for c in results.run_name if c.isalnum() or c in ("-", "_")
    ).rstrip()
    base_filename = f"eval_report_{safe_run_name}"

    chart_gen = ChartGenerator()
    output_files = {}

    # HTML Report with interactive charts
    if "html" in formats:
        html_file = output_dir / f"{base_filename}.html"

        # Generate HTML content
        html_content = _generate_html_report(results, chart_gen, include_charts)

        with open(html_file, "w", encoding="utf-8") as f:
            f.write(html_content)

        output_files["html"] = str(html_file)

    # Excel Report with embedded charts
    if "excel" in formats:
        excel_file = output_dir / f"{base_filename}.xlsx"

        try:
            excel_exporter = ExcelChartExporter()
            excel_path = excel_exporter.create_excel_report(
                results, str(excel_file), include_raw_data=True, include_charts=True
            )
            output_files["excel"] = excel_path
        except ImportError:
            print("Warning: openpyxl not available. Skipping Excel export.")

    # Static image exports
    if any(fmt in formats for fmt in ["png", "pdf", "svg"]):
        for fmt in ["png", "pdf", "svg"]:
            if fmt in formats:
                # Create dashboard chart
                if "dashboard" in include_charts:
                    dashboard = chart_gen.create_dashboard(results)
                    img_file = output_dir / f"{base_filename}_dashboard.{fmt}"
                    chart_gen.save_chart(dashboard, str(img_file), format=fmt)
                    output_files[f"dashboard_{fmt}"] = str(img_file)

    return output_files


def _generate_html_report(
    results,  # EvaluationResult object
    chart_gen: ChartGenerator,
    include_charts: List[str],
) -> str:
    """Generate HTML report content with embedded Plotly charts."""

    html_parts = [
        """
<!DOCTYPE html>
<html>
<head>
    <title>LLM Evaluation Report</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 40px;
            background-color: #f8f9fa;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background-color: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #2E86AB;
            border-bottom: 3px solid #2E86AB;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #343A40;
            margin-top: 40px;
            margin-bottom: 20px;
        }}
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }}
        .summary-card {{
            background-color: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #2E86AB;
        }}
        .summary-card h3 {{
            margin: 0 0 10px 0;
            color: #343A40;
        }}
        .summary-card .value {{
            font-size: 24px;
            font-weight: bold;
            color: #2E86AB;
        }}
        .chart-container {{
            margin: 30px 0;
            padding: 20px;
            background-color: #f8f9fa;
            border-radius: 8px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>LLM Evaluation Report: {run_name}</h1>

        <div class="summary-grid">
            <div class="summary-card">
                <h3>Dataset</h3>
                <div class="value">{dataset_name}</div>
            </div>
            <div class="summary-card">
                <h3>Total Items</h3>
                <div class="value">{total_items}</div>
            </div>
            <div class="summary-card">
                <h3>Success Rate</h3>
                <div class="value">{success_rate:.1%}</div>
            </div>
            <div class="summary-card">
                <h3>Duration</h3>
                <div class="value">{duration:.1f}s</div>
            </div>
        </div>
        """.format(
            run_name=results.run_name,
            dataset_name=results.dataset_name,
            total_items=results.total_items,
            success_rate=results.success_rate,
            duration=results.duration if results.duration else 0,
        )
    ]

    # Add charts
    chart_id = 0

    if "dashboard" in include_charts:
        dashboard = chart_gen.create_dashboard(results)
        html_parts.append(
            f"""
        <h2>Executive Dashboard</h2>
        <div class="chart-container">
            <div id="chart_{chart_id}"></div>
        </div>
        <script>
            Plotly.newPlot('chart_{chart_id}', {dashboard.to_json()});
        </script>
        """
        )
        chart_id += 1

    if "timeline" in include_charts:
        timeline = chart_gen.create_performance_timeline_chart(results)
        html_parts.append(
            f"""
        <h2>Performance Timeline</h2>
        <div class="chart-container">
            <div id="chart_{chart_id}"></div>
        </div>
        <script>
            Plotly.newPlot('chart_{chart_id}', {timeline.to_json()});
        </script>
        """
        )
        chart_id += 1

    if "distributions" in include_charts:
        for metric in results.metrics:
            dist_chart = chart_gen.create_metric_distribution_chart(results, metric)
            html_parts.append(
                f"""
            <h2>Distribution: {metric}</h2>
            <div class="chart-container">
                <div id="chart_{chart_id}"></div>
            </div>
            <script>
                Plotly.newPlot('chart_{chart_id}', {dist_chart.to_json()});
            </script>
            """
            )
            chart_id += 1

    if "correlations" in include_charts and len(results.metrics) >= 2:
        # Create correlation matrix for all metric pairs
        metrics = results.metrics
        for i in range(len(metrics)):
            for j in range(i + 1, len(metrics)):
                corr_chart = chart_gen.create_metric_correlation_chart(
                    results, metrics[i], metrics[j]
                )
                html_parts.append(
                    f"""
                <h2>Correlation: {metrics[i]} vs {metrics[j]}</h2>
                <div class="chart-container">
                    <div id="chart_{chart_id}"></div>
                </div>
                <script>
                    Plotly.newPlot('chart_{chart_id}', {corr_chart.to_json()});
                </script>
                """
                )
                chart_id += 1

    # Close HTML
    html_parts.append(
        """
    </div>
</body>
</html>
    """
    )

    return "".join(html_parts)


def add_charts_to_results(results):  # EvaluationResult object
    """
    Add chart generation methods to EvaluationResult instance.

    Args:
        results: EvaluationResult object

    Returns:
        Enhanced EvaluationResult with chart methods
    """
    chart_gen = ChartGenerator()

    # Add chart generation methods
    results.create_dashboard = lambda: chart_gen.create_dashboard(results)
    results.create_metric_distribution = (
        lambda metric: chart_gen.create_metric_distribution_chart(results, metric)
    )
    results.create_timeline = lambda: chart_gen.create_performance_timeline_chart(
        results
    )
    results.create_correlation = (
        lambda m1, m2: chart_gen.create_metric_correlation_chart(results, m1, m2)
    )
    results.create_report = lambda **kwargs: create_evaluation_report(results, **kwargs)

    return results


def quick_chart(
    results,  # EvaluationResult object
    chart_type: str = "dashboard",
    metric: Optional[str] = None,
    save_path: Optional[str] = None,
    format: str = "html",
) -> Union[str, Any]:
    """
    Quick chart generation utility.

    Args:
        results: EvaluationResult object
        chart_type: Type of chart ("dashboard", "distribution", "timeline", "correlation")
        metric: Metric name (required for distribution charts)
        save_path: Optional path to save chart
        format: Output format ("html", "png", "pdf", "svg")

    Returns:
        Chart object or path to saved file
    """
    chart_gen = ChartGenerator()

    if chart_type == "dashboard":
        fig = chart_gen.create_dashboard(results)
    elif chart_type == "distribution":
        if not metric:
            raise ValueError("Metric name required for distribution chart")
        fig = chart_gen.create_metric_distribution_chart(results, metric)
    elif chart_type == "timeline":
        fig = chart_gen.create_performance_timeline_chart(results)
    elif chart_type == "correlation":
        if not metric or len(results.metrics) < 2:
            raise ValueError("Need at least 2 metrics for correlation chart")
        # Use first two metrics if not specified
        metrics = results.metrics[:2]
        fig = chart_gen.create_metric_correlation_chart(results, metrics[0], metrics[1])
    else:
        raise ValueError(f"Unknown chart type: {chart_type}")

    if save_path:
        return chart_gen.save_chart(fig, save_path, format=format)
    else:
        return fig
