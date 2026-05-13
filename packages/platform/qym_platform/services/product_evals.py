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
from typing import Any, Callable, Dict, Optional
from uuid import uuid4

from qym_platform.settings import PlatformSettings


logger = logging.getLogger(__name__)

ALLOWED_CONFIG_KEYS = {
    "max_concurrency",
    "timeout",
    "max_retries",
    "metric_timeout",
    "max_metric_concurrency",
}


class ProductEvalError(ValueError):
    """User-correctable product eval request error."""


@dataclass(frozen=True)
class ProductEvalPreset:
    name: str
    script_path: Path
    task_name: str
    metric_name: str
    dataset_env: Optional[str]
    model_env: Optional[str]
    default_config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProductEvalJob:
    job_id: str
    preset: str
    owner_user_id: Optional[str] = None
    project_id: Optional[str] = None
    status: str = "QUEUED"
    run_id: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    _run_ready: threading.Event = field(default_factory=threading.Event, repr=False)
    _future: Optional[Future] = field(default=None, repr=False)

    def mark(
        self,
        *,
        status: Optional[str] = None,
        run_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        if status is not None:
            self.status = status
        if run_id:
            self.run_id = run_id
            self._run_ready.set()
        if error is not None:
            self.error = error
        self.updated_at = datetime.utcnow()

    def wait_for_run(self, timeout: float) -> bool:
        return self._run_ready.wait(timeout=timeout)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "preset": self.preset,
            "project_id": self.project_id,
            "status": self.status,
            "run_id": self.run_id,
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


def get_preset(name: str) -> ProductEvalPreset:
    if name == "insightor":
        return ProductEvalPreset(
            name="insightor",
            script_path=_default_insightor_script(),
            task_name="insightor_api",
            metric_name="accuracy",
            dataset_env="EVAL_DATASET",
            model_env="MODEL",
            default_config={
                "max_concurrency": 15,
                "timeout": 900,
            },
        )
    if name == "test":
        return ProductEvalPreset(
            name="test",
            script_path=_default_test_script(),
            task_name="test_task",
            metric_name="exact_match",
            dataset_env=None,
            model_env=None,
            default_config={
                "max_concurrency": 2,
                "timeout": 30,
            },
        )
    raise ProductEvalError(f"Unknown product eval preset: {name}")


def validate_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    clean = dict(config or {})
    disallowed = sorted(set(clean) - ALLOWED_CONFIG_KEYS)
    if disallowed:
        joined = ", ".join(disallowed)
        raise ProductEvalError(f"Unsupported config key(s): {joined}")
    return clean


def validate_submit_request(
    *, preset_name: str, config: Optional[Dict[str, Any]]
) -> ProductEvalPreset:
    preset = get_preset(preset_name)
    validate_config(config)
    if not preset.script_path.exists():
        raise RuntimeError(_format_missing_script_error(preset.script_path))
    dataset = os.getenv(preset.dataset_env, "").strip() if preset.dataset_env else ""
    if preset.dataset_env and not dataset:
        raise RuntimeError(
            f"{preset.dataset_env} is required for preset '{preset.name}'"
        )
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


class ProductEvalJobManager:
    def __init__(self, *, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="qym-product-eval"
        )
        self._jobs: Dict[str, ProductEvalJob] = {}
        self._lock = threading.RLock()

    def submit(
        self,
        *,
        preset_name: str,
        api_key: str,
        run_name: Optional[str],
        task_name: Optional[str],
        model: Optional[str],
        metadata: Dict[str, Any],
        config: Dict[str, Any],
        owner_user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        platform_url: Optional[str] = None,
    ) -> ProductEvalJob:
        preset = validate_submit_request(preset_name=preset_name, config=config)
        job = ProductEvalJob(
            job_id=str(uuid4()),
            preset=preset.name,
            owner_user_id=owner_user_id,
            project_id=project_id,
        )
        with self._lock:
            self._jobs[job.job_id] = job
        future = self._executor.submit(
            self._run_job,
            job,
            preset,
            api_key,
            run_name,
            task_name,
            model,
            dict(metadata or {}),
            validate_config(config),
            platform_url,
        )
        job._future = future
        return job

    def get(self, job_id: str) -> Optional[ProductEvalJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def _run_job(
        self,
        job: ProductEvalJob,
        preset: ProductEvalPreset,
        api_key: str,
        run_name: Optional[str],
        task_name: Optional[str],
        model: Optional[str],
        metadata: Dict[str, Any],
        request_config: Dict[str, Any],
        platform_url: Optional[str],
    ) -> None:
        job.mark(status="RUNNING")
        try:
            from qym import Evaluator

            module = _load_script(preset.script_path)
            task = _get_function(module, preset.script_path, preset.task_name)
            metric = _get_function(module, preset.script_path, preset.metric_name)
            if preset.dataset_env:
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
                platform_url or os.getenv("QYM_PLATFORM_URL") or settings.base_url
            ).rstrip("/")

            run_metadata = dict(metadata or {})
            run_metadata.setdefault("product_eval", {})
            if isinstance(run_metadata["product_eval"], dict):
                run_metadata["product_eval"].update(
                    {"preset": preset.name, "job_id": job.job_id}
                )

            evaluator_config: Dict[str, Any] = {
                **preset.default_config,
                **request_config,
                "run_metadata": run_metadata,
                "platform_api_key": api_key,
                "platform_url": resolved_platform_url,
                "live_mode": "platform",
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
                            os.getenv("AGENT_VERSION"),
                            os.getenv("IMAGE_VERSION"),
                            os.getenv("KB_VERSION"),
                        )
                        if part
                    )
                    if version_name:
                        evaluator_config["run_name"] = version_name
            if task_name:
                evaluator_config["task_name"] = task_name

            def on_progress(snapshot: Any) -> None:
                if getattr(snapshot, "event", None) != "run_start":
                    return
                run_info = getattr(snapshot, "run_info", None) or {}
                platform_run_id = run_info.get("platform_run_id")
                if platform_run_id:
                    job.mark(run_id=str(platform_run_id))

            evaluator = Evaluator(
                task=task,
                dataset=dataset,
                metrics=[metric],
                model=resolved_model,
                config=evaluator_config,
                progress_callback=on_progress,
            )
            evaluator.run(show_tui=False, auto_save=False)
            job.mark(status="COMPLETED")
        except Exception as exc:
            error = _safe_error(exc)
            job.mark(status="FAILED", error=error)
            logger.warning("Product eval job %s failed: %s", job.job_id, error)
