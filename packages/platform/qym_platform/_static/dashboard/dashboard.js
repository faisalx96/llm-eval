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
  const BASE_URL = (() => {
    const loc = window.location;
    // Get the pathname and ensure it ends with /
    let base = loc.pathname;
    // If pathname doesn't end with /, get the directory part
    if (!base.endsWith('/')) {
      base = base.substring(0, base.lastIndexOf('/') + 1) || '/';
    }
    return loc.origin + base;
  })();

  // Helper to build API URLs
  function apiUrl(path) {
    // Remove leading ./ or / from path
    const cleanPath = path.replace(/^\.?\//, '');
    return BASE_URL + cleanPath;
  }

  // ═══════════════════════════════════════════════════
  // STATE
  // ═══════════════════════════════════════════════════

  const state = {
    runs: null,
    flatRuns: [],
    filteredRuns: [],
    sortKey: 'time-desc',
    quickFilter: 'all',
    filterTasks: new Set(),
    filterModels: new Set(),  // Multi-select for models
    filterDatasets: new Set(),
    filterStatuses: new Set(),
    filterVersions: new Set(),
    currentView: 'charts',  // Default to charts view
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
  const MODELS_VIEW_SCORE_STAT_KEYS = ['passAtK', 'passHatK', 'maxAtK', 'consistency', 'reliability', 'avgScore', 'failedCount', 'avgLatency', 'correctDistribution'];
  const MODELS_VIEW_NUMERIC_STAT_KEYS = ['avgScore', 'minScore', 'maxAtK', 'stddevScore', 'totalScoreSum', 'avgLatency'];
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
      ..._traceMetricsForRuns(runs).map(tm => tm.key),
    ];
  }

  function _visibleTraceMetrics(runs = null) {
    const traceMetrics = _traceMetricsForRuns(runs);
    if (traceMetrics.length === 0) return [];
    const vis = state.visibleMetrics;
    if (vis === null) return traceMetrics;
    return traceMetrics.filter(tm => vis.has(tm.key));
  }

  function getMetricDisplayName(metricKey) {
    const traceMetric = TRACE_METRICS.find(tm => tm.key === metricKey);
    return traceMetric ? traceMetric.label : metricKey;
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
        && candidate.model_name === run.model_name
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

  function isEmptyFilterValue(value) {
    return value === null || value === undefined || String(value).trim() === '';
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

  function buildMultiSelect({ btnId, dropdownId, stateSet, values, labelFn, defaultLabel, showSearch, searchPlaceholder, colorFn, onchange }) {
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
      return `<div class="multi-select-option${emptyClass}" data-value="${escapeHtml(v)}" title="${escapeHtml(label)}"${hidden}>${colorDot}<input type="checkbox" ${checked} /><span>${escapeHtml(label)}</span></div>`;
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
        syncMultiSelect({ btnId, dropdownId, stateSet, values, defaultLabel, labelFn });
        if (onchange) onchange();
        render();
      });
    });

    syncMultiSelect({ btnId, dropdownId, stateSet, values, defaultLabel, labelFn });
  }

  function syncMultiSelect({ btnId, dropdownId, stateSet, values, defaultLabel, labelFn }) {
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
        btn.textContent = getFilterOptionLabel([...stateSet][0], labelFn);
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
    const metricOptions = [
      ...(availableMetrics || []),
      ...traceMetrics.map(tm => tm.key),
    ];

    if (metricOptions.length === 0) {
      wrapper.style.display = 'none';
      return;
    }
    wrapper.style.display = '';

    const visibleMetrics = new Set(getVisibleMetrics(metricOptions));
    const allVisible = visibleMetrics.size === metricOptions.length;
    const searchValue = dropdown.querySelector('.model-search-input')?.value || '';
    dropdown.innerHTML =
      '<div class="ms-actions">' +
        '<button class="ms-action-btn" id="mv-select-all">All</button>' +
        '<button class="ms-action-btn" id="mv-select-none">None</button>' +
      '</div>' +
      '<div class="model-search-box"><input type="text" class="model-search-input" placeholder="Search metrics..." value="' + escapeHtml(searchValue) + '" /></div>' +
      availableMetrics.map(m => {
        const checked = allVisible || visibleMetrics.has(m) ? 'checked' : '';
        const hidden = searchValue && !m.toLowerCase().includes(searchValue.toLowerCase()) ? ' style="display:none"' : '';
        return `<div class="multi-select-option"${hidden}><input type="checkbox" ${checked} data-mv-metric="${escapeHtml(m)}" /><span>${escapeHtml(m)}</span></div>`;
      }).join('') +
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
          opt.style.display = m.toLowerCase().includes(q) ? '' : 'none';
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
      btn.textContent = 'No Columns';
      btn.classList.add('has-selection');
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
        case 'avgLatency':
          return { key, label: 'Avg Latency' };
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
            // Some views/filters rely on this precomputed display value.
            display_model: stripModelProvider(run.model_name || modelName || ''),
            completion_rate: completionRate,
            success_on_completed_rate: successOnCompletedRate,
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
      totalModels: new Set(runs.map(r => r.model_name)).size,
      totalItems: runs.reduce((sum, r) => sum + (r.total_items || 0), 0),
      avgSuccess: runs.length ? runs.reduce((sum, r) => sum + (r.success_rate || 0), 0) / runs.length : 0,
      byModel: {},
      byTask: {},
      byDay: {},
    };

    // Aggregate by model
    for (const run of runs) {
      const model = run.model_name;
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

      const model = run.model_name;
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
        total_items: run.total_items,
        git_branch: run.git_branch || '',
        git_commit: run.git_commit || '',
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
    const sortedModels = Object.keys(modelFreq).sort((a, b) => modelFreq[b] - modelFreq[a]);

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
        runs = runs.filter(r => matchesFilterSelection(state.filterModels, r.model_name));
      }
    }
    if (state.filterDatasets.size > 0 && !state.filterDatasets.has('__none__')) {
      runs = runs.filter(r => matchesFilterSelection(state.filterDatasets, r.dataset_name));
    } else if (state.filterDatasets.has('__none__')) {
      runs = [];
    }
    if (state.filterStatuses.size > 0 && !state.filterStatuses.has('__none__')) {
      runs = runs.filter(r => matchesFilterSelection(state.filterStatuses, r.status));
    } else if (state.filterStatuses.has('__none__')) {
      runs = [];
    }
    if (state.filterVersions.size > 0 && !state.filterVersions.has('__none__')) {
      runs = runs.filter(r => matchesFilterSelection(state.filterVersions, r.git_commit));
    } else if (state.filterVersions.has('__none__')) {
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
        runs.sort((a, b) => a.model_name.localeCompare(b.model_name));
        break;
      case 'model-desc':
        runs.sort((a, b) => b.model_name.localeCompare(a.model_name));
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

    el('total-runs').textContent = formatNumber(agg.totalRuns);
    el('total-tasks').textContent = formatNumber(agg.totalTasks);
    el('total-models').textContent = formatNumber(agg.totalModels);
    el('avg-success').textContent = formatPercent(agg.avgSuccess);
    el('total-items').textContent = formatNumber(agg.totalItems);

    // Weekly trend sparkline
    const trendEl = el('weekly-trend');
    const days = Object.values(agg.byDay);
    const maxRuns = Math.max(...days.map(d => d.runs), 1);

    trendEl.innerHTML = days.map((d, i) => {
      const height = Math.max(2, (d.runs / maxRuns) * 16);
      const avgSuccess = d.runs ? d.successSum / d.runs : 0;
      const color = getSuccessClass(avgSuccess);
      const colorVar = color === 'high' ? 'var(--success)' : color === 'mid' ? 'var(--warning)' : 'var(--error)';
      return `<div class="trend-bar" style="height:${height}px;background:${d.runs ? colorVar : 'var(--border-default)'}" title="Day ${i + 1}: ${d.runs} runs"></div>`;
    }).join('');
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

  function renderMiniBarCell({ value, label, ratio, modelIdx, isAggregate = false, cellClass = 'chart-metric-cell' }) {
    const safeRatio = Number.isFinite(ratio) ? Math.max(0, Math.min(ratio, 1)) : 0;
    const width = value === null || value === undefined ? 0 : Math.max(safeRatio * 100, 2);
    const aggregateClass = isAggregate && !Number.isInteger(modelIdx) ? ' aggregate' : '';
    const modelAttr = Number.isInteger(modelIdx) ? ` data-model-idx="${modelIdx}"` : '';
    return `
      <div class="${cellClass}">
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
        <div class="legend-item ${isActive ? '' : 'inactive'}" data-model="${model}" title="${model}">
          <span class="legend-color" style="background:${CHART_COLORS[idx % CHART_COLORS.length]}"></span>
          <span>${stripModelProvider(model)}</span>
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
            isMultiRun: data.runs > 1,
            git_branch: run.git_branch || '',
            git_commit: run.git_commit || '',
          });
        }
      }

      const visibleTraceMetrics = _visibleTraceMetrics(allRuns);

      if (metrics.length === 0 && visibleTraceMetrics.length === 0) {
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

      // Generate unique card ID for sorting state
      const cardId = `${combo.task}|||${combo.dataset}`.replace(/[^a-zA-Z0-9]/g, '_');

      // Default sort by first metric descending
      if (!state.chartSortState) state.chartSortState = {};
      if (!state.chartSortState[cardId]) {
        state.chartSortState[cardId] = { key: metrics[0] || visibleTraceMetrics[0]?.key || 'latency', dir: 'desc' };
      }
      const sortState = state.chartSortState[cardId];

      // Grouping mode: run (default) / version / model
      if (!state.chartGroupMode) state.chartGroupMode = {};
      const groupMode = state.chartGroupMode[cardId] || 'run';

      function getChartSortDirection(key) {
        return key === 'model' ? 'asc' : 'desc';
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
        if (isTraceMetricKey(key)) return run.trace_stats?.[key] ?? -1;
        return run.metric_averages[key] ?? -1;
      }

      function getGroupSortValue(group, key) {
        if (key === 'model') return group.sortModel || group.label || '';
        const agg = group.agg || group;
        if (key === 'latency') return agg.avgLatency;
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
      const LATENCY_COLUMN_KEY = '__latency__';
      const traceMetricKeys = visibleTraceMetrics.map(tm => tm.key);
      const displayColumns = [...visualMetrics, ...numericMetrics, LATENCY_COLUMN_KEY, ...traceMetricKeys];
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
      const latencyScaleMax = Math.max(...allRuns.map(run => Number(run.latency || 0)), 0);

      const firstColSortKey = groupMode === 'version' ? null : 'model';
      const availableSortKeys = [
        ...(firstColSortKey ? [firstColSortKey] : []),
        ...displayColumns.map(column => (column === LATENCY_COLUMN_KEY ? 'latency' : column)),
      ];

      if (!availableSortKeys.includes(sortState.key)) {
        sortState.key = displayColumns[0] === LATENCY_COLUMN_KEY ? 'latency' : displayColumns[0];
        sortState.dir = getChartSortDirection(sortState.key);
        state.chartSortState[cardId] = sortState;
      }

      // Build header row with sortable columns
      const headerCells = displayColumns.map(column => {
        if (column === LATENCY_COLUMN_KEY) {
          const isActive = sortState.key === 'latency';
          const arrow = isActive ? (sortState.dir === 'desc' ? '\u2193' : '\u2191') : '';
          return `<span class="chart-col-header chart-col-header-latency sortable-col ${isActive ? 'active' : ''}" data-card="${cardId}" data-sort="latency" title="Avg Latency"><span class="chart-col-header-label">\u26A1 Avg Latency</span>${arrow ? `<span class="chart-col-sort">${arrow}</span>` : ''}</span>`;
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

      function renderLatencyValueCell(latencyValue, modelIdx, isAggregate = false) {
        if (!latencyValue) {
          return `<div class="chart-latency-cell"><span class="metric-na">\u2014</span></div>`;
        }
        return renderMiniBarCell({
          value: latencyValue,
          label: formatLatency(latencyValue),
          ratio: latencyScaleMax > 0 ? latencyValue / latencyScaleMax : 0,
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
        const displayModel = stripModelProvider(model);
        const hoverRunName = runData.run_name || 'none';
        let displayHtml = `<span class="model-name-text">${displayModel}</span>`;
        const tsMatch = run_id.match(/-(\d{2})(\d{2})(\d{2})-(\d{2})(\d{2})(?:-(\d+))?$/);
        if (tsMatch) {
          const [, yy, mm, dd, hh, min, counter] = tsMatch;
          const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
          const monthName = months[parseInt(mm, 10) - 1] || mm;
          const day = parseInt(dd, 10);
          const timeStr = `${hh}:${min}`;
          const counterStr = counter ? ` #${counter}` : '';
          displayHtml = `<span class="model-name-text">${displayModel}</span><span class="run-timestamp">${monthName} ${day} \u00b7 ${timeStr}${counterStr}</span>`;
        } else {
          displayHtml = `<span class="model-name-text">${displayModel}</span><span class="run-timestamp">${dt.date} \u00b7 ${dt.time}</span>`;
        }
        const versionStr = runData.git_commit ? (runData.git_branch ? `${runData.git_branch}/${runData.git_commit}` : runData.git_commit) : '';
        const versionTag = versionStr ? `<span class="chart-version-tag">${versionStr}</span>` : '';
        const tooltipText = `Run name: ${hoverRunName}${versionStr ? `\nVersion: ${versionStr}` : ''}`;
        const dataCells = displayColumns.map(column => {
          if (column === LATENCY_COLUMN_KEY) {
            return renderLatencyValueCell(latency, modelIdx);
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
        }
        const metricAverages = {};
        for (const m of metrics) {
          metricAverages[m] = agg[m] ? agg[m].sum / agg[m].count : undefined;
        }
        const traceAverages = {};
        for (const tm of visibleTraceMetrics) {
          traceAverages[tm.key] = traceAgg[tm.key] ? traceAgg[tm.key].sum / traceAgg[tm.key].count : undefined;
        }
        return { metricAverages, traceAverages, avgLatency: latCount > 0 ? latSum / latCount : 0 };
      }

      // --- Helper: render a group header row ---
      function renderGroupHeader(label, runCount, agg, groupId, groupModelIdx = null) {
        const isCollapsed = isChartGroupCollapsed(cardId, groupMode, groupId);
        const dataCells = displayColumns.map(column => {
          if (column === LATENCY_COLUMN_KEY) {
            return renderLatencyValueCell(agg.avgLatency, groupModelIdx, true);
          }
          if (isTraceMetricKey(column)) {
            return renderTraceMetricValueCell(column, agg.traceAverages?.[column], groupModelIdx, true);
          }
          return renderMetricValueCell(column, agg.metricAverages[column], groupModelIdx, true);
        }).join('');
        return `
          <div class="chart-table-group-header" data-group-id="${groupId}">
            <span class="chart-group-first-col">
              <span class="chart-group-toggle">${isCollapsed ? '\u25b6' : '\u25bc'}</span>
              <span class="chart-group-label">${label}</span>
              <span class="chart-group-count">${runCount} run${runCount !== 1 ? 's' : ''}</span>
            </span>
            ${dataCells}
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
        // Group runs by git_commit
        const groups = {};
        const ungrouped = [];
        for (const r of allRuns) {
          if (r.git_commit) {
            const key = r.git_commit;
            if (!groups[key]) groups[key] = { label: r.git_branch ? `${r.git_branch}/${r.git_commit}` : r.git_commit, runs: [] };
            groups[key].runs.push(r);
          } else {
            ungrouped.push(r);
          }
        }
        // Sort groups by aggregate metric
        const sortedGroups = Object.entries(groups).map(([key, g]) => {
          const agg = computeGroupAgg(g.runs);
          // Sort runs within group
          g.runs.sort(sortByState);
          return { key, label: g.label, runs: g.runs, agg };
        });
        sortedGroups.sort((a, b) => {
          return compareChartSortValues(
            getGroupSortValue(a, sortState.key),
            getGroupSortValue(b, sortState.key),
            sortState.dir
          );
        });

        for (const g of sortedGroups) {
          const groupId = `vg_${cardId}_${g.key}`;
          const isCollapsed = isChartGroupCollapsed(cardId, groupMode, groupId);
          if (!isCollapsed) hasExpandedGroups = true;
          rowsHtml += renderGroupHeader(g.label, g.runs.length, g.agg, groupId);
          rowsHtml += `<div class="chart-table-group-body${isCollapsed ? ' collapsed' : ''}" data-group-id="${groupId}">`;
          rowsHtml += g.runs.map(renderRunRow).join('');
          rowsHtml += `</div>`;
        }
        if (ungrouped.length > 0) {
          ungrouped.sort(sortByState);
          const ungroupedAgg = computeGroupAgg(ungrouped);
          const gid = `vg_${cardId}_ungrouped`;
          const isCollapsed = isChartGroupCollapsed(cardId, groupMode, gid);
          if (!isCollapsed) hasExpandedGroups = true;
          rowsHtml += renderGroupHeader('No version', ungrouped.length, ungroupedAgg, gid);
          rowsHtml += `<div class="chart-table-group-body${isCollapsed ? ' collapsed' : ''}" data-group-id="${gid}">`;
          rowsHtml += ungrouped.map(renderRunRow).join('');
          rowsHtml += `</div>`;
        }
      } else if (groupMode === 'model') {
        firstColLabel = 'Model';
        // Group runs by model
        const groups = {};
        for (const r of allRuns) {
          if (!groups[r.model]) groups[r.model] = [];
          groups[r.model].push(r);
        }
        const sortedGroups = Object.entries(groups).map(([model, runs]) => {
          const agg = computeGroupAgg(runs);
          runs.sort(sortByState);
          return { model, label: stripModelProvider(model), sortModel: stripModelProvider(model), runs, agg };
        });
        sortedGroups.sort((a, b) => {
          return compareChartSortValues(
            getGroupSortValue(a, sortState.key),
            getGroupSortValue(b, sortState.key),
            sortState.dir
          );
        });

        for (const g of sortedGroups) {
          const groupId = `mg_${cardId}_${g.model.replace(/[^a-zA-Z0-9]/g, '_')}`;
          const modelIdx = state.allModels.indexOf(g.model) % CHART_COLORS.length;
          const colorDot = `<span class="model-color-dot" style="background:${CHART_COLORS[modelIdx]}"></span>`;
          const isCollapsed = isChartGroupCollapsed(cardId, groupMode, groupId);
          if (!isCollapsed) hasExpandedGroups = true;
          rowsHtml += renderGroupHeader(`${colorDot}${g.label}`, g.runs.length, g.agg, groupId, modelIdx);
          rowsHtml += `<div class="chart-table-group-body${isCollapsed ? ' collapsed' : ''}" data-group-id="${groupId}">`;
          rowsHtml += g.runs.map(renderRunRow).join('');
          rowsHtml += `</div>`;
        }
      }

      // Check if version grouping should be available (any runs have git_commit)
      const hasVersions = allRuns.some(r => r.git_commit);

      const isGrouped = groupMode !== 'run';
      const expandCollapseBtn = isGrouped
        ? `<button class="chart-expand-collapse-btn" data-card="${cardId}">${hasExpandedGroups ? 'Collapse all' : 'Expand all'}</button>`
        : '';

      const controlsHtml = `
        <div class="chart-table-toolbar">
          <span class="chart-segment-control" data-card="${cardId}">
            <button class="chart-segment-btn ${groupMode === 'run' ? 'active' : ''}" data-mode="run">Run</button>
            <button class="chart-segment-btn ${groupMode === 'version' ? 'active' : ''}" data-mode="version" ${!hasVersions ? 'disabled title="No version data available"' : ''}>Version</button>
            <button class="chart-segment-btn ${groupMode === 'model' ? 'active' : ''}" data-mode="model">Model</button>
          </span>
          ${expandCollapseBtn}
        </div>
      `;

      const firstColHtml = `
        <span class="chart-col-header-run">
          <span class="chart-first-col-header-wrap">
            ${firstColSortKey
              ? `<button class="chart-first-col-sort sortable-col ${sortState.key === firstColSortKey ? 'active' : ''}" type="button" data-card="${cardId}" data-sort="${firstColSortKey}" title="Sort by ${firstColLabel.toLowerCase()}">
                  <span class="chart-col-header-label">${firstColLabel}</span>
                  ${sortState.key === firstColSortKey ? `<span class="chart-col-sort">${sortState.dir === 'desc' ? '\u2193' : '\u2191'}</span>` : ''}
                </button>`
              : `<span class="chart-first-col-title">${firstColLabel}</span>`}
            <button class="chart-col-resizer" type="button" title="Drag to resize first column. Double-click to reset width" aria-label="Resize first column"></button>
          </span>
        </span>
      `;

      const metricChartsHtml = `
        <div class="chart-table-shell">
          ${controlsHtml}
          <div class="chart-table-scroll">
            <div class="chart-table" data-card-id="${cardId}">
              <div class="chart-table-header">
                ${firstColHtml}
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
          // Navigate to run detail page
          window.location.href = apiUrl(`run/${encodeURIComponent(filePath)}`);
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
        renderChartsView();
      });
    });

    // Wire up group expand/collapse
    gridEl.querySelectorAll('.chart-table-group-header').forEach(header => {
      header.addEventListener('click', () => {
        const groupId = header.dataset.groupId;
        const card = header.closest('.chart-table')?.dataset.cardId;
        const body = gridEl.querySelector(`.chart-table-group-body[data-group-id="${groupId}"]`);
        const toggle = header.querySelector('.chart-group-toggle');
        if (body && card) {
          const isCollapsed = body.classList.toggle('collapsed');
          const mode = state.chartGroupMode?.[card] || 'run';
          setChartGroupCollapsed(card, mode, groupId, isCollapsed);
          if (toggle) toggle.textContent = isCollapsed ? '\u25b6' : '\u25bc';
          const expandBtn = header.closest('.chart-card')?.querySelector('.chart-expand-collapse-btn');
          if (expandBtn) {
            const bodies = header.closest('.chart-card').querySelectorAll('.chart-table-group-body');
            const anyExpanded = [...bodies].some(b => !b.classList.contains('collapsed'));
            expandBtn.textContent = anyExpanded ? 'Collapse all' : 'Expand all';
          }
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
            b.classList.add('collapsed');
            if (groupId) setChartGroupCollapsed(cardId, mode, groupId, true);
          } else {
            b.classList.remove('collapsed');
            if (groupId) setChartGroupCollapsed(cardId, mode, groupId, false);
          }
        });
        card.querySelectorAll('.chart-group-toggle').forEach(t => {
          t.textContent = anyExpanded ? '\u25b6' : '\u25bc';
        });
        btn.textContent = anyExpanded ? 'Expand all' : 'Collapse all';
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

    // Find the LATENCY column (insert metric columns before it)
    const latencyHeader = headerRow.querySelector('.col-latency');
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

    // Insert the ops separator before LATENCY and trace metric columns after LATENCY
    const vtm = _visibleTraceMetrics(state.filteredRuns);
    if (vtm.length > 0) {
      const sep = document.createElement('th');
      sep.className = 'col-trace-separator';
      headerRow.insertBefore(sep, latencyHeader);
      let insertAfter = latencyHeader;
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
      const numericFields = ['success', 'items', 'status', 'time', 'date', 'latency'];
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
  function extractRunTimestampGroup(run) {
    const name = run.run_name || run.external_run_id || '';
    // Match YYMMDD-HHMM (optionally followed by -N counter)
    const m = name.match(/(\d{6}-\d{4})(?:-\d+)?$/);
    if (!m) return null;
    return `${run.task_name}|||${m[1]}`;
  }

  function renderTableView() {
    const runs = state.filteredRuns;
    const tbody = el('runs-tbody');
    const availableMetrics = getAvailableMetricsForRuns(runs);
    const metricsToShow = getVisibleMetrics(availableMetrics);
    const visibleTraceMetrics = _visibleTraceMetrics(runs);

    if (state.sortKey.startsWith('metric-')) {
      const parts = state.sortKey.split('-');
      const metricName = parts.slice(1, -1).join('-');
      if (!metricsToShow.includes(metricName)) {
        state.sortKey = 'time-desc';
        sortRuns(runs);
      }
    }
    if (state.sortKey.startsWith('trace-')) {
      const parts = state.sortKey.split('-');
      const traceKey = parts.slice(1, -1).join('-');
      if (!visibleTraceMetrics.some(tm => tm.key === traceKey)) {
        state.sortKey = 'time-desc';
        sortRuns(runs);
      }
    }

    // Update header with dynamic metric columns
    updateTableHeader(metricsToShow);

    const _vtmCount = visibleTraceMetrics.length;
    const _traceColCount = _vtmCount > 0 ? _vtmCount + 1 : 0; // +1 for separator
    if (runs.length === 0) {
      const colCount = 11 + metricsToShow.length + _traceColCount;
      tbody.innerHTML = `
        <tr>
          <td colspan="${colCount}" style="text-align:center;padding:2rem;color:var(--text-muted);">
            No runs match current filters
          </td>
        </tr>
      `;
      return;
    }

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
    // 11 base columns + dynamic metric columns + trace metric columns
    const colCount = 11 + metricsToShow.length + _traceColCount;
    tbody.innerHTML = runs.map((run, idx) => {
      const groupKey = runGroupKeys[idx];
      const isGrouped = groupKey && realGroups[groupKey];
      const isFirstInGroup = isGrouped && groupKey !== lastGroupKey;
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
      const isSelected = state.selectedRuns.has(run.file_path);
      const isFocused = idx === state.focusedIndex;

      // Generate metric columns
      const metricCells = metricsToShow.map(metric => {
        const value = run.metric_averages?.[metric];
        if (value === undefined || value === null) {
          return `<td class="col-metric-value"><span class="metric-na">—</span></td>`;
        }
        const mType = state._metricTypes?.[metric] || window.QymMetrics.detectMetricTypeFromAvg(value);
        const metricClass = window.QymMetrics.getMetricColorClass(value, mType);
        const peerValues = getRunComboPeerValues(runs, run, candidate => candidate.metric_averages?.[metric]);
        const display = window.QymMetrics.formatMetricValueSmart(value, mType, peerValues);
        return `<td class="col-metric-value"><span class="metric-score ${metricClass}">${display}</span></td>`;
      }).join('');

      const status = run.status || '';
      const langfuseUrl = run.langfuse_url;
      const approval = run.approval || null;

      const role = (state.currentUser && state.currentUser.role) || '';
      const canApprove = role === 'MANAGER' && status === 'SUBMITTED';
      // Runs submitted via SDK/file upload land as COMPLETED/FAILED; those should be submittable for approval.
      // Managers don't submit - they approve/reject. Only non-managers can submit.
      const canSubmit = role !== 'MANAGER' && (status === 'COMPLETED' || status === 'FAILED');
      const progressText = (status === 'RUNNING' && run.progress_total)
        ? `${run.progress_completed || 0}/${run.progress_total}`
        : (status === 'RUNNING' ? `${run.progress_completed || 0}` : '');
      const progressPctText = (status === 'RUNNING' && typeof run.progress_pct === 'number')
        ? `${Math.round(run.progress_pct * 100)}%`
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
            class="${isSelected ? 'selected' : ''} ${isFocused ? 'focused' : ''} ${isGrouped ? 'grouped-run' : ''}">
          <td class="col-select" onclick="event.stopPropagation()">
            <label class="custom-checkbox">
              <input type="checkbox" class="row-checkbox" ${isSelected ? 'checked' : ''} />
              <span class="checkmark"></span>
            </label>
          </td>
          <td class="col-status">
            ${status ? `<span class="status-badge status-${status}" title="${escapeHtml(statusTooltip)}">${status}${progressPctText ? ` • ${progressPctText}` : ''}${progressText ? ` • ${progressText}` : ''}</span>` : ''}${(run.error_count > 0 && status !== 'RUNNING' && status !== 'PENDING') ? `<span class="status-errors" title="${run.error_count} item${run.error_count === 1 ? '' : 's'} errored">${run.error_count}⚠</span>` : ''}
          </td>
          <td class="col-run">
            <span class="run-id" title="${run.run_id}">${run.external_run_id ? truncateText(run.external_run_id, 30) : run.run_id.substring(0, 8)}</span>
          </td>
          <td class="col-task">
            <span class="tag task" title="${run.task_name}">${truncateText(run.task_name, 30)}</span>
          </td>
          <td class="col-model">
            <span class="tag model" title="${run.model_name}">
              <span class="model-color-dot" style="background:${CHART_COLORS[state.allModels.indexOf(run.model_name) % CHART_COLORS.length]}"></span>
              ${stripModelProvider(run.model_name)}
            </span>
          </td>
          <td class="col-dataset">
            <span class="tag" title="${run.dataset_name}">${truncateText(run.dataset_name, 25)}</span>
          </td>
          <td class="col-version">
            ${run.git_commit ? `<span class="version-badge" title="${run.git_branch ? run.git_branch + '/' : ''}${run.git_commit}">${run.git_branch ? run.git_branch + '/' : ''}${run.git_commit}</span>` : '<span style="color:var(--text-muted)">—</span>'}
          </td>
          ${metricCells}${visibleTraceMetrics.length > 0 ? '<td class="col-trace-separator"></td>' : ''}
          <td class="col-latency">
            <span class="latency-value">${run.avg_latency_ms ? formatLatency(run.avg_latency_ms) : '—'}</span>
          </td>${(() => {
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
            <span class="timestamp">
              <span class="date">${dt.date}</span>
              <span class="time">${dt.time}</span>
            </span>
          </td>
          <td class="col-actions">
            ${canApprove ? `
              <div class="actions-dropdown" onclick="event.stopPropagation()">
                <button class="actions-trigger workflow-trigger" title="Review">
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                    <polyline points="14 2 14 8 20 8"></polyline>
                    <line x1="16" y1="13" x2="8" y2="13"></line>
                    <line x1="16" y1="17" x2="8" y2="17"></line>
                  </svg>
                </button>
                <div class="actions-menu">
                  <a href="#" class="actions-item approve-run approve">
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
                  </a>
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
                <img src="./static/langfuse-color.svg" alt="Langfuse" width="16" height="16" />
              </a>
            ` : ''}
            <a href="#" class="action-icon delete-run" title="Delete" onclick="event.stopPropagation()">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
              </svg>
            </a>
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
      const run = runs[idx];

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
        openRun(filePath);
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
          await fetchRuns();
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

      tr.querySelector('.delete-run').addEventListener('click', (e) => {
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

    // #7: Wire "Compare All" buttons on group headers
    tbody.querySelectorAll('.group-compare-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        try {
          const files = JSON.parse(btn.dataset.groupFiles);
          if (Array.isArray(files) && files.length >= 2) {
            sessionStorage.setItem('compareRuns', JSON.stringify(files));
            const params = files.map(f => 'runs=' + encodeURIComponent(f)).join('&');
            window.location.href = './compare?' + params;
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
            <span class="tag model" title="${run.model_name}">${stripModelProvider(run.model_name)}</span>
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
                    <span class="tag model" title="${run.model_name}">${stripModelProvider(run.model_name)}</span>
                    <span style="color:var(--text-muted);font-size:11px;">${run.total_items} items</span>
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
      runEl.addEventListener('click', () => openRun(filePath));
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
      || state.filterVersions.size > 0;

    let filterText = countText;
    if (hasFilters) {
      const parts = [];
      if (state.filterTasks.size > 0 && !state.filterTasks.has('__none__')) {
        parts.push(`task: ${summarizeFilterSelection(state.filterTasks)}`);
      }
      if (state.filterDatasets.size > 0 && !state.filterDatasets.has('__none__')) {
        parts.push(`dataset: ${summarizeFilterSelection(state.filterDatasets)}`);
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
      if (state.quickFilter === 'today') parts.push('today');
      if (state.quickFilter === 'week') parts.push('last 7d');
      filterText = countText + (parts.length > 0 ? ` — ${parts.join(', ')}` : '');
    }

    el('status-filter').textContent = filterText;
    el('status-selected').textContent = `${selected} selected`;
  }

  function renderComparePanel() {
    const panel = el('compare-panel');
    const selected = state.selectedRuns;

    if (selected.size === 0) {
      panel.style.display = 'none';
      return;
    }

    panel.style.display = 'block';
    el('compare-count').textContent = selected.size;

    const chips = el('compare-chips');
    const selectedRuns = state.flatRuns.filter(r => selected.has(r.file_path));

    // Hide Langfuse button - it's available in row actions
    const langfuseBtn = el('langfuse-btn');
    if (langfuseBtn) langfuseBtn.style.display = 'none';

    // Show Submit button only if:
    // 1. User is not a manager (managers approve/reject, not submit)
    // 2. At least 1 run is selected
    // 3. ALL selected runs are submittable (COMPLETED or FAILED status)
    const publishBtn = el('publish-selected');
    if (publishBtn) {
      const role = (state.currentUser && state.currentUser.role) || '';
      const isManager = role === 'MANAGER';
      const allSubmittable = selectedRuns.length > 0 && selectedRuns.every(r => {
        const status = r.status || '';
        return status === 'COMPLETED' || status === 'FAILED';
      });
      publishBtn.style.display = (!isManager && allSubmittable) ? 'inline-block' : 'none';
      publishBtn.textContent = 'Submit';
    }

    chips.innerHTML = selectedRuns.map(run => `
      <span class="compare-chip">
        <span>${run.run_id}</span>
        <span class="remove" data-file="${encodeURIComponent(run.file_path)}">×</span>
      </span>
    `).join('');

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

    if (state.flatRuns.length === 0) {
      empty.style.display = 'flex';
      chartsView.style.display = 'none';
      tableView.style.display = 'none';
      gridView.style.display = 'none';
      timelineView.style.display = 'none';
      if (modelsView) modelsView.style.display = 'none';
      return;
    }

    empty.style.display = 'none';

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
    chartsView.style.display = state.currentView === 'charts' ? 'block' : 'none';
    tableView.style.display = state.currentView === 'table' ? 'block' : 'none';
    gridView.style.display = 'none';  // Hidden - using simplified toggle
    timelineView.style.display = 'none';  // Hidden - using simplified toggle
    if (modelsView) modelsView.style.display = state.currentView === 'models' ? 'block' : 'none';

    // Recompute chart data based on filtered runs
    state.chartData = computeChartData(state.filteredRuns);

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
    let selectedTask = state.filterTasks.size === 1 ? [...state.filterTasks][0] : '';
    let selectedDataset = state.filterDatasets.size === 1 ? [...state.filterDatasets][0] : '';

    if (!selectedTask || !selectedDataset) {
      const uniqueTasks = new Set(state.filteredRuns.map(r => r.task_name));
      const uniqueDatasets = new Set(state.filteredRuns.map(r => r.dataset_name));
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

    // Get runs matching task+dataset (and model filter if active)
    const matchingRuns = state.flatRuns.filter(r => {
      if (!matchesFilterSelection(new Set([selectedTask]), r.task_name)) return false;
      if (!matchesFilterSelection(new Set([selectedDataset]), r.dataset_name)) return false;
      // #14: Apply global model filter to Models View
      if (state.filterModels.size > 0 && !state.filterModels.has('__none__')) {
        if (!matchesFilterSelection(state.filterModels, r.model_name)) return false;
      }
      if (state.filterModels.has('__none__')) return false;
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
      if (!runsByModel[run.model_name]) {
        runsByModel[run.model_name] = [];
      }
      runsByModel[run.model_name].push(run);
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

    // Show loading state
    if (modelsGrid) modelsGrid.innerHTML = '<div class="models-loading"><img src="./static/qym_icon.png" alt="" class="loading-icon" /><span>Loading run data...</span></div>';

    // Fetch item-level data for each model and calculate stats
    mvs.modelStats = {};
    const traceSourceRuns = [];
    for (const model of Object.keys(runsByModel)) {
      const selectedPaths = selectedRunsByModel[model];
      const selectedRuns = runsByModel[model].filter(r => selectedPaths.includes(r.file_path));
      traceSourceRuns.push(...selectedRuns);

      // Fetch detailed data for this model's runs
      const detailedData = await fetchModelRunsData(selectedPaths);

      mvs.modelStats[model] = calculateModelStatsFromItems(detailedData, mvs.selectedMetric, mvs.threshold, mvs.metricIsBoolean);
      mvs.modelStats[model].traceAverages = calculateModelTraceStats(selectedRuns);
      mvs.modelStats[model].totalAvailable = runsByModel[model].length;
      mvs.modelStats[model].selectedCount = selectedRuns.length;
      mvs.modelStats[model].selectedPaths = selectedPaths;
    }
    mvs.visibleTraceMetrics = _traceMetricsForRuns(traceSourceRuns);
    populateModelsStatVisibility(traceSourceRuns);

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
    let currentTask = state.filterTasks.size === 1 ? [...state.filterTasks][0] : '';
    let currentDataset = state.filterDatasets.size === 1 ? [...state.filterDatasets][0] : '';

    if (!currentTask || !currentDataset) {
      const uniqueTasks = new Set(state.filteredRuns.map(r => r.task_name));
      const uniqueDatasets = new Set(state.filteredRuns.map(r => r.dataset_name));
      if (!currentTask && uniqueTasks.size === 1) currentTask = [...uniqueTasks][0];
      if (!currentDataset && uniqueDatasets.size === 1) currentDataset = [...uniqueDatasets][0];
    }

    // Get metrics for selected task+dataset
    const runsForCombo = currentTask && currentDataset
      ? state.flatRuns.filter(r => r.task_name === currentTask && r.dataset_name === currentDataset)
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

  // Cache for fetched run data to avoid re-fetching
  const modelsRunDataCache = {};

  async function fetchModelRunsData(filePaths) {
    if (filePaths.length === 0) return [];

    // Check cache first
    const cacheKey = filePaths.sort().join('|');
    if (modelsRunDataCache[cacheKey]) {
      return modelsRunDataCache[cacheKey];
    }

    try {
      const params = filePaths.map(f => `files=${encodeURIComponent(f)}`).join('&');
      const response = await fetch(apiUrl(`api/compare?${params}`));
      if (!response.ok) throw new Error('Failed to fetch run data');
      const data = await response.json();
      modelsRunDataCache[cacheKey] = data.runs || [];
      return data.runs || [];
    } catch (error) {
      console.error('Error fetching model runs data:', error);
      return [];
    }
  }

  function calculateModelStatsFromItems(runsData, metricName, threshold, isBoolean) {
    // Get run names before delegating to shared function
    const runNames = (runsData || []).map((r, i) => r?.run?.run_name || `Run ${i + 1}`);
    const K = runsData?.length || 0;

    if (!runsData || runsData.length === 0) {
      return {
        passAtK: 0, passHatK: 0, maxAtK: 0, consistency: 0, reliability: 0, avgScore: 0, avgLatency: 0,
        totalItems: 0, failedCount: 0, K: 0, correctDistribution: [0], runNames: [],
        minScore: 0, stddevScore: 0
      };
    }

    const effectiveThreshold = isBoolean ? 0.9999 : threshold;

    // Use shared metrics calculation
    const metrics = window.QymMetrics.calculateItemLevelMetrics({
      runsData,
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
        avgScore: isNumeric
          ? `Mean value across all items and all ${K} runs`
          : `Mean score across all items and all ${K} runs`,
        avgLatency: `Average response time across all runs`,
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
        addStatTile('avgLatency', '⚡ Avg Latency', formatLatency(stats.avgLatency));
      } else {
        addStatTile('passAtK', `Pass@${K}`, formatPercent(stats.passAtK), getSuccessClass(stats.passAtK), tooltips.passAtK);
        addStatTile('passHatK', `Pass^${K}`, formatPercent(stats.passHatK), getSuccessClass(stats.passHatK), tooltips.passHatK);
        addStatTile('maxAtK', `Max@${K}`, formatPercent(stats.maxAtK), getSuccessClass(stats.maxAtK), tooltips.maxAtK);
        addStatTile('consistency', 'Consistency', stats.consistency !== null ? formatPercent(stats.consistency) : 'NA', stats.consistency !== null ? getSuccessClass(stats.consistency) : '', tooltips.consistency);
        addStatTile('reliability', 'Reliability', stats.reliability !== null ? formatPercent(stats.reliability) : 'NA', stats.reliability !== null ? getSuccessClass(stats.reliability) : '', tooltips.reliability);
        addStatTile('avgScore', 'Avg Score', formatPercent(stats.avgScore), getSuccessClass(stats.avgScore), tooltips.avgScore);
        addStatTile('failedCount', 'Errors', String(stats.failedCount), stats.failedCount > 0 ? 'failed-count' : '', tooltips.failedCount);
        addStatTile('avgLatency', '⚡ Avg Latency', formatLatency(stats.avgLatency));
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
            <div class="model-card-title" title="${model}">
              <span class="model-color-dot" style="background: ${color}"></span>
              <span class="model-name">${stripModelProvider(model)}</span>
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
          window.location.href = apiUrl('compare?' + params);
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
              <span class="model-name">${item.model}</span>
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

    modelNameEl.textContent = stripModelProvider(modelName);
    modelNameEl.title = modelName;

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
        const groupLabel = groupRuns[0]?.run_name || `Config ${Object.keys(configGroups).indexOf(groupKey) + 1}`;
        runListHtml += `<div style="padding:6px 8px;font-size:10px;color:var(--accent-primary);font-weight:600;text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid var(--border-default);">${escapeHtml(groupLabel)} (${groupRuns.length} runs)</div>`;
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

        runListHtml += `
          <label class="run-selection-item ${isSelected ? 'selected' : ''}">
            <input type="checkbox" data-file="${run.file_path}" ${isSelected ? 'checked' : ''} />
            <div class="run-info">
              <div class="run-name" title="${run.run_id}">${stripProviderFromRunId(run.run_id)}</div>
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
        ${hasMultipleGroups ? `<span style="font-size:10px;color:var(--text-muted);margin-left:8px;">${Object.keys(configGroups).length} config groups</span>` : ''}
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

  function toggleSelect(filePath) {
    if (state.selectedRuns.has(filePath)) {
      state.selectedRuns.delete(filePath);
    } else {
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
    if (state.selectedRuns.size === state.filteredRuns.length) {
      state.selectedRuns.clear();
    } else {
      state.filteredRuns.forEach(r => state.selectedRuns.add(r.file_path));
    }
    render();
  }

  function clearSelection() {
    state.selectedRuns.clear();
    render();
  }

  function toggleGroupSelection(filePaths) {
    if (!Array.isArray(filePaths) || filePaths.length === 0) return;
    const allSelected = filePaths.every(filePath => state.selectedRuns.has(filePath));
    if (allSelected) {
      filePaths.forEach(filePath => state.selectedRuns.delete(filePath));
    } else {
      filePaths.forEach(filePath => state.selectedRuns.add(filePath));
    }
    render();
  }

  function openRun(filePath) {
    sessionStorage.setItem('dashboardRunFile', filePath);
    window.location.href = `./run/${encodeURIComponent(filePath)}`;
  }

  function openComparison() {
    if (state.selectedRuns.size < 2) {
      showToast('error', 'Cannot Compare', 'Select at least 2 runs to compare');
      return;
    }
    const files = Array.from(state.selectedRuns);
    sessionStorage.setItem('compareRuns', JSON.stringify(files));
    const params = files.map(f => 'runs=' + encodeURIComponent(f)).join('&');
    window.location.href = './compare?' + params;
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
          await fetchRuns();
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
      await fetchRuns();

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
    titleEl.textContent = isApprove ? 'Approve Run' : 'Reject Run';
    descEl.textContent = isApprove
      ? 'Approve this run to make it visible to leadership.'
      : 'Reject this run and send it back for review.';
    runNameEl.textContent = `${taskName} (${runId.substring(0, 8)}...)`;
    commentEl.value = '';
    modal.style.display = 'flex';

    // Update button style
    confirmBtn.className = isApprove ? 'btn btn-primary' : 'btn btn-danger';
    confirmBtn.textContent = isApprove ? 'Approve' : 'Reject';

    // Remove old listener and add new one
    const newConfirmBtn = confirmBtn.cloneNode(true);
    confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);

    newConfirmBtn.addEventListener('click', async () => {
      newConfirmBtn.disabled = true;
      newConfirmBtn.textContent = isApprove ? 'Approving...' : 'Rejecting...';

      try {
        const endpoint = isApprove ? 'approve' : 'reject';
        const response = await fetch(apiUrl(`v1/runs/${encodeURIComponent(runId)}/${endpoint}`), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ comment: commentEl.value || '' }),
        });

        if (response.ok) {
          modal.style.display = 'none';
          await fetchRuns();
        } else {
          const data = await response.json();
          alert(`Failed to ${action}: ` + (data.detail || 'Unknown error'));
        }
      } catch (err) {
        alert(`Failed to ${action}: ` + err.message);
      } finally {
        newConfirmBtn.disabled = false;
        newConfirmBtn.textContent = isApprove ? 'Approve' : 'Reject';
      }
    });

    // Focus the comment field
    setTimeout(() => commentEl.focus(), 100);
  }

  function moveFocus(delta) {
    const newIdx = state.focusedIndex + delta;
    if (newIdx >= 0 && newIdx < state.filteredRuns.length) {
      state.focusedIndex = newIdx;
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

  function _mergePagedRefreshData(previous, incoming) {
    if (!incoming) return previous;
    if (!previous || !previous.tasks) return incoming;

    const merged = _cloneRunsData(previous);
    const incomingRunIds = new Set();

    for (const models of Object.values(incoming.tasks || {})) {
      for (const runList of Object.values(models || {})) {
        for (const run of runList || []) {
          if (run && run.run_id) incomingRunIds.add(run.run_id);
        }
      }
    }

    for (const models of Object.values(merged.tasks || {})) {
      for (const modelName of Object.keys(models || {})) {
        models[modelName] = (models[modelName] || []).filter(run => !incomingRunIds.has(run.run_id));
      }
    }

    _mergeTasksData(merged, incoming);
    merged.last_updated = incoming.last_updated || merged.last_updated;
    merged.total_count = incoming.total_count || merged.total_count;
    return merged;
  }

  function _applyRunsData(data) {
    state.runs = data;
    const { runs, metrics, metricTypes } = flattenRuns(data);
    state.flatRuns = runs;
    state.allMetrics = metrics;
    state._metricTypes = metricTypes;
    loadMetricVisibility();
    updateProfileLink();
    state.aggregations = computeAggregations(state.flatRuns);
    state.chartData = computeChartData(state.flatRuns);
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
    for (let offset = fetched; offset < totalCount; offset += PAGE_SIZE) {
      pagePromises.push(
        fetch(apiUrl(`api/runs?limit=${PAGE_SIZE}&offset=${offset}`))
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

  async function fetchRuns() {
    try {
      // Fetch first page and current user in parallel
      const [runsResponse, meResponse] = await Promise.all([
        fetch(apiUrl(`api/runs?limit=${PAGE_SIZE}&offset=0`)),
        fetch(apiUrl('v1/me')).catch(() => null),
      ]);

      // Handle authentication errors
      if (runsResponse.status === 401 || (meResponse && meResponse.status === 401)) {
        showAuthError();
        return;
      }

      if (!runsResponse.ok) {
        throw new Error(`HTTP ${runsResponse.status}`);
      }

      const data = await runsResponse.json();
      const totalCount = data.total_count || 0;

      try {
        state.currentUser = meResponse && meResponse.ok ? await meResponse.json() : null;
      } catch {
        state.currentUser = null;
      }

      // Render first page immediately, but preserve already-loaded off-page runs during live refreshes.
      const immediateData = totalCount > PAGE_SIZE
        ? _mergePagedRefreshData(state.runs, data)
        : data;
      _applyRunsData(immediateData);

      // Adjust refresh cadence based on whether we have active runs.
      try { updateRunsRefreshCadence && updateRunsRefreshCadence(); } catch {}

      // Fetch remaining pages in the background
      _fetchRemainingPages(data, totalCount);
    } catch (err) {
      console.error('Failed to fetch runs:', err);
      el('loading').innerHTML = `
        <span style="color:var(--error);">Failed to load runs</span>
        <span>Is the server running?</span>
      `;
    }
  }

  function showAuthError() {
    // Hide everything except header logo
    el('loading').style.display = 'none';
    const commandBar = document.querySelector('.command-bar');
    if (commandBar) commandBar.style.display = 'none';
    const comparePanel = el('compare-panel');
    if (comparePanel) comparePanel.style.display = 'none';
    const footer = document.querySelector('.status-bar');
    if (footer) footer.style.display = 'none';
    const statsBar = document.querySelector('.stats-bar .stat-cells');
    if (statsBar) statsBar.style.display = 'none';
    const headerMeta = document.querySelector('.stats-bar .header-meta');
    if (headerMeta) headerMeta.style.display = 'none';

    // Replace main content with login page
    const main = document.querySelector('main');
    main.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: center; height: calc(100vh - 60px);">
        <div style="text-align: center; max-width: 360px; padding: 40px;">
          <img src="./static/qym_icon.png" alt="قيِّم" style="height: 64px; margin-bottom: 24px;" />
          <h1 style="font-size: 24px; font-weight: 600; color: var(--text-primary); margin-bottom: 8px;">قيِّم Platform</h1>
          <p style="color: var(--text-muted); margin-bottom: 32px;">Sign in to access the evaluation dashboard</p>

          <button onclick="location.reload()" style="width: 100%; padding: 12px 24px; background: var(--accent-primary); color: var(--bg-base); border: none; border-radius: 6px; font-size: 14px; font-weight: 500; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px;">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>
            Sign in with SSO
          </button>
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
      roleEl.textContent = u.role || '';
    }

    // Show admin menu item for ADMIN users
    const adminLink = el('header-admin-link');
    if (adminLink) {
      adminLink.style.display = u.role === 'ADMIN' ? '' : 'none';
    }

    // Setup dropdown toggle
    setupHeaderUserDropdown();
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
        runs = runs.filter(r => matchesFilterSelection(state.filterDatasets, r.dataset_name));
      }
      if (skipFilter !== 'models' && state.filterModels.size > 0 && !state.filterModels.has('__none__')) {
        runs = runs.filter(r => matchesFilterSelection(state.filterModels, r.model_name));
      }
      if (skipFilter !== 'statuses' && state.filterStatuses.size > 0 && !state.filterStatuses.has('__none__')) {
        runs = runs.filter(r => matchesFilterSelection(state.filterStatuses, r.status));
      }
      if (skipFilter !== 'versions' && state.filterVersions.size > 0 && !state.filterVersions.has('__none__')) {
        runs = runs.filter(r => matchesFilterSelection(state.filterVersions, r.git_commit));
      }
      return runs;
    }

    const tasks = collectFilterValues(runsExcluding('tasks'), r => r.task_name);
    const datasets = collectFilterValues(runsExcluding('datasets'), r => r.dataset_name);
    const models = collectFilterValues(runsExcluding('models'), r => r.model_name);
    const statusValues = collectFilterValues(runsExcluding('statuses'), r => r.status);
    const versions = collectFilterValues(runsExcluding('versions'), r => r.git_commit);

    state.allModels = [...new Set(state.flatRuns.map(r => r.model_name).filter(m => !isEmptyFilterValue(m)))].sort();

    const branchMap = {};
    state.flatRuns.forEach(r => {
      if (r.git_commit && r.git_branch) branchMap[r.git_commit] = r.git_branch;
    });

    // Task multi-select
    buildMultiSelect({
      btnId: 'filter-task-btn', dropdownId: 'filter-task-dropdown',
      stateSet: state.filterTasks, values: tasks,
      labelFn: null, defaultLabel: 'All Tasks',
      showSearch: true, searchPlaceholder: 'Search tasks...',
      onchange: () => { state.modelsViewState.selectedMetric = ''; state.modelsViewState.modelRunSelections = {}; },
    });

    // Dataset multi-select
    buildMultiSelect({
      btnId: 'filter-dataset-btn', dropdownId: 'filter-dataset-dropdown',
      stateSet: state.filterDatasets, values: datasets,
      labelFn: null, defaultLabel: 'All Datasets',
      showSearch: true, searchPlaceholder: 'Search datasets...',
      onchange: () => { state.modelsViewState.selectedMetric = ''; state.modelsViewState.modelRunSelections = {}; },
    });

    // Model multi-select
    buildMultiSelect({
      btnId: 'filter-model-btn', dropdownId: 'filter-model-dropdown',
      stateSet: state.filterModels, values: models,
      labelFn: (m) => stripModelProvider(m), defaultLabel: 'All Models',
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

    // Version multi-select
    buildMultiSelect({
      btnId: 'filter-version-btn', dropdownId: 'filter-version-dropdown',
      stateSet: state.filterVersions, values: versions,
      labelFn: (v) => {
        if (v === EMPTY_FILTER_VALUE) return 'Empty / Missing';
        const b = branchMap[v];
        return b ? b + '/' + v : v;
      },
      defaultLabel: 'All Versions', showSearch: true, searchPlaceholder: 'Search versions...',
    });
  }

  function startHeartbeat() {
    setInterval(() => {
      fetch(apiUrl('api/heartbeat'), { method: 'POST' }).catch(() => {});
    }, 30000);
  }

  // ═══════════════════════════════════════════════════
  // EVENT LISTENERS
  // ═══════════════════════════════════════════════════

  // Generic multi-select dropdown toggles
  ['filter-task-btn', 'filter-dataset-btn', 'filter-model-btn', 'filter-version-btn', 'filter-status-btn', 'metric-visibility-btn', 'models-stat-visibility-btn'].forEach(id => {
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
  el('select-all').addEventListener('change', selectAll);

  // Compare actions
  el('compare-view')?.addEventListener('click', openComparison);
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
          render();
        }
        break;
      case 'G':
        e.preventDefault();
        state.focusedIndex = state.filteredRuns.length - 1;
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
        if (state.selectedRuns.size >= 2) {
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
  el('help-modal').addEventListener('click', (e) => {
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
    const container = el('toast-container');
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
    const submittableStatuses = ['COMPLETED', 'FAILED'];
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
      await fetchRuns();
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
    const stateToSave = {
      currentView: state.currentView,
      modelsViewState: state.modelsViewState,
      filterTasks: [...state.filterTasks],
      filterModels: [...state.filterModels],
      filterStatuses: [...state.filterStatuses],
      filterVersions: [...state.filterVersions],
      filterDatasets: [...state.filterDatasets],
      quickFilter: state.quickFilter,
      chartFirstColWidth: state.chartFirstColWidth,
    };
    sessionStorage.setItem('dashboardState', JSON.stringify(stateToSave));
  }

  function restoreDashboardState() {
    const saved = sessionStorage.getItem('dashboardState');
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        if (parsed.currentView) {
          state.currentView = parsed.currentView;
          $$('.view-toggle-btn').forEach(b => b.classList.toggle('active', b.dataset.view === state.currentView));
        }
        if (parsed.modelsViewState) {
          const restoredModelsViewState = { ...state.modelsViewState, ...parsed.modelsViewState };
          if (restoredModelsViewState.visibleStatKeys !== null && !Array.isArray(restoredModelsViewState.visibleStatKeys)) {
            restoredModelsViewState.visibleStatKeys = null;
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
      const res = await fetch(apiUrl('v1/me'));
      if (res.status === 401) {
        showAuthError();
        return;
      }
      if (!res.ok) {
        throw new Error('Auth check failed');
      }
      // Authenticated - proceed with dashboard
      restoreDashboardState();
      startHeartbeat();
      fetchRuns();
    } catch (err) {
      console.error('Auth check error:', err);
      showAuthError();
    }
  }

  checkAuthAndInit();

  // Refresh cadence:
  // - If any runs are RUNNING, refresh frequently to show progress.
  // - Otherwise, keep the dashboard light.
  let runsRefreshId = null;
  function updateRunsRefreshCadence() {
    try {
      const anyActive = (state.flatRuns || []).some(r => { const s = String(r.status || '').toUpperCase(); return s === 'RUNNING' || s === 'PENDING'; });
      const intervalMs = anyActive ? 2000 : 60000;
      if (runsRefreshId) clearInterval(runsRefreshId);
      runsRefreshId = setInterval(fetchRuns, intervalMs);
    } catch {
      if (runsRefreshId) clearInterval(runsRefreshId);
      runsRefreshId = setInterval(fetchRuns, 60000);
    }
  }
  updateRunsRefreshCadence();

})();
