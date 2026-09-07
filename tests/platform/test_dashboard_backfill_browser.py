"""Historical runs remain complete while a newly migrated projection warms up."""

import re
from urllib.parse import parse_qs, urlparse

import pytest

from test_dashboard_paging_browser import DashboardFixture, STATIC, browser, nested
from test_dashboard_durable_summaries import database

pytestmark = pytest.mark.browser


class BackfillFixture(DashboardFixture):
    def __init__(self, browser, view="table"):
        self.backfilling = True
        self.published = 12
        self.source_status = 200
        self.fail_offset = None
        self.hold_offset = None
        self.held = []
        super().__init__(browser, view=view)
        self.page.add_init_script((STATIC / "auth.js").read_text())

    def route(self, route):
        url = urlparse(route.request.url)
        if url.path == "/api/runs":
            query = parse_qs(url.query)
            self.requests.append((url.path, query))
            offset = int(query["offset"][0])
            limit = int(query["limit"][0])
            status = 503 if offset == self.fail_offset else self.source_status
            payload = dict(
                tasks=nested(self.runs[offset : offset + limit]),
                total_count=len(self.runs) if offset == 0 else None,
                project={"slug": "demo", "name": "Demo", "id": "project"},
            )
            if offset == self.hold_offset:
                self.held.append((route, payload))
            else:
                route.fulfill(status=status, json=payload)
            return
        if url.path.startswith("/api/dashboard/") and self.backfilling:
            self.requests.append((url.path, {}))
            rows = self.runs[: self.published]
            overview = self.overview(rows)
            overview.update(
                total_count=len(rows),
                total_runs=len(rows),
                freshness={"updating": True, "backfilling": True},
            )
            payload = (
                overview
                if url.path.endswith("/overview")
                else dict(
                    rows=rows,
                    tasks=nested(rows),
                    total_runs=len(rows),
                    overview=overview,
                    freshness=overview["freshness"],
                )
            )
            route.fulfill(json=payload)
            return
        if url.path == "/projects/demo/models":
            source = (STATIC / "models.html").read_text()
            source = re.sub(
                r'<script src="/static/(?:auth|shell)\.js[^\"]*"></script>', "", source
            )
            route.fulfill(body=source, content_type="text/html")
            return
        super().route(route)

    def open(self):
        suffix = "" if self.view == "table" else "/" + self.view
        self.page.goto("https://qym.test/projects/demo" + suffix)
        self.page.wait_for_function("__dashboardTest.state.dashboardBackfilling")

    def wait_for_held_page(self):
        for _ in range(200):
            if self.held:
                return
            self.page.wait_for_timeout(25)
        raise AssertionError("The second history page was never requested")


@pytest.mark.parametrize("view", ["table", "charts", "models"])
def test_backfill_uses_complete_history_and_global_facets(browser, view):
    fixture = BackfillFixture(browser, view=view)
    try:
        fixture.open()
        page = fixture.page
        assert page.evaluate("__dashboardTest.state.flatRuns.length") == 123
        assert page.evaluate("__dashboardTest.state.aggregations.totalItems") == 1230
        assert "Rare task" in page.locator("#filter-task-dropdown").inner_text()
        assert "late-version" in page.locator("#filter-version-dropdown").inner_text()
        assert page.evaluate('sessionStorage.getItem("qym:runs-cache:demo")') is None
        source = [q for path, q in fixture.requests if path == "/api/runs"]
        assert [q["offset"] for q in source] == [["0"], ["100"]]
        assert all(q["project_slug"] == ["demo"] for q in source)
        assert source[1]["include_total"] == ["false"]
        if view == "table":
            assert page.locator("#runs-tbody tr[data-idx]").count() == 50
            assert page.locator("#status-filter").inner_text() == "123 runs"
        # Publishing a few more summaries must never shrink the full history.
        fixture.published = 15
        page.evaluate("__dashboardTest.fetchRuns()")
        assert page.evaluate("__dashboardTest.state.flatRuns.length") == 123
    finally:
        fixture.close()


def test_backfill_waits_for_all_pages_before_rendering(browser):
    fixture = BackfillFixture(browser)
    fixture.hold_offset = 100
    try:
        page = fixture.page
        page.goto("https://qym.test/projects/demo")
        page.wait_for_function("__dashboardTest.state.runsFetchMeta.inFlight")
        # Let the first page finish and the held second request reach its route.
        fixture.wait_for_held_page()
        assert page.evaluate("__dashboardTest.state.flatRuns.length") == 0
        assert page.locator("#table-view").is_hidden()
        for route, payload in fixture.held:
            route.fulfill(json=payload)
        page.wait_for_function("__dashboardTest.state.flatRuns.length === 123")
        assert page.locator("#status-filter").inner_text() == "123 runs"
    finally:
        fixture.close()


