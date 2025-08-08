"""Chart generation for LLM evaluation results."""

import statistics
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# EvaluationResult will be passed as parameter to avoid circular imports


class ChartGenerator:
    """
    Generates professional charts for LLM evaluation results.

    Supports both interactive Plotly charts and Excel-compatible static charts.
    Designed for executive reports with clean, professional styling.
    """

    # Professional color palette for executive reports
    COLORS = {
        "primary": "#2E86AB",  # Professional blue
        "secondary": "#A23B72",  # Accent purple
        "success": "#F18F01",  # Warm orange for success
        "warning": "#C73E1D",  # Red for warnings/errors
        "neutral": "#6C757D",  # Gray for neutral elements
        "light_blue": "#A8DADC",  # Light blue for backgrounds
        "light_gray": "#F8F9FA",  # Light gray for backgrounds
        "dark_gray": "#343A40",  # Dark gray for text
    }

    # Color sequence for multiple metrics
    COLOR_SEQUENCE = [
        "#2E86AB",
        "#A23B72",
        "#F18F01",
        "#C73E1D",
        "#6C757D",
        "#17A2B8",
        "#28A745",
        "#FFC107",
    ]

    def __init__(self, theme: str = "professional"):
        """
        Initialize chart generator.

        Args:
            theme: Chart theme ('professional', 'minimal', 'colorful')
        """
        self.theme = theme
        self._setup_plotly_theme()

    def _setup_plotly_theme(self):
        """Configure Plotly default theme for professional appearance."""
        self.layout_template = {
            "plot_bgcolor": "white",
            "paper_bgcolor": "white",
            "font": {
                "family": "Arial, sans-serif",
                "size": 12,
                "color": self.COLORS["dark_gray"],
            },
            "title": {
                "font": {"size": 16, "color": self.COLORS["dark_gray"]},
                "x": 0.5,
                "xanchor": "center",
            },
            "colorway": self.COLOR_SEQUENCE,
            "hovermode": "closest",
            "showlegend": True,
            "legend": {
                "orientation": "h",
                "yanchor": "bottom",
                "y": -0.2,
                "xanchor": "center",
                "x": 0.5,
            },
        }

    def create_metric_distribution_chart(
        self,
        results,  # EvaluationResult object
        metric_name: str,
        chart_type: str = "histogram",
    ) -> go.Figure:
        """
        Create distribution chart for a specific metric.

        Args:
            results: EvaluationResult object
            metric_name: Name of the metric to visualize
            chart_type: 'histogram', 'box', or 'violin'

        Returns:
            Plotly figure object
        """
        # Extract metric values
        values = []
        for result in results.results.values():
            if "scores" in result and metric_name in result["scores"]:
                score = result["scores"][metric_name]
                if isinstance(score, (int, float)):
                    values.append(float(score))
                elif isinstance(score, bool):
                    values.append(1.0 if score else 0.0)

        if not values:
            # Create empty chart with message
            fig = go.Figure()
            fig.add_annotation(
                text=f"No valid data for metric '{metric_name}'",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                xanchor="center",
                yanchor="middle",
                showarrow=False,
                font_size=16,
            )
        elif chart_type == "histogram":
            fig = go.Figure()
            fig.add_trace(
                go.Histogram(
                    x=values,
                    nbinsx=min(20, len(set(values))),
                    marker_color=self.COLORS["primary"],
                    opacity=0.7,
                    name=metric_name,
                )
            )
            fig.update_layout(
                title=f"Distribution of {metric_name} Scores",
                xaxis_title=f"{metric_name} Score",
                yaxis_title="Frequency",
                bargap=0.1,
            )
        elif chart_type == "box":
            fig = go.Figure()
            fig.add_trace(
                go.Box(
                    y=values,
                    name=metric_name,
                    marker_color=self.COLORS["primary"],
                    boxpoints="outliers",
                )
            )
            fig.update_layout(
                title=f"Box Plot of {metric_name} Scores",
                yaxis_title=f"{metric_name} Score",
            )
        elif chart_type == "violin":
            fig = go.Figure()
            fig.add_trace(
                go.Violin(
                    y=values,
                    name=metric_name,
                    fillcolor=self.COLORS["light_blue"],
                    line_color=self.COLORS["primary"],
                    box_visible=True,
                    points="outliers",
                )
            )
            fig.update_layout(
                title=f"Violin Plot of {metric_name} Scores",
                yaxis_title=f"{metric_name} Score",
            )

        # Apply theme
        fig.update_layout(**self.layout_template)

        # Add summary statistics as annotation
        if values:
            stats_text = (
                f"Mean: {statistics.mean(values):.3f}<br>"
                f"Std: {statistics.stdev(values) if len(values) > 1 else 0:.3f}<br>"
                f"Min: {min(values):.3f}<br>"
                f"Max: {max(values):.3f}<br>"
                f"Count: {len(values)}"
            )
            fig.add_annotation(
                text=stats_text,
                xref="paper",
                yref="paper",
                x=0.98,
                y=0.98,
                xanchor="right",
                yanchor="top",
                showarrow=False,
                bordercolor=self.COLORS["neutral"],
                borderwidth=1,
                bgcolor="white",
                font_size=10,
            )

        return fig

    def create_performance_timeline_chart(
        self, results
    ) -> go.Figure:  # EvaluationResult object
        """
        Create timeline chart showing response times over evaluation sequence.

        Args:
            results: EvaluationResult object

        Returns:
            Plotly figure object
        """
        # Extract timing data
        times = []
        indices = []

        for i, (item_id, result) in enumerate(results.results.items()):
            if "time" in result and isinstance(result["time"], (int, float)):
                times.append(float(result["time"]))
                indices.append(i + 1)

        if not times:
            # Create empty chart with message
            fig = go.Figure()
            fig.add_annotation(
                text="No timing data available",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                xanchor="center",
                yanchor="middle",
                showarrow=False,
                font_size=16,
            )
        else:
            fig = go.Figure()

            # Add scatter plot of response times
            fig.add_trace(
                go.Scatter(
                    x=indices,
                    y=times,
                    mode="markers+lines",
                    marker=dict(size=6, color=self.COLORS["primary"], opacity=0.7),
                    line=dict(color=self.COLORS["primary"], width=1, dash="dot"),
                    name="Response Time",
                )
            )

            # Add moving average if enough data points
            if len(times) >= 5:
                window_size = min(5, len(times) // 3)
                moving_avg = (
                    pd.Series(times).rolling(window=window_size, center=True).mean()
                )
                fig.add_trace(
                    go.Scatter(
                        x=indices,
                        y=moving_avg,
                        mode="lines",
                        line=dict(color=self.COLORS["secondary"], width=3),
                        name=f"Moving Average ({window_size})",
                    )
                )

            # Add mean line
            mean_time = statistics.mean(times)
            fig.add_hline(
                y=mean_time,
                line_dash="dash",
                line_color=self.COLORS["warning"],
                annotation_text=f"Mean: {mean_time:.2f}s",
                annotation_position="bottom right",
            )

            fig.update_layout(
                title="Response Time Performance Timeline",
                xaxis_title="Evaluation Sequence",
                yaxis_title="Response Time (seconds)",
            )

        # Apply theme
        fig.update_layout(**self.layout_template)

        return fig

    def create_success_rate_summary_chart(
        self, results
    ) -> go.Figure:  # EvaluationResult object
        """
        Create summary chart showing overall success/failure breakdown.

        Args:
            results: EvaluationResult object

        Returns:
            Plotly figure object
        """
        # Calculate success metrics
        total_items = results.total_items
        successful_items = len(results.results)
        failed_items = len(results.errors)
        success_rate = results.success_rate

        # Create subplot with pie chart and metrics
        fig = make_subplots(
            rows=1,
            cols=2,
            specs=[[{"type": "pie"}, {"type": "table"}]],
            subplot_titles=["Success/Failure Distribution", "Summary Metrics"],
            column_widths=[0.6, 0.4],
        )

        # Add pie chart
        fig.add_trace(
            go.Pie(
                labels=["Successful", "Failed"],
                values=[successful_items, failed_items],
                marker_colors=[self.COLORS["success"], self.COLORS["warning"]],
                textinfo="label+percent+value",
                hole=0.3,  # Donut style
                showlegend=False,
            ),
            row=1,
            col=1,
        )

        # Add summary table
        summary_data = [
            ["Total Items", str(total_items)],
            ["Successful", str(successful_items)],
            ["Failed", str(failed_items)],
            ["Success Rate", f"{success_rate:.1%}"],
        ]

        # Add timing statistics if available
        timing_stats = results.get_timing_stats()
        if timing_stats["total"] > 0:
            summary_data.extend(
                [
                    ["Avg Response Time", f"{timing_stats['mean']:.2f}s"],
                    ["Total Time", f"{timing_stats['total']:.1f}s"],
                ]
            )

        fig.add_trace(
            go.Table(
                header=dict(
                    values=["Metric", "Value"],
                    fill_color=self.COLORS["light_blue"],
                    font_color=self.COLORS["dark_gray"],
                    font_size=12,
                    align="left",
                ),
                cells=dict(
                    values=list(zip(*summary_data)),
                    fill_color="white",
                    font_color=self.COLORS["dark_gray"],
                    font_size=11,
                    align=["left", "right"],
                ),
            ),
            row=1,
            col=2,
        )

        fig.update_layout(
            title=f"Evaluation Summary: {results.run_name}",
            showlegend=False,
            **self.layout_template,
        )

        return fig

    def create_metric_correlation_chart(
        self, results, metric1: str, metric2: str  # EvaluationResult object
    ) -> go.Figure:
        """
        Create scatter plot showing correlation between two metrics.

        Args:
            results: EvaluationResult object
            metric1: First metric name
            metric2: Second metric name

        Returns:
            Plotly figure object
        """
        # Extract values for both metrics
        values1, values2 = [], []

        for result in results.results.values():
            if "scores" in result:
                scores = result["scores"]
                if metric1 in scores and metric2 in scores:
                    score1 = scores[metric1]
                    score2 = scores[metric2]

                    # Convert to numeric if possible
                    if isinstance(score1, (int, float, bool)):
                        val1 = (
                            float(score1)
                            if not isinstance(score1, bool)
                            else (1.0 if score1 else 0.0)
                        )
                    else:
                        continue

                    if isinstance(score2, (int, float, bool)):
                        val2 = (
                            float(score2)
                            if not isinstance(score2, bool)
                            else (1.0 if score2 else 0.0)
                        )
                    else:
                        continue

                    values1.append(val1)
                    values2.append(val2)

        if len(values1) < 2:
            # Create empty chart with message
            fig = go.Figure()
            fig.add_annotation(
                text=f"Insufficient data for correlation between '{metric1}' and '{metric2}'",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                xanchor="center",
                yanchor="middle",
                showarrow=False,
                font_size=16,
            )
        else:
            fig = go.Figure()

            # Add scatter plot
            fig.add_trace(
                go.Scatter(
                    x=values1,
                    y=values2,
                    mode="markers",
                    marker=dict(
                        size=8,
                        color=self.COLORS["primary"],
                        opacity=0.6,
                        line=dict(width=1, color="white"),
                    ),
                    name="Data Points",
                )
            )

            # Add trend line
            if len(values1) >= 3:
                z = np.polyfit(values1, values2, 1)
                p = np.poly1d(z)
                x_trend = np.linspace(min(values1), max(values1), 100)
                y_trend = p(x_trend)

                fig.add_trace(
                    go.Scatter(
                        x=x_trend,
                        y=y_trend,
                        mode="lines",
                        line=dict(color=self.COLORS["secondary"], width=2, dash="dash"),
                        name="Trend Line",
                    )
                )

            # Calculate correlation coefficient
            if len(values1) >= 3:
                correlation = np.corrcoef(values1, values2)[0, 1]
                correlation_text = f"Correlation: {correlation:.3f}"

                fig.add_annotation(
                    text=correlation_text,
                    xref="paper",
                    yref="paper",
                    x=0.02,
                    y=0.98,
                    xanchor="left",
                    yanchor="top",
                    showarrow=False,
                    bordercolor=self.COLORS["neutral"],
                    borderwidth=1,
                    bgcolor="white",
                    font_size=12,
                )

            fig.update_layout(
                title=f"Correlation: {metric1} vs {metric2}",
                xaxis_title=metric1,
                yaxis_title=metric2,
            )

        # Apply theme
        fig.update_layout(**self.layout_template)

        return fig

    def create_multi_metric_comparison_chart(
        self, results, chart_type: str = "radar"  # EvaluationResult object
    ) -> go.Figure:
        """
        Create comparison chart for multiple metrics.

        Args:
            results: EvaluationResult object
            chart_type: 'radar', 'bar', or 'line'

        Returns:
            Plotly figure object
        """
        # Get statistics for all metrics
        metric_stats = {}
        for metric in results.metrics:
            stats = results.get_metric_stats(metric)
            metric_stats[metric] = stats

        if not metric_stats:
            # Create empty chart with message
            fig = go.Figure()
            fig.add_annotation(
                text="No metric data available",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                xanchor="center",
                yanchor="middle",
                showarrow=False,
                font_size=16,
            )
        elif chart_type == "radar":
            fig = go.Figure()

            # Create radar chart for mean values
            metrics = list(metric_stats.keys())
            means = [metric_stats[m]["mean"] for m in metrics]

            fig.add_trace(
                go.Scatterpolar(
                    r=means,
                    theta=metrics,
                    fill="toself",
                    fillcolor=self.COLORS["light_blue"],
                    line_color=self.COLORS["primary"],
                    name="Mean Scores",
                )
            )

            fig.update_layout(
                polar=dict(
                    radialaxis=dict(
                        visible=True, range=[0, max(means) * 1.1] if means else [0, 1]
                    )
                ),
                title="Multi-Metric Performance Radar",
                showlegend=False,
            )

        elif chart_type == "bar":
            fig = go.Figure()

            metrics = list(metric_stats.keys())
            means = [metric_stats[m]["mean"] for m in metrics]
            stds = [metric_stats[m]["std"] for m in metrics]

            fig.add_trace(
                go.Bar(
                    x=metrics,
                    y=means,
                    error_y=dict(type="data", array=stds),
                    marker_color=self.COLORS["primary"],
                    opacity=0.8,
                    name="Mean ± Std",
                )
            )

            fig.update_layout(
                title="Multi-Metric Performance Comparison",
                xaxis_title="Metrics",
                yaxis_title="Score",
                xaxis_tickangle=-45,
            )

        elif chart_type == "line":
            fig = go.Figure()

            metrics = list(metric_stats.keys())
            means = [metric_stats[m]["mean"] for m in metrics]

            fig.add_trace(
                go.Scatter(
                    x=metrics,
                    y=means,
                    mode="lines+markers",
                    line=dict(color=self.COLORS["primary"], width=3),
                    marker=dict(size=10, color=self.COLORS["primary"]),
                    name="Mean Scores",
                )
            )

            fig.update_layout(
                title="Multi-Metric Performance Trend",
                xaxis_title="Metrics",
                yaxis_title="Mean Score",
                xaxis_tickangle=-45,
            )

        # Apply theme
        fig.update_layout(**self.layout_template)

        return fig

    def create_dashboard(self, results) -> go.Figure:  # EvaluationResult object
        """
        Create comprehensive dashboard with multiple chart types.

        Args:
            results: EvaluationResult object

        Returns:
            Plotly figure with subplots
        """
        # Create 2x2 subplot grid
        fig = make_subplots(
            rows=2,
            cols=2,
            subplot_titles=[
                "Success Rate Summary",
                "Response Time Timeline",
                "Metric Performance",
                "Key Statistics",
            ],
            specs=[
                [{"type": "pie"}, {"type": "scatter"}],
                [{"type": "bar"}, {"type": "table"}],
            ],
            vertical_spacing=0.12,
            horizontal_spacing=0.1,
        )

        # 1. Success rate pie chart
        successful = len(results.results)
        failed = len(results.errors)

        fig.add_trace(
            go.Pie(
                labels=["Success", "Failed"],
                values=[successful, failed],
                marker_colors=[self.COLORS["success"], self.COLORS["warning"]],
                textinfo="percent",
                hole=0.4,
                showlegend=False,
            ),
            row=1,
            col=1,
        )

        # 2. Response time timeline
        times, indices = [], []
        for i, (_, result) in enumerate(results.results.items()):
            if "time" in result and isinstance(result["time"], (int, float)):
                times.append(float(result["time"]))
                indices.append(i + 1)

        if times:
            fig.add_trace(
                go.Scatter(
                    x=indices,
                    y=times,
                    mode="lines+markers",
                    line=dict(color=self.COLORS["primary"], width=2),
                    marker=dict(size=4),
                    showlegend=False,
                ),
                row=1,
                col=2,
            )

        # 3. Metric performance bar chart
        metric_means = []
        metric_names = []
        for metric in results.metrics:
            stats = results.get_metric_stats(metric)
            metric_means.append(stats["mean"])
            metric_names.append(metric)

        if metric_means:
            fig.add_trace(
                go.Bar(
                    x=metric_names,
                    y=metric_means,
                    marker_color=self.COLORS["primary"],
                    showlegend=False,
                ),
                row=2,
                col=1,
            )

        # 4. Statistics table
        timing_stats = results.get_timing_stats()
        stats_data = [
            ["Total Items", str(results.total_items)],
            ["Success Rate", f"{results.success_rate:.1%}"],
            ["Avg Response Time", f"{timing_stats['mean']:.2f}s"],
            [
                "Total Duration",
                f"{results.duration:.1f}s" if results.duration else "N/A",
            ],
        ]

        fig.add_trace(
            go.Table(
                header=dict(
                    values=["Metric", "Value"],
                    fill_color=self.COLORS["light_blue"],
                    font_color=self.COLORS["dark_gray"],
                    align="left",
                ),
                cells=dict(
                    values=list(zip(*stats_data)),
                    fill_color="white",
                    font_color=self.COLORS["dark_gray"],
                    align=["left", "right"],
                ),
            ),
            row=2,
            col=2,
        )

        # Update layout
        layout_update = dict(self.layout_template)
        layout_update["title"] = f"Evaluation Dashboard: {results.run_name}"
        layout_update["height"] = 800
        fig.update_layout(**layout_update)

        return fig

    def save_chart(
        self,
        fig: go.Figure,
        filename: str,
        format: str = "png",
        width: int = 1200,
        height: int = 800,
    ) -> str:
        """
        Save chart to file.

        Args:
            fig: Plotly figure
            filename: Output filename
            format: File format ('png', 'jpg', 'pdf', 'svg', 'html')
            width: Image width in pixels
            height: Image height in pixels

        Returns:
            Path to saved file
        """
        if format.lower() == "html":
            fig.write_html(filename)
        else:
            fig.write_image(filename, width=width, height=height, format=format)

        return filename
