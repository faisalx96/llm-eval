from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from html import escape
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import Text, case, cast, func, or_
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
    DatasetAlias,
    DatasetVersion,
    Project,
    ProjectMembership,
    ReviewCorrection,
    RootCauseRevision,
    Run,
    RunEvent,
    RunItem,
    RunItemAttempt,
    RunItemPassScore,
    RunItemScore,
    RunMetricSpec,
    RunTraceAggregate,
    RunWorkflowStatus,
    Span,
    User,
    UserRole,
)
from qym_platform.deps import get_db
from qym_platform.item_identity import (
    build_compare_identity,
    finalize_compare_alignment,
)
from qym_platform.permissions import (
    can_approve_run as permission_can_approve_run,
    can_delete_run,
    can_modify_run,
    can_view_run,
    has_project_access,
)
from qym_platform.services.run_lifecycle import reconcile_stale_running_run
from qym_platform.services.run_payloads import compact_row, detail_item_ids, search_conditions
from qym_platform.services.repeat_passes import (
    RepeatPassDeletionError,
    delete_repeat_pass,
)
from qym_platform.services.root_cause_changes import (
    PASS_ANALYSIS_META_KEY,
    apply_root_cause_change,
    lock_run_item,
    replace_metric_review_candidate,
)
from qym_platform.services.root_cause_categories import (
    analysis_root_cause_issues,
    analysis_root_causes,
    normalize_category_taxonomy,
    normalize_root_cause_issues,
    normalize_root_causes,
    patch_issue_categories,
)
from qym_platform.settings import PlatformSettings


router = APIRouter()

_LANGFUSE_URL_RE = re.compile(r"(https?://[^/]+)/project/([^/]+)")


def _metric_spec_payload(spec: RunMetricSpec) -> Dict[str, Any]:
    return {
        "schema_version": spec.schema_version,
        "score_type": spec.score_type,
        "direction": spec.direction,
        "pass_threshold": spec.pass_threshold,
        "sample_reducer": spec.sample_reducer,
        "run_reducer": spec.run_reducer,
        "unit": spec.unit,
        "precision": spec.precision,
    }


