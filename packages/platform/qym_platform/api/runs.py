from __future__ import annotations

import json
import os
import re
from html import escape
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from qym_platform.auth import Principal, require_ui_principal
from qym_platform.auth_oidc import (
    get_session_user_and_provider,
    request_root_path,
    sanitize_next,
    session_auth_enabled,
    with_root_path,
)
from qym_platform.datetime_utils import to_api_timestamp, utc_now_naive
from qym_platform.db.models import (
    Approval,
    ApprovalDecision,
    AuditLog,
    Project,
    ProjectMembership,
    ReviewCorrection,
    RootCauseRevision,
    Run,
    RunEvent,
    RunItem,
    RunItemAttempt,
    RunItemScore,
    RunWorkflowStatus,
    Span,
    User,
    UserRole,
)
from qym_platform.deps import get_db
from qym_platform.item_identity import build_compare_identity, finalize_compare_alignment
from qym_platform.permissions import (
    can_approve_run as permission_can_approve_run,
    can_delete_run,
    can_modify_run,
    can_view_run,
    has_project_access,
)
from qym_platform.services.run_lifecycle import reconcile_stale_running_run
from qym_platform.services.root_cause_changes import apply_root_cause_change
from qym_platform.settings import PlatformSettings


router = APIRouter()

_LANGFUSE_URL_RE = re.compile(r"(https?://[^/]+)/project/([^/]+)")


def _median(values: List[Optional[float]]) -> float:
    numeric = sorted(float(v) for v in values if v is not None)
    if not numeric:
        return 0.0
    mid = len(numeric) // 2
    if len(numeric) % 2 == 0:
        return (numeric[mid - 1] + numeric[mid]) / 2.0
    return numeric[mid]


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


def _dashboard_html_response(idx: Path, request: Request) -> HTMLResponse:
    """Serve a dashboard HTML page, rewriting absolute asset paths and
    injecting ``window.__QYM_ROOT_PATH__`` so client-side JS can build
    correct URLs when the platform is mounted under a sub-path (e.g. ``/qym``)."""
    html = idx.read_text(encoding="utf-8")
    root = request_root_path(request)
    if root:
        html = html.replace('="/static/', f'="{root}/static/')
        html = html.replace("='/static/", f"='{root}/static/")
        html = html.replace('="/ui/', f'="{root}/ui/')
        html = html.replace("='/ui/", f"='{root}/ui/")
    injection = f'<script>window.__QYM_ROOT_PATH__ = {json.dumps(root)};</script>'
    if "<head>" in html:
        html = html.replace("<head>", "<head>\n  " + injection, 1)
    else:
        html = injection + html
    return HTMLResponse(html, media_type="text/html; charset=utf-8")


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


def _platform_static_project_settings() -> Path:
    return _platform_static_dir() / "dashboard" / "project_settings.html"


def _platform_static_overview() -> Path:
    return _platform_static_dir() / "dashboard" / "overview.html"


def _platform_static_projects() -> Path:
    return _platform_static_dir() / "dashboard" / "projects.html"


def _platform_static_charts() -> Path:
    return _platform_static_dir() / "dashboard" / "charts.html"


def _platform_static_models() -> Path:
    return _platform_static_dir() / "dashboard" / "models.html"


def _project_path_prefix(request: Request, project_slug: str) -> str:
    path = request.url.path
    marker = f"/projects/{project_slug}"
    idx = path.find(marker)
    if idx < 0:
        return ""
    return path[:idx]


def _resolve_project_by_slug_for_ui(db: Session, principal: Principal, project_slug: str) -> Project:
    project = db.query(Project).filter(Project.slug == project_slug, Project.is_active.is_(True)).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not has_project_access(db, principal, project.id):
        raise HTTPException(status_code=403, detail="Access denied")
    return project


def _maybe_redirect_to_login(request: Request, db: Session) -> Optional[RedirectResponse]:
    settings = PlatformSettings()
    if not session_auth_enabled(settings):
        return None
    if get_session_user_and_provider(db, request):
        return None
    root = request_root_path(request)
    # ``request.url.path`` already includes ``root_path`` under a Starlette mount,
    # so do NOT prepend it again here. Only the redirect target needs the prefix.
    full_path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    next_value = sanitize_next(full_path, default=(root + "/") if root else "/")
    return RedirectResponse(url=f"{root}/login?next={next_value}", status_code=303)


def _project_not_found_page(request: Request, project_slug: str) -> HTMLResponse:
    prefix = _project_path_prefix(request, project_slug).rstrip("/")
    static_root = f"{prefix}/static" if prefix else "/static"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>قيِّم • Project Not Found</title>
  <link rel="icon" type="image/png" href="{static_root}/qym_icon.png">
  <link rel="stylesheet" href="{static_root}/dashboard.css">
  <link rel="stylesheet" href="{static_root}/shell.css">
  <script src="{static_root}/auth.js"></script>
  <script src="{static_root}/shell.js"></script>
</head>
<body>
  <main style="min-height:50vh;display:flex;align-items:center;justify-content:center;padding:32px;color:var(--text-muted);">
    <div>Loading project…</div>
    <noscript>
      <section style="width:min(640px,100%);background:var(--bg-surface);border:1px solid var(--border-default);border-radius:12px;padding:32px 28px;">
        <div style="font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:var(--error);margin-bottom:12px;">Missing Project</div>
        <h1 style="margin:0 0 10px 0;font-size:30px;line-height:1.15;color:var(--text-primary);">Project not found</h1>
        <p style="margin:0;color:var(--text-secondary);font-size:14px;line-height:1.65;">The requested project "{escape(project_slug)}" does not exist, is archived, or you no longer have access to it.</p>
      </section>
    </noscript>
  </main>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=404)


def _guard_project_page(request: Request, db: Session, project_slug: str) -> Optional[Any]:
    redirect = _maybe_redirect_to_login(request, db)
    if redirect:
        return redirect
    try:
        principal = require_ui_principal(
            request=request,
            db=db,
            x_user_email=request.headers.get("X-User-Email"),
            x_email=request.headers.get("X-Email"),
            x_admin_bootstrap=request.headers.get("X-Admin-Bootstrap"),
        )
        _resolve_project_by_slug_for_ui(db, principal, project_slug)
    except HTTPException as exc:
        if exc.status_code == 404:
            return _project_not_found_page(request, project_slug)
        raise
    return None


def _iso(dt: Optional[datetime]) -> str:
    return to_api_timestamp(dt or utc_now_naive()) or ""


def _reconcile_run_liveness(db: Session, runs: List[Run]) -> None:
    if not runs:
        return
    timeout_seconds = PlatformSettings().run_stale_timeout_seconds
    changed = False
    for run in runs:
        if reconcile_stale_running_run(run, timeout_seconds=timeout_seconds):
            changed = True
    if changed:
        db.commit()
        for run in runs:
            db.refresh(run)


def _serialize_span(span: Span) -> Dict[str, Any]:
    return {
        "trace_id": span.trace_id,
        "span_id": span.span_id,
        "parent_span_id": span.parent_span_id,
        "name": span.name,
        "kind": span.kind,
        "start_time_ns": span.start_time_ns,
        "end_time_ns": span.end_time_ns,
        "duration_ms": span.duration_ms,
        "status": span.status,
        "attributes": span.attributes,
        "events": span.events,
        "links": span.links or [],
    }


