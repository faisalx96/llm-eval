"""Transactional dashboard projection contracts, against independent legacy output."""

from __future__ import annotations

import copy
import os
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, event, func, null, select, text, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("QYM_DATABASE_URL", "sqlite://")
from qym_platform.api import runs as runs_api
from qym_platform.auth import Principal
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
from qym_platform.db.models import (
    Approval,
    ApprovalDecision,
    Base,
    Dataset,
    DatasetAlias,
    DatasetVersion,
    Project,
    Run,
    RunItem,
    RunItemAttempt,
    RunItemPassScore,
    RunItemScore,
    RunMetricSpec,
    RunWorkflowStatus,
    User,
    UserRole,
)
from qym_platform.services import dashboard_summaries as service
from qym_platform.services.dashboard_outbox import enqueue_snapshots, snapshot


@pytest.fixture(params=["sqlite", "postgres"])
def database(request):
    admin = schema = None
    if request.param == "postgres":
        url = os.environ.get("QYM_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("QYM_TEST_POSTGRES_URL not configured")
        schema = "qym_dashboard_" + uuid4().hex
        admin = create_engine(url)
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine(
            "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            User(
                id="u",
                email="owner@example.test",
                display_name="Owner",
                role=UserRole.ADMIN,
            )
        )
        db.flush()
        db.add(Project(id="p", name="Project", slug="test", created_by_user_id="u"))
        db.commit()
    try:
        yield engine
    finally:
        engine.dispose()
        if admin:
            with admin.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


def run(db, run_id="r", **kwargs):
    obj = Run(
        id=run_id,
        project_id="p",
        created_by_user_id="u",
        owner_user_id="u",
        task="task",
        dataset="dataset",
        model="openai/model",
        metrics=["score", "other"],
        started_at=datetime(2026, 9, 1, 12),
        created_at=datetime(2026, 9, 1, 12),
        run_metadata={"total_items": 4},
        run_config={},
        status=RunWorkflowStatus.RUNNING,
        last_event_at=datetime.utcnow(),
    )
    for key, value in kwargs.items():
        setattr(obj, key, value)
    db.add(obj)
    db.flush()
    return obj


def item(db, item_id="i", run_id="r", **kwargs):
    obj = RunItem(
        run_id=run_id,
        item_id=item_id,
        input={"private": "payload"},
        output="answer",
        latency_ms=10.0,
    )
    for key, value in kwargs.items():
        setattr(obj, key, value)
    db.add(obj)
    return obj


def drain(engine, *, max_events=500):
    for _ in range(100):
        with Session(engine, autoflush=False) as db:
            service.drain_dashboard_changes(db, max_events=max_events)
            db.commit()
            pending = db.scalar(
                select(func.count())
                .select_from(Partition)
                .where(Partition.queue_state.in_(["pending", "backfill"]))
            )
        if not pending:
            return
    raise AssertionError("projection failed to settle")


def projected(engine, run_id="r"):
    with Session(engine) as db:
        return {**db.get(Dimension, run_id).descriptor, **db.get(Summary, run_id).data}


def legacy(engine, run_id="r"):
    with Session(engine) as db:
        result = runs_api.legacy_list_runs(
            limit=500,
            offset=0,
            project_slug="test",
            status=None,
            exclude_live=False,
            include_total=True,
            user=None,
            user_id=None,
            owner_user_id=None,
            db=db,
            principal=Principal(user=db.get(User, "u"), auth_type="none"),
        )
    return next(
        row
        for models in result["tasks"].values()
        for rows in models.values()
        for row in rows
        if row["run_id"] == run_id
    )


def assert_legacy_parity(engine, run_id="r"):
    expected, actual = legacy(engine, run_id), projected(engine, run_id)
    for key, value in expected.items():
        assert actual[key] == value, (key, actual[key], value)


