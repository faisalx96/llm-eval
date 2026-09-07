"""Local ingestion comparison with identical dependencies and fresh databases.

Run from /tmp with PYTHON_DOTENV_DISABLED=1 and PYTHONPATH pointing at either
checkout. The same script supports the baseline async route and the new sync
worker body. No HTTP server or external provider is called.
"""

import asyncio
import collections
import json
import os
import platform
import statistics
import sys
import time
import uuid

import sqlalchemy
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from starlette.requests import Request

from qym_platform.api import ingest
from qym_platform.auth import Principal
from qym_platform.db.base import Base
from qym_platform.db.models import Project, Run, RunWorkflowStatus, User, UserRole


async def invoke(run_id, body, db, principal):
    if hasattr(ingest, "_ingest_events_sync"):
        return ingest._ingest_events_sync(run_id, body, db, principal)

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request({"type": "http", "method": "POST", "path": "/"}, receive)
    return await ingest.ingest_events(run_id, request, db, principal)


def sample(kind, count):
    postgres_url = os.environ.get("QYM_BENCH_POSTGRES_URL")
    schema = "qym_benchmark_" + uuid.uuid4().hex
    admin = None
    if postgres_url:
        admin = create_engine(postgres_url)
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(
            postgres_url, connect_args={"options": f"-csearch_path={schema}"}
        )
    else:
        engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine, autoflush=False) as db:
            owner = User(id="owner", email="x@example.invalid", role=UserRole.ADMIN)
            db.add(owner)
            db.flush()
            project = Project(
                id="project", name="Project", slug="project", created_by_user_id="owner"
            )
            db.add(project)
            db.flush()
            run = Run(
                id=str(uuid.uuid4()),
                project_id="project",
                created_by_user_id="owner",
                owner_user_id="owner",
                task="benchmark",
                dataset="test",
                metrics=[],
                status=RunWorkflowStatus.RUNNING,
                run_config={},
                run_metadata={},
            )
            db.add(run)
            db.commit()
            rid = run.id
            principal = Principal(user=owner, auth_type="none")
            body = b"\n".join(
                json.dumps(
                    dict(
                        schema_version=1,
                        run_id=rid,
                        event_id=str(uuid.uuid4()),
                        sequence=i + 1,
                        type=kind,
                        sent_at="2026-09-05T00:00:00Z",
                        payload=(
                            {"item_id": str(i), "index": i, "input": "test"}
                            if kind == "item_started"
                            else {
                                "trace_id": "trace-0",
                                "span_id": f"span-{i}",
                                "name": "span",
                                "duration_ms": 1,
                                "attributes": {},
                            }
                        ),
                    )
                ).encode()
                for i in range(count)
            )
            counts = collections.Counter()

            def record(conn, cursor, statement, *args):
                counts[statement.split()[0].upper()] += 1

            event.listen(engine, "before_cursor_execute", record)
            start = time.perf_counter()
            result = asyncio.run(invoke(rid, body, db, principal))
            elapsed = time.perf_counter() - start
            event.remove(engine, "before_cursor_execute", record)
            assert json.loads(result.body)["applied"] == count
            return elapsed * 1000, dict(counts)
    finally:
        engine.dispose()
        if admin:
            with admin.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


if __name__ == "__main__":
    for kind in ["item_started", "span_completed"]:
        for count in [100, 1000]:
            samples = [sample(kind, count) for _ in range(3)]
            print(
                json.dumps(
                    dict(
                        event=kind,
                        events=count,
                        median_ms=round(statistics.median(s[0] for s in samples), 2),
                        samples_ms=[round(s[0], 2) for s in samples],
                        sql_samples=[s[1] for s in samples],
                        dashboard_hooks_enabled=(
                            "dashboard_change_events" in Base.metadata.tables
                        ),
                        backend=(
                            "postgresql"
                            if os.environ.get("QYM_BENCH_POSTGRES_URL")
                            else "sqlite"
                        ),
                        source=ingest.__file__,
                        python_executable=sys.executable,
                        python_version=platform.python_version(),
                        sqlalchemy_version=sqlalchemy.__version__,
                        handler=(
                            "_ingest_events_sync"
                            if hasattr(ingest, "_ingest_events_sync")
                            else "ingest_events"
                        ),
                    )
                ),
                flush=True,
            )
