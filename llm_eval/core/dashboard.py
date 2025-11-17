"""Shared Rich dashboard for single and multi-run TUIs."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console, Group
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

    def render(self) -> Panel:
        table = Table(
            box=box.SIMPLE_HEAD,
            expand=True,
            show_lines=False,
            padding=(0, 1),
        )
        table.add_column("Run", ratio=2, overflow="fold")
        table.add_column("Progress", ratio=5)
        table.add_column("Metrics", ratio=3, overflow="fold")

        if not self.states:
            table.add_row("No runs", "-", "-")
        else:
            for idx, run_id in enumerate(self.order):
                state = self.states[run_id]
                table.add_row(
                    self._render_run_label(state),
                    self._render_progress(state),
                    self._render_metrics(state),
                    style=self._row_style(state),
                )
                if idx < len(self.order) - 1:
                    table.add_row("", "", "")

        return Panel(
            table,
            title="Multi-Run Progress" if len(self.states) > 1 else "Run Progress",
            border_style="cyan",
            padding=(0, 1),
            expand=True,
        )

    def _render_run_label(self, state: RunVisualState) -> Text:
        label = Text(state.display_name, style="bold white")
        if state.model_name:
            label.append("\nModel: ", style="cyan")
            label.append(state.model_name, style="cyan")
        if state.dataset:
            label.append("\nDataset: ", style="dim")
            label.append(state.dataset, style="dim")
        return label

    def _render_progress(self, state: RunVisualState) -> Group:
        total = max(state.total_items, 1)
        completed = min(state.completed, total)
        bar = ProgressBar(
            total=total,
            completed=completed,
            width=40,
            pulse=state.total_items == 0 and state.status == "running",
        )
        percent = state.percent_complete()
        spinner = Spinner("dots", style="cyan") if state.status == "running" else Text("  ")
        completion_text = Text(f"{state.completed}/{state.total_items or '—'}   {percent:.0f}% complete")
        progress_row = Columns(
            [
                Align(spinner, align="center", width=3),
                bar,
                Align(completion_text, align="left"),
            ],
            expand=True,
            equal=False,
            padding=(0, 1),
        )

        stats = Text()
        stats.append(Text("Success: ", style="green"))
        stats.append(Text(str(state.completed)))
        stats.append(Text("  |  ", style="dim"))
        stats.append(Text("In progress: ", style="yellow"))
        stats.append(Text(str(state.in_progress)))
        stats.append(Text("  |  ", style="dim"))
        stats.append(Text("Failed: ", style="red"))
        stats.append(Text(str(state.failed)))
        pending = max(state.total_items - state.completed - state.in_progress - state.failed, 0)
        stats.append(Text("  |  ", style="dim"))
        stats.append(Text("Pending: ", style="cyan"))
        stats.append(Text(str(pending)))

        status_info = Text()
        elapsed_display = _format_duration((state.end_time or time.time()) - state.start_time) if state.start_time else "--:--"
        status_info.append(Text("Elapsed: ", style="dim"))
        status_info.append(Text(elapsed_display))
        status_info.append(Text("   Latency: ", style="dim"))
        status_info.append(Text(f"{state.avg_latency():.2f} s", style=self._status_color(state.status)))
        if state.last_error:
            status_info.append("\n")
            status_info.append(Text(_strip_markup(state.last_error)[:80], style="red"))

        return Group(progress_row, stats, status_info)

    def _render_metrics(self, state: RunVisualState) -> Text:
        if not state.metrics:
            return Text("No metrics yet", style="dim")
        lines: List[str] = []
        for metric in state.metrics:
            if metric not in state.metric_counts:
                state.metric_counts[metric] = 0
            avg = "-"
            if state.metric_counts.get(metric):
                avg_val = state.metric_totals.get(metric, 0.0) / max(1, state.metric_counts[metric])
                avg = f"{avg_val:.3f}"
                last = _strip_markup(state.metric_last.get(metric, "pending"))
                lines.append(f"{metric}: {avg} (last {last})")
        return Text("\n".join(lines))

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

    def on_run_start(self, **kwargs: Any) -> None:
        self.dashboard.initialize_run(
            self.run_id,
            kwargs.get("run_info", {}),
            kwargs.get("total_items", 0),
            kwargs.get("metrics", []),
        )

    def on_item_start(self, **kwargs: Any) -> None:
        self.dashboard.record_item_start(self.run_id)

    def on_metric_result(self, **kwargs: Any) -> None:
        metric_name = kwargs.get("metric_name")
        score = kwargs.get("score")
        if metric_name is None:
            return
        self.dashboard.record_metric(self.run_id, metric_name, score)

    def on_item_complete(self, **kwargs: Any) -> None:
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
