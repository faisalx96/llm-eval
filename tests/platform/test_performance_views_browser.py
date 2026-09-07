"""Full-versus-compact UX contracts on the shipped Run and Compare pages."""

from __future__ import annotations

import copy
import json
import mimetypes
import re
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from qym_platform.services.run_payloads import compact_row

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "packages/platform/qym_platform/_static/dashboard"


@pytest.fixture(scope="module")
def browser():
    api = pytest.importorskip("playwright.sync_api")
    with api.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


def payload(run_id="run-1", count=260, samples=1):
    rows = []
    for i in range(count):
        output = f"Answer {i}\nneedle-{i} " + ("a" * 400)
        if i == count - 1:
            output = json.dumps({"late_only_field": "last", "answer": output})
        if run_id == "run-2" and i % 2:
            output += " changed"
        row = {
            "item_id": f"item-{i}",
            "compare_item_id": f"aligned-{i}",
            "index": i,
            "input": f"Question {i}",
            "input_full": f"Question {i}",
            "expected": f"Expected {i}",
            "expected_full": f"Expected {i}",
            "output": output,
            "output_full": output,
            "metric_values": [i % 2, i],
            "status": "error" if i == 23 else "completed",
            "error": "timeout: upstream" if i == 23 else "",
            "latency_ms": i * 10,
            "metric_meta": {
                "accuracy": {
                    "explanation": "Judge explanation " + str(i),
                    "modified": i == 7,
                },
                "count": {},
            },
            "item_metadata": {
                "complexity": "hard" if i % 3 else "easy",
                "domain": "finance",
                "root_cause": "Reasoning Error" if i % 2 == 0 else "",
            },
            "retry_count": i % 3,
            "review_correction_status": "approved" if i == 5 else "",
        }
        if samples > 1:
            row["pass_scores"] = {"accuracy": [0, 1, i % 2], "count": [i, i + 1, i + 2]}
            row["pass_metric_meta"] = {
                "accuracy": [
                    {"explanation": f"pass-{p} judge {i}"} for p in range(1, 4)
                ]
            }
            row["pass_attempts"] = [
                {
                    "pass_number": p,
                    "status": "completed",
                    "output": f"pass-{p} output {i}",
                    "latency_ms": i + p,
                    "retry_count": p - 1,
                }
                for p in range(1, 4)
            ]
        rows.append(row)
    return {
        "run": {
            "run_id": run_id,
            "file_path": run_id,
            "run_name": run_id,
            "model_name": run_id,
            "task_name": "task",
            "dataset_name": "dataset",
            "metric_names": ["accuracy", "count"],
            "status": "COMPLETED",
            "samples": samples,
            "can_edit": True,
            "compare_alignment_status": "aligned",
            "project": {"slug": "demo", "name": "Demo"},
            "config": {},
            "metadata": {},
            "owner": {"id": "user-1", "display_name": "User"},
        },
        "snapshot": {
            "rows": rows,
            "stats": {"total": count, "completed": count},
            "metric_names": ["accuracy", "count"],
            "metric_specs": {
                "accuracy": {"score_type": "boolean", "direction": "maximize"},
                "count": {"score_type": "number", "direction": "maximize"},
            },
        },
    }


