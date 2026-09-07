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
from typing import Any, Iterator, Optional
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
        "default_categories": ["Reasoning Error", "Pending Category"],
        "category_details_map": {},
        "category_taxonomy": {},
        "category_examples": {
            "Reasoning Error": [
                {
                    "item_id": "approved-item",
                    "metric_name": "quality",
                    "run_name": "Approved run",
                    "input": {"question": "demo"},
                    "expected": {"answer": "expected"},
                    "output": {"answer": "actual"},
                }
            ],
            "Pending Category": [],
        },
        "category_example_counts": {"Reasoning Error": 1, "Pending Category": 0},
        "existing_details": [],
        "max_root_cause_categories": 3,
        "can_manage_analysis_rules": True,
    }


def _analysis_rule_versions(*, populated: bool = False) -> dict[str, Any]:
    if not populated:
        return {
            "versions": [],
            "production_version_id": None,
            "can_delete": True,
            "can_activate": True,
            "can_restore": False,
        }
    return {
        "versions": [
            {
                "id": "version-3",
                "version": 3,
                "status": "published",
                "is_active": True,
                "is_deleted": False,
                "created_at": "2026-08-10T08:00:00+00:00",
                "updated_at": "2026-08-11T08:30:00+00:00",
                "created_by": {"display_name": "Release Gate"},
                "rules": [
                    {
                        "id": "rule-1",
                        "title": "Check evidence",
                        "instruction": "Use the available evidence.",
                        "inferred_from": "Approved example",
                        "explanation": "The evidence distinguishes the likely cause.",
                    },
                    {
                        "id": "rule-2",
                        "title": "Check completeness",
                        "instruction": "Verify that the response is complete.",
                        "inferred_from": "Project document",
                        "explanation": "Completeness is required for a reliable diagnosis.",
                    },
                ],
                "parent_version_id": None,
                "merge_parent_ids": [],
            },
        ],
        "production_version_id": "version-3",
        "can_delete": True,
        "can_activate": True,
        "can_restore": False,
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


_EXAMPLE_PICKER_ROWS = [
    {
        "id": 1,
        "item_id": "approved-a",
        "task": "Task A",
        "dataset": "Dataset A",
        "model": "model-a",
        "run_name": "Run A",
        "user_id": "user-a",
        "user": {"id": "user-a", "display_name": "Alice"},
        "confidence": 0.8,
        "source": "Corrected",
        "root_causes": ["Reasoning Error"],
        "detail": "Evidence gap",
        "source_characters": 100,
    },
    {
        "id": 2,
        "item_id": "approved-b",
        "task": "Task B",
        "dataset": "Dataset B",
        "model": "model-b",
        "run_name": "Run B",
        "user_id": "user-b",
        "user": {"id": "user-b", "display_name": "Bob"},
        "confidence": 0.9,
        "source": "AI",
        "root_causes": ["Incomplete Answer"],
        "detail": "Missing evidence",
        "source_characters": 120,
    },
]


def _analysis_examples_payload(body: dict[str, Any]) -> dict[str, Any]:
    dimensions = {
        "task": "tasks",
        "dataset": "datasets",
        "model": "models",
        "run_name": "run_names",
    }

    def matches(row: dict[str, Any], skip: Optional[str] = None) -> bool:
        for key in dimensions:
            if key == skip:
                continue
            values = [str(value) for value in (body.get(key) or [])]
            if values and str(row[key]) not in values:
                return False
        user_values = [str(value) for value in (body.get("user_id") or [])]
        if skip != "user_id" and user_values and row["user_id"] not in user_values:
            return False
        return True

    matching = [row for row in _EXAMPLE_PICKER_ROWS if matches(row)]
    selected_ids = {int(value) for value in (body.get("selected_ids") or [])}
    if body.get("selected_only"):
        matching = [row for row in matching if row["id"] in selected_ids]
    page = max(1, int(body.get("page") or 1))
    page_size = max(1, int(body.get("page_size") or 20))

    facets: dict[str, Any] = {}
    for dimension, facet_key in dimensions.items():
        facets[facet_key] = sorted({str(row[dimension]) for row in _EXAMPLE_PICKER_ROWS if matches(row, dimension)})
    facets["users"] = [
        row["user"]
        for row in _EXAMPLE_PICKER_ROWS
        if matches(row, "user_id")
    ]
    first = (page - 1) * page_size
    rows = matching[first : first + page_size]
    examples = [
        {
            **row,
            "corrected_by": row["user"],
            "reviewed_by": None,
        }
        for row in rows
    ]
    return {
        "examples": examples,
        "total": len(matching),
        "page": page,
        "page_size": page_size,
        "page_count": (len(matching) + page_size - 1) // page_size if matching else 0,
        "matching_ids": [row["id"] for row in matching],
        "selected_ids": sorted(selected_ids.intersection(row["id"] for row in _EXAMPLE_PICKER_ROWS)),
        "selected_count": len(selected_ids.intersection(row["id"] for row in _EXAMPLE_PICKER_ROWS)),
        "selected_characters": sum(row["source_characters"] for row in _EXAMPLE_PICKER_ROWS if row["id"] in selected_ids),
        "facets": facets,
        "limits": {"approved_examples_prompt_characters": 256000, "writer_prompt_characters": 256000},
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
            self._json(_analysis_rule_versions(populated=self.server.mode == "rules_initial"))
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
        # Shell/auth helpers may probe endpoints. A stable empty JSON object is
        # preferable to a failed resource request that obscures page errors.
        self._json({})

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length") or 0)
        body: dict[str, Any] = {}
        if content_length:
            try:
                body = json.loads(self.rfile.read(content_length))
            except (TypeError, ValueError):
                body = {}
        path = urlparse(self.path).path
        if path.endswith("/analysis-examples"):
            self.server.example_queries.append(body)
            self._json(_analysis_examples_payload(body))
            return
        if path.endswith("/analyze-preview"):
            self._json(
                {
                    "messages": [
                        {"role": "system", "content": "Analyze the selected metric."},
                        {"role": "user", "content": "Release-gate preview item."},
                    ]
                }
            )
            return
        self._json({})


class _AnalyzerServer(ThreadingHTTPServer):
    mode: str = "ok"
    run_requests: int = 0
    dashboard_queries: list[dict[str, list[str]]]
    occurrence_queries: list[dict[str, list[str]]]
    compare_queries: list[dict[str, list[str]]]
    example_queries: list[dict[str, Any]]

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.dashboard_queries = []
        self.occurrence_queries = []
        self.compare_queries = []
        self.example_queries = []


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
    analyzer_server.example_queries = []
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
    assert tabs.evaluate_all("tabs => tabs.map(tab => tab.dataset.analysisView)") == ["run", "categories", "rules", "documents"]
    assert page.locator("#analysis-run-tab").is_visible()
    assert page.locator("#analysis-dashboard-tab").count() == 1
    assert page.locator("#analysis-dashboard-tab").is_hidden()
    assert page.locator("#analysis-dashboard-view").count() == 1
    assert page.locator("#analysis-dashboard-view").is_hidden()


def test_project_rules_render_selected_version_on_initial_load(analyzer_page: tuple[object, _AnalyzerServer]) -> None:
    page, server = analyzer_page
    server.mode = "rules_initial"
    page.goto(_url(server, "/projects/demo/analysis?scope=rules"))
    _wait_ready(page)

    page.locator("#analysis-rules-view").wait_for(state="visible")
    assert page.locator("#pg-rule-editor-title").inner_text() == "Rules in v3"
    assert "2 rules" in page.locator("#pg-rule-count").inner_text()
    assert "Created at" in page.locator("#pg-rule-version-meta").inner_text()
    assert "Updated at" in page.locator("#pg-rule-version-meta").inner_text()
    assert "Release Gate" in page.locator("#pg-rule-version-meta").inner_text()
    assert page.locator("#pg-context-status").inner_text() == "Opened v3 (read-only)."
    assert page.locator("#pg-rule-list .pg-rule-item").count() == 2
    assert "The evidence distinguishes the likely cause." in (
        page.locator("#pg-rule-list").text_content() or ""
    )
    rule_search = page.locator("#pg-rule-search")
    assert rule_search.is_visible()
    add_examples = page.locator("#pg-add-examples")
    assert add_examples.is_visible()
    assert add_examples.get_attribute("class") == "pg-example-source-control"
    assert add_examples.evaluate(
        "el => { const style = getComputedStyle(el); return style.borderWidth === '0px' && style.borderRadius === '0px' && style.padding === '0px' && style.backgroundColor === 'rgba(0, 0, 0, 0)'; }"
    )
    rule_search.fill("completeness")
    page.wait_for_function(
        "() => document.querySelectorAll('#pg-rule-list .pg-rule-item').length === 1"
    )
    assert "Check completeness" in page.locator("#pg-rule-list").inner_text()
    page.locator("#pg-add-examples").click()
    page.locator("[data-example-filter-panel-trigger]").click()
    rule_selectors = page.locator(".pg-example-picker-dimension-filters .qym-review-selector")
    assert rule_selectors.count() == 5
    assert rule_selectors.evaluate_all(
        "wrappers => wrappers.every(wrapper => wrapper.getBoundingClientRect().width >= 240)"
    )
    page.wait_for_function(
        "() => document.querySelectorAll('select[data-example-filter-select] option').length >= 10"
    )
    assert page.locator(".pg-example-picker-dimension-filters input[type='checkbox']").count() == 0
    assert "Multi-select supported" not in page.locator(".pg-example-picker-filter-panel-menu").inner_text()

    task_filter = page.locator("[data-example-filter='task']")
    task_filter.locator(".multi-select-btn").click()
    assert task_filter.locator(".multi-select-option[data-value]:not([data-value=''])").count() == 2
    task_filter.locator(".multi-select-option[data-value='Task A']").click()
    page.wait_for_function(
        "() => document.querySelector('[data-example-filter-key=task]')?.value === 'Task A'"
    )
    page.wait_for_function(
        "() => document.querySelectorAll('.pg-example-picker-row').length === 1"
    )
    assert server.example_queries[-1]["task"] == ["Task A"]

    # The active task filter keeps both task options available to its own
    # selector, while the dataset selector is narrowed by that task filter.
    task_filter.locator(".multi-select-btn").click()
    assert task_filter.locator(".multi-select-option[data-value]:not([data-value=''])").count() == 2
    dataset_filter = page.locator("[data-example-filter='dataset']")
    assert dataset_filter.locator(".multi-select-option[data-value]:not([data-value=''])").count() == 1


def test_project_diagnosis_catalog_restores_local_tools(analyzer_page: tuple[object, _AnalyzerServer]) -> None:
    page, server = analyzer_page
    page.goto(_url(server, "/projects/demo/analysis?scope=categories"))
    _wait_ready(page)

    page.locator("#analysis-diagnosis-view").wait_for(state="visible")
    diagnosis_tab = page.locator("#analysis-diagnosis-tab")
    assert diagnosis_tab.is_enabled()
    assert page.locator("#analysis-category-count").inner_text() == "1"
    approved_nav = page.locator("#analysis-diagnosis-view .pg-category-nav-item")
    assert approved_nav.count() == 1
    assert approved_nav.first.inner_text().startswith("Reasoning Error")
    assert "Pending Category" not in approved_nav.all_inner_texts()
    category = page.locator("#analysis-diagnosis-view .pg-category-nav-item", has_text="Reasoning Error")
    assert category.is_visible()
    category_panel = page.locator("#analysis-diagnosis-view .pg-category-group[data-cat='Reasoning Error']")
    assert category_panel.is_visible()
    assert category_panel.locator("[data-taxonomy-field='description']").count() == 1
    assert category_panel.locator("[data-taxonomy-field='when_to_use']").count() == 1
    page.locator("#analysis-save-category-catalog").click()
    assert page.locator("#analysis-category-save-status").inner_text() == "Taxonomy required"
    category_panel.locator("[data-category-tab='details']").click()
    detail_selector = category_panel.locator(".pg-detail-review-selector")
    assert detail_selector.is_visible()
    assert detail_selector.evaluate("wrapper => wrapper.getBoundingClientRect().width >= 240")
    detail_selector.locator(".multi-select-btn").click()
    detail_selector.locator(".multi-select-option[data-value='without_examples']").click()
    assert category_panel.locator("[data-detail-filter]").input_value() == "without_examples"

    category_search = page.locator("#analysis-category-search")
    category_search.fill("not present")
    page.wait_for_function(
        "() => document.querySelectorAll('#analysis-diagnosis-view .pg-category-nav-item:not([hidden])').length === 0"
    )
    category_search.fill("")
    page.wait_for_function(
        "() => document.querySelectorAll('#analysis-diagnosis-view .pg-category-nav-item:not([hidden])').length === 1"
    )


def test_run_route_targets_direction_copy_and_command(analyzer_page: tuple[object, _AnalyzerServer]) -> None:
    page, server = analyzer_page
    page.goto(_url(server, "/projects/demo/runs/run-1/analyzer"))
    _wait_ready(page)
    assert page.locator("#analysis-tabs [role=tab]:visible").count() == 4
    page.wait_for_selector("#analyzer-host .pg-item-card")
    target_card = page.locator("#analyzer-host .pg-item-card").first
    assert target_card.locator(".pg-item-target-row").count() == 2
    target_text = target_card.inner_text()
    assert "quality" in target_text
    assert "latency" in target_text
    assert "2 metric targets" in target_text
    assert page.locator("#pg-max-score-direction-note").inner_text().lower() == "(applies only to higher-is-better metrics)"
    footer = page.locator("#analyzer-host .playground-footer.analysis-run-footer")
    footer.wait_for(state="visible")
    assert footer.evaluate("el => getComputedStyle(el).position") == "relative"
    assert page.locator("#pg-runall-btn").inner_text() == "Analyze 1 item"
    connection_trigger = page.locator(".pg-connection-selector .multi-select-btn")
    connection_trigger.click()
    connection_menu = page.locator(".pg-connection-selector .multi-select-dropdown")
    assert connection_menu.is_visible()
    assert connection_menu.locator("[role=option][aria-selected=true]").count() == 1
    page.keyboard.press("Escape")
    assert connection_menu.is_hidden()
    assert connection_trigger.evaluate("el => document.activeElement === el")


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
    first = page.locator("#analysis-run-tab")
    first.focus()
    page.keyboard.press("End")
    assert page.locator("#analysis-documents-tab").evaluate("el => document.activeElement === el")


def test_dashboard_scope_is_redirected_to_analyze_run_without_dashboard_requests(
    analyzer_page: tuple[object, _AnalyzerServer],
) -> None:
    page, server = analyzer_page
    page.goto(_url(server, "/projects/demo/analysis?scope=dashboard"))
    _wait_ready(page)

    assert "scope=run" in page.url
    assert page.locator("#analysis-dashboard-tab").count() == 1
    assert page.locator("#analysis-dashboard-tab").is_hidden()
    assert page.locator("#analysis-dashboard-view").count() == 1
    assert page.locator("#analysis-dashboard-view").is_hidden()
    assert page.locator("#analysis-run-tab").get_attribute("aria-selected") == "true"
    assert server.dashboard_queries == []
    assert server.occurrence_queries == []
    assert server.compare_queries == []


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
