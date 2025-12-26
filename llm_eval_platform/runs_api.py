from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from llm_eval_platform.auth import Principal, require_ui_principal
from llm_eval_platform.db.models import Approval, ApprovalDecision, Run, RunItem, RunItemScore, RunWorkflowStatus, UserRole
from llm_eval_platform.deps import get_db


router = APIRouter()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _sdk_static_ui_index() -> Path:
    return _repo_root() / "llm_eval" / "_static" / "ui" / "index.html"


def _sdk_static_dashboard_index() -> Path:
    return _repo_root() / "llm_eval" / "_static" / "dashboard" / "index.html"


def _iso(dt: Optional[datetime]) -> str:
    return (dt or datetime.utcnow()).isoformat()


def _compute_run_summary(db: Session, run: Run) -> Dict[str, Any]:
    items: List[RunItem] = db.query(RunItem).filter(RunItem.run_id == run.id).order_by(RunItem.index.asc()).all()
    total_items = len(items)
    error_items = {it.item_id for it in items if it.error}
    error_count = len(error_items)
    success_count = total_items - error_count

    # Avg latency across all items that have latency
    latencies = [it.latency_ms for it in items if it.latency_ms is not None]
    avg_latency_ms = float(sum(latencies) / len(latencies)) if latencies else 0.0

    metrics = list(run.metrics or [])
    metric_averages: Dict[str, float] = {m: 0.0 for m in metrics}
    if metrics and total_items:
        # Pull all scores for this run
        scores = db.query(RunItemScore).filter(RunItemScore.run_id == run.id).all()
        by_item_metric: Dict[tuple[str, str], RunItemScore] = {(s.item_id, s.metric_name): s for s in scores}
        for m in metrics:
            ssum = 0.0
            scount = 0
            for it in items:
                if it.item_id in error_items:
                    ssum += 0.0
                    scount += 1
                    continue
                s = by_item_metric.get((it.item_id, m))
                if s and s.score_numeric is not None:
                    ssum += float(s.score_numeric)
                    scount += 1
            metric_averages[m] = (ssum / scount) if scount else 0.0

    return {
        "run_id": run.id,
        "task_name": run.task,
        "model_name": run.model or "",
        "dataset_name": run.dataset,
        "timestamp": _iso(run.started_at or run.created_at),
        "file_path": run.id,  # legacy UI uses file_path as opaque identifier
        "metrics": metrics,
        "metric_averages": metric_averages,
        "total_items": total_items,
        "success_count": success_count,
        "error_count": error_count,
        "success_rate": (success_count / total_items) if total_items else 0.0,
        "avg_latency_ms": avg_latency_ms,
        "langfuse_url": run.run_metadata.get("langfuse_url") if isinstance(run.run_metadata, dict) else None,
        "langfuse_dataset_id": run.run_metadata.get("langfuse_dataset_id") if isinstance(run.run_metadata, dict) else None,
        "langfuse_run_id": run.run_metadata.get("langfuse_run_id") if isinstance(run.run_metadata, dict) else None,
        "status": run.status,
    }


@router.get("/")
def dashboard_index() -> FileResponse:
    idx = _sdk_static_dashboard_index()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Dashboard UI not found")
    return FileResponse(str(idx), media_type="text/html; charset=utf-8")


@router.get("/run/{run_id:path}")
def run_ui(run_id: str) -> FileResponse:
    # Serve the existing run UI index; it will call /api/runs/{run_id} in dashboard-mode.
    idx = _sdk_static_ui_index()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Run UI not found")
    return FileResponse(str(idx), media_type="text/html; charset=utf-8")


