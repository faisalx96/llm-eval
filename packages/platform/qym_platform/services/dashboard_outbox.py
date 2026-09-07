"""Capture source changes transactionally as bounded numeric snapshots."""

from __future__ import annotations

import hashlib
import math
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import case, event, insert, or_, select
from sqlalchemy.orm import Session

_installed = False
NUMERIC_FIELDS = (
    "observed",
    "terminal",
    "success",
    "error",
    "retry_count",
    "latency_ms",
    "score",
    "started_at_ms",
    "is_last",
)


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def _causes(value: Any, *, pass_score=False):
    from qym_platform.services.root_cause_categories import analysis_root_causes

    if not isinstance(value, dict):
        return []
    if pass_score:
        values = analysis_root_causes(value.get("root_cause_analysis") or {})
    else:
        # Preserve the existing runs-list distinct-cause rules exactly.
        values = {str(value.get("root_cause") or "").strip()}
        analyses = value.get("metric_analyses")
        for entry in (analyses.values() if isinstance(analyses, dict) else []):
            if isinstance(entry, dict):
                values.add(str(entry.get("root_cause") or "").strip())
    return sorted({hashlib.sha256(v.encode("utf-8")).hexdigest() for v in values if v})


def snapshot(obj, deleted=False):
    from qym_platform.db.models import (
        Run,
        RunItem,
        RunItemAttempt,
        RunItemPassScore,
        RunItemScore,
    )

    run_id = obj.id if isinstance(obj, Run) else obj.run_id
    data = {
        "partition_key": run_id,
        "record_key": run_id + ":run",
        "metric_key": "",
        "pass_number": 0,
        "record_kind": "run",
        "operation": "DELETE" if deleted else "UPSERT",
        "observed": 0,
        "terminal": 0,
        "success": 0,
        "error": 0,
        "retry_count": 0,
        "latency_ms": None,
        "score": None,
        "started_at_ms": None,
        "is_last": False,
    }
    causes = []
    if isinstance(obj, Run):
        data["project_key"] = obj.project_id
        if obj.deleted_at is not None:
            data["operation"] = "DELETE"
    elif isinstance(obj, (RunItem, RunItemScore, RunItemPassScore, RunItemAttempt)):
        data["record_key"] = run_id + ":" + obj.item_id
        if isinstance(obj, RunItem):
            data["_item_pk"] = obj.id
            data.update(
                record_kind="item",
                observed=1,
                error=int(obj.error is not None),
                terminal=int(obj.output is not None or obj.error is not None),
                success=int(obj.error is None),
                retry_count=int(obj.retry_count or 0),
                latency_ms=_number(obj.latency_ms),
            )
            causes = _causes(obj.item_metadata)
        elif isinstance(obj, RunItemAttempt):
            data.update(
                record_kind="attempt",
                metric_key=str(obj.attempt_number),
                pass_number=int(obj.pass_number),
                observed=1,
                error=int(str(obj.status or "").lower() == "failed"),
                terminal=int(bool(obj.is_last_attempt)),
                is_last=bool(obj.is_last_attempt),
                latency_ms=_number(obj.latency_ms),
                started_at_ms=_number(obj.task_started_at_ms),
            )
        else:
            data.update(
                record_kind=(
                    "pass_score" if isinstance(obj, RunItemPassScore) else "score"
                ),
                metric_key=obj.metric_name,
                score=_number(obj.score_numeric),
            )
            if isinstance(obj, RunItemPassScore):
                data["pass_number"] = int(obj.pass_number)
                causes = _causes(obj.meta, pass_score=True)
    if data["record_kind"] == "run" and not isinstance(obj, Run):
        data["operation"] = "UPSERT"
    return data, ([] if deleted else causes)


