from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from qym_platform.auth import Principal, require_ui_principal
from qym_platform.db.models import (
    Approval,
    ApprovalDecision,
    OrgUnit,
    OrgUnitClosure,
    OrgUnitType,
    PlatformSetting,
    Run,
    RunEvent,
    RunItem,
    RunItemScore,
    RunWorkflowStatus,
    User,
    UserRole,
)
from qym_platform.deps import get_db


router = APIRouter()

_LANGFUSE_URL_RE = re.compile(r"(https?://[^/]+)/project/([^/]+)")


def _stringify(val: Any) -> str:
    """Convert a value to a display string; dicts/lists become pretty JSON."""
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, (dict, list)):
        return json.dumps(val, indent=2, ensure_ascii=False)
    return str(val)


def _strip_model_provider(model_name: str) -> str:
    """Normalize 'provider/model' -> 'model' for consistent display."""
    if not model_name:
        return model_name
    idx = model_name.find("/")
    return model_name[idx + 1:] if idx > 0 else model_name


def _extract_langfuse_ids(run_metadata: dict) -> tuple[str, str]:
    """Extract (host, project_id) from langfuse_url stored in run metadata.

    The SDK sends langfuse_url like ``https://cloud.langfuse.com/project/<id>/datasets/...``
    but does NOT explicitly send ``langfuse_host`` or ``langfuse_project_id``.
    """
    langfuse_url = run_metadata.get("langfuse_url", "") if isinstance(run_metadata, dict) else ""
    host = run_metadata.get("langfuse_host", "") if isinstance(run_metadata, dict) else ""
    project_id = run_metadata.get("langfuse_project_id", "") if isinstance(run_metadata, dict) else ""
    if langfuse_url and (not host or not project_id):
        m = _LANGFUSE_URL_RE.match(langfuse_url)
        if m:
            host = host or m.group(1)
            project_id = project_id or m.group(2)
    return host, project_id


def _platform_static_dir() -> Path:
    """Return the platform static directory."""
    return Path(__file__).resolve().parent.parent / "_static"


def _platform_static_ui_index() -> Path:
    return _platform_static_dir() / "ui" / "index.html"


def _platform_static_dashboard_index() -> Path:
    return _platform_static_dir() / "dashboard" / "index.html"


def _platform_static_dashboard_compare() -> Path:
    return _platform_static_dir() / "dashboard" / "compare.html"


def _platform_static_profile_index() -> Path:
    return _platform_static_dir() / "dashboard" / "profile.html"


def _platform_static_admin_index() -> Path:
    return _platform_static_dir() / "dashboard" / "admin.html"


def _platform_static_dashboard_run() -> Path:
    return _platform_static_dir() / "dashboard" / "run.html"


def _get_setting(db: Session, key: str, default: str = "") -> str:
    """Get a platform setting value."""
    row = db.query(PlatformSetting).filter(PlatformSetting.key == key).first()
    return row.value if row else default


def _user_team_subtree_ids(db: Session, user: User) -> set[str]:
    """Get all org unit IDs in the user's team's subtree (ancestors)."""
    if not user.team_unit_id:
        return set()
    # Get all ancestors of the user's team (including the team itself)
    closures = db.query(OrgUnitClosure).filter(OrgUnitClosure.descendant_id == user.team_unit_id).all()
    return {c.ancestor_id for c in closures}


def _manager_team_ids(db: Session, manager_user_id: str) -> set[str]:
    """Get all team IDs where this user is the manager."""
    teams = db.query(OrgUnit).filter(
        OrgUnit.type == OrgUnitType.TEAM,
        OrgUnit.manager_user_id == manager_user_id
    ).all()
    return {t.id for t in teams}


def _can_approve_run(db: Session, principal: Principal, run: Run) -> bool:
    """Check if the principal can approve/reject this run."""
    # Must be authenticated
    if principal.auth_type == "none":
        return False
    # Get the run owner's team
    owner = db.query(User).filter(User.id == run.owner_user_id).first()
    if not owner or not owner.team_unit_id:
        return False
    # Get the team
    team = db.query(OrgUnit).filter(OrgUnit.id == owner.team_unit_id).first()
    if not team:
        return False
    # Only the team's manager can approve
    return team.manager_user_id == principal.user.id


