"""Read-only API for the project root-cause dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from qym_platform.auth import Principal, require_ui_principal
from qym_platform.db.models import Project
from qym_platform.deps import get_db
from qym_platform.permissions import has_project_access
from qym_platform.services.root_cause_dashboard import (
    DashboardFilters,
    build_compare_payload,
    build_dashboard_payload,
    build_occurrences_payload,
)
from sqlalchemy.orm import Session


router = APIRouter(tags=["root-cause-dashboard"])

# Temporary kill switch.  Keep the route module and service implementation in
# place so the dashboard can be restored by changing one value, while ensuring
# no dashboard query or payload builder can run in the disabled state.
ROOT_CAUSE_DASHBOARD_ENABLED = False


def _require_dashboard_enabled() -> None:
    if not ROOT_CAUSE_DASHBOARD_ENABLED:
        raise HTTPException(
            status_code=404,
            detail="Root-cause dashboard is temporarily disabled",
        )


def _values(values: Iterable[str] | None) -> tuple[str, ...]:
    """Accept both repeated query values and comma-separated UI values."""

    result: list[str] = []
    for value in values or []:
        for part in str(value or "").split(","):
            clean = part.strip()
            if clean and clean not in result:
                result.append(clean)
    return tuple(result)


def _parse_date(value: Optional[str], name: str) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
        # Database timestamps are naive UTC.  Drop an explicit UTC offset while
        # preserving the instant for comparisons in both SQLite and Postgres.
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        if name == "to_date" and "T" not in value and "+" not in value:
            parsed = parsed + timedelta(days=1) - timedelta(microseconds=1)
        return parsed
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {name}; expected ISO date") from exc


def _project(
    db: Session,
    principal: Principal,
    project_slug: str,
) -> Project:
    project = (
        db.query(Project)
        .filter(Project.slug == project_slug, Project.is_active.is_(True))
        .first()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not has_project_access(db, principal, project.id):
        raise HTTPException(status_code=403, detail="Access denied")
    return project


def _filters(
    *,
    run_id: Optional[List[str]] = None,
    task: Optional[List[str]] = None,
    dataset: Optional[List[str]] = None,
    model: Optional[List[str]] = None,
    metric: Optional[List[str]] = None,
    category: Optional[List[str]] = None,
    detail: Optional[List[str]] = None,
    outcome: Optional[List[str]] = None,
    source: Optional[List[str]] = None,
    review_status: Optional[List[str]] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> DashboardFilters:
    return DashboardFilters(
        run_ids=_values(run_id),
        task=_values(task),
        dataset=_values(dataset),
        model=_values(model),
        metric=_values(metric),
        category=_values(category),
        detail=_values(detail),
        outcome=_values(outcome),
        source=_values(source),
        review_status=_values(review_status),
        from_date=_parse_date(from_date, "from_date"),
        to_date=_parse_date(to_date, "to_date"),
    )


@router.get("/api/projects/{project_slug}/root-cause-dashboard")
def root_cause_dashboard(
    project_slug: str,
    run_id: Optional[List[str]] = Query(default=None),
    task: Optional[List[str]] = Query(default=None),
    dataset: Optional[List[str]] = Query(default=None),
    model: Optional[List[str]] = Query(default=None),
    metric: Optional[List[str]] = Query(default=None),
    category: Optional[List[str]] = Query(default=None),
    detail: Optional[List[str]] = Query(default=None),
    outcome: Optional[List[str]] = Query(default=None),
    source: Optional[List[str]] = Query(default=None),
    review_status: Optional[List[str]] = Query(default=None),
    from_date: Optional[str] = Query(default=None),
    to_date: Optional[str] = Query(default=None),
    score_metric: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> dict[str, Any]:
    _require_dashboard_enabled()
    project = _project(db, principal, project_slug)
    return build_dashboard_payload(
        db,
        project,
        _filters(
            run_id=run_id,
            task=task,
            dataset=dataset,
            model=model,
            metric=metric,
            category=category,
            detail=detail,
            outcome=outcome,
            source=source,
            review_status=review_status,
            from_date=from_date,
            to_date=to_date,
        ),
        score_metric=score_metric,
    )


@router.get("/api/projects/{project_slug}/root-cause-dashboard/occurrences")
def root_cause_dashboard_occurrences(
    project_slug: str,
    run_id: Optional[List[str]] = Query(default=None),
    task: Optional[List[str]] = Query(default=None),
    dataset: Optional[List[str]] = Query(default=None),
    model: Optional[List[str]] = Query(default=None),
    metric: Optional[List[str]] = Query(default=None),
    category: Optional[List[str]] = Query(default=None),
    detail: Optional[List[str]] = Query(default=None),
    outcome: Optional[List[str]] = Query(default=None),
    source: Optional[List[str]] = Query(default=None),
    review_status: Optional[List[str]] = Query(default=None),
    from_date: Optional[str] = Query(default=None),
    to_date: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> dict[str, Any]:
    _require_dashboard_enabled()
    project = _project(db, principal, project_slug)
    return build_occurrences_payload(
        db,
        project,
        _filters(
            run_id=run_id,
            task=task,
            dataset=dataset,
            model=model,
            metric=metric,
            category=category,
            detail=detail,
            outcome=outcome,
            source=source,
            review_status=review_status,
            from_date=from_date,
            to_date=to_date,
        ),
        limit=limit,
        offset=offset,
    )


@router.get("/api/projects/{project_slug}/root-cause-dashboard/compare")
def root_cause_dashboard_compare(
    project_slug: str,
    run_id: List[str] = Query(default=[]),
    task: Optional[List[str]] = Query(default=None),
    dataset: Optional[List[str]] = Query(default=None),
    model: Optional[List[str]] = Query(default=None),
    metric: Optional[List[str]] = Query(default=None),
    category: Optional[List[str]] = Query(default=None),
    detail: Optional[List[str]] = Query(default=None),
    outcome: Optional[List[str]] = Query(default=None),
    source: Optional[List[str]] = Query(default=None),
    review_status: Optional[List[str]] = Query(default=None),
    from_date: Optional[str] = Query(default=None),
    to_date: Optional[str] = Query(default=None),
    score_metric: Optional[str] = Query(default=None),
    baseline_run_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> dict[str, Any]:
    _require_dashboard_enabled()
    project = _project(db, principal, project_slug)
    selected_ids = _values(run_id)
    if len(selected_ids) < 2 or len(selected_ids) > 8:
        raise HTTPException(status_code=400, detail="Select between 2 and 8 runs to compare")
    try:
        return build_compare_payload(
            db,
            project,
            selected_ids,
            _filters(
                run_id=selected_ids,
                task=task,
                dataset=dataset,
                model=model,
                metric=metric,
                category=category,
                detail=detail,
                outcome=outcome,
                source=source,
                review_status=review_status,
                from_date=from_date,
                to_date=to_date,
            ),
            score_metric=score_metric,
            baseline_run_id=baseline_run_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
