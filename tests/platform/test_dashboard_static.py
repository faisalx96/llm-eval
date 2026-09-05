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
REPEAT_PASSES_SERVICE = (
    ROOT
    / "packages"
    / "platform"
    / "qym_platform"
    / "services"
    / "repeat_passes.py"
)
ANALYZER_HTML = DASHBOARD_DIR / "analyzer.html"


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


def test_run_and_compare_exports_keep_independent_scroll_containers() -> None:
    """Regression guard for the two standalone export pages."""
    for filename, selector in (
        ("run.html", ".run-container"),
        ("compare.html", ".compare-container"),
    ):
        markup = (DASHBOARD_DIR / filename).read_text(encoding="utf-8")
        rule = _rule(markup, selector)
        assert "height: calc(100vh - 100px);" in rule
        assert "overflow-y: auto;" in rule


def test_approval_filters_include_metric_scoped_reviews() -> None:
    """Metric approvals must participate in both dashboard filter views."""
    run_source = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    compare_source = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")

    assert "row.review_corrections" in run_source
    assert (
        "matchesApprovalFilter(row, state.approvalFilter, state.selectedMetric)"
        in run_source
    )
    assert "getApprovalState(row, state.selectedMetric)" in run_source
    assert "row.review_corrections" in compare_source
    assert (
        "matchesApprovalFilter(r, state.approvalFilter, state.selectedItemsMetric)"
        in compare_source
    )
    assert "getApprovalState(r, state.selectedItemsMetric)" in compare_source


def test_repeat_run_rows_are_ordinary_rows_with_pass_count_chip() -> None:
    """×k rows read as ordinary data rows: no special surface, no dot
    strip — the chevron and the pass-count chip carry the signal."""
    source = DASHBOARD_JS.read_text(encoding="utf-8")
    styles = (DASHBOARD_DIR / "dashboard.css").read_text(encoding="utf-8")

    assert 'class="run-pass-count"' in source
    assert "x${run.samples}" in source
    # the dot strip and the special row surface are gone
    assert "renderPassDots" not in source
    assert "repeat-run-header" not in source
    assert "repeat-run-header" not in styles
    assert ".pdot" not in styles
    assert ".pass-dots" not in styles

    assert ".run-pass-count" in styles


def test_run_column_wraps_names_at_400px() -> None:
    styles = (DASHBOARD_DIR / "dashboard.css").read_text(encoding="utf-8")

    assert "--runs-col-run-width: 400px;" in styles
    assert "--runs-col-run-min-width: 400px;" in styles
    assert "--runs-col-run-max-width: 400px;" in styles
    run_id_rule = _rule(styles, ".run-cell-content .run-id {")
    assert "overflow-wrap: anywhere;" in run_id_rule
    assert "white-space: normal;" in run_id_rule
    assert "text-overflow: clip;" in run_id_rule


def test_live_repeat_progress_is_shown_on_the_active_pass_only() -> None:
    source = DASHBOARD_JS.read_text(encoding="utf-8")

    assert "const parentProgressText = run.samples > 1" in source
    assert ">${status}${passText}${parentProgressText}</span>" in source
    assert "const completedCount = Number(pass.completed_count) || 0;" in source
    assert "const totalCount = Number(pass.items_total) || 0;" in source
    assert "Math.round((completedCount / totalCount) * 100)" in source
    assert "${statusLabel}${progressLabel}</span>" in source


def test_stopped_repeat_run_never_renders_a_running_pass() -> None:
    source = DASHBOARD_JS.read_text(encoding="utf-8")
    api = RUNS_API.read_text(encoding="utf-8")

    assert "stopped: 'STOPPED'" in source
    assert "rawPassStatus === 'running' && terminalPassStatus" in source
    assert "String(pass.status || '').toLowerCase() === 'running'" in source
    assert api.count("_repeat_pass_status(") == 3


def test_repeat_passes_use_runs_view_bulk_delete_action() -> None:
    source = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    dashboard = DASHBOARD_JS.read_text(encoding="utf-8")
    api = RUNS_API.read_text(encoding="utf-8")
    service = REPEAT_PASSES_SERVICE.read_text(encoding="utf-8")

    assert 'data-delete-pass="' not in source
    assert 'class="pass-checkbox"' in dashboard
    assert "const passGroups = new Map();" in dashboard
    assert "body: JSON.stringify({ pass_numbers: group.passNumbers })" in dashboard
    assert 'class="pass-delete-action qym-icon-action action-icon delete-run"' in dashboard
    assert "data-can-delete-pass=" in dashboard
    assert "await fetchRuns({ refreshAllPages: true });" in dashboard
    assert "delete state._samplesData[runId];" in dashboard
    single_delete_handler = dashboard.split(
        "function insertSamplesDetail(runId, row, panelId, animate)", 1
    )[1].split("async function loadSamplesData", 1)[0]
    assert "const runFilePath = decodeURIComponent(row?.dataset?.file || '');" in single_delete_handler
    assert "if (runFilePath) {" in single_delete_handler
    assert '@router.delete("/api/runs/{run_id}/passes/{pass_number}")' in api
    assert '@router.delete("/api/runs/{run_id}/passes")' in api
    assert 'action="run.pass_deleted"' in service


