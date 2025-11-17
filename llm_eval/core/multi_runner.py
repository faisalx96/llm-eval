"""Multi-model orchestration with shared dashboard."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Sequence, Tuple

from rich.console import Console
from rich.live import Live

from .dashboard import RunDashboard, console_supports_live
from .evaluator import Evaluator
from .results import EvaluationResult, render_results_summary, summary_display_enabled
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

        live_enabled = show_tui and console_supports_live(self.console)
        dashboard = RunDashboard(dashboard_configs, enabled=live_enabled, console=self.console)

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

        final_panel = None
        if live_enabled:
            with Live(
                dashboard.render(),
                console=self.console,
                refresh_per_second=6,
                screen=True,
                transient=True,
                vertical_overflow="crop",
            ) as live:
                dashboard.bind(live)
                results = await asyncio.gather(*tasks, return_exceptions=True)
                final_panel = dashboard.render()
        else:
            results = await asyncio.gather(*tasks, return_exceptions=True)

        if live_enabled and final_panel is not None:
            self.console.print(final_panel)

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

    def print_summary(self, results: Sequence[EvaluationResult], *, force: bool = False) -> None:
        """Render a shared summary panel that works for single or multi runs."""
        if not force and not summary_display_enabled():
            return
        panel = render_results_summary(results, title="[bold cyan]Multi-Run Summary[/bold cyan]")
        self.console.print(panel)

    def print_saved_paths(self, results: Sequence[EvaluationResult]) -> None:
        notices = []
        for result in results:
            notice = result.consume_saved_notice(include_run_name=True)
            if notice:
                notices.append(notice)
        if not notices:
            return
        self.console.print("[blue]📁 Results saved:[/blue]")
        for entry in notices:
            self.console.print(f"  - {entry}")
