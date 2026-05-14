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
            "dataset": "customer-langfuse-dataset",
            "insightor_url": "https://insightor.example.com",
            "refresh_token": "refresh-token-1",
            "agent_version": "agent-v1",
            "image_version": "image-v1",
            "kb_version": "kb-v1",
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
    assert payload["qym_runs"] == []
    assert payload["qym_compare_url"] is None
    assert payload["poll_url"] == "/v1/product-evals/run-1"
    assert "run_id" not in payload
    assert "job_id" not in payload
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
    assert payload["qym_runs"] == []
    assert payload["qym_compare_url"] is None
    assert payload["poll_url"] == "/v1/product-evals/jobs/job-1"
    assert "run_id" not in payload
    assert "job_id" not in payload
    assert "project_id" not in payload


def test_job_poll_returns_multi_run_compare_url(
    client, session_factory, monkeypatch
) -> None:
    with session_factory() as session:
        _seed_api_key(session, token="read-token", scopes=["runs:read"])

    job = ProductEvalJob(
        job_id="job-1",
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

    monkeypatch.setattr(product_evals.job_manager, "get", lambda job_id: job)

    response = client.get(
        "/v1/product-evals/jobs/job-1",
        headers=_auth_headers("read-token"),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["qym_run_id"] == "qym-run-1"
    assert payload["qym_run_url"] == "http://testserver/run/qym-run-1"
    assert payload["qym_compare_url"] == (
        "http://testserver/compare?runs=qym-run-1&runs=qym-run-2"
    )
    assert payload["poll_url"] == "/v1/product-evals/jobs/job-1"
    assert payload["qym_runs"] == [
        {
            "attempt": 1,
            "status": "COMPLETED",
            "qym_run_id": "qym-run-1",
            "qym_run_url": "http://testserver/run/qym-run-1",
        },
        {
            "attempt": 2,
            "status": "RUNNING",
            "qym_run_id": "qym-run-2",
            "qym_run_url": "http://testserver/run/qym-run-2",
        },
        {
            "attempt": 3,
            "status": "STARTING",
            "qym_run_id": None,
            "qym_run_url": None,
        },
    ]
    assert "group_analysis" not in payload


def test_job_poll_returns_group_analysis_when_completed(
    client, session_factory, monkeypatch
) -> None:
    with session_factory() as session:
        _seed_api_key(session, token="read-token", scopes=["runs:read"])

    job = ProductEvalJob(
        job_id="job-1",
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

    monkeypatch.setattr(product_evals.job_manager, "get", lambda job_id: job)

    response = client.get(
        "/v1/product-evals/jobs/job-1",
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


@pytest.mark.parametrize("config_key", ["metric_timeout", "max_metric_concurrency"])
def test_submit_rejects_client_controlled_metric_config(
    client, session_factory, config_key
) -> None:
    with session_factory() as session:
        _seed_api_key(session, token="submit-token", scopes=["runs:write"])

    response = client.post(
        "/v1/product-evals",
        headers=_auth_headers("submit-token"),
        json={"preset": "test", "config": {config_key: 1}},
    )

    assert response.status_code == 400
    envelope = response.json()
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "invalid_request"
    assert f"Unsupported config key(s): {config_key}" in envelope["error"]["message"]


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"max_concurrency": 21}, "config.max_concurrency must be between 1 and 20"),
        ({"timeout": 901}, "config.timeout must be between 1 and 900"),
        ({"max_retries": 3}, "config.max_retries must be between 0 and 2"),
        (
            {"max_parallel_runs": 4},
            "config.max_parallel_runs must be between 1 and 3",
        ),
        ({"max_parallel_runs": 1.5}, "config.max_parallel_runs must be an integer"),
    ],
)
def test_submit_rejects_out_of_range_config(
    client, session_factory, config, message
) -> None:
    with session_factory() as session:
        _seed_api_key(session, token="submit-token", scopes=["runs:write"])

    response = client.post(
        "/v1/product-evals",
        headers=_auth_headers("submit-token"),
        json={"preset": "test", "config": config},
    )

    assert response.status_code == 400
    envelope = response.json()
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "invalid_request"
    assert message in envelope["error"]["message"]


