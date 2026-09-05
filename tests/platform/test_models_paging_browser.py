"""Models retain full-scope semantics with bounded candidate and selector reads."""

from __future__ import annotations

import json
import mimetypes
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

STATIC = (
    Path(__file__).resolve().parents[2]
    / "packages/platform/qym_platform/_static/dashboard"
)


@pytest.fixture(scope="module")
def browser():
    api = pytest.importorskip("playwright.sync_api")
    with api.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


def nested(rows):
    tasks = {}
    for row in rows:
        tasks.setdefault(row["task_name"], {}).setdefault(row["model_name"], []).append(
            row
        )
    return tasks


def model_key(row):
    return row["model_name"] + (
        "|||reasoning"
        if row.get("trace_stats", {}).get("reasoning_tokens")
        else "|||plain"
    )


class ModelsFixture:
    def __init__(self, browser):
        self.rows = []
        now = datetime.now(timezone.utc)
        for model_index, model in enumerate(("alpha", "beta", "alpha")):
            for i in range(60):
                self.rows.append(
                    {
                        "run_id": f"m{model_index}-{i:02}",
                        "file_path": f"m{model_index}-{i:02}",
                        "run_name": f"Experiment {model_index} {i}",
                        "model_name": model,
                        "task_name": "Task",
                        "dataset_name": "Data",
                        "dataset_version": "v1",
                        "timestamp": (now - timedelta(hours=i)).isoformat(),
                        "status": "COMPLETED",
                        "total_items": 20,
                        "success_count": 20,
                        "error_count": 0,
                        "success_rate": 1,
                        "metrics": ["accuracy", "count"]
                        + (["late_metric"] if i == 59 else []),
                        "metric_averages": {
                            "accuracy": 0.5,
                            "count": 12 if i == 59 else 1,
                        },
                        "metric_specs": {},
                        "git_commit": "old" if i >= 50 else "new",
                        "owner": {"id": "owner", "display_name": "Owner"},
                        "samples": 3 if i == 0 else 1,
                        "avg_latency_ms": 100 + i,
                        "total_retries": i,
                        "trace_stats": (
                            {"reasoning_tokens": 20} if model_index == 2 else {}
                        ),
                        "run_config": {"temperature": i % 2},
                        "config_group_key": "cold" if i % 2 == 0 else "warm",
                        "_revision": 1,
                    }
                )
        self.requests = []
        self.errors = []
        self.revision = 1
        self.fail_candidates = False
        self.fail_page = False
        self.fail_details = False
        self.api_client = None
        self.context = browser.new_context(
            viewport={"width": 1440, "height": 1100}, reduced_motion="reduce"
        )
        self.page = self.context.new_page()
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.route("**/*", self.route)

    def scope(self, filters):
        result = self.rows
        fields = {
            "tasks": lambda row: row["task_name"],
            "models": model_key,
            "datasets": lambda row: row["dataset_name"] + "␟" + row["dataset_version"],
            "statuses": lambda row: row["status"],
            "versions": lambda row: row["git_commit"],
            "users": lambda row: row["owner"]["id"],
        }
        for field, getter in fields.items():
            if filters.get(field):
                result = [row for row in result if getter(row) in filters[field]]
        if filters.get("since"):
            result = [row for row in result if row["timestamp"] >= filters["since"]]
        if filters.get("until"):
            result = [row for row in result if row["timestamp"] < filters["until"]]
        return result

    def detail(self, run_id):
        run = next(row for row in self.rows if row["run_id"] == run_id)
        rows = []
        for i in range(20):
            row = {
                "item_id": f"item-{i}",
                "index": i,
                "status": "error" if i == 7 else "completed",
                "metric_values": [(i + int(run_id[-2:])) % 2, i],
                "latency_ms": i * 10,
            }
            if run["samples"] > 1:
                row["pass_scores"] = {
                    "accuracy": [0, 1, i % 2],
                    "count": [i, i + 1, i + 2],
                }
            rows.append(row)
        return {
            "run": run,
            "snapshot": {"rows": rows, "metric_names": ["accuracy", "count"]},
        }

    def route(self, route):
        request = route.request
        parsed = urlparse(request.url)
        query = parse_qs(parsed.query)
        path = parsed.path
        if path.startswith("/static/"):
            file = STATIC / path.split("/static/", 1)[1]
            if file.name == "dashboard.js":
                source = file.read_text().replace(
                    "  checkAuthAndInit();",
                    "  window.__modelsTest = {state, render, renderModelsView, fetchRuns, flattenRuns, saveDashboardState};\n  checkAuthAndInit();",
                )
                route.fulfill(body=source, content_type="application/javascript")
            elif file.is_file():
                route.fulfill(
                    path=str(file),
                    content_type=mimetypes.guess_type(file.name)[0]
                    or "application/octet-stream",
                )
            else:
                route.fulfill(status=404, body="")
            return
        if path == "/v1/me":
            route.fulfill(
                json={
                    "id": "owner",
                    "role": "ADMIN",
                    "projects": [
                        {"id": "p", "slug": "demo", "name": "Demo", "role": "MANAGER"}
                    ],
                }
            )
            return
        if path.startswith("/api/dashboard/"):
            body = request.post_data_json if request.method == "POST" else {}
            filters = body.get("filters", json.loads(query.get("filters", ["{}"])[0]))
            self.requests.append((path, query, body))
            if self.api_client is not None:
                target = path + ("?" + parsed.query if parsed.query else "")
                response = (
                    self.api_client.post(target, json=body)
                    if request.method == "POST"
                    else self.api_client.get(target)
                )
                route.fulfill(
                    status=response.status_code,
                    body=response.content,
                    content_type="application/json",
                )
                return
            rows = self.scope(filters)
            if path.endswith("/models"):
                if self.fail_candidates:
                    self.fail_candidates = False
                    route.fulfill(status=503, json={"error": "temporarily unavailable"})
                    return
                k = int(body.get("k", query.get("k", ["5"])[0]))
                selected = body.get(
                    "selected", json.loads(query.get("selected", ["{}"])[0])
                )
                grouped = {}
                for row in rows:
                    grouped.setdefault(model_key(row), []).append(row)
                models = []
                for key, candidates in grouped.items():
                    candidates = sorted(
                        candidates, key=lambda row: row["timestamp"], reverse=True
                    )
                    latest = {row["run_id"] for row in candidates[:k]}
                    wanted = latest | set(selected.get(key, []))
                    models.append(
                        {
                            "model_key": key,
                            "total_runs": len(candidates),
                            "rows": [
                                row for row in candidates if row["run_id"] in wanted
                            ],
                        }
                    )
                metrics = sorted({metric for row in rows for metric in row["metrics"]})
                summary = {}
                for metric in metrics:
                    values = [
                        row["metric_averages"][metric]
                        for row in rows
                        if metric in row["metric_averages"]
                    ]
                    summary[metric] = {
                        "is_boolean": all(
                            min(abs(v), abs(v - 1)) <= 0.0001 for v in values
                        ),
                        "is_numeric": any(v < 0 or v > 1 for v in values),
                    }
                route.fulfill(
                    json={
                        "models": models,
                        "scope": {
                            "tasks": sorted({row["task_name"] for row in rows}),
                            "datasets": sorted(
                                {
                                    row["dataset_name"] + "␟" + row["dataset_version"]
                                    for row in rows
                                }
                            ),
                        },
                        "metrics": metrics,
                        "metric_summary": summary,
                        "revision": self.revision,
                    }
                )
            elif path.endswith("/runs"):
                if self.fail_page:
                    self.fail_page = False
                    route.fulfill(status=503, json={"error": "temporarily unavailable"})
                    return
                offset = int(body.get("offset", query.get("offset", ["0"])[0]))
                limit = int(body.get("limit", query.get("limit", ["50"])[0]))
                rows = sorted(rows, key=lambda row: row["timestamp"], reverse=True)
                groups = [
                    {
                        "key": key,
                        "label": key.title() + " config",
                        "total_runs": sum(
                            row["config_group_key"] == key for row in rows
                        ),
                    }
                    for key in {row["config_group_key"] for row in rows}
                ]
                route.fulfill(
                    json={
                        "tasks": nested(rows[offset : offset + limit]),
                        "total_runs": len(rows),
                        "config_groups": groups,
                    }
                )
            else:
                route.fulfill(
                    json={
                        "total_count": len(self.rows),
                        "total_runs": len(rows),
                        "aggregations": {
                            "totalRuns": len(self.rows),
                            "totalModels": 3,
                            "totalItems": len(self.rows) * 20,
                            "avgSuccess": 1,
                        },
                        "facets": {
                            "tasks": ["Task"],
                            "datasets": ["Data␟v1"],
                            "models": [
                                "alpha|||plain",
                                "alpha|||reasoning",
                                "beta|||plain",
                            ],
                            "statuses": ["COMPLETED"],
                            "versions": ["old", "new"],
                            "users": ["owner"],
                        },
                        "owners": {"owner": {"id": "owner", "display_name": "Owner"}},
                        "all_models": [
                            "alpha|||plain",
                            "alpha|||reasoning",
                            "beta|||plain",
                        ],
                        "metrics": ["accuracy", "count", "late_metric"],
                        "metric_types": {"accuracy": "score", "count": "numeric"},
                        "has_trace_stats": True,
                        "chart_data": {"tasks": [], "combos": []},
                        "revision": self.revision,
                        "freshness": {"updating": False},
                    }
                )
            return
        if path == "/api/models/runs":
            self.requests.append((path, query, {}))
            if self.fail_details:
                self.fail_details = False
                route.fulfill(status=503, json={"error": "temporarily unavailable"})
                return
            route.fulfill(
                json={"runs": [self.detail(run_id) for run_id in query["files"]]}
            )
            return
        if path == "/projects/demo/models":
            source = (STATIC / "models.html").read_text()
            source = re.sub(
                r'<script src="/static/(?:auth|shell)\.js[^\"]*"></script>', "", source
            )
            route.fulfill(body=source, content_type="text/html")
            return
        route.fulfill(status=404, json={"error": path})

    def open(self):
        self.page.goto("https://qym.test/projects/demo/models")
        self.ready()

    def ready(self):
        self.page.wait_for_function(
            "window.__modelsTest && document.querySelectorAll('.model-card').length === 3"
        )

    def stats(self):
        return self.page.evaluate(
            "window.__modelsTest.state.modelsViewState.modelStats"
        )

    def close(self):
        self.context.close()
        assert not self.errors


