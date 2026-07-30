from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_JS = ROOT / "packages" / "platform" / "qym_platform" / "_static" / "dashboard" / "dashboard.js"
DASHBOARD_DIR = ROOT / "packages" / "platform" / "qym_platform" / "_static" / "dashboard"
METRICS_JS = DASHBOARD_DIR / "metrics.js"
DOCS_JS = DASHBOARD_DIR / "docs.js"
DOCS_CSS = DASHBOARD_DIR / "docs.css"
RUNS_API = ROOT / "packages" / "platform" / "qym_platform" / "api" / "runs.py"
ANALYSIS_API = ROOT / "packages" / "platform" / "qym_platform" / "api" / "analysis.py"


def test_docs_page_switch_is_atomic_and_layout_stable() -> None:
    source = DOCS_JS.read_text(encoding="utf-8")
    styles = DOCS_CSS.read_text(encoding="utf-8")

    assert "if (!els.content.childElementCount)" in source
    assert "var requestSequence = ++loadSequence;" in source
    assert "if (requestSequence !== loadSequence) return;" in source
    assert "els.content.removeAttribute('aria-busy');" in source
    assert "event.preventDefault();" in source
    assert "history.pushState(null, '', href);" in source
    assert "document.addEventListener('qym:popstate'" in source
    assert ".shell-content { scrollbar-gutter: stable; }" in styles
    assert styles.count("scrollbar-gutter: stable;") >= 3


def _rule(css: str, selector: str) -> str:
    """The body of the first CSS block that starts with `selector`."""
    start = css.index(selector)
    return css[start:css.index("}", css.index("{", start)) + 1]


def test_dashboard_delete_action_binding_allows_non_deletable_runs() -> None:
    source = DASHBOARD_JS.read_text(encoding="utf-8")

    assert "const deleteBtn = tr.querySelector('.delete-run');" in source
    assert "if (deleteBtn) deleteBtn.addEventListener('click'" in source
    assert "tr.querySelector('.delete-run').addEventListener" not in source


