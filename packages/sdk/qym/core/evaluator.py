"""Main Evaluator class for LLM evaluation."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import inspect
import json as _json
import os
import random
import signal
import threading
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Union, Tuple, Set
from datetime import datetime, timezone
import time
import subprocess
from pathlib import Path
import copy
from contextlib import contextmanager, nullcontext
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
    ProgressCallbackObserver,
    ProgressSnapshot,
)
from .dashboard import RunDashboard, console_supports_live
from ..adapters.base import TaskAdapter, auto_detect_task
from ..metrics.registry import get_metric, get_metric_spec
from ..metrics.judges.base import JudgeInputError
from ..metrics.spec import Metric, MetricSpec
from ..utils.env import load_cwd_dotenv


def _strip_model_provider(model_name: Optional[str]) -> str:
    """Remove provider prefix from model name (e.g., 'qwen/qwen3-235b' -> 'qwen3-235b')."""
    if not model_name:
        return ""
    slash_idx = model_name.find("/")
    return model_name[slash_idx + 1 :] if slash_idx > 0 else model_name


def _compute_run_config_id(config: Dict[str, Any]) -> str:
    """Compute a stable hash from run config, excluding ephemeral fields.

    Used by platform to group runs with identical configurations.
    """
    import hashlib
    import json

    ephemeral = {"run_name", "resume_from", "cli_invocation", "run_metadata"}
    stable = {k: v for k, v in sorted(config.items()) if k not in ephemeral}
    raw = json.dumps(stable, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


from ..utils.errors import DatasetNotFoundError

# UIServer has been removed - platform streaming is now required
# from ..server.app import UIServer  # DEPRECATED
import json
import logging

logger = logging.getLogger(__name__)
from ..platform.defaults import DEFAULT_PLATFORM_URL


def _utc_now_str() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _interrupt_signal_numbers() -> List[int]:
    signals: List[int] = []
    for name in ("SIGINT", "SIGTERM", "SIGHUP", "SIGQUIT"):
        signum = getattr(signal, name, None)
        if signum is not None:
            signals.append(signum)
    return signals


@contextmanager
def _graceful_interrupt_signals():
    """Temporarily map catchable termination signals to KeyboardInterrupt."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    previous_handlers: Dict[int, Any] = {}

    def _raise_keyboard_interrupt(signum, frame):
        raise KeyboardInterrupt()

    try:
        for signum in _interrupt_signal_numbers():
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, _raise_keyboard_interrupt)
    except Exception:
        for signum, handler in previous_handlers.items():
            try:
                signal.signal(signum, handler)
            except Exception:
                pass
        yield
        return

    try:
        yield
    finally:
        for signum, handler in previous_handlers.items():
            try:
                signal.signal(signum, handler)
            except Exception:
                pass


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
                span.set_attribute(
                    "input.value", _json.dumps(input_value, default=str)[:16000]
                )
                span.set_attribute("input.mime_type", "application/json")
            except Exception:
                span.set_attribute("input.value", str(input_value)[:16000])
        if metadata:
            try:
                span.set_attribute(
                    "metadata", _json.dumps(metadata, default=str)[:8000]
                )
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
                span.set_attribute(
                    "output.value",
                    _json.dumps({"error": str(error)}, default=str)[:16000],
                )
            except Exception:
                pass
        elif output_value is not None:
            try:
                span.set_attribute(
                    "output.value", _json.dumps(output_value, default=str)[:16000]
                )
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
            self._end_span(
                self.task_span, self.task_token, output_value=output, error=error
            )
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
            self._end_span(
                self.eval_span, self.eval_token, output_value=output, error=error
            )
            self.eval_span = None
            self.eval_token = None

    def end_all(self, error=None):
        """End all open spans (for error cleanup)."""
        self.end_task(error=error)
        self.end_metrics()
        self.end_eval(error=error)


@dataclass
class TaskAttemptResult:
    attempt_number: int
    spans: ItemSpans
    task_started_at_ms: Optional[int]
    latency_s: float
    output: Any = None
    metric_output: Any = None
    task_metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    retryable: bool = True

    @property
    def success(self) -> bool:
        return self.error is None

    @property
    def status(self) -> str:
        return "completed" if self.success else "failed"

    @property
    def latency_ms(self) -> float:
        return float(self.latency_s * 1000.0)


class TaskExecutionTimeoutError(Exception):
    """Raised when the task itself surfaces a timeout before qym's wrapper does."""


class InvalidTaskOutputError(Exception):
    """Raised when a dict task output does not match qym's task envelope."""


def _normalize_task_output(raw_output: Any) -> Tuple[Any, Dict[str, Any], Any]:
    """Return ``(visible_output, task_metadata, metric_output)`` from a task return value.

    Plain non-dict values are treated as visible outputs. Dict task returns are
    reserved for qym's explicit task-output envelope:
    ``{"output": ..., "metadata": {...}}``.
    """
    if not isinstance(raw_output, dict):
        return raw_output, {}, raw_output

    expected_keys = {"output", "metadata"}
    actual_keys = set(raw_output.keys())
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        extra = sorted(actual_keys - expected_keys)
        details = []
        if missing:
            details.append(f"missing keys: {', '.join(missing)}")
        if extra:
            details.append(f"unexpected keys: {', '.join(extra)}")
        suffix = f" ({'; '.join(details)})" if details else ""
        raise InvalidTaskOutputError(
            "Task returned a dict. Dict task outputs must use qym's envelope "
            '{"output": <visible output>, "metadata": <dict>}'
            f"{suffix}."
        )

    metadata = raw_output.get("metadata")
    if not isinstance(metadata, dict):
        raise InvalidTaskOutputError(
            "Task output envelope field 'metadata' must be a dict."
        )
    return raw_output.get("output"), metadata, raw_output


