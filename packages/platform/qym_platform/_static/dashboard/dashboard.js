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
    searchQuery: '',
    sortKey: 'time-desc',
    quickFilter: 'all',
    filterTask: '',
    filterModels: new Set(),  // Multi-select for models
    filterDataset: '',
    filterPublishStatus: '',  // '' or workflow status (RUNNING/COMPLETED/FAILED/SUBMITTED/APPROVED/REJECTED)
    currentView: 'charts',  // Default to charts view
    selectedRuns: new Set(),
    focusedIndex: -1,
    aggregations: null,
    chartData: null,  // Aggregated data for charts
    allMetrics: [],   // All unique metric names across runs
    allModels: [],    // All unique model names
    currentUser: null,
    // Models view state (uses global filterTask/filterDataset for task+dataset)
    modelsViewState: {
      selectedMetric: '',
      globalK: 5,
      threshold: 0.8,
      metricIsBoolean: false,
      modelRunSelections: {},  // model_name -> [run_file_paths] (custom selection)
      modelStats: {},          // model_name -> computed stats
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

  // ═══════════════════════════════════════════════════
  // UTILITIES
  // ═══════════════════════════════════════════════════

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);
  const el = (id) => document.getElementById(id);

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
    return { runs, metrics: Array.from(metricsSet).sort() };
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
        avg_latency_ms: run.avg_latency_ms,
        total_items: run.total_items,
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

    return {
      combos: sortedCombos,
      models: sortedModels,
      metrics: Array.from(allMetrics),
      modelIndex: Object.fromEntries(sortedModels.map((m, i) => [m, i])),
    };
  }

  function filterRuns() {
    let runs = [...state.flatRuns];

    // Search filter
    if (state.searchQuery) {
      const q = state.searchQuery.toLowerCase();
      runs = runs.filter(r =>
          String(r.run_id || '').toLowerCase().includes(q) ||
          String(r.task_name || '').toLowerCase().includes(q) ||
          String(r.model_name || '').toLowerCase().includes(q) ||
          String(r.display_model || '').toLowerCase().includes(q) ||
          String(r.dataset_name || '').toLowerCase().includes(q)
      );
    }

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
    if (state.filterTask) {
      runs = runs.filter(r => r.task_name === state.filterTask);
    }
    if (state.filterModels.size > 0) {
      if (state.filterModels.has('__none__')) {
        runs = [];
      } else {
        runs = runs.filter(r => state.filterModels.has(r.model_name));
      }
    }
    if (state.filterDataset) {
      runs = runs.filter(r => r.dataset_name === state.filterDataset);
    }
    if (state.filterPublishStatus) {
      runs = runs.filter(r => (r.status || '') === state.filterPublishStatus);
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
        if (state.sortKey.startsWith('metric-')) {
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

  // ═══════════════════════════════════════════════════
  // RENDERING: CHARTS VIEW
  // ═══════════════════════════════════════════════════

  function renderChartsView() {
    const chartData = state.chartData;
    
    // Update subtitle with filter info
    const subtitleEl = $('.charts-subtitle');
    if (subtitleEl) {
      const isFiltered = state.searchQuery || state.quickFilter !== 'all' || state.filterPublishStatus;
      if (isFiltered) {
        subtitleEl.textContent = `Filtered: ${state.filteredRuns.length} runs • Showing average metric scores across all items`;
      } else {
        subtitleEl.textContent = `Showing average metric scores across all items in matching runs`;
      }
    }
    
    if (!chartData || chartData.combos.length === 0) {
      el('charts-grid').innerHTML = `
        <div class="chart-no-data" style="grid-column: 1/-1;">
          ${state.searchQuery || state.quickFilter !== 'all' || state.filterPublishStatus
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

    // Render chart cards - one per task+dataset, showing metrics
    const gridEl = el('charts-grid');
    gridEl.innerHTML = chartData.combos.map(combo => {
      const metrics = combo.metrics || [];
      const modelEntries = Object.entries(combo.models);

      if (metrics.length === 0) {
        return `
          <div class="chart-card">
            <div class="chart-card-header">
              <div class="chart-card-title">
                <span class="chart-task-name">${combo.task}</span>
                <span class="chart-dataset-name">${combo.dataset}</span>
              </div>
              <div class="chart-card-meta">
                <span class="runs-count">${combo.totalRuns} runs</span>
              </div>
            </div>
            <div class="chart-no-data">No metrics recorded</div>
          </div>
        `;
      }

      // Build table with runs as rows and metrics as columns
      // First, collect all unique runs across all models
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
            latency: run.avg_latency_ms || 0,
            isMultiRun: data.runs > 1,
          });
        }
      }

      // Generate unique card ID for sorting state
      const cardId = `${combo.task}|||${combo.dataset}`.replace(/[^a-zA-Z0-9]/g, '_');

      // Default sort by first metric descending
      if (!state.chartSortState) state.chartSortState = {};
      if (!state.chartSortState[cardId]) {
        state.chartSortState[cardId] = { key: metrics[0] || 'latency', dir: 'desc' };
      }
      const sortState = state.chartSortState[cardId];

      // Sort runs
      allRuns.sort((a, b) => {
        let aVal, bVal;
        if (sortState.key === 'latency') {
          aVal = a.latency || 0;
          bVal = b.latency || 0;
        } else {
          aVal = a.metric_averages[sortState.key] ?? -1;
          bVal = b.metric_averages[sortState.key] ?? -1;
        }
        return sortState.dir === 'desc' ? bVal - aVal : aVal - bVal;
      });

      if (allRuns.length === 0) return '';

      // Build header row with sortable columns
      const headerCells = metrics.map(metric => {
        const isActive = sortState.key === metric;
        const arrow = isActive ? (sortState.dir === 'desc' ? ' ↓' : ' ↑') : '';
        return `<span class="chart-col-header sortable-col ${isActive ? 'active' : ''}" data-card="${cardId}" data-sort="${metric}">${metric}${arrow}</span>`;
      }).join('');

      const latencyActive = sortState.key === 'latency';
      const latencyArrow = latencyActive ? (sortState.dir === 'desc' ? ' ↓' : ' ↑') : '';

      // Build data rows
      const rowsHtml = allRuns.map((runData) => {
        const { model, run_id, external_run_id, file_path, timestamp, metric_averages, latency, isMultiRun } = runData;
        const modelIdx = state.allModels.indexOf(model) % CHART_COLORS.length;
        const latencyStr = latency > 0 ? formatLatency(latency) : '—';
        const dt = formatDate(timestamp);

        // Format run label: show model name + run name + date (#13)
        const displayModel = stripModelProvider(model);
        const runNameLabel = runData.run_name ? ` (${runData.run_name})` : '';
        let displayHtml = `<span class="model-name-text" title="${model}">${displayModel}</span>`;
        // Try to extract date from run_id pattern
        const tsMatch = run_id.match(/-(\d{2})(\d{2})(\d{2})-(\d{2})(\d{2})(?:-(\d+))?$/);
        if (tsMatch) {
          const [, yy, mm, dd, hh, min, counter] = tsMatch;
          const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
          const monthName = months[parseInt(mm, 10) - 1] || mm;
          const day = parseInt(dd, 10);
          const timeStr = `${hh}:${min}`;
          const counterStr = counter ? ` #${counter}` : '';
          displayHtml = `<span class="model-name-text" title="${model}${runNameLabel}">${displayModel}${runNameLabel}</span><span class="run-timestamp">${monthName} ${day} · ${timeStr}${counterStr}</span>`;
        } else {
          // Fallback: use formatted timestamp from run data
          displayHtml = `<span class="model-name-text" title="${model}${runNameLabel}">${displayModel}${runNameLabel}</span><span class="run-timestamp">${dt.date} · ${dt.time}</span>`;
        }
        const tooltipText = `${run_id}\n${dt.full}\nClick to view details`;

        // Build metric cells
        const metricCells = metrics.map(metric => {
          const score = metric_averages[metric];
          if (score === undefined || score === null) {
            return `<div class="chart-metric-cell"><span class="metric-na">—</span></div>`;
          }
          const pct = score * 100;
          const barWidth = Math.max(pct, 2);
          const pctStr = pct === 0 ? '0%' : pct === 100 ? '100%' : `${pct.toFixed(1)}%`;
          return `
            <div class="chart-metric-cell">
              <div class="chart-mini-bar-track">
                <div class="chart-mini-bar-fill" data-model-idx="${modelIdx}" style="width:${barWidth}%">
                  <span class="chart-mini-bar-pct">${pctStr}</span>
                </div>
              </div>
            </div>
          `;
        }).join('');

        return `
          <div class="chart-table-row">
            <span class="chart-bar-label clickable-run ${isMultiRun ? 'multi-run' : ''}"
                  data-file="${file_path}"
                  title="${tooltipText}">${displayHtml}</span>
            ${metricCells}
            <span class="chart-latency-cell">${latencyStr}</span>
          </div>
        `;
      }).join('');

      const metricChartsHtml = `
        <div class="chart-table" data-card-id="${cardId}">
          <div class="chart-table-header">
            <span class="chart-col-header-run">Model</span>
            ${headerCells}
            <span class="chart-col-header-latency sortable-col ${latencyActive ? 'active' : ''}" data-card="${cardId}" data-sort="latency">Latency${latencyArrow}</span>
          </div>
          <div class="chart-table-body">
            ${rowsHtml}
          </div>
        </div>
      `;

      return `
        <div class="chart-card">
          <div class="chart-card-header">
            <div class="chart-card-title">
              <span class="chart-task-name">${combo.task}</span>
              <span class="chart-dataset-name">${combo.dataset}</span>
            </div>
            <div class="chart-card-meta">
              <span class="runs-count">${combo.totalRuns} runs</span>
              <span>${modelEntries.length} models • ${metrics.length} metrics</span>
            </div>
          </div>
          ${metricChartsHtml}
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
        const cardId = e.target.dataset.card;
        const sortKey = e.target.dataset.sort;
        if (!cardId || !sortKey) return;

        const currentSort = state.chartSortState[cardId] || { key: sortKey, dir: 'desc' };
        if (currentSort.key === sortKey) {
          // Toggle direction
          currentSort.dir = currentSort.dir === 'desc' ? 'asc' : 'desc';
        } else {
          // New column, default to desc
          currentSort.key = sortKey;
          currentSort.dir = 'desc';
        }
        state.chartSortState[cardId] = currentSort;
        renderChartsView();
      });
    });
  }

  // ═══════════════════════════════════════════════════
  // RENDERING: TABLE VIEW
  // ═══════════════════════════════════════════════════

  function updateTableHeader() {
    // Update the table header to include dynamic metric columns
    const headerRow = el('table-header-row');
    if (!headerRow) return;

    // Find the LATENCY column (insert metric columns before it)
    const latencyHeader = headerRow.querySelector('.col-latency');
    if (!latencyHeader) return;

    // Remove any existing dynamic metric columns
    headerRow.querySelectorAll('.col-metric-dynamic').forEach(col => col.remove());

    // Insert metric columns before LATENCY column (limit to 4 metrics)
    const metricsToShow = state.allMetrics.slice(0, 4);
    metricsToShow.forEach(metric => {
      const th = document.createElement('th');
      th.className = 'col-metric-dynamic sortable';
      th.dataset.sort = `metric-${metric}`;
      th.textContent = metric.toUpperCase();
      th.title = `Sort by ${metric}`;
      headerRow.insertBefore(th, latencyHeader);
    });

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
      const isNumeric = numericFields.includes(sortField) || sortField.startsWith('metric-');
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
    const metricsToShow = state.allMetrics.slice(0, 4);

    // Update header with dynamic metric columns
    updateTableHeader();

    if (runs.length === 0) {
      const colCount = 11 + metricsToShow.length;
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
    // 11 base columns + dynamic metric columns
    const colCount = 11 + metricsToShow.length;
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
        const configRunName = (run.run_config || {}).run_name || '';
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

        groupHeaderHtml = `<tr class="run-group-header" data-group-key="${escapeHtml(groupKey)}" data-group-id="${groupId}">
          <td colspan="${colCount}" style="padding:6px 12px;background:var(--bg-elevated);cursor:pointer;user-select:none;">
            <span class="group-toggle-arrow" style="font-size:var(--font-xs);color:var(--accent-primary);font-weight:600;margin-right:4px;">${arrow}</span>
            <span style="font-size:var(--font-xs);color:var(--accent-primary);font-weight:600;">${escapeHtml(baseLabel)}</span>
            <span style="font-size:var(--font-xs);color:var(--text-muted);margin-left:4px;">${tsLabel}</span>
            <span style="font-size:var(--font-xs);color:var(--text-muted);margin-left:8px;">${groupSize} runs</span>
            <button class="group-compare-btn action-btn" data-group-files='${JSON.stringify(memberFilePaths)}' onclick="event.stopPropagation();" style="margin-left:12px;">Compare</button>
          </td>
        </tr>`;
      }
      lastGroupKey = groupKey;

      // If this run belongs to a collapsed group, hide it (header row stays visible)
      const isCollapsed = isGrouped && state._collapsedGroups[groupKey] === true;
      const hiddenAttr = (isGrouped && isCollapsed) ? 'style="display:none;"' : '';
      const groupDataAttr = isGrouped ? `data-member-of="${escapeHtml(groupKey)}"` : '';
      const dt = formatDate(run.timestamp);
      const completedRate = run.completion_rate ?? 0;
      const successRate = run.success_on_completed_rate;
      const successClass = getSuccessClass(successRate ?? 0);
      const successText = successRate === null ? '\u2014' : formatPercent(successRate);
      const isSelected = state.selectedRuns.has(run.file_path);
      const isFocused = idx === state.focusedIndex;

      // Generate metric columns
      const metricCells = metricsToShow.map(metric => {
        const value = run.metric_averages?.[metric];
        if (value === undefined || value === null) {
          return `<td class="col-metric-value"><span class="metric-na">—</span></td>`;
        }
        const pct = (value * 100).toFixed(1);
        const metricClass = getSuccessClass(value);
        return `<td class="col-metric-value"><span class="metric-score ${metricClass}">${pct}%</span></td>`;
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
            ${status ? `<span class="status-badge status-${status}" title="${escapeHtml(statusTooltip)}">${status}${progressPctText ? ` • ${progressPctText}` : ''}${progressText ? ` • ${progressText}` : ''}</span>` : ''}
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
          <td class="col-owner">
            ${run.owner ? `
              <span class="owner-name" title="${run.owner.email}">
                <span class="owner-avatar">${getInitials(run.owner.display_name)}</span>
                ${truncateText(run.owner.display_name, 15)}
              </span>
            ` : '<span style="color:var(--text-muted)">—</span>'}
          </td>
          <td class="col-success">
            <span class="success-rate ${successClass}">${successText}</span>
          </td>
          ${metricCells}
          <td class="col-latency">
            <span class="latency-value">${run.avg_latency_ms ? formatLatency(run.avg_latency_ms) : '—'}</span>
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
            window.location.href = './compare';
          }
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

    const hasFilters = state.searchQuery
      || state.quickFilter !== 'all'
      || state.filterTask
      || (state.filterModels.size > 0)
      || state.filterDataset
      || state.filterPublishStatus;

    let filterText = 'Showing all runs';
    if (hasFilters) {
      const parts = [];
      if (state.filterTask) parts.push(`task: ${state.filterTask}`);
      if (state.filterDataset) parts.push(`dataset: ${state.filterDataset}`);
      if (state.filterModels.size > 0 && !state.filterModels.has('__none__')) {
        const names = [...state.filterModels].map(m => m.length > 20 ? m.slice(0, 20) + '…' : m);
        parts.push(`model: ${names.join(', ')}`);
      } else if (state.filterModels.has('__none__')) {
        parts.push('model: none');
      }
      if (state.filterPublishStatus) parts.push(`status: ${state.filterPublishStatus}`);
      if (state.quickFilter === 'today') parts.push('today');
      if (state.quickFilter === 'week') parts.push('last 7d');
      if (state.searchQuery) parts.push(`"${state.searchQuery}"`);
      filterText = `Showing ${filtered} of ${total} runs` + (parts.length > 0 ? ` — ${parts.join(', ')}` : '');
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
  }

  // ═══════════════════════════════════════════════════
  // RENDERING: MODELS VIEW
  // ═══════════════════════════════════════════════════

  async function renderModelsView() {
    const modelsEmpty = el('models-empty');
    const modelsGrid = el('models-grid');
    const modelsRanking = el('models-ranking');

    // Populate dropdowns if not already populated
    populateModelsViewDropdowns();

    const mvs = state.modelsViewState;

    // Use global filters for task and dataset
    const selectedTask = state.filterTask;
    const selectedDataset = state.filterDataset;

    // If no task+dataset selected, show empty state
    if (!selectedTask || !selectedDataset) {
      if (modelsEmpty) modelsEmpty.style.display = 'flex';
      if (modelsGrid) modelsGrid.innerHTML = '';
      if (modelsRanking) modelsRanking.style.display = 'none';
      return;
    }

    if (modelsEmpty) modelsEmpty.style.display = 'none';

    // Get runs matching task+dataset (and model filter if active)
    const matchingRuns = state.flatRuns.filter(r => {
      if (r.task_name !== selectedTask || r.dataset_name !== selectedDataset) return false;
      // #14: Apply global model filter to Models View
      if (state.filterModels.size > 0 && !state.filterModels.has('__none__')) {
        if (!state.filterModels.has(r.model_name)) return false;
      }
      if (state.filterModels.has('__none__')) return false;
      return true;
    });

    if (matchingRuns.length === 0) {
      if (modelsGrid) modelsGrid.innerHTML = '<div class="models-empty"><h3>No runs found</h3><p>No runs match the selected task and dataset</p></div>';
      if (modelsRanking) modelsRanking.style.display = 'none';
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

    // Show loading state
    if (modelsGrid) modelsGrid.innerHTML = '<div class="models-loading"><img src="./static/qym_icon.png" alt="" class="loading-icon" /><span>Loading run data...</span></div>';

    // Fetch item-level data for each model and calculate stats
    mvs.modelStats = {};
    for (const model of Object.keys(runsByModel)) {
      const selectedPaths = selectedRunsByModel[model];
      const selectedRuns = runsByModel[model].filter(r => selectedPaths.includes(r.file_path));

      // Fetch detailed data for this model's runs
      const detailedData = await fetchModelRunsData(selectedPaths);

      mvs.modelStats[model] = calculateModelStatsFromItems(detailedData, mvs.selectedMetric, mvs.threshold, mvs.metricIsBoolean);
      mvs.modelStats[model].totalAvailable = runsByModel[model].length;
      mvs.modelStats[model].selectedCount = selectedRuns.length;
      mvs.modelStats[model].selectedPaths = selectedPaths;
    }

    // Render model cards
    renderModelCards(runsByModel, globalK);

    // Render ranking bar
    renderModelsRanking();
  }

  function populateModelsViewDropdowns() {
    const metricSelect = el('models-metric-select');
    const kInput = el('models-k-input');

    if (!metricSelect) return;

    // Use global filters for task and dataset
    const currentTask = state.filterTask;
    const currentDataset = state.filterDataset;

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
        totalItems: 0, failedCount: 0, K: 0, correctDistribution: [0], runNames: []
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
      K: metrics.K,
      correctDistribution: metrics.correctDistribution || new Array(K + 1).fill(0),
      runNames
    };
  }

  function detectModelsViewMetricType(runs, metricName) {
    if (!metricName) {
      state.modelsViewState.metricIsBoolean = true;
      return;
    }

    let allBoolean = true;
    for (const run of runs) {
      const metricAvg = run.metric_averages?.[metricName];
      if (metricAvg !== undefined && metricAvg !== null) {
        const val = parseFloat(metricAvg);
        if (!isNaN(val) && Math.abs(val) > 0.0001 && Math.abs(val - 1) > 0.0001) {
          allBoolean = false;
          break;
        }
      }
    }
    state.modelsViewState.metricIsBoolean = allBoolean;

    // Show/hide threshold control (inline)
    const thresholdRow = el('models-threshold-row');
    if (thresholdRow) {
      thresholdRow.style.display = allBoolean ? 'none' : 'inline-flex';
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
    const threshold = Math.round(mvs.threshold * 100);

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
        maxAtK: `Average of the best score per item across all ${K} runs`,
        consistency: `How often runs agree on pass/fail across ${K} runs. 100% = all agree, 0% = 50/50 split.`,
        reliability: `When an item CAN be solved, how often is it? Only includes items with ≥1 passing run.`,
        failedCount: `Number of runs that threw an error (across all items). Errors are scored as 0%.`,
        avgScore: `Mean score across all items and all ${K} runs`,
        avgLatency: `Average response time across all runs`,
        correctDist: isBoolean
          ? `How many runs got each item correct (100%). "0" = no run solved it, "${K}" = all runs solved it.`
          : `How many runs scored ≥${threshold}% for each item.`
      };

      const distBar = buildModelDistributionBar(stats);

      // Helper to create info icon with tooltip (same as compare view)
      function infoIcon(tooltip) {
        return `<span class="stat-info-icon">i<span class="stat-info-tooltip">${tooltip}</span></span>`;
      }

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

          <div class="model-stats-row">
            <div class="model-stat-box">
              <div class="stat-title">Pass@${K} ${infoIcon(tooltips.passAtK)}</div>
              <div class="stat-main ${getSuccessClass(stats.passAtK)}">${formatPercent(stats.passAtK)}</div>
            </div>
            <div class="model-stat-box">
              <div class="stat-title">Pass^${K} ${infoIcon(tooltips.passHatK)}</div>
              <div class="stat-main ${getSuccessClass(stats.passHatK)}">${formatPercent(stats.passHatK)}</div>
            </div>
            <div class="model-stat-box">
              <div class="stat-title">Max@${K} ${infoIcon(tooltips.maxAtK)}</div>
              <div class="stat-main ${getSuccessClass(stats.maxAtK)}">${formatPercent(stats.maxAtK)}</div>
            </div>
          </div>

          <div class="model-stats-row">
            <div class="model-stat-box">
              <div class="stat-title">Consistency ${infoIcon(tooltips.consistency)}</div>
              <div class="stat-main ${stats.consistency !== null ? getSuccessClass(stats.consistency) : ''}">${stats.consistency !== null ? formatPercent(stats.consistency) : 'NA'}</div>
            </div>
            <div class="model-stat-box">
              <div class="stat-title">Reliability ${infoIcon(tooltips.reliability)}</div>
              <div class="stat-main ${stats.reliability !== null ? getSuccessClass(stats.reliability) : ''}">${stats.reliability !== null ? formatPercent(stats.reliability) : 'NA'}</div>
            </div>
            <div class="model-stat-box">
              <div class="stat-title">Avg Score ${infoIcon(tooltips.avgScore)}</div>
              <div class="stat-main ${getSuccessClass(stats.avgScore)}">${formatPercent(stats.avgScore)}</div>
            </div>
            <div class="model-stat-box">
              <div class="stat-title">Latency ${infoIcon(tooltips.avgLatency)}</div>
              <div class="stat-main">${formatLatency(stats.avgLatency)}</div>
            </div>
            <div class="model-stat-box">
              <div class="stat-title">Errors ${infoIcon(tooltips.failedCount)}</div>
              <div class="stat-main ${stats.failedCount > 0 ? 'failed-count' : ''}">${stats.failedCount}</div>
            </div>
          </div>

          <div class="model-stat-box-wide">
            <div class="stat-title">Correct Distribution ${infoIcon(tooltips.correctDist)}</div>
            <div class="distribution-bar">${distBar}</div>
            <div class="distribution-legend">
              <span class="dist-legend-item"><span style="color:var(--error)">■</span> 0 runs</span>
              <span class="dist-legend-item"><span style="color:var(--warning)">■</span> 1-${K-1} runs</span>
              <span class="dist-legend-item"><span style="color:var(--success)">■</span> ${K} runs</span>
            </div>
          </div>

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
          // Open compare view with selected runs
          sessionStorage.setItem('compareRuns', JSON.stringify(stats.selectedPaths));
          window.location.href = apiUrl('compare');
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

    container.style.display = 'block';
    container.innerHTML = `
      <h3>Ranking (by Avg Score)</h3>
      <div class="ranking-list">
        ${ranked.map((item, idx) => {
          const rank = idx < 3 ? rankEmojis[idx] : `#${idx + 1}`;
          const scoreClass = getSuccessClass(item.score);
          return `
            <div class="ranking-item">
              <span class="rank">${rank}</span>
              <span class="model-name">${item.model}</span>
              <span class="score ${scoreClass}">(${formatPercent(item.score)})</span>
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
        const scoreClass = score !== undefined ? getSuccessClass(score) : '';

        runListHtml += `
          <label class="run-selection-item ${isSelected ? 'selected' : ''}">
            <input type="checkbox" data-file="${run.file_path}" ${isSelected ? 'checked' : ''} />
            <div class="run-info">
              <div class="run-name" title="${run.run_id}">${stripProviderFromRunId(run.run_id)}</div>
              <div class="run-date">${dt.full}</div>
            </div>
            ${score !== undefined ? `<span class="run-score ${scoreClass}">${formatPercent(score)}</span>` : ''}
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
      // If none left, that means nothing would show - revert to show all
      if (state.filterModels.size === 0) {
        // Empty means show all, which is fine
      }
    } else {
      // This model is not in whitelist - add it (show it)
      state.filterModels.add(model);
      // If all models are now selected, clear to "show all" state
      if (state.filterModels.size === state.allModels.length) {
        state.filterModels.clear();
      }
    }
    updateModelFilterButton();
    populateFilterDropdowns(); // Keep dropdown in sync
    render();
  }

  function selectOnlyModel(model) {
    state.filterModels.clear();
    state.filterModels.add(model);
    updateModelFilterButton();
    populateFilterDropdowns(); // Keep dropdown in sync
    render();
  }

  function updateModelFilterButton() {
    const btn = el('filter-model-btn');
    if (!btn) return;

    if (state.filterModels.size === 0) {
      btn.textContent = 'All Models';
    } else if (state.filterModels.has('__none__')) {
      btn.textContent = 'No Models';
    } else if (state.filterModels.size === 1) {
      btn.textContent = [...state.filterModels][0];
    } else {
      btn.textContent = `${state.filterModels.size} Models`;
    }
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

  function openRun(filePath) {
    sessionStorage.setItem('dashboardRunFile', filePath);
    window.location.href = `./run/${encodeURIComponent(filePath)}`;
  }

  function openComparison() {
    if (state.selectedRuns.size < 2) {
      showToast('error', 'Cannot Compare', 'Select at least 2 runs to compare');
      return;
    }
    // Store selected runs for comparison page
    const files = Array.from(state.selectedRuns);
    sessionStorage.setItem('compareRuns', JSON.stringify(files));
    window.location.href = './compare';
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

  async function fetchRuns() {
    try {
      // Fetch runs and current user in parallel (platform)
      const [runsResponse, meResponse] = await Promise.all([
        fetch(apiUrl('api/runs')),
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
      state.runs = data;
      const { runs, metrics } = flattenRuns(data);
      state.flatRuns = runs;
      state.allMetrics = metrics;
      try {
        state.currentUser = meResponse && meResponse.ok ? await meResponse.json() : null;
      } catch {
        state.currentUser = null;
      }
      updateProfileLink();
      state.aggregations = computeAggregations(state.flatRuns);
      state.chartData = computeChartData(state.flatRuns);

      // Populate filter dropdowns
      populateFilterDropdowns();

      el('last-updated').textContent = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

      render();
      // Adjust refresh cadence based on whether we have active runs.
      try { updateRunsRefreshCadence && updateRunsRefreshCadence(); } catch {}
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
    const tasks = [...new Set(state.flatRuns.map(r => r.task_name))].sort();
    const models = [...new Set(state.flatRuns.map(r => r.model_name))].sort();
    const datasets = [...new Set(state.flatRuns.map(r => r.dataset_name))].sort();

    state.allModels = models;

    const taskSelect = el('filter-task');
    const datasetSelect = el('filter-dataset');

    if (taskSelect) {
      taskSelect.innerHTML = '<option value="">All Tasks</option>' +
        tasks.map(t => `<option value="${t}">${t}</option>`).join('');
    }
    if (datasetSelect) {
      datasetSelect.innerHTML = '<option value="">All Datasets</option>' +
        datasets.map(d => `<option value="${d}">${d}</option>`).join('');
    }

    // Populate model multi-select dropdown
    const modelDropdown = el('filter-model-dropdown');
    if (modelDropdown) {
      const isShowingAll = state.filterModels.size === 0;
      const isShowingNone = state.filterModels.has('__none__');
      const searchValue = modelDropdown.querySelector('.model-search-input')?.value || '';

      modelDropdown.innerHTML = `
        <div class="model-search-box">
          <input type="text" class="model-search-input" placeholder="Search models..." value="${searchValue}" />
        </div>
        <div class="multi-select-option" data-value="">
          <span class="model-color" style="background:transparent"></span>
          <input type="checkbox" ${isShowingAll ? 'checked' : ''} />
          <span>All Models</span>
        </div>
        ${models.map((m, idx) => `
          <div class="multi-select-option" data-value="${m}" title="${m}" style="${searchValue && !m.toLowerCase().includes(searchValue.toLowerCase()) ? 'display:none' : ''}">
            <span class="model-color" style="background:${CHART_COLORS[idx % CHART_COLORS.length]}"></span>
            <input type="checkbox" ${isShowingNone ? '' : (isShowingAll || state.filterModels.has(m) ? 'checked' : '')} />
            <span>${stripModelProvider(m)}</span>
          </div>
        `).join('')}
      `;

      // Wire search input
      const searchInput = modelDropdown.querySelector('.model-search-input');
      if (searchInput) {
        searchInput.addEventListener('input', (e) => {
          const query = e.target.value.toLowerCase();
          modelDropdown.querySelectorAll('.multi-select-option[data-value]').forEach(opt => {
            const value = opt.dataset.value;
            if (value === '') return; // Skip "All Models"
            opt.style.display = value.toLowerCase().includes(query) ? '' : 'none';
          });
        });
        searchInput.addEventListener('click', (e) => e.stopPropagation());
        searchInput.addEventListener('keydown', (e) => e.stopPropagation());
      }

      // Wire dropdown events
      modelDropdown.querySelectorAll('.multi-select-option').forEach(opt => {
        opt.addEventListener('click', (e) => {
          e.stopPropagation();
          const value = opt.dataset.value;
          if (value === '') {
            // "All Models" clicked - toggle between all and none
            if (state.filterModels.size === 0) {
              // Already showing all - select none (add a dummy to make filter non-empty but match nothing)
              state.filterModels.add('__none__');
            } else if (state.filterModels.has('__none__')) {
              // Currently showing none - show all
              state.filterModels.clear();
            } else {
              // Some are filtered, clear to show all
              state.filterModels.clear();
            }
          } else {
            // Individual model clicked - simple toggle
            const wasShowingNone = state.filterModels.has('__none__');
            // Clear the __none__ sentinel if present
            state.filterModels.delete('__none__');

            if (wasShowingNone) {
              // Was showing none, now select just this one model
              state.filterModels.add(value);
            } else if (state.filterModels.has(value)) {
              // This model is selected - deselect it
              state.filterModels.delete(value);
              // If none left after removing, show all
              if (state.filterModels.size === 0) {
                // Empty = show all, which is fine
              }
            } else {
              // If currently showing all (size === 0), we need to select all EXCEPT this one
              // to effectively "deselect" this model
              if (state.filterModels.size === 0) {
                // Add all models except the clicked one
                models.forEach(m => {
                  if (m !== value) state.filterModels.add(m);
                });
              } else {
                // Normal case: add this model to selection
                state.filterModels.add(value);
              }
            }
            // If all models are now selected, clear to "show all" state
            if (state.filterModels.size === models.length) {
              state.filterModels.clear();
            }
          }
          updateModelFilterButton();
          populateFilterDropdowns(); // Refresh checkboxes
          render();
        });
      });
    }
  }

  function startHeartbeat() {
    setInterval(() => {
      fetch(apiUrl('api/heartbeat'), { method: 'POST' }).catch(() => {});
    }, 30000);
  }

  // ═══════════════════════════════════════════════════
  // EVENT LISTENERS
  // ═══════════════════════════════════════════════════

  // Search
  el('search').addEventListener('input', debounce((e) => {
    state.searchQuery = e.target.value;
    state.focusedIndex = -1;
    render();
  }, 150));

  // Filter dropdowns
  el('filter-task')?.addEventListener('change', (e) => {
    state.filterTask = e.target.value;
    state.focusedIndex = -1;
    // Reset Models view state when task changes
    state.modelsViewState.selectedMetric = '';
    state.modelsViewState.modelRunSelections = {};
    render();
  });

  // Model multi-select dropdown toggle
  el('filter-model-btn')?.addEventListener('click', (e) => {
    e.stopPropagation();
    const dropdown = el('filter-model-dropdown');
    dropdown.classList.toggle('open');
  });

  // Close dropdown when clicking outside
  document.addEventListener('click', (e) => {
    const wrapper = el('model-filter-wrapper');
    const dropdown = el('filter-model-dropdown');
    if (wrapper && dropdown && !wrapper.contains(e.target)) {
      dropdown.classList.remove('open');
    }
  });

  // Close actions dropdowns when clicking outside
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.actions-dropdown')) {
      document.querySelectorAll('.actions-dropdown.open').forEach(d => {
        d.classList.remove('open');
      });
    }
  });

  el('filter-dataset')?.addEventListener('change', (e) => {
    state.filterDataset = e.target.value;
    state.focusedIndex = -1;
    // Reset Models view state when dataset changes
    state.modelsViewState.selectedMetric = '';
    state.modelsViewState.modelRunSelections = {};
    render();
  });

  el('filter-publish-status')?.addEventListener('change', (e) => {
    state.filterPublishStatus = e.target.value;
    state.focusedIndex = -1;
    render();
  });

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
      case '/':
        e.preventDefault();
        el('search').focus();
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
      filterTask: state.filterTask,
      filterDataset: state.filterDataset,
      quickFilter: state.quickFilter,
      searchQuery: state.searchQuery,
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
          state.modelsViewState = { ...state.modelsViewState, ...parsed.modelsViewState };
        }
        if (parsed.filterTask) state.filterTask = parsed.filterTask;
        if (parsed.filterDataset) state.filterDataset = parsed.filterDataset;
        if (parsed.quickFilter) {
          state.quickFilter = parsed.quickFilter;
          $$('.filter-btn').forEach(b => b.classList.toggle('active', b.dataset.filter === state.quickFilter));
        }
        if (parsed.searchQuery) {
          state.searchQuery = parsed.searchQuery;
          el('search').value = state.searchQuery;
        }
      } catch (e) {
        console.warn('Failed to restore dashboard state:', e);
      }
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
      const anyRunning = (state.flatRuns || []).some(r => String(r.status || '').toUpperCase() === 'RUNNING');
      const intervalMs = anyRunning ? 2000 : 60000;
      if (runsRefreshId) clearInterval(runsRefreshId);
      runsRefreshId = setInterval(fetchRuns, intervalMs);
    } catch {
      if (runsRefreshId) clearInterval(runsRefreshId);
      runsRefreshId = setInterval(fetchRuns, 60000);
    }
  }
  updateRunsRefreshCadence();

})();
