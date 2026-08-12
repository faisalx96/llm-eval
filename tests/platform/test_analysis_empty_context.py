from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from qym_platform.api import analysis as analysis_api
from qym_platform.app import create_app
from qym_platform.auth import Principal, require_ui_principal
from qym_platform.db.base import Base
from qym_platform.db.models import (
    Project,
    ProjectMembership,
    ProjectRole,
    Run,
    RunWorkflowStatus,
    User,
    UserRole,
)
from qym_platform.deps import get_db
from qym_platform.services import llm_analyzer as llm_analyzer_service


@pytest.fixture()
def empty_analysis_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    db: Session = session_factory()
    owner = User(id="owner", email="owner@example.com", role=UserRole.MEMBER)
    project = Project(
        id="project-empty",
        name="Empty context",
        slug="empty-context",
        created_by_user_id=owner.id,
    )
    run = Run(
        id="run-empty",
        project_id=project.id,
        created_by_user_id=owner.id,
        owner_user_id=owner.id,
        task="empty-task",
        dataset="empty-dataset",
        model="test-model",
        metrics=["accuracy"],
        status=RunWorkflowStatus.COMPLETED,
    )
    db.add_all(
        [
            owner,
            project,
            run,
            ProjectMembership(
                project_id=project.id,
                user_id=owner.id,
                role=ProjectRole.MANAGER,
                added_by_user_id=owner.id,
            ),
        ]
    )
    db.commit()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_ui_principal] = lambda: Principal(
        user=owner,
        auth_type="none",
    )
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_rule_inference_rejects_empty_selected_sources_before_provider_call(
    empty_analysis_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_client = MagicMock(side_effect=AssertionError("provider must not be called"))
    monkeypatch.setattr(analysis_api, "build_client", build_client)

    response = empty_analysis_client.post(
        "/api/runs/run-empty/analysis-rules/infer",
        json={
            "include_documents": True,
            "include_examples": True,
            "mode": "generate",
        },
    )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "NO_INFERENCE_SOURCES"
    assert detail["documents_available"] == 0
    assert detail["approved_examples_available"] == 0
    assert "neither an enabled project document nor an approved example" in detail[
        "message"
    ]
    assert "Add and enable a project document, or approve an example" in detail[
        "message"
    ]
    build_client.assert_not_called()


def test_rule_inference_explains_when_all_source_toggles_are_off(
    empty_analysis_client: TestClient,
) -> None:
    response = empty_analysis_client.post(
        "/api/runs/run-empty/analysis-rules/infer",
        json={
            "include_documents": False,
            "include_examples": False,
            "mode": "update",
        },
    )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "NO_INFERENCE_SOURCES_SELECTED"
    assert "Choose at least one source before generating rules" in detail["message"]


@pytest.mark.parametrize("mode", ["generate", "update"])
def test_rule_writer_service_rejects_empty_sources_before_provider_call(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    create_completion = MagicMock(side_effect=AssertionError("provider must not be called"))
    monkeypatch.setattr(
        llm_analyzer_service,
        "create_chat_completion_compat",
        create_completion,
    )
    if mode == "update":
        coroutine = llm_analyzer_service.update_analysis_rules(
            object(),
            "test-model",
            existing_rules=[],
            reference_documents=[],
            corrections=[],
        )
    else:
        coroutine = llm_analyzer_service.infer_analysis_rules(
            object(),
            "test-model",
            reference_documents=[],
            corrections=[],
        )

    with pytest.raises(ValueError, match="no usable source data was provided"):
        asyncio.run(coroutine)
    create_completion.assert_not_called()
