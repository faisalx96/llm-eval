"""Read-only project Insights API.

The dashboard needs complete, chronologically ordered run summaries rather than
the paginated sample used by the Runs table.  This endpoint keeps the expensive
aggregation server-side and returns one compact point per run.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any, Iterable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from qym_platform.auth import Principal, require_ui_principal
from qym_platform.datetime_utils import to_api_timestamp, utc_now_naive
from qym_platform.db.models import (
    DatasetVersion,
    Project,
    Run,
    RunItem,
    RunItemScore,
    RunMetricSpec,
    RunWorkflowStatus,
)
from qym_platform.deps import get_db
from qym_platform.permissions import has_project_access
from qym_platform.services.candidate_relationships import (
    build_relationship_analysis,
    build_relationship_occurrences,
)
from qym_platform.settings import PlatformSettings


router = APIRouter(tags=["insights"])

_MAX_RUNS = 500
_PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90, "all": None}
_LIVE_STATUSES = {
    RunWorkflowStatus.DRAFT,
    RunWorkflowStatus.PENDING,
    RunWorkflowStatus.RUNNING,
}


def _values(values: Iterable[str] | None) -> tuple[str, ...]:
    result: list[str] = []
    for value in values or []:
        for part in str(value or "").split(","):
            clean = part.strip()
            if clean and clean not in result:
                result.append(clean)
    return tuple(result)


def _display_model(model_name: str) -> str:
    if not model_name:
        return ""
    index = model_name.find("/")
    return model_name[index + 1 :] if index > 0 else model_name


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _metric_spec_payload(spec: RunMetricSpec) -> dict[str, Any]:
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


def _project(db: Session, principal: Principal, project_slug: str) -> Project:
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


@router.get("/api/projects/{project_slug}/insights/relationships")
def project_relationships(
    project_slug: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> dict[str, Any]:
    """Compute deterministic candidate relationships for the complete project."""

    project = _project(db, principal, project_slug)
    return build_relationship_analysis(db, project)


@router.get("/api/projects/{project_slug}/insights/relationships/{relationship_id}/occurrences")
def relationship_occurrences(
    project_slug: str,
    relationship_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Any:
    """Return evidence for a current relationship or a stale-ID response."""

    project = _project(db, principal, project_slug)
    payload = build_relationship_occurrences(
        db,
        project,
        relationship_id,
        limit=limit,
        offset=offset,
    )
    if payload is None:
        return JSONResponse(
            status_code=410,
            content={
                "stale": True,
                "code": "stale_relationship",
                "relationship_id": relationship_id,
                "message": "This relationship is no longer present in the current project analysis.",
                "refresh": f"/api/projects/{project_slug}/insights/relationships",
            },
        )
    return payload


@router.get("/api/projects/{project_slug}/insights")
def project_insights(
    project_slug: str,
    period: str = Query(default="30d"),
    task: Optional[list[str]] = Query(default=None),
    dataset: Optional[list[str]] = Query(default=None),
    dataset_version_id: Optional[list[str]] = Query(default=None),
    model: Optional[list[str]] = Query(default=None),
    status: Optional[list[str]] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> dict[str, Any]:
    """Return filtered run points and project-wide filter facets for Insights."""

    if period not in _PERIOD_DAYS:
        raise HTTPException(status_code=400, detail="Invalid period; use 7d, 30d, 90d, or all")

    project = _project(db, principal, project_slug)
    base_criteria: list[Any] = [
        Run.project_id == project.id,
        Run.deleted_at.is_(None),
        ~Run.status.in_(_LIVE_STATUSES),
    ]
    hidden_tasks = {
        task_name.strip().lower()
        for task_name in PlatformSettings().hidden_tasks.split(",")
        if task_name.strip()
    }
    if hidden_tasks:
        base_criteria.append(~func.lower(Run.task).in_(hidden_tasks))
    period_days = _PERIOD_DAYS[period]
    if period_days is not None:
        base_criteria.append(
            func.coalesce(Run.started_at, Run.created_at)
            >= utc_now_naive() - timedelta(days=period_days)
        )

    # Facets intentionally ignore the active selectors. This keeps every
    # regular filter available after the user narrows one dimension.
    task_facets = sorted(
        row[0]
        for row in db.query(Run.task).filter(*base_criteria).distinct().all()
        if row[0]
    )
    dataset_facets = sorted(
        row[0]
        for row in db.query(Run.dataset).filter(*base_criteria).distinct().all()
        if row[0]
    )
    model_facets = [
        {"value": raw, "label": _display_model(raw)}
        for (raw,) in (
            db.query(Run.model)
            .filter(*base_criteria, Run.model.isnot(None), Run.model != "")
            .distinct()
            .all()
        )
        if raw
    ]
    model_facets.sort(key=lambda item: (item["label"].casefold(), item["value"].casefold()))
    status_facets = sorted(
        str(getattr(row[0], "value", row[0]))
        for row in db.query(Run.status).filter(*base_criteria).distinct().all()
        if row[0]
    )
    version_facets = [
        {"value": version_id, "label": version}
        for version_id, version in (
            db.query(DatasetVersion.id, DatasetVersion.version)
            .join(Run, Run.dataset_version_id == DatasetVersion.id)
            .filter(*base_criteria)
            .distinct()
            .all()
        )
    ]
    version_facets.sort(key=lambda item: (item["label"].casefold(), item["value"]))

    metric_names: set[str] = set()
    for (metrics,) in db.query(Run.metrics).filter(*base_criteria).all():
        metric_names.update(str(metric) for metric in (metrics or []) if str(metric).strip())

    selected_tasks = _values(task)
    selected_datasets = _values(dataset)
    selected_versions = _values(dataset_version_id)
    selected_models = _values(model)
    selected_statuses_raw = _values(status)

    selected_statuses: list[RunWorkflowStatus] = []
    for raw_status in selected_statuses_raw:
        try:
            parsed_status = RunWorkflowStatus(raw_status.upper())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid run status: {raw_status}") from exc
        if parsed_status in _LIVE_STATUSES:
            raise HTTPException(status_code=400, detail=f"Live status is not available in Insights: {raw_status}")
        selected_statuses.append(parsed_status)

    query = db.query(Run).filter(*base_criteria)
    if selected_tasks:
        query = query.filter(Run.task.in_(selected_tasks))
    if selected_datasets:
        query = query.filter(Run.dataset.in_(selected_datasets))
    if selected_versions:
        query = query.filter(Run.dataset_version_id.in_(selected_versions))
    if selected_models:
        query = query.filter(Run.model.in_(selected_models))
    if selected_statuses:
        query = query.filter(Run.status.in_(selected_statuses))

    total_count = query.count()
    # Select the latest bounded window, then put it in the requested oldest to
    # latest order for the horizontal timeline.
    runs = (
        query.order_by(
            func.coalesce(Run.started_at, Run.created_at).desc(),
            Run.id.desc(),
        )
        .limit(_MAX_RUNS)
        .all()
    )
    runs.reverse()

    if not runs:
        return {
            "project": {"id": project.id, "slug": project.slug, "name": project.name},
            "period": period,
            "facets": {
                "tasks": task_facets,
                "datasets": dataset_facets,
                "dataset_versions": version_facets,
                "models": model_facets,
                "statuses": status_facets,
                "metrics": sorted(metric_names),
            },
            "runs": [],
            "total_count": total_count,
            "truncated": False,
        }

    run_ids = [run.id for run in runs]
    item_rows = (
        db.query(
            RunItem.run_id,
            func.count(RunItem.id).label("total"),
            func.count(case((RunItem.error.isnot(None), 1))).label("errors"),
            func.coalesce(func.sum(RunItem.retry_count), 0).label("retries"),
            func.avg(RunItem.latency_ms).label("avg_latency"),
        )
        .filter(RunItem.run_id.in_(run_ids))
        .group_by(RunItem.run_id)
        .all()
    )
    item_stats = {
        row.run_id: {
            "total": int(row.total or 0),
            "errors": int(row.errors or 0),
            "retries": int(row.retries or 0),
            "avg_latency": float(row.avg_latency) if row.avg_latency is not None else None,
        }
        for row in item_rows
    }
    latencies: dict[str, list[float]] = defaultdict(list)
    for run_id, latency in (
        db.query(RunItem.run_id, RunItem.latency_ms)
        .filter(RunItem.run_id.in_(run_ids), RunItem.latency_ms.isnot(None))
        .all()
    ):
        latencies[run_id].append(float(latency))

    score_rows = (
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
        .filter(RunItemScore.run_id.in_(run_ids), RunItem.error.is_(None))
        .group_by(RunItemScore.run_id, RunItemScore.metric_name)
        .all()
    )
    scores: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    for row in score_rows:
        scores[row.run_id][row.metric_name] = {
            "sum": float(row.score_sum or 0.0),
            "count": float(row.score_count or 0.0),
        }

    specs: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for spec in (
        db.query(RunMetricSpec)
        .filter(RunMetricSpec.run_id.in_(run_ids))
        .order_by(RunMetricSpec.position.asc())
        .all()
    ):
        specs[spec.run_id][spec.metric_name] = _metric_spec_payload(spec)

    version_map = {
        version.id: version.version
        for version in (
            db.query(DatasetVersion)
            .filter(DatasetVersion.id.in_({run.dataset_version_id for run in runs if run.dataset_version_id}))
            .all()
        )
    }

    run_points: list[dict[str, Any]] = []
    for run in runs:
        stats = item_stats.get(
            run.id,
            {"total": 0, "errors": 0, "retries": 0, "avg_latency": None},
        )
        denominator_by_metric: dict[str, int] = {}
        averages: dict[str, float | None] = {}
        for metric_name in run.metrics or []:
            score = scores.get(run.id, {}).get(metric_name, {"sum": 0.0, "count": 0.0})
            denominator = int(score["count"] + stats["errors"])
            denominator_by_metric[metric_name] = denominator
            averages[metric_name] = score["sum"] / denominator if denominator else None

        started_at = run.started_at or run.created_at
        duration_ms = None
        if started_at and run.ended_at and run.ended_at >= started_at:
            duration_ms = (run.ended_at - started_at).total_seconds() * 1000.0
        run_name = ""
        if isinstance(run.run_config, dict):
            run_name = str(run.run_config.get("run_name") or "")
        run_name = run_name or run.external_run_id or run.id[:8]

        total_items = stats["total"]
        error_count = stats["errors"]
        run_points.append(
            {
                "run_id": run.id,
                "run_name": run_name,
                "timestamp": to_api_timestamp(started_at),
                "task_name": run.task,
                "dataset_name": run.dataset,
                "dataset_version_id": run.dataset_version_id,
                "dataset_version": version_map.get(run.dataset_version_id),
                "model": run.model or "",
                "model_name": _display_model(run.model or ""),
                "status": str(getattr(run.status, "value", run.status)),
                "metrics": list(run.metrics or []),
                "metric_averages": averages,
                "metric_counts": denominator_by_metric,
                "metric_specs": specs.get(run.id, {}),
                "total_items": total_items,
                "error_count": error_count,
                "success_rate": (
                    (total_items - error_count) / total_items if total_items else None
                ),
                "total_retries": stats["retries"],
                "avg_latency_ms": stats["avg_latency"],
                "median_latency_ms": _median(latencies.get(run.id, [])),
                "duration_ms": duration_ms,
                "git_branch": (
                    run.run_config.get("git_branch")
                    if isinstance(run.run_config, dict)
                    else None
                ),
                "git_commit": (
                    run.run_config.get("git_commit")
                    if isinstance(run.run_config, dict)
                    else None
                ),
                "trace_stats": (
                    run.run_metadata.get("trace_stats")
                    if isinstance(run.run_metadata, dict)
                    else None
                ),
            }
        )

    return {
        "project": {"id": project.id, "slug": project.slug, "name": project.name},
        "period": period,
        "facets": {
            "tasks": task_facets,
            "datasets": dataset_facets,
            "dataset_versions": version_facets,
            "models": model_facets,
            "statuses": status_facets,
            "metrics": sorted(metric_names),
        },
        "runs": run_points,
        "total_count": total_count,
        "truncated": total_count > _MAX_RUNS,
    }