def _upsert_partition(connection, run_id, project_id, version, now, *, fresh=False):
    from qym_platform.db.dashboard_models import DashboardPartitionState
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    table = DashboardPartitionState.__table__
    factory = pg_insert if connection.dialect.name == "postgresql" else sqlite_insert
    statement = factory(table).values(
        partition_key=run_id,
        project_key=project_id,
        last_enqueued_version=version,
        last_applied_version=0,
        oldest_pending_event=now,
        queue_state="pending",
        backfill_complete=fresh,
        backfill_kind="item",
        backfill_cursor=0,
        retry_count=0,
        updated_at=now,
    )
    connection.execute(
        statement.on_conflict_do_update(
            index_elements=[table.c.partition_key],
            set_={
                "last_enqueued_version": case(
                    (table.c.last_enqueued_version < version, version),
                    else_=table.c.last_enqueued_version,
                ),
                "oldest_pending_event": case(
                    (table.c.oldest_pending_event.is_(None), now),
                    else_=table.c.oldest_pending_event,
                ),
                "queue_state": case(
                    (table.c.queue_state == "repair_required", "repair_required"),
                    else_="pending",
                ),
                "updated_at": now,
            },
        )
    )


def enqueue_snapshots(connection, snapshots, *, fresh_runs=()):
    from qym_platform.db.dashboard_models import (
        DashboardChangeEvent,
        DashboardEventCause,
    )
    from qym_platform.db.models import Run, RunItem

    if not snapshots:
        return
    run_ids = {
        data["partition_key"] for data, _ in snapshots if not data.get("project_key")
    }
    projects = (
        dict(
            connection.execute(
                select(Run.id, Run.project_id).where(Run.id.in_(run_ids))
            ).all()
        )
        if run_ids
        else {}
    )
    item_ids = [
        data["_item_pk"] for data, _ in snapshots if data.get("_item_pk") is not None
    ]
    # SQL JSON null and SQL NULL have different completion semantics in the
    # legacy endpoint. Read only the scalar predicate after the source flush.
    terminal = (
        dict(
            connection.execute(
                select(
                    RunItem.id,
                    or_(RunItem.output.isnot(None), RunItem.error.isnot(None)),
                ).where(RunItem.id.in_(item_ids))
            ).all()
        )
        if item_ids
        else {}
    )
    now = datetime.utcnow()
    rows, cause_lists = [], []
    for data, causes in snapshots:
        data = {
            "metric_key": "",
            "pass_number": 0,
            "operation": "UPSERT",
            **dict.fromkeys(
                ("observed", "terminal", "success", "error", "retry_count"), 0
            ),
            "latency_ms": None,
            "score": None,
            "started_at_ms": None,
            "is_last": False,
            **data,
        }
        item_pk = data.pop("_item_pk", None)
        if item_pk in terminal:
            data["terminal"] = int(terminal[item_pk])
        project = data.get("project_key") or projects.get(data["partition_key"])
        if not project:
            continue
        data.update(project_key=project, created_at=now, event_id=str(uuid4()))
        rows.append(data)
        cause_lists.append(causes)
    if not rows:
        return
    versions_by_id = dict(
        connection.execute(
            insert(DashboardChangeEvent).returning(
                DashboardChangeEvent.event_id, DashboardChangeEvent.source_version
            ),
            rows,
        ).all()
    )
    versions = [versions_by_id[row["event_id"]] for row in rows]
    cause_rows = [
        {"source_version": version, "cause_key": key}
        for version, keys in zip(versions, cause_lists)
        for key in keys
    ]
    if cause_rows:
        connection.execute(insert(DashboardEventCause), cause_rows)
    latest = {}
    for row, version in zip(rows, versions):
        prior = latest.get(row["partition_key"])
        if prior is None or version > prior[1]:
            latest[row["partition_key"]] = (row["project_key"], version)
    for run_id, (project, version) in sorted(latest.items()):
        _upsert_partition(
            connection, run_id, project, version, now, fresh=run_id in fresh_runs
        )


