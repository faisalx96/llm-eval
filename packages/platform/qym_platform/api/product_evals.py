from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from qym_platform.auth import (
    Principal,
    require_api_key_principal,
    require_api_key_scope,
)
from qym_platform.datetime_utils import to_api_timestamp, utc_now_naive
from qym_platform.db.models import (
    Run,
    RunEvent,
    RunItem,
    RunItemScore,
    RunWorkflowStatus,
)
from qym_platform.deps import get_db
from qym_platform.services.product_evals import (
    ProductEvalError,
    ProductEvalJob,
    ProductEvalJobManager,
    ProductEvalQueueFull,
    ProductEvalRuntimeInputs,
)
from qym_platform.settings import PlatformSettings


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/product-evals", tags=["product-evals"])
job_manager = ProductEvalJobManager()


class ProductEvalSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    preset: str = Field(default="insightor")
    dataset: Optional[str] = None
    insightor_url: Optional[str] = None
    refresh_token: Optional[str] = None
    agent_version: Optional[str] = None
    image_version: Optional[str] = None
    kb_version: Optional[str] = None
    run_name: Optional[str] = None
    task_name: Optional[str] = None
    model: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


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


def _error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> JSONResponse:
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
        headers=headers,
    )


def _qym_run_url(run_id: Optional[str]) -> Optional[str]:
    if not run_id:
        return None
    settings = PlatformSettings()
    return f"{settings.base_url.rstrip('/')}/run/{run_id}"


def _qym_compare_url(run_ids: List[str]) -> Optional[str]:
    clean = [run_id for run_id in run_ids if run_id]
    if len(clean) < 2:
        return None
    settings = PlatformSettings()
    return f"{settings.base_url.rstrip('/')}/compare?{urlencode({'runs': clean}, doseq=True)}"


def _run_summary_payload(db: Session, run: Run) -> Dict[str, Any]:
    payload = build_product_eval_run_payload(db, run, include_items=False)
    return {
        "task": payload.get("task"),
        "dataset": payload.get("dataset"),
        "model": payload.get("model"),
        "summary": {
            "total": payload.get("total"),
            "completed": payload.get("completed"),
            "failed": payload.get("failed"),
            "in_progress": payload.get("in_progress"),
            "pending": payload.get("pending"),
            "metrics": payload.get("metrics") or [],
            "metric_stats": payload.get("metric_stats") or {},
            "latency_ms": payload.get("latency_ms") or {},
            "started_at": payload.get("started_at"),
            "ended_at": payload.get("ended_at"),
        },
    }


def _runs_by_id_for_principal(
    db: Session, principal: Principal, run_ids: List[str]
) -> Dict[str, Run]:
    clean = sorted({run_id for run_id in run_ids if run_id})
    if not clean:
        return {}
    query = Run.active(db).filter(Run.id.in_(clean))
    if principal.project_id:
        query = query.filter(Run.project_id == principal.project_id)
    query = query.filter(Run.owner_user_id == principal.user.id)
    return {run.id: run for run in query.all()}


def _job_payload(
    job: ProductEvalJob,
    *,
    db: Optional[Session] = None,
    principal: Optional[Principal] = None,
) -> Dict[str, Any]:
    snapshot = job.to_dict()
    qym_run_ids = [
        str(row["qym_run_id"]) for row in snapshot["runs"] if row.get("qym_run_id")
    ]
    runs_by_id = (
        _runs_by_id_for_principal(db, principal, qym_run_ids)
        if db is not None and principal is not None
        else {}
    )
    runs = []
    for row in snapshot["runs"]:
        qym_run_id = row.get("qym_run_id")
        run_payload: Dict[str, Any] = {
            "attempt": row.get("attempt"),
            "status": row.get("status"),
            "qym_run_id": qym_run_id,
            "qym_run_url": _qym_run_url(qym_run_id),
            "task": None,
            "dataset": None,
            "model": None,
            "summary": None,
        }
        if qym_run_id and qym_run_id in runs_by_id:
            details = _run_summary_payload(db, runs_by_id[qym_run_id])
            run_payload.update(details)
        runs.append(run_payload)

    status = (
        "STARTING"
        if snapshot["status"] in {"QUEUED", "RUNNING"} and not snapshot["run_id"]
        else snapshot["status"]
    )
    payload: Dict[str, Any] = {
        "eval_id": snapshot["eval_id"],
        "status": status,
        "qym_project_id": snapshot["project_id"],
        "runs": runs,
        "qym_compare_url": _qym_compare_url(qym_run_ids),
        "group_analysis": snapshot["group_analysis"] if snapshot["status"] == "COMPLETED" else None,
        "created_at": snapshot["created_at"],
        "updated_at": snapshot["updated_at"],
    }
    if snapshot["error"]:
        payload["error"] = snapshot["error"]
    return payload


