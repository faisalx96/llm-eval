/**
 * Metrics math ported 1:1 from the legacy dashboard module
 * `packages/platform/qym_platform/_static/dashboard/metrics.js`
 * (`window.QymMetrics`).
 *
 * GOLDEN PARITY: this port is verified value-identical against the legacy
 * implementation by `metrics.test.ts`, which replays the generated fixtures
 * in `__fixtures__/metrics-golden.json` (regenerate with
 * `node scripts/gen-metrics-fixtures.mjs`). Do not "fix" surprising behavior
 * here without regenerating fixtures from an updated legacy file — the math
 * is product integrity.
 *
 * Intentionally preserved legacy semantics (do not change):
 * - Errors score as 0: rows with status 'error' | 'failed' (case-sensitive)
 *   always yield score 0 via {@link getRowScore}, regardless of metric value.
 * - {@link parseScoreValue} keeps JS `parseFloat` semantics: '3.5abc' -> 3.5,
 *   'Infinity' (string) -> Infinity, while *numeric* non-finite inputs
 *   (NaN/±Infinity) -> null.
 * - Divide-by-zero policy: all rate aggregates (passAtK, avgScore, …) return
 *   0 when their denominator is 0; consistency/reliability return null when
 *   no item qualifies (they require >1 scores per item).
 * - Default item identity is `String(row.index)` — rows without `index`
 *   collapse onto the single id 'undefined'.
 * - `formatLatency(999.5)` renders '1000ms', `formatLatency(119999)` renders
 *   '1m 60s', and minutes never roll into hours ('60m 0s').
 * - Thresholds are inclusive: an item passes when `score >= threshold`, so
 *   threshold 0 marks every scored item (even score 0) as passing.
 * - stddevScore is the population standard deviation (divides by N).
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Raw metric cell value as found in snapshot rows. */
export type MetricScalar = number | string | boolean | null | undefined

/** Snapshot row shape (subset used by the metrics math). */
export interface SnapshotRow {
  status?: unknown
  metric_values?: MetricScalar[]
  latency_ms?: number | null
  index?: number | string
  item_id?: string
  item_metadata?: Record<string, unknown>
  retry_count?: number | string | null
  [key: string]: unknown
}

export interface RunSnapshot {
  rows?: SnapshotRow[]
}

/** A run payload; extra fields are carried through untouched. */
export interface RunData {
  snapshot?: RunSnapshot
  [key: string]: unknown
}

export type MetricType = 'boolean' | 'score' | 'numeric'

export interface RowScore {
  /** Score in metric units (0 for error rows), or null when unparseable. */
  score: number | null
  isError: boolean
}

export interface ItemLevelMetricsOptions {
  runsData: ReadonlyArray<RunData | null | undefined> | null | undefined
  /** Unused by the math; kept for call-site parity with the legacy module. */
  metricName?: string | null
  /** Inclusive pass threshold in metric units (score >= threshold passes). */
  threshold: number
  getMetricIndex: (runData: RunData | null | undefined) => number
  /** Defaults to `String(row.index)`. */
  getItemId?: (row: SnapshotRow) => string
  /** Track the per-item correct-count histogram (length K+1). */
  trackDistribution?: boolean
}

export interface ItemLevelMetrics {
  passAtK: number
  passHatK: number
  maxAtK: number
  consistency: number | null
  reliability: number | null
  avgScore: number
  avgLatency: number
  medianLatency: number
  totalItems: number
  failedCount: number
  K: number
  totalScoreSum: number
  totalScoreCount: number
  totalLatencySum: number
  totalLatencyCount: number
  correctDistribution: number[] | null
  minScore: number
  stddevScore: number
}

export type OutcomeBucketKey = 'a_sweeps_b' | 'b_sweeps_a' | 'both_pass' | 'both_fail'

export interface OutcomeBucket {
  count: number
  percentage: number
  itemIds: string[]
}

export type OutcomeBuckets = Record<OutcomeBucketKey, OutcomeBucket>

export interface GroupedComparisonOptions {
  runsData?: ReadonlyArray<RunData | null | undefined> | null
  leftRunIds?: ReadonlyArray<string> | null
  rightRunIds?: ReadonlyArray<string> | null
  threshold?: number
  getMetricIndex?: (runData: RunData | null | undefined) => number
  getItemId?: (row: SnapshotRow) => string
  getRunId?: (runData: RunData | null | undefined) => string | undefined
}

