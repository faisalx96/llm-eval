"""Main Evaluator class for LLM evaluation."""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import json as _json
import os
import random
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Union, Tuple, Set
from datetime import datetime, timezone
import time
import subprocess
from pathlib import Path
import copy
from contextlib import nullcontext
import re

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

@dataclass
class ItemSpans:
    """All OTEL span state for a single evaluation item.

    Manages the lifecycle of OpenInference spans for the eval root,
    task function, and metrics evaluation. Provides helpers to create
    and end spans with proper OpenInference attributes.
    """
    eval_span: Any = None
    eval_token: Any = None
    task_span: Any = None
    task_token: Any = None
    metrics_span: Any = None
    metrics_token: Any = None
    trace_id: Optional[str] = None
    trace_url: Optional[str] = None
    tracer: Any = None  # OTEL tracer if enabled

    @staticmethod
    def _start_span(tracer, name, kind="CHAIN", input_value=None, metadata=None):
        """Create an OTEL span with OpenInference attributes."""
        from opentelemetry import trace as _trace, context as _ctx

        span = tracer.start_span(name)
        span.set_attribute("openinference.span.kind", kind)
        if input_value is not None:
            try:
                span.set_attribute("input.value", _json.dumps(input_value, default=str)[:16000])
                span.set_attribute("input.mime_type", "application/json")
            except Exception:
                span.set_attribute("input.value", str(input_value)[:16000])
        if metadata:
            try:
                span.set_attribute("metadata", _json.dumps(metadata, default=str)[:8000])
            except Exception:
                pass
        token = _ctx.attach(_trace.set_span_in_context(span))
        return span, token

    @staticmethod
    def _end_span(span, token, output_value=None, error=None):
        """End an OTEL span, setting output and optional error status."""
        from opentelemetry import context as _ctx

        if error is not None:
            try:
                from opentelemetry.trace import StatusCode
                span.set_status(StatusCode.ERROR, str(error))
                span.set_attribute("output.value", _json.dumps({"error": str(error)}, default=str)[:16000])
            except Exception:
                pass
        elif output_value is not None:
            try:
                span.set_attribute("output.value", _json.dumps(output_value, default=str)[:16000])
                span.set_attribute("output.mime_type", "application/json")
            except Exception:
                span.set_attribute("output.value", str(output_value)[:16000])
        try:
            span.end()
        except Exception:
            pass
        try:
            _ctx.detach(token)
        except Exception:
            pass

    def end_task(self, output=None, error=None):
        """End the task span."""
        if self.task_span:
            self._end_span(self.task_span, self.task_token, output_value=output, error=error)
            self.task_span = None
            self.task_token = None

    def end_metrics(self, scores=None):
        """End the metrics span."""
        if self.metrics_span:
            self._end_span(self.metrics_span, self.metrics_token, output_value=scores)
            self.metrics_span = None
            self.metrics_token = None

    def add_score_event(self, metric_name, value, label=None, explanation=None):
        """Add a score as an event on the eval root span."""
        if self.eval_span and self.eval_span.is_recording():
            self.eval_span.add_event(
                f"score.{metric_name}",
                attributes={
                    "score.name": metric_name,
                    "score.value": value if isinstance(value, (int, float)) else 0,
                    "score.label": label or "",
                    "score.explanation": explanation or "",
                },
            )

    def end_eval(self, output=None, error=None):
        """End the root eval span."""
        if self.eval_span:
            self._end_span(self.eval_span, self.eval_token, output_value=output, error=error)
            self.eval_span = None
            self.eval_token = None

    def end_all(self, error=None):
        """End all open spans (for error cleanup)."""
        self.end_task(error=error)
        self.end_metrics()
        self.end_eval(error=error)


