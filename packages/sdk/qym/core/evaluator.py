"""Main Evaluator class for LLM evaluation."""

from __future__ import annotations

import asyncio
import inspect
import os
import traceback
from typing import Any, Callable, Dict, List, Optional, Sequence, Union, Tuple, Set
from datetime import datetime, timezone
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
from .checkpoint import (
    CheckpointWriter,
    load_checkpoint_state,
    iter_checkpoint_rows,
    parse_checkpoint_row,
    parse_metric_score,
    serialize_checkpoint_row,
)
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


def _compute_run_config_id(config: Dict[str, Any]) -> str:
    """Compute a stable hash from run config, excluding ephemeral fields.

    Used by platform to group runs with identical configurations.
    """
    import hashlib
    import json
    ephemeral = {'run_name', 'resume_from', 'cli_invocation', 'run_metadata'}
    stable = {k: v for k, v in sorted(config.items()) if k not in ephemeral}
    raw = json.dumps(stable, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


from ..utils.errors import LangfuseConnectionError, DatasetNotFoundError
# UIServer has been removed - platform streaming is now required
# from ..server.app import UIServer  # DEPRECATED
import json
import logging

logger = logging.getLogger(__name__)
from ..platform.defaults import DEFAULT_PLATFORM_URL


def _utc_now_str() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
try:
    from ..platform.client import PlatformClient, PlatformEventStream  # type: ignore
except Exception:  # pragma: no cover
    PlatformClient = None  # type: ignore
    PlatformEventStream = None  # type: ignore
 


console = Console()

class NullTrace:
    """No-op trace/span used when Langfuse is disabled.

    Must support the subset of the Langfuse span API used by adapters and the evaluator.
    """

    def __init__(self, name: str = "", input: Any = None, metadata: Optional[Dict[str, Any]] = None):
        self.name = name
        self.input = input
        self.metadata = metadata or {}
        self.output: Any = None

    def update(self, **kwargs: Any) -> None:
        # Store a few common fields for debugging; otherwise no-op.
        if "input" in kwargs:
            self.input = kwargs.get("input")
        if "metadata" in kwargs and isinstance(kwargs.get("metadata"), dict):
            self.metadata = kwargs.get("metadata") or {}
        if "output" in kwargs:
            self.output = kwargs.get("output")

    def start_span(self, name: str = "", input: Any = None, metadata: Optional[Dict[str, Any]] = None) -> "NullTrace":
        return NullTrace(name=name, input=input, metadata=metadata)

    def score(self, **kwargs: Any) -> None:
        return None

    def end(self) -> None:
        return None


from .config import EvaluatorConfig

class Evaluator:
    """
    Simple evaluator for LLM tasks using Langfuse datasets.
    """
    
    def __init__(
        self,
        task: Any,
        dataset: Union[str, Any],
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
        self._task_name = self.config.task_name or _derive_task_name(task)
            
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
        
        # Initialize Langfuse client ONLY when credentials exist (or user provided a client).
        # This ensures CSV/local datasets work without requiring Langfuse setup.
        self.client: Optional[Langfuse] = None
        self.langfuse_enabled: bool = False
        if langfuse_client is not None:
            self.client = langfuse_client
            self.langfuse_enabled = True
        elif self._langfuse_credentials_available():
            self.client = self._init_langfuse()
            self.langfuse_enabled = True
        
        # Load and validate dataset
        if isinstance(dataset, str):
            self.dataset_name = dataset
            if not self.client:
                raise LangfuseConnectionError(
                    "Langfuse dataset name provided but Langfuse credentials are missing. "
                    "Set LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY or pass langfuse_client, "
                    "or use a CSV dataset object / --dataset-csv."
                )
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
        # Use model_full when set (multi-model runs pass provider-prefixed ID for API calls)
        self.model_name_full = self.config.model_full or self.config.model  # Full ID for user's task (OpenRouter, etc.)
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
        if self._task_name:
            self.run_metadata["task_name"] = self._task_name

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
                version = _im.version("qym")
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
            # Get project ID for deep-links (auto-detect from API if not provided)
            try:
                self.langfuse_project_id = (
                    self.config.langfuse_project_id
                    or os.getenv('LANGFUSE_PROJECT_ID')
                )
                # Auto-detect from Langfuse client if not provided
                if not self.langfuse_project_id:
                    # Try private method first (cached, no extra API call)
                    if hasattr(client, '_get_project_id'):
                        self.langfuse_project_id = client._get_project_id()
                    # Fallback to public API
                    if not self.langfuse_project_id and hasattr(client, 'api'):
                        result = client.api.projects.get()
                        if result.data:
                            self.langfuse_project_id = result.data[0].id
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

    def _langfuse_credentials_available(self) -> bool:
        """Return True if Langfuse credentials appear to be available from config/env.

        This is intentionally a lightweight check that does not validate credentials.
        """
        # Note: do not auto-load .env here; _init_langfuse already best-effort loads it.
        public_key = self.config.langfuse_public_key or os.getenv("LANGFUSE_PUBLIC_KEY")
        secret_key = self.config.langfuse_secret_key or os.getenv("LANGFUSE_SECRET_KEY")
        return bool(public_key and secret_key)
    


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
    
    def run(
        self,
        show_tui: bool = True,
        auto_save: bool = True,
        save_format: str = "csv",
        max_parallel_runs: Optional[int] = None,
    ) -> Union[EvaluationResult, List[EvaluationResult]]:
        """
        Run the evaluation synchronously.

        Args:
            show_tui: Whether to show the terminal UI dashboard (default: True)
            auto_save: Whether to automatically save results after evaluation (default: True)
            save_format: Format for auto-save - "csv", "json", or "xlsx" (default: "csv")
            max_parallel_runs: Maximum number of model runs to execute concurrently
                (only applies when evaluating multiple models).
                None (default) = all models in parallel
                1 = sequential (one model at a time)
                N = run N models at a time

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
            return self._run_multi_model(show_tui, auto_save, save_format, max_parallel_runs)

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
        checkpoint_state = None
        if self.config.resume_from:
            checkpoint_state = load_checkpoint_state(self.config.resume_from)
            if checkpoint_state and checkpoint_state.run_name:
                # Resume should continue the original run_id by default.
                self.run_name = checkpoint_state.run_name
                self.display_name = checkpoint_state.run_name
                self.config.run_name = checkpoint_state.run_name

        result = EvaluationResult(
            dataset_name=self.dataset_name,
            run_name=self.run_name,
            metrics=list(self.metrics.keys()),
            run_metadata=self.run_metadata.copy(),
            run_config={
                "max_concurrency": self.max_concurrency,
                "timeout": self.timeout,
                "user_provided_run_name": bool(self.config.run_name),
            }
        )

        items = self.dataset.get_items()
        if not items:
            console.print("[yellow]Warning: Dataset is empty[/yellow]")
            return result
        self.run_metadata["total_items"] = len(items)
        if self._langfuse_dataset_id:
            self.run_metadata["langfuse_dataset_id"] = self._langfuse_dataset_id

        run_info = self._build_run_info(result)

        # Initialize progress tracker
        metric_names = list(self.metrics.keys())
        tracker = ProgressTracker(items, metric_names)
    
        # Live UI setup (platform streaming required):
        # Local UIServer has been removed - all live viewing is via the platform
        html_url = None
        self._platform_stream = None
        platform_api_key = getattr(self.config, "platform_api_key", None) or os.getenv("QYM_API_KEY")
        live_mode = str(getattr(self.config, "live_mode", "platform")).lower()

        # Platform streaming is now required for live UI
        if live_mode == "local":
            import warnings
            warnings.warn(
                "live_mode='local' is deprecated - local UIServer has been removed. "
                "Please configure platform streaming (QYM_API_KEY) or use TUI only.",
                DeprecationWarning,
                stacklevel=2,
            )
            # Continue without live UI - TUI will still work
        elif platform_api_key:
            platform_url = getattr(self.config, "platform_url", None) or DEFAULT_PLATFORM_URL
            if PlatformClient is None:
                raise RuntimeError("Platform streaming requires the platform client module")
            client = PlatformClient(platform_url=platform_url, api_key=platform_api_key)
            # Include total_items in metadata for progress tracking
            start_metadata = dict(self.run_metadata or {})
            start_metadata["total_items"] = len(items)
            handle = client.create_run(
                external_run_id=self.run_name,
                task=self._task_name,
                dataset=str(self.dataset_name),
                model=self.model_name,
                metrics=list(self.metrics.keys()),
                run_metadata=start_metadata,
                run_config={
                    "max_concurrency": self.max_concurrency,
                    "timeout": self.timeout,
                    "run_name": self.run_name,
                    "task_name": self._task_name,
                    "run_config_id": _compute_run_config_id({"max_concurrency": self.max_concurrency, "timeout": self.timeout, "model": self.model_name, "task": self._task_name, "dataset": str(self.dataset_name)}),
                },
            )
            html_url = handle.live_url
            self._platform_stream = PlatformEventStream(platform_url=platform_url, api_key=platform_api_key, run_id=handle.run_id)
            # Seed run_started event (platform also has run record already; this is for richer metadata)
            try:
                self._platform_stream.emit(
                    "run_started",
                    {
                        "external_run_id": self.run_name,
                        "task": self._task_name,
                        "dataset": str(self.dataset_name),
                        "model": self.model_name,
                        "metrics": list(self.metrics.keys()),
                        "total_items": int(self.total_items),
                        "run_metadata": dict(self.run_metadata or {}),
                        "run_config": {
                            "max_concurrency": self.max_concurrency,
                            "timeout": self.timeout,
                            "run_name": self.run_name,
                            "task_name": self._task_name,
                            "run_config_id": _compute_run_config_id({"max_concurrency": self.max_concurrency, "timeout": self.timeout, "model": self.model_name, "task": self._task_name, "dataset": str(self.dataset_name)}),
                        },
                        "started_at": _utc_now_str(),
                    },
                )
            except Exception:
                pass
        else:
            # No platform configured - TUI only, no live web UI
            pass

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

        # Checkpoint/resume setup
        checkpoint_path = None
        checkpoint_writer = None
        completed_item_ids: Set[str] = set()
        checkpoint_rows: List[Dict[str, Any]] = []
        resume_completed = 0
        resume_failed = 0
        resume_metric_totals: Dict[str, float] = {m: 0.0 for m in metric_names}
        resume_metric_counts: Dict[str, int] = {m: 0 for m in metric_names}
        if self.config.checkpoint_enabled:
            if (self.config.checkpoint_format or "").lower() != "csv":
                raise ValueError("Only CSV checkpointing is supported.")
            checkpoint_path = self.config.resume_from or result._default_save_path(
                "csv", output_dir=self.config.output_dir
            )
            checkpoint_state = checkpoint_state or load_checkpoint_state(checkpoint_path)
            if checkpoint_state:
                if checkpoint_state.dataset_name and checkpoint_state.dataset_name != self.dataset_name:
                    raise ValueError(
                        f"Resume dataset mismatch: {checkpoint_state.dataset_name} != {self.dataset_name}"
                    )
                if sorted(checkpoint_state.metrics) != sorted(metric_names):
                    raise ValueError(
                        "Resume metrics mismatch: "
                        f"{checkpoint_state.metrics} != {metric_names}"
                    )
                if self.config.resume_rerun_errors:
                    raise ValueError(
                        "resume_rerun_errors is not supported when appending to the same run file."
                    )
                completed_item_ids = set(checkpoint_state.completed_item_ids)
                resume_failed = len(checkpoint_state.error_item_ids)
                resume_completed = max(0, len(completed_item_ids) - resume_failed)
                for row in iter_checkpoint_rows(checkpoint_path):
                    checkpoint_rows.append(row)
                    for m in metric_names:
                        val = parse_metric_score(row.get(f"{m}_score", ""))
                        if val is not None:
                            resume_metric_totals[m] += float(val)
                            resume_metric_counts[m] += 1
                    item_id, row_result, is_error = parse_checkpoint_row(row, metric_names)
                    if not item_id:
                        continue
                    if is_error:
                        error_output = str(row_result.get("output", "") or "")
                        error_msg = error_output.replace("ERROR:", "").strip() or "error"
                        result.add_error(
                            item_id,
                            error_msg,
                            row_result.get("trace_id"),
                            task_started_at_ms=row_result.get("task_started_at_ms"),
                        )
                    else:
                        result.add_result(item_id, row_result)

            checkpoint_writer = CheckpointWriter(
                checkpoint_path,
                metrics=metric_names,
                flush_each_item=self.config.checkpoint_flush_each_item,
                fsync=self.config.checkpoint_fsync,
            )
            checkpoint_writer.open()

        run_info = {
            **(run_info or {}),
            "resume_completed": resume_completed,
            "resume_failed": resume_failed,
            "resume_metric_totals": resume_metric_totals,
            "resume_metric_counts": resume_metric_counts,
        }

        self._notify_observer(
            "on_run_start",
            run_info=run_info or {},
            total_items=len(items),
            metrics=list(self.metrics.keys()),
        )

        # Build item list and input metadata
        item_id_to_index: Dict[str, int] = {}
        pending_entries: List[Tuple[int, str, Any]] = []
        use_fallback_ids = bool(
            checkpoint_state
            and any(str(item_id).startswith("item_") for item_id in completed_item_ids)
        )
        for idx, item in enumerate(items):
            primary_id_raw = getattr(item, "id", None)
            primary_id = str(primary_id_raw) if primary_id_raw is not None else None
            fallback_id = f"item_{idx}"
            if primary_id:
                item_id_to_index[primary_id] = idx
            item_id_to_index[fallback_id] = idx
            # Use the same ID scheme as the checkpoint when resuming.
            item_id = fallback_id if use_fallback_ids or not primary_id else primary_id
            result.add_input(item_id, item.input)
            result.add_metadata(item_id, getattr(item, "metadata", {}))
            if item_id in completed_item_ids or fallback_id in completed_item_ids or (primary_id in completed_item_ids if primary_id else False):
                continue
            pending_entries.append((idx, item_id, item))


        with live_context as live:
            if dashboard and live:
                dashboard.bind(live)

            work_queue: asyncio.Queue = asyncio.Queue()
            write_queue: asyncio.Queue = asyncio.Queue()
            interrupted = False

            async def _write_loop():
                if not checkpoint_writer:
                    return
                while True:
                    row = await write_queue.get()
                    if row is None:
                        write_queue.task_done()
                        break
                    checkpoint_writer.append_row(row)
                    write_queue.task_done()

            def _main_score(val: Any) -> Any:
                if isinstance(val, dict):
                    if "error" in val:
                        return f"ERROR: {val['error']}"
                    if "score" in val:
                        return val.get("score")
                return val

            def _checkpoint_run_metadata() -> Dict[str, Any]:
                md = dict(self.run_metadata or {})
                if self._langfuse_dataset_id:
                    md["langfuse_dataset_id"] = self._langfuse_dataset_id
                if self._langfuse_run_id:
                    md["langfuse_run_id"] = self._langfuse_run_id
                langfuse_url = self._build_langfuse_url()
                if langfuse_url:
                    md["langfuse_url"] = langfuse_url
                return md

            async def _worker():
                while True:
                    entry = await work_queue.get()
                    if entry is None:
                        work_queue.task_done()
                        break
                    idx, item_id, item = entry
                    try:
                        eval_result = await self._evaluate_item(idx, item, tracker)
                    except Exception as e:
                        eval_result = e

                    if isinstance(eval_result, Exception):
                        error_msg = str(eval_result)
                        result.add_error(item_id, error_msg)
                        row = serialize_checkpoint_row(
                            dataset_name=self.dataset_name,
                            run_name=self.run_name,
                            run_metadata=_checkpoint_run_metadata(),
                            run_config={"max_concurrency": self.max_concurrency, "timeout": self.timeout},
                            trace_id="",
                            item_id=item_id,
                            item_input=item.input,
                            item_metadata=getattr(item, "metadata", {}),
                            output=f"ERROR: {error_msg}",
                            expected_output=getattr(item, "expected_output", None),
                            time_seconds=0.0,
                            task_started_at_ms=None,
                            scores={m: "N/A" for m in metric_names},
                            metric_meta={},
                        )
                    elif isinstance(eval_result, dict) and "_error" in eval_result:
                        error_msg = str(eval_result.get("_error", "error"))
                        result.add_error(
                            item_id,
                            error_msg,
                            eval_result.get("_trace_id"),
                            task_started_at_ms=eval_result.get("task_started_at_ms"),
                        )
                        row = serialize_checkpoint_row(
                            dataset_name=self.dataset_name,
                            run_name=self.run_name,
                            run_metadata=_checkpoint_run_metadata(),
                            run_config={"max_concurrency": self.max_concurrency, "timeout": self.timeout},
                            trace_id=eval_result.get("_trace_id") or "",
                            item_id=item_id,
                            item_input=item.input,
                            item_metadata=getattr(item, "metadata", {}),
                            output=f"ERROR: {error_msg}",
                            expected_output=getattr(item, "expected_output", None),
                            time_seconds=0.0,
                            task_started_at_ms=eval_result.get("task_started_at_ms"),
                            scores={m: "N/A" for m in metric_names},
                            metric_meta={},
                        )
                    else:
                        result.add_result(item_id, eval_result)
                        scores = eval_result.get("scores", {})
                        metric_meta: Dict[str, Dict[str, Any]] = {}
                        score_row: Dict[str, Any] = {}
                        for m in metric_names:
                            sc = scores.get(m)
                            score_row[m] = _main_score(sc)
                            if isinstance(sc, dict) and isinstance(sc.get("metadata"), dict):
                                metric_meta[m] = sc["metadata"]
                        row = serialize_checkpoint_row(
                            dataset_name=self.dataset_name,
                            run_name=self.run_name,
                            run_metadata=_checkpoint_run_metadata(),
                            run_config={"max_concurrency": self.max_concurrency, "timeout": self.timeout},
                            trace_id=eval_result.get("trace_id") or "",
                            item_id=item_id,
                            item_input=item.input,
                            item_metadata=getattr(item, "metadata", {}),
                            output=eval_result.get("output"),
                            expected_output=eval_result.get("expected"),
                            time_seconds=float(eval_result.get("time", 0.0) or 0.0),
                            task_started_at_ms=eval_result.get("task_started_at_ms"),
                            scores=score_row,
                            metric_meta=metric_meta,
                        )

                    if checkpoint_writer:
                        await write_queue.put(row)
                    work_queue.task_done()

            if pending_entries:
                for entry in pending_entries:
                    await work_queue.put(entry)
            for _ in range(self.max_concurrency):
                await work_queue.put(None)

            writer_task = asyncio.create_task(_write_loop()) if checkpoint_writer else None
            worker_tasks = [asyncio.create_task(_worker()) for _ in range(self.max_concurrency)]

            try:
                await asyncio.gather(*worker_tasks)
            except KeyboardInterrupt:
                interrupted = True
                # Stop scheduling new work
                while not work_queue.empty():
                    try:
                        work_queue.get_nowait()
                        work_queue.task_done()
                    except Exception:
                        break
                for _ in worker_tasks:
                    await work_queue.put(None)
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*worker_tasks, return_exceptions=True),
                        timeout=self.config.interrupt_grace_seconds,
                    )
                except asyncio.TimeoutError:
                    for task in worker_tasks:
                        task.cancel()
            finally:
                if writer_task:
                    await write_queue.join()
                    await write_queue.put(None)
                    await writer_task
                if checkpoint_writer:
                    checkpoint_writer.close()

            if interrupted:
                result.interrupted = True
                result.last_saved_path = checkpoint_path


            if live_tui and dashboard:
                final_panel = dashboard.render()

        if live_tui and final_panel is not None:
            console.print(final_panel)
        if live_tui and dashboard:
            dashboard.shutdown()
        if checkpoint_path:
            result.last_saved_path = checkpoint_path
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

        # Finalize remote streaming
        if getattr(self, "_platform_stream", None) is not None:
            try:
                # First, close the async queue to flush all pending item events
                self._platform_stream.close()
            except Exception:
                pass
            try:
                # Then send run_completed synchronously to ensure it gets through
                # Persist final metadata (e.g., langfuse_url) to the platform by embedding it in the
                # completion summary. The platform ingest path will merge this into Run.run_metadata.
                final_run_metadata = dict(result.run_metadata or {})
                self._platform_stream.emit(
                    "run_completed",
                    {
                        "ended_at": _utc_now_str(),
                        "final_status": "COMPLETED",
                        "summary": {
                            "total_items": result.total_items,
                            "success_count": len(result.results),
                            "error_count": len(result.errors),
                            "run_metadata": final_run_metadata,
                        },
                    },
                    sync=True,  # Send synchronously to guarantee delivery
                )
            except Exception:
                pass
        
        # Auto-save if requested (message printed by save_* methods)
        if auto_save and not checkpoint_path:
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
        max_parallel_runs: Optional[int] = None,
    ) -> List[EvaluationResult]:
        """
        Evaluate multiple tasks concurrently from Python code.

        Args:
            runs: Sequence of dicts or RunSpec instances describing each run.
            show_tui: Whether to show the terminal UI dashboard (default: True)
            auto_save: Forwarded to each evaluator (per-run auto-save).
            save_format: Format for auto-save - "csv", "json", or "xlsx" (default: "csv")
            max_parallel_runs: Maximum number of runs to execute concurrently.
                None (default) = all runs in parallel
                1 = sequential (queue mode)
                N = run N at a time

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
                max_parallel_runs=max_parallel_runs,
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
    
    # Frontend concerns moved to qym.utils.frontend

    def _run_multi_model(self, show_tui: bool, auto_save: bool, save_format: str, max_parallel_runs: Optional[int] = None):
        """Kick off multiple model evaluations via the MultiModelRunner helper."""
        runs = []
        base_name = (self.config.run_name or "").strip() or self._task_name

        # Create base config dict from Pydantic model
        base_config_dict = self.config.model_dump(exclude={'models', 'model', 'run_name', 'run_metadata'})

        # Iterate over both stripped and full model names
        for idx, (model_name, model_name_full) in enumerate(zip(self.models, self.models_full), start=1):
            run_config = copy.deepcopy(base_config_dict)
            run_config['model'] = model_name  # #17: Stripped name for consistent platform display
            run_config['model_full'] = model_name_full  # Full name preserved for user's task

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
                    "dataset": self.dataset,
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
            max_parallel_runs=max_parallel_runs,
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
        # For dashboard display / persistence: when the task execution began (epoch ms).
        task_started_at_ms: Optional[int] = None

        try:
            tracker.start_item(index)

            # Platform: item started
            try:
                ps = getattr(self, "_platform_stream", None)
                if ps is not None:
                    item_id = getattr(item, "id", None) or f"item_{index}"
                    ps.emit(
                        "item_started",
                        {
                            "item_id": str(item_id),
                            "index": int(index),
                            "input": item.input,
                            "expected": getattr(item, "expected_output", None),
                            "item_metadata": getattr(item, "metadata", {}) or {},
                        },
                    )
            except Exception:
                pass

            self._notify_observer(
                "on_item_start",
                item_index=index,
                payload={
                    "input": item.input,
                    "expected": getattr(item, 'expected_output', None),
                },
            )

            # Create span/trace using non-blocking API (queues internally) when Langfuse is enabled.
            # Otherwise use a no-op trace so tasks/metrics/UI still work.
            item_metadata = getattr(item, 'metadata', {})
            if self.client:
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
            else:
                span = NullTrace(
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

            # Execute task - purely async, no thread pool needed.
            # Pass full model name (with provider) to user's task.
            task_started_at_ms = int(time.time() * 1000)
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

                    # Platform: metric scored
                    try:
                        ps = getattr(self, "_platform_stream", None)
                        if ps is not None:
                            item_id = getattr(item, "id", None) or f"item_{index}"
                            score_numeric = None
                            score_raw = score
                            meta_payload: Dict[str, Any] = {}
                            if isinstance(score, dict):
                                score_raw = score
                                if isinstance(score.get("score"), (int, float, bool)):
                                    score_numeric = float(score["score"])
                                if isinstance(score.get("metadata"), dict):
                                    meta_payload = score.get("metadata") or {}
                            elif isinstance(score, (int, float, bool)):
                                score_numeric = float(score)
                            ps.emit(
                                "metric_scored",
                                {
                                    "item_id": str(item_id),
                                    "metric_name": str(m_name),
                                    "score_numeric": score_numeric,
                                    "score_raw": score_raw,
                                    "meta": meta_payload,
                                },
                            )
                    except Exception:
                        pass
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

            # Link to Langfuse dataset run item only for Langfuse datasets (even if tracing is enabled for CSV).
            dataset_item_id = getattr(item, 'id', None)
            trace_id = meta.get('trace_id')
            if isinstance(self.dataset, LangfuseDataset) and self.client and dataset_item_id and trace_id:
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
                        # Send langfuse_url to platform as soon as we have it
                        if self._langfuse_run_id and self._platform_stream:
                            langfuse_url = self._build_langfuse_url()
                            if langfuse_url:
                                try:
                                    self._platform_stream.emit("metadata_update", {
                                        "langfuse_url": langfuse_url,
                                        "langfuse_dataset_id": self._langfuse_dataset_id,
                                        "langfuse_run_id": self._langfuse_run_id,
                                    })
                                except Exception:
                                    pass
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

            # Platform: item completed
            try:
                ps = getattr(self, "_platform_stream", None)
                if ps is not None:
                    item_id = getattr(item, "id", None) or f"item_{index}"
                    ps.emit(
                        "item_completed",
                        {
                            "item_id": str(item_id),
                            "index": int(index),  # Include index for fallback when item_started was missed
                            "output": output,
                            "latency_ms": float(task_elapsed_time * 1000.0),
                            "trace_id": meta.get("trace_id"),
                            "trace_url": meta.get("trace_url"),
                            "task_started_at_ms": task_started_at_ms,
                        },
                    )
            except Exception:
                pass

            self._notify_observer(
                "on_item_complete",
                item_index=index,
                result={
                    "output": output,
                    "scores": scores,
                    "task_time": task_elapsed_time,  # #18: task-only duration (excludes metric compute)
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
                "task_started_at_ms": task_started_at_ms,
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

                # Link to dataset run item even on error (Langfuse datasets only)
                dataset_item_id = getattr(item, 'id', None)
                trace_id = meta.get('trace_id')
                if isinstance(self.dataset, LangfuseDataset) and self.client and dataset_item_id and trace_id:
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
                            # Send langfuse_url to platform as soon as we have it
                            if self._langfuse_run_id and self._platform_stream:
                                langfuse_url = self._build_langfuse_url()
                                if langfuse_url:
                                    try:
                                        self._platform_stream.emit("metadata_update", {
                                            "langfuse_url": langfuse_url,
                                            "langfuse_dataset_id": self._langfuse_dataset_id,
                                            "langfuse_run_id": self._langfuse_run_id,
                                        })
                                    except Exception:
                                        pass
                    except Exception:
                        pass

            # Update trace info even on error so Langfuse link appears in dashboard
            tracker.update_trace_info(index, meta.get('trace_id'), meta.get('trace_url'))
            tracker.fail_item(index, str(e))
            self._notify_observer("on_item_error", item_index=index, error=str(e))
            # Return error info with trace_id so it can be saved to results
            try:
                ps = getattr(self, "_platform_stream", None)
                if ps is not None:
                    item_id = getattr(item, "id", None) or f"item_{index}"
                    ps.emit(
                        "item_failed",
                        {
                            "item_id": str(item_id),
                            "index": int(index),  # Include index for fallback when item_started was missed
                            "error": str(e),
                            "trace_id": meta.get("trace_id"),
                            "trace_url": meta.get("trace_url"),
                        },
                    )
            except Exception:
                pass
            return {
                "_error": str(e),
                "_trace_id": meta.get('trace_id'),
                "task_started_at_ms": task_started_at_ms,
            }

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


_RUN_ID_RE = re.compile(r"^(?P<base>.+)-(?P<ts>\d{6}-\d{4})(?:-\d+)?$")


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