export interface GroupAggregate {
  passAtK: number
  passHatK: number
  avgAtK: number
  consistency: number | null
  reliability: number | null
  avgAttempts: number
}

export interface GroupedComparisonItem {
  itemId: string
  rawItemId: string
  metadata: Record<string, unknown>
  leftScores: number[]
  rightScores: number[]
  leftPasses: boolean[]
  rightPasses: boolean[]
  leftAttempts: number[]
  rightAttempts: number[]
  leftPassCount: number
  rightPassCount: number
  leftAvgAttempts: number
  rightAvgAttempts: number
  move: number
  bucketKey: OutcomeBucketKey | null
}

export interface GroupedComparisonResult {
  eligibleItems: number
  leftRunCount: number
  rightRunCount: number
  k: number
  left: GroupAggregate
  right: GroupAggregate
  deltas: {
    passAtK: number
    passHatK: number
    avgAtK: number
    consistency: number
    reliability: number
  }
  summary: {
    improvedCount: number
    regressedCount: number
    unchangedCount: number
    avgAttemptsDelta: number
  }
  items: GroupedComparisonItem[]
  buckets: OutcomeBuckets
}

export interface GroupedOutcomeBucketsResult {
  eligibleItems: number
  leftRunCount: number
  rightRunCount: number
  buckets: OutcomeBuckets
}

export interface MetricTooltips {
  passAtK: string
  passHatK: string
  maxAtK: string
  consistency: string
  reliability: string
  failedCount: string
  avgScore: string
  avgLatency: string
  medianLatency: string
}

// ---------------------------------------------------------------------------
// Core error handling / score extraction
// ---------------------------------------------------------------------------

/** True when the row represents an error/failed item (status exact-match). */
export function isErrorRow(row: SnapshotRow | null | undefined): boolean {
  if (!row) return false
  const status = row.status
  return status === 'error' || status === 'failed'
}

/**
 * Parse a raw metric cell into a numeric score.
 *
 * Accepts numbers (finite only), booleans, check marks, yes/no, percent
 * strings ('85%' -> 0.85), and anything `parseFloat` can read. Returns null
 * for missing/unparseable values ('n/a', 'na', 'none', 'null', '', NaN, ...).
 */
export function parseScoreValue(metricValue: MetricScalar): number | null {
  if (metricValue === undefined || metricValue === null) return null
  if (typeof metricValue === 'number') {
    return Number.isFinite(metricValue) ? metricValue : null
  }
  if (typeof metricValue === 'boolean') {
    return metricValue ? 1 : 0
  }

  const raw = String(metricValue).trim()
  if (!raw) return null

  const lowered = raw.toLowerCase()
  if (lowered === 'n/a' || lowered === 'na' || lowered === 'none' || lowered === 'null') {
    return null
  }
  if (raw === '✓' || lowered === 'true' || lowered === 'yes' || lowered === 'y') {
    return 1
  }
  if (raw === '✗' || lowered === 'false' || lowered === 'no' || lowered === 'n') {
    return 0
  }

  if (raw.endsWith('%')) {
    const pct = parseFloat(raw.slice(0, -1).trim())
    if (!isNaN(pct)) return pct / 100
  }

  const score = parseFloat(raw)
  if (isNaN(score)) return null
  return score
}

/**
 * Get the score for a row, treating errors as 0.
 * SINGLE SOURCE OF TRUTH for error -> score conversion.
 */
export function getRowScore(
  row: SnapshotRow | null | undefined,
  metricIdx: number,
): RowScore {
  if (!row) return { score: null, isError: false }

  // Errors are always scored as 0
  if (isErrorRow(row)) {
    return { score: 0, isError: true }
  }

  const metricValues = row?.metric_values || []
  const metricValue = metricValues[metricIdx]
  const score = parseScoreValue(metricValue)
  if (score === null) {
    return { score: null, isError: false }
  }

  return { score, isError: false }
}

// ---------------------------------------------------------------------------
// Aggregation
// ---------------------------------------------------------------------------

/** Median of the finite numeric entries of `values`; 0 when none. */
export function calculateMedian(values: ReadonlyArray<unknown> | null | undefined): number {
  if (!Array.isArray(values) || values.length === 0) return 0
  const sorted = [...values]
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value))
    .sort((a, b) => a - b)
  if (sorted.length === 0) return 0

  const mid = Math.floor(sorted.length / 2)
  if (sorted.length % 2 === 0) {
    return (sorted[mid - 1] + sorted[mid]) / 2
  }
  return sorted[mid]
}

