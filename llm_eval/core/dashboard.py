"""Shared Rich dashboard for single and multi-run TUIs."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console, Group, RenderableType
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from .observers import EvaluationObserver


@dataclass
class RunVisualState:
    """Holds mutable state for a single run's dashboard row."""

    run_id: str
    display_name: str
    dataset: Optional[str] = None
    model_name: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)
    run_info: Dict[str, Any] = field(default_factory=dict)
    total_items: int = 0
    completed: int = 0
    failed: int = 0
    in_progress: int = 0
    metrics: Sequence[str] = field(default_factory=list)
    metric_totals: Dict[str, float] = field(default_factory=dict)
    metric_counts: Dict[str, int] = field(default_factory=dict)
    metric_last: Dict[str, str] = field(default_factory=dict)
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    latency_total: float = 0.0
    latency_count: int = 0
    latency_samples: List[float] = field(default_factory=list)
    status: str = "pending"
    last_error: Optional[str] = None

    def success_rate(self) -> float:
        if not self.total_items:
            return 0.0
        return max(0.0, min(1.0, self.completed / self.total_items))

    def avg_latency(self) -> float:
        if not self.latency_count:
            return 0.0
        return self.latency_total / self.latency_count

    def throughput(self) -> float:
        if not self.start_time:
            return 0.0
        duration = (self.end_time or time.time()) - self.start_time
        if duration <= 0:
            return 0.0
        return self.completed / duration

    def percent_complete(self) -> float:
        if not self.total_items:
            return 0.0
        return (self.completed / self.total_items) * 100


