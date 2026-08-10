from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("QYM_AUTH_MODE", "proxy_headers")

from qym_platform.app import create_app
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


@pytest.fixture()
def analysis_route_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("QYM_AUTH_MODE", "proxy_headers")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with session_factory() as session:
        user = User(
            id="analysis-manager",
            email="analysis-manager@example.com",
            role=UserRole.MEMBER,
        )
        member = User(
            id="analysis-member",
            email="analysis-member@example.com",
            role=UserRole.MEMBER,
        )
        outsider = User(
            id="analysis-outsider",
            email="analysis-outsider@example.com",
            role=UserRole.MEMBER,
        )
        project = Project(
            id="analysis-project",
            name="Analysis Project",
            slug="analysis-project",
            created_by_user_id=user.id,
        )
        other_project = Project(
            id="other-analysis-project",
            name="Other Analysis Project",
            slug="other-analysis-project",
            created_by_user_id=user.id,
        )
        session.add_all(
            [
                user,
                member,
                outsider,
                project,
                other_project,
                ProjectMembership(
                    project_id=project.id,
                    user_id=user.id,
                    role=ProjectRole.MANAGER,
                    added_by_user_id=user.id,
                ),
                ProjectMembership(
                    project_id=project.id,
                    user_id=member.id,
                    role=ProjectRole.MEMBER,
                    added_by_user_id=user.id,
                ),
                ProjectMembership(
                    project_id=other_project.id,
                    user_id=user.id,
                    role=ProjectRole.MANAGER,
                    added_by_user_id=user.id,
                ),
                Run(
                    id="analysis/run-1",
                    project_id=project.id,
                    created_by_user_id=user.id,
                    owner_user_id=user.id,
                    task="task",
                    dataset="dataset",
                    metrics=["judge"],
                    status=RunWorkflowStatus.COMPLETED,
                    run_metadata={},
                    run_config={},
                ),
            ]
        )
        session.commit()

    app = create_app()

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _headers() -> dict[str, str]:
    return {"X-User-Email": "analysis-manager@example.com"}


def _member_headers() -> dict[str, str]:
    return {"X-User-Email": "analysis-member@example.com"}


def _outsider_headers() -> dict[str, str]:
    return {"X-User-Email": "analysis-outsider@example.com"}


