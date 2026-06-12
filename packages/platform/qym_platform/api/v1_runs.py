from __future__ import annotations

import re
from collections import Counter
from datetime import timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import String, and_, case, cast, func, or_
from sqlalchemy.orm import Session

from qym_platform.api.runs import _strip_model_provider, _stringify
from qym_platform.api.schemas import (
    ApprovalContext,
    ErrorSummary,
    ItemTraceSummary,
    MetricDistributionBucket,
    MetricStats,
    ProjectOverviewStats,
    ReviewQueueEntry,
    ReviewQueueResponse,
    RunDetail,
    RunItemDetail,
    RunItemSlim,
    RunItemsResponse,
    RunListResponse,
    RunRenameRequest,
    RunRenameResponse,
    RunSummary,
    TrendPoint,
    TrendSeries,
    TrendsResponse,
    UserRef,
    VersionInfo,
)
from qym_platform.auth import Principal, require_ui_principal
from qym_platform.datetime_utils import to_api_timestamp, utc_now_naive
from qym_platform.db.models import (
    ApiKey,
    Approval,
    AuditLog,
    Project,
    ReviewCorrection,
    Run,
    RunItem,
    RunItemScore,
    RunWorkflowStatus,
    User,
)
from qym_platform.deps import get_db
from qym_platform.permissions import can_approve_run, can_view_run, has_project_access
from qym_platform.security import api_key_prefix, verify_api_key


router = APIRouter(tags=["v1"])

_SENSITIVE_METADATA_KEY_RE = re.compile(
    r"(secret|token|password|api[_-]?key|authorization|credential)", re.IGNORECASE
)

# Statuses that represent a finished, scoreable run for aggregates/trends.
_FINISHED_STATUSES = (RunWorkflowStatus.COMPLETED, RunWorkflowStatus.APPROVED)


# ---------------------------------------------------------------------------
# Auth: accept both an SPA session (require_ui_principal) and Bearer API keys,
# mirroring the dual-principal pattern in api/datasets.py.
# ---------------------------------------------------------------------------

def _principal_from_bearer(db: Session, authorization: Optional[str]) -> Optional[Principal]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    if not token:
        return None
    row = (
        db.query(ApiKey)
        .filter(ApiKey.prefix == api_key_prefix(token))
        .filter(ApiKey.revoked_at.is_(None))
        .first()
    )
    if not row or not verify_api_key(token, row.key_hash):
        raise HTTPException(status_code=401, detail="Invalid API key")
    user = db.query(User).filter(User.id == row.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=403, detail="User disabled")
    scopes = tuple(str(scope).strip() for scope in (row.scopes or []) if str(scope).strip())
    return Principal(user=user, auth_type="api_key", scopes=scopes, project_id=row.project_id)


