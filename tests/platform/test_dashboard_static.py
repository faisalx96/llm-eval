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


def test_repeat_run_rows_are_ordinary_rows_with_pass_count_chip() -> None:
    """×k rows read as ordinary data rows: no special surface, no dot
    strip — the chevron and the pass-count chip carry the signal."""
    source = DASHBOARD_JS.read_text(encoding="utf-8")
    styles = (DASHBOARD_DIR / "dashboard.css").read_text(encoding="utf-8")

    assert 'class="run-pass-count"' in source
    assert "${run.samples} passes" in source
    # the dot strip and the special row surface are gone
    assert "renderPassDots" not in source
    assert "repeat-run-header" not in source
    assert "repeat-run-header" not in styles
    assert ".pdot" not in styles
    assert ".pass-dots" not in styles

    assert ".run-pass-count" in styles


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

    # leading disclosure chevron before the run name (mock C's toggle), the
    # pass-count chip after it, and a spacer aligning chevron-less rows
    toggle_at = source.index('class="samples-toggle qym-icon-action${samplesOpen')
    run_id_at = source.index('<span class="run-id"', toggle_at)
    assert toggle_at < run_id_at < source.index('class="run-pass-count"', toggle_at)
    assert 'class="samples-toggle-spacer"' in source
    assert "headerRow.classList.toggle('has-repeat-rows', anyRepeatRows)" in source
    assert "--runs-disclosure-size: var(--control-height);" in styles
    assert ".runs-table thead tr.has-repeat-rows th.col-run::before" in styles
    assert "width: calc(var(--runs-disclosure-size) + var(--space-sm));" in styles
    assert ".samples-toggle.open .samples-toggle-chevron" in styles
    assert "verdict-card" not in source
    assert "verdict-card" not in styles

    # group-metrics strip in the table's group-header dialect, with the
    # platform's inline threshold slider (not a static trailing value) and
    # an item-weighted avg-latency stat
    assert "`% of items where at least one of the ${k} passes" in source
    assert 'class="samples-summary-grid"' in source
    assert "samples-summary-grid qym-stat-strip" not in source
    assert "samples-summary-stat qym-stat-strip__item" not in source
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
    assert source.index("samples-threshold-slider") < source.index(
        'class="samples-summary-grid"'
    )
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
    assert "!state.viewPass && passAttempts" in source
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

    # the lens and its All/pass dot switcher are gone: expanded repeat items
    # show every pass side by side as variant columns instead
    assert "state.itemPassLens" not in source
    assert "pass-dot-switch" not in source
    assert "pass-lensed" not in source
    assert "renderAnswerColumns" in source
    assert 'class="variant-chip' in source
    assert "OUTPUT · ALL PASSES" in source
    assert 'aria-pressed="' in source

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
    components = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")
    repeat_analysis = source.split("async function renderSamplesAnalysis()", 1)[1].split("function wireTopActions", 1)[0]

    assert 'class="model-stat-box qym-stat-strip__item"' in source
    assert 'class="samples-group-tiles qym-stat-strip"' in source
    assert 'class="samples-correct-chart"' in source
    assert 'role="button" tabindex="0" aria-label="' in repeat_analysis
    assert "data-repeat-distribution-bucket" in repeat_analysis
    assert "applyRepeatDistributionFilter" in repeat_analysis
    assert "state.repeatDistFilter = { metric, bucket, samples, threshold };" in repeat_analysis
    assert "getRepeatDistributionBucket" in source
    assert "state.repeatDistFilter = null;" in source
    assert "if (samplesCount <= 10)" in source
    assert "Array.from({ length: 11 }" in source
    assert 'class="samples-metric-tabs qym-segmented" role="group"' in source
    assert 'data-qym-segmented-key="repeat-metric"' in source
    assert "state.samplesMetric = nextMetric;" in source
    assert 'class="threshold-control samples-repeat-threshold"' in source
    metric_row = source.split("'<div class=\"samples-metric-row\">' +", 1)[1].split(
        "'<div class=\"samples-group-tiles", 1
    )[0]
    assert metric_row.index("'<div class=\"samples-metric-tabs qym-segmented\"") < metric_row.index(
        "thresholdControlHtml +"
    )
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
    assert (
        'class="ri-analysis-section samples-performance-section"'
        in repeat_analysis
    )
    assert (
        'style="--ri-section-color:var(--accent-primary)"' in repeat_analysis
    )
    assert (
        '<div class="ri-subhead"><h4>Repeat Performance</h4><span>'
        in repeat_analysis
    )
    assert '<div class="samples-zone-title">Repeat Performance</div>' not in repeat_analysis
    repeat_section_rule = _rule(
        source, ".ri-analysis-section.samples-performance-section,"
    )
    for declaration in (
        "width: 100%;",
        "margin-bottom: var(--space-lg);",
        "padding-top: var(--space-lg);",
        "border-top: 1px solid var(--border-subtle);",
    ):
        assert declaration in repeat_section_rule
    assert ".ri-analysis-section.samples-stability-section {" in repeat_section_rule
    assert '<div class="samples-zone-title">Performance Across Attempts</div>' in repeat_analysis
    assert (
        "const performanceCopy = container.querySelector('.samples-performance-section > .ri-subhead span');"
        in repeat_analysis
    )
    assert (
        "if (performanceCopy) performanceCopy.textContent = selectedStatistic().copy;"
        in repeat_analysis
    )
    assert "data-samples-statistic" in repeat_analysis
    assert "{ key: 'compare', label: 'Compare'" in repeat_analysis
    assert "class=\"samples-statistic-tabs qym-segmented\" role=\"group\"" in repeat_analysis
    assert "class=\"samples-statistic-btn" in repeat_analysis
    assert "samples-curve-controls" not in repeat_analysis
    curve_head = _rule(source, ".samples-curve-head {")
    assert "display: grid;" in curve_head
    assert "grid-template-columns: minmax(0, 1fr) auto;" in curve_head
    assert '"title statistic"' in curve_head
    assert '"legend display"' in curve_head
    statistic_tabs = _rule(source, ".samples-statistic-tabs {")
    assert "grid-area: statistic;" in statistic_tabs
    assert "justify-self: end;" in statistic_tabs
    legend_rule = _rule(source, ".samples-legend {")
    assert "grid-area: legend;" in legend_rule
    assert "justify-self: start;" in legend_rule
    view_toggle = _rule(source, ".samples-curve-head > .samples-view-toggle {")
    assert "grid-area: display;" in view_toggle
    assert "justify-self: end;" in view_toggle
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
    cell_value_rule = _rule(source, ".sw-cell-value {")
    assert "display: inline-flex;" in cell_value_rule
    assert "align-items: center;" in cell_value_rule
    assert "justify-content: center;" in cell_value_rule
    assert "vertical-align: middle;" in cell_value_rule
    assert "text-align: center;" in _rule(source, ".samples-sweep thead th.sw-num-h {")
    assert "text-align: center;" in _rule(source, ".sw-num {")
    best_rule = _rule(source, ".sw-cell-value.sw-best {")
    assert "display: inline-flex;" in best_rule
    assert "padding: 2px 6px;" in best_rule
    assert "margin: -2px 0;" in best_rule
    assert "background: color-mix(in srgb, var(--success) 14%, transparent);" in best_rule
    tied_rule = _rule(source, ".sw-cell-value.sw-best.sw-tied {")
    assert "background: color-mix(in srgb, var(--success) 7%, transparent);" in tied_rule
    assert "box-shadow: inset 0 0 0 1px" in tied_rule
    assert "sw-meter" not in repeat_analysis
    assert 'class="sw-pass-content"' in repeat_analysis
    sw_pass_rule = _rule(source, ".sw-pass {")
    assert "display: flex;" not in sw_pass_rule
    assert "display: flex;" in _rule(source, ".sw-pass-content {")
    assert ">Errors</th>" in source
    assert ">Avg lat</th>" not in source
    assert ">Err</th>" not in source
    assert ".samples-correct-col" in source
    assert "height: 260px;" in _rule(source, ".samples-curve {")
    assert "height: 230px;" in _rule(source, ".samples-correct-chart {")
    assert "border-bottom:" not in _rule(source, ".samples-correct-chart {")
    distribution_col_rule = _rule(source, ".samples-correct-col {")
    assert "cursor: pointer;" in distribution_col_rule
    assert "transition: opacity 0.15s, transform 0.15s;" in distribution_col_rule
    assert ".samples-correct-col:hover" in source
    distribution_panel_rule = _rule(source, ".samples-distribution-panel {")
    assert "display: flex;" in distribution_panel_rule
    assert "flex-direction: column;" in distribution_panel_rule
    assert "justify-content: center;" in _rule(source, ".samples-distribution-panel .samples-chart-body {")
    assert "const tickStep = observedSpan > 0.8 ? 0.2 : 0.1;" in repeat_analysis
    assert "Math.floor((observedMin - padding) / tickStep)" in repeat_analysis
    assert "Math.ceil((observedMax + padding) / tickStep)" in repeat_analysis
    assert "yTicks = Array.from({ length: tickCount + 1 }" in repeat_analysis
    assert "statisticInterval" in repeat_analysis
    assert "intervalPath" in repeat_analysis
    assert "samples-band-table-wrap" in repeat_analysis
    assert "samples-band-cell-ci" in repeat_analysis
    assert "±" in repeat_analysis
    assert "window.QymMetrics.getMetricColorClass(value, groupMetricType)" in repeat_analysis
    assert "samples-band-cell-main qym-score-value" in repeat_analysis
    for band in range(1, 6):
        assert f".qym-score-value.score-{band} {{ color: var(--score-{band}); }}" in components
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