def _trace_time_bounds(spans: List[Span]) -> tuple[Optional[int], Optional[int]]:
    starts: list[int] = []
    ends: list[int] = []
    for span in spans:
        if span.start_time_ns is not None:
            starts.append(int(span.start_time_ns))
        if span.end_time_ns is not None:
            ends.append(int(span.end_time_ns))
        elif span.start_time_ns is not None and span.duration_ms is not None:
            ends.append(int(span.start_time_ns + (float(span.duration_ms) * 1_000_000.0)))
    if not starts or not ends:
        return None, None
    return min(starts), max(ends)


def _build_trace_summary(spans: List[Span]) -> Dict[str, Any]:
    span_ids = {s.span_id for s in spans}
    root_count = 0
    orphan_count = 0
    error_count = 0
    for span in spans:
        status = str(span.status or "").upper()
        if status == "ERROR":
            error_count += 1
        parent_id = span.parent_span_id
        if not parent_id:
            root_count += 1
        elif parent_id not in span_ids:
            root_count += 1
            orphan_count += 1

    started_at_ns, ended_at_ns = _trace_time_bounds(spans)
    duration_ms: Optional[float] = None
    if started_at_ns is not None and ended_at_ns is not None and ended_at_ns >= started_at_ns:
        duration_ms = (ended_at_ns - started_at_ns) / 1_000_000.0

    return {
        "span_count": len(spans),
        "root_count": root_count,
        "error_count": error_count,
        "duration_ms": duration_ms,
        "started_at_ns": started_at_ns,
        "ended_at_ns": ended_at_ns,
        "has_orphans": orphan_count > 0,
        "orphan_count": orphan_count,
    }


def _serialize_attempt_trace_payload(attempt: Dict[str, Any], spans: List[Span]) -> Dict[str, Any]:
    return {
        "attempt_number": attempt.get("attempt_number"),
        "status": attempt.get("status") or "failed",
        "latency_ms": attempt.get("latency_ms"),
        "task_started_at_ms": attempt.get("task_started_at_ms"),
        "trace_id": attempt.get("trace_id") or "",
        "trace_url": attempt.get("trace_url") or "",
        "error": attempt.get("error"),
        "is_last_attempt": bool(attempt.get("is_last_attempt", False)),
        "summary": _build_trace_summary(spans),
        "spans": [_serialize_span(span) for span in spans],
    }


def _build_item_trace_payload(item: RunItem, attempts: List[Dict[str, Any]]) -> Dict[str, Any]:
    retry_count = int(
        getattr(item, "retry_count", 0)
        or ((item.item_metadata or {}).get("retry_count") if isinstance(item.item_metadata, dict) else 0)
        or 0
    )
    last_attempt = attempts[-1] if attempts else None
    last_summary = (last_attempt or {}).get("summary") if isinstance(last_attempt, dict) else None
    last_spans = (last_attempt or {}).get("spans") if isinstance(last_attempt, dict) else None
    return {
        "item": {
            "run_id": item.run_id,
            "item_id": item.item_id,
            "trace_id": (last_attempt or {}).get("trace_id") or item.trace_id or "",
            "trace_url": (last_attempt or {}).get("trace_url") or item.trace_url or "",
            "retry_count": retry_count,
        },
        "summary": last_summary or _build_trace_summary([]),
        "spans": last_spans or [],
        "attempts": attempts,
    }


def _compute_run_summary(db: Session, run: Run) -> Dict[str, Any]:
    items: List[RunItem] = db.query(RunItem).filter(RunItem.run_id == run.id).order_by(RunItem.index.asc()).all()
    total_items = len(items)
    error_items = {it.item_id for it in items if it.error}
    error_count = len(error_items)
    total_retries = sum(int(it.retry_count or 0) for it in items)
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
    median_latency_ms = _median(latencies)

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

    project = db.query(Project).filter(Project.id == run.project_id).first()
    project_info = None
    if project:
        project_info = {"id": project.id, "slug": project.slug, "name": project.name}

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
        "total_retries": total_retries,
        "success_rate": (success_count / total_items) if total_items else 0.0,
        "avg_latency_ms": avg_latency_ms,
        "median_latency_ms": median_latency_ms,
        "langfuse_url": run.run_metadata.get("langfuse_url") if isinstance(run.run_metadata, dict) else None,
        "langfuse_dataset_id": run.run_metadata.get("langfuse_dataset_id") if isinstance(run.run_metadata, dict) else None,
        "langfuse_run_id": run.run_metadata.get("langfuse_run_id") if isinstance(run.run_metadata, dict) else None,
        "status": run.status,
        "run_config": run.run_config if isinstance(run.run_config, dict) else {},
        "owner": owner_info,
        "project": project_info,
        "approval": approval_info,
    }


_LIVE_RUN_STATUSES = {RunWorkflowStatus.RUNNING, RunWorkflowStatus.PENDING}


def _live_run_summary(
    run: Run,
    *,
    project: Optional[Project],
    owner: Optional[User],
    item_agg: Dict[str, Any],
) -> Dict[str, Any]:
    expected_total = None
    if isinstance(run.run_metadata, dict):
        try:
            if run.run_metadata.get("total_items") is not None:
                expected_total = int(run.run_metadata["total_items"])
        except Exception:
            expected_total = None

    completed_count = int(item_agg.get("completed") or 0)
    run_name = ""
    if isinstance(run.run_config, dict):
        run_name = str(run.run_config.get("run_name") or "")
    if not run_name:
        run_name = run.external_run_id or ""

    owner_info = None
    if owner:
        owner_info = {
            "id": owner.id,
            "email": owner.email,
            "display_name": owner.display_name or owner.email.split("@")[0],
        }

    project_info = None
    if project:
        project_info = {"id": project.id, "slug": project.slug, "name": project.name}

    return {
        "run_id": run.id,
        "run_name": run_name,
        "external_run_id": run.external_run_id or "",
        "task_name": run.task,
        "dataset_name": run.dataset,
        "model_name": _strip_model_provider(run.model or ""),
        "status": run.status.value if hasattr(run.status, "value") else str(run.status or ""),
        "timestamp": _iso(run.started_at or run.created_at),
        "started_at": _iso(run.started_at) if run.started_at else None,
        "last_event_at": _iso(run.last_event_at or run.updated_at or run.created_at),
        "progress_completed": completed_count,
        "progress_total": expected_total,
        "progress_pct": (completed_count / expected_total) if expected_total else None,
        "total_items": int(item_agg.get("total") or 0),
        "error_count": int(item_agg.get("error_count") or 0),
        "owner": owner_info,
        "project": project_info,
    }


@router.get("/", response_model=None)
def dashboard_index(request: Request, db: Session = Depends(get_db)) -> Any:
    redirect = _maybe_redirect_to_login(request, db)
    if redirect:
        return redirect
    idx = _platform_static_projects()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Projects UI not found")
    return _dashboard_html_response(idx, request)