def test_legacy_analyzer_url_redirects_to_project_run_route(
    analysis_route_client: TestClient,
) -> None:
    response = analysis_route_client.get(
        "/run/analysis%2Frun-1/analyzer?metric=judge&mode=compact",
        headers=_headers(),
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == (
        "/projects/analysis-project/runs/analysis%2Frun-1/analyzer"
        "?metric=judge&mode=compact"
    )


def test_project_analysis_run_query_redirects_to_focused_route(
    analysis_route_client: TestClient,
) -> None:
    response = analysis_route_client.get(
        "/projects/analysis-project/analysis?run=analysis%2Frun-1&scope=run&metric=judge",
        headers=_headers(),
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == (
        "/projects/analysis-project/runs/analysis%2Frun-1/analyzer?metric=judge"
    )


@pytest.mark.parametrize(
    ("requested_scope", "canonical_scope"),
    [("diagnosis", "categories"), ("project", "rules"), ("run", "dashboard")],
)
def test_project_analysis_scope_aliases_are_canonicalized(
    analysis_route_client: TestClient,
    requested_scope: str,
    canonical_scope: str,
) -> None:
    response = analysis_route_client.get(
        f"/projects/analysis-project/analysis?scope={requested_scope}",
        headers=_headers(),
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == (
        f"/projects/analysis-project/analysis?scope={canonical_scope}"
    )


def test_project_configuration_scope_leaves_run_route(
    analysis_route_client: TestClient,
) -> None:
    response = analysis_route_client.get(
        "/projects/analysis-project/runs/analysis%2Frun-1/analyzer"
        "?scope=documents&metric=judge",
        headers=_headers(),
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == (
        "/projects/analysis-project/analysis?metric=judge&scope=documents"
    )


def test_category_catalog_version_aliases_and_conflict_contract(
    analysis_route_client: TestClient,
) -> None:
    base = "/api/projects/analysis-project/analysis-category-catalog"
    initial = analysis_route_client.get(base, headers=_headers())
    assert initial.status_code == 200
    assert initial.json()["version"] == 0

    saved = analysis_route_client.put(
        base,
        headers=_headers(),
        json={
            "categories": ["Custom Failure"],
            "category_details_map": {"Custom Failure": ["Missing field"]},
            "category_taxonomy": {
                "Custom Failure": {
                    "description": "Project-specific failure.",
                    "when_to_use": "Use for project-specific failures.",
                }
            },
            "max_root_cause_categories": 4,
            "base_revision": 0,
        },
    )
    assert saved.status_code == 200
    catalog = saved.json()["catalog"]
    assert catalog["version"] == 1
    assert catalog["is_active"] is True
    assert catalog["max_root_cause_categories"] == 4
    assert catalog["category_entries"][0]["id"]
    assert catalog["category_entries"][0]["status"] == "active"

    history = analysis_route_client.get(base + "/versions", headers=_headers())
    assert history.status_code == 200
    assert [entry["version"] for entry in history.json()["versions"]] == [1, 0]

    conflict = analysis_route_client.put(
        base,
        headers=_headers(),
        json={"categories": ["Different"], "base_revision": 0},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "catalog_version_conflict"
    assert conflict.json()["detail"]["current_catalog"]["id"] == catalog["id"]

    restored = analysis_route_client.post(
        base + "/versions/" + catalog["id"] + ":restore",
        headers=_headers(),
        json={"base_revision": 1},
    )
    assert restored.status_code == 200
    assert restored.json()["catalog"]["version"] == 2
    assert restored.json()["catalog"]["parent_version_id"] == catalog["id"]
    assert restored.json()["catalog"]["max_root_cause_categories"] == 4
    assert restored.json()["catalog"]["category_entries"][0]["id"] == catalog["category_entries"][0]["id"]


def test_category_catalog_http_access_requires_manager_for_mutations(
    analysis_route_client: TestClient,
) -> None:
    base = "/api/projects/analysis-project/analysis-category-catalog"
    member_get = analysis_route_client.get(base, headers=_member_headers())
    assert member_get.status_code == 200
    assert analysis_route_client.get(base, headers=_outsider_headers()).status_code == 403

    member_save = analysis_route_client.put(
        base,
        headers=_member_headers(),
        json={"categories": ["Denied"], "base_revision": 0},
    )
    assert member_save.status_code == 403

    manager_save = analysis_route_client.put(
        base,
        headers=_headers(),
        json={"categories": ["Manager Category"], "base_revision": 0},
    )
    assert manager_save.status_code == 200
    version_id = manager_save.json()["catalog"]["id"]
    member_restore = analysis_route_client.post(
        base + "/versions/" + version_id + ":restore",
        headers=_member_headers(),
        json={"base_revision": 1},
    )
    assert member_restore.status_code == 403


def test_mismatched_project_slug_redirects_to_run_project(
    analysis_route_client: TestClient,
) -> None:
    response = analysis_route_client.get(
        "/projects/other-analysis-project/runs/analysis%2Frun-1/analyzer?metric=judge",
        headers=_headers(),
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == (
        "/projects/analysis-project/runs/analysis%2Frun-1/analyzer?metric=judge"
    )


def test_missing_legacy_run_renders_recoverable_analysis_page(
    analysis_route_client: TestClient,
) -> None:
    response = analysis_route_client.get(
        "/run/missing-run/analyzer",
        headers=_headers(),
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert 'id="analysis-error"' in response.text
    assert 'role="alert"' in response.text