class NullTrace:
    """No-op trace/span used when OTEL is disabled.

    Provides the interface adapters expect (.update, .trace_id).
    """

    def __init__(self, name: str = "", input: Any = None, metadata: Optional[Dict[str, Any]] = None):
        self.name = name
        self.input = input
        self.metadata = metadata or {}
        self.output: Any = None
        self.trace_id = None

    def update(self, **kwargs: Any) -> None:
        if "input" in kwargs:
            self.input = kwargs.get("input")
        if "output" in kwargs:
            self.output = kwargs.get("output")

    def start_span(self, name: str = "", input: Any = None, metadata: Optional[Dict[str, Any]] = None) -> "NullTrace":
        return NullTrace(name=name, input=input, metadata=metadata)

    def score(self, **kwargs: Any) -> None:
        return None

    def end(self) -> None:
        return None


from .config import EvaluatorConfig


def _detect_git_info(config: Optional[EvaluatorConfig] = None) -> Dict[str, Optional[str]]:
    """Auto-detect git branch and commit hash. Config overrides take precedence."""
    branch = getattr(config, "git_branch", None) if config else None
    commit = getattr(config, "git_commit", None) if config else None

    if not branch:
        try:
            raw = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                stderr=subprocess.DEVNULL,
            )
            branch = raw.decode().strip() or None
        except Exception:
            branch = None

    if not commit:
        try:
            raw = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
            )
            commit = raw.decode().strip() or None
        except Exception:
            commit = None

    return {"git_branch": branch, "git_commit": commit}


