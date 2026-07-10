from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_JS = ROOT / "packages" / "platform" / "qym_platform" / "_static" / "dashboard" / "dashboard.js"
DASHBOARD_DIR = ROOT / "packages" / "platform" / "qym_platform" / "_static" / "dashboard"
METRICS_JS = DASHBOARD_DIR / "metrics.js"
RUNS_API = ROOT / "packages" / "platform" / "qym_platform" / "api" / "runs.py"


def _rule(css: str, selector: str) -> str:
    """The body of the first CSS block that starts with `selector`."""
    start = css.index(selector)
    return css[start:css.index("}", css.index("{", start)) + 1]


def test_dashboard_delete_action_binding_allows_non_deletable_runs() -> None:
    source = DASHBOARD_JS.read_text(encoding="utf-8")

    assert "const deleteBtn = tr.querySelector('.delete-run');" in source
    assert "if (deleteBtn) deleteBtn.addEventListener('click'" in source
    assert "tr.querySelector('.delete-run').addEventListener" not in source


def test_repeat_run_rows_render_pass_dot_strip() -> None:
    """×k rows carry a per-pass dot strip (primary-metric score colors) fed by
    the pass_summaries field of the runs-list payload."""
    source = DASHBOARD_JS.read_text(encoding="utf-8")
    styles = (DASHBOARD_DIR / "dashboard.css").read_text(encoding="utf-8")
    api = RUNS_API.read_text(encoding="utf-8")

    assert "function renderPassDots(run)" in source
    assert "run.pass_summaries" in source
    assert "${renderPassDots(run)}" in source
    # informational only — the samples-toggle button stays the sole expander
    assert "querySelectorAll('.pass-dots')" not in source
    assert 'class="pdot' in source

    assert ".pass-dots" in styles
    assert ".pdot.score-5" in styles
    assert ".pdot.pending" in styles
    assert ".pdot.running" in styles
    assert ".pdot.err" in styles

    assert '"pass_summaries": pass_summary_map.get(r.id) or None,' in api


def test_repeat_run_expander_uses_accessible_attached_inspector() -> None:
    source = DASHBOARD_JS.read_text(encoding="utf-8")
    styles = (DASHBOARD_DIR / "dashboard.css").read_text(encoding="utf-8")

    assert '<button type="button" class="samples-toggle' in source
    assert 'aria-expanded="${samplesOpen ? \'true\' : \'false\'}"' in source
    assert 'aria-controls="${samplesPanelId}"' in source
    assert "event.key !== 'Enter' && event.key !== ' '" in source
    assert "toggle.setAttribute('aria-expanded'" in source
    assert 'class="samples-detail-panel"' in source
    assert "samples-retry-btn" in source
    assert "samples-pass-row" not in source
    assert ".samples-detail-panel" in styles
    assert ".samples-summary-grid" in styles
    assert ".samples-toggle:focus-visible" in styles


def test_repeat_drawer_follows_mock_option_c() -> None:
    """Runs view expands repeat runs in the table's native group dialect
    (mock option C): a compact ×k pill with a disclosure chevron opens a
    group-metrics strip plus one real table row per pass — metrics under
    their columns, inherited context cloned from the parent row and dimmed."""
    source = DASHBOARD_JS.read_text(encoding="utf-8")
    styles = (DASHBOARD_DIR / "dashboard.css").read_text(encoding="utf-8")

    # leading disclosure chevron before the run name (mock C's toggle), pass
    # dots after it, and a spacer aligning chevron-less rows; no hover card
    toggle_at = source.index('class="samples-toggle${samplesOpen')
    run_id_at = source.index('<span class="run-id"', toggle_at)
    assert toggle_at < run_id_at < source.index('${renderPassDots(run)}', toggle_at)
    assert 'class="samples-toggle-spacer"' in source
    assert ".samples-toggle.open .samples-toggle-chevron" in styles
    assert "verdict-card" not in source
    assert "verdict-card" not in styles

    # group-metrics strip in the table's group-header dialect, with the
    # platform's inline threshold slider (not a static trailing value) and
    # an item-weighted avg-latency stat
    assert "`% of items where at least one of the ${k} passes" in source
    assert 'class="samples-summary-grid"' in source
    assert 'class="threshold-slider-inline samples-threshold-slider"' in source
    assert source.index("samples-threshold-slider") < source.index('class="samples-summary-grid"')
    assert ">Avg latency</span>" in source
    assert "${latencyStat}" in source

    # the whole repeat-run row is an expand target (name still navigates)
    assert "const rowToggle = tr.querySelector('.samples-toggle');" in source

    # user-initiated expands fade in (opacity only — a transform would unpin
    # the sticky columns); collapse is instant and re-renders have no motion
    assert "detail.classList.add('samples-anim');" in source
    assert "samples-closing" not in source
    assert "transform" not in _rule(styles, "@keyframes samples-row-in")
    assert ".runs-table > tbody > tr.samples-anim" in styles

    # each completed pass row deep-links to the run page scoped to that pass
    assert 'data-pass-number="${firstPass}"' in source
    assert "`${base}?pass=${passNumber}`" in source
    assert '.runs-table > tbody > tr.pass-member[data-pass-number]:hover' in styles

    # first expand renders optimistically from pass_summaries (shimmer for
    # unknown cells, fetch fills in place); spinner row only as fallback.
    # A fill-in swap landing mid-fade resumes the animation via negative
    # delay instead of cutting it short.
    assert "_optimistic: true" in source
    assert 'class="samples-skel"' in source
    assert ".samples-skel" in styles
    assert "samples-loading-spinner" in source
    assert "detail.style.animationDelay = `${i * 30 - elapsed}ms`;" in source

    # sticky-column zebra/hover rules must not split pass rows visually
    assert ".runs-table > tbody > tr.pass-member:hover > td.col-model" in styles

    # native pass rows: same column skeleton as run rows, inherited cells dimmed
    assert 'class="pass-member' in source
    assert "const inherit = cls =>" in source
    assert "${inherit('col-task')}" in source
    assert "${inherit('col-owner')}" in source
    assert 'class="col-metric-value"' in source
    assert ".runs-table > tbody > tr.pass-member > td:first-child" in styles
    assert ".pass-member .tag," in styles

    # the embedded sub-table and the item × pass matrix are gone
    assert "samples-pass-table" not in source
    assert "QymDataTable" not in source
    assert "samples-matrix" not in source
    assert "smx-" not in styles


