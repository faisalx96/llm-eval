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


def test_profile_admin_bootstrap_panel_uses_me_flag() -> None:
    source = (DASHBOARD_DIR / "profile.html").read_text(encoding="utf-8")

    assert 'id="bootstrap-panel"' in source
    assert 'id="bootstrap-token-input"' in source
    assert "me.can_bootstrap_admin" in source
    assert "apiUrl('v1/auth/bootstrap-admin')" in source


def test_models_run_selection_uses_run_display_names() -> None:
    source = DASHBOARD_JS.read_text(encoding="utf-8")

    assert "function getRunDisplayName(run)" in source
    assert "const runDisplayName = getRunDisplayName(run);" in source
    assert '<div class="run-name" title="${run.run_id}">${stripProviderFromRunId(run.run_id)}</div>' not in source


def test_models_view_uses_globally_filtered_runs() -> None:
    source = DASHBOARD_JS.read_text(encoding="utf-8")
    models_block = source.split("async function renderModelsView()", 1)[1].split("function populateModelsViewDropdowns()", 1)[0]
    dropdown_block = source.split("function populateModelsViewDropdowns()", 1)[1].split("// Cache for fetched Models run data", 1)[0]

    assert "const matchingRuns = state.filteredRuns.filter" in models_block
    assert "const matchingRuns = state.flatRuns.filter" not in models_block
    assert "state.filterModels.size > 0 && !state.filterModels.has('__none__')" not in models_block
    assert "? state.filteredRuns.filter(r => r.task_name === currentTask && getRunDatasetKey(r) === currentDataset)" in dropdown_block
    assert "? state.flatRuns.filter(r => r.task_name === currentTask && getRunDatasetKey(r) === currentDataset)" not in dropdown_block