def test_repeat_parent_checkbox_selects_its_current_scope() -> None:
    source = DASHBOARD_JS.read_text(encoding="utf-8")
    index = (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8")

    # Collapsed repeat rows represent the logical run; expanded rows represent
    # the selectable execution members shown directly beneath them.
    assert "samplesOpen ? 'Select all passes for' : 'Select run'" in source
    assert "if (expanded) {\n            toggleExpandedPassSelection(run, tr);" in source
    assert "checkbox.checked = state.selectedRuns.has(filePath);" in source
    assert "checkbox.checked = refs.length > 0 && selectedCount === refs.length;" in source
    assert "checkbox.indeterminate = selectedCount > 0 && selectedCount < refs.length;" in source
    assert "const repeatExpanded = run.samples > 1" in source
    assert "checkbox.indeterminate = repeatExpanded" in source
    assert "isPartiallySelected" not in source
    assert "state.selectedRuns.delete(filePath);" in source
    assert "if (!allSelected) refs.forEach(ref => state.selectedRuns.add(ref));" in source
    assert "dashboard.js?v=repeat-compare-pass-selection-" in index


def test_repeat_comparison_selection_expands_to_exact_passes() -> None:
    dashboard = DASHBOARD_JS.read_text(encoding="utf-8")
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")

    # A collapsed repeat selection is still a logical run in the Runs table,
    # but comparison columns are executions: selecting x10 yields Pass 1..10.
    assert (
        "const files = expandComparisonRefs(Array.from(state.selectedRuns));"
        in dashboard
    )
    assert "function expandComparisonRefs(filePaths)" in dashboard
    assert "expanded.push(`${ref}${PASS_REF_SEP}${passNumber}`);" in dashboard
    assert "compareBtn.disabled = selectedExecutionCount < 2;" in dashboard
    assert (
        "`${selectedExecutionCount} execution${selectedExecutionCount === 1 ? '' : 's'} selected`"
        in dashboard
    )
    assert "left: expandComparisonRefs(left)" in dashboard
    assert "right: expandComparisonRefs(right)" in dashboard

    # Shared/manual compare URLs get the same expansion, and a requested pass
    # is matched by pass_number. It must never inherit the aggregate final pass.
    pass_slice = compare.split("function sliceRunToPass", 1)[1].split(
        "function expandPassRefIds", 1
    )[0]
    pass_expand = compare.split("function expandPassRefIds", 1)[1].split(
        "function makeSafeDomId", 1
    )[0]
    assert "Number(candidate.pass_number) === passNo" in pass_slice
    assert "output: att ? (att.output ?? null) : null" in pass_slice
    assert "return row.metric_values ? row.metric_values[i] : '';" not in pass_slice
    assert "const fallback = row.metric_meta?.[m];" not in pass_slice
    assert "for (let passNo = 1; passNo <= samples; passNo += 1)" in pass_expand
    assert "out.push(`${base}${PASS_REF_SEP}${passNo}`)" in pass_expand
    assert "[sliceRunToPass(rd, ref, passNo)]" in pass_expand
    assert "state.explicitGroupedOutcomeGroups.leftRunIds = expandPassRefIds" in compare
    assert "?pass_number=${encodeURIComponent(passNumber)}" in compare


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


def test_individual_run_navigation_clears_comparison_state() -> None:
    dashboard = DASHBOARD_JS.read_text(encoding="utf-8")
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")

    open_run = dashboard.split("function openRun(filePath, e)", 1)[1].split(
        "function openComparison", 1
    )[0]
    assert "sessionStorage.removeItem('compareRuns');" in open_run
    assert "sessionStorage.removeItem('compareCohorts');" in open_run
    assert "COMPARE_PASSES" not in run
    assert "const isRepeatItem = !state.viewPass" in run
    assert "renderAnswerColumns(baseRow, itemId, displayItemId, metric, threshold)" in run
    assert "? 'OUTPUT · PASS ' + state.viewPass" in run


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
    assert ".runs-table thead tr.has-repeat-rows .run-header-label::before" in styles
    for column in ("dataset", "owner", "time"):
        assert f".runs-table > tbody > tr.samples-open > td.col-{column}" in styles
    assert "width: calc(var(--runs-disclosure-size) + var(--space-sm));" in styles
    assert ".samples-toggle.open .samples-toggle-chevron" in styles
    toggle_hover = _rule(
        styles,
        ".runs-table > tbody > tr[data-idx]:hover .samples-toggle,",
    )
    assert "color: var(--accent-primary);" in toggle_hover
    assert "background: transparent;" in toggle_hover
    toggle_stroke = _rule(
        styles,
        ".runs-table > tbody > tr[data-idx]:hover .samples-toggle-chevron,",
    )
    assert "stroke: var(--accent-primary);" in toggle_stroke
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
    assert "scores[passNumber - 1]" in source
    assert "function scopedPassMetricMeta(row, metricNames, passNumber)" in source
    assert "function scopeRowToPass(row, metricNames, passNumber)" in source
    assert "metric_meta: passMetricMeta" in source
    assert "next = scopeRowToPass(next, state.allMetrics, state.viewPass);" in source
    # no banner — the headline pill carries the pass label and the way back
    assert "pass-scope-banner" not in source
    assert "Return to all passes." in source
    # pass pages read as a single run: no group tiles/sweep/curve, no
    # Repeat Stability chart panels, no per-pass dot strips on item cards
    assert "if (samplesCount <= 1 || IS_EXPORT || state.viewPass)" in source
    assert source.count("const repeatSeries = state.viewPass ? [] :") == 1
    assert "const isRepeatItem = !state.viewPass" in source
    # edits are allowed and routed to the viewed pass
    assert "const passNumber = Number(btn.dataset.passNumber) || state.viewPass || null;" in source
    assert "updateMetricScore(filePath, rowIndex, metricName, input.value, passNumber)" in source
    assert "...(passNumber ? { pass_number: passNumber } : {})," in source
    # applying the server row keeps per-pass fields and re-applies the lens
    assert "let next = { ...rows[pos], ...updatedRow };" in source
    assert "function scopedPassAttempt(row, passNumber)" in source
    assert "Number(candidate.pass_number) === passNumber" in source
    assert "const att = scopedPassAttempt(row, passNumber);" in source
    assert "? 'OUTPUT · PASS ' + state.viewPass" in source
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
    assert "const positionalAttempt = attempts[passNumber - 1];" in source
    assert "task_started_at_ms: att?.task_started_at_ms ?? null" in source
    assert "retry_count: Number(att?.retry_count || 0)" in source
    assert "trace_stats: att?.trace_stats || null" in source
    assert "'?pass_number=' + encodeURIComponent(att.pass_number)" in source
    assert "state.viewPass ? '?pass_number=' + encodeURIComponent(state.viewPass)" in source
    # Missing attempts become pending instead of inheriting the latest
    # run-level output/status. Header and trace summary use the pass endpoint.
    assert "output: att ? (att.output ?? null) : null" in source
    assert "fetch(apiUrl('api/runs/' + RUN_ID + '/passes'))" in source
    assert "const pass = state.viewPass ? state.passSummary : null;" in source
    assert "let runtimeMs = pass ? pass.duration_ms : run.duration_ms;" in source
    assert "? state.passSummary?.trace_stats" in source
    # A selected pass now has its own diagnosis scope; the aggregate page
    # keeps the read-only root-cause summary visible instead of hiding it.
    assert "function isRepeatAggregateView()" in source
    assert "if (aggregateRepeatView) perMetricAnalysisHtml = '';" in source
    assert "pass_metric_analyses" in source
    assert "status: String(analysis.review_status || 'pending').toLowerCase()" in source
    assert "const reviewStatus = hasStoredAnalysis" in source
    assert "if (state.viewPass) approvalBody.pass_number = state.viewPass;" in source
    assert "id: data.id || correctionId || null" in source
    assert "if (IS_EXPORT || isRepeatAggregateView()) return '';" in source
    assert "window.QymShell?.openConfirmDialog" in source
    assert "Only this sample will be changed." in source
    assert "...(passNumber ? { pass_number: passNumber } : {})" in source

    # the lens and its All/pass dot switcher are gone: expanded repeat items
    # use independently visible output cards and one synchronized detail band
    assert "state.itemPassLens" not in source
    assert "pass-dot-switch" not in source
    assert "pass-lensed" not in source
    assert "renderAnswerColumns" in source
    assert 'class="qym-output-toggle"' in source
    assert 'class="qym-output-group__title">Output' in source
    assert 'data-output-metric="' in source
    assert 'data-metric-panel="' in source
    assert 'data-pass-number="' in source
    assert "itemHiddenOutputs" in source
    assert "itemComparedMetric" in source
    assert 'aria-pressed="' in source

    # the API ships per-pass attempts on run-detail rows, and update_metric
    # accepts a pass_number and re-reduces the run-level mean
    api = RUNS_API.read_text(encoding="utf-8")
    assert '"pass_attempts": (' in api
    assert "RunItemAttempt.is_last_attempt.is_(True)" in api
    assert '"completed_count": completed_by_pass.get(p, 0)' in api
    assert '"running_count": (' in api
    assert 'running_by_pass.get(p, 0) if status == "running" else 0' in api
    assert 'pass_number = request.get("pass_number")' in api
    assert "Re-reduce: run-level score = mean over all stored passes" in api


def test_repeat_and_compare_share_grouped_output_interaction() -> None:
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
    components = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")

    for source in (run, compare):
        assert 'class="qym-output-group"' in source
        assert 'class="qym-output-toggle"' in source
        assert 'data-output-card="' in source
        assert 'data-output-metric="' in source
        assert 'data-metric-panel="' in source
        assert 'class="qym-metric-compare' in source
        assert "wireOutputGroupHandlers" in source
        assert "itemHiddenOutputs" in source
        assert "itemComparedMetric" in source

    # Repeat edits address a pass. Compare edits address a run. Both expose
    # explicit soft save/cancel actions in the aligned comparison band.
    assert 'data-pass-number="' in run
    assert 'data-run-idx="' in compare
    assert 'class="metric-edit-cancel qym-metric-edit-action"' in run
    assert 'class="metric-edit-cancel qym-metric-edit-action"' in compare
    assert "renderCompareOutputGroup(itemId, rowData)" in compare
    assert '<span class="qym-output-group__title">Output</span><div class="qym-output-toggles"' in run
    assert '<span class="qym-output-group__title">Output</span><div class="qym-output-toggles"' in compare
    assert "qym-metric-compare__header" not in run.split("function renderAnswerColumns", 1)[1].split("function _parseMetaDeep", 1)[0]
    assert "qym-metric-compare__header" not in compare.split("function renderCompareOutputGroup", 1)[1].split("function renderItemComparisonCard", 1)[0]
    assert "qym-metric-compare__cell-name" not in components
    assert 'class="det-toggle metric-compare-row' in run
    assert 'class="det-toggle metric-compare-row' in compare
    assert "const hasPassDetails = passDetails.some" in run
    assert "Pass-specific details were not recorded for this run; showing the run-level result." in run
    assert "(baseRow.metric_meta || {})[name]" in run
    # Verdicts describe individual executions beside their identity. The
    # collapsed repeat row no longer presents an aggregate Pass/Fail label.
    repeat_outputs = run.split("function renderAnswerColumns", 1)[1].split(
        "function _parseMetaDeep", 1
    )[0]
    compare_outputs = compare.split("function renderCompareOutputGroup", 1)[1].split(
        "function renderItemComparisonCard", 1
    )[0]
    collapsed_run_header = run.split("// Collapsed header:", 1)[1].split(
        "if (!isExpanded)", 1
    )[0]
    assert "verdictFor(att)" in repeat_outputs
    assert "passIdentityFor(att)" in repeat_outputs
    assert "window.location.pathname + '?pass=' + encodeURIComponent(att.pass_number)" in repeat_outputs
    assert 'class="qym-output-card__link"' in repeat_outputs
    assert "${identityHtml}${verdictFor(row, runIdx)}" in compare_outputs
    assert "(!isExpanded && !isRepeatItem ? statusIndicator : '')" in collapsed_run_header
    assert "qym-tag--success" in repeat_outputs
    assert "qym-tag--danger" in compare_outputs
    # Comparing repeat passes preserves pass-aware editing instead of writing
    # the aggregate run score or replacing the sliced row with aggregate data.
    assert "const baseFilePath = passRefBase(filePath);" in compare
    assert "...(Number.isFinite(passNumber) ? { pass_number: passNumber } : {})," in compare
    assert "updatedRow.pass_scores?.[name]" in compare

    for selector in (
        ".qym-output-group",
        ".qym-output-toggle",
        ".qym-output-grid",
        ".qym-output-card.item-run-output",
        ".qym-metric-compare",
        ".qym-metric-compare__grid",
        ".qym-metric-edit-action",
    ):
        assert selector in components

    # Long output bodies use a shared viewport-aware reading area rather
    # than the old 300px ceiling. Compare derives its alignment cap from
    # that CSS so layout and overflow cannot drift apart again.
    output_body = _rule(components, ".qym-output-card > .output-text {")
    assert "max-height: min(58vh, calc(var(--space-xl) * 18));" in output_body
    assert "window.getComputedStyle(el).maxHeight" in compare
    assert "el.querySelector('.formatted-table-grid') ? 640 : 300" not in compare

    # Editing is a true swap state: the resting score/edit icon disappear,
    # while long metric names and the semantic actions remain contained.
    assert ".det-toggle.editing > .metric-edit-open" in components
    assert ".metric-det-chips .det-toggle.editing" in components
    assert 'const EDIT_ICON = \'<svg viewBox="0 0 16 16" fill="none" stroke="currentColor"' in run
    assert 'const EDIT_ICON = \'<svg viewBox="0 0 16 16" fill="none" stroke="currentColor"' in compare


def test_boolean_metric_observations_stay_boolean_across_item_views() -> None:
    """Legacy repeat artifacts infer from pass observations, while only the
    unreduced repeat item aggregate is rendered as a percentage rate."""
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")

    assert "const passObservationRows = state.viewPass ? []" in run
    assert "row.pass_scores?.[metricName]" in run
    assert "window.QymMetrics.detectMetricType(passObservationRows, 0)" in run

    # Repeat output cards and compare output cards both show one execution,
    # so a boolean score is True/False in both places.
    repeat_outputs = run.split("function renderAnswerColumns", 1)[1].split(
        "function _parseMetaDeep", 1
    )[0]
    compare_outputs = compare.split("function renderCompareOutputGroup", 1)[1].split(
        "function renderItemComparisonCard", 1
    )[0]
    assert "formatMetricObservation(v, mType" in repeat_outputs
    assert "formatMetricObservation(parsed, type" in compare_outputs

    # The all-passes item mean is still a rate; a ?pass=N page is an
    # observation and must not be forced back to percent formatting.
    assert run.count("&& !state.viewPass;") >= 2


def test_grouped_compare_joins_csv_rows_by_stable_compare_identity() -> None:
    """CSV row IDs may differ between runs; every compare mode must use the
    backend's content-derived identity instead of the raw per-run item ID."""
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
    grouped_outcomes = compare.split(
        "function getActiveGroupedOutcomeResults()", 1
    )[1].split("function canShowSweepTab()", 1)[0]

    assert "getItemId: getRowCompareId" in grouped_outcomes
    assert "row?.item_id || row?.compare_item_id" not in grouped_outcomes


def test_item_metric_rows_share_one_responsive_component() -> None:
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
    components = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")
    single_strip = run.split("function renderMetricStrip", 1)[1].split(
        "function renderItems", 1
    )[0]

    # Single, repeat, and compare use the same row/trigger anatomy; only the
    # detail synchronization behavior differs.
    assert 'class="det-toggle metric-compare-row' in single_strip
    assert 'class="metric-compare-trigger"' in single_strip
    assert 'class="det-toggle metric-compare-row' in run
    assert 'class="det-toggle metric-compare-row' in compare
    assert "querySelectorAll('[data-det-target]')" in run

    metric_grid = _rule(components, ".metric-det-chips,")
    assert "display: grid;" in metric_grid
    assert "repeat(auto-fit, minmax(220px, 1fr))" in metric_grid
    metric_row = _rule(components, ".metric-det-chips > .det-toggle,")
    assert "width: 100%;" in metric_row
    assert "border-radius: var(--control-radius);" in metric_row
    assert "min-height: calc(var(--control-height) + var(--space-xs));" in metric_row
    metric_zone = _rule(components, ".item-run-output > .metric-det-zone,")
    assert ".qym-output-card .metric-det-zone" in metric_zone
    assert "background: var(--bg-elevated);" in metric_zone
    caret = _rule(components, ".det-toggle .det-caret {")
    caret_active = _rule(
        components,
        ".det-toggle:is(:hover, :focus-within, .open) .det-caret,",
    )
    assert "color: var(--text-muted);" in caret
    assert "color: var(--accent-primary);" in caret_active
    assert ".metric-compare-trigger.active" in caret_active


def test_item_detail_cards_have_clear_neutral_and_interaction_states() -> None:
    """Run/repeat and compare keep the approved separated-card layout while
    sharing stronger zebra, disclosure, and collapsed-metric contrast."""
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
    components = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")

    for source, card_selector, collapsed_selector, even_selector in (
        (
            run,
            ".item-card {",
            ".item-card.item-collapsed {",
            ".items-grid > .item-card.item-collapsed:nth-child(even) {",
        ),
        (
            compare,
            ".item-comparison-row {",
            ".item-comparison-row.item-collapsed {",
            ".items-grid > .item-comparison-row.item-collapsed:nth-child(even) {",
        ),
    ):
        # Preserve the current separated, rounded composition.
        assert "gap: var(--space-sm);" in _rule(source, ".items-grid {")
        item_detail_styles = source[source.index(".items-grid {"):]
        assert "border-radius: 8px;" in _rule(item_detail_styles, card_selector)

        collapsed = _rule(source, collapsed_selector)
        assert "border: 1px solid var(--border-subtle);" in collapsed
        assert "background: var(--bg-surface);" in collapsed
        assert "background: var(--bg-elevated);" in _rule(source, even_selector)

        chevron = _rule(source, ".item-chevron {")
        assert "background: transparent;" in chevron
        assert "color: var(--text-dim);" in chevron
        chevron_hover = _rule(
            source,
            ".item-header-expand:is(:hover, :focus-visible) .item-chevron {",
        )
        assert "background: transparent;" in chevron_hover
        assert "color: var(--accent-primary);" in chevron_hover

    metric = _rule(components, ".qym-item-metric-cell {")
    assert "var(--text-primary) 6%, transparent" in metric
    assert "box-shadow: none;" in metric
    selected_metric = _rule(components, ".qym-item-metric-cell--selected {")
    assert "var(--text-primary) 9%, transparent" in selected_metric

    assert "qym-item-metric-cell--selected" in run
    assert "qym-item-metric-cell--selected" in compare


def test_item_summary_metrics_use_shared_column_alignment() -> None:
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
    behavior = (DASHBOARD_DIR / "ui_components.js").read_text(encoding="utf-8")

    assert "function alignMetricColumns(root, options)" in behavior
    assert "cell.getBoundingClientRect().width" in behavior
    assert "--qym-item-metric-columns" in behavior
    assert "alignMetricColumns: alignMetricColumns" in behavior

    components = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")
    metric_grid = _rule(components, ".qym-item-metric-grid {")
    assert "display: inline-grid;" in metric_grid
    assert "grid-auto-flow: column;" in metric_grid
    assert "grid-template-columns: var(--qym-item-metric-columns, none);" in metric_grid
    metric_cell = _rule(components, ".qym-item-metric-cell {")
    assert "justify-content: space-between;" in metric_cell

    for source in (run, compare):
        assert "qym-item-metric-grid" in source
        assert "qym-item-metric-cell" in source
        assert "data-qym-metric-grid" in source
        assert "data-qym-metric-column" in source
        assert "qym-item-metric-cell--empty" in source
        assert "window.QymUIComponents?.alignMetricColumns(container);" in source

    # Narrow screens retain the prior wrapping behavior instead of forcing
    # the desktop metric columns beyond the viewport.
    assert ".qym-item-metric-cell--empty { display: none; }" in components


def test_item_detail_section_has_one_defined_shared_shell() -> None:
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
    components = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")

    section = _rule(components, ".qym-item-section {")
    assert "border: 1px solid var(--border-subtle);" in section
    assert "background: color-mix(in srgb, var(--bg-surface) 30%, transparent);" in section
    query = _rule(components, ".qym-item-query {")
    assert "flex: 1 1 680px;" in query
    actions = _rule(components, ".qym-item-actions {")
    assert "margin-left: auto;" in actions
    results = _rule(components, ".qym-item-results {")
    assert "border-top: 1px solid var(--border-subtle);" in results

    for source in (run, compare):
        assert "items-comparison qym-item-section" in source
        assert "qym-item-section-head" in source
        assert "qym-item-result-meter" not in source
        assert "items-fmeter" not in source


def test_compare_expanded_item_shell_matches_run_detail() -> None:
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
    components = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")

    # Expanded comparison rows use the same compact orientation header as
    # run/repeat rows: item number + scope count, without repeating input or
    # selected-metric pills that are visible directly below.
    assert "const compactItemLabel = Number.isFinite(sourceRowIndex)" in compare
    assert '${isExpanded\n                  ? `<span class="item-header-spacer"></span><span class="item-pass-note">${visibleRunCount} run' in compare
    assert ': `<span class="item-title">${escapeHtml(titleText)}</span><span class="item-agg-pills qym-item-metric-grid" data-qym-metric-grid>${headerPills}</span>`}' in compare
    assert '<div class="input-label">INPUT ' in compare
    assert '<div class="expected-label">EXPECTED OUTPUT ' in compare

    shell = components.split("/* Expanded item shell", 1)[1].split(
        "/* Grouped outputs", 1
    )[0]
    assert ".item-header-spacer { flex: 1 1 auto; }" in shell
    assert ".item-pass-note" in shell
    assert ".item-input-row { border-left: 3px solid var(--accent-secondary); }" in shell
    assert "font-family: var(--font-sans);" in shell
    assert "font-family: var(--font-mono);" in shell
    assert "font-size: var(--font-sm);" in shell
    assert "letter-spacing: 0.5px;" in shell
    assert "text-transform: uppercase;" in shell


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
    assert 'class="threshold-control qym-threshold-control samples-repeat-threshold"' in source
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

    assert "const matchingRuns = (candidates ? candidates.rows : state.filteredRuns).filter" in models_block
    assert "candidates = await fetchModelCandidates();" in models_block
    assert "candidates ? candidates.scope.tasks" in models_block
    assert "candidates ? candidates.scope.datasets" in models_block
    assert "const matchingRuns = state.flatRuns.filter" not in models_block
    assert "state.filterModels.size > 0 && !state.filterModels.has('__none__')" not in models_block
    assert "? state.filteredRuns.filter(r => r.task_name === currentTask && getRunDatasetKey(r) === currentDataset)" in dropdown_block
    assert "? state.flatRuns.filter(r => r.task_name === currentTask && getRunDatasetKey(r) === currentDataset)" not in dropdown_block
    assert "currentTask && currentDataset && candidates ? candidates.metrics : []" in dropdown_block


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
    assert "api/dashboard/runs" in overview
    assert "statuses: ['RUNNING', 'PENDING'] }, 8, 'activity-desc'" in overview
    assert "statuses: ['DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED', 'COMPLETED', 'FAILED', 'STOPPED'] }, 5" in overview
    assert "method: 'POST'" in overview
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


def test_item_table_display_controls_use_shared_component_variants() -> None:
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
    components = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")

    for source in (run, compare):
        for control_id in ("metadata-fields-btn", "metric-meta-fields-btn"):
            assert (
                'class="metadata-fields-btn multi-select-btn qym-control qym-select" '
                f'id="{control_id}"'
            ) in source
            assert f'aria-controls="{control_id.removesuffix("-btn")}-dropdown"' in source
        assert 'class="threshold-slider qym-threshold-slider"' in source
        assert "--qym-range-value:80%" in source

    # Export is the shared borderless green action in the item toolbar.
    assert (
        'class="qym-inline-action qym-inline-action--accent" '
        'id="export-filtered-btn"'
    ) in run
    assert "fp-gear-btn metadata-fields-btn multi-select-btn qym-control" not in run
    assert 'class="fp-btn fp-export"' not in run

    for selector in (
        ".qym-threshold-control",
        ".qym-threshold-slider",
        ".qym-threshold-slider::-webkit-slider-thumb",
        ".qym-threshold-slider::-moz-range-progress",
        ".qym-threshold-value",
    ):
        assert selector in components
    assert "var(--accent-primary) var(--qym-range-value)" in components
    assert "style.setProperty('--qym-range-value'" in run
    assert "style.setProperty('--qym-range-value'" in compare

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


def test_dropdown_and_disclosure_chevrons_share_interaction_states() -> None:
    components = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")
    dashboard = (DASHBOARD_DIR / "dashboard.css").read_text(encoding="utf-8")
    behavior = (DASHBOARD_DIR / "ui_components.js").read_text(encoding="utf-8")
    playground = (DASHBOARD_DIR / "playground.js").read_text(encoding="utf-8")

    # Native and custom selects share one generated chevron. Native selects
    # use :open; custom dropdowns expose the same state through aria-expanded.
    for selector in (
        ".qym-select",
        ".multi-select-btn",
        "select.filter-select",
        "select.form-select",
        "select.samples-metric-select",
        "select.qym-pagination__size",
        "select.shell-form-input",
        ".fb-token select",
    ):
        assert selector in components
    assert "--qym-chevron-down-muted:" in components
    assert "--qym-chevron-down-accent:" in components
    assert "--qym-chevron-up-accent:" in components
    assert "d='M4.5 6.25 8 9.75l3.5-3.5'" in components
    assert "stroke-width='1.5'" in components
    assert "--qym-select-chevron-image: var(--qym-chevron-down-muted);" in components
    assert ":is(:hover, :focus-visible, :open)" in components
    assert ':is(.qym-select, .multi-select-btn)[aria-expanded="true"]' in components
    assert 'button:is(.qym-select, .multi-select-btn)[aria-expanded="true"]' in components
    assert "--qym-select-chevron-image: var(--qym-chevron-down-accent);" in components
    assert "--qym-select-chevron-image: var(--qym-chevron-up-accent);" in components
    assert "background-size: 14px 14px;" in components
    # Auto-analysis reuses the Reviews selector contract. The native select is
    # retained only as the value/event mirror and is hidden by the shared
    # enhancer after the Reviews control has been mounted.
    connection = _rule(dashboard, ".pg-connection {")
    connection_selector = _rule(dashboard, ".pg-connection-selector {")
    assert "width: min(360px, 100%);" in connection
    assert "min-width: 320px;" in connection_selector
    assert 'id="pg-connection" class="pg-connection-select"' in playground
    assert "QymUIComponents.enhanceSelect(connEl" in playground
    assert "className: 'pg-connection-selector'" in playground
    assert "placement: 'top'" in playground
    assert "pg-connection-trigger" not in playground
    assert "pg-connection-menu" not in playground

    # SVG/text disclosure chevrons share the quiet/hover signal. Item-row
    # chevrons rotate while open but remain neutral until hover/focus.
    for selector in (
        ".project-trigger-chevron",
        ".rseg-chev",
        ".context-section-caret",
        ".item-chevron",
        ".det-caret",
        ".samples-toggle",
        ".pg-section-chevron",
        ".tv-toggle",
        ".tv-metric-chevron",
        ".expand-btn .arrow",
    ):
        assert selector in components
    assert ".item-header-expand:is(:hover, :focus-visible) .item-chevron" in components
    assert ".item-chevron.open," not in components
    assert ".context-section[open] .context-section-caret" in components
    assert ".pg-section[open] > .pg-section-summary .pg-section-chevron" in components
    assert ".tv-metric-card.expanded .tv-metric-chevron" in components
    assert "color: var(--accent-primary);" in components

    # The shared observer keeps custom dropdown aria state synchronized when
    # page code opens or closes its menu by toggling the dropdown class.
    assert "record.target.matches('.multi-select-dropdown, .qym-dropdown')" in behavior
    assert "ensureDropdownButton(wrapper && wrapper.querySelector('.multi-select-btn'))" in behavior
    assert "attributeFilter: ['aria-selected', 'aria-pressed', 'class']" in behavior


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
    assert "metadata-fields-btn multi-select-btn qym-control qym-select" in compare
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

    # Run/repeat and compare keep the unified clear control beside Filters,
    # outside the expanded filter content.
    run_source = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    assert (
        'class="fp-clear-btn qym-clear-action qym-item-clear" '
        'id="clear-all-btn"'
    ) in run_source
    run_builder = run_source.split('id="item-filter-builder"', 1)[1].split(
        'id="filter-builder-body"', 1
    )[0]
    assert 'id="clear-all-btn"' not in run_builder
    compare_source = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
    assert '<span class="fp-clear-label">Clear</span>' in compare_source
    assert '<svg class="fp-clear-x" viewBox="0 0 12 12"' in compare_source
    compare_builder = compare_source.split('id="item-filter-builder"', 1)[1].split(
        'id="items-grid"', 1
    )[0]
    assert 'id="clear-all-btn"' not in compare_builder

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
        if page.name == "analyzer.html":
            assert "dashboard.css?v=rule-history-bottom-20260816-1" in source
            assert "playground.js?v=rule-history-bottom-20260816-1" in source
            assert "ui_components.css?v=auto-analysis-selectors-20260811-1" in source
            assert "ui_components.js?v=auto-analysis-selectors-20260811-1" in source
            continue
        if "ui_components.css?v=" in source:
            assert "ui_components.css?v=ui-consistency-20260803-60" in source
        if "ui_components.js?v=" in source:
            assert "ui_components.js?v=ui-consistency-20260803-28" in source


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


def test_run_selection_uses_explicit_mode_and_reclaims_checkbox_column() -> None:
    markup = (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8")
    source = DASHBOARD_JS.read_text(encoding="utf-8")
    styles = (DASHBOARD_DIR / "dashboard.css").read_text(encoding="utf-8")

    command_bar = markup.split('<div class="command-bar">', 1)[1].split(
        '<main class="runs-page-main">',
        1,
    )[0]
    assert 'id="select-mode-btn"' in command_bar
    assert command_bar.index('id="select-mode-btn"') < command_bar.index('id="display-tools"')
    assert 'id="compare-panel"' not in command_bar
    assert 'aria-pressed="false" aria-controls="runs-table-scroll">Select</button>' in markup

    main_at = markup.index('<main class="runs-page-main">')
    table_at = markup.index('id="table-view"')
    select_all_at = markup.index('id="select-all"')
    footer_at = markup.index('<footer class="status-bar">')
    actions_at = markup.index('id="compare-panel"')
    assert main_at < table_at < select_all_at < footer_at < actions_at
    assert 'aria-label="Select all visible runs"' in markup
    assert 'class="row-checkbox"' in source
    assert "samplesOpen ? 'Select all passes for' : 'Select run'" in source
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
    assert (
        "`${selectedExecutionCount} execution${selectedExecutionCount === 1 ? '' : 's'} selected`"
        in panel
    )
    assert "panel.style.display = showActions ? 'inline-flex' : 'none';" in panel
    assert "panel.closest('.status-bar')?.classList.toggle('selection-active', showActions)" in panel
    assert "separator.style.display = showActions ? '' : 'none';" in panel
    assert "allDeletable" in panel
    assert "isOwner && (status === 'COMPLETED'" in panel
    assert "const selectionAvailable = !!state.runs && (usesDashboardSummary() ? state.dashboardOverview.total_count > 0 : state.flatRuns.length > 0);" in source
    assert "selectMode: false" in source
    assert "function setSelectMode(enabled)" in source
    assert "tableView.classList.toggle('select-mode', state.selectMode);" in source
    assert "selectModeBtn.textContent = state.selectMode ? 'Done' : 'Select';" in source
    assert "el('select-mode-btn')?.addEventListener('click', () => setSelectMode(!state.selectMode));" in source
    select_mode = source.split("function setSelectMode(enabled)", 1)[1].split(
        "function toggleModelFilter", 1
    )[0]
    assert "state.selectedRuns.clear();" in select_mode
    assert "state.cohortAnchorRuns = null;" in select_mode
    assert "const isSelectionControl = !!e.target.closest('#compare-panel, .run-select-control');" in source
    assert "document.activeElement?.closest?.('#compare-panel, .run-select-control')" in source
    assert "if (restoreTableFocus) el('select-all')?.focus" in source
    assert "selectAllCheckbox.disabled = visibleFilePaths.length === 0;" in source
    assert ".status-bar.selection-active {" in styles
    assert "overflow-x: auto;" in styles
    hidden_control_rule = _rule(
        styles, ".table-container:not(.select-mode) .run-select-control {"
    )
    assert "display: none;" in hidden_control_rule
    assert "RUNS_TABLE_BASE_COLUMN_COUNT = 11" in source
    assert '<th class="col-select">' not in markup
    assert '<td class="col-select"' not in source
    assert "--runs-col-select-offset" not in styles
    assert "--runs-col-select-width" not in styles
    assert ".runs-table tbody tr:hover > .col-select .custom-checkbox" not in styles
    assert ".runs-selection-toolbar {" not in styles
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
    assert "(?:auth|shell|playground|run_details)\\.js" in source
    assert "html.replace(match[0], () => '<style>" in source
    assert "html.replace(match[0], () => '<script>" in source
    assert "html = await inlineCompareExportAssets(html);" in source
    assert "if (!IS_COMPARE_EXPORT && typeof QymPlayground !== 'undefined')" in source


def test_compare_uses_shared_composable_item_filter_builder() -> None:
    source = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    components = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")

    assert 'class="item-filter-builder qym-item-builder" id="item-filter-builder"' in source
    assert 'id="builder-rule-count"' in source
    assert 'id="filter-builder-body"' in source
    assert "filterRoot: { op: 'and', children: [] }" in source
    assert "function compareFilterFieldDefs()" in source
    assert "function compareFilterGroupHtml(node, path = '', depth = 0)" in source
    assert "if (!evalFilterNode(state.filterRoot, filterContext)) continue;" in source
    for field in ("outcome", "winner", "pass_count", "approval", "error", "edited", "output", "latency"):
        assert f"id: '{field}'" in source

    # Legacy selects remain hidden only as compatibility state for existing
    # chart interactions; the opened surface is the shared rule builder.
    assert 'id="compare-legacy-filter-inputs" hidden aria-hidden="true"' in source
    assert ".qym-item-builder .fb-token" in components
    assert ".qym-item-builder .fb-conj" in components
    assert ".fb-head {" not in run

    for markup in (run, source):
        assert 'class="fb-conj qym-segmented"' in markup
        assert 'class="qym-segmented__option' in markup
        assert 'class="fb-vchip qym-chip' in markup
        assert 'class="fb-rm qym-icon-action action-icon delete-run"' in markup
        assert 'const FILTER_TRASH_ICON = \'<svg class="qym-filter-trash-icon"' in markup
        assert 'title="Delete condition" aria-label="Delete condition"' in markup
        assert 'title="Delete group" aria-label="Delete group"' in markup
        assert 'fb-add qym-inline-action qym-inline-action--accent' in markup
        assert 'fb-add-muted qym-inline-action qym-inline-action--neutral' in markup
        assert 'data-fb-k="field" required' in markup
        assert "Choose field…" in markup
        assert "Choose state…" in markup

    run_builder = run.split("// ═══ Item filter rules ═══", 1)[1].split(
        "function getFilteredItems()", 1
    )[0]
    compare_builder = source.split(
        "// Compare uses the same composable filter builder as run detail", 1
    )[1].split("function getFilteredItems()", 1)[0]
    assert "return { field: '', oper: '', value: '' };" in run_builder
    assert "if (!_filterConditionComplete(node)) return true;" in run_builder
    assert "Choose outcome…" in run_builder
    assert "value: 'failed'" not in run_builder
    assert "value: [f.values[0]]" not in run_builder
    assert "if (!field) return { field: '', oper: '', value: '' };" in compare_builder
    assert "if (!compareFilterConditionComplete(node)) return true;" in compare_builder
    assert "value: [field.choices[0].value]" not in compare_builder

    connector = _rule(components, '.qym-item-filter[aria-expanded="true"]::after {')
    assert "top: calc(100% + 1px);" in connector
    assert "height: calc(var(--space-sm) + 1px);" in connector
    builder = _rule(components, ".qym-item-builder {")
    assert "margin-top: var(--space-sm);" in builder
    assert "border: 1px solid var(--border-default);" in builder
    assert "border-radius: var(--dropdown-radius);" in builder
    assert "background: color-mix(in srgb, var(--bg-elevated) 28%, var(--bg-base));" in builder
    filter_count = _rule(components, ".qym-item-filter-count {")
    assert "min-width: var(--space-md);" in filter_count
    assert "height: var(--space-md);" in filter_count
    nested_group = _rule(components, ".qym-item-builder .fb-grp .fb-grp {")
    assert "border-left:" not in nested_group
    assert "background: color-mix(in srgb, var(--bg-elevated) 28%, var(--bg-surface));" in nested_group
    token_controls = _rule(components, '.qym-item-builder .fb-token select,')
    assert "align-self: stretch;" in token_controls
    assert "min-height: var(--control-height);" in token_controls
    assert "height: auto;" in token_controls
    assert "font-size: var(--font-sm);" in token_controls
    token_dividers = _rule(
        components,
        '.qym-item-builder .fb-token > [data-fb-k="oper"],',
    )
    assert '[data-fb-k="value"]' in token_dividers
    assert "> .fb-vchips" in token_dividers
    assert "border-left: 1px solid var(--border-strong);" in token_dividers
    token_select = _rule(components, ".qym-item-builder .fb-token select {")
    assert "padding-right: calc(var(--space-lg) + var(--space-xs));" in token_select
    compact_operator = _rule(
        components,
        '.qym-item-builder .fb-token select[data-fb-k="oper"].fb-oper-compact {',
    )
    assert "width: calc(var(--space-xl) + var(--space-lg));" in compact_operator
    value_select = _rule(
        components, '.qym-item-builder .fb-token select[data-fb-k="value"] {'
    )
    assert "flex: 0 0 auto;" in value_select
    assert "var(--space-xl) + var(--space-xl) + var(--space-xl)" in value_select
    remove_rest = _rule(components, ".qym-item-builder .fb-rm {")
    assert "color: var(--error);" in remove_rest
    assert "opacity: 1;" in remove_rest
    assert "background: rgba(239, 68, 68, 0.1);" in remove_rest
    trash_icon = _rule(components, ".qym-item-builder .qym-filter-trash-icon {")
    assert "width: 14px;" in trash_icon
    assert "height: 14px;" in trash_icon
    assert "transform: translateY(-1px);" in trash_icon
    remove_action = _rule(components, ".qym-item-builder .fb-rm:is(:hover, :focus-visible) {")
    assert "background: rgba(239, 68, 68, 0.2);" in remove_action
    assert "color: var(--error);" in remove_action


def test_compare_cohort_metadata_breakdown_uses_user_defined_item_metadata() -> None:
    source = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")

    assert "const SWEEP_INTERNAL_METADATA_KEYS = new Set([" in source
    assert "'root_cause'," in source
    assert "'trace_stats'," in source
    assert "if (!isUserDefinedSweepMetadataKey(key)) return;" in source
    assert "const preferred = ['domain', 'complexity'];" in source
    assert "const preferred = ['domain', 'complexity', 'root_cause'];" not in source


def test_compare_output_height_alignment_uses_shared_responsive_scroll_cap() -> None:
    source = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
    components = (DASHBOARD_DIR / "ui_components.css").read_text(encoding="utf-8")

    assert ".item-run-output .output-text {\n      font-family: var(--font-mono);" in source
    assert ".item-run-output .output-text:has(.formatted-table-grid)" in source
    output_body = _rule(components, ".qym-output-card > .output-text {")
    assert "max-height: min(58vh, calc(var(--space-xl) * 18));" in output_body
    assert "window.getComputedStyle(el).maxHeight" in source
    assert "Number.isFinite(computedCap) ? computedCap : max" in source
    assert "el.style.minHeight = `${Math.min(max, cap)}px`;" in source
    assert "const cap = el.querySelector('.formatted-table-grid') ? 640 : 300;" not in source
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
    run_filter_panel = run.split(
        '<div class="filter-panel qym-item-control-center">', 1
    )[1].split('<div class="items-grid" id="items-grid">', 1)[0]
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
    compare_filter_panel = compare.split(
        '<div class="filter-panel qym-item-control-center">', 1
    )[1].split('<div class="items-grid" id="items-grid">', 1)[0]
    assert '<div class="pagination qym-pagination" id="pagination"' not in compare_filter_panel
    assert compare.index('id="items-grid"') < compare.index('id="pagination"')
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


def test_auto_analysis_is_a_first_class_project_page() -> None:
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    dashboard = DASHBOARD_JS.read_text(encoding="utf-8")
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
    assert "api/runs?limit=1&project_slug=" not in analyzer
    assert "Select a run to start analysis" in analyzer
    assert "Select a run from Runs" in analyzer
    assert "qym_analysis_run_picker" in analyzer
    assert "analysisRunsPickerUrl" in analyzer
    assert "consumeAnalysisRunPickerContext" in dashboard
    assert "analysisRunPickerContext && run" in dashboard
    assert "openUrl(analyzerUrlForRun(run), e);" in dashboard
    assert "Production rules and Documents remain available" in analyzer
    assert "if (!runId) {" in analyzer
    assert "getRunId: () => state.contextRunId" in analyzer
    assert "requestedPass" in analyzer
    assert "Choose a sample to analyze" in analyzer
    assert "id=\"analysis-pass-picker-select\"" in analyzer
    assert "id=\"analysis-pass-select\"" in analyzer
    assert "getPassNumber" in analyzer
    assert 'id="analyzer-host"' in analyzer
    assert "container: document.getElementById('analyzer-host')" in analyzer
    assert 'id="pg-project-description"' not in playground
    assert 'class="pg-context-panel"' in playground
    assert 'id="pg-rule-list"' in playground
    assert 'pg-rule-metadata' in playground
    assert 'Inferred from' in playground
    assert 'Why this rule helps the analyzer' in playground
    assert "function _analysisRuleForAnalyzer(rule)" in playground
    assert "not included in the analyzer prompt" in playground
    assert 'id="pg-rule-count"' in playground
    assert "function _formatRuleCount()" in playground
    assert "refreshRuleView" in playground
    assert "no rule count limit" in playground
    assert "_MAX_ANALYSIS_RULES" not in playground
    assert "_analysisRules.push({ title: '', instruction: '' });" in playground
    assert 'id="pg-infer-rules"' in playground
    assert 'id="pg-update-rules"' not in playground
    assert 'id="pg-save-context"' not in playground
    assert 'id="pg-infer-use-description"' not in playground
    assert 'id="pg-infer-use-documents"' in playground
    assert 'id="pg-infer-use-examples"' not in playground
    assert 'id="pg-add-examples"' in playground
    assert 'Add documents' in playground
    assert 'Add examples' in playground
    assert 'previous_ai_category_taxonomy' not in playground
    assert 'approved_category_taxonomy' not in playground
    assert 'data-example-prompt-field' in playground
    assert 'data-example-fields-toggle' in playground
    assert 'filtersOpen: false' in playground
    assert "!event.target.closest('.pg-example-picker-fields')" in playground
    assert 'Choose prompt fields' in playground
    assert 'function _fieldToggleMarkup' in playground
    assert 'include_fields: _approvedExampleFieldMap()' in playground
    assert "include_project_description" not in playground
    assert "include_documents: inferenceSources.include_documents" in playground
    assert "include_examples: inferenceSources.include_examples" in playground
    assert "mode: mode" in playground
    assert 'id="pg-rule-version-list"' in playground
    assert 'id="pg-create-rule-version"' in playground
    assert 'pg-rule-compare-stats' in playground
    assert 'pg-rule-compare-group' in playground
    assert 'pg-rule-compare-picker' in playground
    assert 'class="pg-rule-source-actions"' in playground
    assert '<details class="pg-rule-inference-options">' not in playground
    assert 'pg-rule-inference-content' not in playground
    assert 'pg-infer-source-summary' not in playground
    assert 'pg-infer-example-selection-summary' not in playground
    assert 'pg-infer-example-budget' not in playground
    assert 'Rules cannot be generated yet' in playground
    assert 'This project has neither an' in playground
    assert 'enabled project document nor an approved ' in playground
    assert 'pg-infer-source-empty' in playground
    assert 'function _inferenceSourceState()' in playground
    assert "function _syncInferenceSourceSummary()" in playground
    assert "function _syncInferenceSourceAvailability()" in playground
    assert "NO_INFERENCE_SOURCES" in analysis_api
    assert 'pg-context-action-group' in playground
    assert 'pg-context-action-divider' in playground
    assert 'pg-context-feedback' in playground
    assert "function _renderRuleViewStatus()" in playground
    assert "function _showContextFeedback(message, isError)" in playground
    assert '3500' in playground
    assert "Create a draft before editing these rules." in playground
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
    assert "<select data-rule-' + key" in playground
    assert "QymUIComponents.enhanceSelect(select" in playground
    assert "className: 'pg-rule-version-review-selector'" in playground
    assert "search: true" in playground
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
    assert 'data-download-rule-version' in playground
    assert 'function _downloadRuleVersion(versionId)' in playground
    assert 'data-rule-drag-handle' not in playground
    assert 'pg-rule-filters' in playground
    assert 'pg-rule-category' not in playground
    assert 'pg-rule-category-filter' not in playground
    assert 'data-rule-menu-toggle' not in playground
    assert 'data-duplicate-rule' not in playground
    assert 'data-edit-rule' not in playground
    assert 'pg-rule-menu' not in playground
    assert 'pg-rule-remove' in playground
    assert 'data-delete-rule' in playground
    assert 'function _confirmAnalysisRuleDeletion(index)' in playground
    assert 'Delete this rule?' in playground
    assert "This can\\'t be undone." in playground
    assert "_icon('merge')" in playground
    assert "M6 4v4c0 4 2 6 6 6h6" in playground
    assert "candidate.is_active;" in playground
    assert "rule_version_id: _selectedRuleVersionId" in playground
    assert "data-activate-rule-version" in playground
    assert "data-publish-rule-version" in playground
    assert "data-compare-rule-version" in playground
    assert "data-delete-rule-version" in playground
    assert "_confirmRuleVersionDeletion" in playground
    delete_version_confirmation = playground.split(
        "function _confirmRuleVersionDeletion", 1
    )[1].split("function _confirmAnalysisRuleDeletion", 1)[0]
    assert "mount: document.body" in delete_version_confirmation
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
    assert 'analysis-rules-workspace-tabs' not in analyzer
    assert 'data-rules-workspace-tab="rules"' not in analyzer
    assert 'data-rules-workspace-tab="history"' not in analyzer
    assert "setRulesWorkspaceView('rules')" not in analyzer
    assert 'analysis-version-history-button' in analyzer
    assert 'openVersionHistory' in analyzer
    assert 'renderRuleGraph' in analyzer
    assert 'analysis-rule-graph' in analyzer
    assert "rulesHelp" not in analyzer
    assert "How version actions work" not in analyzer
    assert 'analysis-info-popover' not in analyzer
    assert "viewState.className = 'qym-badge qym-badge--neutral'" in analyzer
    assert 'analysis-rule-version-meta' in analyzer
    assert 'analysis-version-heading-description' in analyzer
    assert '--analysis-history-graph-rail: clamp(calc(var(--space-xl) * 4), 30%, calc(var(--space-xl) * 8));' in analyzer
    assert "row.classList.contains('pg-rule-version-selected')" in analyzer
    assert "halo.setAttribute('stroke', 'var(--accent-primary)')" in analyzer
    assert "_renderRuleVersionMeta(selected)" in playground
    assert "label: 'Created at'" in playground
    assert "label: 'Updated at'" in playground
    assert "version.created_by.display_name" in playground
    assert '-webkit-line-clamp: 2' in analyzer
    assert "window.confirm(" not in playground
    assert "window.prompt(" not in playground
    assert "window.alert(" not in playground
    assert "Promote" in playground
    assert "_openRuleVersion(versionRow.dataset.ruleVersionId)" in playground
    assert "data-toggle-rule" in playground
    assert "_editingRuleIndex === toggleIndex ? null : toggleIndex" in playground
    assert "function _readAnalysisRuleDraftsFromEditor()" in playground
    assert "_analysisRules = _readAnalysisRuleDraftsFromEditor();" in playground
    assert "function _validateAnalysisRuleDrafts()" in playground
    assert "Complete the title and instruction for every rule before changes can be saved." in playground
    assert "Removing rule from the current version" in playground
    assert "_saveAnalysisContext().catch(function () {" in playground
    assert "cfg.project_description" not in playground
    assert "cfg.analysis_rules = rules" in playground
    assert "cfg.analysis_rules = rules.map(_analysisRuleForAnalyzer)" in playground
    assert 'id="pg-document-input"' in playground
    assert "cfg.include_project_documents = documentsToggle.checked" in playground
    assert "analysis-documents" in playground
    assert "Project documents" in playground
    assert "_updateReferenceDocumentSelection" in playground
    assert 'class="pg-document-select"' in playground
    assert "_deleteReferenceDocument" in playground
    assert "function _confirmReferenceDocumentDeletion(referenceDocument)" in playground
    assert "Keep document" in playground
    assert "confirmLabel: 'Delete document'" in playground
    assert "confirmClass: 'shell-btn-danger'" in playground
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
    assert '@router.get("/api/projects/{project_slug}/analysis-config")' in analysis_api
    assert '@router.get("/api/projects/{project_slug}/analysis-documents")' in analysis_api
    assert '@router.patch("/api/projects/{project_slug}/analysis-context")' in analysis_api
    assert '@router.post("/api/projects/{project_slug}/analysis-rules/infer")' in analysis_api
    assert 'projectScoped: !!projectScoped' in analyzer
    assert 'await initializePlayground(true)' in analyzer
    assert 'id="analysis-error-retry"' in analyzer
    assert 'role="alert"' in analyzer
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
    assert 'data-metric-issues-item=' in run
    assert 'data-issue-field="category"' in run
    assert 'data-issue-field="subcategory"' in run
    assert 'data-issue-field="finding"' in run
    assert 'data-metric-sol-item=' in run
    assert 'AI analysis did not produce a usable diagnosis.' in run
    assert 'role="alert"' in run
    assert 'Could not save diagnosis' in run
    assert 'if (rootCauseCategories(analysis).length) delete analysis.error;' in run
    assert "saveMetricAnalysisPatch" in run
    assert "metric_name: metricName" in run
    assert "if (!hasStoredAnalysis && !metricFailed) return '';" in run
    assert "const hasCategories = analysisCategories.length > 0;" in run
    assert "renderMetricRootCauseIssues(analysis)" in run
    assert "'>Edit</button>'" not in run
    assert 'id="analysis-metric-list"' in analyzer
    assert "getMetrics: projectScoped ? () => [] : () => state.selectedMetrics.slice()" in analyzer
    assert "body.metrics = _getSelectedMetrics()" in playground
    assert "body.pass_number = Number(passNumber)" in playground
    assert "pass_number: _opts.getPassNumber ? _opts.getPassNumber() : null" in playground
    assert "var _selectedTarget = null;" in playground
    assert 'data-metric-name="' in playground
    assert "var targetMetricNames = failedMetricNames.length ? failedMetricNames : [_getPrimaryMetric(r) || 'metric'];" in playground
    assert 'class="pg-item-target-row' in playground
    assert 'pg-item-target-status qym-badge' in playground
    assert "metricNames.indexOf(target.metric_name) !== -1" in playground
    assert "failedMetricNames.length > 1" not in playground
    assert "function _resolveSelectedTarget(matchedItems)" in playground
    assert "_selectTarget(card.dataset.itemId, card.dataset.metricName || null)" in playground
    assert "metric: metricName || null" in playground
    assert "metric: testTarget.metric_name || null" in playground
    assert "item_ids: [testItemId], metric: _opts.getMetric ? _opts.getMetric() : null" not in playground
    assert "function _isHumanMetricAnalysis(md, metricName)" in playground
    assert "function _getHumanOverwriteTargets(matchedItems)" in playground
    assert "function _confirmHumanOverwrite(targets)" in playground
    assert "Keep human labels" in playground
    assert "if (_opts.dedicatedPage) return;" in playground
    assert "e.target.closest('[role=\"dialog\"][aria-modal=\"true\"]')" in playground
    assert "event.stopPropagation();" in playground
    assert "let inputMappingOpener = null;" in analyzer
    assert "let inputMappingEscapeHandler = null;" in analyzer
    assert "document.removeEventListener('keydown', inputMappingEscapeHandler)" in analyzer
    assert "if (opener && document.contains(opener)) opener.focus();" in analyzer
    assert "getMetric: function () { return null; }" in compare
    assert "row.item_metadata.metric_analyses[result.metric_name]" in compare
    assert "def _is_human_metric_analysis(" in analysis_api
    assert "allow_human_overwrite: bool = False" in analysis_api
    assert "allow_human_overwrite=request.allow_human_overwrite" in analysis_api
    assert '"type": "aggregating"' in analysis_api
    assert "state.phase === 'aggregating'" in playground
    assert "Aggregating root causes…" in playground
    assert "function _analysisCategoryCount(data)" in playground
    assert "Created <strong>" in playground
    assert "var categoryLabel = categoryCount === 1 ? 'category' : 'categories';" in playground
    assert "const categoryLabel = categoryCount === 1 ? 'category' : 'categories';" in analyzer
    assert "getRunUrl" in analyzer
    assert "pg-runall-open-run" in playground
    assert 'class="qym-inline-action qym-inline-action--neutral pg-runall-open-run"' in playground
    assert ">View run</a>" in playground
    assert 'class="qym-icon-action analysis-context-link pg-runall-open-run"' not in playground
    assert "labels consolidated" not in playground
    assert "if (_opts.onAnalysisComplete) _opts.onAnalysisComplete(data);" in playground
    assert "_onFilterChange();" in playground
    assert 'id="pg-target-limit"' in playground
    assert 'class="pg-target-limit-control"' in playground
    assert 'data-target-limit-step="increase"' in playground
    assert 'data-target-limit-step="decrease"' in playground
    assert "_icon('chevronUp')" in playground
    assert "_icon('chevronDown')" in playground
    assert "targetLimit.dispatchEvent(new Event('input'" in playground
    assert 'maxlength="4"' in playground
    assert 'placeholder="All"' in playground
    assert "Empty = all" not in playground
    assert "pg-target-limit-help" not in playground
    assert "slice(0, 4)" in playground
    assert ".analysis-page .pg-score-slider::-webkit-slider-runnable-track" in analyzer
    assert "grid-template-columns: 260px max-content max-content;" in analyzer
    assert "width: 96px;" in analyzer
    assert 'id="pg-connection" class="pg-connection-select"' in playground
    assert "className: 'pg-connection-selector'" in playground
    assert "body.limit = requestedLimit" in playground
    assert "var requestedLimit = _getTargetLimit();" in playground
    assert "analysisItemCount = requestedLimit == null ? itemCount : Math.min(requestedLimit, itemCount)" in playground
    assert "'pg-use-project-description'" not in analyzer
    assert "'pg-use-project-rules'" in analyzer
    assert "'pg-use-project-documents'" in analyzer
    assert "'pg-use-trace'" in analyzer
    assert "['pg-use-project-rules', 'pg-use-project-documents', 'pg-use-trace']" in playground
    assert "fields.trace = traceToggle.checked" in playground
    assert 'id="analysis-mapping-open"' in analyzer
    assert ">Input mapping</button>" in analyzer
    assert "Advanced run configuration" not in analyzer
    assert "state.wizardStep" not in analyzer


def test_repeat_pass_analysis_links_select_that_sample() -> None:
    dashboard = DASHBOARD_JS.read_text(encoding="utf-8")

    # The aggregate run intentionally omits pass= so the analyzer can ask the
    # user which sample to inspect. Expanded pass rows carry their own pass
    # query and therefore open directly in that sample's analyzer context.
    assert "function analyzerUrlForRun(run, passNumber = null)" in dashboard
    assert "const passQuery = Number.isInteger(parsedPass)" in dashboard
    assert "analysis?run=${encodeURIComponent(runId)}${passQuery}" in dashboard
    assert "renderAnalysisCell(parentRun, runStatus, firstPass, pass.analysis_cause_count)" in dashboard
    assert "const analysisLink = event.target.closest?.('.run-analysis-chip, .run-analysis-start')" in dashboard
    assert "if (analysisLink)" in dashboard
    assert "navigateTo(analysisLink.href)" in dashboard


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


def test_rule_generation_progress_card_shows_shared_bar_and_patch_count() -> None:
    analyzer = (DASHBOARD_DIR / "analyzer.html").read_text(encoding="utf-8")
    playground = (DASHBOARD_DIR / "playground.js").read_text(encoding="utf-8")

    assert "analysis-rule-inference-card" in analyzer
    assert "analysis-rule-inference-patch-count" in analyzer
    assert "inferenceProgressBody.append(inferenceProgressHost)" in analyzer
    assert "pg-runall-progress" in playground
    assert "function _setRuleInferencePatchCount(completed, total)" in playground
    assert "_setRuleInferencePatchCount(completed, total)" in playground


def test_rule_version_history_fills_drawer_and_starts_at_bottom() -> None:
    analyzer = (DASHBOARD_DIR / "analyzer.html").read_text(encoding="utf-8")

    popup_styles = analyzer.split(".analysis-version-history-popup-content {", 1)[1].split(
        "}", 1
    )[0]
    list_styles = analyzer.split(
        ".analysis-version-history-popup-content .pg-rule-version-list {", 1
    )[1].split("}", 1)[0]
    assert "flex: 1 1 auto;" in popup_styles
    assert "overflow: hidden;" in popup_styles
    assert "flex: 1 1 auto;" in list_styles
    assert "justify-content: flex-end;" in list_styles
    assert "list.scrollTop = list.scrollHeight;" in analyzer


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
    assert ">Apply</button>" not in analyzer
    assert 'class="analysis-run-context" aria-label="Run information"' in analyzer
    assert 'analysis-run-context-label">Run ID' not in analyzer
    assert "Production rules" in analyzer
    assert ">Documents</button>" in analyzer
    assert 'id="analysis-preview-settings-toggle"' in analyzer
    assert "contextSettings.append(createContextToggles())" in analyzer
    assert "runPanel.append(contextCard)" not in analyzer
    assert "Use project context" not in analyzer
    assert 'role="tablist"' in analyzer
    assert 'id="analysis-rules-tab"' in analyzer
    assert 'id="analysis-documents-tab"' in analyzer
    assert 'id="analysis-dashboard-tab"' in analyzer
    assert 'data-analysis-view="dashboard"' in analyzer
    assert 'id="analysis-dashboard-view"' in analyzer
    assert 'hidden aria-hidden="true">Dashboard</button>' in analyzer
    assert 'data-dashboard-disabled="true"' in analyzer
    assert 'src="/static/qym_table.js"' in analyzer
    assert "root-cause-dashboard" in analyzer
    assert "state.dashboard" in analyzer
    assert "function dashboardQuery" in analyzer
    assert "const AUTO_ANALYSIS_DASHBOARD_ENABLED = false;" in analyzer
    assert "if (!AUTO_ANALYSIS_DASHBOARD_ENABLED) return;" in analyzer
    assert 'id="analysis-run-tab"' in analyzer
    assert 'id="analysis-diagnosis-tab"' in analyzer
    assert 'aria-controls="analysis-diagnosis-view"' in analyzer
    assert 'data-analysis-view="categories"' in analyzer
    assert 'aria-disabled="true" disabled' not in analyzer
    assert "setAnalyzerView(state.currentView" in analyzer
    assert "landing.hidden = nextView !== 'run' || Boolean(runId);" in analyzer
    assert "nextParams.set('scope', nextView)" in analyzer
    assert "Project documents" in analyzer
    assert 'data-context-view="\' + item[3] + \'"' in analyzer
    assert "analysisViewUrl(item[3])" in analyzer
    assert "setAnalyzerView(link.dataset.contextView, { focus: true })" in analyzer
    assert "composePage: composeAnalyzerWorkspace" in analyzer
    assert "function composeAnalyzerWorkspace(parts)" in analyzer
    assert "organizeAnalyzerWorkspace" not in analyzer
    assert "organizeWhenReady" not in analyzer
    assert "playground-page-root" in playground
    assert "playground-page-content" in playground
    assert "window.QymPlayground.refreshRuleView()" in analyzer
    assert analyzer.index("window.QymPlayground.refreshRuleView()") < analyzer.index("        if (!runId) {")
    assert "new MutationObserver" in analyzer
    assert "['overview', 'Overview']" not in analyzer
    assert "documentsPanel.append" in analyzer
    assert "Advanced run configuration" not in analyzer
    assert "buildInputMappingDialog(mapping)" in analyzer
    assert "buildAdvancedDialog" not in analyzer
    assert "diagnosisTab.disabled = false" in analyzer
    assert "diagnosisBody.append(diagnosisToolbar)" in analyzer
    assert "diagnosisPanel.append(diagnosisBody)" in analyzer
    assert "analysis-diagnosis-main-toolbar" in analyzer
    assert "<h2>Diagnosis categories</h2>" not in analyzer
    assert "border-bottom: 1px solid var(--border-strong);" not in analyzer
    assert "diagnosisCard" not in analyzer
    assert 'id="analysis-category-count"' in analyzer
    assert 'id="analysis-example-count"' in analyzer
    assert "data-example-count" in playground
    assert 'data-approved="' in playground
    assert "function _approvedCategoryGroups()" in playground
    assert "group.dataset.approved === 'true'" in playground
    assert "No approved categories yet." in playground
    assert "category_examples" in playground
    assert "Approved examples" in playground
    assert "No approved examples in this category yet." in playground
    assert "Remove category from this analysis" in playground
    assert "pg-category-example-data" in playground
    assert 'data-taxonomy-field="description"' in playground
    assert 'data-taxonomy-field="when_to_use"' in playground
    assert 'data-subcategory-taxonomy-field="description"' in playground
    assert 'data-subcategory-taxonomy-field="when_to_use"' in playground
    assert "cfg.category_taxonomy = taxonomyMap" in playground
    assert "cfg.subcategory_taxonomy = subcategoryTaxonomyMap" in playground
    assert "function _categoryTaxonomyFor" in playground
    assert "function _subcategoryTaxonomyFor" in playground
    assert ".pg-category-taxonomy" in styles
    assert "instructionsBody.append(instructions)" in analyzer
    assert analyzer.index("runPanel.append(instructionsCard)") < analyzer.index("runPanel.append(targetCard)")
    assert "max-height: 420px" not in analyzer
    assert "max-height: 520px" in analyzer
    assert "max-height: 640px" not in analyzer
    assert "_RULES_PAGE_SIZE = 10" in playground
    assert "_PAGE_SIZE = 10" in playground
    assert 'id="pg-rule-pagination"' in playground
    assert 'id="pg-target-pagination"' in playground
    assert "Analysis target pagination" in playground
    assert "pg-target-limit-row" in playground
    assert "data-qym-page" in playground
    assert "analysis-rule-toolbar-actions" in analyzer
    assert "toolbarActions.append(ruleVersionActions)" in analyzer
    assert "rulePaginationFooter.append(rulePagination)" in analyzer
    assert "ruleColumn.append(rulePagination)" not in analyzer
    assert "analysis-rule-pagination-footer" in analyzer
    assert "id=\"pg-rule-version-actions\"" in playground
    assert "function _renderRuleVersionActions()" in playground
    assert "id=\"pg-publish-rule-version\"" in playground
    assert "id=\"pg-promote-rule-version\"" in playground
    assert "pg-example-source-control" in playground
    assert 'class="pg-example-source-control"' in playground
    assert "qym-inline-action pg-example-source-control" not in playground
    assert ">Add examples</button>" in playground
    example_source_control = _rule(styles, ".pg-example-source-control {")
    assert "padding: 0;" in example_source_control
    assert "border: 0;" in example_source_control
    assert "border-radius: 0;" in example_source_control
    assert "background: transparent;" in example_source_control
    assert "qym-help-marker pg-example-source-help" not in playground
    assert "data-example-filter-select" in playground
    assert "enhanceSelects(dialog, 'select[data-example-filter-select]'" in playground
    assert "Each selector accepts one value." in playground
    assert "Multi-select supported" not in playground
    assert "data-example-filter-action" not in playground
    assert "data-example-filter-only" not in playground
    assert "pg-example-picker-scroll" in playground
    example_picker_scroll = _rule(styles, ".pg-example-picker-scroll {")
    assert "flex: 1 1 auto;" in example_picker_scroll
    assert "overflow: auto;" in example_picker_scroll
    assert "grid-template-columns: minmax(0, 1fr) auto;" in analyzer
    assert "analysis-diagnosis-action-row" in analyzer
    assert 'id="analysis-category-search"' in analyzer
    assert 'placeholder="Search categories"' in analyzer
    assert ">Save changes</button>" in analyzer
    assert "analysis-diagnosis-summary-line" in analyzer
    assert "pg-category-workspace" in playground
    assert "pg-category-sidebar" in playground
    assert 'id="pg-category-nav"' in playground
    assert 'id="pg-category-sidebar-title">Categories</h3>' in playground
    assert 'id="pg-category-more"' not in playground
    assert "_CATEGORY_NAV_VISIBLE_LIMIT" not in playground
    assert "filterCategories" in playground
    assert 'id="pg-category-settings-trigger"' not in playground
    assert 'pg-category-settings-popover' not in playground
    assert 'id="pg-max-root-cause-categories"' in playground
    assert 'data-category-limit-field' in playground
    assert 'class="qym-help-marker"' in playground
    assert 'class="qym-help-tooltip" role="tooltip"' in playground
    assert "Limits how many root-cause issues the analyzer can return" in playground
    assert 'min="1"' in playground
    assert 'inputmode="numeric"' in playground
    assert "function _normalizeCategoryLimitInput" in playground
    assert "var _DEFAULT_MAX_ROOT_CAUSE_CATEGORIES = 3;" in playground
    assert "if (value == null) value = _DEFAULT_MAX_ROOT_CAUSE_CATEGORIES;" in playground
    assert "var categoryLimit = _categoryLimitInputValue(maxCategoriesEl);" in playground
    assert "if (categoryLimit != null) cfg.max_root_cause_categories = categoryLimit;" in playground
    assert "maxCategoriesInput.addEventListener('blur', function ()" in playground
    assert "maxCategoriesInput.addEventListener('change', function ()" not in playground
    assert "MAXIMUM ROOT-CAUSE CATEGORIES" in playground
    assert 'pg-hl-category">$1$2</span>' in playground
    assert "diagnosisPanel.querySelector('#pg-max-root-cause-categories')" not in analyzer
    assert "diagnosisBody.querySelector('[data-category-limit-field]')" in analyzer
    assert "categoryLimitField?.querySelector('#pg-max-root-cause-categories')" not in analyzer
    assert "projectMaxCategories" in analyzer
    assert "placeCategoryLimitField" not in analyzer
    assert "analysis-diagnosis-category-limit" not in analyzer
    assert "diagnosisActionRow.insertBefore(categoryLimitField, categorySaveAction)" not in analyzer
    assert "targetLimitRow.append(categoryLimitField)" not in analyzer
    assert "targetToolActions.insertBefore(categoryLimitField, mappingButton)" in analyzer
    assert "analysis-run-category-limit" in analyzer
    assert "Unsaved changes" in analyzer
    assert "analysis-target-pagination" in analyzer
    assert "targetPaginationFooter.append(targetPagination)" in analyzer
    assert "categorySettings.classList.add('analysis-diagnosis-toolbar-settings')" not in analyzer
    assert "color: var(--accent-primary);" in analyzer
    assert "height: calc(100vh - (var(--space-xl) * 5));" in analyzer
    assert "border: 1px solid var(--border-default);" in analyzer
    assert "background: var(--bg-surface);" in analyzer
    assert "flex: 1 1 auto;" in analyzer
    assert "overflow-y: auto;" in analyzer
    assert "border-left: 1px solid var(--border-subtle);" in analyzer
    assert "pg-category-status-dot" in playground
    assert "pg-category-editor-toolbar" in playground
    assert "pg-category-tabs-row" in playground
    assert "qym-icon-action--danger" in playground
    assert "_icon('trash')" in playground
    assert "function _confirmCategoryRemoval" in playground
    assert "Keep category" in playground
    assert "confirmLabel: 'Remove category'" in playground
    assert "pg-category-tabs qym-tabs" in playground
    assert 'role="tab"' in playground
    assert "data-detail-search" in playground
    assert "data-detail-filter" in playground
    assert "pg-detail-example-count" in playground
    assert "function _selectCategory" in playground
    assert "function _filterCategoryDetails" in playground
    assert "_CATEGORY_PAGE_SIZE = 10" in playground
    assert 'data-category-pagination="details"' in playground
    assert 'data-category-pagination="examples"' in playground
    assert "function _filterCategoryExamples" in playground
    assert "function _renderCategoryPagination" in playground
    assert "pageSize: _CATEGORY_PAGE_SIZE" in playground
    assert "variant: 'run'" not in playground
    assert "onPageChange: function (nextPage)" in playground
    assert ".pg-rule-version-lifecycle" not in styles
    assert "qym-icon-action pg-rule-version-menu-toggle" in playground
    assert "pg-rule-version-menu-open" in playground
    assert ".pg-rule-version-menu" in styles
    assert ".analysis-version-history-popup-content .pg-rule-version-menu-open" in analyzer
    assert ".analysis-version-history-popup-content .pg-rule-version-copy" in analyzer
    assert "min-height: calc(var(--space-xl) + var(--space-md));" in analyzer
    assert ".pg-target-limit-control" in styles
    assert "min-height: 36px;" in styles
    footer_style = analyzer.split(".analysis-project-footer {", 1)[1].split("}", 1)[0]
    assert "position: fixed" not in footer_style
    assert "border-top: 1px solid var(--border-subtle);" in footer_style
    assert ".analysis-page .playground-page-root" in analyzer
    assert "projectPanel.append(rulesPanel, documentsPanel)" in analyzer
    assert "Generate diagnostic rules" not in analyzer
    assert "rulesSourceCard" not in analyzer
    assert "manualActionGroup.insertBefore(inference" in analyzer
    assert "rulesWorkspaceCard.append(projectFooter)" in analyzer
    assert "documentsPanel.append(uploadCard, libraryCard)" in analyzer
    assert "runPanel.append(targetCard)" in analyzer
    assert "newRuleTitle.scrollIntoView" in playground
    assert 'class="pg-hl-category" style="color:' not in playground
    assert "pg-hl-rule-title" in playground
    assert "EVALUATION ITEM DATA:|SUPPLIED ANALYSIS DATA" in playground
    assert ".pg-hl-rule-title { color: var(--accent-secondary);" in styles
    assert ".pg-hl-json-key { color: var(--accent-secondary);" in styles

    # The shared Compare modal keeps its controller markup; Auto-analysis uses
    # the explicit dedicated-page renderer and composition callback.
    assert "analysis-scope-card" not in playground
    assert "analysis-document-scope-note" not in playground


def test_root_cause_breakdowns_support_metric_scoping() -> None:
    for page_name in ("run.html", "compare.html"):
        source = (DASHBOARD_DIR / page_name).read_text(encoding="utf-8")

        assert "rootCauseMetric: 'all'" in source
        assert 'id="root-cause-metric-select"' in source
        assert ">All</option>" in source
        assert "getRowRootCauseAnalyses(row, state.rootCauseMetric)" in source
        assert "rootCauseIssues(analysis)" in source
        assert "issue.subcategory" in source
        assert "renderSankeyDiagram" in source


def test_root_cause_issue_records_are_rendered_edited_and_exported() -> None:
    playground = (DASHBOARD_DIR / "playground.js").read_text(encoding="utf-8")
    reviews = (DASHBOARD_DIR / "reviews.html").read_text(encoding="utf-8")
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    compare = (DASHBOARD_DIR / "compare.html").read_text(encoding="utf-8")
    endpoints = (DASHBOARD_DIR / "docs/developer/endpoints.html").read_text(
        encoding="utf-8"
    )

    assert "function _rootCauseIssues" in playground
    assert 'class="pg-result-issues"' in playground
    assert "if (Array.isArray(value.root_cause_issues))" in playground
    assert "var hasCanonicalIssues = Array.isArray(r.root_cause_issues)" in playground
    assert "return (legacyCategories.length ? legacyCategories : ['']).map" in playground
    assert "subcategory: legacySubcategory" in playground
    assert "finding: legacyFinding" in playground
    assert "var useLegacyResultLayout = !hasCanonicalIssues && !issues.length" in playground
    assert "function reviewRootCauseIssues" in reviews
    assert "data-review-issue-edit" in reviews
    assert "human_root_cause_issues: issues" in reviews
    assert "function rootCauseIssuePatch" in run
    assert 'data-metric-issues-item=' in run
    assert ":root_cause_issues" in run
    assert "function rootCauseIssuePatch" in compare
    assert 'data-rc-issues-item=' in compare
    assert "root_cause_issues', label: 'Root cause issues (JSON)'" in compare
    assert "canonical <code>root_cause_issues</code> records" in endpoints

    active_compare_output = compare.split("function renderCompareOutputGroup", 1)[
        1
    ].split("function renderItemComparisonCard", 1)[0]
    assert "const rootCauseBlockFor = (row, runIdx)" in active_compare_output
    assert "${rootCauseBlockFor(row, runIdx)}" in active_compare_output
    assert 'data-rc-issues-item="${escapeAttr(itemId)}"' in active_compare_output


def test_run_manual_diagnosis_uses_project_backed_modal_picker() -> None:
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    analyzer = ANALYZER_HTML.read_text(encoding="utf-8")

    assert "analysis-category-catalog" in run
    assert "loadProjectCategoryCatalog" in run
    assert "addProjectDiagnosisCategory" in run
    assert "data-picker-taxonomy=\"description\"" in run
    assert "data-picker-taxonomy=\"when_to_use\"" in run
    assert "category_taxonomy: nextTaxonomy" in run
    assert "Human selections are not limited" in run
    assert "Select up to " not in run
    assert ".slice(0, categoryLimit)" not in run
    assert "showRootCauseCategoryPicker" in run
    assert "showRootCauseDropdown" not in run
    assert "Save categories" not in run
    assert "rdi-category-picker" in run
    assert "aria-selected" in run
    assert "selectedCategories.splice(index, 1)" in run
    assert "event.target === picker" in run
    assert 'class="rdi-category-picker__done qym-inline-action qym-inline-action--accent"' in run
    assert "rdi-category-picker__footer-actions" in run
    assert "'.rdi-category-picker__done').addEventListener('click', () => cleanup());" in run
    assert "silent: true" in run
    assert "rdi-analysis-warning" in run
    assert "row.item_metadata.analysis_warning" not in analyzer


def test_category_taxonomy_is_required_across_diagnosis_entry_points() -> None:
    playground = (DASHBOARD_DIR / "playground.js").read_text(encoding="utf-8")
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")
    analyzer = ANALYZER_HTML.read_text(encoding="utf-8")

    assert "Both fields are required." in playground
    assert "required aria-required=\"true\"" in playground
    assert "incompleteTaxonomyCategories" in analyzer
    assert "incompleteTaxonomySubcategories" in analyzer
    assert "subcategoryTaxonomyTouched" in analyzer
    assert "Taxonomy required" in analyzer
    assert "Required · saved to the project" in run
    assert "missingTaxonomyField" in run
    assert "Category guidance required" in run
    assert "reportValidity" not in run


def test_shell_and_run_detail_normalize_trailing_slashes_before_route_parsing() -> None:
    shell = (DASHBOARD_DIR / "shell.js").read_text(encoding="utf-8")
    run = (DASHBOARD_DIR / "run.html").read_text(encoding="utf-8")

    assert "if (typeof window.__QYM_ROOT_PATH__ === 'string')" in shell
    assert "return configuredRoot ? configuredRoot + '/' : '/';" in shell
    assert "const path = rawPath.length > 1 ? rawPath.replace(/\\/+$/, '') : rawPath;" in shell
    assert "const pathname = rawPathname.length > 1 ? rawPathname.replace(/\\/+$/, '') : rawPathname;" in shell
    assert "const path = rawPath.length > 1 ? rawPath.replace(/\\/+$/, '') : rawPath;" in run


def test_datasets_routes_honor_the_configured_root_path() -> None:
    datasets = (DASHBOARD_DIR / "datasets.html").read_text(encoding="utf-8")

    assert "function appRootPath(){" in datasets
    assert "window.__QYM_ROOT_PATH__.trim().replace(/\\/+$/, '')" in datasets
    assert "pathname.startsWith(root + '/')" in datasets
    assert "return pathname.slice(root.length) || '/';" in datasets
    assert "const rawPath = routePathname();" in datasets
    assert "let path = appPath('/projects/' + state.slug + '/datasets');" in datasets
    assert "href: '/projects/' + state.slug + '/datasets'" not in datasets
    assert "const datasetHref = '/projects/'" not in datasets


def test_runs_table_analysis_column_shows_state_or_static_action() -> None:
    """The ANALYSIS column carries state: analyzed runs show a root-cause
    count chip, eligible runs a static Analyze action, live runs a dash."""
    index = (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8")
    dashboard_js = (DASHBOARD_DIR / "dashboard.js").read_text(encoding="utf-8")
    styles = (DASHBOARD_DIR / "dashboard.css").read_text(encoding="utf-8")
    runs_api = RUNS_API.read_text(encoding="utf-8")

    # The column sits between DATASET and VERSION, early enough to see
    # without horizontal scrolling.
    assert '<th class="col-analysis">ANALYSIS</th>' in index
    assert index.index("col-analysis") > index.index("col-dataset")
    assert index.index("col-analysis") < index.index("col-version")
    assert "AUTO-ANALYSIS" not in index

    # Cell renderer: chip for analyzed, static action for eligible, dash for
    # live. The action mirrors the run-detail Auto-Analyze recipe at table
    # scale and carries the sparkle icon.
    assert "function renderAnalysisCell(run, status, passNumber = null, analysisCauseCount = null)" in dashboard_js
    assert "run.analysis_cause_count" in dashboard_js
    assert "analysisCauseCount = null" in dashboard_js
    assert "renderAnalysisCell(parentRun, runStatus, firstPass, pass.analysis_cause_count)" in dashboard_js
    assert 'class="run-analysis-chip"' in dashboard_js
    assert 'class="run-analysis-start"' in dashboard_js
    assert "ANALYSIS_SPARK_ICON" in dashboard_js
    assert "run-analysis-link" not in dashboard_js

    # Styling exists for both states; purple stays the AI accent.
    assert ".run-analysis-chip" in styles
    assert ".run-analysis-start" in styles

    # The runs list API exposes the distinct root-cause count per run.
    assert '"analysis_cause_count"' in runs_api
    assert "metric_analyses" in runs_api


def test_runs_table_sticky_columns_size_to_visible_values() -> None:
    """Sticky value columns measure the current page without wrapping values."""
    dashboard_js = (DASHBOARD_DIR / "dashboard.js").read_text(encoding="utf-8")
    styles = (DASHBOARD_DIR / "dashboard.css").read_text(encoding="utf-8")

    assert "const RUNS_STICKY_COLUMN_LIMITS" in dashboard_js
    assert "function scheduleRunsStickyColumnSizing()" in dashboard_js
    assert "runs-table--measuring-sticky-columns" in dashboard_js
    assert "scheduleRunsStickyColumnSizing();" in dashboard_js
    for column in ("status", "run", "task", "model", "dataset", "owner", "time"):
        assert f"--runs-col-{column}-min-width" in styles
    for column in ("status", "run"):
        assert f"--runs-col-{column}-max-width" in styles
    assert ".runs-table.runs-table--measuring-sticky-columns" in styles
    assert ".runs-table .col-model .model-label-text" in styles
    assert "text-overflow: clip" in styles


def test_runs_table_freezes_dataset_owner_and_date_with_identity_columns() -> None:
    markup = (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8")
    source = DASHBOARD_JS.read_text(encoding="utf-8")
    styles = (DASHBOARD_DIR / "dashboard.css").read_text(encoding="utf-8")

    run_header = markup.index('class="col-run sortable" data-sort="run"')
    status_header = markup.index('class="col-status sortable" data-sort="status"')
    assert run_header < status_header
    assert markup.index("RUN NAME", run_header, status_header)
    run_rule = _rule(styles, ".runs-table .col-run {")
    status_rule = _rule(styles, ".runs-table .col-status {")
    assert "left: 0;" in run_rule
    assert "left: var(--runs-col-run-width);" in status_rule

    run_row = source.index('data-can-delete-pass=')
    assert source.index('<td class="col-run">', run_row) < source.index(
        '<td class="col-status">', run_row
    )
    pass_row = source.index('return `<tr class="pass-member')
    assert source.index('<td class="col-run">', pass_row) < source.index(
        '<td class="col-status">', pass_row
    )

    identity_headers = [
        markup.index('class="col-model sortable"'),
        markup.index('class="col-dataset sortable"'),
        markup.index('class="col-owner sortable"'),
        markup.index('class="col-time sortable"'),
        markup.index('class="col-analysis"'),
    ]
    assert identity_headers == sorted(identity_headers)
    for column in ("dataset", "owner", "time"):
        rule = _rule(styles, f".runs-table .col-{column} {{")
        assert "position: sticky;" in rule
        assert "left: calc(" in rule
        assert f"th.col-{column}" in styles
        assert f"td.col-{column}" in styles

    timestamp_rule = _rule(styles, ".timestamp {")
    assert "display: inline-flex;" in timestamp_rule
    assert "gap: var(--space-xs);" in timestamp_rule
    date_cell_rule = _rule(styles, ".runs-table :is(th, td).col-time {")
    assert "padding-inline: var(--space-sm);" in date_cell_rule
