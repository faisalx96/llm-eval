"""Main Evaluator class for LLM evaluation."""

import asyncio
import inspect
import os
import traceback
from typing import Any, Callable, Dict, List, Optional, Sequence, Union, Tuple
from datetime import datetime
import time
import subprocess
from pathlib import Path
import copy
from contextlib import nullcontext
import re

from langfuse import Langfuse
from rich.console import Console
from rich.live import Live
from rich.table import Table

from .results import EvaluationResult
from .dataset import LangfuseDataset
from .progress import ProgressTracker, ProgressObserver
from .observers import (
    EvaluationObserver,
    NullEvaluationObserver,
    CompositeEvaluationObserver,
)
from .dashboard import RunDashboard, console_supports_live
from ..adapters.base import TaskAdapter, auto_detect_task
from ..metrics.registry import get_metric


def _strip_model_provider(model_name: Optional[str]) -> str:
    """Remove provider prefix from model name (e.g., 'qwen/qwen3-235b' -> 'qwen3-235b')."""
    if not model_name:
        return ''
    slash_idx = model_name.find('/')
    return model_name[slash_idx + 1:] if slash_idx > 0 else model_name


from ..utils.errors import LangfuseConnectionError, DatasetNotFoundError
from ..server.app import UIServer
import json
import logging

logger = logging.getLogger(__name__)
 


console = Console()


from .config import EvaluatorConfig