def _product_eval_metadata(run: Run) -> Dict[str, Any]:
    run_metadata = run.run_metadata if isinstance(run.run_metadata, dict) else {}
    product_eval = run_metadata.get("product_eval")
    return product_eval if isinstance(product_eval, dict) else {}


def _runs_for_eval_id(
    db: Session, principal: Principal, eval_id: str
) -> List[Run]:
    query = Run.active(db).filter(Run.owner_user_id == principal.user.id)
    if principal.project_id:
        query = query.filter(Run.project_id == principal.project_id)
    runs = []
    for run in query.order_by(Run.created_at.asc()).all():
        if _product_eval_metadata(run).get("eval_id") == eval_id:
            runs.append(run)
    return runs


def _aggregate_eval_status(statuses: List[str]) -> str:
    if not statuses:
        return "STARTING"
    terminal = {"COMPLETED", "FAILED", "STOPPED"}
    if any(status not in terminal for status in statuses):
        return "RUNNING"
    if any(status == "FAILED" for status in statuses):
        return "FAILED"
    if all(status == "STOPPED" for status in statuses):
        return "STOPPED"
    if all(status == "COMPLETED" for status in statuses):
        return "COMPLETED"
    return "STOPPED"


def _compact_group_analysis_payload(analysis: Dict[str, Any]) -> Dict[str, Any]:
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


def _group_analysis_from_db_runs(
    db: Session, runs: List[Run]
) -> Optional[Dict[str, Any]]:
    if not runs:
        return None
    metric = (runs[0].metrics or [None])[0]
    if not metric:
        return None
    try:
        from qym.core.group_analysis import analyze_group_runs
        from qym.core.results import EvaluationResult
    except Exception:
        logger.warning("Product eval group analysis unavailable: qym SDK import failed", exc_info=True)
        return None

    results = []
    for run in runs:
        result = EvaluationResult(
            run.dataset or "",
            run.external_run_id or run.id,
            list(run.metrics or []),
        )
        items = (
            db.query(RunItem)
            .filter(RunItem.run_id == run.id)
            .order_by(RunItem.index.asc())
            .all()
        )
        scores = (
            db.query(RunItemScore)
            .filter(RunItemScore.run_id == run.id, RunItemScore.metric_name == metric)
            .all()
        )
        scores_by_item = {score.item_id: score for score in scores}
        for item in items:
            if item.item_metadata:
                result.add_metadata(item.item_id, dict(item.item_metadata))
            score = scores_by_item.get(item.item_id)
            latency_seconds = (
                float(item.latency_ms) / 1000.0
                if item.latency_ms is not None
                else None
            )
            if item.error:
                result.add_error(
                    item.item_id,
                    item.error,
                    time_seconds=latency_seconds,
                )
            elif score is not None:
                result.add_result(
                    item.item_id,
                    {
                        "scores": {metric: _score_value(score)},
                        "latency_ms": item.latency_ms,
                        "retry_count": item.retry_count,
                    },
                )
        results.append(result)

    try:
        return _compact_group_analysis_payload(
            analyze_group_runs(
                results,
                metric=metric,
                threshold=0.8,
                track_distribution=False,
            )
        )
    except Exception:
        logger.warning(
            "Product eval group analysis from DB runs failed for runs %s",
            [run.id for run in runs],
            exc_info=True,
        )
        return None


def _db_eval_payload(db: Session, eval_id: str, runs: List[Run]) -> Dict[str, Any]:
    ordered = sorted(
        runs,
        key=lambda run: (
            int(_product_eval_metadata(run).get("attempt") or 999999),
            run.created_at,
        ),
    )
    run_ids = [run.id for run in ordered]
    statuses = [_status_value(run) for run in ordered]
    status = _aggregate_eval_status(statuses)
    project_id = ordered[0].project_id if ordered else None
    created_at = min((run.created_at for run in ordered), default=None)
    updated_at = max((run.updated_at for run in ordered), default=None)
    payload_runs = []
    for index, run in enumerate(ordered, start=1):
        details = _run_summary_payload(db, run)
        product_eval = _product_eval_metadata(run)
        payload_runs.append(
            {
                "attempt": product_eval.get("attempt") or index,
                "status": _status_value(run),
                "qym_run_id": run.id,
                "qym_run_url": _qym_run_url(run.id),
                **details,
            }
        )
    return {
        "eval_id": eval_id,
        "status": status,
        "qym_project_id": project_id,
        "runs": payload_runs,
        "qym_compare_url": _qym_compare_url(run_ids),
        "group_analysis": (
            _group_analysis_from_db_runs(db, ordered) if status == "COMPLETED" else None
        ),
        "created_at": to_api_timestamp(created_at),
        "updated_at": to_api_timestamp(updated_at),
    }


