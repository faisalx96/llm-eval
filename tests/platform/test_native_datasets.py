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
from qym_platform.db.models import (
    ApiKey,
    Project,
    ProjectMembership,
    ProjectRole,
    Run,
    RunItem,
    RunItemScore,
    User,
    UserRole,
)
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


def test_csv_upload_multi_column_input_combines_into_json(client_and_session, tmp_path):
    client, _ = client_and_session
    csv_path = tmp_path / "multi.csv"
    csv_path.write_text(
        "first,last,answer\nAda,Lovelace,mathematician\nGrace,Hopper,admiral\n",
        encoding="utf-8",
    )

    with csv_path.open("rb") as fh:
        upload = client.post(
            "/v1/datasets:upload",
            headers=_bearer(),
            data={
                "name": "Multi",
                "version": "v1",
                "publish": "true",
                "description": "people and their roles",
                "input_cols": "first,last",
                "expected_cols": "answer",
            },
            files={"file": ("multi.csv", fh, "text/csv")},
        )
    assert upload.status_code == 200, upload.text

    # The description from the upload form must land on the dataset (not only the version).
    detail = client.get("/v1/datasets/multi", headers=_bearer())
    assert detail.status_code == 200
    assert detail.json()["dataset"]["description"] == "people and their roles"

    items = client.get("/v1/datasets/multi/versions/v1/items?sort=index_asc", headers=_bearer())
    assert items.status_code == 200
    rows = items.json()["items"]
    # Multiple input columns -> JSON object keyed by column name.
    assert rows[0]["input"] == {"first": "Ada", "last": "Lovelace"}
    # Single expected column -> scalar value.
    assert rows[0]["expected_output"] == "mathematician"


def test_csv_upload_single_column_input_stays_scalar(client_and_session, tmp_path):
    client, _ = client_and_session
    csv_path = tmp_path / "single.csv"
    csv_path.write_text("question,answer\nhi,hello\n", encoding="utf-8")

    with csv_path.open("rb") as fh:
        upload = client.post(
            "/v1/datasets:upload",
            headers=_bearer(),
            data={
                "name": "Single",
                "version": "v1",
                "publish": "true",
                "input_cols": "question",
                # No expected_cols -> genuinely no expected output.
            },
            files={"file": ("single.csv", fh, "text/csv")},
        )
    assert upload.status_code == 200, upload.text

    items = client.get("/v1/datasets/single/versions/v1/items", headers=_bearer())
    row = items.json()["items"][0]
    assert row["input"] == "hi"
    assert row["expected_output"] is None


def test_recreate_dataset_after_soft_delete_reuses_slug(client_and_session, tmp_path):
    client, _ = client_and_session

    # Create a dataset, then soft-delete it.
    created = client.post("/v1/datasets", headers=_bearer(), json={"name": "Recycle", "slug": "recycle"})
    assert created.status_code == 200
    deleted = client.delete("/v1/datasets/recycle", headers=_bearer())
    assert deleted.status_code == 200

    # Re-creating with the same slug must succeed (slug freed from the soft-deleted row).
    again = client.post("/v1/datasets", headers=_bearer(), json={"name": "Recycle", "slug": "recycle"})
    assert again.status_code == 200, again.text
    assert again.json()["dataset"]["slug"] == "recycle"
    assert again.json()["dataset"]["id"] != created.json()["dataset"]["id"]

    # Same via the upload path.
    up = client.delete("/v1/datasets/recycle", headers=_bearer())
    assert up.status_code == 200
    csv_path = tmp_path / "r.csv"
    csv_path.write_text("question,answer\nhi,hello\n", encoding="utf-8")
    with csv_path.open("rb") as fh:
        upload = client.post(
            "/v1/datasets:upload",
            headers=_bearer(),
            data={"name": "Recycle", "version": "v1", "input_cols": "question", "expected_cols": "answer"},
            files={"file": ("r.csv", fh, "text/csv")},
        )
    assert upload.status_code == 200, upload.text


