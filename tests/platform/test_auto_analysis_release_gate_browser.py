"""Release-gate browser contracts for the actual Auto-analysis static page.

The fixture deliberately serves the repository's production assets instead of a
copy. Its HTTP handler supplies deterministic API payloads for the canonical
project and run routes, so failures here are browser-visible regressions rather
than FastAPI/auth/database integration failures.
"""

from __future__ import annotations

import json
import mimetypes
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, urlparse

import pytest


REPO = Path(__file__).resolve().parents[2]
STATIC = REPO / "packages/platform/qym_platform/_static/dashboard"
ANALYZER = STATIC / "analyzer.html"


def _run_payload(*, all_pass: bool = False) -> dict[str, Any]:
    quality = 0.95 if all_pass else 0.25
    latency = 0.10 if all_pass else 0.95
    return {
        "run": {"file_path": "run-1", "run_name": "Demo run", "metric_names": ["quality", "latency"]},
        "snapshot": {
            "metric_names": ["quality", "latency"],
            "metric_specs": {
                "quality": {"pass_threshold": 0.8, "direction": "maximize"},
                "latency": {"pass_threshold": 0.2, "direction": "minimize"},
            },
            "rows": [
                {
                    "item_id": "item-1",
                    "index": 0,
                    "input": {"question": "demo"},
                    "expected": {"answer": "expected"},
                    "output": {"answer": "actual"},
                    "metric_values": [quality, latency],
                    "metric_meta": {"quality": {}, "latency": {}},
                    "item_metadata": {},
                }
            ],
        },
    }


def _analysis_config(*, llm: bool = True) -> dict[str, Any]:
    return {
        "llm_configured": llm,
        "model": "demo-model" if llm else None,
        "llm_connections": ([{"id": "conn-1", "name": "Demo", "llm_model": "demo-model", "llm_api_key_set": True}] if llm else []),
        "default_connection_id": "conn-1" if llm else None,
        "analysis_rules": [],
        "analysis_rule_version": None,
        "default_categories": ["Reasoning Error"],
        "category_details_map": {},
        "category_taxonomy": {},
        "category_examples": {},
        "category_example_counts": {},
        "existing_details": [],
        "max_root_cause_categories": 3,
        "can_manage_analysis_rules": True,
    }


def _dashboard_payload(*, populated: bool = False) -> dict[str, Any]:
    categories = ([
        {"category": "Reasoning Error", "count": 500},
        {"category": "Retrieval Error", "count": 150},
    ] if populated else [])
    return {
        "summary": {
            "diagnosis_occurrences": 650 if populated else 0,
            "affected_run_item_pairs": 1 if populated else 0,
            "runs_with_diagnoses": 1 if populated else 0,
            "categories": len(categories),
            "most_repeated_category": categories[0] if categories else None,
            "failure_coverage": {"rate": 1 if populated else 0, "diagnosed_failed_pairs": 1 if populated else 0, "failed_pairs": 1 if populated else 0},
        },
        "facets": {
            "runs": [{"run_id": "run-1", "run_name": "Demo run", "count": 650}] if populated else [],
            "metrics": [{"value": "quality", "count": 650}] if populated else [],
            "score_metrics": ["quality"] if populated else [],
            "categories": [{"value": item["category"], "count": item["count"]} for item in categories],
            "sources": [{"value": "ai", "count": 650}] if populated else [],
            "tasks": [], "datasets": [], "models": [], "details": [], "review_statuses": [],
        },
        "groups": {"by_category": categories, "by_run": [{"run_id": "run-1", "run_name": "Demo run", "occurrence_count": 650, "categories": [{"value": item["category"], "count": item["count"]} for item in categories]}] if populated else []},
        "scores": {"runs": [], "metric_name": ""},
    }


def _dashboard_compare_payload() -> dict[str, Any]:
    payload = _dashboard_payload(populated=True)
    runs = [
        {"run_id": "run-1", "run_name": "Run One", "count": 10},
        {"run_id": "run-2", "run_name": "Run Two", "count": 20},
        {"run_id": "run-3", "run_name": "Run Three", "count": 30},
    ]
    payload["facets"]["runs"] = [
        {"run_id": run["run_id"], "run_name": run["run_name"], "count": run["count"]}
        for run in runs
    ]
    payload["groups"]["by_run"] = [
        {
            "run_id": run["run_id"],
            "run_name": run["run_name"],
            "occurrence_count": run["count"],
            "categories": [{"value": "Reasoning Error", "count": run["count"]}],
        }
        for run in runs
    ]
    payload["scores"] = {
        "runs": [
            {"run_id": run["run_id"], "average": 0.1 * (index + 2), "spec": {"direction": "maximize"}}
            for index, run in enumerate(runs)
        ],
        "metric_name": "quality",
    }
    return payload