/**
 * Calculate aggregate metrics from item-level data across K runs.
 *
 * pass@K  = share of items where at least one run passed (score >= threshold)
 * pass^K  = share of items where ALL runs passed
 * max@K   = mean of each item's best score
 * consistency = mean per-item binary agreement, (2*max(pass,fail)/n)-1,
 *               items with >1 scores only; null when none qualify
 * reliability = mean pass rate over items with >1 scores AND >=1 pass;
 *               null when none qualify
 */
export function calculateItemLevelMetrics(options: ItemLevelMetricsOptions): ItemLevelMetrics {
  const { runsData, threshold, getMetricIndex, getItemId, trackDistribution } = options

  const K = runsData?.length || 0

  const result: ItemLevelMetrics = {
    passAtK: 0,
    passHatK: 0,
    maxAtK: 0,
    consistency: null,
    reliability: null,
    avgScore: 0,
    avgLatency: 0,
    medianLatency: 0,
    totalItems: 0,
    failedCount: 0,
    K: K,
    totalScoreSum: 0,
    totalScoreCount: 0,
    totalLatencySum: 0,
    totalLatencyCount: 0,
    correctDistribution: trackDistribution ? new Array<number>(K + 1).fill(0) : null,
    minScore: 0,
    stddevScore: 0,
  }

  if (!runsData || runsData.length === 0) {
    return result
  }

  // Get max items across all runs
  const maxItems = Math.max(...runsData.map((r) => (r?.snapshot?.rows || []).length))

  if (maxItems === 0) {
    return result
  }

  let passAtKCount = 0
  let passHatKCount = 0
  let totalConsistencySum = 0 // Sum of per-item consistency scores
  let totalReliabilitySum = 0 // Sum of per-item reliability (pass_count / K) for items with at least one pass
  let maxScoreSum = 0
  let totalScoreSum = 0
  let totalScoreCount = 0
  let totalLatencySum = 0
  let totalLatencyCount = 0
  const latencySamples: number[] = []
  const allScores: number[] = [] // collect all individual scores for min/stddev
  let itemsWithData = 0
  let itemsWithMultipleRuns = 0 // Only count items with K > 1 for consistency
  let itemsWithAtLeastOnePass = 0 // Items where at least one run passed (for reliability)
  let failedCount = 0 // Total number of failed attempts across all items and runs

  // Build item map for matching by ID if available
  const itemIds = new Set<string>()
  for (const runData of runsData) {
    const rows = runData?.snapshot?.rows || []
    for (const row of rows) {
      const itemId = getItemId ? getItemId(row) : String(row.index)
      itemIds.add(itemId)
    }
  }

  // Process each unique item
  for (const itemId of itemIds) {
    const scores: number[] = []

    // Get score for this item from each run
    for (const runData of runsData) {
      const rows = runData?.snapshot?.rows || []
      const row = rows.find((r) => {
        const id = getItemId ? getItemId(r) : String(r.index)
        return id === itemId
      })

      if (!row) continue

      const metricIdx = getMetricIndex(runData)
      if (metricIdx < 0) continue

      // Use centralized score extraction (errors = 0)
      const { score, isError } = getRowScore(row, metricIdx)

      if (score !== null) {
        scores.push(score)
        totalScoreSum += score
        totalScoreCount++
        allScores.push(score)
        if (isError) failedCount++
      }

      // Collect latency
      const latency = row?.latency_ms
      if (latency && latency > 0) {
        totalLatencySum += latency
        totalLatencyCount++
        latencySamples.push(latency)
      }
    }

    if (scores.length === 0) continue
    itemsWithData++

    // Calculate item-level stats
    const maxScore = Math.max(...scores)
    const numCorrect = scores.filter((s) => s >= threshold).length

    // Track distribution if requested
    if (trackDistribution && result.correctDistribution) {
      result.correctDistribution[numCorrect]++
    }

    // Max@K: track the best score for this item
    maxScoreSum += maxScore

    // Pass@K: at least one run passed for this item
    if (numCorrect > 0) passAtKCount++

    // Pass^K: ALL runs passed for this item
    const allCorrectItem = numCorrect === scores.length && scores.length > 0
    if (allCorrectItem) passHatKCount++

    // Consistency: binary agreement (do runs agree on pass/fail?)
    // Formula: 2 * max(passCount, failCount) / K - 1
    // Range: 0% (50/50 split) to 100% (all agree)
    const numScores = scores.length
    if (numScores > 1) {
      const numFail = numScores - numCorrect
      const maxAgreement = Math.max(numCorrect, numFail)
      const itemConsistency = (2 * maxAgreement) / numScores - 1
      totalConsistencySum += itemConsistency
      itemsWithMultipleRuns++

      // Reliability: when it CAN answer correctly, how often does it?
      // Formula: pass_count / K, but ONLY for items where pass_count > 0
      if (numCorrect > 0) {
        const itemReliability = numCorrect / numScores
        totalReliabilitySum += itemReliability
        itemsWithAtLeastOnePass++
      }
    }
  }

  // Calculate final stats
  result.totalItems = itemsWithData
  result.failedCount = failedCount
  result.passAtK = itemsWithData > 0 ? passAtKCount / itemsWithData : 0
  result.passHatK = itemsWithData > 0 ? passHatKCount / itemsWithData : 0
  result.maxAtK = itemsWithData > 0 ? maxScoreSum / itemsWithData : 0
  // Consistency = average of per-item binary agreement scores (requires K > 1)
  result.consistency = itemsWithMultipleRuns > 0 ? totalConsistencySum / itemsWithMultipleRuns : null
  // Reliability = average pass rate for items that CAN be solved (requires K > 1)
  result.reliability = itemsWithAtLeastOnePass > 0 ? totalReliabilitySum / itemsWithAtLeastOnePass : null
  result.avgScore = totalScoreCount > 0 ? totalScoreSum / totalScoreCount : 0
  result.avgLatency = totalLatencyCount > 0 ? totalLatencySum / totalLatencyCount : 0
  result.medianLatency = latencySamples.length > 0 ? calculateMedian(latencySamples) : 0
  result.totalScoreSum = totalScoreSum
  result.totalScoreCount = totalScoreCount
  result.totalLatencySum = totalLatencySum
  result.totalLatencyCount = totalLatencyCount
  result.minScore = allScores.length > 0 ? Math.min(...allScores) : 0
  if (allScores.length > 1) {
    const mean = totalScoreSum / allScores.length
    const sqDiffSum = allScores.reduce((sum, s) => sum + (s - mean) * (s - mean), 0)
    result.stddevScore = Math.sqrt(sqDiffSum / allScores.length)
  } else {
    result.stddevScore = 0
  }

  return result
}