class ViewFixture:
    def __init__(self, browser, kind, *, compact=True, samples=1, count=260):
        self.kind = kind
        self.count = count
        self.compact = compact
        self.data = {rid: payload(rid, count, samples) for rid in ("run-1", "run-2")}
        self.requests = []
        self.fail_details = False
        self.api_client = None
        self.context = browser.new_context(
            viewport={"width": 1440, "height": 1100}, reduced_motion="reduce"
        )
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.route("**/*", self.route)

    def route(self, route):
        request = route.request
        parsed = urlparse(request.url)
        pathname = parsed.path
        query = parse_qs(parsed.query)
        if "/static/" in pathname:
            file = STATIC / pathname.split("/static/", 1)[1]
            if file.is_file():
                route.fulfill(
                    path=str(file),
                    content_type=mimetypes.guess_type(file.name)[0]
                    or "application/octet-stream",
                )
            else:
                route.fulfill(status=404, body="")
            return
        if pathname == "/v1/me":
            route.fulfill(
                json={
                    "id": "user-1",
                    "display_name": "User",
                    "email": "user@example.test",
                    "role": "ADMIN",
                    "projects": [
                        {"id": "p", "slug": "demo", "name": "Demo", "role": "ADMIN"}
                    ],
                }
            )
            return
        if "analysis-category-catalog" in pathname:
            route.fulfill(
                json={
                    "categories": ["Reasoning Error"],
                    "category_entries": [],
                    "category_details_map": {},
                    "category_taxonomy": {},
                    "can_manage": False,
                }
            )
            return
        if self.api_client is not None and (
            pathname == "/api/compare" or pathname.startswith("/api/runs/")
        ):
            body = request.post_data_json if request.method == "POST" else None
            params = [(key, value) for key, values in query.items() for value in values]
            if request.method == "GET" and "view" in query:
                params = [(key, value) for key, value in params if key != "view"] + [
                    ("view", "compact" if self.compact else "full")
                ]
            if request.method == "POST":
                response = self.api_client.post(pathname, json=body)
            else:
                response = self.api_client.get(pathname, params=params)
            run_id = (
                pathname.split("/")[3]
                if pathname.startswith("/api/runs/")
                else "compare"
            )
            verb = (
                "details"
                if pathname.endswith("/items/details")
                else (
                    "search"
                    if pathname.endswith("/items/search")
                    else "update" if pathname.endswith("update_metric") else "snapshot"
                )
            )
            self.requests.append((run_id, verb, body or query))
            if response.status_code >= 400:
                self.errors.append(
                    f"API {pathname}: {response.status_code} {response.text}"
                )
            route.fulfill(
                status=response.status_code,
                body=response.content,
                content_type="application/json",
            )
            return
        if pathname == "/api/runs/update_metric":
            body = request.post_data_json
            row = self.data[body["file_path"]]["snapshot"]["rows"][body["row_index"]]
            index = ["accuracy", "count"].index(body["metric_name"])
            row["metric_values"][index] = float(body["new_score"])
            row["metric_meta"].setdefault(body["metric_name"], {})["modified"] = True
            route.fulfill(json={"ok": True, "row": row})
            return
        if pathname.startswith("/api/runs/"):
            parts = pathname.split("/")
            run_id = parts[3]
            data = self.data[run_id]
            if pathname.endswith("/items/details"):
                body = request.post_data_json
                self.requests.append((run_id, "details", body))
                if self.fail_details:
                    self.fail_details = False
                    route.fulfill(status=503, json={"error": "temporary failure"})
                    return
                rows = [
                    copy.deepcopy(row)
                    for row in data["snapshot"]["rows"]
                    if row["item_id"] in body["item_ids"]
                ]
                for row in rows:
                    row.pop("compare_item_id", None)
                    row["__details_loaded"] = True
                route.fulfill(json={"rows": rows})
                return
            if pathname.endswith("/items/search"):
                body = request.post_data_json
                self.requests.append((run_id, "search", body))
                matches = {}
                for condition in body["conditions"]:
                    ids = []
                    for row in data["snapshot"]["rows"]:
                        output = row["output_full"]
                        if body.get("pass_number"):
                            output = row["pass_attempts"][body["pass_number"] - 1][
                                "output"
                            ]
                        values = [
                            row["item_id"],
                            row["input_full"],
                            row["expected_full"],
                            output,
                        ]
                        if condition["field"] == "output":
                            values = values[-1:]
                        elif condition["field"] == "content":
                            values = values[1:]
                        if any(
                            condition["value"].lower() in value.lower()
                            for value in values
                        ):
                            ids.append(row["item_id"])
                    matches[condition["id"]] = ids
                route.fulfill(json={"matches": matches})
                return
            if pathname.endswith("/passes"):
                route.fulfill(
                    json={
                        "passes": [
                            {"pass_number": p, "status": "completed"}
                            for p in range(1, 4)
                        ]
                    }
                )
                return
            if pathname.endswith("/group-metrics"):
                route.fulfill(json={})
                return
            self.requests.append((run_id, "snapshot", query))
            route.fulfill(json=self.snapshot(run_id))
            return
        if pathname == "/api/compare":
            self.requests.append(("compare", "snapshot", query))
            route.fulfill(
                json={
                    "runs": [
                        self.snapshot(rid)
                        for rid in query.get("files", ["run-1", "run-2"])
                    ],
                    "compare_alignment_status": "aligned",
                }
            )
            return
        if pathname in ("/compare", "/run/run-1", "/projects/demo/runs/run-1"):
            source = (STATIC / (self.kind + ".html")).read_text()
            # Auth/shell are covered by their own browser suites; isolate page
            # behavior while retaining all production data/rendering scripts.
            source = re.sub(
                r'<script src="(?:\./|/)static/(?:auth|shell|playground)\.js[^\"]*"></script>',
                "",
                source,
            )
            init = (
                "      loadComparisonData();"
                if self.kind == "compare"
                else "      loadRunData();"
            )
            helpers = "openItemComparisonModal," if self.kind == "compare" else ""
            source = source.replace(
                init,
                "window.__viewTest = {state, renderItems, getFilteredItems, "
                + helpers
                + "};\n"
                + init,
            )
            route.fulfill(body=source, content_type="text/html")
            return
        route.fulfill(json={})

    def snapshot(self, run_id):
        data = copy.deepcopy(self.data[run_id])
        if self.compact:
            data["snapshot"]["rows"] = [
                compact_row(row) for row in data["snapshot"]["rows"]
            ]
            data["snapshot"]["detail_mode"] = "lazy"
        return data

    def goto(self, suffix=""):
        url = (
            "/compare?runs=run-1&runs=run-2" if self.kind == "compare" else "/run/run-1"
        )
        self.page.goto("http://qym.test" + url + suffix)
        self.ready()

    def ready(self):
        self.page.wait_for_function(
            f"() => Boolean(window.__viewTest && document.querySelector('#filter-count')?.textContent.includes('{self.count}') && !document.querySelector('#items-grid')?.hasAttribute('aria-busy'))"
        )

    def settled(self):
        self.page.wait_for_function(
            "() => !document.querySelector('#items-grid')?.hasAttribute('aria-busy')"
        )

    def state_result(self):
        return self.page.evaluate(
            """() => ({ids: __viewTest.getFilteredItems().map(item => item.itemId || item.row.item_id), count: document.querySelector('#filter-count').textContent, stats: __viewTest.state.comparisonStats || null})"""
        )

    def close(self):
        self.context.close()
        assert not self.errors, "Browser errors: " + "; ".join(self.errors)