class Evaluator:
    """
    Simple evaluator for LLM tasks using Langfuse datasets.
    """
    
    def __init__(
        self,
        task: Any,
        dataset: Union[str, LangfuseDataset], 
        metrics: List[Union[str, Callable]],
        config: Optional[Union[Dict[str, Any], EvaluatorConfig]] = None,
        observer: Optional[EvaluationObserver] = None,
        model: Optional[Union[str, Sequence[str]]] = None,
        langfuse_client: Optional[Langfuse] = None,
    ):
        """
        Initialize the evaluator.
        """

        # Parse config
        if isinstance(config, EvaluatorConfig):
            self.config = config
        else:
            self.config = EvaluatorConfig(**(config or {}))
        self._task_name = _derive_task_name(task)
            
        # Override model if provided explicitly
        if model is not None:
            if isinstance(model, str):
                self.config.model = model
                self.config.models = [model]
            else:
                self.config.models = list(model)
                self.config.model = model[0] if model else None

        self.task = task
        self._raw_metrics = list(metrics)
        self.metrics = self._prepare_metrics(metrics)
        
        # Initialize Langfuse client
        self.client = langfuse_client or self._init_langfuse()
        
        # Load and validate dataset
        if isinstance(dataset, str):
            self.dataset_name = dataset
            self.dataset = LangfuseDataset(self.client, dataset)
        else:
            self.dataset = dataset
            self.dataset_name = getattr(dataset, "dataset_name", getattr(dataset, "name", "unknown"))
        
        # Prepare task adapter
        self.task_adapter = auto_detect_task(task, self.client)
        
        # Configuration shortcuts
        self.max_concurrency = self.config.max_concurrency
        self.timeout = self.config.timeout

        # Model handling - strip provider prefix once, keep full name for user's task
        # e.g., "qwen/qwen3-235b" -> model_name="qwen3-235b", model_name_full="qwen/qwen3-235b"
        self.model_name_full = self.config.model  # Original with provider (for user's task)
        self.model_name = _strip_model_provider(self.config.model)  # Stripped (for display, paths, IDs)
        self.models = [_strip_model_provider(m) for m in (self.config.models or [])]
        self.models_full = self.config.models or []  # Original list with providers

        base_name_raw = (self.config.run_name or "").strip()
        base_name_stripped, has_suffix = _strip_run_suffix(base_name_raw)
        base_name = base_name_stripped or self._task_name
        if has_suffix:
            self.run_name = base_name_raw
            self.display_name = f"{base_name}_task"
        else:
            # Only add suffix if the name wasn't explicitly provided by user
            # We assume if it came from config.run_name, it's user provided
            user_provided_name = bool(self.config.run_name)
            self.run_name, self.display_name = self.build_run_identifiers(
                base_name=base_name,
                model_name=self.model_name,  # Use stripped model name
                add_suffix=not user_provided_name
            )
        self.run_metadata = self.config.run_metadata

        if self.model_name:
            self.run_metadata.setdefault('model', self.model_name)

        # Display name for UI: prefer run_name, but keep a readable task hint
        self.display_name = self.config.run_name
        if self._task_name and self._task_name not in (self.display_name or ""):
            self.display_name = f"{self.display_name} [{self._task_name}]"
            
        base_observer = observer or NullEvaluationObserver()
        self.observer = CompositeEvaluationObserver([base_observer])

        # Langfuse IDs for URL building (populated during run)
        self._langfuse_dataset_id: Optional[str] = getattr(self.dataset, 'id', None)
        self._langfuse_run_id: Optional[str] = None

    # Class-level counter for ensuring unique run IDs within the same process
    _run_id_counter: Dict[str, int] = {}

    @staticmethod
    def build_run_identifiers(base_name: str, model_name: Optional[str], add_suffix: bool = False) -> Tuple[str, str]:
        """Return (run_id_with_suffixes, display_name_for_tui).

        Ensures unique run IDs even when the same model is used multiple times
        by appending a counter when duplicates are detected.

        - run_id: Used for Langfuse logging, must be unique
        - display_name: Used for TUI, keeps original naming convention
        """
        # Matches YYMMDD-HHMM pattern
        timestamp_pattern = r"-\d{6}-\d{4}"

        if re.search(timestamp_pattern, base_name):
            # Already has timestamp, use as is
            run_id = base_name
            display = base_name
            display = re.sub(timestamp_pattern, "", display)
            if add_suffix and not display.endswith("_task"):
                 display = f"{display}_task"
            return run_id, display

        timestamp = datetime.now().strftime("%y%m%d-%H%M")
        base_run_id = base_name
        if model_name:
            base_run_id = f"{base_run_id}-{model_name}"
        base_run_id = f"{base_run_id}-{timestamp}"

        # Ensure uniqueness by checking if this run_id was already used
        # and appending a counter if needed (starts from 1 for first duplicate)
        if base_run_id in Evaluator._run_id_counter:
            Evaluator._run_id_counter[base_run_id] += 1
            counter = Evaluator._run_id_counter[base_run_id]
            run_id = f"{base_run_id}-{counter}"
        else:
            Evaluator._run_id_counter[base_run_id] = 0
            run_id = base_run_id

        # Display name: Keep original convention (no counter suffix)
        if add_suffix and not base_name.endswith("_task"):
            display = f"{base_name}_task"
        else:
            display = base_name

        return run_id, display


    def _extract_trace_meta(self, trace: Any) -> Dict[str, Any]:
        """Extract Langfuse trace_id and URL using SDK-documented methods.

        Prefers callable accessors (e.g., trace.trace_id()) and then attributes.
        """
        meta: Dict[str, Any] = {"trace_id": None, "trace_url": None}
        # trace_id: prefer method, then attribute fallbacks
        try:
            if hasattr(trace, 'trace_id'):
                ti = getattr(trace, 'trace_id')
                meta["trace_id"] = str(ti() if callable(ti) else ti)
        except Exception:
            meta["trace_id"] = None
        if not meta["trace_id"]:
            for name in ("id", "traceId", "observation_id"):
                try:
                    if hasattr(trace, name):
                        val = getattr(trace, name)
                        if val:
                            meta["trace_id"] = str(val)
                            break
                except Exception as e:
                    logger.debug(f"Failed to extract trace_id from {name}: {e}")
                    continue
        # URL: try common getters, then attribute
        url = None
        for getter in ("get_trace_url", "get_url"):
            if hasattr(trace, getter):
                try:
                    url = getattr(trace, getter)()
                    if url:
                        break
                except Exception as e:
                    logger.debug(f"Failed to get URL via {getter}: {e}")
                    url = None
        if not url and hasattr(trace, 'url'):
            try:
                url = trace.url
            except Exception:
                url = None
        if url:
            meta["trace_url"] = str(url)
        return meta

    def _build_run_info(self, result: Optional[EvaluationResult] = None) -> Dict[str, Any]:
        """Assemble run-level metadata for the frontend."""
        # Version
        version = None
        try:
            from .. import __version__ as _v
            version = _v
        except Exception:
            try:
                import importlib.metadata as _im
                version = _im.version("llm-eval")
            except Exception:
                version = None

        # Git SHA (best-effort)
        git_sha = None
        try:
            sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL)
            git_sha = sha.decode().strip()
        except Exception:
            git_sha = None

        run_block: Dict[str, Any] = {
            "dataset_name": self.dataset_name,
            "run_name": self.run_name,
            "config": {
                "max_concurrency": self.max_concurrency,
                "timeout": self.timeout,
                "run_metadata": self.run_metadata,
            },
            "model": self.model_name,
            "version": version,
            "git_sha": git_sha,
            "cli_invocation": self.config.cli_invocation,
            "metric_names": list(self.metrics.keys()),
            "langfuse_host": getattr(self, 'langfuse_host', None),
            "langfuse_project_id": getattr(self, 'langfuse_project_id', None),
        }

        if result is not None:
            try:
                run_block["started_at"] = result.start_time.isoformat() if result.start_time else None
                run_block["ended_at"] = result.end_time.isoformat() if result.end_time else None
                run_block["total_items"] = result.total_items
            except Exception:
                pass

        return run_block
    
    def _init_langfuse(self) -> Langfuse:
        """Initialize Langfuse client with error handling."""
        # Auto-load .env file if it exists
        if os.path.exists('.env'):
            try:
                from dotenv import load_dotenv
                load_dotenv()
            except ImportError:
                logger.warning("python-dotenv not installed, skipping .env loading")
                pass  # dotenv not installed, skip
        
        # Get credentials from config or environment
        public_key = self.config.langfuse_public_key or os.getenv('LANGFUSE_PUBLIC_KEY')
        secret_key = self.config.langfuse_secret_key or os.getenv('LANGFUSE_SECRET_KEY')
        host = self.config.langfuse_host or os.getenv('LANGFUSE_HOST')
        
        # Validate required credentials
        if not public_key:
            raise LangfuseConnectionError(
                "Missing Langfuse public key. Please:\n"
                "1. Set LANGFUSE_PUBLIC_KEY environment variable, or\n"
                "2. Add 'langfuse_public_key' to evaluator config, or\n"
                "3. Create a .env file with LANGFUSE_PUBLIC_KEY=your_key"
            )
        
        if not secret_key:
            raise LangfuseConnectionError(
                "Missing Langfuse secret key. Please:\n"
                "1. Set LANGFUSE_SECRET_KEY environment variable, or\n"
                "2. Add 'langfuse_secret_key' to evaluator config, or\n"
                "3. Create a .env file with LANGFUSE_SECRET_KEY=your_key"
            )
        
        try:
            client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=host,
                timeout=self.config.timeout
            )
            # Expose host for frontend links (default to cloud)
            try:
                self.langfuse_host = host or 'https://cloud.langfuse.com'
            except Exception:
                self.langfuse_host = 'https://cloud.langfuse.com'
            # Optional project id for deep-links
            try:
                self.langfuse_project_id = (
                    self.config.langfuse_project_id
                    or os.getenv('LANGFUSE_PROJECT_ID')
                )
            except Exception:
                self.langfuse_project_id = None
            return client
        except Exception as e:
            if "401" in str(e) or "unauthorized" in str(e).lower():
                raise LangfuseConnectionError(
                    "Invalid Langfuse credentials. Please check your:\n"
                    "- LANGFUSE_PUBLIC_KEY\n"
                    "- LANGFUSE_SECRET_KEY\n"
                    "- LANGFUSE_HOST (if using custom instance)"
                )
            raise LangfuseConnectionError(f"Failed to connect to Langfuse: {e}")
    


    def _prepare_metrics(self, metrics: List[Union[str, Callable]]) -> Dict[str, Callable]:
        """Convert metric list to dict of callables."""
        prepared = {}
        for metric in metrics:
            if isinstance(metric, str):
                prepared[metric] = get_metric(metric)
            elif callable(metric):
                name = getattr(metric, '__name__', f'custom_metric_{len(prepared)}')
                prepared[name] = metric
            else:
                raise ValueError(f"Metric must be string or callable, got {type(metric)}")
        return prepared

    def _build_langfuse_url(self) -> Optional[str]:
        """Build Langfuse dataset run URL using dataset ID and run ID."""
        try:
            host = getattr(self, 'langfuse_host', None)
            project_id = getattr(self, 'langfuse_project_id', None)
            dataset_id = self._langfuse_dataset_id
            run_id = self._langfuse_run_id

            if not host or not project_id or not dataset_id or not run_id:
                return None

            # Langfuse dataset run URL format uses IDs, not names
            return f"{host.rstrip('/')}/project/{project_id}/datasets/{dataset_id}/runs/{run_id}"
        except Exception:
            return None

    def _attach_observer(self, observer: Optional[EvaluationObserver]) -> None:
        """Attach an additional observer (e.g., dashboards)."""
        if observer is None:
            return
        if isinstance(self.observer, CompositeEvaluationObserver):
            self.observer.add_observer(observer)
        else:
            self.observer = CompositeEvaluationObserver([self.observer, observer])

    def _notify_observer(self, method: str, **payload: Any) -> None:
        """Best-effort observer notification."""
        try:
            callback = getattr(self.observer, method, None)
        except Exception:
            callback = None
        if callable(callback):
            try:
                callback(run_id=self.run_name, **payload)
            except Exception as e:
                logger.error(f"Observer callback {method} failed: {e}")
                pass
    
    def run(self, show_tui: bool = True, auto_save: bool = True, save_format: str = "csv") -> Union[EvaluationResult, List[EvaluationResult]]:
        """
        Run the evaluation synchronously.

        Args:
            show_tui: Whether to show the terminal UI dashboard (default: True)
            auto_save: Whether to automatically save results after evaluation (default: True)
            save_format: Format for auto-save - "csv", "json", or "xlsx" (default: "csv")

        Returns:
            EvaluationResult object with scores and statistics

        Note:
            The Web UI is always available at the URL printed at startup.
        """
        # Check if we're already in an event loop (e.g., Jupyter notebook)
        try:
            asyncio.get_running_loop()
            # We're in a running loop (like Jupyter), use nest_asyncio
            import nest_asyncio
            nest_asyncio.apply()
        except RuntimeError:
            # No event loop running, which is fine
            pass

        # Fix Windows event loop issues
        import sys
        if sys.platform == 'win32':
            # Use SelectorEventLoop on Windows to avoid ProactorEventLoop issues
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        if len(self.models) > 1:
            return self._run_multi_model(show_tui, auto_save, save_format)

        # Run the async evaluation
        result = asyncio.run(self.arun(show_tui=show_tui, auto_save=auto_save, save_format=save_format))
        
        # Always print summary (silently no-op when disabled)
        html_url = getattr(result, 'html_url', None)
        result.print_summary(html_url)
        _announce_saved_results([result], include_run_name=False)
        
        
        return result
    
    
    async def arun(self, show_tui: bool = True, auto_save: bool = False, save_format: str = "csv") -> EvaluationResult:
        """
        Run the evaluation asynchronously.

        Args:
            show_tui: Whether to show the terminal UI dashboard (default: True)
            auto_save: Whether to automatically save results after evaluation (default: False)
            save_format: Format for auto-save - "csv", "json", or "xlsx" (default: "csv")

        Returns:
            EvaluationResult object with scores and statistics

        Note:
            The Web UI is always available at the URL printed at startup.
        """
        result = EvaluationResult(
            dataset_name=self.dataset_name,
            run_name=self.run_name,
            metrics=list(self.metrics.keys()),
            run_metadata=self.run_metadata.copy(),
            run_config={"max_concurrency": self.max_concurrency, "timeout": self.timeout}
        )

        items = self.dataset.get_items()
        if not items:
            console.print("[yellow]Warning: Dataset is empty[/yellow]")
            return result
    
        run_info = self._build_run_info(result)

        # Initialize progress tracker
        tracker = ProgressTracker(items, list(self.metrics.keys()))
    
        # Web UI setup - always start the server
        html_url = None
        ui_server = None
        desired_port = 0
        try:
            desired_port = int(self.config.ui_port)
        except Exception:
            desired_port = 0
        ui_server = UIServer(host="127.0.0.1", port=desired_port)
        host, port = ui_server.start()
        html_url = f"http://{host}:{port}/"
        run_info = {**(run_info or {}), "html_url": html_url}
        ui_server.run_state.set_run_info({
            "dataset_name": self.dataset_name,
            "run_name": self.run_name,
            "config": {"max_concurrency": self.max_concurrency, "timeout": self.timeout},
            **({} if run_info is None else run_info),
        })

        dashboard = None
        live_context = nullcontext()
        final_panel = None
        live_tui = show_tui and console_supports_live(console)
        if live_tui:
            dashboard_runs = [
                {
                    "run_id": self.run_name,
                    "display_name": self.display_name,
                    "dataset": self.dataset_name,
                    "model": self.model_name,
                    "config": {
                        "max_concurrency": self.max_concurrency,
                        "timeout": self.timeout,
                        "run_metadata": self.run_metadata,
                    },
                }
            ]
            dashboard = RunDashboard(dashboard_runs, enabled=True, console=console)
            self._attach_observer(dashboard.create_observer(self.run_name))
            live_context = Live(
                dashboard.render(),
                console=console,
                refresh_per_second=6,
                screen=False,
                transient=True,
                vertical_overflow="crop",
            )

        self._notify_observer(
            "on_run_start",
            run_info=run_info or {},
            total_items=len(items),
            metrics=list(self.metrics.keys()),
        )

        async def update_html():
            while True:
                try:
                    snap = tracker.get_snapshot()
                    if ui_server is not None:
                        ui_server.run_state.set_snapshot(snap)
                except Exception as e:
                    logger.debug(f"Failed to update UI snapshot: {e}")
                    pass
                await asyncio.sleep(2)



        with live_context as live:
            if dashboard and live:
                dashboard.bind(live)

            # Inline run_with_table logic
            html_update_task = asyncio.create_task(update_html())

            semaphore = asyncio.Semaphore(self.max_concurrency)
            tasks = []

            async def _bounded_evaluate(idx, item):
                async with semaphore:
                    return await self._evaluate_item(idx, item, tracker)

            for idx, item in enumerate(items):
                # Use actual item ID if available (e.g., from Langfuse dataset), fallback to index-based ID
                item_id = getattr(item, 'id', None) or f"item_{idx}"
                result.add_input(item_id, item.input)
                result.add_metadata(item_id, getattr(item, 'metadata', {}))
                tasks.append(_bounded_evaluate(idx, item))

            try:
                eval_results = await asyncio.gather(*tasks, return_exceptions=True)
            except KeyboardInterrupt:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                html_update_task.cancel()
                try:
                    await html_update_task
                except asyncio.CancelledError:
                    pass
                raise

            html_update_task.cancel()
            try:
                await html_update_task
            except asyncio.CancelledError:
                pass

            # Final snapshot
            try:
                if ui_server is not None:
                    snap = tracker.get_snapshot()
                    ui_server.run_state.set_snapshot(snap)
            except Exception:
                pass

            for idx, eval_result in enumerate(eval_results):
                # Use actual item ID if available (e.g., from Langfuse dataset), fallback to index-based ID
                item = items[idx]
                item_id = getattr(item, 'id', None) or f"item_{idx}"
                if isinstance(eval_result, Exception):
                    result.add_error(item_id, str(eval_result))
                else:
                    result.add_result(item_id, eval_result)
            
            if live_tui and dashboard:
                final_panel = dashboard.render()

        if live_tui and final_panel is not None:
            console.print(final_panel)
        if live_tui and dashboard:
            dashboard.shutdown()
        # Mark evaluation as finished
        result.finish()

        # Build Langfuse URL now that we have the run_id from API responses
        langfuse_url = self._build_langfuse_url()
        if langfuse_url:
            result.langfuse_url = langfuse_url
            result.run_metadata["langfuse_url"] = langfuse_url
            # Also store the IDs separately for future URL rebuilding
            if self._langfuse_dataset_id:
                result.run_metadata["langfuse_dataset_id"] = self._langfuse_dataset_id
            if self._langfuse_run_id:
                result.run_metadata["langfuse_run_id"] = self._langfuse_run_id

        self._notify_observer(
            "on_run_complete",
            result_summary={
                "success_rate": result.success_rate,
                "total_items": result.total_items,
                "metrics": result.metrics,
                "run_metadata": result.run_metadata,
            },
        )
        
        # Store UI URL if available
        if html_url:
            result.html_url = html_url
        
        # Auto-save if requested (message printed by save_* methods)
        if auto_save:
            try:
                result.save(format=save_format, output_dir=self.config.output_dir)
            except Exception as e:
                console.print(f"[yellow]⚠️  Warning: Failed to auto-save results: {e}[/yellow]")
        
        # Keep HTTP server running - don't shut it down
        # The server will be cleaned up when the process exits
        
        return result

    @staticmethod
    def run_parallel(
        runs: Sequence[Any],
        show_tui: bool = True,
        auto_save: bool = False,
        save_format: str = "csv",
    ) -> List[EvaluationResult]:
        """
        Evaluate multiple tasks concurrently from Python code.

        Args:
            runs: Sequence of dicts or RunSpec instances describing each run.
            show_tui: Whether to show the terminal UI dashboard (default: True)
            auto_save: Forwarded to each evaluator (per-run auto-save).
            save_format: Format for auto-save - "csv", "json", or "xlsx" (default: "csv")

        Note:
            The Web UI is always available at the URL printed at startup.
        """
        if not runs:
            raise ValueError("runs must contain at least one configuration")

        from .multi_runner import MultiModelRunner

        # Delegate to MultiModelRunner
        runner = MultiModelRunner.from_runs(runs, console=console)

        # Ensure async loop is ready
        try:
            asyncio.get_running_loop()
            import nest_asyncio  # type: ignore
            nest_asyncio.apply()
        except RuntimeError:
            pass
        except ImportError:
            pass

        results = asyncio.run(
            runner.arun(
                show_tui=show_tui,
                auto_save=auto_save,
                save_format=save_format,
            )
        )

        runner.print_summary(results)
        runner.print_saved_paths(results)

        # Handle per-run saving (legacy support for run_parallel doing the saving)
        for spec, result in zip(runner.specs, results):
            if spec.output_path:
                target_path = Path(spec.output_path)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                suffix = target_path.suffix.lower()
                fmt = save_format
                if suffix == ".json":
                    fmt = "json"
                elif suffix == ".csv":
                    fmt = "csv"
                saved_path = result.save(format=fmt, filepath=str(target_path))
                console.print(f"[green]Saved {spec.run_name} results to {saved_path}[/green]")

        return results



    async def _compute_metric(self, metric: Callable, output: Any, expected: Any, input_data: Any = None) -> Any:
        """Compute a metric, handling both sync and async functions."""
        import inspect
        
        # Determine metric signature
        sig = inspect.signature(metric)
        params = list(sig.parameters.keys())
        
        # Prepare arguments based on metric signature
        if len(params) == 1:
            args = (output,)
        elif len(params) == 2:
            args = (output, expected)
        elif len(params) == 3:
            # For DeepEval metrics that need input_data
            args = (output, expected, input_data)
        else:
            # Try with keyword arguments for flexibility
            kwargs = {'output': output, 'expected': expected, 'input_data': input_data}
            filtered_kwargs = {k: v for k, v in kwargs.items() if k in params}
            args = tuple(filtered_kwargs.values())
        
        # Call metric (async or sync)
        if inspect.iscoroutinefunction(metric):
            result = await metric(*args)
        else:
            result = metric(*args)
        return result
    
    def _get_score_type(self, score: Any) -> str:
        """Determine Langfuse score data type."""
        if isinstance(score, bool):
            return "BOOLEAN"
        elif isinstance(score, (int, float)):
            return "NUMERIC"
        else:
            return "CATEGORICAL"
    
    # Frontend concerns moved to llm_eval.utils.frontend

    def _run_multi_model(self, show_tui: bool, auto_save: bool, save_format: str):
        """Kick off multiple model evaluations via the MultiModelRunner helper."""
        runs = []
        base_name = (self.config.run_name or "").strip() or self._task_name

        # Create base config dict from Pydantic model
        base_config_dict = self.config.model_dump(exclude={'models', 'model', 'run_name', 'run_metadata'})

        # Iterate over both stripped and full model names
        for idx, (model_name, model_name_full) in enumerate(zip(self.models, self.models_full), start=1):
            run_config = copy.deepcopy(base_config_dict)
            run_config['model'] = model_name_full  # Full name for user's task

            run_metadata = dict(self.run_metadata or {})
            run_metadata['model'] = model_name  # Stripped name for display/metadata
            run_config['run_metadata'] = run_metadata

            run_name, display_name = self.build_run_identifiers(base_name, model_name)  # Stripped for run ID
            run_config['run_name'] = run_name

            runs.append(
                {
                    "name": run_name,
                    "display_name": display_name,
                    "task": self.task,
                    "dataset": self.dataset_name,
                    "metrics": self._raw_metrics,
                    "config": run_config,
                    "metadata": {"model": model_name},  # Stripped for display
                }
            )

        return self.run_parallel(
            runs,
            show_tui=show_tui,
            auto_save=auto_save,
            save_format=save_format,
        )
    
    async def _evaluate_item(self, index: int, item: Any, tracker: "ProgressObserver"):
        """
        Evaluate a single item using fully async Langfuse operations.

        This implementation avoids blocking the event loop by:
        1. Using start_span() which queues trace creation (non-blocking)
        2. Running the task purely async
        3. Using async_api for dataset run item linking
        4. Deferring score uploads to background tasks
        """
        meta = {"trace_id": None, "trace_url": None}
        span = None
        item_start_time = time.time()

        try:
            tracker.start_item(index)

            self._notify_observer(
                "on_item_start",
                item_index=index,
                payload={
                    "input": item.input,
                    "expected": getattr(item, 'expected_output', None),
                },
            )

            # Create span/trace using non-blocking API (queues internally)
            item_metadata = getattr(item, 'metadata', {})
            span = self.client.start_span(
                name=f"eval-{self.run_name}-item-{index}",
                input=item.input,
                metadata={
                    **self.run_metadata,
                    "item_index": index,
                    "dataset_item_id": getattr(item, 'id', None),
                    "run_name": self.run_name,
                    "item_metadata": item_metadata,
                },
            )

            # Extract trace metadata
            try:
                meta = self._extract_trace_meta(span)
            except Exception:
                pass

            # Execute task - purely async, no thread pool needed
            # Pass full model name (with provider) to user's task
            task_start_time = time.time()
            output = await self.task_adapter.arun(item.input, span, model_name=self.model_name_full)
            task_elapsed_time = time.time() - task_start_time

            # Update span with output
            try:
                span.update(output=output)
            except Exception:
                pass

            # Compute metrics - async where possible
            scores = {}
            expected_output = getattr(item, 'expected_output', None)

            # Create parent span for all metrics evaluation
            eval_metrics_span = span.start_span(name="eval_metrics")

            for m_name, m_func in self.metrics.items():
                # Create child span for this metric
                metric_span = eval_metrics_span.start_span(
                    name=f"metric_{m_name}",
                    input={"output": output, "expected": expected_output}
                )
                try:
                    # Compute metric (async or sync)
                    if asyncio.iscoroutinefunction(m_func):
                        score = await self._compute_metric(
                            m_func, output,
                            expected_output,
                            item.input
                        )
                    else:
                        # Run sync metrics in thread pool to avoid blocking
                        score = await asyncio.to_thread(
                            self._compute_metric_sync,
                            m_func, output,
                            expected_output,
                            item.input
                        )

                    # Extract main score value
                    main_val = score
                    if isinstance(score, dict):
                        main_val = score.get('score', score)

                    # Update metric span with result
                    metric_span.update(output=score)
                    metric_span.end()

                    # Queue score upload (non-blocking, uses internal queue)
                    try:
                        span.score(
                            name=m_name,
                            value=main_val if isinstance(main_val, (int, float)) else 0,
                            comment=str(score) if not isinstance(main_val, (int, float)) else None
                        )
                    except Exception:
                        pass

                    scores[m_name] = score
                except Exception as e:
                    logger.error(f"Metric {m_name} failed: {e}")
                    error_tb = traceback.format_exc()
                    scores[m_name] = {"score": 0, "error": error_tb}
                    # Update metric span with error
                    metric_span.update(output={"error": error_tb}, level="ERROR")
                    metric_span.end()

            # End the eval_metrics parent span
            eval_metrics_span.end()

            # End the span (queues finalization, non-blocking)
            try:
                span.end()
            except Exception:
                pass

            # Link to dataset run item using async API
            dataset_item_id = getattr(item, 'id', None)
            trace_id = meta.get('trace_id')
            if dataset_item_id and trace_id:
                try:
                    from langfuse.api.resources.dataset_run_items.types import CreateDatasetRunItemRequest
                    response = await self.client.async_api.dataset_run_items.create(
                        request=CreateDatasetRunItemRequest(
                            runName=self.run_name,
                            runDescription=None,
                            metadata=self.run_metadata,
                            datasetItemId=dataset_item_id,
                            traceId=trace_id,
                        )
                    )
                    # Capture run_id from first successful response for URL building
                    if self._langfuse_run_id is None and response:
                        # Try different possible attribute names
                        run_id = (
                            getattr(response, 'run_id', None) or
                            getattr(response, 'runId', None) or
                            getattr(response, 'dataset_run_id', None) or
                            getattr(response, 'datasetRunId', None)
                        )
                        # Also check if it's in a nested 'run' object
                        if not run_id and hasattr(response, 'run'):
                            run_obj = response.run
                            run_id = getattr(run_obj, 'id', None)
                        self._langfuse_run_id = run_id
                        logger.debug(f"Captured Langfuse run_id: {run_id}, response attrs: {dir(response)}")
                except Exception as e:
                    logger.debug(f"Failed to link dataset run item: {e}")

            # Update tracker with results
            tracker.update_trace_info(index, meta.get('trace_id'), meta.get('trace_url'))
            tracker.update_output(index, output)

            for m_name, score in scores.items():
                if score is not None:
                    main_val = score
                    meta_map = {}
                    if isinstance(score, dict):
                        main_val = score.get('score', None)
                        md = score.get('metadata', {})
                        if isinstance(md, dict):
                            for k, v in md.items():
                                if isinstance(v, dict):
                                    for k2, v2 in v.items():
                                        meta_map[f"{k}_{k2}"] = v2
                                else:
                                    meta_map[str(k)] = v
                    tracker.update_metric(index, m_name, main_val, meta_map)

                    self._notify_observer(
                        "on_metric_result",
                        item_index=index,
                        metric_name=m_name,
                        score=score,
                        metadata={
                            "input": item.input,
                            "expected": getattr(item, 'expected_output', None),
                        },
                    )
                else:
                    tracker.set_metric_error(index, m_name)

            # Filter out None scores
            scores = {k: v for k, v in scores.items() if v is not None}

            tracker.complete_item(index)

            self._notify_observer(
                "on_item_complete",
                item_index=index,
                result={
                    "output": output,
                    "scores": scores,
                },
            )

            return {
                "input": item.input,
                "output": output,
                "expected": getattr(item, 'expected_output', None),
                "scores": scores,
                "trace_id": meta.get('trace_id'),
                "trace_url": meta.get('trace_url'),
                "time": task_elapsed_time,
                "success": True,
            }

        except Exception as e:
            # End span on error
            if span:
                try:
                    span.update(output={"error": str(e)}, level="ERROR", status_message=str(e))
                    span.end()
                except Exception:
                    pass

                # Link to dataset run item even on error so it shows in Langfuse
                dataset_item_id = getattr(item, 'id', None)
                trace_id = meta.get('trace_id')
                if dataset_item_id and trace_id:
                    try:
                        from langfuse.api.resources.dataset_run_items.types import CreateDatasetRunItemRequest
                        response = await self.client.async_api.dataset_run_items.create(
                            request=CreateDatasetRunItemRequest(
                                runName=self.run_name,
                                runDescription=None,
                                metadata={**self.run_metadata, "error": str(e)},
                                datasetItemId=dataset_item_id,
                                traceId=trace_id,
                            )
                        )
                        # Capture run_id from first successful response for URL building
                        if self._langfuse_run_id is None and response:
                            run_id = (
                                getattr(response, 'run_id', None) or
                                getattr(response, 'runId', None) or
                                getattr(response, 'dataset_run_id', None) or
                                getattr(response, 'datasetRunId', None)
                            )
                            if not run_id and hasattr(response, 'run'):
                                run_obj = response.run
                                run_id = getattr(run_obj, 'id', None)
                            self._langfuse_run_id = run_id
                    except Exception:
                        pass

            tracker.fail_item(index, str(e))
            self._notify_observer("on_item_error", item_index=index, error=str(e))
            return Exception(str(e))

    def _compute_metric_sync(self, metric_func: Callable, output: Any, expected: Any, input_data: Any) -> Any:
        """Synchronous version of metric computation for thread pool execution."""
        try:
            sig = inspect.signature(metric_func)
            params = list(sig.parameters.keys())

            if len(params) >= 3:
                return metric_func(output, expected, input_data)
            elif len(params) == 2:
                return metric_func(output, expected)
            elif len(params) == 1:
                return metric_func(output)
            else:
                return metric_func()
        except Exception as e:
            error_tb = traceback.format_exc()
            logger.error(f"Metric {getattr(metric_func, '__name__', 'unknown')} failed: {error_tb}")
            return {"score": 0, "error": str(e), "traceback": error_tb}