def _require_job_access(
    job: Optional[ProductEvalJob],
    principal: Principal,
) -> Union[ProductEvalJob, JSONResponse]:
    if not job:
        return _error_response(404, "not_found", "Eval not found")
    snapshot = job.to_dict()
    if snapshot.get("project_id") and principal.project_id and snapshot["project_id"] != principal.project_id:
        return _error_response(403, "forbidden", "Forbidden")
    if job.owner_user_id and job.owner_user_id != principal.user.id:
        return _error_response(403, "forbidden", "Forbidden")
    return job


def _is_eval_id(identifier: str) -> bool:
    return identifier.startswith("eval_")


def _require_run_access(db: Session, principal: Principal, run_id: str) -> Run:
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.owner_user_id != principal.user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    if principal.project_id and run.project_id != principal.project_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return run


def _stop_product_eval_runs(db: Session, job: ProductEvalJob, principal: Principal) -> int:
    snapshot = job.to_dict()
    run_ids = {
        str(row["qym_run_id"])
        for row in snapshot["runs"]
        if row.get("qym_run_id")
    }
    if snapshot.get("run_id"):
        run_ids.add(str(snapshot["run_id"]))
    if not run_ids:
        return 0

    query = Run.active(db).filter(Run.id.in_(sorted(run_ids)))
    if principal.project_id:
        query = query.filter(Run.project_id == principal.project_id)
    query = query.filter(Run.owner_user_id == principal.user.id)

    now = utc_now_naive()
    stopped = 0
    for run in query.all():
        if run.status in {
            RunWorkflowStatus.COMPLETED,
            RunWorkflowStatus.FAILED,
            RunWorkflowStatus.STOPPED,
        }:
            continue
        run.status = RunWorkflowStatus.STOPPED
        run.status_reason = "product_eval_stopped"
        run.ended_at = now
        run.last_event_at = now
        stopped += 1
    db.commit()
    return stopped


def _stop_runs(db: Session, runs: List[Run]) -> int:
    now = utc_now_naive()
    stopped = 0
    for run in runs:
        if run.status in {
            RunWorkflowStatus.COMPLETED,
            RunWorkflowStatus.FAILED,
            RunWorkflowStatus.STOPPED,
        }:
            continue
        run.status = RunWorkflowStatus.STOPPED
        run.status_reason = "product_eval_stopped"
        run.ended_at = now
        run.last_event_at = now
        stopped += 1
    db.commit()
    return stopped


def _mark_run_stopped(db: Session, run: Run) -> bool:
    if run.status in {
        RunWorkflowStatus.COMPLETED,
        RunWorkflowStatus.FAILED,
        RunWorkflowStatus.STOPPED,
    }:
        return False
    now = utc_now_naive()
    run.status = RunWorkflowStatus.STOPPED
    run.status_reason = "product_eval_stopped"
    run.ended_at = now
    run.last_event_at = now
    db.commit()
    return True


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
    }
    if include_items:
        payload["items"] = rows
    return jsonable_encoder(payload)


@router.post("")
def submit_product_eval(
    request: ProductEvalSubmitRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_api_key_principal),
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    require_api_key_scope(principal, "runs:write")
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing Bearer API key")
    if not principal.project_id:
        raise HTTPException(status_code=403, detail="API key is not bound to a project")
    extra_fields = set(request.model_extra or {})
    if "config" in extra_fields:
        return _error_response(
            400,
            "invalid_request",
            "config is not accepted on this endpoint. Product eval runtime settings are controlled by QYM_PRODUCT_EVAL_* environment variables.",
        )
    if extra_fields:
        joined = ", ".join(sorted(extra_fields))
        return _error_response(400, "invalid_request", f"Unsupported field(s): {joined}")

    try:
        job = job_manager.submit(
            preset_name=request.preset,
            api_key=token,
            run_name=request.run_name,
            task_name=request.task_name,
            dataset_name=request.dataset,
            runtime_inputs=ProductEvalRuntimeInputs(
                insightor_url=request.insightor_url,
                refresh_token=request.refresh_token,
                agent_version=request.agent_version,
                image_version=request.image_version,
                kb_version=request.kb_version,
            ),
            model=request.model,
            metadata=request.metadata,
            owner_user_id=principal.user.id,
            project_id=principal.project_id,
        )
    except ProductEvalError as exc:
        return _error_response(400, "invalid_request", str(exc))
    except ProductEvalQueueFull as exc:
        return _error_response(
            429,
            "queue_full",
            str(exc),
            headers={"Retry-After": "30"},
        )
    except RuntimeError as exc:
        return _error_response(500, "preset_error", str(exc))

    job.wait_for_run(timeout=5.0)
    return JSONResponse(_ok(_job_payload(job, db=db, principal=principal)), status_code=202)


