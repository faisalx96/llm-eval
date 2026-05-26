from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("QYM_AUTH_MODE", "none")
os.environ.setdefault("QYM_LLM_CONFIG_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
ROOT = Path(__file__).resolve().parents[2]
for src in (ROOT / "packages" / "platform", ROOT / "packages" / "sdk"):
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

from qym_platform.app import create_app
from qym_platform.db.base import Base
from qym_platform.db.models import ApiKey, Project, ProjectMembership, ProjectRole, Run, RunItem, User, UserRole
from qym_platform.deps import get_db
from qym_platform.security import api_key_prefix, hash_api_key


@pytest.fixture()
def client_and_session(monkeypatch):
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("QYM_AUTH_MODE", "none")
    monkeypatch.setenv("QYM_ALLOW_LEGACY_EMPTY_API_KEY_SCOPES", "true")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with SessionLocal() as session:
        user = User(id="user-1", email="dev@local", display_name="Dev", role=UserRole.ADMIN)
        project = Project(id="project-1", name="Project", slug="project", created_by_user_id=user.id)
        session.add_all(
            [
                user,
                project,
                ProjectMembership(project_id=project.id, user_id=user.id, role=ProjectRole.MANAGER),
                ApiKey(
                    id="key-1",
                    user_id=user.id,
                    project_id=project.id,
                    name="test",
                    prefix=api_key_prefix("token-1"),
                    key_hash=hash_api_key("token-1"),
                    scopes=["runs:write", "runs:read", "datasets:read", "datasets:write", "datasets:delete"],
                ),
            ]
        )
        session.commit()

    app = create_app()

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client, SessionLocal
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _bearer() -> dict[str, str]:
    return {"Authorization": "Bearer token-1"}


def test_dataset_upload_publish_alias_draft_compare_and_item_runs(client_and_session, tmp_path):
    client, SessionLocal = client_and_session
    csv_path = tmp_path / "qa.csv"
    csv_path.write_text("input,expected_output,topic\nhello,world,greeting\n", encoding="utf-8")

    with csv_path.open("rb") as fh:
        upload = client.post(
            "/v1/datasets:upload",
            headers=_bearer(),
            data={
                "name": "QA",
                "version": "v1",
                "publish": "true",
                "set_alias": "production",
                "metadata_cols": "topic",
            },
            files={"file": ("qa.csv", fh, "text/csv")},
        )
    assert upload.status_code == 200
    body = upload.json()
    assert body["version"]["status"] == "published"
    assert "production" in body["version"]["aliases"]

    items = client.get("/v1/datasets/qa/versions/production/items", headers=_bearer())
    assert items.status_code == 200
    item = items.json()["items"][0]
    assert item["metadata"] == {"topic": "greeting"}

    draft = client.post(
        "/v1/datasets/qa/versions",
        headers=_bearer(),
        json={"version": "v2", "from_alias": "production"},
    )
    assert draft.status_code == 200
    assert draft.json()["version"]["status"] == "draft"

    created_item = client.post(
        "/v1/datasets/qa/versions/v2/items",
        headers=_bearer(),
        json={
            "item_id": "manual-case",
            "input": {"question": "manual"},
            "expected_output": {"answer": "case"},
            "metadata": {"topic": "manual"},
            "labels": ["manual"],
        },
    )
    assert created_item.status_code == 200
    assert created_item.json()["item"]["item_id"] == "manual-case"

    edited = client.patch(
        f"/v1/datasets/qa/versions/v2/items/{item['item_id']}",
        headers=_bearer(),
        json={
            "item_id": item["item_id"],
            "input": "hello",
            "expected_output": "WORLD",
            "metadata": {"topic": "greeting"},
            "labels": ["changed"],
        },
    )
    assert edited.status_code == 200

    published = client.post("/v1/datasets/qa/versions/v2:publish", headers=_bearer(), json={})
    assert published.status_code == 200
    promoted = client.post("/v1/datasets/qa/aliases/production", headers=_bearer(), json={"version": "v2"})
    assert promoted.status_code == 200

    compare = client.get("/v1/datasets/qa/versions/v2:compare?base=v1", headers=_bearer())
    assert compare.status_code == 200
    assert compare.json()["summary"]["changed"] == 1
    assert compare.json()["summary"]["added"] == 1

    with SessionLocal() as session:
        version_id = published.json()["version"]["id"]
        run = Run(
            id="run-1",
            project_id="project-1",
            created_by_user_id="user-1",
            owner_user_id="user-1",
            task="task",
            dataset="QA",
            dataset_id=body["dataset"]["id"],
            dataset_version_id=version_id,
            metrics=[],
            run_metadata={},
            run_config={},
        )
        session.add(run)
        session.flush()
        dataset_item_pk = edited.json()["item"]["id"]
        session.add(RunItem(run_id=run.id, item_id=item["item_id"], dataset_item_pk=dataset_item_pk, index=0, input="hello", expected="WORLD", item_metadata={}))
        session.commit()

    runs = client.get(f"/v1/datasets/qa/versions/v2/items/{item['item_id']}/runs", headers=_bearer())
    assert runs.status_code == 200
    assert runs.json()["runs"][0]["run_id"] == "run-1"
