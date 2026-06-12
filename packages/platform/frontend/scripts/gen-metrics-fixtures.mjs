/**
 * Golden-fixture generator for the legacy dashboard metrics module.
 *
 * Loads packages/platform/qym_platform/_static/dashboard/metrics.js (the
 * legacy plain-JS implementation, which attaches `window.QymMetrics`) inside
 * a node `vm` sandbox, executes every exported function across a fixed input
 * grid, and writes the observed outputs to
 * src/lib/__fixtures__/metrics-golden.json.
 *
 * src/lib/metrics.test.ts replays the same calls against the TypeScript port
 * (src/lib/metrics.ts) and asserts value-identical results (1e-12 float
 * tolerance).
 *
 * Determinism: metrics.js uses no Date/randomness. The only locale-sensitive
 * calls are `toLocaleString('en-US', ...)` (pinned locale; node ships
 * full-icu) and `String.prototype.localeCompare` on ASCII ids (stable).
 * Everything in the grid below is hard-coded, so re-running this script is
 * reproducible byte-for-byte.
 *
 * Callback arguments cannot be serialized, so fixture entries for the
 * higher-order functions store a declarative spec instead. The spec ->
 * callback reconstruction here MUST stay in sync with metrics.test.ts:
 *   - kind "itemLevel"  (calculateItemLevelMetrics)
 *       getMetricIndex = (rd) => typeof rd?.metric_idx === 'number' ? rd.metric_idx : -1
 *       getItemId      = itemIdKey ? (row) => String(row[itemIdKey]) : undefined
 *   - kind "grouped"    (calculateGroupedCohortComparison / OutcomeBuckets)
 *       getRunId       = (rd) => rd?.run_id
 *       getItemId      = (row) => row.item_id == null ? '' : String(row.item_id)
 *       getMetricIndex = (rd) => typeof rd?.metric_idx === 'number' ? rd.metric_idx : -1
 *
 * Non-JSON values (undefined / NaN / +-Infinity) are encoded as tagged
 * objects: {"$undef":true}, {"$num":"nan"|"inf"|"-inf"}.
 *
 * Usage: node scripts/gen-metrics-fixtures.mjs
 */

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import vm from 'node:vm'
import process from 'node:process'

const here = path.dirname(fileURLToPath(import.meta.url))
const METRICS_JS = path.resolve(
  here,
  '../../qym_platform/_static/dashboard/metrics.js',
)
const OUT_FILE = path.resolve(here, '../src/lib/__fixtures__/metrics-golden.json')

// ---------------------------------------------------------------------------
// Load legacy module in a sandbox
// ---------------------------------------------------------------------------

const source = readFileSync(METRICS_JS, 'utf8')
const sandbox = { window: {} }
vm.createContext(sandbox)
vm.runInContext(source, sandbox, { filename: 'metrics.js' })
const M = sandbox.window.QymMetrics
if (!M) throw new Error('window.QymMetrics was not attached by metrics.js')

// ---------------------------------------------------------------------------
// Tagged encoding for undefined / NaN / Infinity (mirrored in metrics.test.ts)
// ---------------------------------------------------------------------------

function encode(value) {
  if (value === undefined) return { $undef: true }
  if (typeof value === 'number') {
    if (Number.isNaN(value)) return { $num: 'nan' }
    if (value === Infinity) return { $num: 'inf' }
    if (value === -Infinity) return { $num: '-inf' }
    return value
  }
  if (value === null || typeof value !== 'object') return value
  if (Array.isArray(value)) return value.map(encode)
  const out = {}
  for (const key of Object.keys(value)) out[key] = encode(value[key])
  return out
}

function decode(value) {
  if (value === null || typeof value !== 'object') return value
  if (Array.isArray(value)) return value.map(decode)
  if (value.$undef === true) return undefined
  if (typeof value.$num === 'string') {
    return value.$num === 'nan' ? NaN : value.$num === 'inf' ? Infinity : -Infinity
  }
  const out = {}
  for (const key of Object.keys(value)) out[key] = decode(value[key])
  return out
}

// ---------------------------------------------------------------------------
// Spec -> callback reconstruction (MUST match metrics.test.ts)
// ---------------------------------------------------------------------------

const getMetricIndexFromRun = (rd) =>
  rd && typeof rd.metric_idx === 'number' ? rd.metric_idx : -1