def test_charts_grouped_view_uses_presets_for_version_model_splits() -> None:
    source = DASHBOARD_JS.read_text(encoding="utf-8")
    css = (DASHBOARD_DIR / "dashboard.css").read_text(encoding="utf-8")
    charts_block = source.split("function renderChartsView()", 1)[1].split("// Wire up dataset tab clicks", 1)[0]

    assert "version-model" in charts_block
    assert "model-version" in charts_block
    assert "Grouped by version, comparing models inside each version" in charts_block
    assert "firstColLabel = groupMode === 'version-model' ? 'Version / Model' : 'Model / Version';" in charts_block
    assert "const primaryGrouping = groupMode === 'version-model' ? 'version' : 'model';" in charts_block
    assert "const secondaryGrouping = groupMode === 'version-model' ? 'model' : 'version';" in charts_block
    assert "chart-table-group-header-nested" in charts_block
    assert "chart-row-mode-control" in charts_block
    assert "chart-group-axis-control" in charts_block
    assert "chart-then-axis-control" in charts_block
    assert "chart-row-mode-control" in css
    assert "chart-group-axis-control" in css
    assert "chart-then-axis-control" in css
    assert '<button class="chart-segment-btn ${groupMode === \'run\' ? \'active\' : \'\'}" data-mode="run">Runs</button>' in charts_block
    assert '<button class="chart-segment-btn ${isGrouped ? \'active\' : \'\'}" data-mode="${isGrouped ? groupMode : \'model\'}">Grouped</button>' in charts_block
    assert '<span class="chart-control-label">Group</span>' in charts_block
    assert '<span class="chart-control-label">Then</span>' in charts_block
    assert "const thenModelDisabled = !isGrouped || primaryGroup === 'model';" in charts_block
    assert "const thenVersionDisabled = !isGrouped || primaryGroup === 'version' || !hasVersions;" in charts_block
    assert ".chart-table-group-header-nested" in css
    assert ".chart-table-group-body-nested::before" in css
    assert ".chart-table-group-header-nested::before" in css
    assert ".chart-table-group-body-leaf .chart-table-row::before" in css
    assert "padding-left: 18px;" in css
    assert "padding-left: 28px;" in css
    assert "padding-left: 68px;" not in css
    assert "chartGroupMetricStats" in source
    assert "function renderChartGroupStatCells(runs, modelIdx = null)" in charts_block
    assert "function renderEmptyGroupStatCells()" in charts_block
    assert "function renderGroupStatBar(value, label, title, modelIdx)" in charts_block
    assert "scheduleChartGroupMetricStats(runs, groupMetricName, threshold, isBoolean)" in charts_block
    assert "calculateModelStatsFromItems(detailedRuns, metricName, threshold, isBoolean)" in charts_block
    assert "const GROUP_DISPLAY_COLUMNS = [" in source
    assert "Grouped Run Columns" in source
    assert "...GROUP_DISPLAY_COLUMNS.map(col => col.key)" in source
    assert "function shouldShowGroupedRunColumnOptions()" in source
    assert "state.currentView !== 'charts'" in source
    assert "if (mode === 'run') return false;" in source
    assert "return !Object.values(expansion.expanded || {}).some(isExpanded => isExpanded === true);" in source
    assert "const groupColumns = shouldShowGroupedRunColumnOptions() ? GROUP_DISPLAY_COLUMNS : [];" in source
    assert "populateMetricVisibility(getAvailableMetricsForRuns(metricSourceRuns), metricSourceRuns);" in charts_block
    assert "const visibleGroupStatColumns = isGrouped" in charts_block
    assert "state.visibleMetrics === null || state.visibleMetrics.has(col.key)" in charts_block
    assert "const showGroupStatColumns = isGrouped && visibleGroupStatColumns.length > 0 && !hasExpandedGroupState;" in charts_block
    assert "const groupStatHeaderCells = visibleGroupStatColumns.map" in charts_block
    assert "GROUP_PASS_AT_K_COLUMN_KEY" in charts_block
    assert "GROUP_CONSISTENCY_COLUMN_KEY" in charts_block
    assert "GROUP_RELIABILITY_COLUMN_KEY" in charts_block
    assert "function isGroupStatSortKey(key)" in charts_block
    assert "chart-col-header chart-group-stat-header sortable-col" in charts_block
    assert "data-sort=\"${key}\"" in charts_block
    assert "chart-table ${isGrouped ? 'chart-table-grouped' : ''}" in charts_block
    assert "${showGroupStatColumns ? groupStatHeaderCells : ''}\n                ${headerCells}" in charts_block
    assert "${groupStatCells}\n              ${dataCells}" in charts_block
    assert "${renderEmptyGroupStatCells()}\n            ${dataCells}" not in charts_block
    assert "if (!showGroupStatColumns || visibleGroupStatColumns.length === 0) return '';" in charts_block
    assert "if (!showGroupStatColumns) return '';" in charts_block
    assert "const firstColDisplayLabel = isGrouped && hasExpandedGroups ? `${firstColLabel} / Run` : firstColLabel;" in charts_block
    assert "setChartGroupCollapsed(card, mode, groupId, !isCollapsed);" in charts_block
    assert "render();" in charts_block
    assert '<div class="chart-table-group-main">' in charts_block
    assert '${dataCells}' in charts_block
    assert '<span class="chart-group-copy">' in charts_block
    assert '<span class="chart-group-title-line">' in charts_block
    assert "Pass@K" in source
    assert "Consistency" in source
    assert "Reliability" in source
    assert "Pass@${K} ${formatPercent(stats.passAtK)}" in charts_block
    assert "renderMiniBarCell({" in charts_block
    assert "cellClass: 'chart-metric-cell chart-group-stat-cell'" in charts_block
    assert "renderGroupStatBar(stats.passAtK, formatPercent(stats.passAtK)" in charts_block
    assert "renderGroupStatBar(stats.consistency, consistencyText" in charts_block
    assert "renderGroupStatBar(stats.reliability, reliabilityText" in charts_block
    assert "Pass^" not in charts_block
    assert ".chart-table-group-main" in css
    assert ".chart-group-copy" in css
    assert ".chart-group-title-line" in css
    assert ".chart-group-stat-header" in css
    assert ".chart-group-stat-cell" in css
    assert ".chart-group-stat-cell-empty" in css
    assert ".chart-table-grouped .chart-col-header" in css


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