const BUCKET_KEYS: OutcomeBucketKey[] = ['a_sweeps_b', 'b_sweeps_a', 'both_pass', 'both_fail']

function makeEmptyBuckets(): OutcomeBuckets {
  return BUCKET_KEYS.reduce((acc, key) => {
    acc[key] = { count: 0, percentage: 0, itemIds: [] }
    return acc
  }, {} as OutcomeBuckets)
}

/**
 * Strict grouped item outcomes for two K-run model groups.
 * Thin wrapper over {@link calculateGroupedCohortComparison}.
 */
export function calculateGroupedOutcomeBuckets(
  options: GroupedComparisonOptions | null | undefined,
): GroupedOutcomeBucketsResult {
  const grouped = calculateGroupedCohortComparison(options)
  return {
    eligibleItems: grouped.eligibleItems || 0,
    leftRunCount: grouped.leftRunCount || 0,
    rightRunCount: grouped.rightRunCount || 0,
    buckets: grouped.buckets || makeEmptyBuckets(),
  }
}

interface AggregateState {
  passAtKCount: number
  passHatKCount: number
  totalConsistencySum: number
  itemsWithMultipleRuns: number
  totalReliabilitySum: number
  itemsWithAtLeastOnePass: number
  totalScoreSum: number
  totalScoreCount: number
  totalAttemptsSum: number
  totalAttemptsCount: number
}

interface GroupValues {
  scores: number[]
  passes: boolean[]
  attempts: number[]
  rows: SnapshotRow[]
}

/**
 * Grouped cohort comparison stats for two K-run groups.
 *
 * Only items present with a non-null score in EVERY selected run are
 * eligible. Errors are treated as score 0 via {@link getRowScore}, so they
 * count as failures. Returns the all-zero default result when any input is
 * missing/invalid (empty groups, unknown run ids, missing callbacks).
 */