def test_repeat_run_latency_columns_round_to_whole_seconds() -> None:
    source = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")

    assert "const latCell = v =>" in source
    assert "Math.round(v / 1000) + 's'" in source
    assert ".toFixed(2) + 's'" not in source


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
    assert 'class="ri-chart ri-chart-square"' in active
    correlation_chart_rule = _rule(source, ".ri-chart-square {")
    assert "max-width: var(--analysis-matrix-max-width);" in correlation_chart_rule
    assert "margin-inline: 0;" in correlation_chart_rule
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
    repeat_metric_handler = source.split(
        "container.querySelectorAll('.samples-metric-tab').forEach",
        1,
    )[1].split("const samplesThreshold", 1)[0]
    assert "await renderSamplesAnalysis();" in repeat_metric_handler
    assert "renderMetadataBreakdown();" in repeat_metric_handler
    assert "renderOverview(" not in repeat_metric_handler
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
    assert "systemCards + intelligenceCharts" in source
    assert "const analysisCharts = buildDeepAnalysisCharts(rows);" in source
    assert "const intelligenceCharts = analysisCharts.deepAnalysisHtml;" in source
    assert "const frontierPanel = analysisCharts.frontierPanel;" in source
    assert "relationshipPanels.concat(frontierPanel" not in active
    assert "return { deepAnalysisHtml, frontierPanel };" in active
    assert 'class="ri-grid deep-analysis-grid"' in active
    assert 'relationshipPanels.push(\'<div class="ri-panel">' in active
    assert 'frontierPanel = \'<div class="ri-panel system-frontier-panel">' in active
    assert "radar" not in source.lower()
    assert '<h3 class="section-title">Latency and Trace Analysis</h3>' in source
    assert "Inspect response latency, quality tradeoffs, and trace-level execution behavior." in source
    assert 'class="ri-header system-metrics-header"' in source
    assert "const latencyPanels = (latencyCard || '') + (frontierPanel || '');" in source
    assert "'<div class=\"system-metrics-grid\">' + latencyPanels + '</div>'" in source
    assert "'<div class=\"system-trace-row\">' + traceCard + '</div>'" in source
    assert 'class="metric-card system-latency-card"' in source
    assert 'class="metric-card system-trace-card"' in source
    system_grid = _rule(source, ".system-metrics-grid {")
    assert "grid-template-columns: 1fr 1fr;" in system_grid
    system_grid_children = _rule(
        source, ".system-metrics-grid > :is(.ri-panel, .metric-card) {"
    )
    assert "grid-column: auto;" in system_grid_children
    assert "align-self: stretch;" in system_grid_children
    trace_grid = _rule(
        source, ".system-trace-row .trace-pills-row.qym-stat-strip {"
    )
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in trace_grid
    assert "Qym Metrics" not in source
    assert "system-metrics-label" not in source


def test_repeat_run_analysis_follows_overview_before_deep_analysis() -> None:
    source = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")

    overview_markup = source.split('<div id="overview-section">', 1)[1].split(
        '<div id="metadata-breakdown">',
        1,
    )[0]
    assert (
        overview_markup.index('id="overview-primary-section"')
        < overview_markup.index('id="samples-analysis-section"')
        < overview_markup.index('id="overview-deep-section"')
    )

    render = source.split(
        "function renderOverview(filteredItemsOverride = null)",
        1,
    )[1].split("function getApprovalState", 1)[0]
    assert "primarySection.innerHTML =" in render
    assert "deepSection.innerHTML = systemCards + intelligenceCharts;" in render
    assert "section.innerHTML =" not in render


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
    assert ".category-compare-head span:nth-child(2) { text-align: left; }" in source
    assert ".category-compare-head span:nth-child(n + 3) { text-align: right; }" in source
    assert ".category-compare-head span:not(:first-child)" not in source
    assert "<span>| ' + baselineScope" not in source
    # the 6-card cap is gone: every category card renders, no Show-more
    assert "data-category-expand" not in source
    assert "groupStats.slice(0, 6)" not in source
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
    assert 'class="chart-segment-btn qym-segmented__option ${groupMode === \'run\' ? \'active\' : \'\'}"' in charts_block
    assert 'class="chart-segment-btn qym-segmented__option ${isGrouped ? \'active\' : \'\'}"' in charts_block
    assert 'aria-pressed="${groupMode === \'run\'}"' in charts_block
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
    assert 'class="admin-tabs qym-tabs"' in admin
    assert 'data-admin-tab="runs"' in admin
    assert 'data-admin-tab="live"' not in admin
    assert 'data-admin-tab="by-project"' not in admin
    ui_components = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")
    assert ".admin-tab-btn" in ui_components
    assert "border-bottom: 2px solid transparent" in ui_components
    assert "border-bottom-color: var(--accent-primary)" in ui_components
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
    assert 'id="recent-runs-pagination"' in admin
    assert "renderPagination(document.getElementById('recent-runs-pagination'), {" in admin


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
    assert r'ui_components\.css(?:\?[^"]*)?' in source
    assert r'ui_components\.js(?:\?[^"]*)?' in source
    assert r'metrics\.js(?:\?[^"]*)?' in source
    assert r'trace_viewer\.js(?:\?[^"]*)?' in source
    assert r'auth\.js(?:\?[^"]*)?' in source
    assert r'shell\.js(?:\?[^"]*)?' in source
    assert r'playground\.js(?:\?[^"]*)?' in source
    assert "lambda _match: f\"<style>\\n{css_content}\\n</style>\"" in source
    assert "ui_components_css_content" in source
    assert "ui_components_js" in source
    assert "lambda _match: f\"<script>\\n{metrics_js}\\n</script>\"" in source


def test_shared_ui_component_layer_loads_last_on_platform_pages() -> None:
    """The canonical layer wins over legacy page-local declarations."""
    for path in sorted(DASHBOARD_DIR.glob("*.html")):
        source = path.read_text(encoding="utf-8")
        head = source.split("</head>", 1)[0]
        assert "ui_components.css" in source, f"{path.name} does not load shared UI components"
        assert "ui_components.js" in source, f"{path.name} does not load shared UI behavior"
        assert head.index("ui_components.css") > head.rfind(
            "</style>"
        ), f"{path.name} must load shared UI components after page-local styles"