class RunDashboard:
    """Unified Rich dashboard for single or multi-run execution."""

    def __init__(
        self,
        runs: Sequence[Dict[str, Any]],
        *,
        enabled: bool = True,
        console: Optional[Console] = None,
    ) -> None:
        self.console = console or Console()
        self.enabled = enabled
        self.states: Dict[str, RunVisualState] = {}
        self.order: List[str] = []
        self.live: Optional[Live] = None
        self.start_time = time.time()

        for entry in runs:
            run_id = entry.get("run_id")
            if not run_id:
                continue
            display_name = entry.get("display_name") or run_id
            dataset = entry.get("dataset")
            model_name = entry.get("model")
            config = entry.get("config") or {}
            self.order.append(run_id)
            self.states[run_id] = RunVisualState(
                run_id=run_id,
                display_name=display_name,
                dataset=dataset,
                model_name=model_name,
                config=config,
            )

    def bind(self, live: Live) -> None:
        self.live = live
        self.refresh(force=True)

    def create_observer(self, run_id: str) -> EvaluationObserver:
        return _DashboardObserver(self, run_id)

    def initialize_run(
        self,
        run_id: str,
        run_info: Dict[str, Any],
        total_items: int,
        metrics: Sequence[str],
    ) -> None:
        state = self.states.get(run_id)
        if not state:
            return
        state.run_info = dict(run_info or {})
        state.total_items = total_items
        state.metrics = list(metrics)
        state.metric_totals = {m: 0.0 for m in metrics}
        state.metric_counts = {m: 0 for m in metrics}
        state.start_time = time.time()
        state.status = "running"
        self.refresh()

    def record_item_start(self, run_id: str) -> None:
        state = self.states.get(run_id)
        if not state:
            return
        state.in_progress += 1
        self.refresh()

    def record_metric(self, run_id: str, metric_name: str, score: Any) -> None:
        state = self.states.get(run_id)
        if not state:
            return
        if metric_name not in state.metric_totals:
            state.metric_totals[metric_name] = 0.0
            state.metric_counts[metric_name] = 0
            state.metrics = list(state.metrics) + [metric_name]
        normalized = _extract_numeric_score(score)
        if normalized is not None:
            state.metric_totals[metric_name] = state.metric_totals.get(metric_name, 0.0) + normalized
            state.metric_counts[metric_name] = state.metric_counts.get(metric_name, 0) + 1
        state.metric_last[metric_name] = _format_score(score)
        self.refresh()

    def record_item_complete(self, run_id: str, elapsed: float) -> None:
        state = self.states.get(run_id)
        if not state:
            return
        state.completed += 1
        state.in_progress = max(0, state.in_progress - 1)
        state.latency_total += elapsed
        state.latency_count += 1
        state.latency_samples.append(elapsed)
        if state.completed >= state.total_items and state.failed == 0:
            state.status = "completed"
            state.end_time = time.time()
        self.refresh()

    def record_item_error(self, run_id: str, message: str) -> None:
        state = self.states.get(run_id)
        if not state:
            return
        state.failed += 1
        state.in_progress = max(0, state.in_progress - 1)
        state.last_error = message
        state.status = "error"
        self.refresh()

    def mark_run_complete(self, run_id: str) -> None:
        state = self.states.get(run_id)
        if not state:
            return
        if state.status != "error":
            state.status = "completed"
        state.end_time = time.time()
        self.refresh()

    def mark_run_exception(self, run_id: str, error: str) -> None:
        state = self.states.get(run_id)
        if not state:
            return
        state.status = "error"
        state.last_error = error
        state.end_time = time.time()
        self.refresh(force=True)

    def refresh(self, force: bool = False) -> None:
        if not self.enabled or not self.live:
            return
        self.live.update(self.render(), refresh=force)

    def render(self) -> Layout:
        layout = Layout()
        layout.split(
            Layout(name="header", size=3),
            Layout(name="main"),
            Layout(name="footer", size=1),
        )
        
        layout["header"].update(self._render_header())
        layout["main"].update(self._render_main())
        layout["footer"].update(self._render_footer())
        
        return layout

    def _render_header(self) -> RenderableType:
        # Calculate global stats
        total_runs = len(self.states)
        total_items = sum(s.total_items for s in self.states.values())
        total_completed = sum(s.completed for s in self.states.values())
        total_failed = sum(s.failed for s in self.states.values())
        total_in_progress = sum(s.in_progress for s in self.states.values())
        
        # Global throughput
        elapsed_total = time.time() - self.start_time
        global_throughput = total_completed / elapsed_total if elapsed_total > 0 else 0.0
        
        # Global success rate
        global_success = (total_completed / (total_completed + total_failed) * 100) if (total_completed + total_failed) > 0 else 0.0

        grid = Table.grid(expand=True)
        grid.add_column(justify="left", ratio=1)
        grid.add_column(justify="right", ratio=1)
        
        title = Text("⚡ LLM-Eval", style="bold magenta")
        
        stats = Text()
        stats.append(f"Time: {_format_duration(elapsed_total)}  ", style="bold white")
        stats.append(f"Runs: {total_runs}  ", style="bold white")
        stats.append(f"Items: {total_completed}/{total_items}  ", style="dim white")
        stats.append(f"Rate: {global_throughput:.1f} it/s  ", style="cyan")
        stats.append(f"Success: {global_success:.0f}%", style="green" if global_success > 90 else "yellow")
        
        grid.add_row(title, stats)
        
        return Panel(grid, style="white", box=box.ROUNDED, padding=(0, 1))

    def _render_main(self) -> RenderableType:
        table = Table(
            box=box.SIMPLE,
            expand=True,
            show_lines=False,
            padding=(1, 2),  # More breathing room
            header_style="bold dim white",
        )
        table.add_column("Model / Dataset", ratio=2)
        table.add_column("Status", width=10, justify="center")
        table.add_column("Progress", ratio=3)
        table.add_column("Latency", ratio=2)
        table.add_column("Metrics", ratio=3)

        if not self.states:
            return Panel(Align.center("[dim]No runs configured[/dim]"), box=box.ROUNDED)
            
        for run_id in self.order:
            state = self.states[run_id]
            table.add_row(
                self._render_run_info(state),
                self._render_status_icon(state),
                self._render_progress_bar(state),
                self._render_latency(state),
                self._render_metrics_compact(state),
            )
            
        # Align(..., vertical="top") prevents the panel from stretching to fill vertical space
        return Align(
            Panel(table, box=box.ROUNDED, title="Active Evaluations", border_style="blue"),
            vertical="top"
        )

    def _render_footer(self) -> RenderableType:
        grid = Table.grid(expand=True)
        grid.add_column(justify="left")
        grid.add_column(justify="right")
        
        grid.add_row(
            Text("Press Ctrl+C to stop", style="dim"),
            Text(f"v0.1.0 • {datetime.now().strftime('%H:%M:%S')}", style="dim"),
        )
        return grid

    def _render_run_info(self, state: RunVisualState) -> Text:
        info = Text()
        info.append(state.display_name, style="bold white")
        if state.model_name:
            info.append(f"\n{state.model_name}", style="cyan")
        if state.dataset:
            info.append(f"\n{state.dataset}", style="dim")
        return info

    def _render_progress_bar(self, state: RunVisualState) -> RenderableType:
        total = max(state.total_items, 1)
        completed = min(state.completed, total)
        percent = state.percent_complete()
        
        bar = ProgressBar(
            total=total,
            completed=completed,
            width=None, # Auto width
            pulse=state.total_items == 0 and state.status == "running",
            complete_style="green",
            finished_style="green",
        )
        
        # Use a grid to place text to the right of the bar
        grid = Table.grid(expand=True, padding=(0, 1))
        grid.add_column(ratio=3)
        grid.add_column(ratio=1, justify="right")
        
        text = Text(f"{state.completed}/{state.total_items} ", style="white")
        text.append(f"({percent:.0f}%)", style="cyan")
        
        grid.add_row(bar, text)
        return grid

    def _render_latency(self, state: RunVisualState) -> RenderableType:
        if not state.latency_samples:
            return Text("-", style="dim")
        
        # Sparkline
        data = state.latency_samples[-20:]
        sparkline = Text("", style="yellow")
        if data:
            min_val = min(data)
            max_val = max(data)
            range_val = max_val - min_val
            chars = "  ▂▃▄▅▆▇█"
            result = ""
            for val in data:
                if range_val == 0:
                    # If variance is 0 but value > 0, show a middle block
                    # If value is 0, show empty
                    index = 4 if val > 0 else 0
                else:
                    index = int((val - min_val) / range_val * (len(chars) - 1))
                result += chars[index]
            sparkline = Text(result, style="yellow")

        # Numeric Stats
        percentiles = _latency_percentiles(state.latency_samples)
        p50 = _format_latency_value(percentiles.get("p50", 0))
        p90 = _format_latency_value(percentiles.get("p90", 0))
        p99 = _format_latency_value(percentiles.get("p99", 0))
        
        stats = Text(f"P50: {p50}  P90: {p90}  P99: {p99}", style="dim")
        
        # Add a newline for better spacing
        return Group(sparkline, Text(""), stats)

    def _render_metrics_compact(self, state: RunVisualState) -> Text:
        if not state.metrics:
            return Text("-", style="dim")
            
        text = Text()
        for i, metric in enumerate(state.metrics[:3]): # Show max 3 metrics
            if i > 0:
                text.append("\n")
            
            avg_val = 0.0
            if state.metric_counts.get(metric):
                avg_val = state.metric_totals.get(metric, 0.0) / max(1, state.metric_counts[metric])
            
            text.append(f"{metric}: ", style="dim")
            text.append(f"{avg_val:.2f}", style="white")
            
        if len(state.metrics) > 3:
            text.append(f"\n+ {len(state.metrics)-3} more", style="dim italic")
            
        return text

    def _render_status_icon(self, state: RunVisualState) -> RenderableType:
        if state.status == "running":
            return Spinner("dots", style="cyan", text="Running")
        elif state.status == "error":
            return Text("❌ Error", style="red bold")
        elif state.status == "completed":
            return Text("✅ Done", style="green bold")
        else:
            return Text("⏳ Pending", style="dim")

    def _row_style(self, state: RunVisualState) -> str:
        return self._status_color(state.status)

    @staticmethod
    def _status_color(status: str) -> str:
        return {
            "pending": "yellow",
            "running": "cyan",
            "completed": "green",
            "error": "red",
        }.get(status, "cyan")