def _metric_specs_for_runs(
    db: Session, run_ids: List[str]
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    if not run_ids:
        return {}
    result: Dict[str, Dict[str, Dict[str, Any]]] = {}
    rows = (
        db.query(RunMetricSpec)
        .filter(RunMetricSpec.run_id.in_(run_ids))
        .order_by(RunMetricSpec.position.asc())
        .all()
    )
    for row in rows:
        result.setdefault(row.run_id, {})[row.metric_name] = _metric_spec_payload(row)
    return result


def _refresh_metric_analysis_error(meta: Dict[str, Any]) -> None:
    """Keep the item-level analysis error summary aligned with metric edits."""
    metric_analyses = meta.get("metric_analyses")
    errors = []
    if isinstance(metric_analyses, dict):
        for metric_name, analysis in metric_analyses.items():
            if not isinstance(analysis, dict):
                continue
            error = str(analysis.get("error") or "").strip()
            if error:
                errors.append(f"{metric_name}: {error}")
    if errors:
        meta["analysis_error"] = "; ".join(errors)
    else:
        meta.pop("analysis_error", None)


def _apply_metric_analysis_patch(
    before_analysis: Dict[str, Any] | None,
    patch: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply the editable diagnosis fields without touching other metadata."""
    analysis = dict(before_analysis or {})

    if "root_cause_issues" in patch:
        issues = normalize_root_cause_issues(patch.get("root_cause_issues"))
        analysis["root_cause_issues"] = issues
    elif "root_causes" in patch:
        root_causes = normalize_root_causes(patch.get("root_causes"))
        if root_causes:
            existing = analysis_root_cause_issues(analysis)
            analysis["root_cause_issues"] = patch_issue_categories(
                existing, root_causes
            )
        else:
            analysis["root_cause_issues"] = []
    elif "root_cause" in patch:
        root_cause = str(patch.get("root_cause") or "").strip()
        if root_cause:
            existing = analysis_root_cause_issues(analysis)
            primary = dict(existing[0]) if existing else {}
            primary["category"] = root_cause
            analysis["root_cause_issues"] = [primary, *existing[1:]]
        else:
            analysis["root_cause_issues"] = []
    if "root_cause_detail" in patch:
        issues = analysis_root_cause_issues(analysis)
        if issues:
            issues[0]["subcategory"] = str(
                patch.get("root_cause_detail") or ""
            ).strip()
            analysis["root_cause_issues"] = issues
        else:
            detail = str(patch.get("root_cause_detail") or "").strip()
            if detail:
                analysis["root_cause_detail"] = detail
            else:
                analysis.pop("root_cause_detail", None)
    if "root_cause_note" in patch:
        issues = analysis_root_cause_issues(analysis)
        if issues:
            issues[0]["finding"] = str(
                patch.get("root_cause_note") or ""
            ).strip()
            analysis["root_cause_issues"] = issues
        else:
            note = str(patch.get("root_cause_note") or "").strip()
            if note:
                analysis["root_cause_note"] = note
            else:
                analysis.pop("root_cause_note", None)

    category_was_patched = any(
        field in patch for field in ("root_cause_issues", "root_causes", "root_cause")
    )
    if category_was_patched or any(
        field in patch
        for field in ("root_cause_detail", "root_cause_note")
    ):
        issues = normalize_root_cause_issues(
            analysis.get("root_cause_issues"),
            legacy_root_causes=(
                analysis.get("root_causes") or analysis.get("root_cause")
            ),
            legacy_detail=analysis.get("root_cause_detail"),
            legacy_finding=analysis.get("root_cause_note"),
        )
        if issues:
            categories = normalize_root_causes(
                issue.get("category") for issue in issues
            )
            primary = issues[0]
            analysis["root_cause_issues"] = issues
            analysis["root_causes"] = categories
            analysis["root_cause"] = categories[0]
            if primary.get("subcategory"):
                analysis["root_cause_detail"] = primary["subcategory"]
            else:
                analysis.pop("root_cause_detail", None)
            if primary.get("finding"):
                analysis["root_cause_note"] = primary["finding"]
            else:
                analysis.pop("root_cause_note", None)
        else:
            for field in (
                "root_cause_issues",
                "root_causes",
                "root_cause",
                "root_cause_reason",
                "confidence",
            ):
                analysis.pop(field, None)
            if category_was_patched:
                analysis.pop("root_cause_detail", None)
                analysis.pop("root_cause_note", None)
    if "category_taxonomy" in patch:
        taxonomy = normalize_category_taxonomy(patch.get("category_taxonomy"))
        if taxonomy:
            analysis["category_taxonomy"] = taxonomy
        else:
            analysis.pop("category_taxonomy", None)
    if "solution" in patch:
        solution = str(patch.get("solution") or "").strip()
        if solution:
            analysis["solution"] = solution
        else:
            analysis.pop("solution", None)
            analysis.pop("solution_note", None)
    if "solution_note" in patch:
        solution_note = str(patch.get("solution_note") or "").strip()
        if solution_note:
            analysis["solution_note"] = solution_note
        else:
            analysis.pop("solution_note", None)

    if patch:
        if normalize_root_causes(
            analysis.get("root_causes") or analysis.get("root_cause")
        ):
            analysis.pop("error", None)
        analysis.pop("confidence", None)
        # A new human edit reopens review for this pass.  Keep the review
        # state next to the pass diagnosis so an approved sample does not
        # remain approved after its category or notes change.
        analysis.pop("review_status", None)
        analysis.pop("reviewed_at", None)
        analysis["source"] = "human"

    meaningful = {
        key: value
        for key, value in analysis.items()
        if key != "source" and value not in (None, "", [])
    }
    return analysis if meaningful else {}


def _median(values: List[Optional[float]]) -> float:
    numeric = sorted(float(v) for v in values if v is not None)
    if not numeric:
        return 0.0
    mid = len(numeric) // 2
    if len(numeric) % 2 == 0:
        return (numeric[mid - 1] + numeric[mid]) / 2.0
    return numeric[mid]


def _repeat_pass_status(
    *, pass_number: int, last_completed: int, has_data: bool, run_status: str
) -> str:
    """Derive a pass status without contradicting its parent run."""
    if pass_number <= last_completed:
        return "completed"

    normalized_run_status = str(run_status or "").upper()
    if has_data:
        terminal_status = {
            "COMPLETED": "completed",
            "FAILED": "failed",
            "STOPPED": "stopped",
        }.get(normalized_run_status)
        return terminal_status or "running"

    if normalized_run_status == "RUNNING" and pass_number == last_completed + 1:
        return "running"
    return "pending"


def _repeat_attempt_summaries(
    db: Session, run_ids: List[str]
) -> Dict[str, Dict[str, float]]:
    """Aggregate latency and runtime across every retained repeat pass."""
    if not run_ids:
        return {}

    rows = (
        db.query(
            RunItemAttempt.run_id,
            RunItemAttempt.pass_number,
            RunItemAttempt.latency_ms,
            RunItemAttempt.task_started_at_ms,
        )
        .filter(
            RunItemAttempt.run_id.in_(run_ids),
            RunItemAttempt.is_last_attempt.is_(True),
        )
        .all()
    )
    latencies_by_run: Dict[str, List[float]] = defaultdict(list)
    bounds_by_run_pass: Dict[str, Dict[int, List[float]]] = defaultdict(dict)
    for run_id, pass_number, latency_ms, task_started_at_ms in rows:
        if latency_ms is not None:
            latencies_by_run[run_id].append(float(latency_ms))
        if task_started_at_ms is None or latency_ms is None:
            continue
        start = float(task_started_at_ms)
        end = start + float(latency_ms)
        bounds = bounds_by_run_pass[run_id].setdefault(int(pass_number), [start, end])
        bounds[0] = min(bounds[0], start)
        bounds[1] = max(bounds[1], end)

    summaries: Dict[str, Dict[str, float]] = {}
    for run_id in set(latencies_by_run) | set(bounds_by_run_pass):
        latencies = latencies_by_run.get(run_id, [])
        summary: Dict[str, float] = {}
        if latencies:
            summary["avg_latency_ms"] = sum(latencies) / len(latencies)
            summary["median_latency_ms"] = _median(latencies)
        pass_bounds = bounds_by_run_pass.get(run_id, {})
        if pass_bounds:
            summary["duration_ms"] = sum(
                max(0.0, end - start) for start, end in pass_bounds.values()
            )
        summaries[run_id] = summary
    return summaries


def _stringify(val: Any) -> str:
    """Convert a value to a display string; dicts/lists become pretty JSON."""
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, (dict, list)):
        return json.dumps(val, indent=2, ensure_ascii=False)
    return str(val)


def _repeat_aggregate_metric_meta(
    pass_values: Dict[int, Optional[float]],
    stored_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Describe a repeat reduction without presenting one pass as the mean."""
    meta: Dict[str, Any] = {
        "sample_reducer": "mean",
        "samples_observed": sum(value is not None for value in pass_values.values()),
    }
    for key, value in (stored_meta or {}).items():
        if key in {"modified", "original_score"} or key.startswith("pass_"):
            meta[key] = value
    return meta


def _completed_pass_outputs(
    db: Session,
    run_id: str,
    wanted: set[tuple[str, int]],
) -> Dict[tuple[str, int], Any]:
    """Recover outputs for attempts written by pre-fix SDK event ordering."""
    if not wanted:
        return {}
    recovered: Dict[tuple[str, int], Any] = {}
    rows = (
        db.query(RunEvent.payload)
        .filter(RunEvent.run_id == run_id, RunEvent.type == "item_completed")
        .filter(
            RunEvent.payload["item_id"]
            .as_string()
            .in_({item_id for item_id, _ in wanted})
        )
        .order_by(RunEvent.sequence.asc())
        .all()
    )
    for (payload,) in rows:
        if not isinstance(payload, dict):
            continue
        item_id = str(payload.get("item_id") or "")
        try:
            pass_number = max(1, int(payload.get("pass_number") or 1))
        except (TypeError, ValueError):
            pass_number = 1
        key = (item_id, pass_number)
        if key in wanted and "output" in payload:
            recovered[key] = payload.get("output")
    return recovered


def _repeat_pass_event_state(
    db: Session, run_id: str, *, item_ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Recover per-pass lifecycle state that is not represented by final attempts.

    New evaluations emit attempt-start events before an attempt finishes, while
    older evaluations can emit an item outcome without a matching final-attempt
    row.  Keeping both here prevents live or legacy pass pages from falling back
    to the run-level item's latest state.
    """

    event_types = {
        "item_started",
        "item_attempt_started",
        "item_attempt_finished",
        "metric_scored",
        "item_completed",
        "item_failed",
        "pass_completed",
    }
    rows = (
        db.query(RunEvent)
        .filter(RunEvent.run_id == run_id, RunEvent.type.in_(event_types))
        .filter(
            RunEvent.payload["item_id"].as_string().in_(item_ids)
            if item_ids is not None
            else True
        )
        .order_by(RunEvent.sequence.asc())
        .all()
    )
    outcomes: Dict[tuple[str, int], Dict[str, Any]] = {}
    active_attempts: Dict[tuple[str, int], Dict[str, Any]] = {}
    starts_by_pass: Dict[int, List[int]] = defaultdict(list)
    completed_passes: set[int] = set()

    def _pass_number(payload: Dict[str, Any]) -> int:
        try:
            return max(1, int(payload.get("pass_number") or 1))
        except (TypeError, ValueError):
            return 1

    def _event_ms(event: RunEvent) -> Optional[int]:
        sent_at = getattr(event, "sent_at", None)
        if sent_at is None:
            return None
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=timezone.utc)
        return int(sent_at.timestamp() * 1000)

    for event in rows:
        payload = event.payload if isinstance(event.payload, dict) else {}
        pass_number = _pass_number(payload)
        event_ms = _event_ms(event)
        start_ms = payload.get("task_started_at_ms")
        try:
            start_ms = int(start_ms) if start_ms is not None else None
        except (TypeError, ValueError):
            start_ms = None

        latency_ms = payload.get("latency_ms")
        try:
            latency_ms = float(latency_ms) if latency_ms is not None else None
        except (TypeError, ValueError):
            latency_ms = None

        if start_ms is None and latency_ms is not None and event_ms is not None:
            start_ms = int(event_ms - latency_ms)
        lifecycle_ms = start_ms if start_ms is not None else event_ms
        if lifecycle_ms is not None:
            starts_by_pass[pass_number].append(lifecycle_ms)

        if event.type == "pass_completed":
            completed_passes.add(pass_number)
            continue

        item_id = str(payload.get("item_id") or "")
        if not item_id:
            continue
        key = (item_id, pass_number)

        if event.type == "item_attempt_started":
            try:
                attempt_number = max(1, int(payload.get("attempt_number") or 1))
            except (TypeError, ValueError):
                attempt_number = 1
            active_attempts[key] = {
                "pass_number": pass_number,
                "status": "running",
                "output": None,
                "error": "",
                "latency_ms": None,
                "task_started_at_ms": lifecycle_ms,
                "trace_id": payload.get("trace_id") or "",
                "trace_url": payload.get("trace_url") or "",
                "retry_count": max(0, attempt_number - 1),
            }
            continue

        is_outcome = event.type in {"item_completed", "item_failed"}
        if event.type == "item_attempt_finished":
            is_outcome = bool(payload.get("is_last_attempt"))
        if not is_outcome:
            continue

        failed = (
            event.type == "item_failed"
            or str(payload.get("status") or "").lower() == "failed"
        )
        try:
            retry_count = max(0, int(payload.get("retry_count") or 0))
        except (TypeError, ValueError):
            retry_count = 0
        if event.type == "item_attempt_finished":
            try:
                retry_count = max(
                    retry_count, int(payload.get("attempt_number") or 1) - 1
                )
            except (TypeError, ValueError):
                pass
        error = str(payload.get("error") or "")
        output = payload.get("output")
        previous = outcomes.get(key) or {}
        if output is None and previous.get("output") not in (None, ""):
            output = previous["output"]
        if start_ms is None:
            start_ms = previous.get("task_started_at_ms")
        if latency_ms is None:
            latency_ms = previous.get("latency_ms")
        outcomes[key] = {
            "pass_number": pass_number,
            "status": "error" if failed else "completed",
            "output": f"ERROR: {error}" if failed and error else _stringify(output),
            "error": error,
            "latency_ms": latency_ms,
            "task_started_at_ms": start_ms,
            "trace_id": payload.get("trace_id") or "",
            "trace_url": payload.get("trace_url") or "",
            "retry_count": retry_count,
        }
        active_attempts.pop(key, None)

    return {
        "outcomes": outcomes,
        "active_attempts": active_attempts,
        "starts_by_pass": starts_by_pass,
        "completed_passes": completed_passes,
    }


def _strip_model_provider(model_name: str) -> str:
    """Normalize 'provider/model' -> 'model' for consistent display."""
    if not model_name:
        return model_name
    idx = model_name.find("/")
    return model_name[idx + 1 :] if idx > 0 else model_name


def _extract_langfuse_ids(run_metadata: dict) -> tuple[str, str]:
    """Extract (host, project_id) from langfuse_url stored in run metadata.

    The SDK sends langfuse_url like ``https://cloud.langfuse.com/project/<id>/datasets/...``
    but does NOT explicitly send ``langfuse_host`` or ``langfuse_project_id``.
    """
    langfuse_url = (
        run_metadata.get("langfuse_url", "") if isinstance(run_metadata, dict) else ""
    )
    host = (
        run_metadata.get("langfuse_host", "") if isinstance(run_metadata, dict) else ""
    )
    project_id = (
        run_metadata.get("langfuse_project_id", "")
        if isinstance(run_metadata, dict)
        else ""
    )
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
    injection = f"<script>window.__QYM_ROOT_PATH__ = {json.dumps(root)};</script>"
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


def _platform_static_dashboard_analyzer() -> Path:
    return _platform_static_dir() / "dashboard" / "analyzer.html"


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


def _platform_static_datasets() -> Path:
    return _platform_static_dir() / "dashboard" / "datasets.html"


def _platform_static_docs_guide() -> Path:
    return _platform_static_dir() / "dashboard" / "docs.html"


def _project_path_prefix(request: Request, project_slug: str) -> str:
    path = request.url.path
    marker = f"/projects/{project_slug}"
    idx = path.find(marker)
    if idx < 0:
        return ""
    return path[:idx]


def _resolve_project_by_slug_for_ui(
    db: Session, principal: Principal, project_slug: str
) -> Project:
    project = (
        db.query(Project)
        .filter(Project.slug == project_slug, Project.is_active.is_(True))
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not has_project_access(db, principal, project.id):
        raise HTTPException(status_code=403, detail="Access denied")
    return project


def _maybe_redirect_to_login(
    request: Request, db: Session
) -> Optional[RedirectResponse]:
    settings = PlatformSettings()
    if not session_auth_enabled(settings):
        return None
    if get_session_user_and_provider(db, request):
        return None
    root = request_root_path(request)
    # ``request.url.path`` already includes ``root_path`` under a Starlette mount,
    # so do NOT prepend it again here. Only the redirect target needs the prefix.
    full_path = request.url.path + (
        f"?{request.url.query}" if request.url.query else ""
    )
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
  <link rel="stylesheet" href="{static_root}/dashboard.css?v=ui-consistency-20260730-10">
  <link rel="stylesheet" href="{static_root}/shell.css">
  <script src="{static_root}/auth.js"></script>
  <script src="{static_root}/shell.js?v=ui-consistency-20260730-10"></script>
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


def _guard_project_page(
    request: Request, db: Session, project_slug: str
) -> Optional[Any]:
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


def _analysis_query(
    request: Request,
    *,
    remove: set[str] | None = None,
    scope: str | None = None,
) -> str:
    """Preserve harmless analyzer query state while canonicalizing routes."""
    remove = remove or set()
    pairs = parse_qsl(request.url.query, keep_blank_values=True)
    result: list[tuple[str, str]] = []
    scope_written = False
    for key, value in pairs:
        if key in remove:
            continue
        if key == "scope" and scope is not None:
            if not scope_written:
                result.append(("scope", scope))
                scope_written = True
            continue
        result.append((key, value))
    if scope is not None and not scope_written:
        result.append(("scope", scope))
    return urlencode(result, doseq=True)


def _analysis_project_base(request: Request) -> str:
    path = request.url.path
    marker = "/projects/"
    return path.split(marker, 1)[0] if marker in path else ""


def _analysis_project_url(
    request: Request,
    project_slug: str,
    suffix: str = "analysis",
    query: str = "",
) -> str:
    path = (
        _analysis_project_base(request).rstrip("/")
        + "/projects/"
        + quote(str(project_slug), safe="")
        + ("/" + suffix.lstrip("/") if suffix else "")
    )
    return path + ("?" + query if query else "")


def _visible_run_for_redirect(
    db: Session,
    request: Request,
    run_id: str,
) -> Run | None:
    run = Run.active(db).filter(Run.id == run_id).first()
    if run is None:
        return None
    try:
        principal = require_ui_principal(
            request=request,
            db=db,
            x_user_email=request.headers.get("X-User-Email"),
            x_email=request.headers.get("X-Email"),
            x_admin_bootstrap=request.headers.get("X-Admin-Bootstrap"),
        )
    except HTTPException:
        return None
    return run if can_view_run(db, principal, run) else None


def _canonical_legacy_analyzer_redirect(
    run_id: str,
    request: Request,
    db: Session,
) -> RedirectResponse | None:
    run = _visible_run_for_redirect(db, request, run_id)
    if run is None:
        return None
    project = db.get(Project, run.project_id)
    if project is None:
        return None
    requested_scope = dict(parse_qsl(request.url.query, keep_blank_values=True)).get(
        "scope"
    )
    query = _analysis_query(
        request,
        scope="run" if requested_scope == "dashboard" else None,
    )
    return RedirectResponse(
        url=_analysis_project_url(
            request,
            project.slug,
            "runs/" + quote(run.id, safe="") + "/analyzer",
            query,
        ),
        status_code=307,
    )


def _canonical_project_analysis_redirect(
    project_slug: str,
    request: Request,
    db: Session,
) -> RedirectResponse | None:
    params = dict(parse_qsl(request.url.query, keep_blank_values=True))
    requested_run_id = params.get("run", "").strip()
    if requested_run_id:
        run = _visible_run_for_redirect(db, request, requested_run_id)
        if run is None:
            return None
        project = db.get(Project, run.project_id)
        if project is None:
            return None
        query = _analysis_query(request, remove={"run", "scope"})
        return RedirectResponse(
            url=_analysis_project_url(
                request,
                project.slug,
                "runs/" + quote(run.id, safe="") + "/analyzer",
                query,
            ),
            status_code=307,
        )

    aliases = {"diagnosis": "categories", "project": "rules", "dashboard": "run"}
    requested_scope = params.get("scope")
    canonical_scope = aliases.get(requested_scope or "")
    if canonical_scope is not None:
        query = _analysis_query(request, scope=canonical_scope)
        return RedirectResponse(
            url=_analysis_project_url(request, project_slug, "analysis", query),
            status_code=307,
        )
    return None


def _canonical_project_run_analyzer_redirect(
    project_slug: str,
    run_id: str,
    request: Request,
    db: Session,
) -> RedirectResponse | None:
    run = _visible_run_for_redirect(db, request, run_id)
    if run is not None:
        project = db.get(Project, run.project_id)
        if project is not None and project.slug != project_slug:
            return RedirectResponse(
                url=_analysis_project_url(
                    request,
                    project.slug,
                    "runs/" + quote(run.id, safe="") + "/analyzer",
                    _analysis_query(request),
                ),
                status_code=307,
            )
    requested_scope = dict(parse_qsl(request.url.query, keep_blank_values=True)).get(
        "scope"
    )
    if requested_scope == "dashboard":
        return RedirectResponse(
            url=_analysis_project_url(
                request,
                project_slug,
                "runs/" + quote(run_id, safe="") + "/analyzer",
                _analysis_query(request, remove={"scope"}, scope="run"),
            ),
            status_code=307,
        )
    aliases = {"diagnosis": "categories", "project": "rules"}
    canonical_scope = aliases.get(requested_scope or "")
    if canonical_scope is not None:
        return RedirectResponse(
            url=_analysis_project_url(
                request,
                project_slug,
                "analysis",
                _analysis_query(request, remove={"scope"}, scope=canonical_scope),
            ),
            status_code=307,
        )
    if requested_scope in {"categories", "rules", "documents"}:
        return RedirectResponse(
            url=_analysis_project_url(
                request,
                project_slug,
                "analysis",
                _analysis_query(
                    request, remove={"scope"}, scope=str(requested_scope)
                ),
            ),
            status_code=307,
        )
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
            ends.append(
                int(span.start_time_ns + (float(span.duration_ms) * 1_000_000.0))
            )
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
    if (
        started_at_ns is not None
        and ended_at_ns is not None
        and ended_at_ns >= started_at_ns
    ):
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


def _serialize_attempt_trace_payload(
    attempt: Dict[str, Any], spans: List[Span]
) -> Dict[str, Any]:
    return {
        "pass_number": attempt.get("pass_number"),
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


def _build_item_trace_payload(
    item: RunItem,
    attempts: List[Dict[str, Any]],
    *,
    retry_count_override: Optional[int] = None,
    fallback_to_item_trace: bool = True,
) -> Dict[str, Any]:
    retry_count = (
        int(retry_count_override)
        if retry_count_override is not None
        else int(
            getattr(item, "retry_count", 0)
            or (
                (item.item_metadata or {}).get("retry_count")
                if isinstance(item.item_metadata, dict)
                else 0
            )
            or 0
        )
    )
    last_attempt = attempts[-1] if attempts else None
    last_summary = (
        (last_attempt or {}).get("summary") if isinstance(last_attempt, dict) else None
    )
    last_spans = (
        (last_attempt or {}).get("spans") if isinstance(last_attempt, dict) else None
    )
    return {
        "item": {
            "run_id": item.run_id,
            "item_id": item.item_id,
            "trace_id": (last_attempt or {}).get("trace_id")
            or (item.trace_id if fallback_to_item_trace else "")
            or "",
            "trace_url": (last_attempt or {}).get("trace_url")
            or (item.trace_url if fallback_to_item_trace else "")
            or "",
            "retry_count": retry_count,
        },
        "summary": last_summary or _build_trace_summary([]),
        "spans": last_spans or [],
        "attempts": attempts,
    }


def _dataset_version_info_map(
    db: Session, runs: List[Run]
) -> Dict[str, Dict[str, Any]]:
    """Resolve the dataset version label and aliases for a batch of runs.

    Keyed by ``dataset_version_id``; returns ``{"dataset_version": "v4",
    "dataset_aliases": ["production"]}``. Aliases reflect what currently points at that
    version, so a run shows ``production`` when its version is the live production one.
    Runs with no ``dataset_version_id`` simply aren't in the map.
    """
    version_ids = {run.dataset_version_id for run in runs if run.dataset_version_id}
    if not version_ids:
        return {}
    versions = {
        v.id: v
        for v in db.query(DatasetVersion)
        .filter(DatasetVersion.id.in_(version_ids))
        .all()
    }
    aliases_by_version: Dict[str, List[str]] = defaultdict(list)
    for alias in (
        db.query(DatasetAlias)
        .filter(DatasetAlias.dataset_version_id.in_(version_ids))
        .all()
    ):
        aliases_by_version[alias.dataset_version_id].append(alias.alias)
    info: Dict[str, Dict[str, Any]] = {}
    for vid in version_ids:
        v = versions.get(vid)
        info[vid] = {
            "dataset_version": v.version if v else None,
            "dataset_aliases": sorted(aliases_by_version.get(vid, [])),
        }
    return info


def _dataset_version_fields(
    run: Run, info_map: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """Per-run dataset version/alias fields for inclusion in a run payload."""
    entry = info_map.get(run.dataset_version_id) if run.dataset_version_id else None
    return {
        "dataset_version": entry["dataset_version"] if entry else None,
        "dataset_aliases": entry["dataset_aliases"] if entry else [],
    }


def _compute_run_summary(db: Session, run: Run) -> Dict[str, Any]:
    items: List[RunItem] = (
        db.query(RunItem)
        .filter(RunItem.run_id == run.id)
        .order_by(RunItem.index.asc())
        .all()
    )
    total_items = len(items)
    error_items = {it.item_id for it in items if it.error}
    error_count = len(error_items)
    total_retries = sum(int(it.retry_count or 0) for it in items)
    success_count = total_items - error_count
    completed_count = len(
        [it for it in items if (it.output is not None) or (it.error is not None)]
    )

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
        by_item_metric: Dict[tuple[str, str], RunItemScore] = {
            (s.item_id, s.metric_name): s for s in scores
        }
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
            decision_user = (
                db.query(User).filter(User.id == approval.decision_by_user_id).first()
            )
            if decision_user:
                decision_by = {
                    "id": decision_user.id,
                    "email": decision_user.email,
                    "display_name": decision_user.display_name
                    or decision_user.email.split("@")[0],
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
        "langfuse_url": run.run_metadata.get("langfuse_url")
        if isinstance(run.run_metadata, dict)
        else None,
        "langfuse_dataset_id": run.run_metadata.get("langfuse_dataset_id")
        if isinstance(run.run_metadata, dict)
        else None,
        "langfuse_run_id": run.run_metadata.get("langfuse_run_id")
        if isinstance(run.run_metadata, dict)
        else None,
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
    dataset_fields: Optional[Dict[str, Any]] = None,
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
        "dataset_version": (dataset_fields or {}).get("dataset_version"),
        "dataset_aliases": (dataset_fields or {}).get("dataset_aliases", []),
        "model_name": _strip_model_provider(run.model or ""),
        "status": run.status.value
        if hasattr(run.status, "value")
        else str(run.status or ""),
        "timestamp": _iso(run.started_at or run.created_at),
        "started_at": _iso(run.started_at) if run.started_at else None,
        "last_event_at": _iso(run.last_event_at or run.updated_at or run.created_at),
        "progress_completed": completed_count,
        "progress_total": expected_total,
        "progress_pct": (completed_count / expected_total) if expected_total else None,
        "total_items": int(item_agg.get("total") or 0),
        "error_count": int(item_agg.get("error_count") or 0),
        "samples": int(getattr(run, "samples", 1) or 1),
        "last_completed_pass": (
            run.run_metadata.get("last_completed_pass")
            if isinstance(run.run_metadata, dict)
            else None
        ),
        "owner": owner_info,
        "project": project_info,
    }


def _summarize_runs_for_admin(db: Session, runs: List[Run]) -> List[Dict[str, Any]]:
    if not runs:
        return []

    run_ids = [run.id for run in runs]
    item_agg_rows = (
        db.query(
            RunItem.run_id,
            func.count().label("total"),
            func.count(case((RunItem.error.isnot(None), 1))).label("error_count"),
            func.count(
                case(((RunItem.output.isnot(None)) | (RunItem.error.isnot(None)), 1))
            ).label("completed"),
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
    projects = (
        db.query(Project).filter(Project.id.in_(project_ids)).all()
        if project_ids
        else []
    )
    owners = db.query(User).filter(User.id.in_(owner_ids)).all() if owner_ids else []
    project_map = {project.id: project for project in projects}
    owner_map = {owner.id: owner for owner in owners}
    dataset_info = _dataset_version_info_map(db, runs)

    return [
        _live_run_summary(
            run,
            project=project_map.get(run.project_id),
            owner=owner_map.get(run.owner_user_id),
            item_agg=item_agg.get(run.id, {}),
            dataset_fields=_dataset_version_fields(run, dataset_info),
        )
        for run in runs
    ]


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
def dashboard_project_index(
    project_slug: str, request: Request, db: Session = Depends(get_db)
) -> Any:
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


@router.get("/docs-guide", response_model=None)
def docs_guide_index(request: Request, db: Session = Depends(get_db)) -> Any:
    redirect = _maybe_redirect_to_login(request, db)
    if redirect:
        return redirect
    idx = _platform_static_docs_guide()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Docs UI not found")
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
def project_reviews_index(
    project_slug: str, request: Request, db: Session = Depends(get_db)
) -> Any:
    guarded = _guard_project_page(request, db, project_slug)
    if guarded:
        return guarded
    return reviews_index(request=request, db=db)


@router.get("/projects/{project_slug}/charts", response_model=None)
def project_charts(
    project_slug: str, request: Request, db: Session = Depends(get_db)
) -> Any:
    guarded = _guard_project_page(request, db, project_slug)
    if guarded:
        return guarded
    idx = _platform_static_charts()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Charts UI not found")
    return _dashboard_html_response(idx, request)


@router.get("/projects/{project_slug}/models", response_model=None)
def project_models(
    project_slug: str, request: Request, db: Session = Depends(get_db)
) -> Any:
    guarded = _guard_project_page(request, db, project_slug)
    if guarded:
        return guarded
    idx = _platform_static_models()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Models UI not found")
    return _dashboard_html_response(idx, request)


@router.get("/projects/{project_slug}/datasets", response_model=None)
def project_datasets(
    project_slug: str, request: Request, db: Session = Depends(get_db)
) -> Any:
    guarded = _guard_project_page(request, db, project_slug)
    if guarded:
        return guarded
    idx = _platform_static_datasets()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Datasets UI not found")
    return _dashboard_html_response(idx, request)


@router.get("/projects/{project_slug}/datasets/{dataset_ref:path}", response_model=None)
def project_dataset_detail(
    project_slug: str, dataset_ref: str, request: Request, db: Session = Depends(get_db)
) -> Any:
    guarded = _guard_project_page(request, db, project_slug)
    if guarded:
        return guarded
    idx = _platform_static_datasets()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Datasets UI not found")
    return _dashboard_html_response(idx, request)


@router.get("/projects/{project_slug}/overview", response_model=None)
def project_overview(
    project_slug: str, request: Request, db: Session = Depends(get_db)
) -> Any:
    guarded = _guard_project_page(request, db, project_slug)
    if guarded:
        return guarded
    idx = _platform_static_overview()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Overview UI not found")
    return _dashboard_html_response(idx, request)


@router.get("/projects/{project_slug}/settings", response_model=None)
def project_settings_index(
    project_slug: str, request: Request, db: Session = Depends(get_db)
) -> Any:
    guarded = _guard_project_page(request, db, project_slug)
    if guarded:
        return guarded
    idx = _platform_static_project_settings()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Project settings UI not found")
    return _dashboard_html_response(idx, request)


@router.get("/run/{run_id:path}/analyzer", response_model=None)
def analyzer_ui(run_id: str, request: Request, db: Session = Depends(get_db)) -> Any:
    redirect = _maybe_redirect_to_login(request, db)
    if redirect:
        return redirect
    canonical = _canonical_legacy_analyzer_redirect(run_id, request, db)
    if canonical:
        return canonical
    idx = _platform_static_dashboard_analyzer()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="LLM Analyzer UI not found")
    return _dashboard_html_response(idx, request)


@router.get("/projects/{project_slug}/analysis", response_model=None)
def project_analysis_ui(
    project_slug: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Any:
    """Serve the project's first-class auto-analysis workspace."""
    guarded = _guard_project_page(request, db, project_slug)
    if guarded:
        return guarded
    canonical = _canonical_project_analysis_redirect(project_slug, request, db)
    if canonical:
        return canonical
    idx = _platform_static_dashboard_analyzer()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Auto-analysis UI not found")
    return _dashboard_html_response(idx, request)


@router.get("/projects/{project_slug}/runs/{run_id:path}/analyzer", response_model=None)
def project_analyzer_ui(
    project_slug: str,
    run_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Any:
    guarded = _guard_project_page(request, db, project_slug)
    if guarded:
        return guarded
    canonical = _canonical_project_run_analyzer_redirect(
        project_slug, run_id, request, db
    )
    if canonical:
        return canonical
    idx = _platform_static_dashboard_analyzer()
    if not idx.exists():
        raise HTTPException(status_code=404, detail="LLM Analyzer UI not found")
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
def project_run_ui(
    project_slug: str, run_id: str, request: Request, db: Session = Depends(get_db)
) -> Any:
    guarded = _guard_project_page(request, db, project_slug)
    if guarded:
        return guarded
    return run_ui(run_id=run_id, request=request, db=db)


@router.get("/api/runs")
def legacy_list_runs(
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    project_slug: Optional[str] = Query(default=None),
    status: Optional[str] = Query(
        default=None,
        description="Filter by run workflow status; comma-separated values allowed",
    ),
    exclude_live: bool = Query(
        default=False, description="Exclude live run statuses from the result set"
    ),
    include_total: bool = Query(
        default=True,
        description=(
            "Compute total_count. Defaults to true so existing clients are "
            "unaffected; pagers that already know the total can pass false to "
            "skip a full count on every page."
        ),
    ),
    user: Optional[str] = Query(
        default=None, description="Filter by run owner user id, email, or display name"
    ),
    user_id: Optional[str] = Query(
        default=None, description="Filter by run owner user id"
    ),
    owner_user_id: Optional[str] = Query(
        default=None, description="Filter by run owner user id"
    ),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    q = Run.active(db).order_by(Run.created_at.desc())

    selected_project = None
    if project_slug:
        selected_project = (
            db.query(Project)
            .filter(Project.slug == project_slug, Project.is_active.is_(True))
            .first()
        )
        if not selected_project:
            raise HTTPException(status_code=404, detail="Project not found")
        if not has_project_access(db, principal, selected_project.id):
            raise HTTPException(status_code=403, detail="Access denied")
    else:
        if principal.auth_type == "none" or principal.user.role == UserRole.ADMIN:
            selected_project = (
                db.query(Project)
                .filter(Project.is_active.is_(True))
                .order_by(Project.name)
                .first()
            )
        else:
            selected_project = (
                db.query(Project)
                .join(ProjectMembership, ProjectMembership.project_id == Project.id)
                .filter(
                    ProjectMembership.user_id == principal.user.id,
                    Project.is_active.is_(True),
                )
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

    if status:
        statuses: list[RunWorkflowStatus] = []
        for raw_status in status.split(","):
            normalized = raw_status.strip().upper()
            if not normalized:
                continue
            try:
                statuses.append(RunWorkflowStatus(normalized))
            except ValueError:
                raise HTTPException(
                    status_code=400, detail=f"Invalid run status: {raw_status}"
                ) from None
        if statuses:
            q = q.filter(Run.status.in_(statuses))
    if exclude_live:
        q = q.filter(~Run.status.in_(_LIVE_RUN_STATUSES))

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

    # Total count before pagination.  The count scans the whole project, so a
    # pager walking N pages paid for it N times; callers that already have it
    # can opt out.
    total_count = q.count() if include_total else None

    # Apply pagination
    runs: List[Run] = q.offset(offset).limit(limit).all()
    _reconcile_run_liveness(db, runs)

    if not runs:
        return {
            "tasks": {},
            "last_updated": to_api_timestamp(utc_now_naive()),
            "total_count": total_count,
            "project": {
                "id": selected_project.id,
                "slug": selected_project.slug,
                "name": selected_project.name,
            },
        }

    run_ids = [r.id for r in runs]
    metric_specs_by_run = _metric_specs_for_runs(db, run_ids)

    # --- Batch query: item aggregates per run ---
    item_agg_rows = (
        db.query(
            RunItem.run_id,
            func.count().label("total"),
            func.count(case((RunItem.error.isnot(None), 1))).label("error_count"),
            func.count(
                case(((RunItem.output.isnot(None)) | (RunItem.error.isnot(None)), 1))
            ).label("completed"),
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
            "avg_latency": float(row.avg_latency)
            if row.avg_latency is not None
            else 0.0,
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
        item_agg.setdefault(
            run_id,
            {
                "total": 0,
                "error_count": 0,
                "completed": 0,
                "total_retries": 0,
                "avg_latency": 0.0,
            },
        )["median_latency"] = _median(values)

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
            (RunItem.run_id == RunItemScore.run_id)
            & (RunItem.item_id == RunItemScore.item_id),
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

    # Repeat-run summaries power the pass-dot strip on the runs list. Detailed
    # uncertainty belongs on the run page, where its meaning can be explained;
    # the scan-oriented list intentionally exposes only point estimates.
    sampled_run_ids = [r.id for r in runs if int(getattr(r, "samples", 1) or 1) > 1]
    repeat_attempt_summaries = _repeat_attempt_summaries(db, sampled_run_ids)
    for run_id, attempt_summary in repeat_attempt_summaries.items():
        agg = item_agg.setdefault(
            run_id,
            {
                "total": 0,
                "error_count": 0,
                "completed": 0,
                "total_retries": 0,
                "avg_latency": 0.0,
            },
        )
        if "avg_latency_ms" in attempt_summary:
            agg["avg_latency"] = attempt_summary["avg_latency_ms"]
            agg["median_latency"] = attempt_summary["median_latency_ms"]
    pass_summary_map: Dict[str, List[Dict[str, Any]]] = {}
    pass_analysis_cause_totals: Dict[str, int] = {}
    if sampled_run_ids:
        from qym_platform.db.models import RunItemAttempt, RunItemPassScore

        dot_score_rows = (
            db.query(
                RunItemPassScore.run_id,
                RunItemPassScore.metric_name,
                RunItemPassScore.pass_number,
                func.avg(RunItemPassScore.score_numeric).label("mean"),
            )
            .filter(
                RunItemPassScore.run_id.in_(sampled_run_ids),
                RunItemPassScore.score_numeric.isnot(None),
            )
            .group_by(
                RunItemPassScore.run_id,
                RunItemPassScore.metric_name,
                RunItemPassScore.pass_number,
            )
            .all()
        )
        pass_means: Dict[str, Dict[str, Dict[int, float]]] = {}
        for rid, metric_name, pass_number, mean in dot_score_rows:
            if mean is None:
                continue
            pass_means.setdefault(rid, {}).setdefault(metric_name, {})[
                int(pass_number)
            ] = float(mean)

        dot_attempt_rows = (
            db.query(
                RunItemAttempt.run_id,
                RunItemAttempt.pass_number,
                func.count(RunItemAttempt.id).label("n"),
                func.sum(
                    case((func.lower(RunItemAttempt.status) == "failed", 1), else_=0)
                ).label("errs"),
            )
            .filter(
                RunItemAttempt.run_id.in_(sampled_run_ids),
                RunItemAttempt.is_last_attempt.is_(True),
            )
            .group_by(RunItemAttempt.run_id, RunItemAttempt.pass_number)
            .all()
        )
        pass_attempts: Dict[str, Dict[int, int]] = {}
        pass_errors: Dict[str, Dict[int, int]] = {}
        for rid, pass_number, n_attempts, errs in dot_attempt_rows:
            pass_attempts.setdefault(rid, {})[int(pass_number)] = int(n_attempts or 0)
            pass_errors.setdefault(rid, {})[int(pass_number)] = int(errs or 0)

        # A repeat-run diagnosis is stored on the pass score, not on the
        # reduced RunItem.  Keep the runs-list chip scoped to that pass so a
        # diagnosis on one sample cannot appear on every sample row.
        # Only pass scores that carry an analysis payload can contribute a
        # cause; the loop below discards the rest.  Applying that predicate in
        # SQL and streaming the result keeps this independent of pass volume.
        pass_analysis_rows = (
            db.query(
                RunItemPassScore.run_id,
                RunItemPassScore.pass_number,
                RunItemPassScore.meta,
            )
            .filter(
                RunItemPassScore.run_id.in_(sampled_run_ids),
                cast(RunItemPassScore.meta, Text).like(
                    f'%"{PASS_ANALYSIS_META_KEY}"%'
                ),
            )
            .yield_per(1000)
        )
        pass_analysis_causes: Dict[str, Dict[int, set[str]]] = {}
        for rid, pass_number, meta in pass_analysis_rows:
            analysis = (
                meta.get(PASS_ANALYSIS_META_KEY)
                if isinstance(meta, dict)
                else None
            )
            if not isinstance(analysis, dict):
                continue
            pass_analysis_causes.setdefault(rid, {}).setdefault(
                int(pass_number), set()
            ).update(analysis_root_causes(analysis))

        for r in runs:
            k = int(getattr(r, "samples", 1) or 1)
            if k <= 1:
                continue
            metrics_list = list(r.metrics or [])
            primary = metrics_list[0] if metrics_list else None
            means = (pass_means.get(r.id) or {}).get(primary, {}) if primary else {}
            attempts = pass_attempts.get(r.id, {})
            errors = pass_errors.get(r.id, {})
            last_completed = 0
            if isinstance(r.run_metadata, dict):
                try:
                    last_completed = int(r.run_metadata.get("last_completed_pass") or 0)
                except (TypeError, ValueError):
                    last_completed = 0
            run_status = str(getattr(r.status, "value", r.status) or "").upper()
            summaries: List[Dict[str, Any]] = []
            for p in range(1, k + 1):
                has_data = p in means or p in attempts
                p_status = _repeat_pass_status(
                    pass_number=p,
                    last_completed=last_completed,
                    has_data=has_data,
                    run_status=run_status,
                )
                summaries.append(
                    {
                        "pass_number": p,
                        "status": p_status,
                        "primary_score": means.get(p),
                        "error_count": errors.get(p, 0),
                        "analysis_cause_count": len(
                            (pass_analysis_causes.get(r.id) or {}).get(p, set())
                        ),
                    }
                )
            pass_summary_map[r.id] = summaries
            # The aggregate row represents the whole repeat run.  Its chip
            # therefore totals each sample's diagnosis count, including the
            # same category when it appears on multiple samples.
            pass_analysis_cause_totals[r.id] = sum(
                len((pass_analysis_causes.get(r.id) or {}).get(p, set()))
                for p in range(1, k + 1)
            )

    # --- Batch query: approvals ---
    approvals = db.query(Approval).filter(Approval.run_id.in_(run_ids)).all()
    approval_map = {a.run_id: a for a in approvals}

    # --- Batch query: distinct root-cause counts per run ---
    # Powers the runs-table ANALYSIS column. The LIKE prefilter keeps the scan
    # to items that carry any analysis data; cause extraction is done in Python
    # so the JSON handling is identical on PostgreSQL and SQLite.
    analysis_rows = (
        db.query(RunItem.run_id, RunItem.item_metadata)
        .filter(
            RunItem.run_id.in_(run_ids),
            cast(RunItem.item_metadata, Text).like('%"root_cause"%'),
        )
        .yield_per(1000)
    )
    analysis_causes: Dict[str, set] = {}
    for row in analysis_rows:
        md = row.item_metadata if isinstance(row.item_metadata, dict) else {}
        causes = analysis_causes.setdefault(row.run_id, set())
        legacy = str(md.get("root_cause") or "").strip()
        if legacy:
            causes.add(legacy)
        metric_analyses = md.get("metric_analyses")
        if isinstance(metric_analyses, dict):
            for entry in metric_analyses.values():
                if isinstance(entry, dict):
                    cause = str(entry.get("root_cause") or "").strip()
                    if cause:
                        causes.add(cause)

    # --- Batch query: all referenced users ---
    user_ids = {r.owner_user_id for r in runs}
    user_ids |= {a.decision_by_user_id for a in approvals if a.decision_by_user_id}
    users = db.query(User).filter(User.id.in_(user_ids)).all()
    user_map = {u.id: u for u in users}

    # --- Build summaries from pre-fetched data ---
    dataset_info = _dataset_version_info_map(db, runs)
    tasks: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for r in runs:
        agg = item_agg.get(
            r.id,
            {
                "total": 0,
                "error_count": 0,
                "completed": 0,
                "total_retries": 0,
                "avg_latency": 0.0,
                "median_latency": 0.0,
            },
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
        repeat_duration = repeat_attempt_summaries.get(r.id, {}).get("duration_ms")
        if repeat_duration is not None:
            duration_ms = repeat_duration

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
                        "display_name": decision_user.display_name
                        or decision_user.email.split("@")[0],
                    }
            approval_info = {
                "decision": approval.decision.value if approval.decision else None,
                "decision_at": _iso(approval.decision_at)
                if approval.decision_at
                else None,
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
            "dataset_version": _dataset_version_fields(r, dataset_info)[
                "dataset_version"
            ],
            "dataset_aliases": _dataset_version_fields(r, dataset_info)[
                "dataset_aliases"
            ],
            "timestamp": _iso(started_at),
            "file_path": r.id,
            "metrics": metrics,
            "metric_specs": metric_specs_by_run.get(r.id, {}),
            "metric_averages": metric_averages,
            "total_items": total_items,
            "progress_completed": completed_count,
            "progress_total": expected_total,
            "progress_pct": (completed_count / expected_total)
            if expected_total
            else None,
            "success_count": success_count,
            "error_count": error_count,
            "total_retries": total_retries,
            "success_rate": (success_count / total_items) if total_items else 0.0,
            "avg_latency_ms": agg["avg_latency"],
            "median_latency_ms": agg.get("median_latency", 0.0),
            "duration_ms": duration_ms,
            "langfuse_url": r.run_metadata.get("langfuse_url")
            if isinstance(r.run_metadata, dict)
            else None,
            "langfuse_dataset_id": r.run_metadata.get("langfuse_dataset_id")
            if isinstance(r.run_metadata, dict)
            else None,
            "langfuse_run_id": r.run_metadata.get("langfuse_run_id")
            if isinstance(r.run_metadata, dict)
            else None,
            "status": r.status,
            "run_config": {},  # Omit full config from list view for payload size
            "samples": int(getattr(r, "samples", 1) or 1),
            "report_k": (
                r.run_config.get("report_k") if isinstance(r.run_config, dict) else None
            ),
            "pass_summaries": pass_summary_map.get(r.id) or None,
            "last_completed_pass": (
                r.run_metadata.get("last_completed_pass")
                if isinstance(r.run_metadata, dict)
                else None
            ),
            "git_branch": r.run_config.get("git_branch")
            if isinstance(r.run_config, dict)
            else None,
            "git_commit": r.run_config.get("git_commit")
            if isinstance(r.run_config, dict)
            else None,
            "owner": owner_info,
            "approval": approval_info,
            "analysis_cause_count": (
                pass_analysis_cause_totals[r.id]
                if int(getattr(r, "samples", 1) or 1) > 1
                and pass_analysis_cause_totals.get(r.id, 0) > 0
                else len(analysis_causes.get(r.id, ()))
            ),
            "trace_stats": r.run_metadata.get("trace_stats")
            if isinstance(r.run_metadata, dict)
            else None,
            "product_eval": r.run_metadata.get("product_eval")
            if isinstance(r.run_metadata, dict)
            else None,
        }

        task = summary["task_name"]
        model = summary["model_name"] or "nomodel"
        tasks.setdefault(task, {}).setdefault(model, []).append(summary)

    return {
        "tasks": tasks,
        "last_updated": to_api_timestamp(utc_now_naive()),
        "total_count": total_count,
        "project": {
            "id": selected_project.id,
            "slug": selected_project.slug,
            "name": selected_project.name,
        },
    }


@router.get("/api/runs/live")
def list_live_runs(
    limit: int = Query(default=25, ge=1, le=100),
    project_slug: Optional[str] = Query(default=None),
    all_projects: bool = Query(default=False),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    q = (
        Run.active(db)
        .filter(Run.status.in_(_LIVE_RUN_STATUSES))
        .order_by(Run.last_event_at.desc(), Run.created_at.desc())
    )
    selected_project = None

    if all_projects:
        if principal.auth_type != "none" and principal.user.role != UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Admin only")
        q = q.join(Project, Project.id == Run.project_id).filter(
            Project.is_active.is_(True)
        )
    elif project_slug:
        selected_project = (
            db.query(Project)
            .filter(Project.slug == project_slug, Project.is_active.is_(True))
            .first()
        )
        if not selected_project:
            raise HTTPException(status_code=404, detail="Project not found")
        if not has_project_access(db, principal, selected_project.id):
            raise HTTPException(status_code=403, detail="Access denied")
        q = q.filter(Run.project_id == selected_project.id)
    else:
        if principal.auth_type == "none" or principal.user.role == UserRole.ADMIN:
            selected_project = (
                db.query(Project)
                .filter(Project.is_active.is_(True))
                .order_by(Project.name)
                .first()
            )
        else:
            selected_project = (
                db.query(Project)
                .join(ProjectMembership, ProjectMembership.project_id == Project.id)
                .filter(
                    ProjectMembership.user_id == principal.user.id,
                    Project.is_active.is_(True),
                )
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
                {
                    "id": selected_project.id,
                    "slug": selected_project.slug,
                    "name": selected_project.name,
                }
                if selected_project
                else None
            ),
        }

    return {
        "runs": _summarize_runs_for_admin(db, runs),
        "total_count": total_count,
        "last_updated": to_api_timestamp(utc_now_naive()),
        "project": (
            {
                "id": selected_project.id,
                "slug": selected_project.slug,
                "name": selected_project.name,
            }
            if selected_project
            else None
        ),
    }


@router.get("/api/runs/recent")
def list_recent_runs(
    global_limit: int = Query(default=20, ge=1, le=100),
    global_offset: int = Query(default=0, ge=0),
    per_project_limit: int = Query(default=5, ge=1, le=25),
    include_projects: bool = Query(default=True),
    all_projects: bool = Query(default=False),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    if not all_projects:
        raise HTTPException(status_code=400, detail="all_projects=true is required")
    if principal.auth_type != "none" and principal.user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin only")

    base_q = (
        Run.active(db)
        .join(Project, Project.id == Run.project_id)
        .filter(Project.is_active.is_(True), ~Run.status.in_(_LIVE_RUN_STATUSES))
    )
    total_count = base_q.count()
    global_runs = (
        base_q.order_by(Run.created_at.desc())
        .offset(global_offset)
        .limit(global_limit)
        .all()
    )

    project_sections: List[Dict[str, Any]] = []
    if include_projects:
        projects = (
            db.query(Project)
            .filter(Project.is_active.is_(True))
            .order_by(Project.name.asc())
            .all()
        )
        for project in projects:
            project_runs = (
                Run.active(db)
                .filter(
                    Run.project_id == project.id, ~Run.status.in_(_LIVE_RUN_STATUSES)
                )
                .order_by(Run.created_at.desc())
                .limit(per_project_limit)
                .all()
            )
            if not project_runs:
                continue
            project_sections.append(
                {
                    "project": {
                        "id": project.id,
                        "slug": project.slug,
                        "name": project.name,
                    },
                    "runs": _summarize_runs_for_admin(db, project_runs),
                }
            )

    return {
        "runs": _summarize_runs_for_admin(db, global_runs),
        "projects": project_sections,
        "total_count": total_count,
        "global_limit": global_limit,
        "global_offset": global_offset,
        "last_updated": to_api_timestamp(utc_now_naive()),
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
    metric_specs_by_run = _metric_specs_for_runs(db, run_ids)
    metrics_by_run = {run.id: list(run.metrics or []) for run in runs}
    dataset_info = _dataset_version_info_map(db, runs)
    runs_data: dict[str, dict[str, Any]] = {}
    stats_by_run: dict[str, dict[str, Any]] = {}

    for run in runs:
        metrics = metrics_by_run[run.id]
        stats = {
            "total": 0,
            "completed": 0,
            "in_progress": 0,
            "pending": 0,
            "failed": 0,
        }
        stats_by_run[run.id] = stats
        _dsv = _dataset_version_fields(run, dataset_info)
        runs_data[run.id] = {
            "run": {
                "run_id": run.id,
                "file_path": run.id,
                "run_name": _run_display_name(run),
                "metric_names": metrics,
                "metric_specs": metric_specs_by_run.get(run.id, {}),
                "task_name": run.task,
                "dataset_name": run.dataset,
                "dataset_version": _dsv["dataset_version"],
                "dataset_aliases": _dsv["dataset_aliases"],
                "model_name": _strip_model_provider(run.model or ""),
                "samples": int(getattr(run, "samples", 1) or 1),
            },
            "snapshot": {
                "rows": [],
                "stats": stats,
                "metric_names": metrics,
                "metric_specs": metric_specs_by_run.get(run.id, {}),
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
        value = (
            score.score_numeric if score.score_numeric is not None else score.score_raw
        )
        score_by_run_item.setdefault((score.run_id, score.item_id), {})[
            score.metric_name
        ] = value

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
                "metric_values": [
                    item_scores.get(metric_name, "") for metric_name in metrics
                ],
            }
        )

    for run_id, stats in stats_by_run.items():
        stats["success_rate"] = (
            (stats["completed"] / stats["total"] * 100.0) if stats["total"] else 0.0
        )
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
    view: Optional[str] = None,
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
        data = legacy_run_data(run_id=run_id, db=db, principal=principal, view=view)
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


def _build_run_data(
    db: Session,
    run: Run,
    *,
    item_ids: Optional[List[str]] = None,
    compact: bool = False,
) -> Dict[str, Any]:
    """Build the run + snapshot data dict used by the UI."""
    item_query = db.query(RunItem).filter(RunItem.run_id == run.id)
    if item_ids is not None:
        item_query = item_query.filter(RunItem.item_id.in_(item_ids))
    item_query = item_query.order_by(RunItem.index.asc())
    item_count = item_query.count() if compact else None
    items = item_query.yield_per(200) if compact else item_query.all()
    metrics = list(run.metrics or [])
    metric_specs = _metric_specs_for_runs(db, [run.id]).get(run.id, {})
    corrections = (
        db.query(ReviewCorrection)
        .filter(ReviewCorrection.run_id == run.id, ReviewCorrection.is_active.is_(True))
        .filter(
            ReviewCorrection.item_id.in_(item_ids) if item_ids is not None else True
        )
        .order_by(ReviewCorrection.created_at.desc())
        .all()
    )
    correction_by_item: Dict[str, ReviewCorrection] = {}
    corrections_by_item_metric: Dict[str, Dict[str, ReviewCorrection]] = {}
    for corr in corrections:
        if corr.metric_name:
            corrections_by_item_metric.setdefault(corr.item_id, {}).setdefault(
                corr.metric_name, corr
            )
        else:
            correction_by_item.setdefault(corr.item_id, corr)

    # Read pre-computed trace stats from stored metadata
    run_trace_stats = (
        run.run_metadata.get("trace_stats")
        if isinstance(run.run_metadata, dict)
        else None
    )
    run_config = run.run_config if isinstance(run.run_config, dict) else {}
    run_metadata = run.run_metadata if isinstance(run.run_metadata, dict) else {}

    # Build per-item score/meta for UI
    scores = (
        db.query(RunItemScore)
        .filter(RunItemScore.run_id == run.id)
        .filter(RunItemScore.item_id.in_(item_ids) if item_ids is not None else True)
        .all()
    )
    by_item: Dict[str, Dict[str, RunItemScore]] = {}
    for s in scores:
        by_item.setdefault(s.item_id, {})[s.metric_name] = s

    # Repeat runs: per-pass scores power the dot strips in the items table.
    run_samples = int(getattr(run, "samples", 1) or 1)
    pass_scores_by_item: Dict[str, Dict[str, Dict[int, Optional[float]]]] = {}
    pass_meta_by_item: Dict[str, Dict[str, Dict[int, Dict[str, Any]]]] = {}
    pass_analysis_by_item: Dict[str, Dict[str, Dict[int, Dict[str, Any]]]] = {}
    pass_attempts_by_item: Dict[str, Dict[int, Dict[str, Any]]] = {}
    if run_samples > 1:
        for ps in (
            db.query(RunItemPassScore)
            .filter(RunItemPassScore.run_id == run.id)
            .filter(
                RunItemPassScore.item_id.in_(item_ids) if item_ids is not None else True
            )
            .all()
        ):
            pass_scores_by_item.setdefault(ps.item_id, {}).setdefault(
                ps.metric_name, {}
            )[int(ps.pass_number)] = ps.score_numeric
            # Per-pass judge output, same shape as row-level metric_meta.
            ps_meta: dict[str, Any] = dict(ps.meta) if ps.meta else {}
            pass_analysis = ps_meta.pop(PASS_ANALYSIS_META_KEY, None)
            if isinstance(pass_analysis, dict):
                pass_analysis_by_item.setdefault(ps.item_id, {}).setdefault(
                    ps.metric_name, {}
                )[int(ps.pass_number)] = pass_analysis
            if ps.label:
                ps_meta.setdefault("label", ps.label)
            if ps.explanation:
                ps_meta.setdefault("explanation", ps.explanation)
            if ps_meta:
                pass_meta_by_item.setdefault(ps.item_id, {}).setdefault(
                    ps.metric_name, {}
                )[int(ps.pass_number)] = ps_meta

        # Every pass's final attempt — output, latency, trace — so the UI can
        # show each attempt, not just the item's last one.  Event state fills
        # the two gaps in this table: an attempt that is currently running and
        # legacy item outcomes that arrived without a final-attempt event.
        pass_event_state = _repeat_pass_event_state(db, run.id, item_ids=item_ids)
        all_attempts = (
            db.query(RunItemAttempt)
            .filter(RunItemAttempt.run_id == run.id)
            .filter(
                RunItemAttempt.item_id.in_(item_ids) if item_ids is not None else True
            )
            .all()
        )
        final_attempts = [
            attempt for attempt in all_attempts if attempt.is_last_attempt
        ]
        max_attempt_by_pair: Dict[tuple[str, int], int] = {}
        for attempt in all_attempts:
            key = (attempt.item_id, int(attempt.pass_number))
            max_attempt_by_pair[key] = max(
                max_attempt_by_pair.get(key, 0), int(attempt.attempt_number or 1)
            )
        retry_counts = {
            key: max(0, max_attempt - 1)
            for key, max_attempt in max_attempt_by_pair.items()
        }
        missing_output_pairs = {
            (att.item_id, int(att.pass_number))
            for att in final_attempts
            if att.output is None
        }
        recovered_outputs = _completed_pass_outputs(db, run.id, missing_output_pairs)
        run_status = str(getattr(run.status, "value", run.status) or "").upper()
        terminal_active_status = {
            "COMPLETED": "completed",
            "FAILED": "failed",
            "STOPPED": "stopped",
        }.get(run_status)
        active_event_attempts = pass_event_state["active_attempts"]
        if terminal_active_status:
            active_event_attempts = {
                key: {**payload, "status": terminal_active_status}
                for key, payload in active_event_attempts.items()
            }
        event_attempts = {
            **active_event_attempts,
            **pass_event_state["outcomes"],
        }
        trace_ids = {
            str(trace_id)
            for trace_id in [
                *(attempt.trace_id for attempt in final_attempts),
                *(payload.get("trace_id") for payload in event_attempts.values()),
            ]
            if trace_id
        }
        trace_aggregate_map = {
            aggregate.trace_id: aggregate
            for aggregate in (
                db.query(RunTraceAggregate)
                .filter(
                    RunTraceAggregate.run_id == run.id,
                    RunTraceAggregate.trace_id.in_(trace_ids),
                )
                .all()
                if trace_ids
                else []
            )
        }
        if trace_aggregate_map:
            from qym_platform.api.ingest import _trace_bucket_from_aggregate

            trace_stats_by_id = {
                trace_id: _trace_bucket_from_aggregate(aggregate)
                for trace_id, aggregate in trace_aggregate_map.items()
            }
        else:
            trace_stats_by_id = {}

        for att in final_attempts:
            att_error = att.error or ""
            is_failed = str(att.status or "").lower() == "failed"
            attempt_output = att.output
            if attempt_output is None:
                attempt_output = recovered_outputs.get(
                    (att.item_id, int(att.pass_number))
                )
            pass_attempts_by_item.setdefault(att.item_id, {})[int(att.pass_number)] = {
                "pass_number": int(att.pass_number),
                "status": "error" if is_failed else "completed",
                "output": (
                    f"ERROR: {att_error}"
                    if is_failed and att_error
                    else _stringify(attempt_output)
                ),
                "error": att_error,
                "latency_ms": att.latency_ms,
                "task_started_at_ms": att.task_started_at_ms,
                "trace_id": att.trace_id or "",
                "trace_url": att.trace_url or "",
                "retry_count": retry_counts.get((att.item_id, int(att.pass_number)), 0),
                "trace_stats": trace_stats_by_id.get(att.trace_id),
            }

        for (item_id, pass_number), event_attempt in event_attempts.items():
            if pass_number in pass_attempts_by_item.get(item_id, {}):
                continue
            payload = dict(event_attempt)
            payload["trace_stats"] = trace_stats_by_id.get(payload.get("trace_id"))
            pass_attempts_by_item.setdefault(item_id, {})[pass_number] = payload

    # Fallback timestamps: for items missing task_started_at_ms in item_metadata,
    # look up the item_started event's sent_at timestamp as an approximation.
    _item_start_ts: Dict[str, int] = {}
    need_ts = any(
        not (
            isinstance(it.item_metadata, dict)
            and it.item_metadata.get("task_started_at_ms")
        )
        for it in (
            item_query.with_entities(RunItem.item_metadata).yield_per(200)
            if compact
            else items
        )
    )
    if need_ts:
        started_events: List[RunEvent] = (
            db.query(RunEvent)
            .filter(RunEvent.run_id == run.id, RunEvent.type == "item_started")
            .filter(
                RunEvent.payload["item_id"].as_string().in_(item_ids)
                if item_ids is not None
                else True
            )
            .all()
        )
        for ev in started_events:
            payload = ev.payload or {}
            iid = payload.get("item_id")
            if iid and ev.sent_at:
                _item_start_ts[iid] = int(ev.sent_at.timestamp() * 1000)

    ui_rows = []
    stats = {
        "total": item_count if compact else len(items),
        "completed": 0,
        "in_progress": 0,
        "pending": 0,
        "failed": 0,
    }
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
            pass_values = (pass_scores_by_item.get(it.item_id) or {}).get(m)
            if run_samples > 1 and pass_values:
                metric_meta[m] = _repeat_aggregate_metric_meta(
                    pass_values,
                    dict(sc.meta) if isinstance(sc.meta, dict) else None,
                )
            elif sc.meta:
                metric_meta[m] = dict(sc.meta)
            if run_samples <= 1 and (sc.label or sc.explanation):
                if m not in metric_meta:
                    metric_meta[m] = {}
                if sc.label:
                    metric_meta[m]["label"] = sc.label
                if sc.explanation:
                    metric_meta[m]["explanation"] = sc.explanation

        # Resolve task_started_at_ms: prefer item_metadata, then fallback to event timestamp
        ts_ms = (
            it.item_metadata.get("task_started_at_ms")
            if isinstance(it.item_metadata, dict)
            else None
        )
        if not ts_ms:
            ts_ms = _item_start_ts.get(it.item_id)
        corr = correction_by_item.get(it.item_id)
        metric_corrections = corrections_by_item_metric.get(it.item_id, {})
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
                "output": (
                    _stringify(it.output) if not is_error else f"ERROR: {it.error}"
                ),
                "output_full": (
                    _stringify(it.output) if not is_error else f"ERROR: {it.error}"
                ),
                "expected": _stringify(it.expected),
                "expected_full": _stringify(it.expected),
                "time": (
                    ""
                    if it.latency_ms is None
                    else f"{(it.latency_ms or 0)/1000.0:.3f}"
                ),
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
                    corr.status.value
                    if corr and hasattr(corr.status, "value")
                    else (corr.status if corr else "")
                ),
                "review_corrections": {
                    metric_name: {
                        "id": metric_correction.id,
                        "status": (
                            metric_correction.status.value
                            if hasattr(metric_correction.status, "value")
                            else metric_correction.status
                        ),
                    }
                    for metric_name, metric_correction in metric_corrections.items()
                },
                "trace_stats": (
                    item_metadata.get("trace_stats")
                    if isinstance(item_metadata, dict)
                    else None
                ),
                # Repeat runs: metric -> [score per pass, index 0 = pass 1]
                "pass_scores": (
                    {
                        m: [by_pass.get(p) for p in range(1, run_samples + 1)]
                        for m, by_pass in (
                            pass_scores_by_item.get(it.item_id) or {}
                        ).items()
                    }
                    if run_samples > 1
                    else None
                ),
                # Repeat runs: metric -> [meta per pass, index 0 = pass 1] —
                # each pass's judge output (explanation, label, …).
                "pass_metric_meta": (
                    {
                        m: [by_pass.get(p) for p in range(1, run_samples + 1)]
                        for m, by_pass in (
                            pass_meta_by_item.get(it.item_id) or {}
                        ).items()
                    }
                    if run_samples > 1 and pass_meta_by_item.get(it.item_id)
                    else None
                ),
                # Repeat runs: metric -> [root-cause analysis per pass].  This
                # is deliberately separate from item_metadata so the aggregate
                # view can read it without presenting an editable item card.
                "pass_metric_analyses": (
                    {
                        m: [by_pass.get(p) for p in range(1, run_samples + 1)]
                        for m, by_pass in (
                            pass_analysis_by_item.get(it.item_id) or {}
                        ).items()
                    }
                    if run_samples > 1 and pass_analysis_by_item.get(it.item_id)
                    else None
                ),
                # Repeat runs: [attempt per pass, index 0 = pass 1] — each
                # pass's final output/latency/trace (null where not run yet).
                "pass_attempts": (
                    [
                        (pass_attempts_by_item.get(it.item_id) or {}).get(p)
                        for p in range(1, run_samples + 1)
                    ]
                    if run_samples > 1
                    else None
                ),
            }
        )
        if compact:
            ui_rows[-1] = compact_row(ui_rows[-1])

    stats["success_rate"] = (
        (stats["completed"] / stats["total"] * 100.0) if stats["total"] else 0.0
    )

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

    _dsv = _dataset_version_fields(run, _dataset_version_info_map(db, [run]))

    return finalize_compare_alignment(
        {
            "run": {
                "run_id": run.id,
                "file_path": run.id,
                "task_name": run.task,
                "dataset_name": run.dataset,
                "dataset_version": _dsv["dataset_version"],
                "dataset_aliases": _dsv["dataset_aliases"],
                "model_name": _strip_model_provider(run.model or ""),
                "run_name": run_name,
                "external_run_id": run.external_run_id or "",
                "metric_names": metrics,
                "metric_specs": metric_specs,
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
                "samples": run_samples,
                "last_completed_pass": (
                    run_metadata.get("last_completed_pass")
                    if isinstance(run_metadata, dict)
                    else None
                ),
            },
            "snapshot": {
                "rows": ui_rows,
                "stats": stats,
                "metric_names": metrics,
                "metric_specs": metric_specs,
                **({"detail_mode": "lazy", "detail_page_size": 100} if compact else {}),
            },
        }
    )


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
    shell_css_content = (dashboard_dir / "shell.css").read_text(encoding="utf-8")
    ui_components_css_content = (dashboard_dir / "ui_components.css").read_text(
        encoding="utf-8"
    )
    ui_components_js = (dashboard_dir / "ui_components.js").read_text(encoding="utf-8")
    metrics_js = (dashboard_dir / "metrics.js").read_text(encoding="utf-8")

    # Inline dashboard.css
    run_html = re.sub(
        r'\s*<link\s+rel="stylesheet"\s+href="/static/dashboard\.css(?:\?[^"]*)?">\s*',
        lambda _match: f"<style>\n{css_content}\n</style>",
        run_html,
        count=1,
    )
    run_html = re.sub(
        r'\s*<link\s+rel="stylesheet"\s+href="/static/shell\.css(?:\?[^"]*)?">\s*',
        lambda _match: f"<style>\n{shell_css_content}\n</style>",
        run_html,
        count=1,
    )
    run_html = re.sub(
        r'\s*<link\s+rel="stylesheet"\s+href="/static/ui_components\.css(?:\?[^"]*)?">\s*',
        lambda _match: f"<style>\n{ui_components_css_content}\n</style>",
        run_html,
        count=1,
    )

    # Inline metrics.js
    run_html = re.sub(
        r'\s*<script\s+src="/static/metrics\.js(?:\?[^"]*)?"></script>\s*',
        lambda _match: f"<script>\n{metrics_js}\n</script>",
        run_html,
        count=1,
    )
    run_html = re.sub(
        r'\s*<script\s+defer\s+src="/static/ui_components\.js(?:\?[^"]*)?"></script>\s*',
        lambda _match: f"<script>\n{ui_components_js}\n</script>",
        run_html,
        count=1,
    )

    trace_viewer_path = dashboard_dir / "trace_viewer.js"
    if trace_viewer_path.exists():
        trace_viewer_js = trace_viewer_path.read_text(encoding="utf-8")
        run_html = re.sub(
            r'\s*<script\s+src="/static/trace_viewer\.js(?:\?[^"]*)?"></script>\s*',
            lambda _match: f"<script>\n{trace_viewer_js}\n</script>",
            run_html,
            count=1,
        )

    # Remove browser/session-only scripts that are not needed in standalone export.
    run_html = re.sub(
        r'\s*<script\s+src="/static/auth\.js(?:\?[^"]*)?"></script>\s*', "\n", run_html
    )
    run_html = re.sub(
        r'\s*<script\s+src="/static/shell\.js(?:\?[^"]*)?"></script>\s*', "\n", run_html
    )
    run_html = re.sub(
        r'\s*<script\s+src="/static/playground\.js(?:\?[^"]*)?"></script>\s*',
        "\n",
        run_html,
    )

    # Export embeds full rows and needs no network hydration helper.
    run_html = re.sub(
        r'\s*<script\s+(?:defer\s+)?src="/static/run_details\.js(?:\?[^"]*)?"></script>\s*',
        "\n", run_html,
    )

    # Remove favicon (would be a broken link)
    run_html = re.sub(
        r'\s*<link\s+rel="icon"\s+type="image/png"\s+href="/static/qym_icon\.png(?:\?[^"]*)?">\s*',
        "\n",
        run_html,
        count=1,
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
    safe_name = re.sub(r"[^\w\-.]", "_", str(run_name))[:80]
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

    dataset_info = _dataset_version_info_map(db, deleted_runs)
    result = []
    for r in deleted_runs:
        run_name = ""
        if isinstance(r.run_config, dict):
            run_name = r.run_config.get("run_name", "")
        if not run_name:
            run_name = r.external_run_id or ""
        _dsv = _dataset_version_fields(r, dataset_info)
        result.append(
            {
                "id": r.id,
                "run_name": run_name,
                "task": r.task,
                "dataset": r.dataset,
                "dataset_version": _dsv["dataset_version"],
                "dataset_aliases": _dsv["dataset_aliases"],
                "model": r.model,
                "trace_stats": r.run_metadata.get("trace_stats")
                if isinstance(r.run_metadata, dict)
                else None,
                "status": r.status.value if r.status else None,
                "owner_user_id": r.owner_user_id,
                "deleted_at": to_api_timestamp(r.deleted_at),
                "deleted_by_user_id": r.deleted_by_user_id,
                "deleted_by_name": deleters.get(r.deleted_by_user_id, ""),
                "created_at": to_api_timestamp(r.created_at),
            }
        )
    return result


@router.get("/api/runs/{run_id}/passes")
def run_passes(
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Repeat runs: per-pass slice aggregates (lazy-loaded on runs-list expand)."""
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        return {"error": "Run not found"}
    if not can_view_run(db, principal, run):
        return {"error": "Access denied"}

    from qym_platform.db.models import RunItemAttempt, RunItemPassScore

    samples = int(getattr(run, "samples", 1) or 1)
    metrics = list(run.metrics or [])

    # Per-pass mean per metric.
    score_rows = (
        db.query(
            RunItemPassScore.pass_number,
            RunItemPassScore.metric_name,
            func.avg(RunItemPassScore.score_numeric),
            func.count(RunItemPassScore.id),
        )
        .filter(
            RunItemPassScore.run_id == run.id,
            RunItemPassScore.score_numeric.isnot(None),
        )
        .group_by(RunItemPassScore.pass_number, RunItemPassScore.metric_name)
        .all()
    )
    metric_means: Dict[int, Dict[str, float]] = {}
    counts: Dict[int, int] = {}
    for pass_number, metric_name, avg_val, cnt in score_rows:
        metric_means.setdefault(int(pass_number), {})[metric_name] = (
            float(avg_val) if avg_val is not None else None
        )
        counts[int(pass_number)] = max(counts.get(int(pass_number), 0), int(cnt or 0))

    pass_analysis_rows = (
        db.query(RunItemPassScore.pass_number, RunItemPassScore.meta)
        .filter(
            RunItemPassScore.run_id == run.id,
            cast(RunItemPassScore.meta, Text).like(f'%"{PASS_ANALYSIS_META_KEY}"%'),
        )
        .yield_per(1000)
    )
    pass_analysis_causes: Dict[int, set[str]] = {}
    for pass_number, meta in pass_analysis_rows:
        analysis = (
            meta.get(PASS_ANALYSIS_META_KEY) if isinstance(meta, dict) else None
        )
        if not isinstance(analysis, dict):
            continue
        pass_analysis_causes.setdefault(int(pass_number), set()).update(
            analysis_root_causes(analysis)
        )

    # Per-pass item state.  Final attempts are canonical; lifecycle events
    # cover the currently-running item and legacy outcomes that have no final
    # attempt row.
    attempt_rows = (
        db.query(RunItemAttempt).filter(RunItemAttempt.run_id == run.id).all()
    )
    event_state = _repeat_pass_event_state(db, run.id)
    attempts_by_item_pass: Dict[tuple[str, int], Dict[str, Any]] = {}
    max_attempt_by_pair: Dict[tuple[str, int], int] = {}
    for attempt in attempt_rows:
        key = (attempt.item_id, int(attempt.pass_number))
        max_attempt_by_pair[key] = max(
            max_attempt_by_pair.get(key, 0), int(attempt.attempt_number or 1)
        )
        if not attempt.is_last_attempt:
            continue
        attempts_by_item_pass[key] = {
            "status": (
                "error"
                if str(attempt.status or "").lower() == "failed"
                else "completed"
            ),
            "latency_ms": attempt.latency_ms,
            "task_started_at_ms": attempt.task_started_at_ms,
            "trace_id": attempt.trace_id or "",
        }
    for key, payload in event_state["outcomes"].items():
        attempts_by_item_pass.setdefault(key, payload)
    for key, payload in event_state["active_attempts"].items():
        attempts_by_item_pass.setdefault(key, payload)

    latencies_by_pass: Dict[int, List[float]] = {}
    errors_by_pass: Dict[int, int] = {}
    completed_by_pass: Dict[int, int] = {}
    running_by_pass: Dict[int, int] = {}
    started_items_by_pass: Dict[int, int] = {}
    retries_by_pass: Dict[int, int] = {}
    starts_by_pass: Dict[int, List[int]] = {}
    ends_by_pass: Dict[int, List[float]] = {}
    trace_ids_by_pass: Dict[int, List[str]] = {}
    for (item_id, pass_number), attempt in attempts_by_item_pass.items():
        p = int(pass_number)
        status = str(attempt.get("status") or "").lower()
        latency_ms = attempt.get("latency_ms")
        task_started_at_ms = attempt.get("task_started_at_ms")
        trace_id = attempt.get("trace_id")
        started_items_by_pass[p] = started_items_by_pass.get(p, 0) + 1
        if status == "running":
            running_by_pass[p] = running_by_pass.get(p, 0) + 1
        else:
            completed_by_pass[p] = completed_by_pass.get(p, 0) + 1
        if latency_ms is not None:
            latencies_by_pass.setdefault(p, []).append(float(latency_ms))
        if task_started_at_ms is not None:
            started = int(task_started_at_ms)
            starts_by_pass.setdefault(p, []).append(started)
            if latency_ms is not None:
                ends_by_pass.setdefault(p, []).append(started + float(latency_ms))
        if trace_id and status != "error":
            trace_ids_by_pass.setdefault(p, []).append(str(trace_id))
        if status == "error":
            errors_by_pass[p] = errors_by_pass.get(p, 0) + 1
        retries_by_pass[p] = retries_by_pass.get(p, 0) + max(
            int(attempt.get("retry_count") or 0),
            max(0, max_attempt_by_pair.get((item_id, p), 1) - 1),
        )

    for p, starts in event_state["starts_by_pass"].items():
        starts_by_pass.setdefault(int(p), []).extend(int(value) for value in starts)

    trace_ids = {
        trace_id for values in trace_ids_by_pass.values() for trace_id in values
    }
    trace_aggregates = (
        db.query(RunTraceAggregate)
        .filter(
            RunTraceAggregate.run_id == run.id,
            RunTraceAggregate.trace_id.in_(trace_ids),
        )
        .all()
        if trace_ids
        else []
    )
    trace_aggregate_map = {
        aggregate.trace_id: aggregate for aggregate in trace_aggregates
    }
    if trace_aggregate_map:
        from qym_platform.api.ingest import (
            _build_run_trace_stats,
            _trace_bucket_from_aggregate,
        )

        trace_stats_by_pass = {
            p: _build_run_trace_stats(
                [
                    _trace_bucket_from_aggregate(trace_aggregate_map[trace_id])
                    for trace_id in pass_trace_ids
                    if trace_id in trace_aggregate_map
                ]
            )
            for p, pass_trace_ids in trace_ids_by_pass.items()
            if any(trace_id in trace_aggregate_map for trace_id in pass_trace_ids)
        }
    else:
        trace_stats_by_pass = {}

    def _lat_stats(values: Optional[List[float]]) -> Dict[str, Optional[float]]:
        if not values:
            return {"avg": None, "median": None, "p95": None}
        ordered = sorted(values)
        n = len(ordered)
        median = (
            ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0
        )
        p95 = ordered[min(n - 1, max(0, int(round(0.95 * n)) - 1))]
        return {"avg": sum(ordered) / n, "median": median, "p95": p95}

    last_completed = 0
    if isinstance(run.run_metadata, dict):
        try:
            last_completed = int(run.run_metadata.get("last_completed_pass") or 0)
        except (TypeError, ValueError):
            last_completed = 0
    if event_state["completed_passes"]:
        last_completed = max(last_completed, max(event_state["completed_passes"]))

    run_status = str(getattr(run.status, "value", run.status) or "").upper()
    expected_items = (
        db.query(func.count(RunItem.id)).filter(RunItem.run_id == run.id).scalar() or 0
    )
    if isinstance(run.run_metadata, dict):
        try:
            expected_items = int(run.run_metadata.get("total_items") or expected_items)
        except (TypeError, ValueError):
            pass

    passes = []
    for p in range(1, samples + 1):
        has_data = (
            p in metric_means
            or p in started_items_by_pass
            or p in event_state["starts_by_pass"]
        )
        status = _repeat_pass_status(
            pass_number=p,
            last_completed=last_completed,
            has_data=has_data,
            run_status=run_status,
        )
        lat = _lat_stats(latencies_by_pass.get(p))
        pass_starts = starts_by_pass.get(p) or []
        pass_ends = ends_by_pass.get(p) or []
        started_at_ms = min(pass_starts) if pass_starts else None
        duration_ms = (
            max(pass_ends) - started_at_ms
            if started_at_ms is not None and pass_ends
            else None
        )
        ended_at_ms = max(pass_ends) if status == "completed" and pass_ends else None
        passes.append(
            {
                "pass_number": p,
                "status": status,
                "metric_means": metric_means.get(p, {}),
                "items_scored": counts.get(p, 0),
                "items_total": int(expected_items),
                "items_started": started_items_by_pass.get(p, 0),
                "completed_count": completed_by_pass.get(p, 0),
                "error_count": errors_by_pass.get(p, 0),
                "analysis_cause_count": len(pass_analysis_causes.get(p, set())),
                "running_count": (
                    running_by_pass.get(p, 0) if status == "running" else 0
                ),
                "retry_count": retries_by_pass.get(p, 0),
                "avg_latency_ms": lat["avg"],
                "median_latency_ms": lat["median"],
                "p95_latency_ms": lat["p95"],
                "started_at": (
                    to_api_timestamp(
                        datetime.fromtimestamp(started_at_ms / 1000.0, timezone.utc)
                    )
                    if started_at_ms is not None
                    else None
                ),
                "ended_at": (
                    to_api_timestamp(
                        datetime.fromtimestamp(ended_at_ms / 1000.0, timezone.utc)
                    )
                    if ended_at_ms is not None
                    else None
                ),
                "duration_ms": duration_ms,
                "trace_stats": trace_stats_by_pass.get(p),
            }
        )
    return {"run_id": run.id, "samples": samples, "metrics": metrics, "passes": passes}


@router.delete("/api/runs/{run_id}/passes/{pass_number}")
def delete_run_pass(
    run_id: str,
    pass_number: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Delete one full pass from a completed repeat run."""
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not can_modify_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        result = delete_repeat_pass(
            db,
            run,
            pass_number,
            actor_user_id=(
                principal.user.id if principal.auth_type != "none" else None
            ),
        )
    except RepeatPassDeletionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    db.commit()
    return result


@router.delete("/api/runs/{run_id}/passes")
def delete_run_passes(
    run_id: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Delete several passes atomically, using their original pass numbers."""
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not can_modify_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")

    raw_pass_numbers = payload.get("pass_numbers")
    if not isinstance(raw_pass_numbers, list) or not raw_pass_numbers:
        raise HTTPException(
            status_code=400, detail="pass_numbers must be a non-empty list"
        )
    if any(isinstance(value, bool) for value in raw_pass_numbers):
        raise HTTPException(
            status_code=400, detail="pass_numbers must contain integers"
        )
    try:
        pass_numbers = sorted({int(value) for value in raw_pass_numbers}, reverse=True)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail="pass_numbers must contain integers"
        ) from exc
    if any(value != int(value) for value in raw_pass_numbers):
        raise HTTPException(
            status_code=400, detail="pass_numbers must contain integers"
        )

    samples = int(run.samples or 1)
    if any(pass_number < 1 or pass_number > samples for pass_number in pass_numbers):
        raise HTTPException(
            status_code=400, detail="pass_number out of range for this run"
        )
    if len(pass_numbers) >= samples:
        raise HTTPException(
            status_code=400, detail="A run must retain at least one pass"
        )

    try:
        for pass_number in pass_numbers:
            delete_repeat_pass(
                db,
                run,
                pass_number,
                actor_user_id=(
                    principal.user.id if principal.auth_type != "none" else None
                ),
            )
    except RepeatPassDeletionError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    db.commit()
    return {
        "ok": True,
        "run_id": run.id,
        "deleted_passes": sorted(pass_numbers),
        "samples": int(run.samples or 1),
    }


@router.get("/api/runs/{run_id}/group-metrics")
def run_group_metrics(
    run_id: str,
    metric: Optional[str] = Query(None),
    threshold: float = Query(0.8),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Repeat runs: the group set (k = samples) plus the full accuracy-vs-k band.

    All passes are stored, so any pass@k / pass^k for k <= samples is computed
    on demand — reduction is a display concern, never a data commitment.
    """
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        return {"error": "Run not found"}
    if not can_view_run(db, principal, run):
        return {"error": "Access denied"}

    from qym.core.reducers import group_stats

    from qym_platform.db.models import RunItemPassScore
    from qym_platform.services.repeat_analysis import cached_repeat_analysis

    samples = int(getattr(run, "samples", 1) or 1)
    metric_name = metric or (run.metrics[0] if run.metrics else None)
    if not metric_name:
        return {"error": "Run has no metrics"}

    items_scores: Dict[str, list] = {}
    rows = (
        db.query(
            RunItemPassScore.item_id,
            RunItemPassScore.pass_number,
            RunItemPassScore.score_numeric,
        )
        .filter(
            RunItemPassScore.run_id == run.id,
            RunItemPassScore.metric_name == metric_name,
        )
        .order_by(RunItemPassScore.item_id, RunItemPassScore.pass_number)
        .all()
    )
    score_rows = []
    for item_id, pass_number, score_numeric in rows:
        numeric = float(score_numeric) if score_numeric is not None else 0.0
        items_scores.setdefault(item_id, []).append(numeric)
        score_rows.append((str(item_id), int(pass_number), numeric))

    run_config = run.run_config if isinstance(run.run_config, dict) else {}
    raw_report_k = run_config.get("report_k")
    report_k = (
        int(raw_report_k)
        if isinstance(raw_report_k, (int, float)) and 1 <= int(raw_report_k) <= samples
        else None
    )
    stats = group_stats(items_scores, threshold=threshold, k=samples, report_k=report_k)
    analysis = cached_repeat_analysis(
        db,
        run_id=run.id,
        metric_name=metric_name,
        threshold=threshold,
        samples=samples,
        rows=score_rows,
        items_scores=items_scores,
    )
    return {
        "run_id": run.id,
        "metric": metric_name,
        "threshold": threshold,
        "samples": samples,
        "report_k": report_k,
        "group": stats,
        "band": analysis.get("band", {}),
        "distribution": analysis.get("distribution", []),
        "uncertainty": {
            "confidence": analysis.get("confidence"),
            "bootstrap_iterations": analysis.get("bootstrap_iterations"),
            "minimum_items": analysis.get("minimum_uncertainty_items"),
            "method": analysis.get("method"),
            "method_version": analysis.get("method_version"),
        },
    }


def _detail_run(db: Session, principal: Principal, run_id: str) -> Run:
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(404, "Run not found")
    if not can_view_run(db, principal, run):
        raise HTTPException(403, "Access denied")
    return run


@router.post("/api/runs/{run_id}/items/details")
def run_item_details(
    run_id: str,
    request: Dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    run = _detail_run(db, principal, run_id)
    ids = detail_item_ids(request)
    data = _build_run_data(db, run, item_ids=ids)
    rows = data["snapshot"]["rows"]
    for row in rows:
        # Occurrence-based comparison identity comes from the complete compact
        # index; hydrating a subset must never reset duplicate occurrence IDs.
        row.pop("compare_item_id", None)
        row.pop("compare_alignment_source", None)
        row["__details_loaded"] = True
    present = {row["item_id"] for row in rows}
    return {
        "rows": rows,
        "missing_item_ids": [iid for iid in ids if iid not in present],
    }


@router.post("/api/runs/{run_id}/items/search")
def search_run_items(
    run_id: str,
    request: Dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    run = _detail_run(db, principal, run_id)
    conditions = search_conditions(request)
    pass_number = request.get("pass_number")
    if pass_number is not None:
        if (
            isinstance(pass_number, bool)
            or not isinstance(pass_number, int)
            or not 1 <= pass_number <= int(run.samples or 1)
        ):
            raise HTTPException(422, "pass_number must identify an existing pass")

    matches: Dict[str, List[str]] = {condition["id"]: [] for condition in conditions}
    # Search is deliberately explicit: the initial index never transfers large
    # bodies. Streaming selected columns bounds aggregate-mode server memory.
    if pass_number is None:
        rows = (
            db.query(
                RunItem.item_id,
                RunItem.index,
                RunItem.input,
                RunItem.expected,
                RunItem.output,
                RunItem.error,
            )
            .filter(RunItem.run_id == run.id)
            .order_by(RunItem.index.asc())
            .yield_per(200)
        )
        texts = (
            (
                row.item_id,
                [
                    str(row.item_id or row.index or ""),
                    _stringify(row.input),
                    _stringify(row.expected),
                    f"ERROR: {row.error}" if row.error else _stringify(row.output),
                ],
            )
            for row in rows
        )
    else:
        # Reuse established legacy pass recovery so pre-attempt SDK runs and
        # missing/final attempts have exactly the same search semantics as UI.
        # Scope each recovery batch so repeated searches cannot load every
        # input/output/explanation into memory at once.
        def pass_texts():
            from itertools import islice

            item_ids = iter(
                db.query(RunItem.item_id)
                .filter(RunItem.run_id == run.id)
                .order_by(RunItem.index.asc())
                .yield_per(100)
            )
            while True:
                batch = [item_id for (item_id,) in islice(item_ids, 100)]
                if not batch:
                    break
                data = _build_run_data(db, run, item_ids=batch)
                for row in data["snapshot"]["rows"]:
                    attempts = row.get("pass_attempts") or []
                    output = (
                        str((attempts[pass_number - 1] or {}).get("output") or "")
                        if len(attempts) >= pass_number
                        else ""
                    )
                    yield row["item_id"], [
                        str(row["item_id"] or row["index"] or ""),
                        row["input"], row["expected"], output,
                    ]
                del data

        texts = pass_texts()
    for item_id, values in texts:
        lowered = [value.lower() for value in values]
        for condition in conditions:
            candidates = (
                lowered if condition["field"] == "all"
                else lowered[1:] if condition["field"] == "content"
                else lowered[-1:]
            )
            if any(condition["value"] in candidate for candidate in candidates):
                matches[condition["id"]].append(item_id)
    return {"matches": matches}



@router.get("/api/runs/{run_id}")
def legacy_run_data(
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
    view: Optional[str] = None,
) -> Dict[str, Any]:
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        return {"error": "Run not found"}
    if not can_view_run(db, principal, run):
        return {"error": "Access denied"}
    _reconcile_run_liveness(db, [run])

    if view not in (None, "full", "compact"):
        raise HTTPException(422, "view must be full or compact")
    return _build_run_data(db, run, compact=view == "compact")


@router.post("/api/runs/update_metric")
def update_metric(
    request: Dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Update a single metric score for a run item.

    With ``pass_number`` (repeat runs), the edit targets that pass's score and
    the run-level score is re-reduced as the mean over passes.
    """
    file_path = request.get("file_path")
    row_index = request.get("row_index")
    metric_name = request.get("metric_name")
    new_score = request.get("new_score")
    pass_number = request.get("pass_number")

    if not file_path or metric_name is None or row_index is None:
        raise HTTPException(
            status_code=400, detail="file_path, row_index, and metric_name required"
        )

    run = Run.active(db).filter(Run.id == file_path).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not can_modify_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")

    run_samples = int(run.samples or 1)
    if pass_number is not None:
        try:
            pass_number = int(pass_number)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400, detail="pass_number must be an integer"
            )
        if run_samples <= 1 or pass_number < 1 or pass_number > run_samples:
            raise HTTPException(
                status_code=400, detail="pass_number out of range for this run"
            )

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
        meta["original_score"] = (
            score_record.score_raw
            if score_record.score_raw is not None
            else score_record.score_numeric
        )
    meta["modified"] = "true"

    if pass_number is not None:
        from qym_platform.db.models import RunItemPassScore

        try:
            numeric_val = float(new_score)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Pass scores must be numeric")

        pass_record = (
            db.query(RunItemPassScore)
            .filter(
                RunItemPassScore.run_id == run.id,
                RunItemPassScore.item_id == item.item_id,
                RunItemPassScore.metric_name == metric_name,
                RunItemPassScore.pass_number == pass_number,
            )
            .first()
        )
        if not pass_record:
            pass_record = RunItemPassScore(
                run_id=run.id,
                item_id=item.item_id,
                metric_name=metric_name,
                pass_number=pass_number,
            )
            db.add(pass_record)
        meta.setdefault(f"pass_{pass_number}_original", pass_record.score_numeric)
        pass_meta = dict(pass_record.meta or {})
        pass_meta.setdefault("original_score", pass_record.score_numeric)
        pass_meta["modified"] = "true"
        pass_record.meta = pass_meta
        pass_record.score_numeric = numeric_val

        # Re-reduce: run-level score = mean over all stored passes
        siblings = (
            db.query(RunItemPassScore)
            .filter(
                RunItemPassScore.run_id == run.id,
                RunItemPassScore.item_id == item.item_id,
                RunItemPassScore.metric_name == metric_name,
            )
            .all()
        )
        numerics = [p.score_numeric for p in siblings if p.score_numeric is not None]
        reduced = round(sum(numerics) / len(numerics), 6) if numerics else None
        score_record.score_numeric = reduced
        score_record.score_raw = reduced
        meta = _repeat_aggregate_metric_meta(
            {int(p.pass_number): p.score_numeric for p in siblings}, meta
        )
    else:
        try:
            numeric_val = float(new_score)
            score_record.score_numeric = numeric_val
            score_record.score_raw = numeric_val
        except (ValueError, TypeError):
            score_record.score_numeric = None
            score_record.score_raw = new_score

    score_record.meta = meta
    db.commit()

    # Build the updated row response matching the compare API format
    metrics = list(run.metrics or [])
    all_scores = (
        db.query(RunItemScore)
        .filter(RunItemScore.run_id == run.id, RunItemScore.item_id == item.item_id)
        .all()
    )
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

    # Repeat runs: ship pass_scores/pass_attempts so the client row keeps its
    # per-pass detail (and pass-scoped pages can re-apply their lens).
    pass_scores: Optional[Dict[str, list]] = None
    pass_metric_meta: Optional[Dict[str, list]] = None
    pass_metric_analyses: Optional[Dict[str, list]] = None
    pass_attempts: Optional[list] = None
    if run_samples > 1:
        by_metric: Dict[str, Dict[int, Optional[float]]] = {}
        by_metric_meta: Dict[str, Dict[int, Dict[str, Any]]] = {}
        by_metric_analysis: Dict[str, Dict[int, Dict[str, Any]]] = {}
        pass_score_rows = (
            db.query(RunItemPassScore)
            .filter(
                RunItemPassScore.run_id == run.id,
                RunItemPassScore.item_id == item.item_id,
            )
            .all()
        )
        for ps in pass_score_rows:
            by_metric.setdefault(ps.metric_name, {})[
                int(ps.pass_number)
            ] = ps.score_numeric
            ps_meta = dict(ps.meta) if ps.meta else {}
            pass_analysis = ps_meta.pop(PASS_ANALYSIS_META_KEY, None)
            if isinstance(pass_analysis, dict):
                by_metric_analysis.setdefault(ps.metric_name, {})[
                    int(ps.pass_number)
                ] = pass_analysis
            if ps.label:
                ps_meta.setdefault("label", ps.label)
            if ps.explanation:
                ps_meta.setdefault("explanation", ps.explanation)
            if ps_meta:
                by_metric_meta.setdefault(ps.metric_name, {})[
                    int(ps.pass_number)
                ] = ps_meta
        pass_scores = {
            m: [by_pass.get(p) for p in range(1, run_samples + 1)]
            for m, by_pass in by_metric.items()
        }
        pass_metric_meta = (
            {
                m: [by_pass.get(p) for p in range(1, run_samples + 1)]
                for m, by_pass in by_metric_meta.items()
            }
            if by_metric_meta
            else None
        )
        pass_metric_analyses = (
            {
                m: [by_pass.get(p) for p in range(1, run_samples + 1)]
                for m, by_pass in by_metric_analysis.items()
            }
            if by_metric_analysis
            else None
        )
        attempts_by_pass: Dict[int, Dict[str, Any]] = {}
        final_attempts = (
            db.query(RunItemAttempt)
            .filter(
                RunItemAttempt.run_id == run.id,
                RunItemAttempt.item_id == item.item_id,
                RunItemAttempt.is_last_attempt.is_(True),
            )
            .all()
        )
        missing_output_pairs = {
            (att.item_id, int(att.pass_number))
            for att in final_attempts
            if att.output is None
        }
        recovered_outputs = _completed_pass_outputs(db, run.id, missing_output_pairs)
        for att in final_attempts:
            att_error = att.error or ""
            is_failed = str(att.status or "").lower() == "failed"
            attempt_output = att.output
            if attempt_output is None:
                attempt_output = recovered_outputs.get(
                    (att.item_id, int(att.pass_number))
                )
            attempts_by_pass[int(att.pass_number)] = {
                "pass_number": int(att.pass_number),
                "status": "error" if is_failed else "completed",
                "output": (
                    f"ERROR: {att_error}"
                    if is_failed and att_error
                    else _stringify(attempt_output)
                ),
                "error": att_error,
                "latency_ms": att.latency_ms,
                "trace_id": att.trace_id or "",
                "trace_url": att.trace_url or "",
            }
        pass_attempts = [attempts_by_pass.get(p) for p in range(1, run_samples + 1)]

    is_error = bool(item.error)
    status = "error" if is_error else "completed"
    duplicate_counts: Dict[str, int] = {}
    ordered_items = (
        db.query(RunItem)
        .filter(RunItem.run_id == run.id)
        .order_by(RunItem.index.asc())
        .all()
    )
    identity = {"compare_item_id": item.item_id, "compare_alignment_source": "item_id"}
    for ordered_item in ordered_items:
        ordered_metadata = (
            ordered_item.item_metadata
            if isinstance(ordered_item.item_metadata, dict)
            else {}
        )
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
        "time": ""
        if item.latency_ms is None
        else f"{(item.latency_ms or 0)/1000.0:.3f}",
        "latency_ms": item.latency_ms or 0,
        "retry_count": int(
            item.retry_count
            or (
                item.item_metadata.get("retry_count")
                if isinstance(item.item_metadata, dict)
                else 0
            )
            or 0
        ),
        "trace_id": item.trace_id or "",
        "trace_url": item.trace_url or "",
        "task_started_at_ms": item.item_metadata.get("task_started_at_ms")
        if isinstance(item.item_metadata, dict)
        else None,
        "metric_values": metric_values,
        "metric_meta": metric_meta,
        "item_metadata": item.item_metadata
        if isinstance(item.item_metadata, dict)
        else {},
        "pass_scores": pass_scores,
        "pass_metric_meta": pass_metric_meta,
        "pass_metric_analyses": pass_metric_analyses,
        "pass_attempts": pass_attempts,
    }

    return {"ok": True, "row": row}


@router.post("/api/runs/update_root_cause")
def update_root_cause(
    request: Dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Update item-level or metric-level root-cause analysis for one run item.

    Each field is only modified when its key is explicitly present in the request.
    This prevents partial saves (e.g. saving only root_cause_note) from erasing
    unrelated fields like root_cause or root_cause_detail.

    Supplying ``metric_name`` scopes the patch to the corresponding entry in
    ``item_metadata.metric_analyses`` and leaves the legacy item-level summary
    untouched.
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
    item = lock_run_item(db, run=run, item=item)

    editable_fields = (
        "root_cause",
        "root_causes",
        "root_cause_issues",
        "category_taxonomy",
        "root_cause_detail",
        "root_cause_note",
        "solution",
        "solution_note",
    )
    patch = {}
    for field in editable_fields:
        if field in request or (
            field == "root_cause_note" and request.get(field) is not None
        ):
            patch[field] = request.get(field)

    raw_pass_number = request.get("pass_number")
    pass_number: Optional[int] = None
    if raw_pass_number is not None:
        try:
            pass_number = int(raw_pass_number)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid pass_number") from exc
        if pass_number < 1:
            raise HTTPException(status_code=400, detail="pass_number must be positive")
    run_samples = int(getattr(run, "samples", 1) or 1)
    if run_samples > 1 and pass_number is None:
        raise HTTPException(
            status_code=400,
            detail="pass_number is required when editing a repeat-run diagnosis",
        )
    if pass_number is not None and (
        run_samples <= 1 or pass_number > run_samples
    ):
        raise HTTPException(status_code=400, detail="pass_number is outside this run")

    if pass_number is not None:
        raw_metric_name = request.get("metric_name")
        metric_name = str(raw_metric_name or "").strip()
        if not metric_name:
            raise HTTPException(
                status_code=400,
                detail="metric_name is required for a repeat-run diagnosis",
            )
        known_metrics = {str(name) for name in (run.metrics or [])}
        if metric_name not in known_metrics:
            raise HTTPException(status_code=400, detail="Unknown metric_name")
        pass_score = (
            db.query(RunItemPassScore)
            .filter(
                RunItemPassScore.run_id == run.id,
                RunItemPassScore.item_id == item.item_id,
                RunItemPassScore.metric_name == metric_name,
                RunItemPassScore.pass_number == pass_number,
            )
            .with_for_update()
            .one_or_none()
        )
        if pass_score is None:
            raise HTTPException(status_code=404, detail="Pass score not found")

        pass_meta = dict(pass_score.meta) if isinstance(pass_score.meta, dict) else {}
        before_analysis = (
            dict(pass_meta.get(PASS_ANALYSIS_META_KEY))
            if isinstance(pass_meta.get(PASS_ANALYSIS_META_KEY), dict)
            else {}
        )
        after_analysis = _apply_metric_analysis_patch(before_analysis, patch)
        if after_analysis:
            after_analysis["review_status"] = "pending"
            pass_meta[PASS_ANALYSIS_META_KEY] = after_analysis
        else:
            pass_meta.pop(PASS_ANALYSIS_META_KEY, None)
        pass_score.meta = pass_meta

        if before_analysis != after_analysis:
            db.add(
                AuditLog(
                    actor_user_id=(
                        principal.user.id if principal.auth_type != "none" else None
                    ),
                    action="metric_root_cause_change:human",
                    entity_type="run_item_pass_metric_analysis",
                    entity_id=(
                        f"{run.id}:{item.item_id}:{pass_number}:{metric_name}"
                    ),
                    before=before_analysis,
                    after=after_analysis,
                    created_at=utc_now_naive(),
                )
            )
        db.commit()
        updated_snapshot = _build_run_data(db, run).get("snapshot", {})
        updated_rows = (
            updated_snapshot.get("rows", [])
            if isinstance(updated_snapshot, dict)
            else []
        )
        updated_row = next(
            (row for row in updated_rows if row.get("item_id") == item.item_id),
            None,
        )
        return {"ok": True, "row": updated_row}

    raw_metric_name = request.get("metric_name")
    if raw_metric_name is not None:
        metric_name = str(raw_metric_name).strip()
        if not metric_name:
            raise HTTPException(status_code=400, detail="metric_name must not be empty")

        meta = dict(item.item_metadata) if isinstance(item.item_metadata, dict) else {}
        metric_analyses = (
            dict(meta.get("metric_analyses"))
            if isinstance(meta.get("metric_analyses"), dict)
            else {}
        )
        known_metrics = {str(name) for name in (run.metrics or [])}
        known_metrics.update(str(name) for name in metric_analyses)
        if metric_name not in known_metrics:
            raise HTTPException(status_code=400, detail="Unknown metric_name")

        before_analysis = (
            dict(metric_analyses.get(metric_name))
            if isinstance(metric_analyses.get(metric_name), dict)
            else {}
        )
        analysis = _apply_metric_analysis_patch(before_analysis, patch)

        meaningful_analysis = {
            key: value
            for key, value in analysis.items()
            if key != "source" and value not in (None, "", [])
        }
        if meaningful_analysis:
            metric_analyses[metric_name] = analysis
        else:
            metric_analyses.pop(metric_name, None)

        if metric_analyses:
            meta["metric_analyses"] = metric_analyses
        else:
            meta.pop("metric_analyses", None)
        _refresh_metric_analysis_error(meta)
        item.item_metadata = meta

        after_analysis = dict(metric_analyses.get(metric_name) or {})
        if before_analysis != after_analysis:
            replace_metric_review_candidate(
                db,
                run=run,
                item=item,
                metric_name=metric_name,
                analysis=after_analysis,
                actor_user_id=(
                    principal.user.id if principal.auth_type != "none" else None
                ),
                actor_source="human",
                item_locked=True,
            )
            db.add(
                AuditLog(
                    actor_user_id=(
                        principal.user.id if principal.auth_type != "none" else None
                    ),
                    action="metric_root_cause_change:human",
                    entity_type="run_item_metric_analysis",
                    entity_id=f"{run.id}:{item.item_id}:{metric_name}",
                    before=before_analysis,
                    after=after_analysis,
                    created_at=utc_now_naive(),
                )
            )
        db.commit()
        updated_snapshot = _build_run_data(db, run).get("snapshot", {})
        updated_rows = (
            updated_snapshot.get("rows", [])
            if isinstance(updated_snapshot, dict)
            else []
        )
        updated_row = next(
            (row for row in updated_rows if row.get("item_id") == item.item_id),
            None,
        )
        return {"ok": True, "row": updated_row}

    apply_root_cause_change(
        db,
        run=run,
        item=item,
        actor_user_id=principal.user.id if principal.auth_type != "none" else None,
        actor_source="human",
        human_patch=patch,
        item_locked=True,
    )

    db.commit()
    updated_snapshot = _build_run_data(db, run).get("snapshot", {})
    updated_rows = (
        updated_snapshot.get("rows", []) if isinstance(updated_snapshot, dict) else []
    )
    updated_row = next(
        (row for row in updated_rows if row.get("item_id") == item.item_id), None
    )
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

    # Soft-delete only. All evaluation, analysis, and review history remains
    # available if an administrator restores the run.
    snapshot = run.audit_snapshot()
    run.deleted_at = utc_now_naive()
    run.deleted_by_user_id = principal.user.id

    audit = AuditLog(
        actor_user_id=principal.user.id,
        action="run.deleted",
        entity_type="run",
        entity_id=run.id,
        before=snapshot,
        after={
            "deleted_at": run.deleted_at.isoformat(),
        },
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
    # Allow completed/failed runs and rejected runs that need another review pass.
    submittable_statuses = {
        RunWorkflowStatus.COMPLETED,
        RunWorkflowStatus.FAILED,
        RunWorkflowStatus.REJECTED,
    }
    if run.status not in submittable_statuses:
        raise HTTPException(
            status_code=400, detail=f"Run not submittable from status={run.status}"
        )
    run.status = RunWorkflowStatus.SUBMITTED
    approval = db.query(Approval).filter(Approval.run_id == run.id).first()
    if not approval:
        approval = Approval(run_id=run.id, submitted_by_user_id=principal.user.id)
        db.add(approval)
    else:
        approval.submitted_by_user_id = principal.user.id
        approval.submitted_at = utc_now_naive()
        approval.decision = None
        approval.decision_by_user_id = None
        approval.decision_at = None
        approval.comment = ""
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
        raise HTTPException(
            status_code=403, detail="Only a project manager or admin can approve"
        )
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
        raise HTTPException(
            status_code=403, detail="Only a project manager or admin can reject"
        )
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


@router.post("/v1/runs/{run_id}/unapprove")
def unapprove_run(
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != RunWorkflowStatus.APPROVED:
        raise HTTPException(status_code=400, detail="Run not approved")
    if not _can_approve_run(db, principal, run):
        raise HTTPException(
            status_code=403, detail="Only a project manager or admin can unapprove"
        )
    approval = db.query(Approval).filter(Approval.run_id == run.id).first()
    if not approval:
        raise HTTPException(status_code=400, detail="Missing approval record")
    approval.decision = None
    approval.decision_by_user_id = None
    approval.decision_at = None
    approval.comment = ""
    run.status = RunWorkflowStatus.COMPLETED
    db.commit()
    return {"ok": True, "status": run.status}


@router.post("/v1/runs/{run_id}/unreject")
def unreject_run(
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != RunWorkflowStatus.REJECTED:
        raise HTTPException(status_code=400, detail="Run not rejected")
    if not _can_approve_run(db, principal, run):
        raise HTTPException(
            status_code=403, detail="Only a project manager or admin can unreject"
        )
    approval = db.query(Approval).filter(Approval.run_id == run.id).first()
    if not approval:
        raise HTTPException(status_code=400, detail="Missing approval record")
    approval.decision = None
    approval.decision_by_user_id = None
    approval.decision_at = None
    approval.comment = ""
    run.status = RunWorkflowStatus.COMPLETED
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
    pass_number: Optional[int] = Query(default=None, ge=1),
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

    attempts_query = db.query(RunItemAttempt).filter(
        RunItemAttempt.run_id == run_id, RunItemAttempt.item_id == item_id
    )
    if pass_number is not None:
        attempts_query = attempts_query.filter(
            RunItemAttempt.pass_number == pass_number
        )
    attempts_rows = attempts_query.order_by(
        RunItemAttempt.attempt_number.asc(), RunItemAttempt.id.asc()
    ).all()

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
                        "pass_number": row.pass_number,
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
    elif pass_number is not None:
        event_state = _repeat_pass_event_state(db, run_id)
        event_attempt = event_state["outcomes"].get(
            (item_id, pass_number)
        ) or event_state["active_attempts"].get((item_id, pass_number))
        if event_attempt and event_attempt.get("trace_id"):
            trace_id = str(event_attempt["trace_id"])
            spans = (
                db.query(Span)
                .filter(Span.run_id == run_id, Span.trace_id == trace_id)
                .order_by(Span.start_time_ns.asc().nullslast(), Span.id.asc())
                .all()
            )
            attempt_dicts.append(
                _serialize_attempt_trace_payload(
                    {
                        **event_attempt,
                        "pass_number": pass_number,
                        "attempt_number": int(event_attempt.get("retry_count") or 0)
                        + 1,
                        "is_last_attempt": event_attempt.get("status") != "running",
                    },
                    spans,
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
                    "pass_number": 1,
                    "attempt_number": 1,
                    "status": "failed" if item.error else "completed",
                    "latency_ms": item.latency_ms,
                    "task_started_at_ms": item.item_metadata.get("task_started_at_ms")
                    if isinstance(item.item_metadata, dict)
                    else None,
                    "trace_id": item.trace_id,
                    "trace_url": item.trace_url,
                    "error": item.error,
                    "is_last_attempt": True,
                },
                spans,
            )
        )

    pass_retry_count = None
    if pass_number is not None:
        pass_retry_count = (
            max((int(row.attempt_number or 1) for row in attempts_rows), default=1) - 1
        )
        if not attempts_rows and attempt_dicts:
            pass_retry_count = max(
                0, int(attempt_dicts[-1].get("attempt_number") or 1) - 1
            )
    return _build_item_trace_payload(
        item,
        attempt_dicts,
        retry_count_override=pass_retry_count,
        fallback_to_item_trace=pass_number is None,
    )
