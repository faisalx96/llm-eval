"""Incremental numeric dashboard projection, repair and resumable backfill."""

from __future__ import annotations

import bisect
import hashlib
import json
import logging
import math
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from qym_platform.db.dashboard_models import DashboardBucketRollup as Bucket
from qym_platform.db.dashboard_models import DashboardChangeEvent as Change
from qym_platform.db.dashboard_models import DashboardDeadLetter as DeadLetter
from qym_platform.db.dashboard_models import DashboardEventCause as EventCause
from qym_platform.db.dashboard_models import DashboardHistogram as Histogram
from qym_platform.db.dashboard_models import DashboardPartitionState as Partition
from qym_platform.db.dashboard_models import DashboardRecordCause as RecordCause
from qym_platform.db.dashboard_models import DashboardRecordState as Record
from qym_platform.db.dashboard_models import DashboardRunDimension as Dimension
from qym_platform.db.dashboard_models import DashboardRunSummary as Summary
from qym_platform.services.dashboard_outbox import (
    NUMERIC_FIELDS,
    _upsert_partition,
    enqueue_snapshots,
    snapshot,
)
from sqlalchemy import and_, case, delete, func, insert, or_, select, tuple_, update
from sqlalchemy.orm import Session, aliased

MAX_LATE_EVENT_AGE = timedelta(days=30)
MAX_EVENT_ATTEMPTS = 5
HISTOGRAM_VERSION = 1
LATENCY_EDGES = (0.0, 1.0, 10.0, 100.0, 1000.0, 10000.0, 60000.0)
SCORE_EDGES = tuple(i / 10 for i in range(11))


def _finite_positive(value):
    try:
        return float(value or 0) > 0
    except (TypeError, ValueError):
        return False


def _config_group_key(config):
    def normalize(value):
        if isinstance(value, float):
            return (
                int(value)
                if math.isfinite(value) and value.is_integer()
                else value if math.isfinite(value) else None
            )
        if isinstance(value, list):
            return [normalize(child) for child in value]
        if isinstance(value, dict):
            return {key: normalize(child) for key, child in value.items()}
        return value

    entries = sorted(
        (key, normalize(value))
        for key, value in config.items()
        if key not in {"run_name", "resume_from", "cli_invocation"}
    )
    if not entries:
        return None
    return hashlib.sha256(
        json.dumps(
            entries, separators=(",", ":"), ensure_ascii=False, default=str
        ).encode()
    ).hexdigest()


def _upsert_ignore(db, model, values, keys):
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    factory = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    db.execute(
        factory(model).values(**values).on_conflict_do_nothing(index_elements=keys)
    )


def _zero_numbers():
    return {
        name: 0
        for name in (
            "count",
            "terminal_count",
            "success_count",
            "error_count",
            "retry_sum",
            "latency_count",
            "latency_sum",
            "latency_sum_squares",
            "score_count",
            "score_sum",
            "score_sum_squares",
        )
    }


def _contribution(record, present=None):
    values = _zero_numbers()
    if record is None or not (record.present if present is None else present):
        return values
    if record.record_kind == "item":
        values.update(
            count=record.observed,
            terminal_count=record.terminal,
            success_count=record.success,
            error_count=record.error,
            retry_sum=record.retry_count,
        )
        if record.latency_ms is not None:
            values.update(
                latency_count=1,
                latency_sum=record.latency_ms,
                latency_sum_squares=record.latency_ms**2,
            )
    elif record.record_kind == "score" and record.score is not None:
        values.update(
            score_count=1, score_sum=record.score, score_sum_squares=record.score**2
        )
    return values


def _hour(value):
    value = value or datetime.utcnow()
    return int(value.replace(tzinfo=timezone.utc).timestamp()) // 3600 * 3600