@router.get("/jobs/{job_id}")
def get_product_eval_job(
    job_id: str,
    principal: Principal = Depends(require_api_key_principal),
) -> JSONResponse:
    require_api_key_scope(principal, "runs:read")
    job_or_response = _require_job_access(job_manager.get(job_id), principal)
    if isinstance(job_or_response, JSONResponse):
        return job_or_response
    return JSONResponse(_ok(_job_payload(job_or_response)))


@router.post("/jobs/{job_id}/stop")
def stop_product_eval_job(
    job_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_api_key_principal),
) -> JSONResponse:
    require_api_key_scope(principal, "runs:write")
    job_or_response = _require_job_access(job_manager.get(job_id), principal)
    if isinstance(job_or_response, JSONResponse):
        return job_or_response
    job = job_or_response
    job.request_stop()
    stopped_runs = _stop_product_eval_runs(db, job, principal)
    payload = _job_payload(job, db=db, principal=principal)
    payload["stopped_qym_runs"] = stopped_runs
    return JSONResponse(_ok(payload))


@router.post("/{identifier}/stop")
def stop_product_eval(
    identifier: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_api_key_principal),
) -> JSONResponse:
    require_api_key_scope(principal, "runs:write")

    if _is_eval_id(identifier):
        job = job_manager.get(identifier)
        if job is not None:
            job_or_response = _require_job_access(job, principal)
            if isinstance(job_or_response, JSONResponse):
                return job_or_response
            job_or_response.request_stop()
            stopped_runs = _stop_product_eval_runs(db, job_or_response, principal)
            payload = _job_payload(job_or_response, db=db, principal=principal)
            payload["stopped_qym_runs"] = stopped_runs
            return JSONResponse(_ok(payload))

        runs = _runs_for_eval_id(db, principal, identifier)
        if not runs:
            return _error_response(404, "not_found", "Eval not found")
        stopped_runs = _stop_runs(db, runs)
        payload = _db_eval_payload(db, identifier, runs)
        payload["stopped_qym_runs"] = stopped_runs
        return JSONResponse(_ok(payload))

    run = _require_run_access(db, principal, identifier)

    job = job_manager.get_by_qym_run_id(identifier)
    if job is not None:
        job_or_response = _require_job_access(job, principal)
        if isinstance(job_or_response, JSONResponse):
            return job_or_response
        job_or_response.request_stop()
        stopped_runs = _stop_product_eval_runs(db, job_or_response, principal)
        if run.status not in {
            RunWorkflowStatus.COMPLETED,
            RunWorkflowStatus.FAILED,
            RunWorkflowStatus.STOPPED,
        }:
            run = _require_run_access(db, principal, identifier)
            _mark_run_stopped(db, run)
            stopped_runs += 1
        payload = _job_payload(job_or_response, db=db, principal=principal)
        payload["stopped_qym_runs"] = stopped_runs
        return JSONResponse(_ok(payload))

    stopped = _mark_run_stopped(db, run)
    payload = build_product_eval_run_payload(db, run, include_items=False)
    payload["stopped"] = stopped
    return JSONResponse(_ok(payload))


@router.get("/{identifier}")
def get_product_eval(
    identifier: str,
    include_items: bool = Query(default=False),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_api_key_principal),
) -> Dict[str, Any]:
    require_api_key_scope(principal, "runs:read")
    if _is_eval_id(identifier):
        job = job_manager.get(identifier)
        if job is not None:
            job_or_response = _require_job_access(job, principal)
            if isinstance(job_or_response, JSONResponse):
                return job_or_response  # type: ignore[return-value]
            return _ok(_job_payload(job_or_response, db=db, principal=principal))
        runs = _runs_for_eval_id(db, principal, identifier)
        if not runs:
            return _error_response(404, "not_found", "Eval not found")  # type: ignore[return-value]
        return _ok(_db_eval_payload(db, identifier, runs))

    run = _require_run_access(db, principal, identifier)
    return _ok(build_product_eval_run_payload(db, run, include_items=include_items))
