from __future__ import annotations

import json
import os
import sys
import threading
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
    ProductEvalQueueFull,
    ProductEvalRuntimeInputs,
    ProductEvalError,
    get_preset,
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


def test_submit_product_eval_starts_job_and_returns_eval_id(
    client, session_factory, monkeypatch
) -> None:
    with session_factory() as session:
        _seed_api_key(session, token="submit-token", scopes=["runs:write", "runs:read"])

    captured: dict[str, object] = {}

    def fake_submit(**kwargs):
        captured.update(kwargs)
        job = ProductEvalJob(
            job_id="eval_submit1",
            preset="insightor",
            project_id=kwargs.get("project_id"),
            expected_runs=3,
        )
        job.initialize_planned_runs()
        job.mark(status="RUNNING", run_id="run-1")
        return job

    monkeypatch.setattr(product_evals.job_manager, "submit", fake_submit)

    response = client.post(
        "/v1/product-evals",
        headers=_auth_headers("submit-token"),
        json={
            "preset": "insightor",
            "dataset": "customer-langfuse-dataset",
            "insightor_url": "https://insightor.example.com",
            "refresh_token": "refresh-token-1",
            "agent_version": "agent-v1",
            "image_version": "image-v1",
            "kb_version": "kb-v1",
            "run_name": "external-test-001",
            "metadata": {"source": "curl"},
        },
    )

    assert response.status_code == 202
    envelope = response.json()
    assert envelope["ok"] is True
    assert envelope["error"] is None
    payload = envelope["data"]
    assert payload["eval_id"] == "eval_submit1"
    assert payload["qym_project_id"] == "project-1"
    assert [run["attempt"] for run in payload["runs"]] == [1, 2, 3]
    assert [run["status"] for run in payload["runs"]] == [
        "PENDING",
        "PENDING",
        "PENDING",
    ]
    assert payload["qym_compare_url"] is None
    assert payload["group_analysis"] is None
    assert "qym_run_id" not in payload
    assert "qym_run_url" not in payload
    assert "qym_runs" not in payload
    assert "poll_url" not in payload
    assert "job_id" not in payload
    assert "run_id" not in payload
    assert "project_id" not in payload
    assert "preset" not in payload
    assert captured["api_key"] == "submit-token"
    assert captured["dataset_name"] == "customer-langfuse-dataset"
    runtime_inputs = captured["runtime_inputs"]
    assert runtime_inputs.insightor_url == "https://insightor.example.com"
    assert runtime_inputs.refresh_token == "refresh-token-1"
    assert runtime_inputs.agent_version == "agent-v1"
    assert runtime_inputs.image_version == "image-v1"
    assert runtime_inputs.kb_version == "kb-v1"
    assert captured["run_name"] == "external-test-001"
    assert captured["metadata"] == {"source": "curl"}


def test_submit_product_eval_returns_eval_id_when_starting(
    client, session_factory, monkeypatch
) -> None:
    with session_factory() as session:
        _seed_api_key(session, token="submit-token", scopes=["runs:write", "runs:read"])

    def fake_submit(**kwargs):
        job = ProductEvalJob(
            job_id="eval_starting1",
            preset="test",
            project_id=kwargs.get("project_id"),
            expected_runs=3,
        )
        job.initialize_planned_runs()
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
    assert payload["eval_id"] == "eval_starting1"
    assert payload["status"] == "STARTING"
    assert payload["qym_project_id"] == "project-1"
    assert [run["attempt"] for run in payload["runs"]] == [1, 2, 3]
    assert [run["status"] for run in payload["runs"]] == [
        "PENDING",
        "PENDING",
        "PENDING",
    ]
    assert payload["qym_compare_url"] is None
    assert payload["group_analysis"] is None
    assert "qym_run_id" not in payload
    assert "qym_run_url" not in payload
    assert "qym_runs" not in payload
    assert "poll_url" not in payload
    assert "run_id" not in payload
    assert "job_id" not in payload
    assert "project_id" not in payload


