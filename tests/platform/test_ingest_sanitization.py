from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")
ROOT = Path(__file__).resolve().parents[2]
PLATFORM_SRC = ROOT / "packages" / "platform"
if str(PLATFORM_SRC) not in sys.path:
    sys.path.insert(0, str(PLATFORM_SRC))
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

from qym_platform.app import create_app
from qym_platform.db.base import Base
from qym_platform.db.models import ApiKey, Project, RunItem, RunItemScore, User, UserRole
from qym_platform.deps import get_db
from qym_platform.security import api_key_prefix, hash_api_key


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QYM_AUTH_MODE", "proxy_headers")
    monkeypatch.setenv("QYM_ALLOW_LEGACY_EMPTY_API_KEY_SCOPES", "true")


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_api_key(session: Session, token: str = "test-token") -> None:
    user = User(id="user-1", email="owner@example.com", role=UserRole.MEMBER)
    project = Project(id="project-1", name="Project", slug="project", created_by_user_id=user.id)
    api_key = ApiKey(
        id="key-1",
        user_id=user.id,
        project_id=project.id,
        name="test",
        prefix=api_key_prefix(token),
        key_hash=hash_api_key(token),
        scopes=[],
    )
    session.add_all([user, project, api_key])
    session.commit()


def test_ingest_sanitizes_nan_and_infinity_payloads():
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
            _seed_api_key(session)

        with TestClient(app) as client:
            create_response = client.post(
                "/v1/runs",
                headers=_auth_headers("test-token"),
                json={
                    "task": "task",
                    "dataset": "dataset",
                    "metrics": ["judge"],
                    "run_metadata": {},
                    "run_config": {},
                },
            )
            assert create_response.status_code == 200
            run_id = create_response.json()["run_id"]

            body = "\n".join(
                [
                    (
                        '{"schema_version":1,"event_id":"00000000-0000-0000-0000-000000000001",'
                        f'"sequence":1,"sent_at":"2026-03-23T00:00:00Z","type":"item_started","run_id":"{run_id}",'
                        '"payload":{"item_id":"item-1","index":0,"input":{"prompt":"hi"},"expected":null,"item_metadata":{}}}'
                    ),
                    (
                        '{"schema_version":1,"event_id":"00000000-0000-0000-0000-000000000002",'
                        f'"sequence":2,"sent_at":"2026-03-23T00:00:01Z","type":"item_completed","run_id":"{run_id}",'
                        '"payload":{"item_id":"item-1","index":0,"output":{"value":NaN},"latency_ms":12.5,'
                        '"trace_id":"trace-1","trace_url":"https://langfuse.example/trace-1"}}'
                    ),
                    (
                        '{"schema_version":1,"event_id":"00000000-0000-0000-0000-000000000003",'
                        f'"sequence":3,"sent_at":"2026-03-23T00:00:02Z","type":"metric_scored","run_id":"{run_id}",'
                        '"payload":{"item_id":"item-1","metric_name":"judge","score_numeric":0.5,'
                        '"score_raw":{"score":0.5,"metadata":{"infinite":Infinity}},'
                        '"meta":{"nan_value":NaN},"label":"ok","explanation":"fine"}}'
                    ),
                ]
            ) + "\n"

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
            item = session.query(RunItem).filter(RunItem.run_id == run_id, RunItem.item_id == "item-1").first()
            score = session.query(RunItemScore).filter(
                RunItemScore.run_id == run_id,
                RunItemScore.item_id == "item-1",
                RunItemScore.metric_name == "judge",
            ).first()

            assert item is not None
            assert item.output == {"value": None}
            assert item.trace_id == "trace-1"

            assert score is not None
            assert score.score_raw == {"score": 0.5, "metadata": {"infinite": None}}
            assert score.meta == {"nan_value": None}
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
