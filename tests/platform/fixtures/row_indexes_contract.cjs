// Compare the optimized lookups with the former strict-equality Array.find
// semantics while exercising the complete, unmodified estimator calculations.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const repo = process.argv[2];
const asset = name => path.join(repo, 'packages/platform/qym_platform/_static/dashboard', name);
const source = fs.readFileSync(asset('metrics.js'), 'utf8');
function context(legacy = false) {
  const ctx = vm.createContext({ window: {} });
  vm.runInContext(source, ctx);
  if (legacy) vm.runInContext(`indexRowsById = (rows, getId) => ({ get: id => rows.find(row => getId(row) === id) });`, ctx);
  return ctx;
}
const fast = context(), slow = context(true);
const plain = value => JSON.parse(JSON.stringify(value));
let seed = 93617;
function random() { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; }
const values = [null, undefined, '', 'N/A', '0%', '100%', '0.35', 0, 1, true, false, '✓', '✗', 7, -2, NaN, 'error'];
function datasets(n, k) {
  return Array.from({ length: k }, (_, ri) => ({
    run: { run_id: 'run-' + ri, samples: ri % 2 ? 3 : 1 },
    snapshot: { rows: Array.from({ length: n }, (_, i) => ({
      index: i,
      item_id: i % 13 === 0 ? undefined : i % 11 === 0 ? null : i % 7 === 0 ? 'duplicate' : i % 17 === 0 ? NaN : 'عنصر-' + i,
      compare_item_id: 'compare-' + i,
      status: ['completed', 'error', 'pending', 'failed'][Math.floor(random() * 4)],
      latency_ms: Math.floor(random() * 10000),
      retry_count: Math.floor(random() * 4),
      metric_values: [values[Math.floor(random() * values.length)], values[Math.floor(random() * values.length)]],
      pass_scores: { accuracy: [0, 0.5, 1] },
      item_metadata: { root_cause: 'cause-' + (i % 4), complexity: i % 2 ? 'hard' : 'easy' },
    })) },
  }));
}
function compareEstimators(runs, getItemId, threshold) {
  const options = { runsData: runs, threshold, metricName: 'accuracy', getMetricIndex: run => Number(run.run.run_id.slice(4)) % 2, getItemId, trackDistribution: true };
  assert.deepEqual(plain(fast.calculateItemLevelMetrics(options)), plain(slow.calculateItemLevelMetrics(options)));
  const grouped = { ...options, leftRunIds: ['run-0', 'run-1'], rightRunIds: ['run-2', 'run-3'], getRunId: run => run.run.run_id };
  assert.deepEqual(plain(fast.calculateGroupedCohortComparison(grouped)), plain(slow.calculateGroupedCohortComparison(grouped)));
  assert.deepEqual(plain(fast.calculateGroupedOutcomeBuckets(grouped)), plain(slow.calculateGroupedOutcomeBuckets(grouped)));
}
for (let sample = 0; sample < 25; sample++) {
  const runs = datasets(20 + sample, 4);
  compareEstimators(runs, row => row.item_id, sample % 2 ? 0.8 : 0.5);
  compareEstimators(runs, undefined, 0.8);
  // Repeated calculations must observe changed values, replaced rows, changed
  // IDs, duplicate ordering, and changed array lengths (no stale shared cache).
  runs[0].snapshot.rows[0] = { ...runs[0].snapshot.rows[0], item_id: 'new', metric_values: [1, 1] };
  runs[1].snapshot.rows.reverse();
  runs[2].snapshot.rows[3].item_id = 'new';
  runs[3].snapshot.rows.push({ index: 100, item_id: 'new', metric_values: [0, 0] });
  compareEstimators(runs, row => row.item_id, 0.8);
}
const identity = {};
const rows = [
  { id: undefined, name: 'first missing' }, { id: undefined, name: 'second missing' },
  { id: null }, { id: 0 }, { id: '0' }, { id: NaN }, { id: identity },
  { id: '__proto__' }, { id: 'constructor' },
];
const index = fast.indexRowsById(rows, row => row.id);
for (const id of [undefined, null, 0, -0, '0', NaN, identity, {}, '__proto__', 'constructor']) {
  assert.equal(index.get(id), rows.find(row => row.id === id));
}
// Count callback invocations instead of asserting machine-sensitive timings.
for (const count of [1000, 10000]) {
  const runs = datasets(count, 4);
  let calls = 0;
  const options = { runsData: runs, threshold: 0.8, metricName: 'accuracy', getMetricIndex: () => 0, getItemId: row => { calls++; return row.item_id; } };
  fast.calculateItemLevelMetrics(options);
  assert.ok(calls <= count * 4 * 3, `Item estimators made ${calls} identity calls for ${count} rows`);
  calls = 0;
  fast.calculateGroupedCohortComparison({ ...options, leftRunIds: ['run-0', 'run-1'], rightRunIds: ['run-2', 'run-3'], getRunId: run => run.run.run_id });
  assert.ok(calls <= count * 4 * 3, `Cohort estimators made ${calls} identity calls for ${count} rows`);
}
const compareSource = fs.readFileSync(asset('compare.html'), 'utf8');
const getIdStart = compareSource.indexOf('      function getRowCompareId(');
const end = compareSource.indexOf('      function canRenderItemComparison(', getIdStart);
vm.runInContext(compareSource.slice(getIdStart, end), fast);
const mutable = [{ compare_item_id: 'a', value: 1 }, { compare_item_id: 'a', value: 2 }];
assert.equal(fast.findRowByCompareId(mutable, 'a'), mutable[0]);
mutable[0].value = 3;
assert.equal(fast.findRowByCompareId(mutable, 'a').value, 3);
mutable[0] = { compare_item_id: 'b', value: 4 };
fast.invalidateComparisonRowIndex(mutable);
assert.equal(fast.findRowByCompareId(mutable, 'a'), mutable[1]);
assert.equal(fast.findRowByCompareId(mutable, 'b'), mutable[0]);
mutable[1].compare_item_id = 'c';
fast.invalidateComparisonRowIndex(mutable);
assert.equal(fast.findRowByCompareId(mutable, 'a'), null);
mutable.push({ compare_item_id: 'a', value: 5 });
assert.equal(fast.findRowByCompareId(mutable, 'a'), mutable[2]);
assert.equal(fast.findRowByCompareId([{ compare_item_id: 'a' }], 'a').compare_item_id, 'a');
assert.equal(fast.findRowByCompareId(null, 'a'), null);
console.log('Row index differential, identity, mutation, and linear scaling contracts passed.');