def test_backfill_transition_preserves_page_filter_and_selection(browser):
    fixture = BackfillFixture(browser)
    try:
        fixture.open()
        page = fixture.page
        page.evaluate("""() => {
          const t = __dashboardTest;
          t.state.selectMode = true;
          t.toggleSelect('run-000');
          t.setTablePage(3); t.render();
          t.toggleSelect('run-122');
        }""")
        assert page.locator("#runs-tbody tr[data-idx]").count() == 23
        fixture.backfilling = False
        page.evaluate("__dashboardTest.fetchRuns()")
        assert page.evaluate("__dashboardTest.state.dashboardPage.offset") == 100
        assert page.evaluate("__dashboardTest.state.flatRuns.length") == 24
        assert page.evaluate("[...__dashboardTest.state.selectedRuns]") == [
            "run-000",
            "run-122",
        ]
        assert page.locator("#compare-view").is_enabled()
        assert page.locator("#status-filter").inner_text() == "123 runs"
        before = len([r for r in fixture.requests if r[0] == "/api/runs"])
        page.evaluate("__dashboardTest.fetchRuns()")
        assert len([r for r in fixture.requests if r[0] == "/api/runs"]) == before
    finally:
        fixture.close()


def test_backfill_filters_and_sort_include_unpublished_runs(browser):
    fixture = BackfillFixture(browser)
    try:
        fixture.open()
        page = fixture.page
        page.evaluate("""() => {
          const t = __dashboardTest;
          t.state.filterTasks = new Set(['Rare task']);
          t.state.sortKey = 'metric-accuracy-desc';
          t.render();
        }""")
        assert page.locator("#runs-tbody tr[data-idx]").count() == 23
        expected = page.evaluate(
            "__dashboardTest.state.filteredRuns.map(r => r.run_id)"
        )
        assert expected == [f"run-{i:03}" for i in range(122, 99, -1)]
        fixture.backfilling = False
        page.evaluate("__dashboardTest.fetchRuns()")
        assert (
            page.evaluate("__dashboardTest.state.dashboardPage.rows.map(r => r.run_id)")
            == expected
        )
        assert page.locator("#runs-tbody tr[data-idx]").count() == 23
    finally:
        fixture.close()


def test_history_changes_between_pages_retry_without_duplicates(browser):
    fixture = BackfillFixture(browser)
    fixture.hold_offset = 100
    try:
        page = fixture.page
        page.goto("https://qym.test/projects/demo")
        fixture.wait_for_held_page()
        # A new run inserted before page two shifts an already fetched run into
        # that page. The next complete attempt must include the new run once.
        new = {**fixture.runs[0], "run_id": "new-run", "file_path": "new-run"}
        fixture.runs.insert(0, new)
        fixture.hold_offset = None
        for route, payload in fixture.held:
            payload["tasks"] = nested(fixture.runs[100:])
            route.fulfill(json=payload)
        page.wait_for_function("__dashboardTest.state.flatRuns.length === 124")
        assert (
            page.evaluate(
                "new Set(__dashboardTest.state.flatRuns.map(r => r.run_id)).size"
            )
            == 124
        )
        assert page.locator("#status-filter").inner_text() == "124 runs"
        assert len([r for r in fixture.requests if r[0] == "/api/runs"]) == 4
    finally:
        fixture.close()


def test_failed_backfill_page_preserves_previous_complete_data_and_retries(browser):
    fixture = BackfillFixture(browser)
    try:
        fixture.open()
        fixture.fail_offset = 100
        fixture.runs[0] = {**fixture.runs[0], "run_name": "Changed"}
        page = fixture.page
        page.evaluate("__dashboardTest.fetchRuns()")
        assert page.evaluate("__dashboardTest.state.flatRuns.length") == 123
        assert (
            page.evaluate(
                "__dashboardTest.state.flatRuns.find(r => r.run_id === 'run-000').run_name"
            )
            == "Run 0"
        )
        fixture.fail_offset = None
        page.evaluate("__dashboardTest.fetchRuns()")
        assert (
            page.evaluate(
                "__dashboardTest.state.flatRuns.find(r => r.run_id === 'run-000').run_name"
            )
            == "Changed"
        )
    finally:
        fixture.close()