const getItemIdByKey = (key) => (row) => String(row[key])
const groupedGetItemId = (row) => (row.item_id == null ? '' : String(row.item_id))
const groupedGetRunId = (rd) => (rd ? rd.run_id : undefined)

// ---------------------------------------------------------------------------
// Input grid
// ---------------------------------------------------------------------------

/** @type {Array<object>} */
const fixtures = []
let counter = 0

function plain(fn, ...args) {
  counter += 1
  const result = M[fn](...args.map((a) => decode(encode(a))))
  fixtures.push({
    id: `${fn}#${counter}`,
    kind: 'plain',
    fn,
    args: args.map(encode),
    result: encode(result),
  })
}

function itemLevel(label, spec) {
  counter += 1
  const options = {
    runsData: decode(encode(spec.runsData)),
    metricName: spec.metricName,
    threshold: spec.threshold,
    getMetricIndex: getMetricIndexFromRun,
    getItemId: spec.itemIdKey ? getItemIdByKey(spec.itemIdKey) : undefined,
    trackDistribution: spec.trackDistribution,
  }
  const result = M.calculateItemLevelMetrics(options)
  fixtures.push({
    id: `calculateItemLevelMetrics#${counter}:${label}`,
    kind: 'itemLevel',
    fn: 'calculateItemLevelMetrics',
    spec: {
      runsData: encode(spec.runsData),
      metricName: spec.metricName ?? null,
      threshold: spec.threshold,
      itemIdKey: spec.itemIdKey ?? null,
      trackDistribution: spec.trackDistribution ?? false,
    },
    result: encode(result),
  })
}

function grouped(label, fn, spec) {
  counter += 1
  let options
  if (spec.nullOptions) {
    options = null
  } else {
    options = {
      runsData: decode(encode(spec.runsData)),
      leftRunIds: spec.leftRunIds,
      rightRunIds: spec.rightRunIds,
      threshold: spec.threshold,
      getMetricIndex: spec.omitCallbacks ? undefined : getMetricIndexFromRun,
      getItemId: spec.omitCallbacks ? undefined : groupedGetItemId,
      getRunId: spec.omitCallbacks ? undefined : groupedGetRunId,
    }
  }
  const result = M[fn](options)
  fixtures.push({
    id: `${fn}#${counter}:${label}`,
    kind: 'grouped',
    fn,
    spec: {
      runsData: encode(spec.runsData ?? null),
      leftRunIds: spec.leftRunIds ?? null,
      rightRunIds: spec.rightRunIds ?? null,
      threshold: spec.threshold ?? null,
      omitCallbacks: spec.omitCallbacks ?? false,
      nullOptions: spec.nullOptions ?? false,
    },
    result: encode(result),
  })
}

// --------------------------- parseScoreValue -------------------------------

for (const value of [
  undefined,
  null,
  0,
  1,
  0.5,
  -0.25,
  1.5,
  NaN,
  Infinity,
  -Infinity,
  true,
  false,
  '',
  '   ',
  'n/a',
  'N/A',
  'na',
  'none',
  'NULL',
  'null',
  '✓',
  'true',
  'TRUE',
  'yes',
  'Y',
  '✗',
  'false',
  'no',
  'N',
  '85%',
  ' 85.5 %',
  '12.5%',
  '100%',
  '0%',
  'abc%',
  '%',
  '0.75',
  ' 42 ',
  '3.5abc',
  'abc',
  '1e-3',
  '1e3',
  'Infinity',
  '-2',
  '07',
  '.5',
  '5.',
  '-0',
]) {
  plain('parseScoreValue', value)
}

// ------------------------------ isErrorRow ---------------------------------

for (const row of [
  null,
  undefined,
  {},
  { status: 'error' },
  { status: 'failed' },
  { status: 'ok' },
  { status: 'ERROR' },
  { status: 'Failed' },
  { status: null },
  { status: 0 },
]) {
  plain('isErrorRow', row)
}

// ------------------------------ getRowScore --------------------------------

