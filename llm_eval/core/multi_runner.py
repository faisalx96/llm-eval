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
from pathlib import Path



class MultiModelRunner:
    """Coordinate multiple Evaluator instances in parallel."""

    def __init__(self, specs: Sequence[RunSpec], console: Optional[Console] = None) -> None:
        self.specs = list(specs)
        self.console = console or Console()

    @classmethod
    def from_runs(cls, runs: Sequence[Any], console: Optional[Console] = None) -> "MultiModelRunner":
        """Create a runner from a list of run definitions (dicts or RunSpecs)."""
        if not runs:
            raise ValueError("runs must contain at least one configuration")

        specs: List[RunSpec] = []

        def _expand_models(def_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
            models_value = def_dict.get("models")
            if models_value is None:
                return [def_dict]
            # Use Evaluator's normalize logic
            model_list = Evaluator._normalize_models(models_value)
            if not model_list:
                return [def_dict]
            expanded = []
            for model_name in model_list:
                clone = dict(def_dict)
                clone.pop("models", None)
                clone["model"] = model_name
                expanded.append(clone)
            return expanded

        for idx, definition in enumerate(runs, start=1):
            if isinstance(definition, RunSpec):
                specs.append(definition)
                continue
            if not isinstance(definition, dict):
                raise ValueError(f"Run #{idx} must be a dict or RunSpec")

            expanded_defs = _expand_models(definition)

            for model_variant in expanded_defs:
                current_idx = len(specs) + 1

                if "task" not in model_variant or not callable(model_variant["task"]):
                    raise ValueError(f"Run #{idx} missing callable 'task'")
                if "dataset" not in model_variant:
                    raise ValueError(f"Run #{idx} missing 'dataset'")
                if "metrics" not in model_variant:
                    raise ValueError(f"Run #{idx} missing 'metrics'")

                task_callable = model_variant["task"]
                dataset = model_variant["dataset"]
                metrics_value = model_variant["metrics"]

                if isinstance(metrics_value, str):
                    metrics = [m.strip() for m in metrics_value.split(",") if m.strip()]
                elif isinstance(metrics_value, (list, tuple, set)):
                    metrics = []
                    for metric in metrics_value:
                        if isinstance(metric, str):
                            metric_name = metric.strip()
                            if metric_name:
                                metrics.append(metric_name)
                        elif callable(metric):
                            metrics.append(metric)
                        else:
                            raise ValueError(f"Run #{idx} metric entries must be str or callable")
                else:
                    raise ValueError(f"Run #{idx} metrics must be string or list")

                if not metrics:
                    raise ValueError(f"Run #{idx} has no metrics")

                config = dict(model_variant.get("config") or {})
                config.pop("models", None)
                metadata = dict(model_variant.get("metadata") or {})
                model_name = model_variant.get("model")
                if model_name:
                    metadata.setdefault("model", model_name)
                    config["model"] = model_name
                if metadata:
                    merged_meta = {**metadata, **dict(config.get("run_metadata") or {})}
                    config["run_metadata"] = merged_meta

                base_name = model_variant.get("name") or config.get("run_name") or f"run-{current_idx}"
                name = f"{base_name}-{model_name}" if model_name and not base_name.endswith(str(model_name)) else base_name
                config.setdefault("run_name", name)

                task_file = model_variant.get("task_file") or getattr(task_callable, "__module__", "<python-callable>")
                task_function = model_variant.get("task_function") or getattr(task_callable, "__name__", "<callable>")

                output_value = model_variant.get("output")
                output_path = None
                if output_value:
                    output_path = Path(output_value).expanduser()

                specs.append(
                    RunSpec(
                        name=name,
                        task=task_callable,
                        dataset=dataset,
                        metrics=metrics,
                        task_file=str(task_file),
                        task_function=str(task_function),
                        config=config,
                        output_path=output_path,
                    )
                )

        if not specs:
            raise ValueError("No valid run configurations provided")
            
        return cls(specs, console=console)

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
