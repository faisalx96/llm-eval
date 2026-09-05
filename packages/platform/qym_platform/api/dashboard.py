"""Authorized, bounded dashboard reads over durable numeric projections."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import and_, case, false, func, or_, select
from sqlalchemy.orm import Session

from qym_platform.auth import Principal, require_ui_principal
from qym_platform.db.dashboard_models import (
    DashboardRunDimension as Dimension,
    DashboardRunSummary as Summary,
)
from qym_platform.db.models import Project, ProjectMembership, UserRole
from qym_platform.deps import get_db
from qym_platform.permissions import has_project_access
from qym_platform.settings import PlatformSettings

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
_FILTER_COLUMNS = {
    "tasks": Dimension.task,
    "models": Dimension.model,
    "datasets": Dimension.dataset,
    "statuses": Dimension.status,
    "versions": Dimension.version,
    "users": Dimension.owner,
}


def _parse_filters(raw: Optional[str]) -> dict:
    try:
        value = json.loads(raw or "{}")
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid dashboard filters") from None
    if not isinstance(value, dict) or set(value) - (
        set(_FILTER_COLUMNS) | {"since", "until"}
    ):
        raise HTTPException(400, "Invalid dashboard filters")
    for key in _FILTER_COLUMNS:
        values = value.get(key, [])
        if (
            not isinstance(values, list)
            or len(values) > 1000
            or any(not isinstance(item, str) or len(item) > 1000 for item in values)
        ):
            raise HTTPException(400, f"Invalid {key} filter")
    for key in ("since", "until"):
        if value.get(key) is not None:
            try:
                parsed = datetime.fromisoformat(value[key].replace("Z", "+00:00"))
                value[key] = (
                    parsed.astimezone(timezone.utc).replace(tzinfo=None)
                    if parsed.tzinfo
                    else parsed
                )
            except (ValueError, TypeError, AttributeError):
                raise HTTPException(400, f"Invalid {key} timestamp") from None
    return value


def _project(db, principal, slug):
    query = select(Project).where(Project.is_active.is_(True))
    if slug:
        project = db.scalar(query.where(Project.slug == slug))
        if project is None:
            raise HTTPException(404, "Project not found")
        if not has_project_access(db, principal, project.id):
            raise HTTPException(403, "Access denied")
    else:
        if principal.auth_type != "none" and principal.user.role != UserRole.ADMIN:
            query = query.join(
                ProjectMembership, ProjectMembership.project_id == Project.id
            ).where(ProjectMembership.user_id == principal.user.id)
        project = db.scalar(query.order_by(Project.name, Project.id).limit(1))
    if project is None:
        return None
    from qym_platform.api.projects import _project_payload

    role = (
        "MANAGER"
        if principal.auth_type == "none" or principal.user.role == UserRole.ADMIN
        else db.scalar(
            select(ProjectMembership.role).where(
                ProjectMembership.project_id == project.id,
                ProjectMembership.user_id == principal.user.id,
            )
        )
    )
    return _project_payload(
        db,
        project,
        principal,
        run_counts={project.id: 0},
        role=getattr(role, "value", role) or "",
    )


def _snapshot_project(db, project):
    if project is not None:
        project["run_count"] = (
            db.scalar(
                select(func.count())
                .select_from(Dimension)
                .where(
                    Dimension.project_key == project["id"], Dimension.present.is_(True)
                )
            )
            or 0
        )
    return project


@contextmanager
def _read_snapshot(auth_db):
    """Release auth checkout before owning one repeatable-read connection."""
    bind = auth_db.get_bind()
    auth_db.close()
    with bind.connect() as connection:
        if connection.dialect.name == "postgresql":
            connection = connection.execution_options(isolation_level="REPEATABLE READ")
        elif connection.dialect.name == "sqlite":
            # sqlite3's legacy mode otherwise does not start a transaction for SELECT.
            connection.exec_driver_sql("BEGIN")
        with Session(bind=connection, autoflush=False) as db:
            yield db


def _base_conditions(project):
    conditions = [
        Dimension.project_key == project["id"] if project else false(),
        Dimension.present.is_(True),
    ]
    hidden = [
        task.strip().lower()
        for task in PlatformSettings().hidden_tasks.split(",")
        if task.strip()
    ]
    if hidden:
        conditions.append(~func.lower(Dimension.task).in_(hidden))
    return conditions


def _filter_conditions(filters, *, skip=None, facets=False):
    conditions = []
    for name, column in _FILTER_COLUMNS.items():
        values = filters.get(name, [])
        if name == skip or not values:
            continue
        if "__none__" in values:
            # Existing dropdowns ignore a select-none constraint in OTHER facets.
            if not facets:
                conditions.append(false())
            continue
        ordinary = [value for value in values if value != "__empty__"]
        terms = [column.in_(ordinary)] if ordinary else []
        if "__empty__" in values:
            terms.append(or_(column.is_(None), func.trim(column) == ""))
        conditions.append(or_(*terms))
    if filters.get("since") is not None:
        conditions.append(Dimension.timestamp >= filters["since"])
    if filters.get("until") is not None:
        conditions.append(Dimension.timestamp < filters["until"])
    return conditions


def _query(*columns):
    return (
        select(*(columns or (Dimension, Summary)))
        .select_from(Dimension)
        .join(Summary, Summary.run_key == Dimension.run_key)
    )


def _ordered_query(conditions):
    # First-seen groups are established before dropdown/time filtering in the UI.
    raw_model = Dimension.descriptor["model_name"].as_string()
    task_first = (
        select(
            Dimension.task.label("task"), func.max(Dimension.created_at).label("first")
        )
        .where(conditions[0], Dimension.present.is_(True))
        .group_by(Dimension.task)
        .subquery()
    )
    model_first = (
        select(
            Dimension.task.label("task"),
            raw_model.label("model"),
            func.max(Dimension.created_at).label("first"),
        )
        .where(conditions[0], Dimension.present.is_(True))
        .group_by(Dimension.task, raw_model)
        .subquery()
    )
    query = (
        _query()
        .join(task_first, task_first.c.task == Dimension.task)
        .join(
            model_first,
            and_(
                model_first.c.task == Dimension.task, model_first.c.model == raw_model
            ),
        )
        .where(*conditions)
    )
    order = [
        task_first.c.first.desc(),
        Dimension.task,
        model_first.c.first.desc(),
        raw_model,
        Dimension.created_at.desc(),
        Dimension.run_key,
    ]
    return query, order


def _sort_columns():
    success = func.coalesce(Summary.data["success_count"].as_float(), 0)
    errors = func.coalesce(Summary.data["error_count"].as_float(), 0)
    return {
        "time": Dimension.timestamp,
        "created": Dimension.created_at,
        "activity": Dimension.descriptor["_activity_sort_at"].as_string(),
        "date": Dimension.timestamp,
        "success": case((success + errors > 0, success / (success + errors)), else_=-1),
        "items": func.coalesce(Summary.data["total_items"].as_float(), 0),
        "task": Dimension.task,
        "model": Dimension.model,
        "dataset": Dimension.descriptor["dataset_name"].as_string(),
        "version": func.coalesce(Dimension.descriptor["git_commit"].as_string(), ""),
        "owner": func.coalesce(
            Dimension.descriptor["owner"]["display_name"].as_string(), ""
        ),
        "status": errors,
        "run": Dimension.run_key,
        "latency": Summary.avg_latency_ms,
        "median-latency": Summary.median_latency_ms,
        "duration": func.coalesce(Summary.data["duration_ms"].as_float(), 0),
    }


def _parse_collation(raw):
    try:
        values = json.loads(raw) if raw else []
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid collation order") from None
    if (
        not isinstance(values, list)
        or len(values) > 10000
        or any(not isinstance(value, str) or len(value) > 1000 for value in values)
    ):
        raise HTTPException(400, "Invalid collation order")
    return list(dict.fromkeys(values))


def _sort(key, collation=None):
    field, _, direction = key.rpartition("-")
    if direction not in ("asc", "desc"):
        raise HTTPException(400, "Invalid dashboard sort")
    column = _sort_columns().get(field)
    if column is None and field.startswith("metric-") and len(field) > 7:
        column = func.coalesce(
            Summary.data["metric_averages"][field[7:]].as_float(), -1
        )
    if (
        column is None
        and field.startswith("trace-")
        and field[6:]
        in {"avg_tokens", "avg_llm_calls", "avg_tool_calls", "tool_success_rate"}
    ):
        column = func.coalesce(
            Dimension.descriptor["trace_stats"][field[6:]].as_float(), -1
        )
    if column is None:
        raise HTTPException(400, "Invalid dashboard sort")
    if collation and field in {"task", "model", "dataset", "version", "owner"}:
        column = case(
            {value: index for index, value in enumerate(collation)},
            value=column,
            else_=len(collation),
        )
    return [
        column.desc() if direction == "desc" else column.asc(),
        *([Dimension.created_at.desc()] if field == "activity" else []),
    ]


def _row(dimension, summary):
    return {
        **(dimension.descriptor or {}),
        **(summary.data or {}),
        "_revision": summary.projection_revision,
        "model_key": dimension.model,
    }


def _tasks(rows):
    tasks = {}
    for row in rows:
        tasks.setdefault(row["task_name"], {}).setdefault(
            row.get("model_name") or "nomodel", []
        ).append(row)
    return tasks


def _stream(db, conditions, sort=None, collation=None):
    query, order = _ordered_query(conditions)
    query = query.order_by(*(_sort(sort, collation) if sort else []), *order)
    for dimension, summary in db.execute(query.execution_options(yield_per=200)):
        yield _row(dimension, summary)


def _freshness(db, project):
    from qym_platform.services.dashboard_summaries import dashboard_freshness

    return dashboard_freshness(db, [project["id"]] if project else [])


def _facets(db, base, filters):
    result = {}
    for name, column in _FILTER_COLUMNS.items():
        values = db.scalars(
            _query(column)
            .where(*base, *_filter_conditions(filters, skip=name, facets=True))
            .distinct()
        )
        normalized = {
            str(value) if value is not None and str(value).strip() else "__empty__"
            for value in values
        }
        result[name] = sorted(normalized - {"__empty__"}, key=str.casefold) + (
            ["__empty__"] if "__empty__" in normalized else []
        )
    return result


def _overview(db, project, filters, sort="time-desc", collation=None):
    from qym_platform.services.dashboard_views import build_overview_data

    base = _base_conditions(project)
    filtered = base + _filter_conditions(filters)
    result = build_overview_data(
        _stream(db, base), _stream(db, filtered, sort, collation)
    )
    result.update(
        total_count=db.scalar(_query(func.count()).where(*base)) or 0,
        total_runs=db.scalar(_query(func.count()).where(*filtered)) or 0,
        facets=_facets(db, base, filters),
        project=project,
    )
    owners = db.execute(
        _query(
            Dimension.owner,
            Dimension.descriptor["owner"]["email"].as_string(),
            Dimension.descriptor["owner"]["display_name"].as_string(),
        )
        .where(*base)
        .distinct()
    )
    result["owners"] = {
        owner: {"id": owner, "email": email, "display_name": name}
        for owner, email, name in owners
        if owner and email
    }
    result["all_models"] = sorted(
        db.scalars(_query(Dimension.model).where(*base).distinct()), key=str.casefold
    )
    columns = _sort_columns()
    result["sort_values"] = {
        name: list(db.scalars(_query(columns[field]).where(*filtered).distinct()))
        for name, field in (
            ("tasks", "task"),
            ("models", "model"),
            ("dataset_names", "dataset"),
            ("git_commits", "version"),
            ("owner_names", "owner"),
        )
    }
    result.update(_freshness(db, project))
    return result


def _neighbors(db, conditions, rows):
    """Read adjacent distinct means for page values without fetching history."""
    groups = {
        (row["task_name"], row["model_key"], row.get("dataset_name") or "")
        for row in rows
    }
    metrics = {metric for row in rows for metric in (row.get("metric_averages") or {})}
    raw_model = Dimension.model
    dataset = Dimension.descriptor["dataset_name"].as_string()
    for row in rows:
        row["metric_neighbor_values"] = {}
    for metric in metrics:
        value = Summary.data["metric_averages"][metric].as_float()
        grouped = (
            _query(
                Dimension.task.label("task"),
                raw_model.label("model"),
                dataset.label("dataset"),
                value.label("value"),
            )
            .where(
                *conditions,
                value.isnot(None),
                or_(
                    *(
                        and_(
                            Dimension.task == task, raw_model == model, dataset == data
                        )
                        for task, model, data in groups
                    )
                ),
            )
            .distinct()
            .cte()
        )
        adjacent = select(
            grouped,
            func.lag(grouped.c.value)
            .over(
                partition_by=(grouped.c.task, grouped.c.model, grouped.c.dataset),
                order_by=grouped.c.value,
            )
            .label("lower"),
            func.lead(grouped.c.value)
            .over(
                partition_by=(grouped.c.task, grouped.c.model, grouped.c.dataset),
                order_by=grouped.c.value,
            )
            .label("upper"),
        ).cte()
        requested = [
            and_(
                adjacent.c.task == row["task_name"],
                adjacent.c.model == (row["model_key"]),
                adjacent.c.dataset == (row.get("dataset_name") or ""),
                adjacent.c.value == row["metric_averages"][metric],
            )
            for row in rows
            if row.get("metric_averages", {}).get(metric) is not None
        ]
        if not requested:
            continue
        lookup = {
            (task, model, dataset, value): [lower, upper]
            for task, model, dataset, value, lower, upper in db.execute(
                select(adjacent).where(or_(*requested))
            )
        }
        for row in rows:
            key = (
                row["task_name"],
                row["model_key"],
                row.get("dataset_name") or "",
                row.get("metric_averages", {}).get(metric),
            )
            if key in lookup:
                row["metric_neighbor_values"][metric] = lookup[key]


def _requested_ids(raw):
    try:
        ids = json.loads(raw or "[]")
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid run ids") from None
    if (
        not isinstance(ids, list)
        or len(ids) > 100
        or any(
            not isinstance(value, str) or not value or len(value) > 128 for value in ids
        )
    ):
        raise HTTPException(400, "Run ids must contain at most 100 identifiers")
    return list(dict.fromkeys(ids))


def _config_groups(db, conditions):
    key = Dimension.descriptor["config_group_key"].as_string()
    ranked = (
        _query(
            key.label("key"),
            Dimension.descriptor["run_name"].as_string().label("label"),
            func.count().over(partition_by=key).label("total_runs"),
            func.row_number()
            .over(
                partition_by=key,
                order_by=(
                    Dimension.timestamp.desc(),
                    Dimension.created_at.desc(),
                    Dimension.run_key,
                ),
            )
            .label("rank"),
        )
        .where(*conditions)
        .subquery()
    )
    return [
        {
            "key": row.key or "__ungrouped__",
            "label": row.label or "Unnamed run",
            "total_runs": row.total_runs,
        }
        for row in db.execute(
            select(ranked)
            .where(ranked.c.rank == 1)
            .order_by(ranked.c.total_runs.desc(), ranked.c.key)
        )
    ]


def _page(
    db,
    project,
    filters,
    *,
    limit,
    offset,
    sort,
    ids=None,
    task=None,
    dataset=None,
    include_config_groups=False,
    include_neighbors=True,
    collation=None,
):
    base = _base_conditions(project)
    filtered = base + _filter_conditions(filters)
    if task is not None:
        filtered.append(Dimension.task == task)
    if dataset is not None:
        filtered.append(Dimension.descriptor["dataset_name"].as_string() == dataset)
    total = db.scalar(_query(func.count()).where(*filtered)) or 0
    query, legacy_order = _ordered_query(filtered)
    rows = [
        _row(dimension, summary)
        for dimension, summary in db.execute(
            query.order_by(*_sort(sort, collation), *legacy_order)
            .offset(offset)
            .limit(limit)
        )
    ]
    if include_neighbors:
        _neighbors(db, filtered, rows)
    pinned = []
    if ids:
        lookup = {
            dimension.run_key: _row(dimension, summary)
            for dimension, summary in db.execute(
                _query().where(*base, Dimension.run_key.in_(ids))
            )
        }
        pinned = [lookup[run_id] for run_id in ids if run_id in lookup]
    result = {
        "tasks": _tasks(rows),
        "rows": rows,
        "pinned_rows": pinned,
        "total_runs": total,
        "total_count": db.scalar(_query(func.count()).where(*base)) or 0,
        "has_more": offset + len(rows) < total,
        "offset": offset,
        "limit": limit,
        "project": project,
    }
    if include_config_groups:
        result["config_groups"] = _config_groups(db, filtered)
    result.update(_freshness(db, project))
    return result


@router.get("/runs")
def dashboard_runs(
    project_slug: Optional[str] = None,
    filters: Optional[str] = None,
    sort: str = "time-desc",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    ids: Optional[str] = None,
    include_overview: bool = False,
    include_config_groups: bool = False,
    collation: Optional[str] = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
):
    project, parsed, requested = (
        _project(db, principal, project_slug),
        _parse_filters(filters),
        _requested_ids(ids),
    )
    with _read_snapshot(db) as reader:
        project = _snapshot_project(reader, project)
        result = _page(
            reader,
            project,
            parsed,
            limit=limit,
            offset=offset,
            sort=sort,
            ids=requested,
            include_config_groups=include_config_groups,
            collation=_parse_collation(collation),
        )
        if include_overview:
            result["overview"] = _overview(
                reader, project, parsed, sort, _parse_collation(collation)
            )
        return result


@router.get("/overview")
def dashboard_overview(
    project_slug: Optional[str] = None,
    filters: Optional[str] = None,
    sort: str = "time-desc",
    collation: Optional[str] = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
):
    project, parsed = _project(db, principal, project_slug), _parse_filters(filters)
    with _read_snapshot(db) as reader:
        project = _snapshot_project(reader, project)
        return _overview(reader, project, parsed, sort, _parse_collation(collation))


@router.get("/points")
def dashboard_points(
    project_slug: Optional[str] = None,
    filters: Optional[str] = None,
    sort: str = "time-desc",
    collation: Optional[str] = None,
    task: Optional[str] = None,
    dataset: Optional[str] = None,
    limit: int = Query(500, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
):
    project, parsed = _project(db, principal, project_slug), _parse_filters(filters)
    with _read_snapshot(db) as reader:
        project = _snapshot_project(reader, project)
        return _page(
            reader,
            project,
            parsed,
            limit=limit,
            offset=offset,
            sort=sort,
            collation=_parse_collation(collation),
            task=task,
            dataset=dataset,
            include_neighbors=False,
        )


@router.get("/models")
def dashboard_models(
    project_slug: Optional[str] = None,
    filters: Optional[str] = None,
    k: int = Query(5, ge=1, le=100),
    selected: Optional[str] = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
):
    project, parsed = _project(db, principal, project_slug), _parse_filters(filters)
    try:
        selections = json.loads(selected or "{}")
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid model selection") from None
    if not isinstance(selections, dict) or any(
        not isinstance(model, str) or not isinstance(ids, list)
        for model, ids in selections.items()
    ):
        raise HTTPException(400, "Invalid model selection")
    if len(selections) > 100:
        raise HTTPException(400, "At most 100 model selections are supported")
    selections = {
        model: _requested_ids(json.dumps(values))
        for model, values in selections.items()
    }
    with _read_snapshot(db) as reader:
        project = _snapshot_project(reader, project)
        conditions = _base_conditions(project) + _filter_conditions(parsed)
        scope = {
            name: sorted(
                reader.scalars(_query(column).where(*conditions).distinct()),
                key=str.casefold,
            )
            for name, column in (
                ("tasks", Dimension.task),
                ("datasets", Dimension.dataset),
            )
        }
        counts = dict(
            reader.execute(
                _query(Dimension.model, func.count())
                .where(*conditions)
                .group_by(Dimension.model)
            ).all()
        )
        ranked = (
            _query(
                Dimension.run_key.label("id"),
                Dimension.model.label("model"),
                func.row_number()
                .over(
                    partition_by=Dimension.model,
                    order_by=(
                        Dimension.timestamp.desc(),
                        Dimension.created_at.desc(),
                        Dimension.run_key,
                    ),
                )
                .label("rank"),
            )
            .where(*conditions)
            .subquery()
        )
        chosen = select(ranked.c.id).where(
            or_(
                ranked.c.rank <= k,
                *(
                    and_(ranked.c.model == model, ranked.c.id.in_(values))
                    for model, values in selections.items()
                ),
            )
        )
        rows = reader.execute(
            _query()
            .where(*conditions, Dimension.run_key.in_(chosen))
            .order_by(
                Dimension.timestamp.desc(),
                Dimension.created_at.desc(),
                Dimension.run_key,
            )
        )
        models = {
            model: {"model_key": model, "total_runs": count, "rows": []}
            for model, count in counts.items()
        }
        for dimension, summary in rows:
            models[dimension.model]["rows"].append(_row(dimension, summary))
        metric_summary = {}
        filtered_hash = hashlib.sha256()
        for run_key, revision, averages, metrics in reader.execute(
            _query(
                Dimension.run_key,
                Summary.projection_revision,
                Summary.data["metric_averages"],
                Dimension.descriptor["metrics"],
            )
            .where(*conditions)
            .order_by(Dimension.run_key)
            .execution_options(yield_per=200)
        ):
            filtered_hash.update(
                json.dumps([run_key, revision], separators=(",", ":")).encode()
            )
            for metric in metrics or []:
                metric_summary.setdefault(
                    metric, {"is_boolean": True, "is_numeric": False}
                )
            for metric, value in (averages or {}).items():
                info = metric_summary.setdefault(
                    metric, {"is_boolean": True, "is_numeric": False}
                )
                if value is None:
                    continue
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    continue
                if number < 0 or number > 1:
                    info["is_numeric"], info["is_boolean"] = True, False
                elif abs(number) > 0.0001 and abs(number - 1) > 0.0001:
                    info["is_boolean"] = False
        result = {
            "models": list(models.values()),
            "filtered_revision": filtered_hash.hexdigest(),
            "selected_revision": hashlib.sha256(
                json.dumps(
                    sorted(
                        (row["run_id"], row["_revision"])
                        for model in models.values()
                        for row in model["rows"]
                    ),
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
            "scope": scope,
            "metrics": sorted(metric_summary),
            "metric_summary": metric_summary,
            "project": project,
        }
        result.update(_freshness(reader, project))
        return result


@router.post("/models")
def dashboard_models_selection(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
):
    if set(payload) - {"project_slug", "filters", "k", "selected"}:
        raise HTTPException(400, "Invalid model selection request")
    k = payload.get("k", 5)
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 100:
        raise HTTPException(400, "k must be between 1 and 100")
    slug = payload.get("project_slug")
    if slug is not None and not isinstance(slug, str):
        raise HTTPException(400, "Invalid project slug")
    return dashboard_models(
        project_slug=slug,
        filters=json.dumps(payload.get("filters", {})),
        k=k,
        selected=json.dumps(payload.get("selected", {})),
        db=db,
        principal=principal,
    )


def _body_parameters(payload, allowed):
    if set(payload) - allowed:
        raise HTTPException(400, "Invalid dashboard query")
    slug = payload.get("project_slug")
    if slug is not None and (not isinstance(slug, str) or len(slug) > 400):
        raise HTTPException(400, "Invalid project slug")
    result = {"project_slug": slug, "filters": json.dumps(payload.get("filters", {}))}
    for key, default, minimum, maximum in (
        ("limit", 50, 1, 500),
        ("offset", 0, 0, None),
    ):
        if key in allowed:
            value = payload.get(key, default)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < minimum
                or maximum is not None
                and value > maximum
            ):
                raise HTTPException(400, f"Invalid {key}")
            result[key] = value
    if "sort" in allowed and "ids" not in allowed:
        if not isinstance(payload.get("sort", "time-desc"), str):
            raise HTTPException(400, "Invalid dashboard sort")
        result["sort"] = payload.get("sort", "time-desc")
        result["collation"] = json.dumps(payload.get("collation", []))
    return result


@router.post("/runs")
def dashboard_runs_query(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
):
    args = _body_parameters(
        payload,
        {
            "project_slug",
            "filters",
            "sort",
            "limit",
            "offset",
            "ids",
            "include_overview",
            "include_config_groups",
            "collation",
        },
    )
    for key in ("include_overview", "include_config_groups"):
        if key in payload and not isinstance(payload[key], bool):
            raise HTTPException(400, f"Invalid {key}")
        args[key] = payload.get(key, False)
    if not isinstance(payload.get("sort", "time-desc"), str):
        raise HTTPException(400, "Invalid dashboard sort")
    return dashboard_runs(
        **args,
        sort=payload.get("sort", "time-desc"),
        ids=json.dumps(payload.get("ids", [])),
        collation=json.dumps(payload.get("collation", [])),
        db=db,
        principal=principal,
    )


@router.post("/overview")
def dashboard_overview_query(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
):
    return dashboard_overview(
        **_body_parameters(payload, {"project_slug", "filters", "sort", "collation"}),
        db=db,
        principal=principal,
    )


@router.post("/points")
def dashboard_points_query(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
):
    args = _body_parameters(
        payload,
        {
            "project_slug",
            "filters",
            "task",
            "dataset",
            "limit",
            "offset",
            "sort",
            "collation",
        },
    )
    for key in ("task", "dataset"):
        value = payload.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > 1000):
            raise HTTPException(400, f"Invalid {key}")
        args[key] = value
    return dashboard_points(**args, db=db, principal=principal)