@router.get("/api/runs")
def legacy_list_runs(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    # Visibility (v0):
    # - EMPLOYEE: own runs
    # - MANAGER: all runs (subtree enforcement will be added once org_closure is populated)
    # - GM/VP: approved runs only
    q = db.query(Run).order_by(Run.created_at.desc())
    if principal.user.role == UserRole.EMPLOYEE:
        q = q.filter(Run.owner_user_id == principal.user.id)
    elif principal.user.role in {UserRole.GM, UserRole.VP}:
        q = q.filter(Run.status == RunWorkflowStatus.APPROVED)
    runs = q.all()

    tasks: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for r in runs:
        summary = _compute_run_summary(db, r)
        task = summary["task_name"]
        model = summary["model_name"] or "nomodel"
        tasks.setdefault(task, {}).setdefault(model, []).append(summary)

    return {"tasks": tasks, "last_updated": datetime.utcnow().isoformat()}


@router.get("/api/runs/{run_id:path}")
def legacy_run_data(
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        return {"error": "Run not found"}
    if run.owner_user_id != principal.user.id and principal.user.role not in {UserRole.MANAGER, UserRole.GM, UserRole.VP}:
        return {"error": "Access denied"}

    items: List[RunItem] = db.query(RunItem).filter(RunItem.run_id == run.id).order_by(RunItem.index.asc()).all()
    metrics = list(run.metrics or [])

    # Build per-item score/meta for UI
    scores = db.query(RunItemScore).filter(RunItemScore.run_id == run.id).all()
    by_item: Dict[str, Dict[str, RunItemScore]] = {}
    for s in scores:
        by_item.setdefault(s.item_id, {})[s.metric_name] = s

    ui_rows = []
    stats = {"total": len(items), "completed": 0, "in_progress": 0, "pending": 0, "failed": 0}
    for it in items:
        is_error = bool(it.error)
        status = "error" if is_error else "completed"
        if is_error:
            stats["failed"] += 1
        else:
            stats["completed"] += 1

        metric_values: list[Any] = []
        metric_meta: dict[str, Any] = {}
        for m in metrics:
            sc = (by_item.get(it.item_id, {}) or {}).get(m)
            if not sc:
                metric_values.append("")
                continue
            val = sc.score_raw
            if sc.score_numeric is not None:
                val = sc.score_numeric
            metric_values.append(val)
            if sc.meta:
                metric_meta[m] = sc.meta

        ui_rows.append(
            {
                "index": it.index,
                "item_id": it.item_id,
                "status": status,
                "input": it.input,
                "input_full": it.input,
                "output": it.output if not is_error else f"ERROR: {it.error}",
                "output_full": it.output if not is_error else f"ERROR: {it.error}",
                "expected": it.expected,
                "expected_full": it.expected,
                "time": "" if it.latency_ms is None else f"{(it.latency_ms or 0)/1000.0:.3f}",
                "latency_ms": it.latency_ms or 0,
                "trace_id": it.trace_id or "",
                "trace_url": it.trace_url or "",
                "metric_values": metric_values,
                "metric_meta": metric_meta,
            }
        )

    stats["success_rate"] = (stats["completed"] / stats["total"] * 100.0) if stats["total"] else 0.0

    return {
        "run": {
            "dataset_name": run.dataset,
            "run_name": run.id,
            "metric_names": metrics,
            "config": run.run_config,
            "metadata": run.run_metadata,
            "langfuse_host": run.run_metadata.get("langfuse_host", "") if isinstance(run.run_metadata, dict) else "",
            "langfuse_project_id": run.run_metadata.get("langfuse_project_id", "") if isinstance(run.run_metadata, dict) else "",
        },
        "snapshot": {"rows": ui_rows, "stats": stats, "metric_names": metrics},
    }


@router.post("/v1/runs/{run_id}/submit")
def submit_run(
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.owner_user_id != principal.user.id:
        raise HTTPException(status_code=403, detail="Only owner can submit")
    run.status = RunWorkflowStatus.SUBMITTED
    approval = db.query(Approval).filter(Approval.run_id == run.id).first()
    if not approval:
        approval = Approval(run_id=run.id, submitted_by_user_id=principal.user.id)
        db.add(approval)
    db.commit()
    return {"ok": True, "status": run.status}


class DecisionRequest(JSONResponse):
    pass


@router.post("/v1/runs/{run_id}/approve")
def approve_run(
    run_id: str,
    body: Dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    if principal.user.role != UserRole.MANAGER:
        raise HTTPException(status_code=403, detail="Manager only")
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != RunWorkflowStatus.SUBMITTED:
        raise HTTPException(status_code=400, detail="Run not submitted")
    approval = db.query(Approval).filter(Approval.run_id == run.id).first()
    if not approval:
        raise HTTPException(status_code=400, detail="Missing approval record")
    approval.decision = ApprovalDecision.APPROVED
    approval.decision_by_user_id = principal.user.id
    approval.decision_at = datetime.utcnow()
    approval.comment = str(body.get("comment") or "")
    run.status = RunWorkflowStatus.APPROVED
    db.commit()
    return {"ok": True, "status": run.status}


@router.post("/v1/runs/{run_id}/reject")
def reject_run(
    run_id: str,
    body: Dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    if principal.user.role != UserRole.MANAGER:
        raise HTTPException(status_code=403, detail="Manager only")
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != RunWorkflowStatus.SUBMITTED:
        raise HTTPException(status_code=400, detail="Run not submitted")
    approval = db.query(Approval).filter(Approval.run_id == run.id).first()
    if not approval:
        raise HTTPException(status_code=400, detail="Missing approval record")
    approval.decision = ApprovalDecision.REJECTED
    approval.decision_by_user_id = principal.user.id
    approval.decision_at = datetime.utcnow()
    approval.comment = str(body.get("comment") or "")
    run.status = RunWorkflowStatus.REJECTED
    db.commit()
    return {"ok": True, "status": run.status}