def test_run_page_supports_single_pass_scope() -> None:
    """?pass=N scopes the run page to one pass: metric values swap to that
    pass's scores at load time (so filters/overview/charts follow), the
    headline pill names the pass and links back to all passes, the cross-pass group
    section is hidden, and score edits target that pass (the run-level score
    is re-reduced server-side)."""
    source = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")

    assert "const VIEW_PASS = (() => {" in source
    assert "new URLSearchParams(window.location.search).get('pass')" in source
    assert "scores[state.viewPass - 1]" in source
    # no banner — the headline pill carries the pass label and the way back
    assert "pass-scope-banner" not in source
    assert "Return to all passes." in source
    # pass pages read as a single run: no group tiles/sweep/curve, no
    # Repeat Stability chart panels, no per-pass dot strips on item cards
    assert "if (samplesCount <= 1 || IS_EXPORT || state.viewPass)" in source
    assert source.count("const repeatSeries = state.viewPass ? [] :") == 2
    assert "(!state.viewPass && row.pass_scores && metric)" in source
    # edits are allowed and routed to the viewed pass
    assert "updateMetricScore(filePath, rowIndex, metricName, input.value, state.viewPass)" in source
    assert "...(passNumber ? { pass_number: passNumber } : {})," in source
    # applying the server row keeps per-pass fields and re-applies the lens
    assert "let next = { ...rows[pos], ...updatedRow };" in source
    assert "next.pass_attempts[state.viewPass - 1]" in source
    assert 'class="hero-samples-pill"' in source
    assert "samplesCount > 1 && !state.viewPass" in source
    assert 'class="hero-pass-pill"' in source
    # text-only pills — no decorative dot
    assert "hero-pass-dot" not in source
    assert '<div class="hero-eyebrow">Run Detail</div>' in source
    assert "passEyebrowHtml" not in source
    assert "<strong>x' + samplesCount + '</strong> PASSES" in source
    assert "metaItem('Samples'" not in source
    assert "'samples',\n          'max_metric_concurrency'" in source

    # pass scope swaps outputs/latency/traces too, from per-pass attempts
    assert "row.pass_attempts[state.viewPass - 1]" in source

    # the compact output-header switcher offers Summary or any pass;
    # lensed cards hide score edits (edits apply to the reduced score)
    assert 'class="attempt-switch"' not in source
    assert 'data-pass="' in source
    assert "state.itemPassLens" in source
    assert 'class="pass-dot pass-dot-switch' in source
    assert "pass-dot-summary" in source
    assert "View all-pass summary" in source
    assert ">All</button>" in source
    assert "output from latest available pass" in source
    assert "const outputLabel = shownOutputPass ? 'OUTPUT · PASS '" in source
    assert "+ passNumber + '</button>'" in source
    assert 'aria-pressed="' in source
    assert "querySelectorAll('.pass-dot-switch')" in source
    assert ".pass-dot-switch.active" in source
    assert "var(--warning) 45%" in source
    assert "0 0 9px color-mix(in srgb, var(--warning) 55%" in source
    assert ".item-card.pass-lensed .metric-edit-open { display: none; }" in source

    # the API ships per-pass attempts on run-detail rows, and update_metric
    # accepts a pass_number and re-reduces the run-level mean
    api = RUNS_API.read_text(encoding="utf-8")
    assert '"pass_attempts": (' in api
    assert "RunItemAttempt.is_last_attempt.is_(True)" in api
    assert 'pass_number = request.get("pass_number")' in api
    assert "Re-reduce: run-level score = mean over all stored passes" in api


