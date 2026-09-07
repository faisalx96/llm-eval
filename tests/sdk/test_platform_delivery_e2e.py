"""Real SDK event delivery through the platform ASGI ingestion routes."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from collections import defaultdict
from queue import Full
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

# The standalone SDK test environment need not install the separate platform.
pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from qym import Evaluator, InMemoryDataset
from qym.platform import client as client_module
from qym.platform.client import PlatformEventStream

os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")
from qym_platform.api import ingest
from qym_platform.auth import Principal, require_api_key_principal
from qym_platform.db.base import Base
from qym_platform.db.models import (
    Project,
    Run,
    RunEvent,
    RunItem,
    RunItemAttempt,
    RunItemPassScore,
    RunItemScore,
    RunWorkflowStatus,
    Span,
    User,
    UserRole,
)
from qym_platform.deps import get_db


@pytest.fixture(params=["sqlite", "postgres"])
def platform(request, monkeypatch):
    admin = None
    schema = None
    if request.param == "postgres":
        url = os.environ.get("QYM_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("QYM_TEST_POSTGRES_URL not configured")
        schema = "qym_delivery_" + uuid4().hex
        admin = create_engine(url)
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )

    def cleanup():
        engine.dispose()
        if admin:
            with admin.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()

    request.addfinalizer(cleanup)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(User(id="owner", email="owner@example.invalid", role=UserRole.ADMIN))
        db.flush()
        db.add(
            Project(id="project", name="Test", slug="test", created_by_user_id="owner")
        )
        db.commit()
    app = FastAPI()
    app.include_router(ingest.router)

    def session():
        with Session(engine, autoflush=False) as db:
            yield db

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[require_api_key_principal] = lambda: Principal(
        user=User(id="owner"),
        auth_type="api_key",
        project_id="project",
    )
    observed = []
    with TestClient(app) as client:

        def post_json(url, payload, key, **kwargs):
            response = client.post(urlsplit(url).path, json=payload)
            response.raise_for_status()
            return response.json()

        def post_ndjson(url, payload, key, **kwargs):
            events = [json.loads(line) for line in payload.splitlines()]
            response = client.post(
                urlsplit(url).path,
                content=payload,
                headers={"content-type": "application/x-ndjson"},
            )
            response.raise_for_status()
            observed.extend(events)
            return response.json()

        monkeypatch.setattr(client_module, "_post_json", post_json)
        monkeypatch.setattr(client_module, "_post_ndjson", post_ndjson)
        yield engine, observed, post_ndjson


def _isolated_otel(monkeypatch):
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from qym.core.otel import OtelManager, QymSpanProcessor
    import qym.core.otel as otel_module

    provider = TracerProvider()
    processor = QymSpanProcessor()
    provider.add_span_processor(processor)
    monkeypatch.setattr(
        trace, "get_tracer", lambda name, *args, **kwargs: provider.get_tracer(name)
    )
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: provider)
    monkeypatch.setattr(
        otel_module,
        "create_otel_manager",
        lambda config: OtelManager(provider.get_tracer("qym"), processor),
    )
    return provider


@pytest.mark.asyncio
@pytest.mark.parametrize("lose_response", [False, True])
async def test_sdk_repeats_metrics_traces_and_final_status_reach_platform(
    platform, monkeypatch, tmp_path, lose_response
):
    engine, observed, post = platform
    provider = _isolated_otel(monkeypatch)
    from opentelemetry import trace

    lost = False
    terminal_counts = []

    def transport(url, payload, key, **kwargs):
        nonlocal lost
        events = [json.loads(line) for line in payload.splitlines()]
        if any(row["type"] == "run_completed" for row in events):
            with Session(engine) as db:
                terminal_counts.append(
                    (
                        db.query(RunItem).count(),
                        db.query(RunItemPassScore).count(),
                        db.query(Span).count(),
                    )
                )
        result = post(url, payload, key, **kwargs)
        if (
            lose_response
            and not lost
            and any(row["type"] == "item_completed" for row in events)
        ):
            lost = True
            raise TimeoutError("server committed but acknowledgement was lost")
        return result

    monkeypatch.setattr(client_module, "_post_ndjson", transport)
    monkeypatch.setattr(PlatformEventStream, "MAX_PENDING_MEMORY_BYTES", 2000)
    monkeypatch.setattr(PlatformEventStream, "MAX_PENDING_DISK_BYTES", 12000)
    monkeypatch.setattr(PlatformEventStream, "MAX_BATCH_EVENTS", 5)
    monkeypatch.setattr(PlatformEventStream, "FLUSH_INTERVAL", 0.005)
    monkeypatch.setattr(PlatformEventStream, "RETRY_BACKOFF_BASE", 0.005)
    counts = defaultdict(int)

    async def task(input):
        counts[input] += 1
        with trace.get_tracer("delivery-test").start_as_current_span(
            "fake-llm",
            attributes={"openinference.span.kind": "LLM", "llm.token_count.total": 7},
        ):
            await asyncio.sleep(0.001)
            if input == "question-0" and counts[input] == 1:
                raise RuntimeError("retry this transient task failure")
            return "wrong" if input == "question-1" and counts[input] == 2 else input

    evaluator = Evaluator(
        task,
        InMemoryDataset(
            [
                {
                    "id": f"item-{i}",
                    "input": f"question-{i}",
                    "expected_output": f"question-{i}",
                }
                for i in range(6)
            ]
        ),
        ["exact_match"],
        config={
            "run_name": "delivery",
            "task_name": "delivery",
            "samples": 3,
            "max_concurrency": 3,
            "max_retries": 1,
            "checkpoint_enabled": False,
            "otel_enabled": True,
            "platform_api_key": "test-only",
            "platform_url": "http://testserver",
            "output_dir": str(tmp_path),
        },
    )
    try:
        result = await evaluator.arun(show_tui=False, auto_save=False)
        assert result.total_items == 6
        assert evaluator._run_completed
        stream = evaluator._platform_stream
        assert (
            stream.dropped_events
            == stream._q.unfinished_tasks
            == stream._active_emitters
            == 0
        )
        assert (
            stream._q.peak_memory_bytes <= 2000 and stream._q.peak_disk_bytes <= 12000
        )
        assert stream._q.spool_path is None
        assert terminal_counts and terminal_counts[0][0:2] == (6, 18)
        assert terminal_counts[0][2] > 0
        with Session(engine) as db:
            run = db.query(Run).one()
            assert run.status == RunWorkflowStatus.COMPLETED and run.samples == 3
            assert "ingest_incomplete" not in run.run_metadata
            assert db.query(RunItem).count() == 6
            assert (
                db.query(RunItemAttempt).filter_by(is_last_attempt=True).count() == 18
            )
            assert db.query(RunItemPassScore).count() == 18
            assert db.query(RunItemScore).count() == 6
            for row in db.query(RunItemScore):
                assert row.score_numeric == pytest.approx(
                    2 / 3 if row.item_id == "item-1" else 1
                )
            stored_events = db.query(RunEvent).order_by(RunEvent.sequence).all()
            assert stored_events[-1].type == "run_completed"
            assert sum(row.type == "run_completed" for row in stored_events) == 1
            assert len({row.event_id for row in stored_events}) == len(stored_events)
            spans = db.query(Span).all()
            assert sum(row.name == "fake-llm" for row in spans) == 19
            assert db.query(RunItemAttempt).count() == 19
            assert run.run_metadata["trace_stats"]["avg_tokens"] == 7
            attempts = (
                db.query(RunItemAttempt)
                .filter_by(item_id="item-1")
                .order_by(RunItemAttempt.pass_number)
                .all()
            )
            assert [attempt.output for attempt in attempts] == [
                "question-1",
                "wrong",
                "question-1",
            ]
    finally:
        provider.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_producer", [False, True])
async def test_close_cannot_overtake_async_append_waiting_for_executor(
    monkeypatch, cancel_producer
):
    sent = []
    monkeypatch.setattr(
        client_module,
        "_post_ndjson",
        lambda url, body, key, **kwargs: sent.extend(
            json.loads(line) for line in body.splitlines()
        ),
    )
    stream = PlatformEventStream("http://unused.invalid", "test", str(uuid4()))
    entered, release = threading.Event(), threading.Event()
    original = stream._enqueue

    def delayed(event, **kwargs):
        if kwargs.get("block") is False:
            raise Full
        entered.set()
        assert release.wait(3)
        return original(event, **kwargs)

    monkeypatch.setattr(stream, "_enqueue", delayed)
    producer = asyncio.create_task(stream.aemit("item_completed", {"item_id": "a"}))
    closer = None
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        if cancel_producer:
            producer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await producer
        closer = asyncio.create_task(stream.aclose())
        await asyncio.sleep(0.15)
        assert (
            not closer.done()
        ), "close must include admission waiting outside the queue"
        assert not await stream.aflush(0)
        release.set()
        if not cancel_producer:
            await producer
        await asyncio.wait_for(closer, 2)
        await stream.aemit("run_completed", {}, sync=True)
        assert [row["type"] for row in sent] == ["item_completed", "run_completed"]
        assert stream._active_emitters == stream._q.unfinished_tasks == 0
    finally:
        release.set()
        if closer and not closer.done():
            await closer
        else:
            await stream.aclose()


@pytest.mark.asyncio
async def test_close_timeout_with_pending_admission_is_not_successful_flush(
    monkeypatch,
):
    monkeypatch.setattr(client_module, "_post_ndjson", lambda *args, **kwargs: None)
    monkeypatch.setenv("QYM_PLATFORM_CLOSE_TIMEOUT", "0.02")
    stream = PlatformEventStream("http://unused.invalid", "test", str(uuid4()))
    entered, release = threading.Event(), threading.Event()
    original = stream._enqueue

    def delayed(event, **kwargs):
        if kwargs.get("block") is False:
            raise Full
        entered.set()
        release.wait(2)
        return original(event, **kwargs)

    monkeypatch.setattr(stream, "_enqueue", delayed)
    producer = asyncio.create_task(stream.aemit("item_completed", {"item_id": "a"}))
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        await stream.aclose()
        assert not await stream.aflush(0)
    finally:
        release.set()
        await producer
        await asyncio.to_thread(stream._thread.join, 2)
    assert not stream._thread.is_alive()


@pytest.mark.asyncio
async def test_terminal_delivery_failure_is_not_reported_as_completed(
    platform, monkeypatch, tmp_path
):
    engine, observed, post = platform

    def transport(url, body, key, **kwargs):
        if any(
            json.loads(line)["type"] == "run_completed" for line in body.splitlines()
        ):
            raise OSError("terminal acknowledgement unavailable")
        return post(url, body, key, **kwargs)

    monkeypatch.setattr(client_module, "_post_ndjson", transport)
    monkeypatch.setattr(PlatformEventStream, "SYNC_SEND_RETRIES", 1)

    async def task(input):
        return input

    evaluator = Evaluator(
        task,
        InMemoryDataset([{"input": "yes", "expected_output": "yes"}]),
        ["exact_match"],
        config={
            "run_name": "failed-terminal",
            "task_name": "test",
            "checkpoint_enabled": False,
            "otel_enabled": False,
            "platform_api_key": "test-only",
            "platform_url": "http://testserver",
            "output_dir": str(tmp_path),
        },
    )
    result = await evaluator.arun(show_tui=False, auto_save=False)
    assert result.total_items == 1
    assert not evaluator._run_completed
    assert evaluator._platform_stream.dropped_events == 1
    with Session(engine) as db:
        assert db.query(RunItem).one().output == "yes"
        assert db.query(Run).one().status == RunWorkflowStatus.RUNNING
        assert db.query(RunEvent).filter_by(type="run_completed").count() == 0


@pytest.mark.asyncio
async def test_cancellation_drains_accepted_events_before_stopped_terminal(
    platform, tmp_path
):
    engine, observed, _ = platform
    entered = asyncio.Event()

    async def task(input):
        entered.set()
        await asyncio.Event().wait()

    evaluator = Evaluator(
        task,
        InMemoryDataset(
            [
                {"id": str(i), "input": str(i), "expected_output": str(i)}
                for i in range(3)
            ]
        ),
        ["exact_match"],
        config={
            "run_name": "cancelled",
            "task_name": "test",
            "checkpoint_enabled": False,
            "max_concurrency": 1,
            "interrupt_grace_seconds": 0.1,
            "otel_enabled": False,
            "platform_api_key": "test-only",
            "platform_url": "http://testserver",
            "output_dir": str(tmp_path),
        },
    )
    running = asyncio.create_task(evaluator.arun(show_tui=False, auto_save=False))
    await asyncio.wait_for(entered.wait(), 3)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(running, 5)
    assert evaluator._platform_stream._q.unfinished_tasks == 0
    assert not evaluator._platform_stream._thread.is_alive()
    with Session(engine) as db:
        run = db.query(Run).one()
        assert run.status == RunWorkflowStatus.STOPPED
        rows = db.query(RunEvent).order_by(RunEvent.sequence).all()
        assert rows[-1].type == "run_completed"
        assert rows[-1].payload["final_status"] == "STOPPED"
        assert sum(row.type == "run_completed" for row in rows) == 1
        assert any(row.type == "item_failed" for row in rows)
