"""Projection-only query contracts, pagination, authorization and snapshots."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from qym_platform.api import dashboard
from qym_platform.auth import Principal, require_ui_principal
from qym_platform.db.base import Base
from qym_platform.db.dashboard_models import (
    DashboardRunDimension as Dimension,
    DashboardRunSummary as Summary,
    DashboardPartitionState as Partition,
)
from qym_platform.db.models import Project, ProjectMembership, User, UserRole
from qym_platform.deps import get_db


@pytest.fixture(params=["sqlite", "postgres"])
def dataset(request):
    admin = None
    if request.param == "postgres":
        url = os.environ.get("QYM_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("QYM_TEST_POSTGRES_URL not configured")
        schema = "qym_dashboard_api_" + uuid4().hex
        admin = create_engine(url)
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )

    def cleanup():
        engine.dispose()
        if admin:
            with admin.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()

    request.addfinalizer(cleanup)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        owner = User(
            id="owner",
            email="owner@example.invalid",
            display_name="Owner",
            role=UserRole.MEMBER,
        )
        db.add(owner)
        db.flush()
        db.add_all(
            [
                Project(
                    id="project",
                    name="Project",
                    slug="project",
                    created_by_user_id=owner.id,
                ),
                Project(
                    id="private",
                    name="Private",
                    slug="private",
                    created_by_user_id=owner.id,
                ),
            ]
        )
        db.flush()
        db.add(ProjectMembership(project_id="project", user_id=owner.id))
        db.commit()
        principal = Principal(user=owner, auth_type="local_password")
        # Keep identity available after the fixture session closes.
        _ = owner.id, owner.role, owner.email
        db.expunge(owner)
    app = FastAPI()
    app.include_router(dashboard.router)

    def get_session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = get_session
    app.dependency_overrides[require_ui_principal] = lambda: principal
    with TestClient(app) as client:
        yield engine, client, principal


def seed(engine, count=12, project="project", prefix="run"):
    with Session(engine) as db:
        for index in range(count):
            run = f"{prefix}-{index:04}"
            timestamp = datetime(2026, 9, 1) + timedelta(hours=index)
            task = "task-a" if index % 2 == 0 else "task-b"
            model = "model-a" if index % 3 == 0 else "model-b"
            dataset = "dataset-a" if index % 4 == 0 else "dataset-b"
            descriptor = {
                "run_id": run,
                "file_path": run,
                "run_name": f"Run {index}",
                "task_name": task,
                "model_name": model,
                "dataset_name": dataset,
                "dataset_version": None,
                "timestamp": timestamp.isoformat() + "Z",
                "owner": {
                    "id": "owner",
                    "display_name": "Owner",
                    "email": "owner@example.invalid",
                },
                "metrics": ["quality", "count"],
                "metric_specs": {},
                "trace_stats": None,
                "git_branch": "main" if index % 2 else None,
                "git_commit": None,
                "config_group_key": "group-a" if index % 2 else "group-b",
                "run_config": {},
            }
            data = {
                "total_items": index + 1,
                "success_count": index,
                "error_count": 1,
                "success_rate": index / (index + 1),
                "metric_averages": {"quality": index / 1000, "count": index * 2},
                "avg_latency_ms": index * 10,
                "median_latency_ms": index * 9,
                "duration_ms": index * 20,
            }
            db.add(
                Dimension(
                    run_key=run,
                    project_key=project,
                    task=task,
                    model=model + "|||plain",
                    dataset=dataset,
                    version="main" if index % 2 else "",
                    owner="owner",
                    status="COMPLETED",
                    timestamp=timestamp,
                    created_at=timestamp,
                    present=True,
                    descriptor=descriptor,
                )
            )
            db.add(
                Summary(
                    run_key=run,
                    project_key=project,
                    count=index + 1,
                    success_count=index,
                    error_count=1,
                    avg_latency_ms=index * 10,
                    median_latency_ms=index * 9,
                    data=data,
                    applied_source_version=index + 1,
                )
            )
            db.add(
                Partition(
                    partition_key=run,
                    project_key=project,
                    last_enqueued_version=index + 1,
                    last_applied_version=index + 1,
                    queue_state="ready",
                    backfill_complete=True,
                )
            )
        db.commit()


def get(client, endpoint="runs", filters=None, **params):
    return client.get(
        f"/api/dashboard/{endpoint}",
        params={
            "project_slug": "project",
            "filters": json.dumps(filters or {}),
            **params,
        },
    )


def test_pagination_filters_and_projection_only_reads(dataset):
    engine, client, _ = dataset
    seed(engine, count=105)
    statements = []

    def record(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        first = get(client, limit=10).json()
        second = get(client, limit=10, offset=10).json()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert first["total_count"] == first["total_runs"] == 105
    assert len(first["rows"]) == len(second["rows"]) == 10
    assert first["has_more"] and second["has_more"]
    assert {row["run_id"] for row in first["rows"]}.isdisjoint(
        row["run_id"] for row in second["rows"]
    )
    assert first["rows"][0]["run_id"] == "run-0104"
    assert "config_groups" not in first
    assert all(
        "FROM run_items" not in sql
        and "FROM runs " not in sql
        and "FROM spans" not in sql
        and "FROM run_item_scores" not in sql
        for sql in statements
    )
    response = get(
        client, filters={"tasks": ["task-a"], "versions": ["__empty__"]}
    ).json()
    assert response["total_runs"] == 53
    assert response["total_count"] == 105
    assert all(row["task_name"] == "task-a" for row in response["rows"])


@pytest.mark.parametrize(
    "filters,expected",
    [
        ({"tasks": ["__none__"]}, 0),
        ({"tasks": []}, 12),
        ({"versions": ["__empty__"]}, 6),
        ({"versions": ["main"]}, 6),
        ({"since": "2026-09-01T04:00:00Z", "until": "2026-09-01T08:00:00Z"}, 4),
        ({"since": "2026-09-01T07:00:00+03:00", "until": "2026-09-01T08:00:00Z"}, 4),
    ],
)
def test_exact_filter_semantics(dataset, filters, expected):
    engine, client, _ = dataset
    seed(engine)
    response = get(client, filters=filters)
    assert response.status_code == 200, response.text
    assert response.json()["total_runs"] == expected


def test_access_hidden_deleted_and_pinned_filters(dataset, monkeypatch):
    engine, client, _ = dataset
    seed(engine)
    seed(engine, count=2, project="private", prefix="secret")
    denied = client.get("/api/dashboard/runs", params={"project_slug": "private"})
    assert denied.status_code == 403
    assert (
        client.get(
            "/api/dashboard/runs", params={"project_slug": "missing"}
        ).status_code
        == 404
    )
    with Session(engine) as db:
        db.get(Dimension, "run-0000").present = False
        db.commit()
    monkeypatch.setenv("QYM_HIDDEN_TASKS", "task-b")
    response = get(
        client,
        filters={"models": ["missing"]},
        ids=json.dumps(["run-0002", "run-0000", "run-0001", "secret-0000"]),
    ).json()
    assert response["total_runs"] == 0 and response["total_count"] == 5
    assert [row["run_id"] for row in response["pinned_rows"]] == ["run-0002"]


@pytest.mark.parametrize(
    "value",
    ["[]", '{"tasks":"x"}', '{"unknown":[]}', '{"since":"bad"}', '{"models":[1]}'],
)
def test_invalid_filters_rejected(dataset, value):
    _, client, _ = dataset
    assert (
        client.get(
            "/api/dashboard/runs", params={"project_slug": "project", "filters": value}
        ).status_code
        == 400
    )


def test_sort_neighbors_points_and_configuration_groups(dataset):
    engine, client, _ = dataset
    seed(engine, count=50)
    response = get(
        client, limit=1, sort="metric-quality-asc", include_config_groups="true"
    ).json()
    row = response["rows"][0]
    assert row["run_id"] == "run-0000"
    assert row["metric_neighbor_values"]["quality"] == [None, 0.012]
    assert sum(group["total_runs"] for group in response["config_groups"]) == 50
    assert {group["key"] for group in response["config_groups"]} == {
        "group-a",
        "group-b",
    }
    points = get(
        client, endpoint="points", task="task-a", dataset="dataset-a", limit=3
    ).json()
    assert (
        len(points["rows"]) == 3 and points["total_runs"] == 13 and points["has_more"]
    )
    assert get(client, sort="bad").status_code == 400
    assert get(client, limit=501).status_code == 422


def test_models_latest_k_custom_selection_and_metric_scope(dataset):
    engine, client, _ = dataset
    seed(engine, count=30)
    response = get(
        client,
        endpoint="models",
        k=2,
        selected=json.dumps({"model-a|||plain": ["run-0000", "run-0001"]}),
    ).json()
    models = {row["model_key"]: row for row in response["models"]}
    assert {row["run_id"] for row in models["model-a|||plain"]["rows"]} == {
        "run-0027",
        "run-0024",
        "run-0000",
    }
    assert len(models["model-b|||plain"]["rows"]) == 2
    assert response["scope"] == {
        "tasks": ["task-a", "task-b"],
        "datasets": ["dataset-a", "dataset-b"],
    }
    assert response["metric_summary"]["count"] == {
        "is_numeric": True,
        "is_boolean": False,
    }
    assert response["metric_summary"]["quality"] == {
        "is_numeric": False,
        "is_boolean": False,
    }
    post = client.post(
        "/api/dashboard/models",
        json={
            "project_slug": "project",
            "filters": {},
            "k": 2,
            "selected": {"model-a|||plain": ["run-0000"]},
        },
    )
    assert post.status_code == 200, post.text
    assert post.json() == response


def test_models_custom_selection_respects_filters_and_request_limits(dataset):
    engine, client, _ = dataset
    seed(engine)
    response = get(
        client,
        endpoint="models",
        filters={"tasks": ["task-b"]},
        k=1,
        selected=json.dumps({"model-a|||plain": ["run-0000"]}),
    ).json()
    assert all(
        row["task_name"] == "task-b"
        for model in response["models"]
        for row in model["rows"]
    )
    assert get(client, ids=json.dumps([str(i) for i in range(101)])).status_code == 400
    assert (
        get(
            client,
            endpoint="models",
            selected=json.dumps({"a": [str(i) for i in range(101)]}),
        ).status_code
        == 400
    )
    assert client.post("/api/dashboard/models", json={"k": True}).status_code == 400


def test_facets_ignore_own_filter_and_none_matches_legacy(dataset):
    engine, _, _ = dataset
    seed(engine)
    with Session(engine) as db:
        base = dashboard._base_conditions({"id": "project"})
        facets = dashboard._facets(db, base, {"tasks": ["task-a"]})
        assert facets["tasks"] == ["task-a", "task-b"]
        assert facets["versions"] == ["__empty__"]
        assert dashboard._facets(db, base, {"tasks": ["__none__"]})["tasks"] == [
            "task-a",
            "task-b",
        ]
        assert dashboard._facets(db, base, {"tasks": ["__none__"]})["versions"] == [
            "main",
            "__empty__",
        ]


def test_overview_and_post_defaults_share_one_snapshot(dataset):
    engine, client, _ = dataset
    seed(engine)
    full = get(client, endpoint="overview")
    assert full.status_code == 200, full.text
    overview = full.json()
    assert overview["aggregations"]["totalRuns"] == 12
    assert overview["total_count"] == overview["total_runs"] == 12
    assert all(
        not model.get("runsList")
        for combo in overview["chart_data"]["combos"]
        for model in combo["models"].values()
    )
    assert set(overview["sort_values"]) == {
        "tasks",
        "models",
        "dataset_names",
        "git_commits",
        "owner_names",
    }
    page = client.post(
        "/api/dashboard/runs",
        json={"project_slug": "project", "include_overview": True},
    ).json()
    assert len(page["rows"]) == 12 and page["limit"] == 50
    assert page["revision"] == page["overview"]["revision"]
    assert page["overview"] == overview
    assert (
        client.post("/api/dashboard/overview", json={"project_slug": "project"}).json()
        == overview
    )
    assert (
        client.post(
            "/api/dashboard/points", json={"project_slug": "project"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/dashboard/models", json={"project_slug": "project"}
        ).status_code
        == 200
    )
    assert (
        get(
            client,
            endpoint="runs",
            filters={"tasks": ["task-a"]},
            include_overview="true",
        ).json()["overview"]["total_runs"]
        == 6
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"limit": 0},
        {"limit": 501},
        {"limit": True},
        {"offset": -1},
        {"sort": {}},
        {"include_overview": "true"},
        {"collation": [1]},
        {"extra": 1},
        {"project_slug": 1},
    ],
)
def test_post_query_validation(dataset, payload):
    _, client, _ = dataset
    assert (
        client.post(
            "/api/dashboard/runs", json={"project_slug": "project", **payload}
        ).status_code
        == 400
    )


def test_browser_collation_and_sort_public_values(dataset):
    import subprocess

    engine, client, _ = dataset
    seed(engine, count=8)
    labels = ["éclair", "Éclair", "zèbre", "عربي", "alpha", "Alpha", "a-b", "a b"]
    order = json.loads(
        subprocess.run(
            [
                "node",
                "-e",
                "let s='';process.stdin.on('data',c=>s+=c);process.stdin.on('end',()=>console.log(JSON.stringify(JSON.parse(s).sort((a,b)=>a.localeCompare(b)))));",
            ],
            input=json.dumps(labels),
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )
    with Session(engine) as db:
        for index, label in enumerate(labels):
            dimension = db.get(Dimension, f"run-{index:04}")
            dimension.task = label
            dimension.descriptor = {**dimension.descriptor, "task_name": label}
        summary = db.get(Summary, "run-0000")
        summary.data = {
            **summary.data,
            "total_items": 9999,
            "success_count": 999,
            "error_count": 0,
        }
        db.commit()
    for direction in ("asc", "desc"):
        response = client.post(
            "/api/dashboard/runs",
            json={
                "project_slug": "project",
                "sort": f"task-{direction}",
                "collation": order,
            },
        )
        assert response.status_code == 200, response.text
        assert [row["task_name"] for row in response.json()["rows"]] == (
            order if direction == "asc" else list(reversed(order))
        )
    assert get(client, sort="items-desc").json()["rows"][0]["run_id"] == "run-0000"
    assert get(client, sort="success-desc").json()["rows"][0]["run_id"] == "run-0000"


def test_postgresql_repeatable_read_does_not_mix_page_and_overview(dataset):
    engine, client, _ = dataset
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL snapshot isolation test")
    seed(engine)
    changed = False

    def mutate(conn, cursor, statement, parameters, context, many):
        nonlocal changed
        if (
            changed
            or "dashboard_run_dimensions" not in statement
            or "LIMIT" not in statement
        ):
            return
        changed = True
        with Session(engine) as writer:
            value = writer.get(Summary, "run-0011")
            value.data = {**value.data, "total_items": 9999}
            value.applied_source_version += 500
            writer.commit()

    event.listen(engine, "after_cursor_execute", mutate)
    try:
        response = client.post(
            "/api/dashboard/runs",
            json={"project_slug": "project", "limit": 1, "include_overview": True},
        ).json()
    finally:
        event.remove(engine, "after_cursor_execute", mutate)
    assert changed
    assert response["rows"][0]["total_items"] == 12
    assert response["overview"]["aggregations"]["totalItems"] == sum(range(1, 13))
    assert response["revision"] == response["overview"]["revision"]
    assert get(client, limit=1).json()["rows"][0]["total_items"] == 9999


@pytest.mark.parametrize(
    "role,expected",
    [("MEMBER", "MEMBER"), ("MANAGER", "MANAGER"), ("ADMIN", "MANAGER")],
)
def test_project_descriptor_preserves_action_permissions(dataset, role, expected):
    from qym_platform.db.models import ProjectRole

    engine, client, principal = dataset
    seed(engine, count=1)
    with Session(engine) as db:
        membership = (
            db.query(ProjectMembership)
            .filter_by(project_id="project", user_id="owner")
            .one()
        )
        membership.role = (
            ProjectRole.MANAGER if role == "MANAGER" else ProjectRole.MEMBER
        )
        db.commit()
    if role == "ADMIN":
        principal.user.role = UserRole.ADMIN
    response = get(client).json()
    assert response["project"]["role"] == expected
    assert response["project"]["member_count"] == 1
    assert response["project"]["run_count"] == 1
    assert set(response["project"]) == {
        "id",
        "name",
        "slug",
        "is_active",
        "member_count",
        "run_count",
        "role",
        "created_at",
        "updated_at",
    }


def test_models_version_scope_start_time_and_tolerance(dataset):
    engine, client, _ = dataset
    seed(engine, count=6)
    with Session(engine) as db:
        dimension = db.get(Dimension, "run-0000")
        dimension.timestamp = datetime(2027, 1, 1)
        dimension.dataset = "dataset-a␟v2"
        dimension.descriptor = {
            **dimension.descriptor,
            "dataset_version": "v2",
            "timestamp": "2027-01-01T00:00:00Z",
        }
        summary = db.get(Summary, "run-0000")
        summary.data = {
            **summary.data,
            "metric_averages": {"quality": 0.0001, "count": 1},
        }
        db.commit()
    response = get(
        client, endpoint="models", k=1, filters={"datasets": ["dataset-a␟v2"]}
    ).json()
    assert response["scope"]["datasets"] == ["dataset-a␟v2"]
    assert response["metric_summary"]["quality"]["is_boolean"] is True
    response = get(client, endpoint="models", k=1).json()
    model = next(
        model for model in response["models"] if model["model_key"] == "model-a|||plain"
    )
    assert [row["run_id"] for row in model["rows"]] == ["run-0000"]


def test_post_malformed_empty_containers_are_not_silently_defaulted(dataset):
    _, client, _ = dataset
    for endpoint, payload in [
        ("runs", {"filters": []}),
        ("overview", {"filters": False}),
        ("points", {"filters": None}),
        ("runs", {"ids": {}}),
        ("runs", {"collation": {}}),
        ("models", {"selected": []}),
    ]:
        response = client.post(
            f"/api/dashboard/{endpoint}", json={"project_slug": "project", **payload}
        )
        assert response.status_code == 400, response.text


def test_stable_ties_keep_global_group_order_after_filtering(dataset):
    engine, client, _ = dataset
    seed(engine, count=6)
    with Session(engine) as db:
        for index, task in [(5, "task-a"), (4, "task-b")]:
            dimension = db.get(Dimension, f"run-{index:04}")
            dimension.task = task
            dimension.descriptor = {**dimension.descriptor, "task_name": task}
        db.commit()
    response = get(
        client, filters={"until": "2026-09-01T04:00:00Z"}, sort="metric-missing-asc"
    ).json()
    assert [row["task_name"] for row in response["rows"]] == [
        "task-a",
        "task-a",
        "task-b",
        "task-b",
    ]


def test_overview_filtered_stream_honors_requested_sort(dataset, monkeypatch):
    from qym_platform.services import dashboard_views

    engine, client, _ = dataset
    seed(engine, count=6)
    captured = {}

    def capture(unfiltered, filtered):
        captured["unfiltered"] = [row["run_id"] for row in unfiltered]
        captured["filtered"] = [row["run_id"] for row in filtered]
        return {}

    monkeypatch.setattr(dashboard_views, "build_overview_data", capture)
    response = client.post(
        "/api/dashboard/overview", json={"project_slug": "project", "sort": "time-asc"}
    )
    assert response.status_code == 200, response.text
    assert captured["filtered"] == [f"run-{index:04}" for index in range(6)]
    assert captured["unfiltered"] != captured["filtered"]
    points = client.post(
        "/api/dashboard/points",
        json={"project_slug": "project", "sort": "time-asc", "limit": 2},
    ).json()
    assert [row["run_id"] for row in points["rows"]] == ["run-0000", "run-0001"]


def test_maximum_page_is_complete_and_bounded(dataset):
    engine, client, _ = dataset
    seed(engine, count=505)
    response = get(client, limit=500)
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["rows"]) == 500 and data["has_more"] and data["total_runs"] == 505
    assert len(json.dumps(data)) < 2000000


def test_models_revisions_invalidate_only_matching_candidates(dataset):
    engine, client, _ = dataset
    seed(engine, count=6)

    def fetch():
        return get(client, endpoint="models", filters={"tasks": ["task-a"]}, k=1).json()

    def change(run_id):
        with Session(engine) as db:
            db.get(Summary, run_id).projection_revision += 1
            db.commit()

    initial = fetch()
    change("run-0005")
    outside = fetch()
    assert outside["filtered_revision"] == initial["filtered_revision"]
    assert outside["selected_revision"] == initial["selected_revision"]
    change("run-0002")
    historical = fetch()
    assert historical["filtered_revision"] != initial["filtered_revision"]
    assert historical["selected_revision"] == initial["selected_revision"]
    change("run-0004")
    chosen = fetch()
    assert chosen["selected_revision"] != initial["selected_revision"]
    with Session(engine) as db:
        db.get(Dimension, "run-0004").present = False
        db.commit()
    deleted = fetch()
    assert deleted["filtered_revision"] != chosen["filtered_revision"]
    assert deleted["selected_revision"] != chosen["selected_revision"]


def test_peer_precision_keeps_reasoning_variants_separate(dataset):
    engine, client, _ = dataset
    seed(engine, count=13)
    with Session(engine) as db:
        # The closest value shares raw model/task/dataset, but is another variant.
        dimension = db.get(Dimension, "run-0012")
        dimension.model = "model-a|||reasoning"
        dimension.descriptor = {
            **dimension.descriptor,
            "trace_stats": {"has_reasoning": True},
        }
        db.commit()
    response = get(client, limit=1, sort="metric-quality-asc").json()
    assert response["rows"][0]["model_key"] == "model-a|||plain"
    assert response["rows"][0]["metric_neighbor_values"]["quality"] == [None, None]


def test_empty_model_identity_uses_legacy_nomodel_key(dataset):
    engine, client, _ = dataset
    seed(engine, count=1)
    with Session(engine) as db:
        dimension = db.get(Dimension, "run-0000")
        dimension.model = "nomodel|||plain"
        dimension.descriptor = {**dimension.descriptor, "model_name": ""}
        db.commit()
    response = get(
        client, filters={"models": ["nomodel|||plain"]}, include_overview="true"
    ).json()
    assert response["total_runs"] == 1
    assert response["rows"][0]["model_key"] == "nomodel|||plain"
    assert list(response["tasks"]["task-a"]) == ["nomodel"]
    assert response["overview"]["all_models"] == ["nomodel|||plain"]
    assert response["overview"]["chart_data"]["models"] == ["nomodel|||plain"]
