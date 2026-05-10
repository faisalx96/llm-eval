from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")
os.environ["QYM_AUTH_MODE"] = "proxy_headers"
ROOT = Path(__file__).resolve().parents[2]
PLATFORM_SRC = ROOT / "packages" / "platform"
if str(PLATFORM_SRC) not in sys.path:
    sys.path.insert(0, str(PLATFORM_SRC))
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

from qym_platform.app import create_app
from qym_platform.api.ingest import _refresh_live_trace_stats, _store_trace_stats
from qym_platform.db.base import Base
from qym_platform.db.models import (
    ApiKey,
    Project,
    Run,
    RunItem,
    RunTraceAggregate,
    RunWorkflowStatus,
    Span,
    User,
    UserRole,
)
from qym_platform.deps import get_db
from qym_platform.security import api_key_prefix, hash_api_key


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_owner_and_run(
    session: Session,
    *,
    token: str,
    run_id: str = "00000000-0000-0000-0000-000000000001",
) -> tuple[Project, Run]:
    user = User(id="user-1", email="owner@example.com", role=UserRole.MEMBER)
    project = Project(
        id="project-1", name="Project 1", slug="project-1", created_by_user_id=user.id
    )
    api_key = ApiKey(
        id="key-1",
        user_id=user.id,
        project_id=project.id,
        name="test",
        prefix=api_key_prefix(token),
        key_hash=hash_api_key(token),
        scopes=[],
    )
    run = Run(
        id=run_id,
        project_id=project.id,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        task="trace-task",
        dataset="dataset-1",
        status=RunWorkflowStatus.RUNNING,
        metrics=[],
        run_metadata={},
        run_config={},
    )
    session.add_all([user, project, api_key, run])
    session.commit()
    return project, run


def test_store_trace_stats_omits_avg_cost():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    try:
        with SessionLocal() as session:
            user = User(id="user-1", email="owner@example.com", role=UserRole.MEMBER)
            project = Project(
                id="project-1",
                name="Project 1",
                slug="project-1",
                created_by_user_id=user.id,
            )
            run = Run(
                id="run-1",
                project_id=project.id,
                created_by_user_id=user.id,
                owner_user_id=user.id,
                task="trace-task",
                dataset="dataset-1",
                status=RunWorkflowStatus.COMPLETED,
                metrics=[],
                run_metadata={},
                run_config={},
            )
            item = RunItem(
                run_id=run.id,
                item_id="item-1",
                index=0,
                input={"prompt": "hi"},
                output={"answer": "ok"},
                item_metadata={},
                retry_count=1,
                trace_id="trace-2",
                trace_url="https://langfuse.example/trace-2",
            )
            spans = [
                Span(
                    run_id=run.id,
                    trace_id="trace-1",
                    span_id="span-llm",
                    parent_span_id=None,
                    name="openai.chat",
                    kind="CLIENT",
                    start_time_ns=1,
                    end_time_ns=2,
                    duration_ms=1.0,
                    status="OK",
                    attributes={
                        "openinference.span.kind": "LLM",
                        "llm.token_count.total": 999,
                        "llm.cost.total": 9.99,
                    },
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-2",
                    span_id="span-last-llm",
                    parent_span_id=None,
                    name="openai.chat.last",
                    kind="CLIENT",
                    start_time_ns=2,
                    end_time_ns=3,
                    duration_ms=1.0,
                    status="OK",
                    attributes={
                        "openinference.span.kind": "LLM",
                        "llm.token_count.total": 123,
                        "llm.cost.total": 0.42,
                        "llm.token_count.completion_details.reasoning": 17,
                        "gen_ai.completion.0.reasoning": "Reasoning summary",
                    },
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-2",
                    span_id="span-tool",
                    parent_span_id="span-last-llm",
                    name="tool-call",
                    kind="INTERNAL",
                    start_time_ns=3,
                    end_time_ns=4,
                    duration_ms=1.0,
                    status="OK",
                    attributes={"openinference.span.kind": "TOOL"},
                    events=[],
                ),
            ]
            session.add_all([user, project, run, item, *spans])
            session.commit()

            _store_trace_stats(session, run)
            session.commit()
            session.refresh(run)
            session.refresh(item)

            trace_stats = run.run_metadata["trace_stats"]
            assert trace_stats["avg_tokens"] == 123
            assert trace_stats["avg_llm_calls"] == 1
            assert trace_stats["avg_tool_calls"] == 1
            assert trace_stats["tool_success_rate"] == 1
            assert trace_stats["has_spans"] is True
            assert trace_stats["has_reasoning"] is True
            assert trace_stats["has_reasoning_tokens"] is True
            assert trace_stats["avg_reasoning_tokens"] == 17
            assert "avg_cost" not in trace_stats

            assert item.item_metadata["trace_stats"]["cost"] == 0.42
            assert item.item_metadata["trace_stats"]["has_reasoning"] is True
            assert item.item_metadata["trace_stats"]["reasoning_tokens"] == 17
    finally:
        engine.dispose()