def test_eval_poll_returns_multi_run_compare_url(
    client, session_factory, monkeypatch
) -> None:
    with session_factory() as session:
        _seed_api_key(session, token="read-token", scopes=["runs:read"])

    job = ProductEvalJob(
        job_id="eval_poll1",
        preset="insightor",
        project_id="project-1",
        expected_runs=3,
    )
    job.record_run_matrix(
        [
            {"run_id": "sdk-run-1"},
            {"run_id": "sdk-run-2"},
            {"run_id": "sdk-run-3"},
        ]
    )
    job.mark_run(sdk_run_id="sdk-run-1", status="COMPLETED", qym_run_id="qym-run-1")
    job.mark_run(sdk_run_id="sdk-run-2", status="RUNNING", qym_run_id="qym-run-2")
    job.mark(status="RUNNING")

    monkeypatch.setattr(product_evals.job_manager, "get", lambda eval_id: job)

    response = client.get(
        "/v1/product-evals/eval_poll1",
        headers=_auth_headers("read-token"),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["eval_id"] == "eval_poll1"
    assert payload["qym_compare_url"] == (
        "http://testserver/compare?runs=qym-run-1&runs=qym-run-2"
    )
    assert payload["runs"] == [
        {
            "attempt": 1,
            "status": "COMPLETED",
            "qym_run_id": "qym-run-1",
            "qym_run_url": "http://testserver/run/qym-run-1",
            "task": None,
            "dataset": None,
            "model": None,
            "summary": None,
        },
        {
            "attempt": 2,
            "status": "RUNNING",
            "qym_run_id": "qym-run-2",
            "qym_run_url": "http://testserver/run/qym-run-2",
            "task": None,
            "dataset": None,
            "model": None,
            "summary": None,
        },
        {
            "attempt": 3,
            "status": "STARTING",
            "qym_run_id": None,
            "qym_run_url": None,
            "task": None,
            "dataset": None,
            "model": None,
            "summary": None,
        },
    ]
    assert payload["group_analysis"] is None


def test_eval_poll_includes_pending_planned_attempts(
    client, session_factory, monkeypatch
) -> None:
    with session_factory() as session:
        _seed_api_key(session, token="read-token", scopes=["runs:read"])

    job = ProductEvalJob(
        job_id="eval_pending_attempts",
        preset="test",
        project_id="project-1",
        expected_runs=3,
    )
    job.initialize_planned_runs()
    job.record_run_matrix([{"run_id": "sdk-run-1", "product_eval_attempt": 1}])
    job.mark_run(sdk_run_id="sdk-run-1", status="RUNNING", qym_run_id="qym-run-1")
    job.mark(status="RUNNING", run_id="qym-run-1")

    monkeypatch.setattr(product_evals.job_manager, "get", lambda eval_id: job)

    response = client.get(
        "/v1/product-evals/eval_pending_attempts",
        headers=_auth_headers("read-token"),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["runs"] == [
        {
            "attempt": 1,
            "status": "RUNNING",
            "qym_run_id": "qym-run-1",
            "qym_run_url": "http://testserver/run/qym-run-1",
            "task": None,
            "dataset": None,
            "model": None,
            "summary": None,
        },
        {
            "attempt": 2,
            "status": "PENDING",
            "qym_run_id": None,
            "qym_run_url": None,
            "task": None,
            "dataset": None,
            "model": None,
            "summary": None,
        },
        {
            "attempt": 3,
            "status": "PENDING",
            "qym_run_id": None,
            "qym_run_url": None,
            "task": None,
            "dataset": None,
            "model": None,
            "summary": None,
        },
    ]


def test_eval_poll_returns_group_analysis_when_completed(
    client, session_factory, monkeypatch
) -> None:
    with session_factory() as session:
        _seed_api_key(session, token="read-token", scopes=["runs:read"])

    job = ProductEvalJob(
        job_id="eval_completed1",
        preset="insightor",
        project_id="project-1",
        expected_runs=3,
    )
    job.record_run_matrix(
        [
            {"run_id": "sdk-run-1"},
            {"run_id": "sdk-run-2"},
            {"run_id": "sdk-run-3"},
        ]
    )
    for attempt in range(1, 4):
        job.mark_run(
            sdk_run_id=f"sdk-run-{attempt}",
            status="COMPLETED",
            qym_run_id=f"qym-run-{attempt}",
        )
    job.set_group_analysis(
        {
            "metric": "accuracy",
            "threshold": 0.8,
            "k": 3,
            "total_items": 2,
            "total_score_count": 6,
            "failed_count": 0,
            "pass_at_3": 0.5,
            "avg_at_3": 1 / 6,
            "consistency": 2 / 3,
            "reliability": 1 / 3,
            "avg_latency_ms": 100.0,
        }
    )
    job.mark(status="COMPLETED")

    monkeypatch.setattr(product_evals.job_manager, "get", lambda eval_id: job)

    response = client.get(
        "/v1/product-evals/eval_completed1",
        headers=_auth_headers("read-token"),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["status"] == "COMPLETED"
    assert payload["group_analysis"]["pass_at_3"] == 0.5
    assert payload["group_analysis"]["avg_at_3"] == 1 / 6
    assert payload["group_analysis"]["consistency"] == 2 / 3
    assert payload["group_analysis"]["reliability"] == 1 / 3
    assert payload["group_analysis"]["avg_latency_ms"] == 100.0


def test_stop_product_eval_marks_job_and_runs_stopped(
    client, session_factory, monkeypatch
) -> None:
    with session_factory() as session:
        _seed_api_key(session, token="write-token", scopes=["runs:write"])
        now = utc_now_naive()
        for run_id in ("qym-run-1", "qym-run-2"):
            session.add(
                Run(
                    id=run_id,
                    project_id="project-1",
                    created_by_user_id="user-1",
                    owner_user_id="user-1",
                    task="insightor_api",
                    dataset="dataset-1",
                    model="model-1",
                    metrics=["accuracy"],
                    status=RunWorkflowStatus.RUNNING,
                    started_at=now,
                    last_event_at=now,
                )
            )
        session.commit()

    job = ProductEvalJob(
        job_id="eval_stop1",
        preset="insightor",
        owner_user_id="user-1",
        project_id="project-1",
        expected_runs=3,
    )
    job.record_run_matrix(
        [
            {"run_id": "sdk-run-1"},
            {"run_id": "sdk-run-2"},
            {"run_id": "sdk-run-3"},
        ]
    )
    job.mark_run(sdk_run_id="sdk-run-1", status="RUNNING", qym_run_id="qym-run-1")
    job.mark_run(sdk_run_id="sdk-run-2", status="RUNNING", qym_run_id="qym-run-2")
    job.mark(status="RUNNING", run_id="qym-run-1")

    monkeypatch.setattr(product_evals.job_manager, "get", lambda eval_id: job)

    response = client.post(
        "/v1/product-evals/eval_stop1/stop",
        headers=_auth_headers("write-token"),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["status"] == "STOPPED"
    assert payload["stopped_qym_runs"] == 2
    assert [row["status"] for row in payload["runs"]] == [
        "STOPPED",
        "STOPPED",
        "STOPPED",
    ]

    with session_factory() as session:
        runs = session.query(Run).order_by(Run.id.asc()).all()
        assert [run.status for run in runs] == [
            RunWorkflowStatus.STOPPED,
            RunWorkflowStatus.STOPPED,
        ]
        assert [run.status_reason for run in runs] == [
            "product_eval_stopped",
            "product_eval_stopped",
        ]


def test_stop_product_eval_job_allows_any_valid_key(
    client, session_factory, monkeypatch
) -> None:
    # Scopes are no longer enforced: a key without runs:write is no longer blocked.
    with session_factory() as session:
        _seed_api_key(session, token="read-token", scopes=["runs:read"])

    job = ProductEvalJob(
        job_id="eval_stop_scope1",
        preset="test",
        owner_user_id="user-1",
        project_id="project-1",
    )
    monkeypatch.setattr(product_evals.job_manager, "get", lambda eval_id: job)

    response = client.post(
        "/v1/product-evals/eval_stop_scope1/stop",
        headers=_auth_headers("read-token"),
    )

    assert response.status_code != 403


def test_stop_product_eval_run_marks_run_and_job_stopped(
    client, session_factory, monkeypatch
) -> None:
    run_id = "00000000-0000-0000-0000-000000000501"
    with session_factory() as session:
        _seed_api_key(session, token="write-token", scopes=["runs:write"])
        now = utc_now_naive()
        session.add(
            Run(
                id=run_id,
                project_id="project-1",
                created_by_user_id="user-1",
                owner_user_id="user-1",
                task="test_task",
                dataset="dataset-1",
                model="model-1",
                metrics=["exact_match"],
                status=RunWorkflowStatus.RUNNING,
                started_at=now,
                last_event_at=now,
            )
        )
        session.commit()

    job = ProductEvalJob(
        job_id="job-1",
        preset="test",
        owner_user_id="user-1",
        project_id="project-1",
        expected_runs=1,
    )
    job.mark_run(sdk_run_id="sdk-run-1", status="RUNNING", qym_run_id=run_id)
    job.mark(status="RUNNING", run_id=run_id)

    monkeypatch.setattr(product_evals.job_manager, "get_by_qym_run_id", lambda _: job)

    response = client.post(
        f"/v1/product-evals/{run_id}/stop",
        headers=_auth_headers("write-token"),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["status"] == "STOPPED"
    assert payload["stopped_qym_runs"] == 1

    with session_factory() as session:
        run = session.query(Run).filter(Run.id == run_id).first()
        assert run is not None
        assert run.status == RunWorkflowStatus.STOPPED
        assert run.status_reason == "product_eval_stopped"


def test_submit_rejects_invalid_preset(client, session_factory) -> None:
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


def test_submit_rejects_client_config_field(client, session_factory) -> None:
    with session_factory() as session:
        _seed_api_key(session, token="submit-token", scopes=["runs:write"])

    response = client.post(
        "/v1/product-evals",
        headers=_auth_headers("submit-token"),
        json={"preset": "test", "config": {"max_concurrency": 1}},
    )

    assert response.status_code == 400
    envelope = response.json()
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "invalid_request"
    assert "config is not accepted" in envelope["error"]["message"]


def test_submit_returns_429_when_product_eval_slots_are_full(
    client, session_factory, monkeypatch
) -> None:
    with session_factory() as session:
        _seed_api_key(session, token="submit-token", scopes=["runs:write"])

    def fake_submit(**kwargs):
        raise ProductEvalQueueFull(
            "Too many product eval jobs are already running. Try again later."
        )

    monkeypatch.setattr(product_evals.job_manager, "submit", fake_submit)

    response = client.post(
        "/v1/product-evals",
        headers=_auth_headers("submit-token"),
        json={"preset": "test"},
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "30"
    envelope = response.json()
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "queue_full"
    assert "Too many product eval jobs" in envelope["error"]["message"]


def test_submit_rejects_blank_dataset_name(client, session_factory) -> None:
    with session_factory() as session:
        _seed_api_key(session, token="submit-token", scopes=["runs:write"])

    response = client.post(
        "/v1/product-evals",
        headers=_auth_headers("submit-token"),
        json={"preset": "insightor", "dataset": "   "},
    )

    assert response.status_code == 400
    envelope = response.json()
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "invalid_request"
    assert (
        "dataset must be a non-empty Langfuse dataset name"
        in envelope["error"]["message"]
    )


def test_submit_rejects_test_preset_dataset_override(client, session_factory) -> None:
    with session_factory() as session:
        _seed_api_key(session, token="submit-token", scopes=["runs:write"])

    response = client.post(
        "/v1/product-evals",
        headers=_auth_headers("submit-token"),
        json={"preset": "test", "dataset": "customer-dataset"},
    )

    assert response.status_code == 400
    envelope = response.json()
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "invalid_request"
    assert "dataset is not accepted for preset 'test'" in envelope["error"]["message"]


def test_insightor_preset_defaults_dataset_name(monkeypatch, tmp_path) -> None:
    script = tmp_path / "insightor_eval.py"
    script.write_text(
        "\n".join(
            [
                "def insightor_api(value):",
                "    return value",
                "def accuracy(output, expected):",
                "    return True",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("QYM_INSIGHTOR_EVAL_SCRIPT", str(script))

    preset = validate_submit_request(
        preset_name="insightor",
        dataset_name=None,
        runtime_inputs=ProductEvalRuntimeInputs(
            insightor_url="https://insightor.example.com",
            refresh_token="refresh-token-1",
        ),
    )

    assert preset.default_dataset_name == "playground_set_v2"
    assert preset.requires_dataset_name is False


def test_insightor_preset_rejects_env_effective_concurrency_above_20(
    monkeypatch, tmp_path
) -> None:
    script = tmp_path / "insightor_eval.py"
    script.write_text(
        "\n".join(
            [
                "def insightor_api(value):",
                "    return value",
                "def accuracy(output, expected):",
                "    return True",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("QYM_INSIGHTOR_EVAL_SCRIPT", str(script))
    monkeypatch.setenv("QYM_PRODUCT_EVAL_MAX_CONCURRENCY", "11")
    monkeypatch.setenv("QYM_PRODUCT_EVAL_MAX_PARALLEL_RUNS", "2")

    with pytest.raises(ProductEvalError, match="less than or equal to 20"):
        get_preset("insightor")


def test_submit_requires_insightor_runtime_inputs(client, session_factory) -> None:
    with session_factory() as session:
        _seed_api_key(session, token="submit-token", scopes=["runs:write"])

    response = client.post(
        "/v1/product-evals",
        headers=_auth_headers("submit-token"),
        json={"preset": "insightor", "dataset": "dataset-1"},
    )

    assert response.status_code == 400
    envelope = response.json()
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "invalid_request"
    assert (
        "insightor_url, refresh_token required for preset 'insightor'"
        in envelope["error"]["message"]
    )


def test_test_preset_uses_self_contained_runner(monkeypatch) -> None:
    monkeypatch.delenv("EVAL_DATASET", raising=False)

    preset = validate_submit_request(preset_name="test")

    assert preset.name == "test"
    assert preset.script_path.name == "test_eval.py"
    assert "product_eval_presets" in preset.script_path.parts
    assert preset.run_count == 3
    assert preset.metric_name == "exact_match"
    assert preset.default_config["max_concurrency"] == 10


def test_test_preset_rejects_dataset_override() -> None:
    with pytest.raises(ProductEvalError, match="dataset is not accepted"):
        validate_submit_request(preset_name="test", dataset_name="customer-dataset")


def test_job_manager_uses_configured_worker_count(monkeypatch) -> None:
    monkeypatch.setenv("QYM_PRODUCT_EVAL_MAX_WORKERS", "3")

    manager = ProductEvalJobManager()

    assert manager._executor._max_workers == 3
    manager._executor.shutdown(wait=False, cancel_futures=True)


def test_job_manager_rejects_when_all_worker_slots_are_active(monkeypatch) -> None:
    manager = ProductEvalJobManager(max_workers=1)
    started = threading.Event()
    release = threading.Event()

    def blocking_run(job, *args):
        job.mark(status="RUNNING")
        started.set()
        release.wait(timeout=5)
        job.mark(status="COMPLETED")

    monkeypatch.setattr(manager, "_run_job", blocking_run)

    first = manager.submit(
        preset_name="test",
        api_key="token",
        run_name=None,
        task_name=None,
        dataset_name=None,
        runtime_inputs=None,
        model=None,
        metadata={},
        platform_url="http://testserver",
    )
    assert started.wait(timeout=5)

    with pytest.raises(ProductEvalQueueFull):
        manager.submit(
            preset_name="test",
            api_key="token",
            run_name=None,
            task_name=None,
            dataset_name=None,
            runtime_inputs=None,
            model=None,
            metadata={},
            platform_url="http://testserver",
        )

    release.set()
    assert first._future is not None
    first._future.result(timeout=5)
    manager._executor.shutdown(wait=False, cancel_futures=True)


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


def test_insightor_preset_uses_samples_repeat_run(
    monkeypatch, tmp_path
) -> None:
    """run_count>1 now runs ONE Evaluator with samples=k (native repeat runs)."""
    script = tmp_path / "insightor_eval.py"
    script.write_text(
        "\n".join(
            [
                "MODEL = 'model-from-script'",
                "RUNTIME = {}",
                "def configure_runtime(**kwargs):",
                "    RUNTIME.update(kwargs)",
                "def insightor_api(value):",
                "    return value",
                "def accuracy(output, expected):",
                "    return True",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("EVAL_DATASET", raising=False)
    monkeypatch.setenv("QYM_INSIGHTOR_EVAL_SCRIPT", str(script))
    monkeypatch.setenv("QYM_PRODUCT_EVAL_MAX_CONCURRENCY", "6")
    monkeypatch.setenv("QYM_PRODUCT_EVAL_TIMEOUT", "30")
    monkeypatch.setenv("QYM_PRODUCT_EVAL_MAX_RETRIES", "1")
    monkeypatch.setenv("QYM_PRODUCT_EVAL_MAX_PARALLEL_RUNS", "3")

    import types

    import qym
    from qym.core.results import EvaluationResult

    captured: dict[str, object] = {}

    def sampled_result() -> EvaluationResult:
        # item-1 passes only on pass 1; item-2 never passes — same outcome
        # matrix the old three-run version produced.
        result = EvaluationResult("dataset-1", "external-run", ["accuracy"])
        result.samples = 3
        pass_scores = {"item-1": [1.0, 0.0, 0.0], "item-2": [0.0, 0.0, 0.0]}
        for item_id, scores in pass_scores.items():
            for pass_number, score in enumerate(scores, start=1):
                result.add_pass_result(
                    item_id,
                    pass_number,
                    {"scores": {"accuracy": score}, "time": 0.1, "retry_count": 0},
                )
        return result

    class FakeEvaluator:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self, show_tui=True, auto_save=True, **kwargs):
            captured["show_tui"] = show_tui
            captured["auto_save"] = auto_save
            progress = captured.get("progress_callback")
            if callable(progress):
                progress(
                    types.SimpleNamespace(
                        event="run_start",
                        run_id="sdk-run-1",
                        run_info={"platform_run_id": "qym-run-1"},
                    )
                )
                progress(
                    types.SimpleNamespace(event="run_complete", run_id="sdk-run-1")
                )
            return sampled_result()

    monkeypatch.setattr(qym, "Evaluator", FakeEvaluator)

    manager = ProductEvalJobManager(max_workers=1)
    job = manager.submit(
        preset_name="insightor",
        api_key="token",
        run_name="external-run",
        task_name=None,
        dataset_name=None,
        runtime_inputs=ProductEvalRuntimeInputs(
            insightor_url="https://insightor.example.com",
            refresh_token="refresh-token-1",
            agent_version="agent-v1",
            image_version="image-v1",
            kb_version="kb-v1",
        ),
        model="model-1",
        metadata={"source": "test"},
        platform_url="http://testserver",
    )
    assert job._future is not None
    job._future.result(timeout=5)

    assert captured["show_tui"] is False
    assert captured["auto_save"] is False
    config = captured["config"]
    assert config["samples"] == 3  # ONE run with k passes, not k runs
    assert callable(config["should_stop"])
    assert captured["model"] == "model-1"
    assert captured["dataset"] == "playground_set_v2"
    assert config["run_name"] == "external-run"
    assert config["max_concurrency"] == 6
    assert config["timeout"] == 30
    assert config["max_retries"] == 1
    assert "max_parallel_runs" not in config
    assert config["metric_timeout"] == 300
    assert config["checkpoint_enabled"] is False
    runtime = captured["task"].__globals__["RUNTIME"]
    assert runtime["INSIGHTOR_URL"] == "https://insightor.example.com"
    assert runtime["REFRESH_TOKEN"] == "refresh-token-1"
    assert runtime["AGENT_VERSION"] == "agent-v1"
    assert runtime["IMAGE_VERSION"] == "image-v1"
    assert runtime["KB_VERSION"] == "kb-v1"
    assert config["run_metadata"]["product_eval"]["attempt"] == 1
    assert config["run_metadata"]["product_eval"]["attempts"] == 3
    assert job.eval_id.startswith("eval_")
    assert config["run_metadata"]["product_eval"]["eval_id"] == job.eval_id
    assert "job_id" not in config["run_metadata"]["product_eval"]
    assert "product_eval_id" not in config["run_metadata"]["product_eval"]
    assert job.status == "COMPLETED"
    assert job.run_id == "qym-run-1"
    assert job.group_analysis is not None
    assert job.group_analysis["pass_at_3"] == pytest.approx(0.5)
    assert job.group_analysis["avg_at_3"] == pytest.approx(1 / 6)
    assert job.group_analysis["consistency"] == pytest.approx(2 / 3)
    assert job.group_analysis["reliability"] == pytest.approx(1 / 3)
    assert job.group_analysis["avg_latency_ms"] == pytest.approx(100.0)


def test_insightor_stop_reaches_sampled_run_mid_flight(
    monkeypatch, tmp_path
) -> None:
    """Stop requests wire into the samples=k run via config.should_stop."""
    script = tmp_path / "insightor_eval.py"
    script.write_text(
        "\n".join(
            [
                "RUNTIME = {}",
                "def configure_runtime(**kwargs):",
                "    RUNTIME.update(kwargs)",
                "def insightor_api(value):",
                "    return value",
                "def accuracy(output, expected):",
                "    return True",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("QYM_INSIGHTOR_EVAL_SCRIPT", str(script))
    monkeypatch.setenv("QYM_PRODUCT_EVAL_MAX_PARALLEL_RUNS", "1")

    import types

    import qym
    from qym.core.results import EvaluationResult

    calls: list[dict[str, object]] = []
    job = ProductEvalJob(
        job_id="eval_stop_batches",
        preset="insightor",
        expected_runs=3,
    )
    preset = get_preset("insightor")

    class FakeEvaluator:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            calls.append(kwargs)

        def run(self, show_tui=True, auto_save=True, **kwargs):
            progress = self.kwargs.get("progress_callback")
            if callable(progress):
                progress(
                    types.SimpleNamespace(
                        event="run_start",
                        run_id="sdk-run-1",
                        run_info={"platform_run_id": "qym-run-1"},
                    )
                )
            # A stop request mid-run must be visible to the evaluator via
            # config.should_stop (the SDK checks it between items/passes).
            job.request_stop()
            assert self.kwargs["config"]["should_stop"]() is True
            if callable(progress):
                progress(
                    types.SimpleNamespace(event="run_complete", run_id="sdk-run-1")
                )
            result = EvaluationResult("dataset-1", "attempt-1", ["accuracy"])
            result.samples = 3
            result.interrupted = True
            result.add_pass_result(
                "item-1",
                1,
                {"scores": {"accuracy": 1.0}, "time": 0.1, "retry_count": 0},
            )
            return result

    monkeypatch.setattr(qym, "Evaluator", FakeEvaluator)

    manager = ProductEvalJobManager(max_workers=1)
    manager._run_job(
        job,
        preset,
        "token",
        "external-run",
        None,
        None,
        ProductEvalRuntimeInputs(
            insightor_url="https://insightor.example.com",
            refresh_token="refresh-token-1",
        ),
        "model-1",
        {},
        "http://testserver",
    )

    assert len(calls) == 1  # ONE Evaluator for all k passes
    assert job.status == "STOPPED"
    assert job.group_analysis is None
    first = calls[0]
    assert first["config"]["samples"] == 3
    assert first["config"]["should_stop"] == job.stop_requested
    assert first["config"]["checkpoint_enabled"] is False
    assert first["task"]("value") == "value"
    assert first["metrics"][0]("output", "expected") is True


def test_submit_allows_any_valid_key(client, session_factory) -> None:
    # Scopes are no longer enforced: a key without runs:write is not blocked on scope.
    with session_factory() as session:
        _seed_api_key(session, token="read-token", scopes=["runs:read"])

    response = client.post(
        "/v1/product-evals",
        headers=_auth_headers("read-token"),
        json={"preset": "insightor"},
    )

    assert response.status_code != 403


def test_poll_allows_any_valid_key(client, session_factory) -> None:
    # Scopes are no longer enforced: a key without runs:read is not blocked on scope.
    with session_factory() as session:
        _seed_api_key(session, token="write-token", scopes=["runs:write"])

    response = client.get(
        "/v1/product-evals/run-1", headers=_auth_headers("write-token")
    )

    assert response.status_code != 403


def test_poll_unknown_eval_id_returns_standard_404(client, session_factory) -> None:
    with session_factory() as session:
        _seed_api_key(session, token="read-token", scopes=["runs:read"])

    response = client.get(
        "/v1/product-evals/eval_missing1", headers=_auth_headers("read-token")
    )

    assert response.status_code == 404
    envelope = response.json()
    assert envelope["ok"] is False
    assert envelope["data"] is None
    assert envelope["error"]["code"] == "not_found"
    assert envelope["error"]["message"] == "Eval not found"


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
    assert "config" not in payload
    assert "items" not in payload


def test_poll_stopped_eval_reports_pending_without_failed_items(
    client, session_factory
) -> None:
    eval_id = "eval_stopped_pending"
    run_id = "00000000-0000-0000-0000-000000000311"
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
            status=RunWorkflowStatus.STOPPED,
            run_metadata={
                "total_items": 100,
                "product_eval": {
                    "eval_id": eval_id,
                    "preset": "insightor",
                    "attempt": 1,
                    "attempts": 3,
                },
            },
            run_config={"run_name": "external-1"},
            started_at=now,
            ended_at=now,
            last_event_at=now,
        )
        item = RunItem(
            run_id=run_id,
            item_id="item-1",
            index=0,
            input={"question": "q1"},
            expected="select 1",
            output={"sql": "select 1"},
            item_metadata={},
            latency_ms=120.0,
        )
        score = RunItemScore(
            run_id=run_id,
            item_id="item-1",
            metric_name="accuracy",
            score_numeric=1.0,
            score_raw=True,
            meta={},
        )
        event = RunEvent(
            run_id=run_id,
            event_id="00000000-0000-0000-0000-000000000312",
            sequence=1,
            type="item_completed",
            sent_at=now,
            payload={"item_id": "item-1"},
        )
        session.add_all([run, item, score, event])
        session.commit()

    response = client.get(
        f"/v1/product-evals/{eval_id}", headers=_auth_headers("read-token")
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["status"] == "STOPPED"
    assert payload["group_analysis"] is None
    summary = payload["runs"][0]["summary"]
    assert summary["total"] == 100
    assert summary["completed"] == 1
    assert summary["failed"] == 0
    assert summary["in_progress"] == 0
    assert summary["pending"] == 99
    assert summary["metric_stats"]["accuracy"]["mean"] == 1.0


def test_poll_by_eval_id_recovers_runs_from_db(client, session_factory) -> None:
    eval_id = "eval_db1"
    now = utc_now_naive()
    with session_factory() as session:
        _seed_api_key(
            session, token="read-token", scopes=["runs:read"], user_id="owner-1"
        )
        runs = []
        for attempt in (1, 2, 3):
            run_id = f"00000000-0000-0000-0000-00000000060{attempt}"
            runs.append(
                Run(
                    id=run_id,
                    project_id="project-1",
                    created_by_user_id="owner-1",
                    owner_user_id="owner-1",
                    task="insightor_api",
                    dataset="dataset-1",
                    model="model-1",
                    metrics=["accuracy"],
                    status=RunWorkflowStatus.COMPLETED,
                    run_metadata={
                        "total_items": 1,
                        "product_eval": {
                            "preset": "insightor",
                            "eval_id": eval_id,
                            "attempt": attempt,
                            "attempts": 3,
                        },
                    },
                    started_at=now,
                    ended_at=now,
                    last_event_at=now,
                )
            )
            session.add(
                RunItem(
                    run_id=run_id,
                    item_id=f"item-{attempt}",
                    index=0,
                    input={"question": f"q{attempt}"},
                    output="ok",
                    latency_ms=100.0 * attempt,
                )
            )
            session.add(
                RunItemScore(
                    run_id=run_id,
                    item_id=f"item-{attempt}",
                    metric_name="accuracy",
                    score_numeric=1.0,
                    score_raw=True,
                )
            )
        session.add_all(runs)
        session.commit()

    response = client.get(
        f"/v1/product-evals/{eval_id}", headers=_auth_headers("read-token")
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["eval_id"] == eval_id
    assert payload["status"] == "COMPLETED"
    assert [run["attempt"] for run in payload["runs"]] == [1, 2, 3]
    assert payload["runs"][0]["task"] == "insightor_api"
    assert payload["runs"][0]["dataset"] == "dataset-1"
    assert payload["runs"][0]["model"] == "model-1"
    assert payload["runs"][0]["summary"]["total"] == 1
    assert payload["runs"][0]["summary"]["completed"] == 1
    assert "metadata" not in payload["runs"][0]["summary"]
    assert payload["group_analysis"]["pass_at_3"] == 1.0
    assert payload["group_analysis"]["avg_at_3"] == 1.0
    assert payload["group_analysis"]["avg_latency_ms"] == 200.0
    assert payload["qym_compare_url"] == (
        "http://testserver/compare?"
        "runs=00000000-0000-0000-0000-000000000601&"
        "runs=00000000-0000-0000-0000-000000000602&"
        "runs=00000000-0000-0000-0000-000000000603"
    )


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
    monkeypatch.setenv("QYM_INSIGHTOR_EVAL_SCRIPT", str(broken_script))
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")

    manager = ProductEvalJobManager(max_workers=1)
    job = manager.submit(
        preset_name="insightor",
        api_key="token",
        run_name=None,
        task_name=None,
        dataset_name="dataset-1",
        runtime_inputs=ProductEvalRuntimeInputs(
            insightor_url="https://insightor.example.com",
            refresh_token="refresh-token-1",
        ),
        model=None,
        metadata={},
        platform_url="http://testserver",
    )
    assert job._future is not None
    job._future.result(timeout=5)

    assert job.status == "FAILED"
    assert "Function 'insightor_api' not found" in (job.error or "")