def test_transactional_rollback_and_numeric_only_events(database):
    with Session(database) as db:
        run(db)
        item(db)
        db.flush()
        assert db.scalar(select(func.count()).select_from(Change)) == 2
        db.rollback()
    with Session(database) as db:
        assert db.scalar(select(func.count()).select_from(Change)) == 0
        assert db.scalar(select(func.count()).select_from(Partition)) == 0
        run(db)
        item(db)
        db.commit()
        columns = set(Change.__table__.columns.keys())
        assert not columns & {"payload", "input", "output", "metadata", "score_raw"}
        assert db.scalar(select(func.count()).select_from(Change)) == 2


def test_exact_legacy_means_median_errors_nulls_progress_and_metadata(database):
    with Session(database) as db:
        run(
            db,
            run_config={
                "run_name": "exact",
                "git_branch": " main ",
                "git_commit": " abc ",
            },
            run_metadata={
                "total_items": 6,
                "trace_stats": {"avg_reasoning_tokens": 2},
                "product_eval": {"name": "product"},
            },
        )
        item(db, "a", latency_ms=1.0, error=None)
        item(db, "b", latency_ms=9.0, error="", retry_count=2)
        item(db, "c", latency_ms=30.0, output=None)
        item(db, "d", latency_ms=None, output=null())
        item(
            db,
            "e",
            latency_ms=17.0,
            item_metadata={
                "root_cause": "cause",
                "metric_analyses": {
                    "score": {"root_cause": "cause"},
                    "other": {"root_cause": "second"},
                },
            },
        )
        db.add_all(
            [
                RunItemScore(
                    run_id="r", item_id="a", metric_name="score", score_numeric=0.8
                ),
                RunItemScore(
                    run_id="r", item_id="b", metric_name="score", score_numeric=100
                ),
                RunItemScore(
                    run_id="r", item_id="e", metric_name="other", score_numeric=12
                ),
            ]
        )
        db.commit()
    drain(database, max_events=2)
    assert_legacy_parity(database)
    with Session(database) as db:
        assert db.get(Dimension, "r").dataset == "dataset"
        assert db.get(Dimension, "r").version == "main/abc"
        assert db.get(Dimension, "r").model == "model|||reasoning"
        assert db.get(Summary, "r").score_max == 100
    with Session(database) as db:
        obj = db.scalar(select(RunItem).where(RunItem.item_id == "b"))
        obj.error = None
        obj.latency_ms = 4
        obj = db.scalar(select(RunItemScore).where(RunItemScore.item_id == "a"))
        obj.score_numeric = 0.4
        db.commit()
    drain(database)
    assert_legacy_parity(database)


def test_duplicate_out_of_order_and_tombstone_converge(database):
    with Session(database) as db:
        run(db)
        item(db)
        db.commit()
    drain(database)
    with Session(database) as db:
        obj = db.scalar(select(RunItem))
        obj.latency_ms = 20
        db.commit()
        obj.latency_ms = 30
        db.commit()
    with Session(database, autoflush=False) as db:
        events = list(
            db.scalars(
                select(Change)
                .where(Change.published_at.is_(None))
                .order_by(Change.source_version)
            )
        )
        assert len(events) == 2
        assert service.apply_event(db, events[1])
        assert not service.apply_event(db, events[0])
        assert not service.apply_event(db, events[1])
        db.commit()
        assert db.get(Summary, "r").latency_sum == 30
    with Session(database) as db:
        db.delete(db.scalar(select(RunItem)))
        db.commit()
    drain(database)
    with Session(database) as db:
        deleted = db.scalar(select(Record).where(Record.record_kind == "item"))
        assert not deleted.present
        old = db.scalar(
            select(Change)
            .where(Change.record_kind == "item")
            .order_by(Change.source_version)
        )
        assert not service.apply_event(db, old)
        assert db.get(Summary, "r").count == 0
        db.commit()