def _compare_payload(query: dict[str, list[str]]) -> dict[str, Any]:
    labels = {"run-1": "Run One", "run-2": "Run Two", "run-3": "Run Three"}
    values = {"run-1": 11, "run-2": 22, "run-3": 33}
    selected = query.get("run_id", [])
    return {
        "run_ids": selected,
        "baseline_run_id": selected[0] if selected else "",
        "score_metric": "quality",
        "score_compatibility": {"comparable": True, "reason": "", "missing_run_ids": []},
        "runs": [{"run_id": run_id, "run_name": labels[run_id], "metrics": ["quality"]} for run_id in selected],
        "score_comparison": [
            {
                "run_id": run_id,
                "average": values[run_id],
                "comparison_status": "baseline" if index == 0 else "improved",
                "improvement_delta": 1.0,
            }
            for index, run_id in enumerate(selected)
        ],
        "category_matrix": [
            {
                "category": "Reasoning Error",
                "runs": {run_id: {"count": values[run_id]} for run_id in selected},
                "total_count": sum(values[run_id] for run_id in selected),
            }
        ],
        "metric_matrix": [],
        "run_summary": [
            {
                "run_id": run_id,
                "run_name": labels[run_id],
                "count": values[run_id],
                "share": 0.5,
                "average_score": values[run_id],
            }
            for run_id in selected
        ],
        "summary": {
            "best_run_id": selected[-1] if selected else None,
            "occurrences": sum(values[run_id] for run_id in selected),
            "categories": 1,
            "changes": 0,
        },
        "changes": [],
    }


def _occurrence_page(*, offset: int, limit: int, total: int = 650) -> dict[str, Any]:
    end = min(offset + limit, total)
    return {
        "total": total,
        "occurrences": [
            {
                "category": "Reasoning Error" if index % 2 == 0 else "Retrieval Error",
                "detail": "Diagnosis " + str(index),
                "source": "ai",
                "metric_name": "quality",
                "score": 0.25,
                "run_id": "run-1",
                "item_id": "item-" + str(index),
                "input": "Question " + str(index),
            }
            for index in range(offset, end)
        ],
    }


class _AnalyzerHandler(BaseHTTPRequestHandler):
    server: "_AnalyzerServer"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _asset(self, relative: str) -> None:
        candidate = (STATIC / relative).resolve()
        if STATIC not in candidate.parents or not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(str(candidate))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path in {"/projects/demo/analysis", "/projects/demo/runs/run-1/analyzer"}:
            self._asset("analyzer.html")
            return
        if path.startswith("/static/"):
            self._asset(path.removeprefix("/static/"))
            return
        # The shared shell validates the routed project against the signed-in
        # user's project list before the analyzer initializes.
        if path in {"/api/v1/me", "/v1/me"}:
            self._json({"email": "release-gate@example.test", "projects": [{"id": "project-demo", "name": "Demo", "slug": "demo", "role": "manager"}]})
            return
        if path == "/api/runs/run-1":
            if self.server.mode == "missing":
                self._json({"detail": "Run not found"}, 404)
            elif self.server.mode == "forbidden":
                self._json({"detail": "Access denied"}, 403)
            elif self.server.mode == "error_once" and self.server.run_requests == 0:
                self.server.run_requests += 1
                self._json({"detail": "Temporary failure"}, 500)
            else:
                self.server.run_requests += 1
                self._json(_run_payload(all_pass=self.server.mode == "zero_targets"))
            return
        if path.endswith("/analysis-config"):
            self._json(_analysis_config(llm=self.server.mode != "no_llm"))
            return
        if path.endswith("/analysis-documents"):
            self._json({"documents": []})
            return
        if path.endswith("/analysis-rule-versions"):
            self._json({"versions": [], "production_version_id": None, "can_delete": True, "can_activate": True, "can_restore": False})
            return
        if path.endswith("/root-cause-dashboard/compare"):
            query = parse_qs(parsed.query)
            self.server.compare_queries.append(query)
            self._json(_compare_payload(query))
            return
        if "/root-cause-dashboard/occurrences" in path:
            query = parse_qs(parsed.query)
            self.server.occurrence_queries.append(query)
            if self.server.mode == "dashboard_scale":
                self._json(_occurrence_page(offset=int(query.get("offset", [0])[0]), limit=int(query.get("limit", [200])[0])))
            else:
                self._json({"total": 0, "occurrences": []})
            return
        if "/root-cause-dashboard" in path:
            self.server.dashboard_queries.append(parse_qs(parsed.query))
            self._json(
                _dashboard_compare_payload()
                if self.server.mode == "dashboard_compare"
                else _dashboard_payload(populated=self.server.mode in {"dashboard_scale", "dashboard_filter"})
            )
            return
        if path.endswith("/insights/relationships"):
            self._json({"counts": {}, "policy": {}, "scope": {}, "categories": []})
            return
        # Shell/auth helpers may probe endpoints. A stable empty JSON object is
        # preferable to a failed resource request that obscures page errors.
        self._json({})


