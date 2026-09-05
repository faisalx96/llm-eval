import os, json, time

os.environ.setdefault("QYM_DATABASE_URL", "sqlite://")
from datetime import datetime
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from qym_platform.db.models import Base, User, UserRole, Project, Run, RunItem
from qym_platform.services.dashboard_summaries import drain_dashboard_changes
from qym_platform.db.dashboard_models import DashboardPartitionState

results = []
for count in (100, 1000):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(User(id="u", email="x@test", role=UserRole.ADMIN))
        db.flush()
        db.add(Project(id="p", name="P", slug="p", created_by_user_id="u"))
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
                last_event_at=datetime.utcnow(),
            )
        )
        db.commit()
    queries = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement.split()[0].upper())

    event.listen(engine, "before_cursor_execute", capture)
    started = time.perf_counter()
    with Session(engine, autoflush=False) as db:
        for i in range(count):
            db.add(
                RunItem(
                    run_id="r",
                    item_id=str(i),
                    input={"payload": "x" * 10000},
                    output="a",
                    latency_ms=i,
                )
            )
        db.commit()
    write = time.perf_counter() - started
    write_queries = len(queries)
    queries.clear()
    started = time.perf_counter()
    with Session(engine, autoflush=False) as db:
        while True:
            drain_dashboard_changes(db, max_events=500)
            db.commit()
            if db.get(DashboardPartitionState, "r").queue_state == "ready":
                break
    elapsed = time.perf_counter() - started
    results.append(
        dict(
            items=count,
            write_s=write,
            source_statements=write_queries,
            project_s=elapsed,
            projection_statements=len(queries),
        )
    )
    event.remove(engine, "before_cursor_execute", capture)
    engine.dispose()
print(json.dumps(results, indent=2))
