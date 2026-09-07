"""Independent overview review with the shipped shell, data flow and layout."""

from __future__ import annotations

import mimetypes
import json
import subprocess
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

STATIC = (
    Path(__file__).resolve().parents[2]
    / "packages/platform/qym_platform/_static/dashboard"
)
SCREENSHOTS = (
    Path(__file__).resolve().parents[2] / "artifacts/p1-validation/screenshots"
)
BASELINE = "b1d1d00587df4fcf0e70875c29b0bb0cbc20172c"
pytestmark = pytest.mark.browser


@lru_cache
def baseline_asset(name):
    return subprocess.check_output(
        [
            "git",
            "show",
            f"{BASELINE}:packages/platform/qym_platform/_static/dashboard/{name}",
        ],
        cwd=STATIC,
    )


@pytest.fixture(scope="module")
def browser():
    api = pytest.importorskip("playwright.sync_api")
    with api.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


class OverviewFixture:
    def __init__(self, browser, baseline=False):
        self.baseline = baseline
        self.pending = False
        self.empty = False
        self.denied = False
        self.live_label = "Evaluation in progress"
        self.requests = []
        self.errors = []
        self.context = browser.new_context(
            viewport={"width": 1440, "height": 1000}, reduced_motion="reduce"
        )
        self.page = self.context.new_page()
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.route("**/*", self.route)

    def route(self, route):
        path = urlparse(route.request.url).path
        if path.startswith("/static/"):
            file = STATIC / path.split("/static/", 1)[1]
            if file.is_file():
                route.fulfill(
                    body=(
                        baseline_asset(str(file.relative_to(STATIC)))
                        if self.baseline
                        else file.read_bytes()
                    ),
                    content_type=mimetypes.guess_type(file.name)[0]
                    or "application/octet-stream",
                )
            else:
                route.fulfill(status=404, body="")
            return
        if path in ("/v1/me", "/api/v1/me"):
            route.fulfill(
                json={
                    "id": "owner",
                    "email": "owner@example.test",
                    "display_name": "Owner",
                    "role": "ADMIN",
                    "projects": [
                        {
                            "id": "project",
                            "slug": "demo",
                            "name": "Demo project",
                            "role": "MANAGER",
                        }
                    ],
                }
            )
            return
        if path in ("/api/dashboard/runs", "/api/runs", "/api/runs/live"):
            if path == "/api/dashboard/runs":
                body = route.request.post_data_json
            else:
                query = parse_qs(urlparse(route.request.url).query)
                body = {
                    "filters": {
                        "statuses": (
                            ["RUNNING"]
                            if path.endswith("/live")
                            else (
                                ["APPROVED"]
                                if query.get("status") == ["APPROVED"]
                                else ["COMPLETED"]
                            )
                        )
                    }
                }
            self.requests.append(body)
            if self.denied:
                route.fulfill(status=401, json={"detail": "Expired session"})
                return
            live = "RUNNING" in body["filters"]["statuses"]
            approved = body["filters"]["statuses"] == ["APPROVED"]
            rows = (
                []
                if self.pending or self.empty
                else [
                    {
                        "run_id": (
                            "live-run"
                            if live
                            else "approved-run" if approved else "recent-run"
                        ),
                        "run_name": (
                            self.live_label
                            if live
                            else (
                                "Approved evaluation"
                                if approved
                                else "Latest evaluation"
                            )
                        ),
                        "task_name": "Question answering",
                        "model_name": "model",
                        "dataset_name": "benchmark",
                        "status": (
                            "RUNNING"
                            if live
                            else "APPROVED" if approved else "COMPLETED"
                        ),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "owner": {"id": "owner", "display_name": "Owner"},
                        "total_items": 240,
                        "progress_total": 240,
                        "progress_completed": 120 if live else 240,
                        "metrics": ["accuracy"],
                        "metric_averages": {"accuracy": 0.85},
                        "samples": 3 if live else 1,
                        "last_completed_pass": 1,
                    }
                ]
            )
            total = (
                0
                if self.pending or self.empty
                else 1 if live else 12 if approved else 25
            )
            route.fulfill(
                json={
                    "rows": rows,
                    "runs": rows,
                    "tasks": {"Question answering": {"model": rows}} if rows else {},
                    "total_runs": total,
                    "total_count": total,
                    "freshness": {"updating": self.pending},
                }
            )
            return
        if path == "/api/corrections":
            route.fulfill(
                json={
                    "corrections": [{"id": 1, "human_root_cause": "Reasoning error"}],
                    "total": 1,
                }
            )
            return
        if path == "/projects/demo/overview":
            source = (
                baseline_asset("overview.html").decode()
                if self.baseline
                else (STATIC / "overview.html").read_text()
            ).replace(
                "      load().catch(err => {",
                "      window.__overviewTest = {load, loadLiveRuns};\n      load().catch(err => {",
            )
            route.fulfill(body=source, content_type="text/html")
            return
        route.fulfill(status=404, json={"detail": path})

    def open(self):
        self.page.goto("https://qym.test/projects/demo/overview")
        self.page.wait_for_function(
            "window.__overviewTest && document.querySelector('#approved-runs-body').textContent.indexOf('Loading...') < 0"
        )

    def close(self):
        self.context.close()
        assert not self.errors