def test_store_trace_stats_excludes_metric_llm_spans():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    try:
        with SessionLocal() as session:
            user = User(id="user-1", email="owner@example.com", role=UserRole.MEMBER)
            project = Project(
                id="project-1",
                name="Project 1",
                slug="project-1",
                created_by_user_id=user.id,
            )
            run = Run(
                id="run-1",
                project_id=project.id,
                created_by_user_id=user.id,
                owner_user_id=user.id,
                task="trace-task",
                dataset="dataset-1",
                status=RunWorkflowStatus.COMPLETED,
                metrics=[],
                run_metadata={},
                run_config={},
            )
            item = RunItem(
                run_id=run.id,
                item_id="item-1",
                index=0,
                input={"prompt": "hi"},
                output={"answer": "ok"},
                item_metadata={},
                trace_id="trace-1",
            )
            spans = [
                Span(
                    run_id=run.id,
                    trace_id="trace-1",
                    span_id="span-task-llm",
                    parent_span_id=None,
                    name="openai.chat.task",
                    kind="CLIENT",
                    duration_ms=1.0,
                    status="OK",
                    attributes={
                        "openinference.span.kind": "LLM",
                        "llm.token_count.total": 120,
                        "llm.token_count.completion_details.reasoning": 9,
                    },
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-1",
                    span_id="span-metric-llm",
                    parent_span_id=None,
                    name="openai.chat.metric",
                    kind="CLIENT",
                    duration_ms=1.0,
                    status="OK",
                    attributes={
                        "openinference.span.kind": "LLM",
                        "llm.token_count.total": 999,
                        "llm.token_count.completion_details.reasoning": 77,
                        "qym.usage_scope": "metric",
                    },
                    events=[],
                ),
            ]
            session.add_all([user, project, run, item, *spans])
            session.commit()

            _store_trace_stats(session, run)
            session.commit()
            session.refresh(run)
            session.refresh(item)

            trace_stats = run.run_metadata["trace_stats"]
            assert trace_stats["avg_tokens"] == 120
            assert trace_stats["avg_llm_calls"] == 1
            assert trace_stats["avg_reasoning_tokens"] == 9
            assert item.item_metadata["trace_stats"]["tokens"] == 120
            assert item.item_metadata["trace_stats"]["llm_calls"] == 1
            assert item.item_metadata["trace_stats"]["reasoning_tokens"] == 9
    finally:
        engine.dispose()


def test_store_trace_stats_excludes_eval_metrics_descendant_spans():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    try:
        with SessionLocal() as session:
            user = User(id="user-1", email="owner@example.com", role=UserRole.MEMBER)
            project = Project(
                id="project-1",
                name="Project 1",
                slug="project-1",
                created_by_user_id=user.id,
            )
            run = Run(
                id="run-1",
                project_id=project.id,
                created_by_user_id=user.id,
                owner_user_id=user.id,
                task="trace-task",
                dataset="dataset-1",
                status=RunWorkflowStatus.COMPLETED,
                metrics=[],
                run_metadata={},
                run_config={},
            )
            item = RunItem(
                run_id=run.id,
                item_id="item-1",
                index=0,
                input={"prompt": "hi"},
                output={"answer": "ok"},
                item_metadata={},
                trace_id="trace-1",
            )
            spans = [
                Span(
                    run_id=run.id,
                    trace_id="trace-1",
                    span_id="span-task-llm",
                    parent_span_id=None,
                    name="openai.chat.task",
                    kind="CLIENT",
                    duration_ms=1.0,
                    status="OK",
                    attributes={
                        "openinference.span.kind": "LLM",
                        "llm.token_count.total": 120,
                    },
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-1",
                    span_id="span-eval-metrics",
                    parent_span_id=None,
                    name="eval_metrics",
                    kind="INTERNAL",
                    duration_ms=10.0,
                    status="OK",
                    attributes={"openinference.span.kind": "EVALUATOR"},
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-1",
                    span_id="span-metric-chain",
                    parent_span_id="span-eval-metrics",
                    name="judge-chain",
                    kind="INTERNAL",
                    duration_ms=5.0,
                    status="OK",
                    attributes={"openinference.span.kind": "CHAIN"},
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-1",
                    span_id="span-metric-llm",
                    parent_span_id="span-metric-chain",
                    name="openai.chat.metric",
                    kind="CLIENT",
                    duration_ms=1.0,
                    status="OK",
                    attributes={
                        "openinference.span.kind": "LLM",
                        "llm.token_count.total": 999,
                    },
                    events=[],
                ),
            ]
            session.add_all([user, project, run, item, *spans])
            session.commit()

            _store_trace_stats(session, run)
            session.commit()
            session.refresh(run)
            session.refresh(item)

            trace_stats = run.run_metadata["trace_stats"]
            assert trace_stats["avg_tokens"] == 120
            assert trace_stats["avg_llm_calls"] == 1
            assert item.item_metadata["trace_stats"]["tokens"] == 120
            assert item.item_metadata["trace_stats"]["llm_calls"] == 1
    finally:
        engine.dispose()


