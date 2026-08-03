from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLATFORM = ROOT / "packages" / "platform"
DASHBOARD_DOCS = PLATFORM / "qym_platform" / "_static" / "dashboard" / "docs"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_in_app_docs_navigation_only_references_existing_pages() -> None:
    source = _read(DASHBOARD_DOCS.parent / "docs.js")
    section_pattern = re.compile(
        r"id: '([^']+)',\s+title: '[^']+',\s+icon: .*?\s+pages: \[(.*?)\]\s+}",
        re.DOTALL,
    )
    page_pattern = re.compile(r"\{ id: '([^']+)', title: '[^']+' }")

    pages = [
        (section_id, page_id)
        for section_id, body in section_pattern.findall(source)
        for page_id in page_pattern.findall(body)
    ]
    assert pages
    assert ("platform-guide", "navigation") in pages
    assert ("platform-guide", "runs") in pages
    assert ("platform-guide", "run-detail") in pages
    assert ("platform-guide", "projects-data-review") in pages
    for section_id, page_id in pages:
        assert (DASHBOARD_DOCS / section_id / f"{page_id}.html").is_file()


def test_platform_guides_describe_current_project_and_repeat_model() -> None:
    user_guide = _read(PLATFORM / "docs" / "USER_GUIDE.md")
    readme = _read(PLATFORM / "README.md")
    runs = _read(DASHBOARD_DOCS / "platform-guide" / "runs.html")
    detail = _read(DASHBOARD_DOCS / "platform-guide" / "run-detail.html")
    data_review = _read(DASHBOARD_DOCS / "platform-guide" / "projects-data-review.html")

    for stale_role in ("EMPLOYEE", "GM/VP", "Sector → Department → Team"):
        assert stale_role not in readme
    assert "Project | `MEMBER`" in user_guide
    assert "Project | `MANAGER`" in user_guide
    assert "inside one run" in user_guide
    assert "execution units" in runs.lower()
    assert "pass reference" in runs
    assert "Per-pass metric explanations" in detail
    assert "scope labels are informational" in data_review


def test_ingestion_and_endpoint_docs_cover_repeat_protocol() -> None:
    ingestion = _read(DASHBOARD_DOCS / "developer" / "ingestion.html")
    endpoints = _read(DASHBOARD_DOCS / "developer" / "endpoints.html")

    assert "There are 12 event types" in ingestion
    assert "supports_pass_events" in ingestion
    assert "pass_completed" in ingestion
    assert "is_final_pass" in ingestion
    assert "per metric per item and pass" in ingestion
    assert "/api/runs/{run_id}/passes" in endpoints
    assert "/api/runs/{run_id}/group-metrics" in endpoints
    assert "/v1/admin/org/*" not in endpoints
    assert "GET /v1/admin/settings" not in endpoints


def test_metric_docs_match_runtime_dependency_and_timeout_behavior() -> None:
    config = _read(DASHBOARD_DOCS / "sdk-guide" / "config.html")
    judges = _read(DASHBOARD_DOCS / "sdk-guide" / "judges.html")
    judge_runtime = _read(
        ROOT / "packages" / "sdk" / "qym" / "metrics" / "judges" / "base.py"
    )

    assert "metric_max_retries" in config
    assert "three total attempts" in config
    assert "pip install openai" in judges
    assert "pip install qym[judges]" not in judge_runtime
    assert "JudgeInputError" in judges


def test_product_eval_docs_use_one_native_repeat_run() -> None:
    client = _read(PLATFORM / "docs" / "PRODUCT_EVAL_API_CLIENT_GUIDE.md")
    operator = _read(PLATFORM / "docs" / "PRODUCT_EVAL_API_GUIDE.md")

    assert "one qym run" in client.lower()
    assert "one logical qym run" in operator.lower()
    for guide in (client, operator):
        assert "samples=k" in guide
    assert "does not create `k` dashboard runs" in client