def _item_metadata_with_task_metadata(
    item_metadata: Any, task_metadata: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Merge dataset item metadata with task-return metadata for storage/UI."""
    merged = dict(item_metadata) if isinstance(item_metadata, dict) else {}
    if task_metadata:
        merged["task_metadata"] = dict(task_metadata)
    return merged


class NullTrace:
    """No-op trace/span used when OTEL is disabled.

    Provides the interface adapters expect (.update, .trace_id).
    """

    def __init__(
        self,
        name: str = "",
        input: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
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

    def start_span(
        self,
        name: str = "",
        input: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "NullTrace":
        return NullTrace(name=name, input=input, metadata=metadata)

    def score(self, **kwargs: Any) -> None:
        return None

    def end(self) -> None:
        return None


from .config import EvaluatorConfig


def _detect_git_info(
    config: Optional[EvaluatorConfig] = None,
) -> Dict[str, Optional[str]]:
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


async def _emit_platform_event(stream, type_: str, payload, *, sync=False):
    if callable(getattr(type(stream), "aemit", None)):
        await stream.aemit(type_, payload, sync=sync)
    else:
        # Stream substitutes historically expose only emit().
        if sync:
            await asyncio.to_thread(stream.emit, type_, payload, sync=True)
        else:
            stream.emit(type_, payload)


async def _close_platform_stream(stream):
    if callable(getattr(type(stream), "aclose", None)):
        await stream.aclose()
    else:
        await asyncio.to_thread(stream.close)


class Evaluator:
    """Simple evaluator for LLM tasks."""

    # One-shot probe: track async metric functions already checked for blocking.
    _metric_blocking_probed: Set[int] = set()
    _metric_blocking_warned: Set[int] = set()

    def __init__(
        self,
        task: Any,
        dataset: Union[str, Any],
        metrics: List[Union[str, Callable, Metric]],
        config: Optional[Union[Dict[str, Any], EvaluatorConfig]] = None,
        observer: Optional[EvaluationObserver] = None,
        model: Optional[Union[str, Sequence[str]]] = None,
        samples: Optional[int] = None,
        report_k: Optional[int] = None,
        langfuse_client: Optional[Any] = None,
        progress_callback: Optional[Callable[[ProgressSnapshot], None]] = None,
        input_mapping: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize the evaluator.

        Args:
            task: Callable or framework object to evaluate.
            dataset: qym platform dataset name, local dataset path, or dataset object.
            metrics: Metric names, callables, or typed ``Metric`` definitions.
            config: Optional evaluator configuration.
            observer: Optional lifecycle observer for advanced integrations.
            model: Optional model override or list of models.
            samples: Evaluate every item this many times (k sequential passes)
                as ONE logical run; group metrics (Pass@k, Pass^k, ...) are
                reported with k = samples. Overrides ``config.samples``.
            report_k: Publish pass@k / pass^k at this k, estimated (unbiased)
                from all ``samples`` passes — run 9, report pass@3. Must be
                <= samples. Overrides ``config.report_k``.
            langfuse_client: Deprecated and ignored.
            progress_callback: Optional callback receiving ProgressSnapshot updates.
            input_mapping: Optional mapping from dataset input names to task
                parameter names. Useful when a local CSV uses columns such as
                ``sql_prompt`` and ``sql_context`` but the task signature expects
                ``question`` and ``schema``.
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

        # Override samples if provided explicitly (kwarg wins over config)
        if samples is not None:
            if not isinstance(samples, int) or samples < 1:
                raise ValueError("samples must be an integer >= 1")
            self.config.samples = samples
        if report_k is not None:
            if not isinstance(report_k, int) or report_k < 1:
                raise ValueError("report_k must be an integer >= 1")
            self.config.report_k = report_k
        if (
            self.config.report_k is not None
            and self.config.report_k > self.config.samples
        ):
            raise ValueError(
                f"report_k ({self.config.report_k}) cannot exceed samples ({self.config.samples})"
            )

        self.task = task
        self.input_mapping = self._normalize_input_mapping(input_mapping)
        self._raw_metrics = list(metrics)
        self.metric_specs: Dict[str, MetricSpec] = {}
        self.metrics = self._prepare_metrics(metrics)

        # Load only the caller's cwd .env before any config/env auto-detection.
        load_cwd_dotenv()

        # Initialize OpenLLMetry auto-instrumentation before running user code.
        from .otel import create_otel_manager

        self._otel = create_otel_manager(self.config)

        self.client: Optional[Any] = None
        self.langfuse_enabled: bool = False
        if langfuse_client is not None:
            logger.warning(
                "langfuse_client is deprecated and ignored; qym uses "
                "platform/OpenTelemetry tracing."
            )

        # Load and validate dataset
        if isinstance(dataset, str):
            from .dataset import resolve_dataset

            self.dataset = resolve_dataset(
                dataset,
                version=self.config.dataset_version,
                alias=self.config.dataset_alias,
                platform_url=self.config.platform_url,
                api_key=self.config.platform_api_key,
            )
            self.dataset_name = getattr(self.dataset, "name", dataset)
        else:
            self.dataset = dataset
            self.dataset_name = getattr(
                dataset, "dataset_name", getattr(dataset, "name", "unknown")
            )

        # Prepare task adapter
        self.task_adapter = auto_detect_task(task, self.client)
        self.task_adapter.input_mapping = self.input_mapping
        self.task_adapter._warning_callback = lambda msg: self._notify_observer(
            "on_warning",
            message=msg,
        )

        # Configuration shortcuts
        self.max_concurrency = self.config.max_concurrency
        self.max_metric_concurrency = self.config.max_metric_concurrency
        self.timeout = self.config.timeout
        self.metric_timeout = self.config.metric_timeout
        self.metric_max_retries = self.config.metric_max_retries
        self.max_retries = self.config.max_retries
        self.samples = self.config.samples
        # Passes execute strictly sequentially, so a single instance-level
        # cursor is safe: every emit during pass j reads j here.
        self._current_pass: int = 1
        self._samples_warned: bool = False

        # Model handling - strip provider prefix once, keep full name for user's task
        # e.g., "qwen/qwen3-235b" -> model_name="qwen3-235b", model_name_full="qwen/qwen3-235b"
        # Use model_full when set (multi-model runs pass provider-prefixed ID for API calls)
        self.model_name_full = (
            self.config.model_full or self.config.model
        )  # Full ID for user's task (OpenRouter, etc.)
        self.model_name = _strip_model_provider(
            self.config.model
        )  # Stripped (for display, paths, IDs)
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
                add_suffix=not user_provided_name,
            )
        self.run_metadata = self.config.run_metadata
        if self._task_name:
            self.run_metadata["task_name"] = self._task_name

        if self.model_name:
            self.run_metadata.setdefault("model", self.model_name)

        # Display name for UI: prefer run_name, but keep a readable task hint
        self.display_name = self.config.run_name
        if self._task_name and self._task_name not in (self.display_name or ""):
            self.display_name = f"{self.display_name} [{self._task_name}]"

        observers: List[EvaluationObserver] = [observer or NullEvaluationObserver()]
        if progress_callback is not None:
            observers.append(ProgressCallbackObserver(progress_callback))
        self.observer = CompositeEvaluationObserver(observers)

        self._platform_dataset_id: Optional[str] = getattr(self.dataset, "id", None)
        self._platform_dataset_version_id: Optional[str] = getattr(
            self.dataset, "dataset_version_id", None
        )

    @staticmethod
    def _normalize_input_mapping(
        input_mapping: Optional[Dict[str, str]],
    ) -> Dict[str, str]:
        """Validate and copy dataset-input to task-parameter mappings."""
        if input_mapping is None:
            return {}
        if not isinstance(input_mapping, dict):
            raise TypeError(
                "input_mapping must be a dict of input name to parameter name"
            )

        normalized: Dict[str, str] = {}
        for source, target in input_mapping.items():
            if not isinstance(source, str) or not source.strip():
                raise ValueError("input_mapping keys must be non-empty strings")
            if not isinstance(target, str) or not target.strip():
                raise ValueError("input_mapping values must be non-empty strings")
            normalized[source] = target
        return normalized

    # Class-level counter for ensuring unique run IDs within the same process
    _run_id_counter: Dict[str, int] = {}

    def _should_stop_requested(self) -> bool:
        callback = getattr(self.config, "should_stop", None)
        if not callable(callback):
            return False
        try:
            return bool(callback())
        except Exception:
            logger.warning("Evaluator should_stop callback failed", exc_info=True)
            return False

    @staticmethod
    def build_run_identifiers(
        base_name: str, model_name: Optional[str], add_suffix: bool = False
    ) -> Tuple[str, str]:
        """Return (run_id_with_suffixes, display_name_for_tui).

        Ensures unique run IDs even when the same model is used multiple times
        by appending a counter when duplicates are detected.

        - run_id: Used for persisted run identity, must be unique
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
        """Extract trace_id from a trace-like object."""
        meta: Dict[str, Any] = {"trace_id": None, "trace_url": None}
        try:
            tid = getattr(trace, "trace_id", None) or getattr(trace, "id", None)
            meta["trace_id"] = str(tid) if tid else None
        except Exception:
            pass
        return meta

    def _build_run_info(
        self, result: Optional[EvaluationResult] = None
    ) -> Dict[str, Any]:
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
                "input_mapping": dict(self.input_mapping),
                "run_metadata": self.run_metadata,
            },
            "model": self.model_name,
            "version": version,
            "git_sha": git_info["git_commit"],
            "git_branch": git_info["git_branch"],
            "cli_invocation": self.config.cli_invocation,
            "metric_names": list(self.metrics.keys()),
            "metric_specs": self._metric_specs_payload(),
            "trace": {
                "destinations": {
                    "phoenix": bool(getattr(self._otel, "phoenix_enabled", False)),
                    "platform": False,
                },
                "instrumentors": list(
                    getattr(self._otel, "registered_instrumentors", []) or []
                ),
            },
        }

        if result is not None:
            try:
                run_block["started_at"] = (
                    result.start_time.isoformat() if result.start_time else None
                )
                run_block["ended_at"] = (
                    result.end_time.isoformat() if result.end_time else None
                )
                run_block["total_items"] = result.total_items
            except Exception:
                pass

        return run_block

    def _metric_specs_payload(self) -> Dict[str, Dict[str, Any]]:
        return {name: spec.to_dict() for name, spec in self.metric_specs.items()}

    def _prepare_metrics(
        self, metrics: List[Union[str, Callable, Metric]]
    ) -> Dict[str, Callable]:
        """Convert metric list to dict of callables."""
        prepared = {}
        for metric in metrics:
            if isinstance(metric, Metric):
                name = metric.name
                func = metric.fn
                spec = metric.spec
            elif isinstance(metric, str):
                name = metric
                func = get_metric(metric)
                spec = get_metric_spec(metric)
            elif callable(metric):
                name = getattr(metric, "__name__", f"custom_metric_{len(prepared)}")
                func = metric
                spec = MetricSpec(score_type="legacy")
            else:
                raise ValueError(
                    f"Metric must be string or callable, got {type(metric)}"
                )
            if name in prepared:
                raise ValueError(f"Duplicate metric name: {name!r}")
            prepared[name] = func
            self.metric_specs[name] = spec
        return prepared

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

    def _warning_should_render_only_in_tui(self) -> bool:
        """Return True when warnings should stay inside the live dashboard."""

        def _observer_has_enabled_dashboard(observer: Any) -> bool:
            if observer is None:
                return False
            dashboard = getattr(observer, "dashboard", None)
            if dashboard is not None and bool(getattr(dashboard, "enabled", False)):
                return True
            for child in getattr(observer, "_observers", []) or []:
                if _observer_has_enabled_dashboard(child):
                    return True
            return False

        try:
            return _observer_has_enabled_dashboard(self.observer)
        except Exception:
            return False

    def _maybe_emit_sync_threadpool_advisory(self, *, parallel_runs: int = 1) -> None:
        """Emit a low-priority advisory for sync-threadpool tasks at high concurrency."""
        if getattr(self, "_sync_threadpool_advisory_emitted", False):
            return

        try:
            mode = str(self.task_adapter.execution_mode() or "unknown")
        except Exception:
            mode = "unknown"
        if mode != "sync-threadpool":
            return

        try:
            per_run = max(1, int(self.max_concurrency or 1))
        except Exception:
            per_run = 1
        try:
            parallel = max(1, int(parallel_runs or 1))
        except Exception:
            parallel = 1
        effective = per_run * parallel

        if effective < 12:
            return

        task_name = str(getattr(self, "_task_name", "") or "task")
        advisory_registry = getattr(self, "_sync_threadpool_advisory_registry", None)
        if advisory_registry is not None:
            if task_name in advisory_registry:
                return
            advisory_registry.add(task_name)

        self._sync_threadpool_advisory_emitted = True
        run_label = "run" if parallel == 1 else "runs"
        item_label = "item" if effective == 1 else "items"
        warning_msg = (
            f"Task '{task_name}' is running in sync-threadpool mode. qym is running this task "
            "in worker threads because it is synchronous. That is valid, but at the current effective concurrency "
            f"(up to {effective} in-flight {item_label} across {parallel} parallel {run_label}) "
            "a fully async client may scale better for I/O-bound workloads and reduce thread overhead. "
            "If this task mainly makes network calls, consider switching from blocking clients such as "
            "OpenAI() to async equivalents such as AsyncOpenAI()."
        )
        if not self._warning_should_render_only_in_tui():
            logger.warning(warning_msg)
        self._notify_observer("on_warning", message=warning_msg)

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

        if sys.platform == "win32":
            # Use SelectorEventLoop on Windows to avoid ProactorEventLoop issues
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        if len(self.models) > 1:
            return self._run_multi_model(
                show_tui, auto_save, save_format, max_parallel_runs
            )

        # Run the async evaluation
        try:
            with _graceful_interrupt_signals():
                result = asyncio.run(
                    self.arun(
                        show_tui=show_tui, auto_save=auto_save, save_format=save_format
                    )
                )
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
        html_url = getattr(result, "html_url", None)
        result.print_summary(html_url)
        _announce_saved_results([result], include_run_name=False)

        return result

    async def arun(
        self, show_tui: bool = True, auto_save: bool = False, save_format: str = "csv"
    ) -> EvaluationResult:
        """Run an evaluation and release its judge clients on every exit path."""
        from ..metrics.judges._client import judge_client_scope

        async with judge_client_scope():
            completed = False
            try:
                result = await self._arun(show_tui, auto_save, save_format)
                completed = True
                return result
            finally:
                if not completed:
                    stream = getattr(self, "_platform_stream", None)
                    if stream is not None:
                        await _close_platform_stream(stream)

    async def _arun(
        self, show_tui: bool = True, auto_save: bool = False, save_format: str = "csv"
    ) -> EvaluationResult:
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
        if not getattr(loop, "_qym_executor_set", False):
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
                "samples": self.samples,
                "input_mapping": dict(self.input_mapping),
                **(
                    {"report_k": self.config.report_k}
                    if self.config.report_k is not None
                    else {}
                ),
            },
        )
        result.samples = self.samples
        result.report_k = self.config.report_k

        items = self.dataset.get_items()
        if not items:
            console.print("[yellow]Warning: Dataset is empty[/yellow]")
            return result
        self.run_metadata["total_items"] = len(items)
        self._platform_dataset_id = getattr(self.dataset, "id", None)
        self._platform_dataset_version_id = getattr(
            self.dataset, "dataset_version_id", None
        )
        if self._platform_dataset_id:
            self.run_metadata["dataset_id"] = self._platform_dataset_id
        if self._platform_dataset_version_id:
            self.run_metadata["dataset_version_id"] = self._platform_dataset_version_id

        run_info = self._build_run_info(result)

        # Initialize progress tracker
        metric_names = list(self.metrics.keys())
        tracker = ProgressTracker(items, metric_names)

        # Live UI setup (platform streaming required):
        # Local UIServer has been removed - all live viewing is via the platform
        html_url = None
        self._platform_stream = None
        otel_stream_token = None
        platform_api_key = getattr(self.config, "platform_api_key", None) or os.getenv(
            "QYM_API_KEY"
        )
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
            from ..utils.env import get_platform_url_env

            platform_url = getattr(
                self.config, "platform_url", None
            ) or get_platform_url_env(DEFAULT_PLATFORM_URL)
            if PlatformClient is None:
                warning_msg = "Platform streaming requires the platform client module"
                logger.warning(warning_msg)
                self._notify_observer("on_warning", message=warning_msg)
            else:
                client = PlatformClient(
                    platform_url=platform_url, api_key=platform_api_key
                )
                # Include total_items in metadata for progress tracking
                start_metadata = dict(self.run_metadata or {})
                start_metadata["total_items"] = len(items)
                git_info = _detect_git_info(self.config)
                run_config_id = _compute_run_config_id(
                    {
                        "max_concurrency": self.max_concurrency,
                        "max_metric_concurrency": self.max_metric_concurrency,
                        "timeout": self.timeout,
                        "model": self.model_name,
                        "task": self._task_name,
                        "dataset": str(self.dataset_name),
                        "input_mapping": self.input_mapping,
                    }
                )
                try:
                    handle = await asyncio.to_thread(
                        client.create_run,
                        external_run_id=self.run_name,
                        task=self._task_name,
                        dataset=str(self.dataset_name),
                        model=self.model_name,
                        metrics=list(self.metrics.keys()),
                        metric_specs=self._metric_specs_payload(),
                        run_metadata=start_metadata,
                        run_config={
                            "max_concurrency": self.max_concurrency,
                            "max_metric_concurrency": self.max_metric_concurrency,
                            "timeout": self.timeout,
                            "run_name": self.run_name,
                            "task_name": self._task_name,
                            "input_mapping": dict(self.input_mapping),
                            "run_config_id": run_config_id,
                            "git_branch": git_info["git_branch"],
                            "git_commit": git_info["git_commit"],
                            # Repeat runs: the platform derives Run.samples
                            # from run_config at creation; omitting it made
                            # streamed repeat runs land as samples=1 with no
                            # per-pass scores.
                            "samples": self.samples,
                            **(
                                {"report_k": self.config.report_k}
                                if self.config.report_k is not None
                                else {}
                            ),
                        },
                        dataset_id=self._platform_dataset_id,
                        dataset_version_id=self._platform_dataset_version_id,
                        dataset_alias=getattr(self.dataset, "alias", None),
                        timeout=getattr(self.config, "platform_timeout", 5.0),
                    )
                except Exception as exc:
                    error_text = (
                        f"{type(exc).__name__}: {exc}"
                        if str(exc)
                        else type(exc).__name__
                    )
                    warning_msg = (
                        f"Platform live UI disabled: failed to create run at "
                        f"{platform_url.rstrip('/')}/v1/runs ({error_text})"
                    )
                    logger.warning(warning_msg)
                    self._notify_observer("on_warning", message=warning_msg)
                    run_info.setdefault("trace", {}).setdefault("destinations", {})[
                        "platform_error"
                    ] = error_text
                else:
                    html_url = handle.live_url
                    run_info["qym_url"] = handle.live_url
                    run_info["html_url"] = handle.live_url
                    run_info["platform_run_id"] = handle.run_id
                    self._platform_stream = PlatformEventStream(
                        platform_url=platform_url,
                        api_key=platform_api_key,
                        run_id=handle.run_id,
                    )
                    # Connect QymSpanProcessor to platform stream for local DB capture
                    if self._otel.enabled and self._otel.qym_processor:
                        self._otel.qym_processor.set_stream(self._platform_stream)
                        otel_stream_token = self._otel.bind_stream(
                            self._platform_stream
                        )
                    # Seed run_started event (platform also has run record already; this is for richer metadata)
                    try:
                        await _emit_platform_event(
                            self._platform_stream,
                            "run_started",
                            {
                                "external_run_id": self.run_name,
                                "task": self._task_name,
                                "dataset": str(self.dataset_name),
                                "dataset_id": self._platform_dataset_id,
                                "dataset_version_id": self._platform_dataset_version_id,
                                "dataset_alias": getattr(self.dataset, "alias", None),
                                "model": self.model_name,
                                "metrics": list(self.metrics.keys()),
                                "metric_specs": self._metric_specs_payload(),
                                "total_items": int(self.total_items),
                                "run_metadata": dict(self.run_metadata or {}),
                                "run_config": {
                                    "max_concurrency": self.max_concurrency,
                                    "max_metric_concurrency": self.max_metric_concurrency,
                                    "timeout": self.timeout,
                                    "run_name": self.run_name,
                                    "task_name": self._task_name,
                                    "input_mapping": dict(self.input_mapping),
                                    "run_config_id": run_config_id,
                                    "samples": self.samples,
                                    **(
                                        {"report_k": self.config.report_k}
                                        if self.config.report_k is not None
                                        else {}
                                    ),
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

        self._maybe_emit_sync_threadpool_advisory(parallel_runs=1)

        # Checkpoint/resume setup
        checkpoint_path = None
        checkpoint_writer = None
        completed_item_ids: Set[str] = set()
        completed_pairs: Set[Tuple[str, int]] = set()
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
            checkpoint_state = checkpoint_state or load_checkpoint_state(
                checkpoint_path
            )
            if checkpoint_state:
                if (
                    checkpoint_state.dataset_name
                    and checkpoint_state.dataset_name != self.dataset_name
                ):
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
                completed_pairs = set(checkpoint_state.completed_pairs)
                resume_failed = len(checkpoint_state.error_item_ids)
                resume_completed = max(0, len(completed_item_ids) - resume_failed)
                for row in iter_checkpoint_rows(checkpoint_path):
                    checkpoint_rows.append(row)
                    for m in metric_names:
                        val = parse_metric_score(row.get(f"{m}_score", ""))
                        if val is not None:
                            resume_metric_totals[m] += float(val)
                            resume_metric_counts[m] += 1
                    item_id, row_result, is_error = parse_checkpoint_row(
                        row, metric_names
                    )
                    if not item_id:
                        continue
                    row_pass = int(row_result.get("pass_number") or 1)
                    if is_error:
                        error_output = str(row_result.get("output", "") or "")
                        error_msg = (
                            error_output.replace("ERROR:", "").strip() or "error"
                        )
                        if self.samples > 1:
                            result.add_pass_error(
                                item_id,
                                row_pass,
                                error_msg,
                                row_result.get("trace_id"),
                                task_started_at_ms=row_result.get("task_started_at_ms"),
                                time_seconds=row_result.get("time"),
                            )
                        else:
                            result.add_error(
                                item_id,
                                error_msg,
                                row_result.get("trace_id"),
                                task_started_at_ms=row_result.get("task_started_at_ms"),
                                time_seconds=row_result.get("time"),
                            )
                    else:
                        if isinstance(row_result.get("item_metadata"), dict):
                            result.add_metadata(item_id, row_result["item_metadata"])
                        if self.samples > 1:
                            result.add_pass_result(item_id, row_pass, row_result)
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
            "samples": self.samples,
        }
        run_info.setdefault("trace", {})
        run_info["trace"].setdefault("destinations", {})
        run_info["trace"]["destinations"]["platform"] = bool(self._platform_stream)

        self._notify_observer(
            "on_run_start",
            run_info=run_info or {},
            # Repeat runs: the progress bar spans all passes (items x samples).
            total_items=len(items) * self.samples,
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
            if self.samples > 1:
                # Repeat runs: skip only when EVERY pass already has a row;
                # partially-sampled items re-enter and the per-pass filter at
                # enqueue time skips the passes that are done.
                if all(
                    (item_id, p) in completed_pairs for p in range(1, self.samples + 1)
                ):
                    continue
            elif (
                item_id in completed_item_ids
                or fallback_id in completed_item_ids
                or (primary_id in completed_item_ids if primary_id else False)
            ):
                continue
            pending_entries.append((idx, item_id, item))

        cancel_exc: Optional[BaseException] = None

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
                if self._platform_dataset_id:
                    md["dataset_id"] = self._platform_dataset_id
                if self._platform_dataset_version_id:
                    md["dataset_version_id"] = self._platform_dataset_version_id
                return md

            async def _worker():
                nonlocal interrupted
                while True:
                    entry = await work_queue.get()
                    if entry is None:
                        work_queue.task_done()
                        break
                    idx, item_id, item, pass_number = entry
                    if self._should_stop_requested():
                        interrupted = True
                        work_queue.task_done()
                        break
                    try:
                        eval_result = await self._evaluate_item(idx, item, tracker)
                    except Exception as e:
                        eval_result = e
                        # Last-resort: emit item_failed to the platform since
                        # _evaluate_item's own error handling must have crashed.
                        try:
                            ps = getattr(self, "_platform_stream", None)
                            if ps is not None:
                                await _emit_platform_event(
                                    ps,
                                    "item_failed",
                                    {
                                        "item_id": str(item_id),
                                        "index": int(idx),
                                        "pass_number": pass_number,
                                        "error": str(e),
                                    },
                                )
                        except Exception:
                            pass

                    if isinstance(eval_result, Exception):
                        error_msg = str(eval_result)
                        if self.samples > 1:
                            result.add_pass_error(
                                item_id, pass_number, error_msg, time_seconds=0.0
                            )
                        else:
                            result.add_error(item_id, error_msg, time_seconds=0.0)
                        row = serialize_checkpoint_row(
                            pass_number=pass_number,
                            dataset_name=self.dataset_name,
                            run_name=self.run_name,
                            run_metadata=_checkpoint_run_metadata(),
                            run_config={
                                "max_concurrency": self.max_concurrency,
                                "max_metric_concurrency": self.max_metric_concurrency,
                                "timeout": self.timeout,
                            },
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
                        if self.samples > 1:
                            result.add_pass_error(
                                item_id,
                                pass_number,
                                error_msg,
                                eval_result.get("_trace_id"),
                                task_started_at_ms=eval_result.get(
                                    "task_started_at_ms"
                                ),
                                time_seconds=eval_result.get("time"),
                            )
                        else:
                            result.add_error(
                                item_id,
                                error_msg,
                                eval_result.get("_trace_id"),
                                task_started_at_ms=eval_result.get(
                                    "task_started_at_ms"
                                ),
                                time_seconds=eval_result.get("time"),
                            )
                        row = serialize_checkpoint_row(
                            pass_number=pass_number,
                            dataset_name=self.dataset_name,
                            run_name=self.run_name,
                            run_metadata=_checkpoint_run_metadata(),
                            run_config={
                                "max_concurrency": self.max_concurrency,
                                "max_metric_concurrency": self.max_metric_concurrency,
                                "timeout": self.timeout,
                            },
                            trace_id=eval_result.get("_trace_id") or "",
                            item_id=item_id,
                            item_input=item.input,
                            item_metadata=getattr(item, "metadata", {}),
                            output=f"ERROR: {error_msg}",
                            expected_output=getattr(item, "expected_output", None),
                            time_seconds=float(eval_result.get("time", 0.0) or 0.0),
                            task_started_at_ms=eval_result.get("task_started_at_ms"),
                            scores={m: "N/A" for m in metric_names},
                            metric_meta={},
                        )
                    else:
                        if isinstance(eval_result.get("item_metadata"), dict):
                            result.add_metadata(item_id, eval_result["item_metadata"])
                        if self.samples > 1:
                            eval_result["pass_number"] = pass_number
                            result.add_pass_result(item_id, pass_number, eval_result)
                        else:
                            result.add_result(item_id, eval_result)
                        scores = eval_result.get("scores", {})
                        metric_meta: Dict[str, Dict[str, Any]] = {}
                        score_row: Dict[str, Any] = {}
                        for m in metric_names:
                            sc = scores.get(m)
                            score_row[m] = _main_score(sc)
                            if isinstance(sc, dict) and isinstance(
                                sc.get("metadata"), dict
                            ):
                                metric_meta[m] = sc["metadata"]
                        row = serialize_checkpoint_row(
                            pass_number=pass_number,
                            dataset_name=self.dataset_name,
                            run_name=self.run_name,
                            run_metadata=_checkpoint_run_metadata(),
                            run_config={
                                "max_concurrency": self.max_concurrency,
                                "max_metric_concurrency": self.max_metric_concurrency,
                                "timeout": self.timeout,
                            },
                            trace_id=eval_result.get("trace_id") or "",
                            item_id=item_id,
                            item_input=item.input,
                            item_metadata=eval_result.get(
                                "item_metadata",
                                getattr(item, "metadata", {}),
                            ),
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

            writer_task = (
                asyncio.create_task(_write_loop()) if checkpoint_writer else None
            )
            # Repeat runs execute as k sequential passes over the dataset.
            # Each pass gets its own worker set; gathering them is the pass
            # barrier (pass j's slice metrics are final before pass j+1
            # starts). worker_tasks always holds the CURRENT pass's workers so
            # the interrupt handler below drains the right tasks.
            worker_tasks: List[asyncio.Task] = []

            async def _emit_pass_completed(pass_number: int) -> None:
                if self.samples <= 1:
                    return
                try:
                    slice_stats: Dict[str, Any] = {}
                    for m in metric_names:
                        values: List[float] = []
                        for entries_by_pass in result.passes.values():
                            entry = entries_by_pass.get(pass_number)
                            if entry is None:
                                continue
                            if "error" in entry:
                                values.append(0.0)
                                continue
                            val = result._main_numeric_score(
                                (entry.get("scores") or {}).get(m)
                            )
                            values.append(val if val is not None else 0.0)
                        if values:
                            slice_stats[m] = sum(values) / len(values)
                    payload = {
                        "pass_number": pass_number,
                        "samples": self.samples,
                        "metrics": slice_stats,
                    }
                    ps = getattr(self, "_platform_stream", None)
                    if ps is not None:
                        await _emit_platform_event(ps, "pass_completed", payload)
                    self._notify_observer("on_pass_completed", **payload)

                    # Sampling sanity check: if pass 2 reproduced pass 1's
                    # outputs byte-for-byte, the task is deterministic
                    # (temperature=0 or a provider cache) and samples>1 is
                    # measuring nothing.
                    if pass_number == 2 and not self._samples_warned:
                        identical = True
                        compared = 0
                        for entries_by_pass in result.passes.values():
                            first = entries_by_pass.get(1)
                            second = entries_by_pass.get(2)
                            if not first or not second:
                                continue
                            compared += 1
                            if str(first.get("output")) != str(second.get("output")):
                                identical = False
                                break
                        if compared > 0 and identical:
                            self._samples_warned = True
                            self._notify_observer(
                                "on_warning",
                                message=(
                                    "samples>1 but every pass-2 output is identical "
                                    "to pass 1 — is the task deterministic "
                                    "(temperature=0 or cached)? Repeat metrics "
                                    "won't measure variability."
                                ),
                            )
                except Exception:
                    pass

            async def _run_pass(pass_number: int) -> None:
                self._current_pass = pass_number
                entries = [
                    (idx, item_id, item, pass_number)
                    for idx, item_id, item in pending_entries
                    if (item_id, pass_number) not in completed_pairs
                ]
                for entry in entries:
                    await work_queue.put(entry)
                for _ in range(self.max_concurrency):
                    await work_queue.put(None)
                pass_workers = [
                    asyncio.create_task(_worker()) for _ in range(self.max_concurrency)
                ]
                worker_tasks.clear()
                worker_tasks.extend(pass_workers)
                await asyncio.gather(*pass_workers)

            try:
                for _pass_number in range(1, self.samples + 1):
                    await _run_pass(_pass_number)
                    if interrupted or self._should_stop_requested():
                        interrupted = True
                        break
                    await _emit_pass_completed(_pass_number)
            except (KeyboardInterrupt, asyncio.CancelledError) as exc:
                interrupted = True
                cancel_exc = exc
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
                except asyncio.CancelledError:
                    for task in worker_tasks:
                        task.cancel()
                    await asyncio.gather(*worker_tasks, return_exceptions=True)
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

        if self._platform_dataset_id:
            result.run_metadata["dataset_id"] = self._platform_dataset_id
        if self._platform_dataset_version_id:
            result.run_metadata[
                "dataset_version_id"
            ] = self._platform_dataset_version_id

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

        # Flush and shut down OTEL
        try:
            await asyncio.to_thread(self._otel.shutdown)
        finally:
            self._otel.reset_stream(otel_stream_token)

        # Finalize remote streaming after all spans have had a chance to emit.
        self._run_completed = False
        _final_status = "STOPPED" if interrupted else "COMPLETED"
        platform_stream = getattr(self, "_platform_stream", None)
        if platform_stream is not None:
            try:
                # Close the async queue after all late span/item emits have happened.
                await _close_platform_stream(platform_stream)
            except Exception:
                pass
            try:
                # A timed-out drain must not publish completion ahead of queued
                # item/span events. close() has already reported the backlog.
                if callable(getattr(type(platform_stream), "aflush", None)) and not await platform_stream.aflush(0):
                    raise RuntimeError("Platform upload still pending after close")
                # Send run_completed after the ordered queue has drained.
                final_run_metadata = dict(result.run_metadata or {})
                await _emit_platform_event(
                    platform_stream,
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
                    sync=True,
                )
                if callable(getattr(type(platform_stream), "aflush", None)) and not await platform_stream.aflush(0):
                    raise RuntimeError("Platform completion was not acknowledged")
                self._run_completed = True
            except Exception:
                pass

        # Auto-save if requested (message printed by save_* methods)
        if auto_save and not checkpoint_path:
            try:
                result.save(format=save_format, output_dir=self.config.output_dir)
            except Exception as e:
                console.print(
                    f"[yellow]⚠️  Warning: Failed to auto-save results: {e}[/yellow]"
                )

        # Shut down the thread pool so asyncio.run() doesn't hang waiting for idle threads.
        try:
            loop = asyncio.get_running_loop()
            executor = loop.get_default_executor()
            if executor is not None:
                executor.shutdown(wait=False)
        except Exception:
            pass

        if cancel_exc is not None:
            raise cancel_exc

        return result

    @staticmethod
    def run_parallel(
        runs: Sequence[Any],
        show_tui: bool = True,
        auto_save: bool = False,
        save_format: str = "csv",
        max_parallel_runs: Optional[int] = None,
        observer: Optional[EvaluationObserver] = None,
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
            observer: Optional lifecycle observer for aggregate and per-run events.

        Note:
            The Web UI is always available at the URL printed at startup.
        """
        if not runs:
            raise ValueError("runs must contain at least one configuration")

        from .multi_runner import MultiModelRunner

        # Delegate to MultiModelRunner
        runner = MultiModelRunner.from_runs(runs, console=console, observer=observer)

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
            with _graceful_interrupt_signals():
                results = asyncio.run(
                    runner.arun(
                        show_tui=show_tui,
                        auto_save=auto_save,
                        save_format=save_format,
                        max_parallel_runs=max_parallel_runs,
                    )
                )
        except KeyboardInterrupt:
            incomplete = [
                ev
                for ev in getattr(runner, "_active_evaluators", [])
                if not getattr(ev, "_run_completed", False)
            ]
            if incomplete:
                print(
                    f"[QYM-SDK] Interrupted — sending STOPPED for {len(incomplete)} incomplete run(s)",
                    flush=True,
                )
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
                console.print(
                    f"[green]Saved {spec.run_name} results to {saved_path}[/green]"
                )

        return results

    def _single_dataset_input_name(self) -> Optional[str]:
        """Return the declared input name for a single-column dataset."""
        input_cols = getattr(self.dataset, "input_cols", None)
        if isinstance(input_cols, str):
            return input_cols or None
        if (
            isinstance(input_cols, (list, tuple))
            and len(input_cols) == 1
            and isinstance(input_cols[0], str)
        ):
            return input_cols[0] or None
        return None

    def _prepare_metric_input(self, input_data: Any) -> Any:
        """Apply configured input names at the metric boundary.

        Without an input mapping, preserve the dataset value exactly for legacy
        metrics. When a configured mapping renames at least one field, expose
        the renamed shape through the metric's ``input_data`` argument.
        """
        if not self.input_mapping:
            return input_data

        if isinstance(input_data, dict):
            mapped: Dict[str, Any] = {}
            changed = False
            for input_name, value in input_data.items():
                mapped_name = self.input_mapping.get(input_name, input_name)
                if mapped_name in mapped:
                    raise ValueError(
                        "Multiple input columns map to the same task parameter "
                        f"'{mapped_name}'."
                    )
                mapped[mapped_name] = value
                changed = changed or mapped_name != input_name
            return mapped if changed else input_data

        input_name = self._single_dataset_input_name()
        if input_name:
            mapped_name = self.input_mapping.get(input_name)
            if mapped_name and mapped_name != input_name:
                return {mapped_name: input_data}
            return input_data

        # A one-entry mapping is unambiguous even for dataset implementations
        # that do not expose their single input column name.
        if len(self.input_mapping) == 1:
            input_name, mapped_name = next(iter(self.input_mapping.items()))
            if mapped_name != input_name:
                return {mapped_name: input_data}

        return input_data

    def _metric_input_aliases(
        self, input_data: Any, mapped_input_data: Any
    ) -> Dict[str, Any]:
        """Expose original and mapped input names as metric arguments."""
        aliases: Dict[str, Any] = {}
        if isinstance(input_data, dict):
            for key, value in input_data.items():
                if not isinstance(key, str):
                    continue
                aliases.setdefault(key, value)

            # Apply the mapped shape after the original shape so an explicit
            # mapping has deterministic precedence if names overlap.
            if isinstance(mapped_input_data, dict):
                for key, value in mapped_input_data.items():
                    if isinstance(key, str):
                        aliases[key] = value
            return aliases

        input_name = self._single_dataset_input_name()
        if input_name:
            resolved_name = self.input_mapping.get(input_name, input_name)
            aliases[input_name] = input_data
            aliases[resolved_name] = input_data
            return aliases

        # An explicit one-entry mapping supplies enough information to expose
        # a scalar by name even when the dataset has no schema metadata.
        if len(self.input_mapping) == 1:
            input_name, resolved_name = next(iter(self.input_mapping.items()))
            aliases[input_name] = input_data
            aliases[resolved_name] = input_data

        return aliases

    def _resolve_metric_arguments(
        self,
        metric: Callable,
        output: Any,
        expected: Any,
        input_data: Any = None,
        task_metadata: Optional[Dict[str, Any]] = None,
        item_metadata: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Tuple[Any, ...], Dict[str, Any]]:
        """Resolve metric arguments with backward-compatible positional rules."""
        sig = inspect.signature(metric)
        params = list(sig.parameters.values())
        has_var_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)
        mapped_input_data = self._prepare_metric_input(input_data)

        named_values = {
            "output": output,
            "expected": expected,
            "input_data": mapped_input_data,
            "task_metadata": task_metadata or {},
            "metadata": item_metadata or {},
            "item_metadata": item_metadata or {},
        }

        # Individual parameters may use either original dataset names or names
        # produced by input_mapping. Reserved metric parameters win collisions.
        for key, value in self._metric_input_aliases(
            input_data, mapped_input_data
        ).items():
            named_values.setdefault(key, value)

        concrete_params = [
            p
            for p in params
            if p.kind
            not in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            )
        ]

        can_use_keywords = has_var_kwargs or all(
            p.kind != inspect.Parameter.POSITIONAL_ONLY and p.name in named_values
            for p in concrete_params
        )

        if can_use_keywords:
            kwargs = (
                dict(named_values)
                if has_var_kwargs
                else {p.name: named_values[p.name] for p in concrete_params}
            )
            return (), kwargs

        positional = [
            output,
            expected,
            mapped_input_data,
            item_metadata or {},
        ]
        return tuple(positional[: len(concrete_params)]), {}

    async def _compute_metric(
        self,
        metric: Callable,
        output: Any,
        expected: Any,
        input_data: Any = None,
        task_metadata: Optional[Dict[str, Any]] = None,
        item_metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Compute a metric, handling both sync and async functions."""
        args, kwargs = self._resolve_metric_arguments(
            metric, output, expected, input_data, task_metadata, item_metadata
        )

        # Call metric (async or sync)
        if inspect.iscoroutinefunction(metric):
            result = await metric(*args, **kwargs)
        else:
            # Run sync metrics in the thread pool, same as sync tasks. Calling
            # them inline blocks the event loop, which freezes all in-flight
            # items and inflates their measured task latency by the metric's
            # runtime.
            ctx = contextvars.copy_context()
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, lambda: ctx.run(metric, *args, **kwargs)
            )
        return result

    def _get_score_type(self, score: Any) -> str:
        """Determine score data type."""
        if isinstance(score, bool):
            return "BOOLEAN"
        elif isinstance(score, (int, float)):
            return "NUMERIC"
        else:
            return "CATEGORICAL"

    # Frontend concerns moved to qym.utils.frontend

    def _run_multi_model(
        self,
        show_tui: bool,
        auto_save: bool,
        save_format: str,
        max_parallel_runs: Optional[int] = None,
    ):
        """Kick off multiple model evaluations via the MultiModelRunner helper."""
        runs = []
        base_name = (self.config.run_name or "").strip() or self._task_name

        # Create base config dict from Pydantic model
        base_config_dict = self.config.model_dump(
            exclude={"models", "model", "run_name", "run_metadata"}
        )

        # Iterate over both stripped and full model names
        for idx, (model_name, model_name_full) in enumerate(
            zip(self.models, self.models_full), start=1
        ):
            run_config = copy.deepcopy(base_config_dict)
            run_config[
                "model"
            ] = model_name  # #17: Stripped name for consistent platform display
            run_config[
                "model_full"
            ] = model_name_full  # Full name preserved for user's task

            run_metadata = dict(self.run_metadata or {})
            run_metadata["model"] = model_name  # Stripped name for display/metadata
            run_config["run_metadata"] = run_metadata

            run_name, display_name = self.build_run_identifiers(
                base_name, model_name
            )  # Stripped for run ID
            run_config["run_name"] = run_name

            runs.append(
                {
                    "name": run_name,
                    "display_name": display_name,
                    "task": self.task,
                    "dataset": self.dataset,
                    "metrics": self._raw_metrics,
                    "config": run_config,
                    "metadata": {"model": model_name},  # Stripped for display
                    "input_mapping": dict(self.input_mapping),
                }
            )

        return self.run_parallel(
            runs,
            show_tui=show_tui,
            auto_save=auto_save,
            save_format=save_format,
            max_parallel_runs=max_parallel_runs,
            observer=self.observer,
        )

    # ------------------------------------------------------------------
    # _evaluate_item: decomposed into focused sub-methods
    # ------------------------------------------------------------------

    def _create_item_spans(
        self, index: int, item: Any, attempt_number: int
    ) -> ItemSpans:
        """Create OTEL spans with OpenInference attributes for an eval item."""
        spans = ItemSpans()
        item_metadata = getattr(item, "metadata", {})

        if not self._otel.enabled:
            return spans

        from opentelemetry import trace as otel_trace

        spans.tracer = otel_trace.get_tracer("qym")

        # Root eval span
        spans.eval_span, spans.eval_token = ItemSpans._start_span(
            spans.tracer,
            name=f"eval-{self.run_name}-item-{index}-attempt-{attempt_number}",
            kind="CHAIN",
            input_value=item.input,
            metadata={
                **self.run_metadata,
                "item_index": index,
                "attempt_number": attempt_number,
                "dataset_item_id": getattr(item, "id", None),
                "run_name": self.run_name,
                "item_metadata": item_metadata,
            },
        )

        # Extract trace_id from the OTEL span
        _ctx = spans.eval_span.get_span_context()
        if _ctx.is_valid:
            spans.trace_id = format(_ctx.trace_id, "032x")

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

    async def _emit_item_started(self, index: int, item: Any):
        """Emit item_started to platform stream and notify observer."""
        try:
            ps = getattr(self, "_platform_stream", None)
            if ps is not None:
                item_id = getattr(item, "id", None) or f"item_{index}"
                await _emit_platform_event(
                    ps,
                    "item_started",
                    {
                        "item_id": str(item_id),
                        "index": int(index),
                        "pass_number": self._current_pass,
                        "input": item.input,
                        "expected": getattr(item, "expected_output", None),
                        "item_metadata": getattr(item, "metadata", {}) or {},
                        "dataset_item_pk": getattr(item, "dataset_item_pk", None),
                    },
                )
        except Exception:
            pass
        self._notify_observer(
            "on_item_start",
            item_index=index,
            payload={
                "input": item.input,
                "expected": getattr(item, "expected_output", None),
            },
        )

    async def _emit_item_attempt_started(
        self,
        index: int,
        item: Any,
        attempt_number: int,
        spans: ItemSpans,
        task_started_at_ms: Optional[int],
    ) -> None:
        """Emit the active attempt trace before task execution begins."""
        try:
            ps = getattr(self, "_platform_stream", None)
            if ps is None:
                return
            item_id = getattr(item, "id", None) or f"item_{index}"
            await _emit_platform_event(
                ps,
                "item_attempt_started",
                {
                    "item_id": str(item_id),
                    "index": int(index),
                    "pass_number": self._current_pass,
                    "attempt_number": int(attempt_number),
                    "trace_id": spans.trace_id,
                    "trace_url": spans.trace_url,
                    "task_started_at_ms": task_started_at_ms,
                },
            )
        except Exception:
            pass

    @staticmethod
    def _prepare_task_input(input_data: Any) -> Any:
        """Preserve mapping inputs so adapters can inject multiple columns by name."""
        return dict(input_data) if isinstance(input_data, dict) else input_data

    async def _run_single_task_attempt(
        self, index: int, item: Any, attempt_number: int
    ) -> TaskAttemptResult:
        """Execute a single task attempt with its own trace."""
        spans = self._create_item_spans(index, item, attempt_number)
        task_input = self._prepare_task_input(item.input)
        # Create a NullTrace for adapter compatibility
        adapter_trace = NullTrace(
            name=f"eval-{self.run_name}-item-{index}-attempt-{attempt_number}",
            input=task_input,
        )
        adapter_trace.trace_id = spans.trace_id

        task_started_at_ms = int(time.time() * 1000)
        await self._emit_item_attempt_started(
            index, item, attempt_number, spans, task_started_at_ms
        )
        attempt_start_time = time.monotonic()
        forced_model_token = None
        retryable = True
        try:
            if self.config.force_model_override and self.model_name_full:
                forced_model_token = self._otel.bind_forced_model(self.model_name_full)

            async def _task_call():
                try:
                    return await self.task_adapter.arun(
                        task_input,
                        adapter_trace,
                        model_name=self.model_name_full,
                    )
                except asyncio.TimeoutError as exc:
                    raise TaskExecutionTimeoutError(
                        str(exc) or "task raised TimeoutError"
                    ) from exc

            coro = _task_call()
            if self.timeout is not None:
                raw_output = await asyncio.wait_for(coro, timeout=self.timeout)
            else:
                raw_output = await coro
            output, task_metadata, metric_output = _normalize_task_output(raw_output)
            return TaskAttemptResult(
                attempt_number=attempt_number,
                spans=spans,
                task_started_at_ms=task_started_at_ms,
                latency_s=time.monotonic() - attempt_start_time,
                output=output,
                metric_output=metric_output,
                task_metadata=task_metadata,
            )
        except asyncio.TimeoutError:
            error = f"Task timed out after {self.timeout}s (attempt {attempt_number}/{1 + self.max_retries})"
            logger.warning(f"Item {index}: {error}")
        except TaskExecutionTimeoutError as e:
            error = f"{type(e).__name__}: {e} (attempt {attempt_number}/{1 + self.max_retries})"
            logger.warning(f"Item {index}: {error}")
        except InvalidTaskOutputError as e:
            error = f"{type(e).__name__}: {e}"
            logger.warning(f"Item {index}: {error}")
            retryable = False
        except Exception as e:
            error = f"{type(e).__name__}: {e} (attempt {attempt_number}/{1 + self.max_retries})"
            logger.warning(f"Item {index}: {error}")
            retryable = True
        finally:
            self._otel.reset_forced_model(forced_model_token)

        try:
            spans.end_all(error=error)
        except Exception:
            pass

        return TaskAttemptResult(
            attempt_number=attempt_number,
            spans=spans,
            task_started_at_ms=task_started_at_ms,
            latency_s=time.monotonic() - attempt_start_time,
            error=error,
            retryable=retryable,
        )

    async def _execute_task(
        self, index: int, item: Any
    ) -> Tuple[Optional[TaskAttemptResult], List[TaskAttemptResult], int]:
        """Execute task retries and return the successful or last attempt."""
        attempts: List[TaskAttemptResult] = []

        for attempt_number in range(1, 2 + self.max_retries):
            attempt = await self._run_single_task_attempt(index, item, attempt_number)
            attempts.append(attempt)
            if attempt.success:
                return attempt, attempts, attempt_number - 1
            if not attempt.retryable:
                return None, attempts, attempt_number - 1

            is_terminal_attempt = attempt_number == 1 + self.max_retries
            if not is_terminal_attempt:
                await self._emit_item_attempt_finished(
                    index, item, attempt, is_last_attempt=False
                )
                base_delay = min(2 ** (attempt_number - 1), 30)
                jitter = random.uniform(0, base_delay * 0.5)
                await asyncio.sleep(base_delay + jitter)

        return None, attempts, len(attempts) - 1

    async def _compute_metrics(
        self,
        index: int,
        item: Any,
        output: Any,
        spans: ItemSpans,
        task_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Compute all metrics concurrently. Returns {metric_name: score_dict}."""
        expected_output = getattr(item, "expected_output", None)

        # Create metrics parent span
        if spans.tracer:
            spans.metrics_span, spans.metrics_token = ItemSpans._start_span(
                spans.tracer,
                name="eval_metrics",
                kind="EVALUATOR",
            )

        _metric_sem = asyncio.Semaphore(self.max_metric_concurrency)

        async def run_one(m_name: str, m_func: Callable) -> Tuple[str, Any]:
            async with _metric_sem:
                return await self._run_single_metric(
                    m_name,
                    m_func,
                    output,
                    expected_output,
                    index,
                    item,
                    spans,
                    task_metadata or {},
                )

        results = await asyncio.gather(
            *[run_one(m_name, m_func) for m_name, m_func in self.metrics.items()]
        )
        return dict(results)

    async def _run_single_metric(
        self,
        m_name: str,
        m_func: Callable,
        output: Any,
        expected: Any,
        index: int,
        item: Any,
        spans: ItemSpans,
        task_metadata: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, Any]:
        """Run a single metric, emit score event, and notify platform.

        Each metric attempt is wrapped in ``asyncio.wait_for`` with the
        ``self.metric_timeout`` budget (default 60s). Timeouts retry according to
        ``self.metric_max_retries``; an exhausted timeout follows the ordinary
        metric-error path (score 0 plus an error string).
        """
        metric_started_at_ms = int(time.time() * 1000)
        metric_started_monotonic = time.monotonic()
        metric_status = "completed"

        def _metric_observer_metadata() -> Dict[str, Any]:
            duration_s = max(time.monotonic() - metric_started_monotonic, 0.0)
            return {
                "input": item.input,
                "expected": getattr(item, "expected_output", None),
                "duration_ms": duration_s * 1000.0,
                "duration_seconds": duration_s,
                "started_at_ms": metric_started_at_ms,
                "completed_at_ms": metric_started_at_ms + int(duration_s * 1000.0),
                "status": metric_status,
            }

        # Inline helper that runs the actual metric compute (preserves the
        # existing probe logic for async metrics that accidentally block the loop).
        async def _run_metric_inner():
            if asyncio.iscoroutinefunction(m_func):
                func_id = id(m_func)
                should_probe = func_id not in Evaluator._metric_blocking_probed

                if not should_probe:
                    return await self._compute_metric(
                        m_func,
                        output,
                        expected,
                        item.input,
                        task_metadata,
                        getattr(item, "metadata", {}) or {},
                    )

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
                    return await self._compute_metric(
                        m_func,
                        output,
                        expected,
                        item.input,
                        task_metadata,
                        getattr(item, "metadata", {}) or {},
                    )
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
                            _fname = getattr(m_func, "__name__", m_name)
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
                return await asyncio.to_thread(
                    self._compute_metric_sync,
                    m_func,
                    output,
                    expected,
                    item.input,
                    task_metadata,
                    getattr(item, "metadata", {}) or {},
                )

        try:
            # Apply wall-clock cap on the metric call itself. A timeout
            # retries up to metric_max_retries; when the last attempt also
            # times out, the TimeoutError falls through to the ordinary
            # metric-error handler below (score 0 + error traceback), so the
            # UI surfaces it like any other metric error.
            usage_scope_token = None
            if self.metric_timeout is not None:
                try:
                    usage_scope_token = self._otel.bind_usage_scope("metric")
                    attempts = self.metric_max_retries + 1
                    for attempt in range(1, attempts + 1):
                        try:
                            score = await asyncio.wait_for(
                                _run_metric_inner(), timeout=self.metric_timeout
                            )
                            break
                        except asyncio.TimeoutError:
                            if attempt >= attempts:
                                metric_status = "timeout"
                                raise
                            logger.warning(
                                "Metric %s timed out after %.1fs (attempt %d/%d) — retrying",
                                m_name,
                                self.metric_timeout,
                                attempt,
                                attempts,
                            )
                finally:
                    self._otel.reset_usage_scope(usage_scope_token)
            else:
                try:
                    usage_scope_token = self._otel.bind_usage_scope("metric")
                    score = await _run_metric_inner()
                finally:
                    self._otel.reset_usage_scope(usage_scope_token)

            # Wrap in MetricResult
            from qym.metrics.result import MetricResult

            raw_score_value = score.score if isinstance(score, MetricResult) else score
            if isinstance(score, dict):
                raw_score_value = score.get("score")
            # Internal harnesses and older integrations may replace ``metrics``
            # directly without rebuilding ``metric_specs``. Preserve the
            # legacy score path instead of turning an otherwise valid metric
            # result into a KeyError.
            spec = getattr(self, "metric_specs", {}).get(m_name)
            if spec is None:
                spec = MetricSpec(score_type="legacy")
            if metric_status not in {"timeout", "error"}:
                validated_score = spec.validate_score(raw_score_value)
            else:
                validated_score = MetricResult.from_raw(score).score
            result = MetricResult.from_raw(score)
            result.score = validated_score
            main_val = result.score

            # Add score as OTEL event on eval span (provider-agnostic)
            spans.add_score_event(m_name, main_val, result.label, result.explanation)

            # Platform: metric scored
            try:
                ps = getattr(self, "_platform_stream", None)
                if ps is not None:
                    item_id = getattr(item, "id", None) or f"item_{index}"
                    await _emit_platform_event(
                        ps,
                        "metric_scored",
                        {
                            "item_id": str(item_id),
                            "pass_number": self._current_pass,
                            "metric_name": str(m_name),
                            "score_numeric": result.score,
                            "score_value": raw_score_value,
                            "score_raw": result.to_legacy_dict(),
                            "meta": result.metadata or {},
                            "label": result.label,
                            "explanation": result.explanation,
                        },
                    )
            except Exception:
                pass

            self._notify_observer(
                "on_metric_result",
                item_index=index,
                metric_name=m_name,
                score=score,
                metadata=_metric_observer_metadata(),
            )
            return m_name, score
        except Exception as e:
            if metric_status != "timeout":
                metric_status = "error"
            if isinstance(e, JudgeInputError):
                console.print(e.rich_message())
            elif isinstance(e, asyncio.TimeoutError):
                logger.error(
                    "Metric %s timed out after %.1fs on all %d attempts",
                    m_name,
                    self.metric_timeout,
                    self.metric_max_retries + 1,
                )
            else:
                logger.error(f"Metric {m_name} failed: {e}")
            error_text = (
                f"metric timeout after {self.metric_timeout}s "
                f"({self.metric_max_retries + 1} attempts)"
                if isinstance(e, asyncio.TimeoutError)
                else traceback.format_exc()
            )
            score = {"score": 0, "error": error_text}
            self._notify_observer(
                "on_metric_result",
                item_index=index,
                metric_name=m_name,
                score=score,
                metadata=_metric_observer_metadata(),
            )
            return m_name, score

    def _update_tracker(
        self,
        index: int,
        item: Any,
        output: Any,
        scores: Dict,
        task_time: float,
        retry_count: int,
        spans: ItemSpans,
        tracker: "ProgressObserver",
    ):
        """Update the progress tracker with results."""
        tracker.update_trace_info(index, spans.trace_id, spans.trace_url)
        tracker.update_output(index, output)
        if retry_count > 0:
            tracker.item_statuses[index]["retry_count"] = retry_count

        for m_name, score in scores.items():
            if score is not None:
                main_val = score
                meta_map = {}
                if isinstance(score, dict):
                    main_val = score.get("score", None)
                    md = score.get("metadata", {})
                    if isinstance(md, dict):
                        for k, v in md.items():
                            if isinstance(v, dict):
                                for k2, v2 in v.items():
                                    meta_map[f"{k}_{k2}"] = v2
                            else:
                                meta_map[str(k)] = v
                tracker.update_metric(index, m_name, main_val, meta_map)
            else:
                tracker.set_metric_error(index, m_name)

        scores = {k: v for k, v in scores.items() if v is not None}
        tracker.complete_item(index, elapsed_time=task_time)

    async def _emit_item_attempt_finished(
        self,
        index: int,
        item: Any,
        attempt: TaskAttemptResult,
        *,
        is_last_attempt: bool,
    ) -> None:
        """Emit an individual task attempt outcome to the platform."""
        try:
            ps = getattr(self, "_platform_stream", None)
            if ps is None:
                return
            item_id = getattr(item, "id", None) or f"item_{index}"
            await _emit_platform_event(
                ps,
                "item_attempt_finished",
                {
                    "item_id": str(item_id),
                    "index": int(index),
                    "pass_number": self._current_pass,
                    "attempt_number": attempt.attempt_number,
                    "status": attempt.status,
                    "trace_id": attempt.spans.trace_id,
                    "trace_url": attempt.spans.trace_url,
                    "latency_ms": attempt.latency_ms,
                    "task_started_at_ms": attempt.task_started_at_ms,
                    # Carry the successful task output on the durable attempt
                    # event itself.  Repeat-run UIs read per-pass outputs from
                    # RunItemAttempt, so they must not depend on a later
                    # item_completed event arriving in the same request.
                    "output": attempt.output if attempt.success else None,
                    "error": attempt.error,
                    "is_last_attempt": is_last_attempt,
                },
            )
        except Exception:
            pass

    async def _emit_item_completed(
        self,
        index: int,
        item: Any,
        output: Any,
        task_metadata: Dict[str, Any],
        scores: Dict[str, Any],
        task_time: float,
        item_time: float,
        spans: ItemSpans,
        retry_count: int,
        task_started_at_ms: Optional[int],
        item_started_at_ms: int,
    ):
        """Emit item_completed to platform stream and notify observer."""
        item_completed_at_ms = int(time.time() * 1000)
        task_completed_at_ms = (
            task_started_at_ms + int(task_time * 1000.0)
            if task_started_at_ms is not None
            else None
        )
        try:
            ps = getattr(self, "_platform_stream", None)
            if ps is not None:
                item_id = getattr(item, "id", None) or f"item_{index}"
                await _emit_platform_event(
                    ps,
                    "item_completed",
                    {
                        "item_id": str(item_id),
                        "index": int(index),
                        "pass_number": self._current_pass,
                        "is_final_pass": self._current_pass >= self.samples,
                        "output": output,
                        "item_metadata": _item_metadata_with_task_metadata(
                            getattr(item, "metadata", {}) or {}, task_metadata
                        ),
                        "task_metadata": task_metadata,
                        "latency_ms": float(task_time * 1000.0),
                        "total_latency_ms": float(item_time * 1000.0),
                        "trace_id": spans.trace_id,
                        "trace_url": spans.trace_url,
                        "task_started_at_ms": task_started_at_ms,
                        "task_completed_at_ms": task_completed_at_ms,
                        "item_started_at_ms": item_started_at_ms,
                        "item_completed_at_ms": item_completed_at_ms,
                        "retry_count": retry_count,
                    },
                )
        except Exception:
            pass
        self._notify_observer(
            "on_item_complete",
            item_index=index,
            result={
                "output": output,
                "task_metadata": task_metadata,
                "item_metadata": _item_metadata_with_task_metadata(
                    getattr(item, "metadata", {}) or {}, task_metadata
                ),
                "scores": scores,
                "task_time": task_time,
                "task_time_ms": float(task_time * 1000.0),
                "time": task_time,
                "latency_ms": float(task_time * 1000.0),
                "item_time": item_time,
                "item_time_ms": float(item_time * 1000.0),
                "total_time": item_time,
                "total_time_ms": float(item_time * 1000.0),
                "task_started_at_ms": task_started_at_ms,
                "task_completed_at_ms": task_completed_at_ms,
                "item_started_at_ms": item_started_at_ms,
                "item_completed_at_ms": item_completed_at_ms,
                "trace_id": spans.trace_id,
                "trace_url": spans.trace_url,
                "retry_count": retry_count,
            },
        )

    async def _handle_item_error(
        self,
        index: int,
        item: Any,
        error: Exception,
        spans: ItemSpans,
        tracker: "ProgressObserver",
        *,
        attempt: Optional[TaskAttemptResult] = None,
        retry_count: int = 0,
    ):
        """Handle item evaluation error: emit failure, then clean up."""
        error_str = attempt.error if attempt and attempt.error else str(error)
        item_id = getattr(item, "id", None) or f"item_{index}"
        trace_id = attempt.spans.trace_id if attempt else spans.trace_id
        trace_url = attempt.spans.trace_url if attempt else spans.trace_url
        latency_ms = attempt.latency_ms if attempt else None
        task_started_at_ms = attempt.task_started_at_ms if attempt else None
        # 1. Emit to platform FIRST (most important — prevents ghost items)
        try:
            ps = getattr(self, "_platform_stream", None)
            if ps is not None:
                await _emit_platform_event(
                    ps,
                    "item_failed",
                    {
                        "item_id": str(item_id),
                        "index": int(index),
                        "pass_number": self._current_pass,
                        "error": error_str,
                        "latency_ms": latency_ms,
                        "trace_id": trace_id,
                        "trace_url": trace_url,
                        "task_started_at_ms": task_started_at_ms,
                        "retry_count": retry_count,
                    },
                )
        except Exception:
            pass
        if attempt is not None:
            await self._emit_item_attempt_finished(index, item, attempt, is_last_attempt=True)
        # 2. Update local tracker
        try:
            tracker.update_trace_info(index, trace_id, trace_url)
            tracker.fail_item(
                index, error_str, elapsed_time=attempt.latency_s if attempt else None
            )
            if retry_count > 0:
                tracker.item_statuses[index]["retry_count"] = retry_count
        except Exception:
            pass
        try:
            self._notify_observer("on_item_error", item_index=index, error=error_str)
        except Exception:
            pass
        # 3. Clean up spans (nice-to-have, can crash)
        try:
            spans.end_all(error=error)
        except Exception:
            pass

    async def _finalize_item(
        self,
        index: int,
        item: Any,
        success_attempt: "TaskAttemptResult",
        scores: Dict[str, Any],
        retry_count: int,
        active_spans: ItemSpans,
        tracker: "ProgressObserver",
        item_started_at_ms: int,
        item_started_monotonic: float,
    ) -> None:
        """Run the durable emit phase of a successful item atomically.

        Called under ``asyncio.shield(...)`` from ``_evaluate_item``. Once
        ``_compute_metrics`` returns, the item is functionally done and must
        never be marked as ``item_failed`` even if an external ``CancelledError``
        arrives mid-emit. The shield lets the background Task complete its
        emits even after the caller has been cancelled.

        IMPORTANT: do NOT perform OpenTelemetry span lifecycle operations here.
        ``asyncio.shield`` schedules the inner coroutine as a new Task, which
        inherits a COPY of the parent's ``contextvars.Context``. Any OTel token
        attached in the parent task cannot be ``detach()``-ed here — you'll get
        ``ValueError: Token was created in a different Context``. The caller in
        ``_evaluate_item`` runs ``end_metrics`` / ``end_eval`` in the outer Task
        before calling us.
        """
        # Update local tracker (in-memory progress)
        self._update_tracker(
            index,
            item,
            success_attempt.output,
            scores,
            success_attempt.latency_s,
            retry_count,
            active_spans,
            tracker,
        )
        # Persist the final attempt before item_completed.  Older platforms
        # attach a repeat pass's output to the already-existing final-attempt
        # row when they process item_completed.
        await self._emit_item_attempt_finished(
            index, item, success_attempt, is_last_attempt=True
        )
        # Emit item_completed to the platform stream (fire-and-forget queue put)
        await self._emit_item_completed(
            index,
            item,
            success_attempt.output,
            success_attempt.task_metadata,
            scores,
            success_attempt.latency_s,
            max(time.monotonic() - item_started_monotonic, 0.0),
            active_spans,
            retry_count,
            success_attempt.task_started_at_ms,
            item_started_at_ms,
        )

    async def _evaluate_item(self, index: int, item: Any, tracker: "ProgressObserver"):
        """Evaluate a single item: create spans, run task, compute metrics, emit results."""
        _item_finished = False
        active_spans = ItemSpans()
        active_attempt: Optional[TaskAttemptResult] = None
        active_retry_count = 0
        item_started_at_ms = int(time.time() * 1000)
        item_started_monotonic = time.monotonic()

        try:
            tracker.start_item(index)
            await self._emit_item_started(index, item)

            success_attempt, attempts, retry_count = await self._execute_task(
                index, item
            )
            active_retry_count = retry_count
            last_attempt = attempts[-1] if attempts else None
            if success_attempt is None or last_attempt is None:
                error = RuntimeError(
                    last_attempt.error
                    if last_attempt and last_attempt.error
                    else "Task failed"
                )
                await self._handle_item_error(
                    index,
                    item,
                    error,
                    last_attempt.spans if last_attempt else active_spans,
                    tracker,
                    attempt=last_attempt,
                    retry_count=retry_count,
                )
                _item_finished = True
                return {
                    "_error": str(error),
                    "_trace_id": last_attempt.spans.trace_id if last_attempt else None,
                    "time": last_attempt.latency_s if last_attempt else None,
                    "task_started_at_ms": last_attempt.task_started_at_ms
                    if last_attempt
                    else None,
                    "pass_number": self._current_pass,
                }

            active_spans = success_attempt.spans
            active_attempt = success_attempt
            try:
                active_spans.end_task(output=success_attempt.output)
            except Exception:
                pass
            scores = await self._compute_metrics(
                index,
                item,
                success_attempt.metric_output,
                active_spans,
                success_attempt.task_metadata,
            )

            # Mark the item as finished IMMEDIATELY after metrics compute. Once we
            # have scores, the work is functionally done — any subsequent emit
            # cancellation must not downgrade the item's status in the finally
            # block below.
            _item_finished = True

            # End OTel spans HERE, in the outer Task. These calls detach tokens
            # that were attached by _compute_metrics (line 1781) in this same
            # Task — they MUST NOT be moved inside asyncio.shield, because the
            # shielded task runs with a copied contextvars.Context and OTel
            # token detach across Task boundaries raises ValueError.
            try:
                active_spans.end_metrics(scores=scores)
            except Exception:
                pass
            try:
                active_spans.end_eval(output=success_attempt.output)
            except Exception:
                pass

            # Now the durable emit phase (platform stream + tracker) runs under
            # asyncio.shield so it completes
            # atomically even if the caller is cancelled mid-flight.
            await asyncio.shield(
                self._finalize_item(
                    index,
                    item,
                    success_attempt,
                    scores,
                    retry_count,
                    active_spans,
                    tracker,
                    item_started_at_ms,
                    item_started_monotonic,
                )
            )

            return {
                "input": item.input,
                "output": success_attempt.output,
                "task_metadata": success_attempt.task_metadata,
                "item_metadata": _item_metadata_with_task_metadata(
                    getattr(item, "metadata", {}) or {},
                    success_attempt.task_metadata,
                ),
                "expected": getattr(item, "expected_output", None),
                "scores": {k: v for k, v in scores.items() if v is not None},
                "trace_id": active_spans.trace_id,
                "trace_url": active_spans.trace_url,
                "time": success_attempt.latency_s,
                "task_started_at_ms": success_attempt.task_started_at_ms,
                "retry_count": retry_count,
                "pass_number": self._current_pass,
                "success": True,
            }

        except Exception as e:
            await self._handle_item_error(
                index,
                item,
                e,
                active_spans,
                tracker,
                attempt=active_attempt,
                retry_count=active_retry_count,
            )
            _item_finished = True
            return {
                "_error": str(e),
                "_trace_id": active_spans.trace_id,
                "time": active_attempt.latency_s if active_attempt else None,
                "task_started_at_ms": active_attempt.task_started_at_ms
                if active_attempt
                else None,
            }
        finally:
            # Guard against CancelledError / KeyboardInterrupt leaving items
            # in limbo with no output, no error, and no trace in the platform.
            if not _item_finished:
                # Emit FIRST — most important
                try:
                    ps = getattr(self, "_platform_stream", None)
                    if ps is not None:
                        item_id = getattr(item, "id", None) or f"item_{index}"
                        await _emit_platform_event(
                            ps,
                            "item_failed",
                            {
                                "item_id": str(item_id),
                                "index": int(index),
                                "pass_number": self._current_pass,
                                "error": "Cancelled",
                                "latency_ms": None,
                                "trace_id": active_spans.trace_id,
                                "trace_url": active_spans.trace_url,
                                "task_started_at_ms": None,
                                "retry_count": 0,
                            },
                        )
                except Exception:
                    pass
                try:
                    tracker.fail_item(index, "Cancelled", elapsed_time=None)
                except Exception:
                    pass
                try:
                    active_spans.end_all(error="Cancelled")
                except Exception:
                    pass

    def _compute_metric_sync(
        self,
        metric_func: Callable,
        output: Any,
        expected: Any,
        input_data: Any,
        task_metadata: Optional[Dict[str, Any]] = None,
        item_metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Synchronous version of metric computation for thread pool execution."""
        try:
            args, kwargs = self._resolve_metric_arguments(
                metric_func,
                output,
                expected,
                input_data,
                task_metadata,
                item_metadata,
            )
            return metric_func(*args, **kwargs)
        except Exception as e:
            error_tb = traceback.format_exc()
            logger.error(
                f"Metric {getattr(metric_func, '__name__', 'unknown')} failed: {error_tb}"
            )
            return {"score": 0, "error": str(e), "traceback": error_tb}


def _announce_saved_results(
    results: Sequence[EvaluationResult], *, include_run_name: bool
) -> None:
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