export function calculateGroupedCohortComparison(
  options: GroupedComparisonOptions | null | undefined,
): GroupedComparisonResult {
  const {
    runsData,
    leftRunIds,
    rightRunIds,
    threshold,
    getMetricIndex,
    getItemId,
    getRunId,
  } = options || {}

  const result: GroupedComparisonResult = {
    eligibleItems: 0,
    leftRunCount: Array.isArray(leftRunIds) ? leftRunIds.length : 0,
    rightRunCount: Array.isArray(rightRunIds) ? rightRunIds.length : 0,
    k: Array.isArray(leftRunIds) ? leftRunIds.length : 0,
    left: {
      passAtK: 0,
      passHatK: 0,
      avgAtK: 0,
      consistency: null,
      reliability: null,
      avgAttempts: 0,
    },
    right: {
      passAtK: 0,
      passHatK: 0,
      avgAtK: 0,
      consistency: null,
      reliability: null,
      avgAttempts: 0,
    },
    deltas: {
      passAtK: 0,
      passHatK: 0,
      avgAtK: 0,
      consistency: 0,
      reliability: 0,
    },
    summary: {
      improvedCount: 0,
      regressedCount: 0,
      unchangedCount: 0,
      avgAttemptsDelta: 0,
    },
    items: [],
    buckets: makeEmptyBuckets(),
  }

  if (!Array.isArray(runsData) || !runsData.length) return result
  if (!Array.isArray(leftRunIds) || !leftRunIds.length) return result
  if (!Array.isArray(rightRunIds) || !rightRunIds.length) return result
  if (typeof getMetricIndex !== 'function' || typeof getItemId !== 'function' || typeof getRunId !== 'function') {
    return result
  }

  const runMap = new Map<string, RunData | null | undefined>()
  runsData.forEach((runData) => {
    const runId = getRunId(runData)
    if (runId !== undefined && runId !== null && !runMap.has(runId)) {
      runMap.set(runId, runData)
    }
  })

  const leftRuns = leftRunIds.map((runId) => runMap.get(runId)).filter(Boolean) as RunData[]
  const rightRuns = rightRunIds.map((runId) => runMap.get(runId)).filter(Boolean) as RunData[]
  if (leftRuns.length !== leftRunIds.length || rightRuns.length !== rightRunIds.length) {
    return result
  }

  const selectedRuns = [...leftRuns, ...rightRuns]
  const itemIds = new Set<string>()
  selectedRuns.forEach((runData) => {
    const rows = runData?.snapshot?.rows || []
    rows.forEach((row) => {
      const itemId = getItemId(row)
      if (itemId !== undefined && itemId !== null && itemId !== '') itemIds.add(itemId)
    })
  })

  function makeAggregateState(): AggregateState {
    return {
      passAtKCount: 0,
      passHatKCount: 0,
      totalConsistencySum: 0,
      itemsWithMultipleRuns: 0,
      totalReliabilitySum: 0,
      itemsWithAtLeastOnePass: 0,
      totalScoreSum: 0,
      totalScoreCount: 0,
      totalAttemptsSum: 0,
      totalAttemptsCount: 0,
    }
  }

  function finalizeAggregateState(agg: AggregateState): GroupAggregate {
    return {
      passAtK: result.eligibleItems > 0 ? agg.passAtKCount / result.eligibleItems : 0,
      passHatK: result.eligibleItems > 0 ? agg.passHatKCount / result.eligibleItems : 0,
      avgAtK: agg.totalScoreCount > 0 ? agg.totalScoreSum / agg.totalScoreCount : 0,
      consistency: agg.itemsWithMultipleRuns > 0 ? agg.totalConsistencySum / agg.itemsWithMultipleRuns : null,
      reliability: agg.itemsWithAtLeastOnePass > 0 ? agg.totalReliabilitySum / agg.itemsWithAtLeastOnePass : null,
      avgAttempts: agg.totalAttemptsCount > 0 ? agg.totalAttemptsSum / agg.totalAttemptsCount : 0,
    }
  }

  function collectGroupValues(groupRuns: RunData[], itemId: string): GroupValues | null {
    const scores: number[] = []
    const passes: boolean[] = []
    const attempts: number[] = []
    const rowList: SnapshotRow[] = []
    for (const runData of groupRuns) {
      const runRows = runData?.snapshot?.rows || []
      const row = runRows.find((candidate) => getItemId!(candidate) === itemId)
      if (!row) return null
      const metricIdx = getMetricIndex!(runData)
      if (metricIdx < 0) return null
      const { score } = getRowScore(row, metricIdx)
      if (score === null) return null
      scores.push(score)
      passes.push(score >= (threshold as number))
      attempts.push(Math.max(1, Number(row?.retry_count || 0) + 1))
      rowList.push(row)
    }
    return { scores, passes, attempts, rows: rowList }
  }

  function updateAggregateState(agg: AggregateState, groupValues: GroupValues): void {
    const numCorrect = groupValues.passes.filter(Boolean).length
    const numScores = groupValues.scores.length

    agg.totalScoreSum += groupValues.scores.reduce((sum, score) => sum + score, 0)
    agg.totalScoreCount += numScores
    agg.totalAttemptsSum += groupValues.attempts.reduce((sum, attempt) => sum + attempt, 0)
    agg.totalAttemptsCount += groupValues.attempts.length

    if (numCorrect > 0) agg.passAtKCount += 1
    if (numCorrect === numScores && numScores > 0) agg.passHatKCount += 1
    if (numScores > 1) {
      const numFail = numScores - numCorrect
      const maxAgreement = Math.max(numCorrect, numFail)
      agg.totalConsistencySum += (2 * maxAgreement) / numScores - 1
      agg.itemsWithMultipleRuns += 1
      if (numCorrect > 0) {
        agg.totalReliabilitySum += numCorrect / numScores
        agg.itemsWithAtLeastOnePass += 1
      }
    }
  }

  const leftAgg = makeAggregateState()
  const rightAgg = makeAggregateState()
  let totalAttemptsDelta = 0

  itemIds.forEach((itemId) => {
    const leftValues = collectGroupValues(leftRuns, itemId)
    if (!leftValues || leftValues.scores.length !== leftRuns.length) return
    const rightValues = collectGroupValues(rightRuns, itemId)
    if (!rightValues || rightValues.scores.length !== rightRuns.length) return

    result.eligibleItems += 1
    updateAggregateState(leftAgg, leftValues)
    updateAggregateState(rightAgg, rightValues)

    const leftPassCount = leftValues.passes.filter(Boolean).length
    const rightPassCount = rightValues.passes.filter(Boolean).length
    const move = rightPassCount - leftPassCount

    if (move > 0) result.summary.improvedCount += 1
    else if (move < 0) result.summary.regressedCount += 1
    else result.summary.unchangedCount += 1

    const leftAvgAttempts = leftValues.attempts.length
      ? leftValues.attempts.reduce((sum, attempt) => sum + attempt, 0) / leftValues.attempts.length
      : 0
    const rightAvgAttempts = rightValues.attempts.length
      ? rightValues.attempts.reduce((sum, attempt) => sum + attempt, 0) / rightValues.attempts.length
      : 0
    totalAttemptsDelta += rightAvgAttempts - leftAvgAttempts

    const representativeRow = leftValues.rows.find(Boolean) || rightValues.rows.find(Boolean) || null
    result.items.push({
      itemId,
      rawItemId: representativeRow?.item_id || '',
      metadata: representativeRow?.item_metadata || {},
      leftScores: [...leftValues.scores],
      rightScores: [...rightValues.scores],
      leftPasses: leftValues.passes,
      rightPasses: rightValues.passes,
      leftAttempts: [...leftValues.attempts],
      rightAttempts: [...rightValues.attempts],
      leftPassCount,
      rightPassCount,
      leftAvgAttempts,
      rightAvgAttempts,
      move,
      bucketKey: null,
    })

    const leftAllPass = leftValues.passes.every(Boolean)
    const leftAllFail = leftValues.passes.every((value) => !value)
    const rightAllPass = rightValues.passes.every(Boolean)
    const rightAllFail = rightValues.passes.every((value) => !value)

    let bucketKey: OutcomeBucketKey | null = null
    if (leftAllPass && rightAllFail) bucketKey = 'a_sweeps_b'
    else if (leftAllFail && rightAllPass) bucketKey = 'b_sweeps_a'
    else if (leftAllPass && rightAllPass) bucketKey = 'both_pass'
    else if (leftAllFail && rightAllFail) bucketKey = 'both_fail'

    if (!bucketKey) return
    result.items[result.items.length - 1].bucketKey = bucketKey
    result.buckets[bucketKey].count += 1
    result.buckets[bucketKey].itemIds.push(itemId)
  })

  BUCKET_KEYS.forEach((key) => {
    result.buckets[key].percentage = result.eligibleItems > 0
      ? result.buckets[key].count / result.eligibleItems
      : 0
  })

  result.left = finalizeAggregateState(leftAgg)
  result.right = finalizeAggregateState(rightAgg)
  result.deltas = {
    passAtK: result.right.passAtK - result.left.passAtK,
    passHatK: result.right.passHatK - result.left.passHatK,
    avgAtK: result.right.avgAtK - result.left.avgAtK,
    consistency: (result.right.consistency ?? 0) - (result.left.consistency ?? 0),
    reliability: (result.right.reliability ?? 0) - (result.left.reliability ?? 0),
  }
  result.summary.avgAttemptsDelta = result.eligibleItems > 0 ? totalAttemptsDelta / result.eligibleItems : 0
  result.items.sort((a, b) => {
    if (b.move !== a.move) return b.move - a.move
    if (b.rightPassCount !== a.rightPassCount) return b.rightPassCount - a.rightPassCount
    if (a.leftPassCount !== b.leftPassCount) return a.leftPassCount - b.leftPassCount
    return String(a.itemId || a.rawItemId).localeCompare(String(b.itemId || b.rawItemId))
  })

  return result
}

