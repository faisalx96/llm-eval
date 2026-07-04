from __future__ import annotations

import importlib.util
import os
import sys
import threading
import logging
import re
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from qym_platform.settings import PlatformSettings, ProductEvalSettings


logger = logging.getLogger(__name__)

MAX_EFFECTIVE_CONCURRENCY = 20


class ProductEvalError(ValueError):
    """User-correctable product eval request error."""


class ProductEvalQueueFull(RuntimeError):
    """Raised when no product eval worker slot is available."""


TERMINAL_JOB_STATUSES = {"COMPLETED", "FAILED", "STOPPED"}


@dataclass(frozen=True)
class ProductEvalRuntimeInputs:
    insightor_url: Optional[str] = None
    refresh_token: Optional[str] = None
    agent_version: Optional[str] = None
    image_version: Optional[str] = None
    kb_version: Optional[str] = None


@dataclass(frozen=True)
class ProductEvalPreset:
    name: str
    script_path: Path
    task_name: str
    metric_name: str
    dataset_env: Optional[str]
    model_env: Optional[str]
    default_dataset_name: Optional[str] = None
    default_config: Dict[str, Any] = field(default_factory=dict)
    requires_dataset_name: bool = False
    run_count: int = 1
    max_parallel_runs: Optional[int] = None


@dataclass
class ProductEvalJob:
    job_id: str
    preset: str
    owner_user_id: Optional[str] = None
    project_id: Optional[str] = None
    status: str = "QUEUED"
    run_id: Optional[str] = None
    runs: List[Dict[str, Any]] = field(default_factory=list)
    expected_runs: int = 1
    group_analysis: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _run_ready: threading.Event = field(default_factory=threading.Event, repr=False)
    _stop_requested: threading.Event = field(default_factory=threading.Event, repr=False)
    _future: Optional[Future] = field(default=None, repr=False)

    @property
    def eval_id(self) -> str:
        return self.job_id

    def mark(
        self,
        *,
        status: Optional[str] = None,
        run_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        with self._lock:
            if status is not None:
                self.status = status
            if run_id:
                self.run_id = run_id
                self._run_ready.set()
            if error is not None:
                self.error = error
            self.updated_at = datetime.utcnow()

    def set_group_analysis(self, group_analysis: Dict[str, Any]) -> None:
        with self._lock:
            self.group_analysis = dict(group_analysis)
            self.updated_at = datetime.utcnow()

    def initialize_planned_runs(self) -> None:
        with self._lock:
            existing_attempts = {
                int(row["attempt"]) for row in self.runs if row.get("attempt")
            }
            for attempt in range(1, self.expected_runs + 1):
                if attempt not in existing_attempts:
                    self.runs.append(
                        {
                            "attempt": attempt,
                            "sdk_run_id": None,
                            "qym_run_id": None,
                            "status": "PENDING",
                        }
                    )
            self.runs.sort(key=lambda row: int(row.get("attempt") or 0))
            self.updated_at = datetime.utcnow()

    def record_run_matrix(self, runs: List[Dict[str, Any]]) -> None:
        with self._lock:
            current_by_sdk_id = {
                row.get("sdk_run_id"): row for row in self.runs if row.get("sdk_run_id")
            }
            current_by_attempt = {
                row.get("attempt"): row for row in self.runs if row.get("attempt")
            }
            next_by_attempt = dict(current_by_attempt)
            for index, row in enumerate(runs, start=1):
                sdk_run_id = str(row.get("run_id") or "")
                attempt = int(row.get("product_eval_attempt") or index)
                existing = current_by_sdk_id.get(sdk_run_id) or current_by_attempt.get(
                    attempt, {}
                )
                next_by_attempt[attempt] = {
                    "attempt": attempt,
                    "sdk_run_id": sdk_run_id,
                    "qym_run_id": existing.get("qym_run_id")
                    or row.get("platform_run_id"),
                    "status": existing.get("status") or "STARTING",
                }
            self.runs = [
                dict(next_by_attempt[attempt]) for attempt in sorted(next_by_attempt)
            ]
            self.expected_runs = max(self.expected_runs, len(self.runs))
            self.updated_at = datetime.utcnow()

    def mark_run(
        self,
        *,
        sdk_run_id: str,
        status: Optional[str] = None,
        qym_run_id: Optional[str] = None,
    ) -> None:
        with self._lock:
            target: Optional[Dict[str, Any]] = None
            for row in self.runs:
                if row.get("sdk_run_id") == sdk_run_id:
                    target = row
                    break
            if target is None:
                target = {
                    "attempt": len(self.runs) + 1,
                    "sdk_run_id": sdk_run_id,
                    "qym_run_id": None,
                    "status": "STARTING",
                }
                self.runs.append(target)
            if status:
                target["status"] = status
            if qym_run_id:
                target["qym_run_id"] = qym_run_id
                if not self.run_id:
                    self.run_id = qym_run_id
                self._run_ready.set()
            self.updated_at = datetime.utcnow()

    def wait_for_run(self, timeout: float) -> bool:
        return self._run_ready.wait(timeout=timeout)

    def stop_requested(self) -> bool:
        return self._stop_requested.is_set()

    def request_stop(self) -> bool:
        self._stop_requested.set()
        cancelled_before_start = False
        if self._future is not None:
            cancelled_before_start = self._future.cancel()
        with self._lock:
            if self.status not in TERMINAL_JOB_STATUSES:
                self.status = "STOPPED"
                self.error = None
            for row in self.runs:
                if row.get("status") not in {"COMPLETED", "FAILED", "STOPPED"}:
                    row["status"] = "STOPPED"
            existing_attempts = {
                int(row["attempt"]) for row in self.runs if row.get("attempt")
            }
            for attempt in range(1, self.expected_runs + 1):
                if attempt not in existing_attempts:
                    self.runs.append(
                        {
                            "attempt": attempt,
                            "sdk_run_id": None,
                            "qym_run_id": None,
                            "status": "STOPPED",
                        }
                    )
            self.runs.sort(key=lambda row: int(row.get("attempt") or 0))
            self.updated_at = datetime.utcnow()
        return cancelled_before_start

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "eval_id": self.eval_id,
                "job_id": self.job_id,
                "preset": self.preset,
                "project_id": self.project_id,
                "status": self.status,
                "run_id": self.run_id,
                "runs": [dict(row) for row in self.runs],
                "expected_runs": self.expected_runs,
                "group_analysis": (
                    dict(self.group_analysis) if self.group_analysis else None
                ),
                "error": self.error,
                "created_at": self.created_at.isoformat() + "Z",
                "updated_at": self.updated_at.isoformat() + "Z",
            }