def test_shell_navigation_keeps_shared_components_after_page_styles() -> None:
    """SPA navigation must preserve the same CSS cascade as a full load."""
    source = (DASHBOARD_DIR / "shell.js").read_text(encoding="utf-8")
    style_swap = source.split("// Remove old page-specific styles", 1)[1].split(
        "var fragment = document.createDocumentFragment();", 1
    )[0]

    assert 'link[href*="ui_components.css"]' in style_swap
    assert "document.head.insertBefore(s, sharedComponentsLink || null);" in style_swap
    assert "document.head.appendChild(s);" not in style_swap
    init_block = source.split("function init() {", 1)[1].split(
        "// Parse current route", 1
    )[0]
    assert "head > style:not([data-shell-page])" in init_block
    assert "style.setAttribute('data-shell-page', '1');" in init_block


def test_dashboard_stops_polling_before_shell_navigation() -> None:
    source = DASHBOARD_JS.read_text(encoding="utf-8")

    assert "let dashboardActive = true;" in source
    assert "function teardownDashboard()" in source
    assert "dashboardActive = false;" in source
    assert "window.__QYM_DASHBOARD_INTERVAL__ = null;" in source
    assert (
        "document.addEventListener('qym:before-navigate', teardownDashboard, { once: true });"
        in source
    )
    assert "if (!dashboardActive) return;" in source


def test_changed_route_assets_are_cache_versioned() -> None:
    docs = (DASHBOARD_DIR / "docs.html").read_text(encoding="utf-8")
    runs_api = RUNS_API.read_text(encoding="utf-8")

    assert "/static/docs.css?v=ui-consistency-20260730-15" in docs
    assert "/static/docs.js?v=ui-consistency-20260730-18" in docs
    assert 'dashboard.css?v=ui-consistency-20260730-10"' in runs_api
    assert 'shell.js?v=ui-consistency-20260730-10"' in runs_api


def test_multiselects_share_search_actions_options_and_only_action() -> None:
    dashboard = DASHBOARD_JS.read_text(encoding="utf-8")
    generic = dashboard.split("function buildMultiSelect(", 1)[1].split(
        "function syncMultiSelect", 1
    )[0]
    assert generic.index("qym-dropdown__search") < generic.index(
        "qym-dropdown__actions"
    ) < generic.index("qym-dropdown__option")
    assert "qym-dropdown__only" in generic
    assert "const option = onlyBtn.closest('.multi-select-option');" in generic
    assert generic.index("stateSet.clear();", generic.index("qym-dropdown__only")) < generic.index(
        "stateSet.add(selectedValue);"
    )

    reviews = (DASHBOARD_DIR / "reviews.html").read_text(encoding="utf-8")
    reviews_builder = reviews.split("function buildMultiselectOptions(key, values)", 1)[
        1
    ].split("function setupMultiselectToggle", 1)[0]
    run_builder = (
        (DASHBOARD_DIR / "run.html")
        .read_text(encoding="utf-8")
        .split("function buildMultiselectOptions(category, values)", 1)[1]
        .split("function getCatFilter", 1)[0]
    )
    compare_builder = (
        (DASHBOARD_DIR / "compare.html")
        .read_text(encoding="utf-8")
        .split("function buildMultiselectOptions(category, values)", 1)[1]
        .split("function getCatFilter", 1)[0]
    )
    for source in (reviews_builder, run_builder, compare_builder):
        assert "qym-dropdown__only" in source
        assert source.index("qym-dropdown__search") < source.index(
            "qym-dropdown__actions"
        )
    assert reviews_builder.index("qym-dropdown__actions") < reviews_builder.index(
        "html += mergedValues"
    )
    assert run_builder.index("qym-dropdown__actions") < run_builder.index(
        "html += extraOptions"
    )
    assert compare_builder.index("qym-dropdown__actions") < compare_builder.index(
        "html += extraOptions"
    )
    assert "const label = opt.dataset.searchLabel || opt.dataset.value || '';" in generic
    assert "showSearch: true, searchPlaceholder: 'Search statuses...'" in dashboard

    metric_visibility = dashboard.split("function populateMetricVisibility(", 1)[
        1
    ].split("function syncMetricVisibilityDropdownState", 1)[0]
    model_stats = dashboard.split("function populateModelsStatVisibility(", 1)[
        1
    ].split("// ════════════════════════════════════════════════════\n  // DATA PROCESSING", 1)[0]
    for source in (metric_visibility, model_stats):
        assert source.index("qym-dropdown__search") < source.index(
            "qym-dropdown__actions"
        ) < source.index("qym-dropdown__option")

    assert "if (category === 'domain') state.domainExclusive.clear();" in run_builder
    assert "if (category === 'domain') state.domainExclusive.clear();" in compare_builder


def test_switchers_use_pressed_state_and_refresh_visual_selection() -> None:
    dashboard = DASHBOARD_JS.read_text(encoding="utf-8")
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")

    assert 'class="compare-mode-tabs qym-segmented" id="compare-mode-tabs" role="group"' in compare
    assert 'class="metric-tabs qym-segmented" id="overview-metric-tabs" role="group"' in compare
    compare_mode = compare.split("function renderCompareModeTabs()", 1)[1].split(
        "function renderCompareCohortBanner", 1
    )[0]
    assert 'aria-pressed="${state.activeCompareTab === tab.key}"' in compare_mode
    assert compare_mode.index("renderCompareModeTabs();") < compare_mode.index(
        "applyCompareMode();"
    )
    assert 'aria-pressed="${metric === state.selectedOverviewMetric}"' in compare
    assert 'class="samples-metric-tabs qym-segmented" role="group"' in run
    assert 'class="samples-statistic-tabs qym-segmented" role="group"' in run
    assert "e.target.closest('input, select, textarea, button, a, [contenteditable=\"true\"]')" in dashboard


def test_run_header_status_and_actions_share_one_height() -> None:
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    components = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")

    assert (
        'class="qym-inline-action qym-inline-action--neutral" '
        'id="export-download-btn"'
    ) in run
    assert (
        'class="qym-inline-action qym-inline-action--accent" '
        'id="export-share-btn"'
    ) in run
    assert "qym-inline-action--langfuse" not in run
    assert "View in Langfuse" not in run
    assert "langfuseChip" not in run
    assert "export-html-btn" not in run
    assert "hero-link-btn" not in run
    assert (
        ".qym-inline-action.qym-inline-action--neutral,\n"
        ".qym-inline-action.qym-inline-action--accent {"
    ) in components
    aligned_cluster = run.split(
        ".hero-right .hero-status.qym-badge,\n"
        "    .hero-actions > .qym-inline-action {",
        1,
    )[1].split("}", 1)[0]
    for contract in (
        "min-height: var(--control-height);",
        "height: var(--control-height);",
        "box-sizing: border-box;",
        "margin-top: 0;",
        "padding-top: 0;",
        "padding-bottom: 0;",
    ):
        assert contract in aligned_cluster


