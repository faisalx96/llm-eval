"""Regression contracts for ordered, batched ingestion and trace deltas."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")
from qym_platform.api import ingest
from qym_platform.auth import Principal
from qym_platform.db.base import Base
from qym_platform.db.models import (
    Project,
    Run,
    RunEvent,
    RunItem,
    RunItemAttempt,
    RunItemPassScore,
    RunItemScore,
    RunMetricSpec,
    RunTraceContribution,
    RunTraceSummary,
    RunWorkflowStatus,
    Span,
    User,
    UserRole,
)


@pytest.fixture(params=["sqlite", "postgres"])
def database(request):
    admin = None
    schema = None
    if request.param == "postgres":
        url = os.environ.get("QYM_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("QYM_TEST_POSTGRES_URL not configured")
        schema = "qym_ingestion_" + uuid4().hex
        admin = create_engine(url)
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    def cleanup():
        engine.dispose()
        if admin:
            with admin.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()

    request.addfinalizer(cleanup)
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as db:
        owner = User(id="owner", email="owner@example.invalid", role=UserRole.ADMIN)
        project = Project(
            id="project", name="Test", slug="test", created_by_user_id=owner.id
        )
        run = Run(
            id=str(uuid4()),
            project_id=project.id,
            owner_user_id=owner.id,
            created_by_user_id=owner.id,
            task="test",
            dataset="test",
            metrics=["score"],
            samples=3,
            status=RunWorkflowStatus.RUNNING,
            run_metadata={},
            run_config={},
        )
        db.add(owner)
        db.flush()
        db.add(project)
        db.flush()
        db.add(run)
        db.commit()
        yield engine, db, run, Principal(
            user=owner, auth_type="api_key", project_id=project.id
        )


def _event(run, sequence, kind, payload, event_id=None):
    return dict(
        schema_version=1,
        run_id=run.id,
        event_id=event_id or str(uuid4()),
        sequence=sequence,
        sent_at="2026-09-05T00:00:00Z",
        type=kind,
        payload=payload,
    )


def _apply(db, run, principal, events):
    body = "\n".join(json.dumps(value) for value in events).encode()
    return json.loads(ingest._ingest_events_sync(run.id, body, db, principal).body)


def _canonical(db, run):
    buckets = ingest._build_trace_buckets_from_spans(
        db.query(Span).filter_by(run_id=run.id).all()
    )
    included = []
    for item in db.query(RunItem).filter_by(run_id=run.id).order_by(RunItem.id):
        bucket = buckets.get(item.trace_id)
        if bucket and bucket["span_count"]:
            assert item.item_metadata["trace_stats"] == ingest._sanitize_for_json(
                ingest._public_trace_bucket(bucket)
            )
            if not item.error:
                included.append(bucket)
        else:
            assert "trace_stats" not in item.item_metadata
    return ingest._sanitize_for_json(ingest._build_run_trace_stats(included))


def _assert_nested(actual, expected):
    if isinstance(expected, float):
        assert actual == pytest.approx(expected, abs=1e-8)
    elif isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key in expected:
            _assert_nested(actual[key], expected[key])
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for left, right in zip(actual, expected):
            _assert_nested(left, right)
    else:
        assert actual == expected


@pytest.mark.parametrize("seed", range(8))
def test_incremental_trace_state_matches_full_rebuild_under_mutations(database, seed):
    _, db, run, _ = database
    rng = random.Random(seed)
    for index in range(9):
        db.add(
            RunItem(
                run_id=run.id,
                item_id=f"item-{index}",
                index=index,
                input={},
                item_metadata={},
                trace_id=f"trace-{index % 4}",
            )
        )
    db.commit()
    ingest._refresh_live_trace_stats(db, run)
    db.commit()
    for step in range(45):
        trace_id = f"trace-{rng.randrange(6)}"
        item_id = f"item-{rng.randrange(9)}"
        item = db.query(RunItem).filter_by(run_id=run.id, item_id=item_id).first()
        action = rng.randrange(5)
        if action <= 1:
            kind = rng.choice(["LLM", "TOOL", "CHAIN", "RETRIEVER", "EVALUATOR"])
            # Parent span can arrive after its descendants. Named outer scope
            # ordering and metric-descendant exclusion must be recomputed.
            span_id = f"span-{step}"
            db.add(
                Span(
                    run_id=run.id,
                    trace_id=trace_id,
                    span_id=span_id,
                    parent_span_id=f"span-{step + 1}" if step % 3 == 0 else None,
                    name=f"scope-{step % 3}",
                    status="ERROR" if step % 7 == 0 else "OK",
                    duration_ms=step + 0.25,
                    attributes={
                        "openinference.span.kind": kind,
                        "qym.usage_scope": "metric" if step % 11 == 0 else "task",
                        "llm.token_count.total": step + 1,
                        "llm.token_count.completion_details.reasoning": step % 4,
                        "qym.response.classification": (
                            "malformed_tool_call" if step % 9 == 0 else ""
                        ),
                    },
                    events=[],
                    links=[],
                )
            )
        elif action == 2 and item:
            item.trace_id = trace_id
            item.error = "failed" if step % 2 else None
        elif action == 3 and item:
            db.delete(item)
        elif action == 4 and not item:
            db.add(
                RunItem(
                    run_id=run.id,
                    item_id=item_id,
                    index=int(item_id[5:]),
                    input={},
                    item_metadata={},
                    trace_id=trace_id,
                )
            )
        ingest._refresh_live_trace_stats(
            db, run, touched_trace_ids={trace_id}, touched_item_ids={item_id}
        )
        db.commit()
        _assert_nested(run.run_metadata["trace_stats"], _canonical(db, run))


def test_duplicate_events_and_span_identities_do_not_double_apply(database):
    _, db, run, principal = database
    events = [
        _event(
            run,
            1,
            "item_completed",
            dict(item_id="a", output="yes", latency_ms=1, trace_id="t"),
        ),
        _event(
            run,
            2,
            "span_completed",
            dict(
                trace_id="t",
                span_id="s",
                name="llm",
                attributes={
                    "openinference.span.kind": "LLM",
                    "llm.token_count.total": 12,
                },
            ),
        ),
    ]
    result = _apply(db, run, principal, [events[0], events[0], events[1]])
    assert result == {"ok": True, "applied": 2, "skipped": 1}
    snapshot = copy.deepcopy(run.run_metadata)
    assert _apply(db, run, principal, events)["skipped"] == 2
    second_span = _event(run, 3, "span_completed", events[1]["payload"])
    _apply(db, run, principal, [second_span])
    assert db.query(Span).count() == 1
    assert db.query(RunEvent).count() == 3
    assert run.run_metadata == snapshot


@pytest.mark.parametrize("completed_first", [False, True])
def test_ordered_repeats_keep_outputs_final_attempt_and_reduced_scores(
    database, completed_first
):
    _, db, run, principal = database
    payloads = [
        (
            "item_attempt_finished",
            dict(
                item_id="a",
                pass_number=1,
                attempt_number=1,
                status="failed",
                is_last_attempt=True,
            ),
        ),
        (
            "item_attempt_finished",
            dict(
                item_id="a",
                pass_number=1,
                attempt_number=2,
                status="completed",
                is_last_attempt=True,
            ),
        ),
        (
            "item_completed",
            dict(item_id="a", pass_number=1, output="pass one", latency_ms=3),
        ),
    ]
    if completed_first:
        payloads = [payloads[2], *payloads[:2]]
    payloads += [
        (
            "metric_scored",
            dict(item_id="a", pass_number=1, metric_name="score", score_numeric=1),
        ),
        (
            "metric_scored",
            dict(item_id="a", pass_number=2, metric_name="score", score_numeric=0.5),
        ),
        ("item_failed", dict(item_id="a", pass_number=3, error="failure")),
    ]
    _apply(
        db,
        run,
        principal,
        [
            _event(run, i + 1, kind, payload)
            for i, (kind, payload) in enumerate(payloads)
        ],
    )
    attempts = db.query(RunItemAttempt).order_by(RunItemAttempt.attempt_number).all()
    assert not attempts[0].is_last_attempt
    assert attempts[1].is_last_attempt and attempts[1].output == "pass one"
    assert db.query(RunItemScore).one().score_numeric == pytest.approx(0.5)
    assert [
        row.score_numeric
        for row in db.query(RunItemPassScore).order_by(RunItemPassScore.pass_number)
    ] == [1, 0.5, 0]


def test_invalid_metric_rolls_back_event_and_item_changes_in_worker(database):
    engine, db, run, principal = database
    db.add(
        RunMetricSpec(
            run_id=run.id, metric_name="score", position=0, score_type="percentage"
        )
    )
    db.commit()
    events = [
        _event(run, 1, "item_started", dict(item_id="a", index=0, input="x")),
        _event(
            run,
            2,
            "metric_scored",
            dict(item_id="a", metric_name="score", score_numeric=4),
        ),
    ]
    with pytest.raises(HTTPException):
        ingest._ingest_events_worker(
            run.id, "\n".join(map(json.dumps, events)).encode(), engine, principal
        )
    db.expire_all()
    assert db.query(RunEvent).count() == 0
    assert db.query(RunItem).count() == 0


def test_sequence_collision_rolls_back_entire_batch(database):
    engine, db, run, principal = database
    events = [
        _event(run, 1, "item_started", dict(item_id=str(i), index=i, input="x"))
        for i in range(2)
    ]
    with pytest.raises(IntegrityError):
        ingest._ingest_events_worker(
            run.id, "\n".join(map(json.dumps, events)).encode(), engine, principal
        )
    assert db.query(RunItem).count() == db.query(RunEvent).count() == 0


def test_failed_span_bulk_write_isolates_bad_span_and_keeps_items(
    database, monkeypatch
):
    _, db, run, principal = database
    original = db.execute

    def execute(statement, params=None, *args, **kwargs):
        if getattr(getattr(statement, "table", None), "name", None) == "spans":
            if any(row["span_id"] == "bad" for row in params):
                raise ValueError("injected invalid span")
        return original(statement, params, *args, **kwargs)

    monkeypatch.setattr(db, "execute", execute)
    events = [
        _event(
            run,
            1,
            "item_completed",
            dict(item_id="a", output="ok", latency_ms=1, trace_id="t"),
        )
    ]
    events += [
        _event(
            run,
            i + 2,
            "span_completed",
            dict(trace_id="t", span_id=span_id, name="llm"),
        )
        for i, span_id in enumerate(["good", "bad", "good2"])
    ]
    result = _apply(db, run, principal, events)
    assert result["applied"] == 4
    assert db.query(RunItem).one().output == "ok"
    assert {row.span_id for row in db.query(Span)} == {"good", "good2"}


def test_trace_failure_rolls_back_only_projection_changes(database, monkeypatch):
    _, db, run, principal = database

    def fail(db, run, **kwargs):
        run.run_metadata = {"bad_partial_projection": True}
        db.flush()
        raise ValueError("injected projection failure")

    monkeypatch.setattr(ingest, "_refresh_live_trace_stats", fail)
    _apply(
        db,
        run,
        principal,
        [
            _event(
                run, 1, "item_completed", dict(item_id="a", output="ok", latency_ms=1)
            )
        ],
    )
    assert db.query(RunItem).one().output == "ok"
    assert "bad_partial_projection" not in run.run_metadata


def test_trace_delta_and_ledger_rollback_together(database):
    _, db, run, _ = database
    ingest._refresh_live_trace_stats(db, run)
    db.commit()
    original = copy.deepcopy(run.run_metadata)
    db.add(
        RunItem(
            run_id=run.id,
            item_id="a",
            index=0,
            input={},
            item_metadata={},
            trace_id="t",
        )
    )
    db.add(
        Span(
            run_id=run.id,
            trace_id="t",
            span_id="s",
            name="x",
            attributes={},
            events=[],
            links=[],
        )
    )
    ingest._refresh_live_trace_stats(
        db, run, touched_trace_ids={"t"}, touched_item_ids={"a"}
    )
    db.rollback()
    assert run.run_metadata == original
    assert db.query(RunTraceContribution).count() == 0
    assert db.get(RunTraceSummary, run.id).totals["items"] == 0


def test_warm_refresh_does_not_load_unrelated_items_or_spans(database):
    _, db, run, _ = database
    for i in range(120):
        db.add(
            RunItem(
                run_id=run.id,
                item_id=str(i),
                index=i,
                input="large" * 1000,
                item_metadata={},
                trace_id=f"t-{i}",
            )
        )
        db.add(
            Span(
                run_id=run.id,
                trace_id=f"t-{i}",
                span_id=f"s-{i}",
                name="x",
                attributes={},
                events=[],
                links=[],
            )
        )
    ingest._refresh_live_trace_stats(db, run)
    db.commit()
    run_id = run.id
    db.expunge_all()
    run = db.get(Run, run_id)
    loaded = []
    event.listen(db, "loaded_as_persistent", lambda session, obj: loaded.append(obj))
    ingest._refresh_live_trace_stats(
        db, run, touched_trace_ids={"t-7"}, touched_item_ids={"7"}
    )
    assert len([obj for obj in loaded if isinstance(obj, RunItem)]) == 1
    assert len([obj for obj in loaded if isinstance(obj, Span)]) == 1
    assert len([obj for obj in loaded if isinstance(obj, RunTraceContribution)]) == 1


def test_span_batch_uses_bounded_selects_and_savepoints(database):
    engine, db, run, principal = database
    ingest._refresh_live_trace_stats(db, run)
    db.commit()
    statements = []
    event.listen(
        engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, params, context, many: statements.append(
            statement
        ),
    )
    events = [
        _event(
            run, i + 1, "span_completed", dict(trace_id="t", span_id=str(i), name="x")
        )
        for i in range(100)
    ]
    _apply(db, run, principal, events)
    assert sum(sql.startswith("SELECT") for sql in statements) < 15
    assert sum(sql.startswith("SAVEPOINT") for sql in statements) <= 3
    assert db.query(Span).count() == 100


@pytest.mark.asyncio
async def test_ingest_worker_does_not_block_loop_and_owns_session(
    database, monkeypatch
):
    engine, db, run, principal = database
    main_thread = threading.get_ident()
    entered, release = threading.Event(), threading.Event()
    observed = []
    original = ingest._ingest_events_sync

    def blocked(run_id, body, worker_db, worker_principal):
        observed.append((threading.get_ident(), worker_db is not db))
        entered.set()
        assert release.wait(3)
        return original(run_id, body, worker_db, worker_principal)

    monkeypatch.setattr(ingest, "_ingest_events_sync", blocked)

    class Request:
        async def body(self):
            return b""

    task = asyncio.create_task(ingest.ingest_events(run.id, Request(), db, principal))
    try:
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(0.005)
        assert entered.is_set()
        # This coroutine must run while the database worker is still blocked.
        assert not task.done()
    finally:
        release.set()
    await task
    assert observed[0][0] != main_thread and observed[0][1]


def test_postgres_concurrent_identical_batches_apply_once(database):
    engine, db, run, principal = database
    if engine.dialect.name != "postgresql":
        pytest.skip("requires PostgreSQL row locks")
    events = [
        _event(
            run,
            1,
            "item_completed",
            dict(item_id="a", output="ok", latency_ms=1, trace_id="t"),
        ),
        _event(
            run,
            2,
            "span_completed",
            dict(
                trace_id="t",
                span_id="s",
                name="llm",
                attributes={
                    "openinference.span.kind": "LLM",
                    "llm.token_count.total": 10,
                },
            ),
        ),
    ]
    body = "\n".join(map(json.dumps, events)).encode()
    run_id = run.id
    barrier = threading.Barrier(2)

    def worker():
        isolated = Principal(
            user=User(id="owner"), auth_type="api_key", project_id="project"
        )
        barrier.wait(timeout=5)
        return json.loads(
            ingest._ingest_events_worker(run_id, body, engine, isolated).body
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]
    db.expire_all()
    assert sorted(result["applied"] for result in results) == [0, 2]
    assert db.query(RunEvent).count() == 2
    assert db.query(Span).count() == 1
    assert run.run_metadata["trace_stats"]["avg_tokens"] == 10


def test_legacy_cached_trace_survives_first_incremental_backfill(database):
    _, db, run, _ = database
    from qym_platform.db.models import RunTraceAggregate

    bucket = ingest._empty_trace_bucket()
    bucket.update(span_count=1, tokens=42, llm_calls=1)
    db.add(
        RunItem(
            run_id=run.id,
            item_id="old",
            index=0,
            input={},
            item_metadata={},
            trace_id="legacy",
        )
    )
    db.add(RunTraceAggregate(run_id=run.id, trace_id="legacy", raw_bucket=bucket))
    db.commit()
    ingest._refresh_live_trace_stats(
        db, run, touched_trace_ids={"new"}, touched_item_ids=set()
    )
    db.commit()
    assert run.run_metadata["trace_stats"]["avg_tokens"] == 42
    assert db.query(RunItem).one().item_metadata["trace_stats"]["tokens"] == 42


def test_failed_trace_projection_rebuilds_on_next_unrelated_batch(
    database, monkeypatch
):
    _, db, run, principal = database
    ingest._refresh_live_trace_stats(db, run)
    db.commit()
    original = ingest._refresh_live_trace_stats

    def fail(*args, **kwargs):
        raise ValueError("injected failure")

    monkeypatch.setattr(ingest, "_refresh_live_trace_stats", fail)
    _apply(
        db,
        run,
        principal,
        [
            _event(
                run,
                1,
                "item_completed",
                dict(item_id="a", output="ok", latency_ms=1, trace_id="t"),
            ),
            _event(
                run,
                2,
                "span_completed",
                dict(
                    trace_id="t",
                    span_id="s",
                    name="llm",
                    attributes={
                        "openinference.span.kind": "LLM",
                        "llm.token_count.total": 10,
                    },
                ),
            ),
        ],
    )
    assert db.get(RunTraceSummary, run.id) is None
    monkeypatch.setattr(ingest, "_refresh_live_trace_stats", original)
    _apply(
        db,
        run,
        principal,
        [
            _event(
                run, 3, "item_completed", dict(item_id="b", output="ok", latency_ms=1)
            )
        ],
    )
    assert run.run_metadata["trace_stats"]["avg_tokens"] == 10


@pytest.mark.asyncio
async def test_auth_connection_is_returned_before_ingest_checkout(database):
    engine, db, run, principal = database
    if engine.dialect.name != "postgresql":
        pytest.skip("requires a real connection pool")
    # Preserve this fixture's schema while exercising a single-connection pool.
    with engine.connect() as conn:
        schema = conn.execute(text("SELECT current_schema()")).scalar()
    small_pool = create_engine(
        engine.url,
        connect_args={"options": f"-csearch_path={schema}"},
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.2,
    )
    try:
        with Session(small_pool, autoflush=False) as request_db:
            owner = request_db.get(User, "owner")
            auth = Principal(user=owner, auth_type="api_key", project_id="project")

            class Request:
                async def body(self):
                    return b""

            result = await ingest.ingest_events(run.id, Request(), request_db, auth)
            assert json.loads(result.body)["ok"]
    finally:
        small_pool.dispose()


def test_trace_migration_upgrade_and_downgrade_preserve_source(database):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect as inspect_db
    from qym_platform.db.models import RunTraceNamedContribution

    engine, db, run, _ = database
    run_id = run.id
    db.add(
        RunItem(
            run_id=run_id,
            item_id="source",
            index=0,
            input="unchanged",
            item_metadata={},
        )
    )
    db.commit()
    path = (
        Path(ingest.__file__).parents[1]
        / "migrations/versions/0047_incremental_trace_statistics.py"
    )
    spec = importlib.util.spec_from_file_location("trace_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    # The fixture creates the current model schema; first return only the trace
    # additions to their pre-migration state, then exercise a complete roundtrip.
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            migration.downgrade()
            migration.upgrade()
    tables = inspect_db(engine).get_table_names()
    assert "run_trace_summaries" in tables
    assert "run_trace_contributions" in tables
    with Session(engine, autoflush=False) as check:
        restored = check.get(Run, run_id)
        ingest._refresh_live_trace_stats(check, restored)
        check.commit()
        assert check.query(RunItem).one().input == "unchanged"
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            migration.downgrade()
    assert "run_trace_contributions" not in inspect_db(engine).get_table_names()
    assert db.query(RunItem).one().input == "unchanged"
