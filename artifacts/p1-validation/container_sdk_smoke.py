"""Real authenticated SDK -> Docker API -> PostgreSQL -> worker smoke test.

Requires the disposable qym_p1_container_test database and a local container on
port18089. Creates a fresh isolated test project; never uses real credentials.
"""

import asyncio
import json
import os
import secrets
import tempfile
import time
from uuid import uuid4

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from qym.core.dataset import InMemoryDataset
from qym.core.evaluator import Evaluator
from qym_platform.db.models import (
    ApiKey,
    Project,
    Run,
    RunItem,
    RunItemAttempt,
    RunItemPassScore,
    User,
    UserRole,
)
from qym_platform.security import api_key_prefix, hash_api_key


async def main():
    url = os.environ["QYM_DATABASE_URL"]
    assert url.endswith("/qym_p1_container_test")
    engine = create_engine(url)
    project = "smk-" + uuid4().hex
    token = secrets.token_urlsafe(32)
    with Session(engine) as db:
        db.add(
            User(id=project, email=project + "@example.invalid", role=UserRole.ADMIN)
        )
        db.flush()
        db.add(
            Project(
                id=project,
                slug=project,
                name="Container smoke",
                created_by_user_id=project,
            )
        )
        db.flush()
        db.add(
            ApiKey(
                user_id=project,
                project_id=project,
                name="Ephemeral smoke key",
                prefix=api_key_prefix(token),
                key_hash=hash_api_key(token),
                scopes=["runs:write"],
            )
        )
        db.commit()

    async def task(input):
        await asyncio.sleep(0.001)
        return input if input != "question-3" else "wrong"

    with tempfile.TemporaryDirectory(prefix="qym-container-smoke-") as output:
        evaluator = Evaluator(
            task,
            InMemoryDataset(
                [
                    {
                        "id": f"item-{i}",
                        "input": f"question-{i}",
                        "expected_output": f"question-{i}",
                    }
                    for i in range(8)
                ]
            ),
            ["exact_match"],
            config={
                "run_name": "Container smoke",
                "task_name": "Container smoke",
                "samples": 2,
                "max_concurrency": 3,
                "checkpoint_enabled": False,
                "otel_enabled": False,
                "platform_url": "http://127.0.0.1:18089",
                "platform_api_key": token,
                "output_dir": output,
            },
        )
        result = await evaluator.arun(show_tui=False, auto_save=False)
        assert result.total_items == 8 and evaluator._run_completed
        run_id = evaluator._platform_stream.run_id
        with Session(engine) as db:
            run = db.get(Run, run_id)
            assert run.status.value == "COMPLETED"
            assert db.query(RunItem).filter_by(run_id=run_id).count() == 8
            assert db.query(RunItemPassScore).filter_by(run_id=run_id).count() == 16
            assert (
                db.query(RunItemAttempt)
                .filter_by(run_id=run_id, is_last_attempt=True)
                .count()
                == 16
            )
        async with httpx.AsyncClient(base_url="http://127.0.0.1:18089") as client:
            deadline = time.monotonic() + 30
            while True:
                response = await client.post(
                    "/api/dashboard/runs",
                    json={
                        "project_slug": project,
                        "limit": 50,
                        "include_overview": True,
                    },
                )
                response.raise_for_status()
                data = response.json()
                if data["rows"] and not data["freshness"]["updating"]:
                    break
                assert time.monotonic() < deadline, "Projection did not settle"
                await asyncio.sleep(0.25)
            row = data["rows"][0]
            assert (
                row["total_items"] == 8
                and row["metric_averages"]["exact_match"] == 0.875
            )
            assert len(row["pass_summaries"]) == 2
            compact = (
                await client.get("/api/runs/" + run_id, params={"view": "compact"})
            ).json()
            assert len(compact["snapshot"]["rows"]) == 8
            assert all("input" not in r for r in compact["snapshot"]["rows"])
            detail = (
                await client.post(
                    "/api/runs/" + run_id + "/items/details",
                    json={"item_ids": ["item-7"]},
                )
            ).json()
            assert detail["rows"][0]["output"] == "question-7"
        print(
            json.dumps(
                {
                    "transport": "real HTTP with PBKDF2 API-key authentication",
                    "runtime": "Docker Python3.11",
                    "storage": "PostgreSQL16",
                    "items": 8,
                    "passes": 2,
                    "pass_scores": 16,
                    "final_attempts": 16,
                    "exact_match": 0.875,
                    "status": "COMPLETED",
                    "projection_settled": True,
                    "compact_and_hydration": "passed",
                }
            )
        )
    engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