def _default_insightor_script() -> Path:
    env_path = os.getenv("QYM_INSIGHTOR_EVAL_SCRIPT", "").strip()
    if env_path:
        return Path(env_path).expanduser()
    # packages/platform/qym_platform/services/product_evals.py -> repo root
    return Path(__file__).resolve().parents[4] / "insightor_eval.py"


def _default_test_script() -> Path:
    return Path(__file__).resolve().parents[1] / "product_eval_presets" / "test_eval.py"


def _format_missing_script_error(script_path: Path) -> str:
    return f"Preset script not found: {script_path}"


def _insightor_platform_config() -> tuple[Dict[str, Any], int]:
    settings = ProductEvalSettings()
    config = {
        "max_concurrency": settings.max_concurrency,
        "timeout": settings.timeout,
        "max_retries": settings.max_retries,
        "metric_timeout": settings.metric_timeout,
    }
    max_parallel_runs = settings.max_parallel_runs
    effective_concurrency = config["max_concurrency"] * max_parallel_runs
    if effective_concurrency > MAX_EFFECTIVE_CONCURRENCY:
        raise ProductEvalError(
            "QYM_PRODUCT_EVAL_MAX_CONCURRENCY * QYM_PRODUCT_EVAL_MAX_PARALLEL_RUNS must be less than or equal to 20"
        )
    return config, max_parallel_runs