plain('getRowScore', null, 0)
plain('getRowScore', undefined, 0)
plain('getRowScore', { status: 'error', metric_values: [1, 0.9] }, 0)
plain('getRowScore', { status: 'failed' }, 2)
plain('getRowScore', { metric_values: [0.7, '80%'] }, 0)
plain('getRowScore', { metric_values: [0.7, '80%'] }, 1)
plain('getRowScore', { metric_values: [0.7, '80%'] }, 2)
plain('getRowScore', { metric_values: [0.7, '80%'] }, -1)
plain('getRowScore', { metric_values: ['n/a'] }, 0)
plain('getRowScore', {}, 0)
plain('getRowScore', { status: 'ok', metric_values: [true, false] }, 0)
plain('getRowScore', { status: 'ok', metric_values: [true, false] }, 1)
plain('getRowScore', { metric_values: [NaN] }, 0)
plain('getRowScore', { metric_values: [null] }, 0)

// ---------------------------- calculateMedian ------------------------------

plain('calculateMedian', [])
plain('calculateMedian', null)
plain('calculateMedian', undefined)
plain('calculateMedian', 'not-an-array')
plain('calculateMedian', [5])
plain('calculateMedian', [1, 2, 3])
plain('calculateMedian', [1, 2, 3, 4])
plain('calculateMedian', [3, 1, 2])
plain('calculateMedian', ['3', '1', '2'])
plain('calculateMedian', [1, 'x', 2, NaN, Infinity, 3])
plain('calculateMedian', [-5, 5])
plain('calculateMedian', [2.5, 1.5])
plain('calculateMedian', [10, 10, 10, 10])
plain('calculateMedian', [0, 0, 1])
plain('calculateMedian', ['abc', NaN])

// ------------------------ calculateItemLevelMetrics ------------------------

// Shared 3-run dataset keyed by item_id; run3 has the metric at index 1.
const runsA = [
  {
    run_id: 'r1',
    metric_idx: 0,
    snapshot: {
      rows: [
        { item_id: 'a', metric_values: [1], latency_ms: 100 },
        { item_id: 'b', metric_values: [0], latency_ms: 200 },
        { item_id: 'c', metric_values: ['85%'], latency_ms: 1500 },
        { item_id: 'd', metric_values: ['n/a'], latency_ms: 0 },
        { item_id: 'e', status: 'error', metric_values: [1], latency_ms: 50 },
      ],
    },
  },
  {
    run_id: 'r2',
    metric_idx: 0,
    snapshot: {
      rows: [
        { item_id: 'a', metric_values: [true], latency_ms: 120 },
        { item_id: 'b', metric_values: ['✗'], latency_ms: 80 },
        { item_id: 'c', metric_values: [0.6], latency_ms: null },
        { item_id: 'd', metric_values: [0.9], latency_ms: 300 },
      ],
    },
  },
  {
    run_id: 'r3',
    metric_idx: 1,
    snapshot: {
      rows: [
        { item_id: 'a', metric_values: ['other', 0.4], latency_ms: 90 },
        { item_id: 'b', metric_values: ['other', 1], latency_ms: 60 },
        { item_id: 'c', metric_values: ['other', 'yes'], latency_ms: -5 },
        { item_id: 'd', metric_values: ['other', null], latency_ms: 40 },
        { item_id: 'e', metric_values: ['other', 0.7], latency_ms: 70 },
      ],
    },
  },
]