class _DashboardObserver(EvaluationObserver):
    """Bridges evaluator events into the dashboard."""

    def __init__(self, dashboard: RunDashboard, run_id: str) -> None:
        self.dashboard = dashboard
        self.run_id = run_id
        self._item_starts: Dict[int, float] = {}

    def on_run_start(self, **kwargs: Any) -> None:
        self.dashboard.initialize_run(
            self.run_id,
            kwargs.get("run_info", {}),
            kwargs.get("total_items", 0),
            kwargs.get("metrics", []),
        )

    def on_item_start(self, **kwargs: Any) -> None:
        item_index = kwargs.get("item_index")
        if item_index is not None:
            self._item_starts[item_index] = time.time()
        self.dashboard.record_item_start(self.run_id)

    def on_metric_result(self, **kwargs: Any) -> None:
        metric_name = kwargs.get("metric_name")
        score = kwargs.get("score")
        if metric_name is None:
            return
        self.dashboard.record_metric(self.run_id, metric_name, score)

    def on_item_complete(self, **kwargs: Any) -> None:
        item_index = kwargs.get("item_index")
        elapsed = 0.0
        if item_index is not None:
            start = self._item_starts.pop(item_index, None)
            if start:
                elapsed = time.time() - start
        
        # Fallback if time provided in result (unlikely based on investigation)
        if elapsed == 0.0:
            result = kwargs.get("result") or {}
            elapsed = float(result.get("time") or 0.0)
            
        self.dashboard.record_item_complete(self.run_id, elapsed)

    def on_item_error(self, **kwargs: Any) -> None:
        error = kwargs.get("error", "error")
        self.dashboard.record_item_error(self.run_id, str(error))

    def on_run_complete(self, **kwargs: Any) -> None:
        self.dashboard.mark_run_complete(self.run_id)


