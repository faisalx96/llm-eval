"""Adversarial repair and deletion cases found during independent review."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from test_dashboard_durable_summaries import (
    Change,
    Dimension,
    Partition,
    Record,
    Run,
    RunItem,
    Summary,
    database,
    drain,
    item,
    run,
    service,
)


def test_explicit_repair_cannot_resurrect_deleted_source_from_pending_snapshot(
    database,
):
    with Session(database) as db:
        run(db)
        item(db)
        db.commit()
    drain(database)
    with Session(database) as db:
        source = db.scalar(select(RunItem))
        source.latency_ms = 20
        db.commit()
        db.delete(source)
        db.commit()
    # The contract permits out-of-order delivery. A delete beyond the late-event
    # horizon must require repair while preserving an earlier pending update.
    with Session(database) as db:
        deletion = db.scalar(
            select(Change)
            .where(Change.published_at.is_(None))
            .order_by(Change.source_version.desc())
        )
        assert deletion.operation == "DELETE"
        deletion.created_at = datetime.utcnow() - timedelta(days=31)
        service.apply_event(db, deletion)
        db.commit()
        assert db.get(Partition, "r").queue_state == "repair_required"
    with Session(database) as db:
        assert service.request_dashboard_repair(db, "r")
        db.commit()
    drain(database)
    with Session(database) as db:
        assert db.scalar(select(RunItem)) is None
        assert db.get(Summary, "r").count == 0
        assert not db.scalar(select(Record).where(Record.record_kind == "item")).present
        assert db.get(Partition, "r").queue_state == "ready"


def test_hard_run_deletion_advances_visible_revision(database):
    with Session(database) as db:
        run(db)
        db.commit()
    drain(database)
    with Session(database) as db:
        before = service.dashboard_freshness(db, ["p"])["revision"]
        db.delete(db.get(Run, "r"))
        db.commit()
    drain(database)
    with Session(database) as db:
        assert not db.get(Dimension, "r").present
        assert service.dashboard_freshness(db, ["p"])["revision"] > before