def _iso(dt: Optional[datetime]) -> str:
    return (dt or datetime.utcnow()).isoformat()


def _compute_run_summary(db: Session, run: Run) -> Dict[str, Any]:
    items: List[RunItem] = db.query(RunItem).filter(RunItem.run_id == run.id).order_by(RunItem.index.asc()).all()
    total_items = len(items)
    error_items = {it.item_id for it in items if it.error}
    error_count = len(error_items)
    success_count = total_items - error_count
    completed_count = len([it for it in items if (it.output is not None) or (it.error is not None)])

    expected_total = None
    if isinstance(run.run_metadata, dict):
        try:
            if run.run_metadata.get("total_items") is not None:
                expected_total = int(run.run_metadata["total_items"])
        except Exception:
            expected_total = None

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

    # Get owner user info
    owner = db.query(User).filter(User.id == run.owner_user_id).first()
    owner_info = None
    if owner:
        owner_info = {
            "id": owner.id,
            "email": owner.email,
            "display_name": owner.display_name or owner.email.split("@")[0],
        }

    # Get approval info if exists
    approval_info = None
    approval = db.query(Approval).filter(Approval.run_id == run.id).first()
    if approval:
        decision_by = None
        if approval.decision_by_user_id:
            decision_user = db.query(User).filter(User.id == approval.decision_by_user_id).first()
            if decision_user:
                decision_by = {
                    "id": decision_user.id,
                    "email": decision_user.email,
                    "display_name": decision_user.display_name or decision_user.email.split("@")[0],
                }
        approval_info = {
            "decision": approval.decision.value if approval.decision else None,
            "decision_at": _iso(approval.decision_at) if approval.decision_at else None,
            "decision_by": decision_by,
            "comment": approval.comment or "",
        }

    # Derive run_name: prefer run_config.run_name, then external_run_id, then run.id
    run_name = ""
    if isinstance(run.run_config, dict):
        run_name = run.run_config.get("run_name", "")
    if not run_name:
        run_name = run.external_run_id or ""

    return {
        "run_id": run.id,
        "run_name": run_name,
        "external_run_id": run.external_run_id or "",
        "task_name": run.task,
        "model_name": _strip_model_provider(run.model or ""),
        "dataset_name": run.dataset,
        "timestamp": _iso(run.started_at or run.created_at),
        "file_path": run.id,  # legacy UI uses file_path as opaque identifier
        "metrics": metrics,
        "metric_averages": metric_averages,
        "total_items": total_items,
        # Progress signals for list view (esp. RUNNING).
        "progress_completed": completed_count,
        "progress_total": expected_total,
        "progress_pct": (completed_count / expected_total) if expected_total else None,
        "success_count": success_count,
        "error_count": error_count,
        "success_rate": (success_count / total_items) if total_items else 0.0,
        "avg_latency_ms": avg_latency_ms,
        "langfuse_url": run.run_metadata.get("langfuse_url") if isinstance(run.run_metadata, dict) else None,
        "langfuse_dataset_id": run.run_metadata.get("langfuse_dataset_id") if isinstance(run.run_metadata, dict) else None,
        "langfuse_run_id": run.run_metadata.get("langfuse_run_id") if isinstance(run.run_metadata, dict) else None,
        "status": run.status,
        "run_config": run.run_config if isinstance(run.run_config, dict) else {},
        "owner": owner_info,
        "approval": approval_info,
    }


@router.get("/")
def dashboard_index() -> FileResponse:
    idx = _platform_static_dashboard_index()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Dashboard UI not found")
    return FileResponse(str(idx), media_type="text/html; charset=utf-8")


@router.get("/profile")
def profile_index() -> FileResponse:
    idx = _platform_static_profile_index()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Profile UI not found")
    return FileResponse(str(idx), media_type="text/html; charset=utf-8")


