"""Evaluation results container and analysis."""

from typing import Any, Dict, List, Optional
from datetime import datetime
import statistics
import json
import csv
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel


console = Console()


class EvaluationResult:
    """Container for evaluation results with analysis capabilities."""
    
    def __init__(self, dataset_name: str, run_name: str, metrics: List[str]):
        """
        Initialize results container.
        
        Args:
            dataset_name: Name of the evaluated dataset
            run_name: Name of this evaluation run
            metrics: List of metric names used
        """
        self.dataset_name = dataset_name
        self.run_name = run_name
        self.metrics = metrics
        self.start_time = datetime.now()
        self.end_time = None
        
        # Results storage
        self.results = {}  # item_id -> result dict
        self.errors = {}   # item_id -> error message
        
    def add_result(self, item_id: str, result: Dict[str, Any]):
        """Add a successful evaluation result."""
        self.results[item_id] = result
    
    def add_error(self, item_id: str, error: str):
        """Add an evaluation error."""
        self.errors[item_id] = error
    
    def finish(self):
        """Mark evaluation as finished."""
        self.end_time = datetime.now()
    
    @property
    def total_items(self) -> int:
        """Total number of evaluated items."""
        return len(self.results) + len(self.errors)
    
    @property
    def success_rate(self) -> float:
        """Percentage of successful evaluations."""
        if self.total_items == 0:
            return 0.0
        return len(self.results) / self.total_items
    
    @property
    def duration(self) -> Optional[float]:
        """Evaluation duration in seconds."""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None
    
    def get_metric_stats(self, metric_name: str) -> Dict[str, float]:
        """
        Get statistics for a specific metric.
        
        Returns dict with: mean, std, min, max, success_rate
        """
        scores = []
        errors = 0
        
        for result in self.results.values():
            if 'scores' in result and metric_name in result['scores']:
                score = result['scores'][metric_name]
                if isinstance(score, (int, float)):
                    scores.append(float(score))
                elif isinstance(score, bool):
                    scores.append(1.0 if score else 0.0)
                elif isinstance(score, dict) and 'error' in score:
                    errors += 1
        
        if not scores:
            return {
                'mean': 0.0,
                'std': 0.0,
                'min': 0.0,
                'max': 0.0,
                'success_rate': 0.0
            }
        
        return {
            'mean': statistics.mean(scores),
            'std': statistics.stdev(scores) if len(scores) > 1 else 0.0,
            'min': min(scores),
            'max': max(scores),
            'success_rate': len(scores) / (len(scores) + errors)
        }
    
    def get_timing_stats(self) -> Dict[str, float]:
        """
        Get timing statistics for all evaluations.
        
        Returns dict with: mean, std, min, max, total
        """
        times = []
        
        for result in self.results.values():
            if 'time' in result and isinstance(result['time'], (int, float)):
                times.append(float(result['time']))
        
        if not times:
            return {
                'mean': 0.0,
                'std': 0.0,
                'min': 0.0,
                'max': 0.0,
                'total': 0.0
            }
        
        return {
            'mean': statistics.mean(times),
            'std': statistics.stdev(times) if len(times) > 1 else 0.0,
            'min': min(times),
            'max': max(times),
            'total': sum(times)
        }
    
    def summary(self) -> str:
        """Generate a text summary of results."""
        lines = []
        lines.append(f"Evaluation Results: {self.run_name}")
        lines.append(f"Dataset: {self.dataset_name}")
        lines.append(f"Total Items: {self.total_items}")
        lines.append(f"Success Rate: {self.success_rate:.1%}")
        
        if self.duration:
            lines.append(f"Duration: {self.duration:.1f}s")
        
        lines.append("\nMetric Results:")
        for metric in self.metrics:
            stats = self.get_metric_stats(metric)
            lines.append(f"  {metric}:")
            lines.append(f"    Mean: {stats['mean']:.3f}")
            lines.append(f"    Std:  {stats['std']:.3f}")
            lines.append(f"    Range: [{stats['min']:.3f}, {stats['max']:.3f}]")
        
        if self.errors:
            lines.append(f"\nErrors: {len(self.errors)} items failed")
            # Show first few errors
            for item_id, error in list(self.errors.items())[:3]:
                lines.append(f"  - {item_id}: {error[:100]}...")
        
        return "\n".join(lines)
    
    def _format_duration(self, seconds: float) -> str:
        """Format duration in a human-readable way."""
        seconds = int(seconds)
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            minutes = seconds // 60
            secs = seconds % 60
            if secs > 0:
                return f"{minutes}m {secs}s"
            return f"{minutes}m"
        else:
            hours = seconds // 3600
            remaining = seconds % 3600
            minutes = remaining // 60
            if minutes > 0:
                return f"{hours}h {minutes}m"
            return f"{hours}h"
    
    def print_summary(self, html_url: Optional[str] = None):
        """Print a rich formatted summary to console."""
        from rich.console import Group
        from rich.rule import Rule
        from rich.align import Align
        
        # Get timing statistics
        timing_stats = self.get_timing_stats()
        
        # Create the metrics table
        from rich.box import ROUNDED
        table = Table(box=ROUNDED, show_header=True, header_style="bold", expand=True)
        table.add_column("Metric", style="cyan", width=30)
        table.add_column("Mean", justify="right", style="green", width=10)
        table.add_column("Std Dev", justify="right", width=10)
        table.add_column("Min", justify="right", width=10)
        table.add_column("Max", justify="right", width=10)
        table.add_column("Success", justify="right", style="yellow", width=10)
        
        for metric in self.metrics:
            stats = self.get_metric_stats(metric)
            table.add_row(
                metric,
                f"{stats['mean']:.0f}",
                f"{stats['std']:.0f}",
                f"{stats['min']:.0f}",
                f"{stats['max']:.0f}",
                f"{int(stats['success_rate'] * 100)}%"
            )
        
        # Build content sections
        header_line = f"[bold]Dataset:[/bold] {self.dataset_name} │ [bold]{self.run_name}[/bold]"
        
        # Create timing statistics section
        from rich.columns import Columns
        from rich.text import Text
        
        timing_items = [
            Text.from_markup(f"[bold cyan]⏱  Total:[/bold cyan] {self._format_duration(self.duration)}"),
            Text.from_markup(f"[bold green]➜ Average:[/bold green] {self._format_duration(timing_stats['mean'])}"),
            Text.from_markup(f"[bold yellow]~  Std Dev:[/bold yellow] {self._format_duration(timing_stats['std'])}"),
            Text.from_markup(f"[bold blue]⬇  Min:[/bold blue] {self._format_duration(timing_stats['min'])}"),
            Text.from_markup(f"[bold red]⬆  Max:[/bold red] {self._format_duration(timing_stats['max'])}"),
        ]
        
        timing_info = Columns(timing_items, equal=True, expand=True)
        
        # Create content group
        content_parts = [
            header_line,
            Rule(style="dim"),
            "",
            Align.center("[bold]Timing Statistics[/bold]"),
            "",
            timing_info,
            "",
            Rule(style="dim"),
            "",
            Align.center("[bold]Metric Performance[/bold]"),
            "",
            table,
        ]
        
        # Don't add HTML URL to the display
        
        # Add error summary if there are errors
        if self.errors:
            content_parts.extend([
                "",
                Rule(style="dim"),
                "",
                f"[red]⚠️  Errors:[/red] {len(self.errors)} items failed"
            ])
        
        # Create the final panel
        panel = Panel(
            Group(*content_parts),
            title="[bold cyan]✨ Evaluation Results[/bold cyan]",
            expand=False,
            border_style="cyan",
            padding=(1, 3),
            width=100
        )
        
        console.print(panel)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert results to dictionary format."""
        metric_stats = {
            metric: self.get_metric_stats(metric) 
            for metric in self.metrics
        }
        
        return {
            'dataset_name': self.dataset_name,
            'run_name': self.run_name,
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'duration': self.duration,
            'total_items': self.total_items,
            'success_rate': self.success_rate,
            'metrics': self.metrics,
            'metric_stats': metric_stats,
            'results': self.results,
            'errors': self.errors
        }
    
    def failed_items(self) -> List[str]:
        """Get list of failed item IDs."""
        return list(self.errors.keys())
    
    def successful_items(self) -> List[str]:
        """Get list of successful item IDs."""
        return list(self.results.keys())
    
    def save_json(self, filepath: Optional[str] = None) -> str:
        """
        Save results to JSON file.
        
        Args:
            filepath: Optional custom filepath. If not provided, generates one.
            
        Returns:
            Path to the saved file
        """
        if filepath is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = f"eval_results_{self.dataset_name}_{timestamp}.json"
        
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, default=str, ensure_ascii=False)
        
        console.print(f"[blue]📁 Results saved to:[/blue] {filepath}")
        return str(filepath)
    
    def save_csv(self, filepath: Optional[str] = None) -> str:
        """
        Save results to CSV file for spreadsheet analysis.
        
        Args:
            filepath: Optional custom filepath. If not provided, generates one.
            
        Returns:
            Path to the saved file
        """
        if filepath is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = f"eval_results_{self.dataset_name}_{timestamp}.csv"
        
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        # Prepare rows for CSV
        rows = []
        for item_id, result in self.results.items():
            row = {
                'item_id': item_id,
                'output': str(result.get('output', ''))[:100],  # Truncate long outputs
                'success': result.get('success', False),
                'time': result.get('time', 0.0)
            }
            
            # Add metric scores
            if 'scores' in result:
                for metric_name, score in result['scores'].items():
                    if isinstance(score, dict) and 'error' in score:
                        row[f'metric_{metric_name}'] = 'ERROR'
                        row[f'metric_{metric_name}_error'] = score['error']
                    else:
                        row[f'metric_{metric_name}'] = score
            
            rows.append(row)
        
        # Add failed items
        for item_id, error in self.errors.items():
            row = {
                'item_id': item_id,
                'output': f'ERROR: {error[:100]}',
                'success': False,
                'time': 0.0
            }
            for metric in self.metrics:
                row[f'metric_{metric}'] = 'N/A'
            rows.append(row)
        
        # Write CSV
        if rows:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
        
        console.print(f"[blue]📁 Results saved to:[/blue] {filepath}")
        return str(filepath)
    
    def save(self, format: str = "json", filepath: Optional[str] = None) -> str:
        """
        Save results in specified format.
        
        Args:
            format: Export format - "json" or "csv"
            filepath: Optional custom filepath
            
        Returns:
            Path to the saved file
        """
        if format.lower() == "json":
            return self.save_json(filepath)
        elif format.lower() == "csv":
            return self.save_csv(filepath)
        else:
            raise ValueError(f"Unsupported format: {format}. Use 'json' or 'csv'.")