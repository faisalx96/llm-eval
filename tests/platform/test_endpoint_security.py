from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("QYM_AUTH_MODE", "proxy_headers")
os.environ.setdefault(
    "QYM_LLM_CONFIG_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8")
)
ROOT = Path(__file__).resolve().parents[2]
PLATFORM_SRC = ROOT / "packages" / "platform"
SDK_SRC = ROOT / "packages" / "sdk"
for src in (PLATFORM_SRC, SDK_SRC):
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

from qym_platform.app import create_app
from qym_platform.api import analysis as analysis_api
from qym_platform.db.base import Base
from qym_platform.db.models import (
    ApiKey,
    AuditLog,
    CorrectionStatus,
    Project,
    ProjectLlmConnection,
    ProjectMembership,
    ProjectRole,
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
from qym_platform.services.analysis_aggregation import AnalysisAggregationError


@pytest.fixture()
def session_factory(monkeypatch):
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("QYM_AUTH_MODE", "proxy_headers")
    monkeypatch.setenv(
        "QYM_LLM_CONFIG_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8")
    )
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
    return {"X-User-Email": email, "Origin": "http://localhost:8000"}


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_platform_data(session: Session) -> None:
    manager_a = User(
        id="manager-a", email="manager-a@example.com", role=UserRole.MEMBER
    )
    manager_b = User(
        id="manager-b", email="manager-b@example.com", role=UserRole.MEMBER
    )
    owner = User(id="owner-1", email="owner@example.com", role=UserRole.MEMBER)
    other = User(id="other-1", email="other@example.com", role=UserRole.MEMBER)
    nonmember = User(
        id="nonmember-1", email="nonmember@example.com", role=UserRole.MEMBER
    )
    admin = User(id="admin-1", email="admin@example.com", role=UserRole.ADMIN)

    project_a = Project(
        id="project-a", name="Project A", slug="project-a", created_by_user_id=admin.id
    )
    project_b = Project(
        id="project-b", name="Project B", slug="project-b", created_by_user_id=admin.id
    )
    memberships = [
        ProjectMembership(
            project_id=project_a.id,
            user_id=manager_a.id,
            role=ProjectRole.MANAGER,
            added_by_user_id=admin.id,
        ),
        ProjectMembership(
            project_id=project_a.id,
            user_id=owner.id,
            role=ProjectRole.MEMBER,
            added_by_user_id=admin.id,
        ),
        ProjectMembership(
            project_id=project_b.id,
            user_id=manager_b.id,
            role=ProjectRole.MANAGER,
            added_by_user_id=admin.id,
        ),
        ProjectMembership(
            project_id=project_b.id,
            user_id=other.id,
            role=ProjectRole.MEMBER,
            added_by_user_id=admin.id,
        ),
    ]

    run = Run(
        id="run-1",
        project_id=project_a.id,
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
    session.add_all(
        [manager_a, manager_b, owner, other, nonmember, admin, project_a, project_b]
    )
    session.add_all(memberships)
    session.add_all([run, item, score, correction])
    session.commit()


def _seed_api_key(session: Session, *, token: str, scopes: list[str]) -> None:
    user = User(id=f"user-{token}", email=f"{token}@example.com", role=UserRole.MEMBER)
    project = Project(
        id=f"project-{token}",
        name=f"Project {token}",
        slug=f"project-{token}",
        created_by_user_id=user.id,
    )
    membership = ProjectMembership(
        project_id=project.id,
        user_id=user.id,
        role=ProjectRole.MEMBER,
        added_by_user_id=user.id,
    )
    api_key = ApiKey(
        id=f"key-{token}",
        user_id=user.id,
        project_id=project.id,
        name=token,
        prefix=api_key_prefix(token),
        key_hash=hash_api_key(token),
        scopes=scopes,
    )
    session.add_all([user, project, membership, api_key])
    session.commit()


def test_project_analysis_context_works_without_runs(client, session_factory) -> None:
    with session_factory() as session:
        manager = User(
            id="empty-project-manager",
            email="empty-project-manager@example.com",
            role=UserRole.MEMBER,
        )
        project = Project(
            id="empty-project",
            name="Empty Project",
            slug="empty-project",
            created_by_user_id=manager.id,
        )
        membership = ProjectMembership(
            project_id=project.id,
            user_id=manager.id,
            role=ProjectRole.MANAGER,
            added_by_user_id=manager.id,
        )
        session.add_all([manager, project, membership])
        session.commit()

    config = client.get(
        "/api/projects/empty-project/analysis-config",
        headers=_headers("empty-project-manager@example.com"),
    )
    assert config.status_code == 200
    assert config.json()["total_items"] == 0
    assert config.json()["analysis_rules"] == []

    empty_documents = client.get(
        "/api/projects/empty-project/analysis-documents",
        headers=_headers("empty-project-manager@example.com"),
    )
    assert empty_documents.status_code == 200
    assert empty_documents.json()["documents"] == []

    uploaded = client.post(
        "/api/projects/empty-project/analysis-documents",
        headers=_headers("empty-project-manager@example.com"),
        files={"file": ("rubric.txt", b"Use evidence.", "text/plain")},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["document"]["content"] == "Use evidence."

    versions = client.get(
        "/api/projects/empty-project/analysis-rule-versions",
        headers=_headers("empty-project-manager@example.com"),
    )
    assert versions.status_code == 200
    assert versions.json()["versions"] == []

    draft = client.post(
        "/api/projects/empty-project/analysis-rule-versions",
        headers=_headers("empty-project-manager@example.com"),
        json={"description": "First project draft"},
    )
    assert draft.status_code == 200
    assert draft.json()["version"]["status"] == "draft"

    denied = client.get(
        "/api/projects/empty-project/analysis-config",
        headers=_headers("not-a-project-member@example.com"),
    )
    assert denied.status_code == 403


def test_proxy_headers_auto_provisions_new_user(client, session_factory):
    response = client.get("/api/runs", headers=_headers("new.user@example.com"))
    assert response.status_code == 200

    with session_factory() as session:
        user = session.query(User).filter(User.email == "new.user@example.com").first()
        assert user is not None
        assert user.role == UserRole.MEMBER
        assert user.display_name == "New User"


def test_run_mutation_permissions_enforced(client, session_factory) -> None:
    with session_factory() as session:
        _seed_platform_data(session)

    owner_metric = client.post(
        "/api/runs/update_metric",
        headers=_headers("owner@example.com"),
        json={
            "file_path": "run-1",
            "row_index": 0,
            "metric_name": "judge",
            "new_score": 0.9,
        },
    )
    assert owner_metric.status_code == 200

    manager_metric = client.post(
        "/api/runs/update_metric",
        headers=_headers("manager-a@example.com"),
        json={
            "file_path": "run-1",
            "row_index": 0,
            "metric_name": "judge",
            "new_score": 0.7,
        },
    )
    assert manager_metric.status_code == 200

    other_metric = client.post(
        "/api/runs/update_metric",
        headers=_headers("other@example.com"),
        json={
            "file_path": "run-1",
            "row_index": 0,
            "metric_name": "judge",
            "new_score": 0.1,
        },
    )
    assert other_metric.status_code == 403

    nonmember_root_cause = client.post(
        "/api/runs/update_root_cause",
        headers=_headers("nonmember@example.com"),
        json={"run_id": "run-1", "item_id": "item-1", "root_cause": "Hallucination"},
    )
    assert nonmember_root_cause.status_code == 403

    denied_analyze = client.post(
        "/api/runs/run-1/analyze",
        headers=_headers("other@example.com"),
        json={"item_filter": "all"},
    )
    assert denied_analyze.status_code == 403

    denied_aggregate = client.post(
        "/api/runs/run-1/aggregate-analysis",
        headers=_headers("other@example.com"),
        json={},
    )
    assert denied_aggregate.status_code == 403

    owner_document = client.post(
        "/api/runs/run-1/analysis-documents",
        headers=_headers("owner@example.com"),
        files={"file": ("rubric.txt", b"Answers must cite evidence.", "text/plain")},
    )
    assert owner_document.status_code == 200
    assert owner_document.json()["document"]["content"] == "Answers must cite evidence."
    document_id = owner_document.json()["document"]["id"]

    with session_factory() as session:
        session.add(
            Run(
                id="run-2",
                project_id="project-a",
                created_by_user_id="owner-1",
                owner_user_id="owner-1",
                task="task-2",
                dataset="dataset-2",
                metrics=["judge"],
                status=RunWorkflowStatus.COMPLETED,
                run_metadata={},
                run_config={},
            )
        )
        session.commit()

    owner_library = client.get(
        "/api/runs/run-1/analysis-documents",
        headers=_headers("owner@example.com"),
    )
    assert owner_library.status_code == 200
    assert owner_library.json()["documents"] == [owner_document.json()["document"]]

    manager_library = client.get(
        "/api/runs/run-1/analysis-documents",
        headers=_headers("manager-a@example.com"),
    )
    assert manager_library.status_code == 200
    assert manager_library.json()["documents"] == [owner_document.json()["document"]]

    second_run_library = client.get(
        "/api/runs/run-2/analysis-documents",
        headers=_headers("manager-a@example.com"),
    )
    assert second_run_library.status_code == 200
    assert second_run_library.json()["documents"][0]["id"] == document_id
    assert second_run_library.json()["documents"][0]["selected"] is True

    deselected = client.patch(
        f"/api/runs/run-1/analysis-documents/{document_id}",
        headers=_headers("owner@example.com"),
        json={"selected": False},
    )
    assert deselected.status_code == 200
    assert deselected.json()["document"]["selected"] is False
    project_selection_from_second_run = client.get(
        "/api/runs/run-2/analysis-documents",
        headers=_headers("manager-a@example.com"),
    )
    assert (
        project_selection_from_second_run.json()["documents"][0]["selected"]
        is False
    )

    manager_can_change_project_document_selection = client.patch(
        f"/api/runs/run-1/analysis-documents/{document_id}",
        headers=_headers("manager-a@example.com"),
        json={"selected": True},
    )
    assert manager_can_change_project_document_selection.status_code == 200
    assert (
        manager_can_change_project_document_selection.json()["document"]["selected"]
        is True
    )

    shared_selection = client.get(
        "/api/runs/run-1/analysis-documents",
        headers=_headers("owner@example.com"),
    )
    assert shared_selection.json()["documents"][0]["selected"] is True
    shared_selection_from_second_run = client.get(
        "/api/runs/run-2/analysis-documents",
        headers=_headers("manager-a@example.com"),
    )
    assert shared_selection_from_second_run.json()["documents"][0]["selected"] is True

    denied_document = client.post(
        "/api/runs/run-1/analysis-documents",
        headers=_headers("other@example.com"),
        files={"file": ("rubric.txt", b"Answers must cite evidence.", "text/plain")},
    )
    assert denied_document.status_code == 403

    deleted = client.delete(
        f"/api/runs/run-1/analysis-documents/{document_id}",
        headers=_headers("owner@example.com"),
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True, "document_id": document_id}


def test_saved_analysis_can_be_aggregated_from_the_run(
    client, session_factory, monkeypatch
) -> None:
    with session_factory() as session:
        _seed_platform_data(session)
        item = (
            session.query(RunItem)
            .filter(RunItem.run_id == "run-1", RunItem.item_id == "item-1")
            .one()
        )
        item.item_metadata = {
            "metric_analyses": {
                "judge": {
                    "source": "ai",
                    "root_cause": "Reasoning Error",
                    "root_cause_detail": "Incorrect grouping",
                }
            }
        }
        session.commit()

    monkeypatch.setattr(
        analysis_api,
        "_get_llm_config",
        lambda *_args, **_kwargs: {"llm_model": "test-model"},
    )
    monkeypatch.setattr(analysis_api, "build_client", lambda *_args: object())

    response = client.post(
        "/api/runs/run-1/aggregate-analysis",
        headers=_headers("owner@example.com"),
        json={},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"
    assert response.json()["categories"] == {"Reasoning Error": 1}
    with session_factory() as session:
        run = session.get(Run, "run-1")
        assert run is not None
        assert run.run_metadata["analysis_aggregation"]["status"] == "succeeded"
        assert run.run_metadata["analysis_aggregation"]["aggregated"] == 0


def test_saved_analysis_aggregation_failure_is_persisted_for_the_run_ui(
    client, session_factory, monkeypatch
) -> None:
    with session_factory() as session:
        _seed_platform_data(session)

    monkeypatch.setattr(
        analysis_api,
        "_get_llm_config",
        lambda *_args, **_kwargs: {"llm_model": "test-model"},
    )
    monkeypatch.setattr(analysis_api, "build_client", lambda *_args: object())
    monkeypatch.setattr(
        analysis_api,
        "_aggregate_run_analysis_results",
        AsyncMock(
            side_effect=AnalysisAggregationError(
                "root_cause_detail aggregation quality retry failed"
            )
        ),
    )

    response = client.post(
        "/api/runs/run-1/aggregate-analysis",
        headers=_headers("owner@example.com"),
        json={},
    )

    assert response.status_code == 502
    assert response.headers["X-Qym-Aggregation-Status"] == "failed"
    assert "quality retry failed" in response.json()["detail"]
    with session_factory() as session:
        run = session.get(Run, "run-1")
        assert run is not None
        status = run.run_metadata["analysis_aggregation"]
        assert status["status"] == "failed"
        assert status["metrics"] is None
        assert "quality retry failed" in status["error"]


def test_regular_member_cannot_repoint_preserved_llm_key(
    client, session_factory, monkeypatch
) -> None:
    with session_factory() as session:
        _seed_platform_data(session)
    monkeypatch.setenv("QYM_ALLOW_PRIVATE_LLM_BASE_URLS", "true")

    created = client.post(
        "/v1/projects/project-a/llm-connections",
        headers=_headers("manager-a@example.com"),
        json={
            "name": "trusted",
            "llm_base_url": "http://127.0.0.1:9999/v1",
            "llm_model": "test-model",
            "llm_api_key": "sk-protected",
        },
    )
    assert created.status_code == 200

    denied = client.put(
        f"/v1/projects/project-a/llm-connections/{created.json()['id']}",
        headers=_headers("owner@example.com"),
        json={
            "name": "stolen",
            "llm_base_url": "https://attacker.example/v1",
            "llm_model": "test-model",
            "llm_api_key": "__KEEP__",
        },
    )

    assert denied.status_code == 403
    with session_factory() as session:
        connection = session.get(ProjectLlmConnection, created.json()["id"])
        assert connection is not None
        assert connection.name == "trusted"
        assert connection.llm_base_url == "http://127.0.0.1:9999/v1"


def test_metric_root_cause_edits_are_scoped_and_audited(
    client, session_factory
) -> None:
    with session_factory() as session:
        _seed_platform_data(session)
        item = (
            session.query(RunItem)
            .filter(RunItem.run_id == "run-1", RunItem.item_id == "item-1")
            .one()
        )
        assert item is not None
        item.item_metadata = {
            "root_cause": "Item Summary",
            "root_cause_source": "ai",
            "keep_me": "untouched",
            "metric_analyses": {
                "judge": {
                    "source": "ai",
                    "root_cause": "Wrong Format",
                    "root_cause_detail": "Bad envelope",
                    "root_cause_note": "Original explanation",
                    "confidence": 0.82,
                    "solution": "Refine Prompt Instructions",
                }
            },
        }
        session.commit()

    changed = client.post(
        "/api/runs/update_root_cause",
        headers=_headers("owner@example.com"),
        json={
            "run_id": "run-1",
            "item_id": "item-1",
            "metric_name": "judge",
            "root_cause": "Reasoning Error",
        },
    )
    assert changed.status_code == 200
    changed_meta = changed.json()["row"]["item_metadata"]
    changed_analysis = changed_meta["metric_analyses"]["judge"]
    assert changed_analysis["root_cause"] == "Reasoning Error"
    assert changed_analysis["root_cause_detail"] == "Bad envelope"
    assert changed_analysis["root_cause_note"] == "Original explanation"
    assert changed_analysis["solution"] == "Refine Prompt Instructions"
    assert changed_analysis["source"] == "human"
    assert "confidence" not in changed_analysis
    assert changed_meta["root_cause"] == "Item Summary"
    assert changed_meta["keep_me"] == "untouched"

    annotated = client.post(
        "/api/runs/update_root_cause",
        headers=_headers("owner@example.com"),
        json={
            "run_id": "run-1",
            "item_id": "item-1",
            "metric_name": "judge",
            "root_cause_detail": "Wrong join key",
            "root_cause_note": "Reviewed against the expected output.",
        },
    )
    assert annotated.status_code == 200
    annotated_analysis = annotated.json()["row"]["item_metadata"]["metric_analyses"][
        "judge"
    ]
    assert annotated_analysis["root_cause"] == "Reasoning Error"
    assert annotated_analysis["root_cause_detail"] == "Wrong join key"
    assert (
        annotated_analysis["root_cause_note"] == "Reviewed against the expected output."
    )

    unknown_metric = client.post(
        "/api/runs/update_root_cause",
        headers=_headers("owner@example.com"),
        json={
            "run_id": "run-1",
            "item_id": "item-1",
            "metric_name": "not-a-run-metric",
            "root_cause": "Other",
        },
    )
    assert unknown_metric.status_code == 400

    with session_factory() as session:
        audits = (
            session.query(AuditLog)
            .filter(AuditLog.action == "metric_root_cause_change:human")
            .order_by(AuditLog.id.asc())
            .all()
        )
        assert len(audits) == 2
        assert audits[0].entity_id == "run-1:item-1:judge"
        assert audits[0].before["root_cause"] == "Wrong Format"
        assert audits[0].after["root_cause"] == "Reasoning Error"


def test_correction_review_permissions_and_filtering(client, session_factory) -> None:
    with session_factory() as session:
        _seed_platform_data(session)

    manager_list = client.get(
        "/api/corrections", headers=_headers("manager-a@example.com")
    )
    assert manager_list.status_code == 200
    assert len(manager_list.json()["corrections"]) == 1

    outsider_list = client.get(
        "/api/corrections", headers=_headers("other@example.com")
    )
    assert outsider_list.status_code == 200
    assert outsider_list.json()["corrections"] == []

    denied_get = client.get("/api/corrections/1", headers=_headers("other@example.com"))
    assert denied_get.status_code == 403

    denied_update = client.put(
        "/api/corrections/1",
        headers=_headers("other@example.com"),
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

    analysis_config = client.get(
        "/api/runs/run-1/analysis-config",
        headers=_headers("manager-a@example.com"),
    )
    assert analysis_config.status_code == 200
    category_examples = analysis_config.json()["category_examples"]
    assert analysis_config.json()["category_example_counts"]["Wrong Format"] == 1
    assert category_examples["Wrong Format"] == [
        {
            "id": 1,
            "item_id": "item-1",
            "metric_name": None,
            "run_name": "run-1",
            "dataset": "dataset-1",
            "model": "",
            "detail": "",
            "note": "Human review",
            "solution": "",
            "solution_note": "",
            "input": {"prompt": "hello"},
            "expected": {"answer": "world"},
            "output": {"answer": "nope"},
            "created_at": category_examples["Wrong Format"][0]["created_at"],
        }
    ]

    denied_bulk = client.post(
        "/api/corrections/bulk",
        headers=_headers("manager-b@example.com"),
        json={"ids": [1], "action": "reject", "comment": "nope"},
    )
    assert denied_bulk.status_code == 403

    removed = client.delete(
        "/api/corrections/1",
        headers=_headers("manager-a@example.com"),
    )
    assert removed.status_code == 200
    assert removed.json() == {"ok": True, "deleted_id": 1, "status": "rejected"}
    with session_factory() as session:
        correction = session.get(ReviewCorrection, 1)
        assert correction is not None
        assert correction.status == CorrectionStatus.REJECTED
        assert correction.is_active is False
        assert (
            correction.review_comment
            == "Rejected automatically after deletion request."
        )

    manager_list_after_delete = client.get(
        "/api/corrections", headers=_headers("manager-a@example.com")
    )
    assert manager_list_after_delete.status_code == 200
    assert manager_list_after_delete.json()["corrections"] == []


def test_api_key_scopes_are_not_enforced(client, session_factory) -> None:
    # Scope enforcement is intentionally disabled: any valid, non-revoked key has full
    # access to its project regardless of the scopes recorded on the key. Authentication
    # and project membership still gate access; per-key scopes are no longer checked.
    with session_factory() as session:
        _seed_api_key(session, token="write-token", scopes=["runs:write"])
        _seed_api_key(session, token="read-token", scopes=["runs:read"])
        _seed_api_key(session, token="legacy-token", scopes=[])

    for token in ("write-token", "read-token", "legacy-token"):
        response = client.post(
            "/v1/runs",
            headers=_auth_headers(token),
            json={
                "task": "task",
                "dataset": "dataset",
                "metrics": [],
                "run_metadata": {},
                "run_config": {},
            },
        )
        assert response.status_code == 200, (token, response.text)
