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

from qym_platform.api.runs import _build_run_data
from qym_platform.db.base import Base
from qym_platform.db.models import Project, Run, RunItem, RunWorkflowStatus, User, UserRole


def test_build_run_data_includes_hero_fields():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    try:
        with SessionLocal() as session:
            owner = User(
                id="user-1",
                email="owner@example.com",
                display_name="Owner User",
                role=UserRole.MEMBER,
            )
            project = Project(
                id="project-1",
                name="Platform",
                slug="platform",
                created_by_user_id=owner.id,
            )
            run = Run(
                id="run-1",
                project_id=project.id,
                external_run_id="ext-run-1",
                created_by_user_id=owner.id,
                owner_user_id=owner.id,
                task="sql_eval",
                dataset="dataset-1",
                model="openai/gpt-4o-mini",
                metrics=["valid_sql"],
                run_metadata={"langfuse_url": "https://cloud.langfuse.com/project/proj-1/datasets/ds"},
                run_config={"run_name": "Nightly SQL Eval", "git_branch": "main", "git_commit": "abc123"},
                status=RunWorkflowStatus.COMPLETED,
            )
            run.started_at = run.created_at
            item = RunItem(
                run_id=run.id,
                item_id="item-1",
                index=0,
                input={"prompt": "hi"},
                expected={"answer": "ok"},
                output={"answer": "ok"},
                item_metadata={},
                latency_ms=123.0,
            )
            session.add_all([owner, project, run, item])
            session.commit()

            payload = _build_run_data(session, run)
            run_payload = payload["run"]

            assert run_payload["run_id"] == "run-1"
            assert run_payload["run_name"] == "Nightly SQL Eval"
            assert run_payload["external_run_id"] == "ext-run-1"
            assert run_payload["task_name"] == "sql_eval"
            assert run_payload["dataset_name"] == "dataset-1"
            assert run_payload["model_name"] == "gpt-4o-mini"
            assert run_payload["owner"]["display_name"] == "Owner User"
            assert run_payload["team_name"] == "Platform"
            assert run_payload["git_branch"] == "main"
            assert run_payload["git_commit"] == "abc123"
            assert run_payload["started_at"]
            assert run_payload["created_at"]
            assert run_payload["started_at"].endswith("Z")
            assert run_payload["created_at"].endswith("Z")
    finally:
        engine.dispose()
