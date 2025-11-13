"""Multi-model orchestration and TUI dashboard."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Table
from rich.text import Text

from .evaluator import Evaluator
from .observers import EvaluationObserver
from .results import EvaluationResult
from .run_spec import RunSpec


@dataclass
class RunVisualState:
    """Holds mutable state for a single run's dashboard row."""

    run_id: str
    display_name: str
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
        now = time.time()
        if not self.start_time:
            return 0.0
        duration = (self.end_time or now) - self.start_time
        if duration <= 0:
            return 0.0
        return self.completed / duration

    def percent_complete(self) -> float:
        if not self.total_items:
            return 0.0
        return (self.completed / self.total_items) * 100


class MultiRunDashboard:
    """Owns the Rich Live rendering for all runs."""

    def __init__(self, specs: Sequence[RunSpec], enabled: bool = True, console: Optional[Console] = None) -> None:
        self.console = console or Console()
        self.enabled = enabled
        self.states: Dict[str, RunVisualState] = {}
        self.order: List[str] = []
        self.live: Optional[Live] = None
        for spec in specs:
            run_id = spec.run_name
            self.order.append(run_id)
            base_info = {
                "dataset": spec.dataset,
                "task_file": spec.task_file,
                "task_function": spec.task_function,
                "config": spec.config,
            }
            self.states[run_id] = RunVisualState(
                run_id=run_id,
                display_name=spec.name,
                run_info=base_info,
            )

    def bind(self, live: Live) -> None:
        self.live = live
        self.refresh(force=True)

    def create_observer(self, run_id: str) -> EvaluationObserver:
        return _DashboardObserver(self, run_id)

    def initialize_run(self, run_id: str, run_info: Dict[str, Any], total_items: int, metrics: Sequence[str]) -> None:
        state = self.states.get(run_id)
        if not state:
            return
        state.run_info.update(run_info or {})
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
        state.status = "completed" if state.failed == 0 else "error"
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
        panels: List[Panel] = []
        if not self.states:
            return Panel(Text("No runs configured"), border_style="cyan")
        for run_id in self.order:
            state = self.states[run_id]
            panels.append(self._render_run_panel(state))
        return Panel(Columns(panels, expand=True), border_style="cyan", title="Multi-Run Progress")

    def _render_run_panel(self, state: RunVisualState) -> Panel:
        total = max(state.total_items, 1)
        progress = Progress(
            TextColumn("{task.description}"),
            BarColumn(bar_width=None, complete_style="bright_green"),
            TextColumn("{task.completed}/{task.total}"),
            TextColumn("{task.percentage:>3.0f}%"),
            transient=True,
            expand=True,
        )
        task = progress.add_task(
            description=f"[bold]{state.display_name}[/bold]",
            total=total,
            completed=min(state.completed, total),
        )
        progress.update(task, completed=min(state.completed, total))

        status_color = {
            "pending": "yellow",
            "running": "cyan",
            "completed": "green",
            "error": "red",
        }.get(state.status, "cyan")

        kpi_table = Table.grid(padding=(0, 1))
        kpi_table.add_row("Status", f"[{status_color}]{state.status.upper()}[/]")
        kpi_table.add_row("Items", f"{state.completed}/{state.total_items or '?'}")
        kpi_table.add_row("In Flight", str(state.in_progress))
        kpi_table.add_row("Failed", str(state.failed))
        kpi_table.add_row("Success", f"{state.success_rate()*100:.1f}%")
        kpi_table.add_row("Avg Latency", f"{state.avg_latency()*1000:.0f} ms")
        kpi_table.add_row("Throughput", f"{state.throughput():.2f} it/s")

        metrics_table = Table(box=box.SIMPLE, show_header=True, header_style="bold magenta")
        metrics_table.add_column("Metric", justify="left")
        metrics_table.add_column("Live Score", justify="right")
        if not state.metrics:
            metrics_table.add_row("-", "pending")
        else:
            for metric in state.metrics:
                avg = "-"
                if state.metric_counts.get(metric):
                    avg_val = state.metric_totals.get(metric, 0.0) / max(1, state.metric_counts[metric])
                    avg = f"{avg_val:.3f}"
                last = state.metric_last.get(metric, "pending")
                metrics_table.add_row(metric, f"{avg} (last {last})")

        meta_table = Table.grid(padding=(0, 1))
        meta_table.add_row("Dataset", state.run_info.get("dataset", "-"))
        config = state.run_info.get("config") or {}
        meta_table.add_row("Max Concurrency", str(config.get("max_concurrency", "—")))
        model_name = (
            (config.get("run_metadata") or {}).get("model")
            or config.get("model")
            or config.get("model_name")
            or state.display_name
        )
        meta_table.add_row("Model", str(model_name))

        if state.last_error:
            meta_table.add_row("Error", f"[red]{state.last_error}[/red]")

        body = Group(
            progress,
            kpi_table,
            metrics_table,
            meta_table,
        )
        return Panel(
            Align.center(body, vertical="top"),
            title=f"[bold]{state.display_name}[/bold]",
            border_style=status_color,
            padding=(1, 2),
        )