def test_langfuse_ctas_are_removed_from_all_user_surfaces() -> None:
    surfaces = [
        DASHBOARD_JS,
        DASHBOARD_DIR / "compare.html",
        DASHBOARD_DIR / "run.html",
        DASHBOARD_DIR / "ui_components.css",
        DASHBOARD_DIR / "dashboard.css",
        ROOT / "packages" / "platform" / "qym_platform" / "_static" / "ui" / "index.html",
        ROOT / "packages" / "platform" / "qym_platform" / "_static" / "ui" / "app.js",
        ROOT / "packages" / "sdk" / "qym" / "_static" / "ui" / "index.html",
        ROOT / "packages" / "sdk" / "qym" / "_static" / "ui" / "app.js",
    ]
    forbidden = (
        "View in Langfuse",
        "Open in Langfuse",
        "qym-inline-action--langfuse",
        "langfuseChip",
        "langfuse-icon",
        "brand-langfuse",
    )
    for path in surfaces:
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, f"{token!r} remains in {path.name}"

    # Old payload fields remain accepted for migration, but are not rendered as CTAs.
    for path in (DASHBOARD_DIR / "compare.html", DASHBOARD_DIR / "run.html"):
        assert "langfuse_host" in path.read_text(encoding="utf-8")


def test_semantic_quick_actions_keep_shared_surface_and_hover_states() -> None:
    components = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")

    accent = components.split(
        ".action-icon:is(.submit-run, .approve-run),\n.actions-trigger.workflow-trigger {",
        1,
    )[1].split("}", 1)[0]
    accent_hover = components.split(
        ".action-icon:is(.submit-run, .approve-run):hover,", 1
    )[1].split("}", 1)[0]
    danger = components.split(
        ".action-icon:is(.reject-run, .delete-run) {", 1
    )[1].split("}", 1)[0]
    danger_hover = components.split(
        ".action-icon:is(.reject-run, .delete-run):is(:hover, :focus-visible) {",
        1,
    )[1].split("}", 1)[0]

    assert "background: rgba(0, 212, 170, 0.1);" in accent
    assert "background: rgba(0, 212, 170, 0.2);" in accent_hover
    assert "background: rgba(239, 68, 68, 0.1);" in danger
    assert "background: rgba(239, 68, 68, 0.2);" in danger_hover
    assert "background-color 0.15s ease" in components


def test_item_table_toolbar_actions_use_shared_inline_action_variants() -> None:
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    components = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")

    for control_id in ("metadata-fields-btn", "metric-meta-fields-btn"):
        assert (
            'class="qym-inline-action qym-inline-action--neutral" '
            f'id="{control_id}"'
        ) in run
    # The export control is a rail segment now, not an inline action
    assert 'class="rseg" id="export-filtered-btn"' in run
    assert "fp-gear-btn metadata-fields-btn multi-select-btn qym-control" not in run
    assert 'class="fp-btn fp-export"' not in run

    shared_actions = components.split(
        ".qym-inline-action.qym-inline-action--neutral,\n"
        ".qym-inline-action.qym-inline-action--accent {",
        1,
    )[1].split("}", 1)[0]
    for contract in (
        "padding-right: var(--space-md);",
        "padding-left: var(--space-md);",
        "border: 0;",
        "border-radius: var(--control-radius);",
        "font-weight: 600;",
    ):
        assert contract in shared_actions
    assert ".qym-inline-action.qym-inline-action--neutral:hover {" in components
    assert ".qym-inline-action.qym-inline-action--accent:hover {" in components


def test_compare_view_uses_current_run_detail_component_contracts() -> None:
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
    overview_controls = compare.split('<div class="comparison-overview-heading">', 1)[1].split(
        '<div class="comparison-stats"', 1
    )[0]
    assert overview_controls.index('id="threshold-control"') < overview_controls.index(
        'id="overview-metric-tabs"'
    )

    assert '<h1 class="compare-title">Compare Runs</h1>' in compare
    assert 'id="compare-subtitle"' in compare
    assert compare.count('class="compare-section-copy"') >= 3
    assert "container.hidden = tabs.length < 2;" in compare
    assert (
        'class="export-html-btn qym-inline-action qym-inline-action--accent" '
        'id="export-share-btn"'
    ) in compare

    assert 'class="metrics-table qdt-table" id="metrics-table"' in compare
    assert 'class="metric-value-cell"' in compare
    assert "metric-val qym-score-value" in compare
    assert "metric-run-heading" in compare
    assert "table-layout: fixed;" in compare
    assert "width: 18%;" in compare
    assert "display: flex;" in compare.split(".metric-run-heading {", 1)[1].split("}", 1)[0]
    assert "const isBest = mType !== 'numeric'" in compare
    assert "text-align: center;" in compare.split(
        ".metrics-table.qdt-table th:not(:first-child),", 1
    )[1].split("}", 1)[0]

    for control_id in (
        "items-metric-select",
        "item-filter",
        "run-winner-filter",
        "pass-rate-op",
        "sort-select",
        "filter-approval",
        "sweep-move-filter",
        "sweep-outcome-filter",
        "sweep-metadata-key-filter",
    ):
        assert re.search(
            rf'id="{control_id}" class="[^"]*qym-control qym-select',
            compare,
        )
    assert (
        'id="items-search" class="qym-control qym-search"'
        in compare
    )
    assert 'class="filter-count" id="filter-count"' in compare
    assert 'class="filter-count qym-tag qym-tag--count"' not in compare
    assert (
        "metadata-fields-btn multi-select-btn qym-inline-action "
        "qym-inline-action--neutral"
    ) in compare
    assert (
        "fp-export qym-inline-action qym-inline-action--accent"
    ) in compare

    for contract in (
        "qym-badge--success",
        "qym-badge--info",
        "qym-badge--danger",
        "qym-badge--warning",
        "qym-badge--neutral",
        "compare-run-remove qym-icon-action",
        "sweep-table qdt-table",
        "sweep-metadata-table qdt-table",
    ):
        assert contract in compare
    assert 'class="compare-run-link langfuse' not in compare
    assert "langfuseChip" not in compare


def test_compare_category_breakdown_matches_run_detail_component() -> None:
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
    breakdown = compare.split("function renderMetadataBreakdown()", 1)[1].split(
        "function wireChipClicks", 1
    )[0]

    assert "categoryBreakdownView: 'cards'" in compare
    assert "categoryCompareKey: null" in compare
    assert 'data-category-view="cards"' in breakdown
    assert 'data-category-view="compare"' in breakdown
    assert 'class="comparison-stats metadata-breakdown-content"' in breakdown
    assert "Overall metric average score" in breakdown
    assert "categoryScoreTrack(group.avgScore, overallAverage)" in breakdown
    assert 'class="category-compare-row"' in breakdown
    assert '<span class="score-col-label">Average</span>' in breakdown
    assert '<span class="score-col-label">Items</span>' in breakdown
    assert '<span class="score-col-label">Latency</span>' in breakdown
    assert "Avg@" not in breakdown
    assert "Pass@" not in breakdown
    assert "Consistency" not in breakdown
    assert "#metadata-breakdown > .comparison-stats" not in compare


def test_category_cards_hug_the_latency_column() -> None:
    for page in ("run.html", "compare.html"):
        source = (DASHBOARD_DIR / page).read_text(encoding="utf-8")
        card_rule = _rule(source, ".breakdown-card {")
        assert "width: fit-content;" in card_rule
        assert "min-width: 220px;" not in card_rule


def test_clear_filter_control_has_aligned_label_and_soft_count_pill() -> None:
    components = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")
    aligned_content = _rule(
        components,
        ":is(.fp-clear-btn, .clear-filters-btn, .btn-clear-filters)\n"
        "  :is(.fp-clear-label, .clear-filters-label) {",
    )
    count_pill = _rule(
        components,
        ":is(.filter-count-badge.filter-count-badge, .fp-clear-count.fp-clear-count) {",
    )

    # run.html: the clear control moved into the filter builder head
    run_source = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    assert 'class="fb-clear" id="clear-all-btn"' in run_source
    compare_source = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
    assert '<span class="fp-clear-label">Clear</span>' in compare_source
    assert '<svg class="fp-clear-x" viewBox="0 0 12 12"' in compare_source

    for page in ("index.html", "models.html", "charts.html"):
        source = (DASHBOARD_DIR / page).read_text(encoding="utf-8")
        assert '<span class="clear-filters-label">Clear</span>' in source
        assert '<svg class="clear-filters-x" viewBox="0 0 12 12"' in source

    reviews = (DASHBOARD_DIR / "reviews.html").read_text(encoding="utf-8")
    assert '<span class="clear-filters-label">Clear filters</span>' in reviews
    assert '<svg class="clear-filters-x" viewBox="0 0 12 12"' in reviews

    assert "display: inline-flex;" in aligned_content
    assert "align-items: center;" in aligned_content
    assert "border-radius: 999px;" in count_pill
    assert "background: rgba(239, 68, 68, 0.14);" in count_pill
    assert "font-family: var(--font-mono);" in components

    for page in DASHBOARD_DIR.glob("*.html"):
        source = page.read_text(encoding="utf-8")
        if "ui_components.css?v=" in source:
            assert "ui_components.css?v=ui-consistency-20260730-32" in source