def test_store_trace_stats_tracks_named_outer_scope_parent_span_averages():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    try:
        with SessionLocal() as session:
            user = User(id="user-1", email="owner@example.com", role=UserRole.MEMBER)
            project = Project(
                id="project-1",
                name="Project 1",
                slug="project-1",
                created_by_user_id=user.id,
            )
            run = Run(
                id="run-1",
                project_id=project.id,
                created_by_user_id=user.id,
                owner_user_id=user.id,
                task="trace-task",
                dataset="dataset-1",
                status=RunWorkflowStatus.COMPLETED,
                metrics=[],
                run_metadata={},
                run_config={},
            )
            item = RunItem(
                run_id=run.id,
                item_id="item-1",
                index=0,
                input={"prompt": "hi"},
                output={"answer": "ok"},
                item_metadata={},
                trace_id="trace-1",
            )
            spans = [
                Span(
                    run_id=run.id,
                    trace_id="trace-1",
                    span_id="span-item-root",
                    parent_span_id=None,
                    name="eval-spider2-lite-sqlite-item-0-attempt-1",
                    kind="INTERNAL",
                    duration_ms=41900.0,
                    status="OK",
                    attributes={"openinference.span.kind": "CHAIN"},
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-1",
                    span_id="span-task-root",
                    parent_span_id="span-item-root",
                    name="spider2_sqlite_task",
                    kind="INTERNAL",
                    duration_ms=41100.0,
                    status="OK",
                    attributes={"openinference.span.kind": "CHAIN"},
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-1",
                    span_id="span-task-llm",
                    parent_span_id="span-task-root",
                    name="ChatCompletion",
                    kind="CLIENT",
                    duration_ms=2600.0,
                    status="OK",
                    attributes={
                        "openinference.span.kind": "LLM",
                        "llm.token_count.total": 524,
                    },
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-1",
                    span_id="span-postprocess-root",
                    parent_span_id="span-item-root",
                    name="postprocess_scope",
                    kind="INTERNAL",
                    duration_ms=3000.0,
                    status="OK",
                    attributes={"openinference.span.kind": "CHAIN"},
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-1",
                    span_id="span-eval-metrics",
                    parent_span_id="span-item-root",
                    name="eval_metrics",
                    kind="INTERNAL",
                    duration_ms=739.0,
                    status="OK",
                    attributes={"openinference.span.kind": "EVALUATOR"},
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-1",
                    span_id="span-metric-llm",
                    parent_span_id="span-eval-metrics",
                    name="ChatCompletion",
                    kind="CLIENT",
                    duration_ms=9000.0,
                    status="OK",
                    attributes={
                        "openinference.span.kind": "LLM",
                        "llm.token_count.total": 99999,
                    },
                    events=[],
                ),
            ]
            session.add_all([user, project, run, item, *spans])
            session.commit()

            _store_trace_stats(session, run)
            session.commit()
            session.refresh(run)
            session.refresh(item)

            trace_stats = run.run_metadata["trace_stats"]
            assert trace_stats["avg_tokens"] == 524
            assert trace_stats["avg_llm_calls"] == 1
            assert trace_stats["avg_llm_ms"] == 2600.0
            assert trace_stats["avg_evaluator_ms"] == 739.0
            assert trace_stats["outer_scope_parent_spans"] == [
                {"name": "spider2_sqlite_task", "avg_ms": 41100.0, "count": 1},
                {"name": "postprocess_scope", "avg_ms": 3000.0, "count": 1},
            ]
            assert item.item_metadata["trace_stats"]["outer_scope_parent_spans"] == [
                {"name": "spider2_sqlite_task", "avg_ms": 41100.0, "count": 1},
                {"name": "postprocess_scope", "avg_ms": 3000.0, "count": 1},
            ]
    finally:
        engine.dispose()


