from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from qym_platform.auth import (
    Principal,
    require_api_key_principal,
    require_api_key_scope,
)
from qym_platform.datetime_utils import to_api_timestamp
from qym_platform.db.models import Run, RunEvent, RunItem, RunItemScore
from qym_platform.deps import get_db
from qym_platform.services.product_evals import (
    ProductEvalError,
    ProductEvalJob,
    ProductEvalJobManager,
)
from qym_platform.settings import PlatformSettings


router = APIRouter(prefix="/v1/product-evals", tags=["product-evals"])
job_manager = ProductEvalJobManager()


class ProductEvalSubmitRequest(BaseModel):
    preset: str = Field(default="insightor")
    run_name: Optional[str] = None
    task_name: Optional[str] = None
    model: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    config: Dict[str, Any] = Field(default_factory=dict)


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def _ok(data: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {
            "ok": False,
            "data": None,
            "error": {
                "code": code,
                "message": message,
            },
        },
        status_code=status_code,
    )


def _qym_run_url(run_id: Optional[str]) -> Optional[str]:
    if not run_id:
        return None
    settings = PlatformSettings()
    return f"{settings.base_url.rstrip('/')}/run/{run_id}"


def _job_payload(job: ProductEvalJob, *, internal: bool = False) -> Dict[str, Any]:
    if job.run_id:
        poll_url = f"/v1/product-evals/{job.run_id}"
    else:
        poll_url = f"/v1/product-evals/jobs/{job.job_id}"
    status = (
        "STARTING"
        if job.status in {"QUEUED", "RUNNING"} and not job.run_id
        else job.status
    )
    payload: Dict[str, Any] = {
        "status": status,
        "qym_run_id": job.run_id,
        "qym_project_id": job.project_id,
        "qym_run_url": _qym_run_url(job.run_id),
        "poll_url": poll_url,
        "created_at": job.created_at.isoformat() + "Z",
        "updated_at": job.updated_at.isoformat() + "Z",
    }
    if job.error:
        payload["error"] = job.error
    if internal:
        payload.update(
            {
                "job_id": job.job_id,
                "preset": job.preset,
            }
        )
    return payload


def _require_run_access(db: Session, principal: Principal, run_id: str) -> Run:
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.owner_user_id != principal.user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    if principal.project_id and run.project_id != principal.project_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return run


def _status_value(run: Run) -> str:
    status = run.status
    return status.value if hasattr(status, "value") else str(status)


def _score_value(score: RunItemScore) -> Any:
    if score.score_numeric is not None:
        return score.score_numeric
    return score.score_raw


def _metric_stats(
    metrics: List[str], scores: List[RunItemScore]
) -> Dict[str, Dict[str, Any]]:
    stats: Dict[str, Dict[str, Any]] = {}
    for metric in metrics:
        values = [
            float(score.score_numeric)
            for score in scores
            if score.metric_name == metric and score.score_numeric is not None
        ]
        stats[metric] = {
            "count": len(values),
            "mean": (sum(values) / len(values)) if values else None,
            "min": min(values) if values else None,
            "max": max(values) if values else None,
        }
    return stats


