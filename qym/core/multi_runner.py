"""Multi-model orchestration with shared dashboard."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Sequence, Tuple

from rich.console import Console
from rich.live import Live
from rich.table import Table

from .dashboard import RunDashboard, console_supports_live
from .evaluator import Evaluator
from .results import EvaluationResult, render_results_summary, summary_display_enabled
from .config import RunSpec, EvaluatorConfig

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
            
            # Use Pydantic validator logic via Config
            normalized = EvaluatorConfig.normalize_models(models_value)
            if not normalized:
                return [def_dict]
                
            expanded = []
            for model_name in normalized:
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
                
                # Prepare config for Pydantic
                raw_config = dict(model_variant.get("config") or {})
                raw_config.pop("models", None)
                task_display = str(
                    model_variant.get("task_function")
                    or getattr(model_variant.get("task"), "__name__", "task")
                )
                
                # Merge metadata
                metadata = dict(model_variant.get("metadata") or {})
                model_name = model_variant.get("model")
                if model_name:
                    metadata.setdefault("model", model_name)
                    raw_config["model"] = model_name
                
                if metadata:
                    merged_meta = {**metadata, **dict(raw_config.get("run_metadata") or {})}
                    raw_config["run_metadata"] = merged_meta
                
                # Determine run name
                user_provided_name = bool(model_variant.get("name") or raw_config.get("run_name"))
                base_name = model_variant.get("name") or raw_config.get("run_name") or task_display
                
                if model_variant.get("display_name"):
                    # If display_name is already provided (e.g. by Evaluator), use it
                    # But we still need to ensure unique run_name if not provided
                    name, _ = Evaluator.build_run_identifiers(base_name, model_name, add_suffix=not user_provided_name)
                    display = model_variant.get("display_name")
                    # If the provided name was just the base name, we might want to use the generated unique name
                    if not model_variant.get("name"):
                         pass # name is already set above
                else:
                    name, display = Evaluator.build_run_identifiers(base_name, model_name, add_suffix=not user_provided_name)
                raw_config["run_name"] = name

                # Create RunSpec using Pydantic
                try:
                    spec = RunSpec(
                        name=name,
                        display_name=display,
                        task=model_variant.get("task"),
                        dataset=model_variant.get("dataset"),
                        metrics=model_variant.get("metrics"),
                        config=EvaluatorConfig(**raw_config),
                        metadata=metadata,
                        output_path=model_variant.get("output"),
                        task_file=str(model_variant.get("task_file") or getattr(model_variant.get("task"), "__module__", "<python-callable>")),
                        task_function=str(model_variant.get("task_function") or getattr(model_variant.get("task"), "__name__", "<callable>"))
                    )
                    specs.append(spec)
                except Exception as e:
                    raise ValueError(f"Run #{idx} invalid: {e}")

        if not specs:
            raise ValueError("No valid run configurations provided")
            
        return cls(specs, console=console)

    async def arun(
        self,
        show_tui: bool = True,
        auto_save: bool = True,
        save_format: str = "csv",
        max_parallel_runs: Optional[int] = None,
    ) -> List[EvaluationResult]:
        # 1. Pre-load unique datasets to avoid redundant downloads
        from .dataset import LangfuseDataset
        from langfuse import Langfuse
        import os

        # Identify unique dataset names that haven't been loaded yet
        unique_dataset_names = set()
        for spec in self.specs:
            if isinstance(spec.dataset, str):
                unique_dataset_names.add(spec.dataset)
        
        dataset_cache: Dict[str, LangfuseDataset] = {}
        
        if unique_dataset_names:
            # Initialize a temporary client for downloading
            # We use the config from the first spec that has credentials, or env vars
            # This is a best-effort to find credentials
            first_config = self.specs[0].config
            public_key = first_config.langfuse_public_key or os.getenv('LANGFUSE_PUBLIC_KEY')
            secret_key = first_config.langfuse_secret_key or os.getenv('LANGFUSE_SECRET_KEY')
            host = first_config.langfuse_host or os.getenv('LANGFUSE_HOST') or 'https://cloud.langfuse.com'
            
            # Use the timeout from the first config as a reasonable default
            timeout = first_config.timeout
            
            if public_key and secret_key:
                try:
                    client = Langfuse(
                        public_key=public_key,
                        secret_key=secret_key,
                        host=host,
                        timeout=timeout
                    )
                    
                    self.console.print(f"[dim]Pre-loading {len(unique_dataset_names)} unique datasets...[/dim]")
                    for name in unique_dataset_names:
                        try:
                            dataset_cache[name] = LangfuseDataset(client, name)
                        except Exception as e:
                            self.console.print(f"[yellow]Warning: Failed to pre-load dataset '{name}': {e}[/yellow]")
                except Exception as e:
                    self.console.print(f"[yellow]Warning: Failed to initialize Langfuse client for pre-loading: {e}[/yellow]")

        dashboard_configs: List[Dict[str, Any]] = []
        for spec in self.specs:
            # Inject pre-loaded dataset if available
            if isinstance(spec.dataset, str) and spec.dataset in dataset_cache:
                spec.dataset = dataset_cache[spec.dataset]

            model_name = spec.config.model or spec.config.run_metadata.get("model")
            display_text = spec.display_name or spec.name
            
            # Handle dataset name for display
            ds_name = spec.dataset
            if hasattr(spec.dataset, 'name'):
                ds_name = spec.dataset.name
                
            dashboard_configs.append(
                {
                    "run_id": spec.name,
                    "display_name": display_text,
                    "dataset": ds_name,
                    "model": model_name,
                    "config": spec.config.model_dump(),
                }
            )

        live_enabled = show_tui and console_supports_live(self.console)
        dashboard = RunDashboard(dashboard_configs, enabled=live_enabled, console=self.console)

        # Create semaphore if max_parallel_runs is set
        semaphore = asyncio.Semaphore(max_parallel_runs) if max_parallel_runs else None

        async def _run_spec(spec: RunSpec):
            # Acquire semaphore if limiting parallel runs
            if semaphore:
                async with semaphore:
                    return await _run_spec_inner(spec)
            else:
                return await _run_spec_inner(spec)

        async def _run_spec_inner(spec: RunSpec):
            observer = dashboard.create_observer(spec.name)
            # Pass config object directly
            evaluator = Evaluator(
                task=spec.task,
                dataset=spec.dataset,
                metrics=spec.metrics,
                config=spec.config,
                observer=observer,
            )
            try:
                result = await evaluator.arun(
                    show_tui=False,
                    auto_save=auto_save,
                    save_format=save_format,
                )
                return result
            except Exception as exc:
                dashboard.mark_run_exception(spec.name, str(exc))
                raise

        tasks = [asyncio.create_task(_run_spec(spec)) for spec in self.specs]

        final_panel = None
        if live_enabled:
            dashboard_bound = False
            try:
                with Live(
                    dashboard.render(),
                    console=self.console,
                    refresh_per_second=12,
                    screen=False,
                    transient=True,
                    vertical_overflow="crop",
                ) as live:
                    dashboard.bind(live)
                    dashboard_bound = True
                    try:
                        results = await asyncio.gather(*tasks, return_exceptions=True)
                    except KeyboardInterrupt:
                        for task in tasks:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                        raise
                    finally:
                        final_panel = dashboard.render()
            finally:
                if dashboard_bound:
                    dashboard.shutdown()
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
            summary = ", ".join(f"{spec.name}: {err}" for spec, err in errors)
            raise RuntimeError(f"One or more runs failed: {summary}")

        return final_results

    def print_summary(self, results: Sequence[EvaluationResult], *, force: bool = False) -> None:
        """Render a shared summary panel that works for single or multi runs."""
        if not force and not summary_display_enabled():
            return
        panel = render_results_summary(results, title="[bold cyan]Multi-Run Summary[/bold cyan]")
        self.console.print(panel)

    def print_saved_paths(self, results: Sequence[EvaluationResult]) -> None:
        table = Table(box=None, show_header=False, padding=(0, 0))
        table.add_column("Saved to", style="dim")

        rows_added = 0
        for result in results:
            if isinstance(result, Exception):
                continue
            notice = result.consume_saved_notice(include_run_name=True)
            if not notice:
                continue
            path = notice.split(":", 1)[-1] if ":" in notice else notice
            table.add_row(path.strip())
            rows_added += 1

        if rows_added == 0:
            return

        self.console.print("[blue]📁 Results saved[/blue]")
        self.console.print(table)