// ---------------------------------------------------------------------------
// Metric type detection
// ---------------------------------------------------------------------------

/**
 * Detect the type of a metric from its actual values across rows.
 *   'boolean' — all values exactly 0 or 1   (display as %)
 *   'score'   — all values in [0, 1]        (display as %)
 *   'numeric' — any value > 1 or < 0        (display as raw number)
 * Empty/no parseable values defaults to 'score'.
 */
export function detectMetricType(rows: ReadonlyArray<SnapshotRow>, metricIdx: number): MetricType {
  let hasNonBinary = false
  let hasOutOfRange = false
  let count = 0

  for (const row of rows) {
    const { score } = getRowScore(row, metricIdx)
    if (score === null) continue
    count++
    if (score !== 0 && score !== 1) hasNonBinary = true
    if (score > 1 || score < 0) {
      hasOutOfRange = true
      break
    }
  }

  if (count === 0) return 'score'
  if (hasOutOfRange) return 'numeric'
  if (!hasNonBinary) return 'boolean'
  return 'score'
}

/**
 * Detect metric type from a pre-computed average value (summary-only data).
 */
export function detectMetricTypeFromAvg(avgValue: number | null | undefined): 'score' | 'numeric' {
  if (avgValue === null || avgValue === undefined || isNaN(avgValue)) return 'score'
  if (avgValue > 1 || avgValue < 0) return 'numeric'
  return 'score'
}

