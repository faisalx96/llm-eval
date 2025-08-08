"""
Demonstration of LLM Evaluation Visualization System

This script shows how to use the visualization system with sample data
to create professional charts and reports for executive presentations.
"""

import sys
import os
from datetime import datetime
import random
import numpy as np

# Add the parent directory to the path so we can import llm_eval
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_eval.core.results import EvaluationResult
from llm_eval.visualizations import ChartGenerator, ExcelChartExporter
from llm_eval.visualizations.utils import create_evaluation_report, quick_chart


def create_sample_results() -> EvaluationResult:
    """Create sample evaluation results for demonstration."""

    # Create EvaluationResult instance
    results = EvaluationResult(
        dataset_name="qa-benchmark-v2",
        run_name="gpt-4-evaluation-2024",
        metrics=["accuracy", "relevance", "coherence", "response_time"]
    )

    # Simulate evaluation results
    num_items = 50

    for i in range(num_items):
        # Simulate different performance patterns
        if i < 40:  # Most items succeed
            # Generate correlated metric scores (better models tend to score well across metrics)
            base_performance = random.uniform(0.6, 0.95)
            noise = random.uniform(-0.1, 0.1)

            scores = {
                "accuracy": max(0, min(1, base_performance + random.uniform(-0.05, 0.05))),
                "relevance": max(0, min(1, base_performance + random.uniform(-0.1, 0.1))),
                "coherence": max(0, min(1, base_performance + random.uniform(-0.08, 0.08))),
                "response_time": random.uniform(0.5, 3.0)  # Independent of quality
            }

            result = {
                "output": f"Generated response for question {i+1}...",
                "scores": scores,
                "success": True,
                "time": scores["response_time"]
            }

            results.add_result(f"item_{i:03d}", result)

        else:  # Some items fail
            error_msg = random.choice([
                "Connection timeout",
                "Rate limit exceeded",
                "Invalid API response",
                "Model overloaded"
            ])
            results.add_error(f"item_{i:03d}", error_msg)

    # Mark as finished
    results.finish()

    return results


def demonstrate_chart_generation():
    """Demonstrate chart generation capabilities."""
    print("🎯 LLM Evaluation Visualization System Demo")
    print("=" * 50)

    # Create sample data
    print("📊 Creating sample evaluation results...")
    results = create_sample_results()

    # Print basic summary
    print(f"✅ Generated {results.total_items} evaluation items")
    print(f"📈 Success rate: {results.success_rate:.1%}")
    print(f"⏱️  Duration: {results.duration:.1f} seconds")
    print()

    # Initialize chart generator
    chart_gen = ChartGenerator()

    print("🎨 Generating charts...")

    # 1. Dashboard - comprehensive overview
    print("  • Creating executive dashboard...")
    dashboard = chart_gen.create_dashboard(results)
    dashboard.write_html("demo_dashboard.html")
    print("    ✅ Saved: demo_dashboard.html")

    # 2. Metric distributions
    print("  • Creating metric distribution charts...")
    for metric in results.metrics:
        if metric != "response_time":  # Skip response_time for distribution
            dist_chart = chart_gen.create_metric_distribution_chart(results, metric)
            filename = f"demo_distribution_{metric}.html"
            dist_chart.write_html(filename)
            print(f"    ✅ Saved: {filename}")

    # 3. Performance timeline
    print("  • Creating performance timeline...")
    timeline = chart_gen.create_performance_timeline_chart(results)
    timeline.write_html("demo_timeline.html")
    print("    ✅ Saved: demo_timeline.html")

    # 4. Correlation analysis
    print("  • Creating correlation charts...")
    quality_metrics = ["accuracy", "relevance", "coherence"]
    for i in range(len(quality_metrics)):
        for j in range(i + 1, len(quality_metrics)):
            corr_chart = chart_gen.create_metric_correlation_chart(
                results, quality_metrics[i], quality_metrics[j]
            )
            filename = f"demo_correlation_{quality_metrics[i]}_{quality_metrics[j]}.html"
            corr_chart.write_html(filename)
            print(f"    ✅ Saved: {filename}")

    # 5. Multi-metric comparison
    print("  • Creating multi-metric comparison...")
    comparison_chart = chart_gen.create_multi_metric_comparison_chart(results, "radar")
    comparison_chart.write_html("demo_comparison_radar.html")
    print("    ✅ Saved: demo_comparison_radar.html")

    print()
    return results


