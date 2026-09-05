// Synthetic CPU and asset benchmarks. No DOM, network, credentials, or service access.
// Usage: node bench_frontend.cjs /path/to/qym
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const zlib = require('zlib');
const root = process.argv[2] || process.cwd();
const assets = path.join(root, 'packages/platform/qym_platform/_static/dashboard');
global.window = {};
vm.runInThisContext(fs.readFileSync(path.join(assets, 'metrics.js'), 'utf8'));
function extract(source, name, indent) {
  const prefix = ' '.repeat(indent);
  const start = source.indexOf(prefix + 'function ' + name + '(');
  if (start < 0) throw Error(name);
  return source.slice(start, source.indexOf('\n' + prefix + '}', start) + indent + 2);
}
const compare = fs.readFileSync(path.join(assets, 'compare.html'), 'utf8');
for (const f of ['getRowCompareId', 'findRowByCompareId']) vm.runInThisContext(extract(compare, f, 6));
const dashboard = fs.readFileSync(path.join(assets, 'dashboard.js'), 'utf8');
for (const f of ['hasReasoningTraceStats', 'runHasReasoning', 'getModelVariantKey', 'parseModelVariantKey', 'getRunModelKey', 'compareModelVariantKeys', 'stripModelProvider', 'flattenRuns', 'computeAggregations', 'computeChartData', '_mergeTasksData', '_cloneRunsData', '_mergePagedRefreshData']) vm.runInThisContext(extract(dashboard, f, 2));
function median(values) { return +values.sort((a, b) => a - b)[Math.floor(values.length / 2)].toFixed(2); }
function benchLookup(items, runs = 2) {
  const snapshots = Array.from({ length: runs }, (_, r) => Array.from({ length: items }, (_, i) => ({ compare_item_id: `item-${i}`, metric_values: [(i + r) % 2] })));
  const ids = snapshots[0].map(row => row.compare_item_id);
  const existing = [], indexed = [];
  let checksum = 0;
  for (let sample = 0; sample < 3; sample++) {
    let t = performance.now();
    for (const id of ids) { const rows = snapshots.map(rs => findRowByCompareId(rs, id)); checksum += rows[0].metric_values[0]; }
    existing.push(performance.now() - t);
    t = performance.now();
    const indices = snapshots.map(rs => new Map(rs.map(row => [getRowCompareId(row), row])));
    for (const id of ids) { const rows = indices.map(idx => idx.get(id) || null); checksum += rows[0].metric_values[0]; }
    indexed.push(performance.now() - t);
  }
  return { items, runs, exact_lookup_median_ms: median(existing), map_build_and_lookup_median_ms: median(indexed), row_checks_per_scan: runs * items * (items + 1) / 2, checksum };
}
function benchModels(items, runs = 5) {
  const runsData = Array.from({ length: runs }, (_, r) => ({ run: { run_id: 'run-' + r }, snapshot: { metric_names: ['score'], rows: Array.from({ length: items }, (_, i) => ({ index: i, item_id: 'item-' + i, status: 'completed', metric_values: [(i + r) % 2], latency_ms: 100 })) } }));
  const samples = []; let result;
  for (let sample = 0; sample < 3; sample++) {
    const t = performance.now();
    result = calculateItemLevelMetrics({ runsData, metricName: 'score', threshold: 0.8, getMetricIndex: () => 0, getItemId: row => row.item_id });
    samples.push(performance.now() - t);
  }
  return { items, runs, exact_calculateItemLevelMetrics_median_ms: median(samples), totalItems: result.totalItems };
}
function summaryData(n) {
  const runs = [];
  for (let i = 0; i < n; i++) runs.push({ run_id: 'run-' + i, run_name: 'Experiment ' + i, external_run_id: 'evaluation-' + i, model_name: 'provider/model', dataset_name: 'benchmark', timestamp: new Date(1750000000000 + i * 1000).toISOString(), file_path: 'run-' + i, metrics: ['accuracy', 'f1', 'groundedness', 'helpfulness', 'exact_match'], metric_specs: { accuracy: { score_type: 'percentage', pass_threshold: 0.8 } }, metric_averages: { accuracy: 0.85, f1: 0.71, groundedness: 0.9, helpfulness: 0.88, exact_match: 0.61 }, total_items: 1000, success_count: 998, error_count: 2, total_retries: 1, success_rate: 0.998, avg_latency_ms: 1000, median_latency_ms: 900, status: 'COMPLETED', samples: 1, git_branch: 'main', git_commit: 'a'.repeat(40), owner: { id: 'owner-id', display_name: 'Synthetic User' }, run_config: {}, trace_stats: { total_tokens: 123456, input_tokens: 120000, output_tokens: 3456, reasoning_tokens: 0 } });
  return { tasks: { task: { model: runs } }, total_count: n, last_updated: new Date().toISOString() };
}
function benchDashboard(n) {
  const old = summaryData(n), incoming = summaryData(100); incoming.total_count = n;
  const samples = []; let bytes;
  for (let sample = 0; sample < 5; sample++) {
    const t = performance.now();
    const merged = _mergePagedRefreshData(old, incoming);
    const flat = flattenRuns(merged).runs;
    computeAggregations(flat); computeChartData(flat);
    const cache = JSON.stringify({ saved_at: Date.now(), data: merged }); bytes = Buffer.byteLength(cache);
    flat.sort((a, b) => b._date - a._date); computeChartData(flat);
    samples.push(performance.now() - t);
  }
  return { runs: n, summary_json_bytes: bytes, processing_median_ms: median(samples) };
}
function assetSizes() {
  const pages = { dashboard: ['index.html', 'dashboard.css', 'shell.css', 'auth.js', 'shell.js', 'ui_components.css', 'metrics.js', 'qym_table.js', 'dashboard.js'], run: ['run.html', 'dashboard.css', 'shell.css', 'auth.js', 'shell.js', 'metrics.js', 'trace_viewer.js', 'ui_components.css', 'ui_components.js'] };
  return Object.entries(pages).map(([page, files]) => {
    let raw_bytes = 0, gzip_bytes = 0;
    for (const file of files) { const data = fs.readFileSync(path.join(assets, file)); raw_bytes += data.length; gzip_bytes += zlib.gzipSync(data).length; }
    return { page, files, raw_bytes, gzip_bytes, reduction_percent: +(100 * (1 - gzip_bytes / raw_bytes)).toFixed(1) };
  });
}
benchLookup(500); benchModels(100, 2); benchDashboard(100);
console.log(JSON.stringify({ node: process.version, generated_at: new Date().toISOString(), scope: 'Synthetic exact-source CPU benchmarks; excludes browser DOM/layout, real DB/network latency, storage writes and production load. Lookup uses actual helper plus matching caller loop. Dashboard executes exact merge, flatten, aggregation, both chart-data passes, sort and cache JSON serialization; excludes filter/dropdown processing. Medians: lookup/models 3 samples; dashboard 5 samples. Map alternative includes building indexes. Asset gzip is hypothetical byte comparison, not a deployment response measurement.', lookup: [benchLookup(1000), benchLookup(5000), benchLookup(10000)], models: [benchModels(1000), benchModels(5000), benchModels(10000)], dashboard: [benchDashboard(1000), benchDashboard(10000), benchDashboard(50000)], assets: assetSizes() }, null, 2));