@router.get("/projects/{project_slug}", response_model=None)
def dashboard_project_index(project_slug: str, request: Request, db: Session = Depends(get_db)) -> Any:
    guarded = _guard_project_page(request, db, project_slug)
    if guarded:
        return guarded
    idx = _platform_static_dashboard_index()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Dashboard UI not found")
    return _dashboard_html_response(idx, request)


@router.get("/profile", response_model=None)
def profile_index(request: Request, db: Session = Depends(get_db)) -> Any:
    redirect = _maybe_redirect_to_login(request, db)
    if redirect:
        return redirect
    idx = _platform_static_profile_index()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Profile UI not found")
    return _dashboard_html_response(idx, request)


@router.get("/admin", response_model=None)
def admin_index(request: Request, db: Session = Depends(get_db)) -> Any:
    redirect = _maybe_redirect_to_login(request, db)
    if redirect:
        return redirect
    idx = _platform_static_admin_index()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Admin UI not found")
    return _dashboard_html_response(idx, request)


@router.get("/compare", response_model=None)
def compare_index(request: Request, db: Session = Depends(get_db)) -> Any:
    redirect = _maybe_redirect_to_login(request, db)
    if redirect:
        return redirect
    idx = _platform_static_dashboard_compare()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Compare UI not found")
    return _dashboard_html_response(idx, request)


@router.get("/trash", response_model=None)
def trash_index(request: Request, db: Session = Depends(get_db)) -> Any:
    redirect = _maybe_redirect_to_login(request, db)
    if redirect:
        return redirect
    idx = _platform_static_dir() / "dashboard" / "trash.html"
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Trash UI not found")
    return _dashboard_html_response(idx, request)


@router.get("/reviews", response_model=None)
def reviews_index(request: Request, db: Session = Depends(get_db)) -> Any:
    redirect = _maybe_redirect_to_login(request, db)
    if redirect:
        return redirect
    idx = _platform_static_dir() / "dashboard" / "reviews.html"
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Reviews UI not found")
    return _dashboard_html_response(idx, request)


@router.get("/projects/{project_slug}/reviews", response_model=None)
def project_reviews_index(project_slug: str, request: Request, db: Session = Depends(get_db)) -> Any:
    guarded = _guard_project_page(request, db, project_slug)
    if guarded:
        return guarded
    return reviews_index(request=request, db=db)


@router.get("/projects/{project_slug}/charts", response_model=None)
def project_charts(project_slug: str, request: Request, db: Session = Depends(get_db)) -> Any:
    guarded = _guard_project_page(request, db, project_slug)
    if guarded:
        return guarded
    idx = _platform_static_charts()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Charts UI not found")
    return _dashboard_html_response(idx, request)


@router.get("/projects/{project_slug}/models", response_model=None)
def project_models(project_slug: str, request: Request, db: Session = Depends(get_db)) -> Any:
    guarded = _guard_project_page(request, db, project_slug)
    if guarded:
        return guarded
    idx = _platform_static_models()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Models UI not found")
    return _dashboard_html_response(idx, request)


@router.get("/projects/{project_slug}/overview", response_model=None)
def project_overview(project_slug: str, request: Request, db: Session = Depends(get_db)) -> Any:
    guarded = _guard_project_page(request, db, project_slug)
    if guarded:
        return guarded
    idx = _platform_static_overview()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Overview UI not found")
    return _dashboard_html_response(idx, request)


@router.get("/projects/{project_slug}/settings", response_model=None)
def project_settings_index(project_slug: str, request: Request, db: Session = Depends(get_db)) -> Any:
    guarded = _guard_project_page(request, db, project_slug)
    if guarded:
        return guarded
    idx = _platform_static_project_settings()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Project settings UI not found")
    return _dashboard_html_response(idx, request)


@router.get("/run/{run_id:path}", response_model=None)
def run_ui(run_id: str, request: Request, db: Session = Depends(get_db)) -> Any:
    redirect = _maybe_redirect_to_login(request, db)
    if redirect:
        return redirect
    idx = _platform_static_dashboard_run()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Run UI not found")
    return _dashboard_html_response(idx, request)


@router.get("/projects/{project_slug}/runs/{run_id:path}", response_model=None)
def project_run_ui(project_slug: str, run_id: str, request: Request, db: Session = Depends(get_db)) -> Any:
    guarded = _guard_project_page(request, db, project_slug)
    if guarded:
        return guarded
    return run_ui(run_id=run_id, request=request, db=db)