def get_preset(name: str) -> ProductEvalPreset:
    if name == "insightor":
        default_config, max_parallel_runs = _insightor_platform_config()
        return ProductEvalPreset(
            name="insightor",
            script_path=_default_insightor_script(),
            task_name="insightor_api",
            metric_name="accuracy",
            dataset_env=None,
            model_env="MODEL",
            default_dataset_name="playground_set_v2",
            default_config=default_config,
            run_count=3,
            max_parallel_runs=max_parallel_runs,
        )
    if name == "test":
        settings = ProductEvalSettings()
        return ProductEvalPreset(
            name="test",
            script_path=_default_test_script(),
            task_name="test_task",
            metric_name="exact_match",
            dataset_env=None,
            model_env=None,
            default_config={
                "max_concurrency": 10,
                "timeout": 30,
            },
            run_count=3,
            max_parallel_runs=settings.max_parallel_runs,
        )
    raise ProductEvalError(f"Unknown product eval preset: {name}")


def validate_dataset_name(dataset_name: Optional[str]) -> Optional[str]:
    if dataset_name is None:
        return None
    clean = str(dataset_name).strip()
    if not clean:
        raise ProductEvalError("dataset must be a non-empty Langfuse dataset name")
    return clean


def _clean_optional_string(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    clean = str(value).strip()
    return clean or None


def validate_runtime_inputs(
    preset: ProductEvalPreset,
    runtime_inputs: Optional[ProductEvalRuntimeInputs],
) -> ProductEvalRuntimeInputs:
    inputs = runtime_inputs or ProductEvalRuntimeInputs()
    clean = ProductEvalRuntimeInputs(
        insightor_url=_clean_optional_string(inputs.insightor_url),
        refresh_token=_clean_optional_string(inputs.refresh_token),
        agent_version=_clean_optional_string(inputs.agent_version),
        image_version=_clean_optional_string(inputs.image_version),
        kb_version=_clean_optional_string(inputs.kb_version),
    )
    if preset.name == "insightor":
        missing = []
        if not clean.insightor_url:
            missing.append("insightor_url")
        if not clean.refresh_token:
            missing.append("refresh_token")
        if missing:
            joined = ", ".join(missing)
            raise ProductEvalError(f"{joined} required for preset '{preset.name}'")
    return clean


def validate_submit_request(
    *,
    preset_name: str,
    dataset_name: Optional[str] = None,
    runtime_inputs: Optional[ProductEvalRuntimeInputs] = None,
) -> ProductEvalPreset:
    preset = get_preset(preset_name)
    requested_dataset = validate_dataset_name(dataset_name)
    if preset.name == "test" and requested_dataset:
        raise ProductEvalError(
            "dataset is not accepted for preset 'test'; omit it to use the built-in test dataset"
        )
    if not preset.script_path.exists():
        raise RuntimeError(_format_missing_script_error(preset.script_path))
    if (
        preset.requires_dataset_name
        and not requested_dataset
        and not preset.default_dataset_name
    ):
        raise ProductEvalError(f"dataset is required for preset '{preset.name}'")
    validate_runtime_inputs(preset, runtime_inputs)
    return preset


def _load_script(script_path: Path) -> Any:
    if not script_path.exists():
        raise RuntimeError(f"Preset script not found: {script_path}")
    module_name = f"qym_product_eval_{script_path.stem}_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, str(script_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load preset script: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _get_function(
    module: Any, script_path: Path, function_name: str
) -> Callable[..., Any]:
    func = getattr(module, function_name, None)
    if not callable(func):
        raise RuntimeError(f"Function '{function_name}' not found in {script_path}")
    return func


def _safe_error(exc: BaseException) -> str:
    message = f"{type(exc).__name__}: {exc}"
    if not str(exc):
        message = type(exc).__name__
    message = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", message)
    message = re.sub(r"\b(sk|pk|dkuaps)-[A-Za-z0-9._~+/=-]+", r"\1-[REDACTED]", message)
    return message[:1000]