def demonstrate_excel_export(results: EvaluationResult):
    """Demonstrate Excel export with embedded charts."""
    print("📊 Demonstrating Excel export...")

    try:
        excel_exporter = ExcelChartExporter()
        excel_path = excel_exporter.create_excel_report(
            results,
            "demo_evaluation_report.xlsx",
            include_raw_data=True,
            include_charts=True
        )
        print(f"    ✅ Excel report saved: {excel_path}")

    except ImportError as e:
        print(f"    ⚠️  Excel export requires openpyxl: {e}")
        print("       Install with: pip install openpyxl")


def demonstrate_comprehensive_report(results: EvaluationResult):
    """Demonstrate comprehensive report generation."""
    print("📑 Creating comprehensive evaluation report...")

    # Create reports directory
    os.makedirs("demo_reports", exist_ok=True)

    # Generate comprehensive report
    report_files = create_evaluation_report(
        results,
        output_dir="./demo_reports",
        formats=["html", "excel"],
        include_charts=["dashboard", "distributions", "timeline", "correlations"]
    )

    print("    Generated reports:")
    for format_type, filepath in report_files.items():
        print(f"      ✅ {format_type.upper()}: {filepath}")


def demonstrate_quick_utilities(results: EvaluationResult):
    """Demonstrate quick utility functions."""
    print("⚡ Demonstrating quick chart utilities...")

    # Quick dashboard
    dashboard_path = quick_chart(
        results,
        chart_type="dashboard",
        save_path="quick_dashboard.html",
        format="html"
    )
    print(f"    ✅ Quick dashboard: {dashboard_path}")

    # Quick distribution
    dist_path = quick_chart(
        results,
        chart_type="distribution",
        metric="accuracy",
        save_path="quick_accuracy_dist.html",
        format="html"
    )
    print(f"    ✅ Quick distribution: {dist_path}")


def print_integration_examples():
    """Print code examples for integration."""
    print("\n" + "=" * 60)
    print("🔧 INTEGRATION EXAMPLES")
    print("=" * 60)

    print("""
1. Basic Chart Generation:

   from llm_eval.visualizations import ChartGenerator

   chart_gen = ChartGenerator()
   dashboard = chart_gen.create_dashboard(results)
   dashboard.show()  # Display interactively
   dashboard.write_html("report.html")  # Save to file

2. Excel Export:

   from llm_eval.visualizations import ExcelChartExporter

   exporter = ExcelChartExporter()
   excel_path = exporter.create_excel_report(
       results,
       "evaluation_report.xlsx",
       include_charts=True
   )

3. Comprehensive Reports:

   from llm_eval.visualizations.utils import create_evaluation_report

   reports = create_evaluation_report(
       results,
       output_dir="./reports",
       formats=["html", "excel", "png"],
       include_charts=["dashboard", "distributions", "timeline"]
   )

4. Integration with Evaluator:

   # After running evaluation
   evaluator = Evaluator(task, dataset, metrics)
   results = evaluator.run()

   # Generate charts directly
   dashboard = results.create_dashboard()  # If enhanced
   results.create_report(output_dir="./reports")

5. Quick Visualization:

   from llm_eval.visualizations.utils import quick_chart

   # Quick dashboard
   quick_chart(results, "dashboard", save_path="dash.html")

   # Quick metric distribution
   quick_chart(results, "distribution", metric="accuracy")
    """)


if __name__ == "__main__":
    print("🚀 Starting LLM Evaluation Visualization Demo\n")

    try:
        # Main demonstration
        results = demonstrate_chart_generation()
        demonstrate_excel_export(results)
        demonstrate_comprehensive_report(results)
        demonstrate_quick_utilities(results)

        # Show integration examples
        print_integration_examples()

        print("\n" + "=" * 60)
        print("✨ DEMO COMPLETE!")
        print("=" * 60)
        print("""
Generated files:
  • Individual charts: demo_*.html
  • Comprehensive reports: demo_reports/
  • Quick utilities: quick_*.html
  • Excel report: demo_evaluation_report.xlsx (if openpyxl available)

Open any .html file in your browser to view interactive charts.
        """)

    except Exception as e:
        print(f"❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()