@contextmanager
def projected_dashboard(rows):
    """Connect Chromium's dashboard reads to the real SQL/FastAPI contract."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from qym_platform.api.dashboard import router
    from qym_platform.auth import Principal, require_ui_principal
    from qym_platform.db.base import Base
    from qym_platform.db.dashboard_models import (
        DashboardRunDimension,
        DashboardRunSummary,
    )
    from qym_platform.db.models import Project, User, UserRole
    from qym_platform.deps import get_db

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        user = User(
            id="owner",
            email="models@example.test",
            display_name="Owner",
            role=UserRole.ADMIN,
        )
        db.add(user)
        db.flush()
        db.add(Project(id="p", slug="demo", name="Demo", created_by_user_id="owner"))
        for index, row in enumerate(rows):
            stamp = datetime.fromisoformat(row["timestamp"]).replace(tzinfo=None)
            db.add(
                DashboardRunDimension(
                    run_key=row["run_id"],
                    project_key="p",
                    task=row["task_name"],
                    model=model_key(row),
                    dataset=row["dataset_name"] + "␟" + row["dataset_version"],
                    version=row["git_commit"],
                    owner="owner",
                    status=row["status"],
                    timestamp=stamp,
                    # Deliberately disagree with started-at order to catch latest-K
                    # ranking by creation time instead of the UI timestamp.
                    created_at=stamp + timedelta(hours=(index % 60) * 2),
                    descriptor=row,
                )
            )
            db.add(
                DashboardRunSummary(
                    run_key=row["run_id"],
                    project_key="p",
                    data=row,
                    count=20,
                    success_count=20,
                    applied_source_version=index + 1,
                )
            )
        db.commit()
        principal = Principal(user=user, auth_type="local_password")
        db.expunge(user)

    app = FastAPI()
    app.include_router(router)

    def session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[require_ui_principal] = lambda: principal
    try:
        with TestClient(app) as client:
            yield client
    finally:
        engine.dispose()


def test_models_browser_uses_real_projection_api_for_versions_latest_and_selection(
    browser, monkeypatch
):
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite://")
    fixture = ModelsFixture(browser)
    try:
        with projected_dashboard(fixture.rows) as client:
            fixture.api_client = client
            fixture.open()
            assert all(
                stats["selectedPaths"][0].endswith("00")
                for stats in fixture.stats().values()
            )
            page = fixture.page
            page.locator('.customize-btn[data-model="alpha|||plain"]').click()
            page.wait_for_function(
                "document.querySelectorAll('#run-selection-list input[type=checkbox]').length === 50"
            )
            assert "2 config groups" in page.locator("#run-selection-list").inner_text()
            assert "30 runs" in page.locator("#run-selection-list").inner_text()
            page.locator('#run-selection-list input[data-file="m0-00"]').uncheck()
            page.locator('#run-selection-list [aria-label="Last page"]').click()
            page.wait_for_function(
                "document.querySelectorAll('#run-selection-list input[type=checkbox]').length === 10"
            )
            page.locator('#run-selection-list input[data-file="m0-59"]').check()
            page.locator("#confirm-run-selection-btn").click()
            page.wait_for_function(
                "__modelsTest.state.modelsViewState.modelStats['alpha|||plain'].selectedPaths.includes('m0-59')"
            )
            assert len(fixture.stats()["alpha|||plain"]["selectedPaths"]) == 5
            page.locator("#models-metric-select").select_option("count")
            page.wait_for_function("__modelsTest.state.modelsViewState.metricIsNumeric")
            page.evaluate(
                "__modelsTest.state.filterVersions = new Set(['old']); __modelsTest.render()"
            )
            page.wait_for_function(
                "Object.values(__modelsTest.state.modelsViewState.modelStats).every(stats => stats.totalAvailable === 10)"
            )
            assert fixture.stats()["alpha|||plain"]["selectedPaths"] == ["m0-59"]
    finally:
        fixture.close()


def test_models_candidates_equal_original_full_history_estimators(browser):
    fixture = ModelsFixture(browser)
    try:
        fixture.open()
        bounded = fixture.stats()
        assert all(
            stats["totalAvailable"] == 60
            and stats["selectedCount"] == 5
            and stats["K"] == 7
            for stats in bounded.values()
        )
        assert fixture.page.evaluate("__modelsTest.state.flatRuns.length") == 0
        assert (
            fixture.page.evaluate(
                "__modelsTest.state.modelsViewState.candidates.rows.length"
            )
            == 15
        )
        assert (
            "late_metric" in fixture.page.locator("#models-metric-select").inner_text()
        )
        assert all(
            len(query["files"]) <= 100
            for path, query, _ in fixture.requests
            if path == "/api/models/runs"
        )
        fixture.page.evaluate(
            """async data => {
          const t = __modelsTest;
          t.state.dashboardOverview = null;
          t.state.flatRuns = t.state.filteredRuns = t.flattenRuns(data).runs;
          await t.renderModelsView();
        }""",
            {"tasks": nested(fixture.rows)},
        )
        assert fixture.stats() == bounded
    finally:
        fixture.close()


def test_models_selector_preserves_offpage_selection_groups_and_k(browser):
    fixture = ModelsFixture(browser)
    try:
        fixture.open()
        page = fixture.page
        page.locator('.customize-btn[data-model="alpha|||plain"]').click()
        page.wait_for_function(
            "document.querySelectorAll('#run-selection-list input[type=checkbox]').length === 50"
        )
        assert "2 config groups" in page.locator("#run-selection-list").inner_text()
        assert (
            "Cold config (30 runs)" in page.locator("#run-selection-list").inner_text()
        )
        page.locator('#run-selection-list input[data-file="m0-00"]').uncheck()
        page.locator('#run-selection-list [aria-label="Last page"]').click()
        page.wait_for_function(
            "document.querySelectorAll('#run-selection-list input[type=checkbox]').length === 10"
        )
        assert (
            "4 selected on other pages"
            in page.locator("#run-selection-list").inner_text()
        )
        page.locator('#run-selection-list input[data-file="m0-59"]').check()
        page.locator('#run-selection-list input[data-file="m0-58"]').click()
        assert not page.locator(
            '#run-selection-list input[data-file="m0-58"]'
        ).is_checked()
        page.locator('#run-selection-list [aria-label="First page"]').click()
        page.wait_for_function(
            "document.querySelectorAll('#run-selection-list input[type=checkbox]').length === 50"
        )
        assert not page.locator(
            '#run-selection-list input[data-file="m0-00"]'
        ).is_checked()
        assert page.locator('#run-selection-list input[data-file="m0-01"]').is_checked()
        page.locator("#confirm-run-selection-btn").click()
        page.wait_for_function(
            "__modelsTest.state.modelsViewState.modelStats['alpha|||plain'].selectedPaths.includes('m0-59')"
        )
        assert fixture.stats()["alpha|||plain"]["selectedPaths"] == [
            "m0-01",
            "m0-02",
            "m0-03",
            "m0-04",
            "m0-59",
        ]
        assert any(
            body.get("selected")
            for path, _, body in fixture.requests
            if path.endswith("/models")
        )
        page.evaluate("__modelsTest.saveDashboardState()")
        saved = page.evaluate(
            "Object.values(sessionStorage).find(value => value.includes('modelRunSelections'))"
        )
        assert "candidates" not in saved
        page.locator('.customize-btn[data-model="alpha|||plain"]').click()
        page.wait_for_function(
            "document.querySelectorAll('#run-selection-list input[type=checkbox]').length === 50"
        )
        assert (
            "1 selected on other pages"
            in page.locator("#run-selection-list").inner_text()
        )
        page.locator("#run-selection-modal .modal-close").click()
        page.reload()
        fixture.ready()
        assert "m0-59" in fixture.stats()["alpha|||plain"]["selectedPaths"]
        page.locator('.compare-link[data-model="alpha|||plain"]').click()
        page.wait_for_url("**/compare?*")
        compared = parse_qs(urlparse(page.url).query)["runs"]
        assert compared == ["m0-01", "m0-02", "m0-03", "m0-04", "m0-59"]
    finally:
        fixture.close()


def test_models_global_filters_metric_detection_and_revision_invalidation(browser):
    fixture = ModelsFixture(browser)
    try:
        fixture.open()
        page = fixture.page
        page.locator("#models-metric-select").select_option("count")
        page.wait_for_function("__modelsTest.state.modelsViewState.metricIsNumeric")
        assert page.locator("#models-threshold-row").is_hidden()
        page.evaluate(
            "__modelsTest.state.filterVersions = new Set(['old']); __modelsTest.render()"
        )
        page.wait_for_function(
            "Object.values(__modelsTest.state.modelsViewState.modelStats).every(stats => stats.totalAvailable === 10)"
        )
        assert all(
            stats["selectedPaths"][0].endswith("50")
            for stats in fixture.stats().values()
        )
        before = len(
            [1 for path, _, _ in fixture.requests if path == "/api/models/runs"]
        )
        fixture.revision += 1
        fixture.rows[50]["_revision"] += 1
        page.evaluate("__modelsTest.fetchRuns()")
        page.wait_for_function(
            f"__modelsTest.state.dashboardOverview.revision === {fixture.revision}"
        )
        page.wait_for_function(
            "__modelsTest.state.modelsViewState.candidates.revision === 2"
        )
        assert (
            len([1 for path, _, _ in fixture.requests if path == "/api/models/runs"])
            > before
        )
        before = len(
            [1 for path, _, _ in fixture.requests if path == "/api/models/runs"]
        )
        fixture.revision += 1
        fixture.rows[59]["_revision"] += 1
        page.evaluate("__modelsTest.fetchRuns()")
        page.wait_for_function(
            "__modelsTest.state.modelsViewState.candidates.revision === 3"
        )
        assert (
            len([1 for path, _, _ in fixture.requests if path == "/api/models/runs"])
            == before
        )
        page.evaluate(
            "__modelsTest.state.filterDatasets = new Set(['__none__']); __modelsTest.render()"
        )
        page.wait_for_function(
            "__modelsTest.state.modelsViewState.candidates.rows.length === 0"
        )
        assert page.locator(".model-card").count() == 0
    finally:
        fixture.close()


@pytest.mark.parametrize("failure", ["candidates", "details"])
def test_models_fetch_failure_has_retry_without_false_zero_scores(browser, failure):
    fixture = ModelsFixture(browser)
    try:
        setattr(fixture, "fail_" + failure, True)
        fixture.page.goto("https://qym.test/projects/demo/models")
        fixture.page.locator("#models-load-retry").wait_for()
        assert fixture.page.locator(".model-card").count() == 0
        fixture.page.locator("#models-load-retry").click()
        fixture.ready()
    finally:
        fixture.close()


def test_models_selector_retry_keeps_selection(browser):
    fixture = ModelsFixture(browser)
    try:
        fixture.open()
        page = fixture.page
        page.locator('.customize-btn[data-model="alpha|||plain"]').click()
        page.wait_for_function(
            "document.querySelectorAll('#run-selection-list input[type=checkbox]').length === 50"
        )
        page.locator('#run-selection-list input[data-file="m0-00"]').uncheck()
        fixture.fail_page = True
        page.locator('#run-selection-list [aria-label="Last page"]').click()
        page.locator("[data-selection-retry]").wait_for()
        assert page.locator("#confirm-run-selection-btn").is_disabled()
        page.locator("[data-selection-retry]").click()
        page.wait_for_function(
            "document.querySelectorAll('#run-selection-list input[type=checkbox]').length === 10"
        )
        assert (
            "4 selected on other pages"
            in page.locator("#run-selection-list").inner_text()
        )
        page.locator("#confirm-run-selection-btn").click()
        page.wait_for_function(
            "__modelsTest.state.modelsViewState.modelStats['alpha|||plain'].selectedCount === 4"
        )
    finally:
        fixture.close()


def test_models_large_k_batches_details_and_preserves_all_runs(browser):
    fixture = ModelsFixture(browser)
    try:
        fixture.open()
        fixture.page.locator("#models-k-input").fill("100")
        fixture.page.locator("#models-k-input").dispatch_event("change")
        fixture.page.wait_for_function(
            "Object.values(__modelsTest.state.modelsViewState.modelStats).every(stats => stats.selectedCount === 60)"
        )
        assert all(
            stats["K"] == 62 and len(stats["selectedPaths"]) == 60
            for stats in fixture.stats().values()
        )
        batches = [
            query["files"]
            for path, query, _ in fixture.requests
            if path == "/api/models/runs"
        ]
        assert [len(batch) for batch in batches[-2:]] == [100, 80]
        assert len(set(batches[-2] + batches[-1])) == 180
        assert fixture.page.locator(".runs-warning").count() == 3
    finally:
        fixture.close()


def test_models_stale_candidate_response_cannot_replace_current_filter(browser):
    fixture = ModelsFixture(browser)
    try:
        fixture.open()
        page = fixture.page
        page.evaluate("""() => {
          const fetchOriginal = window.fetch;
          window.fetch = async (url, options) => {
            const response = await fetchOriginal(url, options);
            if (String(url).endsWith('/api/dashboard/models') &&
                JSON.parse(options.body).filters.versions.includes('old')) {
              await new Promise(resolve => window.__releaseOldCandidates = resolve);
              window.__oldCandidatesCompleted = true;
            }
            return response;
          };
          __modelsTest.state.filterVersions = new Set(['old']);
          __modelsTest.render();
        }""")
        page.wait_for_function("typeof window.__releaseOldCandidates === 'function'")
        page.evaluate(
            "__modelsTest.state.filterVersions = new Set(['new']); __modelsTest.render()"
        )
        page.wait_for_function(
            "Object.values(__modelsTest.state.modelsViewState.modelStats).every(stats => stats.totalAvailable === 50)"
        )
        before = fixture.stats()
        page.evaluate("window.__releaseOldCandidates()")
        page.wait_for_function("window.__oldCandidatesCompleted")
        assert fixture.stats() == before
        assert all(
            stats["selectedPaths"][0].endswith("00") for stats in before.values()
        )
    finally:
        fixture.close()