def test_soft_delete_restore_and_timestamp_move_adjust_all_buckets(database):
    with Session(database) as db:
        run(db)
        item(db, latency_ms=7)
        run(db, "other", started_at=datetime(2026, 9, 2, 12))
        item(db, "other", run_id="other", latency_ms=80)
        db.commit()
    drain(database)
    with Session(database) as db:
        obj = db.get(Run, "r")
        obj.deleted_at = datetime.utcnow()
        db.commit()
    drain(database)
    with Session(database) as db:
        assert not db.get(Dimension, "r").present
        assert (
            sum(db.scalars(select(Bucket.count).where(Bucket.granularity == "hour")))
            == 1
        )
        obj = db.get(Run, "r")
        obj.deleted_at = None
        obj.started_at = datetime(2026, 9, 2, 12)
        db.commit()
    drain(database)
    with Session(database) as db:
        assert db.get(Dimension, "r").present
        buckets = list(db.scalars(select(Bucket).where(Bucket.granularity == "hour")))
        assert sum(b.count for b in buckets) == 2
        nonempty = next(b for b in buckets if b.count)
        assert (nonempty.latency_min, nonempty.latency_max) == (7, 80)
        assert all(b.latency_min is None for b in buckets if not b.count)
        assert (
            sum(
                db.scalars(
                    select(Histogram.count).where(
                        Histogram.granularity == "hour",
                        Histogram.value_kind == "latency",
                    )
                )
            )
            == 2
        )


def test_extrema_dirty_then_exact_numeric_only_repair(database):
    with Session(database) as db:
        run(db)
        item(db, "min", latency_ms=1)
        item(db, "max", latency_ms=20)
        db.commit()
    drain(database)
    with Session(database) as db:
        db.delete(db.scalar(select(RunItem).where(RunItem.item_id == "min")))
        db.commit()
    with Session(database) as db:
        change = db.scalar(select(Change).where(Change.published_at.is_(None)))
        service.apply_event(db, change)
        db.flush()
        bucket = db.scalar(select(Bucket).where(Bucket.granularity == "hour"))
        assert bucket.extrema_state == "dirty_known"
        assert service.extrema_payload(bucket)["latency_min"] is None
        statements = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement.lower())

        event.listen(database, "before_cursor_execute", capture)
        try:
            service.repair_extrema(db, bucket.project_key, bucket.bucket_key)
        finally:
            event.remove(database, "before_cursor_execute", capture)
        assert (bucket.latency_min, bucket.latency_max) == (20, 20)
        assert not any(
            "run_items" in s or "run_item_scores" in s or " spans " in s
            for s in statements
        )
        db.commit()


def test_late_events_deadletter_and_freshness_remains_updating(database):
    with Session(database) as db:
        run(db)
        item(db)
        db.commit()
        obj = db.scalar(select(Change).where(Change.record_kind == "item"))
        obj.created_at = datetime.utcnow() - timedelta(days=31)
        db.commit()
    drain(database)
    with Session(database) as db:
        assert db.scalar(select(func.count()).select_from(DeadLetter)) == 1
        assert db.get(Partition, "r").queue_state == "repair_required"
        assert service.dashboard_freshness(db, ["p"])["freshness"]["updating"]
        assert db.get(Summary, "r").count == 0


def test_schema_failure_and_transient_retry_are_durable(database, monkeypatch):
    with Session(database) as db:
        run(db)
        item(db)
        db.commit()
        obj = db.scalar(select(Change).where(Change.record_kind == "item"))
        obj.operation = "BAD"
        db.commit()
    drain(database)
    with Session(database) as db:
        assert db.scalar(select(func.count()).select_from(DeadLetter)) == 1
        assert db.get(Summary, "r").count == 0
    with Session(database) as db:
        run(db, "retry")
        item(db, run_id="retry")
        db.commit()
    original = service.apply_event

    def fail_once(db, obj, **kwargs):
        if obj.partition_key == "retry" and obj.record_kind == "item":
            raise RuntimeError("transient failure")
        return original(db, obj, **kwargs)

    monkeypatch.setattr(service, "apply_event", fail_once)
    for n in range(5):
        with Session(database) as db:
            service.process_partition(db, "retry")
            db.commit()
    with Session(database) as db:
        assert db.get(Partition, "retry").queue_state == "repair_required"
        assert db.get(Partition, "retry").retry_count == 5
        assert db.scalar(select(func.count()).select_from(DeadLetter)) == 2
        assert db.get(Summary, "retry").count == 0