def test_repeat_run_analysis_uses_shared_visual_language() -> None:
    source = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    repeat_analysis = source.split("async function renderSamplesAnalysis()", 1)[1].split("function wireTopActions", 1)[0]

    assert 'class="model-stat-box"' in source
    assert 'class="samples-correct-chart"' in source
    assert "if (samplesCount <= 10)" in source
    assert "Array.from({ length: 11 }" in source
    assert 'class="samples-metric-tabs" role="tablist"' in source
    assert "state.samplesMetric = nextMetric;" in source
    assert 'class="threshold-control samples-repeat-threshold"' in source
    assert "justify-content: flex-start;" in _rule(source, ".samples-metric-row {")
    assert ".samples-repeat-threshold {" not in source
    assert 'data-samples-threshold min="0" max="100" step="5"' in source
    assert "!isBooleanMetric && metricType !== 'numeric'" in source
    assert "'&threshold=' + encodeURIComponent(requestedThreshold)" in source
    assert "state.metricThresholds[groupMetric] = value / 100;" in source
    assert 'class="samples-metric-threshold"' not in source
    assert "window.QymMetrics.getMetricColorClass(v, mTypeOf(m))" in source
    assert "statTile('Max@' + samplesCount" not in source
    assert "statTile('Avg Score'" in source

    # sweep rows deep-link to that pass's page (cmd/ctrl-click opens a tab)
    assert "'<tr data-sw-pass=\"' + p.pass_number + '\"" in source
    assert "window.location.pathname + '?pass=' + tr.dataset.swPass" in source
    assert ".samples-sweep tbody tr[data-sw-pass] { cursor: pointer; }" in source

    # the curve draws at the measured box size (no fixed-viewBox letterboxing)
    assert "function curveChartHtml(W = 620, H = 230)" in source
    assert "function fitCurveChart()" in source
    assert "requestAnimationFrame(fitCurveChart)" in source
    assert "flex: 1 1 auto;" in _rule(source, ".samples-curve {")
    assert "statTile('Errors'" in source
    assert "statTile('Avg Latency'" in source
    assert source.index("statTile('Avg Latency'") < source.index("statTile('Errors'")
    assert "escapeHtml(groupMetricLabel) + ' vs k</div>'" in source
    assert "Probability that at least one or all selected attempts pass." in repeat_analysis
    assert "Items by exact correct-pass count." in repeat_analysis
    assert 'fill="var(--success-dim)"' not in repeat_analysis
    shared_box_rule = _rule(source, ".metric-card,")
    assert ".samples-chart-block," in shared_box_rule
    assert "background: var(--bg-surface);" in shared_box_rule
    assert "border: 1px solid var(--border-default);" in shared_box_rule
    assert "border-radius: 10px;" in shared_box_rule
    assert "⚡ Avg Latency" in source
    assert "⚡ Median Latency" in source
    assert "P95 Latency" not in repeat_analysis
    assert "p.p95_latency_ms" not in repeat_analysis
    assert "sw-meter" not in repeat_analysis
    assert "<span>Pass ' + p.pass_number + '</span>" in repeat_analysis
    assert ">Errors</th>" in source
    assert ">Avg lat</th>" not in source
    assert ">Err</th>" not in source
    assert ".samples-correct-col" in source
    assert "height: 230px;" in _rule(source, ".samples-curve {")
    assert "height: 230px;" in _rule(source, ".samples-correct-chart {")
    assert "border-bottom:" not in _rule(source, ".samples-correct-chart {")
    assert "const paddedSpan = Math.max(0.2, observedSpan * 1.4);" in repeat_analysis
    assert "const yTicks = Array.from({ length: 5 }" in repeat_analysis
    assert "with y-axis from" in repeat_analysis
    assert "samples-curve-value" in repeat_analysis
    assert "ri-point-value" in source
    assert "formatPercent(value, 0)" in source
    assert "labelOffset: 14" in source
    paired_chart_rule = _rule(source, ".samples-charts-row > .samples-chart-block {")
    assert "align-self: stretch;" in paired_chart_rule
    assert "height: 100%;" in paired_chart_rule


