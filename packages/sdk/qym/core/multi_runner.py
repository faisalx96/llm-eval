"""Multi-model orchestration with shared dashboard."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
from uuid import uuid4
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

from rich.console import Console
from rich.live import Live
from rich.table import Table

from .dashboard import RunDashboard, console_supports_live
from .evaluator import Evaluator
from .observers import CompositeEvaluationObserver, EvaluationObserver
from .results import EvaluationResult, render_results_summary, summary_display_enabled
from .config import RunSpec, EvaluatorConfig


class MultiModelRunner:
    """Coordinate multiple Evaluator instances in parallel."""

    def __init__(
        self,
        specs: Sequence[RunSpec],
        console: Optional[Console] = None,
        observer: Optional[EvaluationObserver] = None,
    ) -> None:
        self.specs = list(specs)
        self.console = console or Console()
        self.observer = observer
        self.matrix_id = f"run-matrix-{uuid4().hex[:8]}"

    @classmethod
    def from_runs(
        cls,
        runs: Sequence[Any],
        console: Optional[Console] = None,
        observer: Optional[EvaluationObserver] = None,
    ) -> "MultiModelRunner":
        """Create a runner from a list of run definitions (dicts or RunSpecs)."""
        if not runs:
            raise ValueError("runs must contain at least one configuration")

        # Repeat-run guidance: duplicating the same spec k times was the old
        # way to get pass@k. samples=k is the native primitive now.
        seen_signatures: Dict[Tuple, int] = {}
        for definition in runs:
            if isinstance(definition, dict):
                sig = (
                    str(definition.get("task")),
                    str(definition.get("task_file")),
                    str(definition.get("task_function")),
                    str(definition.get("dataset")),
                    str(definition.get("model") or definition.get("models")),
                    json.dumps(definition.get("config") or {}, sort_keys=True, default=str),
                )
                seen_signatures[sig] = seen_signatures.get(sig, 0) + 1
        dup_count = max(seen_signatures.values(), default=0)
        if dup_count > 1:
            logger.warning(
                "Detected %d identical run specs — did you mean samples=%d? "
                "Repeat runs are native now: Evaluator(..., samples=%d) runs "
                "every item %d times as ONE run with Pass@k/Pass^k reported.",
                dup_count, dup_count, dup_count, dup_count,
            )

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
                    merged_meta = {
                        **metadata,
                        **dict(raw_config.get("run_metadata") or {}),
                    }
                    raw_config["run_metadata"] = merged_meta

                # Determine run name
                user_provided_name = bool(
                    model_variant.get("name") or raw_config.get("run_name")
                )
                base_name = (
                    model_variant.get("name")
                    or raw_config.get("run_name")
                    or task_display
                )

                if model_variant.get("display_name"):
                    # If display_name is already provided (e.g. by Evaluator), use it
                    # But we still need to ensure unique run_name if not provided
                    name, _ = Evaluator.build_run_identifiers(
                        base_name, model_name, add_suffix=not user_provided_name
                    )
                    display = model_variant.get("display_name")
                    # If the provided name was just the base name, we might want to use the generated unique name
                    if not model_variant.get("name"):
                        pass  # name is already set above
                else:
                    name, display = Evaluator.build_run_identifiers(
                        base_name, model_name, add_suffix=not user_provided_name
                    )
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
                        task_file=str(
                            model_variant.get("task_file")
                            or getattr(
                                model_variant.get("task"),
                                "__module__",
                                "<python-callable>",
                            )
                        ),
                        task_function=str(
                            model_variant.get("task_function")
                            or getattr(
                                model_variant.get("task"), "__name__", "<callable>"
                            )
                        ),
                    )
                    specs.append(spec)
                except Exception as e:
                    raise ValueError(f"Run #{idx} invalid: {e}")

        if not specs:
            raise ValueError("No valid run configurations provided")

        return cls(specs, console=console, observer=observer)

    def _build_run_matrix(self) -> List[Dict[str, Any]]:
        matrix: List[Dict[str, Any]] = []
        for index, spec in enumerate(self.specs):
            model_name = spec.config.model or spec.config.run_metadata.get("model")
            ds_name = spec.dataset
            if hasattr(spec.dataset, "name"):
                ds_name = spec.dataset.name
            total_items = None
            try:
                if hasattr(spec.dataset, "get_items"):
                    total_items = len(spec.dataset.get_items())
            except Exception:
                total_items = None
            matrix.append(
                {
                    "index": index,
                    "run_id": spec.name,
                    "display_name": spec.display_name or spec.name,
                    "task": spec.config.task_name or spec.task_function,
                    "task_file": spec.task_file,
                    "task_function": spec.task_function,
                    "dataset": str(ds_name),
                    "model": model_name,
                    "metrics": [
                        metric
                        if isinstance(metric, str)
                        else getattr(metric, "__name__", str(metric))
                        for metric in spec.metrics
                    ],
                    "total_items": total_items,
                    "status": "pending",
                    "qym_url": None,
                    "platform_run_id": None,
                }
            )
        return matrix

    def _notify_observer(self, method: str, **payload: Any) -> None:
        if self.observer is None:
            return
        callback = getattr(self.observer, method, None)
        if callable(callback):
            try:
                callback(**payload)
            except Exception:
                pass

    async def arun(
        self,
        show_tui: bool = True,
        auto_save: bool = True,
        save_format: str = "csv",
        max_parallel_runs: Optional[int] = None,
    ) -> List[EvaluationResult]:
        # 1. Pre-load unique qym platform/local datasets to avoid redundant downloads.
        from .dataset import resolve_dataset

        # Identify unique dataset specs that haven't been loaded yet.
        unique_dataset_names = set()
        for spec in self.specs:
            if isinstance(spec.dataset, str):
                unique_dataset_names.add(
                    (
                        spec.dataset,
                        spec.config.dataset_version,
                        spec.config.dataset_alias,
                        spec.config.platform_url,
                        spec.config.platform_api_key,
                    )
                )

        dataset_cache: Dict[tuple, Any] = {}

        if unique_dataset_names:
            self.console.print(
                f"[dim]Pre-loading {len(unique_dataset_names)} unique datasets...[/dim]"
            )
            for key in unique_dataset_names:
                name, version, alias, platform_url, api_key = key
                try:
                    dataset_cache[key] = resolve_dataset(
                        name,
                        version=version,
                        alias=alias,
                        platform_url=platform_url,
                        api_key=api_key,
                    )
                except Exception as e:
                    self.console.print(
                        f"[yellow]Warning: Failed to pre-load dataset '{name}': {e}[/yellow]"
                    )

        for spec in self.specs:
            if isinstance(spec.dataset, str):
                key = (
                    spec.dataset,
                    spec.config.dataset_version,
                    spec.config.dataset_alias,
                    spec.config.platform_url,
                    spec.config.platform_api_key,
                )
                if key in dataset_cache:
                    spec.dataset = dataset_cache[key]

        run_matrix = self._build_run_matrix()
        self._notify_observer(
            "on_run_matrix",
            matrix_id=self.matrix_id,
            runs=run_matrix,
            total_runs=len(run_matrix),
        )

        dashboard_configs: List[Dict[str, Any]] = []
        for spec in self.specs:
            # Inject pre-loaded dataset if available
            model_name = spec.config.model or spec.config.run_metadata.get("model")
            display_text = spec.display_name or spec.name

            # Handle dataset name for display
            ds_name = spec.dataset
            if hasattr(spec.dataset, "name"):
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
        dashboard = RunDashboard(
            dashboard_configs, enabled=live_enabled, console=self.console
        )

        # Create semaphore if max_parallel_runs is set
        semaphore = asyncio.Semaphore(max_parallel_runs) if max_parallel_runs else None

        # Size the thread pool to match actual parallelism so sync tasks don't queue.
        # Effective parallel models = min(num_specs, max_parallel_runs or num_specs)
        num_specs = len(self.specs)
        effective_parallel = (
            min(num_specs, max_parallel_runs) if max_parallel_runs else num_specs
        )
        max_conc = max((s.config.max_concurrency or 10) for s in self.specs)
        pool_size = max_conc * effective_parallel
        loop = asyncio.get_running_loop()
        loop.set_default_executor(
            concurrent.futures.ThreadPoolExecutor(max_workers=pool_size)
        )
        loop._qym_executor_set = True

        async def _run_spec(spec: RunSpec):
            # Acquire semaphore if limiting parallel runs
            if semaphore:
                async with semaphore:
                    return await _run_spec_inner(spec)
            else:
                return await _run_spec_inner(spec)

        # Track active evaluators so interrupt handler can send STOPPED
        _active_evaluators: list = []
        advisory_tasks_emitted: set[str] = set()

        async def _run_spec_inner(spec: RunSpec):
            dashboard_observer = dashboard.create_observer(spec.name)
            observer = (
                CompositeEvaluationObserver([dashboard_observer, self.observer])
                if self.observer is not None
                else dashboard_observer
            )
            # Pass config object directly
            evaluator = Evaluator(
                task=spec.task,
                dataset=spec.dataset,
                metrics=spec.metrics,
                config=spec.config,
                observer=observer,
            )
            evaluator._sync_threadpool_advisory_registry = advisory_tasks_emitted
            _active_evaluators.append(evaluator)
            evaluator._maybe_emit_sync_threadpool_advisory(
                parallel_runs=effective_parallel
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

        self._active_evaluators = _active_evaluators
        tasks = [asyncio.create_task(_run_spec(spec)) for spec in self.specs]

        final_panel = None
        interrupted = False
        cancel_exc: Optional[BaseException] = None
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
                    except (KeyboardInterrupt, asyncio.CancelledError) as exc:
                        interrupted = True
                        cancel_exc = exc
                        for task in tasks:
                            task.cancel()
                        results = await asyncio.gather(*tasks, return_exceptions=True)
                    finally:
                        final_panel = dashboard.render()
            finally:
                if dashboard_bound:
                    dashboard.shutdown()
        else:
            results = await asyncio.gather(*tasks, return_exceptions=True)

        if live_enabled and final_panel is not None:
            self.console.print(final_panel)

        if cancel_exc is not None:
            raise cancel_exc

        errors: List[Tuple[RunSpec, Exception]] = []
        final_results: List[EvaluationResult] = []
        for spec, result in zip(self.specs, results):
            if isinstance(result, Exception):
                errors.append((spec, result))
            else:
                if interrupted:
                    result.interrupted = True
                final_results.append(result)

        if errors and not interrupted:
            summary = ", ".join(f"{spec.name}: {err}" for spec, err in errors)
            raise RuntimeError(f"One or more runs failed: {summary}")

        # Force-close any remaining PlatformEventStream threads to prevent hang.
        # Each evaluator's arun() already called close(), but if any are stuck
        # (retry loops, network issues), force them to stop.
        for ev in _active_evaluators:
            stream = getattr(ev, "_platform_stream", None)
            if stream is not None:
                try:
                    if hasattr(stream, "_stop"):
                        stream._stop.set()  # Signal the background thread to exit
                except Exception:
                    pass

        # Shut down the thread pool so asyncio.run() doesn't hang waiting for idle threads.
        try:
            executor = loop.get_default_executor()
            if executor is not None:
                executor.shutdown(wait=False)
        except Exception:
            pass

        return final_results

    def print_summary(
        self, results: Sequence[EvaluationResult], *, force: bool = False
    ) -> None:
        """Render a shared summary panel that works for single or multi runs."""
        if not force and not summary_display_enabled():
            return
        panel = render_results_summary(
            results, title="[bold cyan]Multi-Run Summary[/bold cyan]"
        )
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