def test_bulk_mutations_repeat_deletion_and_dimension_changes(database):
    with Session(database) as db:
        run(db, samples=3, run_metadata={"total_items": 2, "last_completed_pass": 2})
        item(db, "a", latency_ms=5)
        item(db, "b", latency_ms=15, error="error")
        for p in (1, 2):
            for i, lat in (("a", 5), ("b", 15)):
                db.add(
                    RunItemAttempt(
                        run_id="r",
                        item_id=i,
                        pass_number=p,
                        attempt_number=1,
                        status="FAILED" if i == "b" else "COMPLETED",
                        is_last_attempt=True,
                        latency_ms=lat + p,
                        task_started_at_ms=1000 * p,
                    )
                )
                db.add(
                    RunItemPassScore(
                        run_id="r",
                        item_id=i,
                        metric_name="score",
                        pass_number=p,
                        score_numeric=p / 3,
                        meta={"root_cause_analysis": {"root_cause": "same cause"}},
                    )
                )
        db.add(
            Approval(
                run_id="r",
                submitted_by_user_id="u",
                decision_by_user_id="u",
                decision=ApprovalDecision.APPROVED,
                comment="ok",
            )
        )
        db.commit()
    drain(database)
    assert_legacy_parity(database)
    with Session(database) as db:
        db.query(RunItemAttempt).filter(RunItemAttempt.pass_number == 2).delete(
            synchronize_session=False
        )
        db.query(RunItemPassScore).filter(RunItemPassScore.pass_number == 2).delete(
            synchronize_session=False
        )
        db.execute(update(RunItem).where(RunItem.item_id == "a").values(latency_ms=25))
        db.get(User, "u").display_name = "New owner"
        db.commit()
    drain(database)
    assert_legacy_parity(database)
    assert projected(database)["owner"]["display_name"] == "New owner"


def test_backfill_resumes_and_live_corrections_win(database):
    with Session(database) as db:
        db.info["dashboard_projection_worker"] = True
        run(db)
        for i in range(8):
            item(db, str(i), latency_ms=i)
            db.add(
                RunItemScore(
                    run_id="r",
                    item_id=str(i),
                    metric_name="score",
                    score_numeric=i / 10,
                )
            )
        db.commit()
    with Session(database) as db:
        assert service.bootstrap_partitions(db) == 1
        service.backfill_partition(db, "r", chunk_size=2)
        service.process_partition(db, "r")
        db.commit()
        assert db.get(Partition, "r").backfill_cursor == 2
    with Session(database) as db:
        obj = db.scalar(select(RunItem).where(RunItem.item_id == "0"))
        obj.latency_ms = 100
        db.delete(db.scalar(select(RunItem).where(RunItem.item_id == "7")))
        item(db, "new", latency_ms=40)
        db.commit()
    drain(database, max_events=2)
    assert_legacy_parity(database)
    with Session(database) as db:
        assert db.get(Partition, "r").backfill_complete
        assert db.get(Summary, "r").count == 8
        assert (
            sum(db.scalars(select(Bucket.count).where(Bucket.granularity == "hour")))
            == 8
        )


def test_partition_revisions_and_leases_do_not_hide_other_runs(database):
    with Session(database) as db:
        run(db)
        item(db)
        run(db, "second")
        item(db, run_id="second")
        db.commit()
    with Session(database) as db:
        service.process_partition(db, "second")
        db.commit()
        before = service.dashboard_freshness(db, ["p"])
        part = db.get(Partition, "r")
        part.lease_owner = "other-worker"
        part.lease_until = datetime.utcnow() + timedelta(seconds=60)
        db.commit()
        assert service.process_partition(db, "r", owner="my-worker") == 0
        part.lease_until = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
        service.process_partition(db, "r", owner="my-worker")
        db.commit()
        after = service.dashboard_freshness(db, ["p"])
        assert after["revision"] > before["revision"]
        assert not after["freshness"]["updating"]
        assert service.dashboard_freshness(db, ["unrelated"])["revision"] == 0