def test_overview_post_filters_progress_links_and_layout(browser):
    fixture = OverviewFixture(browser)
    try:
        fixture.open()
        page = fixture.page
        assert page.locator("#overview-title").inner_text() == "Demo project"
        assert page.locator("#ov-runs").inner_text() == "25"
        assert "pass 2/3" in page.locator("#live-runs-body").inner_text()
        assert "120/240" in page.locator("#live-runs-body").inner_text()
        assert (
            page.locator("#recent-runs-body a").get_attribute("href")
            == "/projects/demo/runs/recent-run"
        )
        assert (
            page.locator("#view-all-reviews").get_attribute("href")
            == "/projects/demo/reviews"
        )
        assert [request["limit"] for request in fixture.requests] == [8, 5, 5]
        assert "RUNNING" not in fixture.requests[1]["filters"]["statuses"]
        assert fixture.requests[2]["filters"]["statuses"] == ["APPROVED"]
        SCREENSHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SCREENSHOTS / "overview-desktop.png"), full_page=True)
        assert page.locator("#recent-runs-table").evaluate(
            "element => element.getBoundingClientRect().right <= innerWidth"
        )
        page.set_viewport_size({"width": 1280, "height": 900})
        page.screenshot(
            path=str(SCREENSHOTS / "overview-desktop-1280.png"), full_page=True
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    finally:
        fixture.close()


def test_overview_narrow_layout_matches_baseline_limitation(browser):
    geometry = {}
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    for baseline in (True, False):
        fixture = OverviewFixture(browser, baseline=baseline)
        try:
            fixture.open()
            fixture.page.set_viewport_size({"width": 390, "height": 844})
            name = "baseline" if baseline else "current"
            fixture.page.screenshot(
                path=str(
                    SCREENSHOTS
                    / f"overview-narrow{'-baseline' if baseline else ''}.png"
                ),
                full_page=True,
            )
            geometry[name] = fixture.page.evaluate("""() => ({
              viewport: innerWidth,
              mainWidth: document.querySelector('main').getBoundingClientRect().width,
              recentTableWidth: document.querySelector('#recent-runs-table').getBoundingClientRect().width,
              recentCardWidth: document.querySelector('#recent-runs-table').closest('.overview-card').getBoundingClientRect().width,
              sidebarWidth: document.querySelector('#qym-sidebar').getBoundingClientRect().width
            })""")
        finally:
            fixture.close()
    (SCREENSHOTS / "overview-narrow-comparison.json").write_text(
        json.dumps(
            {
                "baseline_ref": BASELINE,
                "geometry": geometry,
                "limitation": "At 390px the persistent sidebar and two-column cards clip table content in both versions.",
            },
            indent=2,
        )
        + "\n"
    )
    # Existing clipping is documented explicitly; this is a regression comparison,
    # not a claim that narrow viewports are fully supported.
    assert geometry["current"] == geometry["baseline"]
    assert (
        geometry["current"]["recentTableWidth"] > geometry["current"]["recentCardWidth"]
    )


def test_overview_initial_projection_distinguishes_unknown_from_empty(browser):
    fixture = OverviewFixture(browser)
    fixture.pending = True
    try:
        fixture.open()
        page = fixture.page
        assert "Updating" in page.locator("#recent-runs-body").inner_text()
        assert page.locator("#recent-runs-body").get_attribute("aria-busy") == "true"
        assert page.locator("#ov-runs").inner_text() == "—"
        assert page.locator("#ov-items").inner_text() == "—"
        fixture.pending = False
        page.evaluate("__overviewTest.load()")
        assert page.locator("#ov-runs").inner_text() == "25"
        assert page.locator("#recent-runs-body").get_attribute("aria-busy") == "false"
        fixture.empty = True
        page.evaluate("__overviewTest.load()")
        assert page.locator("#ov-runs").inner_text() == "0"
        assert page.locator("#ov-items").inner_text() == "0"
        assert page.locator("#ov-success").inner_text() == "—"
        assert "No runs yet" in page.locator("#recent-runs-body").inner_text()
    finally:
        fixture.close()


def test_overview_expired_session_shows_auth_and_stops_refresh(browser):
    fixture = OverviewFixture(browser)
    try:
        fixture.open()
        fixture.denied = True
        fixture.page.evaluate("__overviewTest.loadLiveRuns('demo')")
        fixture.page.get_by_role("link", name="Sign in", exact=True).wait_for()
        before = len(fixture.requests)
        fixture.page.evaluate("__overviewTest.loadLiveRuns('demo')")
        assert len(fixture.requests) == before
    finally:
        fixture.close()


def test_overview_out_of_order_live_reply_does_not_restore_old_progress(browser):
    fixture = OverviewFixture(browser)
    try:
        fixture.open()
        page = fixture.page
        fixture.live_label = "Older result"
        page.evaluate("""() => {
          const original = fetch;
          let hold = true;
          window.fetch = async (...args) => {
            const response = await original(...args);
            if (hold && String(args[0]).endsWith('/api/dashboard/runs')) {
              hold = false;
              await new Promise(resolve => window.__releaseOldLive = resolve);
            }
            return response;
          };
          __overviewTest.loadLiveRuns('demo');
        }""")
        page.wait_for_function("typeof window.__releaseOldLive === 'function'")
        fixture.live_label = "Newer result"
        page.evaluate("__overviewTest.loadLiveRuns('demo')")
        assert "Newer result" in page.locator("#live-runs-body").inner_text()
        page.evaluate("window.__releaseOldLive()")
        page.evaluate(
            "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
        )
        assert "Newer result" in page.locator("#live-runs-body").inner_text()
    finally:
        fixture.close()


def test_overview_late_unauthorized_reply_preserves_next_page(browser):
    fixture = OverviewFixture(browser)
    try:
        fixture.open()
        fixture.denied = True
        page = fixture.page
        page.evaluate("""() => {
          const original = fetch;
          window.fetch = async (...args) => {
            const response = await original(...args);
            await new Promise(resolve => window.__releaseUnauthorized = resolve);
            return response;
          };
          window.__pendingLive = __overviewTest.loadLiveRuns('demo');
        }""")
        page.wait_for_function("typeof __releaseUnauthorized === 'function'")
        page.evaluate("""async () => {
          document.dispatchEvent(new CustomEvent('qym:before-navigate'));
          document.querySelector('main').innerHTML = '<p id="next-page">Next page</p>';
          __releaseUnauthorized();
          await __pendingLive;
        }""")
        assert page.locator("#next-page").inner_text() == "Next page"
        assert page.get_by_role("link", name="Sign in", exact=True).count() == 0
    finally:
        fixture.close()
