"""Full-chain PostgreSQL migration and real ASGI worker lifecycle validation."""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from qym_platform.db.dashboard_models import DashboardRunDimension, DashboardRunSummary
from qym_platform.db.models import (
    Project,
    ProjectAnalysisCategoryCatalogVersion,
    ReviewCorrection,
    Run,
    RunEvent,
    RunItem,
    RunItemScore,
    RunWorkflowStatus,
    User,
    UserRole,
)

MIGRATIONS = (
    Path(__file__).resolve().parents[2] / "packages/platform/qym_platform/migrations"
)


@pytest.fixture
def postgres(request, monkeypatch):
    url = os.environ.get("QYM_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("QYM_TEST_POSTGRES_URL not configured")
    schema = "qym_migration_lifecycle_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = make_url(url).update_query_dict({"options": f"-csearch_path={schema}"})
    engine = create_engine(scoped)
    monkeypatch.setenv("QYM_DATABASE_URL", scoped.render_as_string(hide_password=False))
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))

    def cleanup():
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()

    request.addfinalizer(cleanup)
    return engine, config


def seed(engine, *, before_dashboard=False):
    with Session(engine) as db:
        if before_dashboard:
            db.info["dashboard_projection_worker"] = True
        db.add(User(id="owner", email="owner@example.invalid", role=UserRole.ADMIN))
        db.flush()
        db.add(
            Project(
                id="project", name="Project", slug="project", created_by_user_id="owner"
            )
        )
        db.flush()
        db.add(
            Run(
                id="run",
                project_id="project",
                owner_user_id="owner",
                created_by_user_id="owner",
                task="test",
                dataset="test",
                model=None,
                metrics=["quality"],
                run_config={},
                run_metadata={"total_items": 1},
                status=RunWorkflowStatus.COMPLETED,
                created_at=datetime.now(),
                started_at=datetime.now(),
                last_event_at=datetime.now(),
            )
        )
        db.flush()
        db.add(
            ProjectAnalysisCategoryCatalogVersion(
                id="catalog",
                project_id="project",
                version=1,
                content_hash="f" * 64,
                subcategory_taxonomy={
                    "reasoning": {"math": {"label": "Math", "description": "Preserve"}}
                },
            )
        )
        db.add(
            ReviewCorrection(
                run_id="run",
                item_id="item",
                task="test",
                ai_root_cause="reasoning",
                human_root_cause="reasoning",
                ai_root_cause_issues=[
                    {"category": "reasoning", "subcategory": "math", "finding": "AI"}
                ],
                human_root_cause_issues=[
                    {"category": "reasoning", "subcategory": "math", "finding": "Human"}
                ],
            )
        )
        db.add(
            RunItem(
                run_id="run",
                item_id="item",
                input={"preserve": "source"},
                output="original",
                latency_ms=12,
            )
        )
        db.add(
            RunItemScore(
                run_id="run", item_id="item", metric_name="quality", score_numeric=0.75
            )
        )
        db.add(
            RunEvent(
                run_id="run",
                event_id=str(uuid4()),
                sequence=1,
                sent_at=datetime.now(),
                type="item_completed",
                payload={"preserve": True},
            )
        )
        db.commit()


def source_snapshot(engine):
    with Session(engine) as db:
        source = db.scalar(select(RunItem))
        return {
            "run": db.get(Run, "run").id,
            "input": source.input,
            "output": source.output,
            "score": db.scalar(select(RunItemScore.score_numeric)),
            "event": db.scalar(select(RunEvent.payload)),
            "subcategory_taxonomy": db.scalar(
                select(ProjectAnalysisCategoryCatalogVersion.subcategory_taxonomy)
            ),
            "ai_root_cause_issues": db.scalar(
                select(ReviewCorrection.ai_root_cause_issues)
            ),
            "human_root_cause_issues": db.scalar(
                select(ReviewCorrection.human_root_cause_issues)
            ),
        }


@pytest.mark.parametrize("populated", [False, True])
def test_postgres_full_chain_upgrade_p1_downgrade_reupgrade(postgres, populated):
    engine, config = postgres
    command.upgrade(config, "0046")
    if populated:
        seed(engine, before_dashboard=True)
        expected = source_snapshot(engine)
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert (
            connection.scalar(text("select version_num from alembic_version")) == "0048"
        )
        inspector = inspect(connection)
        assert "ix_dashboard_event_retention" in {
            row["name"] for row in inspector.get_indexes("dashboard_change_events")
        }
        assert "ix_dashboard_record_retention" in {
            row["name"] for row in inspector.get_indexes("dashboard_record_state")
        }
        tables = set(inspector.get_table_names())
        assert {
            "run_trace_summaries",
            "dashboard_run_summaries",
            "dashboard_partition_state",
        } <= tables
    if populated:
        assert source_snapshot(engine) == expected
        from qym_platform.db.dashboard_models import DashboardPartitionState

        with Session(engine) as db:
            partition = db.get(DashboardPartitionState, "run")
            assert partition and not partition.backfill_complete
    command.downgrade(config, "0046")
    with engine.connect() as connection:
        assert (
            connection.scalar(text("select version_num from alembic_version")) == "0046"
        )
        tables = set(inspect(connection).get_table_names())
        assert (
            "run_trace_summaries" not in tables
            and "dashboard_run_summaries" not in tables
        )
    if populated:
        assert source_snapshot(engine) == expected
    command.upgrade(config, "head")
    if populated:
        assert source_snapshot(engine) == expected


def test_real_application_starts_projects_restarts_and_stops_worker(
    postgres, monkeypatch
):
    engine, config = postgres
    command.upgrade(config, "head")
    from qym_platform.app import create_app
    from qym_platform.db import session as db_session
    from qym_platform.settings import PlatformSettings

    monkeypatch.setattr(
        db_session, "SessionLocal", sessionmaker(bind=engine, autoflush=False)
    )
    seed(engine)
    app = create_app(PlatformSettings(environment="test", auth_mode="none"))
    worker = app.state.dashboard_summary_worker
    worker.interval = 0.02

    def wait_for_output(expected):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with Session(engine) as db:
                summary = db.get(DashboardRunSummary, "run")
                if (
                    summary
                    and summary.data.get("metric_averages", {}).get("quality")
                    == expected
                ):
                    assert (
                        db.get(DashboardRunDimension, "run").model == "nomodel|||plain"
                    )
                    return
            time.sleep(0.02)
        raise AssertionError("application worker did not publish source change")

    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert worker._thread is not None and worker._thread.is_alive()
        wait_for_output(0.75)
        first_thread = worker._thread
    assert not first_thread.is_alive()
    # A stopped process leaves durable queued changes for its replacement.
    with Session(engine) as db:
        db.scalar(select(RunItemScore)).score_numeric = 0.25
        db.commit()
    with TestClient(app):
        assert worker._thread is not first_thread and worker._thread.is_alive()
        wait_for_output(0.25)
    assert not worker._thread.is_alive()
    assert engine.pool.checkedout() == 0