@router.get("/admin")
def admin_index() -> FileResponse:
    idx = _platform_static_admin_index()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Admin UI not found")
    return FileResponse(str(idx), media_type="text/html; charset=utf-8")


@router.get("/compare")
def compare_index() -> FileResponse:
    idx = _platform_static_dashboard_compare()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Compare UI not found")
    return FileResponse(str(idx), media_type="text/html; charset=utf-8")


@router.get("/admin")
def admin_index() -> FileResponse:
    idx = _platform_static_admin_index()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Admin UI not found")
    return FileResponse(str(idx), media_type="text/html; charset=utf-8")


@router.get("/run/{run_id:path}")
def run_ui(run_id: str) -> FileResponse:
    idx = _platform_static_dashboard_run()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Run UI not found")
    return FileResponse(str(idx), media_type="text/html; charset=utf-8")


@router.get("/api/runs")
def legacy_list_runs(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """List runs with visibility based on role and org structure.

    Visibility rules:
    - ADMIN: all runs (platform administration)
    - EMPLOYEE: own runs only
    - MANAGER: runs from their managed team(s)
    - GM/VP: approved runs only in their subtree (configurable via policy)
    - Local dev mode (auth_type == "none"): show everything
    """
    q = db.query(Run).order_by(Run.created_at.desc())

    # Local dev mode: show everything to reduce friction
    if principal.auth_type == "none":
        runs = q.all()
    elif principal.user.role == UserRole.ADMIN:
        # Admin sees all runs
        runs = q.all()
    elif principal.user.role == UserRole.EMPLOYEE:
        # Employee sees only their own runs
        runs = q.filter(Run.owner_user_id == principal.user.id).all()
    elif principal.user.role == UserRole.MANAGER:
        # Manager sees runs from their managed team(s)
        managed_team_ids = _manager_team_ids(db, principal.user.id)
        if managed_team_ids:
            # Get users in those teams
            team_users = db.query(User.id).filter(User.team_unit_id.in_(managed_team_ids)).all()
            team_user_ids = {u.id for u in team_users}
            # Include manager's own runs too
            team_user_ids.add(principal.user.id)
            runs = q.filter(Run.owner_user_id.in_(team_user_ids)).all()
        else:
            # No managed teams, show only own runs
            runs = q.filter(Run.owner_user_id == principal.user.id).all()
    elif principal.user.role in {UserRole.GM, UserRole.VP}:
        # GM/VP: approved runs only by default (can be relaxed via policy)
        gm_vp_approved_only = _get_setting(db, "gm_vp_approved_only", "true").lower() == "true"
        if gm_vp_approved_only:
            runs = q.filter(Run.status == RunWorkflowStatus.APPROVED).all()
        else:
            # Show SUBMITTED and APPROVED
            runs = q.filter(Run.status.in_([RunWorkflowStatus.SUBMITTED, RunWorkflowStatus.APPROVED])).all()
    else:
        # Fallback: own runs only
        runs = q.filter(Run.owner_user_id == principal.user.id).all()

    tasks: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for r in runs:
        summary = _compute_run_summary(db, r)
        task = summary["task_name"]
        model = summary["model_name"] or "nomodel"
        tasks.setdefault(task, {}).setdefault(model, []).append(summary)

    return {"tasks": tasks, "last_updated": datetime.utcnow().isoformat()}


@router.get("/api/compare")
def legacy_compare(
    files: List[str] = Query(default=[]),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Return multiple run snapshots for comparison.

    The static dashboard expects query param(s) named `files` containing opaque run identifiers.
    In the platform, `file_path` is the run_id, so we accept run IDs here.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files specified")
    run_ids: list[str] = []
    for f in files:
        for part in str(f).split(","):
            p = part.strip()
            if p:
                run_ids.append(p)

    runs_data: list[dict[str, Any]] = []
    for run_id in run_ids:
        data = legacy_run_data(run_id=run_id, db=db, principal=principal)
        if not data.get("error"):
            runs_data.append(data)

    # Top-level Langfuse config from env vars
    lf_host = os.getenv("LANGFUSE_HOST", "")
    lf_project_id = os.getenv("LANGFUSE_PROJECT_ID", "")
    # Fallback: extract from the first run's langfuse_url if env vars are incomplete
    if (not lf_host or not lf_project_id) and runs_data:
        first_run = runs_data[0].get("run", {})
        lf_host = lf_host or first_run.get("langfuse_host", "")
        lf_project_id = lf_project_id or first_run.get("langfuse_project_id", "")

    return {
        "runs": runs_data,
        "langfuse_host": lf_host,
        "langfuse_project_id": lf_project_id,
    }


def _can_view_run(db: Session, principal: Principal, run: Run) -> bool:
    """Check if the principal can view this run based on visibility rules."""
    # Local dev mode: allow all
    if principal.auth_type == "none":
        return True

    # Admin can view all
    if principal.user.role == UserRole.ADMIN:
        return True

    # Owner can always view their own runs
    if run.owner_user_id == principal.user.id:
        return True

    # Manager can view runs from their managed teams
    if principal.user.role == UserRole.MANAGER:
        owner = db.query(User).filter(User.id == run.owner_user_id).first()
        if owner and owner.team_unit_id:
            managed_team_ids = _manager_team_ids(db, principal.user.id)
            if owner.team_unit_id in managed_team_ids:
                return True
        return False

    # GM/VP can view approved runs (or submitted if policy allows)
    if principal.user.role in {UserRole.GM, UserRole.VP}:
        gm_vp_approved_only = _get_setting(db, "gm_vp_approved_only", "true").lower() == "true"
        if gm_vp_approved_only:
            return run.status == RunWorkflowStatus.APPROVED
        else:
            return run.status in {RunWorkflowStatus.SUBMITTED, RunWorkflowStatus.APPROVED}

    return False


def _can_approve_run(db: Session, principal: Principal, run: Run) -> bool:
    """Check if the principal can approve/reject this run (must be the team's manager or admin)."""
    # Local dev mode: allow all
    if principal.auth_type == "none":
        return True

    # Admin can approve all
    if principal.user.role == UserRole.ADMIN:
        return True

    # Only managers can approve
    if principal.user.role != UserRole.MANAGER:
        return False

    # Manager must be the team manager for the run owner's team
    owner = db.query(User).filter(User.id == run.owner_user_id).first()
    if not owner or not owner.team_unit_id:
        return False

    managed_team_ids = _manager_team_ids(db, principal.user.id)
    return owner.team_unit_id in managed_team_ids


@router.get("/api/runs/{run_id:path}")
def legacy_run_data(
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        return {"error": "Run not found"}
    if not _can_view_run(db, principal, run):
        return {"error": "Access denied"}

    items: List[RunItem] = db.query(RunItem).filter(RunItem.run_id == run.id).order_by(RunItem.index.asc()).all()
    metrics = list(run.metrics or [])

    # Build per-item score/meta for UI
    scores = db.query(RunItemScore).filter(RunItemScore.run_id == run.id).all()
    by_item: Dict[str, Dict[str, RunItemScore]] = {}
    for s in scores:
        by_item.setdefault(s.item_id, {})[s.metric_name] = s

    # Fallback timestamps: for items missing task_started_at_ms in item_metadata,
    # look up the item_started event's sent_at timestamp as an approximation.
    _item_start_ts: Dict[str, int] = {}
    need_ts = any(
        not (isinstance(it.item_metadata, dict) and it.item_metadata.get("task_started_at_ms"))
        for it in items
    )
    if need_ts:
        started_events: List[RunEvent] = (
            db.query(RunEvent)
            .filter(RunEvent.run_id == run.id, RunEvent.type == "item_started")
            .all()
        )
        for ev in started_events:
            payload = ev.payload or {}
            iid = payload.get("item_id")
            if iid and ev.sent_at:
                _item_start_ts[iid] = int(ev.sent_at.timestamp() * 1000)

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

        # Resolve task_started_at_ms: prefer item_metadata, then fallback to event timestamp
        ts_ms = it.item_metadata.get("task_started_at_ms") if isinstance(it.item_metadata, dict) else None
        if not ts_ms:
            ts_ms = _item_start_ts.get(it.item_id)

        ui_rows.append(
            {
                "index": it.index,
                "item_id": it.item_id,
                "status": status,
                "input": _stringify(it.input),
                "input_full": _stringify(it.input),
                "output": _stringify(it.output) if not is_error else f"ERROR: {it.error}",
                "output_full": _stringify(it.output) if not is_error else f"ERROR: {it.error}",
                "expected": _stringify(it.expected),
                "expected_full": _stringify(it.expected),
                "time": "" if it.latency_ms is None else f"{(it.latency_ms or 0)/1000.0:.3f}",
                "latency_ms": it.latency_ms or 0,
                "trace_id": it.trace_id or "",
                "trace_url": it.trace_url or "",
                "task_started_at_ms": ts_ms,
                "metric_values": metric_values,
                "metric_meta": metric_meta,
                "item_metadata": it.item_metadata if isinstance(it.item_metadata, dict) else {},
            }
        )

    stats["success_rate"] = (stats["completed"] / stats["total"] * 100.0) if stats["total"] else 0.0

    # Extract Langfuse host/project_id from run metadata (langfuse_url fallback)
    lf_host, lf_project_id = _extract_langfuse_ids(run.run_metadata or {})

    return {
        "run": {
            "file_path": run.id,
            "dataset_name": run.dataset,
            "run_name": run.external_run_id or run.id,
            "metric_names": metrics,
            "config": run.run_config,
            "metadata": run.run_metadata,
            "status": run.status,
            "langfuse_host": lf_host,
            "langfuse_project_id": lf_project_id,
        },
        "snapshot": {"rows": ui_rows, "stats": stats, "metric_names": metrics},
    }


@router.post("/api/runs/update_metric")
def update_metric(
    request: Dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Update a single metric score for a run item."""
    file_path = request.get("file_path")
    row_index = request.get("row_index")
    metric_name = request.get("metric_name")
    new_score = request.get("new_score")

    if not file_path or metric_name is None or row_index is None:
        raise HTTPException(status_code=400, detail="file_path, row_index, and metric_name required")

    run = db.query(Run).filter(Run.id == file_path).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Find the item by index
    item = (
        db.query(RunItem)
        .filter(RunItem.run_id == run.id, RunItem.index == int(row_index))
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Find or create the score record
    score_record = (
        db.query(RunItemScore)
        .filter(
            RunItemScore.run_id == run.id,
            RunItemScore.item_id == item.item_id,
            RunItemScore.metric_name == metric_name,
        )
        .first()
    )

    if not score_record:
        score_record = RunItemScore(
            run_id=run.id,
            item_id=item.item_id,
            metric_name=metric_name,
            meta={},
        )
        db.add(score_record)

    # Store original score in meta if not already stored
    meta = dict(score_record.meta or {})
    if "original_score" not in meta:
        meta["original_score"] = score_record.score_raw if score_record.score_raw is not None else score_record.score_numeric
    meta["modified"] = "true"
    score_record.meta = meta

    # Update the score
    try:
        numeric_val = float(new_score)
        score_record.score_numeric = numeric_val
        score_record.score_raw = numeric_val
    except (ValueError, TypeError):
        score_record.score_numeric = None
        score_record.score_raw = new_score

    db.commit()

    # Build the updated row response matching the compare API format
    metrics = list(run.metrics or [])
    all_scores = db.query(RunItemScore).filter(
        RunItemScore.run_id == run.id, RunItemScore.item_id == item.item_id
    ).all()
    score_map = {s.metric_name: s for s in all_scores}

    metric_values: list[Any] = []
    metric_meta: dict[str, Any] = {}
    for m in metrics:
        sc = score_map.get(m)
        if not sc:
            metric_values.append("")
            continue
        val = sc.score_raw
        if sc.score_numeric is not None:
            val = sc.score_numeric
        metric_values.append(val)
        if sc.meta:
            metric_meta[m] = sc.meta

    is_error = bool(item.error)
    status = "error" if is_error else "completed"

    row = {
        "index": item.index,
        "item_id": item.item_id,
        "status": status,
        "input": item.input,
        "input_full": item.input,
        "output": item.output if not is_error else f"ERROR: {item.error}",
        "output_full": item.output if not is_error else f"ERROR: {item.error}",
        "expected": item.expected,
        "expected_full": item.expected,
        "time": "" if item.latency_ms is None else f"{(item.latency_ms or 0)/1000.0:.3f}",
        "latency_ms": item.latency_ms or 0,
        "trace_id": item.trace_id or "",
        "trace_url": item.trace_url or "",
        "task_started_at_ms": item.item_metadata.get("task_started_at_ms") if isinstance(item.item_metadata, dict) else None,
        "metric_values": metric_values,
        "metric_meta": metric_meta,
        "item_metadata": item.item_metadata if isinstance(item.item_metadata, dict) else {},
    }

    return {"ok": True, "row": row}


@router.post("/api/runs/update_root_cause")
def update_root_cause(
    request: Dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Update root_cause in item_metadata for a single run's item."""
    item_id = request.get("item_id")
    root_cause = (request.get("root_cause") or "").strip()
    run_id = request.get("run_id")

    if not item_id or not run_id:
        raise HTTPException(status_code=400, detail="item_id and run_id required")

    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    item = (
        db.query(RunItem)
        .filter(RunItem.run_id == run.id, RunItem.item_id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    meta = dict(item.item_metadata) if isinstance(item.item_metadata, dict) else {}
    if root_cause:
        meta["root_cause"] = root_cause
    else:
        meta.pop("root_cause", None)
    item.item_metadata = meta

    db.commit()
    return {"ok": True}


@router.post("/api/runs/delete")
def delete_run(
    request: Dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Delete a run and all associated data."""
    file_path = request.get("file_path")
    if not file_path:
        raise HTTPException(status_code=400, detail="file_path required")

    run = db.query(Run).filter(Run.id == file_path).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Admin can always delete
    if principal.user.role == UserRole.ADMIN:
        pass
    # Owner can delete their own runs
    elif run.owner_user_id == principal.user.id:
        pass
    # Manager can delete runs from their managed teams
    elif principal.user.role == UserRole.MANAGER:
        owner = db.query(User).filter(User.id == run.owner_user_id).first()
        if not owner or not owner.team_unit_id:
            raise HTTPException(status_code=403, detail="Permission denied")
        managed_team_ids = _manager_team_ids(db, principal.user.id)
        if owner.team_unit_id not in managed_team_ids:
            raise HTTPException(status_code=403, detail="Permission denied")
    else:
        raise HTTPException(status_code=403, detail="Permission denied")

    # Delete related data first (foreign key constraints)
    db.query(RunItemScore).filter(RunItemScore.run_id == run.id).delete()
    db.query(RunItem).filter(RunItem.run_id == run.id).delete()
    db.query(RunEvent).filter(RunEvent.run_id == run.id).delete()
    db.query(Approval).filter(Approval.run_id == run.id).delete()
    db.delete(run)
    db.commit()

    return {"ok": True}


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
    # Allow submitting completed/failed runs for the approval workflow.
    if run.status in {RunWorkflowStatus.APPROVED, RunWorkflowStatus.REJECTED, RunWorkflowStatus.SUBMITTED}:
        raise HTTPException(status_code=400, detail=f"Run not submittable from status={run.status}")
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
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != RunWorkflowStatus.SUBMITTED:
        raise HTTPException(status_code=400, detail="Run not submitted")
    # Check if the principal can approve this run (must be the team's manager)
    if not _can_approve_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Only the team manager can approve")
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
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != RunWorkflowStatus.SUBMITTED:
        raise HTTPException(status_code=400, detail="Run not submitted")
    # Check if the principal can reject this run (must be the team's manager)
    if not _can_approve_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Only the team manager can reject")
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