def test_concurrent_same_bucket_atomic_deltas(database):
    if database.dialect.name != "postgresql":
        pytest.skip("SQLite single-connection fixture is intentionally serial")
    with Session(database) as db:
        for n in range(8):
            run(db, str(n))
            item(db, run_id=str(n), latency_ms=n + 1)
        db.commit()
    barrier = threading.Barrier(8)

    def process(n):
        barrier.wait(timeout=5)
        with Session(database) as db:
            service.process_partition(db, str(n))
            db.commit()

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(process, range(8)))
    with Session(database) as db:
        bucket = db.scalar(select(Bucket).where(Bucket.granularity == "hour"))
        assert bucket.count == 8
        assert bucket.latency_sum == 36
        assert (bucket.latency_min, bucket.latency_max) == (1, 8)
        assert (
            sum(
                db.scalars(
                    select(Histogram.count).where(
                        Histogram.granularity == "hour",
                        Histogram.value_kind == "latency",
                    )
                )
            )
            == 8
        )


def test_worker_owns_sessions_and_stop_is_idempotent(database):
    with Session(database) as db:
        run(db)
        item(db)
        db.commit()
    worker = service.DashboardSummaryWorker(
        sessionmaker(database, autoflush=False), interval=0.01
    )
    assert worker.tick() == 2
    assert worker.tick() == 0
    worker.start()
    worker.start()
    assert worker.stop(timeout=3)
    assert worker.stop(timeout=3)
    assert projected(database)["total_items"] == 1


def test_outbox_insert_batches_and_event_cause_identity(database):
    with Session(database) as db:
        run(db)
        db.commit()
        statements = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            if statement.lower().startswith("insert into dashboard_change_events"):
                statements.append(statement)

        event.listen(database, "before_cursor_execute", capture)
        try:
            for i in range(100):
                item(db, str(i), item_metadata={"root_cause": f"cause-{i}"})
            db.commit()
        finally:
            event.remove(database, "before_cursor_execute", capture)
        assert len(statements) <= 2
        pairs = db.execute(
            select(Change.record_key, EventCause.cause_key).join(
                EventCause, EventCause.source_version == Change.source_version
            )
        ).all()
        import hashlib

        assert dict(pairs) == {
            f"r:{i}": hashlib.sha256(f"cause-{i}".encode()).hexdigest()
            for i in range(100)
        }


def test_source_commit_order_still_advances_publication_revision(database):
    with Session(database) as db:
        run(db)
        item(db, "first")
        item(db, "second")
        db.commit()
    with Session(database) as db:
        changes = list(
            db.scalars(
                select(Change)
                .where(Change.record_kind == "item")
                .order_by(Change.source_version)
            )
        )
        older_id = changes[0].source_version
        # Simulate an older source transaction that is not visible at first.
        changes[0].published_at = datetime.utcnow()
        service.process_partition(db, "r")
        db.commit()
        revision = service.dashboard_freshness(db, ["p"])["revision"]
        db.get(Change, older_id).published_at = None
        db.commit()
        service.process_partition(db, "r")
        db.commit()
        assert db.get(Summary, "r").count == 2
        assert service.dashboard_freshness(db, ["p"])["revision"] > revision


def test_background_liveness_expiry_and_heartbeat_restore(database):
    from qym_platform.services.run_lifecycle import mark_run_running

    start = datetime.utcnow()
    with Session(database) as db:
        run(db, last_event_at=start)
        item(db)
        db.commit()
    drain(database)
    with Session(database) as db:
        assert (
            service.reconcile_expired_dashboard_runs(
                db, now=start + timedelta(seconds=61), timeout_seconds=60
            )
            == 1
        )
        db.commit()
    drain(database)
    assert projected(database)["status"] == "STOPPED"
    with Session(database) as db:
        obj = db.get(Run, "r")
        mark_run_running(obj)
        obj.last_event_at = start + timedelta(seconds=62)
        db.commit()
    drain(database)
    assert projected(database)["status"] == "RUNNING"