def test_store_trace_stats_includes_average_span_type_latency_metrics():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    try:
        with SessionLocal() as session:
            user = User(id="user-1", email="owner@example.com", role=UserRole.MEMBER)
            project = Project(
                id="project-1",
                name="Project 1",
                slug="project-1",
                created_by_user_id=user.id,
            )
            run = Run(
                id="run-latency-metrics",
                project_id=project.id,
                created_by_user_id=user.id,
                owner_user_id=user.id,
                task="trace-task",
                dataset="dataset-1",
                status=RunWorkflowStatus.COMPLETED,
                metrics=[],
                run_metadata={},
                run_config={},
            )
            item = RunItem(
                run_id=run.id,
                item_id="item-1",
                index=0,
                input={"prompt": "hi"},
                output={"answer": "ok"},
                item_metadata={},
                retry_count=0,
                trace_id="trace-latency",
                trace_url="https://langfuse.example/trace-latency",
            )
            spans = [
                Span(
                    run_id=run.id,
                    trace_id="trace-latency",
                    span_id="span-llm",
                    parent_span_id=None,
                    name="openai.chat",
                    kind="CLIENT",
                    start_time_ns=1,
                    end_time_ns=2,
                    duration_ms=120.0,
                    status="OK",
                    attributes={
                        "openinference.span.kind": "LLM",
                        "llm.token_count.total": 123,
                    },
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-latency",
                    span_id="span-tool",
                    parent_span_id="span-llm",
                    name="tool-call",
                    kind="INTERNAL",
                    start_time_ns=2,
                    end_time_ns=3,
                    duration_ms=30.0,
                    status="OK",
                    attributes={"openinference.span.kind": "TOOL"},
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-latency",
                    span_id="span-retriever",
                    parent_span_id="span-llm",
                    name="retrieve-docs",
                    kind="INTERNAL",
                    start_time_ns=3,
                    end_time_ns=4,
                    duration_ms=45.0,
                    status="OK",
                    attributes={"openinference.span.kind": "RETRIEVER"},
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-latency",
                    span_id="span-evaluator",
                    parent_span_id="span-llm",
                    name="judge",
                    kind="INTERNAL",
                    start_time_ns=4,
                    end_time_ns=5,
                    duration_ms=12.0,
                    status="OK",
                    attributes={"openinference.span.kind": "EVALUATOR"},
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-latency",
                    span_id="span-chain-root",
                    parent_span_id=None,
                    name="graph-root",
                    kind="INTERNAL",
                    start_time_ns=5,
                    end_time_ns=6,
                    duration_ms=40.0,
                    status="OK",
                    attributes={"openinference.span.kind": "CHAIN"},
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-latency",
                    span_id="span-chain-child",
                    parent_span_id="span-chain-root",
                    name="graph-child",
                    kind="INTERNAL",
                    start_time_ns=6,
                    end_time_ns=7,
                    duration_ms=8.0,
                    status="OK",
                    attributes={"openinference.span.kind": "CHAIN"},
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-latency",
                    span_id="span-chain-orphan",
                    parent_span_id="missing-parent",
                    name="graph-orphan",
                    kind="INTERNAL",
                    start_time_ns=7,
                    end_time_ns=8,
                    duration_ms=20.0,
                    status="OK",
                    attributes={"openinference.span.kind": "CHAIN"},
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-latency",
                    span_id="span-chain-invalid",
                    parent_span_id=None,
                    name="graph-invalid",
                    kind="INTERNAL",
                    start_time_ns=8,
                    end_time_ns=9,
                    duration_ms=None,
                    status="OK",
                    attributes={"openinference.span.kind": "CHAIN"},
                    events=[],
                ),
            ]
            session.add_all([user, project, run, item, *spans])
            session.commit()

            _store_trace_stats(session, run)
            session.commit()
            session.refresh(run)
            session.refresh(item)

            trace_stats = run.run_metadata["trace_stats"]
            assert trace_stats["avg_llm_ms"] == 120.0
            assert trace_stats["avg_tool_ms"] == 30.0
            assert trace_stats["avg_retriever_ms"] == 45.0
            assert trace_stats["avg_evaluator_ms"] == 12.0
            assert trace_stats["avg_top_level_chain_ms"] == 30.0

            item_trace_stats = item.item_metadata["trace_stats"]
            assert item_trace_stats["avg_llm_ms"] == 120.0
            assert item_trace_stats["avg_tool_ms"] == 30.0
            assert item_trace_stats["avg_retriever_ms"] == 45.0
            assert item_trace_stats["avg_evaluator_ms"] == 12.0
            assert item_trace_stats["avg_top_level_chain_ms"] == 30.0
    finally:
        engine.dispose()


def test_store_trace_stats_counts_malformed_tool_call_as_tool_error():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    try:
        with SessionLocal() as session:
            user = User(id="user-1", email="owner@example.com", role=UserRole.MEMBER)
            project = Project(
                id="project-1",
                name="Project 1",
                slug="project-1",
                created_by_user_id=user.id,
            )
            run = Run(
                id="run-malformed",
                project_id=project.id,
                created_by_user_id=user.id,
                owner_user_id=user.id,
                task="trace-task",
                dataset="dataset-1",
                status=RunWorkflowStatus.COMPLETED,
                metrics=[],
                run_metadata={},
                run_config={},
            )
            item = RunItem(
                run_id=run.id,
                item_id="item-1",
                index=0,
                input={"prompt": "hi"},
                output={"answer": None},
                item_metadata={},
                retry_count=1,
                trace_id="trace-malformed",
                trace_url="https://langfuse.example/trace-malformed",
            )
            span = Span(
                run_id=run.id,
                trace_id="trace-malformed",
                span_id="span-llm-malformed",
                parent_span_id=None,
                name="openai.chat",
                kind="CLIENT",
                start_time_ns=1,
                end_time_ns=2,
                duration_ms=1.0,
                status="ERROR",
                attributes={
                    "openinference.span.kind": "LLM",
                    "qym.response.classification": "malformed_tool_call",
                    "qym.response.where": "content",
                },
                events=[],
            )
            session.add_all([user, project, run, item, span])
            session.commit()

            _store_trace_stats(session, run)
            session.commit()
            session.refresh(run)
            session.refresh(item)

            trace_stats = run.run_metadata["trace_stats"]
            assert trace_stats["tool_success_rate"] == 0
            assert trace_stats["total_malformed_tool_calls"] == 1

            item_trace_stats = item.item_metadata["trace_stats"]
            assert item_trace_stats["tool_calls"] == 0
            assert item_trace_stats["tool_errors"] == 1
            assert item_trace_stats["malformed_tool_calls"] == 1
    finally:
        engine.dispose()