def _compact_group_analysis(analysis: Dict[str, Any]) -> Dict[str, Any]:
    k = int(analysis.get("k") or 0)
    return {
        "metric": analysis.get("metric"),
        "threshold": analysis.get("threshold"),
        "k": k,
        "total_items": analysis.get("total_items"),
        "total_score_count": analysis.get("total_score_count"),
        "failed_count": analysis.get("failed_count"),
        f"pass_at_{k}": analysis.get("pass_at_k"),
        f"avg_at_{k}": analysis.get("avg_at_k"),
        "consistency": analysis.get("consistency"),
        "reliability": analysis.get("reliability"),
        "avg_latency_ms": analysis.get("avg_latency"),
    }


def _compact_from_sampled_result(
    result: Any,
    *,
    metric_name: str,
    threshold: float = 0.8,
) -> Optional[Dict[str, Any]]:
    """Compact group analysis from ONE samples=k run (native repeat runs).

    Emits the exact shape `_compact_group_analysis` produces from k separate
    runs, so the product-eval API response contract stays unchanged.
    """
    try:
        stats = result.group_stats(metric=metric_name, threshold=threshold)
        items_scores = result.item_pass_scores(metric_name)
        total_score_count = sum(len(v) for v in items_scores.values())
        failed_count = sum(
            1
            for entries in getattr(result, "passes", {}).values()
            for entry in entries.values()
            if isinstance(entry, dict) and "error" in entry
        )
        timing = result.get_timing_stats()
        avg_latency_ms = float(timing.get("mean") or 0.0) * 1000.0
        k = int(stats.get("k") or 0)
        return {
            "metric": metric_name,
            "threshold": threshold,
            "k": k,
            "total_items": stats.get("total_items"),
            "total_score_count": total_score_count,
            "failed_count": failed_count,
            f"pass_at_{k}": stats.get("pass_at_k"),
            f"avg_at_{k}": stats.get("avg_at_k"),
            "consistency": stats.get("consistency"),
            "reliability": stats.get("reliability"),
            "avg_latency_ms": avg_latency_ms,
        }
    except Exception as exc:
        logger.warning(
            "Product eval sampled group analysis failed: %s", _safe_error(exc)
        )
        return None


def _analyze_completed_group_results(
    results: Any,
    *,
    metric_name: str,
    threshold: float = 0.8,
) -> Optional[Dict[str, Any]]:
    if not results:
        return None
    try:
        from qym.core.group_analysis import analyze_group_runs

        analysis = analyze_group_runs(
            list(results),
            metric=metric_name,
            threshold=threshold,
            track_distribution=False,
        )
    except Exception as exc:
        logger.warning("Product eval group analysis failed: %s", _safe_error(exc))
        return None
    return _compact_group_analysis(analysis)