itemLevel('threeRuns-mixed', {
  runsData: runsA,
  metricName: 'accuracy',
  threshold: 0.5,
  itemIdKey: 'item_id',
  trackDistribution: true,
})
itemLevel('threeRuns-threshold1', {
  runsData: runsA,
  threshold: 1,
  itemIdKey: 'item_id',
  trackDistribution: true,
})
itemLevel('threeRuns-threshold0', {
  runsData: runsA,
  threshold: 0,
  itemIdKey: 'item_id',
})
itemLevel('emptyRunsData', { runsData: [], threshold: 0.5 })
itemLevel('nullRunsData', { runsData: null, threshold: 0.5, trackDistribution: true })
itemLevel('emptyRows', {
  runsData: [{ metric_idx: 0, snapshot: { rows: [] } }, null],
  threshold: 0.5,
  trackDistribution: true,
})
itemLevel('singleRun-mixed', {
  runsData: [
    {
      metric_idx: 0,
      snapshot: {
        rows: [
          { item_id: 'a', metric_values: [1], latency_ms: 111 },
          { item_id: 'b', metric_values: [0], latency_ms: 222 },
          { item_id: 'c', metric_values: [0.5], latency_ms: 333 },
        ],
      },
    },
  ],
  threshold: 0.5,
  itemIdKey: 'item_id',
  trackDistribution: true,
})
itemLevel('allPass-twoRuns', {
  runsData: [
    {
      metric_idx: 0,
      snapshot: {
        rows: [
          { item_id: 'a', metric_values: [1] },
          { item_id: 'b', metric_values: [0.9] },
        ],
      },
    },
    {
      metric_idx: 0,
      snapshot: {
        rows: [
          { item_id: 'a', metric_values: [0.8] },
          { item_id: 'b', metric_values: [1] },
        ],
      },
    },
  ],
  threshold: 0.5,
  itemIdKey: 'item_id',
  trackDistribution: true,
})
itemLevel('allFail-twoRuns', {
  runsData: [
    {
      metric_idx: 0,
      snapshot: {
        rows: [
          { item_id: 'a', metric_values: [0] },
          { item_id: 'b', metric_values: [0.1] },
        ],
      },
    },
    {
      metric_idx: 0,
      snapshot: {
        rows: [
          { item_id: 'a', metric_values: [0.2] },
          { item_id: 'b', metric_values: [0] },
        ],
      },
    },
  ],
  threshold: 0.5,
  itemIdKey: 'item_id',
  trackDistribution: true,
})
// Default getItemId (String(row.index)); run2 shorter than run1 (k > n cases).
itemLevel('defaultItemId-unevenRuns', {
  runsData: [
    {
      metric_idx: 0,
      snapshot: {
        rows: [
          { index: 0, metric_values: [1], latency_ms: 10 },
          { index: 1, metric_values: [0], latency_ms: 20 },
          { index: 2, metric_values: [0.75], latency_ms: 30 },
        ],
      },
    },
    {
      metric_idx: 0,
      snapshot: {
        rows: [
          { index: 0, metric_values: [0] },
          { index: 1, metric_values: [1] },
        ],
      },
    },
  ],
  threshold: 0.5,
  trackDistribution: true,
})
// Rows without `index` all collapse to the "undefined" item id (legacy quirk).
itemLevel('defaultItemId-missingIndex', {
  runsData: [
    {
      metric_idx: 0,
      snapshot: {
        rows: [
          { metric_values: [1] },
          { metric_values: [0] },
          { metric_values: [0.6] },
        ],
      },
    },
  ],
  threshold: 0.5,
})
// One run reports metric_idx -1 -> its rows are skipped entirely.
itemLevel('metricIdxMinusOne', {
  runsData: [
    {
      metric_idx: 0,
      snapshot: {
        rows: [
          { item_id: 'a', metric_values: [1], latency_ms: 5 },
          { item_id: 'b', metric_values: [0], latency_ms: 6 },
        ],
      },
    },
    {
      metric_idx: -1,
      snapshot: {
        rows: [
          { item_id: 'a', metric_values: [0], latency_ms: 7 },
          { item_id: 'b', metric_values: [1], latency_ms: 8 },
        ],
      },
    },
  ],
  threshold: 0.5,
  itemIdKey: 'item_id',
  trackDistribution: true,
})
// Out-of-range numeric metric values with a numeric threshold.
itemLevel('numericScores', {
  runsData: [
    {
      metric_idx: 0,
      snapshot: {
        rows: [
          { item_id: 'a', metric_values: [5], latency_ms: 1000 },
          { item_id: 'b', metric_values: [12], latency_ms: 2000 },
          { item_id: 'c', metric_values: [-3], latency_ms: 3000 },
        ],
      },
    },
    {
      metric_idx: 0,
      snapshot: {
        rows: [
          { item_id: 'a', metric_values: [4] },
          { item_id: 'b', metric_values: [2] },
          { item_id: 'c', metric_values: [6] },
        ],
      },
    },
  ],
  threshold: 4,
  itemIdKey: 'item_id',
  trackDistribution: true,
})
// Duplicate item ids inside a run: rows.find takes the FIRST match.
itemLevel('duplicateItemIdsInRun', {
  runsData: [
    {
      metric_idx: 0,
      snapshot: {
        rows: [
          { item_id: 'a', metric_values: [1], latency_ms: 10 },
          { item_id: 'a', metric_values: [0], latency_ms: 99999 },
          { item_id: 'b', metric_values: [0.5], latency_ms: 20 },
        ],
      },
    },
  ],
  threshold: 0.5,
  itemIdKey: 'item_id',
})
// All scores null -> item skipped; errors-only run.
itemLevel('allNullScores', {
  runsData: [
    {
      metric_idx: 0,
      snapshot: {
        rows: [
          { item_id: 'a', metric_values: ['n/a'], latency_ms: 10 },
          { item_id: 'b', metric_values: [null], latency_ms: 20 },
        ],
      },
    },
  ],
  threshold: 0.5,
  itemIdKey: 'item_id',
  trackDistribution: true,
})
itemLevel('errorsOnly', {
  runsData: [
    {
      metric_idx: 0,
      snapshot: {
        rows: [
          { item_id: 'a', status: 'error', latency_ms: 10 },
          { item_id: 'b', status: 'failed', metric_values: [1] },
        ],
      },
    },
    {
      metric_idx: 0,
      snapshot: {
        rows: [
          { item_id: 'a', metric_values: [1], latency_ms: 30 },
          { item_id: 'b', status: 'error', latency_ms: 40 },
        ],
      },
    },
  ],
  threshold: 0.5,
  itemIdKey: 'item_id',
  trackDistribution: true,
})

