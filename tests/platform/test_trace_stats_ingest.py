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
from qym_platform.db.models import Run, RunItem, RunWorkflowStatus, Span, User, UserRole


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
            user = User(id="user-1", email="owner@example.com", role=UserRole.EMPLOYEE)
            run = Run(
                id="run-1",
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
                trace_url="https://langfuse.example/trace-1",
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
                        "llm.token_count.total": 123,
                        "llm.cost.total": 0.42,
                    },
                    events=[],
                ),
                Span(
                    run_id=run.id,
                    trace_id="trace-1",
                    span_id="span-tool",
                    parent_span_id="span-llm",
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
            session.add_all([user, run, item, *spans])
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
            assert "avg_cost" not in trace_stats

            assert item.item_metadata["trace_stats"]["cost"] == 0.42
    finally:
        engine.dispose()