// ---------------------------------------------------------------------------
// Legacy formatting (kept verbatim for golden parity; the app-wide formatting
// ruleset lives in format.ts — prefer that for new UI code)
// ---------------------------------------------------------------------------

/** '0.528' -> '52.8%'; null/undefined/NaN -> em dash. */
export function formatPercent(value: number | null | undefined, decimals: number = 1): string {
  if (value === undefined || value === null || isNaN(value)) return '—'
  return (value * 100).toFixed(decimals) + '%'
}

/**
 * Legacy latency formatting. Quirks preserved: 999.5 -> '1000ms',
 * 119999 -> '1m 60s', no hours unit (3600000 -> '60m 0s'), non-positive -> '—'.
 */
export function formatLatency(ms: number | null | undefined): string {
  if (!ms || ms <= 0) return '—'
  if (ms >= 60000) {
    const minutes = Math.floor(ms / 60000)
    const seconds = (ms % 60000) / 1000
    return `${minutes}m ${seconds.toFixed(0)}s`
  } else if (ms >= 1000) {
    return `${(ms / 1000).toFixed(1)}s`
  } else {
    return `${ms.toFixed(0)}ms`
  }
}

/** Score (0..1) -> bucketed CSS class 'score-1'..'score-5' (NaN -> 'score-1'). */
export function getScoreColorClass(score: number): string {
  if (score >= 0.9) return 'score-5'
  if (score >= 0.75) return 'score-4'
  if (score >= 0.6) return 'score-3'
  if (score >= 0.4) return 'score-2'
  return 'score-1'
}