def test_run_payload_includes_dataset_version_and_aliases(client_and_session):
    client, SessionLocal = client_and_session
    from qym_platform.api.runs import _dataset_version_fields, _dataset_version_info_map

    created = client.post("/v1/datasets", headers=_bearer(), json={"name": "Ver", "slug": "ver"})
    assert created.status_code == 200
    dataset_id = created.json()["dataset"]["id"]
    assert client.post("/v1/datasets/ver/versions", headers=_bearer(), json={"version": "v1"}).status_code == 200
    assert client.post(
        "/v1/datasets/ver/versions/v1/items",
        headers=_bearer(),
        json={"item_id": "x", "input": "a", "expected_output": "b"},
    ).status_code == 200
    pub = client.post("/v1/datasets/ver/versions/v1:publish", headers=_bearer(), json={})
    assert pub.status_code == 200
    version_id = pub.json()["version"]["id"]
    assert client.post("/v1/datasets/ver/aliases/production", headers=_bearer(), json={"version": "v1"}).status_code == 200

    with SessionLocal() as session:
        session.add(
            Run(
                id="run-ver",
                project_id="project-1",
                created_by_user_id="user-1",
                owner_user_id="user-1",
                task="t",
                dataset="Ver",
                dataset_id=dataset_id,
                dataset_version_id=version_id,
                metrics=[],
                run_metadata={},
                run_config={},
            )
        )
        session.commit()

    with SessionLocal() as session:
        run = session.query(Run).filter(Run.id == "run-ver").first()
        fields = _dataset_version_fields(run, _dataset_version_info_map(session, [run]))
        assert fields["dataset_version"] == "v1"
        assert "production" in fields["dataset_aliases"]

    # A run with no dataset_version_id yields empty fields, not an error.
    with SessionLocal() as session:
        bare = Run(
            id="run-bare",
            project_id="project-1",
            created_by_user_id="user-1",
            owner_user_id="user-1",
            task="t",
            dataset="Ver",
            metrics=[],
            run_metadata={},
            run_config={},
        )
        fields = _dataset_version_fields(bare, _dataset_version_info_map(session, [bare]))
        assert fields["dataset_version"] is None
        assert fields["dataset_aliases"] == []


def test_dataset_runs_endpoint(client_and_session):
    client, SessionLocal = client_and_session

    created = client.post(
        "/v1/datasets",
        headers=_bearer(),
        json={"name": "Runs DS", "slug": "runs-ds"},
    )
    assert created.status_code == 200
    dataset_id = created.json()["dataset"]["id"]

    draft = client.post("/v1/datasets/runs-ds/versions", headers=_bearer(), json={"version": "v1"})
    assert draft.status_code == 200
    item = client.post(
        "/v1/datasets/runs-ds/versions/v1/items",
        headers=_bearer(),
        json={"item_id": "case-1", "input": "q", "expected_output": "a"},
    )
    assert item.status_code == 200
    published = client.post("/v1/datasets/runs-ds/versions/v1:publish", headers=_bearer(), json={})
    assert published.status_code == 200
    version_id = published.json()["version"]["id"]

    # Two runs: one against v1, one not tied to any version of this dataset.
    with SessionLocal() as session:
        run = Run(
            id="run-a",
            project_id="project-1",
            created_by_user_id="user-1",
            owner_user_id="user-1",
            task="task",
            dataset="Runs DS",
            dataset_id=dataset_id,
            dataset_version_id=version_id,
            model="gpt-test",
            metrics=[],
            run_metadata={},
            run_config={},
        )
        session.add(run)
        session.flush()
        session.add(RunItem(run_id=run.id, item_id="case-1", index=0, input="q", expected="a", item_metadata={}))
        session.add(RunItem(run_id=run.id, item_id="case-2", index=1, input="q2", expected="a2", item_metadata={}))
        session.add(RunItemScore(run_id=run.id, item_id="case-1", metric_name="accuracy", score_numeric=1.0))
        session.add(RunItemScore(run_id=run.id, item_id="case-2", metric_name="accuracy", score_numeric=0.0))
        session.commit()

    resp = client.get("/v1/datasets/runs-ds/runs", headers=_bearer())
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["total"] == 1
    row = payload["runs"][0]
    assert row["id"] == "run-a"
    assert row["version_label"] == "v1"
    assert row["model"] == "gpt-test"
    assert row["items_count"] == 2
    assert row["eval_score"] == 0.5

    # Version filter that matches the run.
    filtered = client.get("/v1/datasets/runs-ds/runs?version=v1", headers=_bearer())
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1

    # Version filter that does not exist returns 404 from version resolution.
    missing = client.get("/v1/datasets/runs-ds/runs?version=v9", headers=_bearer())
    assert missing.status_code == 404