def v1_principal(
    request: Request,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(default=None),
    x_user_email: Optional[str] = Header(default=None, alias="X-User-Email"),
    x_email: Optional[str] = Header(default=None, alias="X-Email"),
    x_admin_bootstrap: Optional[str] = Header(default=None, alias="X-Admin-Bootstrap"),
) -> Principal:
    api_principal = _principal_from_bearer(db, authorization)
    if api_principal:
        return api_principal
    return require_ui_principal(
        request=request,
        db=db,
        x_user_email=x_user_email,
        x_email=x_email,
        x_admin_bootstrap=x_admin_bootstrap,
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _check_project_access(db: Session, principal: Principal, project: Project) -> None:
    # API keys are bound to a single project; never let them cross over.
    if principal.project_id and principal.project_id != project.id:
        raise HTTPException(status_code=403, detail="Access denied")
    if not has_project_access(db, principal, project.id):
        raise HTTPException(status_code=403, detail="Access denied")


def _resolve_project(
    db: Session,
    principal: Principal,
    project_id: Optional[str],
    project_slug: Optional[str],
) -> Project:
    if not project_id and not project_slug:
        raise HTTPException(status_code=400, detail="project_id or project_slug is required")
    query = db.query(Project).filter(Project.is_active.is_(True))
    if project_id:
        project = query.filter(Project.id == project_id).first()
    else:
        project = query.filter(Project.slug == project_slug).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    _check_project_access(db, principal, project)
    return project


def _resolve_project_ref(db: Session, principal: Principal, ref: str) -> Project:
    """Resolve a path reference that may be a project id or slug."""
    project = (
        db.query(Project)
        .filter(Project.is_active.is_(True))
        .filter(or_(Project.id == ref, Project.slug == ref))
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    _check_project_access(db, principal, project)
    return project


def _get_run(db: Session, run_id: str) -> Run:
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def _check_run_access(db: Session, principal: Principal, run: Run) -> None:
    if principal.project_id and principal.project_id != run.project_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if not can_view_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")


def _iso(dt) -> Optional[str]:
    return to_api_timestamp(dt) if dt else None


def _run_name(run: Run) -> str:
    """Human name: run_config.run_name -> external_run_id -> id (legacy derivation)."""
    name = ""
    if isinstance(run.run_config, dict):
        name = str(run.run_config.get("run_name") or "")
    return name or run.external_run_id or run.id


def _group_key(run: Run) -> str:
    model = _strip_model_provider(run.model or "") or "nomodel"
    return f"{run.task}|{run.dataset}|{model}"


def _duration_ms(run: Run) -> Optional[float]:
    started = run.started_at or run.created_at
    if started and run.ended_at and run.ended_at >= started:
        return (run.ended_at - started).total_seconds() * 1000.0
    return None


def _version_info(run: Run) -> Optional[VersionInfo]:
    config = run.run_config if isinstance(run.run_config, dict) else {}
    branch = config.get("git_branch")
    commit = config.get("git_commit")
    if not branch and not commit:
        return None
    return VersionInfo(branch=branch, commit=commit)


def _user_ref(user: Optional[User]) -> Optional[UserRef]:
    if not user:
        return None
    return UserRef(
        id=user.id,
        email=user.email,
        display_name=user.display_name or user.email.split("@")[0],
    )


def _sanitize_run_metadata(metadata: Any) -> Dict[str, Any]:
    """Drop secret-looking keys; trace_stats is exposed as its own field."""
    if not isinstance(metadata, dict):
        return {}
    return {
        key: value
        for key, value in metadata.items()
        if key != "trace_stats" and not _SENSITIVE_METADATA_KEY_RE.search(str(key))
    }


def _item_aggregates(db: Session, run_ids: List[str]) -> Dict[str, Dict[str, int]]:
    if not run_ids:
        return {}
    rows = (
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
    return {
        row.run_id: {
            "total": int(row.total or 0),
            "error_count": int(row.error_count or 0),
            "completed": int(row.completed or 0),
        }
        for row in rows
    }


def _score_aggregates(db: Session, run_ids: List[str]) -> Dict[str, Dict[str, Dict[str, float]]]:
    """run_id -> metric -> {sum, count}. Errored items excluded (legacy semantics)."""
    if not run_ids:
        return {}
    rows = (
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
        .filter(RunItemScore.run_id.in_(run_ids), RunItem.error.is_(None))
        .group_by(RunItemScore.run_id, RunItemScore.metric_name)
        .all()
    )
    agg: Dict[str, Dict[str, Dict[str, float]]] = {}
    for row in rows:
        agg.setdefault(row.run_id, {})[row.metric_name] = {
            "sum": float(row.score_sum) if row.score_sum is not None else 0.0,
            "count": float(row.score_count or 0),
        }
    return agg


def _metric_averages_for_run(
    run: Run,
    run_score_agg: Dict[str, Dict[str, float]],
    error_count: int,
) -> Dict[str, float]:
    """Match run-detail semantics: errored items count as 0, unscored excluded."""
    averages: Dict[str, float] = {}
    for metric in list(run.metrics or []):
        entry = run_score_agg.get(metric, {})
        denominator = entry.get("count", 0.0) + error_count
        averages[metric] = (entry.get("sum", 0.0) / denominator) if denominator else 0.0
    return averages


def _summarize_runs(db: Session, runs: List[Run]) -> List[RunSummary]:
    if not runs:
        return []
    run_ids = [run.id for run in runs]
    item_agg = _item_aggregates(db, run_ids)
    score_agg = _score_aggregates(db, run_ids)
    owner_ids = {run.owner_user_id for run in runs}
    owners = db.query(User).filter(User.id.in_(owner_ids)).all() if owner_ids else []
    owner_map = {owner.id: owner for owner in owners}

    summaries: List[RunSummary] = []
    for run in runs:
        agg = item_agg.get(run.id, {"total": 0, "error_count": 0, "completed": 0})
        expected_total = None
        if isinstance(run.run_metadata, dict):
            try:
                if run.run_metadata.get("total_items") is not None:
                    expected_total = int(run.run_metadata["total_items"])
            except Exception:
                expected_total = None
        completed = agg["completed"]
        summaries.append(
            RunSummary(
                id=run.id,
                name=_run_name(run),
                task=run.task,
                dataset=run.dataset,
                model=_strip_model_provider(run.model or "") or None,
                status=run.status.value if hasattr(run.status, "value") else str(run.status or ""),
                created_at=_iso(run.created_at),
                started_at=_iso(run.started_at),
                ended_at=_iso(run.ended_at),
                duration_ms=_duration_ms(run),
                owner=_user_ref(owner_map.get(run.owner_user_id)),
                total_items=agg["total"],
                completed_items=completed,
                error_items=agg["error_count"],
                progress_pct=(completed / expected_total) if expected_total else None,
                metric_averages=_metric_averages_for_run(run, score_agg.get(run.id, {}), agg["error_count"]),
                version=_version_info(run),
                group_key=_group_key(run),
            )
        )
    return summaries


def _parse_statuses(raw: Optional[str]) -> List[RunWorkflowStatus]:
    statuses: List[RunWorkflowStatus] = []
    for part in (raw or "").split(","):
        normalized = part.strip().upper()
        if not normalized:
            continue
        try:
            statuses.append(RunWorkflowStatus(normalized))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid run status: {part}") from None
    return statuses


def _duration_order_expr(db: Session):
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        return func.julianday(Run.ended_at) - func.julianday(func.coalesce(Run.started_at, Run.created_at))
    return func.extract("epoch", Run.ended_at) - func.extract("epoch", func.coalesce(Run.started_at, Run.created_at))


# ---------------------------------------------------------------------------
# 1. GET /v1/runs — flat paginated run list
# ---------------------------------------------------------------------------

@router.get("/v1/runs", response_model=RunListResponse)
def list_runs(
    project_id: Optional[str] = Query(default=None),
    project_slug: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None, description="Comma-separated workflow statuses"),
    owner: Optional[str] = Query(default=None, description="Owner user id, email, or display name"),
    task: Optional[str] = Query(default=None),
    dataset: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None, description="Substring match on run name"),
    needs_review: bool = Query(default=False, description="Only runs awaiting review (SUBMITTED)"),
    sort: str = Query(default="-created_at", description="created_at|-created_at|duration|-duration"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(v1_principal),
) -> RunListResponse:
    project = _resolve_project(db, principal, project_id, project_slug)

    query = Run.active(db).filter(Run.project_id == project.id)

    statuses = _parse_statuses(status)
    if statuses:
        query = query.filter(Run.status.in_(statuses))
    if needs_review:
        query = query.filter(Run.status == RunWorkflowStatus.SUBMITTED)
    if task:
        query = query.filter(Run.task == task)
    if dataset:
        query = query.filter(Run.dataset == dataset)
    if model:
        lowered = model.strip().lower()
        query = query.filter(
            or_(func.lower(Run.model) == lowered, func.lower(Run.model).like(f"%/{lowered}"))
        )
    if owner:
        lowered_owner = owner.strip().lower()
        query = query.join(User, User.id == Run.owner_user_id).filter(
            or_(
                Run.owner_user_id == owner.strip(),
                func.lower(User.email) == lowered_owner,
                func.lower(User.display_name).like(f"%{lowered_owner}%"),
            )
        )
    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        name_expr = func.lower(func.coalesce(Run.run_config["run_name"].as_string(), ""))
        query = query.filter(
            or_(
                name_expr.like(needle),
                func.lower(func.coalesce(Run.external_run_id, "")).like(needle),
            )
        )

    if sort == "created_at":
        query = query.order_by(Run.created_at.asc())
    elif sort == "-created_at":
        query = query.order_by(Run.created_at.desc())
    elif sort in ("duration", "-duration"):
        expr = _duration_order_expr(db)
        ordered = expr.asc() if sort == "duration" else expr.desc()
        query = query.order_by(ordered.nullslast(), Run.created_at.desc())
    else:
        raise HTTPException(status_code=400, detail=f"Invalid sort: {sort}")

    total = query.count()
    runs = query.offset(offset).limit(limit).all()
    return RunListResponse(runs=_summarize_runs(db, runs), total=total, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# 2. GET /v1/runs/{run_id} — run detail without items
# ---------------------------------------------------------------------------

def _metric_stats(db: Session, run: Run, error_count: int) -> List[MetricStats]:
    score = RunItemScore.score_numeric
    bucket_defs = [
        ("0.00-0.25", and_(score >= 0.0, score < 0.25)),
        ("0.25-0.50", and_(score >= 0.25, score < 0.5)),
        ("0.50-0.75", and_(score >= 0.5, score < 0.75)),
        ("0.75-1.00", score >= 0.75),
    ]
    rows = (
        db.query(
            RunItemScore.metric_name,
            func.sum(score).label("score_sum"),
            func.count(score).label("score_count"),
            func.sum(case((score >= 0.5, 1), else_=0)).label("pass_count"),
            func.sum(case((score < 0.5, 1), else_=0)).label("fail_count"),
            *[
                func.sum(case((condition, 1), else_=0)).label(f"bucket_{index}")
                for index, (_label, condition) in enumerate(bucket_defs)
            ],
        )
        .join(
            RunItem,
            (RunItem.run_id == RunItemScore.run_id) & (RunItem.item_id == RunItemScore.item_id),
        )
        .filter(RunItemScore.run_id == run.id, RunItem.error.is_(None), score.isnot(None))
        .group_by(RunItemScore.metric_name)
        .all()
    )
    by_metric = {row.metric_name: row for row in rows}
    stats: List[MetricStats] = []
    for metric in list(run.metrics or []):
        row = by_metric.get(metric)
        score_sum = float(row.score_sum) if row and row.score_sum is not None else 0.0
        score_count = int(row.score_count or 0) if row else 0
        denominator = score_count + error_count
        stats.append(
            MetricStats(
                name=metric,
                avg=(score_sum / denominator) if denominator else 0.0,
                pass_count=int(row.pass_count or 0) if row else 0,
                fail_count=(int(row.fail_count or 0) if row else 0) + error_count,
                distribution=[
                    MetricDistributionBucket(
                        label=label,
                        count=int(getattr(row, f"bucket_{index}") or 0) if row else 0,
                    )
                    for index, (label, _condition) in enumerate(bucket_defs)
                ],
            )
        )
    return stats


def _approval_context(db: Session, run: Run) -> Optional[ApprovalContext]:
    approval = db.query(Approval).filter(Approval.run_id == run.id).first()
    if not approval:
        return None
    user_ids = {uid for uid in (approval.submitted_by_user_id, approval.decision_by_user_id) if uid}
    users = db.query(User).filter(User.id.in_(user_ids)).all() if user_ids else []
    user_map = {user.id: user for user in users}
    return ApprovalContext(
        status=approval.decision.value if approval.decision else "PENDING",
        submitted_by=_user_ref(user_map.get(approval.submitted_by_user_id)),
        submitted_at=_iso(approval.submitted_at),
        decided_by=_user_ref(user_map.get(approval.decision_by_user_id)),
        decided_at=_iso(approval.decision_at),
        comment=approval.comment or "",
    )


def _error_summary(db: Session, run: Run, error_count: int) -> ErrorSummary:
    if not error_count:
        return ErrorSummary(task_errors=0, types={})
    rows = db.query(RunItem.error).filter(RunItem.run_id == run.id, RunItem.error.isnot(None)).all()
    counter: Counter[str] = Counter()
    for (error_text,) in rows:
        first_line = str(error_text or "").strip().splitlines()[0][:120] if error_text else "unknown"
        counter[first_line or "unknown"] += 1
    return ErrorSummary(task_errors=error_count, types=dict(counter.most_common(10)))


@router.get("/v1/runs/{run_id}", response_model=RunDetail)
def get_run_detail(
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(v1_principal),
) -> RunDetail:
    run = _get_run(db, run_id)
    _check_run_access(db, principal, run)

    summary = _summarize_runs(db, [run])[0]
    error_count = summary.error_items
    run_metadata = run.run_metadata if isinstance(run.run_metadata, dict) else {}
    trace_stats = run_metadata.get("trace_stats")
    return RunDetail(
        **summary.model_dump(),
        run_config=run.run_config if isinstance(run.run_config, dict) else {},
        run_metadata=_sanitize_run_metadata(run_metadata),
        metrics=list(run.metrics or []),
        metric_stats=_metric_stats(db, run, error_count),
        trace_stats=trace_stats if isinstance(trace_stats, dict) else None,
        approval=_approval_context(db, run),
        error_summary=_error_summary(db, run, error_count),
    )


# ---------------------------------------------------------------------------
# 3. GET /v1/runs/{run_id}/items — paginated slim rows
# ---------------------------------------------------------------------------

def _preview(value: Any, max_chars: int = 200) -> str:
    return _stringify(value)[:max_chars]


def _metric_values_for_items(db: Session, run_id: str, item_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not item_ids:
        return {}
    rows = (
        db.query(RunItemScore)
        .filter(RunItemScore.run_id == run_id, RunItemScore.item_id.in_(item_ids))
        .all()
    )
    values: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        value = row.score_numeric if row.score_numeric is not None else row.score_raw
        values.setdefault(row.item_id, {})[row.metric_name] = value
    return values


def _correction_status_for_items(db: Session, run_id: str, item_ids: List[str]) -> Dict[str, str]:
    if not item_ids:
        return {}
    corrections = (
        db.query(ReviewCorrection)
        .filter(
            ReviewCorrection.run_id == run_id,
            ReviewCorrection.item_id.in_(item_ids),
            ReviewCorrection.is_active.is_(True),
        )
        .order_by(ReviewCorrection.created_at.desc())
        .all()
    )
    statuses: Dict[str, str] = {}
    for correction in corrections:
        if correction.item_id in statuses:
            continue
        statuses[correction.item_id] = (
            correction.status.value if hasattr(correction.status, "value") else str(correction.status or "")
        )
    return statuses


@router.get("/v1/runs/{run_id}/items", response_model=RunItemsResponse)
def list_run_items(
    run_id: str,
    status: Optional[str] = Query(default=None, description="completed|failed"),
    failed_only: bool = Query(default=False),
    metric: Optional[str] = Query(default=None, description="Metric name for below/score filters"),
    below: Optional[float] = Query(default=None, description="Only items with metric score below this value"),
    sort: str = Query(default="index", description="index|latency|-latency|score"),
    q: Optional[str] = Query(default=None, description="Substring over input/output"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(v1_principal),
) -> RunItemsResponse:
    run = _get_run(db, run_id)
    _check_run_access(db, principal, run)

    if status not in (None, "completed", "failed"):
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    query = db.query(RunItem).filter(RunItem.run_id == run.id)
    if failed_only or status == "failed":
        query = query.filter(RunItem.error.isnot(None))
    elif status == "completed":
        query = query.filter(RunItem.error.is_(None))

    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        query = query.filter(
            or_(
                func.lower(func.coalesce(cast(RunItem.input, String), "")).like(needle),
                func.lower(func.coalesce(cast(RunItem.output, String), "")).like(needle),
            )
        )

    score_join = and_(
        RunItemScore.run_id == RunItem.run_id,
        RunItemScore.item_id == RunItem.item_id,
        RunItemScore.metric_name == (metric or ""),
    )
    score_joined = False
    if below is not None:
        if not metric:
            raise HTTPException(status_code=400, detail="below requires metric")
        query = query.join(RunItemScore, score_join).filter(RunItemScore.score_numeric < below)
        score_joined = True

    if sort == "index":
        order = RunItem.index.asc()
    elif sort == "latency":
        order = RunItem.latency_ms.asc().nullslast()
    elif sort == "-latency":
        order = RunItem.latency_ms.desc().nullslast()
    elif sort == "score":
        if not metric:
            raise HTTPException(status_code=400, detail="sort=score requires metric")
        if not score_joined:
            query = query.outerjoin(RunItemScore, score_join)
        order = RunItemScore.score_numeric.asc().nullslast()
    else:
        raise HTTPException(status_code=400, detail=f"Invalid sort: {sort}")

    total = query.count()
    items = query.order_by(order, RunItem.index.asc()).offset(offset).limit(limit).all()

    item_ids = [item.item_id for item in items]
    metric_values = _metric_values_for_items(db, run.id, item_ids)
    correction_statuses = _correction_status_for_items(db, run.id, item_ids)

    rows: List[RunItemSlim] = []
    for item in items:
        item_metadata = item.item_metadata if isinstance(item.item_metadata, dict) else {}
        rows.append(
            RunItemSlim(
                item_id=item.item_id,
                index=item.index,
                status="failed" if item.error else "completed",
                input_preview=_preview(item.input),
                output_preview=_preview(item.output),
                expected_preview=_preview(item.expected),
                latency_ms=item.latency_ms,
                retry_count=int(item.retry_count or item_metadata.get("retry_count") or 0),
                metric_values=metric_values.get(item.item_id, {}),
                has_trace=bool(item.trace_id),
                root_cause=str(item_metadata.get("root_cause") or "") or None,
                root_cause_source=str(item_metadata.get("root_cause_source") or "") or None,
                review_correction_status=correction_statuses.get(item.item_id),
            )
        )
    return RunItemsResponse(items=rows, total=total, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# 4. GET /v1/runs/{run_id}/items/{item_id} — full item detail
# ---------------------------------------------------------------------------

@router.get("/v1/runs/{run_id}/items/{item_id}", response_model=RunItemDetail)
def get_run_item_detail(
    run_id: str,
    item_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(v1_principal),
) -> RunItemDetail:
    run = _get_run(db, run_id)
    _check_run_access(db, principal, run)

    item = (
        db.query(RunItem)
        .filter(RunItem.run_id == run.id, RunItem.item_id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    scores = (
        db.query(RunItemScore)
        .filter(RunItemScore.run_id == run.id, RunItemScore.item_id == item.item_id)
        .all()
    )
    metric_values: Dict[str, Any] = {}
    metric_meta: Dict[str, Any] = {}
    for score in scores:
        metric_values[score.metric_name] = (
            score.score_numeric if score.score_numeric is not None else score.score_raw
        )
        meta = dict(score.meta or {})
        if score.label:
            meta["label"] = score.label
        if score.explanation:
            meta["explanation"] = score.explanation
        if meta:
            metric_meta[score.metric_name] = meta

    item_metadata = item.item_metadata if isinstance(item.item_metadata, dict) else {}
    correction_statuses = _correction_status_for_items(db, run.id, [item.item_id])
    return RunItemDetail(
        item_id=item.item_id,
        index=item.index,
        status="failed" if item.error else "completed",
        input=item.input,
        output=item.output,
        expected=item.expected,
        error=item.error,
        latency_ms=item.latency_ms,
        retry_count=int(item.retry_count or item_metadata.get("retry_count") or 0),
        item_metadata=item_metadata,
        metric_values=metric_values,
        metric_meta=metric_meta,
        trace=ItemTraceSummary(
            has_trace=bool(item.trace_id),
            trace_id=item.trace_id or "",
            trace_url=item.trace_url or "",
        ),
        review_correction_status=correction_statuses.get(item.item_id),
    )


# ---------------------------------------------------------------------------
# 5. PATCH /v1/runs/{run_id} — rename
# ---------------------------------------------------------------------------

@router.patch("/v1/runs/{run_id}", response_model=RunRenameResponse)
def rename_run(
    run_id: str,
    body: RunRenameRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(v1_principal),
) -> RunRenameResponse:
    run = _get_run(db, run_id)
    _check_run_access(db, principal, run)
    # Owner, project manager, or admin only (plain members cannot rename others' runs).
    if run.owner_user_id != principal.user.id and not can_approve_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Only the run owner or a project manager can rename")

    name = body.display_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="display_name must not be blank")

    # run_config.run_name is what every list/detail name derivation reads.
    config = dict(run.run_config) if isinstance(run.run_config, dict) else {}
    previous = str(config.get("run_name") or "")
    config["run_name"] = name
    run.run_config = config
    db.add(
        AuditLog(
            actor_user_id=principal.user.id,
            action="run.renamed",
            entity_type="run",
            entity_id=run.id,
            before={"run_name": previous},
            after={"run_name": name},
        )
    )
    db.commit()
    return RunRenameResponse(id=run.id, name=name)


# ---------------------------------------------------------------------------
# 6. GET /v1/projects/{project_id}/overview-stats
# ---------------------------------------------------------------------------

@router.get("/v1/projects/{project_id}/overview-stats", response_model=ProjectOverviewStats)
def project_overview_stats(
    project_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(v1_principal),
) -> ProjectOverviewStats:
    project = _resolve_project_ref(db, principal, project_id)

    status_rows = (
        db.query(Run.status, func.count(Run.id), func.max(Run.created_at))
        .filter(Run.project_id == project.id, Run.deleted_at.is_(None))
        .group_by(Run.status)
        .all()
    )
    by_status: Dict[str, int] = {}
    total_runs = 0
    last_run_at = None
    for run_status, count, latest in status_rows:
        key = run_status.value if hasattr(run_status, "value") else str(run_status or "")
        by_status[key] = int(count or 0)
        total_runs += int(count or 0)
        if latest and (last_run_at is None or latest > last_run_at):
            last_run_at = latest

    model_rows = (
        db.query(Run.model)
        .filter(Run.project_id == project.id, Run.deleted_at.is_(None), Run.model.isnot(None))
        .distinct()
        .all()
    )
    models = sorted({_strip_model_provider(row[0] or "") for row in model_rows if row[0]})

    total_items = (
        db.query(func.count(RunItem.id))
        .join(Run, Run.id == RunItem.run_id)
        .filter(Run.project_id == project.id, Run.deleted_at.is_(None))
        .scalar()
        or 0
    )

    metric_rows = (
        db.query(RunItemScore.metric_name, func.avg(RunItemScore.score_numeric))
        .select_from(RunItemScore)
        .join(Run, Run.id == RunItemScore.run_id)
        .join(
            RunItem,
            (RunItem.run_id == RunItemScore.run_id) & (RunItem.item_id == RunItemScore.item_id),
        )
        .filter(
            Run.project_id == project.id,
            Run.deleted_at.is_(None),
            Run.status.in_(_FINISHED_STATUSES),
            RunItem.error.is_(None),
            RunItemScore.score_numeric.isnot(None),
        )
        .group_by(RunItemScore.metric_name)
        .all()
    )
    metric_averages = {name: float(avg) for name, avg in metric_rows if avg is not None}

    return ProjectOverviewStats(
        project_id=project.id,
        total_runs=total_runs,
        by_status=by_status,
        models=models,
        total_items=int(total_items),
        metric_averages=metric_averages,
        last_run_at=_iso(last_run_at),
    )


# ---------------------------------------------------------------------------
# 7. GET /v1/projects/{project_id}/trends
# ---------------------------------------------------------------------------

def _trend_group(run: Run, group_by: str) -> str:
    if group_by == "version":
        config = run.run_config if isinstance(run.run_config, dict) else {}
        commit = str(config.get("git_commit") or "")
        branch = str(config.get("git_branch") or "")
        return commit[:12] or branch or "unversioned"
    return _strip_model_provider(run.model or "") or "nomodel"


@router.get("/v1/projects/{project_id}/trends", response_model=TrendsResponse)
def project_trends(
    project_id: str,
    task: str = Query(...),
    dataset: Optional[str] = Query(default=None),
    metric: Optional[str] = Query(default=None),
    group_by: str = Query(default="model", description="model|version"),
    window: int = Query(default=90, ge=1, le=365, description="Window in days"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(v1_principal),
) -> TrendsResponse:
    project = _resolve_project_ref(db, principal, project_id)
    if group_by not in ("model", "version"):
        raise HTTPException(status_code=400, detail=f"Invalid group_by: {group_by}")

    cutoff = utc_now_naive() - timedelta(days=window)
    effective_start = func.coalesce(Run.started_at, Run.created_at)
    runs_query = Run.active(db).filter(
        Run.project_id == project.id,
        Run.task == task,
        Run.status.in_(_FINISHED_STATUSES),
        effective_start >= cutoff,
    )
    if dataset:
        runs_query = runs_query.filter(Run.dataset == dataset)
    runs = runs_query.order_by(effective_start.asc()).limit(500).all()

    run_ids = [run.id for run in runs]
    score_agg = _score_aggregates(db, run_ids)
    item_agg = _item_aggregates(db, run_ids)

    series_map: Dict[tuple[str, str], TrendSeries] = {}
    for run in runs:
        group = _trend_group(run, group_by)
        error_count = item_agg.get(run.id, {}).get("error_count", 0)
        for metric_name, entry in sorted(score_agg.get(run.id, {}).items()):
            if metric and metric_name != metric:
                continue
            denominator = entry.get("count", 0.0) + error_count
            if not denominator:
                continue
            key = (group, metric_name)
            if key not in series_map:
                series_map[key] = TrendSeries(group=group, metric=metric_name, points=[])
            series_map[key].points.append(
                TrendPoint(
                    run_id=run.id,
                    date=_iso(run.started_at or run.created_at),
                    value=entry.get("sum", 0.0) / denominator,
                    n_items=int(denominator),
                )
            )

    return TrendsResponse(
        task=task,
        dataset=dataset,
        group_by=group_by,
        window_days=window,
        series=[series_map[key] for key in sorted(series_map)],
    )


# ---------------------------------------------------------------------------
# 8. GET /v1/reviews/queue
# ---------------------------------------------------------------------------

@router.get("/v1/reviews/queue", response_model=ReviewQueueResponse)
def reviews_queue(
    project_id: Optional[str] = Query(default=None),
    project_slug: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(v1_principal),
) -> ReviewQueueResponse:
    project = _resolve_project(db, principal, project_id, project_slug)

    submitted = (
        Run.active(db)
        .filter(Run.project_id == project.id, Run.status == RunWorkflowStatus.SUBMITTED)
        .order_by(Run.created_at.desc())
        .limit(100)
        .all()
    )
    summaries = _summarize_runs(db, submitted)

    # Baseline lookup: one indexed query per submitted run. The review queue is
    # small by construction (only SUBMITTED runs), so this stays cheap; metric
    # averages for all baselines are computed in a single batch below.
    baselines: Dict[str, Run] = {}
    for run in submitted:
        baseline = (
            Run.active(db)
            .filter(
                Run.project_id == project.id,
                Run.task == run.task,
                Run.dataset == run.dataset,
                Run.model == run.model,
                Run.status.in_(_FINISHED_STATUSES),
                Run.created_at < run.created_at,
            )
            .order_by(Run.created_at.desc())
            .first()
        )
        if baseline:
            baselines[run.id] = baseline

    unique_baselines = {baseline.id: baseline for baseline in baselines.values()}
    baseline_summaries = {
        summary.id: summary for summary in _summarize_runs(db, list(unique_baselines.values()))
    }

    entries: List[ReviewQueueEntry] = []
    for run, summary in zip(submitted, summaries):
        baseline = baselines.get(run.id)
        baseline_summary = baseline_summaries.get(baseline.id) if baseline else None
        delta: Dict[str, float] = {}
        if baseline_summary:
            shared = set(summary.metric_averages) & set(baseline_summary.metric_averages)
            delta = {
                metric_name: summary.metric_averages[metric_name] - baseline_summary.metric_averages[metric_name]
                for metric_name in sorted(shared)
            }
        entries.append(
            ReviewQueueEntry(
                run=summary,
                baseline_run_id=baseline.id if baseline else None,
                baseline_delta=delta,
            )
        )
    return ReviewQueueResponse(entries=entries, total=len(entries))