// --------------- calculateGroupedCohortComparison / buckets ----------------

const groupedRuns = [
  {
    run_id: 'L1',
    metric_idx: 0,
    snapshot: {
      rows: [
        { item_id: 'i1', metric_values: [1], retry_count: 0 },
        { item_id: 'i2', metric_values: [0], retry_count: 1 },
        { item_id: 'i3', metric_values: [1], retry_count: null },
        { item_id: 'i4', metric_values: [0] },
        { item_id: 'i5', metric_values: [0.4], retry_count: '2' },
        { item_id: 'i6', metric_values: [1] },
        { item_id: 'i7', metric_values: ['n/a'] },
      ],
    },
  },
  {
    run_id: 'L2',
    metric_idx: 0,
    snapshot: {
      rows: [
        { item_id: 'i1', metric_values: [0.9], retry_count: 2 },
        { item_id: 'i2', metric_values: [0.2] },
        { item_id: 'i3', metric_values: [0.8] },
        { item_id: 'i4', metric_values: [0.1] },
        { item_id: 'i5', metric_values: [1] },
        { item_id: 'i6', metric_values: [1] },
        { item_id: 'i7', metric_values: [1] },
      ],
    },
  },
  {
    run_id: 'R1',
    metric_idx: 0,
    snapshot: {
      rows: [
        { item_id: 'i1', metric_values: [0] },
        { item_id: 'i2', metric_values: [1], retry_count: 3 },
        { item_id: 'i3', metric_values: [1] },
        { item_id: 'i4', metric_values: [0.3] },
        { item_id: 'i5', metric_values: [1] },
        { item_id: 'i6', metric_values: [1] },
        { item_id: 'i7', metric_values: [1] },
      ],
    },
  },
  {
    run_id: 'R2',
    metric_idx: 0,
    snapshot: {
      rows: [
        { item_id: 'i1', metric_values: [0.2] },
        { item_id: 'i2', metric_values: [0.95] },
        { item_id: 'i3', metric_values: [0.7] },
        { item_id: 'i4', metric_values: [0] },
        { item_id: 'i5', metric_values: [1] },
        // i6 missing -> ineligible
        { item_id: 'i7', metric_values: [1] },
      ],
    },
  },
]

for (const fn of ['calculateGroupedCohortComparison', 'calculateGroupedOutcomeBuckets']) {
  grouped('twoVsTwo', fn, {
    runsData: groupedRuns,
    leftRunIds: ['L1', 'L2'],
    rightRunIds: ['R1', 'R2'],
    threshold: 0.5,
  })
  grouped('nullOptions', fn, { nullOptions: true })
  grouped('missingRunId', fn, {
    runsData: groupedRuns,
    leftRunIds: ['L1', 'NOPE'],
    rightRunIds: ['R1', 'R2'],
    threshold: 0.5,
  })
  grouped('omitCallbacks', fn, {
    runsData: groupedRuns,
    leftRunIds: ['L1'],
    rightRunIds: ['R1'],
    threshold: 0.5,
    omitCallbacks: true,
  })
}

