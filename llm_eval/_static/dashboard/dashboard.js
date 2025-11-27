/**
 * LLM-Eval Analytics Dashboard
 * Dense, keyboard-driven interface for analyzing evaluation runs
 */

(() => {
  'use strict';

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
    currentView: 'charts',  // Default to charts view
    selectedRuns: new Set(),
    focusedIndex: -1,
    aggregations: null,
    chartData: null,  // Aggregated data for charts
    allMetrics: [],   // All unique metric names across runs
    allModels: [],    // All unique model names
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
    if (rate >= 0.9) return 'high';
    if (rate >= 0.7) return 'mid';
    return 'low';
  }

  function formatNumber(n) {
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
    return n.toString();
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

  function truncateText(text, maxLen = 200) {
    if (!text || text.length <= maxLen) return text;
    return text.substring(0, maxLen) + '...';
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
          totalItems: 0,
          latestTimestamp: null,
          metricSums: {},
          metricCounts: {},
        };
      }

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

      // Track latest run
      const ts = new Date(run.timestamp);
      if (!combos[key].models[model].latestTimestamp || ts > combos[key].models[model].latestTimestamp) {
        combos[key].models[model].latestTimestamp = ts;
      }
    }

    // Calculate metric averages per model
    for (const key of Object.keys(combos)) {
      combos[key].metrics = Array.from(combos[key].metrics);
      for (const model of Object.keys(combos[key].models)) {
        const m = combos[key].models[model];
        m.metricAverages = {};
        for (const [metric, sum] of Object.entries(m.metricSums)) {
          const count = m.metricCounts[metric] || 1;
          m.metricAverages[metric] = sum / count;
        }
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
          r.run_id.toLowerCase().includes(q) ||
          r.task_name.toLowerCase().includes(q) ||
          r.model_name.toLowerCase().includes(q) ||
          r.display_model.toLowerCase().includes(q) ||
          r.dataset_name.toLowerCase().includes(q)
      );
    }

    // Quick filter (only time-based filters now)
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
      const isFiltered = state.searchQuery || state.quickFilter !== 'all';
      if (isFiltered) {
        subtitleEl.textContent = `Filtered: ${state.filteredRuns.length} runs • Showing average metric scores across all items`;
      } else {
        subtitleEl.textContent = `Showing average metric scores across all items in matching runs`;
      }
    }
    
    if (!chartData || chartData.combos.length === 0) {
      el('charts-grid').innerHTML = `
        <div class="chart-no-data" style="grid-column: 1/-1;">
          ${state.searchQuery || state.quickFilter !== 'all' 
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
        <div class="legend-item ${isActive ? '' : 'inactive'}" data-model="${model}">
          <span class="legend-color" style="background:${CHART_COLORS[idx % CHART_COLORS.length]}"></span>
          <span>${model}</span>
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

      // Build charts for each metric
      const metricChartsHtml = metrics.map(metric => {
        // Get model scores for this metric, sorted by score
        const modelScores = modelEntries
          .map(([model, data]) => ({
            model,
            score: data.metricAverages?.[metric] ?? 0,
            runs: data.runs,
          }))
          .filter(m => m.score > 0 || m.runs > 0)
          .sort((a, b) => b.score - a.score);

        if (modelScores.length === 0) return '';

        const barsHtml = modelScores.map(({ model, score, runs }) => {
          const pct = score * 100;
          const successClass = getSuccessClass(score);
          const modelIdx = chartData.modelIndex[model] % 8;
          const barWidth = Math.max(pct, 2);
          const runsLabel = runs === 1 ? '1 run' : `${runs} runs`;

          return `
            <div class="chart-bar-row">
              <span class="chart-bar-label" title="${model}">${model}</span>
              <div class="chart-bar-container">
                <div class="chart-bar-track">
                  <div class="chart-bar-fill animated" data-model-idx="${modelIdx}" style="width:${barWidth}%">
                    ${pct > 20 ? `<span class="chart-bar-inner-value">${pct.toFixed(1)}%</span>` : ''}
                  </div>
                </div>
                <span class="chart-bar-value ${successClass}">${pct.toFixed(1)}%</span>
                <span class="chart-bar-runs" title="Averaged from ${runsLabel}">${runs}×</span>
              </div>
            </div>
          `;
        }).join('');

        return `
          <div class="metric-section">
            <div class="metric-section-header">${metric}</div>
            <div class="chart-bars">
              ${barsHtml}
            </div>
          </div>
        `;
      }).join('');

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
  }

  // ═══════════════════════════════════════════════════
  // RENDERING: TABLE VIEW
  // ═══════════════════════════════════════════════════

  function updateTableHeader() {
    // Update the table header to include dynamic metric columns
    const headerRow = el('table-header-row');
    if (!headerRow) return;

    // Find the TIME column (insert metric columns before it)
    const timeHeader = headerRow.querySelector('.col-time');
    if (!timeHeader) return;

    // Remove any existing dynamic metric columns
    headerRow.querySelectorAll('.col-metric-dynamic').forEach(col => col.remove());

    // Insert metric columns before TIME column (limit to 4 metrics)
    const metricsToShow = state.allMetrics.slice(0, 4);
    metricsToShow.forEach(metric => {
      const th = document.createElement('th');
      th.className = 'col-metric-dynamic sortable';
      th.dataset.sort = `metric-${metric}`;
      th.textContent = metric.toUpperCase();
      th.title = `Sort by ${metric}`;
      headerRow.insertBefore(th, timeHeader);
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
      const numericFields = ['success', 'items', 'status', 'time', 'date'];
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
      const statusClass = run.error_count > 0 ? 'warn' : 'ok';
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

      return `
        <tr data-idx="${idx}" data-file="${encodeURIComponent(run.file_path)}"
            class="${isSelected ? 'selected' : ''} ${isFocused ? 'focused' : ''}">
          <td class="col-select" onclick="event.stopPropagation()">
            <input type="checkbox" class="row-checkbox" ${isSelected ? 'checked' : ''} />
          </td>
          <td class="col-status">
            <span class="status-dot ${statusClass}" title="${run.error_count} errors"></span>
          </td>
          <td class="col-run">
            <span class="run-id" title="${run.run_id}">${truncateText(run.run_id, 40)}</span>
          </td>
          <td class="col-task">
            <span class="tag task" title="${run.task_name}">${truncateText(run.task_name, 30)}</span>
          </td>
          <td class="col-model">
            <span class="tag model" title="${run.model_name}">
              <span class="model-color-dot" style="background:${CHART_COLORS[state.allModels.indexOf(run.model_name) % CHART_COLORS.length]}"></span>
              ${truncateText(run.model_name, 30)}
            </span>
          </td>
          <td class="col-dataset">
            <span class="tag" title="${run.dataset_name}">${truncateText(run.dataset_name, 25)}</span>
          </td>
          <td class="col-items">
            <span class="items-count">${run.total_items}</span>
          </td>
          <td class="col-success">
            <span class="success-rate ${successClass}">${formatPercent(run.success_rate)}</span>
          </td>
          ${metricCells}
          <td class="col-time">
            <span class="timestamp">
              <span class="date">${dt.date}</span>
              <span class="time">${dt.time}</span>
            </span>
          </td>
          <td class="col-actions">
            <a href="#" class="action-link open-run" title="Open">→</a>
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

      tr.querySelector('.open-run').addEventListener('click', (e) => {
        e.preventDefault();
        openRun(filePath);
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
            <span class="grid-card-title">${run.run_id}</span>
            <span class="grid-card-success ${successClass}">${formatPercent(run.success_rate)}</span>
          </div>
          <div class="grid-card-meta">
            <span class="tag task">${run.task_name}</span>
            <span class="tag model">${run.model_name}</span>
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
                    <span class="tag model">${run.model_name}</span>
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
    if (state.searchQuery || state.quickFilter !== 'all') {
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

    if (!state.runs) {
      loading.style.display = 'flex';
      empty.style.display = 'none';
      chartsView.style.display = 'none';
      tableView.style.display = 'none';
      gridView.style.display = 'none';
      timelineView.style.display = 'none';
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
      return;
    }

    empty.style.display = 'none';

    // Show current view (Charts or Table/Runs)
    chartsView.style.display = state.currentView === 'charts' ? 'block' : 'none';
    tableView.style.display = state.currentView === 'table' ? 'block' : 'none';
    gridView.style.display = 'none';  // Hidden - using simplified toggle
    timelineView.style.display = 'none';  // Hidden - using simplified toggle

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
    }

    renderStatsBar();
    renderStatusBar();
    renderComparePanel();
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
      // Currently showing all - select all except this one (deselect this one)
      state.allModels.forEach(m => {
        if (m !== model) state.filterModels.add(m);
      });
    } else if (state.filterModels.has(model)) {
      // This model is selected - deselect it
      state.filterModels.delete(model);
      // If none left, show all
      if (state.filterModels.size === 0) {
        // Already empty, will show all
      }
    } else {
      // This model is not selected - select it
      state.filterModels.add(model);
    }
    updateModelFilterButton();
    render();
  }

  function selectOnlyModel(model) {
    state.filterModels.clear();
    state.filterModels.add(model);
    updateModelFilterButton();
    render();
  }

  function updateModelFilterButton() {
    const btn = el('filter-model-btn');
    if (!btn) return;

    if (state.filterModels.size === 0) {
      btn.textContent = 'All Models';
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
    window.location.href = `/run/${encodeURIComponent(filePath)}`;
  }

  function openComparison() {
    if (state.selectedRuns.size < 2) {
      alert('Select at least 2 runs to compare');
      return;
    }
    // Store selected runs for comparison page
    const files = Array.from(state.selectedRuns);
    sessionStorage.setItem('compareRuns', JSON.stringify(files));
    window.location.href = '/compare';
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
      const response = await fetch('/api/runs');
      const data = await response.json();
      state.runs = data;
      const { runs, metrics } = flattenRuns(data);
      state.flatRuns = runs;
      state.allMetrics = metrics;
      state.aggregations = computeAggregations(state.flatRuns);
      state.chartData = computeChartData(state.flatRuns);

      // Populate filter dropdowns
      populateFilterDropdowns();

      el('last-updated').textContent = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

      render();
    } catch (err) {
      console.error('Failed to fetch runs:', err);
      el('loading').innerHTML = `
        <span style="color:var(--error);">Failed to load runs</span>
        <span>Is the server running?</span>
      `;
    }
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
      modelDropdown.innerHTML = `
        <div class="multi-select-option" data-value="">
          <input type="checkbox" ${state.filterModels.size === 0 ? 'checked' : ''} />
          <span>All Models</span>
        </div>
        ${models.map((m, idx) => `
          <div class="multi-select-option" data-value="${m}">
            <span class="model-color" style="background:${CHART_COLORS[idx % CHART_COLORS.length]}"></span>
            <input type="checkbox" ${state.filterModels.size === 0 || state.filterModels.has(m) ? 'checked' : ''} />
            <span>${m}</span>
          </div>
        `).join('')}
      `;

      // Wire dropdown events
      modelDropdown.querySelectorAll('.multi-select-option').forEach(opt => {
        opt.addEventListener('click', (e) => {
          e.stopPropagation();
          const value = opt.dataset.value;
          if (value === '') {
            // "All Models" clicked - clear filter
            state.filterModels.clear();
          } else {
            if (state.filterModels.size === 0) {
              // Currently all selected, now select only this one
              state.filterModels.add(value);
            } else if (state.filterModels.has(value)) {
              state.filterModels.delete(value);
              // If all deselected, show all
            } else {
              state.filterModels.add(value);
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
      fetch('/api/heartbeat', { method: 'POST' }).catch(() => {});
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

  // View toggle (Charts vs Runs)
  $$('.view-toggle-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.view-toggle-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.currentView = btn.dataset.view;
      render();
    });
  });

  // Select all checkbox
  el('select-all').addEventListener('change', selectAll);

  // Compare actions
  el('compare-view')?.addEventListener('click', openComparison);
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
  // INIT
  // ═══════════════════════════════════════════════════

  startHeartbeat();
  fetchRuns();

  // Refresh every 60 seconds
  setInterval(fetchRuns, 60000);

})();
