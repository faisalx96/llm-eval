"""Evaluation results container and analysis."""

from typing import Any, Dict, List, Optional
from datetime import datetime
import statistics
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
    
    def print_summary(self):
        """Print a rich formatted summary to console."""
        # Create summary table
        table = Table(title=f"Evaluation Results: {self.run_name}")
        table.add_column("Metric", style="cyan")
        table.add_column("Mean", justify="right", style="green")
        table.add_column("Std Dev", justify="right")
        table.add_column("Min", justify="right")
        table.add_column("Max", justify="right")
        table.add_column("Success", justify="right", style="yellow")
        
        for metric in self.metrics:
            stats = self.get_metric_stats(metric)
            table.add_row(
                metric,
                f"{stats['mean']:.3f}",
                f"{stats['std']:.3f}",
                f"{stats['min']:.3f}",
                f"{stats['max']:.3f}",
                f"{stats['success_rate']:.1%}"
            )
        
        # Print overview panel
        overview = Panel(
            f"[bold]Dataset:[/bold] {self.dataset_name}\n"
            f"[bold]Total Items:[/bold] {self.total_items}\n"
            f"[bold]Success Rate:[/bold] {self.success_rate:.1%}\n"
            f"[bold]Duration:[/bold] {self.duration:.1f}s" if self.duration else "",
            title="Overview",
            expand=False
        )
        
        console.print(overview)
        console.print(table)
        
        if self.errors:
            console.print(f"\n[red]Errors:[/red] {len(self.errors)} items failed")
    
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