def test_shared_latency_formatter_normalizes_minute_rollover() -> None:
    source = METRICS_JS.read_text(encoding="utf-8")

    assert "const totalSeconds = Math.round(ms / 1000);" in source
    assert "const seconds = totalSeconds % 60;" in source
    assert "return seconds ? `${minutes}m ${seconds}s` : `${minutes}m`;" in source


def test_run_detail_includes_non_redundant_intelligence_charts() -> None:
    source = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    active = source.split("function buildDeepAnalysisCharts(rows)", 1)[1].split("function renderOverview", 1)[0]

    assert "function buildDeepAnalysisCharts(rows)" in source
    assert "Metric Relationships" in active
    assert "Metric Correlation" in active
    assert "Metric Relationship" in active
    assert "Quality and Latency" in active
    assert "Quality–Latency Frontier" in active
    assert "Fast + strong zone" in active
    assert "Slow + weak zone" in active
    assert "Dot size = retries" in active
    assert "ri-frontier-line p95" in active
    assert "p95 latency" in active
    assert "Latency median" in active
    assert "medianQuality" in active
    assert "ri-frontier-outlier" in active
    assert "outlierItems" in active
    assert "const p95X = plotRight - outlierBandWidth;" in active
    assert "Dashed = medians · dotted = p95 latency" not in active
    assert 'r="3.5" fill="var(--chart-1)"' in active
    assert "const radius = 3.5 + Math.min(2" in active
    assert 'stroke-width="1.5"' in active
    assert "Repeat Stability" in active
    assert "Quality–Stability Map" in active
    assert "Threshold Explorer" in active
    assert "Score Estimate by Pass Count" in active
    assert "ri-x-axis" in active
    assert "ri-y-axis" in active
    assert "repeatAnalysisMetric" in source
    assert "repeatStabilityHiddenMetrics" in source
    assert "data-ri-repeat-metric" in active
    assert "data-ri-stability-metric" in active
    assert "ri-legend-toggle" in active
    assert "if (visibleCount <= 1) return;" in source
    assert "const thresholdMetric = repeatMetric;" in active
    assert "state.repeatAnalysisMetric = select.value;" in source
    assert "rotateMatrixLabels" in active
    assert "const rotateMatrixLabels = series.length > 4;" in active
    assert "truncateMatrixLabel" in active
    assert "const top = series.length <= 4 ? 42 : 58;" in active
    assert 'text-anchor="middle" class="ri-label"' in active
    shared_box_rule = _rule(source, ".metric-card,")
    assert ".samples-group-tiles .model-stat-box," in shared_box_rule
    assert ".ri-panel," in shared_box_rule
    assert ".breakdown-card" in shared_box_rule
    assert "background: var(--bg-surface);" in _rule(source, ".ri-axis-select {")
    assert "Item Performance Matrix" not in active
    assert "Observed Performance by Pass" not in active
    assert "intelligenceCharts +" in source
    assert "const intelligenceCharts = buildDeepAnalysisCharts(rows);" in source
    assert "radar" not in source.lower()


def test_run_item_detail_offers_virtualized_repeat_heatmap() -> None:
    source = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")

    assert "itemDetailView: 'cards'" in source
    assert "itemsViewToggle.hidden = samplesTotal <= 1" in source
    assert "if (samplesTotal <= 1) state.itemDetailView = 'cards';" in source
    assert ".items-view-toggle[hidden] { display: none; }" in source
    assert 'data-items-view="cards"' in source
    assert 'data-items-view="heatmap"' in source
    assert "function renderItemsHeatmap(container, items, metric, metricIndex)" in source
    assert 'class="item-heatmap-viewport"' in source
    assert "Math.floor(viewport.scrollTop / rowHeight)" in source
    assert "Only visible rows are rendered" in source


def test_run_category_breakdown_keeps_cards_and_adds_repeat_aware_compare_view() -> None:
    source = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")

    assert "categoryBreakdownView: 'cards'" in source
    assert "function getCategoryMetricScores(row, metric, metricIndex)" in source
    assert "row.pass_scores[metric]" in source
    assert "if (!state.viewPass" in source
    assert 'data-category-view="cards"' in source
    assert 'data-category-view="compare"' in source
    assert 'class="category-breakdown-context"' not in source
    assert 'id="category-breakdown-sort"' not in source
    assert 'class="score-col-performance"' in source
    assert "performanceLabel = sameDisplay ? 'Avg · pass rate' : 'Avg / pass rate';" in source
    assert 'class="breakdown-pass-summary"' not in source
    assert 'class="category-pass-track' in source
    assert 'class="category-compare-row"' in source
    assert "Run pass rate &middot;" in source
    assert "data-category-expand" in source
    assert "metricType !== 'numeric'" in source


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