def _source_types():
    from qym_platform.db.models import (
        Approval,
        Run,
        RunItem,
        RunItemAttempt,
        RunItemPassScore,
        RunItemScore,
        RunMetricSpec,
    )

    return (
        Run,
        RunItem,
        RunItemScore,
        RunItemPassScore,
        RunItemAttempt,
        RunMetricSpec,
        Approval,
    )


def _before_flush(session, flush_context, instances):
    if session.info.get("dashboard_projection_worker"):
        return
    source = _source_types()
    pending = []
    # Session.new/deleted build IdentitySets on each access. Cache them once;
    # membership checks inside a large flush must stay linear overall.
    new, deleted = session.new, session.deleted
    changed = new.union(session.dirty).union(deleted)
    for obj in changed:
        if isinstance(obj, source) and (
            obj in new
            or obj in deleted
            or session.is_modified(obj, include_collections=False)
        ):
            pending.append((obj, obj in deleted, obj in new))
    session.info["dashboard_source_changes"] = pending
    from qym_platform.db.models import DatasetAlias, DatasetVersion, User
    from sqlalchemy import inspect

    users, versions = set(), set()
    for obj in changed:
        if (
            obj not in new
            and obj not in deleted
            and not session.is_modified(obj, include_collections=False)
        ):
            continue
        if isinstance(obj, User) and obj not in new:
            users.add(obj.id)
        elif isinstance(obj, DatasetVersion):
            versions.add(obj.id)
        elif isinstance(obj, DatasetAlias):
            versions.add(obj.dataset_version_id)
            versions.update(inspect(obj).attrs.dataset_version_id.history.deleted)
    session.info["dashboard_dimension_changes"] = (users, versions)


def _after_flush(session, flush_context):
    if session.info.get("dashboard_projection_worker"):
        return
    from qym_platform.db.models import Approval, Run

    pending = session.info.pop("dashboard_source_changes", [])
    users, versions = session.info.pop("dashboard_dimension_changes", (set(), set()))
    dimensions = []
    if users or versions:
        query = select(Run.id, Run.project_id).where(
            or_(
                Run.owner_user_id.in_(users),
                Run.id.in_(
                    select(Approval.run_id).where(
                        Approval.decision_by_user_id.in_(users)
                    )
                ),
                Run.dataset_version_id.in_(versions),
            )
        )
        dimensions = [
            (
                dict(
                    partition_key=run_id,
                    project_key=project,
                    record_key=run_id + ":run",
                    record_kind="run",
                    operation="UPSERT",
                ),
                [],
            )
            for run_id, project in session.connection().execute(query)
        ]
    if pending or dimensions:
        enqueue_snapshots(
            session.connection(),
            [snapshot(obj, deleted) for obj, deleted, _ in pending] + dimensions,
            fresh_runs={
                obj.id for obj, _, fresh in pending if fresh and isinstance(obj, Run)
            },
        )


def _bulk_source_mutation(state):
    if not (state.is_update or state.is_delete) or state.session.info.get(
        "dashboard_projection_worker"
    ):
        return
    mapper = state.bind_mapper
    if mapper is None or mapper.class_ not in _source_types():
        return
    model = mapper.class_
    statement = state.statement
    where = statement.whereclause
    query = select(model)
    if where is not None:
        query = query.where(where)
    objects = list(state.session.scalars(query.with_for_update()))
    if not objects:
        return
    snapshots = [snapshot(obj, True) for obj in objects]
    ids = [obj.id for obj in objects]
    result = state.invoke_statement()
    if state.is_update:
        state.session.expire_all()
        snapshots = [
            snapshot(obj)
            for obj in state.session.scalars(select(model).where(model.id.in_(ids)))
        ]
    enqueue_snapshots(state.session.connection(), snapshots)
    return result


def install_dashboard_outbox_hooks():
    global _installed
    if _installed:
        return
    event.listen(Session, "before_flush", _before_flush)
    event.listen(Session, "after_flush_postexec", _after_flush)
    event.listen(Session, "do_orm_execute", _bulk_source_mutation, retval=True)
    _installed = True