def _latency_stats(items: List[RunItem]) -> Dict[str, Any]:
    values = [float(item.latency_ms) for item in items if item.latency_ms is not None]
    return {
        "count": len(values),
        "mean": (sum(values) / len(values)) if values else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def _public_metadata(run_metadata: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in run_metadata.items() if key != "product_eval"}


def _completed_event_item_ids(db: Session, run_id: str) -> set[str]:
    events = (
        db.query(RunEvent)
        .filter(
            RunEvent.run_id == run_id,
            RunEvent.type.in_(["item_completed", "item_failed"]),
        )
        .all()
    )
    item_ids: set[str] = set()
    for event in events:
        payload = event.payload or {}
        item_id = payload.get("item_id") if isinstance(payload, dict) else None
        if item_id:
            item_ids.add(str(item_id))
    return item_ids


def build_product_eval_run_payload(
    db: Session, run: Run, *, include_items: bool = False
) -> Dict[str, Any]:
    items: List[RunItem] = (
        db.query(RunItem)
        .filter(RunItem.run_id == run.id)
        .order_by(RunItem.index.asc())
        .all()
    )
    scores: List[RunItemScore] = (
        db.query(RunItemScore).filter(RunItemScore.run_id == run.id).all()
    )
    metrics = list(run.metrics or [])
    completed_event_ids = _completed_event_item_ids(db, run.id)

    scores_by_item: Dict[str, Dict[str, RunItemScore]] = {}
    for score in scores:
        scores_by_item.setdefault(score.item_id, {})[score.metric_name] = score

    rows: List[Dict[str, Any]] = []
    completed = 0
    failed = 0
    in_progress = 0
    for item in items:
        is_failed = bool(item.error)
        is_done = (
            is_failed or item.item_id in completed_event_ids or item.output is not None
        )
        if is_failed:
            status = "error"
            failed += 1
        elif is_done:
            status = "completed"
            completed += 1
        else:
            status = "in_progress"
            in_progress += 1

        item_scores = scores_by_item.get(item.item_id, {})
        score_payload: Dict[str, Any] = {}
        metric_meta: Dict[str, Any] = {}
        for metric in metrics:
            score = item_scores.get(metric)
            if not score:
                continue
            score_payload[metric] = _score_value(score)
            meta = dict(score.meta or {})
            if score.label:
                meta["label"] = score.label
            if score.explanation:
                meta["explanation"] = score.explanation
            if meta:
                metric_meta[metric] = meta

        if include_items:
            rows.append(
                {
                    "index": item.index,
                    "item_id": item.item_id,
                    "status": status,
                    "input": item.input,
                    "expected": item.expected,
                    "output": item.output,
                    "error": item.error,
                    "latency_ms": item.latency_ms,
                    "retry_count": item.retry_count,
                    "trace_id": item.trace_id,
                    "trace_url": item.trace_url,
                    "metadata": item.item_metadata or {},
                    "scores": score_payload,
                    "metric_metadata": metric_meta,
                }
            )

    run_metadata = run.run_metadata if isinstance(run.run_metadata, dict) else {}
    total_raw = run_metadata.get("total_items")
    try:
        total = int(total_raw)
    except Exception:
        total = len(items)
    total = max(total, len(items))
    pending = max(total - completed - failed - in_progress, 0)

    payload = {
        "qym_run_id": run.id,
        "qym_project_id": run.project_id,
        "qym_run_url": _qym_run_url(run.id),
        "external_run_id": run.external_run_id,
        "status": _status_value(run),
        "task": run.task,
        "dataset": run.dataset,
        "model": run.model,
        "metrics": metrics,
        "total": total,
        "completed": completed,
        "failed": failed,
        "in_progress": in_progress,
        "pending": pending,
        "metric_stats": _metric_stats(metrics, scores),
        "latency_ms": _latency_stats(items),
        "started_at": to_api_timestamp(run.started_at),
        "ended_at": to_api_timestamp(run.ended_at),
        "created_at": to_api_timestamp(run.created_at),
        "metadata": _public_metadata(run_metadata),
        "config": run.run_config if isinstance(run.run_config, dict) else {},
    }
    if include_items:
        payload["items"] = rows
    return jsonable_encoder(payload)


@router.post("")
def submit_product_eval(
    request: ProductEvalSubmitRequest,
    principal: Principal = Depends(require_api_key_principal),
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    require_api_key_scope(principal, "runs:write")
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing Bearer API key")
    if not principal.project_id:
        raise HTTPException(status_code=403, detail="API key is not bound to a project")

    try:
        job = job_manager.submit(
            preset_name=request.preset,
            api_key=token,
            run_name=request.run_name,
            task_name=request.task_name,
            model=request.model,
            metadata=request.metadata,
            config=request.config,
            owner_user_id=principal.user.id,
            project_id=principal.project_id,
        )
    except ProductEvalError as exc:
        return _error_response(400, "invalid_request", str(exc))
    except RuntimeError as exc:
        return _error_response(500, "preset_error", str(exc))

    job.wait_for_run(timeout=5.0)
    return JSONResponse(_ok(_job_payload(job)), status_code=202)


@router.get("/jobs/{job_id}")
def get_product_eval_job(
    job_id: str,
    principal: Principal = Depends(require_api_key_principal),
) -> JSONResponse:
    require_api_key_scope(principal, "runs:read")
    job = job_manager.get(job_id)
    if not job:
        return _error_response(404, "not_found", "Job not found")
    if job.owner_user_id and job.owner_user_id != principal.user.id:
        return _error_response(403, "forbidden", "Forbidden")
    if (
        job.project_id
        and principal.project_id
        and job.project_id != principal.project_id
    ):
        return _error_response(403, "forbidden", "Forbidden")
    return JSONResponse(_ok(_job_payload(job)))


@router.get("/{run_id}")
def get_product_eval_run(
    run_id: str,
    include_items: bool = Query(default=False),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_api_key_principal),
) -> Dict[str, Any]:
    require_api_key_scope(principal, "runs:read")
    run = _require_run_access(db, principal, run_id)
    return _ok(build_product_eval_run_payload(db, run, include_items=include_items))