class Evaluator:
    """
    Simple evaluator for LLM tasks using Langfuse datasets.
    """

    # One-shot probe: track async metric functions already checked for blocking.
    _metric_blocking_probed: Set[int] = set()
    _metric_blocking_warned: Set[int] = set()

    def __init__(
        self,
        task: Any,
        dataset: Union[str, Any],
        metrics: List[Union[str, Callable]],
        config: Optional[Union[Dict[str, Any], EvaluatorConfig]] = None,
        observer: Optional[EvaluationObserver] = None,
        model: Optional[Union[str, Sequence[str]]] = None,
        langfuse_client: Optional[Any] = None,
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
        
        # Initialize OpenLLMetry auto-instrumentation FIRST so TracerProvider exists
        # before Langfuse (which will attach its processor to the same provider).
        from .otel import create_otel_manager
        self._otel = create_otel_manager(self.config)

        # Initialize Langfuse client ONLY when credentials exist (or user provided a client).
        # This ensures CSV/local datasets work without requiring Langfuse setup.
        self.client: Optional[Any] = None
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
            from .dataset import LangfuseDataset
            self.dataset = LangfuseDataset(self.client, dataset)
        else:
            self.dataset = dataset
            self.dataset_name = getattr(dataset, "dataset_name", getattr(dataset, "name", "unknown"))
        
        # Prepare task adapter
        self.task_adapter = auto_detect_task(task, self.client)
        self.task_adapter._warning_callback = lambda msg: self._notify_observer(
            "on_warning", message=msg,
        )

        # Configuration shortcuts
        self.max_concurrency = self.config.max_concurrency
        self.max_metric_concurrency = self.config.max_metric_concurrency
        self.timeout = self.config.timeout
        self.max_retries = self.config.max_retries

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
        """Extract trace_id and build Langfuse URL.

        In Langfuse SDK v3, LangfuseSpan exposes .trace_id directly.
        Falls back to .id for NullTrace or legacy objects.
        """
        meta: Dict[str, Any] = {"trace_id": None, "trace_url": None}
        try:
            tid = getattr(trace, 'trace_id', None) or getattr(trace, 'id', None)
            meta["trace_id"] = str(tid) if tid else None
        except Exception:
            pass
        if meta["trace_id"] and getattr(self, 'langfuse_host', None) and getattr(self, 'langfuse_project_id', None):
            host = self.langfuse_host.rstrip('/')
            meta["trace_url"] = f"{host}/project/{self.langfuse_project_id}/traces/{meta['trace_id']}"
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

        # Git info (best-effort, with config overrides)
        git_info = _detect_git_info(self.config)

        run_block: Dict[str, Any] = {
            "dataset_name": self.dataset_name,
            "run_name": self.run_name,
            "config": {
                "max_concurrency": self.max_concurrency,
                "max_metric_concurrency": self.max_metric_concurrency,
                "timeout": self.timeout,
                "run_metadata": self.run_metadata,
            },
            "model": self.model_name,
            "version": version,
            "git_sha": git_info["git_commit"],
            "git_branch": git_info["git_branch"],
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
    
    def _init_langfuse(self) -> Any:
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
            from langfuse import Langfuse

            # Pass traceloop's TracerProvider so Langfuse adds its span processor
            # to the same provider — all spans (auto-instrumented + manual) flow
            # through one provider to both Langfuse and QymSpanProcessor.
            init_kwargs = dict(
                public_key=public_key,
                secret_key=secret_key,
                host=host,
                timeout=self.config.timeout,
            )
            if self._otel.enabled:
                from opentelemetry import trace as otel_trace
                provider = otel_trace.get_tracer_provider()
                init_kwargs["tracer_provider"] = provider
            client = Langfuse(**init_kwargs)
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

    def _is_langfuse_dataset(self) -> bool:
        """Check if current dataset is a LangfuseDataset without top-level import."""
        return type(self.dataset).__name__ == "LangfuseDataset"

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
        try:
            result = asyncio.run(self.arun(show_tui=show_tui, auto_save=auto_save, save_format=save_format))
        except KeyboardInterrupt:
            # asyncio.run() tears down the event loop on Ctrl+C before arun's
            # finalization code can send run_completed. Send STOPPED synchronously here.
            if not getattr(self, "_run_completed", False):
                print("[QYM-SDK] Interrupted — sending STOPPED to platform", flush=True)
                stream = getattr(self, "_platform_stream", None)
                if stream is not None:
                    try:
                        stream.emit(
                            "run_completed",
                            {
                                "ended_at": _utc_now_str(),
                                "final_status": "STOPPED",
                                "summary": {},
                            },
                            sync=True,
                        )
                    except Exception:
                        pass
            raise

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
        # Size the thread pool to match concurrency so sync tasks don't queue.
        # Skip if MultiModelRunner already sized the pool for all models.
        loop = asyncio.get_running_loop()
        if not getattr(loop, '_qym_executor_set', False):
            loop.set_default_executor(
                concurrent.futures.ThreadPoolExecutor(max_workers=self.max_concurrency)
            )
            loop._qym_executor_set = True

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
                "max_metric_concurrency": self.max_metric_concurrency,
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
            git_info = _detect_git_info(self.config)
            handle = client.create_run(
                external_run_id=self.run_name,
                task=self._task_name,
                dataset=str(self.dataset_name),
                model=self.model_name,
                metrics=list(self.metrics.keys()),
                run_metadata=start_metadata,
                run_config={
                    "max_concurrency": self.max_concurrency,
                    "max_metric_concurrency": self.max_metric_concurrency,
                    "timeout": self.timeout,
                    "run_name": self.run_name,
                    "task_name": self._task_name,
                    "run_config_id": _compute_run_config_id({"max_concurrency": self.max_concurrency, "max_metric_concurrency": self.max_metric_concurrency, "timeout": self.timeout, "model": self.model_name, "task": self._task_name, "dataset": str(self.dataset_name)}),
                    "git_branch": git_info["git_branch"],
                    "git_commit": git_info["git_commit"],
                },
            )
            html_url = handle.live_url
            self._platform_stream = PlatformEventStream(platform_url=platform_url, api_key=platform_api_key, run_id=handle.run_id)
            # Connect QymSpanProcessor to platform stream for local DB capture
            if self._otel.enabled and self._otel.qym_processor:
                self._otel.qym_processor.set_stream(self._platform_stream)
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
                            "max_metric_concurrency": self.max_metric_concurrency,
                            "timeout": self.timeout,
                            "run_name": self.run_name,
                            "task_name": self._task_name,
                            "run_config_id": _compute_run_config_id({"max_concurrency": self.max_concurrency, "max_metric_concurrency": self.max_metric_concurrency, "timeout": self.timeout, "model": self.model_name, "task": self._task_name, "dataset": str(self.dataset_name)}),
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
                        "max_metric_concurrency": self.max_metric_concurrency,
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
                            run_config={"max_concurrency": self.max_concurrency, "max_metric_concurrency": self.max_metric_concurrency, "timeout": self.timeout},
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
                            run_config={"max_concurrency": self.max_concurrency, "max_metric_concurrency": self.max_metric_concurrency, "timeout": self.timeout},
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
                            run_config={"max_concurrency": self.max_concurrency, "max_metric_concurrency": self.max_metric_concurrency, "timeout": self.timeout},
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
        self._run_completed = False
        _final_status = "STOPPED" if interrupted else "COMPLETED"
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
                        "final_status": _final_status,
                        "summary": {
                            "total_items": result.total_items,
                            "success_count": len(result.results),
                            "error_count": len(result.errors),
                            "run_metadata": final_run_metadata,
                        },
                    },
                    sync=True,  # Send synchronously to guarantee delivery
                )
                self._run_completed = True
            except Exception:
                pass

        # Auto-save if requested (message printed by save_* methods)
        if auto_save and not checkpoint_path:
            try:
                result.save(format=save_format, output_dir=self.config.output_dir)
            except Exception as e:
                console.print(f"[yellow]⚠️  Warning: Failed to auto-save results: {e}[/yellow]")
        
        # Flush Langfuse spans
        if self.client:
            try:
                self.client.flush()
            except Exception:
                pass

        # Flush and shut down OTEL
        self._otel.shutdown()

        # Shut down the thread pool so asyncio.run() doesn't hang waiting for idle threads.
        try:
            loop = asyncio.get_running_loop()
            executor = loop.get_default_executor()
            if executor is not None:
                executor.shutdown(wait=False)
        except Exception:
            pass

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

        try:
            results = asyncio.run(
                runner.arun(
                    show_tui=show_tui,
                    auto_save=auto_save,
                    save_format=save_format,
                    max_parallel_runs=max_parallel_runs,
                )
            )
        except KeyboardInterrupt:
            incomplete = [ev for ev in getattr(runner, "_active_evaluators", []) if not getattr(ev, "_run_completed", False)]
            if incomplete:
                print(f"[QYM-SDK] Interrupted — sending STOPPED for {len(incomplete)} incomplete run(s)", flush=True)
                for ev in incomplete:
                    stream = getattr(ev, "_platform_stream", None)
                    if stream is not None:
                        try:
                            stream.emit(
                                "run_completed",
                                {
                                    "ended_at": _utc_now_str(),
                                    "final_status": "STOPPED",
                                    "summary": {},
                                },
                                sync=True,
                            )
                        except Exception:
                            pass
            raise

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
    
    # ------------------------------------------------------------------
    # _evaluate_item: decomposed into focused sub-methods
    # ------------------------------------------------------------------

    def _create_item_spans(self, index: int, item: Any) -> ItemSpans:
        """Create OTEL spans with OpenInference attributes for an eval item."""
        spans = ItemSpans()
        item_metadata = getattr(item, 'metadata', {})

        if not self._otel.enabled:
            return spans

        from opentelemetry import trace as otel_trace
        spans.tracer = otel_trace.get_tracer("qym")

        # Root eval span
        spans.eval_span, spans.eval_token = ItemSpans._start_span(
            spans.tracer,
            name=f"eval-{self.run_name}-item-{index}",
            kind="CHAIN",
            input_value=item.input,
            metadata={
                **self.run_metadata,
                "item_index": index,
                "dataset_item_id": getattr(item, 'id', None),
                "run_name": self.run_name,
                "item_metadata": item_metadata,
            },
        )

        # Extract trace_id from the OTEL span
        _ctx = spans.eval_span.get_span_context()
        if _ctx.is_valid:
            spans.trace_id = format(_ctx.trace_id, '032x')
            if getattr(self, 'langfuse_host', None) and getattr(self, 'langfuse_project_id', None):
                host = self.langfuse_host.rstrip('/')
                spans.trace_url = f"{host}/project/{self.langfuse_project_id}/traces/{spans.trace_id}"

        # Task function span (child of eval, parent of LLM calls)
        task_name = getattr(self.task_adapter.task, "__name__", "task")
        spans.task_span, spans.task_token = ItemSpans._start_span(
            spans.tracer,
            name=task_name,
            kind="AGENT",
            input_value=item.input,
        )

        # Reset tool call tracking for this item
        from .otel import _emitted_tool_ids
        _emitted_tool_ids.set(set())

        return spans

    def _emit_item_started(self, index: int, item: Any):
        """Emit item_started to platform stream and notify observer."""
        try:
            ps = getattr(self, "_platform_stream", None)
            if ps is not None:
                item_id = getattr(item, "id", None) or f"item_{index}"
                ps.emit("item_started", {
                    "item_id": str(item_id),
                    "index": int(index),
                    "input": item.input,
                    "expected": getattr(item, "expected_output", None),
                    "item_metadata": getattr(item, "metadata", {}) or {},
                })
        except Exception:
            pass
        self._notify_observer("on_item_start", item_index=index, payload={
            "input": item.input,
            "expected": getattr(item, 'expected_output', None),
        })

    async def _execute_task(self, index: int, item: Any, spans: ItemSpans) -> Tuple[Any, float, int]:
        """Execute the task with retry logic. Returns (output, elapsed_time, retry_count)."""
        # Create a NullTrace for adapter compatibility
        adapter_trace = NullTrace(name=f"eval-{self.run_name}-item-{index}", input=item.input)
        adapter_trace.trace_id = spans.trace_id

        task_start_time = time.time()
        last_error = None
        output = None

        for _attempt in range(1 + self.max_retries):
            try:
                coro = self.task_adapter.arun(item.input, adapter_trace, model_name=self.model_name_full)
                if self.timeout is not None:
                    output = await asyncio.wait_for(coro, timeout=self.timeout)
                else:
                    output = await coro
                last_error = None
                break
            except asyncio.TimeoutError:
                last_error = f"Task timed out after {self.timeout}s (attempt {_attempt + 1}/{1 + self.max_retries})"
                logger.warning(f"Item {index}: {last_error}")
            except Exception as e:
                last_error = f"{type(e).__name__}: {e} (attempt {_attempt + 1}/{1 + self.max_retries})"
                logger.warning(f"Item {index}: {last_error}")
            if _attempt < self.max_retries and last_error is not None:
                base_delay = min(2 ** _attempt, 30)
                jitter = random.uniform(0, base_delay * 0.5)
                await asyncio.sleep(base_delay + jitter)

        retry_count = _attempt
        if last_error is not None:
            raise RuntimeError(last_error)

        return output, time.time() - task_start_time, retry_count

    async def _compute_metrics(self, index: int, item: Any, output: Any, spans: ItemSpans) -> Dict[str, Any]:
        """Compute all metrics concurrently. Returns {metric_name: score_dict}."""
        expected_output = getattr(item, 'expected_output', None)

        # Create metrics parent span
        if spans.tracer:
            spans.metrics_span, spans.metrics_token = ItemSpans._start_span(
                spans.tracer, name="eval_metrics", kind="EVALUATOR",
            )

        _metric_sem = asyncio.Semaphore(self.max_metric_concurrency)

        async def run_one(m_name: str, m_func: Callable) -> Tuple[str, Any]:
            async with _metric_sem:
                return await self._run_single_metric(
                    m_name, m_func, output, expected_output, index, item, spans,
                )

        results = await asyncio.gather(*[
            run_one(m_name, m_func) for m_name, m_func in self.metrics.items()
        ])
        return dict(results)

    async def _run_single_metric(
        self, m_name: str, m_func: Callable, output: Any, expected: Any,
        index: int, item: Any, spans: ItemSpans,
    ) -> Tuple[str, Any]:
        """Run a single metric, emit score event, and notify platform."""
        try:
            # Compute metric (async or sync)
            if asyncio.iscoroutinefunction(m_func):
                func_id = id(m_func)
                should_probe = func_id not in Evaluator._metric_blocking_probed

                if not should_probe:
                    score = await self._compute_metric(m_func, output, expected, item.input)
                else:
                    Evaluator._metric_blocking_probed.add(func_id)
                    _hb_ticks = 0
                    _hb_stop = False

                    async def _hb():
                        nonlocal _hb_ticks
                        while not _hb_stop:
                            await asyncio.sleep(0.1)
                            _hb_ticks += 1

                    hb_task = asyncio.create_task(_hb())
                    _t0 = time.monotonic()
                    try:
                        score = await self._compute_metric(m_func, output, expected, item.input)
                    finally:
                        _hb_stop = True
                        _elapsed = time.monotonic() - _t0
                        hb_task.cancel()
                        try:
                            await hb_task
                        except asyncio.CancelledError:
                            pass

                        if _elapsed > 1.0 and _hb_ticks < 2:
                            if func_id not in Evaluator._metric_blocking_warned:
                                Evaluator._metric_blocking_warned.add(func_id)
                                _fname = getattr(m_func, '__name__', m_name)
                                warning_msg = (
                                    f"Async metric '{_fname}' appears to block "
                                    f"the event loop ({_elapsed:.1f}s elapsed, "
                                    f"{_hb_ticks} event-loop ticks). Fix: remove "
                                    f"'async' from your metric function so qym "
                                    f"runs it in a thread pool automatically."
                                )
                                logger.warning(warning_msg)
                                self._notify_observer("on_warning", message=warning_msg)
            else:
                score = await asyncio.to_thread(
                    self._compute_metric_sync, m_func, output, expected, item.input,
                )

            # Wrap in MetricResult
            from qym.metrics.result import MetricResult
            result = MetricResult.from_raw(score)
            main_val = result.score

            # Add score as OTEL event on eval span (provider-agnostic)
            spans.add_score_event(m_name, main_val, result.label, result.explanation)

            # Langfuse: push score to Langfuse API (for UI score badges + dataset linkage)
            if self.client and spans.trace_id:
                try:
                    comment = result.explanation or (str(score) if not isinstance(main_val, (int, float)) else None)
                    self.client.create_score(
                        trace_id=spans.trace_id,
                        name=m_name,
                        value=main_val if isinstance(main_val, (int, float)) else 0,
                        comment=comment,
                    )
                except Exception:
                    pass

            # Platform: metric scored
            try:
                ps = getattr(self, "_platform_stream", None)
                if ps is not None:
                    item_id = getattr(item, "id", None) or f"item_{index}"
                    ps.emit("metric_scored", {
                        "item_id": str(item_id),
                        "metric_name": str(m_name),
                        "score_numeric": result.score,
                        "score_raw": result.to_legacy_dict(),
                        "meta": result.metadata or {},
                        "label": result.label,
                        "explanation": result.explanation,
                    })
            except Exception:
                pass

            return m_name, score
        except Exception as e:
            logger.error(f"Metric {m_name} failed: {e}")
            return m_name, {"score": 0, "error": traceback.format_exc()}

    async def _link_dataset_item(self, index: int, item: Any, spans: ItemSpans, error: Optional[str] = None):
        """Link trace to Langfuse dataset run item (Langfuse datasets only)."""
        dataset_item_id = getattr(item, 'id', None)
        trace_id = spans.trace_id
        if not (self._is_langfuse_dataset() and self.client and dataset_item_id and trace_id):
            return
        try:
            from langfuse.api.resources.dataset_run_items.types import CreateDatasetRunItemRequest
            metadata = {**self.run_metadata}
            if error:
                metadata["error"] = error
            response = await self.client.async_api.dataset_run_items.create(
                request=CreateDatasetRunItemRequest(
                    runName=self.run_name,
                    runDescription=None,
                    metadata=metadata,
                    datasetItemId=dataset_item_id,
                    traceId=trace_id,
                )
            )
            if self._langfuse_run_id is None and response:
                run_id = (
                    getattr(response, 'run_id', None) or
                    getattr(response, 'runId', None) or
                    getattr(response, 'dataset_run_id', None) or
                    getattr(response, 'datasetRunId', None)
                )
                if not run_id and hasattr(response, 'run'):
                    run_id = getattr(response.run, 'id', None)
                self._langfuse_run_id = run_id
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

    def _update_tracker(
        self, index: int, item: Any, output: Any, scores: Dict,
        task_time: float, retry_count: int, spans: ItemSpans,
        tracker: "ProgressObserver",
    ):
        """Update the progress tracker with results."""
        tracker.update_trace_info(index, spans.trace_id, spans.trace_url)
        tracker.update_output(index, output)
        if retry_count > 0:
            tracker.item_statuses[index]['retry_count'] = retry_count

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
                self._notify_observer("on_metric_result", item_index=index,
                                      metric_name=m_name, score=score,
                                      metadata={"input": item.input, "expected": getattr(item, 'expected_output', None)})
            else:
                tracker.set_metric_error(index, m_name)

        scores = {k: v for k, v in scores.items() if v is not None}
        tracker.complete_item(index)

    def _emit_item_completed(
        self, index: int, item: Any, output: Any, task_time: float,
        spans: ItemSpans, retry_count: int,
    ):
        """Emit item_completed to platform stream and notify observer."""
        try:
            ps = getattr(self, "_platform_stream", None)
            if ps is not None:
                item_id = getattr(item, "id", None) or f"item_{index}"
                ps.emit("item_completed", {
                    "item_id": str(item_id),
                    "index": int(index),
                    "output": output,
                    "latency_ms": float(task_time * 1000.0),
                    "trace_id": spans.trace_id,
                    "trace_url": spans.trace_url,
                    "task_started_at_ms": int(time.time() * 1000),
                    "retry_count": retry_count,
                })
        except Exception:
            pass
        self._notify_observer("on_item_complete", item_index=index, result={
            "output": output, "scores": {}, "task_time": task_time,
        })

    async def _handle_item_error(
        self, index: int, item: Any, error: Exception,
        spans: ItemSpans, tracker: "ProgressObserver",
        task_started_at_ms: Optional[int] = None,
    ):
        """Handle item evaluation error: end spans, link dataset, emit failure."""
        spans.end_all(error=error)
        await self._link_dataset_item(index, item, spans, error=str(error))
        tracker.update_trace_info(index, spans.trace_id, spans.trace_url)
        tracker.fail_item(index, str(error))
        self._notify_observer("on_item_error", item_index=index, error=str(error))
        try:
            ps = getattr(self, "_platform_stream", None)
            if ps is not None:
                item_id = getattr(item, "id", None) or f"item_{index}"
                ps.emit("item_failed", {
                    "item_id": str(item_id),
                    "index": int(index),
                    "error": str(error),
                    "trace_id": spans.trace_id,
                    "trace_url": spans.trace_url,
                })
        except Exception:
            pass

    async def _evaluate_item(self, index: int, item: Any, tracker: "ProgressObserver"):
        """Evaluate a single item: create spans, run task, compute metrics, emit results."""
        spans = self._create_item_spans(index, item)
        task_started_at_ms: Optional[int] = None

        try:
            tracker.start_item(index)
            self._emit_item_started(index, item)

            task_started_at_ms = int(time.time() * 1000)
            output, task_time, retry_count = await self._execute_task(index, item, spans)
            spans.end_task(output=output)
            scores = await self._compute_metrics(index, item, output, spans)
            spans.end_metrics(scores=scores)
            spans.end_eval(output=output)
            await self._link_dataset_item(index, item, spans)
            self._update_tracker(index, item, output, scores, task_time, retry_count, spans, tracker)
            self._emit_item_completed(index, item, output, task_time, spans, retry_count)

            return {
                "input": item.input,
                "output": output,
                "expected": getattr(item, 'expected_output', None),
                "scores": {k: v for k, v in scores.items() if v is not None},
                "trace_id": spans.trace_id,
                "trace_url": spans.trace_url,
                "time": task_time,
                "task_started_at_ms": task_started_at_ms,
                "success": True,
            }

        except Exception as e:
            await self._handle_item_error(index, item, e, spans, tracker, task_started_at_ms)
            return {
                "_error": str(e),
                "_trace_id": spans.trace_id,
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