def test_store_trace_stats_includes_malformed_tool_calls_in_success_denominator():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    try:
        with SessionLocal() as session:
            user = User(id="user-1", email="owner@example.com", role=UserRole.MEMBER)
            project = Project(
                id="project-1",
                name="Project 1",
                slug="project-1",
                created_by_user_id=user.id,
            )
            run = Run(
                id="run-mixed-tool-attempts",
                project_id=project.id,
                created_by_user_id=user.id,
                owner_user_id=user.id,
                task="trace-task",
                dataset="dataset-1",
                status=RunWorkflowStatus.COMPLETED,
                metrics=[],
                run_metadata={},
                run_config={},
            )
            item = RunItem(
                run_id=run.id,
                item_id="item-1",
                index=0,
                input={"prompt": "hi"},
                output={"answer": "partial"},
                item_metadata={},
                retry_count=1,
                trace_id="trace-mixed-tool-attempts",
                trace_url="https://langfuse.example/trace-mixed-tool-attempts",
            )
            spans = [
                Span(
                    run_id=run.id,
                    trace_id="trace-mixed-tool-attempts",
                    span_id="span-llm-malformed",
                    parent_span_id=None,
                    name="openai.chat",
                    kind="CLIENT",
                    start_time_ns=1,
                    end_time_ns=2,
                    duration_ms=1.0,
                    status="ERROR",
                    attributes={
                        "openinference.span.kind": "LLM",
                        "qym.response.classification": "malformed_tool_call",
                        "qym.response.where": "reasoning",
                    },
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-mixed-tool-attempts",
                    span_id="span-tool-success",
                    parent_span_id="span-llm-malformed",
                    name="tool-call",
                    kind="INTERNAL",
                    start_time_ns=2,
                    end_time_ns=3,
                    duration_ms=1.0,
                    status="OK",
                    attributes={"openinference.span.kind": "TOOL"},
                    events=[],
                ),
            ]
            session.add_all([user, project, run, item, *spans])
            session.commit()

            _store_trace_stats(session, run)
            session.commit()
            session.refresh(run)
            session.refresh(item)

            trace_stats = run.run_metadata["trace_stats"]
            assert trace_stats["avg_tool_calls"] == 1
            assert trace_stats["tool_success_rate"] == 0.5

            item_trace_stats = item.item_metadata["trace_stats"]
            assert item_trace_stats["tool_calls"] == 1
            assert item_trace_stats["tool_errors"] == 1
            assert item_trace_stats["malformed_tool_calls"] == 1
    finally:
        engine.dispose()


def test_store_trace_stats_counts_response_classification_on_agent_spans():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    try:
        with SessionLocal() as session:
            user = User(id="user-1", email="owner@example.com", role=UserRole.MEMBER)
            project = Project(
                id="project-1",
                name="Project 1",
                slug="project-1",
                created_by_user_id=user.id,
            )
            run = Run(
                id="run-agent-classification",
                project_id=project.id,
                created_by_user_id=user.id,
                owner_user_id=user.id,
                task="trace-task",
                dataset="dataset-1",
                status=RunWorkflowStatus.COMPLETED,
                metrics=[],
                run_metadata={},
                run_config={},
            )
            item = RunItem(
                run_id=run.id,
                item_id="item-1",
                index=0,
                input={"prompt": "hi"},
                output={"answer": None},
                item_metadata={},
                retry_count=1,
                trace_id="trace-agent-classification",
                trace_url="https://langfuse.example/trace-agent-classification",
            )
            spans = [
                Span(
                    run_id=run.id,
                    trace_id="trace-agent-classification",
                    span_id="span-agent",
                    parent_span_id=None,
                    name="sql_agent_task_async",
                    kind="INTERNAL",
                    start_time_ns=1,
                    end_time_ns=4,
                    duration_ms=3.0,
                    status="ERROR",
                    attributes={
                        "openinference.span.kind": "AGENT",
                        "qym.response.classification": "malformed_tool_call",
                        "qym.response.where": "reasoning",
                    },
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-agent-classification",
                    span_id="span-llm",
                    parent_span_id="span-agent",
                    name="ChatCompletion",
                    kind="INTERNAL",
                    start_time_ns=2,
                    end_time_ns=3,
                    duration_ms=1.0,
                    status="OK",
                    attributes={
                        "openinference.span.kind": "LLM",
                        "llm.token_count.total": 42,
                    },
                    events=[],
                ),
            ]
            session.add_all([user, project, run, item, *spans])
            session.commit()

            _store_trace_stats(session, run)
            session.commit()
            session.refresh(run)
            session.refresh(item)

            trace_stats = run.run_metadata["trace_stats"]
            assert trace_stats["tool_success_rate"] == 0
            assert trace_stats["total_malformed_tool_calls"] == 1

            item_trace_stats = item.item_metadata["trace_stats"]
            assert item_trace_stats["llm_calls"] == 1
            assert item_trace_stats["tool_calls"] == 0
            assert item_trace_stats["tool_errors"] == 1
            assert item_trace_stats["malformed_tool_calls"] == 1
    finally:
        engine.dispose()


