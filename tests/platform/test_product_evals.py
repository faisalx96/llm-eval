from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("QYM_AUTH_MODE", "proxy_headers")
ROOT = Path(__file__).resolve().parents[2]
PLATFORM_SRC = ROOT / "packages" / "platform"
SDK_SRC = ROOT / "packages" / "sdk"
for src in (PLATFORM_SRC, SDK_SRC):
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

from qym_platform.api import product_evals
from qym_platform.app import create_app
from qym_platform.datetime_utils import utc_now_naive
from qym_platform.db.base import Base
from qym_platform.db.models import (
    ApiKey,
    Project,
    Run,
    RunEvent,
    RunItem,
    RunItemScore,
    RunWorkflowStatus,
    User,
    UserRole,
)
from qym_platform.deps import get_db
from qym_platform.security import api_key_prefix, hash_api_key
from qym_platform.services.product_evals import (
    ProductEvalJob,
    ProductEvalJobManager,
    validate_submit_request,
)


@pytest.fixture()
def session_factory(monkeypatch):
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("QYM_AUTH_MODE", "proxy_headers")
    monkeypatch.setenv("QYM_BASE_URL", "http://testserver")
    monkeypatch.setenv("QYM_ALLOW_LEGACY_EMPTY_API_KEY_SCOPES", "false")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    try:
        yield SessionLocal
    finally:
        engine.dispose()


@pytest.fixture()
def client(session_factory):
    app = create_app()

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_api_key(
    session: Session,
    *,
    token: str,
    scopes: list[str],
    user_id: str = "user-1",
    project_id: str = "project-1",
) -> None:
    user = session.query(User).filter(User.id == user_id).first()
    if not user:
        user = User(id=user_id, email=f"{user_id}@example.com", role=UserRole.MEMBER)
        session.add(user)
    project = session.query(Project).filter(Project.id == project_id).first()
    if not project:
        project = Project(
            id=project_id, name="Project 1", slug=project_id, created_by_user_id=user_id
        )
        session.add(project)
    api_key = ApiKey(
        id=f"key-{token}",
        user_id=user_id,
        project_id=project_id,
        name=token,
        prefix=api_key_prefix(token),
        key_hash=hash_api_key(token),
        scopes=scopes,
    )
    session.add(api_key)
    session.commit()


def test_submit_product_eval_starts_job_and_returns_run_id(
    client, session_factory, monkeypatch
) -> None:
    with session_factory() as session:
        _seed_api_key(session, token="submit-token", scopes=["runs:write", "runs:read"])

    captured: dict[str, object] = {}

    def fake_submit(**kwargs):
        captured.update(kwargs)
        job = ProductEvalJob(
            job_id="job-1",
            preset="insightor",
            project_id=kwargs.get("project_id"),
        )
        job.mark(status="RUNNING", run_id="run-1")
        return job

    monkeypatch.setattr(product_evals.job_manager, "submit", fake_submit)

    response = client.post(
        "/v1/product-evals",
        headers=_auth_headers("submit-token"),
        json={
            "preset": "insightor",
            "run_name": "external-test-001",
            "metadata": {"source": "curl"},
            "config": {"timeout": 30},
        },
    )

    assert response.status_code == 202
    envelope = response.json()
    assert envelope["ok"] is True
    assert envelope["error"] is None
    payload = envelope["data"]
    assert payload["qym_run_id"] == "run-1"
    assert payload["qym_project_id"] == "project-1"
    assert payload["qym_run_url"] == "http://testserver/run/run-1"
    assert payload["poll_url"] == "/v1/product-evals/run-1"
    assert "run_id" not in payload
    assert "job_id" not in payload
    assert "project_id" not in payload
    assert "preset" not in payload
    assert captured["api_key"] == "submit-token"
    assert captured["run_name"] == "external-test-001"
    assert captured["metadata"] == {"source": "curl"}


def test_submit_product_eval_hides_job_id_when_run_is_starting(
    client, session_factory, monkeypatch
) -> None:
    with session_factory() as session:
        _seed_api_key(session, token="submit-token", scopes=["runs:write", "runs:read"])

    def fake_submit(**kwargs):
        job = ProductEvalJob(
            job_id="job-1",
            preset="test",
            project_id=kwargs.get("project_id"),
        )
        job.mark(status="RUNNING")
        return job

    monkeypatch.setattr(product_evals.job_manager, "submit", fake_submit)

    response = client.post(
        "/v1/product-evals",
        headers=_auth_headers("submit-token"),
        json={"preset": "test"},
    )

    assert response.status_code == 202
    payload = response.json()["data"]
    assert payload["status"] == "STARTING"
    assert payload["qym_run_id"] is None
    assert payload["qym_project_id"] == "project-1"
    assert payload["qym_run_url"] is None
    assert payload["poll_url"] == "/v1/product-evals/jobs/job-1"
    assert "run_id" not in payload
    assert "job_id" not in payload
    assert "project_id" not in payload