def test_dataset_alias_repoint_refreshes_both_old_and_new_dimensions(database):
    with Session(database) as db:
        db.add(
            Dataset(
                id="d",
                project_id="p",
                name="Dataset",
                slug="dataset",
                created_by_user_id="u",
            )
        )
        db.flush()
        for id_, label in (("v1", "v1"), ("v2", "v2")):
            db.add(
                DatasetVersion(
                    id=id_, dataset_id="d", version=label, created_by_user_id="u"
                )
            )
        db.flush()
        alias = DatasetAlias(
            dataset_id="d",
            alias="production",
            dataset_version_id="v1",
            updated_by_user_id="u",
        )
        db.add(alias)
        run(db, dataset_version_id="v1")
        run(db, "second", dataset_version_id="v2")
        db.commit()
    drain(database)
    assert projected(database)["dataset_aliases"] == ["production"]
    with Session(database) as db:
        db.scalar(select(DatasetAlias)).dataset_version_id = "v2"
        db.commit()
    drain(database)
    assert projected(database)["dataset_aliases"] == []
    assert projected(database, "second")["dataset_aliases"] == ["production"]
    with Session(database) as db:
        assert db.get(Dimension, "r").dataset == "dataset␟v1"
        assert db.get(Dimension, "second").dataset == "dataset␟v2"


def test_explicit_repair_recovers_late_event_without_losing_evidence(database):
    with Session(database) as db:
        run(db)
        item(db)
        db.commit()
        db.scalar(select(Change).where(Change.record_kind == "item")).created_at = (
            datetime.utcnow() - timedelta(days=31)
        )
        db.commit()
    drain(database)
    with Session(database) as db:
        assert service.request_dashboard_repair(db, "r")
        db.commit()
    drain(database, max_events=1)
    assert_legacy_parity(database)
    with Session(database) as db:
        assert db.scalar(select(func.count()).select_from(DeadLetter)) == 1
        assert db.get(Partition, "r").queue_state == "ready"
        assert (
            sum(db.scalars(select(Bucket.count).where(Bucket.granularity == "hour")))
            == 1
        )


def test_migration_frozen_schema_and_existing_history_seed(database):
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = (
        Path(__file__).parents[2]
        / "packages/platform/qym_platform/migrations/versions/0048_durable_dashboard_summaries.py"
    )
    assert "qym_platform.db" not in path.read_text()
    spec = importlib.util.spec_from_file_location("dashboard_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with Session(database) as db:
        run(db)
        item(db)
        db.commit()
    with database.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.downgrade()
        migration.upgrade()
    with Session(database) as db:
        assert db.get(Partition, "r").queue_state == "backfill"
        assert not db.get(Partition, "r").backfill_complete
    drain(database, max_events=1)
    assert_legacy_parity(database)


def test_concurrent_backfill_and_live_update_preserve_lock_order(database):
    if database.dialect.name != "postgresql":
        pytest.skip("requires independent row-level locks")
    with Session(database) as db:
        db.info["dashboard_projection_worker"] = True
        run(db)
        item(db)
        db.commit()
    with Session(database) as db:
        service.bootstrap_partitions(db)
        db.commit()
    locked = threading.Event()
    release = threading.Event()

    def mutate():
        with Session(database) as db:
            obj = db.scalar(select(RunItem).with_for_update())
            obj.latency_ms = 90
            locked.set()
            assert release.wait(5)
            db.commit()

    def backfill():
        assert locked.wait(5)
        with Session(database) as db:
            service.backfill_partition(db, "r", chunk_size=1)
            service.process_partition(db, "r")
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(mutate)
        filler = pool.submit(backfill)
        assert locked.wait(5)
        release.set()
        writer.result(timeout=10)
        filler.result(timeout=10)
    drain(database, max_events=1)
    assert_legacy_parity(database)
    assert projected(database)["avg_latency_ms"] == 90


def test_concurrent_opposite_timestamp_moves_do_not_deadlock(database):
    if database.dialect.name != "postgresql":
        pytest.skip("requires independent row-level locks")
    first, second = datetime(2026, 9, 1, 12), datetime(2026, 9, 2, 12)
    with Session(database) as db:
        run(db, started_at=first)
        item(db, latency_ms=10)
        run(db, "second", started_at=second)
        item(db, run_id="second", latency_ms=20)
        db.commit()
    drain(database)
    with Session(database) as db:
        db.get(Run, "r").started_at = second
        db.get(Run, "second").started_at = first
        db.commit()
    barrier = threading.Barrier(2)

    def process(run_id):
        barrier.wait(5)
        with Session(database) as db:
            service.process_partition(db, run_id)
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(process, key) for key in ("r", "second")]
        for future in futures:
            future.result(timeout=10)
    with Session(database) as db:
        assert (
            sum(db.scalars(select(Bucket.count).where(Bucket.granularity == "hour")))
            == 2
        )