def test_live_trace_stats_update_before_run_completed():
    run_id = "00000000-0000-0000-0000-000000000101"
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    app = create_app()

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        with SessionLocal() as session:
            _seed_owner_and_run(session, token="test-token", run_id=run_id)

        body = (
            "\n".join(
                [
                    (
                        '{"schema_version":1,"event_id":"00000000-0000-0000-0000-000000000011",'
                        '"sequence":1,"sent_at":"2026-04-10T00:00:00Z","type":"item_started",'
                        f'"run_id":"{run_id}","payload":{{"item_id":"item-1","index":0,"input":{{"prompt":"hi"}},'
                        '"expected":null,"item_metadata":{}}}'
                    ),
                    (
                        '{"schema_version":1,"event_id":"00000000-0000-0000-0000-000000000012",'
                        '"sequence":2,"sent_at":"2026-04-10T00:00:00Z","type":"item_attempt_started",'
                        f'"run_id":"{run_id}","payload":{{"item_id":"item-1","index":0,"attempt_number":1,'
                        '"trace_id":"trace-1","trace_url":"https://langfuse.example/trace-1","task_started_at_ms":1234}}'
                    ),
                    (
                        '{"schema_version":1,"event_id":"00000000-0000-0000-0000-000000000013",'
                        '"sequence":3,"sent_at":"2026-04-10T00:00:01Z","type":"span_completed",'
                        f'"run_id":"{run_id}","payload":{{"trace_id":"trace-1","span_id":"span-1","parent_span_id":null,'
                        '"name":"openai.chat","kind":"CLIENT","start_time_ns":1,"end_time_ns":2,"duration_ms":1.0,'
                        '"status":"OK","attributes":{"openinference.span.kind":"LLM","llm.token_count.total":120,'
                        '"llm.cost.total":0.3,"llm.token_count.completion_details.reasoning":9,'
                        '"gen_ai.completion.0.reasoning":"Reasoning summary"},"events":[],"links":[]}}'
                    ),
                    (
                        '{"schema_version":1,"event_id":"00000000-0000-0000-0000-000000000014",'
                        '"sequence":4,"sent_at":"2026-04-10T00:00:02Z","type":"span_completed",'
                        f'"run_id":"{run_id}","payload":{{"trace_id":"trace-1","span_id":"span-metric","parent_span_id":null,'
                        '"name":"openai.chat.metric","kind":"CLIENT","start_time_ns":3,"end_time_ns":4,"duration_ms":1.0,'
                        '"status":"OK","attributes":{"openinference.span.kind":"LLM","llm.token_count.total":999,'
                        '"llm.token_count.completion_details.reasoning":77,"qym.usage_scope":"metric"},'
                        '"events":[],"links":[]}}'
                    ),
                ]
            )
            + "\n"
        )

        with TestClient(app) as client:
            ingest_response = client.post(
                f"/v1/runs/{run_id}/events",
                headers={
                    **_auth_headers("test-token"),
                    "Content-Type": "application/x-ndjson",
                },
                content=body,
            )
            assert ingest_response.status_code == 200

        with SessionLocal() as session:
            run = session.query(Run).filter(Run.id == run_id).first()
            item = (
                session.query(RunItem)
                .filter(RunItem.run_id == run_id, RunItem.item_id == "item-1")
                .first()
            )
            agg = (
                session.query(RunTraceAggregate)
                .filter(
                    RunTraceAggregate.run_id == run_id,
                    RunTraceAggregate.trace_id == "trace-1",
                )
                .first()
            )

            assert run is not None
            assert item is not None
            assert agg is not None
            assert run.run_metadata["trace_stats"]["avg_tokens"] == 120
            assert run.run_metadata["trace_stats"]["avg_llm_calls"] == 1
            assert run.run_metadata["trace_stats"]["has_reasoning"] is True
            assert run.run_metadata["trace_stats"]["has_reasoning_tokens"] is True
            assert run.run_metadata["trace_stats"]["avg_reasoning_tokens"] == 9
            assert item.item_metadata["trace_stats"]["tokens"] == 120
            assert item.item_metadata["trace_stats"]["reasoning_tokens"] == 9
            assert agg.tokens == 120
            assert agg.reasoning_tokens == 9
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_live_trace_stats_match_final_store_for_latency_metrics():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    try:
        with SessionLocal() as session:
            user = User(id="user-1", email="owner@example.com", role=UserRole.MEMBER)
            project = Project(
                id="project-1",
                name="Project 1",
                slug="project-1",
                created_by_user_id=user.id,
            )
            run = Run(
                id="run-live-final-match",
                project_id=project.id,
                created_by_user_id=user.id,
                owner_user_id=user.id,
                task="trace-task",
                dataset="dataset-1",
                status=RunWorkflowStatus.RUNNING,
                metrics=[],
                run_metadata={},
                run_config={},
            )
            item = RunItem(
                run_id=run.id,
                item_id="item-1",
                index=0,
                input={"prompt": "hi"},
                output={"answer": "ok"},
                item_metadata={},
                retry_count=0,
                trace_id="trace-live-final",
                trace_url="https://langfuse.example/trace-live-final",
            )
            spans = [
                Span(
                    run_id=run.id,
                    trace_id="trace-live-final",
                    span_id="span-llm",
                    parent_span_id=None,
                    name="openai.chat",
                    kind="CLIENT",
                    start_time_ns=1,
                    end_time_ns=2,
                    duration_ms=90.0,
                    status="OK",
                    attributes={
                        "openinference.span.kind": "LLM",
                        "llm.token_count.total": 50,
                    },
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-live-final",
                    span_id="span-tool",
                    parent_span_id="span-llm",
                    name="tool-call",
                    kind="INTERNAL",
                    start_time_ns=2,
                    end_time_ns=3,
                    duration_ms=15.0,
                    status="OK",
                    attributes={"openinference.span.kind": "TOOL"},
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-live-final",
                    span_id="span-chain-root",
                    parent_span_id=None,
                    name="graph-root",
                    kind="INTERNAL",
                    start_time_ns=3,
                    end_time_ns=4,
                    duration_ms=18.0,
                    status="OK",
                    attributes={"openinference.span.kind": "CHAIN"},
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-live-final",
                    span_id="span-chain-child",
                    parent_span_id="span-chain-root",
                    name="graph-child",
                    kind="INTERNAL",
                    start_time_ns=4,
                    end_time_ns=5,
                    duration_ms=6.0,
                    status="OK",
                    attributes={"openinference.span.kind": "CHAIN"},
                    events=[],
                ),
            ]
            session.add_all([user, project, run, item, *spans])
            session.commit()

            _refresh_live_trace_stats(session, run)
            session.commit()
            session.refresh(run)
            session.refresh(item)
            live_run_trace_stats = dict(run.run_metadata["trace_stats"])
            live_item_trace_stats = dict(item.item_metadata["trace_stats"])

            _store_trace_stats(session, run)
            session.commit()
            session.refresh(run)
            session.refresh(item)

            for key in (
                "avg_tokens",
                "avg_llm_calls",
                "avg_tool_calls",
                "avg_llm_ms",
                "avg_tool_ms",
                "avg_top_level_chain_ms",
            ):
                assert run.run_metadata["trace_stats"][key] == live_run_trace_stats[key]

            for key in (
                "tokens",
                "llm_calls",
                "tool_calls",
                "avg_llm_ms",
                "avg_tool_ms",
                "avg_top_level_chain_ms",
            ):
                assert (
                    item.item_metadata["trace_stats"][key] == live_item_trace_stats[key]
                )
    finally:
        engine.dispose()


