"""Review summary initialization, session expiry and retained selections."""

from urllib.parse import urlparse

import pytest

from test_dashboard_paging_browser import DashboardFixture, STATIC, browser

pytestmark = pytest.mark.browser


class ReviewFixture(DashboardFixture):
    def __init__(self, browser):
        self.pending = False
        self.denied = False
        super().__init__(browser)
        # The shared fixture isolates shell navigation; retain the actual auth UI.
        self.page.add_init_script((STATIC / "auth.js").read_text())

    def route(self, route):
        path = urlparse(route.request.url).path
        if path.startswith("/api/dashboard/") and (self.pending or self.denied):
            self.requests.append((path, route.request.post_data_json))
            if self.denied:
                route.fulfill(status=401, json={"detail": "Expired session"})
                return
            overview = self.overview([])
            overview.update(total_count=0, total_runs=0, freshness={"updating": True})
            overview["aggregations"].update(totalRuns=0, totalModels=0, totalItems=0)
            route.fulfill(
                json={
                    "tasks": {},
                    "pinned_rows": [],
                    "total_runs": 0,
                    "overview": overview,
                    "freshness": {"updating": True},
                }
            )
            return
        super().route(route)


def test_initial_projection_is_loading_until_history_arrives(browser):
    fixture = ReviewFixture(browser)
    fixture.pending = True
    try:
        page = fixture.page
        page.goto("https://qym.test/projects/demo")
        page.get_by_text("Preparing run history…", exact=True).wait_for()
        assert page.locator("#empty").is_hidden()
        assert page.locator("#table-view").is_hidden()
        fixture.pending = False
        page.evaluate("__dashboardTest.fetchRuns()")
        page.wait_for_function("__dashboardTest.state.dashboardPage.rows.length === 50")
        assert page.locator("#loading").is_hidden()
        assert page.locator("#runs-tbody tr[data-idx]").count() == 50
        assert page.locator("#status-filter").inner_text() == "123 runs"
    finally:
        fixture.close()


def test_expired_session_removes_data_and_stops_reads(browser):
    fixture = ReviewFixture(browser)
    try:
        fixture.open()
        fixture.denied = True
        fixture.page.evaluate("__dashboardTest.fetchRuns()")
        fixture.page.get_by_role("link", name="Sign in", exact=True).wait_for()
        before = len(fixture.requests)
        fixture.page.evaluate("__dashboardTest.fetchRuns()")
        assert len(fixture.requests) == before
        assert fixture.page.locator("#runs-tbody").count() == 0
    finally:
        fixture.close()


def test_offpage_selection_refreshes_and_removes_deleted_run(browser):
    fixture = ReviewFixture(browser)
    try:
        fixture.open()
        page = fixture.page
        page.evaluate("""() => {
          const t = __dashboardTest;
          t.state.selectMode = true;
          t.toggleSelect('run-000');
          t.setTablePage(3); t.render();
        }""")
        page.wait_for_function("__dashboardTest.state.dashboardPage.offset === 100")
        page.evaluate("__dashboardTest.toggleSelect('run-122')")
        fixture.runs[0]["status"] = "APPROVED"
        fixture.runs[0]["owner"] = {"id": "reviewer", "display_name": "Reviewer"}
        page.evaluate("__dashboardTest.fetchRuns()")
        selected = page.evaluate(
            "__dashboardTest.state.flatRuns.find(row => row.run_id === 'run-000')"
        )
        assert selected["status"] == "APPROVED"
        assert selected["owner"]["display_name"] == "Reviewer"
        assert page.locator("#compare-view").is_enabled()
        assert page.evaluate("__dashboardTest.state.flatRuns.length") == 24
        fixture.runs = [row for row in fixture.runs if row["run_id"] != "run-000"]
        page.evaluate("__dashboardTest.fetchRuns()")
        assert not page.evaluate("__dashboardTest.state.selectedRuns.has('run-000')")
        assert page.evaluate("__dashboardTest.state.selectedRuns.has('run-122')")
        assert page.locator("#compare-view").is_disabled()
        assert page.locator("#status-filter").inner_text() == "122 runs"
    finally:
        fixture.close()
