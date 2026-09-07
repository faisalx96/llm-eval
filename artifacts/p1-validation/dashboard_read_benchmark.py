"""Compare old browser history reads with the projected first page.

Use an isolated SQLite database and real HTTP handlers. Projection setup is
excluded: summaries are copied from the legacy oracle, whose parity with the
worker is tested separately. This measures read cost, not backfill cost.
"""

import collections
import json
import statistics
import time
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from qym_platform.api import dashboard, runs
from qym_platform.auth import Principal, require_ui_principal
from qym_platform.db.base import Base
from qym_platform.db.dashboard_models import DashboardRunDimension, DashboardRunSummary
from qym_platform.db.models import Project, Run, RunItem, RunItemScore, User, UserRole
from qym_platform.deps import get_db


def benchmark(run_count=1000, items_per_run=50):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add(User(id="owner", email="bench@example.invalid", role=UserRole.ADMIN))
        db.flush()
        db.add(
            Project(
                id="project", slug="bench", name="Benchmark", created_by_user_id="owner"
            )
        )
        db.flush()
        run_rows, item_rows, score_rows = [], [], []
        for i in range(run_count):
            rid = f"run-{i:05}"
            stamp = datetime(2026, 8, 1) + timedelta(minutes=i)
            run_rows.append(
                dict(
                    id=rid,
                    project_id="project",
                    created_by_user_id="owner",
                    owner_user_id="owner",
                    task=f"task-{i%4}",
                    model=f"model-{i%5}",
                    dataset=f"dataset-{i%3}",
                    metrics=["quality"],
                    status="COMPLETED",
                    created_at=stamp,
                    started_at=stamp,
                    ended_at=stamp + timedelta(seconds=50),
                    run_metadata={"total_items": items_per_run},
                    run_config={},
                )
            )
            for j in range(items_per_run):
                item_rows.append(
                    dict(
                        run_id=rid,
                        item_id=str(j),
                        index=j,
                        input={"text": "i" * 1024},
                        expected={"text": "e" * 1024},
                        output={"text": "o" * 1024},
                        latency_ms=float(j + 1),
                        item_metadata={},
                    )
                )
                score_rows.append(
                    dict(
                        run_id=rid,
                        item_id=str(j),
                        metric_name="quality",
                        score_numeric=float(j % 2),
                        score_raw=float(j % 2),
                        meta={},
                    )
                )
        db.bulk_insert_mappings(Run, run_rows)
        db.bulk_insert_mappings(RunItem, item_rows)
        db.bulk_insert_mappings(RunItemScore, score_rows)
        db.commit()
        principal = Principal(user=db.get(User, "owner"), auth_type="local_password")
        db.expunge(principal.user)
    app = FastAPI()
    app.include_router(runs.router)
    app.include_router(dashboard.router)

    def session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[require_ui_principal] = lambda: principal
    statements = collections.Counter()
    event.listen(
        engine,
        "before_cursor_execute",
        lambda _c, _cu, sql, _p, _co, _e: statements.update(
            [sql.lstrip().split()[0].upper()]
        ),
    )
    with TestClient(app) as client:

        def legacy():
            return [
                client.get(
                    "/api/runs",
                    params={"project_slug": "bench", "limit": 500, "offset": offset},
                )
                for offset in range(0, run_count, 500)
            ]

        source = legacy()
        with Session(engine) as db:
            for response in source:
                response.raise_for_status()
                for models in response.json()["tasks"].values():
                    for rows in models.values():
                        for row in rows:
                            stamp = datetime.fromisoformat(
                                row["timestamp"].replace("Z", "+00:00")
                            ).replace(tzinfo=None)
                            db.add(
                                DashboardRunDimension(
                                    run_key=row["run_id"],
                                    project_key="project",
                                    task=row["task_name"],
                                    model=row["model_name"] + "|||plain",
                                    dataset=row["dataset_name"],
                                    owner="owner",
                                    status="COMPLETED",
                                    timestamp=stamp,
                                    created_at=stamp,
                                    descriptor=row,
                                )
                            )
                            db.add(
                                DashboardRunSummary(
                                    run_key=row["run_id"],
                                    project_key="project",
                                    data=row,
                                    avg_latency_ms=row["avg_latency_ms"],
                                    median_latency_ms=row["median_latency_ms"],
                                    success_rate=row["success_rate"],
                                    projection_revision=1,
                                )
                            )
            db.commit()

        def projected():
            return [
                client.post(
                    "/api/dashboard/runs",
                    json={
                        "project_slug": "bench",
                        "limit": 50,
                        "include_overview": True,
                    },
                )
            ]

        for name, read in [
            ("legacy_full_history", legacy),
            ("projected_first_page_with_global_overview", projected),
        ]:
            times = []
            for _ in range(3):
                statements.clear()
                start = time.perf_counter()
                responses = read()
                times.append((time.perf_counter() - start) * 1000)
                for response in responses:
                    response.raise_for_status()
            print(
                json.dumps(
                    dict(
                        case=name,
                        runs=run_count,
                        items_per_run=items_per_run,
                        backend="sqlite",
                        median_ms=round(statistics.median(times), 2),
                        requests=len(responses),
                        response_bytes=sum(len(r.content) for r in responses),
                        sql=dict(statements),
                    )
                ),
                flush=True,
            )
    engine.dispose()


if __name__ == "__main__":
    benchmark()