def test_terminal_backlog_does_not_publish_completed_partial_totals(database):
    with Session(database) as db:
        run(db)
        item(db, "first")
        db.commit()
    drain(database)
    previous = projected(database)
    with Session(database) as db:
        for n in range(12):
            item(db, str(n), latency_ms=n)
        obj = db.get(Run, "r")
        obj.status = RunWorkflowStatus.COMPLETED
        obj.ended_at = datetime.utcnow()
        db.commit()
    with Session(database) as db:
        service.process_partition(db, "r", max_events=3)
        db.commit()
        assert service.dashboard_freshness(db, ["p"])["freshness"]["updating"]
    assert projected(database) == previous
    drain(database, max_events=3)
    assert projected(database)["status"] == "COMPLETED"
    assert projected(database)["total_items"] == 13
    assert_legacy_parity(database)


def test_new_terminal_backfill_waits_until_consistent_publication(database):
    with Session(database) as db:
        db.info["dashboard_projection_worker"] = True
        run(db, status=RunWorkflowStatus.COMPLETED)
        for n in range(12):
            item(db, str(n))
        db.commit()
    with Session(database) as db:
        service.bootstrap_partitions(db)
        service.backfill_partition(db, "r", chunk_size=3)
        service.process_partition(db, "r", max_events=1)
        db.commit()
        assert db.get(Dimension, "r") is None
    drain(database, max_events=3)
    assert projected(database)["total_items"] == 12
    assert_legacy_parity(database)


def test_retention_requires_watermark_and_preserves_sequence(database):
    with Session(database) as db:
        run(db)
        item(db, item_metadata={"root_cause": "old"})
        db.commit()
    drain(database)
    with Session(database) as db:
        db.delete(db.scalar(select(RunItem)))
        db.commit()
    drain(database)
    old = datetime.utcnow() - timedelta(days=31)
    with Session(database) as db:
        previous = db.scalar(select(func.max(Change.source_version)))
        db.execute(update(Change).values(created_at=old))
        db.execute(
            update(Record).where(Record.present.is_(False)).values(updated_at=old)
        )
        part = db.get(Partition, "r")
        part.queue_state = "repair_required"
        db.commit()
        assert service.prune_dashboard_state(db) == 0
        assert service.prune_dashboard_events(db) == 0
        part.queue_state = "ready"
        part.last_applied_version = 0
        db.commit()
        assert service.prune_dashboard_events(db) == 0
        part.last_applied_version = part.last_enqueued_version
        db.commit()
        assert service.prune_dashboard_state(db) == 1
        assert service.prune_dashboard_events(db) == 3
        db.commit()
        assert db.scalar(select(func.count()).select_from(EventCause)) == 0
        item(db, "new")
        db.commit()
        assert db.scalar(select(func.max(Change.source_version))) > previous
    drain(database)
    assert projected(database)["total_items"] == 1


