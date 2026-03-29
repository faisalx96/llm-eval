from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("QYM_AUTH_MODE", "proxy_headers")
os.environ.setdefault("QYM_LLM_CONFIG_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
ROOT = Path(__file__).resolve().parents[2]
PLATFORM_SRC = ROOT / "packages" / "platform"
SDK_SRC = ROOT / "packages" / "sdk"
for src in (PLATFORM_SRC, SDK_SRC):
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

from qym_platform.app import create_app
from qym_platform.db.base import Base
from qym_platform.db.models import (
    ApiKey,
    CorrectionStatus,
    OrgUnit,
    OrgUnitType,
    ReviewCorrection,
    Run,
    RunItem,
    RunItemScore,
    RunWorkflowStatus,
    User,
    UserRole,
)
from qym_platform.deps import get_db
from qym_platform.security import api_key_prefix, hash_api_key


@pytest.fixture()
def session_factory(monkeypatch):
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("QYM_AUTH_MODE", "proxy_headers")
    monkeypatch.setenv("QYM_LLM_CONFIG_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setenv("QYM_ALLOW_LEGACY_EMPTY_API_KEY_SCOPES", "true")
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


def _headers(email: str) -> dict[str, str]:
    return {"X-User-Email": email}


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_platform_data(session: Session) -> None:
    team_a = OrgUnit(id="team-a", name="Team A", type=OrgUnitType.TEAM, manager_user_id="manager-a")
    team_b = OrgUnit(id="team-b", name="Team B", type=OrgUnitType.TEAM, manager_user_id="manager-b")
    manager_a = User(id="manager-a", email="manager-a@example.com", role=UserRole.MANAGER, team_unit_id=team_a.id)
    manager_b = User(id="manager-b", email="manager-b@example.com", role=UserRole.MANAGER, team_unit_id=team_b.id)
    owner = User(id="owner-1", email="owner@example.com", role=UserRole.EMPLOYEE, team_unit_id=team_a.id)
    other = User(id="other-1", email="other@example.com", role=UserRole.EMPLOYEE, team_unit_id=team_b.id)
    gm = User(id="gm-1", email="gm@example.com", role=UserRole.GM)
    admin = User(id="admin-1", email="admin@example.com", role=UserRole.ADMIN)

    run = Run(
        id="run-1",
        created_by_user_id=owner.id,
        owner_user_id=owner.id,
        task="task-1",
        dataset="dataset-1",
        metrics=["judge"],
        status=RunWorkflowStatus.COMPLETED,
        run_metadata={},
        run_config={},
    )
    item = RunItem(
        run_id=run.id,
        item_id="item-1",
        index=0,
        input={"prompt": "hello"},
        expected={"answer": "world"},
        output={"answer": "nope"},
        item_metadata={},
    )
    score = RunItemScore(
        run_id=run.id,
        item_id=item.item_id,
        metric_name="judge",
        score_numeric=0.2,
        score_raw=0.2,
        meta={},
    )
    correction = ReviewCorrection(
        run_id=run.id,
        item_id=item.item_id,
        task=run.task,
        input_snapshot=item.input,
        expected_snapshot=item.expected,
        output_snapshot=item.output,
        scores_snapshot={"judge": 0.2},
        ai_root_cause="Wrong Format",
        ai_root_cause_note="AI guess",
        human_root_cause="Wrong Format",
        human_root_cause_note="Human review",
        status=CorrectionStatus.PENDING,
        is_active=True,
    )
    session.add_all([team_a, team_b, manager_a, manager_b, owner, other, gm, admin, run, item, score, correction])
    session.commit()


def _seed_api_key(session: Session, *, token: str, scopes: list[str]) -> None:
    user = User(id=f"user-{token}", email=f"{token}@example.com", role=UserRole.EMPLOYEE)
    api_key = ApiKey(
        id=f"key-{token}",
        user_id=user.id,
        name=token,
        prefix=api_key_prefix(token),
        key_hash=hash_api_key(token),
        scopes=scopes,
    )
    session.add_all([user, api_key])
    session.commit()


def test_run_mutation_permissions_enforced(client, session_factory) -> None:
    with session_factory() as session:
        _seed_platform_data(session)

    owner_metric = client.post(
        "/api/runs/update_metric",
        headers=_headers("owner@example.com"),
        json={"file_path": "run-1", "row_index": 0, "metric_name": "judge", "new_score": 0.9},
    )
    assert owner_metric.status_code == 200

    manager_metric = client.post(
        "/api/runs/update_metric",
        headers=_headers("manager-a@example.com"),
        json={"file_path": "run-1", "row_index": 0, "metric_name": "judge", "new_score": 0.7},
    )
    assert manager_metric.status_code == 200

    other_metric = client.post(
        "/api/runs/update_metric",
        headers=_headers("other@example.com"),
        json={"file_path": "run-1", "row_index": 0, "metric_name": "judge", "new_score": 0.1},
    )
    assert other_metric.status_code == 403

    gm_root_cause = client.post(
        "/api/runs/update_root_cause",
        headers=_headers("gm@example.com"),
        json={"run_id": "run-1", "item_id": "item-1", "root_cause": "Hallucination"},
    )
    assert gm_root_cause.status_code == 403

    denied_analyze = client.post(
        "/api/runs/run-1/analyze",
        headers=_headers("other@example.com"),
        json={"item_filter": "all"},
    )
    assert denied_analyze.status_code == 403


def test_correction_review_permissions_and_filtering(client, session_factory) -> None:
    with session_factory() as session:
        _seed_platform_data(session)

    manager_list = client.get("/api/corrections", headers=_headers("manager-a@example.com"))
    assert manager_list.status_code == 200
    assert len(manager_list.json()["corrections"]) == 1

    employee_list = client.get("/api/corrections", headers=_headers("owner@example.com"))
    assert employee_list.status_code == 200
    assert employee_list.json()["corrections"] == []

    denied_get = client.get("/api/corrections/1", headers=_headers("owner@example.com"))
    assert denied_get.status_code == 403

    denied_update = client.put(
        "/api/corrections/1",
        headers=_headers("owner@example.com"),
        json={"human_root_cause_note": "should fail"},
    )
    assert denied_update.status_code == 403

    allowed_approve = client.post(
        "/api/corrections/1/approve",
        headers=_headers("manager-a@example.com"),
        json={"comment": "approved"},
    )
    assert allowed_approve.status_code == 200
    assert allowed_approve.json()["status"] == "approved"

    denied_bulk = client.post(
        "/api/corrections/bulk",
        headers=_headers("manager-b@example.com"),
        json={"ids": [1], "action": "reject", "comment": "nope"},
    )
    assert denied_bulk.status_code == 403


def test_api_key_scope_enforcement_and_legacy_compatibility(client, session_factory, monkeypatch) -> None:
    with session_factory() as session:
        _seed_api_key(session, token="write-token", scopes=["runs:write"])
        _seed_api_key(session, token="read-token", scopes=["runs:read"])
        _seed_api_key(session, token="legacy-token", scopes=[])

    write_response = client.post(
        "/v1/runs",
        headers=_auth_headers("write-token"),
        json={"task": "task", "dataset": "dataset", "metrics": [], "run_metadata": {}, "run_config": {}},
    )
    assert write_response.status_code == 200

    read_response = client.post(
        "/v1/runs",
        headers=_auth_headers("read-token"),
        json={"task": "task", "dataset": "dataset", "metrics": [], "run_metadata": {}, "run_config": {}},
    )
    assert read_response.status_code == 403

    legacy_allowed = client.post(
        "/v1/runs",
        headers=_auth_headers("legacy-token"),
        json={"task": "task", "dataset": "dataset", "metrics": [], "run_metadata": {}, "run_config": {}},
    )
    assert legacy_allowed.status_code == 200

    monkeypatch.setenv("QYM_ALLOW_LEGACY_EMPTY_API_KEY_SCOPES", "false")
    legacy_denied = client.post(
        "/v1/runs",
        headers=_auth_headers("legacy-token"),
        json={"task": "task", "dataset": "dataset", "metrics": [], "run_metadata": {}, "run_config": {}},
    )
    assert legacy_denied.status_code == 403
