from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_JS = ROOT / "packages" / "platform" / "qym_platform" / "_static" / "dashboard" / "dashboard.js"
DASHBOARD_DIR = ROOT / "packages" / "platform" / "qym_platform" / "_static" / "dashboard"
RUNS_API = ROOT / "packages" / "platform" / "qym_platform" / "api" / "runs.py"


def test_dashboard_delete_action_binding_allows_non_deletable_runs() -> None:
    source = DASHBOARD_JS.read_text(encoding="utf-8")

    assert "const deleteBtn = tr.querySelector('.delete-run');" in source
    assert "if (deleteBtn) deleteBtn.addEventListener('click'" in source
    assert "tr.querySelector('.delete-run').addEventListener" not in source


def test_user_filter_is_available_and_clickable_on_dashboard_views() -> None:
    source = DASHBOARD_JS.read_text(encoding="utf-8")
    assert "'filter-user-btn'" in source

    for name in ("index.html", "charts.html", "models.html"):
        html = (DASHBOARD_DIR / name).read_text(encoding="utf-8")
        assert 'id="filter-user-btn"' in html
        assert 'id="filter-user-dropdown"' in html


def test_models_run_selection_uses_run_display_names() -> None:
    source = DASHBOARD_JS.read_text(encoding="utf-8")

    assert "function getRunDisplayName(run)" in source
    assert "const runDisplayName = getRunDisplayName(run);" in source
    assert '<div class="run-name" title="${run.run_id}">${stripProviderFromRunId(run.run_id)}</div>' not in source


def test_live_runs_sections_are_present_on_overview_and_admin() -> None:
    overview = (DASHBOARD_DIR / "overview.html").read_text(encoding="utf-8")
    admin = (DASHBOARD_DIR / "admin.html").read_text(encoding="utf-8")

    assert "Live Runs" in overview
    assert "api/runs/live?limit=8" in overview
    assert "exclude_live=true" in overview
    assert "<th>Run</th><th>User</th><th>Items</th><th>Date</th>" in overview
    assert "<th>Run</th><th>User</th><th>Score</th><th>Date</th>" not in overview
    assert "<th>Run</th><th>User</th><th>Model</th><th>Score</th><th>Date</th>" not in overview
    assert "const reviewLimit = 12;" in overview
    assert "Live Runs" in admin
    assert 'class="admin-tabs"' in admin
    assert 'data-admin-tab="runs"' in admin
    assert 'data-admin-tab="live"' not in admin
    assert 'data-admin-tab="by-project"' not in admin
    assert 'border-bottom: 2px solid transparent' in admin
    assert 'border-bottom-color: var(--accent-primary)' in admin
    assert 'data-admin-panel="runs"' in admin
    assert 'data-admin-panel="users"' in admin
    assert "api/runs/live?all_projects=true&limit=100" in admin
    assert "<th>Project</th><th>Run</th><th>Owner</th>" in admin
    assert "<th>Project</th><th>Run</th><th>Owner</th><th>Status</th><th>Items</th><th>Created</th>" in admin
    assert "<th>Project</th><th>Run</th><th>Owner</th><th>Status</th><th>Score</th><th>Created</th>" not in admin
    assert "Most Recent Eval Runs" in admin
    assert "Recent Eval Runs by Project" not in admin
    assert "recentRunsPageSize: 6" in admin
    assert "include_projects=false" in admin
    assert "global_offset=${offset}" in admin
    assert 'id="recent-runs-prev"' in admin
    assert 'id="recent-runs-next"' in admin


def test_run_and_compare_overviews_are_filter_aware() -> None:
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")

    assert "function renderOverview(filteredItemsOverride = null)" in run
    assert "renderOverview(items);" in run
    assert "function renderComparisonStats(filteredItemsOverride = null)" in compare
    assert "renderComparisonStats(items);" in compare
    assert "calculateComparisonStatsForMetric(state.selectedOverviewMetric, filteredItemIds)" in compare
    assert "const itemIdSet = new Set(itemIdList);" in compare
    assert "if (!itemIdSet.has(itemId)) continue;" in compare


def test_run_html_export_inlines_versioned_static_assets() -> None:
    source = RUNS_API.read_text(encoding="utf-8")

    assert r'dashboard\.css(?:\?[^"]*)?' in source
    assert r'shell\.css(?:\?[^"]*)?' in source
    assert r'metrics\.js(?:\?[^"]*)?' in source
    assert r'trace_viewer\.js(?:\?[^"]*)?' in source
    assert r'auth\.js(?:\?[^"]*)?' in source
    assert r'shell\.js(?:\?[^"]*)?' in source
    assert r'playground\.js(?:\?[^"]*)?' in source
    assert "lambda _match: f\"<style>\\n{css_content}\\n</style>\"" in source
    assert "lambda _match: f\"<script>\\n{metrics_js}\\n</script>\"" in source


def test_compare_html_export_is_self_contained_and_export_safe() -> None:
    source = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")

    assert "async function inlineCompareExportAssets(html)" in source
    assert "(?:dashboard|shell)\\.css" in source
    assert "(?:metrics|trace_viewer)\\.js" in source
    assert "(?:auth|shell|playground)\\.js" in source
    assert "html.replace(match[0], () => '<style>" in source
    assert "html.replace(match[0], () => '<script>" in source
    assert "html = await inlineCompareExportAssets(html);" in source
    assert "if (!IS_COMPARE_EXPORT && typeof QymPlayground !== 'undefined')" in source


def test_compare_filter_bar_does_not_use_rigid_wide_grid() -> None:
    source = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")

    assert "grid-template-columns: 210px 170px 240px" not in source
    assert ".fp-filter-row {\n      display: flex;" in source
    assert ".fp-actions {\n      display: flex;" in source
    assert "min-width: max-content;" in source


def test_compare_output_height_alignment_preserves_scroll_caps() -> None:
    source = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")

    assert ".item-run-output .output-text {\n      font-family: var(--font-mono);" in source
    assert "max-height: 300px;" in source
    assert ".item-run-output .output-text:has(.formatted-table-grid)" in source
    assert "const cap = el.querySelector('.formatted-table-grid') ? 640 : 300;" in source
    assert "el.style.minHeight = `${Math.min(max, cap)}px`;" in source
    assert "el.style.minHeight = `${max}px`;" not in source