def test_live_trace_stats_switch_to_new_attempt_trace():
    run_id = "00000000-0000-0000-0000-000000000102"
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    app = create_app()

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        with SessionLocal() as session:
            _seed_owner_and_run(session, token="retry-token", run_id=run_id)

        body = (
            "\n".join(
                [
                    (
                        '{"schema_version":1,"event_id":"00000000-0000-0000-0000-000000000021",'
                        '"sequence":1,"sent_at":"2026-04-10T00:00:00Z","type":"item_started",'
                        f'"run_id":"{run_id}","payload":{{"item_id":"item-1","index":0,"input":{{"prompt":"hi"}},'
                        '"expected":null,"item_metadata":{}}}'
                    ),
                    (
                        '{"schema_version":1,"event_id":"00000000-0000-0000-0000-000000000022",'
                        '"sequence":2,"sent_at":"2026-04-10T00:00:00Z","type":"item_attempt_started",'
                        f'"run_id":"{run_id}","payload":{{"item_id":"item-1","index":0,"attempt_number":1,'
                        '"trace_id":"trace-1","trace_url":"https://langfuse.example/trace-1","task_started_at_ms":1000}}'
                    ),
                    (
                        '{"schema_version":1,"event_id":"00000000-0000-0000-0000-000000000023",'
                        '"sequence":3,"sent_at":"2026-04-10T00:00:01Z","type":"span_completed",'
                        f'"run_id":"{run_id}","payload":{{"trace_id":"trace-1","span_id":"span-1","parent_span_id":null,'
                        '"name":"openai.chat.1","kind":"CLIENT","start_time_ns":1,"end_time_ns":2,"duration_ms":1.0,'
                        '"status":"OK","attributes":{"openinference.span.kind":"LLM","llm.token_count.total":120},'
                        '"events":[],"links":[]}}'
                    ),
                    (
                        '{"schema_version":1,"event_id":"00000000-0000-0000-0000-000000000024",'
                        '"sequence":4,"sent_at":"2026-04-10T00:00:02Z","type":"item_attempt_started",'
                        f'"run_id":"{run_id}","payload":{{"item_id":"item-1","index":0,"attempt_number":2,'
                        '"trace_id":"trace-2","trace_url":"https://langfuse.example/trace-2","task_started_at_ms":2000}}'
                    ),
                    (
                        '{"schema_version":1,"event_id":"00000000-0000-0000-0000-000000000025",'
                        '"sequence":5,"sent_at":"2026-04-10T00:00:03Z","type":"span_completed",'
                        f'"run_id":"{run_id}","payload":{{"trace_id":"trace-2","span_id":"span-2","parent_span_id":null,'
                        '"name":"openai.chat.2","kind":"CLIENT","start_time_ns":2,"end_time_ns":3,"duration_ms":1.0,'
                        '"status":"OK","attributes":{"openinference.span.kind":"LLM","llm.token_count.total":30},'
                        '"events":[],"links":[]}}'
                    ),
                ]
            )
            + "\n"
        )

        with TestClient(app) as client:
            ingest_response = client.post(
                f"/v1/runs/{run_id}/events",
                headers={
                    **_auth_headers("retry-token"),
                    "Content-Type": "application/x-ndjson",
                },
                content=body,
            )
            assert ingest_response.status_code == 200

        with SessionLocal() as session:
            run = session.query(Run).filter(Run.id == run_id).first()
            item = (
                session.query(RunItem)
                .filter(RunItem.run_id == run_id, RunItem.item_id == "item-1")
                .first()
            )

            assert run is not None
            assert item is not None
            assert item.trace_id == "trace-2"
            assert run.run_metadata["trace_stats"]["avg_tokens"] == 30
            assert item.item_metadata["trace_stats"]["tokens"] == 30
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_duplicate_span_event_does_not_double_count_live_trace_stats():
    run_id = "00000000-0000-0000-0000-000000000103"
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    app = create_app()

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        with SessionLocal() as session:
            _seed_owner_and_run(session, token="dup-token", run_id=run_id)

        body = (
            "\n".join(
                [
                    (
                        '{"schema_version":1,"event_id":"00000000-0000-0000-0000-000000000031",'
                        '"sequence":1,"sent_at":"2026-04-10T00:00:00Z","type":"item_started",'
                        f'"run_id":"{run_id}","payload":{{"item_id":"item-1","index":0,"input":{{"prompt":"hi"}},'
                        '"expected":null,"item_metadata":{}}}'
                    ),
                    (
                        '{"schema_version":1,"event_id":"00000000-0000-0000-0000-000000000032",'
                        '"sequence":2,"sent_at":"2026-04-10T00:00:00Z","type":"item_attempt_started",'
                        f'"run_id":"{run_id}","payload":{{"item_id":"item-1","index":0,"attempt_number":1,'
                        '"trace_id":"trace-1","trace_url":"https://langfuse.example/trace-1","task_started_at_ms":1000}}'
                    ),
                    (
                        '{"schema_version":1,"event_id":"00000000-0000-0000-0000-000000000033",'
                        '"sequence":3,"sent_at":"2026-04-10T00:00:01Z","type":"span_completed",'
                        f'"run_id":"{run_id}","payload":{{"trace_id":"trace-1","span_id":"span-1","parent_span_id":null,'
                        '"name":"openai.chat","kind":"CLIENT","start_time_ns":1,"end_time_ns":2,"duration_ms":1.0,'
                        '"status":"OK","attributes":{"openinference.span.kind":"LLM","llm.token_count.total":77},'
                        '"events":[],"links":[]}}'
                    ),
                    (
                        '{"schema_version":1,"event_id":"00000000-0000-0000-0000-000000000034",'
                        '"sequence":4,"sent_at":"2026-04-10T00:00:02Z","type":"span_completed",'
                        f'"run_id":"{run_id}","payload":{{"trace_id":"trace-1","span_id":"span-1","parent_span_id":null,'
                        '"name":"openai.chat","kind":"CLIENT","start_time_ns":1,"end_time_ns":2,"duration_ms":1.0,'
                        '"status":"OK","attributes":{"openinference.span.kind":"LLM","llm.token_count.total":77},'
                        '"events":[],"links":[]}}'
                    ),
                ]
            )
            + "\n"
        )

        with TestClient(app) as client:
            ingest_response = client.post(
                f"/v1/runs/{run_id}/events",
                headers={
                    **_auth_headers("dup-token"),
                    "Content-Type": "application/x-ndjson",
                },
                content=body,
            )
            assert ingest_response.status_code == 200

        with SessionLocal() as session:
            run = session.query(Run).filter(Run.id == run_id).first()
            agg = (
                session.query(RunTraceAggregate)
                .filter(
                    RunTraceAggregate.run_id == run_id,
                    RunTraceAggregate.trace_id == "trace-1",
                )
                .first()
            )

            assert run is not None
            assert agg is not None
            assert agg.span_count == 1
            assert agg.tokens == 77
            assert run.run_metadata["trace_stats"]["avg_tokens"] == 77
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