class _DashboardObserver(EvaluationObserver):
    """Bridges evaluator events into the dashboard."""

    def __init__(self, dashboard: MultiRunDashboard, run_id: str) -> None:
        self.dashboard = dashboard
        self.run_id = run_id

    def on_run_start(self, run_id: str, run_info: Dict[str, Any], total_items: int, metrics: Sequence[str]) -> None:  # type: ignore[override]
        self.dashboard.initialize_run(self.run_id, run_info, total_items, metrics)

    def on_item_start(self, run_id: str, item_index: int, payload: Optional[Dict[str, Any]] = None) -> None:  # type: ignore[override]
        self.dashboard.record_item_start(self.run_id)

    def on_metric_result(
        self,
        run_id: str,
        item_index: int,
        metric_name: str,
        score: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:  # type: ignore[override]
        self.dashboard.record_metric(self.run_id, metric_name, score)

    def on_item_complete(self, run_id: str, item_index: int, result: Dict[str, Any]) -> None:  # type: ignore[override]
        elapsed = float(result.get("time") or 0.0)
        self.dashboard.record_item_complete(self.run_id, elapsed)

    def on_item_error(self, run_id: str, item_index: int, error: str) -> None:  # type: ignore[override]
        self.dashboard.record_item_error(self.run_id, error)

    def on_run_complete(self, run_id: str, result_summary: Dict[str, Any]) -> None:  # type: ignore[override]
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


class MultiModelRunner:
    """Coordinate multiple Evaluator instances in parallel."""

    def __init__(self, specs: Sequence[RunSpec], console: Optional[Console] = None) -> None:
        self.specs = list(specs)
        self.console = console or Console()

    async def arun(
        self,
        show_tui: bool = True,
        auto_save: bool = True,
        save_format: str = "csv",
    ) -> List[EvaluationResult]:
        dashboard = MultiRunDashboard(self.specs, enabled=show_tui, console=self.console)

        async def _run_spec(spec: RunSpec):
            observer = dashboard.create_observer(spec.run_name)
            model_option = spec.config.get("model") or spec.config.get("models")
            evaluator = Evaluator(
                task=spec.task,
                dataset=spec.dataset,
                metrics=spec.metrics,
                config=spec.config,
                observer=observer,
                model=model_option,
            )
            try:
                result = await evaluator.arun(
                    show_progress=False,
                    show_table=False,
                    auto_save=auto_save,
                    save_format=save_format,
                )
                return result
            except Exception as exc:
                dashboard.mark_run_exception(spec.run_name, str(exc))
                raise

        tasks = [asyncio.create_task(_run_spec(spec)) for spec in self.specs]

        if show_tui:
            with Live(dashboard.render(), console=self.console, refresh_per_second=6) as live:
                dashboard.bind(live)
                results = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            results = await asyncio.gather(*tasks, return_exceptions=True)

        errors: List[Tuple[RunSpec, Exception]] = []
        final_results = []
        for spec, result in zip(self.specs, results):
            if isinstance(result, Exception):
                errors.append((spec, result))
            else:
                final_results.append(result)

        if errors:
            summary = ", ".join(f"{spec.run_name}: {err}" for spec, err in errors)
            raise RuntimeError(f"One or more runs failed: {summary}")

        return final_results

    def print_summary(self, results: Sequence[EvaluationResult]) -> None:
        """Render a compact summary table for all runs."""
        table = Table(title="Multi-Run Summary", header_style="bold")
        table.add_column("Run")
        table.add_column("Dataset")
        table.add_column("Success Rate", justify="right")
        table.add_column("Metrics", justify="left")

        for spec, result in zip(self.specs, results):
            metric_lines = []
            for metric in result.metrics:
                stats = result.get_metric_stats(metric)
                metric_lines.append(f"{metric}: {stats['mean']:.3f}")
            metric_cell = "\n".join(metric_lines) if metric_lines else "-"
            table.add_row(
                spec.run_name,
                spec.dataset,
                f"{result.success_rate:.1%}",
                metric_cell,
            )

        self.console.print(table)