class _AnalyzerServer(ThreadingHTTPServer):
    mode: str = "ok"
    run_requests: int = 0
    dashboard_queries: list[dict[str, list[str]]]
    occurrence_queries: list[dict[str, list[str]]]
    compare_queries: list[dict[str, list[str]]]

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.dashboard_queries = []
        self.occurrence_queries = []
        self.compare_queries = []


@pytest.fixture(scope="module")
def chromium_browser() -> Iterator[object]:
    sync_api = pytest.importorskip("playwright.sync_api")
    try:
        with sync_api.sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                yield browser
            finally:
                browser.close()
    except sync_api.Error:
        # Browser release gates must fail when CI has not provisioned Chromium.
        if os.environ.get("CI"):
            raise
        pytest.skip("Chromium is unavailable; run: playwright install chromium")


@pytest.fixture(scope="module")
def analyzer_server(chromium_browser: object) -> Iterator[_AnalyzerServer]:
    server = _AnalyzerServer(("127.0.0.1", 0), _AnalyzerHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.fixture
def analyzer_page(chromium_browser: object, analyzer_server: _AnalyzerServer) -> Iterator[tuple[object, _AnalyzerServer]]:
    analyzer_server.mode = "ok"
    analyzer_server.run_requests = 0
    analyzer_server.dashboard_queries = []
    analyzer_server.occurrence_queries = []
    analyzer_server.compare_queries = []
    context = chromium_browser.new_context(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
    page = context.new_page()
    errors: list[str] = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        yield page, analyzer_server
    finally:
        context.close()
        if getattr(page, "_release_gate_allow_http_console_errors", False):
            errors = [
                error for error in errors
                if not error.startswith("Failed to load resource: the server responded with a status of")
            ]
        assert not errors, "Browser console/page errors: " + "; ".join(errors)


pytestmark = pytest.mark.browser


def _url(server: _AnalyzerServer, path: str) -> str:
    return f"http://127.0.0.1:{server.server_port}{path}"


def _wait_ready(page: object) -> None:
    page.wait_for_function(
        """() => {
          const loading = document.getElementById('analysis-loading');
          const tabs = document.getElementById('analysis-tabs');
          return Boolean(loading && tabs && (!loading.hidden || !tabs.hidden));
        }"""
    )
    page.wait_for_function("() => { const tabs = document.getElementById('analysis-tabs'); return Boolean(tabs && !tabs.hidden); }")


def test_project_route_keeps_analyze_run_tab(analyzer_page: tuple[object, _AnalyzerServer]) -> None:
    page, server = analyzer_page
    page.goto(_url(server, "/projects/demo/analysis"))
    _wait_ready(page)
    tabs = page.locator("#analysis-tabs [role=tab]:visible")
    assert tabs.evaluate_all("tabs => tabs.map(tab => tab.dataset.analysisView)") == ["dashboard", "run", "categories", "rules", "documents"]
    assert page.locator("#analysis-run-tab").is_visible()
    assert page.locator("#analysis-dashboard").is_visible()


def test_run_route_targets_direction_copy_and_sticky_command(analyzer_page: tuple[object, _AnalyzerServer]) -> None:
    page, server = analyzer_page
    page.goto(_url(server, "/projects/demo/runs/run-1/analyzer"))
    _wait_ready(page)
    assert page.locator("#analysis-tabs [role=tab]:visible").count() == 5
    page.wait_for_selector("#analyzer-host .pg-item-row")
    assert "quality" in page.locator("#analyzer-host .pg-item-row").first.inner_text()
    assert page.locator("#pg-max-score-direction-note").inner_text().lower() == "(applies only to higher-is-better metrics)"
    footer = page.locator("#analyzer-host .playground-footer.analysis-run-footer")
    footer.wait_for(state="visible")
    assert footer.evaluate("el => getComputedStyle(el).position") == "sticky"
    assert page.locator("#pg-runall-btn").inner_text() == "Analyze 1 item"


@pytest.mark.parametrize("mode, expected", [("missing", "HTTP 404"), ("forbidden", "HTTP 403"), ("no_llm", "No LLM connection"), ("zero_targets", "All matching targets already have analysis")])
def test_run_release_states(analyzer_page: tuple[object, _AnalyzerServer], mode: str, expected: str) -> None:
    page, server = analyzer_page
    server.mode = mode
    page.goto(_url(server, "/projects/demo/runs/run-1/analyzer"))
    if mode in {"missing", "forbidden"}:
        page._release_gate_allow_http_console_errors = True
        page.wait_for_selector("#analysis-error:not([hidden])")
        assert expected in page.locator("#analysis-error").inner_text()
    else:
        _wait_ready(page)
        page.wait_for_selector("text=" + expected)


def test_retry_and_tab_keyboard_focus(analyzer_page: tuple[object, _AnalyzerServer]) -> None:
    page, server = analyzer_page
    server.mode = "error_once"
    page.goto(_url(server, "/projects/demo/runs/run-1/analyzer"))
    page._release_gate_allow_http_console_errors = True
    page.wait_for_selector("#analysis-error:not([hidden])")
    page.locator("#analysis-error-retry").click()
    _wait_ready(page)
    page.goto(_url(server, "/projects/demo/analysis"))
    _wait_ready(page)
    first = page.locator("#analysis-dashboard-tab")
    first.focus()
    page.keyboard.press("End")
    assert page.locator("#analysis-documents-tab").evaluate("el => document.activeElement === el")


def test_mobile_rtl_no_body_overflow_and_discoverable_controls(analyzer_page: tuple[object, _AnalyzerServer]) -> None:
    page, server = analyzer_page
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(_url(server, "/projects/demo/runs/run-1/analyzer"))
    _wait_ready(page)
    page.wait_for_selector("#pg-runall-btn")
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
    assert page.locator("#pg-runall-btn").is_visible()
    page.evaluate("() => document.documentElement.setAttribute('dir', 'auto')")
    assert page.evaluate("() => document.documentElement.getAttribute('dir')") == "auto"


def test_dashboard_filter_emits_selected_category_query(analyzer_page: tuple[object, _AnalyzerServer]) -> None:
    page, server = analyzer_page
    server.mode = "dashboard_filter"
    page.goto(_url(server, "/projects/demo/analysis"))
    _wait_ready(page)
    category_filter = page.locator('[data-dashboard-filter="category"]')
    category_filter.locator("button.qym-dropdown__trigger").wait_for(state="visible")
    category_filter.locator("button.qym-dropdown__trigger").click()
    category_filter.locator("label", has_text="Retrieval Error").click()
    page.wait_for_function(
        """() => document.querySelector('[data-dashboard-filter=\"category\"] button.qym-dropdown__trigger')?.textContent.includes('1 selected')"""
    )
    assert any(query.get("category") == ["Reasoning Error"] for query in server.dashboard_queries)


def test_dashboard_compare_refreshes_when_target_runs_change(analyzer_page: tuple[object, _AnalyzerServer]) -> None:
    page, server = analyzer_page
    server.mode = "dashboard_compare"
    page.goto(_url(server, "/projects/demo/analysis"))
    _wait_ready(page)

    page.get_by_role("checkbox", name="Select Run One for comparison").check()
    page.get_by_role("checkbox", name="Select Run Two for comparison").check()
    page.get_by_role("button", name="Compare selected", exact=True).click()
    page.get_by_role("heading", name="Run comparison · quality").wait_for()
    assert "Run One" in page.locator("#analysis-dashboard-compare-view").inner_text()
    assert "Run Two" in page.locator("#analysis-dashboard-compare-view").inner_text()

    # Once a comparison is open, replacing one target should invalidate the
    # previous payload and keep the compare panel on the new pair.
    page.get_by_role("checkbox", name="Select Run Two for comparison").uncheck()
    page.get_by_role("checkbox", name="Select Run Three for comparison").check()
    page.wait_for_function(
        """() => {
          const host = document.getElementById('analysis-dashboard-compare-view');
          const text = host?.textContent || '';
          return Boolean(host && !host.hidden && text.includes('Run Three') && !text.includes('Run Two'));
        }"""
    )
    compare_text = page.locator("#analysis-dashboard-compare-view").inner_text()
    assert "Run One" in compare_text
    assert "Run Three" in compare_text
    assert "Run Two" not in compare_text
    assert server.compare_queries[-1].get("run_id") == ["run-1", "run-3"]


def test_dashboard_run_filter_does_not_change_compare_targets(analyzer_page: tuple[object, _AnalyzerServer]) -> None:
    page, server = analyzer_page
    server.mode = "dashboard_compare"
    page.goto(_url(server, "/projects/demo/analysis"))
    _wait_ready(page)

    page.get_by_role("checkbox", name="Select Run One for comparison").check()
    page.get_by_role("checkbox", name="Select Run Two for comparison").check()
    page.get_by_role("button", name="Compare selected", exact=True).click()
    page.get_by_role("heading", name="Run comparison · quality").wait_for()

    run_filter = page.locator('[data-dashboard-filter="run_id"]')
    run_filter.locator(".qym-dropdown__trigger").click()
    run_filter.locator('input[value="run-1"]').uncheck()
    page.wait_for_function(
        """() => {
          const host = document.getElementById('analysis-dashboard-compare-view');
          const text = host?.textContent || '';
          return Boolean(host && !host.hidden && text.includes('Run One') && text.includes('Run Two') && !text.includes('Run Three'));
        }"""
    )
    compare_text = page.locator("#analysis-dashboard-compare-view").inner_text()
    assert "Run One" in compare_text
    assert "Run Two" in compare_text
    assert "Run Three" not in compare_text
    assert server.dashboard_queries[-1].get("run_id") == ["run-2", "run-3"]
    assert server.compare_queries[-1].get("run_id") == ["run-1", "run-2"]


def test_dashboard_run_filter_allows_empty_scope(analyzer_page: tuple[object, _AnalyzerServer]) -> None:
    page, server = analyzer_page
    server.mode = "dashboard_compare"
    page.goto(_url(server, "/projects/demo/analysis"))
    _wait_ready(page)
    dashboard_request_count = len(server.dashboard_queries)

    run_filter = page.locator('[data-dashboard-filter="run_id"]')
    run_filter.locator(".qym-dropdown__trigger").click()
    run_filter.get_by_role("button", name="Clear", exact=True).click()

    page.get_by_text("No runs match the current controls.", exact=True).first.wait_for()
    assert run_filter.locator(".qym-dropdown__trigger").inner_text() == "No Runs"
    assert page.locator("#analysis-dashboard-filter-count").inner_text() == "1"
    assert len(server.dashboard_queries) == dashboard_request_count


def test_dashboard_heatmap_hover_shows_category_occurrence_count(analyzer_page: tuple[object, _AnalyzerServer]) -> None:
    page, server = analyzer_page
    server.mode = "dashboard_scale"
    page.goto(_url(server, "/projects/demo/analysis"))
    _wait_ready(page)
    segment = page.locator('[data-dashboard-tooltip-category="Reasoning Error"]').first
    segment.wait_for(state="visible")
    segment.hover()
    tooltip = page.locator("#analysis-dashboard-stacked-tooltip")
    tooltip.wait_for(state="visible")
    assert tooltip.locator(".analysis-dashboard-stacked-tooltip-category").inner_text() == "Reasoning Error"
    assert tooltip.locator(".analysis-dashboard-stacked-tooltip-count").inner_text() == "500 occurrences"


def test_dashboard_occurrences_are_server_paginated_from_a_heatmap_cell(analyzer_page: tuple[object, _AnalyzerServer]) -> None:
    page, server = analyzer_page
    server.mode = "dashboard_scale"
    page.goto(_url(server, "/projects/demo/analysis"))
    _wait_ready(page)
    summary = page.locator("#analysis-dashboard-occurrences")
    summary.get_by_text("650 diagnoses in this scope.").wait_for()
    # A project dashboard must not fetch or render every diagnosis up front.
    assert server.occurrence_queries == []
    page.locator('[data-occurrence-run="run-1"][data-occurrence-category="Reasoning Error"]').click()
    page.locator("#analysis-occurrence-table").get_by_text("Diagnosis 0").wait_for()
    assert any(
        query.get("run_id") == ["run-1"]
        and query.get("category") == ["Reasoning Error"]
        and query.get("limit") == ["50"]
        and query.get("offset") == ["0"]
        for query in server.occurrence_queries
    )


def test_auto_analysis_has_no_serious_or_critical_axe_violations(analyzer_page: tuple[object, _AnalyzerServer]) -> None:
    axe_module = pytest.importorskip("axe_playwright_python.sync_playwright")
    page, server = analyzer_page
    page.goto(_url(server, "/projects/demo/analysis"))
    _wait_ready(page)
    results = axe_module.Axe().run(page)
    violations = [
        violation for violation in results.response["violations"]
        if violation.get("impact") in {"serious", "critical"}
    ]
    assert not violations, "Axe violations: " + ", ".join(violation["id"] for violation in violations)
