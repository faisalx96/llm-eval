"""Bounded Runs navigation on the shipped dashboard, with full-history oracles."""

from __future__ import annotations

import json
import mimetypes
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from qym_platform.services.dashboard_views import build_overview_data

STATIC = (
    Path(__file__).resolve().parents[2]
    / "packages/platform/qym_platform/_static/dashboard"
)
pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def browser():
    api = pytest.importorskip("playwright.sync_api")
    with api.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


def make_runs(count=123):
    now = datetime.now(timezone.utc)
    return [
        dict(
            run_id=f"run-{i:03}",
            file_path=f"run-{i:03}",
            run_name=f"Run {i}",
            task_name="Rare task" if i >= 100 else "Common task",
            model_name="model",
            dataset_name="dataset",
            timestamp=(now - timedelta(hours=i)).isoformat(),
            total_items=10,
            success_count=8,
            error_count=1,
            success_rate=0.8,
            metrics=["accuracy"],
            metric_averages={"accuracy": i / 124},
            metric_specs={
                "accuracy": {"score_type": "continuous", "direction": "maximize"}
            },
            metric_neighbor_values={"accuracy": [(i - 1) / 124, (i + 1) / 124]},
            avg_latency_ms=100 + i,
            median_latency_ms=90 + i,
            duration_ms=1000 + i,
            status="COMPLETED",
            samples=1,
            owner={"id": "owner", "display_name": "Owner"},
            git_commit="late-version" if i >= 100 else "early-version",
        )
        for i in range(count)
    ]


def nested(runs):
    tasks = {}
    for run in runs:
        tasks.setdefault(run["task_name"], {}).setdefault(run["model_name"], []).append(
            run
        )
    return tasks