def _announce_saved_results(results: Sequence[EvaluationResult], *, include_run_name: bool) -> None:
    table = Table(box=None, show_header=False, padding=(0, 0))
    table.add_column("Saved to", style="dim")

    rows_added = 0
    for res in results:
        if isinstance(res, Exception):
            continue
        notice = res.consume_saved_notice(include_run_name=include_run_name)
        if not notice:
            continue
        path = notice.split(":", 1)[-1] if ":" in notice else notice
        table.add_row(path.strip())
        rows_added += 1

    if rows_added == 0:
        return

    console.print("\n[blue]📁 Results saved[/blue]")
    console.print(table)


def _derive_task_name(task: Any) -> str:
    """Pick a readable name for a task callable/object."""
    for attr in ("__qualname__", "__name__"):
        name = getattr(task, attr, None)
        if isinstance(name, str) and name.strip():
            return name.strip()
    return "task"


_RUN_ID_RE = re.compile(r"^(?P<base>.+)-(?P<ts>\d{8}-\d{6})(?:-.+)?$")


def _strip_run_suffix(name: str) -> Tuple[str, bool]:
    """If name already has timestamp/model suffix, return base and flag."""
    m = _RUN_ID_RE.match(name)
    if not m:
        return name, False
    return m.group("base"), True


class _RunWithModel:
    """Small helper to wrap model runs with shared dataset."""

    def __init__(self, evaluator: "Evaluator", model: str):
        self.evaluator = evaluator
        self.model = model