def test_operational_statistics_use_connected_strip_contract() -> None:
    dashboard = DASHBOARD_JS.read_text(encoding="utf-8")
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
    datasets = (DASHBOARD_DIR / "datasets.html").read_text(encoding="utf-8")
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")

    assert 'class="samples-summary-grid"' in dashboard
    assert 'class="samples-summary-stat"' in dashboard
    assert "samples-summary-grid qym-stat-strip" not in dashboard
    assert "samples-summary-stat qym-stat-strip__item" not in dashboard
    assert 'class="model-stats-grid"' in dashboard
    assert 'class="model-stat-item"' in dashboard
    assert "model-stats-grid qym-stat-strip" not in dashboard
    assert "model-stat-item qym-stat-strip__item" not in dashboard
    assert "{ key, label: '⚡ Avg Latency' }" in dashboard
    assert "{ key, label: '⚡ Median Latency' }" in dashboard

    for contract in (
        "stats-row qym-stat-strip",
        "stat-box qym-stat-strip__item",
        "stat-title qym-stat-strip__label",
        "stat-main qym-stat-strip__value",
    ):
        assert contract in compare

    for contract in (
        "dsx-run-aggregate qym-stat-strip",
        "tile qym-stat-strip__item",
        "label qym-stat-strip__label",
        "value qym-stat-strip__value",
    ):
        assert contract in datasets

    for contract in (
        "overview-summary-strip qym-stat-strip",
        "overview-summary-pill qym-stat-strip__item",
        "overview-summary-label qym-stat-strip__label",
        "overview-summary-value qym-stat-strip__value",
        "metric-numeric-stats qym-stat-strip",
        "metric-num-stat qym-stat-strip__item",
        "trace-pill qym-stat-strip__item",
        "trace-pill-label qym-stat-strip__label",
        "trace-pill-val qym-stat-strip__value",
    ):
        assert contract in run
    assert "overview-summary-text" not in run
    assert "compare-run-summary-strip.compare-run-summary-strip.qym-stat-strip" in compare
    assert "grid-template-columns: repeat(3, max-content);" in compare
    assert "justify-content: space-between;" in compare.split(
        ".compare-run-summary-strip.compare-run-summary-strip.qym-stat-strip {", 1
    )[1].split("}", 1)[0]
    assert "width: 100%;" in compare.split(
        ".compare-run-summary-strip.compare-run-summary-strip.qym-stat-strip {", 1
    )[1].split("}", 1)[0]
    assert "overflow: visible;" in compare.split(
        ".compare-run-summary-strip.compare-run-summary-strip.qym-stat-strip {", 1
    )[1].split("}", 1)[0]
    assert "background: transparent;" in compare.split(
        ".compare-run-summary-strip.compare-run-summary-strip.qym-stat-strip {", 1
    )[1].split("}", 1)[0]
    assert "border: 0;" in compare.split(
        ".compare-run-summary-strip.compare-run-summary-strip.qym-stat-strip {", 1
    )[1].split("}", 1)[0]
    assert ".compare-run-summary-strip.compare-run-summary-strip > .compare-run-summary-pill.compare-run-summary-pill.qym-stat-strip__item" in compare
    assert "justify-content: flex-start;" in compare.split(
        ".compare-run-summary-strip.compare-run-summary-strip > .compare-run-summary-pill.compare-run-summary-pill.qym-stat-strip__item", 1
    )[1].split("}", 1)[0]
    assert 'class="compare-run-title-line"' in compare
    card_template = compare.split('<div class="compare-run-card"', 1)[1].split('</div>', 1)[0]
    assert "compare-run-title-line" in card_template
    assert 'class="compare-run-summary-strip qym-stat-strip"' in compare
    assert compare.index('${summaryHtml}', compare.index('class="compare-run-card"')) < compare.index('class="compare-run-meta-grid"', compare.index('class="compare-run-card"'))
    assert ".compare-run-summary-strip.compare-run-summary-strip > .compare-run-summary-pill .compare-run-summary-value" in compare
    summary_builder = compare.split("function renderSummaries()", 1)[1].split(
        "function renderMetricsTable()", 1
    )[0]
    assert "compare-run-link langfuse" not in summary_builder
    assert "compare-run-remove qym-icon-action" in summary_builder
    assert 'aria-label="Remove from comparison"' in summary_builder
    assert 'class="compare-run-remove-icon"' in summary_builder
    assert "e.currentTarget.dataset.idx" in summary_builder
    remove_button = _rule(compare, ".compare-run-remove.compare-run-remove {")
    for contract in (
        "position: absolute;",
        "top: 10px;",
        "right: 10px;",
        "background: rgba(239, 68, 68, 0.1);",
        "color: #f87171;",
    ):
        assert contract in remove_button
    assert "grid-template-columns: repeat(3, max-content);" in run
    assert "flex: 0 0 auto;" in run
    assert "width: auto;" in run
    assert "flex: 0 1 var(--overview-summary-max-width);" not in run
    assert ".overview-summary-strip > .overview-summary-pill .overview-summary-value {" in run
    compact_summary = run.split(
        ".overview-summary-strip > .overview-summary-pill.qym-stat-strip__item {",
        1,
    )[1].split("}", 1)[0]
    for contract in (
        "display: flex;",
        "align-items: center;",
        "min-height: 34px;",
        "height: 34px;",
        "padding: 0 var(--space-md);",
    ):
        assert contract in compact_summary
    compact_value = run.split(
        ".overview-summary-strip > .overview-summary-pill .overview-summary-value {",
        1,
    )[1].split("}", 1)[0]
    assert "font-size: var(--font-md);" in compact_value
    assert "margin-top: 0;" in compact_value