def _bucket_keys(project, hour):
    return sorted(
        [(project, "all", hour, "hour"), (project, "all", hour // 86400 * 86400, "day")]
    )


def _lock_buckets(db, project, hours):
    """Take shared bucket locks in one order, including timestamp corrections."""
    for key in sorted({key for hour in hours for key in _bucket_keys(project, hour)}):
        identity = dict(
            zip(("project_key", "slice_key", "bucket_key", "granularity"), key)
        )
        _upsert_ignore(db, Bucket, identity, list(identity))
        db.scalar(
            select(Bucket)
            .where(*(getattr(Bucket, k) == v for k, v in identity.items()))
            .with_for_update()
        )


def _apply_numbers(db, model, identity, delta, version):
    batch = db.info.get("dashboard_numeric_batch")
    if batch is not None:
        key = (model, tuple(sorted(identity.items())))
        entry = batch["deltas"].setdefault(
            key, {"numbers": _zero_numbers(), "version": 0}
        )
        for name, value in delta.items():
            entry["numbers"][name] += value
        entry["version"] = max(entry["version"], version)
        return
    table = model.__table__
    filters = [getattr(model, key) == value for key, value in identity.items()]
    _upsert_ignore(db, model, identity, [column.name for column in table.primary_key])
    changes = {name: getattr(model, name) + value for name, value in delta.items()}
    changes.update(
        applied_source_version=case(
            (model.applied_source_version < version, version),
            else_=model.applied_source_version,
        ),
        updated_at=datetime.utcnow(),
    )
    db.execute(update(model).where(*filters).values(**changes))


def _histogram_delta(db, identity, kind, value, delta):
    if value is None or not delta:
        return
    edges = LATENCY_EDGES if kind == "latency" else SCORE_EDGES
    values = {
        **identity,
        "definition_version": HISTOGRAM_VERSION,
        "value_kind": kind,
        "bucket_index": bisect.bisect_right(edges, value) - 1,
    }
    batch = db.info.get("dashboard_numeric_batch")
    if batch is not None:
        batch["histograms"][tuple(sorted(values.items()))] += delta
        return
    _upsert_ignore(db, Histogram, values, list(values))
    db.execute(
        update(Histogram)
        .where(*(getattr(Histogram, k) == v for k, v in values.items()))
        .values(count=Histogram.count + delta)
    )


def _apply_bucket_record(db, record, contribution, sign, version):
    for project, slice_key, bucket_key, granularity in _bucket_keys(
        record.project_key, record.bucket_key
    ):
        identity = dict(
            project_key=project,
            slice_key=slice_key,
            bucket_key=bucket_key,
            granularity=granularity,
        )
        _apply_numbers(
            db,
            Bucket,
            identity,
            {key: sign * value for key, value in contribution.items()},
            version,
        )
        kind = (
            "latency"
            if record.record_kind == "item"
            else "score" if record.record_kind == "score" else None
        )
        if kind:
            value = record.latency_ms if kind == "latency" else record.score
            _histogram_delta(db, identity, kind, value, sign)
            if sign < 0 and value is not None:
                batch = db.info.get("dashboard_numeric_batch")
                if batch is not None:
                    batch["invalidated"][tuple(sorted(identity.items()))][kind].add(
                        value
                    )
                    continue
                lo, hi = getattr(Bucket, kind + "_min"), getattr(Bucket, kind + "_max")
                db.execute(
                    update(Bucket)
                    .where(
                        *(getattr(Bucket, k) == v for k, v in identity.items()),
                        or_(lo == value, hi == value),
                    )
                    .values(extrema_state="dirty_known", dirty_since_version=version)
                )


def apply_event(db: Session, event: Change, *, now=None):
    """Apply one versioned numeric snapshot transactionally; return whether new."""
    db.info["dashboard_projection_worker"] = True
    now = now or datetime.utcnow()
    if event.operation not in {"UPSERT", "DELETE"} or event.record_kind not in {
        "run",
        "item",
        "score",
        "pass_score",
        "attempt",
    }:
        raise ValueError("Unknown dashboard event operation or record kind")
    for name in ("latency_ms", "score", "started_at_ms"):
        value = getattr(event, name)
        if value is not None and not math.isfinite(value):
            raise ValueError("Non-finite dashboard event " + name)
    for name in ("observed", "terminal", "success", "error", "retry_count"):
        if getattr(event, name) < 0:
            raise ValueError("Negative dashboard event " + name)
    if event.created_at and event.created_at < now - MAX_LATE_EVENT_AGE:
        _upsert_ignore(
            db,
            DeadLetter,
            dict(
                event_id=event.event_id,
                project_key=event.project_key,
                partition_key=event.partition_key,
                source_version=event.source_version,
                error="Event exceeds MAX_LATE_EVENT_AGE; explicit backfill required",
            ),
            ["event_id"],
        )
        event.published_at = now
        partition = db.get(Partition, event.partition_key)
        if partition:
            partition.queue_state = "repair_required"
            partition.last_error = "Late event requires explicit backfill"
        return False
    identity = dict(
        project_key=event.project_key,
        record_key=event.record_key,
        metric_key=event.metric_key,
        record_kind=event.record_kind,
        pass_number=event.pass_number,
    )
    batch = db.info.get("dashboard_numeric_batch")
    record_identity = (
        event.record_key,
        event.metric_key,
        event.record_kind,
        event.pass_number,
    )
    record = (
        batch["records"].get(record_identity)
        if batch is not None
        else db.scalar(
            select(Record)
            .where(*(getattr(Record, k) == v for k, v in identity.items()))
            .with_for_update()
        )
    )
    if record and event.source_version <= record.applied_source_version:
        event.published_at = now
        return False
    dimension = (
        batch["dimension"]
        if batch is not None
        else db.get(Dimension, event.partition_key)
    )
    summary = (
        batch["summary"] if batch is not None else db.get(Summary, event.partition_key)
    )
    if not summary:
        _upsert_ignore(
            db,
            Summary,
            dict(run_key=event.partition_key, project_key=event.project_key),
            ["run_key"],
        )
    old = _contribution(record)
    visible = dimension is not None and dimension.present
    if record and record.present and visible:
        _apply_bucket_record(db, record, old, -1, event.source_version)
    if record is None:
        record = Record(
            **identity,
            run_key=event.partition_key,
            bucket_key=_hour(dimension.timestamp if dimension else None),
        )
        db.add(record)
        if batch is not None:
            batch["records"][record_identity] = record
    record.present = event.operation != "DELETE"
    for name in NUMERIC_FIELDS:
        setattr(record, name, getattr(event, name))
    record.applied_source_version = event.source_version
    record.updated_at = now
    new = _contribution(record)
    _apply_numbers(
        db,
        Summary,
        dict(run_key=event.partition_key, project_key=event.project_key),
        {key: new[key] - old[key] for key in new},
        event.source_version,
    )
    if record.present and visible:
        _apply_bucket_record(db, record, new, 1, event.source_version)
    if batch is not None:
        batch["causes"][record_identity] = (record, event.source_version)
    else:
        db.flush()
        db.execute(delete(RecordCause).where(RecordCause.record_state_id == record.id))
        if record.present:
            causes = list(
                db.scalars(
                    select(EventCause.cause_key).where(
                        EventCause.source_version == event.source_version
                    )
                )
            )
            if causes:
                db.execute(
                    insert(RecordCause),
                    [
                        dict(
                            record_state_id=record.id,
                            cause_key=key,
                            run_key=record.run_key,
                            pass_number=record.pass_number,
                        )
                        for key in causes
                    ],
                )
    event.published_at = now
    return True


def apply_events(db, events):
    """Batch the normal path while preserving the per-record version contract.

    Memory is bounded by the worker's event limit. Numeric deltas are accumulated
    within the same transaction, then sent as constant-size bucket updates and
    batched bookkeeping. Failed batches fall back to isolated event retries.
    """
    if not events:
        return
    run_id = events[0].partition_key
    if any(event.partition_key != run_id for event in events):
        raise ValueError("A dashboard batch must contain one partition")
    identities = {
        (event.record_key, event.metric_key, event.record_kind, event.pass_number)
        for event in events
    }
    records = list(
        db.scalars(
            select(Record)
            .where(
                Record.run_key == run_id,
                tuple_(
                    Record.record_key,
                    Record.metric_key,
                    Record.record_kind,
                    Record.pass_number,
                ).in_(identities),
            )
            .with_for_update()
        )
    )
    summary = db.get(Summary, run_id)
    if summary is None:
        _upsert_ignore(
            db,
            Summary,
            dict(run_key=run_id, project_key=events[0].project_key),
            ["run_key"],
        )
        summary = db.get(Summary, run_id)
    batch = {
        "records": {
            (row.record_key, row.metric_key, row.record_kind, row.pass_number): row
            for row in records
        },
        "summary": summary,
        "dimension": db.get(Dimension, run_id),
        "deltas": {},
        "histograms": defaultdict(int),
        "invalidated": defaultdict(lambda: defaultdict(set)),
        "causes": {},
    }
    db.info["dashboard_numeric_batch"] = batch
    try:
        with db.no_autoflush:
            for change in events:
                apply_event(db, change)
    finally:
        db.info.pop("dashboard_numeric_batch", None)
    # ORM-generated integer IDs force one INSERT per record on SQLite when an
    # ordered RETURNING is requested. Identity-bearing RETURNING lets both
    # databases insert the bounded record batch in one statement instead.
    new_records = [record for record in batch["records"].values() if record in db.new]
    if new_records:
        for record in new_records:
            db.expunge(record)
        columns = [
            column.name for column in Record.__table__.columns if column.name != "id"
        ]
        inserted = db.execute(
            insert(Record).returning(
                Record.id,
                Record.record_key,
                Record.metric_key,
                Record.record_kind,
                Record.pass_number,
            ),
            [
                {name: getattr(record, name) for name in columns}
                for record in new_records
            ],
        ).all()
        for ident, record_key, metric_key, kind, pass_number in inserted:
            batch["records"][(record_key, metric_key, kind, pass_number)].id = ident
    db.flush()
    _flush_numeric_batch(db, batch, max(event.source_version for event in events))
    affected = list(batch["causes"].values())
    if affected:
        db.execute(
            delete(RecordCause).where(
                RecordCause.record_state_id.in_([record.id for record, _ in affected])
            )
        )
        records_by_version = {
            version: record for record, version in affected if record.present
        }
        causes = list(
            db.execute(
                select(EventCause.source_version, EventCause.cause_key).where(
                    EventCause.source_version.in_(records_by_version)
                )
            )
        )
        if causes:
            db.execute(
                insert(RecordCause),
                [
                    dict(
                        record_state_id=records_by_version[version].id,
                        cause_key=key,
                        run_key=run_id,
                        pass_number=records_by_version[version].pass_number,
                    )
                    for version, key in causes
                ],
            )


def _flush_numeric_batch(db, batch, version):
    for (model, identity), value in batch["deltas"].items():
        _apply_numbers(db, model, dict(identity), value["numbers"], value["version"])
    for identity, delta in batch["histograms"].items():
        if delta:
            values = dict(identity)
            _upsert_ignore(db, Histogram, values, list(values))
            db.execute(
                update(Histogram)
                .where(*(getattr(Histogram, k) == v for k, v in values.items()))
                .values(count=Histogram.count + delta)
            )
    for identity, kinds in batch["invalidated"].items():
        invalid = []
        for kind, values in kinds.items():
            invalid.extend(
                (
                    getattr(Bucket, kind + "_min").in_(values),
                    getattr(Bucket, kind + "_max").in_(values),
                )
            )
        db.execute(
            update(Bucket)
            .where(*(getattr(Bucket, k) == v for k, v in identity), or_(*invalid))
            .values(extrema_state="dirty_known", dirty_since_version=version)
        )


def _move_numeric_records(
    db, run_id, project, old_visible, new_visible, new_hour, version, *, tombstone=False
):
    """Move visibility/time buckets with bounded numeric memory and SQL batches."""
    query = (
        select(Record)
        .where(Record.run_key == run_id, Record.present.is_(True))
        .order_by(Record.id)
    )
    cursor = 0
    while True:
        records = list(db.scalars(query.where(Record.id > cursor).limit(500)))
        if not records:
            break
        batch = {
            "deltas": {},
            "histograms": defaultdict(int),
            "invalidated": defaultdict(lambda: defaultdict(set)),
        }
        db.info["dashboard_numeric_batch"] = batch
        try:
            for record in records:
                contribution = _contribution(record)
                if old_visible:
                    _apply_bucket_record(db, record, contribution, -1, version)
                if new_hour is not None:
                    record.bucket_key = new_hour
                if new_visible:
                    _apply_bucket_record(db, record, contribution, 1, version)
                if tombstone:
                    _apply_numbers(
                        db,
                        Summary,
                        dict(run_key=run_id, project_key=project),
                        {key: -value for key, value in contribution.items()},
                        version,
                    )
                    record.present = False
                    record.applied_source_version = max(
                        record.applied_source_version, version
                    )
        finally:
            db.info.pop("dashboard_numeric_batch", None)
        db.flush()
        _flush_numeric_batch(db, batch, version)
        if tombstone:
            db.execute(
                delete(RecordCause).where(
                    RecordCause.record_state_id.in_([record.id for record in records])
                )
            )
        cursor = records[-1].id


def _median(db, query, column):
    count = (
        db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
        or 0
    )
    if not count:
        return 0.0
    values = list(
        db.scalars(
            query.order_by(column)
            .offset((count - 1) // 2)
            .limit(2 if count % 2 == 0 else 1)
        )
    )
    return sum(values) / len(values)


def repair_extrema(db, project_key, bucket_key, granularity="hour"):
    """Repair only one dirty numeric bucket, never source payload history."""
    bucket = db.get(
        Bucket, (project_key, "all", bucket_key, granularity), with_for_update=True
    )
    if bucket is None:
        return
    bucket.extrema_state = "rebuilding"
    width = 3600 if granularity == "hour" else 86400
    base = (
        select(Record)
        .join(Dimension, Dimension.run_key == Record.run_key)
        .where(
            Record.project_key == project_key,
            Record.bucket_key >= bucket_key,
            Record.bucket_key < bucket_key + width,
            Record.present.is_(True),
            Dimension.present.is_(True),
        )
    )
    for kind, record_kind, column in (
        ("latency", "item", Record.latency_ms),
        ("score", "score", Record.score),
    ):
        values = base.with_only_columns(column).where(
            Record.record_kind == record_kind, column.isnot(None)
        )
        setattr(
            bucket, kind + "_min", db.scalar(values.order_by(column.asc()).limit(1))
        )
        setattr(
            bucket, kind + "_max", db.scalar(values.order_by(column.desc()).limit(1))
        )
    bucket.extrema_state = "valid"
    bucket.extrema_verified_version = bucket.applied_source_version
    bucket.dirty_since_version = None


def extrema_payload(bucket):
    valid = bucket.extrema_state == "valid"
    return {
        "state": bucket.extrema_state,
        "revision": bucket.extrema_verified_version,
        **{
            name: getattr(bucket, name) if valid else None
            for name in ("latency_min", "latency_max", "score_min", "score_max")
        },
    }


def _sync_dimension(db, run_id, version):
    from qym_platform.api.runs import (
        _dataset_version_fields,
        _dataset_version_info_map,
        _iso,
        _metric_specs_for_runs,
        _strip_model_provider,
    )
    from qym_platform.db.models import Approval, Run, User

    run = db.get(Run, run_id)
    dimension = db.get(Dimension, run_id)
    if not run:
        if dimension:
            if dimension.present:
                _lock_buckets(db, dimension.project_key, {_hour(dimension.timestamp)})
                _move_numeric_records(
                    db, run_id, dimension.project_key, True, False, None, version
                )
            dimension.present = False
            db.flush()
        return dimension, None
    old_visible = dimension.present if dimension else False
    old_hour = (
        _hour(dimension.timestamp)
        if dimension
        else _hour(run.started_at or run.created_at)
    )
    created = dimension is None
    if created:
        dimension = Dimension(run_key=run.id, project_key=run.project_id)
    config = run.run_config if isinstance(run.run_config, dict) else {}
    metadata = run.run_metadata if isinstance(run.run_metadata, dict) else {}
    owner = db.get(User, run.owner_user_id)
    owner_info = (
        {
            "id": owner.id,
            "email": owner.email,
            "display_name": owner.display_name or owner.email.split("@")[0],
        }
        if owner
        else None
    )
    approval = db.scalar(select(Approval).where(Approval.run_id == run.id))
    approval_info = None
    if approval:
        decider = (
            db.get(User, approval.decision_by_user_id)
            if approval.decision_by_user_id
            else None
        )
        approval_info = {
            "decision": getattr(approval.decision, "value", approval.decision),
            "decision_at": _iso(approval.decision_at) if approval.decision_at else None,
            "decision_by": (
                {
                    "id": decider.id,
                    "email": decider.email,
                    "display_name": decider.display_name or decider.email.split("@")[0],
                }
                if decider
                else None
            ),
            "comment": approval.comment or "",
        }
    dataset = _dataset_version_fields(run, _dataset_version_info_map(db, [run]))
    raw_model = _strip_model_provider(run.model or "")
    trace = metadata.get("trace_stats")
    has_reasoning = bool(
        isinstance(trace, dict)
        and (
            trace.get("has_reasoning")
            or trace.get("has_reasoning_tokens")
            or _finite_positive(trace.get("reasoning_tokens"))
            or _finite_positive(trace.get("avg_reasoning_tokens"))
        )
    )
    dimension.task, dimension.model = run.task, (raw_model or "nomodel") + "|||" + (
        "reasoning" if has_reasoning else "plain"
    )
    dataset_version = str(dataset.get("dataset_version") or "").strip()
    dimension.dataset = run.dataset + (
        "\u241f" + dataset_version if dataset_version else ""
    )
    branch, commit = (
        str(config.get("git_branch") or "").strip(),
        str(config.get("git_commit") or "").strip(),
    )
    dimension.version = branch + "/" + commit if branch and commit else branch or commit
    dimension.owner, dimension.status = run.owner_user_id, str(
        getattr(run.status, "value", run.status)
    )
    dimension.timestamp, dimension.created_at = (
        run.started_at or run.created_at,
        run.created_at,
    )
    dimension.present = run.deleted_at is None
    dimension.descriptor = {
        "run_id": run.id,
        "run_name": config.get("run_name") or run.external_run_id or "",
        "external_run_id": run.external_run_id or "",
        "task_name": run.task,
        "model_name": raw_model,
        "dataset_name": run.dataset,
        "timestamp": _iso(dimension.timestamp),
        "file_path": run.id,
        "config_group_key": _config_group_key(config),
        "started_at": _iso(run.started_at) if run.started_at else None,
        "last_event_at": _iso(run.last_event_at or run.updated_at or run.created_at),
        "_activity_sort_at": _iso(run.last_event_at) if run.last_event_at else None,
        "metrics": list(run.metrics or []),
        "metric_specs": _metric_specs_for_runs(db, [run.id]).get(run.id, {}),
        "run_config": {},
        "samples": int(run.samples or 1),
        "report_k": config.get("report_k"),
        "last_completed_pass": metadata.get("last_completed_pass"),
        "git_branch": config.get("git_branch"),
        "git_commit": config.get("git_commit"),
        "owner": owner_info,
        "approval": approval_info,
        "status": dimension.status,
        "trace_stats": trace,
        "product_eval": metadata.get("product_eval"),
        "langfuse_url": metadata.get("langfuse_url"),
        "langfuse_dataset_id": metadata.get("langfuse_dataset_id"),
        "langfuse_run_id": metadata.get("langfuse_run_id"),
        **dataset,
    }
    if created:
        db.add(dimension)
    db.flush()
    new_hour = _hour(dimension.timestamp)
    if old_visible != dimension.present or old_hour != new_hour or created:
        _lock_buckets(db, run.project_id, {old_hour, new_hour})
        _move_numeric_records(
            db,
            run_id,
            run.project_id,
            old_visible,
            dimension.present,
            new_hour,
            version,
        )
        db.flush()
        for hour in {old_hour, new_hour}:
            for _, _, bucket, granularity in _bucket_keys(run.project_id, hour):
                repair_extrema(db, run.project_id, bucket, granularity)
    return dimension, run


def refresh_run_summary(db, run_id, version):
    """Build display numbers from numeric state and current small dimensions."""
    dimension, run = _sync_dimension(db, run_id, version)
    summary = db.get(Summary, run_id)
    if summary is None:
        return
    if not run:
        summary.projection_revision += 1
        summary.applied_source_version = max(summary.applied_source_version, version)
        summary.updated_at = datetime.utcnow()
        return
    db.flush()
    db.refresh(summary)
    items = select(Record).where(
        Record.run_key == run_id, Record.record_kind == "item", Record.present.is_(True)
    )
    latency = items.with_only_columns(Record.latency_ms).where(
        Record.latency_ms.isnot(None)
    )
    avg_latency = (
        summary.latency_sum / summary.latency_count if summary.latency_count else 0.0
    )
    median_latency = _median(db, latency, Record.latency_ms)
    item_alias = aliased(Record)
    metric_rows = db.execute(
        select(Record.metric_key, func.sum(Record.score), func.count(Record.score))
        .join(
            item_alias,
            and_(
                item_alias.record_key == Record.record_key,
                item_alias.record_kind == "item",
                item_alias.present.is_(True),
                item_alias.error == 0,
            ),
        )
        .where(
            Record.run_key == run_id,
            Record.record_kind == "score",
            Record.present.is_(True),
        )
        .group_by(Record.metric_key)
    ).all()
    metric_agg = {
        metric: (total or 0, count or 0) for metric, total, count in metric_rows
    }
    metric_means = {
        metric: (
            metric_agg.get(metric, (0, 0))[0]
            / (metric_agg.get(metric, (0, 0))[1] + summary.error_count)
            if metric_agg.get(metric, (0, 0))[1] + summary.error_count
            else 0.0
        )
        for metric in run.metrics or []
    }
    md = run.run_metadata if isinstance(run.run_metadata, dict) else {}
    try:
        expected = int(md["total_items"]) if md.get("total_items") is not None else None
    except (TypeError, ValueError):
        expected = None
    duration = (
        (run.ended_at - (run.started_at or run.created_at)).total_seconds() * 1000
        if run.ended_at and run.ended_at >= (run.started_at or run.created_at)
        else None
    )
    causes = (
        db.scalar(
            select(func.count(func.distinct(RecordCause.cause_key))).where(
                RecordCause.run_key == run_id, RecordCause.pass_number == 0
            )
        )
        or 0
    )
    passes = None
    if int(run.samples or 1) > 1:
        from qym_platform.api.runs import _repeat_pass_status

        attempts = select(Record).where(
            Record.run_key == run_id,
            Record.record_kind == "attempt",
            Record.present.is_(True),
            Record.is_last.is_(True),
        )
        attempt_latencies = attempts.with_only_columns(Record.latency_ms).where(
            Record.latency_ms.isnot(None)
        )
        attempt_average = db.scalar(
            attempts.with_only_columns(func.avg(Record.latency_ms))
        )
        if attempt_average is not None:
            avg_latency, median_latency = float(attempt_average), _median(
                db, attempt_latencies, Record.latency_ms
            )
        bounds = db.execute(
            attempts.with_only_columns(
                Record.pass_number,
                func.min(Record.started_at_ms),
                func.max(Record.started_at_ms + Record.latency_ms),
            )
            .where(Record.started_at_ms.isnot(None), Record.latency_ms.isnot(None))
            .group_by(Record.pass_number)
        ).all()
        if bounds:
            duration = sum(max(0.0, end - start) for _, start, end in bounds)
        attempt_counts = {
            p: (count, errors or 0)
            for p, count, errors in db.execute(
                attempts.with_only_columns(
                    Record.pass_number, func.count(), func.sum(Record.error)
                ).group_by(Record.pass_number)
            )
        }
        primary = (run.metrics or [None])[0]
        means = dict(
            db.execute(
                select(Record.pass_number, func.avg(Record.score))
                .where(
                    Record.run_key == run_id,
                    Record.record_kind == "pass_score",
                    Record.metric_key == primary,
                    Record.present.is_(True),
                    Record.score.isnot(None),
                )
                .group_by(Record.pass_number)
            ).all()
        )
        pass_causes = dict(
            db.execute(
                select(
                    RecordCause.pass_number,
                    func.count(func.distinct(RecordCause.cause_key)),
                )
                .where(RecordCause.run_key == run_id, RecordCause.pass_number > 0)
                .group_by(RecordCause.pass_number)
            ).all()
        )
        try:
            last_completed = int(md.get("last_completed_pass") or 0)
        except (TypeError, ValueError):
            last_completed = 0
        passes = [
            {
                "pass_number": p,
                "status": _repeat_pass_status(
                    pass_number=p,
                    last_completed=last_completed,
                    has_data=p in means or p in attempt_counts,
                    run_status=dimension.status,
                ),
                "primary_score": means.get(p),
                "error_count": attempt_counts.get(p, (0, 0))[1],
                "analysis_cause_count": pass_causes.get(p, 0),
            }
            for p in range(1, int(run.samples) + 1)
        ]
        if sum(pass_causes.values()):
            causes = sum(pass_causes.values())
    success_rate = summary.success_count / summary.count if summary.count else 0.0
    completed_success = (
        max(0, summary.terminal_count - summary.error_count) / summary.terminal_count
        if summary.terminal_count
        else -1.0
    )
    summary.avg_latency_ms, summary.median_latency_ms = avg_latency, median_latency
    summary.success_rate, summary.completed_success_rate = (
        success_rate,
        completed_success,
    )
    summary.data = {
        "metric_averages": metric_means,
        "total_items": summary.count,
        "progress_completed": summary.terminal_count,
        "progress_total": expected,
        "progress_pct": summary.terminal_count / expected if expected else None,
        "success_count": summary.success_count,
        "error_count": summary.error_count,
        "total_retries": summary.retry_sum,
        "success_rate": success_rate,
        "avg_latency_ms": avg_latency,
        "median_latency_ms": median_latency,
        "duration_ms": duration,
        "pass_summaries": passes,
        "analysis_cause_count": causes,
    }
    summary.projection_revision += 1
    summary.applied_source_version = max(summary.applied_source_version, version)
    summary.extrema_state = "valid"
    summary.extrema_verified_version = version
    summary.latency_min = db.scalar(latency.order_by(Record.latency_ms).limit(1))
    summary.latency_max = db.scalar(latency.order_by(Record.latency_ms.desc()).limit(1))
    scores = select(Record.score).where(
        Record.run_key == run_id,
        Record.record_kind == "score",
        Record.present.is_(True),
        Record.score.isnot(None),
    )
    summary.score_min = db.scalar(scores.order_by(Record.score).limit(1))
    summary.score_max = db.scalar(scores.order_by(Record.score.desc()).limit(1))
    summary.updated_at = datetime.utcnow()
    for _, _, bucket, granularity in _bucket_keys(
        run.project_id, _hour(dimension.timestamp)
    ):
        repair_extrema(db, run.project_id, bucket, granularity)


def process_partition(db: Session, run_id: str, *, max_events=500, owner=None):
    """Serialize one partition; commit snapshot, deltas and watermark together."""
    db.info["dashboard_projection_worker"] = True
    partition = db.scalar(
        select(Partition)
        .where(Partition.partition_key == run_id)
        .with_for_update(skip_locked=True)
    )
    if partition is None:
        return 0
    now = datetime.utcnow()
    owner = owner or str(uuid4())
    if (
        partition.lease_until
        and partition.lease_until > now
        and partition.lease_owner not in (None, owner)
    ):
        return 0
    partition.lease_owner, partition.lease_until = owner, now + timedelta(seconds=30)
    events = list(
        db.scalars(
            select(Change)
            .where(Change.partition_key == run_id, Change.published_at.is_(None))
            .order_by(Change.source_version)
            .limit(max_events)
        )
    )
    if not events:
        partition.lease_owner = partition.lease_until = None
        return 0
    # Source writes lock execution rows before the outbox partition. This worker
    # only reads source dimensions under MVCC; it never requests a source lock.
    from qym_platform.db.models import Run

    run = db.get(Run, run_id)
    dimension = db.get(Dimension, run_id)
    hours = {_hour(dimension.timestamp)} if dimension else set()
    if run:
        hours.add(_hour(run.started_at or run.created_at))
    _lock_buckets(db, partition.project_key, hours)
    try:
        with db.begin_nested():
            apply_events(db, events)
        accepted = events
    except Exception:
        accepted = []
        for event in events:
            try:
                with db.begin_nested():
                    apply_event(db, event)
            except Exception as exc:
                # A failed event rolls back only its own numeric deltas. Prior
                # events retain their watermark; unrelated partitions proceed.
                event.attempt_count += 1
                partition.retry_count += 1
                partition.last_error = str(exc)[:2000]
                if (
                    isinstance(exc, ValueError)
                    or event.attempt_count >= MAX_EVENT_ATTEMPTS
                ):
                    _upsert_ignore(
                        db,
                        DeadLetter,
                        dict(
                            event_id=event.event_id,
                            project_key=event.project_key,
                            partition_key=event.partition_key,
                            source_version=event.source_version,
                            error=partition.last_error,
                        ),
                        ["event_id"],
                    )
                    event.published_at = now
                    partition.queue_state = "repair_required"
                else:
                    break
            accepted.append(event)
    db.flush()
    remaining = db.scalar(
        select(func.min(Change.created_at)).where(
            Change.partition_key == run_id, Change.published_at.is_(None)
        )
    )
    if accepted:
        version = max(event.source_version for event in accepted)
        terminal = run is not None and getattr(run.status, "value", run.status) not in {
            "RUNNING",
            "PENDING",
        }
        # A terminal source row may be newer than this bounded event batch.
        # Retain the last published descriptor/numbers until all its committed
        # events are applied. Source commits wait on our partition row lock.
        if (remaining is None and partition.backfill_complete) or not terminal:
            refresh_run_summary(db, run_id, version)
        partition.last_applied_version = max(partition.last_applied_version, version)
    partition.oldest_pending_event = remaining
    if partition.queue_state != "repair_required":
        partition.queue_state = (
            "pending"
            if remaining is not None
            else "ready" if partition.backfill_complete else "backfill"
        )
    partition.lease_owner = partition.lease_until = None
    partition.updated_at = now
    return len(accepted)


def bootstrap_partitions(db, *, limit=100):
    from qym_platform.db.models import Run

    db.info["dashboard_projection_worker"] = True
    runs = list(
        db.execute(
            select(Run.id, Run.project_id)
            .outerjoin(Partition, Partition.partition_key == Run.id)
            .where(Partition.partition_key.is_(None))
            .order_by(Run.created_at, Run.id)
            .limit(limit)
        )
    )
    for run_id, project in runs:
        _upsert_partition(db.connection(), run_id, project, 0, datetime.utcnow())
    return len(runs)


def backfill_partition(db, run_id, *, chunk_size=500):
    """Resume a bounded source partition while live transactional events continue."""
    from qym_platform.db.models import (
        Run,
        RunItem,
        RunItemAttempt,
        RunItemPassScore,
        RunItemScore,
    )

    db.info["dashboard_projection_worker"] = True
    partition = db.get(Partition, run_id)
    if partition is None or partition.backfill_complete:
        return 0
    source_types = [
        ("item", RunItem),
        ("score", RunItemScore),
        ("pass_score", RunItemPassScore),
        ("attempt", RunItemAttempt),
    ]
    position = next(
        (
            i
            for i, (name, _) in enumerate(source_types)
            if name == partition.backfill_kind
        ),
        0,
    )
    kind, model = source_types[position]
    rows = list(
        db.scalars(
            select(model)
            .where(model.run_id == run_id, model.id > partition.backfill_cursor)
            .order_by(model.id)
            .limit(chunk_size)
            .with_for_update()
        )
    )
    expected_cursor, expected_kind = partition.backfill_cursor, partition.backfill_kind
    db.refresh(partition, with_for_update=True)
    if (
        partition.backfill_cursor != expected_cursor
        or partition.backfill_kind != expected_kind
        or partition.backfill_complete
    ):
        return 0
    if partition.backfill_kind == "item" and partition.backfill_cursor == 0:
        partition.backfill_source_version = partition.last_enqueued_version
    if rows:
        enqueue_snapshots(db.connection(), [snapshot(row) for row in rows])
        partition.backfill_cursor = rows[-1].id
    if len(rows) < chunk_size:
        if position + 1 < len(source_types):
            partition.backfill_kind = source_types[position + 1][0]
            partition.backfill_cursor = 0
        else:
            run = db.get(Run, run_id)
            if run:
                enqueue_snapshots(db.connection(), [snapshot(run)])
            partition.backfill_complete = True
    return len(rows)


def drain_dashboard_changes(db, *, max_partitions=20, max_events=500):
    """One bounded worker tick; no request handler calls this function."""
    db.info["dashboard_projection_worker"] = True
    db.flush()
    partitions = list(
        db.scalars(
            select(Partition.partition_key)
            .where(
                Partition.queue_state.in_(["pending", "backfill"]),
                or_(
                    Partition.lease_until.is_(None),
                    Partition.lease_until <= datetime.utcnow(),
                ),
            )
            .order_by(Partition.updated_at, Partition.partition_key)
            .limit(max_partitions)
        )
    )
    processed = 0
    for run_id in partitions:
        backfill_partition(db, run_id, chunk_size=max_events)
        processed += process_partition(db, run_id, max_events=max_events)
    return processed


def prune_dashboard_state(db, *, before=None, limit=1000):
    """Prune old tombstones only after all source events have crossed watermark."""
    before = before or datetime.utcnow() - MAX_LATE_EVENT_AGE
    candidates = list(
        db.scalars(
            select(Record.id)
            .join(Partition, Partition.partition_key == Record.run_key)
            .where(
                Record.present.is_(False),
                Record.updated_at < before,
                Partition.last_applied_version >= Partition.last_enqueued_version,
                Partition.queue_state == "ready",
                Partition.lease_until.is_(None),
            )
            .limit(limit)
        )
    )
    if candidates:
        db.execute(
            delete(RecordCause).where(RecordCause.record_state_id.in_(candidates))
        )
        db.execute(delete(Record).where(Record.id.in_(candidates)))
    return len(candidates)


def prune_dashboard_events(db, *, before=None, limit=1000):
    """Bounded retention of published outbox rows behind settled watermarks."""
    before = before or datetime.utcnow() - MAX_LATE_EVENT_AGE
    versions = list(
        db.scalars(
            select(Change.source_version)
            .join(Partition, Partition.partition_key == Change.partition_key)
            .where(
                Change.published_at.isnot(None),
                Change.created_at < before,
                Partition.last_applied_version >= Change.source_version,
                Partition.queue_state == "ready",
                Partition.lease_until.is_(None),
            )
            .order_by(Change.source_version)
            .limit(limit)
        )
    )
    if versions:
        db.execute(delete(EventCause).where(EventCause.source_version.in_(versions)))
        db.execute(delete(Change).where(Change.source_version.in_(versions)))
    return len(versions)


def dashboard_freshness(db, project_ids):
    """Return the durable revision and lag for the caller's authorized projects."""
    projects = list(project_ids)
    # Source sequence allocation is independent of commit order. A published
    # revision increments even when an older transaction arrives after a newer
    # record in the same run. Summing these monotonic counters also covers slow
    # partitions without evicting unrelated projects.
    revision = (
        db.scalar(
            select(func.sum(Summary.projection_revision)).where(
                Summary.project_key.in_(projects)
            )
        )
        or 0
    )
    pending, oldest = db.execute(
        select(func.count(), func.min(Partition.oldest_pending_event)).where(
            Partition.project_key.in_(projects),
            or_(
                Partition.queue_state != "ready",
                Partition.last_applied_version < Partition.last_enqueued_version,
            ),
        )
    ).one()
    return {
        "revision": int(revision),
        "freshness": {
            "updating": bool(pending),
            "pending_partitions": int(pending),
            "oldest_pending_at": oldest.isoformat() + "Z" if oldest else None,
        },
    }


def repair_dirty_buckets(db, *, limit=20):
    keys = list(
        db.execute(
            select(Bucket.project_key, Bucket.bucket_key, Bucket.granularity)
            .where(Bucket.extrema_state.in_(["dirty_known", "unknown", "rebuilding"]))
            .order_by(Bucket.project_key, Bucket.bucket_key, Bucket.granularity)
            .limit(limit)
        )
    )
    for project, bucket, granularity in keys:
        repair_extrema(db, project, bucket, granularity)
    return len(keys)


def reconcile_expired_dashboard_runs(db, *, now=None, timeout_seconds=None, limit=100):
    """Bounded active-run maintenance; dashboard reads remain source-free."""
    from qym_platform.db.models import Run, RunWorkflowStatus
    from qym_platform.services.run_lifecycle import reconcile_stale_running_run
    from qym_platform.settings import PlatformSettings

    now = now or datetime.utcnow()
    timeout_seconds = timeout_seconds or PlatformSettings().run_stale_timeout_seconds
    cutoff = now - timedelta(seconds=timeout_seconds)
    last_seen = func.coalesce(Run.last_event_at, Run.started_at, Run.created_at)
    runs = list(
        db.scalars(
            select(Run)
            .where(
                Run.deleted_at.is_(None),
                Run.status == RunWorkflowStatus.RUNNING,
                last_seen <= cutoff,
            )
            .order_by(last_seen, Run.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    changed = sum(
        bool(reconcile_stale_running_run(run, timeout_seconds=timeout_seconds, now=now))
        for run in runs
    )
    # This is a source mutation, so use the transactional outbox hooks.
    db.flush()
    return changed


def request_dashboard_repair(db, run_id):
    """Explicit operator repair: reset one partition, retain failure evidence.

    Tombstones and versions remain available to reject old redeliveries. The
    resumed source backfill allocates new versions under source row locks.
    """
    db.info["dashboard_projection_worker"] = True
    partition = db.get(Partition, run_id, with_for_update=True)
    if partition is None:
        return False
    barrier = partition.last_enqueued_version
    # The explicit source rebuild replaces every committed event at this repair
    # boundary. Retire those pending snapshots before scanning, otherwise an old
    # UPSERT could resurrect an item whose DELETE entered the dead-letter queue.
    db.execute(
        update(Change)
        .where(
            Change.partition_key == run_id,
            Change.published_at.is_(None),
            Change.source_version <= barrier,
        )
        .values(published_at=datetime.utcnow())
    )
    partition.last_applied_version = max(partition.last_applied_version, barrier)
    partition.backfill_source_version = barrier
    dimension = db.get(Dimension, run_id)
    hours = list(
        db.scalars(select(Record.bucket_key).where(Record.run_key == run_id).distinct())
    )
    _lock_buckets(db, partition.project_key, hours)
    _move_numeric_records(
        db,
        run_id,
        partition.project_key,
        bool(dimension and dimension.present),
        False,
        None,
        barrier,
        tombstone=True,
    )
    db.execute(
        update(Record)
        .where(Record.run_key == run_id, Record.applied_source_version < barrier)
        .values(applied_source_version=barrier, updated_at=datetime.utcnow())
    )
    partition.backfill_complete = False
    partition.backfill_kind, partition.backfill_cursor = "item", 0
    partition.queue_state = "backfill"
    partition.last_error = None
    partition.retry_count = 0
    partition.lease_owner = partition.lease_until = None
    partition.oldest_pending_event = datetime.utcnow()
    db.flush()
    refresh_run_summary(db, run_id, partition.last_applied_version)
    return True


class DashboardSummaryWorker:
    """A restart-safe polling worker with bounded transactions and owned sessions.

    The database is the queue. Multiple application processes may run a worker;
    partition row locks and shared bucket lock ordering serialize their updates.
    Each tick commits partitions separately so a noisy run cannot delay others.
    """

    def __init__(
        self, session_factory, *, interval=1.0, max_partitions=20, max_events=500
    ):
        self.session_factory = session_factory
        self.interval = interval
        self.max_partitions = max_partitions
        self.max_events = max_events
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._logger = logging.getLogger(__name__)

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="qym-dashboard-summary", daemon=True
            )
            self._thread.start()

    def stop(self, *, timeout=10.0):
        self._stop.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        return not thread or not thread.is_alive()

    def tick(self):
        with self.session_factory() as db:
            reconcile_expired_dashboard_runs(db, limit=self.max_partitions)
            db.commit()
            partitions = list(
                db.scalars(
                    select(Partition.partition_key)
                    .where(
                        Partition.queue_state.in_(["pending", "backfill"]),
                        or_(
                            Partition.lease_until.is_(None),
                            Partition.lease_until <= datetime.utcnow(),
                        ),
                    )
                    .order_by(Partition.updated_at, Partition.partition_key)
                    .limit(self.max_partitions)
                )
            )
        processed = 0
        for run_id in partitions:
            if self._stop.is_set():
                break
            try:
                with self.session_factory() as db:
                    db.info["dashboard_projection_worker"] = True
                    backfill_partition(db, run_id, chunk_size=self.max_events)
                    processed += process_partition(
                        db, run_id, max_events=self.max_events
                    )
                    db.commit()
            except Exception as exc:
                self._logger.exception(
                    "Dashboard projection failed for partition %s", run_id
                )
                # Persist a visible retry boundary even when projection repair
                # itself failed outside an individual event savepoint.
                try:
                    with self.session_factory() as db:
                        db.info["dashboard_projection_worker"] = True
                        partition = db.get(Partition, run_id, with_for_update=True)
                        if partition is None:
                            continue
                        partition.last_error = str(exc)[:2000]
                        partition.retry_count += 1
                        partition.updated_at = datetime.utcnow()
                        partition.lease_owner = partition.lease_until = None
                        if partition.retry_count >= MAX_EVENT_ATTEMPTS:
                            failed = list(
                                db.scalars(
                                    select(Change)
                                    .where(
                                        Change.partition_key == run_id,
                                        Change.published_at.is_(None),
                                    )
                                    .order_by(Change.source_version)
                                    .limit(self.max_events)
                                )
                            )
                            for change in failed:
                                _upsert_ignore(
                                    db,
                                    DeadLetter,
                                    dict(
                                        event_id=change.event_id,
                                        project_key=change.project_key,
                                        partition_key=run_id,
                                        source_version=change.source_version,
                                        error=partition.last_error,
                                    ),
                                    ["event_id"],
                                )
                                change.attempt_count = max(
                                    change.attempt_count, partition.retry_count
                                )
                                change.published_at = datetime.utcnow()
                            partition.queue_state = "repair_required"
                        db.commit()
                except Exception:
                    self._logger.exception("Could not persist dashboard worker failure")
        with self.session_factory() as db:
            db.info["dashboard_projection_worker"] = True
            repair_dirty_buckets(db, limit=self.max_partitions)
            prune_dashboard_state(db, limit=self.max_events)
            prune_dashboard_events(db, limit=self.max_events)
            db.commit()
        return processed

    def _run(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                # Startup before migrations or a transient DB outage must not
                # lose the durable queue or terminate the background worker.
                self._logger.exception("Dashboard summary worker tick failed")
            self._stop.wait(self.interval)
