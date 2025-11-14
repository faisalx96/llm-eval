"""Multi-model orchestration with shared dashboard."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Sequence, Tuple

from rich.console import Console
from rich.live import Live

from .dashboard import RunDashboard
from .evaluator import Evaluator
from .results import EvaluationResult
from .run_spec import RunSpec


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
        dashboard_configs: List[Dict[str, Any]] = []
        for spec in self.specs:
            model_name = spec.config.get("model") or (spec.config.get("run_metadata") or {}).get("model")
            dashboard_configs.append(
                {
                    "run_id": spec.run_name,
                    "display_name": spec.name,
                    "dataset": spec.dataset,
                    "model": model_name,
                    "config": spec.config,
                }
            )

        dashboard = RunDashboard(dashboard_configs, enabled=show_tui, console=self.console)

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
        final_results: List[EvaluationResult] = []
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
        from rich.table import Table

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