def test_run_selection_uses_persistent_checkboxes_and_status_bar_actions() -> None:
    markup = (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8")
    source = DASHBOARD_JS.read_text(encoding="utf-8")
    styles = (DASHBOARD_DIR / "dashboard.css").read_text(encoding="utf-8")

    command_bar = markup.split('<div class="command-bar">', 1)[1].split(
        '<main class="runs-page-main">',
        1,
    )[0]
    assert 'id="select-mode-btn"' not in command_bar
    assert 'id="compare-panel"' not in command_bar
    assert 'id="select-mode-btn"' not in markup

    main_at = markup.index('<main class="runs-page-main">')
    table_at = markup.index('id="table-view"')
    select_all_at = markup.index('id="select-all"')
    footer_at = markup.index('<footer class="status-bar">')
    actions_at = markup.index('id="compare-panel"')
    assert main_at < table_at < select_all_at < footer_at < actions_at
    assert 'aria-label="Select all visible runs"' in markup
    assert 'class="row-checkbox" aria-label="Select run ' in source
    assert 'id="selection-status-separator" style="display:none;"' in markup
    assert 'role="group" aria-label="Selected run actions"' in markup
    assert 'id="selection-guidance" aria-live="polite"' in markup
    assert 'id="compare-count" aria-live=' not in markup
    assert "compare-subtitle" not in markup
    assert "compare-chips" not in markup
    assert "langfuse-btn" not in markup
    assert 'class="selection-action qym-inline-action submit"' in markup
    assert 'class="selection-action qym-inline-action danger"' in markup

    panel = source.split("function renderComparePanel()", 1)[1].split(
        "// ═══════════════════════════════════════════════════\n  // MAIN RENDER",
        1,
    )[0]
    assert "const showActions = selected.size > 0 || isCohortMode;" in panel
    assert "`${selected.size} selected`" in panel
    assert "panel.style.display = showActions ? 'inline-flex' : 'none';" in panel
    assert "panel.closest('.status-bar')?.classList.toggle('selection-active', showActions)" in panel
    assert "separator.style.display = showActions ? '' : 'none';" in panel
    assert "allDeletable" in panel
    assert "isOwner && (status === 'COMPLETED'" in panel
    assert "const selectionAvailable = !!state.runs && state.flatRuns.length > 0;" in source
    assert "state.selectMode" not in source
    assert "setSelectMode" not in source
    assert "select-mode-btn" not in source
    assert "const isSelectionControl = !!e.target.closest('#compare-panel, .col-select');" in source
    assert "document.activeElement?.closest?.('#compare-panel, .col-select')" in source
    assert "if (restoreTableFocus) el('select-all')?.focus" in source
    assert "selectAllCheckbox.disabled = visibleFilePaths.length === 0;" in source
    assert ".status-bar.selection-active {" in styles
    assert "overflow-x: auto;" in styles
    assert ".runs-selection-toolbar {" not in styles
    assert ".table-container:not(.select-mode)" not in styles
    assert ".select-mode-btn" not in styles
    assert ".selection-actions {" in styles
    assert ".selection-action.submit {" in styles
    assert ".selection-action.danger {" in styles


def test_chart_dataset_tabs_restore_filled_selection_and_hover_scrollbars() -> None:
    components = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")
    tabs = components.split(
        "/* Chart-card datasets are dense collection tabs",
        1,
    )[1].split("/* 4. In-place switching", 1)[0]

    for contract in (
        "background: var(--bg-elevated)",
        "background: var(--bg-surface)",
        "border-bottom-color: var(--accent-primary)",
        "color: var(--accent-primary)",
        "background: var(--bg-active)",
        "scrollbar-color: transparent transparent",
        "scrollbar-color: var(--border-strong) transparent",
        ":hover::-webkit-scrollbar-thumb",
    ):
        assert contract in tabs


def test_shared_segmented_controls_use_one_motion_indicator() -> None:
    components = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")
    behavior = (DASHBOARD_DIR / "ui_components.js").read_text(encoding="utf-8")

    assert ".qym-segmented.qym-segmented--ready::before {" in components
    assert "transform: translateX(var(--qym-segment-x));" in components
    assert "width: var(--qym-segment-width);" in components
    assert "cubic-bezier(0.16, 1, 0.3, 1)" in components
    assert "@media (prefers-reduced-motion: reduce)" in components
    assert "function syncSegmented(segmented)" in behavior
    assert "function scheduleSegmentedSync(segmented, frames)" in behavior
    assert "function observeSegmented(segmented)" in behavior
    assert "function cleanupSegmented(root)" in behavior
    assert "function segmentedHistoryKey(segmented)" in behavior
    assert "var segmentPositions = new Map();" in behavior
    assert "new ResizeObserver" in behavior
    assert "active.offsetLeft + 'px'" in behavior
    assert "active.offsetWidth + 'px'" in behavior
    assert "setupSegmented(record.target.closest && record.target.closest('.qym-segmented'))" in behavior
    assert "scheduleSegmentedSync(record.target.closest('.qym-segmented'))" in behavior
    assert "record.removedNodes.forEach" in behavior
    assert "attributeFilter: ['aria-selected', 'aria-pressed', 'class']" in behavior
    assert "background-color 0.24s cubic-bezier(0.16, 1, 0.3, 1)" in components
    assert ".qym-segmented.qym-segmented--ready > :is(" in components


def test_flat_tags_and_shared_icon_actions_are_used_without_flattening_statuses() -> None:
    dashboard = DASHBOARD_JS.read_text(encoding="utf-8")
    reviews = (DASHBOARD_DIR / "reviews.html").read_text(encoding="utf-8")
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
    trace = (DASHBOARD_DIR / "trace_viewer.js").read_text(encoding="utf-8")
    components = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")

    assert "tab-count qym-tag qym-tag--count" in dashboard
    assert "version-badge qym-tag" in dashboard
    assert "version-badge qym-badge" not in dashboard
    assert ".tag.qym-tag.task {" in components
    assert "diff-source-tag qym-tag ai" in reviews
    assert "diff-source-tag qym-tag human" in reviews

    for name in ("admin.html", "profile.html", "project_settings.html", "projects.html"):
        source = (DASHBOARD_DIR / name).read_text(encoding="utf-8")
        for class_value in re.findall(r'class="([^"]*(?:role-badge|role-pill)[^"]*)"', source):
            assert "qym-tag" in class_value, f"{name} role must use the flat tag primitive"
            assert "qym-badge" not in class_value, f"{name} role must not use a status pill"

    for status_source in (
        (DASHBOARD_DIR / "datasets.html").read_text(encoding="utf-8"),
        dashboard,
    ):
        assert "status-badge qym-badge" in status_source

    assert ".metric-edit-open," in components
    assert ".metric-edit-btn" not in components
    assert "metric-edit-open qym-icon-action" in run
    assert "metric-edit-open qym-icon-action" in compare
    assert "tv-copy-btn qym-icon-action" in trace
    assert "tv-close qym-icon-action" in trace
    assert "qym-tag qym-tag--count" in trace
    assert "qym-tag qym-tag--data" in trace


def test_quick_actions_share_the_same_icon_only_green_treatment() -> None:
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
    datasets = (DASHBOARD_DIR / "datasets.html").read_text(encoding="utf-8")
    docs = (DASHBOARD_DIR / "docs.js").read_text(encoding="utf-8")
    reviews = (DASHBOARD_DIR / "reviews.html").read_text(encoding="utf-8")
    components = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")

    for source in (run, compare):
        copy_classes = re.findall(
            r'<button class="([^"]*\bcopy-btn\b[^"]*)"',
            source,
        )
        assert copy_classes
        assert all("qym-icon-action" in classes for classes in copy_classes)

    assert "className: 'tv-copy-btn qym-icon-action'" in datasets
    assert "className: 'tv-expand-btn qym-icon-action'" in datasets
    assert "className: 'copy qym-icon-action'" in datasets
    assert '<button class="docs-copy-btn qym-icon-action"' in docs
    assert '<button class="expand-btn qym-icon-action"' in reviews
    assert "samples-toggle qym-icon-action" in DASHBOARD_JS.read_text(encoding="utf-8")
    for source in (
        DASHBOARD_JS.read_text(encoding="utf-8"),
        run,
        compare,
        reviews,
        (DASHBOARD_DIR / "trash.html").read_text(encoding="utf-8"),
    ):
        assert re.search(r'class="toast-close qym-icon-action"', source)
    title_copy_rule = datasets.split(
        ".dsx-item-title-line .tv-copy-btn {",
        1,
    )[1].split("}", 1)[0]
    assert "opacity" not in title_copy_rule

    canonical_copy_icon = (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        'aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"/>'
        '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 '
        '2 2v1"/></svg>'
    )
    for source in (
        datasets,
        (DASHBOARD_DIR / "trace_viewer.js").read_text(encoding="utf-8"),
        docs,
        run,
        compare,
    ):
        assert canonical_copy_icon in source
        assert 'stroke="#9898a8"' not in source

    icon_action_rule = components.split(
        "/* Compact icon actions — quiet surfaces; only the glyph changes on hover. */",
        1,
    )[1]
    assert ".copy-btn," in icon_action_rule
    assert "background: transparent" in icon_action_rule
    assert "color: var(--accent-primary)" in icon_action_rule
    assert "outline: 1px solid var(--accent-primary)" in icon_action_rule
    assert ").qym-icon-action.copied" in icon_action_rule
    assert ".samples-toggle," in icon_action_rule
    assert ".toast-close," in icon_action_rule
    hover_rule = icon_action_rule.split("):hover {", 1)[1].split("}", 1)[0]
    copied_rule = icon_action_rule.split(").qym-icon-action.copied {", 1)[1].split("}", 1)[0]
    focus_rule = icon_action_rule.split("):focus-visible {", 1)[1].split("}", 1)[0]
    for state_rule in (hover_rule, copied_rule, focus_rule):
        assert "background: transparent;" in state_rule
        assert "box-shadow: none;" in state_rule
        assert "color-mix(" not in state_rule
    assert "0 0 12px color-mix(in srgb, var(--accent-primary)" not in icon_action_rule


def test_trace_actions_use_shared_inline_treatment_and_precede_copy() -> None:
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
    components = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")

    assert ".qym-trace-action" in components
    assert ".qym-inline-action.qym-inline-action--neutral.qym-trace-action:is(:hover, :focus-visible)" in components
    assert ".item-run-output .output-actions" in components
    assert 'class="action-chip trace-drawer-btn"' not in run
    assert 'class="action-chip trace-drawer-btn"' not in compare
    assert "qym-inline-action qym-inline-action--neutral qym-trace-action" in run
    assert "qym-inline-action qym-inline-action--neutral qym-trace-action" in compare
    assert (
        '<span class="output-actions">' + "' + traceChip + copyBtn + '" + '</span>'
        in run
    )
    assert '<span class="output-actions">${traceButton}${copyBtn}</span>' in compare


def test_error_filter_cards_match_page_hover_and_keyboard_states() -> None:
    for name in ("run.html", "compare.html"):
        source = (DASHBOARD_DIR / name).read_text(encoding="utf-8")
        error_styles = source.split(
            ".breakdown-errors.task-error-group .error-card:not(.active):is(:hover, :focus-visible)",
            1,
        )[1].split(".error-card-top", 1)[0]

        for contract in (
            "border-left-color: color-mix(in srgb, var(--error) 35%, transparent)",
            "border-left-color: color-mix(in srgb, var(--warning) 42%, transparent)",
            "border-color: var(--border-strong)",
            "box-shadow: 0 2px 16px rgba(0, 0, 0, 0.12)",
            "outline: 1px solid var(--accent-primary)",
        ):
            assert contract in error_styles
        assert "background: var(--bg-hover)" not in error_styles

        if name == "compare.html":
            surface_rule = source.split(
                "/* Error Distribution cards use the same analysis surface as run detail. */",
                1,
            )[1].split("}", 1)[0]
            assert "background: var(--bg-surface);" in surface_rule
            assert "border-radius: 10px;" in surface_rule
            assert "padding: 10px 12px;" in surface_rule
            assert "gap: 2px;" in surface_rule
            assert "min-height: 0;" in surface_rule
            hover_rule = source.split(
                ".breakdown-errors .error-card:hover {", 1
            )[1].split("}", 1)[0]
            assert "border-top-color: var(--border-strong);" in hover_rule
            assert "box-shadow: 0 2px 16px rgba(0, 0, 0, 0.12);" in hover_rule
            empty_state_rule = source.split(
                ".category-empty-state,\n    .section-empty-state {", 1
            )[1].split("}", 1)[0]
            assert "min-height: 80px;" in empty_state_rule
            assert "background: var(--bg-elevated);" not in empty_state_rule
            assert "border: 1px dashed var(--border-subtle);" not in empty_state_rule

        assert (
            '" role="button" tabindex="0" aria-pressed="'
            + "' + (isActive ? 'true' : 'false') + '"
            in source
        )
        assert "card.addEventListener('keydown', (e) => {" in source
        assert "e.key !== 'Enter' && e.key !== ' '" in source
        assert "e.preventDefault();" in source


def test_reviews_and_dataset_controls_match_the_approved_shared_components() -> None:
    reviews = (DASHBOARD_DIR / "reviews.html").read_text(encoding="utf-8")
    datasets = (DASHBOARD_DIR / "datasets.html").read_text(encoding="utf-8")
    components = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")

    assert 'class="qym-segmented reviews-source-segmented"' in reviews
    for source in ("", "ai_only", "human_only", "corrected"):
        assert f'data-source="{source}"' in reviews
    assert 'class="filter-chip qym-chip active" data-source=' not in reviews

    assert "className: 'qym-control qym-select', 'aria-label': 'Sort datasets'" in datasets
    assert "+ New dataset ▾" not in datasets
    assert "+ Create your first dataset ▾" not in datasets
    assert "'aria-haspopup': 'menu', style: { flex: 'none' } }, '+ New dataset'" in datasets
    assert "className: 'qym-chip'" in datasets
    assert "qym-tag qym-tag--version" in datasets
    assert "qym-tag qym-tag--count qym-tag--success" in datasets
    assert "#dsx-detail-tabs.qym-tabs {" in components
    detail_tabs = components.split("#dsx-detail-tabs.qym-tabs {", 1)[1].split("}", 1)[0]
    assert "padding-inline: var(--space-md)" in detail_tabs
    assert "overflow-x: auto" in detail_tabs
    assert "flex-wrap: nowrap" in detail_tabs
    assert ".dsx-item-tabs.qym-tabs {" in components
    item_tabs = components.split(".dsx-item-tabs.qym-tabs {", 1)[1].split("}", 1)[0]
    assert "padding-inline: var(--space-md)" in item_tabs
    assert ".dsx-item-actions > .shell-btn.qym-inline-action {" in components
    assert datasets.count("shell-btn shell-btn-primary qym-inline-action") >= 2
    assert datasets.count("shell-btn shell-btn-secondary qym-inline-action") == 2
    assert "shell-btn shell-btn-danger qym-inline-action" in datasets
    assert "requestAnimationFrame(() => activeTab.scrollIntoView({ block: 'nearest', inline: 'nearest' }));" in datasets


def test_rerendered_controls_restore_keyboard_focus() -> None:
    dashboard = DASHBOARD_JS.read_text(encoding="utf-8")
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
    reviews = (DASHBOARD_DIR / "reviews.html").read_text(encoding="utf-8")
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")

    assert "const restoreFocus = (kind, value)" in dashboard
    assert "restoreMetricVisibilityFocus('checkbox', metric);" in dashboard
    assert "restoreModelsStatVisibilityFocus('checkbox', statKey);" in dashboard
    assert "replacement?.focus({ preventScroll: true });" in dashboard
    assert 'container.querySelector(`[data-compare-tab="${nextTab}"]`)?.focus' in compare
    assert "restoreMultiselectFocus('checkbox', selectedValue)" in reviews
    assert "await renderSamplesAnalysis();" in run
    assert "replacement?.focus({ preventScroll: true });" in run


def test_shared_help_markers_are_keyboard_and_touch_operable() -> None:
    behavior = (DASHBOARD_DIR / "ui_components.js").read_text(encoding="utf-8")
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")

    for source in (DASHBOARD_JS.read_text(encoding="utf-8"), run, compare):
        assert 'class="stat-info-icon qym-help-marker' in source
        assert 'role="tooltip"' in source
        assert 'aria-expanded="false"' in source
    assert "marker.classList.toggle('is-open', !wasOpen);" in behavior
    assert "event.key === 'Escape'" in behavior
    assert "marker.focus({ preventScroll: true });" in behavior
    assert "marker.setAttribute('aria-describedby', tooltip.id);" in behavior
    assert "directTabs(tablist)" in behavior
    assert "'ArrowLeft', 'ArrowRight', 'Home', 'End'" in behavior


def test_compare_html_export_is_self_contained_and_export_safe() -> None:
    source = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")

    assert "async function inlineCompareExportAssets(html)" in source
    assert "(?:dashboard|shell|ui_components)\\.css" in source
    assert "(?:metrics|trace_viewer|ui_components)\\.js" in source
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
    assert "className: 'status-badge qym-badge status-' + status" in runs_tab_block
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


def test_data_pagination_uses_one_shared_first_last_control() -> None:
    datasets = (DASHBOARD_DIR / "datasets.html").read_text(encoding="utf-8")
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
    index = (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8")
    admin = (DASHBOARD_DIR / "admin.html").read_text(encoding="utf-8")
    dashboard_js = DASHBOARD_JS.read_text(encoding="utf-8")
    shared_js = (DASHBOARD_DIR / "ui_components.js").read_text(encoding="utf-8")
    shared_css = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")

    assert "function renderPagination(host, options)" in shared_js
    for action in ("first", "prev", "next", "last"):
        assert f'data-qym-page="{action}"' in shared_js
        assert f"PAGINATION_ICONS.{action}" in shared_js
    assert 'class="qym-pagination__input"' in shared_js
    assert "style=\"--qym-page-digits:" in shared_js
    assert "' + start + '–' + end + ' of ' + total + ' ' + noun" in shared_js
    assert ">First</button>" not in shared_js
    assert ">Previous</button>" not in shared_js
    assert ">Next</button>" not in shared_js
    assert ">Last</button>" not in shared_js
    assert "onPageChange" in shared_js
    assert "onPageSizeChange" in shared_js
    assert ".qym-pagination__controls" in shared_css
    assert "height: var(--control-height);" in shared_css
    assert "border-radius: var(--control-radius);" in shared_css
    assert ".qym-pagination__button:hover:not(:disabled)" in shared_css
    controls_rule = shared_css.split(".qym-pagination__controls {", 1)[1].split("}", 1)[0]
    assert "border: 0;" in controls_rule
    assert "background: transparent;" in controls_rule
    assert ".qym-pagination .qym-pagination__button svg" in shared_css
    input_rule = shared_css.split(".qym-pagination__input {", 1)[1].split("}", 1)[0]
    assert "width: max(28px, calc(var(--qym-page-digits, 1) * 1ch + 8px));" in input_rule
    assert "border: 1px solid var(--border-subtle);" in input_rule
    assert "border-radius: var(--control-radius);" in input_rule
    assert "background: var(--bg-elevated);" in input_rule

    datasets_items_block = datasets.split("async function renderItemsTab(host){", 1)[1].split("    // -------------------------------------------------------------\n    // ITEM DRAWER", 1)[0]
    assert "id: 'dsx-pager-top'" not in datasets_items_block
    assert "pagerTop" not in datasets_items_block
    assert "className: 'dsx-pager qym-pagination', id: 'dsx-pager'" in datasets_items_block
    assert "className: 'dsx-table-wrap paged', id: 'dsx-table-wrap'" in datasets_items_block
    assert "position: fixed; left: 0; right: 0; bottom: 0;" in datasets
    assert "renderPagination(pager, {" in datasets_items_block
    assert "pageSizeOptions: [25, 50, 100, 250]" in datasets_items_block

    assert 'id="pagination-top"' not in run
    assert "paginationEls" not in run
    assert 'class="pagination qym-pagination" id="pagination"' in run
    run_filter_panel = run.split('<div class="filter-panel">', 1)[1].split('<div class="items-grid" id="items-grid">', 1)[0]
    assert 'id="pagination"' not in run_filter_panel
    assert ".items-comparison {\n      margin-bottom: var(--space-xl);\n    }" in run
    assert "renderPagination(paginationEl, {" in run
    assert "onPageChange: page =>" in run
    assert "function scrollItemByItemToTop()" in run
    assert "document.querySelector('.items-comparison')" in run
    assert "scheduleBreakdownRender(preserveAnchor, scrollToTop ? scrollItemByItemToTop : null)" in run
    assert "host.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });" in run
    assert "container.scrollIntoView" not in run

    assert 'id="pagination-top"' not in compare
    assert "paginationEls" not in compare
    assert 'class="pagination qym-pagination" id="pagination"' in compare
    compare_filter_panel = compare.split('<div class="filter-panel">', 1)[1].split('<div class="items-grid" id="items-grid">', 1)[0]
    assert '<div class="pagination qym-pagination" id="pagination"' not in compare_filter_panel
    assert '<div class="items-grid" id="items-grid"></div>\n          <div class="pagination qym-pagination" id="pagination"' in compare
    assert "renderPagination(paginationEl, {" in compare
    assert "function scrollItemByItemToTop()" in compare
    assert "requestAnimationFrame(scrollItemByItemToTop);" in compare
    assert "container.scrollIntoView" not in compare

    assert 'id="table-pagination-top"' not in index
    assert 'class="table-pagination qym-pagination" id="table-pagination"' in index
    footer_block = index.split('<footer class="status-bar">', 1)[1].split('</footer>', 1)[0]
    assert 'class="status-center"' in footer_block
    assert 'id="table-pagination"' in footer_block
    assert "pagination(host, {" in dashboard_js
    assert "tablePagination.style.display = state.currentView === 'table' ? 'flex' : 'none';" in dashboard_js

    assert 'id="recent-runs-pagination"' in admin
    assert "renderPagination(document.getElementById('recent-runs-pagination'), {" in admin


def test_runs_table_has_persistent_bottom_horizontal_scrollbar() -> None:
    index = (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8")
    shared_js = (DASHBOARD_DIR / "ui_components.js").read_text(encoding="utf-8")
    shared_css = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")

    assert 'data-qym-scroll-mirror-for="runs-table-scroll"' in index
    assert 'id="runs-table-scroll"' in index
    assert 'role="scrollbar"' in index
    assert 'aria-orientation="horizontal"' in index
    assert 'class="qym-scroll-mirror__track"' in index
    assert 'class="qym-scroll-mirror__thumb"' in index
    assert "function setupScrollMirror(mirror)" in shared_js
    assert "target.classList.add('qym-scroll-mirror-target');" in shared_js
    assert "target.addEventListener('scroll', updateThumb" in shared_js
    assert "track.addEventListener('pointerdown'" in shared_js
    assert "thumb.addEventListener('pointermove'" in shared_js
    assert "mirror.addEventListener('wheel'" in shared_js
    assert "event.key === 'Home'" in shared_js
    assert "event.key === 'End'" in shared_js
    assert ".qym-scroll-mirror" in shared_css
    hidden_native_rule = shared_css.split(
        ".qym-scroll-mirror-target::-webkit-scrollbar {", 1
    )[1].split("}", 1)[0]
    assert "scrollbar-width: none;" in shared_css
    assert "width: 0;" in hidden_native_rule
    assert "height: 0;" in hidden_native_rule
    scroll_rule = shared_css.split(".qym-scroll-mirror {", 1)[1].split("}", 1)[0]
    assert "position: fixed;" in scroll_rule
    assert "bottom: var(--status-bar-height);" in scroll_rule
    assert "border: 0;" in scroll_rule
    assert "background: transparent;" in scroll_rule
    track_rule = shared_css.split(".qym-scroll-mirror__track {", 1)[1].split("}", 1)[0]
    thumb_rule = shared_css.split(".qym-scroll-mirror__thumb {", 1)[1].split("}", 1)[0]
    active_rule = shared_css.split(".qym-scroll-mirror__thumb:active {", 1)[1].split("}", 1)[0]
    assert "background: transparent;" in track_rule
    assert "background: rgba(120, 120, 150, 0.55);" in thumb_rule
    assert "background: rgba(80, 80, 94, 0.92);" in active_rule
    assert "var(--accent-primary)" not in active_rule


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