def test_compare_cohort_metadata_breakdown_uses_user_defined_item_metadata() -> None:
    source = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")

    assert "const SWEEP_INTERNAL_METADATA_KEYS = new Set([" in source
    assert "'root_cause'," in source
    assert "'trace_stats'," in source
    assert "if (!isUserDefinedSweepMetadataKey(key)) return;" in source
    assert "const preferred = ['domain', 'complexity'];" in source
    assert "const preferred = ['domain', 'complexity', 'root_cause'];" not in source


def test_compare_output_height_alignment_preserves_scroll_caps() -> None:
    source = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")

    assert ".item-run-output .output-text {\n      font-family: var(--font-mono);" in source
    assert "max-height: 300px;" in source
    assert ".item-run-output .output-text:has(.formatted-table-grid)" in source
    assert "const cap = el.querySelector('.formatted-table-grid') ? 640 : 300;" in source
    assert "el.style.minHeight = `${Math.min(max, cap)}px`;" in source
    assert "el.style.minHeight = `${max}px`;" not in source


def test_datasets_detail_actions_are_version_state_driven() -> None:
    source = (DASHBOARD_DIR / "datasets.html").read_text(encoding="utf-8")
    draft_block = source.split("if (isDraft) {", 1)[1].split("} else if", 1)[0]

    # shared height variable exists (exact px is a design choice, not a contract)
    assert "--dsx-action-h:" in source
    assert ".dsx-hero-actions .shell-btn,\n    .dsx-version-pill" in source
    assert "height: var(--dsx-action-h); min-height: var(--dsx-action-h);" in source
    assert "width: var(--dsx-action-h); height: var(--dsx-action-h); box-sizing: border-box;" in source
    assert ".dsx-pill.published { color: var(--accent-secondary); border-color: rgba(0,168,255,0.35);" in source
    assert "if (versionIsProduction(v)) return 'success';\n      return 'published';" in source
    assert "'+ Add item'" in draft_block
    assert "openUploadWizard({ mode: 'add-to-draft'" in draft_block
    assert "'Publish'" in draft_block
    assert "'+ Create draft'" not in draft_block
    assert "versionIsProduction(v)" in source
    assert "title: 'Publish draft ' + version + '?'" in source
    assert "details: [" in source
    assert "'Snapshot draft ' + version" in source
    assert "'Published versions stay stable for comparisons and prior runs.'" in source
    assert "'Move the production alias to ' + version" in source
    assert "confirmLabel: 'Publish draft'" in source


def test_datasets_runs_tab_is_flush_without_redundant_heading() -> None:
    source = (DASHBOARD_DIR / "datasets.html").read_text(encoding="utf-8")
    runs_tab_block = source.split("async function renderRunsTab(host){", 1)[1].split("    // -------------------------------------------------------------\n    // LINEAGE TAB", 1)[0]

    assert "Runs against this dataset" not in source
    assert "const listHost = el('div');" in runs_tab_block
    assert "className: 'dsx-table-wrap flush'" in runs_tab_block
    assert ".dsx-table-wrap.flush { border-top: 0; }" in source
    assert "const status = String(r.status || '—').toUpperCase();" in runs_tab_block
    assert "className: 'status-badge status-' + status" in runs_tab_block
    assert "className: 'dsx-pill ' + (r.status === 'completed'" not in runs_tab_block