class DashboardFixture:
    def __init__(self, browser, view="table", runs=None):
        self.view = view
        self.api_client = None
        self.runs = runs if runs is not None else make_runs()
        self.requests = []
        self.errors = []
        self.context = browser.new_context(
            viewport={"width": 1440, "height": 1000}, reduced_motion="reduce"
        )
        self.page = self.context.new_page()
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.route("**/*", self.route)

    def scope(self, filters):
        result = self.runs
        for field, attr in [
            ("tasks", "task_name"),
            ("datasets", "dataset_name"),
            ("versions", "git_commit"),
            ("statuses", "status"),
        ]:
            selected = filters.get(field, [])
            if selected:
                result = [row for row in result if row[attr] in selected]
        return result

    def overview(self, scoped):
        return {
            "total_count": len(self.runs),
            "total_runs": len(scoped),
            "aggregations": {
                "totalRuns": len(self.runs),
                "totalModels": 1,
                "totalItems": 10 * len(self.runs),
                "avgSuccess": 0.8,
            },
            "facets": {
                "tasks": ["Common task", "Rare task"],
                "datasets": ["dataset"],
                "models": ["model|||plain"],
                "statuses": ["COMPLETED"],
                "versions": ["early-version", "late-version"],
                "users": ["owner"],
            },
            "owners": {"owner": {"id": "owner", "display_name": "Owner"}},
            "all_models": ["model|||plain"],
            "metrics": ["accuracy"],
            "metric_types": {"accuracy": "score"},
            "has_trace_stats": False,
            "chart_data": build_overview_data(iter(self.runs), iter(scoped))[
                "chart_data"
            ],
            "revision": 1,
            "freshness": {"updating": False},
        }

    def route(self, route):
        url = urlparse(route.request.url)
        query = parse_qs(url.query)
        if route.request.method == "POST":
            query.update(
                {
                    key: [
                        (
                            json.dumps(value)
                            if isinstance(value, (dict, list, bool))
                            else str(value)
                        )
                    ]
                    for key, value in route.request.post_data_json.items()
                }
            )
        if url.path.startswith("/static/"):
            file = STATIC / url.path.split("/static/", 1)[1]
            if file.name == "dashboard.js":
                source = file.read_text().replace(
                    "  checkAuthAndInit();",
                    "  window.__dashboardTest = {state, render, fetchRuns, setTablePage, toggleSelect, moveFocus, dashboardFilters};\n  checkAuthAndInit();",
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
        if url.path == "/v1/me":
            route.fulfill(
                json={
                    "id": "owner",
                    "role": "ADMIN",
                    "display_name": "Owner",
                    "projects": [
                        {
                            "id": "project",
                            "slug": "demo",
                            "name": "Demo",
                            "role": "MANAGER",
                        }
                    ],
                }
            )
            return
        if url.path.startswith("/api/dashboard/"):
            self.requests.append((url.path, query))
            if self.api_client is not None:
                response = self.api_client.request(
                    route.request.method,
                    url.path,
                    params=parse_qs(url.query),
                    json=(
                        route.request.post_data_json
                        if route.request.method == "POST"
                        else None
                    ),
                )
                route.fulfill(
                    status=response.status_code,
                    body=response.content,
                    content_type="application/json",
                )
                return
            filters = json.loads(query.get("filters", ["{}"])[0])
            scoped = self.scope(filters)
            if query.get("task"):
                scoped = [row for row in scoped if row["task_name"] == query["task"][0]]
            if query.get("dataset"):
                scoped = [
                    row for row in scoped if row["dataset_name"] == query["dataset"][0]
                ]
            if url.path.endswith("/runs") or url.path.endswith("/points"):
                sort = query.get("sort", ["time-desc"])[0]
                if sort == "time-asc":
                    scoped = list(reversed(scoped))
                elif sort.startswith("metric-accuracy"):
                    scoped = sorted(
                        scoped,
                        key=lambda r: r["metric_averages"]["accuracy"],
                        reverse=sort.endswith("desc"),
                    )
                offset = int(query.get("offset", ["0"])[0])
                limit = int(query.get("limit", ["50"])[0])
                route.fulfill(
                    json={
                        "tasks": nested(scoped[offset : offset + limit]),
                        "total_runs": len(scoped),
                        "offset": offset,
                        "limit": limit,
                        "has_more": offset + limit < len(scoped),
                        "revision": 1,
                        "freshness": {"updating": False},
                        "pinned_rows": [
                            row
                            for row in self.runs
                            if row["run_id"] in json.loads(query.get("ids", ["[]"])[0])
                        ],
                        "overview": self.overview(scoped),
                    }
                )
            else:
                route.fulfill(json=self.overview(scoped))
            return
        if url.path in ("/projects/demo", "/projects/demo/charts"):
            source = (
                STATIC / ("index.html" if self.view == "table" else "charts.html")
            ).read_text()
            source = re.sub(
                r'<script src="/static/(?:auth|shell)\.js[^\"]*"></script>', "", source
            )
            route.fulfill(body=source, content_type="text/html")
            return
        route.fulfill(status=404, json={"error": url.path})

    def open(self):
        self.page.goto(
            "https://qym.test/projects/demo"
            + ("/charts" if self.view == "charts" else "")
        )
        if self.view == "charts":
            self.page.wait_for_function(
                '() => Array.from(window.__dashboardTest?.state.chartHistory?.values() || []).some(entry => entry.status === "ready")'
            )
        else:
            self.page.wait_for_function(
                "() => window.__dashboardTest?.state.dashboardPage?.rows.length === 50"
            )

    def close(self):
        self.context.close()
        assert not self.errors


@pytest.fixture
def dashboard(browser):
    view = DashboardFixture(browser)
    view.open()
    try:
        yield view
    finally:
        view.close()


def test_initial_page_keeps_global_totals_and_offpage_facets(dashboard):
    page = dashboard.page
    assert page.locator("#runs-tbody tr[data-idx]").count() == 50
    assert page.locator("#status-filter").inner_text() == "123 runs"
    assert page.evaluate("window.__dashboardTest.state.flatRuns.length") == 50
    assert page.evaluate("window.__dashboardTest.state.aggregations.totalItems") == 1230
    assert "Rare task" in page.locator("#filter-task-dropdown").inner_text()
    assert "late-version" in page.locator("#filter-version-dropdown").inner_text()
    assert (
        len([request for request in dashboard.requests if request[0].endswith("/runs")])
        == 1
    )
    assert page.evaluate('sessionStorage.getItem("qym:runs-cache:demo")') is None


def test_page_selection_sort_and_global_filter(dashboard):
    page = dashboard.page
    page.evaluate(
        '() => { const t=window.__dashboardTest; t.state.selectMode=true; t.toggleSelect("run-000"); t.setTablePage(3); t.render(); }'
    )
    page.wait_for_function(
        "() => window.__dashboardTest.state.dashboardPage.offset === 100"
    )
    assert page.locator("#runs-tbody tr[data-idx]").count() == 23
    assert page.evaluate("window.__dashboardTest.state.flatRuns.length") == 24
    assert page.evaluate('window.__dashboardTest.state.selectedRuns.has("run-000")')
    page.evaluate(
        '() => { const t=window.__dashboardTest; t.toggleSelect("run-122"); t.setTablePage(1); t.render(); }'
    )
    page.wait_for_function(
        "() => window.__dashboardTest.state.dashboardPage.offset === 0"
    )
    assert page.locator("#compare-view").is_enabled()
    assert page.evaluate("window.__dashboardTest.state.flatRuns.length") == 51
    page.evaluate(
        '() => { const t=window.__dashboardTest; t.state.sortKey="metric-accuracy-desc"; t.render(); }'
    )
    page.wait_for_function(
        '() => window.__dashboardTest.state.filteredRuns[0]?.run_id === "run-122"'
    )
    page.evaluate(
        '() => { const t=window.__dashboardTest; t.state.filterTasks=new Set(["Rare task"]); t.render(); }'
    )
    page.wait_for_function(
        "() => window.__dashboardTest.state.dashboardPage.total_runs === 23"
    )
    assert page.locator("#runs-tbody tr[data-idx]").count() == 23
    assert "23 of 123 runs" in page.locator("#status-filter").inner_text()
    assert page.locator("#compare-view").is_enabled()


def test_keyboard_page_boundary_and_filtered_empty(dashboard):
    page = dashboard.page
    page.evaluate(
        "() => { const t=window.__dashboardTest; t.state.focusedIndex=49; t.moveFocus(1); }"
    )
    page.wait_for_function(
        "() => window.__dashboardTest.state.dashboardPage.offset === 50"
    )
    assert page.locator('tr[data-idx="50"]').get_attribute("class").find("focused") >= 0
    page.evaluate(
        '() => { const t=window.__dashboardTest; t.state.filterTasks=new Set(["__none__"]); t.render(); }'
    )
    page.wait_for_function(
        "() => window.__dashboardTest.state.dashboardPage.total_runs === 0"
    )
    assert "No runs match current filters" in page.locator("#runs-tbody").inner_text()
    assert page.locator("#empty").is_hidden()
    assert "0 of 123 runs" in page.locator("#status-filter").inner_text()


def test_charts_load_complete_open_dataset_history_and_evict_hidden_tab(browser):
    rows = make_runs(650)
    for row in rows:
        row["task_name"] = "task"
        row["dataset_name"] = (
            "Opened" if int(row["run_id"].split("-")[1]) < 600 else "Hidden"
        )
    view = DashboardFixture(browser, view="charts", runs=rows)
    try:
        view.open()
        page = view.page
        assert page.evaluate("window.__dashboardTest.state.flatRuns.length") == 600
        point_requests = [
            query for path, query in view.requests if path.endswith("/points")
        ]
        assert len(point_requests) == 2
        assert all(query["dataset"] == ["Opened"] for query in point_requests)
        assert page.locator(".chart-bar-label.clickable-run").count() == 600
        assert "650 runs" in page.locator(".chart-task-meta").inner_text()
        assert page.locator('[data-dataset="Hidden"]').inner_text().split() == [
            "Hidden",
            "50",
        ]
        page.locator('[data-dataset="Hidden"]').click()
        page.wait_for_function(
            "() => window.__dashboardTest.state.flatRuns.length === 50"
        )
        assert page.locator(".chart-bar-label.clickable-run").count() == 50
        assert page.evaluate("window.__dashboardTest.state.chartHistory.size") == 1
        assert (
            page.evaluate("window.__dashboardTest.state.aggregations.totalRuns") == 650
        )
    finally:
        view.close()


def test_runs_and_charts_use_actual_post_api_scope_sort_and_selection(
    browser, monkeypatch
):
    from test_models_paging_browser import projected_dashboard

    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite://")

    rows = make_runs()
    for row in rows:
        row["dataset_version"] = "v1"
    with projected_dashboard(rows) as client:
        view = DashboardFixture(browser, runs=rows)
        view.api_client = client
        try:
            view.open()
            page = view.page
            assert page.locator("#status-filter").inner_text() == "123 runs"
            page.evaluate(
                '() => { const t=window.__dashboardTest; t.state.sortKey="task-desc"; t.render(); }'
            )
            page.wait_for_function(
                '() => window.__dashboardTest.state.dashboardPage.rows[0]?.task_name === "Rare task"'
            )
            page.evaluate(
                "() => { const t=window.__dashboardTest; t.state.selectMode=true; t.toggleSelect(t.state.filteredRuns[0].file_path); t.setTablePage(3); t.render(); }"
            )
            page.wait_for_function(
                "() => window.__dashboardTest.state.dashboardPage.offset === 100"
            )
            assert page.evaluate("window.__dashboardTest.state.selectedRuns.size") == 1
            assert page.evaluate("window.__dashboardTest.state.flatRuns.length") == 24
            page.evaluate(
                '() => { const t=window.__dashboardTest; t.state.filterTasks=new Set(["Rare task"]); t.render(); }'
            )
            page.wait_for_function(
                "() => window.__dashboardTest.state.dashboardPage.total_runs === 23"
            )
            assert "23 of 123 runs" in page.locator("#status-filter").inner_text()
            assert (
                page.evaluate("window.__dashboardTest.state.currentProject.role")
                == "MANAGER"
            )
        finally:
            view.close()
        chart = DashboardFixture(browser, view="charts", runs=rows)
        chart.api_client = client
        try:
            chart.open()
            assert (
                chart.page.evaluate(
                    "window.__dashboardTest.state.aggregations.totalRuns"
                )
                == 123
            )
            assert chart.page.locator(".chart-bar-label.clickable-run").count() >= 100
            assert not any(path == "/api/runs" for path, _ in chart.requests)
        finally:
            chart.close()