def test_submit_rejects_invalid_preset(client, session_factory, monkeypatch) -> None:
    monkeypatch.setenv("EVAL_DATASET", "dataset")
    with session_factory() as session:
        _seed_api_key(session, token="submit-token", scopes=["runs:write"])

    response = client.post(
        "/v1/product-evals",
        headers=_auth_headers("submit-token"),
        json={"preset": "not-allowed"},
    )

    assert response.status_code == 400
    envelope = response.json()
    assert envelope["ok"] is False
    assert envelope["data"] is None
    assert envelope["error"]["code"] == "invalid_request"
    assert "Unknown product eval preset" in envelope["error"]["message"]


def test_test_preset_uses_self_contained_runner(monkeypatch) -> None:
    monkeypatch.delenv("EVAL_DATASET", raising=False)

    preset = validate_submit_request(preset_name="test", config={})

    assert preset.name == "test"
    assert preset.script_path.name == "test_eval.py"
    assert "product_eval_presets" in preset.script_path.parts


def test_run_v2_async_preset_is_removed(client, session_factory) -> None:
    with session_factory() as session:
        _seed_api_key(session, token="submit-token", scopes=["runs:write"])

    response = client.post(
        "/v1/product-evals",
        headers=_auth_headers("submit-token"),
        json={"preset": "run_v2_async"},
    )

    assert response.status_code == 400
    envelope = response.json()
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "invalid_request"
    assert "Unknown product eval preset" in envelope["error"]["message"]


def test_submit_requires_runs_write_scope(client, session_factory) -> None:
    with session_factory() as session:
        _seed_api_key(session, token="read-token", scopes=["runs:read"])

    response = client.post(
        "/v1/product-evals",
        headers=_auth_headers("read-token"),
        json={"preset": "insightor"},
    )

    assert response.status_code == 403


def test_poll_requires_runs_read_scope(client, session_factory) -> None:
    with session_factory() as session:
        _seed_api_key(session, token="write-token", scopes=["runs:write"])

    response = client.get(
        "/v1/product-evals/run-1", headers=_auth_headers("write-token")
    )

    assert response.status_code == 403


def test_poll_returns_aggregate_run_progress_by_default(
    client, session_factory
) -> None:
    run_id = "00000000-0000-0000-0000-000000000301"
    now = utc_now_naive()
    with session_factory() as session:
        _seed_api_key(
            session, token="read-token", scopes=["runs:read"], user_id="owner-1"
        )
        run = Run(
            id=run_id,
            project_id="project-1",
            created_by_user_id="owner-1",
            owner_user_id="owner-1",
            external_run_id="external-1",
            task="insightor_api",
            dataset="dataset-1",
            model="model-1",
            metrics=["accuracy"],
            status=RunWorkflowStatus.RUNNING,
            run_metadata={
                "total_items": 3,
                "source": "test",
                "product_eval": {"preset": "test", "job_id": "internal-job"},
            },
            run_config={"run_name": "external-1"},
            started_at=now,
            last_event_at=now,
        )
        completed_item = RunItem(
            run_id=run_id,
            item_id="item-1",
            index=0,
            input={"question": "q1"},
            expected="select 1",
            output={"sql": "select 1"},
            item_metadata={"domain": "sql"},
            latency_ms=120.0,
        )
        failed_item = RunItem(
            run_id=run_id,
            item_id="item-2",
            index=1,
            input={"question": "q2"},
            expected="select 2",
            error="boom",
            item_metadata={},
            latency_ms=50.0,
        )
        running_item = RunItem(
            run_id=run_id,
            item_id="item-3",
            index=2,
            input={"question": "q3"},
            expected="select 3",
            item_metadata={},
        )
        score = RunItemScore(
            run_id=run_id,
            item_id="item-1",
            metric_name="accuracy",
            score_numeric=1.0,
            score_raw=True,
            meta={"reasoning": "ok"},
        )
        event = RunEvent(
            run_id=run_id,
            event_id="00000000-0000-0000-0000-000000000302",
            sequence=1,
            type="item_completed",
            sent_at=now,
            payload={"item_id": "item-1"},
        )
        session.add_all([run, completed_item, failed_item, running_item, score, event])
        session.commit()

    response = client.get(
        f"/v1/product-evals/{run_id}", headers=_auth_headers("read-token")
    )

    assert response.status_code == 200
    envelope = response.json()
    assert envelope["ok"] is True
    assert envelope["error"] is None
    payload = envelope["data"]
    assert payload["qym_run_id"] == run_id
    assert payload["qym_project_id"] == "project-1"
    assert payload["qym_run_url"] == f"http://testserver/run/{run_id}"
    assert "run_id" not in payload
    assert payload["status"] == "RUNNING"
    assert payload["total"] == 3
    assert payload["completed"] == 1
    assert payload["failed"] == 1
    assert payload["in_progress"] == 1
    assert payload["pending"] == 0
    assert payload["metric_stats"]["accuracy"]["mean"] == 1.0
    assert payload["latency_ms"]["count"] == 2
    assert payload["latency_ms"]["mean"] == 85.0
    assert payload["latency_ms"]["min"] == 50.0
    assert payload["latency_ms"]["max"] == 120.0
    assert payload["metadata"]["source"] == "test"
    assert payload["metadata"]["total_items"] == 3
    assert "product_eval" not in payload["metadata"]
    assert "items" not in payload


