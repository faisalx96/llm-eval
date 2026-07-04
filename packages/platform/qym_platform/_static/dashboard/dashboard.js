/**
 * قيِّم Analytics Dashboard
 * Dense, keyboard-driven interface for analyzing evaluation runs
 */

(() => {
  'use strict';

  // ═══════════════════════════════════════════════════
  // BASE URL HANDLING (for proxy/subpath compatibility)
  // ═══════════════════════════════════════════════════

  // Compute the base URL for API calls, handling reverse proxy scenarios
  // e.g., if served at https://proxy.example/workspace/8080/, API calls should go to that base
  function getAppRootPath() {
    const path = window.location.pathname;
    const patterns = [
      /\/projects\/[^/]+\/runs\/[^/]+$/,
      /\/projects\/[^/]+\/reviews$/,
      /\/projects\/[^/]+\/charts$/,
      /\/projects\/[^/]+\/models$/,
      /\/projects\/[^/]+\/overview$/,
      /\/projects\/[^/]+\/settings$/,
      /\/projects\/[^/]+$/,
      /\/run\/[^/]+$/,
      /\/reviews$/,
      /\/profile$/,
      /\/admin$/,
      /\/trash$/,
      /\/compare$/,
    ];
    for (const pattern of patterns) {
      if (pattern.test(path)) {
        const next = path.replace(pattern, '/');
        return next.endsWith('/') ? next : `${next}/`;
      }
    }
    if (path.endsWith('/')) return path;
    return (path.substring(0, path.lastIndexOf('/') + 1) || '/');
  }

  const BASE_URL = (() => {
    const loc = window.location;
    return loc.origin + getAppRootPath();
  })();

  // Helper to build API URLs
  function apiUrl(path) {
    // Remove leading ./ or / from path
    const cleanPath = path.replace(/^\.?\//, '');
    return BASE_URL + cleanPath;
  }

  function getProjectSlugFromPath() {
    const match = window.location.pathname.match(/\/projects\/([^/]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function getRunVersionKey(run) {
    if (!run) return '';
    const branch = String(run.git_branch || '').trim();
    const commit = String(run.git_commit || '').trim();
    if (branch && commit) return `${branch}/${commit}`;
    return commit || branch || '';
  }

  // Dataset filter identity: each dataset VERSION is its own entry. The key encodes
  // name + dataset version so e.g. "ragbench-100 v1" and "ragbench-100 v4" filter
  // independently. Runs with no platform dataset version fall back to just the name.
  const DATASET_KEY_SEP = '␟';
  function getRunDatasetKey(run) {
    if (!run) return '';
    const name = String(run.dataset_name || '');
    const version = String(run.dataset_version || '').trim();
    return version ? name + DATASET_KEY_SEP + version : name;
  }
  function splitDatasetKey(key) {
    const s = String(key == null ? '' : key);
    const i = s.indexOf(DATASET_KEY_SEP);
    return i === -1 ? { name: s, version: '' } : { name: s.slice(0, i), version: s.slice(i + 1) };
  }
  function getDatasetFilterLabel(key) {
    const p = splitDatasetKey(key);
    return p.version ? `${p.name} ${p.version}` : p.name;
  }
  function renderDatasetFilterLabel(key) {
    const p = splitDatasetKey(key);
    return escapeHtml(p.name) + (p.version && window.QymShell ? QymShell.datasetVersionInline(p.version) : '');
  }

  function getProjectStorageKey() {
    return 'qym:last-project-slug';
  }

  function getStoredProjectSlug() {
    try {
      return window.localStorage.getItem(getProjectStorageKey()) || '';
    } catch {
      return '';
    }
  }

  function storeProjectSlug(slug) {
    try {
      window.localStorage.setItem(getProjectStorageKey(), slug || '');
    } catch {}
  }

  function projectUrl(slug, suffix = '') {
    const encoded = encodeURIComponent(slug || '');
    const cleanSuffix = String(suffix || '').replace(/^\/+/, '');
    return apiUrl(`projects/${encoded}${cleanSuffix ? `/${cleanSuffix}` : ''}`);
  }

  function navigateTo(url) {
    if (window.QymShell && typeof window.QymShell.navigateTo === 'function') {
      window.QymShell.navigateTo(url);
      return;
    }
    window.location.href = url;
  }

  function isModifiedEvent(e) {
    return !!(e && (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button === 1));
  }

  function openUrl(url, e) {
    if (isModifiedEvent(e)) {
      window.open(url, '_blank', 'noopener');
      return;
    }
    navigateTo(url);
  }

  // ═══════════════════════════════════════════════════
  // STATE
  // ═══════════════════════════════════════════════════

  const state = {
    runs: null,
    flatRuns: [],
    filteredRuns: [],
    sortKey: 'time-desc',
    tablePage: 1,
    tableFilterKey: '',
    quickFilter: 'all',
    filterTasks: new Set(),
    filterModels: new Set(),  // Multi-select for models
    filterDatasets: new Set(),
    filterStatuses: new Set(),
    filterVersions: new Set(),
    filterUsers: new Set(),
    knownVersions: new Set(),
    knownVersionsProjectSlug: '',
    currentView: window.__QYM_INITIAL_VIEW__ || 'charts',
    selectedRuns: new Set(),
    focusedIndex: -1,
    aggregations: null,
    chartData: null,  // Aggregated data for charts
    chartDatasetTab: {},  // {taskName: datasetName} — active dataset tab per task card
    chartFirstColWidth: 320,
    allMetrics: [],   // All unique metric names across runs
    visibleMetrics: null, // null = all visible; Set of visible metric names
    allModels: [],    // All unique model names
    currentUser: null,
    availableProjects: [],
    currentProject: null,
    cohortAnchorRuns: null,
    chartGroupMetricStats: {},
    // Models view state (uses global filterTasks/filterDatasets for task+dataset)
    modelsViewState: {
      selectedMetric: '',
      globalK: 5,
      threshold: 0.8,
      metricIsBoolean: false,
      metricIsNumeric: false,
      visibleStatKeys: null,  // null = all visible; [] = none; otherwise explicit keys
      modelRunSelections: {},  // model_name -> [run_file_paths] (custom selection)
      modelStats: {},          // model_name -> computed stats
      visibleTraceMetrics: [],
      requestKey: '',
      inFlightRequestKey: '',
      inFlightRequestPromise: null,
      renderToken: 0,
    },
    runsFetchMeta: {
      totalCount: 0,
      hasLoadedAllPages: false,
      lastFullFetchAt: 0,
      inFlight: false,
      pendingOptions: null,
    },
  };

  // Chart color palette - extended for more models
  const CHART_COLORS = [
    '#00d4aa', '#00a8ff', '#a855f7', '#f472b6',
    '#fbbf24', '#60a5fa', '#34d399', '#fb923c',
    '#e879f9', '#22d3ee', '#facc15', '#f87171',
    '#4ade80', '#818cf8', '#fb7185', '#a3e635',
    '#2dd4bf', '#c084fc', '#fcd34d', '#6ee7b7'
  ];
  const TABLE_PAGE_SIZE = 50;
  const CHART_FIRST_COL_DEFAULT_WIDTH = 320;
  const CHART_FIRST_COL_MIN_WIDTH = 280;
  const CHART_FIRST_COL_MAX_WIDTH = 720;

  // ⚡ Trace metrics — auto-derived from OTEL spans
  function _fmtTraceNum(v) {
    if (v >= 1000000) return (v / 1000000).toFixed(1) + 'M';
    if (v >= 1000) return (v / 1000).toFixed(1) + 'K';
    return String(Math.round(v));
  }
  const TRACE_METRICS = [
    { key: 'avg_tokens',    label: '⚡ Avg Tokens',        modelsLabel: '⚡ Avg Tokens',   fmt: v => v != null ? _fmtTraceNum(v) : '—' },
    { key: 'avg_llm_calls', label: '⚡ Avg LLM Calls',     modelsLabel: '⚡ Avg LLM Calls', fmt: v => v != null ? v.toFixed(1) : '—' },
    { key: 'avg_tool_calls',label: '⚡ Avg Tool Calls',    modelsLabel: '⚡ Avg Tool Calls', fmt: v => v != null ? v.toFixed(1) : '—' },
    { key: 'tool_success_rate', label: '⚡ Tool Success Rate', modelsLabel: '⚡ Tool Success Rate', fmt: v => v != null ? (v * 100).toFixed(1) + '%' : '—' },
  ];
  const SYSTEM_DISPLAY_COLUMNS = [
    { key: 'latency', label: '⚡ Avg Latency' },
    { key: 'median-latency', label: '⚡ Median Latency' },
  ];
  const GROUP_PASS_AT_K_COLUMN_KEY = '__group_pass_at_k__';
  const GROUP_CONSISTENCY_COLUMN_KEY = '__group_consistency__';
  const GROUP_RELIABILITY_COLUMN_KEY = '__group_reliability__';
  const GROUP_DISPLAY_COLUMNS = [
    { key: GROUP_PASS_AT_K_COLUMN_KEY, label: 'Pass@K' },
    { key: GROUP_CONSISTENCY_COLUMN_KEY, label: 'Consistency' },
    { key: GROUP_RELIABILITY_COLUMN_KEY, label: 'Reliability' },
  ];
  const RUNS_TABLE_BASE_COLUMN_COUNT = 11;
  const MODELS_VIEW_SCORE_STAT_KEYS = ['passAtK', 'passHatK', 'maxAtK', 'consistency', 'reliability', 'avgScore', 'failedCount', 'totalRetries', 'avgLatency', 'medianLatency', 'correctDistribution'];
  const MODELS_VIEW_NUMERIC_STAT_KEYS = ['avgScore', 'minScore', 'maxAtK', 'stddevScore', 'totalScoreSum', 'failedCount', 'totalRetries', 'avgLatency', 'medianLatency'];
  function _traceMetricsForRuns(runs = null) {
    const sourceRuns = Array.isArray(runs)
      ? runs
      : ((state.filteredRuns && state.filteredRuns.length) ? state.filteredRuns : state.flatRuns);
    if (!Array.isArray(sourceRuns) || sourceRuns.length === 0) return [];
    return sourceRuns.some(r => r.trace_stats) ? TRACE_METRICS : [];
  }

  function _hasAnyTraceStats(runs = null) {
    return _traceMetricsForRuns(runs).length > 0;
  }

  function _allMetricsWithTrace(runs = null, baseMetrics = state.allMetrics) {
    return [
      ...(baseMetrics || []),
      ...GROUP_DISPLAY_COLUMNS.map(col => col.key),
      ...SYSTEM_DISPLAY_COLUMNS.map(col => col.key),
      ..._traceMetricsForRuns(runs).map(tm => tm.key),
    ];
  }

  function _visibleSystemColumns() {
    const vis = state.visibleMetrics;
    if (vis === null) return SYSTEM_DISPLAY_COLUMNS;
    return SYSTEM_DISPLAY_COLUMNS.filter(col => vis.has(col.key));
  }

  function _visibleTraceMetrics(runs = null) {
    const traceMetrics = _traceMetricsForRuns(runs);
    if (traceMetrics.length === 0) return [];
    const vis = state.visibleMetrics;
    if (vis === null) return traceMetrics;
    return traceMetrics.filter(tm => vis.has(tm.key));
  }

  function getRunsTableColumnCount(metricsCount, visibleSystemColumnCount, visibleTraceMetricCount) {
    const metricCols = Number(metricsCount) || 0;
    const systemCols = Number(visibleSystemColumnCount) || 0;
    const traceMetricCols = Number(visibleTraceMetricCount) || 0;
    const traceCols = traceMetricCols > 0 ? traceMetricCols + 1 : 0; // +1 separator
    return RUNS_TABLE_BASE_COLUMN_COUNT + metricCols + systemCols + traceCols;
  }

  function getMetricDisplayName(metricKey) {
    const groupColumn = GROUP_DISPLAY_COLUMNS.find(col => col.key === metricKey);
    if (groupColumn) return groupColumn.label;
    const systemColumn = SYSTEM_DISPLAY_COLUMNS.find(col => col.key === metricKey);
    if (systemColumn) return systemColumn.label;
    const traceMetric = TRACE_METRICS.find(tm => tm.key === metricKey);
    return traceMetric ? traceMetric.label : metricKey;
  }

  function getChartCardId(taskName, datasetName) {
    return `${taskName}|||${datasetName}`.replace(/[^a-zA-Z0-9]/g, '_');
  }

  function comboHasVersionData(combo) {
    if (!combo || !combo.models) return false;
    return Object.values(combo.models).some(data =>
      (data.runsList || []).some(run => run.git_commit)
    );
  }

  function getEffectiveChartGroupMode(cardId, combo) {
    const mode = state.chartGroupMode?.[cardId] || 'run';
    if (!comboHasVersionData(combo) && (mode === 'version' || mode === 'version-model' || mode === 'model-version')) {
      return 'run';
    }
    return mode;
  }

  function shouldShowGroupedRunColumnOptions() {
    if (state.currentView !== 'charts' || !state.chartData) return false;
    return (state.chartData.tasks || []).some(taskGroup => {
      const datasets = taskGroup.datasets || [];
      const activeDataset = state.chartDatasetTab[taskGroup.task] || datasets[0]?.dataset || '';
      const combo = datasets.find(d => d.dataset === activeDataset) || datasets[0];
      if (!combo) return false;
      const cardId = getChartCardId(combo.task, combo.dataset);
      const mode = getEffectiveChartGroupMode(cardId, combo);
      if (mode === 'run') return false;
      const expansion = state.chartGroupExpansion?.[cardId];
      if (!expansion || expansion.mode !== mode) return true;
      return !Object.values(expansion.expanded || {}).some(isExpanded => isExpanded === true);
    });
  }

  function getTraceMetricConfig(metricKey) {
    return TRACE_METRICS.find(tm => tm.key === metricKey) || null;
  }

  function isTraceMetricKey(metricKey) {
    return !!getTraceMetricConfig(metricKey);
  }

  function renderTraceMetricTableCell(traceMetric, value) {
    if (value === undefined || value === null) {
      return '<td class="col-trace-metric-value">—</td>';
    }
    if (traceMetric.key === 'tool_success_rate') {
      const metricClass = window.QymMetrics.getMetricColorClass(value, 'score');
      return `<td class="col-trace-metric-value"><span class="metric-score ${metricClass}">${traceMetric.fmt(value)}</span></td>`;
    }
    return `<td class="col-trace-metric-value">${traceMetric.fmt(value)}</td>`;
  }

  function getRunComboPeerValues(runs, run, valueGetter) {
    if (!Array.isArray(runs) || !run || typeof valueGetter !== 'function') return [];
    return runs
      .filter(candidate =>
        candidate
        && candidate.file_path !== run.file_path
        && candidate.task_name === run.task_name
        && getRunModelKey(candidate) === getRunModelKey(run)
        && candidate.dataset_name === run.dataset_name
      )
      .map(candidate => valueGetter(candidate))
      .filter(value => value !== undefined && value !== null && !isNaN(value));
  }

  // ═══════════════════════════════════════════════════
  // UTILITIES
  // ═══════════════════════════════════════════════════

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);
  const el = (id) => document.getElementById(id);
  const EMPTY_FILTER_VALUE = '__empty__';

  function debounce(fn, ms) {
    let t;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...args), ms);
    };
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  const MODEL_REASONING_BADGE_TITLE = 'Reasoning model';
  const MODEL_REASONING_BADGE_ICON = `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M9 18h6" />
      <path d="M10 21h4" />
      <path d="M12 2a7 7 0 0 0-4.2 12.6c.7.5 1.2 1.4 1.2 2.3V18h6v-1.1c0-.9.5-1.8 1.2-2.3A7 7 0 0 0 12 2Z" />
    </svg>
  `;

  function hasReasoningTraceStats(traceStats) {
    if (!traceStats || typeof traceStats !== 'object') return false;
    return !!(
      traceStats.has_reasoning
      || traceStats.has_reasoning_tokens
      || Number(traceStats.reasoning_tokens || 0) > 0
      || Number(traceStats.avg_reasoning_tokens || 0) > 0
    );
  }

  function runHasReasoning(run) {
    return hasReasoningTraceStats(run?.trace_stats);
  }

  function getModelVariantKey(modelName, hasReasoning) {
    return `${String(modelName || '')}|||${hasReasoning ? 'reasoning' : 'plain'}`;
  }

  function parseModelVariantKey(modelValue) {
    const raw = String(modelValue || '');
    const marker = '|||';
    const idx = raw.lastIndexOf(marker);
    if (idx < 0) {
      return { rawModelName: raw, hasReasoning: null, isVariantKey: false };
    }
    const suffix = raw.slice(idx + marker.length);
    if (suffix !== 'reasoning' && suffix !== 'plain') {
      return { rawModelName: raw, hasReasoning: null, isVariantKey: false };
    }
    return {
      rawModelName: raw.slice(0, idx),
      hasReasoning: suffix === 'reasoning',
      isVariantKey: true,
    };
  }

  function getRunModelKey(run) {
    if (!run) return getModelVariantKey('', false);
    return run.model_key || getModelVariantKey(run.raw_model_name || run.model_name || '', !!run.model_has_reasoning || runHasReasoning(run));
  }

  function getModelFilterOptionLabel(value) {
    return stripModelProvider(parseModelVariantKey(value).rawModelName || value || '');
  }

  function compareModelVariantKeys(a, b) {
    const parsedA = parseModelVariantKey(a);
    const parsedB = parseModelVariantKey(b);
    const labelCmp = stripModelProvider(parsedA.rawModelName || '').localeCompare(stripModelProvider(parsedB.rawModelName || ''));
    if (labelCmp !== 0) return labelCmp;
    if (!!parsedA.hasReasoning === !!parsedB.hasReasoning) return 0;
    return parsedA.hasReasoning ? 1 : -1;
  }

  function modelHasReasoning(modelName, runs = null) {
    const sourceRuns = Array.isArray(runs) ? runs : state.flatRuns;
    return Array.isArray(sourceRuns) && sourceRuns.some(run =>
      run && getRunModelKey(run) === modelName && runHasReasoning(run)
    );
  }

  function renderModelReasoningBadge() {
    return `<span class="model-reasoning-badge" title="${escapeHtml(MODEL_REASONING_BADGE_TITLE)}" aria-label="${escapeHtml(MODEL_REASONING_BADGE_TITLE)}">${MODEL_REASONING_BADGE_ICON}</span>`;
  }

  function renderModelLabel(displayLabel, hasReasoning) {
    const label = displayLabel || '—';
    return `<span class="model-label"><span class="model-label-text">${escapeHtml(label)}</span>${hasReasoning ? renderModelReasoningBadge() : ''}</span>`;
  }

  function renderModelLabelForRun(run, rawModelName = null) {
    const modelName = rawModelName == null ? (run?.raw_model_name || run?.model_name) : rawModelName;
    const hasReasoning = run?.model_has_reasoning != null ? !!run.model_has_reasoning : runHasReasoning(run);
    return renderModelLabel(stripModelProvider(modelName || ''), hasReasoning);
  }

  function renderModelLabelForModelName(modelName, runs = null) {
    const parsed = parseModelVariantKey(modelName);
    const rawModelName = parsed.rawModelName || modelName || '';
    const hasReasoning = parsed.isVariantKey ? !!parsed.hasReasoning : modelHasReasoning(modelName, runs);
    return renderModelLabel(stripModelProvider(rawModelName), hasReasoning);
  }

  function clampChartFirstColWidth(width) {
    const numericWidth = Number(width);
    if (!Number.isFinite(numericWidth)) return CHART_FIRST_COL_DEFAULT_WIDTH;
    return Math.min(CHART_FIRST_COL_MAX_WIDTH, Math.max(CHART_FIRST_COL_MIN_WIDTH, Math.round(numericWidth)));
  }

  function applyChartFirstColWidth(width) {
    const nextWidth = clampChartFirstColWidth(width);
    state.chartFirstColWidth = nextWidth;
    document.documentElement.style.setProperty('--chart-first-col-width', `${nextWidth}px`);
    return nextWidth;
  }

  function formatDate(isoStr) {
    try {
      const d = new Date(isoStr);
      return {
        date: d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
        time: d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false }),
        full: d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' }),
        iso: d.toISOString().split('T')[0],
      };
    } catch {
      return { date: '--', time: '--', full: '--', iso: '--' };
    }
  }

  function formatPercent(rate) {
    const pct = rate * 100;
    if (pct === 0) return '0%';
    if (pct === 100) return '100%';
    return `${pct.toFixed(1)}%`;
  }

  function getSuccessClass(rate) {
    if (rate >= 0.9) return 'score-5';
    if (rate >= 0.75) return 'score-4';
    if (rate >= 0.6) return 'score-3';
    if (rate >= 0.4) return 'score-2';
    return 'score-1';
  }

  function formatNumber(n) {
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
    return n.toString();
  }

  function formatLatency(ms) {
    if (ms >= 1000) {
      return (ms / 1000).toFixed(1) + 's';
    }
    return Math.round(ms) + 'ms';
  }

  function formatDurationMs(ms) {
    if (ms == null || !Number.isFinite(Number(ms)) || Number(ms) < 0) return '—';
    const totalMs = Number(ms);
    if (totalMs < 1000) return Math.round(totalMs) + 'ms';
    if (totalMs < 60000) return (totalMs / 1000).toFixed(totalMs >= 10000 ? 0 : 1) + 's';
    const totalSeconds = Math.round(totalMs / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    if (hours > 0) return hours + 'h ' + minutes + 'm';
    if (minutes > 0) return minutes + 'm ' + seconds + 's';
    return totalSeconds + 's';
  }

  function isToday(isoStr) {
    const d = new Date(isoStr);
    const now = new Date();
    return d.toDateString() === now.toDateString();
  }

  function isWithinDays(isoStr, days) {
    const d = new Date(isoStr);
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - days);
    return d >= cutoff;
  }

  function truncateText(text, maxLen = null) {
    // No truncation - return full text
    return text || '';
  }

  function getInitials(name) {
    if (!name) return '?';
    const parts = name.trim().split(/\s+/);
    if (parts.length >= 2) {
      return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }
    return name.substring(0, 2).toUpperCase();
  }

  function stripModelProvider(modelName) {
    // Remove provider prefix (e.g., "qwen/qwen3-235b" -> "qwen3-235b")
    if (!modelName) return '';
    const slashIdx = modelName.indexOf('/');
    return slashIdx > 0 ? modelName.slice(slashIdx + 1) : modelName;
  }

  function stripProviderFromRunId(runId) {
    // Remove provider prefix from run ID (e.g., "ragbench-qwen/qwen3-235b-251205-1918" -> "ragbench-qwen3-235b-251205-1918")
    if (!runId) return '';
    const slashIdx = runId.indexOf('/');
    if (slashIdx < 0) return runId;
    // Find the dash before the provider (e.g., "ragbench-" before "qwen/")
    const beforeSlash = runId.slice(0, slashIdx);
    const lastDash = beforeSlash.lastIndexOf('-');
    if (lastDash < 0) return runId.slice(slashIdx + 1);
    // Keep everything before the provider name, then append everything after the slash
    return beforeSlash.slice(0, lastDash + 1) + runId.slice(slashIdx + 1);
  }

  function getRunDisplayName(run) {
    if (!run) return '';
    return run.run_name || run.external_run_id || stripProviderFromRunId(run.run_id || run.file_path || '');
  }

  function isEmptyFilterValue(value) {
    return value === null || value === undefined || String(value).trim() === '';
  }

  function getTableFilterKey() {
    return JSON.stringify({
      quickFilter: state.quickFilter,
      tasks: [...state.filterTasks].sort(),
      models: [...state.filterModels].sort(),
      datasets: [...state.filterDatasets].sort(),
      statuses: [...state.filterStatuses].sort(),
      versions: [...state.filterVersions].sort(),
      users: [...state.filterUsers].sort(),
    });
  }

  function getTablePageCount(totalRuns = state.filteredRuns.length) {
    return Math.max(1, Math.ceil((totalRuns || 0) / TABLE_PAGE_SIZE));
  }

  function clampTablePage(totalRuns = state.filteredRuns.length) {
    const pageCount = getTablePageCount(totalRuns);
    if (!Number.isFinite(state.tablePage) || state.tablePage < 1) state.tablePage = 1;
    if (state.tablePage > pageCount) state.tablePage = pageCount;
    return pageCount;
  }

  function getTablePageSlice(runs = state.filteredRuns) {
    const totalRuns = Array.isArray(runs) ? runs.length : 0;
    const pageCount = clampTablePage(totalRuns);
    const start = totalRuns === 0 ? 0 : (state.tablePage - 1) * TABLE_PAGE_SIZE;
    const end = Math.min(start + TABLE_PAGE_SIZE, totalRuns);
    return {
      totalRuns,
      pageCount,
      start,
      end,
      pageRuns: Array.isArray(runs) ? runs.slice(start, end) : [],
    };
  }

  function setTablePage(page, options = {}) {
    const { syncFocus = false } = options;
    const { totalRuns, pageCount } = getTablePageSlice(state.filteredRuns);
    const nextPage = Math.min(Math.max(1, Number(page) || 1), pageCount);
    state.tablePage = nextPage;
    if (syncFocus) {
      state.focusedIndex = totalRuns > 0 ? (nextPage - 1) * TABLE_PAGE_SIZE : -1;
    }
  }

  function renderTablePagination(meta) {
    const infoEls = Array.from(document.querySelectorAll('.table-pagination-info'));
    const pageEls = Array.from(document.querySelectorAll('.table-pagination-page'));
    const prevBtns = Array.from(document.querySelectorAll('[data-table-page="prev"]'));
    const nextBtns = Array.from(document.querySelectorAll('[data-table-page="next"]'));
    if (!infoEls.length || !pageEls.length || !prevBtns.length || !nextBtns.length) return;

    const { totalRuns, pageCount, start, end } = meta;
    const startLabel = totalRuns === 0 ? 0 : start + 1;
    infoEls.forEach(infoEl => { infoEl.textContent = `Showing ${startLabel}-${end} of ${totalRuns} runs`; });
    pageEls.forEach(pageEl => { pageEl.textContent = `Page ${pageCount === 0 ? 0 : state.tablePage} of ${pageCount}`; });
    prevBtns.forEach(prevBtn => { prevBtn.disabled = state.tablePage <= 1; });
    nextBtns.forEach(nextBtn => { nextBtn.disabled = state.tablePage >= pageCount; });
  }

  function getFilterOptionLabel(value, labelFn = null) {
    if (value === EMPTY_FILTER_VALUE) return 'Empty / Missing';
    const label = labelFn ? labelFn(value) : value;
    return isEmptyFilterValue(label) ? 'Empty / Missing' : String(label);
  }

  function collectFilterValues(runs, getter) {
    const values = new Set();
    let hasEmpty = false;
    (runs || []).forEach(run => {
      const value = getter(run);
      if (isEmptyFilterValue(value)) {
        hasEmpty = true;
      } else {
        values.add(value);
      }
    });
    const ordered = Array.from(values).sort((a, b) => String(a).localeCompare(String(b)));
    if (hasEmpty) ordered.push(EMPTY_FILTER_VALUE);
    return ordered;
  }

  function matchesFilterSelection(selection, value) {
    if (!selection || selection.size === 0) return true;
    if (selection.has('__none__')) return false;
    const normalized = isEmptyFilterValue(value) ? EMPTY_FILTER_VALUE : value;
    return selection.has(normalized);
  }

  function getRunOwnerKey(run) {
    return run && run.owner && run.owner.id ? String(run.owner.id) : '';
  }

  function getOwnerForFilterValue(value) {
    if (value === EMPTY_FILTER_VALUE) return null;
    const run = state.flatRuns.find(r => getRunOwnerKey(r) === value);
    return run && run.owner ? run.owner : null;
  }

  function getOwnerFilterLabel(value) {
    if (value === EMPTY_FILTER_VALUE) return 'Empty / Missing';
    const owner = getOwnerForFilterValue(value);
    if (!owner) return value;
    return owner.display_name || (owner.email ? owner.email.split('@')[0] : '') || owner.id || value;
  }

  function renderOwnerFilterLabel(value) {
    if (value === EMPTY_FILTER_VALUE) return 'Empty / Missing';
    const label = getOwnerFilterLabel(value);
    return `<span class="owner-filter-label"><span class="owner-avatar">${escapeHtml(getInitials(label))}</span><span class="owner-filter-text">${escapeHtml(label)}</span></span>`;
  }

  function summarizeFilterSelection(selection, labelFn = null) {
    if (!selection || selection.size === 0) return '';
    if (selection.has('__none__')) return 'none';
    return [...selection].map(value => {
      const label = getFilterOptionLabel(value, labelFn);
      return label.length > 20 ? label.slice(0, 20) + '...' : label;
    }).join(', ');
  }

  // ═══════════════════════════════════════════════════
  // GENERIC MULTI-SELECT BUILDER
  // ═══════════════════════════════════════════════════

  function buildMultiSelect({ btnId, dropdownId, stateSet, values, labelFn, htmlLabelFn, defaultLabel, showSearch, searchPlaceholder, colorFn, onchange }) {
    const btn = el(btnId);
    const dropdown = el(dropdownId);
    if (!btn || !dropdown) return;

    const searchValue = dropdown.querySelector('.model-search-input')?.value || '';

    let html = '<div class="ms-actions"><button class="ms-action-btn" data-action="all">Select All</button><button class="ms-action-btn" data-action="none">None</button></div>';
    if (showSearch) {
      html += `<div class="model-search-box"><input type="text" class="model-search-input" placeholder="${searchPlaceholder || 'Search...'}" value="${escapeHtml(searchValue)}" /></div>`;
    }
    html += values.map((v, idx) => {
      const checked = stateSet.size === 0 || stateSet.has(v) ? 'checked' : '';
      const label = getFilterOptionLabel(v, labelFn);
      const color = colorFn && v !== EMPTY_FILTER_VALUE ? colorFn(v, idx) : '';
      const colorDot = color ? `<span class="model-color" style="background:${color}"></span>` : '';
      const emptyClass = v === EMPTY_FILTER_VALUE ? ' is-empty-option' : '';
      const hidden = showSearch && searchValue && !label.toLowerCase().includes(searchValue.toLowerCase()) ? ' style="display:none"' : '';
      const labelHtml = htmlLabelFn ? htmlLabelFn(v, label) : escapeHtml(label);
      return `<div class="multi-select-option${emptyClass}" data-value="${escapeHtml(v)}" title="${escapeHtml(label)}"${hidden}>${colorDot}<input type="checkbox" ${checked} /><span>${labelHtml}</span></div>`;
    }).join('');
    dropdown.innerHTML = html;

    // Wire search
    if (showSearch) {
      const searchInput = dropdown.querySelector('.model-search-input');
      if (searchInput) {
        searchInput.addEventListener('input', (e) => {
          const q = e.target.value.toLowerCase();
          dropdown.querySelectorAll('.multi-select-option').forEach(opt => {
            const text = opt.textContent || opt.dataset.value || '';
            opt.style.display = text.toLowerCase().includes(q) ? '' : 'none';
          });
        });
        searchInput.addEventListener('click', (e) => e.stopPropagation());
        searchInput.addEventListener('keydown', (e) => e.stopPropagation());
      }
    }

    // Wire All/None buttons
    dropdown.querySelectorAll('.ms-action-btn').forEach(ab => {
      ab.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (ab.dataset.action === 'all') {
          stateSet.clear();
        } else {
          stateSet.clear();
          stateSet.add('__none__');
        }
        syncMultiSelect({ btnId, dropdownId, stateSet, values, defaultLabel, labelFn });
        if (onchange) onchange();
        render();
      });
    });

    // Wire individual option clicks
    dropdown.querySelectorAll('.multi-select-option').forEach(opt => {
      opt.addEventListener('click', (e) => {
        e.stopPropagation();
        const value = opt.dataset.value;
        const wasNone = stateSet.has('__none__');
        stateSet.delete('__none__');
        if (wasNone) {
          stateSet.clear();
          stateSet.add(value);
        } else if (stateSet.size === 0) {
          // Was "all" - select all except clicked one
          values.forEach(v => { if (v !== value) stateSet.add(v); });
        } else if (stateSet.has(value)) {
          stateSet.delete(value);
          if (stateSet.size === 0) stateSet.add('__none__');
        } else {
          stateSet.add(value);
        }
        // Normalize: if all selected, clear to "show all"
        if (!stateSet.has('__none__') && stateSet.size >= values.length) stateSet.clear();
        syncMultiSelect({ btnId, dropdownId, stateSet, values, defaultLabel, labelFn, htmlLabelFn });
        if (onchange) onchange();
        render();
      });
    });

    syncMultiSelect({ btnId, dropdownId, stateSet, values, defaultLabel, labelFn, htmlLabelFn });
  }

  function syncMultiSelect({ btnId, dropdownId, stateSet, values, defaultLabel, labelFn, htmlLabelFn }) {
    const btn = el(btnId);
    const dropdown = el(dropdownId);

    // Update button text
    if (btn) {
      if (stateSet.size === 0) {
        btn.textContent = defaultLabel;
        btn.classList.remove('has-selection');
      } else if (stateSet.has('__none__')) {
        btn.textContent = 'None';
        btn.classList.add('has-selection');
      } else if (stateSet.size === 1) {
        if (htmlLabelFn) {
          const value = [...stateSet][0];
          const label = getFilterOptionLabel(value, labelFn);
          btn.innerHTML = htmlLabelFn(value, label);
        } else {
          btn.textContent = getFilterOptionLabel([...stateSet][0], labelFn);
        }
        btn.classList.add('has-selection');
      } else {
        btn.textContent = `${stateSet.size} selected`;
        btn.classList.add('has-selection');
      }
    }

    // Update checkboxes
    if (dropdown) {
      const isAll = stateSet.size === 0;
      const isNone = stateSet.has('__none__');
      dropdown.querySelectorAll('.multi-select-option').forEach(opt => {
        const cb = opt.querySelector('input[type="checkbox"]');
        if (!cb) return;
        const v = opt.dataset.value;
        cb.checked = isAll || (!isNone && stateSet.has(v));
      });
    }
  }

  // ═══════════════════════════════════════════════════
  // METRIC VISIBILITY
  // ═══════════════════════════════════════════════════

  function getAvailableMetricsForRuns(runs) {
    if (!Array.isArray(runs) || runs.length === 0) return [];

    const available = new Set();
    runs.forEach(run => {
      if (Array.isArray(run.metrics)) {
        run.metrics.forEach(metric => available.add(metric));
      }
      if (run.metric_averages) {
        Object.keys(run.metric_averages).forEach(metric => available.add(metric));
      }
    });

    const ordered = state.allMetrics.filter(metric => available.has(metric));
    const extras = Array.from(available).filter(metric => !state.allMetrics.includes(metric)).sort();
    return ordered.concat(extras);
  }

  function getVisibleMetrics(availableMetrics = _allMetricsWithTrace()) {
    if (!state.visibleMetrics) return availableMetrics;
    return availableMetrics.filter(m => state.visibleMetrics.has(m));
  }

  function setVisibleMetricsForAvailable(availableMetrics, checkedMetrics) {
    const availableSet = new Set(availableMetrics || []);
    const knownMetrics = Array.from(new Set([
      ...state.allMetrics,
      ...(availableMetrics || []),
      ...(state.visibleMetrics ? [...state.visibleMetrics] : []),
    ]));

    const preserved = state.visibleMetrics
      ? knownMetrics.filter(m => !availableSet.has(m) && state.visibleMetrics.has(m))
      : knownMetrics.filter(m => !availableSet.has(m));

    const merged = new Set([...preserved, ...checkedMetrics]);
    state.visibleMetrics = merged.size === knownMetrics.length ? null : merged;
  }

  function saveMetricVisibility() {
    try {
      if (!state.visibleMetrics) {
        sessionStorage.removeItem('qym_visible_metrics');
      } else {
        sessionStorage.setItem('qym_visible_metrics', JSON.stringify([...state.visibleMetrics]));
      }
    } catch (e) {}
  }

  function loadMetricVisibility() {
    try {
      const saved = sessionStorage.getItem('qym_visible_metrics');
      if (saved) {
        const arr = JSON.parse(saved);
        if (Array.isArray(arr)) {
          const allowedMetrics = _allMetricsWithTrace(state.flatRuns, state.allMetrics);
          const valid = arr.filter(m => allowedMetrics.includes(m));
          if (valid.length > 0 && valid.length < allowedMetrics.length) {
            state.visibleMetrics = new Set(valid);
          } else {
            state.visibleMetrics = null;
          }
        }
      }
    } catch (e) {}
  }

  function populateMetricVisibility(availableMetrics = state.allMetrics, runs = null) {
    const wrapper = el('metric-visibility-wrapper');
    const dropdown = el('metric-visibility-dropdown');
    const btn = el('metric-visibility-btn');
    if (!wrapper || !dropdown || !btn) return;

    const traceMetrics = _traceMetricsForRuns(runs);
    const groupColumns = shouldShowGroupedRunColumnOptions() ? GROUP_DISPLAY_COLUMNS : [];
    const systemColumns = SYSTEM_DISPLAY_COLUMNS;
    const metricOptions = [
      ...(availableMetrics || []),
      ...groupColumns.map(col => col.key),
      ...systemColumns.map(col => col.key),
      ...traceMetrics.map(tm => tm.key),
    ];

    wrapper.style.display = '';

    if (metricOptions.length === 0) {
      btn.disabled = true;
      btn.textContent = 'Columns';
      btn.classList.remove('has-selection');
      btn.title = 'Columns will appear when metrics are available';
      dropdown.classList.remove('open');
      dropdown.innerHTML = '';
      return;
    }
    btn.disabled = false;
    btn.title = 'Choose which columns to show';

    const visibleMetrics = new Set(getVisibleMetrics(metricOptions));
    const allVisible = visibleMetrics.size === metricOptions.length;
    const searchValue = dropdown.querySelector('.model-search-input')?.value || '';
    dropdown.innerHTML =
      '<div class="ms-actions">' +
        '<button class="ms-action-btn" id="mv-select-all">All</button>' +
        '<button class="ms-action-btn" id="mv-select-none">None</button>' +
      '</div>' +
      '<div class="model-search-box"><input type="text" class="model-search-input" placeholder="Search columns..." value="' + escapeHtml(searchValue) + '" /></div>' +
      availableMetrics.map(m => {
        const checked = allVisible || visibleMetrics.has(m) ? 'checked' : '';
        const hidden = searchValue && !getMetricDisplayName(m).toLowerCase().includes(searchValue.toLowerCase()) ? ' style="display:none"' : '';
        return `<div class="multi-select-option"${hidden}><input type="checkbox" ${checked} data-mv-metric="${escapeHtml(m)}" /><span>${escapeHtml(m)}</span></div>`;
      }).join('') +
      (groupColumns.length > 0 ?
        '<div class="mv-trace-separator"></div><div class="mv-trace-label">Grouped Run Columns</div>' +
        groupColumns.map(col => {
          const checked = allVisible || visibleMetrics.has(col.key) ? 'checked' : '';
          const hidden = searchValue && !col.label.toLowerCase().includes(searchValue.toLowerCase()) ? ' style="display:none"' : '';
          return `<div class="multi-select-option"${hidden}><input type="checkbox" ${checked} data-mv-metric="${escapeHtml(col.key)}" /><span>${escapeHtml(col.label)}</span></div>`;
        }).join('') : '') +
      (systemColumns.length > 0 ?
        '<div class="mv-trace-separator"></div><div class="mv-trace-label">⚡ System Columns</div>' +
        systemColumns.map(col => {
          const checked = allVisible || visibleMetrics.has(col.key) ? 'checked' : '';
          const hidden = searchValue && !col.label.toLowerCase().includes(searchValue.toLowerCase()) ? ' style="display:none"' : '';
          return `<div class="multi-select-option"${hidden}><input type="checkbox" ${checked} data-mv-metric="${escapeHtml(col.key)}" /><span>${escapeHtml(col.label)}</span></div>`;
        }).join('') : '') +
      (traceMetrics.length > 0 ?
        '<div class="mv-trace-separator"></div><div class="mv-trace-label">⚡ Trace Stats</div>' +
        traceMetrics.map(tm => {
          const checked = allVisible || visibleMetrics.has(tm.key) ? 'checked' : '';
          const hidden = searchValue && !tm.label.toLowerCase().includes(searchValue.toLowerCase()) ? ' style="display:none"' : '';
          return `<div class="multi-select-option"${hidden}><input type="checkbox" ${checked} data-mv-metric="${escapeHtml(tm.key)}" /><span>${escapeHtml(tm.label)}</span></div>`;
        }).join('') : '');

    // Update button text
    updateMetricVisibilityBtn(metricOptions);

    // Wire search input for metrics
    const mvSearchInput = dropdown.querySelector('.model-search-input');
    if (mvSearchInput) {
      mvSearchInput.addEventListener('input', (e) => {
        const q = e.target.value.toLowerCase();
        dropdown.querySelectorAll('.multi-select-option').forEach(opt => {
          const metricCb = opt.querySelector('input[data-mv-metric]');
          if (!metricCb) return;
          const m = metricCb.dataset.mvMetric || '';
          opt.style.display = getMetricDisplayName(m).toLowerCase().includes(q) ? '' : 'none';
        });
      });
      mvSearchInput.addEventListener('click', (e) => e.stopPropagation());
      mvSearchInput.addEventListener('keydown', (e) => e.stopPropagation());
    }

    dropdown.querySelectorAll('input[type="checkbox"]').forEach(cb => {
      cb.addEventListener('change', () => {
        applyMetricVisibilityFromCheckboxes(metricOptions);
      });
    });

    dropdown.querySelectorAll('.multi-select-option').forEach(opt => {
      const metricCb = opt.querySelector('input[data-mv-metric]');
      if (!metricCb) return;
      opt.addEventListener('click', (e) => {
        e.stopPropagation();
        metricCb.checked = !metricCb.checked;
        applyMetricVisibilityFromCheckboxes(metricOptions);
      });
    });

    const selAll = dropdown.querySelector('#mv-select-all');
    const selNone = dropdown.querySelector('#mv-select-none');
    if (selAll) selAll.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      setVisibleMetricsForAvailable(metricOptions, new Set(metricOptions));
      saveMetricVisibility();
      syncMetricVisibilityDropdownState(metricOptions);
      render();
    });
    if (selNone) selNone.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      setVisibleMetricsForAvailable(metricOptions, new Set());
      saveMetricVisibility();
      syncMetricVisibilityDropdownState(metricOptions);
      render();
    });
  }

  function syncMetricVisibilityDropdownState(availableMetrics = _allMetricsWithTrace()) {
    const dropdown = el('metric-visibility-dropdown');
    if (!dropdown) return;

    const visibleMetrics = new Set(getVisibleMetrics(availableMetrics));
    const allVisible = visibleMetrics.size === availableMetrics.length;
    dropdown.querySelectorAll('input[data-mv-metric]').forEach(cb => {
      cb.checked = allVisible || visibleMetrics.has(cb.dataset.mvMetric);
    });
    updateMetricVisibilityBtn(availableMetrics);
  }

  function updateMetricVisibilityBtn(availableMetrics = _allMetricsWithTrace()) {
    const btn = el('metric-visibility-btn');
    if (!btn) return;
    const visibleMetrics = getVisibleMetrics(availableMetrics);
    if (availableMetrics.length === 0) {
      btn.textContent = 'Columns';
      btn.classList.remove('has-selection');
    } else if (visibleMetrics.length === availableMetrics.length) {
      btn.textContent = 'Columns';
      btn.classList.remove('has-selection');
    } else if (visibleMetrics.length === 0) {
      btn.textContent = 'No Columns';
      btn.classList.add('has-selection');
    } else if (visibleMetrics.length === 1) {
      btn.textContent = getMetricDisplayName(visibleMetrics[0]);
      btn.classList.add('has-selection');
    } else {
      btn.textContent = visibleMetrics.length + ' Columns';
      btn.classList.add('has-selection');
    }
  }

  function applyMetricVisibilityFromCheckboxes(availableMetrics = _allMetricsWithTrace()) {
    const dropdown = el('metric-visibility-dropdown');
    if (!dropdown) return;
    const checked = new Set();
    dropdown.querySelectorAll('input[data-mv-metric]').forEach(cb => {
      if (cb.checked) checked.add(cb.dataset.mvMetric);
    });
    setVisibleMetricsForAvailable(availableMetrics, checked);
    saveMetricVisibility();
    syncMetricVisibilityDropdownState(availableMetrics);
    render();
  }

  // ═══════════════════════════════════════════════════
  // MODELS VIEW STAT VISIBILITY
  // ═══════════════════════════════════════════════════

  function getModelsViewStatOptions(runs = null) {
    const mvs = state.modelsViewState;
    if (!mvs.selectedMetric) return [];

    const baseKeys = mvs.metricIsNumeric ? MODELS_VIEW_NUMERIC_STAT_KEYS : MODELS_VIEW_SCORE_STAT_KEYS;
    const K = Math.max(0, Number(mvs.globalK) || 0);
    const traceMetrics = Array.isArray(runs) ? _traceMetricsForRuns(runs) : (mvs.visibleTraceMetrics || []);

    const baseOptions = baseKeys.map((key) => {
      switch (key) {
        case 'passAtK':
          return { key, label: `Pass@${K}` };
        case 'passHatK':
          return { key, label: `Pass^${K}` };
        case 'maxAtK':
          return { key, label: `Max@${K}` };
        case 'consistency':
          return { key, label: 'Consistency' };
        case 'reliability':
          return { key, label: 'Reliability' };
        case 'avgScore':
          return { key, label: mvs.metricIsNumeric ? 'Avg' : 'Avg Score' };
        case 'failedCount':
          return { key, label: 'Errors' };
        case 'totalRetries':
          return { key, label: 'Retries' };
        case 'avgLatency':
          return { key, label: 'Avg Latency' };
        case 'medianLatency':
          return { key, label: 'Median Latency' };
        case 'correctDistribution':
          return { key, label: 'Correct Distribution' };
        case 'minScore':
          return { key, label: 'Min' };
        case 'stddevScore':
          return { key, label: 'StdDev' };
        case 'totalScoreSum':
          return { key, label: 'Total' };
        default:
          return { key, label: key };
      }
    });

    const traceOptions = traceMetrics.map((traceMetric) => ({
      key: `trace:${traceMetric.key}`,
      label: traceMetric.modelsLabel || traceMetric.label,
    }));

    return [...baseOptions, ...traceOptions];
  }

  function getAllModelsViewStatKeys() {
    return Array.from(new Set([
      ...MODELS_VIEW_SCORE_STAT_KEYS,
      ...MODELS_VIEW_NUMERIC_STAT_KEYS,
      ...TRACE_METRICS.map(metric => `trace:${metric.key}`),
    ]));
  }

  function getVisibleModelsViewStatKeys(availableOptions) {
    const visible = state.modelsViewState.visibleStatKeys;
    const availableKeys = (availableOptions || []).map(option => option.key);
    if (visible === null) return availableKeys;
    if (!Array.isArray(visible)) return availableKeys;
    return availableKeys.filter(key => visible.includes(key));
  }

  function setVisibleModelsViewStatsForAvailable(availableOptions, checkedKeys) {
    const availableKeys = (availableOptions || []).map(option => option.key);
    const knownKeys = getAllModelsViewStatKeys();
    const selectedKeys = Array.from(checkedKeys || []);
    const currentVisible = Array.isArray(state.modelsViewState.visibleStatKeys)
      ? state.modelsViewState.visibleStatKeys
      : null;
    const preserved = currentVisible === null
      ? knownKeys.filter(key => !availableKeys.includes(key))
      : currentVisible.filter(key => !availableKeys.includes(key));
    const merged = Array.from(new Set([...preserved, ...selectedKeys]));
    state.modelsViewState.visibleStatKeys = merged.length === knownKeys.length ? null : merged;
  }

  function updateModelsStatVisibilityBtn(availableOptions) {
    const wrapper = el('models-stat-visibility-wrapper');
    const btn = el('models-stat-visibility-btn');
    if (!wrapper || !btn) return;

    if (!availableOptions || availableOptions.length === 0) {
      wrapper.style.display = 'none';
      return;
    }

    wrapper.style.display = '';
    const visibleKeys = getVisibleModelsViewStatKeys(availableOptions);
    if (visibleKeys.length === availableOptions.length) {
      btn.textContent = 'Shown Metrics';
      btn.classList.remove('has-selection');
    } else if (visibleKeys.length === 0) {
      btn.textContent = 'No Metrics';
      btn.classList.add('has-selection');
    } else if (visibleKeys.length === 1) {
      const only = availableOptions.find(option => option.key === visibleKeys[0]);
      btn.textContent = only ? only.label : '1 Metric';
      btn.classList.add('has-selection');
    } else {
      btn.textContent = `${visibleKeys.length} Metrics`;
      btn.classList.add('has-selection');
    }
  }

  function syncModelsStatVisibilityDropdownState(availableOptions) {
    const dropdown = el('models-stat-visibility-dropdown');
    if (!dropdown) return;

    const visibleKeys = new Set(getVisibleModelsViewStatKeys(availableOptions));
    const allVisible = visibleKeys.size === (availableOptions || []).length;
    dropdown.querySelectorAll('input[data-model-stat-key]').forEach(cb => {
      cb.checked = allVisible || visibleKeys.has(cb.dataset.modelStatKey);
    });
    updateModelsStatVisibilityBtn(availableOptions);
  }

  function applyModelsStatVisibilityFromCheckboxes(availableOptions) {
    const dropdown = el('models-stat-visibility-dropdown');
    if (!dropdown) return;

    const checkedKeys = new Set();
    dropdown.querySelectorAll('input[data-model-stat-key]').forEach(cb => {
      if (cb.checked) checkedKeys.add(cb.dataset.modelStatKey);
    });

    setVisibleModelsViewStatsForAvailable(availableOptions, checkedKeys);
    syncModelsStatVisibilityDropdownState(availableOptions);
    renderModelsView();
  }

  function populateModelsStatVisibility(runs = null) {
    const wrapper = el('models-stat-visibility-wrapper');
    const dropdown = el('models-stat-visibility-dropdown');
    if (!wrapper || !dropdown) return;

    const options = getModelsViewStatOptions(runs);
    if (options.length === 0) {
      wrapper.style.display = 'none';
      dropdown.classList.remove('open');
      dropdown.innerHTML = '';
      return;
    }

    wrapper.style.display = '';
    const visibleKeys = new Set(getVisibleModelsViewStatKeys(options));
    const allVisible = visibleKeys.size === options.length;
    const searchValue = dropdown.querySelector('.model-search-input')?.value || '';

    dropdown.innerHTML =
      '<div class="ms-actions">' +
        '<button class="ms-action-btn" id="models-stat-select-all">All</button>' +
        '<button class="ms-action-btn" id="models-stat-select-none">None</button>' +
      '</div>' +
      '<div class="model-search-box"><input type="text" class="model-search-input" placeholder="Search shown metrics..." value="' + escapeHtml(searchValue) + '" /></div>' +
      options.map((option) => {
        const checked = allVisible || visibleKeys.has(option.key) ? 'checked' : '';
        const hidden = searchValue && !option.label.toLowerCase().includes(searchValue.toLowerCase()) ? ' style="display:none"' : '';
        return `<div class="multi-select-option"${hidden}><input type="checkbox" ${checked} data-model-stat-key="${escapeHtml(option.key)}" /><span>${escapeHtml(option.label)}</span></div>`;
      }).join('');

    updateModelsStatVisibilityBtn(options);

    const searchInput = dropdown.querySelector('.model-search-input');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        const q = e.target.value.toLowerCase();
        dropdown.querySelectorAll('.multi-select-option').forEach((opt) => {
          const statCb = opt.querySelector('input[data-model-stat-key]');
          if (!statCb) return;
          const option = options.find(item => item.key === statCb.dataset.modelStatKey);
          const label = option ? option.label : statCb.dataset.modelStatKey;
          opt.style.display = label.toLowerCase().includes(q) ? '' : 'none';
        });
      });
      searchInput.addEventListener('click', (e) => e.stopPropagation());
      searchInput.addEventListener('keydown', (e) => e.stopPropagation());
    }

    dropdown.querySelectorAll('input[data-model-stat-key]').forEach(cb => {
      cb.addEventListener('change', () => {
        applyModelsStatVisibilityFromCheckboxes(options);
      });
    });

    dropdown.querySelectorAll('.multi-select-option').forEach(opt => {
      const statCb = opt.querySelector('input[data-model-stat-key]');
      if (!statCb) return;
      opt.addEventListener('click', (e) => {
        e.stopPropagation();
        statCb.checked = !statCb.checked;
        applyModelsStatVisibilityFromCheckboxes(options);
      });
    });

    const selectAllBtn = dropdown.querySelector('#models-stat-select-all');
    const selectNoneBtn = dropdown.querySelector('#models-stat-select-none');
    if (selectAllBtn) selectAllBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      setVisibleModelsViewStatsForAvailable(options, new Set(options.map(option => option.key)));
      syncModelsStatVisibilityDropdownState(options);
      renderModelsView();
    });
    if (selectNoneBtn) selectNoneBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      setVisibleModelsViewStatsForAvailable(options, new Set());
      syncModelsStatVisibilityDropdownState(options);
      renderModelsView();
    });
  }

  // ═══════════════════════════════════════════════════
  // DATA PROCESSING
  // ═══════════════════════════════════════════════════

  function flattenRuns(data) {
    const runs = [];
    const metricsSet = new Set();
    if (!data || !data.tasks) return { runs, metrics: [] };
    for (const [taskName, models] of Object.entries(data.tasks)) {
      for (const [modelName, runList] of Object.entries(models)) {
        for (const run of runList) {
          const totalItems = Number(run.total_items || 0);
          const successCount = Number(run.success_count || 0);
          const errorCount = Number(run.error_count || 0);
          const completedCount = successCount + errorCount;
          const completionRate = totalItems > 0 ? (completedCount / totalItems) : 0;
          const successOnCompletedRate = completedCount > 0 ? (successCount / completedCount) : null;

          // Collect all unique metrics
          if (run.metrics) {
            run.metrics.forEach(m => metricsSet.add(m));
          }
          // Model name is already stripped of provider in backend
          runs.push({
            ...run,
            task_name: taskName,
            model_name: run.model_name || modelName,
            raw_model_name: run.model_name || modelName,
            model_has_reasoning: hasReasoningTraceStats(run.trace_stats),
            model_key: getModelVariantKey(run.model_name || modelName, hasReasoningTraceStats(run.trace_stats)),
            // Some views/filters rely on this precomputed display value.
            display_model: stripModelProvider(run.model_name || modelName || ''),
            completion_rate: completionRate,
            success_on_completed_rate: successOnCompletedRate,
            total_retries: Number(run.total_retries || 0),
            _date: new Date(run.timestamp),
          });
        }
      }
    }
    // Detect metric types from averages across all runs
    const metricTypes = {};
    for (const metric of metricsSet) {
      let detectedNumeric = false;
      for (const run of runs) {
        const avg = run.metric_averages?.[metric];
        if (avg !== undefined && avg !== null && (avg > 1 || avg < 0)) {
          detectedNumeric = true;
          break;
        }
      }
      metricTypes[metric] = detectedNumeric ? 'numeric' : 'score';
    }

    return { runs, metrics: Array.from(metricsSet).sort(), metricTypes };
  }

  function computeAggregations(runs) {
    const agg = {
      totalRuns: runs.length,
      totalTasks: new Set(runs.map(r => r.task_name)).size,
      totalModels: new Set(runs.map(r => getRunModelKey(r))).size,
      totalItems: runs.reduce((sum, r) => sum + (r.total_items || 0), 0),
      avgSuccess: runs.length ? runs.reduce((sum, r) => sum + (r.success_rate || 0), 0) / runs.length : 0,
      byModel: {},
      byTask: {},
      byDay: {},
    };

    // Aggregate by model
    for (const run of runs) {
      const model = getRunModelKey(run);
      if (!agg.byModel[model]) {
        agg.byModel[model] = { runs: 0, items: 0, successSum: 0 };
      }
      agg.byModel[model].runs++;
      agg.byModel[model].items += run.total_items || 0;
      agg.byModel[model].successSum += run.success_rate || 0;
    }
    for (const m of Object.keys(agg.byModel)) {
      agg.byModel[m].avgSuccess = agg.byModel[m].successSum / agg.byModel[m].runs;
    }

    // Aggregate by task
    for (const run of runs) {
      const task = run.task_name;
      if (!agg.byTask[task]) {
        agg.byTask[task] = { runs: 0, items: 0, successSum: 0 };
      }
      agg.byTask[task].runs++;
      agg.byTask[task].items += run.total_items || 0;
      agg.byTask[task].successSum += run.success_rate || 0;
    }
    for (const t of Object.keys(agg.byTask)) {
      agg.byTask[t].avgSuccess = agg.byTask[t].successSum / agg.byTask[t].runs;
    }

    // Aggregate by day (last 7 days)
    const today = new Date();
    for (let i = 6; i >= 0; i--) {
      const d = new Date(today);
      d.setDate(d.getDate() - i);
      const key = d.toISOString().split('T')[0];
      agg.byDay[key] = { runs: 0, successSum: 0 };
    }
    for (const run of runs) {
      const key = run._date.toISOString().split('T')[0];
      if (agg.byDay[key]) {
        agg.byDay[key].runs++;
        agg.byDay[key].successSum += run.success_rate || 0;
      }
    }

    return agg;
  }

  function computeChartData(runs) {
    // Group runs by task+dataset combination
    const combos = {};
    const allModels = new Set();
    const allMetrics = new Set();

    for (const run of runs) {
      const key = `${run.task_name}|||${run.dataset_name}`;
      if (!combos[key]) {
        combos[key] = {
          task: run.task_name,
          dataset: run.dataset_name,
          models: {},
          metrics: new Set(),
          totalRuns: 0,
        };
      }

      const model = getRunModelKey(run);
      allModels.add(model);

      // Track metrics for this combo
      if (run.metrics) {
        run.metrics.forEach(m => {
          combos[key].metrics.add(m);
          allMetrics.add(m);
        });
      }

      if (!combos[key].models[model]) {
        combos[key].models[model] = {
          runs: 0,
          runsList: [],  // Store individual run data
          totalItems: 0,
          latestTimestamp: null,
          metricSums: {},
          metricCounts: {},
          latencySum: 0,
          latencyCount: 0,
          medianLatencyValues: [],
        };
      }

      // Store individual run data for display
      combos[key].models[model].runsList.push({
        run_id: run.run_id,
        run_name: run.run_name || '',
        external_run_id: run.external_run_id,
        file_path: run.file_path,
        timestamp: run.timestamp,
        metric_averages: run.metric_averages || {},
        trace_stats: run.trace_stats || null,
        avg_latency_ms: run.avg_latency_ms,
        median_latency_ms: run.median_latency_ms,
        total_items: run.total_items,
        git_branch: run.git_branch || '',
        git_commit: run.git_commit || '',
        raw_model_name: run.raw_model_name || run.model_name || modelName,
        model_has_reasoning: run.model_has_reasoning != null ? !!run.model_has_reasoning : runHasReasoning(run),
      });

      combos[key].models[model].runs++;
      combos[key].models[model].totalItems += run.total_items || 0;
      combos[key].totalRuns++;

      // Accumulate metric averages
      if (run.metric_averages) {
        for (const [metric, value] of Object.entries(run.metric_averages)) {
          if (!combos[key].models[model].metricSums[metric]) {
            combos[key].models[model].metricSums[metric] = 0;
            combos[key].models[model].metricCounts[metric] = 0;
          }
          combos[key].models[model].metricSums[metric] += value;
          combos[key].models[model].metricCounts[metric]++;
        }
      }

      // Accumulate latency
      if (run.avg_latency_ms) {
        combos[key].models[model].latencySum += run.avg_latency_ms;
        combos[key].models[model].latencyCount++;
      }
      if (run.median_latency_ms) {
        combos[key].models[model].medianLatencyValues.push(run.median_latency_ms);
      }

      // Track latest run
      const ts = new Date(run.timestamp);
      if (!combos[key].models[model].latestTimestamp || ts > combos[key].models[model].latestTimestamp) {
        combos[key].models[model].latestTimestamp = ts;
      }
    }

    // Calculate metric averages and avg latency per model
    for (const key of Object.keys(combos)) {
      combos[key].metrics = Array.from(combos[key].metrics);
      for (const model of Object.keys(combos[key].models)) {
        const m = combos[key].models[model];
        m.metricAverages = {};
        for (const [metric, sum] of Object.entries(m.metricSums)) {
          const count = m.metricCounts[metric] || 1;
          m.metricAverages[metric] = sum / count;
        }
        m.avgLatencyMs = m.latencyCount > 0 ? m.latencySum / m.latencyCount : 0;
        m.medianLatencyMs = m.medianLatencyValues.length > 0
          ? window.QymMetrics.calculateMedian(m.medianLatencyValues)
          : 0;
      }
    }

    // Sort combos by total runs (most active first)
    const sortedCombos = Object.values(combos).sort((a, b) => b.totalRuns - a.totalRuns);

    // Create stable model ordering based on overall frequency
    const modelFreq = {};
    for (const combo of sortedCombos) {
      for (const model of Object.keys(combo.models)) {
        modelFreq[model] = (modelFreq[model] || 0) + combo.models[model].runs;
      }
    }
    const sortedModels = Object.keys(modelFreq).sort((a, b) => {
      const freqCmp = modelFreq[b] - modelFreq[a];
      return freqCmp !== 0 ? freqCmp : compareModelVariantKeys(a, b);
    });

    // Group combos by task for dataset-tab cards
    const taskGroupsMap = {};
    for (const combo of sortedCombos) {
      if (!taskGroupsMap[combo.task]) {
        taskGroupsMap[combo.task] = { task: combo.task, datasets: [] };
      }
      taskGroupsMap[combo.task].datasets.push(combo);
    }
    const tasks = Object.values(taskGroupsMap).sort(
      (a, b) => b.datasets.reduce((s, d) => s + d.totalRuns, 0) - a.datasets.reduce((s, d) => s + d.totalRuns, 0)
    );

    return {
      combos: sortedCombos,
      tasks,
      models: sortedModels,
      metrics: Array.from(allMetrics),
      modelIndex: Object.fromEntries(sortedModels.map((m, i) => [m, i])),
    };
  }

  function filterRuns() {
    let runs = [...state.flatRuns];

    // Quick filter (time-based)
    switch (state.quickFilter) {
      case 'today':
        runs = runs.filter(r => isToday(r.timestamp));
        break;
      case 'week':
        runs = runs.filter(r => isWithinDays(r.timestamp, 7));
        break;
    }

    // Dropdown filters
    if (state.filterTasks.size > 0 && !state.filterTasks.has('__none__')) {
      runs = runs.filter(r => matchesFilterSelection(state.filterTasks, r.task_name));
    } else if (state.filterTasks.has('__none__')) {
      runs = [];
    }
    if (state.filterModels.size > 0) {
      if (state.filterModels.has('__none__')) {
        runs = [];
      } else {
        runs = runs.filter(r => matchesFilterSelection(state.filterModels, getRunModelKey(r)));
      }
    }
    if (state.filterDatasets.size > 0 && !state.filterDatasets.has('__none__')) {
      runs = runs.filter(r => matchesFilterSelection(state.filterDatasets, getRunDatasetKey(r)));
    } else if (state.filterDatasets.has('__none__')) {
      runs = [];
    }
    if (state.filterStatuses.size > 0 && !state.filterStatuses.has('__none__')) {
      runs = runs.filter(r => matchesFilterSelection(state.filterStatuses, r.status));
    } else if (state.filterStatuses.has('__none__')) {
      runs = [];
    }
    if (state.filterVersions.size > 0 && !state.filterVersions.has('__none__')) {
      runs = runs.filter(r => matchesFilterSelection(state.filterVersions, getRunVersionKey(r)));
    } else if (state.filterVersions.has('__none__')) {
      runs = [];
    }
    if (state.filterUsers.size > 0 && !state.filterUsers.has('__none__')) {
      runs = runs.filter(r => matchesFilterSelection(state.filterUsers, getRunOwnerKey(r)));
    } else if (state.filterUsers.has('__none__')) {
      runs = [];
    }

    // Sort
    sortRuns(runs);

    state.filteredRuns = runs;
    return runs;
  }

  function sortRuns(runs) {
    switch (state.sortKey) {
      case 'time-desc':
      case 'date-desc':
        runs.sort((a, b) => b._date - a._date);
        break;
      case 'time-asc':
      case 'date-asc':
        runs.sort((a, b) => a._date - b._date);
        break;
      case 'success-desc':
        runs.sort((a, b) => {
          const aVal = a.success_on_completed_rate ?? -1;
          const bVal = b.success_on_completed_rate ?? -1;
          return bVal - aVal;
        });
        break;
      case 'success-asc':
        runs.sort((a, b) => {
          const aVal = a.success_on_completed_rate ?? -1;
          const bVal = b.success_on_completed_rate ?? -1;
          return aVal - bVal;
        });
        break;
      case 'items-desc':
        runs.sort((a, b) => b.total_items - a.total_items);
        break;
      case 'items-asc':
        runs.sort((a, b) => a.total_items - b.total_items);
        break;
      case 'task-asc':
        runs.sort((a, b) => a.task_name.localeCompare(b.task_name));
        break;
      case 'task-desc':
        runs.sort((a, b) => b.task_name.localeCompare(a.task_name));
        break;
      case 'model-asc':
        runs.sort((a, b) => compareModelVariantKeys(getRunModelKey(a), getRunModelKey(b)));
        break;
      case 'model-desc':
        runs.sort((a, b) => compareModelVariantKeys(getRunModelKey(b), getRunModelKey(a)));
        break;
      case 'dataset-asc':
        runs.sort((a, b) => a.dataset_name.localeCompare(b.dataset_name));
        break;
      case 'dataset-desc':
        runs.sort((a, b) => b.dataset_name.localeCompare(a.dataset_name));
        break;
      case 'version-asc':
        runs.sort((a, b) => (a.git_commit || '').localeCompare(b.git_commit || ''));
        break;
      case 'version-desc':
        runs.sort((a, b) => (b.git_commit || '').localeCompare(a.git_commit || ''));
        break;
      case 'owner-asc':
        runs.sort((a, b) => (a.owner?.display_name || '').localeCompare(b.owner?.display_name || ''));
        break;
      case 'owner-desc':
        runs.sort((a, b) => (b.owner?.display_name || '').localeCompare(a.owner?.display_name || ''));
        break;
      case 'status-asc':
        runs.sort((a, b) => a.error_count - b.error_count);
        break;
      case 'status-desc':
        runs.sort((a, b) => b.error_count - a.error_count);
        break;
      case 'run-asc':
        runs.sort((a, b) => a.run_id.localeCompare(b.run_id));
        break;
      case 'run-desc':
        runs.sort((a, b) => b.run_id.localeCompare(a.run_id));
        break;
      case 'latency-desc':
        runs.sort((a, b) => (b.avg_latency_ms || 0) - (a.avg_latency_ms || 0));
        break;
      case 'latency-asc':
        runs.sort((a, b) => (a.avg_latency_ms || 0) - (b.avg_latency_ms || 0));
        break;
      case 'median-latency-desc':
        runs.sort((a, b) => (b.median_latency_ms || 0) - (a.median_latency_ms || 0));
        break;
      case 'median-latency-asc':
        runs.sort((a, b) => (a.median_latency_ms || 0) - (b.median_latency_ms || 0));
        break;
      case 'duration-desc':
        runs.sort((a, b) => (b.duration_ms || 0) - (a.duration_ms || 0));
        break;
      case 'duration-asc':
        runs.sort((a, b) => (a.duration_ms || 0) - (b.duration_ms || 0));
        break;
      default:
        // Handle metric column sorting (e.g., "metric-exact_match-desc")
        if (state.sortKey.startsWith('trace-')) {
          const parts = state.sortKey.split('-');
          const traceKey = parts.slice(1, -1).join('-');
          const direction = parts[parts.length - 1];
          runs.sort((a, b) => {
            const aVal = a.trace_stats?.[traceKey] ?? -1;
            const bVal = b.trace_stats?.[traceKey] ?? -1;
            return direction === 'desc' ? bVal - aVal : aVal - bVal;
          });
        } else if (state.sortKey.startsWith('metric-')) {
          const parts = state.sortKey.split('-');
          const metricName = parts.slice(1, -1).join('-');
          const direction = parts[parts.length - 1];
          runs.sort((a, b) => {
            const aVal = a.metric_averages?.[metricName] ?? -1;
            const bVal = b.metric_averages?.[metricName] ?? -1;
            return direction === 'desc' ? bVal - aVal : aVal - bVal;
          });
        }
        break;
    }
  }

  // ═══════════════════════════════════════════════════
  // RENDERING: STATS BAR
  // ═══════════════════════════════════════════════════

  function renderStatsBar() {
    const agg = state.aggregations;
    if (!agg) return;

    // Push stats to the shell topbar
    if (window.QymShell) {
      window.QymShell.setTopbarStats([
        { label: 'runs', value: formatNumber(agg.totalRuns), color: 'var(--accent-primary)' },
        { label: 'success', value: formatPercent(agg.avgSuccess), color: 'var(--success)' },
        { label: 'models', value: formatNumber(agg.totalModels), color: 'var(--accent-secondary)' },
        { label: 'items', value: formatNumber(agg.totalItems), color: 'var(--accent-tertiary)' },
      ]);
    }
  }

  function isLatencyLikeMetric(metricName) {
    return /(^|[_\s-])latency([_\s-]|$)/i.test(String(metricName || ''));
  }

  function isTokenLikeMetric(metricName) {
    return /(^|[_\s-])(token|tokens|usage)([_\s-]|$)/i.test(String(metricName || ''));
  }

  function prefersBarChartMetric(metricName, metricType) {
    if (metricType !== 'numeric') return true;
    return isLatencyLikeMetric(metricName) || isTokenLikeMetric(metricName);
  }

  function orderChartMetrics(metrics) {
    return metrics
      .map((metric, index) => ({ metric, index }))
      .sort((a, b) => {
        const aType = state._metricTypes?.[a.metric] || 'score';
        const bType = state._metricTypes?.[b.metric] || 'score';
        const aPriority = prefersBarChartMetric(a.metric, aType) ? 0 : 1;
        const bPriority = prefersBarChartMetric(b.metric, bType) ? 0 : 1;
        if (aPriority !== bPriority) return aPriority - bPriority;
        return a.index - b.index;
      })
      .map(entry => entry.metric);
  }

  function renderMiniBarCell({ value, label, ratio, modelIdx, isAggregate = false, cellClass = 'chart-metric-cell', title = '' }) {
    const safeRatio = Number.isFinite(ratio) ? Math.max(0, Math.min(ratio, 1)) : 0;
    const width = value === null || value === undefined ? 0 : Math.max(safeRatio * 100, 2);
    const aggregateClass = isAggregate && !Number.isInteger(modelIdx) ? ' aggregate' : '';
    const modelAttr = Number.isInteger(modelIdx) ? ` data-model-idx="${modelIdx}"` : '';
    const titleAttr = title ? ` title="${title}"` : '';
    return `
      <div class="${cellClass}"${titleAttr}>
        <div class="chart-mini-bar-track">
          <div class="chart-mini-bar-fill${aggregateClass}"${modelAttr} style="width:${width}%">
            <span class="chart-mini-bar-label">${label}</span>
          </div>
        </div>
      </div>
    `;
  }

  function getChartGroupExpansionEntry(cardId, mode) {
    if (!state.chartGroupExpansion) state.chartGroupExpansion = {};
    const existing = state.chartGroupExpansion[cardId];
    if (!existing || existing.mode !== mode) {
      state.chartGroupExpansion[cardId] = { mode, expanded: {} };
    }
    return state.chartGroupExpansion[cardId];
  }

  function isChartGroupCollapsed(cardId, mode, groupId) {
    const entry = getChartGroupExpansionEntry(cardId, mode);
    return entry.expanded[groupId] !== true;
  }

  function setChartGroupCollapsed(cardId, mode, groupId, collapsed) {
    const entry = getChartGroupExpansionEntry(cardId, mode);
    entry.expanded[groupId] = !collapsed;
  }

  // ═══════════════════════════════════════════════════
  // RENDERING: CHARTS VIEW
  // ═══════════════════════════════════════════════════

  function renderChartsView() {
    const chartData = state.chartData;
    const visibleSystemColumns = _visibleSystemColumns();
    
    // Update subtitle with filter info
    const subtitleEl = $('.charts-subtitle');
    if (subtitleEl) {
      const isFiltered = state.quickFilter !== 'all' || state.filterStatuses.size > 0 || state.filterVersions.size > 0;
      if (isFiltered) {
        subtitleEl.textContent = `Filtered: ${state.filteredRuns.length} runs • Showing average metric scores across all items`;
      } else {
        subtitleEl.textContent = `Showing average metric scores across all items in matching runs`;
      }
    }

    if (!chartData || chartData.combos.length === 0) {
      el('charts-grid').innerHTML = `
        <div class="chart-no-data" style="grid-column: 1/-1;">
          ${state.quickFilter !== 'all' || state.filterStatuses.size > 0 || state.filterVersions.size > 0
            ? 'No runs match current filters'
            : 'No data available for charts. Run some evaluations first.'}
        </div>
      `;
      el('charts-legend').innerHTML = '';
      return;
    }

    // Render legend (models) - interactive toggle
    const legendEl = el('charts-legend');
    legendEl.innerHTML = state.allModels.map((model, idx) => {
      const isActive = state.filterModels.size === 0 || state.filterModels.has(model);
      return `
        <div class="legend-item ${isActive ? '' : 'inactive'}" data-model="${model}" title="${getModelFilterOptionLabel(model)}">
          <span class="legend-color" style="background:${CHART_COLORS[idx % CHART_COLORS.length]}"></span>
          ${renderModelLabelForModelName(model)}
        </div>
      `;
    }).join('');

    // Wire legend click events
    legendEl.querySelectorAll('.legend-item').forEach(item => {
      const model = item.dataset.model;

      // Single click - toggle this model
      item.addEventListener('click', (e) => {
        e.preventDefault();
        toggleModelFilter(model);
      });

      // Double click - select only this model
      item.addEventListener('dblclick', (e) => {
        e.preventDefault();
        selectOnlyModel(model);
      });
    });

    // Render chart cards - one per task, with dataset tabs
    const gridEl = el('charts-grid');
    gridEl.innerHTML = (chartData.tasks || []).map(taskGroup => {
      const taskName = taskGroup.task;
      const datasets = taskGroup.datasets;
      const totalTaskRuns = datasets.reduce((s, d) => s + d.totalRuns, 0);
      const allTaskModels = new Set();
      datasets.forEach(d => Object.keys(d.models).forEach(m => allTaskModels.add(m)));

      // Determine active dataset tab
      const activeDataset = state.chartDatasetTab[taskName] || datasets[0]?.dataset || '';
      const combo = datasets.find(d => d.dataset === activeDataset) || datasets[0];
      if (!combo) return '';

      // Dataset tabs HTML
      const datasetTabsHtml = `
        <div class="chart-dataset-tabs">
          ${datasets.map(d => `
            <div class="chart-dataset-tab ${d.dataset === combo.dataset ? 'active' : ''}" data-task="${taskName}" data-dataset="${d.dataset}">
              ${d.dataset} <span class="tab-count">${d.totalRuns}</span>
            </div>
          `).join('')}
        </div>
      `;

      const allComboMetrics = combo.metrics || [];
      const visSet = state.visibleMetrics;
      const metrics = orderChartMetrics(visSet ? allComboMetrics.filter(m => visSet.has(m)) : allComboMetrics);
      const modelEntries = Object.entries(combo.models);

      // Collect all runs across all models
      const allRuns = [];
      for (const [model, data] of modelEntries) {
        for (const run of data.runsList) {
          allRuns.push({
            model,
            run_id: run.run_id,
            run_name: run.run_name || '',
            external_run_id: run.external_run_id,
            file_path: run.file_path,
            timestamp: run.timestamp,
            metric_averages: run.metric_averages || {},
            trace_stats: run.trace_stats || null,
            latency: run.avg_latency_ms || 0,
            median_latency: run.median_latency_ms || 0,
            isMultiRun: data.runs > 1,
            git_branch: run.git_branch || '',
            git_commit: run.git_commit || '',
          });
        }
      }

      const visibleTraceMetrics = _visibleTraceMetrics(allRuns);
      const groupMetricName = allComboMetrics.find(metric => (state._metricTypes?.[metric] || 'score') !== 'numeric') || '';

      // Generate unique card ID for sorting state
      const cardId = getChartCardId(combo.task, combo.dataset);

      // Grouping mode: run (default) / version / model / version-model / model-version
      if (!state.chartGroupMode) state.chartGroupMode = {};
      const hasVersions = comboHasVersionData(combo);
      let groupMode = getEffectiveChartGroupMode(cardId, combo);
      if (groupMode !== (state.chartGroupMode[cardId] || 'run')) {
        groupMode = 'run';
        state.chartGroupMode[cardId] = groupMode;
      }
      const isGrouped = groupMode !== 'run';
      const visibleGroupStatColumns = isGrouped
        ? GROUP_DISPLAY_COLUMNS.filter(col => state.visibleMetrics === null || state.visibleMetrics.has(col.key))
        : [];
      const groupExpansion = state.chartGroupExpansion?.[cardId];
      const hasExpandedGroupState = isGrouped
        && groupExpansion
        && groupExpansion.mode === groupMode
        && Object.values(groupExpansion.expanded || {}).some(isExpanded => isExpanded === true);
      const showGroupStatColumns = isGrouped && visibleGroupStatColumns.length > 0 && !hasExpandedGroupState;

      if (metrics.length === 0 && visibleTraceMetrics.length === 0 && visibleSystemColumns.length === 0 && !showGroupStatColumns) {
        return `
          <div class="chart-task-section">
            <div class="chart-task-header">
              <span class="chart-task-name">${taskName}</span>
              <span class="chart-task-meta">${totalTaskRuns} runs \u00b7 ${allTaskModels.size} models</span>
            </div>
            <div class="chart-card">
              ${datasetTabsHtml}
              <div class="chart-card-body">
                <div class="chart-no-data">No metrics recorded</div>
              </div>
            </div>
          </div>
        `;
      }

      // Default sort by first metric descending
      if (!state.chartSortState) state.chartSortState = {};
      if (!state.chartSortState[cardId]) {
        state.chartSortState[cardId] = { key: metrics[0] || visibleTraceMetrics[0]?.key || 'latency', dir: 'desc' };
      }
      const sortState = state.chartSortState[cardId];

      function getChartSortDirection(key) {
        return key === 'model' ? 'asc' : 'desc';
      }

      function isGroupStatSortKey(key) {
        return key === GROUP_PASS_AT_K_COLUMN_KEY
          || key === GROUP_CONSISTENCY_COLUMN_KEY
          || key === GROUP_RELIABILITY_COLUMN_KEY;
      }

      function compareChartSortValues(aVal, bVal, dir) {
        const aMissing = aVal === undefined || aVal === null || aVal === '';
        const bMissing = bVal === undefined || bVal === null || bVal === '';
        if (aMissing || bMissing) {
          if (aMissing && bMissing) return 0;
          return aMissing ? 1 : -1;
        }
        if (typeof aVal === 'string' || typeof bVal === 'string') {
          const cmp = String(aVal).localeCompare(String(bVal), undefined, {
            numeric: true,
            sensitivity: 'base',
          });
          return dir === 'desc' ? -cmp : cmp;
        }
        return dir === 'desc' ? bVal - aVal : aVal - bVal;
      }

      function getRunSortValue(run, key) {
        if (key === 'model') return stripModelProvider(run.model || '');
        if (key === 'latency') return run.latency || 0;
        if (key === 'median-latency') return run.median_latency || 0;
        if (isTraceMetricKey(key)) return run.trace_stats?.[key] ?? -1;
        return run.metric_averages[key] ?? -1;
      }

      function getGroupSortValue(group, key) {
        if (key === 'model') return group.sortModel || group.label || '';
        const agg = group.agg || group;
        if (key === 'latency') return agg.avgLatency;
        if (key === 'median-latency') return agg.medianLatency;
        if (isGroupStatSortKey(key)) {
          const statsEntry = scheduleChartGroupMetricStats(
            group.runs || [],
            groupMetricName,
            getChartGroupMetricThreshold(group.runs || [], groupMetricName),
            isChartGroupMetricBoolean(group.runs || [], groupMetricName)
          );
          if (statsEntry?.status !== 'ready' || !statsEntry.stats) return -1;
          if (key === GROUP_PASS_AT_K_COLUMN_KEY) return statsEntry.stats.passAtK ?? -1;
          if (key === GROUP_CONSISTENCY_COLUMN_KEY) return statsEntry.stats.consistency ?? -1;
          if (key === GROUP_RELIABILITY_COLUMN_KEY) return statsEntry.stats.reliability ?? -1;
        }
        if (isTraceMetricKey(key)) return agg.traceAverages?.[key] ?? -1;
        return agg.metricAverages[key] ?? -1;
      }

      // Sort helper
      function sortByState(a, b) {
        const aVal = getRunSortValue(a, sortState.key);
        const bVal = getRunSortValue(b, sortState.key);
        const cmp = compareChartSortValues(aVal, bVal, sortState.dir);
        if (cmp !== 0) return cmp;
        if (sortState.key === 'model') {
          return compareChartSortValues(a.timestamp || '', b.timestamp || '', 'desc');
        }
        return 0;
      }

      if (allRuns.length === 0) return '';

      const visualMetrics = metrics.filter(metric => {
        const metricType = state._metricTypes?.[metric] || 'score';
        return prefersBarChartMetric(metric, metricType);
      });
      const numericMetrics = metrics.filter(metric => !visualMetrics.includes(metric));
      const AVG_LATENCY_COLUMN_KEY = '__latency_avg__';
      const MEDIAN_LATENCY_COLUMN_KEY = '__latency_median__';
      const traceMetricKeys = visibleTraceMetrics.map(tm => tm.key);
      const displayColumns = [
        ...visualMetrics,
        ...numericMetrics,
        ...(visibleSystemColumns.some(col => col.key === 'latency') ? [AVG_LATENCY_COLUMN_KEY] : []),
        ...(visibleSystemColumns.some(col => col.key === 'median-latency') ? [MEDIAN_LATENCY_COLUMN_KEY] : []),
        ...traceMetricKeys,
      ];
      const metricScaleMax = {};
      for (const metric of visualMetrics) {
        const metricType = state._metricTypes?.[metric] || 'score';
        if (metricType !== 'numeric') continue;
        metricScaleMax[metric] = Math.max(...allRuns.map(run => Number(run.metric_averages?.[metric] || 0)), 0);
      }
      const traceMetricScaleMax = {};
      for (const traceMetric of visibleTraceMetrics) {
        if (traceMetric.key === 'tool_success_rate') continue;
        traceMetricScaleMax[traceMetric.key] = Math.max(
          ...allRuns.map(run => Number(run.trace_stats?.[traceMetric.key] || 0)),
          0
        );
      }
      const avgLatencyScaleMax = Math.max(...allRuns.map(run => Number(run.latency || 0)), 0);
      const medianLatencyScaleMax = Math.max(...allRuns.map(run => Number(run.median_latency || 0)), 0);

      const firstColSortKey = (groupMode === 'version' || groupMode === 'version-model') ? null : 'model';
      const availableSortKeys = [
        ...(firstColSortKey ? [firstColSortKey] : []),
        ...(showGroupStatColumns ? visibleGroupStatColumns.map(col => col.key) : []),
        ...displayColumns.map(column => (
          column === AVG_LATENCY_COLUMN_KEY
            ? 'latency'
            : column === MEDIAN_LATENCY_COLUMN_KEY
              ? 'median-latency'
              : column
        )),
      ];

      if (!availableSortKeys.includes(sortState.key)) {
        const fallbackSortKey = (showGroupStatColumns ? visibleGroupStatColumns[0]?.key : null) || displayColumns[0] || firstColSortKey || 'model';
        sortState.key = fallbackSortKey === AVG_LATENCY_COLUMN_KEY
          ? 'latency'
          : fallbackSortKey === MEDIAN_LATENCY_COLUMN_KEY
            ? 'median-latency'
            : fallbackSortKey;
        sortState.dir = getChartSortDirection(sortState.key);
        state.chartSortState[cardId] = sortState;
      }

      // Build header row with sortable columns
      const groupStatHeaderCells = visibleGroupStatColumns.map(({ key, label }) => {
        const isActive = sortState.key === key;
        const arrow = isActive ? (sortState.dir === 'desc' ? '\u2193' : '\u2191') : '';
        const title = `${label} for grouped runs`;
        return `<span class="chart-col-header chart-group-stat-header sortable-col ${isActive ? 'active' : ''}" data-card="${cardId}" data-sort="${key}" title="${title}"><span class="chart-col-header-label">${label}</span>${arrow ? `<span class="chart-col-sort">${arrow}</span>` : ''}</span>`;
      }).join('');
      const headerCells = displayColumns.map(column => {
        if (column === AVG_LATENCY_COLUMN_KEY) {
          const isActive = sortState.key === 'latency';
          const arrow = isActive ? (sortState.dir === 'desc' ? '\u2193' : '\u2191') : '';
          return `<span class="chart-col-header chart-col-header-latency sortable-col ${isActive ? 'active' : ''}" data-card="${cardId}" data-sort="latency" title="Avg Latency"><span class="chart-col-header-label">\u26A1 Avg Latency</span>${arrow ? `<span class="chart-col-sort">${arrow}</span>` : ''}</span>`;
        }
        if (column === MEDIAN_LATENCY_COLUMN_KEY) {
          const isActive = sortState.key === 'median-latency';
          const arrow = isActive ? (sortState.dir === 'desc' ? '\u2193' : '\u2191') : '';
          return `<span class="chart-col-header chart-col-header-latency sortable-col ${isActive ? 'active' : ''}" data-card="${cardId}" data-sort="median-latency" title="Median Latency"><span class="chart-col-header-label">\u26A1 Median Latency</span>${arrow ? `<span class="chart-col-sort">${arrow}</span>` : ''}</span>`;
        }
        const label = getMetricDisplayName(column);
        const isActive = sortState.key === column;
        const arrow = isActive ? (sortState.dir === 'desc' ? '\u2193' : '\u2191') : '';
        return `<span class="chart-col-header sortable-col ${isActive ? 'active' : ''}" data-card="${cardId}" data-sort="${column}" title="${label}"><span class="chart-col-header-label">${label}</span>${arrow ? `<span class="chart-col-sort">${arrow}</span>` : ''}</span>`;
      }).join('');

      function renderMetricValueCell(metricName, value, modelIdx, isAggregate = false) {
        if (value === undefined || value === null) {
          return `<div class="chart-metric-cell"><span class="metric-na">\u2014</span></div>`;
        }
        const chartMType = state._metricTypes?.[metricName] || window.QymMetrics.detectMetricTypeFromAvg(value);
        if (!prefersBarChartMetric(metricName, chartMType)) {
          const display = window.QymMetrics.formatNumericValue(value);
          return `<div class="chart-metric-cell"><span class="chart-numeric-value${isAggregate ? ' aggregate' : ''}">${display}</span></div>`;
        }
        if (chartMType === 'numeric') {
          const scaleMax = metricScaleMax[metricName] || value || 1;
          return renderMiniBarCell({
            value,
            label: window.QymMetrics.formatNumericValue(value),
            ratio: scaleMax > 0 ? value / scaleMax : 0,
            modelIdx,
            isAggregate,
          });
        }
        const pct = value * 100;
        const label = pct === 0 ? '0%' : pct === 100 ? '100%' : `${pct.toFixed(1)}%`;
        return renderMiniBarCell({
          value,
          label,
          ratio: value,
          modelIdx,
          isAggregate,
        });
      }

      function renderLatencyValueCell(latencyValue, scaleMax, modelIdx, isAggregate = false) {
        if (!latencyValue) {
          return `<div class="chart-latency-cell"><span class="metric-na">\u2014</span></div>`;
        }
        return renderMiniBarCell({
          value: latencyValue,
          label: formatLatency(latencyValue),
          ratio: scaleMax > 0 ? latencyValue / scaleMax : 0,
          modelIdx,
          isAggregate,
          cellClass: 'chart-latency-cell',
        });
      }

      function renderTraceMetricValueCell(metricKey, value, modelIdx, isAggregate = false) {
        if (value === undefined || value === null) {
          return `<div class="chart-metric-cell"><span class="metric-na">\u2014</span></div>`;
        }
        const traceMetric = getTraceMetricConfig(metricKey);
        const display = traceMetric ? traceMetric.fmt(value) : String(value);
        if (metricKey === 'tool_success_rate') {
          return renderMiniBarCell({
            value,
            label: display,
            ratio: value,
            modelIdx,
            isAggregate,
          });
        }
        const scaleMax = traceMetricScaleMax[metricKey] || value || 1;
        return renderMiniBarCell({
          value,
          label: display,
          ratio: scaleMax > 0 ? value / scaleMax : 0,
          modelIdx,
          isAggregate,
        });
      }

      // --- Helper: render a single run row ---
      function renderRunRow(runData) {
        const { model, run_id, file_path, timestamp, metric_averages, latency, isMultiRun } = runData;
        const modelIdx = state.allModels.indexOf(model) % CHART_COLORS.length;
        const dt = formatDate(timestamp);
        const displayModel = renderModelLabelForModelName(model);
        const hoverRunName = runData.run_name || 'none';
        let displayHtml = `${displayModel}`;
        const tsMatch = run_id.match(/-(\d{2})(\d{2})(\d{2})-(\d{2})(\d{2})(?:-(\d+))?$/);
        if (tsMatch) {
          const [, yy, mm, dd, hh, min, counter] = tsMatch;
          const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
          const monthName = months[parseInt(mm, 10) - 1] || mm;
          const day = parseInt(dd, 10);
          const timeStr = `${hh}:${min}`;
          const counterStr = counter ? ` #${counter}` : '';
          displayHtml = `${displayModel}<span class="run-timestamp">${monthName} ${day} \u00b7 ${timeStr}${counterStr}</span>`;
        } else {
          displayHtml = `${displayModel}<span class="run-timestamp">${dt.date} \u00b7 ${dt.time}</span>`;
        }
        const versionStr = runData.git_commit ? (runData.git_branch ? `${runData.git_branch}/${runData.git_commit}` : runData.git_commit) : '';
        const versionTag = versionStr ? `<span class="chart-version-tag">${versionStr}</span>` : '';
        const tooltipText = `Run name: ${hoverRunName}${versionStr ? `\nVersion: ${versionStr}` : ''}`;
        const dataCells = displayColumns.map(column => {
          if (column === AVG_LATENCY_COLUMN_KEY) {
            return renderLatencyValueCell(latency, avgLatencyScaleMax, modelIdx);
          }
          if (column === MEDIAN_LATENCY_COLUMN_KEY) {
            return renderLatencyValueCell(runData.median_latency, medianLatencyScaleMax, modelIdx);
          }
          if (isTraceMetricKey(column)) {
            return renderTraceMetricValueCell(column, runData.trace_stats?.[column], modelIdx);
          }
          return renderMetricValueCell(column, metric_averages[column], modelIdx);
        }).join('');
        return `
          <div class="chart-table-row">
            <span class="chart-bar-label clickable-run ${isMultiRun ? 'multi-run' : ''}"
                  data-file="${file_path}"
                  title="${tooltipText}">${displayHtml}${versionTag}</span>
            ${dataCells}
          </div>
        `;
      }

      // --- Helper: compute group aggregates ---
      function computeGroupAgg(runs) {
        const agg = {};
        const traceAgg = {};
        let latSum = 0, latCount = 0;
        const medianLatencies = [];
        for (const r of runs) {
          for (const m of metrics) {
            const v = r.metric_averages[m];
            if (v !== undefined && v !== null) {
              if (!agg[m]) agg[m] = { sum: 0, count: 0 };
              agg[m].sum += v;
              agg[m].count++;
            }
          }
          for (const tm of visibleTraceMetrics) {
            const v = r.trace_stats?.[tm.key];
            if (v !== undefined && v !== null) {
              if (!traceAgg[tm.key]) traceAgg[tm.key] = { sum: 0, count: 0 };
              traceAgg[tm.key].sum += v;
              traceAgg[tm.key].count++;
            }
          }
          if (r.latency) { latSum += r.latency; latCount++; }
          if (r.median_latency) medianLatencies.push(r.median_latency);
        }
        const metricAverages = {};
        for (const m of metrics) {
          metricAverages[m] = agg[m] ? agg[m].sum / agg[m].count : undefined;
        }
        const traceAverages = {};
        for (const tm of visibleTraceMetrics) {
          traceAverages[tm.key] = traceAgg[tm.key] ? traceAgg[tm.key].sum / traceAgg[tm.key].count : undefined;
        }
        return {
          metricAverages,
          traceAverages,
          avgLatency: latCount > 0 ? latSum / latCount : 0,
          medianLatency: medianLatencies.length > 0 ? window.QymMetrics.calculateMedian(medianLatencies) : 0,
        };
      }

      function isChartGroupMetricBoolean(runs, metricName) {
        if (!metricName) return false;
        let count = 0;
        let allBinary = true;
        for (const run of runs || []) {
          const value = run.metric_averages?.[metricName];
          if (value === undefined || value === null || isNaN(Number(value))) continue;
          count++;
          const numeric = Number(value);
          if (Math.abs(numeric) > 0.0001 && Math.abs(numeric - 1) > 0.0001) {
            allBinary = false;
            break;
          }
        }
        return count > 0 && allBinary;
      }

      function getChartGroupMetricCacheKey(runs, metricName, threshold) {
        const paths = (runs || []).map(run => run.file_path).filter(Boolean).sort();
        return [cardId, metricName, String(threshold), ...paths].join('||');
      }

      function getChartGroupMetricThreshold(runs, metricName) {
        return isChartGroupMetricBoolean(runs, metricName) ? 0.9999 : 0.8;
      }

      function scheduleChartGroupMetricStats(runs, metricName, threshold, isBoolean) {
        if (!metricName || !Array.isArray(runs) || runs.length === 0) return null;
        if (!state.chartGroupMetricStats) state.chartGroupMetricStats = {};
        const cacheKey = getChartGroupMetricCacheKey(runs, metricName, threshold);
        const cached = state.chartGroupMetricStats[cacheKey];
        if (cached) return cached;

        state.chartGroupMetricStats[cacheKey] = { status: 'loading', K: runs.length };
        const paths = Array.from(new Set(runs.map(run => run.file_path).filter(Boolean)));
        fetchModelRunsData(paths).then((payload) => {
          const detailedRuns = payload && Array.isArray(payload.runs) ? payload.runs : [];
          const stats = calculateModelStatsFromItems(detailedRuns, metricName, threshold, isBoolean);
          state.chartGroupMetricStats[cacheKey] = { status: 'ready', K: stats.K || runs.length, stats };
          if (state.currentView === 'charts') renderChartsView();
        }).catch(() => {
          state.chartGroupMetricStats[cacheKey] = { status: 'error', K: runs.length };
          if (state.currentView === 'charts') renderChartsView();
        });
        return state.chartGroupMetricStats[cacheKey];
      }

      function renderEmptyGroupStatCells() {
        if (!showGroupStatColumns || visibleGroupStatColumns.length === 0) return '';
        return visibleGroupStatColumns
          .map(() => '<div class="chart-metric-cell chart-group-stat-cell chart-group-stat-cell-empty"><span class="metric-na">\u2014</span></div>')
          .join('');
      }

      function renderGroupStatBar(value, label, title, modelIdx) {
        if (value === undefined || value === null) {
          return `<div class="chart-metric-cell chart-group-stat-cell" title="${title}"><span class="metric-na">\u2014</span></div>`;
        }
        return renderMiniBarCell({
          value,
          label,
          ratio: value,
          modelIdx,
          isAggregate: true,
          cellClass: 'chart-metric-cell chart-group-stat-cell',
          title,
        });
      }

      function renderChartGroupStatCells(runs, modelIdx = null) {
        if (!showGroupStatColumns) return '';
        const emptyCells = renderEmptyGroupStatCells();
        if (!groupMetricName || !Array.isArray(runs) || runs.length === 0) return emptyCells;
        const isBoolean = isChartGroupMetricBoolean(runs, groupMetricName);
        const threshold = getChartGroupMetricThreshold(runs, groupMetricName);
        const entry = scheduleChartGroupMetricStats(runs, groupMetricName, threshold, isBoolean);
        const K = entry?.K || runs.length;
        if (!entry || entry.status === 'loading') {
          const loadingTitles = {
            [GROUP_PASS_AT_K_COLUMN_KEY]: `Loading Pass@${K} for ${escapeHtml(groupMetricName)}`,
            [GROUP_CONSISTENCY_COLUMN_KEY]: `Loading consistency for ${escapeHtml(groupMetricName)}`,
            [GROUP_RELIABILITY_COLUMN_KEY]: `Loading reliability for ${escapeHtml(groupMetricName)}`,
          };
          return visibleGroupStatColumns
            .map(col => `<div class="chart-metric-cell chart-group-stat-cell is-loading" title="${loadingTitles[col.key]}"><span class="metric-na">\u2014</span></div>`)
            .join('');
        }
        if (entry.status !== 'ready' || !entry.stats) {
          return emptyCells;
        }
        const stats = entry.stats;
        const consistencyText = stats.consistency !== null ? formatPercent(stats.consistency) : 'NA';
        const reliabilityText = stats.reliability !== null ? formatPercent(stats.reliability) : 'NA';
        return visibleGroupStatColumns.map(col => {
          if (col.key === GROUP_PASS_AT_K_COLUMN_KEY) {
            return renderGroupStatBar(stats.passAtK, formatPercent(stats.passAtK), `Pass@${K} ${formatPercent(stats.passAtK)}`, modelIdx);
          }
          if (col.key === GROUP_CONSISTENCY_COLUMN_KEY) {
            return renderGroupStatBar(stats.consistency, consistencyText, `Consistency ${consistencyText}`, modelIdx);
          }
          if (col.key === GROUP_RELIABILITY_COLUMN_KEY) {
            return renderGroupStatBar(stats.reliability, reliabilityText, `Reliability ${reliabilityText}`, modelIdx);
          }
          return '';
        }).join('');
      }

      function safeChartGroupId(value) {
        return String(value || 'empty').replace(/[^a-zA-Z0-9_-]/g, '_');
      }

      function getRunVersionGroup(run) {
        if (run.git_commit) {
          return {
            key: run.git_commit,
            label: run.git_branch ? `${run.git_branch}/${run.git_commit}` : run.git_commit,
          };
        }
        return { key: '__no_version__', label: 'No version' };
      }

      function groupRunsBy(runs, grouping) {
        const groups = {};
        for (const run of runs) {
          const groupInfo = grouping === 'version'
            ? getRunVersionGroup(run)
            : {
                key: run.model,
                label: renderModelLabelForModelName(run.model),
                sortModel: stripModelProvider(parseModelVariantKey(run.model).rawModelName || run.model),
                model: run.model,
              };
          if (!groups[groupInfo.key]) groups[groupInfo.key] = { ...groupInfo, runs: [] };
          groups[groupInfo.key].runs.push(run);
        }
        return Object.values(groups);
      }

      function sortGroupsByState(groups) {
        groups.sort((a, b) => compareChartSortValues(
          getGroupSortValue(a, sortState.key),
          getGroupSortValue(b, sortState.key),
          sortState.dir
        ));
      }

      // --- Helper: render a group header row ---
      function renderGroupHeader(label, runCount, agg, groupId, groupModelIdx = null, level = 1, groupRuns = null) {
        const isCollapsed = isChartGroupCollapsed(cardId, groupMode, groupId);
        const groupStatCells = isCollapsed ? renderChartGroupStatCells(groupRuns || [], groupModelIdx) : '';
        const dataCells = displayColumns.map(column => {
          if (column === AVG_LATENCY_COLUMN_KEY) {
            return renderLatencyValueCell(agg.avgLatency, avgLatencyScaleMax, groupModelIdx, true);
          }
          if (column === MEDIAN_LATENCY_COLUMN_KEY) {
            return renderLatencyValueCell(agg.medianLatency, medianLatencyScaleMax, groupModelIdx, true);
          }
          if (isTraceMetricKey(column)) {
            return renderTraceMetricValueCell(column, agg.traceAverages?.[column], groupModelIdx, true);
          }
          return renderMetricValueCell(column, agg.metricAverages[column], groupModelIdx, true);
        }).join('');
        return `
          <div class="chart-table-group-header ${level > 1 ? 'chart-table-group-header-nested' : ''}" data-group-id="${groupId}">
            <div class="chart-table-group-main">
              <span class="chart-group-first-col">
                <span class="chart-group-toggle">${isCollapsed ? '\u25b6' : '\u25bc'}</span>
                <span class="chart-group-copy">
                  <span class="chart-group-title-line">
                    <span class="chart-group-label">${label}</span>
                    <span class="chart-group-count">${runCount} run${runCount !== 1 ? 's' : ''}</span>
                  </span>
                </span>
              </span>
              ${groupStatCells}
              ${dataCells}
            </div>
          </div>
        `;
      }

      // --- Build table body based on grouping mode ---
      let rowsHtml = '';
      let firstColLabel = 'Model';
      let hasExpandedGroups = false;

      if (groupMode === 'run') {
        // Flat run rows (original behavior)
        allRuns.sort(sortByState);
        rowsHtml = allRuns.map(renderRunRow).join('');
      } else if (groupMode === 'version') {
        firstColLabel = 'Version';
        const sortedGroups = groupRunsBy(allRuns, 'version').map((g) => {
          const agg = computeGroupAgg(g.runs);
          g.runs.sort(sortByState);
          return { ...g, agg };
        });
        sortGroupsByState(sortedGroups);

        for (const g of sortedGroups) {
          const groupId = `vg_${cardId}_${safeChartGroupId(g.key)}`;
          const isCollapsed = isChartGroupCollapsed(cardId, groupMode, groupId);
          if (!isCollapsed) hasExpandedGroups = true;
          rowsHtml += renderGroupHeader(escapeHtml(g.label), g.runs.length, g.agg, groupId, null, 1, g.runs);
          rowsHtml += `<div class="chart-table-group-body${isCollapsed ? ' collapsed' : ''}" data-group-id="${groupId}">`;
          rowsHtml += g.runs.map(renderRunRow).join('');
          rowsHtml += `</div>`;
        }
      } else if (groupMode === 'model') {
        firstColLabel = 'Model';
        const sortedGroups = groupRunsBy(allRuns, 'model').map((g) => {
          const agg = computeGroupAgg(g.runs);
          g.runs.sort(sortByState);
          return { ...g, agg };
        });
        sortGroupsByState(sortedGroups);

        for (const g of sortedGroups) {
          const groupId = `mg_${cardId}_${safeChartGroupId(g.model)}`;
          const modelIdx = state.allModels.indexOf(g.model) % CHART_COLORS.length;
          const colorDot = `<span class="model-color-dot" style="background:${CHART_COLORS[modelIdx]}"></span>`;
          const isCollapsed = isChartGroupCollapsed(cardId, groupMode, groupId);
          if (!isCollapsed) hasExpandedGroups = true;
          rowsHtml += renderGroupHeader(`${colorDot}${g.label}`, g.runs.length, g.agg, groupId, modelIdx, 1, g.runs);
          rowsHtml += `<div class="chart-table-group-body${isCollapsed ? ' collapsed' : ''}" data-group-id="${groupId}">`;
          rowsHtml += g.runs.map(renderRunRow).join('');
          rowsHtml += `</div>`;
        }
      } else if (groupMode === 'version-model' || groupMode === 'model-version') {
        const primaryGrouping = groupMode === 'version-model' ? 'version' : 'model';
        const secondaryGrouping = groupMode === 'version-model' ? 'model' : 'version';
        firstColLabel = groupMode === 'version-model' ? 'Version / Model' : 'Model / Version';
        const sortedPrimaryGroups = groupRunsBy(allRuns, primaryGrouping).map((g) => {
          const agg = computeGroupAgg(g.runs);
          return { ...g, agg };
        });
        sortGroupsByState(sortedPrimaryGroups);

        for (const primary of sortedPrimaryGroups) {
          const primaryId = `${primaryGrouping === 'version' ? 'vg' : 'mg'}_${cardId}_${safeChartGroupId(primary.key)}`;
          const primaryModelIdx = primaryGrouping === 'model'
            ? state.allModels.indexOf(primary.model) % CHART_COLORS.length
            : null;
          const primaryColorDot = primaryGrouping === 'model'
            ? `<span class="model-color-dot" style="background:${CHART_COLORS[primaryModelIdx]}"></span>`
            : '';
          const primaryLabel = primaryGrouping === 'version'
            ? escapeHtml(primary.label)
            : `${primaryColorDot}${primary.label}`;
          const primaryCollapsed = isChartGroupCollapsed(cardId, groupMode, primaryId);
          if (!primaryCollapsed) hasExpandedGroups = true;
          rowsHtml += renderGroupHeader(primaryLabel, primary.runs.length, primary.agg, primaryId, primaryModelIdx, 1, primary.runs);
          rowsHtml += `<div class="chart-table-group-body chart-table-group-body-nested${primaryCollapsed ? ' collapsed' : ''}" data-group-id="${primaryId}">`;

          const sortedSecondaryGroups = groupRunsBy(primary.runs, secondaryGrouping).map((g) => {
            const agg = computeGroupAgg(g.runs);
            g.runs.sort(sortByState);
            return { ...g, agg };
          });
          sortGroupsByState(sortedSecondaryGroups);

          for (const secondary of sortedSecondaryGroups) {
            const secondaryId = `${primaryId}_${secondaryGrouping === 'version' ? 'vg' : 'mg'}_${safeChartGroupId(secondary.key)}`;
            const secondaryModelIdx = secondaryGrouping === 'model'
              ? state.allModels.indexOf(secondary.model) % CHART_COLORS.length
              : primaryModelIdx;
            const secondaryColorDot = secondaryGrouping === 'model'
              ? `<span class="model-color-dot" style="background:${CHART_COLORS[secondaryModelIdx]}"></span>`
              : '';
            const secondaryLabel = secondaryGrouping === 'version'
              ? escapeHtml(secondary.label)
              : `${secondaryColorDot}${secondary.label}`;
            const secondaryCollapsed = isChartGroupCollapsed(cardId, groupMode, secondaryId);
            if (!secondaryCollapsed) hasExpandedGroups = true;
            rowsHtml += renderGroupHeader(secondaryLabel, secondary.runs.length, secondary.agg, secondaryId, secondaryModelIdx, 2, secondary.runs);
            rowsHtml += `<div class="chart-table-group-body chart-table-group-body-leaf${secondaryCollapsed ? ' collapsed' : ''}" data-group-id="${secondaryId}">`;
            rowsHtml += secondary.runs.map(renderRunRow).join('');
            rowsHtml += `</div>`;
          }

          rowsHtml += `</div>`;
        }
      }

      const expandCollapseBtn = isGrouped
        ? `<button class="chart-expand-collapse-btn" data-card="${cardId}">${hasExpandedGroups ? 'Collapse all' : 'Expand all'}</button>`
        : '';
      const groupedSummary = {
        version: 'Grouped by version',
        model: 'Grouped by model',
        'version-model': 'Grouped by version, comparing models inside each version',
        'model-version': 'Grouped by model, split by version',
      }[groupMode] || '';
      const primaryGroup = groupMode === 'version' || groupMode === 'version-model' ? 'version' : 'model';
      const secondaryGroup = groupMode === 'version-model' ? 'model' : (groupMode === 'model-version' ? 'version' : '');
      const thenModelDisabled = !isGrouped || primaryGroup === 'model';
      const thenVersionDisabled = !isGrouped || primaryGroup === 'version' || !hasVersions;
      const groupVersionDisabled = !hasVersions;
      const thenModelTitle = primaryGroup === 'model' ? 'Already grouped by model' : '';
      const thenVersionTitle = !hasVersions ? 'No version data available' : (primaryGroup === 'version' ? 'Already grouped by version' : '');
      const thenModelAttrs = thenModelDisabled ? `disabled title="${thenModelTitle}"` : '';
      const thenVersionAttrs = thenVersionDisabled ? `disabled title="${thenVersionTitle}"` : '';
      const firstColDisplayLabel = isGrouped && hasExpandedGroups ? `${firstColLabel} / Run` : firstColLabel;

      const controlsHtml = `
        <div class="chart-table-toolbar">
          <div class="chart-group-controls">
            <span class="chart-control-label">Rows</span>
            <span class="chart-segment-control chart-row-mode-control" data-card="${cardId}">
              <button class="chart-segment-btn ${groupMode === 'run' ? 'active' : ''}" data-mode="run">Runs</button>
              <button class="chart-segment-btn ${isGrouped ? 'active' : ''}" data-mode="${isGrouped ? groupMode : 'model'}">Grouped</button>
            </span>
            ${isGrouped ? `
              <span class="chart-control-label">Group</span>
              <span class="chart-segment-control chart-group-axis-control" data-card="${cardId}">
                <button class="chart-segment-btn ${primaryGroup === 'model' ? 'active' : ''}" data-mode="model">Model</button>
                <button class="chart-segment-btn ${primaryGroup === 'version' ? 'active' : ''}" data-mode="version" ${groupVersionDisabled ? 'disabled title="No version data available"' : ''}>Version</button>
              </span>
              <span class="chart-control-label">Then</span>
              <span class="chart-segment-control chart-then-axis-control" data-card="${cardId}">
                <button class="chart-segment-btn ${secondaryGroup === 'model' ? 'active' : ''}" data-mode="version-model" ${thenModelAttrs}>Model</button>
                <button class="chart-segment-btn ${secondaryGroup === 'version' ? 'active' : ''}" data-mode="model-version" ${thenVersionAttrs}>Version</button>
              </span>
              <span class="chart-group-summary">${groupedSummary}</span>
            ` : ''}
          </div>
          ${expandCollapseBtn}
        </div>
      `;

      const firstColHtml = `
        <span class="chart-col-header-run">
          <span class="chart-first-col-header-wrap">
            ${firstColSortKey
              ? `<button class="chart-first-col-sort sortable-col ${sortState.key === firstColSortKey ? 'active' : ''}" type="button" data-card="${cardId}" data-sort="${firstColSortKey}" title="Sort by ${firstColDisplayLabel.toLowerCase()}">
                  <span class="chart-col-header-label">${firstColDisplayLabel}</span>
                  ${sortState.key === firstColSortKey ? `<span class="chart-col-sort">${sortState.dir === 'desc' ? '\u2193' : '\u2191'}</span>` : ''}
                </button>`
              : `<span class="chart-first-col-title">${firstColDisplayLabel}</span>`}
            <button class="chart-col-resizer" type="button" title="Drag to resize first column. Double-click to reset width" aria-label="Resize first column"></button>
          </span>
        </span>
      `;

      const metricChartsHtml = `
        <div class="chart-table-shell">
          ${controlsHtml}
          <div class="chart-table-scroll">
            <div class="chart-table ${isGrouped ? 'chart-table-grouped' : ''}" data-card-id="${cardId}">
              <div class="chart-table-header">
                ${firstColHtml}
                ${showGroupStatColumns ? groupStatHeaderCells : ''}
                ${headerCells}
              </div>
              <div class="chart-table-body">
                ${rowsHtml}
              </div>
            </div>
          </div>
        </div>
      `;

      return `
          <div class="chart-task-section">
            <div class="chart-task-header">
              <span class="chart-task-name">${taskName}</span>
              <span class="chart-task-meta">${totalTaskRuns} runs \u00b7 ${allTaskModels.size} models \u00b7 ${metrics.length + visibleTraceMetrics.length} metrics</span>
            </div>
          <div class="chart-card">
            ${datasetTabsHtml}
            <div class="chart-card-body">
              ${metricChartsHtml}
            </div>
          </div>
        </div>
      `;
    }).join('');

    // Wire up click events for run labels
    gridEl.querySelectorAll('.chart-bar-label.clickable-run').forEach(label => {
      label.addEventListener('click', (e) => {
        const target = e.target.closest('.chart-bar-label');
        const filePath = target?.dataset.file;
        if (filePath) {
          openRun(filePath, e);
        }
      });
      label.addEventListener('auxclick', (e) => {
        if (e.button !== 1) return;
        const target = e.target.closest('.chart-bar-label');
        const filePath = target?.dataset.file;
        if (filePath) {
          e.preventDefault();
          openRun(filePath, e);
        }
      });
    });

    // Wire up sortable column headers
    gridEl.querySelectorAll('.sortable-col').forEach(header => {
      header.addEventListener('click', (e) => {
        const target = e.currentTarget;
        const cardId = target.dataset.card;
        const sortKey = target.dataset.sort;
        if (!cardId || !sortKey) return;

        const currentSort = state.chartSortState[cardId] || { key: sortKey, dir: 'desc' };
        if (currentSort.key === sortKey) {
          currentSort.dir = currentSort.dir === 'desc' ? 'asc' : 'desc';
        } else {
          currentSort.key = sortKey;
          currentSort.dir = getChartSortDirection(sortKey);
        }
        state.chartSortState[cardId] = currentSort;
        renderChartsView();
      });
    });

    // Wire up segmented control (Run / Version / Model)
    gridEl.querySelectorAll('.chart-segment-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const cardId = e.target.closest('.chart-segment-control')?.dataset.card;
        const mode = e.target.dataset.mode;
        if (!cardId || !mode || e.target.disabled) return;
        if (!state.chartGroupMode) state.chartGroupMode = {};
        state.chartGroupMode[cardId] = mode;
        if (mode !== 'run') {
          state.chartGroupExpansion = state.chartGroupExpansion || {};
          state.chartGroupExpansion[cardId] = { mode, expanded: {} };
        }
        const metricSourceRuns = state.filteredRuns.length > 0 ? state.filteredRuns : state.flatRuns;
        populateMetricVisibility(getAvailableMetricsForRuns(metricSourceRuns), metricSourceRuns);
        renderChartsView();
      });
    });

    // Wire up group expand/collapse
    gridEl.querySelectorAll('.chart-table-group-header').forEach(header => {
      header.addEventListener('click', () => {
        const groupId = header.dataset.groupId;
        const card = header.closest('.chart-table')?.dataset.cardId;
        const body = gridEl.querySelector(`.chart-table-group-body[data-group-id="${groupId}"]`);
        if (body && card) {
          const mode = state.chartGroupMode?.[card] || 'run';
          const isCollapsed = body.classList.contains('collapsed');
          setChartGroupCollapsed(card, mode, groupId, !isCollapsed);
          render();
        }
      });
    });

    // Wire up expand/collapse all buttons
    gridEl.querySelectorAll('.chart-expand-collapse-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const cardId = btn.dataset.card;
        const card = btn.closest('.chart-card');
        if (!card) return;
        const bodies = card.querySelectorAll('.chart-table-group-body');
        const anyExpanded = [...bodies].some(b => !b.classList.contains('collapsed'));
        const mode = state.chartGroupMode?.[cardId] || 'run';
        bodies.forEach(b => {
          const groupId = b.dataset.groupId;
          if (anyExpanded) {
            if (groupId) setChartGroupCollapsed(cardId, mode, groupId, true);
          } else {
            if (groupId) setChartGroupCollapsed(cardId, mode, groupId, false);
          }
        });
        render();
      });
    });

    // Wire up dataset tab clicks
    gridEl.querySelectorAll('.chart-dataset-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        const taskName = tab.dataset.task;
        const dataset = tab.dataset.dataset;
        if (taskName && dataset) {
          state.chartDatasetTab[taskName] = dataset;
          renderChartsView();
        }
      });
    });

    // Wire up first-column resize handles
    gridEl.querySelectorAll('.chart-col-resizer').forEach(handle => {
      handle.addEventListener('dblclick', (e) => {
        e.preventDefault();
        applyChartFirstColWidth(CHART_FIRST_COL_DEFAULT_WIDTH);
        saveDashboardState();
      });

      handle.addEventListener('pointerdown', (e) => {
        if (e.pointerType === 'mouse' && e.button !== 0) return;
        e.preventDefault();

        const startX = e.clientX;
        const startWidth = state.chartFirstColWidth || CHART_FIRST_COL_DEFAULT_WIDTH;
        const activeHandle = e.currentTarget;
        activeHandle.classList.add('active');
        document.body.classList.add('chart-col-resize-active');

        const onMove = (moveEvent) => {
          applyChartFirstColWidth(startWidth + (moveEvent.clientX - startX));
        };

        const onEnd = () => {
          activeHandle.classList.remove('active');
          document.body.classList.remove('chart-col-resize-active');
          window.removeEventListener('pointermove', onMove);
          window.removeEventListener('pointerup', onEnd);
          window.removeEventListener('pointercancel', onEnd);
          saveDashboardState();
        };

        window.addEventListener('pointermove', onMove);
        window.addEventListener('pointerup', onEnd);
        window.addEventListener('pointercancel', onEnd);
      });
    });
  }

  // ═══════════════════════════════════════════════════
  // RENDERING: TABLE VIEW
  // ═══════════════════════════════════════════════════

  function updateTableHeader(metricsToShow) {
    // Update the table header to include dynamic metric columns
    const headerRow = el('table-header-row');
    if (!headerRow) return;

    // Find the latency columns (insert metric columns before them)
    const latencyHeader = headerRow.querySelector('.col-latency');
    const medianLatencyHeader = headerRow.querySelector('.col-latency-median');
    if (!latencyHeader) return;

    // Remove any existing dynamic metric columns and trace columns
    headerRow.querySelectorAll('.col-metric-dynamic, .col-trace-separator, .col-trace-metric').forEach(col => col.remove());

    // Insert metric columns before LATENCY column
    metricsToShow.forEach(metric => {
      const th = document.createElement('th');
      th.className = 'col-metric-dynamic sortable';
      th.dataset.sort = `metric-${metric}`;
      th.textContent = metric;
      th.title = `Sort by ${metric}`;
      headerRow.insertBefore(th, latencyHeader);
    });

    // Insert the ops separator before latency columns and trace metric columns after them
    const vtm = _visibleTraceMetrics(state.filteredRuns);
    if (vtm.length > 0) {
      const sep = document.createElement('th');
      sep.className = 'col-trace-separator';
      headerRow.insertBefore(sep, latencyHeader);
      let insertAfter = medianLatencyHeader || latencyHeader;
      vtm.forEach(tm => {
        const th = document.createElement('th');
        th.className = 'col-trace-metric sortable';
        th.dataset.sort = `trace-${tm.key}`;
        th.textContent = tm.label;
        th.title = `Sort by ${tm.label}`;
        insertAfter.insertAdjacentElement('afterend', th);
        insertAfter = th;
      });
    }

    // Wire up sorting for all sortable columns
    headerRow.querySelectorAll('.sortable').forEach(th => {
      th.onclick = () => handleColumnSort(th.dataset.sort);
    });
  }

  function handleColumnSort(sortField) {
    // Determine current direction and toggle
    const currentKey = state.sortKey;
    let newKey;

    if (currentKey.startsWith(sortField + '-') || currentKey.startsWith('metric-' + sortField + '-')) {
      // Toggle direction
      const direction = currentKey.endsWith('-asc') ? 'desc' : 'asc';
      newKey = sortField.startsWith('metric-') ? `${sortField}-${direction}` : `${sortField}-${direction}`;
    } else {
      // Default to descending for numeric/time, ascending for text
      const numericFields = ['success', 'items', 'status', 'time', 'date', 'latency', 'median-latency', 'duration'];
      const isNumeric = numericFields.includes(sortField) || sortField.startsWith('metric-') || sortField.startsWith('trace-');
      newKey = `${sortField}-${isNumeric ? 'desc' : 'asc'}`;
    }

    state.sortKey = newKey;
    updateSortIndicators();
    render();
  }

  function updateSortIndicators() {
    const headerRow = el('table-header-row');
    if (!headerRow) return;

    headerRow.querySelectorAll('.sortable').forEach(th => {
      th.classList.remove('sorted', 'asc');
      const sortField = th.dataset.sort;
      if (state.sortKey.startsWith(sortField + '-') ||
          (sortField.startsWith('metric-') && state.sortKey.startsWith(sortField))) {
        th.classList.add('sorted');
        if (state.sortKey.endsWith('-asc')) {
          th.classList.add('asc');
        }
      }
    });
  }

  // #7: Compute a stable grouping key from run_config (exclude ephemeral fields)
  function computeRunConfigGroupKey(run) {
    const config = run.run_config || {};
    const ephemeral = new Set(['run_name', 'resume_from', 'cli_invocation']);
    const stableEntries = Object.entries(config)
      .filter(([k]) => !ephemeral.has(k))
      .sort(([a], [b]) => a.localeCompare(b));
    if (stableEntries.length === 0) return null;
    try {
      return JSON.stringify(stableEntries);
    } catch {
      return null;
    }
  }

  // #7: Extract base timestamp from run name/id for grouping.
  // e.g. "my_task-gpt4-260218-1430-2" -> "260218-1430"
  // Runs with the same task + base timestamp belong together.
  // Repeat runs: expand each ×k run into k per-pass pseudo-runs so group
  // analysis pools attempts (the attempt is the atomic unit). Runs without
  // pass data flow through unchanged (each = 1 attempt, today's semantics).
  function expandSampledRunsData(runsData) {
    const out = [];
    (runsData || []).forEach(rd => {
      const samples = parseInt(rd?.run?.samples, 10) || 1;
      const rows = rd?.snapshot?.rows || [];
      const hasPassData = samples > 1 && rows.some(r => r && r.pass_scores);
      if (!hasPassData) { out.push(rd); return; }
      const metricNames = rd.snapshot.metric_names || rd.run.metric_names || [];
      for (let p = 0; p < samples; p++) {
        const passRows = rows.map(row => {
          const mv = metricNames.map((m, i) => {
            const ps = row.pass_scores ? row.pass_scores[m] : null;
            if (Array.isArray(ps)) return (ps[p] == null ? '' : ps[p]);
            return row.metric_values ? row.metric_values[i] : '';
          });
          return Object.assign({}, row, { metric_values: mv });
        });
        out.push({ run: rd.run, snapshot: Object.assign({}, rd.snapshot, { rows: passRows }) });
      }
    });
    return out;
  }

  // Repeat runs: markup for the expanded two-zone instrument panel —
  // pass ledger (score-colored numbers + meters, dot statuses) on the left,
  // the group-metric verdict tiles on the right.
  function renderSamplesDetail(passes, group) {
    const metricNames = (passes && passes.metrics) || [];
    const primaryMetric = metricNames[0];
    const allPasses = (passes && passes.passes) || [];
    const fmt = v => (typeof v === 'number' ? window.QymMetrics.formatNumericValue(v) : '—');
    const scoreClass = v => {
      if (typeof v !== 'number') return '';
      const cls = window.QymMetrics.getMetricColorClass(v, 'score');
      return cls ? cls.replace('score-', 'sc-') : '';
    };

    // Pending passes collapse into one line instead of a stack of empty rows.
    const visible = allPasses.filter(p => p.status !== 'pending');
    const queued = allPasses.length - visible.length;
    const ledgerRows = visible.map(p => {
      const v = primaryMetric ? (p.metric_means || {})[primaryMetric] : undefined;
      const cls = scoreClass(v);
      const pct = (typeof v === 'number') ? Math.round(Math.max(0, Math.min(1, v)) * 100) : 0;
      const lat = (typeof p.avg_latency_ms === 'number') ? formatLatency(p.avg_latency_ms) : '—';
      return `<div class="sp-row">
        <span class="sp-label">pass ${p.pass_number}/${passes.samples}</span>
        <span class="sp-dot ${escapeHtml(p.status || '')}"></span>
        <span class="sp-score ${cls || 'empty'}">${typeof v === 'number' ? fmt(v) : '—'}</span>
        <span class="sp-meter ${cls}"><i style="width:${pct}%"></i></span>
        <span class="sp-latency">${lat}</span>
        <span class="sp-items">${p.items_scored || 0}</span>
      </div>`;
    }).join('');
    const queuedLine = queued > 0
      ? `<div class="sp-queued">${queued === 1
          ? `pass ${allPasses.length}/${passes.samples} queued`
          : `passes ${allPasses.length - queued + 1}–${allPasses.length}/${passes.samples} queued`}</div>`
      : '';

    const g = (group && group.group) || {};
    const k = g.k || (passes && passes.samples) || 0;
    const tile = (label, value, mods) =>
      `<div class="sv-tile ${mods || ''}">
        <div class="sv-label">${label}</div>
        <div class="sv-value ${scoreClass(value) || 'empty'}">${fmt(value)}</div>
      </div>`;
    const tiles = [
      tile(`Pass@${k}`, g.pass_at_k, 'hero'),
      tile(`Pass^${k}`, g.pass_hat_k, 'hero-warn'),
      tile(`Avg@${k}`, g.avg_at_k),
      tile(`Max@${k}`, g.max_at_k),
      tile('Consist.', g.consistency),
      tile('Reliab.', g.reliability),
    ].join('');

    return `<div class="samples-panel">
        <div class="samples-passes">
          <div class="samples-zone-title">Passes <span class="mono-note">· ${escapeHtml(primaryMetric || '')}</span></div>
          ${ledgerRows}${queuedLine}
        </div>
        <div class="samples-verdict">
          <div class="samples-zone-title">Group metrics <span class="mono-note">· k=${k} · threshold ${group && group.threshold != null ? group.threshold : 0.8}</span></div>
          <div class="sv-grid">${tiles}</div>
        </div>
      </div>`;
  }

  function extractRunTimestampGroup(run) {
    // Repeat runs are ONE logical run — never glue them into legacy
    // timestamp groups (runs.samples replaced the heuristic for new runs).
    if (run.samples > 1) return null;
    const productEval = run.product_eval || {};
    if (productEval && productEval.eval_id) {
      return `${run.task_name}|||product_eval:${productEval.eval_id}`;
    }
    const name = run.run_name || run.external_run_id || '';
    // Match YYMMDD-HHMM (optionally followed by -N counter)
    const m = name.match(/(\d{6}-\d{4})(?:-\d+)?$/);
    if (!m) return null;
    return `${run.task_name}|||${m[1]}`;
  }

  function renderTableView() {
    const allRuns = state.filteredRuns;
    const tbody = el('runs-tbody');
    const availableMetrics = getAvailableMetricsForRuns(allRuns);
    const metricsToShow = getVisibleMetrics(availableMetrics);
    const visibleTraceMetrics = _visibleTraceMetrics(allRuns);
    const visibleSystemColumns = new Set(_visibleSystemColumns().map(col => col.key));

    if (state.sortKey.startsWith('metric-')) {
      const parts = state.sortKey.split('-');
      const metricName = parts.slice(1, -1).join('-');
      if (!metricsToShow.includes(metricName)) {
        state.sortKey = 'time-desc';
        sortRuns(allRuns);
      }
    }
    if (state.sortKey.startsWith('trace-')) {
      const parts = state.sortKey.split('-');
      const traceKey = parts.slice(1, -1).join('-');
      if (!visibleTraceMetrics.some(tm => tm.key === traceKey)) {
        state.sortKey = 'time-desc';
        sortRuns(allRuns);
      }
    }
    if ((state.sortKey === 'latency-desc' || state.sortKey === 'latency-asc') && !visibleSystemColumns.has('latency')) {
      state.sortKey = 'time-desc';
      sortRuns(allRuns);
    }
    if ((state.sortKey === 'median-latency-desc' || state.sortKey === 'median-latency-asc') && !visibleSystemColumns.has('median-latency')) {
      state.sortKey = 'time-desc';
      sortRuns(allRuns);
    }

    // Update header with dynamic metric columns
    updateTableHeader(metricsToShow);
    const headerRow = el('table-header-row');
    if (headerRow) {
      const latencyHeader = headerRow.querySelector('.col-latency');
      const medianLatencyHeader = headerRow.querySelector('.col-latency-median');
      if (latencyHeader) latencyHeader.style.display = visibleSystemColumns.has('latency') ? '' : 'none';
      if (medianLatencyHeader) medianLatencyHeader.style.display = visibleSystemColumns.has('median-latency') ? '' : 'none';
    }

    const visibleSystemColumnCount = visibleSystemColumns.size;
    const visibleTraceMetricCount = visibleTraceMetrics.length;
    const colCount = getRunsTableColumnCount(
      metricsToShow.length,
      visibleSystemColumnCount,
      visibleTraceMetricCount,
    );
    if (allRuns.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="${colCount}" style="text-align:center;padding:2rem;color:var(--text-muted);">
            No runs match current filters
          </td>
        </tr>
      `;
      renderTablePagination({ totalRuns: 0, pageCount: 1, start: 0, end: 0 });
      const selectAllCheckbox = el('select-all');
      if (selectAllCheckbox) {
        selectAllCheckbox.checked = false;
        selectAllCheckbox.indeterminate = false;
      }
      return;
    }

    const pagination = getTablePageSlice(allRuns);
    const runs = pagination.pageRuns;

    // #7: Group runs by task + base timestamp (same batch = same task, same YYMMDD-HHMM)
    const groupMap = {};  // groupKey -> { runs: [{run, idx}], ... }
    const runGroupKeys = [];
    runs.forEach((r, idx) => {
      const key = extractRunTimestampGroup(r);
      runGroupKeys.push(key);
      if (key) {
        if (!groupMap[key]) groupMap[key] = [];
        groupMap[key].push({ run: r, idx });
      }
    });

    // Only groups with >1 run are real groups
    const realGroups = {};
    for (const [key, members] of Object.entries(groupMap)) {
      if (members.length > 1) realGroups[key] = members;
    }

    // Track which groups are collapsed (default: collapsed)
    if (!state._collapsedGroups) state._collapsedGroups = {};

    let lastGroupKey = null;
    let groupCounter = 0;
    tbody.innerHTML = runs.map((run, pageIdx) => {
      const idx = pagination.start + pageIdx;
      const groupKey = runGroupKeys[pageIdx];
      const isGrouped = groupKey && realGroups[groupKey];
      const isFirstInGroup = isGrouped && groupKey !== lastGroupKey;
      const nextGroupKey = runGroupKeys[pageIdx + 1];
      const isLastInGroup = isGrouped && nextGroupKey !== groupKey;
      let groupHeaderHtml = '';

      if (isFirstInGroup) {
        groupCounter++;
        const groupId = `rg_${groupCounter}`;
        const members = realGroups[groupKey];
        const groupSize = members.length;
        // Derive group title: task_name is always available; show user-provided
        // run_name only if it differs from the auto-generated task-model pattern
        const configRunName = run.run_name || '';
        // Strip timestamp+counter suffix, then strip model suffix to get user's intent
        let userBaseName = configRunName.replace(/-\d{6}-\d{4}(?:-\d+)?$/, '');
        // Collect all model names in this group to strip them from the base name
        const groupModels = [...new Set(members.map(m => stripModelProvider(m.run.model_name || '')).filter(Boolean))];
        for (const model of groupModels) {
          if (userBaseName.endsWith('-' + model)) {
            userBaseName = userBaseName.slice(0, -(model.length + 1));
          }
        }
        const taskName = run.task_name || '';
        let baseLabel;
        if (userBaseName && userBaseName !== taskName) {
          baseLabel = `${userBaseName} · ${taskName}`;
        } else {
          baseLabel = taskName || userBaseName || 'Group';
        }
        // Extract timestamp for display
        const tsSource = run.run_name || run.external_run_id || '';
        const tsMatch = tsSource.match(/(\d{6})-(\d{4})(?:-\d+)?$/);
        let tsLabel = '';
        if (tsMatch) {
          const [, yymmdd, hhmm] = tsMatch;
          const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
          const mm = yymmdd.slice(2,4); const dd = yymmdd.slice(4,6);
          const monthName = months[parseInt(mm, 10) - 1] || mm;
          tsLabel = ` · ${monthName} ${parseInt(dd, 10)} · ${hhmm.slice(0,2)}:${hhmm.slice(2)}`;
        }
        const isCollapsed = state._collapsedGroups[groupKey] === true; // default expanded
        const arrow = isCollapsed ? '▶' : '▼';
        const memberFilePaths = members.map(m => m.run.file_path);
        const selectedGroupRunCount = memberFilePaths.filter(filePath => state.selectedRuns.has(filePath)).length;
        const allGroupRunsSelected = selectedGroupRunCount === memberFilePaths.length;
        const someGroupRunsSelected = selectedGroupRunCount > 0 && !allGroupRunsSelected;

        groupHeaderHtml = `<tr class="run-group-header${isCollapsed ? ' collapsed' : ''}" data-group-key="${escapeHtml(groupKey)}" data-group-id="${groupId}">
          <td colspan="${colCount}" style="padding:6px 0;background:var(--bg-elevated);cursor:pointer;user-select:none;">
            <div class="group-header-content">
              <div class="group-header-main">
                <span class="group-toggle-arrow">${arrow}</span>
                <label class="custom-checkbox group-select-checkbox" onclick="event.stopPropagation();" title="Select all runs in this group">
                  <input
                    type="checkbox"
                    class="group-select-input"
                    data-group-files='${JSON.stringify(memberFilePaths)}'
                    ${allGroupRunsSelected ? 'checked' : ''}
                    ${someGroupRunsSelected ? 'data-indeterminate="true"' : ''}
                  />
                  <span class="checkmark"></span>
                </label>
                <span class="group-header-title" title="${escapeHtml(baseLabel)}">${escapeHtml(baseLabel)}</span>
                ${tsLabel ? `<span class="group-header-timestamp">${tsLabel}</span>` : ''}
                <span class="group-header-count">${groupSize} runs</span>
              </div>
              <div class="group-header-actions">
                <button class="group-compare-btn action-btn" data-group-files='${JSON.stringify(memberFilePaths)}' onclick="event.stopPropagation();">Compare</button>
              </div>
            </div>
          </td>
        </tr>`;
      }
      lastGroupKey = groupKey;

      // If this run belongs to a collapsed group, hide it (header row stays visible)
      const isCollapsed = isGrouped && state._collapsedGroups[groupKey] === true;
      const hiddenAttr = (isGrouped && isCollapsed) ? 'style="display:none;"' : '';
      const groupDataAttr = isGrouped ? `data-member-of="${escapeHtml(groupKey)}"` : '';
      const dt = formatDate(run.timestamp);
      const durationText = formatDurationMs(run.duration_ms);
      const isSelected = state.selectedRuns.has(run.file_path);
      const isFocused = idx === state.focusedIndex;
      const rowClasses = [
        isSelected ? 'selected' : '',
        isFocused ? 'focused' : '',
        isGrouped ? 'grouped-run' : '',
        isGrouped && isFirstInGroup ? 'grouped-run-start' : '',
        isGrouped && isLastInGroup ? 'grouped-run-end' : '',
      ].filter(Boolean).join(' ');

      // Generate metric columns
      const metricCells = metricsToShow.map(metric => {
        const value = run.metric_averages?.[metric];
        if (value === undefined || value === null) {
          return `<td class="col-metric-value"><span class="metric-na">—</span></td>`;
        }
        const mType = state._metricTypes?.[metric] || window.QymMetrics.detectMetricTypeFromAvg(value);
        const metricClass = window.QymMetrics.getMetricColorClass(value, mType);
        const peerValues = getRunComboPeerValues(allRuns, run, candidate => candidate.metric_averages?.[metric]);
        const display = window.QymMetrics.formatMetricValueSmart(value, mType, peerValues);
        // Repeat runs: the ±CI half-width is the visual marker that this
        // value is a mean over samples passes.
        const ciHalf = (run.samples > 1 && run.metric_cis) ? run.metric_cis[metric] : null;
        const ciHtml = (typeof ciHalf === 'number')
          ? `<span class="metric-ci" title="95% CI over ${run.samples} passes">±${window.QymMetrics.formatNumericValue(ciHalf)}</span>`
          : '';
        return `<td class="col-metric-value"><span class="metric-score ${metricClass}">${display}</span>${ciHtml}</td>`;
      }).join('');

      const status = run.status || '';
      const langfuseUrl = run.langfuse_url;
      const approval = run.approval || null;

      const globalRole = (state.currentUser && state.currentUser.role) || '';
      const projectRole = (state.currentProject && state.currentProject.role) || '';
      const isOwner = !!(state.currentUser && run.owner && run.owner.id === state.currentUser.id);
      const isProjectManager = globalRole === 'ADMIN' || projectRole === 'MANAGER';
      const canApprove = isProjectManager && status === 'SUBMITTED';
      const canUnapprove = isProjectManager && status === 'APPROVED';
      const canUnreject = isProjectManager && status === 'REJECTED';
      const canSubmit = isOwner && (status === 'COMPLETED' || status === 'FAILED' || status === 'REJECTED');
      const canDelete = globalRole === 'ADMIN' || isProjectManager || isOwner;
      const progressText = (status === 'RUNNING' && run.progress_total)
        ? `${run.progress_completed || 0}/${run.progress_total}`
        : (status === 'RUNNING' ? `${run.progress_completed || 0}` : '');
      const progressPctText = (status === 'RUNNING' && typeof run.progress_pct === 'number')
        ? `${Math.round(run.progress_pct * 100)}%`
        : '';
      // Repeat runs: show which pass is executing while live.
      const passText = (run.samples > 1 && (status === 'RUNNING' || status === 'PENDING'))
        ? ` • pass ${Math.min((run.last_completed_pass || 0) + 1, run.samples)}/${run.samples}`
        : '';

      // Build status tooltip with approval info
      let statusTooltip = status;
      if (approval && approval.decision_by) {
        statusTooltip = `${status} by ${approval.decision_by.display_name || approval.decision_by.email}`;
        if (approval.comment) {
          statusTooltip += `\n"${approval.comment}"`;
        }
      }

      return `${groupHeaderHtml}
        <tr data-idx="${idx}" data-file="${encodeURIComponent(run.file_path)}" ${groupDataAttr} ${hiddenAttr}
            class="${rowClasses}">
          <td class="col-select" onclick="event.stopPropagation()">
            <label class="custom-checkbox">
              <input type="checkbox" class="row-checkbox" ${isSelected ? 'checked' : ''} />
              <span class="checkmark"></span>
            </label>
          </td>
          <td class="col-status">
            ${status ? `<span class="status-badge status-${status}" title="${escapeHtml(statusTooltip)}">${status}${passText}${progressPctText ? ` • ${progressPctText}` : ''}${progressText ? ` • ${progressText}` : ''}</span>` : ''}${(run.error_count > 0 && status !== 'RUNNING' && status !== 'PENDING') ? `<span class="status-errors" title="${run.error_count} item${run.error_count === 1 ? '' : 's'} errored">${run.error_count}⚠</span>` : ''}${(run.total_retries > 0 && status !== 'RUNNING' && status !== 'PENDING') ? `<span class="status-retries" title="${run.total_retries} total retr${run.total_retries === 1 ? 'y' : 'ies'} across all items">${run.total_retries}↻</span>` : ''}
          </td>
          <td class="col-run">
            ${run.samples > 1 ? `<span class="samples-toggle" data-run-id="${run.run_id}" title="Show per-pass results" onclick="event.stopPropagation()">▶</span>` : ''}<span class="run-id" title="${run.run_id}">${run.external_run_id ? truncateText(run.external_run_id, 30) : run.run_id.substring(0, 8)}</span>${run.samples > 1 ? `<span class="samples-pill" title="Repeat run: every item evaluated ${run.samples} times">×${run.samples}</span>` : ''}
          </td>
          <td class="col-task">
            <span class="tag task" title="${escapeHtml(run.task_name || '')}">${run.task_name ? escapeHtml(run.task_name) : '—'}</span>
          </td>
          <td class="col-model">
            <span class="tag model" title="${run.model_name}">
              <span class="model-color-dot" style="background:${CHART_COLORS[state.allModels.indexOf(getRunModelKey(run)) % CHART_COLORS.length]}"></span>
              ${renderModelLabelForRun(run)}
            </span>
          </td>
          <td class="col-dataset">
            <span class="tag" title="${run.dataset_name}">${truncateText(run.dataset_name, 25)}${window.QymShell ? QymShell.datasetVersionInline(run.dataset_version) + QymShell.datasetAliasTags(run.dataset_aliases) : ''}</span>
          </td>
          <td class="col-version">
            ${run.git_commit ? `<span class="version-badge" title="${run.git_branch ? run.git_branch + '/' : ''}${run.git_commit}">${run.git_branch ? run.git_branch + '/' : ''}${run.git_commit}</span>` : '<span style="color:var(--text-muted)">—</span>'}
          </td>
          ${metricCells}${visibleTraceMetrics.length > 0 ? '<td class="col-trace-separator"></td>' : ''}
          ${visibleSystemColumns.has('latency') ? `<td class="col-latency">
            <span class="latency-value">${run.avg_latency_ms ? formatLatency(run.avg_latency_ms) : '—'}</span>
          </td>` : ''}
          ${visibleSystemColumns.has('median-latency') ? `<td class="col-latency-median">
            <span class="latency-value">${run.median_latency_ms ? formatLatency(run.median_latency_ms) : '—'}</span>
          </td>` : ''}${(() => {
            if (visibleTraceMetrics.length === 0) return '';
            const ts = run.trace_stats;
            return visibleTraceMetrics.map(tm => {
              const v = ts ? ts[tm.key] : null;
              return renderTraceMetricTableCell(tm, v);
            }).join('');
          })()}
          <td class="col-owner">
            ${run.owner ? `
              <span class="owner-name" title="${run.owner.email}">
                <span class="owner-avatar">${getInitials(run.owner.display_name)}</span>
                ${truncateText(run.owner.display_name, 15)}
              </span>
            ` : '<span style="color:var(--text-muted)">—</span>'}
          </td>
          <td class="col-time">
            <span class="timestamp" title="${escapeHtml(dt.full)}">
              <span class="date">${dt.date}</span>
              <span class="timestamp-sep">·</span>
              <span class="time">${dt.time}</span>
            </span>
          </td>
          <td class="col-duration">
            <span class="duration-value">${durationText}</span>
          </td>
          <td class="col-actions">
            ${(canApprove || canUnapprove || canUnreject) ? `
              <div class="actions-dropdown" onclick="event.stopPropagation()">
                <button class="actions-trigger workflow-trigger" title="${(canUnapprove || canUnreject) ? 'Review decision actions' : 'Review'}">
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                    <polyline points="14 2 14 8 20 8"></polyline>
                    <line x1="16" y1="13" x2="8" y2="13"></line>
                    <line x1="16" y1="17" x2="8" y2="17"></line>
                  </svg>
                </button>
                <div class="actions-menu">
                  ${canApprove ? `<a href="#" class="actions-item approve-run approve">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                      <polyline points="20 6 9 17 4 12"></polyline>
                    </svg>
                    <span>Approve</span>
                  </a>
                  <a href="#" class="actions-item reject-run reject">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                      <line x1="18" y1="6" x2="6" y2="18"></line>
                      <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                    <span>Reject</span>
                  </a>` : ''}
                  ${canUnapprove ? `<a href="#" class="actions-item unapprove-run reject">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74"></path>
                      <path d="M3 3v6h6"></path>
                    </svg>
                    <span>Unapprove</span>
                  </a>` : ''}
                  ${canUnreject ? `<a href="#" class="actions-item unreject-run approve">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74"></path>
                      <path d="M3 3v6h6"></path>
                    </svg>
                    <span>Unreject</span>
                  </a>` : ''}
                </div>
              </div>
            ` : ''}
            ${canSubmit ? `
              <a href="#" class="action-icon submit-run" title="Submit for Approval" onclick="event.stopPropagation()">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                  <line x1="22" y1="2" x2="11" y2="13"></line>
                  <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                </svg>
              </a>
            ` : ''}
            ${langfuseUrl ? `
              <a href="${langfuseUrl}" target="_blank" class="action-icon langfuse-icon" title="View in Langfuse" onclick="event.stopPropagation()">
                <img src="/static/langfuse-color.svg" alt="Langfuse" width="16" height="16" />
              </a>
            ` : ''}
            ${canDelete ? `
            <a href="#" class="action-icon delete-run" title="Delete" onclick="event.stopPropagation()">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
              </svg>
            </a>
            ` : ''}
          </td>
        </tr>
      `;
    }).join('');

    // Update sort indicators
    updateSortIndicators();

    // Wire events
    tbody.querySelectorAll('tr[data-idx]').forEach(tr => {
      const idx = parseInt(tr.dataset.idx);
      const filePath = decodeURIComponent(tr.dataset.file);
      const run = state.filteredRuns[idx];

      const checkbox = tr.querySelector('.row-checkbox');
      if (checkbox) {
        checkbox.addEventListener('click', (e) => {
          e.stopPropagation();
        });
        checkbox.addEventListener('change', (e) => {
          toggleSelect(filePath);
        });
      }

      tr.querySelector('.run-id').addEventListener('click', (e) => {
        e.stopPropagation();
        openRun(filePath, e);
      });
      tr.querySelector('.run-id').addEventListener('auxclick', (e) => {
        if (e.button !== 1) return;
        e.preventDefault();
        e.stopPropagation();
        openRun(filePath, e);
      });

      const closeDropdown = () => {
        tr.querySelector('.actions-dropdown')?.classList.remove('open');
      };

      const submitBtn = tr.querySelector('.submit-run');
      if (submitBtn) submitBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        closeDropdown();
        try {
          const resp = await fetch(apiUrl(`v1/runs/${encodeURIComponent(run.run_id)}/submit`), { method: 'POST' });
          if (resp.ok) {
            showToast('success', 'Submitted', 'Run submitted for approval');
          } else {
            showToast('error', 'Submit Failed', 'Could not submit run');
          }
          await fetchRuns({ refreshAllPages: true });
        } catch (err) {
          console.error('Submit failed', err);
          showToast('error', 'Submit Failed', err.message || 'Could not submit run');
        }
      });

      const approveBtn = tr.querySelector('.approve-run');
      if (approveBtn) approveBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        closeDropdown();
        showWorkflowModal('approve', run.run_id, run.task_name);
      });

      const rejectBtn = tr.querySelector('.reject-run');
      if (rejectBtn) rejectBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        closeDropdown();
        showWorkflowModal('reject', run.run_id, run.task_name);
      });

      const unapproveBtn = tr.querySelector('.unapprove-run');
      if (unapproveBtn) unapproveBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        closeDropdown();
        showWorkflowModal('unapprove', run.run_id, run.task_name);
      });

      const unrejectBtn = tr.querySelector('.unreject-run');
      if (unrejectBtn) unrejectBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        closeDropdown();
        showWorkflowModal('unreject', run.run_id, run.task_name);
      });

      const deleteBtn = tr.querySelector('.delete-run');
      if (deleteBtn) deleteBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        closeDropdown();
        confirmDeleteRun(filePath, run.run_id);
      });

      // Actions dropdown toggle
      const actionsDropdown = tr.querySelector('.actions-dropdown');
      const actionsTrigger = tr.querySelector('.actions-trigger');
      if (actionsTrigger && actionsDropdown) {
        actionsTrigger.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          // Close any other open dropdowns
          document.querySelectorAll('.actions-dropdown.open').forEach(d => {
            if (d !== actionsDropdown) d.classList.remove('open');
          });
          actionsDropdown.classList.toggle('open');
        });
      }

      tr.addEventListener('click', () => {
        state.focusedIndex = idx;
        renderTableView();
      });

      tr.addEventListener('dblclick', () => {
        openRun(filePath);
      });
    });

    // #7: Wire group header click to toggle collapse
    // Convention: state._collapsedGroups[key] === true means collapsed; absent/false means expanded
    tbody.querySelectorAll('.run-group-header').forEach(header => {
      header.addEventListener('click', () => {
        const groupKey = header.dataset.groupKey;
        if (!groupKey) return;
        const wasCollapsed = state._collapsedGroups[groupKey] === true;
        state._collapsedGroups[groupKey] = !wasCollapsed;
        const nowExpanded = !state._collapsedGroups[groupKey];
        header.classList.toggle('collapsed', !nowExpanded);
        const arrow = header.querySelector('.group-toggle-arrow');
        if (arrow) arrow.textContent = nowExpanded ? '▼' : '▶';
        tbody.querySelectorAll(`tr[data-member-of="${groupKey}"]`).forEach(row => {
          row.style.display = nowExpanded ? '' : 'none';
        });
      });
    });

    // Repeat runs: expand a ×k row into its per-pass slices + group metrics.
    // Data is lazy-loaded on first expand (/passes + /group-metrics); expansion
    // state + fetched markup survive the live-polling re-renders.
    state._samplesExpanded = state._samplesExpanded || {};
    state._samplesDetailHtml = state._samplesDetailHtml || {};

    function insertSamplesDetail(runId, row, html) {
      const detail = document.createElement('tr');
      detail.className = 'samples-detail-row';
      detail.dataset.samplesFor = runId;
      detail.innerHTML = `<td colspan="${row.children.length}" class="samples-detail-cell">${html}</td>`;
      row.insertAdjacentElement('afterend', detail);
      return detail;
    }

    async function loadSamplesDetail(runId, detail) {
      try {
        const [passesRes, groupRes] = await Promise.all([
          fetch(apiUrl(`api/runs/${encodeURIComponent(runId)}/passes`)),
          fetch(apiUrl(`api/runs/${encodeURIComponent(runId)}/group-metrics`)),
        ]);
        const passes = await passesRes.json();
        const group = await groupRes.json();
        const html = renderSamplesDetail(passes, group);
        state._samplesDetailHtml[runId] = html;
        if (detail.isConnected) detail.querySelector('td').innerHTML = html;
      } catch (err) {
        if (detail.isConnected) {
          detail.querySelector('td').innerHTML =
            `<span style="color:var(--error);font-size:var(--font-sm)">Failed to load pass data</span>`;
        }
      }
    }

    tbody.querySelectorAll('.samples-toggle').forEach(toggle => {
      const runId = toggle.dataset.runId;
      // Restore expansions the re-render just wiped.
      if (runId && state._samplesExpanded[runId]) {
        const row = toggle.closest('tr');
        if (row && !tbody.querySelector(`tr.samples-detail-row[data-samples-for="${runId}"]`)) {
          toggle.textContent = '▼';
          const cached = state._samplesDetailHtml[runId];
          const detail = insertSamplesDetail(
            runId, row,
            cached || `<span style="color:var(--text-muted);font-size:var(--font-sm)">Loading passes…</span>`
          );
          // Live runs: refresh the pass data on every re-render pass.
          loadSamplesDetail(runId, detail);
        }
      }
      toggle.addEventListener('click', async (e) => {
        e.stopPropagation();
        const row = toggle.closest('tr');
        if (!runId || !row) return;
        const existing = tbody.querySelector(`tr.samples-detail-row[data-samples-for="${runId}"]`);
        if (existing) {
          const hidden = existing.style.display === 'none';
          existing.style.display = hidden ? '' : 'none';
          toggle.textContent = hidden ? '▼' : '▶';
          state._samplesExpanded[runId] = hidden;
          return;
        }
        toggle.textContent = '▼';
        state._samplesExpanded[runId] = true;
        const detail = insertSamplesDetail(
          runId, row,
          `<span style="color:var(--text-muted);font-size:var(--font-sm)">Loading passes…</span>`
        );
        await loadSamplesDetail(runId, detail);
      });
    });

    // #7: Wire "Compare All" buttons on group headers
    tbody.querySelectorAll('.group-compare-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        try {
          const files = JSON.parse(btn.dataset.groupFiles);
          if (Array.isArray(files) && files.length >= 2) {
            sessionStorage.setItem('compareRuns', JSON.stringify(files));
            const params = files.map(f => 'runs=' + encodeURIComponent(f)).join('&');
            navigateTo(apiUrl('compare?' + params));
          }
        } catch {}
      });
    });

    tbody.querySelectorAll('.group-select-input').forEach(input => {
      if (input.dataset.indeterminate === 'true') input.indeterminate = true;
      input.addEventListener('click', (e) => {
        e.stopPropagation();
      });
      input.addEventListener('change', (e) => {
        e.stopPropagation();
        try {
          toggleGroupSelection(JSON.parse(input.dataset.groupFiles));
        } catch {}
      });
    });

    renderTablePagination(pagination);

    const selectAllCheckbox = el('select-all');
    if (selectAllCheckbox) {
      const visibleFilePaths = runs.map(run => run.file_path);
      const selectedCount = visibleFilePaths.filter(filePath => state.selectedRuns.has(filePath)).length;
      selectAllCheckbox.checked = visibleFilePaths.length > 0 && selectedCount === visibleFilePaths.length;
      selectAllCheckbox.indeterminate = selectedCount > 0 && selectedCount < visibleFilePaths.length;
    }
  }

  // ═══════════════════════════════════════════════════
  // RENDERING: GRID VIEW
  // ═══════════════════════════════════════════════════

  function renderGridView() {
    const runs = state.filteredRuns;
    const container = el('grid-view');

    if (runs.length === 0) {
      container.innerHTML = `<div style="text-align:center;padding:2rem;color:var(--text-muted);">No runs match current filters</div>`;
      return;
    }

    container.innerHTML = runs.map((run, idx) => {
      const dt = formatDate(run.timestamp);
    const successClass = getSuccessClass(run.success_rate);
      const isSelected = state.selectedRuns.has(run.file_path);
      const successPct = run.success_rate * 100;
      const errorPct = (run.error_count / (run.total_items || 1)) * 100;

    return `
        <div class="grid-card ${isSelected ? 'selected' : ''}" data-file="${encodeURIComponent(run.file_path)}">
          <div class="grid-card-header">
            <span class="grid-card-title" title="${run.run_id}">${stripProviderFromRunId(run.run_id)}</span>
            <span class="grid-card-success ${successClass}">${formatPercent(run.success_rate)}</span>
          </div>
          <div class="grid-card-meta">
            <span class="tag task">${run.task_name}</span>
            <span class="tag model" title="${run.model_name}">${renderModelLabelForRun(run)}</span>
        </div>
          <div class="grid-card-bar">
            <div class="segment success" style="width:${successPct}%"></div>
            <div class="segment error" style="width:${errorPct}%"></div>
          </div>
          <div class="grid-card-footer">
            <span>${run.total_items} items</span>
            <span>${dt.date} ${dt.time}</span>
          </div>
        </div>
      `;
    }).join('');

    container.querySelectorAll('.grid-card').forEach(card => {
      const filePath = decodeURIComponent(card.dataset.file);
      card.addEventListener('click', () => toggleSelect(filePath));
      card.addEventListener('dblclick', () => openRun(filePath));
    });
  }

  // ═══════════════════════════════════════════════════
  // RENDERING: TIMELINE VIEW
  // ═══════════════════════════════════════════════════

  function renderTimelineView() {
    const runs = state.filteredRuns;
    const container = el('timeline-view');

    if (runs.length === 0) {
      container.innerHTML = `<div style="text-align:center;padding:2rem;color:var(--text-muted);">No runs match current filters</div>`;
      return;
    }

    // Group by date
    const byDate = {};
    for (const run of runs) {
      const key = formatDate(run.timestamp).iso;
      if (!byDate[key]) byDate[key] = [];
      byDate[key].push(run);
    }

    const sortedDates = Object.keys(byDate).sort().reverse();

    container.innerHTML = sortedDates.map(date => {
      const dayRuns = byDate[date];
      const dateLabel = new Date(date).toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });

      return `
        <div class="timeline-day">
          <div class="timeline-date">${dateLabel}</div>
          <div class="timeline-runs">
            ${dayRuns.map(run => {
              const dt = formatDate(run.timestamp);
              const successClass = getSuccessClass(run.success_rate);
              return `
                <div class="timeline-run" data-file="${encodeURIComponent(run.file_path)}">
                  <span class="timeline-time">${dt.time}</span>
                  <div class="timeline-info">
                    <span class="tag task">${run.task_name}</span>
                    <span class="tag model" title="${run.model_name}">${renderModelLabelForRun(run)}</span>
                    <span style="color:var(--text-muted);font-size:var(--font-sm);">${run.total_items} items</span>
                  </div>
                  <span class="timeline-success ${successClass}">${formatPercent(run.success_rate)}</span>
                </div>
              `;
            }).join('')}
          </div>
        </div>
      `;
    }).join('');

    container.querySelectorAll('.timeline-run').forEach(runEl => {
      const filePath = decodeURIComponent(runEl.dataset.file);
      runEl.addEventListener('click', (e) => openRun(filePath, e));
      runEl.addEventListener('auxclick', (e) => {
        if (e.button !== 1) return;
        e.preventDefault();
        openRun(filePath, e);
      });
    });
  }

  // ═══════════════════════════════════════════════════
  // RENDERING: STATUS & COMPARE
  // ═══════════════════════════════════════════════════

  function renderStatusBar() {
    const total = state.flatRuns.length;
    const filtered = state.filteredRuns.length;
    const selected = state.selectedRuns.size;
    const countText = filtered === total ? `${total} runs` : `${filtered} of ${total} runs`;

    const hasFilters = state.quickFilter !== 'all'
      || state.filterTasks.size > 0
      || (state.filterModels.size > 0)
      || state.filterDatasets.size > 0
      || state.filterStatuses.size > 0
      || state.filterVersions.size > 0
      || state.filterUsers.size > 0;

    let filterText = countText;
    if (hasFilters) {
      const parts = [];
      if (state.filterTasks.size > 0 && !state.filterTasks.has('__none__')) {
        parts.push(`task: ${summarizeFilterSelection(state.filterTasks)}`);
      }
      if (state.filterDatasets.size > 0 && !state.filterDatasets.has('__none__')) {
        parts.push(`dataset: ${summarizeFilterSelection(state.filterDatasets, getDatasetFilterLabel)}`);
      }
      if (state.filterModels.size > 0 && !state.filterModels.has('__none__')) {
        parts.push(`model: ${summarizeFilterSelection(state.filterModels, stripModelProvider)}`);
      } else if (state.filterModels.has('__none__')) {
        parts.push('model: none');
      }
      if (state.filterStatuses.size > 0 && !state.filterStatuses.has('__none__')) {
        parts.push(`status: ${summarizeFilterSelection(state.filterStatuses, (s) => isEmptyFilterValue(s) ? 'Empty / Missing' : s.charAt(0) + s.slice(1).toLowerCase())}`);
      }
      if (state.filterVersions.size > 0 && !state.filterVersions.has('__none__')) {
        parts.push(`version: ${summarizeFilterSelection(state.filterVersions)}`);
      }
      if (state.filterUsers.size > 0 && !state.filterUsers.has('__none__')) {
        parts.push(`user: ${summarizeFilterSelection(state.filterUsers, getOwnerFilterLabel)}`);
      } else if (state.filterUsers.has('__none__')) {
        parts.push('user: none');
      }
      if (state.quickFilter === 'today') parts.push('today');
      if (state.quickFilter === 'week') parts.push('last 7d');
      filterText = countText + (parts.length > 0 ? ` — ${parts.join(', ')}` : '');
    }

    if (el('status-filter')) el('status-filter').textContent = filterText;
    if (el('status-selected')) el('status-selected').textContent = `${selected} selected`;
  }

  function renderComparePanel() {
    const panel = el('compare-panel');
    const selected = state.selectedRuns;
    const cohortAnchor = Array.isArray(state.cohortAnchorRuns) ? state.cohortAnchorRuns : null;
    const isCohortMode = !!(cohortAnchor && cohortAnchor.length > 0);

    if (!panel) return;
    if (selected.size === 0 && !isCohortMode) {
      panel.style.display = 'none';
      return;
    }

    panel.style.display = 'block';
    const countEl = el('compare-count');
    if (countEl) {
      countEl.textContent = isCohortMode ? `${selected.size}/${cohortAnchor.length}` : selected.size;
    }

    const chips = el('compare-chips');
    const selectedRuns = state.flatRuns.filter(r => selected.has(r.file_path));
    const anchorRuns = isCohortMode
      ? cohortAnchor.map(filePath => state.flatRuns.find(run => run.file_path === filePath)).filter(Boolean)
      : [];

    // Hide Langfuse button - it's available in row actions
    const langfuseBtn = el('langfuse-btn');
    if (langfuseBtn) langfuseBtn.style.display = 'none';

    const compareBtn = el('compare-view');
    const cohortBtn = el('cohort-view');
    const clearBtn = el('compare-clear');
    const deleteBtn = el('delete-selected');
    const headerLabel = panel.querySelector('.compare-header > span');
    const subtitleEl = el('compare-subtitle');
    const hasOverlap = isCohortMode && selectedRuns.some(run => cohortAnchor.includes(run.file_path));

    if (headerLabel) {
      headerLabel.textContent = isCohortMode
        ? `⊕ COHORT B ${selected.size}/${cohortAnchor.length} RUNS`
        : `⊕ SELECTED ${selected.size} RUNS`;
    }
    if (subtitleEl) {
      subtitleEl.classList.remove('is-warning', 'is-ready');
      if (!isCohortMode) {
        subtitleEl.textContent = selected.size >= 2
          ? 'Ready to open a flat comparison, or lock this selection as Cohort A.'
          : 'Select runs, then use Compare for a flat comparison or Cohort for an explicit A vs B setup.';
      } else if (hasOverlap) {
        subtitleEl.textContent = 'Cohort B cannot include runs already locked in Cohort A.';
        subtitleEl.classList.add('is-warning');
      } else if (selected.size < cohortAnchor.length) {
        subtitleEl.textContent = `Cohort A is locked. Select ${cohortAnchor.length - selected.size} more run${cohortAnchor.length - selected.size === 1 ? '' : 's'} for Cohort B.`;
      } else if (selected.size === cohortAnchor.length) {
        subtitleEl.textContent = 'Cohort B is ready. Click Open Cohort to compare the two groups.';
        subtitleEl.classList.add('is-ready');
      }
    }
    if (compareBtn) compareBtn.style.display = isCohortMode ? 'none' : 'inline-block';
    if (cohortBtn) {
      cohortBtn.style.display = 'inline-block';
      cohortBtn.textContent = isCohortMode ? 'Open Cohort' : 'Cohort';
      cohortBtn.disabled = isCohortMode ? (selected.size !== cohortAnchor.length || hasOverlap) : (selected.size < 1);
      cohortBtn.title = isCohortMode
        ? (hasOverlap ? 'Cohort B cannot reuse runs from Cohort A' : `Select exactly ${cohortAnchor.length} runs for Cohort B`)
        : 'Lock the current selection as Cohort A';
    }
    if (clearBtn) clearBtn.textContent = isCohortMode ? 'Cancel Cohort' : 'Clear';
    if (deleteBtn) deleteBtn.style.display = isCohortMode ? 'none' : 'inline-block';

    // Show Submit button only if:
    // 1. User is not a manager (managers approve/reject, not submit)
    // 2. At least 1 run is selected
    // 3. ALL selected runs are submittable (COMPLETED, FAILED, or REJECTED status)
    const publishBtn = el('publish-selected');
    if (publishBtn) {
      const role = (state.currentUser && state.currentUser.role) || '';
      const isManager = role === 'MANAGER';
      const allSubmittable = selectedRuns.length > 0 && selectedRuns.every(r => {
        const status = r.status || '';
        return status === 'COMPLETED' || status === 'FAILED' || status === 'REJECTED';
      });
      publishBtn.style.display = (!isManager && allSubmittable && !isCohortMode) ? 'inline-block' : 'none';
      publishBtn.textContent = 'Submit';
    }

    chips.innerHTML = [
      ...anchorRuns.map(run => `
        <span class="compare-chip is-cohort-a">
          <span title="${escapeHtml(run.run_id)}">${escapeHtml(getCohortRunDisplayName(run.file_path) || run.run_id)}</span>
        </span>
      `),
      ...selectedRuns.map(run => `
        <span class="compare-chip is-cohort-b">
          <span title="${escapeHtml(run.run_id)}">${escapeHtml(getCohortRunDisplayName(run.file_path) || run.run_id)}</span>
          <span class="remove" data-file="${encodeURIComponent(run.file_path)}">×</span>
        </span>
      `),
    ].join('');

    chips.querySelectorAll('.remove').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const filePath = decodeURIComponent(btn.dataset.file);
        state.selectedRuns.delete(filePath);
        render();
      });
    });
  }

  // ═══════════════════════════════════════════════════
  // MAIN RENDER
  // ═══════════════════════════════════════════════════

  function render() {
    // Re-populate dropdowns with applicable values for current filter state
    populateFilterDropdowns();

    const loading = el('loading');
    const empty = el('empty');
    const chartsView = el('charts-view');
    const tableView = el('table-view');
    const gridView = el('grid-view');
    const timelineView = el('timeline-view');
    const modelsView = el('models-view');

    if (!state.runs) {
      loading.style.display = 'flex';
      empty.style.display = 'none';
      chartsView.style.display = 'none';
      tableView.style.display = 'none';
      gridView.style.display = 'none';
      timelineView.style.display = 'none';
      if (modelsView) modelsView.style.display = 'none';
      return;
    }

    loading.style.display = 'none';

    const runs = filterRuns();
    const tableFilterKey = getTableFilterKey();
    if (tableFilterKey !== state.tableFilterKey) {
      state.tableFilterKey = tableFilterKey;
      state.tablePage = 1;
      state.focusedIndex = -1;
    }

    if (state.flatRuns.length === 0) {
      const tbody = el('runs-tbody');
      if (tbody) tbody.innerHTML = '';
      renderTablePagination({ totalRuns: 0, pageCount: 1, start: 0, end: 0 });
      const selectAllCheckbox = el('select-all');
      if (selectAllCheckbox) {
        selectAllCheckbox.checked = false;
        selectAllCheckbox.indeterminate = false;
      }
      empty.style.display = 'flex';
      chartsView.style.display = 'none';
      tableView.style.display = 'none';
      gridView.style.display = 'none';
      timelineView.style.display = 'none';
      if (modelsView) modelsView.style.display = 'none';
      return;
    }

    empty.style.display = 'none';

    // Recompute chart data before rendering display controls; grouped column visibility is chart-mode dependent.
    state.chartData = computeChartData(state.filteredRuns);

    const metricSourceRuns = state.filteredRuns.length > 0 ? state.filteredRuns : state.flatRuns;
    const availableMetrics = getAvailableMetricsForRuns(metricSourceRuns);
    populateMetricVisibility(availableMetrics, metricSourceRuns);

    const displayTools = el('display-tools');
    const metricVisibilityDropdown = el('metric-visibility-dropdown');
    const modelsStatVisibilityDropdown = el('models-stat-visibility-dropdown');
    const showDisplayTools = state.currentView === 'table' || state.currentView === 'charts';
    if (displayTools) {
      displayTools.style.display = showDisplayTools ? 'flex' : 'none';
    }
    if (!showDisplayTools && metricVisibilityDropdown) {
      metricVisibilityDropdown.classList.remove('open');
    }
    if (state.currentView !== 'models' && modelsStatVisibilityDropdown) {
      modelsStatVisibilityDropdown.classList.remove('open');
    }

    // Show current view (Charts, Table/Runs, or Models)
    if (chartsView) chartsView.style.display = state.currentView === 'charts' ? 'block' : 'none';
    if (tableView) tableView.style.display = state.currentView === 'table' ? 'block' : 'none';
    if (gridView) gridView.style.display = 'none';
    if (timelineView) timelineView.style.display = 'none';
    if (modelsView) modelsView.style.display = state.currentView === 'models' ? 'block' : 'none';
    const tablePagination = el('table-pagination');
    if (tablePagination) tablePagination.style.display = state.currentView === 'table' ? 'flex' : 'none';

    // Render current view
    switch (state.currentView) {
      case 'charts':
        renderChartsView();
        break;
      case 'table':
        renderTableView();
        break;
      case 'grid':
        renderGridView();
        break;
      case 'timeline':
        renderTimelineView();
        break;
      case 'models':
        renderModelsView();
        break;
    }

    renderStatsBar();
    renderStatusBar();
    renderComparePanel();
    updateFilterUI();
  }

  // ═══════════════════════════════════════════════════
  // FILTER UI HELPERS
  // ═══════════════════════════════════════════════════

  function countActiveFilters() {
    let n = 0;
    if (state.filterTasks.size > 0) n++;
    if (state.filterModels.size > 0) n++;
    if (state.filterStatuses.size > 0) n++;
    if (state.filterVersions.size > 0) n++;
    if (state.filterDatasets.size > 0) n++;
    if (state.filterUsers.size > 0) n++;
    if (state.quickFilter !== 'all') n++;
    return n;
  }

  function updateFilterUI() {
    // Clear button
    const clearBtn = el('clear-all-filters');
    const countBadge = el('active-filter-count');
    const n = countActiveFilters();
    if (clearBtn) {
      clearBtn.classList.toggle('is-visible', n > 0);
      clearBtn.setAttribute('aria-hidden', n > 0 ? 'false' : 'true');
      if (countBadge) countBadge.textContent = n;
    }
  }

  function clearAllFilters() {
    state.filterTasks.clear();
    state.filterModels.clear();
    state.filterStatuses.clear();
    state.filterVersions.clear();
    state.filterDatasets.clear();
    state.filterUsers.clear();
    state.quickFilter = 'all';
    $$('.filter-btn').forEach(b => b.classList.toggle('active', b.dataset.filter === 'all'));
    populateFilterDropdowns();
    render();
  }

  // ═══════════════════════════════════════════════════
  // RENDERING: MODELS VIEW
  // ═══════════════════════════════════════════════════

  async function renderModelsView() {
    const modelsEmpty = el('models-empty');
    const modelsGrid = el('models-grid');
    const modelsRanking = el('models-ranking');
    const modelsStatVisibilityWrapper = el('models-stat-visibility-wrapper');

    // Populate dropdowns if not already populated
    populateModelsViewDropdowns();

    const mvs = state.modelsViewState;

    // Use global filters for task and dataset
    // Models view requires exactly one task and one dataset.
    // If the filter explicitly selects one, use it; otherwise infer from
    // the currently visible (filtered) runs — when all filters narrow to a
    // single task/dataset the view should render automatically.
    let selectedTask = state.filterTasks.size === 1 && !state.filterTasks.has('__none__') ? [...state.filterTasks][0] : '';
    let selectedDataset = state.filterDatasets.size === 1 && !state.filterDatasets.has('__none__') ? [...state.filterDatasets][0] : '';

    if (!selectedTask || !selectedDataset) {
      const uniqueTasks = new Set(state.filteredRuns.map(r => r.task_name));
      const uniqueDatasets = new Set(state.filteredRuns.map(r => getRunDatasetKey(r)));
      if (!selectedTask && uniqueTasks.size === 1) selectedTask = [...uniqueTasks][0];
      if (!selectedDataset && uniqueDatasets.size === 1) selectedDataset = [...uniqueDatasets][0];
    }

    // If no task+dataset selected, show empty state
    if (!selectedTask || !selectedDataset) {
      if (modelsEmpty) modelsEmpty.style.display = 'flex';
      if (modelsGrid) modelsGrid.innerHTML = '';
      if (modelsRanking) modelsRanking.style.display = 'none';
      if (modelsStatVisibilityWrapper) modelsStatVisibilityWrapper.style.display = 'none';
      return;
    }

    if (modelsEmpty) modelsEmpty.style.display = 'none';

    // Start from the globally filtered run set so version, model, status, user,
    // and quick-date filters all constrain the Models view consistently.
    const matchingRuns = state.filteredRuns.filter(r => {
      if (!matchesFilterSelection(new Set([selectedTask]), r.task_name)) return false;
      if (!matchesFilterSelection(new Set([selectedDataset]), getRunDatasetKey(r))) return false;
      return true;
    });

    if (matchingRuns.length === 0) {
      if (modelsGrid) modelsGrid.innerHTML = '<div class="models-empty"><h3>No runs found</h3><p>No runs match the selected task and dataset</p></div>';
      if (modelsRanking) modelsRanking.style.display = 'none';
      if (modelsStatVisibilityWrapper) modelsStatVisibilityWrapper.style.display = 'none';
      return;
    }

    // Group runs by model
    const runsByModel = {};
    for (const run of matchingRuns) {
      const modelKey = getRunModelKey(run);
      if (!runsByModel[modelKey]) {
        runsByModel[modelKey] = [];
      }
      runsByModel[modelKey].push(run);
    }

    // Sort runs within each model by date (newest first)
    for (const model of Object.keys(runsByModel)) {
      runsByModel[model].sort((a, b) => b._date - a._date);
    }

    // Select K runs per model
    const globalK = parseInt(mvs.globalK) || 5;
    const selectedRunsByModel = {};
    for (const model of Object.keys(runsByModel)) {
      const customSelection = mvs.modelRunSelections[model];
      if (customSelection && customSelection.length > 0) {
        // Use custom selection, filter to only valid runs
        const validPaths = new Set(runsByModel[model].map(r => r.file_path));
        selectedRunsByModel[model] = customSelection
          .filter(fp => validPaths.has(fp))
          .slice(0, globalK);
      } else {
        // Use most recent K runs
        selectedRunsByModel[model] = runsByModel[model].slice(0, globalK).map(r => r.file_path);
      }
    }

    // Detect if metric is boolean
    detectModelsViewMetricType(matchingRuns, mvs.selectedMetric);
    populateModelsStatVisibility(matchingRuns);

    const models = Object.keys(runsByModel);
    const modelSelections = models.map((model) => {
      const selectedPaths = selectedRunsByModel[model];
      const selectedRuns = runsByModel[model].filter(r => selectedPaths.includes(r.file_path));
      return { model, selectedPaths, selectedRuns };
    });
    const traceSourceRuns = modelSelections.flatMap(({ selectedRuns }) => selectedRuns);
    const requestKey = [
      selectedTask,
      selectedDataset,
      mvs.selectedMetric,
      String(mvs.threshold),
      String(mvs.metricIsBoolean),
      String(globalK),
      ...modelSelections
        .map(({ model, selectedPaths }) => `${model}:${selectedPaths.slice().sort().join(',')}`)
        .sort(),
    ].join('||');

    mvs.visibleTraceMetrics = _traceMetricsForRuns(traceSourceRuns);
    populateModelsStatVisibility(traceSourceRuns);

    if (mvs.requestKey === requestKey && Object.keys(mvs.modelStats || {}).length > 0) {
      renderModelCards(runsByModel, globalK);
      renderModelsRanking();
      return;
    }

    // Show loading state only when the Models payload actually needs to change.
    if (modelsGrid) modelsGrid.innerHTML = '<div class="models-loading"><img src="/static/qym_icon.png" alt="" class="loading-icon" /><span>Loading run data...</span></div>';

    const renderToken = (mvs.renderToken || 0) + 1;
    mvs.renderToken = renderToken;

    let combinedRunsPromise = null;
    if (mvs.inFlightRequestKey === requestKey && mvs.inFlightRequestPromise) {
      combinedRunsPromise = mvs.inFlightRequestPromise;
    } else {
      const allSelectedPaths = Array.from(new Set(modelSelections.flatMap(({ selectedPaths }) => selectedPaths)));
      combinedRunsPromise = fetchModelRunsData(allSelectedPaths);
      mvs.inFlightRequestKey = requestKey;
      mvs.inFlightRequestPromise = combinedRunsPromise;
    }

    const comparePayload = await combinedRunsPromise;
    if (mvs.renderToken !== renderToken) return;
    if (mvs.inFlightRequestKey === requestKey) {
      mvs.inFlightRequestKey = '';
      mvs.inFlightRequestPromise = null;
    }

    const combinedRunsData = comparePayload && Array.isArray(comparePayload.runs) ? comparePayload.runs : [];
    const runsDataById = new Map((combinedRunsData || []).map((runData) => {
      const runInfo = runData && runData.run ? runData.run : {};
      const runId = runInfo.file_path || runInfo.run_id || '';
      return [runId, runData];
    }));

    mvs.modelStats = {};
    modelSelections.forEach(({ model, selectedPaths, selectedRuns }) => {
      const detailedData = selectedPaths.map((path) => runsDataById.get(path)).filter(Boolean);
      mvs.modelStats[model] = calculateModelStatsFromItems(detailedData, mvs.selectedMetric, mvs.threshold, mvs.metricIsBoolean);
      mvs.modelStats[model].traceAverages = calculateModelTraceStats(selectedRuns);
      mvs.modelStats[model].totalRetries = selectedRuns.reduce((sum, run) => sum + Number(run.total_retries || 0), 0);
      mvs.modelStats[model].totalAvailable = runsByModel[model].length;
      mvs.modelStats[model].selectedCount = selectedRuns.length;
      mvs.modelStats[model].selectedPaths = selectedPaths;
    });
    mvs.requestKey = requestKey;

    // Render model cards
    renderModelCards(runsByModel, globalK);

    // Render ranking bar
    renderModelsRanking();
  }

  function populateModelsViewDropdowns() {
    const metricSelect = el('models-metric-select');
    const kInput = el('models-k-input');

    if (!metricSelect) return;

    // Use global filters for task and dataset, with inference fallback
    let currentTask = state.filterTasks.size === 1 && !state.filterTasks.has('__none__') ? [...state.filterTasks][0] : '';
    let currentDataset = state.filterDatasets.size === 1 && !state.filterDatasets.has('__none__') ? [...state.filterDatasets][0] : '';

    if (!currentTask || !currentDataset) {
      const uniqueTasks = new Set(state.filteredRuns.map(r => r.task_name));
      const uniqueDatasets = new Set(state.filteredRuns.map(r => getRunDatasetKey(r)));
      if (!currentTask && uniqueTasks.size === 1) currentTask = [...uniqueTasks][0];
      if (!currentDataset && uniqueDatasets.size === 1) currentDataset = [...uniqueDatasets][0];
    }

    // Get metrics for selected task+dataset
    const runsForCombo = currentTask && currentDataset
      ? state.filteredRuns.filter(r => r.task_name === currentTask && getRunDatasetKey(r) === currentDataset)
      : [];
    const metricsSet = new Set();
    for (const run of runsForCombo) {
      if (run.metrics) {
        run.metrics.forEach(m => metricsSet.add(m));
      }
    }
    const metrics = [...metricsSet].sort();
    const currentMetric = state.modelsViewState.selectedMetric;
    metricSelect.innerHTML = '<option value="">Select a metric...</option>' +
      metrics.map(m => `<option value="${m}" ${m === currentMetric ? 'selected' : ''}>${m}</option>`).join('');

    // Auto-select first metric if none selected or current metric not in list
    if ((!currentMetric || !metrics.includes(currentMetric)) && metrics.length > 0) {
      state.modelsViewState.selectedMetric = metrics[0];
      metricSelect.value = metrics[0];
    }

    // K input value
    if (kInput) {
      kInput.value = state.modelsViewState.globalK;
    }

    // Threshold slider value
    const thresholdSlider = el('models-threshold-slider');
    const thresholdValue = el('models-threshold-value');
    if (thresholdSlider) {
      const pct = Math.round(state.modelsViewState.threshold * 100);
      thresholdSlider.value = pct;
      if (thresholdValue) thresholdValue.textContent = `${pct}%`;
    }
  }

  // Cache for fetched Models run data to avoid re-fetching
  const modelsRunDataCache = {};

  async function fetchModelRunsData(filePaths) {
    if (filePaths.length === 0) return { runs: [], cacheHit: true };

    // Check cache first
    const cacheKey = filePaths.sort().join('|');
    if (modelsRunDataCache[cacheKey]) {
      return { runs: modelsRunDataCache[cacheKey], cacheHit: true };
    }

    try {
      const params = filePaths.map(f => `files=${encodeURIComponent(f)}`).join('&');
      const response = await fetch(apiUrl(`api/models/runs?${params}`));
      if (!response.ok) throw new Error('Failed to fetch run data');
      const data = await response.json();
      modelsRunDataCache[cacheKey] = data.runs || [];
      return { runs: data.runs || [], cacheHit: false };
    } catch (error) {
      console.error('Error fetching model runs data:', error);
      return { runs: [], cacheHit: false };
    }
  }

  function calculateModelStatsFromItems(runsData, metricName, threshold, isBoolean) {
    // Get run names before delegating to shared function
    const runNames = (runsData || []).map((r, i) => r?.run?.run_name || `Run ${i + 1}`);
    const K = runsData?.length || 0;

    if (!runsData || runsData.length === 0) {
      return {
        passAtK: 0, passHatK: 0, maxAtK: 0, consistency: 0, reliability: 0, avgScore: 0, avgLatency: 0, medianLatency: 0,
        totalItems: 0, failedCount: 0, K: 0, correctDistribution: [0], runNames: [],
        minScore: 0, stddevScore: 0
      };
    }

    const effectiveThreshold = isBoolean ? 0.9999 : threshold;

    // Use shared metrics calculation. Repeat runs pool their ATTEMPTS: a ×k
    // run contributes k per-pass entries, so Pass@K math runs over the pooled
    // attempt set — never pass@k of pass@k.
    const metrics = window.QymMetrics.calculateItemLevelMetrics({
      runsData: expandSampledRunsData(runsData),
      metricName,
      threshold: effectiveThreshold,
      getMetricIndex: (runData) => {
        const metricNames = runData?.snapshot?.metric_names || runData?.run?.metric_names || [];
        return metricNames.indexOf(metricName);
      },
      getItemId: (row) => row.item_id || String(row.index),
      trackDistribution: true
    });

    return {
      passAtK: metrics.passAtK,
      passHatK: metrics.passHatK,
      maxAtK: metrics.maxAtK,
      consistency: metrics.consistency,
      reliability: metrics.reliability,
      avgScore: metrics.avgScore,
      avgLatency: metrics.avgLatency,
      medianLatency: metrics.medianLatency,
      totalItems: metrics.totalItems,
      failedCount: metrics.failedCount,
      totalScoreSum: metrics.totalScoreSum,
      totalScoreCount: metrics.totalScoreCount,
      minScore: metrics.minScore,
      stddevScore: metrics.stddevScore,
      K: metrics.K,
      correctDistribution: metrics.correctDistribution || new Array(K + 1).fill(0),
      runNames
    };
  }

  function calculateModelTraceStats(runs) {
    const traceMetrics = _traceMetricsForRuns(runs);
    if (traceMetrics.length === 0) return {};

    return traceMetrics.reduce((acc, metric) => {
      let sum = 0;
      let count = 0;
      (runs || []).forEach(run => {
        const value = run?.trace_stats?.[metric.key];
        if (value !== undefined && value !== null && Number.isFinite(Number(value))) {
          sum += Number(value);
          count += 1;
        }
      });
      acc[metric.key] = count > 0 ? (sum / count) : null;
      return acc;
    }, {});
  }

  function detectModelsViewMetricType(runs, metricName) {
    if (!metricName) {
      state.modelsViewState.metricIsBoolean = true;
      state.modelsViewState.metricIsNumeric = false;
      return;
    }

    let allBoolean = true;
    let isNumeric = false;
    for (const run of runs) {
      const metricAvg = run.metric_averages?.[metricName];
      if (metricAvg !== undefined && metricAvg !== null) {
        const val = parseFloat(metricAvg);
        if (!isNaN(val)) {
          if (val > 1 || val < 0) { isNumeric = true; allBoolean = false; break; }
          if (Math.abs(val) > 0.0001 && Math.abs(val - 1) > 0.0001) allBoolean = false;
        }
      }
    }
    state.modelsViewState.metricIsBoolean = allBoolean;
    state.modelsViewState.metricIsNumeric = isNumeric;

    // Show/hide threshold control (inline) — hide for boolean and numeric
    const thresholdRow = el('models-threshold-row');
    if (thresholdRow) {
      thresholdRow.style.display = (allBoolean || isNumeric) ? 'none' : 'inline-flex';
    }
  }

  function buildModelDistributionBar(stats) {
    const K = stats.K;
    const dist = stats.correctDistribution || [];
    const total = stats.totalItems || 1;

    if (K === 0 || total === 0) return '';

    let segments = '';
    for (let i = 0; i <= K; i++) {
      const count = dist[i] || 0;
      if (count === 0) continue;
      const pct = (count / total) * 100;
      let segClass = 'dist-partial';
      if (i === 0) segClass = 'dist-zero';
      else if (i === K) segClass = 'dist-all';

      segments += `<div class="dist-segment ${segClass}" style="flex: ${count}" title="${i}/${K} runs correct: ${count} items (${pct.toFixed(1)}%)">
        <span class="dist-label">${i}</span>
        <span class="dist-count">${count}</span>
      </div>`;
    }
    return segments;
  }

  function renderModelCards(runsByModel, globalK) {
    const container = el('models-grid');
    if (!container) return;

    const mvs = state.modelsViewState;
    const isBoolean = mvs.metricIsBoolean;
    const isNumeric = mvs.metricIsNumeric;
    const mType = isNumeric ? 'numeric' : (isBoolean ? 'boolean' : 'score');
    const threshold = Math.round(mvs.threshold * 100);
    const visibleTraceMetrics = mvs.visibleTraceMetrics || [];
    const availableStatOptions = getModelsViewStatOptions();
    const visibleStatKeys = new Set(getVisibleModelsViewStatKeys(availableStatOptions));

    const models = Object.keys(runsByModel).sort((a, b) => {
      // Sort by avg score descending
      const scoreA = mvs.modelStats[a]?.avgScore || 0;
      const scoreB = mvs.modelStats[b]?.avgScore || 0;
      return scoreB - scoreA;
    });

    container.innerHTML = models.map((model, idx) => {
      const stats = mvs.modelStats[model];
      const color = CHART_COLORS[idx % CHART_COLORS.length];
      const hasWarning = stats.selectedCount < globalK;
      const K = stats.K;

      // Tooltips
      const correctDef = isBoolean ? '100%' : `≥${threshold}%`;
      const tooltips = {
        passAtK: isBoolean
          ? `% of items where at least one of the ${K} runs achieved 100%`
          : `% of items where at least one of the ${K} runs scored ≥${threshold}%`,
        passHatK: isBoolean
          ? `% of items where ALL ${K} runs achieved 100%`
          : `% of items where ALL ${K} runs scored ≥${threshold}%`,
        maxAtK: isNumeric
          ? `Average of the best value per item across all ${K} runs`
          : `Average of the best score per item across all ${K} runs`,
        consistency: `How often runs agree on pass/fail across ${K} runs. 100% = all agree, 0% = 50/50 split.`,
        reliability: `When an item CAN be solved, how often is it? Only includes items with ≥1 passing run.`,
        failedCount: `Number of runs that threw an error (across all items). Errors are scored as 0%.`,
        totalRetries: `Total retries across all items in the selected runs. This sums per-item retry counts, not distinct items that retried.`,
        avgScore: isNumeric
          ? `Mean value across all items and all ${K} runs`
          : `Mean score across all items and all ${K} runs`,
        avgLatency: `Average response time across all runs`,
        medianLatency: `Median response time across all items and all ${K} runs. Less sensitive to outliers than the mean.`,
        correctDist: isBoolean
          ? `How many runs got each item correct (100%). "0" = no run solved it, "${K}" = all runs solved it.`
          : `How many runs scored ≥${threshold}% for each item.`
      };

      const distBar = isNumeric ? '' : buildModelDistributionBar(stats);

      // Helper to create info icon with tooltip (same as compare view)
      function infoIcon(tooltip) {
        return `<span class="stat-info-icon">i<span class="stat-info-tooltip">${tooltip}</span></span>`;
      }

      function renderModelStatTile(title, value, valueClass = '', tooltip = '') {
        return `
          <div class="model-stat-item">
            <div class="stat-label">${title}${tooltip ? ` ${infoIcon(tooltip)}` : ''}</div>
            <div class="stat-value ${valueClass}">${value}</div>
          </div>
        `;
      }

      const fmtN = window.QymMetrics.formatNumericValue;
      const statTiles = [];
      function addStatTile(key, title, value, valueClass = '', tooltip = '') {
        if (!visibleStatKeys.has(key)) return;
        statTiles.push(renderModelStatTile(title, value, valueClass, tooltip));
      }
      if (isNumeric) {
        addStatTile('avgScore', 'Avg', fmtN(stats.avgScore), '', tooltips.avgScore);
        addStatTile('minScore', 'Min', fmtN(stats.minScore), '', 'Minimum value across all items and runs.');
        addStatTile('maxAtK', `Max@${K}`, fmtN(stats.maxAtK), '', tooltips.maxAtK);
        addStatTile('stddevScore', 'StdDev', fmtN(stats.stddevScore), '', 'Standard deviation across all items and runs. Lower = more consistent.');
        addStatTile('totalScoreSum', 'Total', fmtN(stats.totalScoreSum), 'accent-value', 'Sum of all values across all items and runs.');
        addStatTile('failedCount', 'Errors', String(stats.failedCount), stats.failedCount > 0 ? 'failed-count' : '', tooltips.failedCount);
        addStatTile('totalRetries', 'Retries', String(stats.totalRetries || 0), stats.totalRetries > 0 ? 'retry-count' : '', tooltips.totalRetries);
        addStatTile('avgLatency', '⚡ Avg Latency', formatLatency(stats.avgLatency), '', tooltips.avgLatency);
        addStatTile('medianLatency', '⚡ Median Latency', formatLatency(stats.medianLatency), '', tooltips.medianLatency);
      } else {
        addStatTile('passAtK', `Pass@${K}`, formatPercent(stats.passAtK), getSuccessClass(stats.passAtK), tooltips.passAtK);
        addStatTile('passHatK', `Pass^${K}`, formatPercent(stats.passHatK), getSuccessClass(stats.passHatK), tooltips.passHatK);
        addStatTile('maxAtK', `Max@${K}`, formatPercent(stats.maxAtK), getSuccessClass(stats.maxAtK), tooltips.maxAtK);
        addStatTile('consistency', 'Consistency', stats.consistency !== null ? formatPercent(stats.consistency) : 'NA', stats.consistency !== null ? getSuccessClass(stats.consistency) : '', tooltips.consistency);
        addStatTile('reliability', 'Reliability', stats.reliability !== null ? formatPercent(stats.reliability) : 'NA', stats.reliability !== null ? getSuccessClass(stats.reliability) : '', tooltips.reliability);
        addStatTile('avgScore', 'Avg Score', formatPercent(stats.avgScore), getSuccessClass(stats.avgScore), tooltips.avgScore);
        addStatTile('failedCount', 'Errors', String(stats.failedCount), stats.failedCount > 0 ? 'failed-count' : '', tooltips.failedCount);
        addStatTile('totalRetries', 'Retries', String(stats.totalRetries || 0), stats.totalRetries > 0 ? 'retry-count' : '', tooltips.totalRetries);
        addStatTile('avgLatency', '⚡ Avg Latency', formatLatency(stats.avgLatency), '', tooltips.avgLatency);
        addStatTile('medianLatency', '⚡ Median Latency', formatLatency(stats.medianLatency), '', tooltips.medianLatency);
      }

      visibleTraceMetrics.forEach((traceMetric) => {
        if (!visibleStatKeys.has(`trace:${traceMetric.key}`)) return;
        const traceValue = stats.traceAverages?.[traceMetric.key];
        const traceClass = traceMetric.key === 'tool_success_rate' && traceValue !== null && traceValue !== undefined
          ? getSuccessClass(traceValue)
          : '';
        statTiles.push(renderModelStatTile(traceMetric.modelsLabel || traceMetric.label, traceMetric.fmt(traceValue), traceClass));
      });

      const showDistribution = !isNumeric && visibleStatKeys.has('correctDistribution');
      const statsGridHtml = statTiles.length > 0
        ? `<div class="model-stats-grid">${statTiles.join('')}</div>`
        : '<div class="model-stats-empty">No summary metrics selected.</div>';

      return `
        <div class="model-card" data-model="${model}">
          <div class="model-card-header">
            <div class="model-card-title" title="${getModelFilterOptionLabel(model)}">
              <span class="model-color-dot" style="background: ${color}"></span>
              ${renderModelLabelForModelName(model)}
            </div>
            <div class="model-card-runs">
              <span class="runs-count">${stats.selectedCount}/${globalK} runs</span>
              ${hasWarning ? `<span class="runs-warning" title="Only ${stats.totalAvailable} runs available (requested ${globalK})">⚠️</span>` : ''}
              <button class="customize-btn" data-model="${model}" title="Customize run selection">Edit</button>
            </div>
          </div>

          ${statsGridHtml}

          ${showDistribution ? `<div class="model-stat-box-wide">
            <div class="stat-title">Correct Distribution ${infoIcon(tooltips.correctDist)}</div>
            <div class="distribution-bar">${distBar}</div>
            <div class="distribution-legend">
              <span class="dist-legend-item"><span style="color:var(--error)">■</span> 0 runs</span>
              <span class="dist-legend-item"><span style="color:var(--warning)">■</span> 1-${K-1} runs</span>
              <span class="dist-legend-item"><span style="color:var(--success)">■</span> ${K} runs</span>
            </div>
          </div>` : ''}

          <div class="model-card-footer">
            <span class="latency">${stats.totalItems} items</span>
            <a href="#" class="compare-link" data-model="${model}">See item-by-item comparison →</a>
          </div>
        </div>
      `;
    }).join('');

    // Wire up event listeners
    container.querySelectorAll('.customize-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        openRunSelectionModal(btn.dataset.model, runsByModel[btn.dataset.model]);
      });
    });

    container.querySelectorAll('.compare-link').forEach(link => {
      link.addEventListener('click', (e) => {
        e.preventDefault();
        const model = link.dataset.model;
        const stats = mvs.modelStats[model];
        if (stats && stats.selectedPaths && stats.selectedPaths.length >= 2) {
          sessionStorage.setItem('compareRuns', JSON.stringify(stats.selectedPaths));
          const params = stats.selectedPaths.map(f => 'runs=' + encodeURIComponent(f)).join('&');
          navigateTo(apiUrl('compare?' + params));
        } else {
          alert('Need at least 2 runs to compare');
        }
      });
    });
  }

  function renderModelsRanking() {
    const container = el('models-ranking');
    if (!container) return;

    const mvs = state.modelsViewState;
    const models = Object.keys(mvs.modelStats);

    if (models.length === 0) {
      container.style.display = 'none';
      return;
    }

    // Sort by avg score descending
    const ranked = models
      .map(m => ({ model: m, score: mvs.modelStats[m]?.avgScore || 0 }))
      .sort((a, b) => b.score - a.score);

    const rankEmojis = ['🥇', '🥈', '🥉'];

    const isNumeric = mvs.metricIsNumeric;
    const rankMType = isNumeric ? 'numeric' : 'score';

    container.style.display = 'block';
    container.innerHTML = `
      <h3>Ranking (by ${isNumeric ? 'Avg Value' : 'Avg Score'})</h3>
      <div class="ranking-list">
        ${ranked.map((item, idx) => {
          const rank = idx < 3 ? rankEmojis[idx] : `#${idx + 1}`;
          const scoreClass = window.QymMetrics.getMetricColorClass(item.score, rankMType);
          const display = window.QymMetrics.formatMetricValue(item.score, rankMType);
          return `
            <div class="ranking-item">
              <span class="rank">${rank}</span>
              ${renderModelLabelForModelName(item.model)}
              <span class="score ${scoreClass}">(${display})</span>
            </div>
          `;
        }).join('')}
      </div>
    `;
  }

  function openRunSelectionModal(modelName, allRuns) {
    const modal = el('run-selection-modal');
    const modelNameEl = el('run-selection-model-name');
    const listEl = el('run-selection-list');
    const confirmBtn = el('confirm-run-selection-btn');

    if (!modal || !listEl) return;

    const mvs = state.modelsViewState;
    const currentSelection = mvs.modelRunSelections[modelName] || [];
    const globalK = parseInt(mvs.globalK) || 5;

    modelNameEl.innerHTML = renderModelLabelForModelName(modelName);
    modelNameEl.title = getModelFilterOptionLabel(modelName);

    // Track selection count
    let selectionCount = 0;

    // #9: Group runs by config for K-vs-K comparison
    const configGroups = {};
    allRuns.forEach(run => {
      const key = computeRunConfigGroupKey(run) || '__ungrouped__';
      if (!configGroups[key]) configGroups[key] = [];
      configGroups[key].push(run);
    });
    const hasMultipleGroups = Object.keys(configGroups).length > 1;

    // Render run list with config group labels
    let runListHtml = '';
    let runFlatIdx = 0;
    for (const [groupKey, groupRuns] of Object.entries(configGroups)) {
      if (hasMultipleGroups && groupKey !== '__ungrouped__') {
        const groupLabel = getRunDisplayName(groupRuns[0]) || `Config ${Object.keys(configGroups).indexOf(groupKey) + 1}`;
        runListHtml += `<div style="padding:6px 8px;font-size:var(--font-sm);color:var(--accent-primary);font-weight:600;text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid var(--border-default);">${escapeHtml(groupLabel)} (${groupRuns.length} runs)</div>`;
      }
      for (const run of groupRuns) {
        const idx = runFlatIdx++;
        const isSelected = currentSelection.length > 0
          ? currentSelection.includes(run.file_path)
          : idx < globalK;
        if (isSelected) selectionCount++;
        const dt = formatDate(run.timestamp);
        const metric = mvs.selectedMetric;
        const score = run.metric_averages?.[metric];
        const selMType = mvs.metricIsNumeric ? 'numeric' : 'score';
        const scoreClass = score !== undefined ? window.QymMetrics.getMetricColorClass(score, selMType) : '';
        const scoreDisplay = score !== undefined ? window.QymMetrics.formatMetricValue(score, selMType) : '';
        const runDisplayName = getRunDisplayName(run);

        runListHtml += `
          <label class="run-selection-item ${isSelected ? 'selected' : ''}">
            <input type="checkbox" data-file="${run.file_path}" ${isSelected ? 'checked' : ''} />
            <div class="run-info">
              <div class="run-name" title="${escapeHtml(runDisplayName)}">${escapeHtml(runDisplayName)}</div>
              <div class="run-date">${dt.full}</div>
            </div>
            ${score !== undefined ? `<span class="run-score ${scoreClass}">${scoreDisplay}</span>` : ''}
          </label>
        `;
      }
    }

    listEl.innerHTML = `
      <div class="run-selection-header">
        <span class="selection-counter"><span id="selection-count">0</span> / ${globalK} selected</span>
        ${hasMultipleGroups ? `<span style="font-size:var(--font-sm);color:var(--text-muted);margin-left:8px;">${Object.keys(configGroups).length} config groups</span>` : ''}
      </div>
      <div class="run-selection-items">
        ${runListHtml}
      </div>
    `;

    // Update counter
    const updateCounter = () => {
      const count = listEl.querySelectorAll('input[type="checkbox"]:checked').length;
      const counterEl = listEl.querySelector('#selection-count');
      if (counterEl) {
        counterEl.textContent = count;
        counterEl.parentElement.classList.toggle('at-limit', count >= globalK);
        counterEl.parentElement.classList.toggle('over-limit', count > globalK);
      }
    };
    updateCounter();

    // Wire up checkbox change events to enforce K limit
    listEl.querySelectorAll('input[type="checkbox"]').forEach(cb => {
      cb.addEventListener('change', (e) => {
        const item = e.target.closest('.run-selection-item');
        const checkedCount = listEl.querySelectorAll('input[type="checkbox"]:checked').length;

        if (e.target.checked && checkedCount > globalK) {
          // Exceeded limit - uncheck this one
          e.target.checked = false;
          item.classList.remove('selected');
          return;
        }

        item.classList.toggle('selected', e.target.checked);
        updateCounter();
      });
    });

    modal.style.display = 'flex';

    // Wire confirm button
    const newConfirmBtn = confirmBtn.cloneNode(true);
    confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);

    newConfirmBtn.addEventListener('click', () => {
      const selected = [];
      listEl.querySelectorAll('input[type="checkbox"]:checked').forEach(cb => {
        selected.push(cb.dataset.file);
      });

      if (selected.length > 0) {
        mvs.modelRunSelections[modelName] = selected;
      } else {
        delete mvs.modelRunSelections[modelName];
      }

      modal.style.display = 'none';
      renderModelsView();
    });
  }

  // ═══════════════════════════════════════════════════
  // ACTIONS
  // ═══════════════════════════════════════════════════

  function getActiveCohortAnchorRuns() {
    return Array.isArray(state.cohortAnchorRuns) ? state.cohortAnchorRuns : null;
  }

  function canSelectForCohortB(filePath, options = {}) {
    const { showError = true } = options;
    const cohortAnchor = getActiveCohortAnchorRuns();
    if (!cohortAnchor || !cohortAnchor.length) return true;

    if (state.selectedRuns.has(filePath)) return true;
    if (cohortAnchor.includes(filePath)) {
      if (showError) {
        showToast('error', 'Run Already In Cohort A', 'Pick a different run for Cohort B. The two cohorts must be disjoint.');
      }
      return false;
    }
    if (state.selectedRuns.size >= cohortAnchor.length) {
      if (showError) {
        showToast('error', 'Cohort B Is Full', `Cohort B already has ${cohortAnchor.length}/${cohortAnchor.length} runs. Remove one or open the cohort comparison.`);
      }
      return false;
    }
    return true;
  }

  function toggleSelect(filePath) {
    if (state.selectedRuns.has(filePath)) {
      state.selectedRuns.delete(filePath);
    } else {
      if (!canSelectForCohortB(filePath)) return;
      state.selectedRuns.add(filePath);
    }
    render();
  }

  function toggleModelFilter(model) {
    if (state.filterModels.size === 0) {
      // Currently showing all - clicking a model should hide it (select all others)
      state.allModels.forEach(m => {
        if (m !== model) state.filterModels.add(m);
      });
    } else if (state.filterModels.has(model)) {
      // This model is in the whitelist - remove it (hide it)
      state.filterModels.delete(model);
    } else {
      // This model is not in whitelist - add it (show it)
      state.filterModels.add(model);
      // If all models are now selected, clear to "show all" state
      if (state.filterModels.size === state.allModels.length) {
        state.filterModels.clear();
      }
    }
    syncMultiSelect({ btnId: 'filter-model-btn', dropdownId: 'filter-model-dropdown', stateSet: state.filterModels, values: state.allModels, defaultLabel: 'All Models' });
    render();
  }

  function selectOnlyModel(model) {
    state.filterModels.clear();
    state.filterModels.add(model);
    syncMultiSelect({ btnId: 'filter-model-btn', dropdownId: 'filter-model-dropdown', stateSet: state.filterModels, values: state.allModels, defaultLabel: 'All Models' });
    render();
  }

  function selectAll() {
    if (getActiveCohortAnchorRuns()) {
      showToast('error', 'Select All Disabled In Cohort Mode', 'Choose Cohort B runs explicitly so you can control membership and avoid overlap with Cohort A.');
      return;
    }
    const { pageRuns } = getTablePageSlice(state.filteredRuns);
    const visibleFilePaths = pageRuns.map(run => run.file_path);
    const allVisibleSelected = visibleFilePaths.length > 0 && visibleFilePaths.every(filePath => state.selectedRuns.has(filePath));
    if (allVisibleSelected) {
      visibleFilePaths.forEach(filePath => state.selectedRuns.delete(filePath));
    } else {
      visibleFilePaths.forEach(filePath => state.selectedRuns.add(filePath));
    }
    render();
  }

  function clearSelection() {
    state.selectedRuns.clear();
    state.cohortAnchorRuns = null;
    render();
  }

  function getCohortRunDisplayName(filePath) {
    const run = state.flatRuns.find(candidate => candidate.file_path === filePath);
    if (!run) return '';
    return stripProviderFromRunId(run.run_id || run.run_name || filePath);
  }

  function buildCohortLabel(filePaths) {
    const labels = (filePaths || [])
      .map(getCohortRunDisplayName)
      .filter(Boolean);
    if (labels.length === 0) return 'Cohort';
    if (labels.length === 1) return labels[0];
    if (labels.length === 2) return `${labels[0]}, ${labels[1]}`;
    return `${labels[0]}, ${labels[1]} +${labels.length - 2}`;
  }

  function toggleGroupSelection(filePaths) {
    if (!Array.isArray(filePaths) || filePaths.length === 0) return;
    if (getActiveCohortAnchorRuns()) {
      showToast('error', 'Group Selection Disabled In Cohort Mode', 'Select Cohort B runs one by one. Cohort mode requires an exact, disjoint set.');
      return;
    }
    const allSelected = filePaths.every(filePath => state.selectedRuns.has(filePath));
    if (allSelected) {
      filePaths.forEach(filePath => state.selectedRuns.delete(filePath));
    } else {
      filePaths.forEach(filePath => state.selectedRuns.add(filePath));
    }
    render();
  }

  function openRun(filePath, e) {
    sessionStorage.setItem('dashboardRunFile', filePath);
    const url = state.currentProject && state.currentProject.slug
      ? projectUrl(state.currentProject.slug, `runs/${encodeURIComponent(filePath)}`)
      : apiUrl(`run/${encodeURIComponent(filePath)}`);
    openUrl(url, e);
  }

  function openComparison(e) {
    if (state.selectedRuns.size < 2) {
      showToast('error', 'Cannot Compare', 'Select at least 2 runs to compare');
      return;
    }
    const files = Array.from(state.selectedRuns);
    sessionStorage.removeItem('compareCohorts');
    sessionStorage.setItem('compareRuns', JSON.stringify(files));
    const params = files.map(f => 'runs=' + encodeURIComponent(f)).join('&');
    openUrl(apiUrl('compare?' + params), e);
  }

  function openCohortComparison(e) {
    const selectedFiles = Array.from(state.selectedRuns);
    if (!Array.isArray(state.cohortAnchorRuns) || state.cohortAnchorRuns.length === 0) {
      if (selectedFiles.length < 1) {
        showToast('error', 'Cannot Start Cohort Mode', 'Select at least 1 run, then click Cohort to lock them as Cohort A.');
        return;
      }
      state.cohortAnchorRuns = selectedFiles;
      state.selectedRuns.clear();
      render();
      showToast('success', 'Cohort A Locked', `Now select exactly ${selectedFiles.length} run${selectedFiles.length === 1 ? '' : 's'} for Cohort B, then click Open Cohort.`);
      return;
    }

    const left = state.cohortAnchorRuns;
    const right = selectedFiles;
    if (right.length !== left.length) {
      showToast('error', 'Cohort B Incomplete', `Cohort A has ${left.length} runs. Select exactly ${left.length} runs for Cohort B before opening the comparison.`);
      return;
    }
    if (right.some(file => left.includes(file))) {
      showToast('error', 'Cohorts Must Be Disjoint', 'One or more selected runs are already in Cohort A. Remove them from Cohort B and pick different runs.');
      return;
    }

    const cohortPayload = {
      left,
      right,
      leftLabel: buildCohortLabel(left),
      rightLabel: buildCohortLabel(right),
    };
    sessionStorage.setItem('compareCohorts', JSON.stringify(cohortPayload));
    sessionStorage.setItem('compareRuns', JSON.stringify([...left, ...right]));
    const params = new URLSearchParams();
    left.forEach(file => params.append('cohortA', file));
    right.forEach(file => params.append('cohortB', file));
    params.set('cohortALabel', cohortPayload.leftLabel);
    params.set('cohortBLabel', cohortPayload.rightLabel);
    openUrl(apiUrl('compare?' + params.toString()), e);
  }

  function confirmDeleteRun(filePath, runId) {
    const modal = el('delete-modal');
    const runNameEl = el('delete-run-name');
    const confirmBtn = el('confirm-delete-btn');

    runNameEl.textContent = runId;
    modal.style.display = 'flex';

    // Remove old listener and add new one
    const newConfirmBtn = confirmBtn.cloneNode(true);
    confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);

    newConfirmBtn.addEventListener('click', async () => {
      newConfirmBtn.disabled = true;
      newConfirmBtn.textContent = 'Deleting...';

      try {
        const response = await fetch(apiUrl('api/runs/delete'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ file_path: filePath })
        });

        if (response.ok) {
          modal.style.display = 'none';
          // Remove from selection if selected
          state.selectedRuns.delete(filePath);
          // Refresh data
          await fetchRuns({ refreshAllPages: true });
        } else {
          const data = await response.json();
          alert('Failed to delete: ' + (data.error || 'Unknown error'));
        }
      } catch (err) {
        alert('Failed to delete: ' + err.message);
      } finally {
        newConfirmBtn.disabled = false;
        newConfirmBtn.textContent = 'Delete';
      }
    });
  }

  function confirmDeleteSelected() {
    const count = state.selectedRuns.size;
    if (count === 0) return;

    const modal = el('delete-modal');
    const runNameEl = el('delete-run-name');
    const confirmBtn = el('confirm-delete-btn');

    runNameEl.textContent = `${count} run${count > 1 ? 's' : ''} selected`;
    modal.style.display = 'flex';

    // Remove old listener and add new one
    const newConfirmBtn = confirmBtn.cloneNode(true);
    confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);

    newConfirmBtn.addEventListener('click', async () => {
      newConfirmBtn.disabled = true;
      newConfirmBtn.textContent = 'Deleting...';

      const filePaths = Array.from(state.selectedRuns);
      let successCount = 0;
      let errorCount = 0;

      for (const filePath of filePaths) {
        try {
          const response = await fetch(apiUrl('api/runs/delete'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file_path: filePath })
          });

          if (response.ok) {
            successCount++;
            state.selectedRuns.delete(filePath);
          } else {
            errorCount++;
          }
        } catch (err) {
          errorCount++;
        }
      }

      modal.style.display = 'none';
      newConfirmBtn.disabled = false;
      newConfirmBtn.textContent = 'Delete';

      // Refresh data
      await fetchRuns({ refreshAllPages: true });

      if (errorCount > 0) {
        alert(`Deleted ${successCount} run(s). Failed to delete ${errorCount} run(s).`);
      }
    });
  }

  function showWorkflowModal(action, runId, taskName) {
    const modal = el('workflow-modal');
    const titleEl = el('workflow-modal-title');
    const descEl = el('workflow-modal-description');
    const runNameEl = el('workflow-run-name');
    const commentEl = el('workflow-comment');
    const confirmBtn = el('confirm-workflow-btn');

    const isApprove = action === 'approve';
    const isUnapprove = action === 'unapprove';
    const isUnreject = action === 'unreject';
    titleEl.textContent = isUnapprove
      ? 'Unapprove Run'
      : (isUnreject ? 'Unreject Run' : (isApprove ? 'Approve Run' : 'Reject Run'));
    descEl.textContent = isUnapprove
      ? 'Clear this approval and return the run to completed.'
      : (isUnreject
        ? 'Clear this rejection and return the run to completed.'
      : (isApprove
        ? 'Approve this run to make it visible to leadership.'
        : 'Reject this run and send it back for review.'));
    runNameEl.textContent = `${taskName} (${runId.substring(0, 8)}...)`;
    commentEl.value = '';
    modal.style.display = 'flex';

    // Update button style
    confirmBtn.className = isApprove ? 'btn btn-primary' : 'btn btn-danger';
    confirmBtn.textContent = isUnapprove ? 'Unapprove' : (isUnreject ? 'Unreject' : (isApprove ? 'Approve' : 'Reject'));

    // Remove old listener and add new one
    const newConfirmBtn = confirmBtn.cloneNode(true);
    confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);

    newConfirmBtn.addEventListener('click', async () => {
      newConfirmBtn.disabled = true;
      newConfirmBtn.textContent = isUnapprove ? 'Unapproving...' : (isUnreject ? 'Unrejecting...' : (isApprove ? 'Approving...' : 'Rejecting...'));

      try {
        const endpoint = isUnapprove ? 'unapprove' : (isUnreject ? 'unreject' : (isApprove ? 'approve' : 'reject'));
        const response = await fetch(apiUrl(`v1/runs/${encodeURIComponent(runId)}/${endpoint}`), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ comment: commentEl.value || '' }),
        });

        if (response.ok) {
          modal.style.display = 'none';
          await fetchRuns({ refreshAllPages: true });
          showToast(
            'success',
            isUnapprove ? 'Unapproved' : (isUnreject ? 'Unrejected' : (isApprove ? 'Approved' : 'Rejected')),
            (isUnapprove || isUnreject) ? 'Run returned to completed' : (isApprove ? 'Run approved' : 'Run rejected'),
          );
        } else {
          const data = await response.json();
          showToast('error', `${isUnapprove ? 'Unapprove' : (isUnreject ? 'Unreject' : (isApprove ? 'Approve' : 'Reject'))} Failed`, data.detail || 'Unknown error');
        }
      } catch (err) {
        showToast('error', `${isUnapprove ? 'Unapprove' : (isUnreject ? 'Unreject' : (isApprove ? 'Approve' : 'Reject'))} Failed`, err.message || 'Unknown error');
      } finally {
        newConfirmBtn.disabled = false;
        newConfirmBtn.textContent = isUnapprove ? 'Unapprove' : (isUnreject ? 'Unreject' : (isApprove ? 'Approve' : 'Reject'));
      }
    });

    // Focus the comment field
    setTimeout(() => commentEl.focus(), 100);
  }

  function moveFocus(delta) {
    const newIdx = state.focusedIndex + delta;
    if (newIdx >= 0 && newIdx < state.filteredRuns.length) {
      state.focusedIndex = newIdx;
      setTablePage(Math.floor(newIdx / TABLE_PAGE_SIZE) + 1);
      render();

      // Scroll into view
      const row = $(`tr[data-idx="${newIdx}"]`);
      if (row) {
        row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    }
  }

  function openFocusedRun() {
    if (state.focusedIndex >= 0 && state.focusedIndex < state.filteredRuns.length) {
      const run = state.filteredRuns[state.focusedIndex];
      openRun(run.file_path);
    }
  }

  function toggleFocusedSelect() {
    if (state.focusedIndex >= 0 && state.focusedIndex < state.filteredRuns.length) {
      const run = state.filteredRuns[state.focusedIndex];
      toggleSelect(run.file_path);
    }
  }

  // ═══════════════════════════════════════════════════
  // API & INITIALIZATION
  // ═══════════════════════════════════════════════════

  const PAGE_SIZE = 100;
  const LIVE_REFRESH_INTERVAL_MS = 15000;
  const IDLE_REFRESH_INTERVAL_MS = 60000;
  const FULL_REFRESH_STALE_MS = 5 * 60 * 1000;

  function hasActiveRuns(runs = state.flatRuns) {
    return (runs || []).some(r => {
      const status = String(r.status || '').toUpperCase();
      return status === 'RUNNING' || status === 'PENDING';
    });
  }

  function queueRunsFetch(options) {
    const current = state.runsFetchMeta.pendingOptions || { refreshAllPages: false };
    state.runsFetchMeta.pendingOptions = {
      refreshAllPages: Boolean(current.refreshAllPages || (options && options.refreshAllPages)),
    };
  }

  function _mergeTasksData(base, incoming) {
    if (!incoming || !incoming.tasks) return base;
    for (const [taskName, models] of Object.entries(incoming.tasks)) {
      if (!base.tasks[taskName]) base.tasks[taskName] = {};
      for (const [modelName, runList] of Object.entries(models)) {
        if (!base.tasks[taskName][modelName]) base.tasks[taskName][modelName] = [];
        base.tasks[taskName][modelName].push(...runList);
      }
    }
    return base;
  }

  function _cloneRunsData(data) {
    if (!data) return { tasks: {}, last_updated: '', total_count: 0 };
    try {
      return JSON.parse(JSON.stringify(data));
    } catch {
      return { tasks: data.tasks || {}, last_updated: data.last_updated || '', total_count: data.total_count || 0 };
    }
  }

  function getRunsCacheKey() {
    const projectSlug = getProjectSlugFromPath() || '__global__';
    return `qym:runs-cache:${projectSlug}`;
  }

  function getDashboardStateKey() {
    const projectSlug = getProjectSlugFromPath() || '__global__';
    return `qym:dashboard-state:${projectSlug}`;
  }

  function saveRunsDataCache(data) {
    try {
      const payload = {
        saved_at: Date.now(),
        data: _cloneRunsData(data),
      };
      sessionStorage.setItem(getRunsCacheKey(), JSON.stringify(payload));
    } catch {}
  }

  function restoreRunsDataCache(maxAgeMs = 15 * 60 * 1000) {
    try {
      const raw = sessionStorage.getItem(getRunsCacheKey());
      if (!raw) return false;
      const parsed = JSON.parse(raw);
      const savedAt = Number(parsed?.saved_at || 0);
      if (!parsed?.data || !Number.isFinite(savedAt)) return false;
      if ((Date.now() - savedAt) > maxAgeMs) return false;
      _applyRunsData(parsed.data);
      return true;
    } catch {
      return false;
    }
  }

  function _mergePagedRefreshData(previous, incoming) {
    if (!incoming) return previous;
    if (!previous || !previous.tasks) return incoming;
    if ((incoming.total_count ?? 0) === 0) return incoming;

    const merged = _cloneRunsData(previous);
    const incomingRunIds = new Set();

    for (const models of Object.values(incoming.tasks || {})) {
      for (const runList of Object.values(models || {})) {
        for (const run of runList || []) {
          if (run && run.run_id) incomingRunIds.add(run.run_id);
        }
      }
    }

    if (incomingRunIds.size === 0) return incoming;

    for (const models of Object.values(merged.tasks || {})) {
      for (const modelName of Object.keys(models || {})) {
        models[modelName] = (models[modelName] || []).filter(run => !incomingRunIds.has(run.run_id));
      }
    }

    _mergeTasksData(merged, incoming);
    merged.last_updated = incoming.last_updated || merged.last_updated;
    merged.total_count = incoming.total_count ?? merged.total_count;
    return merged;
  }

  function _applyRunsData(data) {
    showDashboardChrome();
    state.runs = data;
    if (data && data.project) {
      state.currentProject = data.project;
      if (state.currentProject && state.currentProject.slug) {
        storeProjectSlug(state.currentProject.slug);
      }
    }
    const { runs, metrics, metricTypes } = flattenRuns(data);
    const projectSlug = (data && data.project && data.project.slug) || '';
    if (state.knownVersionsProjectSlug !== projectSlug) {
      state.knownVersions = new Set();
      state.knownVersionsProjectSlug = projectSlug;
    }
    const currentVersionKeys = runs.map(getRunVersionKey).filter(v => !isEmptyFilterValue(v));
    const totalCount = Number((data && data.total_count) || 0);
    const hasCompleteRunSet = totalCount === 0 || runs.length >= totalCount;
    if (hasCompleteRunSet) {
      state.knownVersions = new Set(currentVersionKeys);
    } else {
      currentVersionKeys.forEach(v => state.knownVersions.add(v));
    }
    state.flatRuns = runs;
    state.allMetrics = metrics;
    state._metricTypes = metricTypes;
    loadMetricVisibility();
    updateProfileLink();
    state.aggregations = computeAggregations(state.flatRuns);
    state.chartData = computeChartData(state.flatRuns);
    saveRunsDataCache(data);
    populateFilterDropdowns();
    populateMetricVisibility();
    el('last-updated').textContent = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    render();
  }

  async function _fetchRemainingPages(data, totalCount) {
    // Fetch remaining pages in the background and merge into state
    const fetched = PAGE_SIZE; // first page already loaded
    if (fetched >= totalCount) return;

    const pagePromises = [];
    const projectSlug = state.currentProject && state.currentProject.slug ? `&project_slug=${encodeURIComponent(state.currentProject.slug)}` : '';
    for (let offset = fetched; offset < totalCount; offset += PAGE_SIZE) {
      pagePromises.push(
        fetch(apiUrl(`api/runs?limit=${PAGE_SIZE}&offset=${offset}${projectSlug}`))
          .then(r => r.ok ? r.json() : null)
          .catch(() => null)
      );
    }

    const pages = await Promise.all(pagePromises);
    for (const page of pages) {
      if (page) _mergeTasksData(data, page);
    }

    // Re-apply with full data
    _applyRunsData(data);
    try { updateRunsRefreshCadence && updateRunsRefreshCadence(); } catch {}
  }

  function renderProjectChooser(projects) {
    const modal = el('project-chooser');
    const list = el('project-chooser-list');
    if (!modal || !list) return;
    const loading = el('loading');
    if (loading) loading.style.display = 'none';
    const empty = el('empty');
    if (empty) empty.style.display = 'none';
    list.innerHTML = (projects || []).map(project => `
      <button class="project-choice-btn" data-project-choice="${escapeHtml(project.slug)}">
        <span class="project-choice-name">${escapeHtml(project.name)}</span>
        <span class="project-choice-role">${escapeHtml(project.role || '')}</span>
      </button>
    `).join('');
    list.querySelectorAll('[data-project-choice]').forEach(btn => {
      btn.addEventListener('click', () => {
        const slug = btn.getAttribute('data-project-choice') || '';
        if (!slug) return;
        storeProjectSlug(slug);
        navigateTo(projectUrl(slug));
      });
    });
    modal.style.display = '';
  }

  function hideProjectChooser() {
    const modal = el('project-chooser');
    if (modal) modal.style.display = 'none';
  }

  function canCreateProjects() {
    const user = state.currentUser || {};
    if (user.role === 'ADMIN') return true;
    return (state.availableProjects || []).some(project => project.role === 'MANAGER');
  }

  function showDashboardChrome() {
    const commandBar = document.querySelector('.command-bar');
    if (commandBar) commandBar.style.display = '';
    const comparePanel = el('compare-panel');
    if (comparePanel) comparePanel.style.display = state.selectedRuns.size ? '' : 'none';
    const footer = document.querySelector('.status-bar');
    if (footer) footer.style.display = '';
    const statsBar = document.querySelector('.stats-bar .stat-cells');
    if (statsBar) statsBar.style.display = '';
  }

  function hideDashboardChrome() {
    const commandBar = document.querySelector('.command-bar');
    if (commandBar) commandBar.style.display = 'none';
    const comparePanel = el('compare-panel');
    if (comparePanel) comparePanel.style.display = 'none';
    const footer = document.querySelector('.status-bar');
    if (footer) footer.style.display = 'none';
    const statsBar = document.querySelector('.stats-bar .stat-cells');
    if (statsBar) statsBar.style.display = 'none';
  }

  async function createProjectFromSelector() {
    const nameInput = el('project-create-name');
    const slugInput = el('project-create-slug');
    const descInput = el('project-create-description');
    const errorEl = el('project-selector-message');
    if (!nameInput) return;
    const payload = {
      name: (nameInput.value || '').trim(),
      slug: (slugInput && slugInput.value || '').trim(),
      description: (descInput && descInput.value || '').trim(),
    };
    if (!payload.name) {
      if (errorEl) errorEl.textContent = 'Project name is required';
      return;
    }
    if (errorEl) errorEl.textContent = 'Creating project...';
    try {
      const response = await fetch(apiUrl('v1/projects'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || 'Failed to create project');
      }
      if (errorEl) errorEl.textContent = '';
      storeProjectSlug(data.slug || '');
      navigateTo(projectUrl(data.slug || ''));
    } catch (err) {
      if (errorEl) errorEl.textContent = err.message || 'Failed to create project';
    }
  }

  function showProjectSelectorPage() {
    hideProjectChooser();
    hideDashboardChrome();
    const loading = el('loading');
    if (loading) loading.style.display = 'none';
    const empty = el('empty');
    const projects = state.availableProjects || [];
    const createAllowed = canCreateProjects();
    if (empty) {
      empty.style.display = '';
      empty.innerHTML = `
        <div class="project-hub">
          <div class="project-hub-hero">
            <div>
              <div class="project-hub-title">Projects</div>
              <div class="project-hub-subtitle">${projects.length
                ? 'Select a project to open its runs, reviews, and settings.'
                : (createAllowed
                    ? 'Create your first project to start organizing runs, memberships, approvals, and API keys.'
                    : 'You are not a member of any project yet. Ask a project manager to add you to an existing project.')}</div>
            </div>
          </div>
          <div class="project-hub-grid">
            <section class="project-hub-panel ${projects.length ? '' : 'project-hub-empty'}">
              <h3>${projects.length ? 'Your Projects' : 'No Projects Available'}</h3>
              <p>${projects.length
                ? 'Projects are your workspace boundary. Access, approvals, and API keys are scoped here.'
                : 'Once you join a project, it will appear here and become your entry point into the app.'}</p>
              ${projects.length ? `
                <div class="project-hub-list">
                  ${projects.map(project => `
                    <button class="project-hub-card" data-project-selector="${escapeHtml(project.slug)}">
                      <span class="project-hub-card-main">
                        <span class="project-hub-card-name">${escapeHtml(project.name)}</span>
                        <span class="project-hub-card-meta">
                          <span class="project-hub-pill">${escapeHtml(project.role || '')}</span>
                          <span>${escapeHtml(project.slug || '')}</span>
                        </span>
                      </span>
                      <span class="project-hub-arrow">›</span>
                    </button>
                  `).join('')}
                </div>
              ` : `
                <div class="project-hub-empty-note">${createAllowed
                  ? 'Use the creation panel to the right to create the first project.'
                  : 'You need to be added to a project before you can access runs or reviews.'}</div>
              `}
            </section>
            <aside class="project-hub-panel">
              <h3>${createAllowed ? 'Create Project' : 'Access'}</h3>
              <p>${createAllowed
                ? 'Project creators automatically become managers of the new project.'
                : 'Project managers control membership. If you need access, ask to be invited to a project.'}</p>
              ${createAllowed ? `
                <div class="project-hub-actions">
                  <input id="project-create-name" class="form-input" placeholder="Project name" />
                  <input id="project-create-slug" class="form-input" placeholder="project-slug (optional)" />
                  <input id="project-create-description" class="form-input" placeholder="Description (optional)" />
                  <button id="project-create-submit" class="btn btn-primary" type="button">Create Project</button>
                  <div id="project-selector-message" class="project-hub-message"></div>
                </div>
              ` : `
                <div class="project-hub-message">No action is available here until you are added to a project.</div>
              `}
            </aside>
          </div>
        </div>
      `;
    }
    document.querySelectorAll('[data-project-selector]').forEach(btn => {
      btn.addEventListener('click', () => {
        const slug = btn.getAttribute('data-project-selector') || '';
        if (!slug) return;
        storeProjectSlug(slug);
        navigateTo(projectUrl(slug));
      });
    });
    const createBtn = el('project-create-submit');
    if (createBtn) createBtn.addEventListener('click', createProjectFromSelector);
  }

  function resolveProjectContext(me) {
    const projects = Array.isArray(me?.projects) ? me.projects : [];
    state.availableProjects = projects;

    const currentSlug = getProjectSlugFromPath();
    if (currentSlug) {
      const current = projects.find(project => project.slug === currentSlug) || null;
      state.currentProject = current || (me?.role === 'ADMIN' ? { slug: currentSlug, name: currentSlug, role: 'ADMIN' } : null);
      if (state.currentProject) {
        storeProjectSlug(state.currentProject.slug);
        hideProjectChooser();
        return true;
      }
      throw new Error('Project not found');
    }

    if (projects.length === 0) {
      state.currentProject = null;
      hideProjectChooser();
      return false;
    }
    state.currentProject = null;
    hideProjectChooser();
    return false;
  }

  async function fetchRuns(options = {}) {
    const fetchOptions = {
      refreshAllPages: false,
      ...options,
    };

    if (state.runsFetchMeta.inFlight) {
      queueRunsFetch(fetchOptions);
      return;
    }

    state.runsFetchMeta.inFlight = true;
    try {
      // Use shell's cached user if available, otherwise fetch
      if (window.__QYM_USER__) {
        state.currentUser = window.__QYM_USER__;
      } else {
        const meResponse = await fetch(apiUrl('v1/me')).catch(() => null);
        if (meResponse && meResponse.ok) {
          state.currentUser = await meResponse.json();
          window.__QYM_USER__ = state.currentUser;
        } else {
          state.currentUser = null;
        }
      }
      if (state.currentUser) {
        if (!resolveProjectContext(state.currentUser)) {
          state.runsFetchMeta.hasLoadedAllPages = false;
          showProjectSelectorPage();
          return;
        }
      }

      const projectSlug = state.currentProject && state.currentProject.slug ? `&project_slug=${encodeURIComponent(state.currentProject.slug)}` : '';
      const runsResponse = await fetch(apiUrl(`api/runs?limit=${PAGE_SIZE}&offset=0${projectSlug}`));

      // Handle authentication errors
      if (runsResponse.status === 401) {
        showAuthError();
        return;
      }

      if (runsResponse.status === 404 && getProjectSlugFromPath()) {
        throw new Error('Project not found');
      }

      if (!runsResponse.ok) {
        throw new Error(`HTTP ${runsResponse.status}`);
      }

      const data = await runsResponse.json();
      const totalCount = data.total_count || 0;
      const previousTotalCount = state.runsFetchMeta.totalCount || 0;
      state.runsFetchMeta.totalCount = totalCount;

      // Render first page immediately, but preserve already-loaded off-page runs during live refreshes.
      const immediateData = totalCount > PAGE_SIZE
        ? _mergePagedRefreshData(state.runs, data)
        : data;
      _applyRunsData(immediateData);

      // Adjust refresh cadence based on whether we have active runs.
      try { updateRunsRefreshCadence && updateRunsRefreshCadence(); } catch {}

      const activeRunsPresent = hasActiveRuns();
      const totalCountChanged = previousTotalCount > 0 && previousTotalCount !== totalCount;
      const fullRefreshExpired = (Date.now() - (state.runsFetchMeta.lastFullFetchAt || 0)) > FULL_REFRESH_STALE_MS;
      const shouldFetchAllPages = totalCount > PAGE_SIZE && (
        fetchOptions.refreshAllPages ||
        !state.runsFetchMeta.hasLoadedAllPages ||
        (!activeRunsPresent && (totalCountChanged || fullRefreshExpired))
      );

      if (shouldFetchAllPages) {
        await _fetchRemainingPages(data, totalCount);
        state.runsFetchMeta.hasLoadedAllPages = true;
        state.runsFetchMeta.lastFullFetchAt = Date.now();
        state.runsFetchMeta.totalCount = totalCount;
      } else {
        state.runsFetchMeta.hasLoadedAllPages = state.flatRuns.length >= totalCount;
      }
    } catch (err) {
      console.error('Failed to fetch runs:', err);
      if (err && err.message === 'Project not found') {
        showProjectNotFound();
        return;
      }
      el('loading').innerHTML = `
        <span style="color:var(--error);">Failed to load runs</span>
        <span>Is the server running?</span>
      `;
    } finally {
      state.runsFetchMeta.inFlight = false;
      if (state.runsFetchMeta.pendingOptions) {
        const pending = state.runsFetchMeta.pendingOptions;
        state.runsFetchMeta.pendingOptions = null;
        fetchRuns(pending);
      }
    }
  }

  function showAuthError() {
    // Hide everything except header logo
    el('loading').style.display = 'none';
    hideDashboardChrome();
    const headerMeta = document.querySelector('.stats-bar .header-meta');
    if (headerMeta) headerMeta.style.display = 'none';

    const main = document.querySelector('main');
    if (window.QymAuth) {
      window.QymAuth.renderAuthGate(main, {
        message: 'Sign in to access the evaluation dashboard',
      });
    }
  }

  function showProjectNotFound() {
    const slug = getProjectSlugFromPath();
    if (window.QymShell && window.QymShell.renderProjectNotFound) {
      window.QymShell.renderProjectNotFound(slug);
      return;
    }

    el('loading').style.display = 'none';
    hideDashboardChrome();
    const main = document.querySelector('main');
    if (!main) return;
    main.innerHTML = `
      <div style="max-width:640px;margin:56px auto;padding:0 20px;">
        <div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:12px;padding:28px 24px;">
          <div style="font-size:var(--font-sm);font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:var(--error);margin-bottom:12px;">Missing Project</div>
          <h1 style="margin:0 0 10px 0;font-size:var(--font-title);line-height:1.2;color:var(--text-primary);">Project not found</h1>
          <p style="margin:0;color:var(--text-secondary);font-size:var(--font-md);line-height:1.6;">The requested project does not exist, is archived, or you no longer have access to it.</p>
          ${slug ? `<div style="margin-top:16px;padding:10px 12px;border-radius:8px;background:var(--bg-elevated);border:1px solid var(--border-subtle);font-family:var(--font-mono);font-size:var(--font-base);color:var(--text-muted);">Slug: ${escapeHtml(slug)}</div>` : ''}
          <div style="margin-top:20px;"><a href="/" class="btn btn-primary" style="display:inline-flex;text-decoration:none;">Back to Projects</a></div>
        </div>
      </div>
    `;
  }

  function updateProfileLink() {
    const u = state.currentUser || {};
    const displayName = u.display_name || (u.email ? u.email.split('@')[0] : 'User');
    const initials = getInitials(displayName);

    // Update trigger avatar
    const avatar = el('header-user-avatar');
    if (avatar) {
      avatar.textContent = initials;
    }

    // Update menu avatar
    const menuAvatar = el('header-menu-avatar');
    if (menuAvatar) {
      menuAvatar.textContent = initials;
    }

    // Update display name
    const nameEl = el('header-user-name');
    if (nameEl) {
      nameEl.textContent = displayName;
    }

    // Update dropdown header
    const emailEl = el('header-user-email');
    if (emailEl) {
      emailEl.textContent = u.email || '';
    }

    const roleEl = el('header-user-role');
    if (roleEl) {
      const projectRole = state.currentProject && state.currentProject.role ? ` · ${state.currentProject.role}` : '';
      roleEl.textContent = `${u.role || ''}${projectRole}`;
    }

    // Show admin menu items for ADMIN users
    const adminLink = el('header-admin-link');
    if (adminLink) {
      adminLink.style.display = u.role === 'ADMIN' ? '' : 'none';
    }
    const trashLink = el('header-trash-link');
    if (trashLink) {
      trashLink.style.display = u.role === 'ADMIN' ? '' : 'none';
    }

    const reviewsLink = el('header-reviews-link');
    if (reviewsLink && state.currentProject && state.currentProject.slug) {
      reviewsLink.href = projectUrl(state.currentProject.slug, 'reviews');
    }

    const settingsLink = el('header-project-settings-link');
    if (settingsLink && state.currentProject && state.currentProject.slug) {
      settingsLink.href = projectUrl(state.currentProject.slug, 'settings');
      settingsLink.style.display = '';
    } else if (settingsLink) {
      settingsLink.style.display = 'none';
    }

    renderProjectSwitcher();

    // Setup dropdown toggle
    setupHeaderUserDropdown();
  }

  function renderProjectSwitcher() {
    const wrapper = el('project-switcher');
    const trigger = el('project-switcher-btn');
    const menu = el('project-switcher-menu');
    if (!wrapper || !trigger || !menu) return;

    const projects = state.availableProjects || [];
    if (!projects.length) {
      wrapper.style.display = 'none';
      return;
    }

    wrapper.style.display = '';
    trigger.textContent = state.currentProject && state.currentProject.name ? state.currentProject.name : 'Choose Project';
    menu.innerHTML = projects.map(project => `
      <a class="project-switcher-item${state.currentProject && state.currentProject.slug === project.slug ? ' active' : ''}" data-project-switch="${escapeHtml(project.slug)}" href="${projectUrl(project.slug)}">
        <span>${escapeHtml(project.name)}</span>
        <span>${escapeHtml(project.role || '')}</span>
      </a>
    `).join('');
    menu.querySelectorAll('[data-project-switch]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        if (isModifiedEvent(e)) return;
        const slug = btn.getAttribute('data-project-switch') || '';
        if (!slug) return;
        storeProjectSlug(slug);
        navigateTo(projectUrl(slug));
        e.preventDefault();
      });
    });
  }

  function setupHeaderUserDropdown() {
    const dropdown = el('header-user-dropdown');
    const trigger = el('header-user-trigger');
    if (!dropdown || !trigger) return;

    // Prevent duplicate listeners
    if (trigger.dataset.initialized) return;
    trigger.dataset.initialized = 'true';

    trigger.addEventListener('click', (e) => {
      e.stopPropagation();
      dropdown.classList.toggle('open');
    });

    // Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
      if (!dropdown.contains(e.target)) {
        dropdown.classList.remove('open');
      }
    });

    // Close on escape key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        dropdown.classList.remove('open');
      }
    });
  }

  function populateFilterDropdowns() {
    // For each filter, compute applicable values from runs matching ALL OTHER active filters.
    // This ensures each dropdown only shows values that would produce results.
    function runsExcluding(skipFilter) {
      let runs = state.flatRuns;
      switch (state.quickFilter) {
        case 'today':
          runs = runs.filter(r => isToday(r.timestamp));
          break;
        case 'week':
          runs = runs.filter(r => isWithinDays(r.timestamp, 7));
          break;
      }
      if (skipFilter !== 'tasks' && state.filterTasks.size > 0 && !state.filterTasks.has('__none__')) {
        runs = runs.filter(r => matchesFilterSelection(state.filterTasks, r.task_name));
      }
      if (skipFilter !== 'datasets' && state.filterDatasets.size > 0 && !state.filterDatasets.has('__none__')) {
        runs = runs.filter(r => matchesFilterSelection(state.filterDatasets, getRunDatasetKey(r)));
      }
      if (skipFilter !== 'models' && state.filterModels.size > 0 && !state.filterModels.has('__none__')) {
        runs = runs.filter(r => matchesFilterSelection(state.filterModels, getRunModelKey(r)));
      }
      if (skipFilter !== 'statuses' && state.filterStatuses.size > 0 && !state.filterStatuses.has('__none__')) {
        runs = runs.filter(r => matchesFilterSelection(state.filterStatuses, r.status));
      }
      if (skipFilter !== 'versions' && state.filterVersions.size > 0 && !state.filterVersions.has('__none__')) {
        runs = runs.filter(r => matchesFilterSelection(state.filterVersions, getRunVersionKey(r)));
      }
      if (skipFilter !== 'users' && state.filterUsers.size > 0 && !state.filterUsers.has('__none__')) {
        runs = runs.filter(r => matchesFilterSelection(state.filterUsers, getRunOwnerKey(r)));
      }
      return runs;
    }

    const tasks = collectFilterValues(runsExcluding('tasks'), r => r.task_name);
    const datasets = collectFilterValues(runsExcluding('datasets'), r => getRunDatasetKey(r));
    const models = collectFilterValues(runsExcluding('models'), r => getRunModelKey(r)).sort(compareModelVariantKeys);
    const statusValues = collectFilterValues(runsExcluding('statuses'), r => r.status);
    const ownerValues = collectFilterValues(runsExcluding('users'), r => getRunOwnerKey(r));
    const owners = ownerValues
      .filter(v => v !== EMPTY_FILTER_VALUE)
      .sort((a, b) => getOwnerFilterLabel(a).localeCompare(getOwnerFilterLabel(b)))
      .concat(ownerValues.includes(EMPTY_FILTER_VALUE) ? [EMPTY_FILTER_VALUE] : []);
    const constrainingFiltersActive = state.quickFilter !== 'all'
      || state.filterTasks.size > 0
      || state.filterDatasets.size > 0
      || state.filterModels.size > 0
      || state.filterStatuses.size > 0
      || state.filterUsers.size > 0;
    const versionValues = collectFilterValues(runsExcluding('versions'), r => getRunVersionKey(r));
    const versions = (!constrainingFiltersActive && state.knownVersions.size > versionValues.length)
      ? Array.from(new Set([...versionValues, ...state.knownVersions])).sort()
      : versionValues;

    state.allModels = [...new Set(state.flatRuns.map(r => getRunModelKey(r)).filter(m => !isEmptyFilterValue(m)))].sort(compareModelVariantKeys);

    // Task multi-select
    buildMultiSelect({
      btnId: 'filter-task-btn', dropdownId: 'filter-task-dropdown',
      stateSet: state.filterTasks, values: tasks,
      labelFn: null, defaultLabel: 'All Tasks',
      showSearch: true, searchPlaceholder: 'Search tasks...',
      onchange: () => { state.modelsViewState.selectedMetric = ''; state.modelsViewState.modelRunSelections = {}; },
    });

    // Dataset multi-select — each dataset version is its own entry.
    buildMultiSelect({
      btnId: 'filter-dataset-btn', dropdownId: 'filter-dataset-dropdown',
      stateSet: state.filterDatasets, values: datasets,
      labelFn: getDatasetFilterLabel, htmlLabelFn: (k) => renderDatasetFilterLabel(k),
      defaultLabel: 'All Datasets',
      showSearch: true, searchPlaceholder: 'Search datasets...',
      onchange: () => { state.modelsViewState.selectedMetric = ''; state.modelsViewState.modelRunSelections = {}; },
    });

    // Model multi-select
    buildMultiSelect({
      btnId: 'filter-model-btn', dropdownId: 'filter-model-dropdown',
      stateSet: state.filterModels, values: models,
      labelFn: (m) => getModelFilterOptionLabel(m), defaultLabel: 'All Models',
      htmlLabelFn: (m) => renderModelLabelForModelName(m),
      showSearch: true, searchPlaceholder: 'Search models...',
      colorFn: (m, idx) => CHART_COLORS[state.allModels.indexOf(m) % CHART_COLORS.length],
    });

    // Status multi-select
    buildMultiSelect({
      btnId: 'filter-status-btn', dropdownId: 'filter-status-dropdown',
      stateSet: state.filterStatuses, values: statusValues,
      labelFn: (s) => isEmptyFilterValue(s) ? 'Empty / Missing' : s.charAt(0) + s.slice(1).toLowerCase(), defaultLabel: 'All Status',
      showSearch: false,
    });

    // User multi-select
    buildMultiSelect({
      btnId: 'filter-user-btn', dropdownId: 'filter-user-dropdown',
      stateSet: state.filterUsers, values: owners,
      labelFn: getOwnerFilterLabel,
      htmlLabelFn: (v) => renderOwnerFilterLabel(v),
      defaultLabel: 'All Users',
      showSearch: true, searchPlaceholder: 'Search users...',
    });

    // Version multi-select
    buildMultiSelect({
      btnId: 'filter-version-btn', dropdownId: 'filter-version-dropdown',
      stateSet: state.filterVersions, values: versions,
      labelFn: (v) => {
        if (v === EMPTY_FILTER_VALUE) return 'Empty / Missing';
        return v;
      },
      defaultLabel: 'All Versions', showSearch: true, searchPlaceholder: 'Search versions...',
    });
  }

  function startHeartbeat() {
    // Heartbeat disabled — no backend endpoint exists
  }

  // ═══════════════════════════════════════════════════
  // EVENT LISTENERS
  // ═══════════════════════════════════════════════════

  // Generic multi-select dropdown toggles
  ['filter-task-btn', 'filter-dataset-btn', 'filter-model-btn', 'filter-version-btn', 'filter-status-btn', 'filter-user-btn', 'metric-visibility-btn', 'models-stat-visibility-btn'].forEach(id => {
    el(id)?.addEventListener('click', (e) => {
      e.stopPropagation();
      const wrapper = e.target.closest('.multi-select-wrapper');
      const dd = wrapper?.querySelector('.multi-select-dropdown');
      if (dd) {
        // Close other open dropdowns first
        document.querySelectorAll('.multi-select-dropdown.open').forEach(other => {
          if (other !== dd) other.classList.remove('open');
        });
        dd.classList.toggle('open');
      }
    });
  });

  // Unified click-outside handler for all multi-select dropdowns
  document.addEventListener('click', (e) => {
    document.querySelectorAll('.multi-select-dropdown.open').forEach(dd => {
      if (!dd.parentElement.contains(e.target)) {
        dd.classList.remove('open');
      }
    });
  });

  // Close actions dropdowns when clicking outside
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.actions-dropdown')) {
      document.querySelectorAll('.actions-dropdown.open').forEach(d => {
        d.classList.remove('open');
      });
    }
  });

  // Clear all filters button
  el('clear-all-filters')?.addEventListener('click', clearAllFilters);

  // Quick filters
  $$('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.quickFilter = btn.dataset.filter;
      state.focusedIndex = -1;
      render();
    });
  });

  // View toggle (Charts vs Runs vs Models)
  $$('.view-toggle-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.view-toggle-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.currentView = btn.dataset.view;
      render();
    });
  });

  // Models view dropdowns (metric only - task/dataset use global filters)
  el('models-metric-select')?.addEventListener('change', (e) => {
    state.modelsViewState.selectedMetric = e.target.value;
    render();
  });

  el('models-k-input')?.addEventListener('change', (e) => {
    const value = parseInt(e.target.value);
    if (!isNaN(value) && value >= 1) {
      state.modelsViewState.globalK = value;
      state.modelsViewState.modelRunSelections = {};  // Clear custom selections when K changes
      render();
    }
  });

  // Models threshold slider
  el('models-threshold-slider')?.addEventListener('input', (e) => {
    const value = parseFloat(e.target.value);
    const thresholdValue = el('models-threshold-value');
    if (thresholdValue) thresholdValue.textContent = `${value}%`;
  });

  el('models-threshold-slider')?.addEventListener('change', (e) => {
    const value = parseFloat(e.target.value);
    if (!isNaN(value) && value >= 0 && value <= 100) {
      state.modelsViewState.threshold = value / 100;
      // Clear stats cache so they get recalculated with new threshold
      state.modelsViewState.modelStats = {};
      renderModelsView();
    }
  });

  // Close run selection modal when clicking outside
  el('run-selection-modal')?.addEventListener('click', (e) => {
    if (e.target.id === 'run-selection-modal') {
      el('run-selection-modal').style.display = 'none';
    }
  });

  // Select all checkbox
  el('select-all')?.addEventListener('change', selectAll);
  document.querySelectorAll('[data-table-page="prev"]').forEach(btn => btn.addEventListener('click', () => {
    setTablePage(state.tablePage - 1, { syncFocus: true });
    render();
  }));
  document.querySelectorAll('[data-table-page="next"]').forEach(btn => btn.addEventListener('click', () => {
    setTablePage(state.tablePage + 1, { syncFocus: true });
    render();
  }));

  // Compare actions
  el('compare-view')?.addEventListener('click', openComparison);
  el('cohort-view')?.addEventListener('click', openCohortComparison);
  el('delete-selected')?.addEventListener('click', confirmDeleteSelected);
  el('compare-clear')?.addEventListener('click', clearSelection);

  // Keyboard navigation
  document.addEventListener('keydown', (e) => {
    // Ignore if focused on input
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA') {
      if (e.key === 'Escape') {
        e.target.blur();
      }
      return;
    }

    switch (e.key) {
      case 'j':
      case 'ArrowDown':
        e.preventDefault();
        moveFocus(1);
        break;
      case 'k':
      case 'ArrowUp':
        e.preventDefault();
        moveFocus(-1);
        break;
      case 'g':
        if (!e.shiftKey) {
          e.preventDefault();
          state.focusedIndex = 0;
          setTablePage(1);
          render();
        }
        break;
      case 'G':
        e.preventDefault();
        state.focusedIndex = state.filteredRuns.length - 1;
        setTablePage(getTablePageCount(state.filteredRuns.length));
        render();
        break;
      case 'Enter':
        e.preventDefault();
        openFocusedRun();
        break;
      case 'x':
        e.preventDefault();
        toggleFocusedSelect();
        break;
      case 'c':
        if (state.cohortAnchorRuns) {
          e.preventDefault();
          openCohortComparison();
        } else if (state.selectedRuns.size >= 2) {
          e.preventDefault();
          openComparison();
        }
        break;
      case 'Escape':
        e.preventDefault();
        clearSelection();
        break;
      case '?':
        e.preventDefault();
        el('help-modal').style.display = 'flex';
        break;
      case '1':
      case '2':
      case '3':
        const filters = ['all', 'today', 'week'];
        const idx = parseInt(e.key) - 1;
        if (idx >= 0 && idx < filters.length) {
          e.preventDefault();
          state.quickFilter = filters[idx];
          $$('.filter-btn').forEach((b, i) => b.classList.toggle('active', i === idx));
          render();
        }
        break;
      case 't':
        e.preventDefault();
        state.currentView = 'table';
        $$('.view-toggle-btn').forEach(b => b.classList.toggle('active', b.dataset.view === 'table'));
        render();
        break;
      case 'h':
        e.preventDefault();
        state.currentView = 'charts';
        $$('.view-toggle-btn').forEach(b => b.classList.toggle('active', b.dataset.view === 'charts'));
        render();
        break;
      case 'm':
        e.preventDefault();
        state.currentView = 'models';
        $$('.view-toggle-btn').forEach(b => b.classList.toggle('active', b.dataset.view === 'models'));
        render();
        break;
    }
  });

  // Close modal on click outside
  el('help-modal')?.addEventListener('click', (e) => {
    if (e.target === el('help-modal')) {
      el('help-modal').style.display = 'none';
    }
  });

  // Header help shortcut
  $('.help-trigger')?.addEventListener('click', () => {
    el('help-modal').style.display = 'flex';
  });

  // ═══════════════════════════════════════════════════
  // TOAST NOTIFICATIONS
  // ═══════════════════════════════════════════════════

  function showToast(type, title, message, duration = 5000) {
    let container = el('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      container.className = 'toast-container';
      document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    const icon = type === 'success' ? '✓' : '✕';

    toast.innerHTML = `
      <div class="toast-icon">${icon}</div>
      <div class="toast-content">
        <div class="toast-title">${title}</div>
        ${message ? `<div class="toast-message">${message}</div>` : ''}
      </div>
      <button class="toast-close">×</button>
    `;

    container.appendChild(toast);

    // Close button
    toast.querySelector('.toast-close').addEventListener('click', () => {
      dismissToast(toast);
    });

    // Auto dismiss
    if (duration > 0) {
      setTimeout(() => dismissToast(toast), duration);
    }

    return toast;
  }

  function dismissToast(toast) {
    toast.classList.add('toast-exit');
    setTimeout(() => toast.remove(), 300);
  }

  // ═══════════════════════════════════════════════════
  // WORKFLOW SUBMIT
  // ═══════════════════════════════════════════════════

  async function submitSelectedRuns() {
    if (state.selectedRuns.size === 0) return;
    const selectedRuns = state.flatRuns.filter(r => state.selectedRuns.has(r.file_path));

    // Pre-validate: check which runs can be submitted
    const submittableStatuses = ['COMPLETED', 'FAILED', 'REJECTED'];
    const submittable = [];
    const notSubmittable = [];

    for (const run of selectedRuns) {
      const status = run.status || '';
      if (submittableStatuses.includes(status)) {
        submittable.push(run);
      } else {
        notSubmittable.push(run);
      }
    }

    // If some runs can't be submitted, show a single clear error
    if (notSubmittable.length > 0) {
      const statuses = [...new Set(notSubmittable.map(r => r.status))].join(', ');
      showToast('error', 'Cannot Submit', `${notSubmittable.length} run(s) already have status: ${statuses}`);
      return;
    }

    // Submit only the valid runs
    let ok = 0;
    let failed = 0;

    for (const run of submittable) {
      const runId = run.run_id || run.file_path;
      try {
        const res = await fetch(apiUrl(`v1/runs/${encodeURIComponent(runId)}/submit`), { method: 'POST' });
        if (res.ok) ok++;
        else failed++;
      } catch (e) {
        failed++;
      }
    }

    try {
      await fetchRuns({ refreshAllPages: true });
    } catch {}

    try {
      if (failed === 0) showToast('success', 'Submitted', `Submitted ${ok} run(s)`);
      else showToast('error', 'Partial Submit', `Submitted ${ok}, failed ${failed}`);
    } catch {
      if (failed === 0) alert(`Submitted ${ok} run(s)`);
      else alert(`Submitted ${ok}, failed ${failed}`);
    }
  }

  // Compare panel: submit selected runs
  el('publish-selected')?.addEventListener('click', submitSelectedRuns);

  // ═══════════════════════════════════════════════════
  // STATE PERSISTENCE (for back/forward navigation)
  // ═══════════════════════════════════════════════════

  function saveDashboardState() {
    const {
      inFlightRequestPromise,
      inFlightRequestKey,
      renderToken,
      ...serializableModelsViewState
    } = state.modelsViewState || {};
    const stateToSave = {
      currentView: state.currentView,
      modelsViewState: serializableModelsViewState,
      filterTasks: [...state.filterTasks],
      filterModels: [...state.filterModels],
      filterStatuses: [...state.filterStatuses],
      filterVersions: [...state.filterVersions],
      filterDatasets: [...state.filterDatasets],
      filterUsers: [...state.filterUsers],
      quickFilter: state.quickFilter,
      chartFirstColWidth: state.chartFirstColWidth,
    };
    sessionStorage.setItem(getDashboardStateKey(), JSON.stringify(stateToSave));
  }

  function restoreDashboardState() {
    const saved = sessionStorage.getItem(getDashboardStateKey());
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        // __QYM_INITIAL_VIEW__ takes precedence (set by each page's HTML)
        if (window.__QYM_INITIAL_VIEW__) {
          state.currentView = window.__QYM_INITIAL_VIEW__;
        } else if (parsed.currentView) {
          state.currentView = parsed.currentView;
        }
        $$('.view-toggle-btn').forEach(b => b.classList.toggle('active', b.dataset.view === state.currentView));
        if (parsed.modelsViewState) {
          const restoredModelsViewState = { ...state.modelsViewState, ...parsed.modelsViewState };
          restoredModelsViewState.inFlightRequestKey = '';
          restoredModelsViewState.inFlightRequestPromise = null;
          restoredModelsViewState.renderToken = 0;
          if (restoredModelsViewState.visibleStatKeys !== null && !Array.isArray(restoredModelsViewState.visibleStatKeys)) {
            restoredModelsViewState.visibleStatKeys = null;
          }
          if (Array.isArray(restoredModelsViewState.visibleStatKeys)
              && restoredModelsViewState.visibleStatKeys.includes('avgLatency')
              && !restoredModelsViewState.visibleStatKeys.includes('medianLatency')) {
            restoredModelsViewState.visibleStatKeys = [...restoredModelsViewState.visibleStatKeys, 'medianLatency'];
          }
          if (!Array.isArray(restoredModelsViewState.visibleTraceMetrics)) {
            restoredModelsViewState.visibleTraceMetrics = [];
          }
          state.modelsViewState = restoredModelsViewState;
        }
        if (parsed.filterTasks) state.filterTasks = new Set(parsed.filterTasks);
        if (parsed.filterModels) state.filterModels = new Set(parsed.filterModels);
        if (parsed.filterStatuses) state.filterStatuses = new Set(parsed.filterStatuses);
        if (parsed.filterVersions) state.filterVersions = new Set(parsed.filterVersions);
        if (parsed.filterDatasets) state.filterDatasets = new Set(parsed.filterDatasets);
        if (parsed.filterUsers) state.filterUsers = new Set(parsed.filterUsers);
        if (parsed.quickFilter) {
          state.quickFilter = parsed.quickFilter;
          $$('.filter-btn').forEach(b => b.classList.toggle('active', b.dataset.filter === state.quickFilter));
        }
        applyChartFirstColWidth(parsed.chartFirstColWidth || CHART_FIRST_COL_DEFAULT_WIDTH);
      } catch (e) {
        console.warn('Failed to restore dashboard state:', e);
      }
    } else {
      applyChartFirstColWidth(CHART_FIRST_COL_DEFAULT_WIDTH);
    }
  }

  // Save state before navigating away
  window.addEventListener('beforeunload', saveDashboardState);
  window.addEventListener('pagehide', saveDashboardState);
  document.addEventListener('qym:before-navigate', saveDashboardState);

  // Also save on visibility change (for mobile)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      saveDashboardState();
    }
  });

  // ═══════════════════════════════════════════════════
  // INIT
  // ═══════════════════════════════════════════════════

  // Check auth first before loading dashboard
  async function checkAuthAndInit() {
    try {
      restoreDashboardState();
      restoreRunsDataCache();

      // If shell is present, wait for it to fetch the user
      if (window.QymShell && !window.__QYM_USER__) {
        await new Promise(r => document.addEventListener('qym:shell-ready', r, { once: true }));
      }
      if (window.__QYM_USER__) {
        state.currentUser = window.__QYM_USER__;
        startHeartbeat();
        fetchRuns({ refreshAllPages: true });
        return;
      }
      // Fallback: fetch directly (no shell, or shell failed)
      const res = await fetch(apiUrl('v1/me'));
      if (res.status === 401) {
        showAuthError();
        return;
      }
      if (!res.ok) {
        throw new Error('Auth check failed');
      }
      // Authenticated - proceed with dashboard
      startHeartbeat();
      fetchRuns({ refreshAllPages: true });
    } catch (err) {
      console.error('Auth check error:', err);
      showAuthError();
    }
  }

  checkAuthAndInit();

  // Refresh cadence:
  // - If any runs are RUNNING, refresh frequently to show progress.
  // - Otherwise, keep the dashboard light.
  // Use a global ref so previous IIFE executions (after SPA navigation)
  // have their intervals cleared when dashboard.js re-runs.
  if (window.__QYM_DASHBOARD_INTERVAL__) {
    clearInterval(window.__QYM_DASHBOARD_INTERVAL__);
    window.__QYM_DASHBOARD_INTERVAL__ = null;
  }
  function updateRunsRefreshCadence() {
    try {
      const intervalMs = hasActiveRuns() ? LIVE_REFRESH_INTERVAL_MS : IDLE_REFRESH_INTERVAL_MS;
      if (window.__QYM_DASHBOARD_INTERVAL__) clearInterval(window.__QYM_DASHBOARD_INTERVAL__);
      window.__QYM_DASHBOARD_INTERVAL__ = setInterval(fetchRuns, intervalMs);
    } catch {
      if (window.__QYM_DASHBOARD_INTERVAL__) clearInterval(window.__QYM_DASHBOARD_INTERVAL__);
      window.__QYM_DASHBOARD_INTERVAL__ = setInterval(fetchRuns, IDLE_REFRESH_INTERVAL_MS);
    }
  }
  updateRunsRefreshCadence();

})();