@router.get("/api/runs")
def legacy_list_runs(
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    project_slug: Optional[str] = Query(default=None),
    user: Optional[str] = Query(default=None, description="Filter by run owner user id, email, or display name"),
    user_id: Optional[str] = Query(default=None, description="Filter by run owner user id"),
    owner_user_id: Optional[str] = Query(default=None, description="Filter by run owner user id"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    q = Run.active(db).order_by(Run.created_at.desc())

    selected_project = None
    if project_slug:
        selected_project = db.query(Project).filter(Project.slug == project_slug, Project.is_active.is_(True)).first()
        if not selected_project:
            raise HTTPException(status_code=404, detail="Project not found")
        if not has_project_access(db, principal, selected_project.id):
            raise HTTPException(status_code=403, detail="Access denied")
    else:
        if principal.auth_type == "none" or principal.user.role == UserRole.ADMIN:
            selected_project = db.query(Project).filter(Project.is_active.is_(True)).order_by(Project.name).first()
        else:
            selected_project = (
                db.query(Project)
                .join(ProjectMembership, ProjectMembership.project_id == Project.id)
                .filter(ProjectMembership.user_id == principal.user.id, Project.is_active.is_(True))
                .order_by(Project.name)
                .first()
            )

    if selected_project:
        q = q.filter(Run.project_id == selected_project.id)
    else:
        return {
            "tasks": {},
            "last_updated": to_api_timestamp(utc_now_naive()),
            "total_count": 0,
            "project": None,
        }

    # Filter out hidden tasks
    from qym_platform.settings import PlatformSettings
    settings = PlatformSettings()
    hidden = {t.strip().lower() for t in settings.hidden_tasks.split(",") if t.strip()}
    if hidden:
        q = q.filter(~func.lower(Run.task).in_(hidden))

    user_filter = (owner_user_id or user_id or user or "").strip()
    if user_filter:
        lowered_user_filter = user_filter.lower()
        q = q.join(User, User.id == Run.owner_user_id).filter(
            or_(
                Run.owner_user_id == user_filter,
                func.lower(User.email) == lowered_user_filter,
                func.lower(User.display_name).like(f"%{lowered_user_filter}%"),
            )
        )

    # Total count before pagination
    total_count = q.count()

    # Apply pagination
    runs: List[Run] = q.offset(offset).limit(limit).all()
    _reconcile_run_liveness(db, runs)

    if not runs:
        return {
            "tasks": {},
            "last_updated": to_api_timestamp(utc_now_naive()),
            "total_count": total_count,
            "project": {"id": selected_project.id, "slug": selected_project.slug, "name": selected_project.name},
        }

    run_ids = [r.id for r in runs]

    # --- Batch query: item aggregates per run ---
    item_agg_rows = (
        db.query(
            RunItem.run_id,
            func.count().label("total"),
            func.count(case((RunItem.error.isnot(None), 1))).label("error_count"),
            func.count(case(((RunItem.output.isnot(None)) | (RunItem.error.isnot(None)), 1))).label("completed"),
            func.coalesce(func.sum(RunItem.retry_count), 0).label("total_retries"),
            func.avg(RunItem.latency_ms).label("avg_latency"),
        )
        .filter(RunItem.run_id.in_(run_ids))
        .group_by(RunItem.run_id)
        .all()
    )
    item_agg = {
        row.run_id: {
            "total": row.total,
            "error_count": row.error_count,
            "completed": row.completed,
            "total_retries": int(row.total_retries or 0),
            "avg_latency": float(row.avg_latency) if row.avg_latency is not None else 0.0,
        }
        for row in item_agg_rows
    }

    latency_rows = (
        db.query(RunItem.run_id, RunItem.latency_ms)
        .filter(RunItem.run_id.in_(run_ids), RunItem.latency_ms.isnot(None))
        .all()
    )
    latency_values_by_run: Dict[str, List[float]] = {}
    for row in latency_rows:
        latency_values_by_run.setdefault(row.run_id, []).append(float(row.latency_ms))
    for run_id, values in latency_values_by_run.items():
        item_agg.setdefault(run_id, {"total": 0, "error_count": 0, "completed": 0, "total_retries": 0, "avg_latency": 0.0})[
            "median_latency"
        ] = _median(values)

    # --- Batch query: score sums per run+metric ---
    # Match run-detail semantics:
    # - errored items count as 0
    # - scored items count normally
    # - in-flight / unscored items are excluded from the denominator
    score_agg_rows = (
        db.query(
            RunItemScore.run_id,
            RunItemScore.metric_name,
            func.sum(RunItemScore.score_numeric).label("score_sum"),
            func.count(RunItemScore.score_numeric).label("score_count"),
        )
        .join(
            RunItem,
            (RunItem.run_id == RunItemScore.run_id) & (RunItem.item_id == RunItemScore.item_id),
        )
        .filter(
            RunItemScore.run_id.in_(run_ids),
            RunItem.error.is_(None),
        )
        .group_by(RunItemScore.run_id, RunItemScore.metric_name)
        .all()
    )
    # Build nested map: run_id -> {metric_name: {"sum": ..., "count": ...}}
    score_agg: Dict[str, Dict[str, Dict[str, float]]] = {}
    for row in score_agg_rows:
        score_agg.setdefault(row.run_id, {})[row.metric_name] = {
            "sum": float(row.score_sum) if row.score_sum is not None else 0.0,
            "count": float(row.score_count or 0),
        }

    # --- Batch query: approvals ---
    approvals = db.query(Approval).filter(Approval.run_id.in_(run_ids)).all()
    approval_map = {a.run_id: a for a in approvals}

    # --- Batch query: all referenced users ---
    user_ids = {r.owner_user_id for r in runs}
    user_ids |= {a.decision_by_user_id for a in approvals if a.decision_by_user_id}
    users = db.query(User).filter(User.id.in_(user_ids)).all()
    user_map = {u.id: u for u in users}

    # --- Build summaries from pre-fetched data ---
    tasks: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for r in runs:
        agg = item_agg.get(
            r.id,
            {"total": 0, "error_count": 0, "completed": 0, "total_retries": 0, "avg_latency": 0.0, "median_latency": 0.0},
        )
        total_items = agg["total"]
        error_count = agg["error_count"]
        total_retries = int(agg.get("total_retries") or 0)
        success_count = total_items - error_count
        completed_count = agg["completed"]
        started_at = r.started_at or r.created_at
        ended_at = r.ended_at
        duration_ms = None
        if started_at and ended_at and ended_at >= started_at:
            duration_ms = (ended_at - started_at).total_seconds() * 1000.0

        expected_total = None
        if isinstance(r.run_metadata, dict):
            try:
                if r.run_metadata.get("total_items") is not None:
                    expected_total = int(r.run_metadata["total_items"])
            except Exception:
                expected_total = None

        metrics = list(r.metrics or [])
        run_score_agg = score_agg.get(r.id, {})
        metric_averages = {
            m: (
                (
                    run_score_agg.get(m, {}).get("sum", 0.0)
                    / (run_score_agg.get(m, {}).get("count", 0.0) + error_count)
                )
                if (run_score_agg.get(m, {}).get("count", 0.0) + error_count)
                else 0.0
            )
            for m in metrics
        }

        # Owner info
        owner = user_map.get(r.owner_user_id)
        owner_info = None
        if owner:
            owner_info = {
                "id": owner.id,
                "email": owner.email,
                "display_name": owner.display_name or owner.email.split("@")[0],
            }

        # Approval info
        approval_info = None
        approval = approval_map.get(r.id)
        if approval:
            decision_by = None
            if approval.decision_by_user_id:
                decision_user = user_map.get(approval.decision_by_user_id)
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

        # Derive run_name from run_config without including full config in response
        run_name = ""
        if isinstance(r.run_config, dict):
            run_name = r.run_config.get("run_name", "")
        if not run_name:
            run_name = r.external_run_id or ""

        summary = {
            "run_id": r.id,
            "run_name": run_name,
            "external_run_id": r.external_run_id or "",
            "task_name": r.task,
            "model_name": _strip_model_provider(r.model or ""),
            "dataset_name": r.dataset,
            "timestamp": _iso(started_at),
            "file_path": r.id,
            "metrics": metrics,
            "metric_averages": metric_averages,
            "total_items": total_items,
            "progress_completed": completed_count,
            "progress_total": expected_total,
            "progress_pct": (completed_count / expected_total) if expected_total else None,
            "success_count": success_count,
            "error_count": error_count,
            "total_retries": total_retries,
            "success_rate": (success_count / total_items) if total_items else 0.0,
            "avg_latency_ms": agg["avg_latency"],
            "median_latency_ms": agg.get("median_latency", 0.0),
            "duration_ms": duration_ms,
            "langfuse_url": r.run_metadata.get("langfuse_url") if isinstance(r.run_metadata, dict) else None,
            "langfuse_dataset_id": r.run_metadata.get("langfuse_dataset_id") if isinstance(r.run_metadata, dict) else None,
            "langfuse_run_id": r.run_metadata.get("langfuse_run_id") if isinstance(r.run_metadata, dict) else None,
            "status": r.status,
            "run_config": {},  # Omit full config from list view for payload size
            "git_branch": r.run_config.get("git_branch") if isinstance(r.run_config, dict) else None,
            "git_commit": r.run_config.get("git_commit") if isinstance(r.run_config, dict) else None,
            "owner": owner_info,
            "approval": approval_info,
            "trace_stats": r.run_metadata.get("trace_stats") if isinstance(r.run_metadata, dict) else None,
            "product_eval": r.run_metadata.get("product_eval") if isinstance(r.run_metadata, dict) else None,
        }

        task = summary["task_name"]
        model = summary["model_name"] or "nomodel"
        tasks.setdefault(task, {}).setdefault(model, []).append(summary)

    return {
        "tasks": tasks,
        "last_updated": to_api_timestamp(utc_now_naive()),
        "total_count": total_count,
        "project": {"id": selected_project.id, "slug": selected_project.slug, "name": selected_project.name},
    }


@router.get("/api/runs/live")
def list_live_runs(
    limit: int = Query(default=25, ge=1, le=100),
    project_slug: Optional[str] = Query(default=None),
    all_projects: bool = Query(default=False),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    q = Run.active(db).filter(Run.status.in_(_LIVE_RUN_STATUSES)).order_by(Run.last_event_at.desc(), Run.created_at.desc())
    selected_project = None

    if all_projects:
        if principal.auth_type != "none" and principal.user.role != UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Admin only")
        q = q.join(Project, Project.id == Run.project_id).filter(Project.is_active.is_(True))
    elif project_slug:
        selected_project = db.query(Project).filter(Project.slug == project_slug, Project.is_active.is_(True)).first()
        if not selected_project:
            raise HTTPException(status_code=404, detail="Project not found")
        if not has_project_access(db, principal, selected_project.id):
            raise HTTPException(status_code=403, detail="Access denied")
        q = q.filter(Run.project_id == selected_project.id)
    else:
        if principal.auth_type == "none" or principal.user.role == UserRole.ADMIN:
            selected_project = db.query(Project).filter(Project.is_active.is_(True)).order_by(Project.name).first()
        else:
            selected_project = (
                db.query(Project)
                .join(ProjectMembership, ProjectMembership.project_id == Project.id)
                .filter(ProjectMembership.user_id == principal.user.id, Project.is_active.is_(True))
                .order_by(Project.name)
                .first()
            )
        if selected_project:
            q = q.filter(Run.project_id == selected_project.id)
        else:
            return {
                "runs": [],
                "total_count": 0,
                "last_updated": to_api_timestamp(utc_now_naive()),
                "project": None,
            }

    candidates: List[Run] = q.limit(500).all()
    _reconcile_run_liveness(db, candidates)

    total_count = q.count()
    runs: List[Run] = q.limit(limit).all()
    if not runs:
        return {
            "runs": [],
            "total_count": total_count,
            "last_updated": to_api_timestamp(utc_now_naive()),
            "project": (
                {"id": selected_project.id, "slug": selected_project.slug, "name": selected_project.name}
                if selected_project
                else None
            ),
        }

    run_ids = [run.id for run in runs]
    item_agg_rows = (
        db.query(
            RunItem.run_id,
            func.count().label("total"),
            func.count(case((RunItem.error.isnot(None), 1))).label("error_count"),
            func.count(case(((RunItem.output.isnot(None)) | (RunItem.error.isnot(None)), 1))).label("completed"),
        )
        .filter(RunItem.run_id.in_(run_ids))
        .group_by(RunItem.run_id)
        .all()
    )
    item_agg = {
        row.run_id: {
            "total": row.total,
            "error_count": row.error_count,
            "completed": row.completed,
        }
        for row in item_agg_rows
    }

    project_ids = {run.project_id for run in runs}
    owner_ids = {run.owner_user_id for run in runs}
    projects = db.query(Project).filter(Project.id.in_(project_ids)).all() if project_ids else []
    owners = db.query(User).filter(User.id.in_(owner_ids)).all() if owner_ids else []
    project_map = {project.id: project for project in projects}
    owner_map = {owner.id: owner for owner in owners}

    return {
        "runs": [
            _live_run_summary(
                run,
                project=project_map.get(run.project_id),
                owner=owner_map.get(run.owner_user_id),
                item_agg=item_agg.get(run.id, {}),
            )
            for run in runs
        ],
        "total_count": total_count,
        "last_updated": to_api_timestamp(utc_now_naive()),
        "project": (
            {"id": selected_project.id, "slug": selected_project.slug, "name": selected_project.name}
            if selected_project
            else None
        ),
    }


def _parse_requested_run_ids(files: List[str]) -> list[str]:
    run_ids: list[str] = []
    for f in files:
        for part in str(f).split(","):
            p = part.strip()
            if p:
                run_ids.append(p)
    return run_ids


def _run_display_name(run: Run) -> str:
    run_config = run.run_config if isinstance(run.run_config, dict) else {}
    run_name = ""
    if isinstance(run_config, dict):
        run_name = run_config.get("run_name", "")
    return run_name or run.external_run_id or run.id


def _build_models_runs_data(db: Session, runs: list[Run]) -> list[dict[str, Any]]:
    if not runs:
        return []

    run_ids = [run.id for run in runs]
    metrics_by_run = {run.id: list(run.metrics or []) for run in runs}
    runs_data: dict[str, dict[str, Any]] = {}
    stats_by_run: dict[str, dict[str, Any]] = {}

    for run in runs:
        metrics = metrics_by_run[run.id]
        stats = {"total": 0, "completed": 0, "in_progress": 0, "pending": 0, "failed": 0}
        stats_by_run[run.id] = stats
        runs_data[run.id] = {
            "run": {
                "run_id": run.id,
                "file_path": run.id,
                "run_name": _run_display_name(run),
                "metric_names": metrics,
                "task_name": run.task,
                "dataset_name": run.dataset,
                "model_name": _strip_model_provider(run.model or ""),
            },
            "snapshot": {
                "rows": [],
                "stats": stats,
                "metric_names": metrics,
            },
        }

    score_rows = (
        db.query(
            RunItemScore.run_id,
            RunItemScore.item_id,
            RunItemScore.metric_name,
            RunItemScore.score_numeric,
            RunItemScore.score_raw,
        )
        .filter(RunItemScore.run_id.in_(run_ids))
        .all()
    )
    score_by_run_item: dict[tuple[str, str], dict[str, Any]] = {}
    for score in score_rows:
        value = score.score_numeric if score.score_numeric is not None else score.score_raw
        score_by_run_item.setdefault((score.run_id, score.item_id), {})[score.metric_name] = value

    item_rows = (
        db.query(
            RunItem.run_id,
            RunItem.item_id,
            RunItem.index,
            RunItem.error,
            RunItem.latency_ms,
        )
        .filter(RunItem.run_id.in_(run_ids))
        .order_by(RunItem.run_id.asc(), RunItem.index.asc())
        .all()
    )

    for item in item_rows:
        run_data = runs_data.get(item.run_id)
        if not run_data:
            continue
        metrics = metrics_by_run.get(item.run_id, [])
        item_scores = score_by_run_item.get((item.run_id, item.item_id), {})
        status = "error" if item.error else "completed"
        stats = stats_by_run[item.run_id]
        stats["total"] += 1
        if status == "error":
            stats["failed"] += 1
        else:
            stats["completed"] += 1

        run_data["snapshot"]["rows"].append(
            {
                "index": item.index,
                "item_id": item.item_id,
                "status": status,
                "latency_ms": item.latency_ms or 0,
                "metric_values": [item_scores.get(metric_name, "") for metric_name in metrics],
            }
        )

    for run_id, stats in stats_by_run.items():
        stats["success_rate"] = (stats["completed"] / stats["total"] * 100.0) if stats["total"] else 0.0
        runs_data[run_id]["snapshot"]["stats"] = stats

    return [runs_data[run.id] for run in runs if run.id in runs_data]


@router.get("/api/models/runs")
def models_runs_data(
    files: List[str] = Query(default=[]),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Return lightweight per-run snapshots for the Models view."""
    if not files:
        raise HTTPException(status_code=400, detail="No files specified")

    requested_run_ids = _parse_requested_run_ids(files)

    unique_run_ids: list[str] = []
    seen_run_ids: set[str] = set()
    for run_id in requested_run_ids:
        if run_id in seen_run_ids:
            continue
        seen_run_ids.add(run_id)
        unique_run_ids.append(run_id)

    runs = Run.active(db).filter(Run.id.in_(unique_run_ids)).all()
    runs_by_id = {run.id: run for run in runs}
    accessible_runs: list[Run] = []
    for run_id in unique_run_ids:
        run = runs_by_id.get(run_id)
        if not run:
            continue
        if can_view_run(db, principal, run):
            accessible_runs.append(run)

    runs_data = _build_models_runs_data(db, accessible_runs)
    return {"runs": runs_data}


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
    run_ids = _parse_requested_run_ids(files)

    runs_data: list[dict[str, Any]] = []
    for run_id in run_ids:
        data = legacy_run_data(run_id=run_id, db=db, principal=principal)
        if not data.get("error"):
            runs_data.append(data)

    # Top-level Langfuse config from env vars
    lf_host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL", "")
    lf_project_id = os.getenv("LANGFUSE_PROJECT_ID", "")
    # Fallback: extract from the first run's langfuse_url if env vars are incomplete
    if (not lf_host or not lf_project_id) and runs_data:
        first_run = runs_data[0].get("run", {})
        lf_host = lf_host or first_run.get("langfuse_host", "")
        lf_project_id = lf_project_id or first_run.get("langfuse_project_id", "")

    unalignable_runs = [
        {
            "run_name": str(data.get("run", {}).get("run_name") or ""),
            "issues": list(data.get("run", {}).get("compare_alignment_issues") or []),
        }
        for data in runs_data
        if str(data.get("run", {}).get("compare_alignment_status") or "") != "aligned"
    ]
    compare_alignment_status = "unalignable" if unalignable_runs else "aligned"

    return {
        "runs": runs_data,
        "langfuse_host": lf_host,
        "langfuse_project_id": lf_project_id,
        "compare_alignment_status": compare_alignment_status,
        "unalignable_runs": unalignable_runs,
    }


def _can_approve_run(db: Session, principal: Principal, run: Run) -> bool:
    """Check if the principal can approve or reject this run."""
    return permission_can_approve_run(db, principal, run)


def _build_run_data(db: Session, run: Run) -> Dict[str, Any]:
    """Build the run + snapshot data dict used by the UI."""
    items: List[RunItem] = db.query(RunItem).filter(RunItem.run_id == run.id).order_by(RunItem.index.asc()).all()
    metrics = list(run.metrics or [])
    corrections = (
        db.query(ReviewCorrection)
        .filter(ReviewCorrection.run_id == run.id, ReviewCorrection.is_active.is_(True))
        .order_by(ReviewCorrection.created_at.desc())
        .all()
    )
    correction_by_item: Dict[str, ReviewCorrection] = {}
    for corr in corrections:
        correction_by_item.setdefault(corr.item_id, corr)

    # Read pre-computed trace stats from stored metadata
    run_trace_stats = run.run_metadata.get("trace_stats") if isinstance(run.run_metadata, dict) else None
    run_config = run.run_config if isinstance(run.run_config, dict) else {}
    run_metadata = run.run_metadata if isinstance(run.run_metadata, dict) else {}

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
    duplicate_counts: Dict[str, int] = {}
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
                metric_meta[m] = dict(sc.meta)
            if sc.label or sc.explanation:
                if m not in metric_meta:
                    metric_meta[m] = {}
                if sc.label:
                    metric_meta[m]["label"] = sc.label
                if sc.explanation:
                    metric_meta[m]["explanation"] = sc.explanation

        # Resolve task_started_at_ms: prefer item_metadata, then fallback to event timestamp
        ts_ms = it.item_metadata.get("task_started_at_ms") if isinstance(it.item_metadata, dict) else None
        if not ts_ms:
            ts_ms = _item_start_ts.get(it.item_id)
        corr = correction_by_item.get(it.item_id)
        item_metadata = it.item_metadata if isinstance(it.item_metadata, dict) else {}
        retry_count = int(it.retry_count or item_metadata.get("retry_count") or 0)
        identity = build_compare_identity(
            item_id=it.item_id,
            input_value=it.input,
            expected_value=it.expected,
            metadata=item_metadata,
            duplicate_counts=duplicate_counts,
        )

        ui_rows.append(
            {
                "index": it.index,
                "item_id": it.item_id,
                "compare_item_id": identity["compare_item_id"],
                "compare_alignment_source": identity["compare_alignment_source"],
                "status": status,
                "error": it.error or "",
                "input": _stringify(it.input),
                "input_full": _stringify(it.input),
                "output": _stringify(it.output) if not is_error else f"ERROR: {it.error}",
                "output_full": _stringify(it.output) if not is_error else f"ERROR: {it.error}",
                "expected": _stringify(it.expected),
                "expected_full": _stringify(it.expected),
                "time": "" if it.latency_ms is None else f"{(it.latency_ms or 0)/1000.0:.3f}",
                "latency_ms": it.latency_ms or 0,
                "retry_count": retry_count,
                "trace_id": it.trace_id or "",
                "trace_url": it.trace_url or "",
                "task_started_at_ms": ts_ms,
                "metric_values": metric_values,
                "metric_meta": metric_meta,
                "item_metadata": item_metadata,
                "review_correction_id": corr.id if corr else None,
                "review_correction_status": (
                    corr.status.value if corr and hasattr(corr.status, "value") else (corr.status if corr else "")
                ),
                "trace_stats": item_metadata.get("trace_stats") if isinstance(item_metadata, dict) else None,
            }
        )

    stats["success_rate"] = (stats["completed"] / stats["total"] * 100.0) if stats["total"] else 0.0

    # Extract Langfuse host/project_id from run metadata (langfuse_url fallback)
    lf_host, lf_project_id = _extract_langfuse_ids(run.run_metadata or {})
    owner = db.query(User).filter(User.id == run.owner_user_id).first()
    project = db.query(Project).filter(Project.id == run.project_id).first()
    owner_info = None
    if owner:
        owner_info = {
            "id": owner.id,
            "email": owner.email,
            "display_name": owner.display_name or owner.email.split("@")[0],
        }
    project_info = None
    if project:
        project_info = {"id": project.id, "slug": project.slug, "name": project.name}

    started_at = run.started_at or run.created_at
    ended_at = run.ended_at
    duration_ms = None
    if started_at and ended_at and ended_at >= started_at:
        duration_ms = (ended_at - started_at).total_seconds() * 1000.0

    run_name = ""
    if isinstance(run_config, dict):
        run_name = run_config.get("run_name", "")
    if not run_name:
        run_name = run.external_run_id or run.id

    return finalize_compare_alignment({
        "run": {
            "run_id": run.id,
            "file_path": run.id,
            "task_name": run.task,
            "dataset_name": run.dataset,
            "model_name": _strip_model_provider(run.model or ""),
            "run_name": run_name,
            "external_run_id": run.external_run_id or "",
            "metric_names": metrics,
            "config": run_config,
            "metadata": run_metadata,
            "status": run.status,
            "owner": owner_info,
            "team_name": project.name if project else None,
            "project": project_info,
            "started_at": _iso(started_at) if started_at else "",
            "ended_at": _iso(ended_at) if ended_at else "",
            "created_at": _iso(run.created_at) if run.created_at else "",
            "duration_ms": duration_ms,
            "git_branch": run_config.get("git_branch"),
            "git_commit": run_config.get("git_commit"),
            "langfuse_host": lf_host,
            "langfuse_project_id": lf_project_id,
            "trace_stats": run_trace_stats,
        },
        "snapshot": {"rows": ui_rows, "stats": stats, "metric_names": metrics},
    })


@router.get("/api/runs/{run_id}/export-html")
def export_run_html(
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> HTMLResponse:
    """Export a run page as a self-contained HTML file with all assets inlined."""
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not can_view_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")

    data = _build_run_data(db, run)
    dashboard_dir = _platform_static_dir() / "dashboard"

    # Read source files
    run_html = (dashboard_dir / "run.html").read_text(encoding="utf-8")
    css_content = (dashboard_dir / "dashboard.css").read_text(encoding="utf-8")
    metrics_js = (dashboard_dir / "metrics.js").read_text(encoding="utf-8")

    # Inline dashboard.css
    run_html = run_html.replace(
        '<link rel="stylesheet" href="/static/dashboard.css">',
        f"<style>\n{css_content}\n</style>",
    )

    # Inline metrics.js
    run_html = run_html.replace(
        '<script src="/static/metrics.js"></script>',
        f"<script>\n{metrics_js}\n</script>",
    )

    trace_viewer_path = dashboard_dir / "trace_viewer.js"
    if trace_viewer_path.exists():
        trace_viewer_js = trace_viewer_path.read_text(encoding="utf-8")
        run_html = run_html.replace(
            '<script src="/static/trace_viewer.js"></script>',
            f"<script>\n{trace_viewer_js}\n</script>",
        )

    # Remove playground.js (not needed in export)
    run_html = run_html.replace('<script src="/static/playground.js"></script>', "")

    # Remove favicon (would be a broken link)
    run_html = run_html.replace(
        '<link rel="icon" type="image/png" href="/static/qym_icon.png">', ""
    )

    # Serialize data — escape </script> sequences in JSON to prevent premature tag closing
    data_json = json.dumps(data, ensure_ascii=False, default=str)
    data_json = data_json.replace("</", "<\\/")

    # Inject export flag + data before the main inline <script> block
    export_script = (
        "<script>\n"
        "window.__QYM_EXPORT__ = true;\n"
        f"window.__QYM_EXPORT_DATA__ = {data_json};\n"
        "</script>\n"
    )
    # Insert just before the main <script> that starts the app
    run_html = run_html.replace(
        "  <script>\n    (() => {",
        f"{export_script}  <script>\n    (() => {{",
        1,
    )

    run_name = data["run"].get("run_name", run_id)
    # Sanitize filename
    safe_name = re.sub(r'[^\w\-.]', '_', str(run_name))[:80]
    filename = f"qym-run-{safe_name}.html"

    return HTMLResponse(
        content=run_html,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/runs/trash")
def list_deleted_runs(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> List[Dict[str, Any]]:
    """List soft-deleted runs (admin only)."""
    if principal.user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin only")

    deleted_runs = (
        db.query(Run)
        .filter(Run.deleted_at.isnot(None))
        .order_by(Run.deleted_at.desc())
        .limit(200)
        .all()
    )

    # Gather deleter display names
    deleter_ids = {r.deleted_by_user_id for r in deleted_runs if r.deleted_by_user_id}
    deleters = {}
    if deleter_ids:
        for u in db.query(User).filter(User.id.in_(deleter_ids)).all():
            deleters[u.id] = u.display_name or u.email

    result = []
    for r in deleted_runs:
        run_name = ""
        if isinstance(r.run_config, dict):
            run_name = r.run_config.get("run_name", "")
        if not run_name:
            run_name = r.external_run_id or ""
        result.append({
            "id": r.id,
            "run_name": run_name,
            "task": r.task,
            "dataset": r.dataset,
            "model": r.model,
            "trace_stats": r.run_metadata.get("trace_stats") if isinstance(r.run_metadata, dict) else None,
            "status": r.status.value if r.status else None,
            "owner_user_id": r.owner_user_id,
            "deleted_at": to_api_timestamp(r.deleted_at),
            "deleted_by_user_id": r.deleted_by_user_id,
            "deleted_by_name": deleters.get(r.deleted_by_user_id, ""),
            "created_at": to_api_timestamp(r.created_at),
        })
    return result


@router.get("/api/runs/{run_id}")
def legacy_run_data(
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        return {"error": "Run not found"}
    if not can_view_run(db, principal, run):
        return {"error": "Access denied"}
    _reconcile_run_liveness(db, [run])

    return _build_run_data(db, run)


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

    run = Run.active(db).filter(Run.id == file_path).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not can_modify_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")

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
    duplicate_counts: Dict[str, int] = {}
    ordered_items = db.query(RunItem).filter(RunItem.run_id == run.id).order_by(RunItem.index.asc()).all()
    identity = {"compare_item_id": item.item_id, "compare_alignment_source": "item_id"}
    for ordered_item in ordered_items:
        ordered_metadata = ordered_item.item_metadata if isinstance(ordered_item.item_metadata, dict) else {}
        ordered_identity = build_compare_identity(
            item_id=ordered_item.item_id,
            input_value=ordered_item.input,
            expected_value=ordered_item.expected,
            metadata=ordered_metadata,
            duplicate_counts=duplicate_counts,
        )
        if ordered_item.id == item.id:
            identity = ordered_identity
            break

    row = {
        "index": item.index,
        "item_id": item.item_id,
        "compare_item_id": identity["compare_item_id"],
        "compare_alignment_source": identity["compare_alignment_source"],
        "status": status,
        "error": item.error or "",
        "input": item.input,
        "input_full": item.input,
        "output": item.output if not is_error else f"ERROR: {item.error}",
        "output_full": item.output if not is_error else f"ERROR: {item.error}",
        "expected": item.expected,
        "expected_full": item.expected,
        "time": "" if item.latency_ms is None else f"{(item.latency_ms or 0)/1000.0:.3f}",
        "latency_ms": item.latency_ms or 0,
        "retry_count": int(item.retry_count or (item.item_metadata.get("retry_count") if isinstance(item.item_metadata, dict) else 0) or 0),
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
    """Update root_cause and feedback (root_cause_note) in item_metadata for a single run's item.

    Each field is only modified when its key is explicitly present in the request.
    This prevents partial saves (e.g. saving only root_cause_note) from erasing
    unrelated fields like root_cause or root_cause_detail.
    """
    item_id = request.get("item_id")
    run_id = request.get("run_id")

    if not item_id or not run_id:
        raise HTTPException(status_code=400, detail="item_id and run_id required")

    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not can_modify_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")

    item = (
        db.query(RunItem)
        .filter(RunItem.run_id == run.id, RunItem.item_id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    patch = {}
    for field in ("root_cause", "root_cause_detail", "root_cause_note", "solution", "solution_note"):
        if field in request or (field == "root_cause_note" and request.get(field) is not None):
            patch[field] = request.get(field)

    apply_root_cause_change(
        db,
        run=run,
        item=item,
        actor_user_id=principal.user.id if principal.auth_type != "none" else None,
        actor_source="human",
        human_patch=patch,
    )

    db.commit()
    updated_snapshot = _build_run_data(db, run).get("snapshot", {})
    updated_rows = updated_snapshot.get("rows", []) if isinstance(updated_snapshot, dict) else []
    updated_row = next((row for row in updated_rows if row.get("item_id") == item.item_id), None)
    return {"ok": True, "row": updated_row}


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

    run = Run.active(db).filter(Run.id == file_path).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not can_delete_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Permission denied")

    # Soft-delete: mark as deleted instead of removing data
    snapshot = run.audit_snapshot()
    run.deleted_at = utc_now_naive()
    run.deleted_by_user_id = principal.user.id

    audit = AuditLog(
        actor_user_id=principal.user.id,
        action="run.deleted",
        entity_type="run",
        entity_id=run.id,
        before=snapshot,
        after={"deleted_at": run.deleted_at.isoformat()},
    )
    db.add(audit)
    db.commit()

    return {"ok": True}


@router.post("/api/runs/restore")
def restore_run(
    request: Dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Restore a soft-deleted run (admin only)."""
    if principal.user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin only")

    run_id = request.get("run_id")
    if not run_id:
        raise HTTPException(status_code=400, detail="run_id required")

    run = db.query(Run).filter(Run.id == run_id, Run.deleted_at.isnot(None)).first()
    if not run:
        raise HTTPException(status_code=404, detail="Deleted run not found")

    run.deleted_at = None
    run.deleted_by_user_id = None

    audit = AuditLog(
        actor_user_id=principal.user.id,
        action="run.restored",
        entity_type="run",
        entity_id=run.id,
        before={"deleted_at": True},
        after={},
    )
    db.add(audit)
    db.commit()

    return {"ok": True}


@router.post("/v1/runs/{run_id}/submit")
def submit_run(
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    run = Run.active(db).filter(Run.id == run_id).first()
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
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != RunWorkflowStatus.SUBMITTED:
        raise HTTPException(status_code=400, detail="Run not submitted")
    if not _can_approve_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Only a project manager or admin can approve")
    approval = db.query(Approval).filter(Approval.run_id == run.id).first()
    if not approval:
        raise HTTPException(status_code=400, detail="Missing approval record")
    approval.decision = ApprovalDecision.APPROVED
    approval.decision_by_user_id = principal.user.id
    approval.decision_at = utc_now_naive()
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
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != RunWorkflowStatus.SUBMITTED:
        raise HTTPException(status_code=400, detail="Run not submitted")
    if not _can_approve_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Only a project manager or admin can reject")
    approval = db.query(Approval).filter(Approval.run_id == run.id).first()
    if not approval:
        raise HTTPException(status_code=400, detail="Missing approval record")
    approval.decision = ApprovalDecision.REJECTED
    approval.decision_by_user_id = principal.user.id
    approval.decision_at = utc_now_naive()
    approval.comment = str(body.get("comment") or "")
    run.status = RunWorkflowStatus.REJECTED
    db.commit()
    return {"ok": True, "status": run.status}


# ---------------------------------------------------------------------------
# Spans (OTEL trace data)
# ---------------------------------------------------------------------------

@router.get("/api/runs/{run_id}/spans")
def get_run_spans(
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
):
    """Return all OTEL spans captured for a run, ordered by start time."""
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not can_view_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")

    spans = (
        db.query(Span)
        .filter(Span.run_id == run_id)
        .order_by(Span.start_time_ns.asc().nullslast())
        .all()
    )
    return {"spans": [_serialize_span(s) for s in spans]}


@router.get("/api/runs/{run_id}/items/{item_id}/spans")
def get_item_spans(
    run_id: str,
    item_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
):
    """Return OTEL spans for a specific run item, looked up via trace_id."""
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not can_view_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")

    item = (
        db.query(RunItem)
        .filter(RunItem.run_id == run_id, RunItem.item_id == item_id)
        .first()
    )
    if not item or not item.trace_id:
        return {"spans": []}
    spans = (
        db.query(Span)
        .filter(Span.run_id == run_id, Span.trace_id == item.trace_id)
        .order_by(Span.start_time_ns.asc().nullslast())
        .all()
    )
    return {"spans": [_serialize_span(s) for s in spans]}


@router.get("/api/runs/{run_id}/items/{item_id}/trace")
def get_item_trace(
    run_id: str,
    item_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
):
    """Return trace metadata + spans for an individual run item."""
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not can_view_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")

    item = (
        db.query(RunItem)
        .filter(RunItem.run_id == run_id, RunItem.item_id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    attempts_rows = (
        db.query(RunItemAttempt)
        .filter(RunItemAttempt.run_id == run_id, RunItemAttempt.item_id == item_id)
        .order_by(RunItemAttempt.attempt_number.asc(), RunItemAttempt.id.asc())
        .all()
    )

    attempt_dicts: List[Dict[str, Any]] = []
    if attempts_rows:
        trace_ids = [row.trace_id for row in attempts_rows if row.trace_id]
        spans_by_trace: Dict[str, List[Span]] = {}
        if trace_ids:
            span_rows = (
                db.query(Span)
                .filter(Span.run_id == run_id, Span.trace_id.in_(trace_ids))
                .order_by(Span.start_time_ns.asc().nullslast(), Span.id.asc())
                .all()
            )
            for span in span_rows:
                spans_by_trace.setdefault(span.trace_id, []).append(span)
        for row in attempts_rows:
            attempt_dicts.append(
                _serialize_attempt_trace_payload(
                    {
                        "attempt_number": row.attempt_number,
                        "status": str(row.status or "").lower() or "failed",
                        "latency_ms": row.latency_ms,
                        "task_started_at_ms": row.task_started_at_ms,
                        "trace_id": row.trace_id,
                        "trace_url": row.trace_url,
                        "error": row.error,
                        "is_last_attempt": row.is_last_attempt,
                    },
                    spans_by_trace.get(row.trace_id or "", []),
                )
            )
    elif item.trace_id:
        spans = (
            db.query(Span)
            .filter(Span.run_id == run_id, Span.trace_id == item.trace_id)
            .order_by(Span.start_time_ns.asc().nullslast(), Span.id.asc())
            .all()
        )
        attempt_dicts.append(
            _serialize_attempt_trace_payload(
                {
                    "attempt_number": 1,
                    "status": "failed" if item.error else "completed",
                    "latency_ms": item.latency_ms,
                    "task_started_at_ms": item.item_metadata.get("task_started_at_ms") if isinstance(item.item_metadata, dict) else None,
                    "trace_id": item.trace_id,
                    "trace_url": item.trace_url,
                    "error": item.error,
                    "is_last_attempt": True,
                },
                spans,
            )
        )

    return _build_item_trace_payload(item, attempt_dicts)