def test_normal_worker_batches_numerical_sql(database):
    with Session(database) as db:
        run(db)
        for n in range(100):
            item(db, str(n), latency_ms=n)
        db.commit()
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    event.listen(database, "before_cursor_execute", capture)
    try:
        drain(database)
    finally:
        event.remove(database, "before_cursor_execute", capture)
    assert len(statements) < 180
    assert (
        sum(
            statement.startswith("insert into dashboard_record_state")
            for statement in statements
        )
        <= 2
    )
    assert sum(statement.startswith("savepoint") for statement in statements) <= 2


@pytest.mark.parametrize(
    "status",
    [RunWorkflowStatus.COMPLETED, RunWorkflowStatus.APPROVED, RunWorkflowStatus.DRAFT],
)
def test_worker_historical_terminal_waits_for_all_source_kinds(database, status):
    with Session(database) as db:
        db.info["dashboard_projection_worker"] = True
        run(db, status=status)
        for n in range(12):
            item(db, str(n))
            db.add(
                RunItemScore(
                    run_id="r", item_id=str(n), metric_name="score", score_numeric=0.75
                )
            )
        db.commit()
    with Session(database) as db:
        service.bootstrap_partitions(db)
        db.commit()
    worker = service.DashboardSummaryWorker(
        sessionmaker(database, autoflush=False), max_events=3
    )
    for _ in range(30):
        worker.tick()
        with Session(database) as db:
            partition = db.get(Partition, "r")
            if not partition.backfill_complete:
                assert db.get(Dimension, "r") is None
                assert service.dashboard_freshness(db, ["p"])["freshness"]["updating"]
            elif partition.queue_state == "ready":
                break
    else:
        raise AssertionError("historical backfill did not complete")
    assert projected(database)["status"] == status.value
    assert projected(database)["metric_averages"]["score"] == 0.75
    assert projected(database)["total_items"] == 12
    assert_legacy_parity(database)


def test_worker_repeated_publication_failure_deadletters_and_retains_source(
    database, monkeypatch
):
    with Session(database) as db:
        run(db)
        item(db)
        db.commit()

    def fail(*args, **kwargs):
        raise RuntimeError("publication failed")

    monkeypatch.setattr(service, "refresh_run_summary", fail)
    worker = service.DashboardSummaryWorker(sessionmaker(database, autoflush=False))
    for _ in range(5):
        worker.tick()
    with Session(database) as db:
        assert db.get(Partition, "r").queue_state == "repair_required"
        assert db.get(Partition, "r").retry_count == 5
        assert db.scalar(select(func.count()).select_from(DeadLetter)) == 2
        assert db.scalar(select(func.count()).select_from(RunItem)) == 1
        assert service.dashboard_freshness(db, ["p"])["freshness"]["updating"]


def test_missing_model_identity_matches_legacy_flattening(database):
    with Session(database) as db:
        run(db, model=None)
        db.commit()
    drain(database)
    with Session(database) as db:
        assert db.get(Dimension, "r").model == "nomodel|||plain"
        assert db.get(Dimension, "r").descriptor["model_name"] == ""


def test_source_flush_snapshots_membership_sets_once():
    from qym_platform.services.dashboard_outbox import _before_flush
    from sqlalchemy.util import IdentitySet

    class SessionProbe:
        def __init__(self):
            self.info = {}
            self.new_reads = self.deleted_reads = 0
            self._new = IdentitySet(
                RunItem(run_id="r", item_id=str(n)) for n in range(1000)
            )
            self.dirty = IdentitySet()

        @property
        def new(self):
            self.new_reads += 1
            return IdentitySet(self._new)

        @property
        def deleted(self):
            self.deleted_reads += 1
            return IdentitySet()

        def is_modified(self, obj, **kwargs):
            raise AssertionError("New objects need no dirty-state inspection")

    session = SessionProbe()
    _before_flush(session, None, None)
    assert session.new_reads == session.deleted_reads == 1
    assert len(session.info["dashboard_source_changes"]) == 1000