grouped('oneVsOne', 'calculateGroupedCohortComparison', {
  runsData: groupedRuns,
  leftRunIds: ['L1'],
  rightRunIds: ['R1'],
  threshold: 0.5,
})
grouped('unevenGroups', 'calculateGroupedCohortComparison', {
  runsData: groupedRuns,
  leftRunIds: ['L1', 'L2'],
  rightRunIds: ['R1'],
  threshold: 0.5,
})
grouped('duplicateRunIdInGroup', 'calculateGroupedCohortComparison', {
  runsData: groupedRuns,
  leftRunIds: ['L1', 'L1'],
  rightRunIds: ['R1', 'R2'],
  threshold: 0.5,
})
grouped('emptyLeftIds', 'calculateGroupedCohortComparison', {
  runsData: groupedRuns,
  leftRunIds: [],
  rightRunIds: ['R1'],
  threshold: 0.5,
})
grouped('errorRowsCountAsFail', 'calculateGroupedCohortComparison', {
  runsData: [
    {
      run_id: 'A',
      metric_idx: 0,
      snapshot: {
        rows: [
          { item_id: 'x', status: 'error', metric_values: [1] },
          { item_id: 'y', metric_values: [1], retry_count: 1 },
        ],
      },
    },
    {
      run_id: 'B',
      metric_idx: 0,
      snapshot: {
        rows: [
          { item_id: 'x', metric_values: [1] },
          { item_id: 'y', status: 'failed' },
        ],
      },
    },
  ],
  leftRunIds: ['A'],
  rightRunIds: ['B'],
  threshold: 0.5,
})
grouped('thresholdZero', 'calculateGroupedCohortComparison', {
  runsData: groupedRuns,
  leftRunIds: ['L1', 'L2'],
  rightRunIds: ['R1', 'R2'],
  threshold: 0,
})
grouped('duplicateRunDataId', 'calculateGroupedCohortComparison', {
  runsData: [
    {
      run_id: 'D',
      metric_idx: 0,
      snapshot: { rows: [{ item_id: 'x', metric_values: [1] }] },
    },
    {
      run_id: 'D',
      metric_idx: 0,
      snapshot: { rows: [{ item_id: 'x', metric_values: [0] }] },
    },
    {
      run_id: 'E',
      metric_idx: 0,
      snapshot: { rows: [{ item_id: 'x', metric_values: [0] }] },
    },
  ],
  leftRunIds: ['D'],
  rightRunIds: ['E'],
  threshold: 0.5,
})

// ---------------------------- detectMetricType -----------------------------

plain('detectMetricType', [], 0)
plain('detectMetricType', [{ metric_values: [1] }, { metric_values: [0] }], 0)
plain('detectMetricType', [{ metric_values: [1] }, { metric_values: [0.5] }], 0)
plain('detectMetricType', [{ metric_values: [1.5] }, { metric_values: [0.5] }], 0)
plain('detectMetricType', [{ metric_values: [-0.1] }], 0)
plain('detectMetricType', [{ metric_values: ['n/a'] }, { metric_values: [null] }], 0)
plain('detectMetricType', [{ status: 'error', metric_values: [5] }], 0)
plain('detectMetricType', [{ metric_values: [true] }, { metric_values: ['no'] }], 0)
plain('detectMetricType', [{ metric_values: ['85%'] }], 0)
plain('detectMetricType', [{ metric_values: [0, 7] }], 1)

// ------------------------- detectMetricTypeFromAvg -------------------------

for (const v of [null, undefined, NaN, 0, 0.5, 1, 1.0001, -0.1, 100, -5]) {
  plain('detectMetricTypeFromAvg', v)
}

// ------------------------------ formatPercent ------------------------------

plain('formatPercent', undefined)
plain('formatPercent', null)
plain('formatPercent', NaN)
plain('formatPercent', 0)
plain('formatPercent', 1)
plain('formatPercent', 0.528)
plain('formatPercent', 0.5285)
plain('formatPercent', 0.5285, 2)
plain('formatPercent', 0.5285, 0)
plain('formatPercent', 0.5285, 3)
plain('formatPercent', 0.9999)
plain('formatPercent', -0.123)
plain('formatPercent', 2.5)
plain('formatPercent', 0.0005)
plain('formatPercent', 1 / 3)

// ------------------------------ formatLatency ------------------------------