def test_items_search_sort_label_and_bulk_endpoint_and_compare_diffs(client_and_session):
    client, _ = client_and_session

    created = client.post(
        "/v1/datasets",
        headers=_bearer(),
        json={"name": "Search Test", "slug": "search-test"},
    )
    assert created.status_code == 200
    draft = client.post(
        "/v1/datasets/search-test/versions",
        headers=_bearer(),
        json={"version": "v1"},
    )
    assert draft.status_code == 200

    for idx, payload in enumerate(
        [
            {"item_id": "alpha-1", "input": "billing question", "expected_output": "refund process", "labels": ["billing"]},
            {"item_id": "beta-1", "input": "shipping question", "expected_output": "tracking", "labels": ["logistics"]},
            {"item_id": "gamma-1", "input": "billing followup", "expected_output": "credit", "labels": ["billing", "vip"]},
        ]
    ):
        res = client.post(
            "/v1/datasets/search-test/versions/v1/items",
            headers=_bearer(),
            json=payload,
        )
        assert res.status_code == 200, res.text

    search = client.get(
        "/v1/datasets/search-test/versions/v1/items?search=billing",
        headers=_bearer(),
    )
    assert search.status_code == 200
    found_ids = sorted([item["item_id"] for item in search.json()["items"]])
    assert found_ids == ["alpha-1", "gamma-1"]
    assert search.json()["total"] == 2

    by_label = client.get(
        "/v1/datasets/search-test/versions/v1/items?label=vip",
        headers=_bearer(),
    )
    assert by_label.status_code == 200
    vip = [item["item_id"] for item in by_label.json()["items"]]
    assert vip == ["gamma-1"]

    sorted_desc = client.get(
        "/v1/datasets/search-test/versions/v1/items?sort=index_desc",
        headers=_bearer(),
    )
    assert sorted_desc.status_code == 200
    indices = [item["index"] for item in sorted_desc.json()["items"]]
    assert indices == sorted(indices, reverse=True)

    bulk = client.post(
        "/v1/datasets/search-test/versions/v1/items:bulk",
        headers=_bearer(),
        json={
            "upserts": [
                {"item_id": "alpha-1", "input": "billing question (refined)", "expected_output": "refund"},
                {"input": "brand-new", "expected_output": "new"},
            ],
            "deletes": ["beta-1"],
        },
    )
    assert bulk.status_code == 200, bulk.text
    body = bulk.json()
    assert body["summary"]["updated"] == 1
    assert body["summary"]["created"] == 1
    assert body["summary"]["deleted"] == 1

    after_bulk = client.get(
        "/v1/datasets/search-test/versions/v1/items",
        headers=_bearer(),
    )
    assert after_bulk.status_code == 200
    ids = sorted(it["item_id"] for it in after_bulk.json()["items"])
    assert "beta-1" not in ids
    assert any(it.startswith("item-") or it == "alpha-1" or it == "gamma-1" for it in ids)

    publish_v1 = client.post(
        "/v1/datasets/search-test/versions/v1:publish",
        headers=_bearer(),
        json={"set_alias": "production"},
    )
    assert publish_v1.status_code == 200

    draft_v2 = client.post(
        "/v1/datasets/search-test/versions",
        headers=_bearer(),
        json={"version": "v2", "from_alias": "production"},
    )
    assert draft_v2.status_code == 200

    edit = client.patch(
        "/v1/datasets/search-test/versions/v2/items/alpha-1",
        headers=_bearer(),
        json={"input": "completely new input", "expected_output": "different"},
    )
    assert edit.status_code == 200

    compare = client.get(
        "/v1/datasets/search-test/versions/v2:compare?base=v1&include_diffs=1",
        headers=_bearer(),
    )
    assert compare.status_code == 200
    payload = compare.json()
    assert "field_diffs" in payload
    assert any(d["item_id"] == "alpha-1" for d in payload["field_diffs"])
    assert "added_items" in payload
    assert "removed_items" in payload