def test_datasets_version_switching_preserves_lineage_tab() -> None:
    source = (DASHBOARD_DIR / "datasets.html").read_text(encoding="utf-8")
    version_row_block = source.split("function versionPopoverRow(v, onSelect){", 1)[1].split("function buildTabs(){", 1)[0]
    lineage_block = source.split("async function renderLineageTab(host){", 1)[1].split("    // -------------------------------------------------------------\n    // SETTINGS TAB", 1)[0]

    assert "navigate({ tab: state.tab, v: v.version, item: null });" in version_row_block
    assert "navigate({ tab: 'lineage', v: v.version, item: null })" in lineage_block
    assert "navigate({ tab: 'items', v: v.version })" not in lineage_block
    assert "const childrenByParent = {};" in lineage_block
    assert "className: 'dsx-lineage-children'" in lineage_block
    assert "' has-children'" in lineage_block
    assert "const childNode = renderNode(child);" in lineage_block
    assert "dsx-lineage-parent-label" not in source
    assert "dsx-lineage-branch-label" not in source
    assert ".dsx-lineage-changes { display: flex; flex-direction: column; gap: 2px; margin: 0 0 4px 44px; padding-left: 0; }" in source
    assert ".dsx-lineage-tree-node.has-children > .dsx-lineage-changes::before" in source
    assert "'forked from ' + parentVersion.version" not in lineage_block
    assert "style: { marginLeft: (depth * 18) + 'px' }" not in lineage_block