def test_empty_dashboard_links_to_first_run_docs() -> None:
    markup = (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8")
    source = DASHBOARD_JS.read_text(encoding="utf-8")

    assert 'id="empty-docs-link"' in markup
    assert 'href="/docs-guide#get-started/first-run"' in markup
    assert "qym --task-file my_task.py" not in markup
    assert "emptyDocsLink.href = apiUrl('docs-guide#get-started/first-run');" in source


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
    assert 'class="samples-metric-select"' in source
    assert source.index('class="samples-metric-select"') < source.index(
        'class="threshold-slider-inline samples-threshold-slider"'
    )
    assert "state._samplesMetric[runId] = metricSelect.value;" in source
    assert "params.set('metric', metric);" in source
    assert "const controlsRow = inserted.find" in source
    metric_select_rule = _rule(styles, ".samples-metric-select {")
    assert "box-sizing: border-box;" in metric_select_rule
    assert "height: var(--space-lg);" in metric_select_rule
    assert "max-width: 112px;" in metric_select_rule
    assert "font-size: var(--font-sm);" in metric_select_rule
    assert "line-height: 1;" in metric_select_rule
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
    assert "pass.trace_stats?.[tm.key]" in source
    assert (
        "const passDate = pass.started_at ? formatDate(pass.started_at) : null;"
        in source
    )
    assert "formatDurationMs(pass.duration_ms)" in source
    assert (
        "return passRows.map((pass, i) => memberRow(pass, i === passRows.length - 1)).join('') + strip;"
        in source
    )
    assert ".runs-table > tbody > tr.pass-member > td:first-child" in styles
    assert ".pass-member .tag," in styles

    # best-in-column chips across sibling passes (same dialect as the run
    # page's pass sweep): max wins for metrics, min wins for latencies
    assert "winnersFor(p => (p.metric_means || {})[metric], 'max')" in source
    assert "const avgLatencyWinners = winnersFor(p => p.avg_latency_ms, 'min');" in source
    assert "const medianLatencyWinners = winnersFor(p => p.median_latency_ms, 'min');" in source
    assert "const chipAttrs = (winners, passNumber) =>" in source
    assert "Tied for best across passes" in source
    chip_rule = _rule(styles, ".pass-member .sw-best {")
    assert "display: inline-block;" in chip_rule
    # zero left padding: the chip stays flush with the column's left alignment
    # edge, so the tint never crosses under the header
    assert "padding: 2px 8px 2px 0;" in chip_rule
    assert "margin: -2px 0;" in chip_rule
    assert "background: color-mix(in srgb, var(--success) 14%, transparent);" in chip_rule
    tied_chip_rule = _rule(styles, ".pass-member .sw-best.sw-tied {")
    assert "box-shadow: inset 0 0 0 1px" in tied_chip_rule

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
    assert source.count("const repeatSeries = state.viewPass ? [] :") == 1
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
    assert "inset 0 0 0 2px color-mix(in srgb, var(--warning) 65%" in source
    assert "0 0 4px color-mix(in srgb, var(--warning) 25%" in source
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
    dashboard_js = DASHBOARD_JS.read_text(encoding="utf-8")
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
    assert "const finalRepeatPoint = group.band?.[samplesCount]" in source
    assert "statTile(estimatorLabel('@'), estActive ? g.pass_at_k : finalPassAtK" in source
    assert "statTile(estimatorLabel('^'), estActive ? g.pass_hat_k : finalPassHatK" in source

    # sweep rows deep-link to that pass's page (cmd/ctrl-click opens a tab)
    assert "'<tr data-sw-pass=\"' + p.pass_number + '\"" in source
    assert "window.location.pathname + '?pass=' + tr.dataset.swPass" in source
    assert ".samples-sweep tbody tr[data-sw-pass] { cursor: pointer; }" in source

    # the curve draws at the measured box size (no fixed-viewBox letterboxing)
    assert "function curveChartHtml(W = 620, H = 230)" in source
    assert "function fitCurveChart()" in source
    assert "requestAnimationFrame(fitCurveChart)" in source
    assert "flex: none;" in _rule(source, ".samples-curve {")
    assert "statTile('Errors'" in source
    assert "statTile('Avg Latency'" in source
    assert source.index("statTile('Avg Latency'") < source.index("statTile('Errors'")
    assert '<div class="samples-zone-title">Repeat Performance</div>' in repeat_analysis
    assert "data-samples-statistic" in repeat_analysis
    assert "{ key: 'compare', label: 'Compare'" in repeat_analysis
    assert "class=\"samples-statistic-tabs\" role=\"tablist\"" in repeat_analysis
    assert "class=\"samples-statistic-btn" in repeat_analysis
    assert "samples-statistic-select" not in source
    assert "samplesStatistic: 'compare'" in source
    assert "Pass@k" in repeat_analysis
    assert "Pass^k" in repeat_analysis
    assert "{ key: 'cumulative_avg', label: 'Average'" in repeat_analysis
    assert "divergencePath" not in repeat_analysis
    assert ">divergence<" not in repeat_analysis
    assert "visibleKeys.map(key => intervalPathFor(key, isComparison ? 0.08 : 0.12))" in repeat_analysis
    assert "const whiskersFor = key =>" not in repeat_analysis
    assert "Attempts allowed" in repeat_analysis
    assert "Passes observed" in repeat_analysis
    assert "95% uncertainty" in repeat_analysis
    assert "Uncertainty when generalizing to another comparable set" in repeat_analysis
    assert "Items by exact correct-pass count." in repeat_analysis
    assert "Repeat Stability" in repeat_analysis
    assert "Quality–Stability Map" in repeat_analysis
    assert "if (!isBool && groupMetricType !== 'numeric'" in repeat_analysis
    assert "Threshold Explorer" in repeat_analysis
    assert 'fill="var(--success-dim)"' not in repeat_analysis
    shared_box_rule = _rule(source, ".metric-card,")
    assert ".samples-chart-block," in shared_box_rule
    assert "background: var(--bg-surface);" in shared_box_rule
    assert "border: 1px solid var(--border-default);" in shared_box_rule
    assert "border-radius: 10px;" in shared_box_rule
    shared_hover_rule = _rule(source, ".metric-card:hover,")
    assert ".samples-group-tiles .model-stat-box:hover" in shared_hover_rule
    assert ".samples-sweep-wrap:hover" in shared_hover_rule
    assert ".samples-chart-block:hover" in shared_hover_rule
    assert ".ri-panel:hover" in shared_hover_rule
    assert ".breakdown-card:hover" in shared_hover_rule
    assert "border-color: var(--border-strong);" in shared_hover_rule
    assert "box-shadow: 0 2px 16px rgba(0, 0, 0, 0.12);" in shared_hover_rule
    assert "⚡ Avg Latency" in source
    assert "⚡ Median Latency" in source
    assert "P95 Latency" not in repeat_analysis
    assert "p.p95_latency_ms" not in repeat_analysis
    assert "const winnersFor = (valueOf, direction) =>" in source
    assert "winnersFor(p => (p.metric_means || {})[m], 'max')" in source
    assert "const avgLatencyWinners = winnersFor(p => p.avg_latency_ms, 'min');" in source
    assert "const medianLatencyWinners = winnersFor(p => p.median_latency_ms, 'min');" in source
    assert "const errorWinners = winnersFor(p => Number(p.error_count || 0), 'min');" in source
    assert "if (values.every(entry => entry.value === best)) return new Set();" in source
    assert "sw-winner-badge" not in source
    assert "sw-winner-cell" not in source
    assert "Best across passes" in source
    assert "Tied for best across passes" in source
    assert "display: block;" in _rule(source, ".sw-cell-value {")
    best_rule = _rule(source, ".sw-cell-value.sw-best {")
    assert "display: inline-block;" in best_rule
    # zero right padding: the chip stays flush with the column's right
    # alignment edge, so the tint never crosses under the header
    assert "padding: 2px 0 2px 8px;" in best_rule
    assert "margin: -2px 0;" in best_rule
    assert "background: color-mix(in srgb, var(--success) 14%, transparent);" in best_rule
    tied_rule = _rule(source, ".sw-cell-value.sw-best.sw-tied {")
    assert "background: color-mix(in srgb, var(--success) 7%, transparent);" in tied_rule
    assert "box-shadow: inset 0 0 0 1px" in tied_rule
    assert "sw-meter" not in repeat_analysis
    assert "<span>Pass ' + p.pass_number + '</span>" in repeat_analysis
    assert ">Errors</th>" in source
    assert ">Avg lat</th>" not in source
    assert ">Err</th>" not in source
    assert ".samples-correct-col" in source
    assert "height: 260px;" in _rule(source, ".samples-curve {")
    assert "height: 230px;" in _rule(source, ".samples-correct-chart {")
    assert "border-bottom:" not in _rule(source, ".samples-correct-chart {")
    assert "const tickStep = observedSpan > 0.8 ? 0.2 : 0.1;" in repeat_analysis
    assert "Math.floor((observedMin - padding) / tickStep)" in repeat_analysis
    assert "Math.ceil((observedMax + padding) / tickStep)" in repeat_analysis
    assert "yTicks = Array.from({ length: tickCount + 1 }" in repeat_analysis
    assert "statisticInterval" in repeat_analysis
    assert "intervalPath" in repeat_analysis
    assert "samples-band-table-wrap" in repeat_analysis
    assert "samples-band-cell-ci" in repeat_analysis
    assert "±" in repeat_analysis
    assert "{ key: 'cumulative_avg', label: 'Average' }" in repeat_analysis
    assert "samples-curve-value" in repeat_analysis
    assert "ri-point-value" in source
    assert "formatPercent(value, 0)" in source
    assert "labelOffset: 14" in source
    paired_chart_rule = _rule(source, ".samples-charts-row > .samples-chart-block {")
    assert "align-self: stretch;" in paired_chart_rule
    assert "height: auto;" in paired_chart_rule
    assert "max-width:" not in _rule(source, ".samples-charts-row {")
    assert "max-width:" not in _rule(source, ".samples-stability-section {")
    assert "max-width:" not in _rule(source, ".ri-insights {")
    assert "grid-template-columns: minmax(0, 2fr) minmax(320px, 1fr);" in _rule(source, ".samples-charts-row.with-distribution {")
    assert "const stabilityPanelsHtml = stabilityMapHtml + thresholdExplorerHtml;" in repeat_analysis
    assert "(distBlockHtml ? ' with-distribution' : '')" in repeat_analysis
    assert "distBlockHtml +" in repeat_analysis
    assert 'stabilityMapHtml = \'<div class="ri-panel half"' in repeat_analysis
    assert "metric_cis" not in dashboard_js
    assert "metric-ci" not in dashboard_js


def test_shared_latency_formatter_normalizes_minute_rollover() -> None:
    source = METRICS_JS.read_text(encoding="utf-8")

    assert "const totalSeconds = Math.round(ms / 1000);" in source
    assert "const seconds = totalSeconds % 60;" in source
    assert "return seconds ? `${minutes}m ${seconds}s` : `${minutes}m`;" in source


def test_run_detail_includes_non_redundant_intelligence_charts() -> None:
    source = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    active = source.split("function buildDeepAnalysisCharts(rows)", 1)[1].split("function renderOverview", 1)[0]

    assert "function buildDeepAnalysisCharts(rows)" in source
    assert "Metric Correlation" in active
    assert "Metric Relationship" in active
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
    assert "Repeat Stability" not in active
    assert "Score Estimate by Pass Count" not in active
    assert "ri-x-axis" in active
    assert "ri-y-axis" in active
    assert "samplesStatistic" in source
    assert "repeatAnalysisMetric" not in source
    assert "repeatStabilityHiddenMetrics" not in source
    assert "data-ri-repeat-metric" not in active
    assert "data-ri-stability-metric" not in active
    assert "ri-legend-toggle" not in active
    assert "state.samplesMetric = nextMetric;" in source
    assert "renderOverview(getFilteredItems());" in source
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
    assert "const deepPanels = relationshipPanels.concat(frontierPanel ? [frontierPanel] : []);" in active
    assert 'class="ri-grid deep-analysis-grid"' in active
    assert 'relationshipPanels.push(\'<div class="ri-panel">' in active
    assert 'frontierPanel = \'<div class="ri-panel">' in active
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
    assert "Avg · pass rate" not in source
    assert "Avg / pass rate" not in source
    assert 'class="breakdown-pass-summary"' not in source
    assert 'class="category-pass-track' in source
    assert "function categoryScoreTrack(score, baseline)" in source
    assert "categoryScoreTrack(group.avgScore, overallAverage)" in source
    assert 'class="category-compare-row"' in source
    assert "<span>Pass rate</span>" not in source
    assert "<span>Rate</span>" not in source
    assert "const metric = state.samplesMetric || state.selectedMetric || state.allMetrics[0];" in source
    assert "Overall metric average score" in source
    assert 'class="category-baseline-score"' in source
    assert "renderMetadataBreakdown();" in source
    assert "'Overall run mean'" not in source
    assert "'Filtered mean'" not in source
    assert "scored results from" not in source
    assert "items across" not in source
    assert "scored items in Pass" not in source
    track_rule = _rule(source, ".category-pass-track {")
    marker_rule = _rule(source, ".category-pass-track.has-baseline::after {")
    assert "background: var(--bg-elevated);" in track_rule
    assert "width: 2px;" in marker_rule
    assert "background: var(--text-secondary);" in marker_rule
    assert "<span>| ' + baselineScope" not in source
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


def test_auto_analysis_is_a_first_class_project_page() -> None:
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    analyzer = (DASHBOARD_DIR / "analyzer.html").read_text(encoding="utf-8")
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
    playground = (DASHBOARD_DIR / "playground.js").read_text(encoding="utf-8")
    shell = (DASHBOARD_DIR / "shell.js").read_text(encoding="utf-8")
    routes = RUNS_API.read_text(encoding="utf-8")
    analysis_api = ANALYSIS_API.read_text(encoding="utf-8")

    assert "openAnalyzerPage" in run
    assert "QymPlayground.open()" not in run
    assert "projectUrl(CURRENT_PROJECT_SLUG, 'analysis')" in run
    assert "buildNavItem('Auto-analysis', 'analysis', 'analysis'" in shell
    assert "else if (rest === 'analysis') page = 'analysis';" in shell
    assert 'id="analysis-run-select"' not in analyzer
    assert "api/runs?limit=200&project_slug=" not in analyzer
    assert "api/runs?limit=1&project_slug=" in analyzer
    assert "Select a run to start analysis" in analyzer
    assert "Select a run from Runs" in analyzer
    assert "Production rules and Documents remain available" in analyzer
    assert "if (!runId) {" in analyzer
    assert "getRunId: () => state.contextRunId" in analyzer
    assert 'id="analyzer-host"' in analyzer
    assert "container: document.getElementById('analyzer-host')" in analyzer
    assert 'id="pg-project-description"' not in playground
    assert 'class="pg-context-panel"' in playground
    assert 'id="pg-rule-list"' in playground
    assert 'id="pg-rule-count"' in playground
    assert "function _formatRuleCount()" in playground
    assert "no rule count limit" in playground
    assert "_MAX_ANALYSIS_RULES" not in playground
    assert "_analysisRules.push({ title: '', instruction: '' });" in playground
    assert 'id="pg-infer-rules"' in playground
    assert 'id="pg-update-rules"' in playground
    assert 'id="pg-infer-use-description"' not in playground
    assert 'id="pg-infer-use-documents"' in playground
    assert 'id="pg-infer-use-examples"' in playground
    assert "include_project_description" not in playground
    assert "include_documents: inferenceSources.include_documents" in playground
    assert "include_examples: inferenceSources.include_examples" in playground
    assert "mode: mode" in playground
    assert 'id="pg-rule-version-list"' in playground
    assert 'id="pg-create-rule-version"' in playground
    assert 'pg-rule-compare-stats' in playground
    assert 'pg-rule-compare-group' in playground
    assert 'pg-rule-compare-picker' in playground
    assert '<details class="pg-rule-inference-options">' in playground
    assert 'pg-rule-inference-content' in playground
    assert 'pg-infer-source-summary' in playground
    assert '2 of 2 sources enabled' in playground
    assert "function _syncInferenceSourceSummary()" in playground
    assert 'pg-context-action-group' in playground
    assert 'pg-context-action-divider' in playground
    assert 'pg-context-feedback' in playground
    assert "function _renderRuleViewStatus()" in playground
    assert "function _showContextFeedback(message, isError)" in playground
    assert '3500' in playground
    assert "Create a draft to edit rules" in playground
    assert "Create a draft to add rules" in playground
    assert "panel.classList.add('pg-rule-compare-picker')" in playground
    assert "panel.classList.remove('pg-rule-compare-picker')" in playground
    assert 'pg-rule-compare-backdrop' in playground
    assert 'role="dialog"' in playground
    assert "event.key !== 'Escape'" in playground
    assert "function _createRuleDraft(fromVersionId)" in playground
    assert "var sourceVersionId = fromVersionId || _selectedRuleVersionId;" in playground
    assert "Select an available version before creating a draft." in playground
    assert "from_version: String(selected.id)" in playground
    assert "_createRuleDraft(selected.id)" in playground
    assert "function _ruleVersionStateLabel(version)" in playground
    assert "return 'Live';" in playground
    assert "return 'Draft';" in playground
    assert "return 'Published';" in playground
    assert "function _renderRuleCompareDialog(panel, content)" in playground
    assert "function _mountRuleComparePortal(panel)" in playground
    assert "document.body.appendChild(panel)" in playground
    assert "function _closeRuleCompareDialog(panel)" in playground
    assert "function _wireRuleVersionSearch(panel, selectSelector, searchSelector, emptySelector)" in playground
    assert "data-rule-' + key + '-search" in playground
    assert "data-rule-' + key + ' value=" in playground
    assert 'class="pg-rule-version-option' in playground
    assert 'role="option"' in playground
    assert "pg-rule-version-option-selected" in playground
    assert "No matching versions." in playground
    assert "function _publishRuleVersion(versionId)" in playground
    assert "function _openRuleMerge(targetId)" in playground
    assert "function _openRuleCompare(versionId)" in playground
    assert "if (versionId && (activate || publish || merge || compare || remove))" in playground
    assert "_openRuleVersion(versionId);" in playground
    assert "data-merge-rule-version" in playground
    assert "data-rule-version-menu-toggle" in playground
    assert "Compare with…" in playground
    assert "Merge with…" in playground
    assert "_icon('check')" in playground
    assert "_icon('upload')" in playground
    assert 'M5 14v6h14v-6' in playground
    assert "_icon('rocket')" in playground
    assert "_icon('checkFilled')" in playground
    assert 'pg-rule-version-lifecycle-label' in playground
    assert '>Publish</span>' in playground
    assert '>Promote</span>' in playground
    assert '>Live</span>' in playground
    assert "_icon('merge')" in playground
    assert "M6 4v4c0 4 2 6 6 6h6" in playground
    assert "candidate.is_active;" in playground
    assert "rule_version_id: _selectedRuleVersionId" in playground
    assert "data-activate-rule-version" in playground
    assert "data-publish-rule-version" in playground
    assert "data-compare-rule-version" in playground
    assert "data-delete-rule-version" in playground
    assert "_confirmRuleVersionDeletion" in playground
    assert "Delete version" in playground
    assert "confirmClass: 'shell-btn-danger'" in playground
    assert "window.confirm('Delete this rule version?" not in playground
    assert "This action cannot be undone." in playground
    assert "liveVersionCount > 1" in playground
    assert "openFormDialog" in playground
    assert "Set as production" in playground
    assert 'pg-rule-compare-picker' in analyzer
    assert 'width: min(680px, 100%)' in analyzer
    assert 'position: fixed' in analyzer
    assert 'place-items: center' in analyzer
    assert 'grid-template-columns: minmax(0, 1fr)' in analyzer
    assert 'analysis-info-popover' in analyzer
    assert 'analysis-rule-view-state' in analyzer
    assert 'analysis-rule-version-meta' in analyzer
    assert 'analysis-version-node-key' in analyzer
    assert "_renderRuleVersionMeta(selected)" in playground
    assert "label: 'Created at'" in playground
    assert "label: 'Updated at'" in playground
    assert "version.created_by.display_name" in playground
    assert '-webkit-line-clamp: 2' in analyzer
    assert "window.confirm(" not in playground
    assert "window.prompt(" not in playground
    assert "window.alert(" not in playground
    assert "to production" in playground
    assert "_openRuleVersion(versionRow.dataset.ruleVersionId)" in playground
    assert "data-toggle-rule" in playground
    assert "_editingRuleIndex === toggleIndex ? null : toggleIndex" in playground
    assert "function _readAnalysisRuleDraftsFromEditor()" in playground
    assert "_analysisRules = _readAnalysisRuleDraftsFromEditor();" in playground
    assert "function _validateAnalysisRuleDrafts()" in playground
    assert "Complete the title and instruction for every rule before saving." in playground
    assert "Removing rule from the current version" in playground
    assert "_saveAnalysisContext().catch(function () {" in playground
    assert "cfg.project_description" not in playground
    assert "cfg.analysis_rules = rules" in playground
    assert 'id="pg-document-input"' in playground
    assert "cfg.include_project_documents = documentsToggle.checked" in playground
    assert "'/analysis-documents'" in playground
    assert "Project documents" in playground
    assert "_updateReferenceDocumentSelection" in playground
    assert 'class="pg-document-select"' in playground
    assert "_deleteReferenceDocument" in playground
    assert '@router.get("/api/runs/{run_id:path}/analysis-documents")' in analysis_api
    assert '@router.patch("/api/runs/{run_id:path}/analysis-documents/{document_id}")' in analysis_api
    assert '@router.delete("/api/runs/{run_id:path}/analysis-documents/{document_id}")' in analysis_api
    assert "_MAX_REFERENCE_DOCUMENTS" not in playground
    assert "5 documents" not in playground
    assert "_validateProjectDescription" not in playground
    assert '@router.get("/projects/{project_slug}/analysis"' in routes
    assert '@router.get("/projects/{project_slug}/runs/{run_id:path}/analyzer"' in routes
    assert '@router.post("/api/runs/{run_id:path}/analysis-documents")' in analysis_api
    assert '@router.patch("/api/runs/{run_id:path}/analysis-context")' in analysis_api
    assert '@router.post("/api/runs/{run_id:path}/analysis-rules/infer")' in analysis_api
    assert '"/api/runs/{run_id:path}/analysis-rule-versions/{version_ref}:publish"' in analysis_api
    assert '"/api/runs/{run_id:path}/analysis-rule-versions/{version_ref}:compare"' in analysis_api
    assert '"/api/runs/{run_id:path}/analysis-rule-aliases/{alias_name}"' in analysis_api
    assert '"/api/runs/{run_id:path}/analysis-rule-versions/{version_id}/activate"' in analysis_api
    assert "metric_analyses" in run
    assert "Per-metric root cause analysis" in run
    assert "legacyMetric && md.root_cause_source !== 'human'" in run
    assert "!isValid(metricAnalyses[legacyMetric])) return [];" in run
    assert "rootCauseHtml" not in run
    assert "'<div class=\"rc-sol-row\">'" not in run
    assert 'data-metric-rc-item=' in run
    assert 'data-metric-rcdetail-item=' in run
    assert 'data-metric-feedback-item=' in run
    assert 'data-metric-sol-item=' in run
    assert "saveMetricAnalysisPatch" in run
    assert "metric_name: metricName" in run
    assert "if (!hasStoredAnalysis && !metricFailed) return '';" in run
    assert "(analysis.root_cause || '+ Category')" in run
    assert "'>Edit</button>'" not in run
    assert 'id="analysis-metric-list"' in analyzer
    assert "getMetrics: () => state.selectedMetrics.slice()" in analyzer
    assert "body.metrics = _getSelectedMetrics()" in playground
    assert "getMetric: function () { return null; }" in compare
    assert "row.item_metadata.metric_analyses[result.metric_name]" in compare
    assert '"type": "aggregating"' in analysis_api
    assert "evt.type === 'aggregating'" in playground
    assert "Aggregating root causes\\u2026" in playground
    assert "labels consolidated" in playground
    assert 'id="pg-target-limit"' in playground
    assert 'id="pg-target-limit-decrease"' not in playground
    assert 'id="pg-target-limit-increase"' not in playground
    assert 'maxlength="4"' in playground
    assert 'placeholder="All"' in playground
    assert "Empty = all" not in playground
    assert "pg-target-limit-help" not in playground
    assert "slice(0, 4)" in playground
    assert ".analysis-page .pg-score-slider::-webkit-slider-runnable-track" in analyzer
    assert "grid-template-columns: 260px max-content max-content;" in analyzer
    assert "width: 96px;" in analyzer
    assert 'id="pg-connection-trigger"' in playground
    assert 'id="pg-connection-menu"' in playground
    assert "body.limit = requestedLimit" in playground
    assert "'pg-use-project-description'" not in analyzer
    assert "'pg-use-project-rules'" in analyzer
    assert "'pg-use-project-documents'" in analyzer
    assert 'id="analysis-mapping-open"' in analyzer
    assert ">Input mapping</button>" in analyzer
    assert "Advanced run configuration" not in analyzer
    assert "state.wizardStep" not in analyzer


def test_playground_pages_load_matching_asset_revisions() -> None:
    for page_name in ("analyzer.html", "compare.html"):
        source = (DASHBOARD_DIR / page_name).read_text(encoding="utf-8")
        dashboard_revision = re.search(
            r'dashboard\.css\?v=([^"]+)',
            source,
        )
        playground_revision = re.search(
            r'playground\.js\?v=([^"]+)',
            source,
        )

        assert dashboard_revision is not None
        assert playground_revision is not None
        assert dashboard_revision.group(1) == playground_revision.group(1)


def test_auto_analysis_page_uses_first_class_run_rules_and_document_tabs() -> None:
    analyzer = (DASHBOARD_DIR / "analyzer.html").read_text(encoding="utf-8")
    playground = (DASHBOARD_DIR / "playground.js").read_text(encoding="utf-8")
    styles = (DASHBOARD_DIR / "dashboard.css").read_text(encoding="utf-8")

    assert "Auto-analysis views" in analyzer
    assert "Project configuration" not in analyzer
    assert "Analyze run" in analyzer
    assert "Analyze this run" not in analyzer
    assert "Choose another run" not in analyzer
    assert ">Select all</button>" in analyzer
    assert ">Clear</button>" in analyzer
    assert 'class="analysis-run-context" aria-label="Run information"' in analyzer
    assert 'analysis-run-context-label">Run ID' not in analyzer
    assert "Production rules" in analyzer
    assert ">Documents</button>" in analyzer
    assert 'role="tablist"' in analyzer
    assert 'id="analysis-rules-tab"' in analyzer
    assert 'id="analysis-documents-tab"' in analyzer
    assert 'id="analysis-run-tab"' in analyzer
    assert 'id="analysis-diagnosis-tab"' in analyzer
    assert 'aria-controls="analysis-diagnosis-view"' in analyzer
    assert 'aria-disabled="true" disabled' in analyzer
    assert "setAnalyzerView(state.currentView" in analyzer
    assert "nextParams.set('scope', nextView)" in analyzer
    assert "Project documents" in analyzer
    assert 'data-context-view="\' + item[3] + \'"' in analyzer
    assert "analysisViewUrl(item[3])" in analyzer
    assert "setAnalyzerView(link.dataset.contextView, { focus: true })" in analyzer
    assert "organizeAnalyzerWorkspace()" in analyzer
    assert "organizeWhenReady()" in analyzer
    assert "new MutationObserver" in analyzer
    assert "['overview', 'Overview']" not in analyzer
    assert "documentsPanel.append" in analyzer
    assert "Advanced run configuration" not in analyzer
    assert "buildInputMappingDialog(mapping)" in analyzer
    assert "buildAdvancedDialog" not in analyzer
    assert "diagnosisTab.disabled = false" in analyzer
    assert "diagnosisBody.append(catalog)" in analyzer
    assert "diagnosisPanel.append(diagnosisHeader, diagnosisBody)" in analyzer
    assert "diagnosisCard" not in analyzer
    assert 'id="analysis-category-count"' in analyzer
    assert 'id="analysis-example-count"' in analyzer
    assert "data-example-count" in playground
    assert "category_examples" in playground
    assert "Approved examples" in playground
    assert "No approved examples in this category yet." in playground
    assert "Remove category from this analysis" in playground
    assert "pg-category-example-data" in playground
    assert "instructionsBody.append(instructions)" in analyzer
    assert analyzer.index("runPanel.append(instructionsCard)") < analyzer.index("runPanel.append(targetCard)")
    assert "max-height: 420px" in analyzer
    assert "max-height: 640px" in analyzer
    assert "grid-template-columns: minmax(220px, 0.46fr) minmax(0, 1.54fr);" in analyzer
    footer_style = analyzer.split(".analysis-project-footer {", 1)[1].split("}", 1)[0]
    assert "position: fixed" not in footer_style
    assert "border-top: 1px solid var(--border-subtle);" in footer_style
    assert ".analysis-page .playground-page-overlay" in analyzer
    assert "projectPanel.append(rulesPanel, documentsPanel)" in analyzer
    assert "rulesWorkspaceCard.append(projectFooter)" in analyzer
    assert "documentsPanel.append(uploadCard, libraryCard)" in analyzer
    assert "runPanel.append(targetCard)" in analyzer
    assert "newRuleTitle.scrollIntoView" in playground
    assert 'class="pg-hl-category" style="color:' not in playground
    assert "pg-hl-rule-title" in playground
    assert ".pg-hl-rule-title { color: var(--accent-primary);" in styles

    # The shared Compare modal keeps using the untouched controller markup;
    # the dedicated page applies its organization only after page-mode render.
    assert "analysis-scope-card" not in playground
    assert "analysis-document-scope-note" not in playground


def test_root_cause_breakdowns_support_metric_scoping() -> None:
    for page_name in ("run.html", "compare.html"):
        source = (DASHBOARD_DIR / page_name).read_text(encoding="utf-8")

        assert "rootCauseMetric: 'all'" in source
        assert 'id="root-cause-metric-select"' in source
        assert ">All</option>" in source
        assert "getRowRootCauseAnalyses(row, state.rootCauseMetric)" in source
        assert "analysis.root_cause_detail" in source
        assert "renderSankeyDiagram" in source


def test_shell_and_run_detail_normalize_trailing_slashes_before_route_parsing() -> None:
    shell = (DASHBOARD_DIR / "shell.js").read_text(encoding="utf-8")
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")

    assert "if (typeof window.__QYM_ROOT_PATH__ === 'string')" in shell
    assert "return configuredRoot ? configuredRoot + '/' : '/';" in shell
    assert "const path = rawPath.length > 1 ? rawPath.replace(/\\/+$/, '') : rawPath;" in shell
    assert "const pathname = rawPathname.length > 1 ? rawPathname.replace(/\\/+$/, '') : rawPathname;" in shell
    assert "const path = rawPath.length > 1 ? rawPath.replace(/\\/+$/, '') : rawPath;" in run
