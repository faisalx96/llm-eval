from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")
ROOT = Path(__file__).resolve().parents[2]
PLATFORM_SRC = ROOT / "packages" / "platform"
if str(PLATFORM_SRC) not in sys.path:
    sys.path.insert(0, str(PLATFORM_SRC))
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

from qym_platform.api.ingest import _store_trace_stats
from qym_platform.db.base import Base
from qym_platform.db.models import Project, Run, RunItem, RunWorkflowStatus, Span, User, UserRole


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
            project = Project(id="project-1", name="Project 1", slug="project-1", created_by_user_id=user.id)
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
