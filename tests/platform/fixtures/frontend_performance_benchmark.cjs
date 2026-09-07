// Reproducible CPU comparison against a fixed pre-optimization revision.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { execFileSync } = require('node:child_process');
const assert = require('node:assert/strict');
const { performance } = require('node:perf_hooks');
const repo = process.argv[2];
const baseline = process.argv[3] || 'b1d1d00587df4fcf0e70875c29b0bb0cbc20172c';
const assetRoot = 'packages/platform/qym_platform/_static/dashboard/';
function context(original) {
  const read = name => original
    ? execFileSync('git', ['show', baseline + ':' + assetRoot + name], { cwd: repo, encoding: 'utf8' })
    : fs.readFileSync(path.join(repo, assetRoot, name), 'utf8');
  const compare = read('compare.html');
  const start = compare.indexOf('      function getRowCompareId(');
  const helpers = compare.slice(start, compare.indexOf('      function canRenderItemComparison(', start));
  // Both implementations run in this realm with separate lexical scopes, so
  // VM global-proxy lookup overhead cannot dominate the old inner loop.
  return vm.runInThisContext('(function () { const window = {};\n' + read('metrics.js') + '\n' + helpers +
    '\nreturn {calculateItemLevelMetrics, findRowByCompareId, invalidateComparisonRowIndex: typeof invalidateComparisonRowIndex === "function" ? invalidateComparisonRowIndex : null}; })()');
}
const before = context(true), after = context(false);
const median = times => +times.sort((a, b) => a - b)[Math.floor(times.length / 2)].toFixed(3);
function rows(n, k) {
  return Array.from({ length: k }, (_, run) => ({ run: { run_id: 'run-' + run }, snapshot: {
    metric_names: ['score'], rows: Array.from({ length: n }, (_, i) => ({ index: i,
      item_id: 'item-' + i, compare_item_id: 'item-' + i, status: 'completed',
      metric_values: [(i + run) % 2], latency_ms: 100,
    })),
  } }));
}
function measureModels(n, k) {
  const runs = rows(n, k), results = [], timings = [];
  for (const ctx of [before, after]) {
    const samples = [];
    for (let i = 0; i < 3; i++) {
      const start = performance.now();
      const result = ctx.calculateItemLevelMetrics({ runsData: runs, metricName: 'score', threshold: .8,
        getMetricIndex: () => 0, getItemId: row => row.item_id, trackDistribution: true });
      samples.push(performance.now() - start);
      if (!i) results.push(JSON.parse(JSON.stringify(result)));
    }
    timings.push(median(samples));
  }
  assert.deepEqual(results[0], results[1]);
  return { items: n, runs: k, before_ms: timings[0], after_ms: timings[1], speedup: +(timings[0] / timings[1]).toFixed(1) };
}
function measureComparison(n, k) {
  const snapshots = rows(n, k).map(run => run.snapshot.rows), timings = [], sums = [];
  for (const ctx of [before, after]) {
    const samples = [];
    for (let sample = 0; sample < 3; sample++) {
      if (ctx.invalidateComparisonRowIndex) snapshots.forEach(ctx.invalidateComparisonRowIndex);
      let checksum = 0;
      const start = performance.now();
      for (let i = 0; i < n; i++) for (const rows of snapshots) checksum += ctx.findRowByCompareId(rows, 'item-' + i).metric_values[0];
      samples.push(performance.now() - start);
      if (!sample) sums.push(checksum);
    }
    timings.push(median(samples));
  }
  assert.equal(sums[0], sums[1]);
  return { items: n, runs: k, before_ms: timings[0], after_ms: timings[1], speedup: +(timings[0] / timings[1]).toFixed(1) };
}
measureModels(100, 2); measureComparison(100, 2);
console.log(JSON.stringify({ node: process.version, baseline, generated_at: new Date().toISOString(),
  scope: 'Synthetic CPU, actual shipped source at baseline versus working tree. Median of three; Compare includes map construction each sample. Excludes browser DOM/layout, database and network. Exact outputs checked.',
  models: [measureModels(1000, 5), measureModels(10000, 5)],
  comparison: [measureComparison(1000, 2), measureComparison(10000, 2)],
}, null, 2));