def test_submit_rejects_effective_concurrency_above_20(
    client, session_factory
) -> None:
    with session_factory() as session:
        _seed_api_key(session, token="submit-token", scopes=["runs:write"])

    response = client.post(
        "/v1/product-evals",
        headers=_auth_headers("submit-token"),
        json={
            "preset": "insightor",
            "insightor_url": "https://insightor.example.com",
            "refresh_token": "refresh-token-1",
            "config": {"max_concurrency": 7, "max_parallel_runs": 3},
        },
    )

    assert response.status_code == 400
    envelope = response.json()
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "invalid_request"
    assert (
        "config.max_concurrency * config.max_parallel_runs must be less than or equal to 20"
        in envelope["error"]["message"]
    )


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
        config={},
        dataset_name=None,
        runtime_inputs=ProductEvalRuntimeInputs(
            insightor_url="https://insightor.example.com",
            refresh_token="refresh-token-1",
        ),
    )

    assert preset.default_dataset_name == "playground_set_v2"
    assert preset.requires_dataset_name is False


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

    preset = validate_submit_request(preset_name="test", config={})

    assert preset.name == "test"
    assert preset.script_path.name == "test_eval.py"
    assert "product_eval_presets" in preset.script_path.parts


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
        config={},
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
            config={},
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


def test_insightor_preset_uses_three_run_parallel_attempts(
    monkeypatch, tmp_path
) -> None:
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

    import qym
    from qym.core.results import EvaluationResult

    captured: dict[str, object] = {}

    def result_for_run(name: str, scores: list[float]) -> EvaluationResult:
        result = EvaluationResult("dataset-1", name, ["accuracy"])
        for index, score in enumerate(scores, start=1):
            result.add_result(
                f"item-{index}",
                {
                    "scores": {"accuracy": score},
                    "latency_ms": 100.0,
                    "retry_count": 0,
                },
            )
        return result

    class FakeEvaluator:
        @staticmethod
        def run_parallel(**kwargs):
            captured.update(kwargs)
            observer = kwargs["observer"]
            matrix = [{"run_id": f"sdk-run-{attempt}"} for attempt in range(1, 4)]
            observer.on_run_matrix(matrix_id="matrix-1", runs=matrix, total_runs=3)
            for attempt in range(1, 4):
                observer.on_run_start(
                    run_id=f"sdk-run-{attempt}",
                    run_info={"platform_run_id": f"qym-run-{attempt}"},
                    total_items=1,
                    metrics=["accuracy"],
                )
                observer.on_run_complete(
                    run_id=f"sdk-run-{attempt}",
                    result_summary={},
                )
            return [
                result_for_run("attempt-1", [1.0, 0.0]),
                result_for_run("attempt-2", [0.0, 0.0]),
                result_for_run("attempt-3", [0.0, 0.0]),
            ]

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
        config={"max_concurrency": 6, "max_parallel_runs": 3, "timeout": 30},
        platform_url="http://testserver",
    )
    assert job._future is not None
    job._future.result(timeout=5)

    assert captured["max_parallel_runs"] == 3
    assert captured["show_tui"] is False
    assert captured["auto_save"] is False
    runs = captured["runs"]
    assert len(runs) == 3
    assert [run["name"] for run in runs] == ["external-run"] * 3
    assert [run["model"] for run in runs] == ["model-1"] * 3
    assert [run["dataset"] for run in runs] == ["playground_set_v2"] * 3
    assert [run["config"]["max_concurrency"] for run in runs] == [6] * 3
    assert "max_parallel_runs" not in runs[0]["config"]
    assert [run["config"]["metric_timeout"] for run in runs] == [300] * 3
    runtime = runs[0]["task"].__globals__["RUNTIME"]
    assert runtime["INSIGHTOR_URL"] == "https://insightor.example.com"
    assert runtime["REFRESH_TOKEN"] == "refresh-token-1"
    assert runtime["AGENT_VERSION"] == "agent-v1"
    assert runtime["IMAGE_VERSION"] == "image-v1"
    assert runtime["KB_VERSION"] == "kb-v1"
    assert [
        run["config"]["run_metadata"]["product_eval"]["attempt"] for run in runs
    ] == [1, 2, 3]
    assert [
        run["config"]["run_metadata"]["product_eval"]["attempts"] for run in runs
    ] == [3, 3, 3]
    assert job.status == "COMPLETED"
    assert job.run_id == "qym-run-1"
    assert [row["qym_run_id"] for row in job.runs] == [
        "qym-run-1",
        "qym-run-2",
        "qym-run-3",
    ]
    assert job.group_analysis is not None
    assert job.group_analysis["pass_at_3"] == pytest.approx(0.5)
    assert job.group_analysis["avg_at_3"] == pytest.approx(1 / 6)
    assert job.group_analysis["consistency"] == pytest.approx(2 / 3)
    assert job.group_analysis["reliability"] == pytest.approx(1 / 3)
    assert job.group_analysis["avg_latency_ms"] == pytest.approx(100.0)


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
        config={},
        platform_url="http://testserver",
    )
    assert job._future is not None
    job._future.result(timeout=5)

    assert job.status == "FAILED"
    assert "Function 'insightor_api' not found" in (job.error or "")