def test_item_pagination_controls_are_single_bottom_bars() -> None:
    datasets = (DASHBOARD_DIR / "datasets.html").read_text(encoding="utf-8")
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
    index = (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8")
    dashboard_js = DASHBOARD_JS.read_text(encoding="utf-8")
    dashboard_css = (DASHBOARD_DIR / "dashboard.css").read_text(encoding="utf-8")

    datasets_items_block = datasets.split("async function renderItemsTab(host){", 1)[1].split("    // -------------------------------------------------------------\n    // ITEM DRAWER", 1)[0]
    assert "id: 'dsx-pager-top'" not in datasets_items_block
    assert "pagerTop" not in datasets_items_block
    assert "className: 'dsx-pager', id: 'dsx-pager'" in datasets_items_block
    assert "className: 'dsx-table-wrap paged', id: 'dsx-table-wrap'" in datasets_items_block
    assert "position: fixed; left: 0; right: 0; bottom: 0;" in datasets
    assert "min-height: 36px;" in datasets
    datasets_pagination_css = datasets.split("    /* PAGINATION */", 1)[1].split("    /* DRAWER", 1)[0]
    assert "justify-content: center;" in datasets_pagination_css
    assert "gap: 14px;" in datasets_pagination_css
    assert ".dsx-pager-info" in datasets_pagination_css
    assert ".dsx-pager-page" in datasets_pagination_css
    assert ".dsx-pager-controls { display: inline-flex; gap: 0;" in datasets_pagination_css
    assert "border-radius: 7px;" in datasets_pagination_css
    assert ".dsx-pager-info { width: 252px; text-align: right; }" in datasets_pagination_css
    assert "width: 112px;" in datasets_pagination_css
    assert "border-radius: 8px;" not in datasets_pagination_css
    assert "'Previous'" in datasets_items_block
    assert "'Next'" in datasets_items_block
    assert "className: 'dsx-pager-page'" in datasets_items_block
    assert "'Page ' + (total === 0 ? 0 : state.page + 1) + ' of ' + totalPages" in datasets_items_block
    assert "'← Prev'" not in datasets_items_block
    assert "'Next →'" not in datasets_items_block
    assert "' items'" in datasets_items_block
    assert "box-shadow: 0 10px 30px rgba(0,0,0,0.28)" not in datasets

    assert 'id="pagination-top"' not in run
    assert "paginationEls" not in run
    assert 'class="pagination" id="pagination"' in run
    run_filter_panel = run.split('<div class="filter-panel">', 1)[1].split('<div class="items-grid" id="items-grid">', 1)[0]
    assert '<div class="pagination" id="pagination"></div>' in run_filter_panel
    run_pagination_css = run.split("    /* Pagination */", 1)[1].split("    .pagination button", 1)[0]
    assert "position: sticky;" not in run_pagination_css
    assert "position: fixed;" not in run_pagination_css
    assert "display: inline-flex;" in run_pagination_css
    assert "gap: 0;" in run_pagination_css
    assert "border-radius: 7px;" in run_pagination_css
    assert "width: 112px;" in run
    run_status_css = run.split("    .fp-status .filter-count {", 1)[1].split("    .fp-status .filter-count .count-num", 1)[0]
    assert "width: 172px;" in run_status_css
    assert "font-variant-numeric: tabular-nums;" in run_status_css
    assert "margin-left: auto;" in run_pagination_css
    assert "min-height: 36px;" not in run_pagination_css
    assert "border-radius: 8px;" not in run_pagination_css
    assert "box-shadow: 0 10px 30px rgba(0,0,0,0.28)" not in run

    assert 'id="pagination-top"' not in compare
    assert "paginationEls" not in compare
    assert 'class="pagination" id="pagination"' in compare
    compare_filter_panel = compare.split('<div class="filter-panel">', 1)[1].split('<div class="items-grid" id="items-grid">', 1)[0]
    assert '<div class="pagination" id="pagination"></div>' in compare_filter_panel
    compare_pagination_css = compare.split("    /* Pagination */", 1)[1].split("    .pagination button", 1)[0]
    assert "position: sticky;" not in compare_pagination_css
    assert "position: fixed;" not in compare_pagination_css
    assert "display: inline-flex;" in compare_pagination_css
    assert "gap: 0;" in compare_pagination_css
    assert "border-radius: 7px;" in compare_pagination_css
    assert "width: 112px;" in compare
    compare_status_css = compare.split("    .fp-status .filter-count {", 1)[1].split("    .fp-status .filter-count .count-num", 1)[0]
    assert "width: 172px;" in compare_status_css
    assert "font-variant-numeric: tabular-nums;" in compare_status_css
    assert "margin-left: auto;" in compare_pagination_css
    assert "min-height: 36px;" not in compare_pagination_css
    assert "border-radius: 8px;" not in compare_pagination_css
    assert "box-shadow: 0 10px 30px rgba(0,0,0,0.28)" not in compare

    assert 'id="table-pagination-top"' not in index
    assert 'class="table-pagination" id="table-pagination"' in index
    footer_block = index.split('<footer class="status-bar">', 1)[1].split('</footer>', 1)[0]
    assert 'class="status-center"' in footer_block
    assert 'id="table-pagination"' in footer_block
    assert 'data-table-page="prev"' in index
    assert "document.querySelectorAll('[data-table-page=\"prev\"]')" in dashboard_js
    table_pagination_css = dashboard_css.split(".table-pagination {", 1)[1].split(".table-pagination-info", 1)[0]
    assert "position: fixed;" not in table_pagination_css
    assert "border-top: 1px solid var(--border-subtle);" not in table_pagination_css
    assert ".table-pagination-info {\n  width: 252px;\n  text-align: right;\n}" in dashboard_css
    assert "width: 112px;" in dashboard_css
    assert ".status-center" in dashboard_css
    assert "grid-template-columns: minmax(220px, 1fr) auto minmax(220px, 1fr);" in dashboard_css
    assert "tablePagination.style.display = state.currentView === 'table' ? 'flex' : 'none';" in dashboard_js
    assert "min-height: 36px;" in dashboard_css
    assert "box-shadow: 0 10px 30px rgba(0,0,0,0.28)" not in dashboard_css


def test_datasets_version_popover_uses_fast_switcher() -> None:
    source = (DASHBOARD_DIR / "datasets.html").read_text(encoding="utf-8")

    assert "placeholder: 'Search versions...'" in source
    assert "function renderVersionList(query)" in source
    assert "versionSearchText(v).includes(q)" in source
    assert "appendVersionSection" not in source
    assert "dsx-version-popover-header" not in source
    assert "versionPopoverRow(v, closePopover)" in source
    assert "Changes vs production" not in source
    assert "compareSummaryCache" not in source


def test_shell_form_dialog_supports_structured_details() -> None:
    source = (DASHBOARD_DIR / "shell.js").read_text(encoding="utf-8")
    styles = (DASHBOARD_DIR / "shell.css").read_text(encoding="utf-8")

    assert "options.details" in source
    assert "shell-modal-detail-list" in source
    assert "shell-form-checkbox" in source
    assert ".shell-modal-detail-item" in styles
    assert ".shell-form-checkbox-help" in styles