def test_poll_can_include_item_rows_when_requested(client, session_factory) -> None:
    run_id = "00000000-0000-0000-0000-000000000401"
    now = utc_now_naive()
    with session_factory() as session:
        _seed_api_key(
            session, token="read-token", scopes=["runs:read"], user_id="owner-1"
        )
        run = Run(
            id=run_id,
            project_id="project-1",
            created_by_user_id="owner-1",
            owner_user_id="owner-1",
            external_run_id="external-1",
            task="insightor_api",
            dataset="dataset-1",
            model="model-1",
            metrics=["accuracy"],
            status=RunWorkflowStatus.RUNNING,
            run_metadata={"total_items": 3},
            run_config={"run_name": "external-1"},
            started_at=now,
            last_event_at=now,
        )
        completed_item = RunItem(
            run_id=run_id,
            item_id="item-1",
            index=0,
            input={"question": "q1"},
            expected="select 1",
            output={"sql": "select 1"},
            item_metadata={"domain": "sql"},
            latency_ms=120.0,
        )
        failed_item = RunItem(
            run_id=run_id,
            item_id="item-2",
            index=1,
            input={"question": "q2"},
            expected="select 2",
            error="boom",
            item_metadata={},
            latency_ms=50.0,
        )
        running_item = RunItem(
            run_id=run_id,
            item_id="item-3",
            index=2,
            input={"question": "q3"},
            expected="select 3",
            item_metadata={},
        )
        score = RunItemScore(
            run_id=run_id,
            item_id="item-1",
            metric_name="accuracy",
            score_numeric=1.0,
            score_raw=True,
            meta={"reasoning": "ok"},
        )
        event = RunEvent(
            run_id=run_id,
            event_id="00000000-0000-0000-0000-000000000402",
            sequence=1,
            type="item_completed",
            sent_at=now,
            payload={"item_id": "item-1"},
        )
        session.add_all([run, completed_item, failed_item, running_item, score, event])
        session.commit()

    response = client.get(
        f"/v1/product-evals/{run_id}?include_items=true",
        headers=_auth_headers("read-token"),
    )

    assert response.status_code == 200
    envelope = response.json()
    assert envelope["ok"] is True
    assert envelope["error"] is None
    payload = envelope["data"]
    assert payload["items"][0]["scores"] == {"accuracy": 1.0}
    assert payload["items"][0]["metric_metadata"]["accuracy"]["reasoning"] == "ok"
    assert payload["items"][1]["status"] == "error"
    assert payload["items"][2]["status"] == "in_progress"


def test_job_manager_records_background_failure(monkeypatch, tmp_path) -> None:
    broken_script = tmp_path / "broken_insightor_eval.py"
    broken_script.write_text("# no expected functions\n", encoding="utf-8")
    monkeypatch.setenv("EVAL_DATASET", "dataset-1")
    monkeypatch.setenv("QYM_INSIGHTOR_EVAL_SCRIPT", str(broken_script))
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")

    manager = ProductEvalJobManager(max_workers=1)
    job = manager.submit(
        preset_name="insightor",
        api_key="token",
        run_name=None,
        task_name=None,
        model=None,
        metadata={},
        config={},
        platform_url="http://testserver",
    )
    assert job._future is not None
    job._future.result(timeout=5)

    assert job.status == "FAILED"
    assert "Function 'insightor_api' not found" in (job.error or "")
