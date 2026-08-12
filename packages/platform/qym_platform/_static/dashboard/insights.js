(() => {
  'use strict';

  const chartColors = [
    'var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)',
    'var(--score-2)', 'var(--accent-tertiary-soft)', 'var(--info)', 'var(--success)', 'var(--warning)'
  ];

  const state = {
    projectSlug: '',
    payload: null,
    selectedMetrics: new Set(),
    legendMetrics: [],
    metricMode: 'all',
    pointSequence: 0,
    chartWidth: 0,
    filters: {
      period: '30d',
      task: '',
      dataset: '',
      version: '',
      model: '',
      status: '',
      granularity: 'run',
      runLimit: '10',
      scaleMode: 'focus',
    },
  };

  const el = id => document.getElementById(id);

  function escapeHtml(value) {
    const node = document.createElement('div');
    node.textContent = value == null ? '' : String(value);
    return node.innerHTML;
  }

  function escapeAttr(value) {
    return escapeHtml(value)
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;')
      .replace(/`/g, '&#96;');
  }

  function apiUrl(path) {
    const prefix = (window.__QYM_ROOT_PATH__ || '').replace(/\/$/, '');
    return window.location.origin + prefix + '/' + String(path || '').replace(/^\/+/, '');
  }

  function preferenceKey() {
    return 'qym:insights:' + (state.projectSlug || 'project');
  }

  function loadPreferences() {
    try {
      const saved = JSON.parse(localStorage.getItem(preferenceKey()) || '{}');
      Object.keys(state.filters).forEach(key => {
        if (typeof saved[key] === 'string') state.filters[key] = saved[key];
      });
      if (Array.isArray(saved.metrics)) {
        state.selectedMetrics = new Set(saved.metrics.map(String));
        state.metricMode = saved.metricMode === 'all' ? 'all' : 'custom';
      }
    } catch (_error) {
      // A corrupt preference should never prevent Insights from loading.
    }
  }

  function savePreferences() {
    try {
      localStorage.setItem(preferenceKey(), JSON.stringify({
        ...state.filters,
        metrics: Array.from(state.selectedMetrics),
        metricMode: state.metricMode,
      }));
    } catch (_error) {
      // Storage may be disabled; the dashboard remains fully functional.
    }
  }

  function applyControlValues() {
    const controls = {
      'insights-period': 'period',
      'insights-task': 'task',
      'insights-dataset': 'dataset',
      'insights-version': 'version',
      'insights-model': 'model',
      'insights-status': 'status',
      'insights-granularity': 'granularity',
      'insights-run-limit': 'runLimit',
      'insights-scale-mode': 'scaleMode',
    };
    Object.entries(controls).forEach(([id, key]) => {
      const control = el(id);
      if (control) control.value = state.filters[key];
    });
  }

  function populateSelect(id, options, emptyLabel) {
    const select = el(id);
    if (!select) return;
    const current = select.value || '';
    const normalized = (options || []).map(option => (
      typeof option === 'string' ? { value: option, label: option } : option
    ));
    select.innerHTML = '<option value="">' + escapeHtml(emptyLabel) + '</option>'
      + normalized.map(option => '<option value="' + escapeAttr(option.value) + '">' + escapeHtml(option.label) + '</option>').join('');
    select.value = normalized.some(option => option.value === current) ? current : '';
  }

  function selectedFilterParams() {
    const params = new URLSearchParams({ period: state.filters.period });
    if (state.filters.task) params.set('task', state.filters.task);
    if (state.filters.dataset) params.set('dataset', state.filters.dataset);
    if (state.filters.version) params.set('dataset_version_id', state.filters.version);
    if (state.filters.model) params.set('model', state.filters.model);
    if (state.filters.status) params.set('status', state.filters.status);
    return params;
  }

  function availableMetrics() {
    const names = new Set();
    ((state.payload && state.payload.runs) || []).forEach(run => {
      (run.metrics || []).forEach(metric => names.add(String(metric)));
    });
    return Array.from(names).sort((a, b) => a.localeCompare(b));
  }

  function syncMetricSelection(metrics) {
    if (state.metricMode === 'all') {
      state.selectedMetrics = new Set(metrics);
    } else {
      state.selectedMetrics = new Set(Array.from(state.selectedMetrics).filter(metric => metrics.includes(metric)));
    }
  }

  function updateMetricTrigger(metrics) {
    const trigger = el('insights-metric-trigger');
    if (!trigger) return;
    const count = state.selectedMetrics.size;
    if (metrics.length && count === metrics.length) trigger.textContent = 'All metrics';
    else if (count === 1) trigger.textContent = Array.from(state.selectedMetrics)[0];
    else if (count > 1) trigger.textContent = count + ' metrics';
    else trigger.textContent = 'No metrics';
  }

  function renderMetricOptions(metrics) {
    const host = el('insights-metric-options');
    if (!host) return;
    host.innerHTML = metrics.map(metric => {
      const checked = state.selectedMetrics.has(metric) ? ' checked' : '';
      return '<div class="qym-dropdown__option" data-qym-dropdown-search-text="' + escapeAttr(metric) + '">'
        + '<label class="qym-dropdown__option-label">'
        + '<input type="checkbox" value="' + escapeAttr(metric) + '"' + checked + '>'
        + '<span class="qym-dropdown__option-text">' + escapeHtml(metric) + '</span>'
        + '</label>'
        + '<button class="qym-inline-action qym-dropdown__only" type="button" data-metric-only="' + escapeAttr(metric) + '">Only</button>'
        + '</div>';
    }).join('');
    updateMetricTrigger(metrics);
  }

  function metricSpec(run, metric) {
    return (run && run.metric_specs && run.metric_specs[metric]) || {};
  }

  function metricIsPercentage(metric, runs) {
    const specs = runs.map(run => metricSpec(run, metric)).filter(spec => spec && spec.score_type);
    if (specs.length && specs.every(spec => ['boolean', 'percentage'].includes(spec.score_type))) return true;
    if (specs.some(spec => ['count', 'number'].includes(spec.score_type))) return false;
    const values = runs
      .map(run => run.metric_averages && run.metric_averages[metric])
      .filter(value => Number.isFinite(Number(value)))
      .map(Number);
    return values.length > 0 && values.every(value => value >= 0 && value <= 1);
  }

  function metricAxis(metric, runs) {
    if (metricIsPercentage(metric, runs)) {
      return { key: 'percentage', label: 'Percentage', percentage: true, unit: '%' };
    }
    const specs = runs.map(run => metricSpec(run, metric)).filter(spec => spec && spec.score_type);
    const unit = (specs.find(spec => spec.unit) || {}).unit || '';
    const scoreType = (specs.find(spec => spec.score_type) || {}).score_type || 'number';
    return {
      key: scoreType + ':' + (unit || 'number'),
      label: unit ? 'Value · ' + unit : (scoreType === 'count' ? 'Count' : 'Numeric value'),
      percentage: false,
      unit,
    };
  }

  function formatMetricValue(value, metric, run) {
    if (!Number.isFinite(Number(value))) return '—';
    const numeric = Number(value);
    if (metricIsPercentage(metric, [run])) return (numeric * 100).toFixed(1) + '%';
    const spec = metricSpec(run, metric);
    const precision = Number.isInteger(spec.precision) ? spec.precision : (spec.score_type === 'count' ? 0 : 2);
    return numeric.toFixed(precision) + (spec.unit ? ' ' + spec.unit : '');
  }

  function formatAxisValue(value, axis) {
    if (axis.percentage) {
      const precision = axis.domainSpan < 0.2 ? 1 : 0;
      return (value * 100).toFixed(precision) + '%';
    }
    const absolute = Math.abs(value);
    let textValue;
    if (absolute >= 1000000) textValue = (value / 1000000).toFixed(1) + 'M';
    else if (absolute >= 1000) textValue = (value / 1000).toFixed(1) + 'K';
    else if (absolute >= 10) textValue = value.toFixed(1);
    else textValue = value.toFixed(2);
    return textValue + (axis.unit ? ' ' + axis.unit : '');
  }

  function formatLatency(value) {
    if (!Number.isFinite(Number(value))) return '—';
    const milliseconds = Number(value);
    return milliseconds >= 1000 ? (milliseconds / 1000).toFixed(2) + 's' : Math.round(milliseconds) + 'ms';
  }

  function formatDate(value, withTime) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '—';
    const options = { month: 'short', day: 'numeric' };
    if (withTime) {
      options.hour = '2-digit';
      options.minute = '2-digit';
    }
    return date.toLocaleString(undefined, options);
  }

  function truncateLabel(value, length) {
    const textValue = String(value || 'Run');
    return textValue.length > length ? textValue.slice(0, Math.max(1, length - 1)) + '…' : textValue;
  }

  function bucketStart(timestamp, granularity) {
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) return null;
    date.setUTCHours(0, 0, 0, 0);
    if (granularity === 'week') {
      const day = date.getUTCDay();
      date.setUTCDate(date.getUTCDate() - ((day + 6) % 7));
    }
    return date;
  }

  function aggregateTimeline(runs, granularity) {
    if (granularity === 'run') return runs;
    const buckets = new Map();
    runs.forEach(run => {
      const start = bucketStart(run.timestamp, granularity);
      if (!start) return;
      const key = start.toISOString();
      if (!buckets.has(key)) {
        buckets.set(key, {
          timestamp: key,
          run_name: granularity === 'week' ? 'Week of ' + formatDate(key, false) : formatDate(key, false),
          run_count: 0,
          total_items: 0,
          metric_averages: {},
          metric_counts: {},
          metric_specs: {},
          metrics: [],
          _metricSums: {},
        });
      }
      const bucket = buckets.get(key);
      bucket.run_count += 1;
      bucket.total_items += Number(run.total_items || 0);
      (run.metrics || []).forEach(metric => {
        const value = run.metric_averages && run.metric_averages[metric];
        if (!Number.isFinite(Number(value))) return;
        const weight = Math.max(1, Number((run.metric_counts && run.metric_counts[metric]) || 0));
        bucket._metricSums[metric] = Number(bucket._metricSums[metric] || 0) + Number(value) * weight;
        bucket.metric_counts[metric] = Number(bucket.metric_counts[metric] || 0) + weight;
        bucket.metric_specs[metric] = metricSpec(run, metric);
      });
    });
    return Array.from(buckets.values()).sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp)).map(bucket => {
      Object.keys(bucket._metricSums).forEach(metric => {
        bucket.metric_averages[metric] = bucket._metricSums[metric] / bucket.metric_counts[metric];
      });
      bucket.metrics = Object.keys(bucket.metric_averages);
      delete bucket._metricSums;
      return bucket;
    });
  }

  function limitedRuns() {
    const runs = ((state.payload && state.payload.runs) || []).slice();
    if (state.filters.runLimit === 'all') return runs;
    const limit = Math.max(1, Number(state.filters.runLimit) || 10);
    return runs.slice(-limit);
  }

  function semanticKey(run, metric) {
    const spec = metricSpec(run, metric);
    return [
      run.task_name || '', run.dataset_name || '', run.dataset_version_id || '',
      spec.score_type || '', spec.direction || 'maximize', spec.unit || '',
      spec.sample_reducer || 'mean', spec.run_reducer || 'mean'
    ].join('|||');
  }

  function lineSegments(points, metric, granularity) {
    const segments = [];
    let current = [];
    let previousKey = null;
    points.forEach((point, index) => {
      const value = point.metric_averages && point.metric_averages[metric];
      if (!Number.isFinite(Number(value))) {
        if (current.length) segments.push(current);
        current = [];
        previousKey = null;
        return;
      }
      const key = granularity === 'run' ? semanticKey(point, metric) : 'aggregate';
      if (current.length && key !== previousKey) {
        segments.push(current);
        current = [];
      }
      current.push({ point, index, value: Number(value) });
      previousKey = key;
    });
    if (current.length) segments.push(current);
    return segments;
  }

  function chartDomain(values, axis) {
    if (!values.length) return { min: 0, max: 1, span: 1 };
    const dataMin = Math.min(...values);
    const dataMax = Math.max(...values);
    const nonNegative = dataMin >= 0;

    if (state.filters.scaleMode === 'full') {
      if (axis.percentage) return { min: 0, max: 1, span: 1 };
      let min = Math.min(0, dataMin);
      let max = Math.max(0, dataMax);
      if (min === max) max = min + 1;
      const padding = (max - min) * 0.08;
      min = nonNegative ? 0 : min - padding;
      max += padding;
      return { min, max, span: max - min };
    }

    const midpoint = (dataMin + dataMax) / 2;
    const dataSpan = dataMax - dataMin;
    const minimumSpan = axis.percentage
      ? 0.04
      : Math.max(1, Math.abs(midpoint) * 0.05);
    const span = Math.max(dataSpan * 1.35, minimumSpan);
    let min = midpoint - span / 2;
    let max = midpoint + span / 2;

    if (axis.percentage) {
      min = Math.max(0, min);
      max = Math.min(1, max);
      if (max - min < minimumSpan) {
        if (min === 0) max = Math.min(1, minimumSpan);
        else if (max === 1) min = Math.max(0, 1 - minimumSpan);
      }
    } else if (nonNegative) {
      min = Math.max(0, min);
    }
    if (min === max) max = min + (axis.percentage ? 0.04 : 1);
    return { min, max, span: max - min };
  }

  function chartPanel(axis, metrics, points, colorByMetric) {
    const margin = { left: 76, right: 36, top: 30, bottom: 72 };
    const hostWidth = Math.max(760, state.chartWidth || 1000);
    const runWidth = state.filters.granularity === 'run'
      ? margin.left + margin.right + Math.max(1, points.length - 1) * 92
      : hostWidth;
    const width = Math.max(hostWidth, runWidth);
    const height = 360;
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const values = [];
    metrics.forEach(metric => points.forEach(point => {
      const value = point.metric_averages && point.metric_averages[metric];
      if (Number.isFinite(Number(value))) values.push(Number(value));
    }));

    const domain = chartDomain(values, axis);
    const minValue = domain.min;
    const maxValue = domain.max;
    const axisWithDomain = { ...axis, domainSpan: domain.span };

    const times = points.map(point => new Date(point.timestamp).getTime()).filter(Number.isFinite);
    const minTime = times.length ? Math.min(...times) : 0;
    const maxTime = times.length ? Math.max(...times) : minTime;
    const showTimeOnAxis = maxTime - minTime < 2 * 24 * 60 * 60 * 1000;
    const xFor = (point, index) => {
      if (state.filters.granularity === 'run') {
        if (points.length <= 1) return margin.left + plotWidth / 2;
        return margin.left + (index / (points.length - 1)) * plotWidth;
      }
      const time = new Date(point.timestamp).getTime();
      if (maxTime > minTime && Number.isFinite(time)) return margin.left + ((time - minTime) / (maxTime - minTime)) * plotWidth;
      if (points.length <= 1) return margin.left + plotWidth / 2;
      return margin.left + (index / (points.length - 1)) * plotWidth;
    };
    const yFor = value => margin.top + (1 - (value - minValue) / (maxValue - minValue)) * plotHeight;

    const scaleLabel = state.filters.scaleMode === 'full' ? 'Full scale' : 'Focused scale';
    const domainLabel = formatAxisValue(minValue, axisWithDomain) + '–' + formatAxisValue(maxValue, axisWithDomain);
    let svg = '<svg width="' + width + '" height="' + height + '" viewBox="0 0 ' + width + ' ' + height + '" role="img" aria-label="' + escapeAttr(axis.label + ' metric timeline, ' + scaleLabel.toLowerCase() + ' ' + domainLabel) + '">';
    svg += '<rect class="insights-plot-surface" x="' + margin.left + '" y="' + margin.top + '" width="' + plotWidth + '" height="' + plotHeight + '" rx="8"></rect>';
    const tickCount = 4;
    for (let index = 0; index <= tickCount; index += 1) {
      const ratio = index / tickCount;
      const value = maxValue - ratio * (maxValue - minValue);
      const y = margin.top + ratio * plotHeight;
      svg += '<line class="insights-grid-line" x1="' + margin.left + '" y1="' + y + '" x2="' + (width - margin.right) + '" y2="' + y + '"></line>';
      svg += '<text class="insights-axis-label" x="' + (margin.left - 10) + '" y="' + (y + 4) + '" text-anchor="end">' + escapeHtml(formatAxisValue(value, axisWithDomain)) + '</text>';
    }
    svg += '<line class="insights-axis-line" x1="' + margin.left + '" y1="' + (height - margin.bottom) + '" x2="' + (width - margin.right) + '" y2="' + (height - margin.bottom) + '"></line>';

    const xTickCount = Math.min(state.filters.granularity === 'run' ? 10 : 6, points.length);
    const usedTicks = new Set();
    for (let tick = 0; tick < xTickCount; tick += 1) {
      const pointIndex = xTickCount === 1 ? 0 : Math.round((tick / (xTickCount - 1)) * (points.length - 1));
      if (usedTicks.has(pointIndex)) continue;
      usedTicks.add(pointIndex);
      const point = points[pointIndex];
      const x = xFor(point, pointIndex);
      svg += '<line class="insights-run-guide" x1="' + x + '" y1="' + margin.top + '" x2="' + x + '" y2="' + (height - margin.bottom) + '"></line>';
      svg += '<line class="insights-axis-line" x1="' + x + '" y1="' + (height - margin.bottom) + '" x2="' + x + '" y2="' + (height - margin.bottom + 5) + '"></line>';
      if (state.filters.granularity === 'run') {
        svg += '<text class="insights-axis-label insights-axis-run-label" x="' + x + '" y="' + (height - 38) + '" text-anchor="middle">'
          + '<tspan x="' + x + '">' + escapeHtml(truncateLabel(point.run_name, 16)) + '</tspan>'
          + '<tspan class="insights-axis-run-meta" x="' + x + '" dy="16">' + escapeHtml(formatDate(point.timestamp, showTimeOnAxis)) + '</tspan>'
          + '</text>';
      } else {
        svg += '<text class="insights-axis-label" x="' + x + '" y="' + (height - 24) + '" text-anchor="middle">' + escapeHtml(formatDate(point.timestamp, false)) + '</text>';
      }
    }

    metrics.forEach(metric => {
      const color = colorByMetric[metric];
      const segments = lineSegments(points, metric, state.filters.granularity);
      const metricEntries = segments.flat();
      const latestMetricEntry = metricEntries[metricEntries.length - 1];
      segments.forEach(segment => {
        if (segment.length > 1) {
          const path = segment.map((entry, index) => (index ? 'L' : 'M') + xFor(entry.point, entry.index).toFixed(2) + ' ' + yFor(entry.value).toFixed(2)).join(' ');
          svg += '<path class="insights-series-glow" data-series-metric="' + escapeAttr(metric) + '" style="--insights-line-color:' + color + '" d="' + path + '"></path>';
          svg += '<path class="insights-series-line" data-series-metric="' + escapeAttr(metric) + '" style="--insights-line-color:' + color + '" d="' + path + '"></path>';
        }
        segment.forEach((entry, entryIndex) => {
          const pointId = 'insights-point-' + (++state.pointSequence);
          const runCount = entry.point.run_count || 1;
          const previousEntry = entryIndex > 0 ? segment[entryIndex - 1] : null;
          const change = previousEntry ? entry.value - previousEntry.value : null;
          const changeText = Number.isFinite(change)
            ? (axis.percentage
              ? (change >= 0 ? '+' : '') + (change * 100).toFixed(1) + ' pp from previous shown run'
              : (change >= 0 ? '+' : '') + change.toFixed(2) + ' from previous shown run')
            : '';
          const pointX = xFor(entry.point, entry.index).toFixed(2);
          const pointY = yFor(entry.value).toFixed(2);
          const latestClass = entry === latestMetricEntry ? ' is-latest' : '';
          if (latestClass) {
            svg += '<circle class="insights-series-halo" data-series-metric="' + escapeAttr(metric) + '" style="--insights-line-color:' + color + '" cx="' + pointX + '" cy="' + pointY + '" r="10"></circle>';
          }
          svg += '<circle id="' + pointId + '" class="insights-series-point' + latestClass + '" data-series-metric="' + escapeAttr(metric) + '" style="--insights-line-color:' + color + '" '
            + 'cx="' + pointX + '" cy="' + pointY + '" r="4.5" '
            + 'data-run-name="' + escapeAttr(entry.point.run_name || '') + '" '
            + 'data-run-count="' + escapeAttr(runCount) + '" data-metric="' + escapeAttr(metric) + '" '
            + 'data-value="' + escapeAttr(formatMetricValue(entry.value, metric, entry.point)) + '" '
            + 'data-change="' + escapeAttr(changeText) + '" data-run-position="' + (entry.index + 1) + ' of ' + points.length + '" '
            + 'data-timestamp="' + escapeAttr(entry.point.timestamp || '') + '" '
            + 'data-model="' + escapeAttr(entry.point.model_name || '') + '" data-dataset="' + escapeAttr(entry.point.dataset_name || '') + '">'
            + '<title>' + escapeHtml((entry.point.run_name || formatDate(entry.point.timestamp, false)) + ' · ' + metric + ' · ' + formatMetricValue(entry.value, metric, entry.point)) + '</title>'
            + '</circle>';
        });
      });
    });
    svg += '</svg>';
    return '<div class="insights-chart-panel">'
      + '<div class="insights-chart-panel-header"><span>' + escapeHtml(axis.label) + ' <span class="qym-tag qym-tag--data insights-scale-tag">' + escapeHtml(scaleLabel) + '</span></span>'
      + '<span>' + metrics.length + ' metric' + (metrics.length === 1 ? '' : 's') + ' · ' + escapeHtml(domainLabel) + '</span></div>'
      + '<div class="insights-chart-scroll">' + svg + '</div>'
      + '<div class="insights-tooltip" role="tooltip"></div>'
      + '</div>';
  }

  function attachPointInteractions() {
    document.querySelectorAll('.insights-series-point').forEach(point => {
      const panel = point.closest('.insights-chart-panel');
      const tooltip = panel && panel.querySelector('.insights-tooltip');
      if (!panel || !tooltip) return;

      const show = event => {
        const runCount = Number(point.dataset.runCount || 1);
        const title = runCount > 1 ? runCount + ' runs · ' + formatDate(point.dataset.timestamp, false) : (point.dataset.runName || 'Run');
        tooltip.innerHTML = '<div class="insights-tooltip-title">' + escapeHtml(title) + '</div>'
          + '<div class="insights-tooltip-kicker">Run ' + escapeHtml(point.dataset.runPosition || '') + '</div>'
          + '<div class="insights-tooltip-row"><span>' + escapeHtml(point.dataset.metric) + '</span><span class="insights-tooltip-value">' + escapeHtml(point.dataset.value) + '</span></div>'
          + (point.dataset.change ? '<div class="insights-tooltip-change">' + escapeHtml(point.dataset.change) + '</div>' : '')
          + (point.dataset.model ? '<div class="insights-tooltip-row"><span>Model</span><span class="insights-tooltip-value">' + escapeHtml(point.dataset.model) + '</span></div>' : '')
          + (point.dataset.dataset ? '<div class="insights-tooltip-row"><span>Dataset</span><span class="insights-tooltip-value">' + escapeHtml(point.dataset.dataset) + '</span></div>' : '')
          + '<div class="insights-tooltip-row"><span>Time</span><span class="insights-tooltip-value">' + escapeHtml(formatDate(point.dataset.timestamp, true)) + '</span></div>';
        tooltip.classList.add('is-visible');
        const panelRect = panel.getBoundingClientRect();
        const pointRect = point.getBoundingClientRect();
        const requestedLeft = event && Number.isFinite(event.clientX) ? event.clientX - panelRect.left : pointRect.left - panelRect.left;
        const maxLeft = Math.max(8, panelRect.width - tooltip.offsetWidth - 8);
        tooltip.style.left = Math.max(8, Math.min(requestedLeft + 12, maxLeft)) + 'px';
        tooltip.style.top = Math.max(8, pointRect.top - panelRect.top - tooltip.offsetHeight - 10) + 'px';
      };
      const hide = () => tooltip.classList.remove('is-visible');
      point.addEventListener('pointerenter', show);
      point.addEventListener('pointermove', show);
      point.addEventListener('pointerleave', hide);
    });
  }

  function emphasizeSeries(metric) {
    document.querySelectorAll('[data-series-metric]').forEach(node => {
      const matches = node.dataset.seriesMetric === metric;
      node.classList.toggle('is-emphasized', Boolean(metric) && matches);
      node.classList.toggle('is-deemphasized', Boolean(metric) && !matches);
    });
  }

  function renderLegend(metrics, colorByMetric) {
    const legend = el('insights-legend');
    if (!legend) return;
    const metricsKey = metrics.join('\u0000');
    if (legend.dataset.metricsKey !== metricsKey) {
      legend.innerHTML = '<span class="insights-legend-label">Quick metric switch</span>'
        + '<button class="insights-legend-item insights-legend-all" type="button" data-legend-all aria-pressed="false" style="--insights-line-color:var(--accent-primary)">All metrics</button>'
        + metrics.map(metric => '<button class="insights-legend-item" type="button" data-legend-metric="' + escapeAttr(metric) + '" aria-pressed="false" title="Focus ' + escapeAttr(metric) + '">'
          + '<span class="insights-legend-swatch" style="--insights-line-color:' + colorByMetric[metric] + '"></span>'
          + escapeHtml(metric)
          + '</button>').join('');
      legend.dataset.metricsKey = metricsKey;
    }
    const allSelected = metrics.length > 0 && state.selectedMetrics.size === metrics.length;
    const allButton = legend.querySelector('[data-legend-all]');
    if (allButton) {
      allButton.classList.toggle('is-selected', allSelected);
      allButton.setAttribute('aria-pressed', allSelected ? 'true' : 'false');
    }
    legend.querySelectorAll('[data-legend-metric]').forEach(button => {
      const selected = state.selectedMetrics.has(button.dataset.legendMetric);
      button.classList.toggle('is-selected', selected);
      button.setAttribute('aria-pressed', selected ? 'true' : 'false');
    });
  }

  function compatiblePrevious(runs, latest, metric) {
    const latestIndex = runs.indexOf(latest);
    const latestSpecKey = metric ? semanticKey(latest, metric) : [latest.task_name, latest.dataset_name, latest.dataset_version_id || ''].join('|||');
    for (let index = latestIndex - 1; index >= 0; index -= 1) {
      const candidate = runs[index];
      const candidateKey = metric ? semanticKey(candidate, metric) : [candidate.task_name, candidate.dataset_name, candidate.dataset_version_id || ''].join('|||');
      if (candidateKey !== latestSpecKey) continue;
      if (metric && !Number.isFinite(Number(candidate.metric_averages && candidate.metric_averages[metric]))) continue;
      return candidate;
    }
    return null;
  }

  function deltaClass(delta, direction) {
    if (!Number.isFinite(delta) || Math.abs(delta) < 0.0000001) return 'is-neutral';
    const improved = direction === 'minimize' ? delta < 0 : delta > 0;
    return improved ? 'is-positive' : 'is-negative';
  }

  function setMeta(id, textValue, className, titleValue) {
    const target = el(id);
    if (!target) return;
    target.textContent = textValue;
    target.title = titleValue || textValue;
    target.className = 'qym-stat-strip__meta insights-stat-delta ' + (className || 'is-neutral');
  }

  function sameRunCohort(first, second) {
    return [first.task_name, first.dataset_name, first.dataset_version_id || ''].join('|||')
      === [second.task_name, second.dataset_name, second.dataset_version_id || ''].join('|||');
  }

  function metricSummaryLabel(metrics) {
    if (metrics.length === 1) return metrics[0];
    if (state.metricMode === 'all') return 'All metrics average';
    return 'Selected metrics average';
  }

  function metricAverageForRun(run, metrics) {
    if (!run || !metrics.length) return null;
    const values = metrics.map(metric => run.metric_averages && run.metric_averages[metric]);
    if (values.some(value => !Number.isFinite(Number(value)))) return null;
    const axes = metrics.map(metric => metricAxis(metric, [run]));
    if (new Set(axes.map(axis => axis.key)).size > 1) {
      return { mixedUnits: true, metrics };
    }
    return {
      mixedUnits: false,
      axis: axes[0],
      metrics,
      value: values.reduce((sum, value) => sum + Number(value), 0) / values.length,
    };
  }

  function compatiblePreviousForMetrics(runs, latest, metrics) {
    const latestIndex = runs.indexOf(latest);
    for (let index = latestIndex - 1; index >= 0; index -= 1) {
      const candidate = runs[index];
      if (!sameRunCohort(candidate, latest)) continue;
      const compatible = metrics.every(metric => (
        Number.isFinite(Number(candidate.metric_averages && candidate.metric_averages[metric]))
        && semanticKey(candidate, metric) === semanticKey(latest, metric)
      ));
      if (compatible) return candidate;
    }
    return null;
  }

  function metricSummaryForRuns(runs) {
    const metrics = Array.from(state.selectedMetrics);
    if (!metrics.length) return { metrics, latest: null, average: null, previous: null, previousAverage: null };
    const latest = [...runs].reverse().find(run => metricAverageForRun(run, metrics));
    if (!latest) return { metrics, latest: null, average: null, previous: null, previousAverage: null };
    const average = metricAverageForRun(latest, metrics);
    if (!average || average.mixedUnits) return { metrics, latest, average, previous: null, previousAverage: null };
    const previous = compatiblePreviousForMetrics(runs, latest, metrics);
    const previousAverage = previous ? metricAverageForRun(previous, metrics) : null;
    return { metrics, latest, average, previous, previousAverage };
  }

  function formatMetricAverage(summary) {
    if (!summary || !summary.average || summary.average.mixedUnits) return '—';
    const { average, latest, metrics } = summary;
    if (average.axis.percentage) return (average.value * 100).toFixed(1) + '%';
    return formatMetricValue(average.value, metrics[0], latest);
  }

  function summaryDirection(summary) {
    const directions = new Set(summary.metrics.map(metric => metricSpec(summary.latest, metric).direction || 'maximize'));
    return directions.size === 1 ? Array.from(directions)[0] : null;
  }

  function renderStats(runs) {
    const metricSummary = metricSummaryForRuns(runs);
    el('insights-metric-summary-label').textContent = metricSummaryLabel(metricSummary.metrics);
    if (metricSummary.latest && metricSummary.average && !metricSummary.average.mixedUnits) {
      el('insights-metric-summary-value').textContent = formatMetricAverage(metricSummary);
      const averagePrefix = metricSummary.metrics.length > 1
        ? 'Unweighted average of ' + metricSummary.metrics.length + ' selected metrics'
        : metricSummary.metrics[0];
      if (metricSummary.previous && metricSummary.previousAverage) {
        const delta = metricSummary.average.value - metricSummary.previousAverage.value;
        const deltaText = metricSummary.average.axis.percentage
          ? (delta >= 0 ? '+' : '') + (delta * 100).toFixed(1) + ' pp'
          : (delta >= 0 ? '+' : '') + delta.toFixed(2);
        const direction = summaryDirection(metricSummary);
        const comparisonText = deltaText + ' vs ' + metricSummary.previous.run_name;
        setMeta(
          'insights-metric-summary-meta',
          comparisonText,
          direction ? deltaClass(delta, direction) : 'is-neutral',
          averagePrefix + ' · ' + comparisonText
        );
      } else {
        setMeta('insights-metric-summary-meta', averagePrefix + ' · no comparable predecessor', 'is-neutral');
      }
    } else if (metricSummary.average && metricSummary.average.mixedUnits) {
      el('insights-metric-summary-value').textContent = '—';
      setMeta('insights-metric-summary-meta', 'Mixed metric units cannot be averaged fairly', 'is-neutral');
    } else {
      el('insights-metric-summary-value').textContent = '—';
      setMeta('insights-metric-summary-meta', state.selectedMetrics.size ? 'No run contains every selected metric' : 'Select a metric', 'is-neutral');
    }

    const latest = runs.length ? runs[runs.length - 1] : null;
    const previous = latest ? compatiblePrevious(runs, latest, null) : null;
    if (latest && Number.isFinite(Number(latest.success_rate))) {
      const value = Number(latest.success_rate);
      el('insights-reliability').textContent = (value * 100).toFixed(1) + '%';
      if (previous && Number.isFinite(Number(previous.success_rate))) {
        const delta = value - Number(previous.success_rate);
        setMeta('insights-reliability-meta', (delta >= 0 ? '+' : '') + (delta * 100).toFixed(1) + ' pp vs ' + previous.run_name, deltaClass(delta, 'maximize'));
      } else setMeta('insights-reliability-meta', 'No comparable predecessor', 'is-neutral');
    } else {
      el('insights-reliability').textContent = '—';
      setMeta('insights-reliability-meta', 'No completed items', 'is-neutral');
    }

    if (latest && Number.isFinite(Number(latest.median_latency_ms))) {
      const value = Number(latest.median_latency_ms);
      el('insights-latency').textContent = formatLatency(value);
      if (previous && Number(previous.median_latency_ms) > 0) {
        const relative = (value - Number(previous.median_latency_ms)) / Number(previous.median_latency_ms);
        setMeta('insights-latency-meta', (relative >= 0 ? '+' : '') + (relative * 100).toFixed(1) + '% vs ' + previous.run_name, deltaClass(relative, 'minimize'));
      } else setMeta('insights-latency-meta', 'No comparable predecessor', 'is-neutral');
    } else {
      el('insights-latency').textContent = '—';
      setMeta('insights-latency-meta', 'No latency data', 'is-neutral');
    }

    const totalItems = runs.reduce((sum, run) => sum + Number(run.total_items || 0), 0);
    el('insights-items').textContent = totalItems.toLocaleString();
    if (latest && previous && Number(previous.total_items) > 0) {
      const relative = (Number(latest.total_items || 0) - Number(previous.total_items)) / Number(previous.total_items);
      setMeta('insights-items-meta', (relative >= 0 ? '+' : '') + (relative * 100).toFixed(1) + '% in latest run · ' + runs.length + ' shown', 'is-neutral');
    } else setMeta('insights-items-meta', 'Across ' + runs.length + ' shown run' + (runs.length === 1 ? '' : 's'), 'is-neutral');
  }

  function comparisonStatement(label, textValue) {
    return '<div class="insights-comparison-item"><strong>' + escapeHtml(label) + '</strong><br>' + escapeHtml(textValue) + '</div>';
  }

  function renderComparison(runs) {
    const host = el('insights-comparison');
    if (!host) return;
    if (runs.length < 2) {
      host.innerHTML = comparisonStatement('Comparison', 'At least two comparable runs are needed for change insights.');
      return;
    }
    const latest = runs[runs.length - 1];
    const previous = compatiblePrevious(runs, latest, null);
    const metricSummary = metricSummaryForRuns(runs);
    const statements = [];
    if (metricSummary.average && !metricSummary.average.mixedUnits && metricSummary.previousAverage) {
      const delta = metricSummary.average.value - metricSummary.previousAverage.value;
      const direction = summaryDirection(metricSummary);
      const outcome = Math.abs(delta) < 0.0000001
        ? 'was unchanged'
        : (direction ? (deltaClass(delta, direction) === 'is-positive' ? 'improved' : 'regressed') : 'changed');
      const amount = metricSummary.average.axis.percentage
        ? Math.abs(delta * 100).toFixed(1) + ' percentage points'
        : Math.abs(delta).toFixed(2);
      const label = metricSummaryLabel(metricSummary.metrics);
      const subject = metricSummary.metrics.length > 1
        ? 'The unweighted average of ' + metricSummary.metrics.length + ' selected metrics'
        : metricSummary.metrics[0];
      statements.push(comparisonStatement(label, subject + ' ' + outcome + (Math.abs(delta) ? ' by ' + amount : '') + ' versus ' + metricSummary.previous.run_name + '.'));
    }
    if (previous && Number.isFinite(Number(latest.success_rate)) && Number.isFinite(Number(previous.success_rate))) {
      const delta = (Number(latest.success_rate) - Number(previous.success_rate)) * 100;
      statements.push(comparisonStatement('Reliability', 'Execution reliability changed by ' + (delta >= 0 ? '+' : '') + delta.toFixed(1) + ' percentage points versus ' + previous.run_name + '.'));
    }
    if (previous && Number(previous.median_latency_ms) > 0 && Number.isFinite(Number(latest.median_latency_ms))) {
      const delta = (Number(latest.median_latency_ms) - Number(previous.median_latency_ms)) / Number(previous.median_latency_ms) * 100;
      statements.push(comparisonStatement('Performance', 'Median latency changed by ' + (delta >= 0 ? '+' : '') + delta.toFixed(1) + '% versus ' + previous.run_name + '.'));
    }
    if (!statements.length) statements.push(comparisonStatement('Comparison', 'The latest run has no compatible predecessor for the visible data.'));
    host.innerHTML = statements.slice(0, 3).join('');
  }

  function renderChart() {
    const chart = el('insights-chart');
    if (!chart || !state.payload) return;
    const measuredWidth = Math.round(chart.clientWidth || 0);
    if (measuredWidth > 0) state.chartWidth = measuredWidth;
    const filteredRuns = state.payload.runs || [];
    const runs = limitedRuns();
    const allMetrics = availableMetrics();
    const legendMetrics = state.legendMetrics.length ? state.legendMetrics : allMetrics;
    const allSelected = Array.from(state.selectedMetrics);
    const visibleMetrics = allSelected;
    renderStats(runs);
    renderComparison(runs);

    const countLabel = state.payload.total_count + ' run' + (state.payload.total_count === 1 ? '' : 's');
    el('insights-run-count').textContent = countLabel;
    const shownLabel = runs.length === filteredRuns.length
      ? runs.length + ' run' + (runs.length === 1 ? '' : 's') + ' shown'
      : runs.length + ' of ' + filteredRuns.length + ' filtered runs shown';
    const metaParts = [shownLabel, allSelected.length + ' selected metric' + (allSelected.length === 1 ? '' : 's')];
    if (state.payload.truncated) metaParts.push('latest 500 available');
    const cohortKeys = new Set(runs.map(run => [run.task_name, run.dataset_name, run.dataset_version_id || ''].join('|||')));
    if (cohortKeys.size > 1 && state.filters.granularity === 'run') metaParts.push('mixed cohorts separated');
    el('insights-chart-meta').textContent = metaParts.join(' · ');
    el('insights-chart-copy').textContent = state.filters.granularity === 'run'
      ? 'Every run is evenly spaced from oldest to latest, even when timestamps match.'
      : 'Runs are aggregated by ' + (state.filters.granularity === 'day' ? 'day' : 'week') + ' from oldest to latest.';

    const colorByMetric = {};
    legendMetrics.forEach((metric, index) => { colorByMetric[metric] = chartColors[index % chartColors.length]; });
    renderLegend(legendMetrics, colorByMetric);

    if (!runs.length) {
      chart.innerHTML = '<div class="insights-empty">No completed runs match these filters.</div>';
      return;
    }
    if (!allSelected.length) {
      chart.innerHTML = '<div class="insights-empty">Choose one or more metrics to draw the timeline.</div>';
      return;
    }
    const points = aggregateTimeline(runs, state.filters.granularity);
    state.pointSequence = 0;
    const axisGroups = new Map();
    visibleMetrics.forEach(metric => {
      const axis = metricAxis(metric, runs);
      if (!axisGroups.has(axis.key)) axisGroups.set(axis.key, { axis, metrics: [] });
      axisGroups.get(axis.key).metrics.push(metric);
    });
    chart.innerHTML = Array.from(axisGroups.values()).map(group => chartPanel(group.axis, group.metrics, points, colorByMetric)).join('');
    attachPointInteractions();
  }

  function applyFacets() {
    const facets = (state.payload && state.payload.facets) || {};
    populateSelect('insights-task', facets.tasks, 'All tasks');
    populateSelect('insights-dataset', facets.datasets, 'All datasets');
    populateSelect('insights-version', facets.dataset_versions, 'All versions');
    populateSelect('insights-model', facets.models, 'All models');
    populateSelect('insights-status', facets.statuses, 'All statuses');
    applyControlValues();
  }

  async function loadInsights() {
    if (!state.projectSlug) return;
    el('insights-chart-meta').textContent = 'Loading insights…';
    try {
      const response = await fetch(apiUrl('api/projects/' + encodeURIComponent(state.projectSlug) + '/insights?' + selectedFilterParams().toString()));
      if (!response.ok) throw new Error('Insights request failed (' + response.status + ')');
      state.payload = await response.json();
      applyFacets();
      const metrics = availableMetrics();
      state.legendMetrics = metrics.slice();
      syncMetricSelection(metrics);
      renderMetricOptions(metrics);
      renderChart();
      savePreferences();
    } catch (error) {
      console.error('[Insights] Failed to load:', error);
      el('insights-chart').innerHTML = '<div class="insights-empty insights-error">Insights could not be loaded.</div>';
      el('insights-chart-meta').textContent = 'Unavailable';
    }
  }

  function setMetricSelection(metrics, mode) {
    state.metricMode = mode;
    state.selectedMetrics = new Set(metrics);
    renderMetricOptions(availableMetrics());
    savePreferences();
    renderChart();
  }

  function bindControls() {
    const filterControls = {
      'insights-period': 'period',
      'insights-task': 'task',
      'insights-dataset': 'dataset',
      'insights-version': 'version',
      'insights-model': 'model',
      'insights-status': 'status',
    };
    Object.entries(filterControls).forEach(([id, key]) => {
      el(id).addEventListener('change', event => {
        state.filters[key] = event.target.value;
        savePreferences();
        loadInsights();
      });
    });
    [
      ['insights-granularity', 'granularity'],
      ['insights-run-limit', 'runLimit'],
      ['insights-scale-mode', 'scaleMode'],
    ].forEach(([id, key]) => {
      el(id).addEventListener('change', event => {
        state.filters[key] = event.target.value;
        savePreferences();
        renderChart();
      });
    });
    el('insights-reset').addEventListener('click', () => {
      state.filters = {
        period: '30d', task: '', dataset: '', version: '', model: '', status: '',
        granularity: 'run', runLimit: '10', scaleMode: 'focus',
      };
      state.metricMode = 'all';
      state.selectedMetrics.clear();
      applyControlValues();
      loadInsights();
    });
    el('insights-metric-options').addEventListener('change', event => {
      if (!event.target.matches('input[type="checkbox"]')) return;
      const metric = event.target.value;
      if (event.target.checked) state.selectedMetrics.add(metric);
      else state.selectedMetrics.delete(metric);
      state.metricMode = state.selectedMetrics.size === availableMetrics().length ? 'all' : 'custom';
      updateMetricTrigger(availableMetrics());
      savePreferences();
      renderChart();
    });
    el('insights-metric-options').addEventListener('click', event => {
      const only = event.target.closest('[data-metric-only]');
      if (!only) return;
      setMetricSelection([only.dataset.metricOnly], 'custom');
    });
    el('insights-metric-all').addEventListener('click', () => {
      setMetricSelection(availableMetrics(), 'all');
    });
    el('insights-metric-none').addEventListener('click', () => {
      setMetricSelection([], 'custom');
    });
    el('insights-legend').addEventListener('click', event => {
      const all = event.target.closest('[data-legend-all]');
      if (all) {
        setMetricSelection(availableMetrics(), 'all');
        return;
      }
      const item = event.target.closest('[data-legend-metric]');
      if (!item) return;
      setMetricSelection([item.dataset.legendMetric], 'custom');
    });
    el('insights-legend').addEventListener('pointerover', event => {
      const item = event.target.closest('[data-legend-metric]');
      emphasizeSeries(item ? item.dataset.legendMetric : '');
    });
    el('insights-legend').addEventListener('pointerleave', () => emphasizeSeries(''));
  }

  async function init() {
    if (!el('insights-card')) return;
    if (window.QymShell && !window.__QYM_USER__) {
      await new Promise(resolve => document.addEventListener('qym:shell-ready', resolve, { once: true }));
    }
    const context = window.QymShell ? window.QymShell.getPageContext() : {};
    const project = window.QymShell ? window.QymShell.getProject() : null;
    state.projectSlug = context.projectSlug || (project && project.slug) || '';
    if (!state.projectSlug) {
      el('insights-chart').innerHTML = '<div class="insights-empty">Choose a project to view Insights.</div>';
      return;
    }
    loadPreferences();
    bindControls();
    applyControlValues();
    await loadInsights();
    if ('ResizeObserver' in window) {
      let resizeTimer = null;
      const chart = el('insights-chart');
      const observer = new ResizeObserver(entries => {
        const width = Math.round(entries[0] && entries[0].contentRect.width || 0);
        if (!width || Math.abs(width - state.chartWidth) < 2) return;
        state.chartWidth = width;
        window.clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(renderChart, 80);
      });
      observer.observe(chart);
    }
  }

  init().catch(error => {
    console.error('[Insights] Initialization failed:', error);
    if (el('insights-chart')) el('insights-chart').innerHTML = '<div class="insights-empty insights-error">Insights could not be initialized.</div>';
  });
})();
