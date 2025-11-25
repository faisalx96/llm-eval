"""Shared Rich dashboard for single and multi-run TUIs."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence
import threading
import re

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

from llm_eval import __version__

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
    last_update: Optional[float] = None
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
        processed = self.completed + self.failed
        return processed / duration

    def percent_complete(self) -> float:
        if not self.total_items:
            return 0.0
        return ((self.completed + self.failed) / self.total_items) * 100

    def touch(self) -> None:
        self.last_update = time.time()


class RunDashboard:
    """Unified Rich dashboard for single or multi-run execution."""

    def __init__(
        self,
        runs: Sequence[Dict[str, Any]],
        *,
        enabled: bool = True,
        console: Optional[Console] = None,
        max_visible_runs: int = 12,
    ) -> None:
        self.console = console or Console()
        self.enabled = enabled
        self.max_visible_runs = max_visible_runs
        self.states: Dict[str, RunVisualState] = {}
        self.order: List[str] = []
        self.live: Optional[Live] = None
        self.start_time = time.time()
        self._auto_refresh_stop: Optional[threading.Event] = None
        self._auto_refresh_thread: Optional[threading.Thread] = None

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
        self._start_auto_refresh()
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
        state.touch()
        self.refresh()

    def record_item_start(self, run_id: str) -> None:
        state = self.states.get(run_id)
        if not state:
            return
        state.in_progress += 1
        state.touch()
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
        state.touch()
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
        state.touch()
        self.refresh()

    def record_item_error(self, run_id: str, message: str) -> None:
        state = self.states.get(run_id)
        if not state:
            return
        state.failed += 1
        state.in_progress = max(0, state.in_progress - 1)
        state.last_error = message
        if state.status == "pending":
            state.status = "running"
        state.touch()
        self.refresh()

    def mark_run_complete(self, run_id: str) -> None:
        state = self.states.get(run_id)
        if not state:
            return
        if state.status != "error":
            state.status = "completed"
        state.end_time = time.time()
        state.touch()
        self.refresh()

    def mark_run_exception(self, run_id: str, error: str) -> None:
        state = self.states.get(run_id)
        if not state:
            return
        state.status = "error"
        state.last_error = error
        state.end_time = time.time()
        state.touch()
        self.refresh(force=True)

    def refresh(self, force: bool = False) -> None:
        if not self.enabled or not self.live:
            return
        self.live.update(self.render(), refresh=force)

    def shutdown(self) -> None:
        if self._auto_refresh_stop:
            self._auto_refresh_stop.set()
        if self._auto_refresh_thread:
            self._auto_refresh_thread.join(timeout=1.0)
        self._auto_refresh_stop = None
        self._auto_refresh_thread = None

    def render(self) -> RenderableType:
        return Group(
            self._render_header(),
            self._render_main(),
            self._render_footer(),
        )

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
        table.add_column("Model / Dataset", ratio=3)
        table.add_column("Status", ratio=2)
        table.add_column("Progress", ratio=4)
        table.add_column("Latency", ratio=3)
        table.add_column("Metrics", ratio=3)

        if not self.states:
            return Panel(Align.center("[dim]No runs configured[/dim]"), box=box.ROUNDED)

        # Sort runs by priority: Running > Pending > Error > Completed
        # We want to keep active things at the top
        def _sort_key(rid: str) -> tuple:
            s = self.states[rid]
            # Priority (lower is better)
            if s.status == "running":
                prio = 0
            elif s.status == "pending":
                prio = 1
            elif s.status == "error":
                prio = 2
            else:  # completed
                prio = 3
            # Secondary sort: start time (newest first) or original order
            return (prio, -1 * (s.start_time or 0))

        sorted_runs = sorted(self.order, key=_sort_key)
        
        # Slice to max visible
        visible_runs = sorted_runs[:self.max_visible_runs]
        hidden_count = len(sorted_runs) - len(visible_runs)

        for run_id in visible_runs:
            state = self.states[run_id]
            table.add_row(
                self._render_run_info(state),
                self._render_status_icon(state),
                self._render_progress_bar(state),
                self._render_latency(state),
                self._render_metrics_compact(state),
            )
        
        if hidden_count > 0:
            # Add summary row
            hidden_states = [self.states[rid] for rid in sorted_runs[self.max_visible_runs:]]
            h_completed = sum(1 for s in hidden_states if s.status == "completed")
            h_running = sum(1 for s in hidden_states if s.status == "running")
            h_pending = sum(1 for s in hidden_states if s.status == "pending")
            h_failed = sum(1 for s in hidden_states if s.status == "error")
            
            summary = []
            if h_running: summary.append(f"{h_running} running")
            if h_pending: summary.append(f"{h_pending} pending")
            if h_completed: summary.append(f"{h_completed} done")
            if h_failed: summary.append(f"{h_failed} failed")
            
            summary_text = f"+ {hidden_count} more runs ({', '.join(summary)})"
            table.add_row(
                Text(summary_text, style="dim italic"),
                Text(""),
                Text(""),
                Text(""),
                Text(""),
            )
            
        return Panel(
            table,
            box=box.ROUNDED,
            title="Active Evaluations",
            border_style="blue",
            expand=True,
        )

    def _render_footer(self) -> RenderableType:
        grid = Table.grid(expand=True)
        grid.add_column(justify="left")
        grid.add_column(justify="right")
        
        grid.add_row(
            Text("Press Ctrl+C to stop", style="dim"),
            Text(f"v{__version__} • {datetime.now().strftime('%H:%M:%S')}", style="dim"),
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
        processed = state.completed + state.failed
        total_items = state.total_items or max(processed, 1)
        pulse = state.total_items == 0 and state.status == "running"

        bar = ProgressBar(
            total=total_items,
            completed=min(processed, total_items),
            width=36,
            pulse=pulse,
            complete_style="green",
            finished_style="green",
        )

        bar_row = Table.grid(expand=True, padding=(0, 0))
        bar_row.add_column(ratio=1)
        bar_row.add_row(bar)

        chips_line = self._render_progress_chips(state)
        stats_line = self._render_progress_stats(state)

        return Group(bar_row, chips_line, stats_line)

    def _render_progress_chips(self, state: RunVisualState) -> Text:
        pending_val = "—"
        if state.total_items:
            pending_val = str(max(state.total_items - (state.completed + state.failed + state.in_progress), 0))

        chips = Text()
        chips.append("✔ ", style="green")
        chips.append(str(state.completed), style="white")
        chips.append("    ", style="dim")
        chips.append("× ", style="red")
        chips.append(str(state.failed), style="white")
        chips.append("    ", style="dim")
        chips.append("↻ ", style="yellow")
        chips.append(str(state.in_progress), style="white")
        chips.append("    ", style="dim")
        chips.append("◦ ", style="cyan")
        chips.append(pending_val, style="white" if state.total_items else "dim")
        return chips

    def _render_progress_stats(self, state: RunVisualState) -> Text:
        now = time.time()
        elapsed = 0.0
        if state.start_time:
            elapsed = max(0.0, (state.end_time or now) - state.start_time)

        throughput = state.throughput()
        eta_text = None
        if throughput > 0 and state.total_items:
            remaining = max(0, state.total_items - (state.completed + state.failed))
            eta_seconds = remaining / throughput if throughput > 0 else 0.0
            eta_text = _format_duration(eta_seconds)

        parts: List[Text] = []
        parts.append(Text(f"Elapsed {_format_duration(elapsed)}", style="dim"))

        if eta_text:
            parts.append(Text(f"ETA {eta_text}", style="cyan"))

        if throughput > 0:
            parts.append(Text(f"{throughput:.2f}/s", style="white"))

        if not parts:
            return Text("-", style="dim")

        combined = Text()
        for idx, part in enumerate(parts):
            if idx:
                combined.append(" • ", style="dim")
            combined.append_text(part)
        return combined

    def _render_latency(self, state: RunVisualState) -> RenderableType:
        if not state.latency_samples:
            return Text("-", style="dim")
        
        # Sparkline
        data = state.latency_samples[-50:]
        spark_width = 24
        if len(data) > spark_width:
            step = len(data) / spark_width
            sampled = []
            idx = 0.0
            for _ in range(spark_width):
                sampled.append(data[int(idx)])
                idx += step
            data = sampled

        sparkline = Text("", style="yellow")
        if data:
            min_val = min(data)
            max_val = max(data)
            range_val = max_val - min_val
            chars = "  ▂▃▄▅▆▇█"
            result = ""
            for val in data:
                if range_val == 0:
                    index = 4 if val > 0 else 0
                else:
                    index = int((val - min_val) / range_val * (len(chars) - 1))
                result += chars[index]
            result = result.ljust(spark_width)
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
            
            text.append(f"{metric}: ", style="bold white")
            text.append(f"{avg_val:.2f}", style="white")
            
        if len(state.metrics) > 3:
            text.append(f"\n+ {len(state.metrics)-3} more", style="dim italic")
            
        return text

    def _render_status_icon(self, state: RunVisualState) -> RenderableType:
        if state.status == "running":
            status_display: RenderableType = Spinner("dots", style="cyan", text="Running")
        elif state.status == "error":
            status_display = Text("❌ Error", style="red bold")
        elif state.status == "completed":
            status_display = Text("✅ Done", style="green bold")
        else:
            status_display = Text("⏳ Pending", style="dim")

        processed = state.completed + state.failed
        total_display = state.total_items if state.total_items else "—"
        counts = Text()
        counts.append(f"{processed}/{total_display}", style="white")
        if state.total_items:
            counts.append(" • ", style="dim")
            counts.append(f"{state.percent_complete():.0f}%", style="cyan")

        grid = Table.grid(padding=(0, 0))
        grid.add_column(justify="center", no_wrap=True)
        grid.add_row(status_display)
        grid.add_row(counts)
        return grid

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

    def _start_auto_refresh(self) -> None:
        if not self.enabled or self._auto_refresh_thread:
            return
        self._auto_refresh_stop = threading.Event()

        def _ticker() -> None:
            while self.enabled and not self._auto_refresh_stop.is_set():
                try:
                    self.refresh(force=True)
                except Exception:
                    pass
                time.sleep(0.5)

        self._auto_refresh_thread = threading.Thread(target=_ticker, daemon=True)
        self._auto_refresh_thread.start()


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
    return f"{round(value):.0f}s"



def console_supports_live(console: Console) -> bool:
    """Return True when live updates should be rendered for this console."""
    return bool(getattr(console, "is_terminal", False))


_RUN_ID_RE = re.compile(r"^(?P<base>.+)-\d{8}-\d{6}(?:-.+)?$")


def _strip_run_suffix_local(name: str) -> str:
    """Strip timestamp/model suffix to recover the base name."""
    match = _RUN_ID_RE.match(name or "")
    if not match:
        return name
    return match.group("base")