@contextmanager
def source_run_api(count=61, seed_issues=False):
    """Real source rows, repeats and score mutations behind the shipped pages."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from qym_platform.api.runs import router
    from qym_platform.auth import Principal, require_ui_principal
    from qym_platform.db.base import Base
    from qym_platform.db.models import (
        Project,
        Run,
        RunItem,
        RunItemAttempt,
        RunItemPassScore,
        RunItemScore,
        RunMetricSpec,
        RunWorkflowStatus,
        User,
        UserRole,
    )
    from qym_platform.deps import get_db

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        user = User(
            id="user-1",
            email="source@example.test",
            display_name="User",
            role=UserRole.ADMIN,
        )
        db.add(user)
        db.flush()
        db.add(
            Project(id="project", slug="demo", name="Demo", created_by_user_id=user.id)
        )
        db.flush()
        for run_id in ("run-1", "run-2"):
            run = Run(
                id=run_id,
                project_id="project",
                owner_user_id=user.id,
                created_by_user_id=user.id,
                task="task",
                dataset="dataset",
                model=run_id,
                metrics=["accuracy", "count"],
                status=RunWorkflowStatus.COMPLETED,
                samples=3,
                run_metadata={"last_completed_pass": 3},
                run_config={"run_name": run_id},
            )
            db.add(run)
            db.flush()
            for position, metric in enumerate(run.metrics):
                db.add(
                    RunMetricSpec(
                        run_id=run_id,
                        metric_name=metric,
                        position=position,
                        score_type="boolean" if metric == "accuracy" else "number",
                    )
                )
            for row in payload(run_id, count, 3)["snapshot"]["rows"]:
                if seed_issues and row["index"] == 0:
                    row["item_metadata"].update(
                        root_causes=["Aggregate only"],
                        root_cause_issues=[
                            {
                                "category": "Aggregate only",
                                "subcategory": "Stale summary",
                                "finding": "Aggregate diagnosis must not appear in a pass",
                            }
                        ],
                        root_cause_reason="Aggregate category explanation",
                    )
                db.add(
                    RunItem(
                        run_id=run_id,
                        item_id=row["item_id"],
                        index=row["index"],
                        input=row["input"],
                        expected=row["expected"],
                        output=row["output"],
                        error=row["error"] or None,
                        latency_ms=row["latency_ms"],
                        retry_count=row["retry_count"],
                        item_metadata=row["item_metadata"],
                    )
                )
                for metric_index, metric in enumerate(run.metrics):
                    value = row["metric_values"][metric_index]
                    db.add(
                        RunItemScore(
                            run_id=run_id,
                            item_id=row["item_id"],
                            metric_name=metric,
                            score_numeric=value,
                            score_raw=value,
                            explanation=row["metric_meta"]
                            .get(metric, {})
                            .get("explanation"),
                            meta={},
                        )
                    )
                    for pass_index, value in enumerate(row["pass_scores"][metric]):
                        db.add(
                            RunItemPassScore(
                                run_id=run_id,
                                item_id=row["item_id"],
                                metric_name=metric,
                                pass_number=pass_index + 1,
                                score_numeric=value,
                                explanation=f"pass-{pass_index + 1} judge {row['index']}",
                                meta={},
                            )
                        )
                for attempt in row["pass_attempts"]:
                    output = attempt["output"]
                    if row["index"] == count - 1 and attempt["pass_number"] == 2:
                        output = {"late_only_field": "last", "answer": output}
                    db.add(
                        RunItemAttempt(
                            run_id=run_id,
                            item_id=row["item_id"],
                            pass_number=attempt["pass_number"],
                            attempt_number=1,
                            is_last_attempt=True,
                            status="completed",
                            output=output,
                            latency_ms=attempt["latency_ms"],
                        )
                    )
        db.commit()
        principal = Principal(user=user, auth_type="local_password")
        db.expunge(user)
    app = FastAPI()
    app.include_router(router)

    def session():
        with Session(engine, autoflush=False) as db:
            yield db

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[require_ui_principal] = lambda: principal
    try:
        with TestClient(app) as client:
            if seed_issues:
                for pass_number in (1, 2, 3):
                    issues = [
                        {
                            "category": "Reasoning Error",
                            "subcategory": "First mechanism",
                            "finding": f"pass-{pass_number} first finding {count - 1}",
                        }
                    ]
                    if pass_number == 2:
                        issues.append(
                            {
                                "category": "Reasoning Error",
                                "subcategory": "Second mechanism",
                                "finding": f"pass-2 second finding {count - 1}",
                            }
                        )
                    response = client.post(
                        "/api/runs/update_root_cause",
                        json={
                            "run_id": "run-1",
                            "item_id": f"item-{count - 1}",
                            "metric_name": "accuracy",
                            "pass_number": pass_number,
                            "root_cause_issues": issues,
                        },
                    )
                    assert response.status_code == 200, response.text
            yield client
    finally:
        engine.dispose()


@pytest.mark.parametrize("kind", ["run", "compare"])
def test_source_api_preserves_repeated_offpage_details_search_edit_and_csv(
    browser, monkeypatch, tmp_path, kind
):
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite://")
    fixtures = []
    try:
        with source_run_api() as client:
            for compact in (False, True):
                fixture = ViewFixture(
                    browser, kind, compact=compact, count=61, samples=3
                )
                fixtures.append(fixture)
                fixture.api_client = client
                fixture.goto("?pass=2&item=item-60" if kind == "run" else "")
                page = fixture.page
                if kind == "compare":
                    page.evaluate("""() => {
                      const item = __viewTest.getFilteredItems().find(item => item.rowData.some(row => row?.item_id === 'item-60'));
                      __viewTest.openItemComparisonModal(item.itemId);
                    }""")
                    page.wait_for_function(
                        "document.querySelector('#item-comparison-modal-body').textContent.includes('pass-2 output 60')"
                    )
                    assert (
                        "pass-3 output 60"
                        in page.locator("#item-comparison-modal-body").inner_text()
                    )
                    page.locator("#item-comparison-modal-close").click()
                else:
                    assert (
                        page.locator(
                            '#pagination [aria-label="Page number"]'
                        ).input_value()
                        == "4"
                    )
                page.locator("#items-search").fill("pass-2 output 60")
                page.wait_for_function(
                    "__viewTest.state.searchQuery === 'pass-2 output 60'"
                )
                fixture.settled()
                assert len(fixture.state_result()["ids"]) == 1
                page.locator("#export-filtered-btn").click()
                page.locator("#export-modal-overlay.open").wait_for()
                assert (
                    "late_only_field"
                    in page.locator("#export-modal-overlay").inner_text()
                )
                with page.expect_download() as download:
                    page.locator("#export-modal-confirm").click()
                target = tmp_path / f"source-{kind}-{compact}.csv"
                download.value.save_as(target)
                assert "pass-2 output 60" in target.read_text()
            assert (tmp_path / f"source-{kind}-False.csv").read_bytes() == (
                tmp_path / f"source-{kind}-True.csv"
            ).read_bytes()
            assert fixtures[0].state_result() == fixtures[1].state_result()
            fixture = fixtures[1]
            page = fixture.page
            # Editing must reach the real pass score and re-reduced run score,
            # then keep its body and logical identity after the response patch.
            page.locator("#items-grid .item-header-expand").first.click()
            page.locator("#items-grid .metric-edit-open").first.click()
            editor = page.locator("#items-grid .metric-edit-input:visible").first
            editor.fill("0.25")
            with page.expect_response("**/api/runs/update_metric") as edited:
                editor.press("Enter")
            assert edited.value.status == 200
            editor.wait_for(state="hidden")
            updated = client.get("/api/runs/run-1").json()["snapshot"]["rows"][60]
            assert 0.25 in updated["pass_scores"]["accuracy"]
            assert any(verb == "details" for _, verb, _ in fixture.requests)
            assert any(verb == "search" for _, verb, _ in fixture.requests)
            assert all(
                len(body["item_ids"]) <= 100
                for _, verb, body in fixture.requests
                if verb == "details"
            )
    finally:
        for fixture in fixtures:
            fixture.close()


@pytest.mark.parametrize("kind", ["run", "compare"])
def test_source_issue_records_keep_full_compact_pass_filter_export_and_edit_parity(
    browser, monkeypatch, tmp_path, kind
):
    monkeypatch.setenv("QYM_DATABASE_URL", "sqlite://")
    fixtures = []
    try:
        with source_run_api(seed_issues=True) as client:
            for compact in (False, True):
                fixture = ViewFixture(
                    browser, kind, compact=compact, count=61, samples=3
                )
                fixture.api_client = client
                fixtures.append(fixture)
                fixture.goto("?pass=2" if kind == "run" else "")
                page = fixture.page
                page.locator(
                    "#root-cause-section .rc-category-pill-count"
                ).first.wait_for(state="attached")
                assert page.locator(
                    "#root-cause-section .rc-category-pill-count"
                ).all_inner_texts() == ["2" if kind == "run" else "4"]
                assert (
                    "Aggregate only"
                    not in page.locator("#root-cause-section").inner_text()
                )
                if compact:
                    assert page.evaluate(
                        "(__viewTest.state.snapshot?.rows || __viewTest.state.runs[0].snapshot.rows)[60].__details_loaded === false"
                    )
                page.evaluate(
                    "__viewTest.state.rootCauseMetric='accuracy'; __viewTest.state.rootCauseFilter=['Reasoning Error']; __viewTest.renderItems()"
                )
                fixture.settled()
                assert len(fixture.state_result()["ids"]) == 1
                page.locator("#items-grid .item-header-expand").first.click()
                visible = page.locator("#items-grid").inner_text()
                assert "pass-2 first finding 60" in visible
                assert "pass-2 second finding 60" in visible
                assert "Aggregate diagnosis" not in visible
                if kind == "run":
                    assert "pass-1 first finding" not in visible
                    assert (
                        page.locator("#items-grid .metric-analysis-issue").count() == 2
                    )
                else:
                    assert "pass-1 first finding 60" in visible
                    assert "pass-3 first finding 60" in visible
                    assert page.locator("#items-grid .compare-issue").count() == 4
                page.locator("#export-filtered-btn").click()
                page.locator("#export-modal-overlay.open").wait_for()
                with page.expect_download() as download:
                    page.locator("#export-modal-confirm").click()
                target = tmp_path / f"issues-{kind}-{compact}.csv"
                download.value.save_as(target)
                assert "pass-2 first finding 60" in target.read_text()
                assert "pass-2 second finding 60" in target.read_text()
            assert (tmp_path / f"issues-{kind}-False.csv").read_bytes() == (
                tmp_path / f"issues-{kind}-True.csv"
            ).read_bytes()
            fixture = fixtures[1]
            page = fixture.page
            if kind == "run":
                trigger = page.locator(
                    '[data-metric-issues-item="item-60"][data-metric-name="accuracy"]'
                )
            else:
                run_index = page.evaluate(
                    "__viewTest.state.runs.findIndex(run => run.run.file_path === 'run-1::pass2')"
                )
                trigger = page.locator(
                    f'[data-rc-issues-run-idx="{run_index}"][data-rc-issues-metric="accuracy"]'
                )
            trigger.first.click()
            editor = page.get_by_role("dialog", name="Edit root-cause issues")
            fields = editor.locator('[data-issue-field="finding"]')
            assert fields.count() == 2
            fields.nth(1).fill("Reviewed second issue")
            with page.expect_response("**/api/runs/update_root_cause") as saved:
                editor.locator("[data-save-issues]").click()
            assert saved.value.status == 200
            editor.wait_for(state="hidden")
            fixture.settled()
            updated = client.get("/api/runs/run-1").json()["snapshot"]["rows"][60]
            analyses = updated["pass_metric_analyses"]["accuracy"]
            assert (
                analyses[1]["root_cause_issues"][1]["finding"]
                == "Reviewed second issue"
            )
            assert (
                analyses[1]["root_cause_issues"][0]["finding"]
                == "pass-2 first finding 60"
            )
            assert (
                analyses[0]["root_cause_issues"][0]["finding"]
                == "pass-1 first finding 60"
            )
            assert (
                analyses[2]["root_cause_issues"][0]["finding"]
                == "pass-3 first finding 60"
            )
            assert "Reviewed second issue" in page.locator("#items-grid").inner_text()
    finally:
        for fixture in fixtures:
            fixture.close()


@pytest.mark.parametrize("kind", ["run", "compare"])
def test_full_and_compact_keep_global_filters_pages_and_csv(browser, kind, tmp_path):
    fixtures = [ViewFixture(browser, kind, compact=value) for value in (False, True)]
    try:
        for fixture in fixtures:
            fixture.goto()
        assert fixtures[0].state_result() == fixtures[1].state_result()
        for fixture in fixtures:
            page = fixture.page
            page.locator('#pagination [aria-label="Last page"]').click()
            fixture.settled()
            assert (
                page.locator('#pagination [aria-label="Page number"]').input_value()
                == "13"
            )
            assert "259" in page.locator("#items-grid").inner_text()
            page.locator("#items-search").fill("needle-259")
            page.wait_for_function("__viewTest.state.searchQuery === 'needle-259'")
            fixture.settled()
            assert len(fixture.state_result()["ids"]) == 1
            page.locator("#export-filtered-btn").click()
            page.locator("#export-modal-overlay.open").wait_for()
            assert (
                "late_only_field" in page.locator("#export-modal-overlay").inner_text()
            )
            with page.expect_download() as download:
                page.locator("#export-modal-confirm").click()
            target = tmp_path / f"{kind}-{fixture.compact}.csv"
            download.value.save_as(target)
        assert (tmp_path / f"{kind}-False.csv").read_bytes() == (
            tmp_path / f"{kind}-True.csv"
        ).read_bytes()
        assert fixtures[0].state_result() == fixtures[1].state_result()
        requests = fixtures[1].requests
        assert requests[0][2].get("view") == ["compact"]
        assert all(
            len(body["item_ids"]) <= 100
            for _, verb, body in requests
            if verb == "details"
        )
        assert any(verb == "search" for _, verb, _ in requests)
    finally:
        for fixture in fixtures:
            fixture.close()


@pytest.mark.parametrize("kind", ["run", "compare"])
def test_mixed_boolean_filters_and_different_outputs_match_full_history(browser, kind):
    fixtures = [ViewFixture(browser, kind, compact=value) for value in (False, True)]
    try:
        for fixture in fixtures:
            fixture.goto()
            fixture.page.evaluate("""() => {
                const v=__viewTest;
                v.state.filterRoot={op:'or',children:[{field:'output',oper:'contains',value:'needle-259'},
                  {op:'and',children:[{field:'output',oper:'notcontains',value:'needle-1'},
                    {field:'output',oper:'contains',value:'needle-25'}]}]};
                v.renderItems();
            }""")
            fixture.settled()
        assert fixtures[0].state_result() == fixtures[1].state_result()
        assert len(fixtures[1].state_result()["ids"]) == 11
        if kind == "compare":
            for fixture in fixtures:
                fixture.page.evaluate(
                    "__viewTest.state.filterRoot={op:'and',children:[]}; __viewTest.state.itemFilter='different'; __viewTest.renderItems()"
                )
                fixture.settled()
            assert fixtures[0].state_result() == fixtures[1].state_result()
            assert len(fixtures[1].state_result()["ids"]) == 130
    finally:
        for fixture in fixtures:
            fixture.close()


def test_repeat_pass_search_hydration_and_deep_link(browser):
    fixture = ViewFixture(browser, "run", samples=3)
    try:
        fixture.goto("?pass=2&item=item-259")
        assert (
            fixture.page.locator('#pagination [aria-label="Page number"]').input_value()
            == "13"
        )
        fixture.page.locator("#items-search").fill("pass-2 output 259")
        fixture.page.wait_for_function(
            "__viewTest.state.searchQuery === 'pass-2 output 259'"
        )
        fixture.settled()
        assert fixture.state_result()["ids"] == ["item-259"]
        row = fixture.page.evaluate("__viewTest.getFilteredItems()[0].row")
        assert row["output"] == "pass-2 output 259"
        assert row["metric_values"] == [1, 260]
        assert row["metric_meta"]["accuracy"]["explanation"] == "pass-2 judge 259"
        assert any(
            body.get("pass_number") == 2
            for _, verb, body in fixture.requests
            if verb == "search"
        )
    finally:
        fixture.close()


def test_run_hydration_retry_and_resident_body_bound(browser):
    fixture = ViewFixture(browser, "run")
    fixture.fail_details = True
    try:
        fixture.page.goto("http://qym.test/run/run-1")
        fixture.page.locator("#items-grid button").get_by_text("Retry").click()
        fixture.ready()
        for number in range(2, 14):
            fixture.page.locator('#pagination [aria-label="Page number"]').fill(
                str(number)
            )
            fixture.page.locator('#pagination [aria-label="Page number"]').press(
                "Enter"
            )
            fixture.settled()
        resident = fixture.page.evaluate(
            "__viewTest.state.snapshot.rows.filter(row => row.__details_loaded).length"
        )
        assert resident <= 200
        fixture.page.locator('#pagination [aria-label="First page"]').click()
        fixture.settled()
        assert (
            fixture.page.evaluate("__viewTest.state.snapshot.rows[0].output")
            == fixture.data["run-1"]["snapshot"]["rows"][0]["output"]
        )
    finally:
        fixture.close()


@pytest.mark.parametrize("kind", ["run", "compare"])
def test_metric_edit_updates_global_numbers_and_survives_eviction(browser, kind):
    fixture = ViewFixture(browser, kind)
    try:
        fixture.goto()
        fixture.page.locator("#items-grid .item-header-expand").first.click()
        fixture.page.locator("#items-grid .metric-edit-open").first.click()
        editor = fixture.page.locator("#items-grid .metric-edit-input:visible").first
        editor.fill("1")
        editor.press("Enter")
        fixture.page.wait_for_function("""() => {
          const s=__viewTest.state;
          return (s.snapshot?.rows || s.runs?.[0]?.snapshot.rows)[0].metric_values[0] === 1;
        }""")
        for number in range(2, 14):
            pager = fixture.page.locator('#pagination [aria-label="Page number"]')
            pager.fill(str(number))
            pager.press("Enter")
            fixture.settled()
        fixture.page.locator('#pagination [aria-label="First page"]').click()
        fixture.settled()
        row = fixture.page.evaluate(
            "(__viewTest.state.snapshot?.rows || __viewTest.state.runs?.[0]?.snapshot.rows)[0]"
        )
        assert row["metric_values"][0] == 1
        assert row["metric_meta"]["accuracy"]["modified"] is True
        assert row["metric_meta"]["accuracy"]["explanation"] == "Judge explanation 0"
        assert row["compare_item_id"] == "aligned-0"
        assert len(fixture.state_result()["ids"]) == 260
    finally:
        fixture.close()


def test_compare_modal_loads_off_page_repeated_passes(browser):
    fixture = ViewFixture(browser, "compare", samples=3)
    try:
        fixture.goto()
        fixture.page.evaluate("__viewTest.openItemComparisonModal('aligned-259')")
        fixture.page.wait_for_function(
            "document.querySelector('#item-comparison-modal-body').textContent.includes('pass-2 output 259')"
        )
        text = fixture.page.locator("#item-comparison-modal-body").inner_text()
        assert "pass-1 output 259" in text
        assert "pass-3 output 259" in text
        fixture.page.locator("#item-comparison-modal-close").click()
        fixture.page.locator("#items-search").fill("pass-2 output 259")
        fixture.page.wait_for_function(
            "__viewTest.state.searchQuery === 'pass-2 output 259'"
        )
        fixture.settled()
        assert fixture.state_result()["ids"] == ["aligned-259"]
        assert len(fixture.page.evaluate("__viewTest.state.runs")) == 6
    finally:
        fixture.close()


def test_compare_cross_field_search_retains_exact_joined_semantics(browser):
    fixtures = [
        ViewFixture(browser, "compare", compact=value) for value in (False, True)
    ]
    try:
        for fixture in fixtures:
            fixture.goto()
            fixture.page.evaluate(
                "__viewTest.state.searchQuery='Question 259\\nExpected 259'; __viewTest.renderItems()"
            )
            fixture.settled()
        assert fixtures[0].state_result() == fixtures[1].state_result()
        assert fixtures[1].state_result()["ids"] == ["aligned-259"]
        fixtures[1].page.evaluate(
            "__viewTest.state.searchQuery=''; __viewTest.renderItems()"
        )
        fixtures[1].settled()
        assert fixtures[1].page.evaluate(
            "__viewTest.state.runs.every(run => run.snapshot.rows.filter(row => row.__details_loaded).length <= 200)"
        )
    finally:
        for fixture in fixtures:
            fixture.close()


def test_compare_html_export_contains_every_body_and_opens_offline(browser, tmp_path):
    fixture = ViewFixture(browser, "compare")
    offline = None
    try:
        fixture.goto()
        with fixture.page.expect_download() as download:
            fixture.page.locator("#export-share-btn").click()
        target = tmp_path / "compare.html"
        download.value.save_as(target)
        exported = target.read_text()
        assert "needle-259" in exported
        assert "Judge explanation 259" in exported
        assert not re.search(r"<script\s+src=", exported)
        offline = browser.new_context(offline=True)
        page = offline.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(target.as_uri())
        page.wait_for_function(
            "document.querySelector('#filter-count')?.textContent.includes('260')"
        )
        page.locator("#items-search").fill("needle-259")
        page.wait_for_function("__viewTest.state.searchQuery === 'needle-259'")
        assert page.evaluate("__viewTest.getFilteredItems().length") == 1
        assert not errors
    finally:
        if offline:
            offline.close()
        fixture.close()


@pytest.mark.parametrize("kind", ["run", "compare"])
def test_slow_old_search_cannot_replace_new_results(browser, kind):
    fixture = ViewFixture(browser, kind)
    try:
        fixture.goto()
        fixture.page.evaluate("""() => {
          const fetchOriginal = window.fetch;
          window.__heldOld = [];
          window.__oldCompleted = 0;
          window.fetch = async (url, options) => {
            const response = await fetchOriginal(url, options);
            if (String(url).endsWith('/items/search') &&
                JSON.parse(options.body).conditions.some(c => c.value === 'needle-258')) {
              await new Promise(resolve => window.__heldOld.push(resolve));
              window.__oldCompleted++;
            }
            return response;
          };
          __viewTest.state.searchQuery = 'needle-258';
          __viewTest.renderItems();
        }""")
        count = 2 if kind == "compare" else 1
        fixture.page.wait_for_function(f"window.__heldOld.length === {count}")
        fixture.page.evaluate(
            "__viewTest.state.searchQuery='needle-259'; __viewTest.renderItems()"
        )
        fixture.settled()
        before = fixture.state_result()
        assert len(before["ids"]) == 1
        assert before["ids"][0].endswith("259")
        fixture.page.evaluate("window.__heldOld.forEach(resolve => resolve())")
        fixture.page.wait_for_function(f"window.__oldCompleted === {count}")
        fixture.settled()
        assert fixture.state_result() == before
        assert "Question 259" in fixture.page.locator("#items-grid").inner_text()
    finally:
        fixture.close()
