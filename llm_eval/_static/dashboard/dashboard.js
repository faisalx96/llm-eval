/**
 * LLM-Eval Analytics Dashboard
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
    filterPublishStatus: '',  // '' or workflow status (DRAFT/SUBMITTED/APPROVED/REJECTED/RUNNING/COMPLETED/FAILED)
    currentView: 'charts',  // Default to charts view
    selectedRuns: new Set(),
    focusedIndex: -1,
    aggregations: null,
    chartData: null,  // Aggregated data for charts
    allMetrics: [],   // All unique metric names across runs
    allModels: [],    // All unique model names
    // Confluence support removed.
    publishedRuns: new Set(),
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
    return `${(rate * 100).toFixed(1)}%`;
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
      runs = runs.filter(r => state.filterModels.has(r.model_name));
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
        runs.sort((a, b) => b.success_rate - a.success_rate);
        break;
      case 'success-asc':
        runs.sort((a, b) => a.success_rate - b.success_rate);
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
        const { model, run_id, file_path, timestamp, metric_averages, latency, isMultiRun } = runData;
        const modelIdx = state.allModels.indexOf(model) % CHART_COLORS.length;
        const latencyStr = latency > 0 ? formatLatency(latency) : '—';
        const dt = formatDate(timestamp);

        // Format run label
        const displayModel = stripModelProvider(model);
        let displayHtml = `<span class="model-name-text" title="${model}">${displayModel}</span>`;
        if (isMultiRun) {
          const tsMatch = run_id.match(/-(\d{2})(\d{2})(\d{2})-(\d{2})(\d{2})(?:-(\d+))?$/);
          if (tsMatch) {
            const [, yy, mm, dd, hh, min, counter] = tsMatch;
            const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
            const monthName = months[parseInt(mm, 10) - 1] || mm;
            const day = parseInt(dd, 10);
            const timeStr = `${hh}:${min}`;
            const counterStr = counter ? ` #${counter}` : '';
            displayHtml = `<span class="model-name-text" title="${model}">${displayModel}</span><span class="run-timestamp">${monthName} ${day} · ${timeStr}${counterStr}</span>`;
          }
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
          return `
            <div class="chart-metric-cell">
              <div class="chart-mini-bar-track">
                <div class="chart-mini-bar-fill" data-model-idx="${modelIdx}" style="width:${barWidth}%">
                  <span class="chart-mini-bar-pct">${pct.toFixed(1)}%</span>
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
            <span class="chart-col-header-run">Run</span>
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

  function renderTableView() {
    const runs = state.filteredRuns;
    const tbody = el('runs-tbody');
    const metricsToShow = state.allMetrics.slice(0, 4);

    // Update header with dynamic metric columns
    updateTableHeader();

    if (runs.length === 0) {
      const colCount = 9 + metricsToShow.length; // base columns + metrics
      tbody.innerHTML = `
        <tr>
          <td colspan="${colCount}" style="text-align:center;padding:2rem;color:var(--text-muted);">
            No runs match current filters
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = runs.map((run, idx) => {
      const dt = formatDate(run.timestamp);
      const successClass = getSuccessClass(run.success_rate);
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

      const role = (state.currentUser && state.currentUser.role) || '';
      const canApprove = role === 'MANAGER' && status === 'SUBMITTED';
      // Runs submitted via SDK/file upload land as COMPLETED/FAILED; those should be submittable for approval.
      const canSubmit = (status === 'DRAFT' || status === 'COMPLETED' || status === 'FAILED');
      const progressText = (status === 'RUNNING' && run.progress_total)
        ? `${run.progress_completed || 0}/${run.progress_total}`
        : (status === 'RUNNING' ? `${run.progress_completed || 0}` : '');
      const progressPctText = (status === 'RUNNING' && typeof run.progress_pct === 'number')
        ? `${Math.round(run.progress_pct * 100)}%`
        : '';

      return `
        <tr data-idx="${idx}" data-file="${encodeURIComponent(run.file_path)}"
            class="${isSelected ? 'selected' : ''} ${isFocused ? 'focused' : ''}">
          <td class="col-select" onclick="event.stopPropagation()">
            <label class="custom-checkbox">
              <input type="checkbox" class="row-checkbox" ${isSelected ? 'checked' : ''} />
              <span class="checkmark"></span>
            </label>
          </td>
          <td class="col-run">
            <span class="run-id" title="${run.run_id}">${stripProviderFromRunId(run.run_id)}</span>
            ${status ? `<span class="status-badge status-${status}">${status}${progressPctText ? ` • ${progressPctText}` : ''}${progressText ? ` • ${progressText}` : ''}</span>` : ''}
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
          <td class="col-success">
            <span class="success-rate ${successClass}">${formatPercent(run.success_rate)}</span>
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
            ${langfuseUrl ? `
              <a href="${langfuseUrl}" target="_blank" class="action-btn langfuse-btn" title="View in Langfuse" onclick="event.stopPropagation()">Langfuse ↗</a>
            ` : ''}
            ${canSubmit ? `
              <a href="#" class="action-icon submit-run" title="Submit">
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                  <line x1="22" y1="2" x2="11" y2="13"></line>
                  <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                </svg>
              </a>
            ` : ''}
            ${canApprove ? `
              <a href="#" class="action-icon approve-run" title="Approve">
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
              </a>
              <a href="#" class="action-icon reject-run" title="Reject">
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
              </a>
            ` : ''}
            <a href="#" class="action-icon delete-run" title="Delete run">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
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

      const submitBtn = tr.querySelector('.submit-run');
      if (submitBtn) submitBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        try {
          await fetch(apiUrl(`v1/runs/${encodeURIComponent(run.run_id)}/submit`), { method: 'POST' });
          await fetchRuns();
        } catch (err) {
          console.error('Submit failed', err);
        }
      });

      const approveBtn = tr.querySelector('.approve-run');
      if (approveBtn) approveBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        const comment = prompt('Approval comment (optional):') || '';
        try {
          await fetch(apiUrl(`v1/runs/${encodeURIComponent(run.run_id)}/approve`), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ comment }),
          });
          await fetchRuns();
        } catch (err) {
          console.error('Approve failed', err);
        }
      });

      const rejectBtn = tr.querySelector('.reject-run');
      if (rejectBtn) rejectBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        const comment = prompt('Rejection comment (optional):') || '';
        try {
          await fetch(apiUrl(`v1/runs/${encodeURIComponent(run.run_id)}/reject`), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ comment }),
          });
          await fetchRuns();
        } catch (err) {
          console.error('Reject failed', err);
        }
      });

      tr.querySelector('.delete-run').addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        confirmDeleteRun(filePath, run.run_id);
      });

      tr.addEventListener('click', () => {
        state.focusedIndex = idx;
        renderTableView();
      });

      tr.addEventListener('dblclick', () => {
        openRun(filePath);
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

    let filterText = 'Showing all runs';
    if (state.searchQuery || state.quickFilter !== 'all' || state.filterPublishStatus) {
      filterText = `Showing ${filtered} of ${total} runs`;
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

    // Show Submit button when at least 1 run is selected (bulk submit for approval)
    const publishBtn = el('publish-selected');
    if (publishBtn) {
      publishBtn.style.display = selectedRuns.length >= 1 ? 'inline-block' : 'none';
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

    // Get runs matching task+dataset
    const matchingRuns = state.flatRuns.filter(r =>
      r.task_name === selectedTask && r.dataset_name === selectedDataset
    );

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
    if (modelsGrid) modelsGrid.innerHTML = '<div class="models-loading">Loading run data...</div>';

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
    const metrics = window.LLMEvalMetrics.calculateItemLevelMetrics({
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
              <div class="stat-main ${getSuccessClass(stats.consistency)}">${formatPercent(stats.consistency)}</div>
            </div>
            <div class="model-stat-box">
              <div class="stat-title">Reliability ${infoIcon(tooltips.reliability)}</div>
              <div class="stat-main ${getSuccessClass(stats.reliability)}">${formatPercent(stats.reliability)}</div>
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

    // Render run list
    listEl.innerHTML = `
      <div class="run-selection-header">
        <span class="selection-counter"><span id="selection-count">0</span> / ${globalK} selected</span>
      </div>
      <div class="run-selection-items">
        ${allRuns.map((run, idx) => {
          const isSelected = currentSelection.length > 0
            ? currentSelection.includes(run.file_path)
            : idx < globalK;  // Default: first K runs
          if (isSelected) selectionCount++;
          const dt = formatDate(run.timestamp);
          const metric = mvs.selectedMetric;
          const score = run.metric_averages?.[metric];
          const scoreClass = score !== undefined ? getSuccessClass(score) : '';

          const isPublished = state.publishedRuns.has(run.run_id);
          return `
            <label class="run-selection-item ${isSelected ? 'selected' : ''}">
              <input type="checkbox" data-file="${run.file_path}" ${isSelected ? 'checked' : ''} />
              <div class="run-info">
                <div class="run-name" title="${run.run_id}">${stripProviderFromRunId(run.run_id)}${isPublished ? '<span class="published-badge"><span class="badge-icon">✓</span>Published</span>' : ''}</div>
                <div class="run-date">${dt.full}</div>
              </div>
              ${score !== undefined ? `<span class="run-score ${scoreClass}">${formatPercent(score)}</span>` : ''}
            </label>
          `;
        }).join('')}
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
      alert('Select at least 2 runs to compare');
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
      const data = await runsResponse.json();
      state.runs = data;
      const { runs, metrics } = flattenRuns(data);
      state.flatRuns = runs;
      state.allMetrics = metrics;
      try {
        state.currentUser = meResponse ? await meResponse.json() : null;
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

  function updateProfileLink() {
    const link = el('profile-link');
    if (!link) return;
    link.href = apiUrl('profile');
    const u = state.currentUser || {};
    const label = u.display_name || u.email || 'Profile';
    link.textContent = label;
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
  $('.header-meta').addEventListener('click', () => {
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

  // Confluence support removed (publishing, projects/tasks/users, and related git-info fetching).

  async function submitSelectedRuns() {
    if (state.selectedRuns.size === 0) return;
    const selectedRuns = state.flatRuns.filter(r => state.selectedRuns.has(r.file_path));
    let ok = 0;
    let failed = 0;

    for (const run of selectedRuns) {
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

  // Compare panel: bulk-submit selected runs for approval.
  el('publish-selected')?.addEventListener('click', () => submitSelectedRuns());

  /* Confluence publishing removed.
   *
   * The sections below were the legacy Confluence publish/aggregate publish UI
   * and related API calls. They are intentionally disabled to avoid any Confluence
   * surface area in the dashboard.
   */
  // Aggregate publish state
  const aggregatePublishState = {
    runs: [],
    thresholds: {},  // metric_name -> threshold (0-1)
    commonMetrics: [],
    runsData: null,  // Cached run data from compare API for preview and publish
  };

  function validateAggregateRuns(runs) {
    // Check that all runs have the same model, dataset, task, and commit
    if (runs.length < 2) return { valid: false, error: 'Need at least 2 runs to publish aggregate results' };

    const first = runs[0];
    const model = first.model_name;
    const dataset = first.dataset_name;
    const task = first.task_name;

    for (const run of runs) {
      if (run.model_name !== model) {
        return { valid: false, error: `All runs must use the same model. Found "${model}" and "${run.model_name}"` };
      }
      if (run.dataset_name !== dataset) {
        return { valid: false, error: `All runs must use the same dataset. Found "${dataset}" and "${run.dataset_name}"` };
      }
      if (run.task_name !== task) {
        return { valid: false, error: `All runs must use the same task. Found "${task}" and "${run.task_name}"` };
      }
    }

    // Check commit - warn if different but don't block
    const commits = new Set(runs.map(r => r.commit || 'unknown'));
    let warning = null;
    if (commits.size > 1) {
      warning = 'Warning: Selected runs have different git commits. This may affect comparability.';
    }

    return { valid: true, warning };
  }

  function getCommonMetrics(runs) {
    // Find metrics that exist in all runs
    if (runs.length === 0) return [];

    const first = runs[0];
    if (!first.metric_averages) return [];

    const metrics = Object.keys(first.metric_averages);
    return metrics.filter(metric =>
      runs.every(r => r.metric_averages && r.metric_averages[metric] !== undefined)
    );
  }

  function calculateAggregateMetricsFromItems(runsData, metric, threshold) {
    // Use shared metrics calculation
    const K = runsData?.length || 0;

    if (!runsData || runsData.length === 0) {
      return {
        metric_name: metric,
        threshold: threshold,
        pass_at_k: 0,
        pass_k: 0,
        max_at_k: 0,
        consistency: 0,
        reliability: 0,
        avg_score: 0,
        failed_count: 0,
        min_score: 0,
        max_score: 0,
        runs_passed: 0,
        total_runs: 0,
      };
    }

    const metrics = window.LLMEvalMetrics.calculateItemLevelMetrics({
      runsData,
      metricName: metric,
      threshold,
      getMetricIndex: (runData) => {
        const metricNames = runData?.run?.metric_names || [];
        return metricNames.indexOf(metric);
      },
      getItemId: (row) => row.item_id || String(row.index)
    });

    // Calculate run-level stats for min/max/runs_passed (for display)
    const runAvgScores = runsData.map(r => {
      const avg = r?.run?.metric_averages?.[metric];
      return avg !== undefined ? avg : 0;
    });
    const runsPassed = runAvgScores.filter(s => s >= threshold).length;

    return {
      metric_name: metric,
      threshold: threshold,
      pass_at_k: metrics.passAtK,
      pass_k: metrics.passHatK,
      max_at_k: metrics.maxAtK,
      consistency: metrics.consistency,
      reliability: metrics.reliability,
      avg_score: metrics.avgScore,
      failed_count: metrics.failedCount,
      min_score: Math.min(...runAvgScores),
      max_score: Math.max(...runAvgScores),
      runs_passed: runsPassed,
      total_runs: K,
    };
  }

  async function fetchRunsDataForAggregate(filePaths) {
    if (filePaths.length === 0) return [];
    try {
      const params = filePaths.map(f => `files=${encodeURIComponent(f)}`).join('&');
      const response = await fetch(apiUrl(`api/compare?${params}`));
      if (!response.ok) throw new Error('Failed to fetch run data');
      const data = await response.json();
      return data.runs || [];
    } catch (error) {
      console.error('Error fetching runs data for aggregate:', error);
      return [];
    }
  }

  // Load metrics preview when modal opens
  async function loadMetricsPreview(runs) {
    const previewTable = el('metrics-preview-table');
    const loadingDiv = el('metrics-preview-loading');

    // Show loading
    previewTable.innerHTML = '';
    loadingDiv.style.display = 'block';

    // Fetch detailed run data
    const filePaths = runs.map(r => r.file_path);
    const runsData = await fetchRunsDataForAggregate(filePaths);

    // Store for later use
    aggregatePublishState.runsData = runsData;

    loadingDiv.style.display = 'none';

    if (runsData.length === 0) {
      previewTable.innerHTML = '<p style="padding: 1rem; color: var(--text-muted);">Failed to load run data for preview.</p>';
      return;
    }

    // Render the preview
    updateMetricsPreview();
  }

  // Update metrics preview table based on current thresholds
  function updateMetricsPreview() {
    const previewTable = el('metrics-preview-table');
    const runsData = aggregatePublishState.runsData;
    const metrics = aggregatePublishState.commonMetrics;
    const K = aggregatePublishState.runs.length;

    if (!runsData || runsData.length === 0 || metrics.length === 0) {
      previewTable.innerHTML = '<p style="padding: 1rem; color: var(--text-muted);">No metrics data available.</p>';
      return;
    }

    // Calculate metrics for each metric name
    const rows = metrics.map(metricName => {
      const threshold = aggregatePublishState.thresholds[metricName] ?? 0.8;
      const result = calculateAggregateMetricsFromItems(runsData, metricName, threshold);
      return {
        name: metricName.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
        threshold: threshold,
        ...result
      };
    });

    // Calculate average latency across all runs
    let totalLatency = 0;
    let latencyCount = 0;
    for (const run of aggregatePublishState.runs) {
      if (run.avg_latency_ms > 0) {
        totalLatency += run.avg_latency_ms;
        latencyCount++;
      }
    }
    const avgLatency = latencyCount > 0 ? totalLatency / latencyCount : 0;

    // Format latency
    const formatLat = (ms) => {
      if (!ms || ms <= 0) return '—';
      if (ms >= 60000) return `${Math.floor(ms / 60000)}m ${((ms % 60000) / 1000).toFixed(0)}s`;
      if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
      return `${ms.toFixed(0)}ms`;
    };

    // Get score color class - 5-level gradient matching compare view
    const getColorClass = (score) => {
      if (score >= 0.9) return 'score-5';
      if (score >= 0.75) return 'score-4';
      if (score >= 0.6) return 'score-3';
      if (score >= 0.4) return 'score-2';
      return 'score-1';
    };

    // Render table
    previewTable.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>Metric</th>
            <th>Threshold</th>
            <th>Pass@${K}</th>
            <th>Pass^${K}</th>
            <th>Max@${K}</th>
            <th>Consistency</th>
            <th>Reliability</th>
            <th>Avg Score</th>
            <th>Errors</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(r => `
            <tr>
              <td>${r.name}</td>
              <td>≥${(r.threshold * 100).toFixed(0)}%</td>
              <td class="${getColorClass(r.pass_at_k)}">${(r.pass_at_k * 100).toFixed(1)}%</td>
              <td class="${getColorClass(r.pass_k)}">${(r.pass_k * 100).toFixed(1)}%</td>
              <td class="${getColorClass(r.max_at_k)}">${(r.max_at_k * 100).toFixed(1)}%</td>
              <td class="${getColorClass(r.consistency)}">${(r.consistency * 100).toFixed(1)}%</td>
              <td class="${getColorClass(r.reliability)}">${(r.reliability * 100).toFixed(1)}%</td>
              <td class="${getColorClass(r.avg_score)}">${(r.avg_score * 100).toFixed(1)}%</td>
              <td class="${r.failed_count > 0 ? 'score-1' : ''}">${r.failed_count}</td>
            </tr>
          `).join('')}
          <tr style="background: var(--bg-active);">
            <td colspan="9" style="text-align: right; font-weight: 500;">Avg Latency:</td>
            <td>${formatLat(avgLatency)}</td>
          </tr>
        </tbody>
      </table>
    `;
  }

  function openAggregatePublishModal(runs) {
    // Validate runs
    const validation = validateAggregateRuns(runs);

    const errorDiv = el('aggregate-validation-error');
    const errorMsg = el('aggregate-error-message');

    if (!validation.valid) {
      errorDiv.style.display = 'flex';
      errorMsg.textContent = validation.error;
      el('confirm-aggregate-publish-btn').disabled = true;
    } else {
      errorDiv.style.display = validation.warning ? 'flex' : 'none';
      if (validation.warning) {
        errorMsg.textContent = validation.warning;
      }
      el('confirm-aggregate-publish-btn').disabled = false;
    }

    // Store runs and reset cached data
    aggregatePublishState.runs = runs;
    aggregatePublishState.runsData = null;  // Reset to force fresh fetch for preview

    // Get common metrics
    const commonMetrics = getCommonMetrics(runs);
    aggregatePublishState.commonMetrics = commonMetrics;

    // Initialize thresholds to 80% by default
    aggregatePublishState.thresholds = {};
    commonMetrics.forEach(m => {
      aggregatePublishState.thresholds[m] = 0.8;
    });

    const first = runs[0];
    const k = runs.length;

    // Generate default run name (use stripped model name)
    const timestamp = new Date().toISOString().slice(2, 16).replace(/[-T:]/g, '').slice(0, 11);
    const defaultRunName = `${stripModelProvider(first.model_name)}-K${k}-${timestamp}`;
    el('agg-publish-run-name').value = defaultRunName;

    // Populate run info
    const avgLatency = runs.reduce((sum, r) => sum + (r.avg_latency_ms || 0), 0) / k;
    const avgItems = Math.round(runs.reduce((sum, r) => sum + r.total_items, 0) / k);

    el('aggregate-run-info').innerHTML = `
      <div class="info-header">
        <h3>Aggregate Publish</h3>
        <span class="k-badge">K = ${k} runs</span>
      </div>
      <div class="info-grid">
        <div class="info-item">
          <div class="info-label">Model</div>
          <div class="info-value" title="${first.model_name}">${stripModelProvider(first.model_name)}</div>
        </div>
        <div class="info-item">
          <div class="info-label">Dataset</div>
          <div class="info-value">${first.dataset_name}</div>
        </div>
        <div class="info-item">
          <div class="info-label">Task</div>
          <div class="info-value">${first.task_name}</div>
        </div>
        <div class="info-item">
          <div class="info-label">Avg Items/Run</div>
          <div class="info-value">${avgItems}</div>
        </div>
      </div>
    `;

    // Populate threshold sliders
    const slidersContainer = el('threshold-sliders');
    if (commonMetrics.length === 0) {
      slidersContainer.innerHTML = '<p style="color: var(--text-muted);">No common metrics found across selected runs.</p>';
    } else {
      slidersContainer.innerHTML = commonMetrics.map(metric => `
        <div class="threshold-row" data-metric="${metric}">
          <span class="metric-name">${metric.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</span>
          <div class="slider-container">
            <input type="range" class="threshold-slider" data-metric="${metric}"
                   min="0" max="100" step="5" value="80">
            <span class="threshold-value" data-metric="${metric}">80%</span>
          </div>
        </div>
      `).join('');

      // Wire up slider events
      slidersContainer.querySelectorAll('.threshold-slider').forEach(slider => {
        slider.addEventListener('input', (e) => {
          const metric = e.target.dataset.metric;
          const value = parseInt(e.target.value);
          aggregatePublishState.thresholds[metric] = value / 100;
          slidersContainer.querySelector(`.threshold-value[data-metric="${metric}"]`).textContent = `${value}%`;
          // Update preview when threshold changes
          updateMetricsPreview();
        });
      });
    }

    // Load and show metrics preview
    loadMetricsPreview(runs);

    // Reset form
    el('agg-publish-project').value = '';
    el('agg-publish-task').value = '';
    el('agg-publish-task').disabled = true;
    el('agg-add-task-btn').disabled = true;
    el('agg-publish-user-search').value = '';
    el('agg-publish-user').value = '';
    el('agg-publish-description').value = '';
    el('agg-publish-branch').value = publishState.gitInfo.branch || '(not available)';
    el('agg-publish-commit').value = publishState.gitInfo.commit || '(not available)';

    // Update button text
    el('confirm-aggregate-publish-btn').textContent = `Publish ${k} Runs`;

    // Fetch projects
    fetchProjectsForAggregate();

    // Show modal
    el('aggregate-publish-modal').style.display = 'flex';
  }

  async function fetchProjectsForAggregate() {
    try {
      const response = await fetch(apiUrl('api/confluence/projects'));
      const data = await response.json();
      const projects = data.projects || [];

      const select = el('agg-publish-project');
      select.innerHTML = '<option value="">Select a project...</option>' +
        projects.map(p => `<option value="${p.name}">${p.name}</option>`).join('');
    } catch (err) {
      console.error('Failed to fetch projects:', err);
    }
  }

  async function fetchTasksForAggregate(projectName) {
    try {
      const response = await fetch(apiUrl(`api/confluence/projects/${encodeURIComponent(projectName)}/tasks`));
      const data = await response.json();
      const tasks = data.tasks || [];

      const select = el('agg-publish-task');
      select.innerHTML = '<option value="">Select a task...</option>' +
        tasks.map(t => `<option value="${t.title}">${t.title}</option>`).join('');
      select.disabled = false;
      el('agg-add-task-btn').disabled = false;
    } catch (err) {
      console.error('Failed to fetch tasks:', err);
    }
  }

  async function searchUsersForAggregate(query) {
    try {
      const url = apiUrl(query ? `api/confluence/users?q=${encodeURIComponent(query)}` : 'api/confluence/users');
      const response = await fetch(url);
      const data = await response.json();
      const users = data.users || [];

      const dropdown = el('agg-user-dropdown');
      if (users.length === 0) {
        dropdown.innerHTML = '<div class="user-option no-results">No users found</div>';
      } else {
        dropdown.innerHTML = users.map(u => `
          <div class="user-option" data-username="${u.username}" data-display="${u.display_name}">
            <span class="user-name">${u.display_name}</span>
            <span class="user-username">@${u.username}</span>
          </div>
        `).join('');

        // Wire up click events
        dropdown.querySelectorAll('.user-option').forEach(opt => {
          opt.addEventListener('click', () => {
            el('agg-publish-user').value = opt.dataset.username;
            el('agg-publish-user-search').value = opt.dataset.display;
            dropdown.style.display = 'none';
          });
        });
      }
      dropdown.style.display = 'block';
    } catch (err) {
      console.error('Failed to search users:', err);
    }
  }

  async function publishAggregateRuns() {
    const runs = aggregatePublishState.runs;
    if (runs.length === 0) return;

    const runName = el('agg-publish-run-name').value.trim();
    const projectName = el('agg-publish-project').value;
    const taskName = el('agg-publish-task').value;
    const username = el('agg-publish-user').value;
    const description = el('agg-publish-description').value.trim();

    // Validate
    if (!runName) {
      showToast('error', 'Missing Run Name', 'Please provide a run name');
      return;
    }
    if (!projectName) {
      showToast('error', 'Missing Project', 'Please select a project');
      return;
    }
    if (!taskName) {
      showToast('error', 'Missing Task', 'Please select or create a task');
      return;
    }
    if (!username) {
      showToast('error', 'Missing User', 'Please select a user');
      return;
    }
    if (!description) {
      showToast('error', 'Missing Description', 'Please provide a description');
      return;
    }

    const btn = el('confirm-aggregate-publish-btn');
    btn.disabled = true;
    btn.textContent = 'Publishing...';

    // Reuse runs data already fetched for preview (or fetch if not available)
    let runsData = aggregatePublishState.runsData;
    if (!runsData || runsData.length === 0) {
      btn.textContent = 'Loading data...';
      const filePaths = runs.map(r => r.file_path);
      runsData = await fetchRunsDataForAggregate(filePaths);
      if (runsData.length === 0) {
        showToast('error', 'Load Failed', 'Failed to load run data for metric calculation');
        btn.disabled = false;
        btn.textContent = `Publish ${runs.length} Runs`;
        return;
      }
      btn.textContent = 'Publishing...';
    }

    // Calculate aggregate metrics for each metric using item-level data
    const metricResults = aggregatePublishState.commonMetrics.map(metric => {
      const threshold = aggregatePublishState.thresholds[metric] ?? 0.8;
      return calculateAggregateMetricsFromItems(runsData, metric, threshold);
    });

    // Build per-run details with all metrics and latency
    const runDetails = runs.map(r => ({
      run_id: r.run_id,
      langfuse_url: r.langfuse_url || null,
      metrics: r.metric_averages || {},
      latency_ms: r.avg_latency_ms || 0,
    }));

    const first = runs[0];
    const avgLatency = runs.reduce((sum, r) => sum + (r.avg_latency_ms || 0), 0) / runs.length;
    const avgItems = Math.round(runs.reduce((sum, r) => sum + r.total_items, 0) / runs.length);

    try {
      const response = await fetch(apiUrl('api/confluence/publish-aggregate'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_name: projectName,
          task_name: taskName,
          run_name: runName,
          published_by: username,
          description: description,
          model: first.model_name,
          dataset: first.dataset_name,
          task: first.task_name,
          run_details: runDetails,
          metric_results: metricResults,
          total_items_per_run: avgItems,
          avg_latency_ms: avgLatency,
          branch: publishState.gitInfo.branch,
          commit: publishState.gitInfo.commit,
        })
      });

      const result = await response.json();

      if (result.success) {
        el('aggregate-publish-modal').style.display = 'none';
        // Mark aggregate run as published
        publishState.publishedRuns.add(runName);
        state.publishedRuns.add(runName);  // Sync to main state
        // Show success toast
        showToast('success', 'Published Successfully', `Aggregate results for ${runs.length} runs published to Confluence`);
        // Clear selection and re-render
        state.selectedRuns.clear();
        render();
      } else {
        showToast('error', 'Publish Failed', result.error || 'Unknown error');
      }
    } catch (err) {
      showToast('error', 'Publish Failed', err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = `Publish ${runs.length} Runs`;
    }
  }

  async function publishRun() {
    const run = publishState.currentRun;
    if (!run) return;

    const runName = el('publish-run-name').value.trim();
    const projectName = el('publish-project').value;
    const taskName = el('publish-task').value;
    const username = el('publish-user').value;
    const description = el('publish-description').value.trim();

    // Validate
    if (!runName) {
      showToast('error', 'Missing Run Name', 'Please provide a run name');
      return;
    }
    if (!projectName) {
      showToast('error', 'Missing Project', 'Please select a project');
      return;
    }
    if (!taskName) {
      showToast('error', 'Missing Task', 'Please select or create a task');
      return;
    }
    if (!username) {
      showToast('error', 'Missing User', 'Please select a user');
      return;
    }
    if (!description) {
      showToast('error', 'Missing Description', 'Please provide a description');
      return;
    }

    const btn = el('confirm-publish-btn');
    btn.disabled = true;
    btn.textContent = 'Publishing...';

    try {
      const response = await fetch(apiUrl('api/confluence/publish'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_name: projectName,
          task_name: taskName,
          run_id: runName,  // Use user-provided run name
          published_by: username,
          description: description,
          metrics: run.metric_averages || {},
          model: run.model_name,
          dataset: run.dataset_name,
          total_items: run.total_items,
          success_count: run.success_count,
          error_count: run.error_count,
          avg_latency_ms: run.avg_latency_ms,
          branch: publishState.gitInfo.branch,
          commit: publishState.gitInfo.commit,
          trace_url: run.langfuse_url || null,
        })
      });

      const result = await response.json();

      if (result.success) {
        el('publish-modal').style.display = 'none';
        // Mark run as published (use original run_id for tracking)
        publishState.publishedRuns.add(run.run_id);
        state.publishedRuns.add(run.run_id);  // Sync to main state
        // Show success toast
        showToast('success', 'Published Successfully', `Run "${runName}" has been published to Confluence`);
        // Clear selection and re-render to show published badge
        state.selectedRuns.clear();
        render();
      } else {
        showToast('error', 'Publish Failed', result.error || 'Unknown error');
      }
    } catch (err) {
      showToast('error', 'Publish Failed', err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Publish';
    }
  }

  async function createTask() {
    // Check if this was triggered from the aggregate modal
    const isAggregate = el('create-task-modal').dataset.target === 'aggregate';
    const projectName = isAggregate ? el('agg-publish-project').value : el('publish-project').value;

    if (!projectName) {
      showToast('error', 'Missing Project', 'Please select a project first');
      return;
    }

    const taskName = el('new-task-name').value.trim();
    if (!taskName) {
      showToast('error', 'Missing Task Name', 'Please enter a task name');
      return;
    }

    const btn = el('confirm-create-task-btn');
    btn.disabled = true;
    btn.textContent = 'Creating...';

    try {
      const response = await fetch(apiUrl(`api/confluence/projects/${encodeURIComponent(projectName)}/tasks`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: taskName })
      });

      const result = await response.json();

      if (result.id) {
        el('create-task-modal').style.display = 'none';
        el('create-task-modal').dataset.target = '';  // Reset target
        el('new-task-name').value = '';

        // Refresh tasks and select the new one in the appropriate modal
        if (isAggregate) {
          await fetchTasksForAggregate(projectName);
          el('agg-publish-task').value = result.title;
        } else {
          await fetchTasks(projectName);
          el('publish-task').value = result.title;
        }
        showToast('success', 'Task Created', `Task "${taskName}" has been created`);
      } else {
        showToast('error', 'Create Failed', result.error || 'Unknown error');
      }
    } catch (err) {
      showToast('error', 'Create Failed', err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Create';
    }
  }

  // Wire up publish modal events
  el('publish-project')?.addEventListener('change', (e) => {
    const projectName = e.target.value;
    if (projectName) {
      fetchTasks(projectName);
    } else {
      el('publish-task').innerHTML = '<option value="">Select a task...</option>';
      el('publish-task').disabled = true;
      el('add-task-btn').disabled = true;
    }
  });

  el('publish-user-search')?.addEventListener('input', debounce((e) => {
    const query = e.target.value.trim();
    if (query.length >= 1) {
      fetchUsers(query);
    } else {
      fetchUsers();
    }
  }, 200));

  el('publish-user-search')?.addEventListener('focus', () => {
    if (publishState.users.length > 0) {
      el('user-dropdown').style.display = 'block';
    } else {
      fetchUsers();
    }
  });

  // Close user dropdown when clicking outside
  document.addEventListener('click', (e) => {
    const wrapper = document.querySelector('.user-search-wrapper');
    if (wrapper && !wrapper.contains(e.target)) {
      el('user-dropdown').style.display = 'none';
    }
  });

  el('add-task-btn')?.addEventListener('click', () => {
    el('create-task-modal').style.display = 'flex';
    el('create-task-modal').dataset.target = '';  // Clear target for single-run modal
  });

  el('confirm-publish-btn')?.addEventListener('click', publishRun);
  el('confirm-create-task-btn')?.addEventListener('click', createTask);
  // Compare panel: rename "Publish" to "Submit" and bulk-submit selected runs for approval.
  el('publish-selected')?.addEventListener('click', () => submitSelectedRuns());

  // Aggregate publish modal events
  el('confirm-aggregate-publish-btn')?.addEventListener('click', publishAggregateRuns);

  el('agg-publish-project')?.addEventListener('change', (e) => {
    const projectName = e.target.value;
    if (projectName) {
      fetchTasksForAggregate(projectName);
    } else {
      el('agg-publish-task').innerHTML = '<option value="">Select a task...</option>';
      el('agg-publish-task').disabled = true;
      el('agg-add-task-btn').disabled = true;
    }
  });

  el('agg-add-task-btn')?.addEventListener('click', () => {
    // Reuse the create task modal but wire it to aggregate form
    el('create-task-modal').style.display = 'flex';
    el('create-task-modal').dataset.target = 'aggregate';
  });

  // User search for aggregate modal
  el('agg-publish-user-search')?.addEventListener('input', debounce((e) => {
    const query = e.target.value.trim();
    if (query.length >= 1) {
      searchUsersForAggregate(query);
    } else {
      el('agg-user-dropdown').style.display = 'none';
    }
  }, 200));

  el('agg-publish-user-search')?.addEventListener('focus', () => {
    // Fetch all users when focused
    searchUsersForAggregate('');
  });

  // Close aggregate user dropdown when clicking outside
  document.addEventListener('click', (e) => {
    const aggWrapper = document.querySelector('#aggregate-publish-modal .user-search-wrapper');
    if (aggWrapper && !aggWrapper.contains(e.target)) {
      el('agg-user-dropdown').style.display = 'none';
    }
  });

  // Close modals on click outside
  ['publish-modal', 'create-task-modal', 'aggregate-publish-modal'].forEach(modalId => {
    el(modalId)?.addEventListener('click', (e) => {
      if (e.target.id === modalId) {
        el(modalId).style.display = 'none';
      }
    });
  });

  // Fetch git info on load
  fetchGitInfo();

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

  restoreDashboardState();
  startHeartbeat();
  fetchRuns();

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