plain('formatLatency', null)
plain('formatLatency', undefined)
plain('formatLatency', 0)
plain('formatLatency', -5)
plain('formatLatency', NaN)
plain('formatLatency', 1)
plain('formatLatency', 129)
plain('formatLatency', 999)
plain('formatLatency', 999.5) // legacy quirk: renders "1000ms"
plain('formatLatency', 1000)
plain('formatLatency', 1500)
plain('formatLatency', 2300)
plain('formatLatency', 59999)
plain('formatLatency', 60000)
plain('formatLatency', 90000)
plain('formatLatency', 106000)
plain('formatLatency', 119999) // legacy quirk: renders "1m 60s"
plain('formatLatency', 3600000) // no hours unit: "60m 0s"
plain('formatLatency', 11406000)

// --------------------------- getScoreColorClass ----------------------------

for (const v of [0.95, 0.9, 0.89, 0.75, 0.74, 0.6, 0.59, 0.4, 0.39, 0, -1, NaN, 1.5]) {
  plain('getScoreColorClass', v)
}

// --------------------------- getMetricColorClass ---------------------------

plain('getMetricColorClass', 0.8, 'numeric')
plain('getMetricColorClass', 0.8, 'score')
plain('getMetricColorClass', 1, 'boolean')
plain('getMetricColorClass', 0.1, 'score')

// ---------------------------- formatMetricValue ----------------------------

plain('formatMetricValue', undefined, 'score')
plain('formatMetricValue', null, 'numeric')
plain('formatMetricValue', NaN, 'score')
plain('formatMetricValue', 0.5285, 'score')
plain('formatMetricValue', 0.5285, 'score', 2)
plain('formatMetricValue', 0.5285, 'boolean')
plain('formatMetricValue', 1234.5, 'numeric')
plain('formatMetricValue', 1234.5, 'numeric', 2)
plain('formatMetricValue', 0.5, 'numeric')
plain('formatMetricValue', 7, 'numeric')

// -------------------------- formatMetricValueSmart -------------------------

plain('formatMetricValueSmart', undefined, 'score', [])
plain('formatMetricValueSmart', NaN, 'numeric', [1])
plain('formatMetricValueSmart', 0.523, 'score', null)
plain('formatMetricValueSmart', 0.523, 'score', [])
plain('formatMetricValueSmart', 0.523, 'score', [0.524]) // collides at 1dp -> 2dp
plain('formatMetricValueSmart', 0.523, 'score', [0.5231]) // collides up to 3dp -> max
plain('formatMetricValueSmart', 0.523, 'score', [0.9])
plain('formatMetricValueSmart', 0.523, 'score', [0.523]) // self excluded from peers
plain('formatMetricValueSmart', 0.523, 'score', [NaN, null, undefined, 0.524])
plain('formatMetricValueSmart', 0.5, 'score', [0.52], 1, 3)
plain('formatMetricValueSmart', 7, 'numeric', [7.04]) // integer default 0dp, collision -> more
plain('formatMetricValueSmart', 7, 'numeric', [8])
plain('formatMetricValueSmart', 7.123, 'numeric', [7.1])
plain('formatMetricValueSmart', 1234.5, 'numeric', [1234.6]) // locale path collides at every dp
plain('formatMetricValueSmart', 0.523, 'score', [0.524], 2, 3)

// ---------------------------- formatNumericValue ---------------------------

plain('formatNumericValue', undefined)
plain('formatNumericValue', null)
plain('formatNumericValue', NaN)
plain('formatNumericValue', 0)
plain('formatNumericValue', 5)
plain('formatNumericValue', 5.25)
plain('formatNumericValue', 5.25, 2)
plain('formatNumericValue', -3.7)
plain('formatNumericValue', 999)
plain('formatNumericValue', 999.9)
plain('formatNumericValue', 1000)
plain('formatNumericValue', 1234.56)
plain('formatNumericValue', 9999)
plain('formatNumericValue', 10000)
plain('formatNumericValue', 999999)
plain('formatNumericValue', 1000000)
plain('formatNumericValue', 1234567)
plain('formatNumericValue', -1234567)
plain('formatNumericValue', -10000)

// ----------------------------- getMetricTooltips ---------------------------

plain('getMetricTooltips', 3, true, 80)
plain('getMetricTooltips', 5, false, 50)
plain('getMetricTooltips', 1, false, 0)

// ---------------------------------------------------------------------------
// Write
// ---------------------------------------------------------------------------

mkdirSync(path.dirname(OUT_FILE), { recursive: true })
writeFileSync(OUT_FILE, JSON.stringify(fixtures, null, 1) + '\n', 'utf8')
process.stdout.write(`Wrote ${fixtures.length} fixtures to ${OUT_FILE}\n`)