def _extract_numeric_score(score: Any) -> Optional[float]:
    if isinstance(score, (int, float)):
        return float(score)
    if isinstance(score, bool):
        return 1.0 if score else 0.0
    if isinstance(score, dict):
        if "score" in score:
            inner = score.get("score")
            if isinstance(inner, (int, float)):
                return float(inner)
            if isinstance(inner, bool):
                return 1.0 if inner else 0.0
    return None


def _format_score(score: Any) -> str:
    if isinstance(score, dict):
        if "score" in score:
            return _format_score(score["score"])
        return str({k: v for k, v in score.items() if k != "metadata"})
    if isinstance(score, bool):
        return "✓" if score else "✗"
    return str(score)


def _strip_markup(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return Text.from_markup(value).plain
    except Exception:
        return value.replace("[", "").replace("]", "")


def _format_duration(duration: float) -> str:
    total_seconds = max(0, int(duration))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def _latency_percentiles(samples: Sequence[float]) -> Dict[str, float]:
    if not samples:
        return {}
    values = sorted(samples)
    return {
        "p50": _percentile(values, 50.0),
        "p90": _percentile(values, 90.0),
        "p99": _percentile(values, 99.0),
    }


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    k = (len(values) - 1) * (percentile / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(values[int(k)])
    d0 = values[f] * (c - k)
    d1 = values[c] * (k - f)
    return float(d0 + d1)


def _format_latency_value(value: float) -> str:
    if value < 1.0:
        return f"{value * 1000:.0f}ms"
    if value < 10.0:
        return f"{value:.1f}s"
    return f"{value:.0f}s"


def console_supports_live(console: Console) -> bool:
    """Return True when live updates should be rendered for this console."""
    return bool(getattr(console, "is_terminal", False))