@pytest.mark.parametrize("offset", [0, 100])
def test_expired_backfill_session_clears_data_and_stops_reads(browser, offset):
    fixture = BackfillFixture(browser)
    try:
        fixture.open()
        if offset == 0:
            fixture.source_status = 401
        else:
            original = fixture.route

            def expire_second(route):
                if (
                    "/api/runs?" in route.request.url
                    and "offset=100&" in route.request.url
                ):
                    route.fulfill(status=401, json={"detail": "Expired"})
                else:
                    original(route)

            fixture.page.unroute("**/*")
            fixture.page.route("**/*", expire_second)
        fixture.page.evaluate("__dashboardTest.fetchRuns()")
        fixture.page.get_by_role("link", name="Sign in", exact=True).wait_for()
        before = len(fixture.requests)
        fixture.page.evaluate("__dashboardTest.fetchRuns()")
        assert len(fixture.requests) == before
        assert fixture.page.locator("#runs-tbody").count() == 0
    finally:
        fixture.close()


def test_real_unprojected_history_matches_after_backfill(browser, database):
    from datetime import datetime, timedelta

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from qym_platform.api import dashboard, runs
    from qym_platform.auth import Principal, require_ui_principal
    from qym_platform.db.models import Project, RunItemScore, RunWorkflowStatus, User
    from qym_platform.deps import get_db
    from qym_platform.services import dashboard_summaries as service
    from test_dashboard_durable_summaries import drain, item, run

    with Session(database) as db:
        db.info["dashboard_projection_worker"] = True
        db.get(Project, "p").slug = "demo"
        for index in range(123):
            run_id = f"real-{index:03}"
            run(
                db,
                run_id=run_id,
                status=RunWorkflowStatus.COMPLETED,
                created_at=datetime(2026, 9, 1) + timedelta(minutes=index),
                run_metadata={"total_items": 2},
            )
            item(db, run_id=run_id, latency_ms=index + 1)
            item(
                db,
                item_id="failed",
                run_id=run_id,
                status="error",
                error="failed",
                latency_ms=50,
            )
            db.add(
                RunItemScore(
                    run_id=run_id,
                    item_id="i",
                    metric_name="score",
                    score_numeric=(index % 10) / 10,
                )
            )
        db.commit()
        service.bootstrap_partitions(db, limit=500)
        db.commit()

    app = FastAPI()
    app.include_router(runs.router)
    app.include_router(dashboard.router)

    def session():
        with Session(database) as db:
            yield db

    with Session(database) as db:
        owner = db.get(User, "u")
        db.expunge(owner)
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[require_ui_principal] = lambda: Principal(
        user=owner, auth_type="none"
    )

    class SourceFixture(DashboardFixture):
        def route(self, route):
            url = urlparse(route.request.url)
            if url.path == "/api/runs":
                response = self.api_client.get(url.path, params=parse_qs(url.query))
                route.fulfill(
                    status=response.status_code,
                    body=response.content,
                    content_type="application/json",
                )
                return
            super().route(route)

    with TestClient(app) as client:
        fixture = SourceFixture(browser)
        fixture.api_client = client
        try:
            page = fixture.page
            page.goto("https://qym.test/projects/demo")
            page.wait_for_function("__dashboardTest.state.flatRuns.length === 123")
            assert page.evaluate("__dashboardTest.state.dashboardBackfilling")
            before = page.evaluate("__dashboardTest.state.flatRuns")
            assert page.locator("#status-filter").inner_text() == "123 runs"
            assert all(
                row["total_items"] == 2 and row["error_count"] == 1 for row in before
            )
            expected = {row["run_id"]: row for row in before}
            drain(database)
            page.evaluate("__dashboardTest.fetchRuns()")
            assert not page.evaluate("__dashboardTest.state.dashboardBackfilling")
            assert page.evaluate("__dashboardTest.state.flatRuns.length") == 50
            assert page.locator("#status-filter").inner_text() == "123 runs"
            for actual in page.evaluate("__dashboardTest.state.flatRuns"):
                for key in (
                    "total_items",
                    "success_count",
                    "error_count",
                    "metric_averages",
                    "avg_latency_ms",
                    "median_latency_ms",
                    "status",
                ):
                    assert actual[key] == expected[actual["run_id"]][key]
        finally:
            fixture.close()
