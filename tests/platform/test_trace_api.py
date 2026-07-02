from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")
ROOT = Path(__file__).resolve().parents[2]
PLATFORM_SRC = ROOT / "packages" / "platform"
if str(PLATFORM_SRC) not in sys.path:
    sys.path.insert(0, str(PLATFORM_SRC))
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

from qym_platform.app import create_app
from qym_platform.db.base import Base
from qym_platform.db.models import (
    Project,
    ProjectMembership,
    ProjectRole,
    Run,
    RunItem,
    RunItemAttempt,
    RunWorkflowStatus,
    Span,
    User,
    UserRole,
)
from qym_platform.deps import get_db


@pytest.fixture(autouse=True)
def _auth_mode(monkeypatch):
    # scoped replacement for a module-level os.environ write that leaked
    # into every other test file in the run
    monkeypatch.setenv("QYM_AUTH_MODE", "proxy_headers")


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    try:
        yield SessionLocal
    finally:
        engine.dispose()


@pytest.fixture()
def client(session_factory):
    app = create_app()

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def _seed_trace_data(session: Session) -> None:
    project = Project(id="project-1", name="Project 1", slug="project-1", created_by_user_id="user-owner")
    owner = User(id="user-owner", email="owner@example.com", role=UserRole.MEMBER)
    other = User(id="user-other", email="other@example.com", role=UserRole.MEMBER)
    membership = ProjectMembership(project_id=project.id, user_id=owner.id, role=ProjectRole.MEMBER)
    run = Run(
        id="run-1",
        project_id=project.id,
        created_by_user_id=owner.id,
        owner_user_id=owner.id,
        task="trace_task",
        dataset="dataset-1",
        status=RunWorkflowStatus.COMPLETED,
        metrics=[],
        run_metadata={},
        run_config={},
    )
    traced_item = RunItem(
        run_id=run.id,
        item_id="item-1",
        index=0,
        input={"prompt": "hello"},
        expected={"answer": "world"},
        output={"answer": "world"},
        item_metadata={},
        retry_count=1,
        trace_id="trace-2",
        trace_url="https://langfuse.example/trace-2",
    )
    plain_item = RunItem(
        run_id=run.id,
        item_id="item-2",
        index=1,
        input={"prompt": "no-trace"},
        expected=None,
        output={"answer": "ok"},
        item_metadata={},
        trace_id=None,
        trace_url=None,
    )
    attempts = [
        RunItemAttempt(
            run_id=run.id,
            item_id="item-1",
            attempt_number=1,
            status="failed",
            latency_ms=2000.0,
            task_started_at_ms=1000,
            trace_id="trace-1",
            trace_url="https://langfuse.example/trace-1",
            error="boom",
            is_last_attempt=False,
        ),
        RunItemAttempt(
            run_id=run.id,
            item_id="item-1",
            attempt_number=2,
            status="completed",
            latency_ms=1500.0,
            task_started_at_ms=3000,
            trace_id="trace-2",
            trace_url="https://langfuse.example/trace-2",
            error=None,
            is_last_attempt=True,
        ),
    ]
    spans = [
        Span(
            run_id=run.id,
            trace_id="trace-1",
            span_id="span-root",
            parent_span_id=None,
            name="eval-run-item-0",
            kind="INTERNAL",
            start_time_ns=1_000_000_000,
            end_time_ns=3_000_000_000,
            duration_ms=2000.0,
            status="OK",
            attributes={"openinference.span.kind": "CHAIN"},
            events=[],
        ),
        Span(
            run_id=run.id,
            trace_id="trace-1",
            span_id="span-child",
            parent_span_id="span-root",
            name="openai.chat",
            kind="CLIENT",
            start_time_ns=1_200_000_000,
            end_time_ns=2_200_000_000,
            duration_ms=1000.0,
            status="OK",
            attributes={"openinference.span.kind": "LLM"},
            events=[{"name": "llm.start", "time_unix_nano": 1_250_000_000, "attributes": {"model": "gpt"}}],
        ),
        Span(
            run_id=run.id,
            trace_id="trace-2",
            span_id="span-last-root",
            parent_span_id=None,
            name="eval-run-item-0-attempt-2",
            kind="INTERNAL",
            start_time_ns=6_000_000_000,
            end_time_ns=7_500_000_000,
            duration_ms=1500.0,
            status="OK",
            attributes={"openinference.span.kind": "CHAIN"},
            events=[],
        ),
    ]
    session.add_all([owner, other, project, membership, run, traced_item, plain_item, *attempts, *spans])
    session.commit()


def _headers(email: str) -> dict[str, str]:
    return {"X-User-Email": email}


def test_item_trace_endpoint_returns_summary_and_spans(client, session_factory) -> None:
    with session_factory() as session:
        _seed_trace_data(session)

    response = client.get("/api/runs/run-1/items/item-1/trace", headers=_headers("owner@example.com"))

    assert response.status_code == 200
    body = response.json()
    assert body["item"] == {
        "run_id": "run-1",
        "item_id": "item-1",
        "trace_id": "trace-2",
        "trace_url": "https://langfuse.example/trace-2",
        "retry_count": 1,
    }
    assert body["summary"]["span_count"] == 1
    assert body["summary"]["root_count"] == 1
    assert body["summary"]["error_count"] == 0
    assert body["summary"]["orphan_count"] == 0
    assert body["summary"]["has_orphans"] is False
    assert body["summary"]["started_at_ns"] == 6_000_000_000
    assert body["summary"]["ended_at_ns"] == 7_500_000_000
    assert body["summary"]["duration_ms"] == pytest.approx(1500.0)
    assert [span["span_id"] for span in body["spans"]] == ["span-last-root"]
    assert [attempt["attempt_number"] for attempt in body["attempts"]] == [1, 2]
    assert body["attempts"][0]["trace_id"] == "trace-1"
    assert body["attempts"][0]["summary"]["span_count"] == 2
    assert body["attempts"][1]["trace_id"] == "trace-2"
    assert body["attempts"][1]["summary"]["span_count"] == 1


def test_item_trace_endpoint_returns_empty_payload_when_item_has_no_trace(client, session_factory) -> None:
    with session_factory() as session:
        _seed_trace_data(session)

    response = client.get("/api/runs/run-1/items/item-2/trace", headers=_headers("owner@example.com"))

    assert response.status_code == 200
    body = response.json()
    assert body["item"]["item_id"] == "item-2"
    assert body["item"]["trace_id"] == ""
    assert body["item"]["trace_url"] == ""
    assert body["item"]["retry_count"] == 0
    assert body["summary"] == {
        "span_count": 0,
        "root_count": 0,
        "error_count": 0,
        "duration_ms": None,
        "started_at_ns": None,
        "ended_at_ns": None,
        "has_orphans": False,
        "orphan_count": 0,
    }
    assert body["spans"] == []
    assert body["attempts"] == []


def test_item_trace_endpoint_rejects_other_user(client, session_factory) -> None:
    with session_factory() as session:
        _seed_trace_data(session)

    response = client.get("/api/runs/run-1/items/item-1/trace", headers=_headers("other@example.com"))

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"


def test_legacy_span_endpoints_enforce_run_visibility(client, session_factory) -> None:
    with session_factory() as session:
        _seed_trace_data(session)

    run_response = client.get("/api/runs/run-1/spans", headers=_headers("other@example.com"))
    item_response = client.get("/api/runs/run-1/items/item-1/spans", headers=_headers("other@example.com"))

    assert run_response.status_code == 403
    assert item_response.status_code == 403