/** Tooltip copy for aggregate metrics (K runs, boolean-ness, threshold %). */
export function getMetricTooltips(K: number, isBoolean: boolean, threshold: number): MetricTooltips {
  return {
    passAtK: isBoolean
      ? `Percentage of items where at least one of the ${K} runs achieved a perfect score (100%).`
      : `Percentage of items where at least one of the ${K} runs scored ≥${threshold}%.`,
    passHatK: isBoolean
      ? `Percentage of items where all ${K} runs achieved a perfect score (100%).`
      : `Percentage of items where all ${K} runs scored ≥${threshold}%.`,
    maxAtK: `Average of the best score across all ${K} runs for each item.`,
    consistency: `Measures how often runs agree on pass/fail across ${K} runs. 100% = all runs agree, 0% = 50/50 split.`,
    reliability: `When an item CAN be solved, how often is it? Only includes items with at least one passing run.`,
    failedCount: `Number of runs that threw an error (across all items). Errors are scored as 0%.`,
    avgScore: `The mean score across all items and all runs.`,
    avgLatency: `The mean response time across all items and all runs.`,
    medianLatency: `The median response time across all items and all runs. Less sensitive to outliers than the mean.`,
  }
}

/** Format a metric value according to its detected type. */
export function formatMetricValue(
  value: number | null | undefined,
  metricType: MetricType,
  decimals?: number,
): string {
  if (value === undefined || value === null || isNaN(value)) return '—'
  if (metricType === 'numeric') {
    return formatNumericValue(value)
  }
  return formatPercent(value, decimals)
}

/**
 * Pick the smallest decimal count (default..max) that renders `value`
 * distinctly from all of its peers; falls back to `maxDecimals`.
 * (Internal helper in the legacy module; exported here for reuse.)
 */
export function pickAdaptiveDecimals(
  value: number,
  peerValues: ReadonlyArray<number | null | undefined> | null | undefined,
  formatWithDecimals: (value: number, decimals: number) => string,
  defaultDecimals: number = 1,
  maxDecimals: number = 3,
): number {
  const peers = Array.isArray(peerValues)
    ? (peerValues.filter(
        (peer) => peer !== undefined && peer !== null && !isNaN(peer) && peer !== value,
      ) as number[])
    : []
  if (peers.length === 0) return defaultDecimals

  for (let decimals = defaultDecimals; decimals <= maxDecimals; decimals++) {
    const formatted = formatWithDecimals(value, decimals)
    const hasCollision = peers.some((peer) => formatWithDecimals(peer, decimals) === formatted)
    if (!hasCollision) return decimals
  }

  return maxDecimals
}

/**
 * Format a metric value, adaptively increasing precision until it does not
 * collide with any peer value's rendering.
 */
export function formatMetricValueSmart(
  value: number | null | undefined,
  metricType: MetricType,
  peerValues: ReadonlyArray<number | null | undefined> | null | undefined,
  defaultDecimals: number = 1,
  maxDecimals: number = 3,
): string {
  if (value === undefined || value === null || isNaN(value)) return '—'
  if (metricType === 'numeric') {
    const decimals = pickAdaptiveDecimals(
      value,
      peerValues,
      (candidate, precision) => formatNumericValue(candidate, precision),
      Number.isInteger(value) ? 0 : defaultDecimals,
      maxDecimals,
    )
    return formatNumericValue(value, decimals)
  }

  const decimals = pickAdaptiveDecimals(
    value,
    peerValues,
    (candidate, precision) => formatPercent(candidate, precision),
    defaultDecimals,
    maxDecimals,
  )
  return formatPercent(value, decimals)
}

/**
 * Raw numeric value with abbreviation: >=1M -> '1.2M', >=10K -> '12.3K',
 * >=1000 -> '1,234', integers verbatim, else `toFixed(decimals)`.
 */
export function formatNumericValue(value: number | null | undefined, decimals: number = 1): string {
  if (value === undefined || value === null || isNaN(value)) return '—'
  const abs = Math.abs(value)
  if (abs >= 1000000) return (value / 1000000).toFixed(1) + 'M'
  if (abs >= 10000) return (value / 1000).toFixed(1) + 'K'
  if (abs >= 1000) return value.toLocaleString('en-US', { maximumFractionDigits: 0 })
  if (Number.isInteger(value)) return value.toString()
  return value.toFixed(decimals)
}

/**
 * CSS color class for a metric value, respecting its type.
 * Numeric metrics get no color class (no intrinsic good/bad scale).
 */
export function getMetricColorClass(value: number, metricType: MetricType): string {
  if (metricType === 'numeric') return ''
  return getScoreColorClass(value)
}