class ProductEvalJobManager:
    def __init__(self, *, max_workers: Optional[int] = None) -> None:
        if max_workers is None:
            max_workers = ProductEvalSettings().max_workers
        self._max_workers = max(1, int(max_workers))
        self._executor = ThreadPoolExecutor(
            max_workers=self._max_workers, thread_name_prefix="qym-product-eval"
        )
        self._jobs: Dict[str, ProductEvalJob] = {}
        self._lock = threading.RLock()

    def _inflight_job_count_locked(self) -> int:
        return sum(
            1
            for job in self._jobs.values()
            if job.to_dict()["status"] not in TERMINAL_JOB_STATUSES
        )

    def submit(
        self,
        *,
        preset_name: str,
        api_key: str,
        run_name: Optional[str],
        task_name: Optional[str],
        dataset_name: Optional[str],
        runtime_inputs: Optional[ProductEvalRuntimeInputs],
        model: Optional[str],
        metadata: Dict[str, Any],
        owner_user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        platform_url: Optional[str] = None,
    ) -> ProductEvalJob:
        requested_dataset = validate_dataset_name(dataset_name)
        preset = validate_submit_request(
            preset_name=preset_name,
            dataset_name=requested_dataset,
            runtime_inputs=runtime_inputs,
        )
        validated_runtime_inputs = validate_runtime_inputs(preset, runtime_inputs)
        job = ProductEvalJob(
            job_id=f"eval_{uuid4().hex}",
            preset=preset.name,
            owner_user_id=owner_user_id,
            project_id=project_id,
            expected_runs=preset.run_count,
        )
        job.initialize_planned_runs()
        with self._lock:
            if self._inflight_job_count_locked() >= self._max_workers:
                raise ProductEvalQueueFull(
                    "Too many product eval jobs are already running. Try again later."
                )
            self._jobs[job.job_id] = job
        try:
            future = self._executor.submit(
                self._run_job,
                job,
                preset,
                api_key,
                run_name,
                task_name,
                requested_dataset,
                validated_runtime_inputs,
                model,
                dict(metadata or {}),
                platform_url,
            )
        except Exception:
            with self._lock:
                self._jobs.pop(job.job_id, None)
            raise
        job._future = future
        return job

    def get(self, job_id: str) -> Optional[ProductEvalJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def get_by_qym_run_id(self, run_id: str) -> Optional[ProductEvalJob]:
        with self._lock:
            for job in self._jobs.values():
                snapshot = job.to_dict()
                if snapshot.get("run_id") == run_id:
                    return job
                for row in snapshot["runs"]:
                    if row.get("qym_run_id") == run_id:
                        return job
        return None

    def _run_job(
        self,
        job: ProductEvalJob,
        preset: ProductEvalPreset,
        api_key: str,
        run_name: Optional[str],
        task_name: Optional[str],
        dataset_name: Optional[str],
        runtime_inputs: ProductEvalRuntimeInputs,
        model: Optional[str],
        metadata: Dict[str, Any],
        platform_url: Optional[str],
    ) -> None:
        job.mark(status="RUNNING")
        try:
            if job.stop_requested():
                job.mark(status="STOPPED")
                return

            from qym import Evaluator, ProgressCallbackObserver

            resolved_max_parallel_runs = preset.max_parallel_runs

            module = _load_script(preset.script_path)
            configure_runtime = getattr(module, "configure_runtime", None)
            if callable(configure_runtime):
                configure_runtime(
                    INSIGHTOR_URL=runtime_inputs.insightor_url,
                    REFRESH_TOKEN=runtime_inputs.refresh_token,
                    AGENT_VERSION=runtime_inputs.agent_version,
                    IMAGE_VERSION=runtime_inputs.image_version,
                    KB_VERSION=runtime_inputs.kb_version,
                )
            task = _get_function(module, preset.script_path, preset.task_name)
            metric = _get_function(module, preset.script_path, preset.metric_name)

            if dataset_name:
                dataset = dataset_name
            elif preset.default_dataset_name:
                dataset = preset.default_dataset_name
            elif preset.requires_dataset_name:
                raise RuntimeError(f"dataset is required for preset '{preset.name}'")
            elif preset.dataset_env:
                dataset = os.getenv(preset.dataset_env, "").strip()
                if not dataset:
                    raise RuntimeError(
                        f"{preset.dataset_env} is required for preset '{preset.name}'"
                    )
            else:
                dataset = getattr(module, "EVAL_DATASET", None)
                if dataset is None:
                    raise RuntimeError(
                        f"EVAL_DATASET is required for preset '{preset.name}'"
                    )

            env_model = os.getenv(preset.model_env) if preset.model_env else None
            resolved_model = model or env_model or getattr(module, "MODEL", None)
            settings = PlatformSettings()
            resolved_platform_url = (
                platform_url or settings.base_url
            ).rstrip("/")

            def build_run_metadata(attempt: int) -> Dict[str, Any]:
                run_metadata = dict(metadata or {})
                product_eval = run_metadata.get("product_eval")
                product_eval = (
                    dict(product_eval) if isinstance(product_eval, dict) else {}
                )
                product_eval.update(
                    {
                        "preset": preset.name,
                        "eval_id": job.eval_id,
                        "attempt": attempt,
                        "attempts": preset.run_count,
                    }
                )
                run_metadata["product_eval"] = product_eval
                return run_metadata

            run_metadata = build_run_metadata(1)

            evaluator_config: Dict[str, Any] = {
                **preset.default_config,
                "run_metadata": run_metadata,
                "platform_api_key": api_key,
                "platform_url": resolved_platform_url,
                "live_mode": "platform",
                "should_stop": job.stop_requested,
                "checkpoint_enabled": False,
            }
            if run_name:
                evaluator_config["run_name"] = run_name
            else:
                default_run_name = getattr(module, "DEFAULT_RUN_NAME", None)
                if default_run_name:
                    evaluator_config["run_name"] = default_run_name
                else:
                    version_name = "_".join(
                        part
                        for part in (
                            runtime_inputs.agent_version,
                            runtime_inputs.image_version,
                            runtime_inputs.kb_version,
                        )
                        if part
                    )
                    if version_name:
                        evaluator_config["run_name"] = version_name
            if task_name:
                evaluator_config["task_name"] = task_name

            current_batch_start = 0

            def on_progress(snapshot: Any) -> None:
                event = getattr(snapshot, "event", None)
                if event == "run_matrix":
                    run_matrix = []
                    for row in getattr(snapshot, "run_matrix", None) or []:
                        next_row = dict(row)
                        try:
                            index = int(next_row.get("index") or 0)
                        except Exception:
                            index = 0
                        next_row["product_eval_attempt"] = (
                            current_batch_start + index + 1
                        )
                        run_matrix.append(next_row)
                    job.record_run_matrix(run_matrix)
                    return
                sdk_run_id = str(getattr(snapshot, "run_id", "") or "")
                if not sdk_run_id:
                    return
                if event == "run_start":
                    run_info = getattr(snapshot, "run_info", None) or {}
                    platform_run_id = run_info.get("platform_run_id")
                    job.mark_run(
                        sdk_run_id=sdk_run_id,
                        status="STOPPED" if job.stop_requested() else "RUNNING",
                        qym_run_id=str(platform_run_id) if platform_run_id else None,
                    )
                elif event == "run_complete":
                    job.mark_run(
                        sdk_run_id=sdk_run_id,
                        status="STOPPED" if job.stop_requested() else "COMPLETED",
                    )

            if preset.run_count > 1:
                # Repeat runs are native now: ONE run with samples=k replaces
                # the old k-RunSpec fan-out (one dashboard row, per-pass
                # storage, group metrics computed by the run itself).
                base_name = (
                    run_name
                    or getattr(module, "DEFAULT_RUN_NAME", None)
                    or "_".join(
                        part
                        for part in (
                            runtime_inputs.agent_version,
                            runtime_inputs.image_version,
                            runtime_inputs.kb_version,
                        )
                        if part
                    )
                    or preset.task_name
                )
                sampled_config = {
                    **evaluator_config,
                    "run_metadata": build_run_metadata(1),
                    "run_name": base_name,
                    "samples": int(preset.run_count),
                    # Stop requests take effect mid-run (the old batch loop
                    # checked between run_parallel batches).
                    "should_stop": job.stop_requested,
                }
                evaluator = Evaluator(
                    task=task,
                    dataset=dataset,
                    metrics=[metric],
                    model=resolved_model,
                    config=sampled_config,
                    progress_callback=on_progress,
                )
                result = evaluator.run(show_tui=False, auto_save=False)
                if not job.stop_requested():
                    group_analysis = _compact_from_sampled_result(
                        result,
                        metric_name=preset.metric_name,
                    )
                    if group_analysis:
                        job.set_group_analysis(group_analysis)
            else:
                evaluator = Evaluator(
                    task=task,
                    dataset=dataset,
                    metrics=[metric],
                    model=resolved_model,
                    config=evaluator_config,
                    progress_callback=on_progress,
                )
                evaluator.run(show_tui=False, auto_save=False)
            job.mark(status="STOPPED" if job.stop_requested() else "COMPLETED")
        except Exception as exc:
            error = _safe_error(exc)
            if job.stop_requested():
                job.mark(status="STOPPED", error=None)
                logger.info("Product eval %s stopped", job.eval_id)
            else:
                job.mark(status="FAILED", error=error)
                logger.warning("Product eval %s failed: %s", job.eval_id, error)
