"""Run unchanged against baseline and P1 PYTHONPATH; use a disposable SQLite DB."""

import json
import os
import statistics
import time
from datetime import datetime, timezone

os.environ.setdefault("QYM_DATABASE_URL", "sqlite://")
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from qym_platform.db.models import Base, Project, Run, RunItem, User, UserRole

results = []
for repetition in range(6):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(User(id="u", email="benchmark@example.test", role=UserRole.ADMIN))
        db.flush()
        db.add(Project(id="p", name="Benchmark", slug="p", created_by_user_id="u"))
        db.flush()
        db.add(
            Run(
                id="r",
                project_id="p",
                owner_user_id="u",
                created_by_user_id="u",
                task="task",
                dataset="dataset",
                metrics=["m"],
                run_config={},
                run_metadata={},
                last_event_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        db.commit()
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.split()[0].upper())

    event.listen(engine, "before_cursor_execute", capture)
    started = time.perf_counter()
    with Session(engine, autoflush=False) as db:
        for n in range(1000):
            db.add(
                RunItem(
                    run_id="r",
                    item_id=str(n),
                    input={"payload": "x" * 10000},
                    output="answer",
                    latency_ms=n,
                )
            )
        db.commit()
    elapsed = time.perf_counter() - started
    event.remove(engine, "before_cursor_execute", capture)
    engine.dispose()
    if repetition:
        results.append({"elapsed_s": elapsed, "statements": len(statements)})
print(
    json.dumps(
        {
            "items": 1000,
            "input_characters_per_item": 10000,
            "warmup_runs": 1,
            "median_s": statistics.median(row["elapsed_s"] for row in results),
            "runs": results,
        },
        indent=2,
    )
)
