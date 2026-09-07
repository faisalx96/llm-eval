/**
 * Shared metrics calculation utilities for قيِّم Dashboard
 *
 * This module provides consistent metric calculations across:
 * - Compare view
 * - Models view
 * - Aggregate publish
 *
 * IMPORTANT: Error handling is centralized here. Errors are treated as 0% score.
 */

/**
 * Check if a row represents an error/failed item
 * @param {Object} row - Row data from snapshot
 * @returns {boolean} True if the row is an error
 */
function isErrorRow(row) {
  if (!row) return false;
  const status = row.status;
  return status === 'error' || status === 'failed';
}

/**
 * Get the score for a row, treating errors as 0
 * This is the SINGLE SOURCE OF TRUTH for error -> score conversion
 * @param {Object} row - Row data from snapshot
 * @param {number} metricIdx - Index of the metric in metric_values array
 * @returns {{score: number|null, isError: boolean}} Score (0 for errors) and error flag
 */
function parseScoreValue(metricValue) {
  if (metricValue === undefined || metricValue === null) return null;
  if (typeof metricValue === 'number') {
    return Number.isFinite(metricValue) ? metricValue : null;
  }
  if (typeof metricValue === 'boolean') {
    return metricValue ? 1 : 0;
  }

  const raw = String(metricValue).trim();
  if (!raw) return null;

  const lowered = raw.toLowerCase();
  if (lowered === 'n/a' || lowered === 'na' || lowered === 'none' || lowered === 'null') {
    return null;
  }
  if (raw === '✓' || lowered === 'true' || lowered === 'yes' || lowered === 'y') {
    return 1;
  }
  if (raw === '✗' || lowered === 'false' || lowered === 'no' || lowered === 'n') {
    return 0;
  }

  if (raw.endsWith('%')) {
    const pct = parseFloat(raw.slice(0, -1).trim());
    if (!isNaN(pct)) return pct / 100;
  }

  const score = parseFloat(raw);
  if (isNaN(score)) return null;
  return score;
}

function getRowScore(row, metricIdx) {
  if (!row) return { score: null, isError: false };

  // Errors are always scored as 0
  if (isErrorRow(row)) {
    return { score: 0, isError: true };
  }

  const metricValues = row?.metric_values || [];
  const metricValue = metricValues[metricIdx];
  const score = parseScoreValue(metricValue);
  if (score === null) {
    return { score: null, isError: false };
  }

  return { score, isError: false };
}

/** Index rows using the same first-match identity semantics as Array.find. */
function indexRowsById(rows, getItemId) {
  const index = new Map();
  for (const row of rows || []) {
    const id = getItemId(row);
    // Array.find uses strict equality: NaN never matches, and duplicates use
    // the first row. Keep both rules when indexing arbitrary item identities.
    if (id === id && !index.has(id)) index.set(id, row);
  }
  return index;
}

/**
 * Calculate aggregate metrics from item-level data across K runs
 *
 * @param {Object} options - Calculation options
 * @param {Array} options.runsData - Array of run data objects with snapshot.rows
 * @param {string} options.metricName - Name of the metric to calculate
 * @param {number} options.threshold - Threshold for "passing" (0-1)
 * @param {Function} options.getMetricIndex - Function to get metric index from run data
 * @param {Function} [options.getItemId] - Optional function to get item ID from row (defaults to index)
 * @param {boolean} [options.trackDistribution] - If true, track correctDistribution array
 * @returns {Object} Calculated metrics
 */
function calculateItemLevelMetrics(options) {
  const { runsData, metricName, threshold, getMetricIndex, getItemId, trackDistribution } = options;

  const K = runsData?.length || 0;

  const result = {
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
    correctDistribution: trackDistribution ? new Array(K + 1).fill(0) : null,
    minScore: 0,
    stddevScore: 0
  };

  if (!runsData || runsData.length === 0) {
    return result;
  }

  // Get max items across all runs
  const maxItems = Math.max(...runsData.map(r => (r?.snapshot?.rows || []).length));

  if (maxItems === 0) {
    return result;
  }

  let passAtKCount = 0;
  let passHatKCount = 0;
  let totalConsistencySum = 0;  // Sum of per-item consistency scores
  let totalReliabilitySum = 0;  // Sum of per-item reliability (pass_count / K) for items with at least one pass
  let maxScoreSum = 0;
  let totalScoreSum = 0;
  let totalScoreCount = 0;
  let totalLatencySum = 0;
  let totalLatencyCount = 0;
  let latencySamples = [];
  let allScores = [];  // collect all individual scores for min/stddev
  let itemsWithData = 0;
  let itemsWithMultipleRuns = 0;  // Only count items with K > 1 for consistency
  let itemsWithAtLeastOnePass = 0;  // Items where at least one run passed (for reliability)
  let failedCount = 0;  // Total number of failed attempts across all items and runs

  // Build item map for matching by ID if available
  const itemIds = new Set();
  const rowIndexes = new Map();
  const rowId = getItemId || (row => String(row.index));
  for (const runData of runsData) {
    const rows = runData?.snapshot?.rows || [];
    rowIndexes.set(runData, indexRowsById(rows, rowId));
    for (const row of rows) {
      const itemId = getItemId ? getItemId(row) : String(row.index);
      itemIds.add(itemId);
    }
  }

  // Process each unique item
  for (const itemId of itemIds) {
    const scores = [];

    // Get score for this item from each run
    for (const runData of runsData) {
      const row = rowIndexes.get(runData).get(itemId);

      if (!row) continue;

      const metricIdx = getMetricIndex(runData);
      if (metricIdx < 0) continue;

      // Use centralized score extraction (errors = 0)
      const { score, isError } = getRowScore(row, metricIdx);

      if (score !== null) {
        scores.push(score);
        totalScoreSum += score;
        totalScoreCount++;
        allScores.push(score);
        if (isError) failedCount++;
      }

      // Collect latency
      const latency = row?.latency_ms;
      if (latency && latency > 0) {
        totalLatencySum += latency;
        totalLatencyCount++;
        latencySamples.push(latency);
      }
    }

    if (scores.length === 0) continue;
    itemsWithData++;

    // Calculate item-level stats
    const maxScore = Math.max(...scores);
    const numCorrect = scores.filter(s => s >= threshold).length;

    // Track distribution if requested
    if (trackDistribution && result.correctDistribution) {
      result.correctDistribution[numCorrect]++;
    }

    // Max@K: track the best score for this item
    maxScoreSum += maxScore;

    // Pass@K: at least one run passed for this item
    if (numCorrect > 0) passAtKCount++;

    // Pass^K: ALL runs passed for this item
    const allCorrectItem = numCorrect === scores.length && scores.length > 0;
    if (allCorrectItem) passHatKCount++;

    // Consistency: binary agreement (do runs agree on pass/fail?)
    // Formula: 2 * max(passCount, failCount) / K - 1
    // Range: 0% (50/50 split) to 100% (all agree)
    const numScores = scores.length;
    if (numScores > 1) {
      const numFail = numScores - numCorrect;
      const maxAgreement = Math.max(numCorrect, numFail);
      const itemConsistency = (2 * maxAgreement / numScores) - 1;
      totalConsistencySum += itemConsistency;
      itemsWithMultipleRuns++;

      // Reliability: when it CAN answer correctly, how often does it?
      // Formula: pass_count / K, but ONLY for items where pass_count > 0
      if (numCorrect > 0) {
        const itemReliability = numCorrect / numScores;
        totalReliabilitySum += itemReliability;
        itemsWithAtLeastOnePass++;
      }
    }
  }

  // Calculate final stats
  result.totalItems = itemsWithData;
  result.failedCount = failedCount;
  result.passAtK = itemsWithData > 0 ? passAtKCount / itemsWithData : 0;
  result.passHatK = itemsWithData > 0 ? passHatKCount / itemsWithData : 0;
  result.maxAtK = itemsWithData > 0 ? maxScoreSum / itemsWithData : 0;
  // Consistency = average of per-item binary agreement scores (requires K > 1)
  result.consistency = itemsWithMultipleRuns > 0 ? totalConsistencySum / itemsWithMultipleRuns : null;
  // Reliability = average pass rate for items that CAN be solved (requires K > 1)
  result.reliability = itemsWithAtLeastOnePass > 0 ? totalReliabilitySum / itemsWithAtLeastOnePass : null;
  result.avgScore = totalScoreCount > 0 ? totalScoreSum / totalScoreCount : 0;
  result.avgLatency = totalLatencyCount > 0 ? totalLatencySum / totalLatencyCount : 0;
  result.medianLatency = latencySamples.length > 0 ? calculateMedian(latencySamples) : 0;
  result.totalScoreSum = totalScoreSum;
  result.totalScoreCount = totalScoreCount;
  result.totalLatencySum = totalLatencySum;
  result.totalLatencyCount = totalLatencyCount;
  result.minScore = allScores.length > 0 ? Math.min(...allScores) : 0;
  if (allScores.length > 1) {
    const mean = totalScoreSum / allScores.length;
    const sqDiffSum = allScores.reduce((sum, s) => sum + (s - mean) * (s - mean), 0);
    result.stddevScore = Math.sqrt(sqDiffSum / allScores.length);
  } else {
    result.stddevScore = 0;
  }

  return result;
}

function calculateMedian(values) {
  if (!Array.isArray(values) || values.length === 0) return 0;
  const sorted = [...values]
    .map(value => Number(value))
    .filter(value => Number.isFinite(value))
    .sort((a, b) => a - b);
  if (sorted.length === 0) return 0;

  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 0) {
    return (sorted[mid - 1] + sorted[mid]) / 2;
  }
  return sorted[mid];
}

/**
 * Calculate strict grouped item outcomes for two K-run model groups.
 *
 * Only items present with a non-null score in all selected runs are eligible.
 * Errors are treated as score 0 via getRowScore(), so they count as failures.
 *
 * @param {Object} options
 * @param {Array} options.runsData
 * @param {Array<string>} options.leftRunIds
 * @param {Array<string>} options.rightRunIds
 * @param {number} options.threshold
 * @param {Function} options.getMetricIndex
 * @param {Function} options.getItemId
 * @param {Function} options.getRunId
 * @returns {Object}
 */
function calculateGroupedOutcomeBuckets(options) {
  const grouped = calculateGroupedCohortComparison(options);
  return {
    eligibleItems: grouped.eligibleItems || 0,
    leftRunCount: grouped.leftRunCount || 0,
    rightRunCount: grouped.rightRunCount || 0,
    buckets: grouped.buckets || {
      a_sweeps_b: { count: 0, percentage: 0, itemIds: [] },
      b_sweeps_a: { count: 0, percentage: 0, itemIds: [] },
      both_pass: { count: 0, percentage: 0, itemIds: [] },
      both_fail: { count: 0, percentage: 0, itemIds: [] },
    },
  };
}

/**
 * Calculate grouped cohort comparison stats for two K-run groups.
 *
 * Only items present with a non-null score in every selected run are eligible.
 * Errors are treated as score 0 via getRowScore(), so they count as failures.
 *
 * @param {Object} options
 * @param {Array} options.runsData
 * @param {Array<string>} options.leftRunIds
 * @param {Array<string>} options.rightRunIds
 * @param {number} options.threshold
 * @param {Function} options.getMetricIndex
 * @param {Function} options.getItemId
 * @param {Function} options.getRunId
 * @returns {Object}
 */
function calculateGroupedCohortComparison(options) {
  const {
    runsData,
    leftRunIds,
    rightRunIds,
    threshold,
    getMetricIndex,
    getItemId,
    getRunId,
    metricName,
  } = options || {};

  const bucketKeys = ['a_sweeps_b', 'b_sweeps_a', 'both_pass', 'both_fail'];
  const result = {
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
    buckets: bucketKeys.reduce((acc, key) => {
      acc[key] = { count: 0, percentage: 0, itemIds: [] };
      return acc;
    }, {}),
  };

  if (!Array.isArray(runsData) || !runsData.length) return result;
  if (!Array.isArray(leftRunIds) || !leftRunIds.length) return result;
  if (!Array.isArray(rightRunIds) || !rightRunIds.length) return result;
  if (typeof getMetricIndex !== 'function' || typeof getItemId !== 'function' || typeof getRunId !== 'function') {
    return result;
  }

  const runMap = new Map();
  runsData.forEach((runData) => {
    const runId = getRunId(runData);
    if (runId !== undefined && runId !== null && !runMap.has(runId)) {
      runMap.set(runId, runData);
    }
  });

  const leftRuns = leftRunIds.map(runId => runMap.get(runId)).filter(Boolean);
  const rightRuns = rightRunIds.map(runId => runMap.get(runId)).filter(Boolean);
  if (leftRuns.length !== leftRunIds.length || rightRuns.length !== rightRunIds.length) {
    return result;
  }

  // Cohort size counts passes, not runs: a samples=9 repeat run contributes
  // nine entries per item once its per-pass scores are exploded below.
  const sideSampleCount = runs => runs.reduce(
    (sum, runData) => sum + Math.max(1, Number(runData?.run?.samples || 1)), 0,
  );
  result.leftRunCount = sideSampleCount(leftRuns);
  result.rightRunCount = sideSampleCount(rightRuns);
  result.k = result.leftRunCount;

  const selectedRuns = [...leftRuns, ...rightRuns];
  const itemIds = new Set();
  const rowIndexes = new Map();
  selectedRuns.forEach((runData) => {
    const rows = runData?.snapshot?.rows || [];
    rowIndexes.set(runData, indexRowsById(rows, getItemId));
    rows.forEach((row) => {
      const itemId = getItemId(row);
      if (itemId !== undefined && itemId !== null && itemId !== '') itemIds.add(itemId);
    });
  });

  function makeAggregateState() {
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
    };
  }

  function finalizeAggregateState(agg) {
    return {
      passAtK: result.eligibleItems > 0 ? agg.passAtKCount / result.eligibleItems : 0,
      passHatK: result.eligibleItems > 0 ? agg.passHatKCount / result.eligibleItems : 0,
      avgAtK: agg.totalScoreCount > 0 ? agg.totalScoreSum / agg.totalScoreCount : 0,
      consistency: agg.itemsWithMultipleRuns > 0 ? agg.totalConsistencySum / agg.itemsWithMultipleRuns : null,
      reliability: agg.itemsWithAtLeastOnePass > 0 ? agg.totalReliabilitySum / agg.itemsWithAtLeastOnePass : null,
      avgAttempts: agg.totalAttemptsCount > 0 ? agg.totalAttemptsSum / agg.totalAttemptsCount : 0,
    };
  }

  function collectGroupValues(groupRuns, itemId) {
    const scores = [];
    const passes = [];
    const attempts = [];
    const rowList = [];
    for (const runData of groupRuns) {
      const row = rowIndexes.get(runData).get(itemId);
      if (!row) return null;
      const metricIdx = getMetricIndex(runData);
      if (metricIdx < 0) return null;
      // Repeat runs carry per-pass scores; each pass joins the cohort as its
      // own entry so pass@k / noise math sees all of them, not the reduced
      // mean. Falls back to the single reduced score when unavailable.
      const perPass = metricName && row?.pass_scores ? row.pass_scores[metricName] : null;
      const cleanPasses = Array.isArray(perPass)
        ? perPass.map(Number).filter(value => Number.isFinite(value))
        : [];
      if (cleanPasses.length) {
        const attempt = Math.max(1, Number(row?.retry_count || 0) + 1);
        cleanPasses.forEach((value) => {
          scores.push(value);
          passes.push(value >= threshold);
          attempts.push(attempt);
        });
        rowList.push(row);
        continue;
      }
      const { score } = getRowScore(row, metricIdx);
      if (score === null) return null;
      scores.push(score);
      passes.push(score >= threshold);
      attempts.push(Math.max(1, Number(row?.retry_count || 0) + 1));
      rowList.push(row);
    }
    return { scores, passes, attempts, rows: rowList };
  }

  function updateAggregateState(agg, groupValues) {
    const numCorrect = groupValues.passes.filter(Boolean).length;
    const numScores = groupValues.scores.length;

    agg.totalScoreSum += groupValues.scores.reduce((sum, score) => sum + score, 0);
    agg.totalScoreCount += numScores;
    agg.totalAttemptsSum += groupValues.attempts.reduce((sum, attempt) => sum + attempt, 0);
    agg.totalAttemptsCount += groupValues.attempts.length;

    if (numCorrect > 0) agg.passAtKCount += 1;
    if (numCorrect === numScores && numScores > 0) agg.passHatKCount += 1;
    if (numScores > 1) {
      const numFail = numScores - numCorrect;
      const maxAgreement = Math.max(numCorrect, numFail);
      agg.totalConsistencySum += (2 * maxAgreement / numScores) - 1;
      agg.itemsWithMultipleRuns += 1;
      if (numCorrect > 0) {
        agg.totalReliabilitySum += numCorrect / numScores;
        agg.itemsWithAtLeastOnePass += 1;
      }
    }
  }

  const leftAgg = makeAggregateState();
  const rightAgg = makeAggregateState();
  let totalAttemptsDelta = 0;

  itemIds.forEach((itemId) => {
    const leftValues = collectGroupValues(leftRuns, itemId);
    if (!leftValues || leftValues.scores.length < leftRuns.length) return;
    const rightValues = collectGroupValues(rightRuns, itemId);
    if (!rightValues || rightValues.scores.length < rightRuns.length) return;

    result.eligibleItems += 1;
    updateAggregateState(leftAgg, leftValues);
    updateAggregateState(rightAgg, rightValues);

    const leftPassCount = leftValues.passes.filter(Boolean).length;
    const rightPassCount = rightValues.passes.filter(Boolean).length;
    const move = rightPassCount - leftPassCount;

    if (move > 0) result.summary.improvedCount += 1;
    else if (move < 0) result.summary.regressedCount += 1;
    else result.summary.unchangedCount += 1;

    const leftAvgAttempts = leftValues.attempts.length
      ? leftValues.attempts.reduce((sum, attempt) => sum + attempt, 0) / leftValues.attempts.length
      : 0;
    const rightAvgAttempts = rightValues.attempts.length
      ? rightValues.attempts.reduce((sum, attempt) => sum + attempt, 0) / rightValues.attempts.length
      : 0;
    totalAttemptsDelta += rightAvgAttempts - leftAvgAttempts;

    const representativeRow = leftValues.rows.find(Boolean) || rightValues.rows.find(Boolean) || null;
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
    });

    const leftAllPass = leftValues.passes.every(Boolean);
    const leftAllFail = leftValues.passes.every(value => !value);
    const rightAllPass = rightValues.passes.every(Boolean);
    const rightAllFail = rightValues.passes.every(value => !value);

    let bucketKey = null;
    if (leftAllPass && rightAllFail) bucketKey = 'a_sweeps_b';
    else if (leftAllFail && rightAllPass) bucketKey = 'b_sweeps_a';
    else if (leftAllPass && rightAllPass) bucketKey = 'both_pass';
    else if (leftAllFail && rightAllFail) bucketKey = 'both_fail';

    if (!bucketKey) return;
    result.items[result.items.length - 1].bucketKey = bucketKey;
    result.buckets[bucketKey].count += 1;
    result.buckets[bucketKey].itemIds.push(itemId);
  });

  bucketKeys.forEach((key) => {
    result.buckets[key].percentage = result.eligibleItems > 0
      ? result.buckets[key].count / result.eligibleItems
      : 0;
  });

  result.left = finalizeAggregateState(leftAgg);
  result.right = finalizeAggregateState(rightAgg);
  result.deltas = {
    passAtK: result.right.passAtK - result.left.passAtK,
    passHatK: result.right.passHatK - result.left.passHatK,
    avgAtK: result.right.avgAtK - result.left.avgAtK,
    consistency: (result.right.consistency ?? 0) - (result.left.consistency ?? 0),
    reliability: (result.right.reliability ?? 0) - (result.left.reliability ?? 0),
  };
  result.summary.avgAttemptsDelta = result.eligibleItems > 0 ? totalAttemptsDelta / result.eligibleItems : 0;
  result.items.sort((a, b) => {
    if (b.move !== a.move) return b.move - a.move;
    if (b.rightPassCount !== a.rightPassCount) return b.rightPassCount - a.rightPassCount;
    if (a.leftPassCount !== b.leftPassCount) return a.leftPassCount - b.leftPassCount;
    return String(a.itemId || a.rawItemId).localeCompare(String(b.itemId || b.rawItemId));
  });

  return result;
}

/**
 * Format a decimal as a percentage string
 * @param {number} value - Value between 0 and 1
 * @param {number} [decimals=1] - Number of decimal places
 * @returns {string} Formatted percentage
 */
function formatPercent(value, decimals = 1) {
  if (value === undefined || value === null || isNaN(value)) return '—';
  return (value * 100).toFixed(decimals) + '%';
}

/**
 * Format latency in human-readable form
 * @param {number} ms - Latency in milliseconds
 * @returns {string} Formatted latency string
 */
function formatLatency(ms) {
  if (!ms || ms <= 0) return '—';
  if (ms >= 60000) {
    const totalSeconds = Math.round(ms / 1000);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return seconds ? `${minutes}m ${seconds}s` : `${minutes}m`;
  } else if (ms >= 1000) {
    return `${(ms / 1000).toFixed(1)}s`;
  } else {
    return `${ms.toFixed(0)}ms`;
  }
}

/**
 * Get CSS class for score coloring
 * @param {number} score - Score between 0 and 1
 * @returns {string} CSS class name
 */
function getScoreColorClass(score) {
  if (score >= 0.9) return 'score-5';
  if (score >= 0.75) return 'score-4';
  if (score >= 0.6) return 'score-3';
  if (score >= 0.4) return 'score-2';
  return 'score-1';
}

/**
 * Generate tooltip definitions for aggregate metrics
 * @param {number} K - Number of runs
 * @param {boolean} isBoolean - Whether metric is boolean (0/1)
 * @param {number} threshold - Threshold percentage (0-100)
 * @returns {Object} Tooltip definitions
 */
function getMetricTooltips(K, isBoolean, threshold) {
  const correctDef = isBoolean ? '100%' : `≥${threshold}%`;

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
    medianLatency: `The median response time across all items and all runs. Less sensitive to outliers than the mean.`
  };
}

/**
 * Detect the type of a metric from its actual values across rows.
 *
 * Types:
 *   'boolean'  — all values are exactly 0 or 1  (display as %)
 *   'score'    — all values in [0, 1] range      (display as %)
 *   'numeric'  — any value > 1 or < 0            (display as raw number)
 *
 * @param {Array} rows  - Snapshot rows
 * @param {number} metricIdx - Index in metric_values
 * @returns {'boolean'|'score'|'numeric'}
 */
function detectMetricType(rows, metricIdx) {
  let hasNonBinary = false;
  let hasOutOfRange = false;
  let count = 0;

  for (const row of rows) {
    const { score } = getRowScore(row, metricIdx);
    if (score === null) continue;
    count++;
    if (score !== 0 && score !== 1) hasNonBinary = true;
    if (score > 1 || score < 0) { hasOutOfRange = true; break; }
  }

  if (count === 0) return 'score';
  if (hasOutOfRange) return 'numeric';
  if (!hasNonBinary) return 'boolean';
  return 'score';
}

/**
 * Detect metric type from a pre-computed average value.
 * Used when only summary data is available (e.g. dashboard list).
 * @param {number} avgValue
 * @returns {'score'|'numeric'}
 */
function detectMetricTypeFromAvg(avgValue) {
  if (avgValue === null || avgValue === undefined || isNaN(avgValue)) return 'score';
  if (avgValue > 1 || avgValue < 0) return 'numeric';
  return 'score';
}

/** Map an authoritative API metric spec to the dashboard's presentation type. */
function metricTypeFromSpec(spec, fallbackValue) {
  const scoreType = spec && spec.score_type;
  if (scoreType === 'boolean') return 'boolean';
  if (scoreType === 'percentage') return 'score';
  if (scoreType === 'count' || scoreType === 'number') return 'numeric';
  return detectMetricTypeFromAvg(fallbackValue);
}

/** Format a single, unreduced metric observation. */
function formatMetricObservation(value, metricType, spec) {
  if (value === undefined || value === null || isNaN(value)) return '\u2014';
  if (metricType === 'boolean') return Number(value) === 1 ? 'True' : 'False';
  const precision = spec && Number.isInteger(spec.precision) ? spec.precision : undefined;
  const formatted = formatMetricValue(value, metricType, precision);
  return spec && spec.unit && metricType === 'numeric' ? `${formatted} ${spec.unit}` : formatted;
}

/**
 * Format a metric value according to its type.
 * @param {number} value
 * @param {'boolean'|'score'|'numeric'} metricType
 * @param {number} [decimals=1]
 * @returns {string}
 */
function formatMetricValue(value, metricType, decimals) {
  if (value === undefined || value === null || isNaN(value)) return '\u2014';
  if (metricType === 'numeric') {
    return formatNumericValue(value);
  }
  return formatPercent(value, decimals);
}

function pickAdaptiveDecimals(value, peerValues, formatWithDecimals, defaultDecimals = 1, maxDecimals = 3) {
  const peers = Array.isArray(peerValues)
    ? peerValues.filter(peer => peer !== undefined && peer !== null && !isNaN(peer) && peer !== value)
    : [];
  if (peers.length === 0) return defaultDecimals;

  for (let decimals = defaultDecimals; decimals <= maxDecimals; decimals++) {
    const formatted = formatWithDecimals(value, decimals);
    const hasCollision = peers.some(peer => formatWithDecimals(peer, decimals) === formatted);
    if (!hasCollision) return decimals;
  }

  return maxDecimals;
}

function formatMetricValueSmart(value, metricType, peerValues, defaultDecimals = 1, maxDecimals = 3) {
  if (value === undefined || value === null || isNaN(value)) return '\u2014';
  if (metricType === 'numeric') {
    const decimals = pickAdaptiveDecimals(
      value,
      peerValues,
      (candidate, precision) => formatNumericValue(candidate, precision),
      Number.isInteger(value) ? 0 : defaultDecimals,
      maxDecimals,
    );
    return formatNumericValue(value, decimals);
  }

  const decimals = pickAdaptiveDecimals(
    value,
    peerValues,
    (candidate, precision) => formatPercent(candidate, precision),
    defaultDecimals,
    maxDecimals,
  );
  return formatPercent(value, decimals);
}

/**
 * Format a raw numeric value with appropriate precision and abbreviation.
 * @param {number} value
 * @returns {string}
 */
function formatNumericValue(value, decimals = 1) {
  if (value === undefined || value === null || isNaN(value)) return '\u2014';
  const abs = Math.abs(value);
  if (abs >= 1000000) return (value / 1000000).toFixed(1) + 'M';
  if (abs >= 10000) return (value / 1000).toFixed(1) + 'K';
  if (abs >= 1000) return value.toLocaleString('en-US', { maximumFractionDigits: 0 });
  if (Number.isInteger(value)) return value.toString();
  return value.toFixed(decimals);
}

/**
 * Get CSS color class for a metric value, respecting its type.
 * Numeric metrics get no color class (they have no intrinsic good/bad scale).
 * @param {number} value
 * @param {'boolean'|'score'|'numeric'} metricType
 * @returns {string}
 */
function getMetricColorClass(value, metricType) {
  if (metricType === 'numeric') return '';
  return getScoreColorClass(value);
}

// Export for use in other modules (if using ES modules)
if (typeof window !== 'undefined') {
  window.QymMetrics = {
    // Core error handling - USE THESE for consistent error treatment
    isErrorRow,
    getRowScore,
    parseScoreValue,
    indexRowsById,
    // Metrics calculation
    calculateItemLevelMetrics,
    calculateGroupedOutcomeBuckets,
    calculateGroupedCohortComparison,
    calculateMedian,
    // Type detection
    detectMetricType,
    detectMetricTypeFromAvg,
    metricTypeFromSpec,
    // Formatting utilities
    formatPercent,
    formatMetricValue,
    formatMetricObservation,
    formatMetricValueSmart,
    formatNumericValue,
    formatLatency,
    getScoreColorClass,
    getMetricColorClass,
    getMetricTooltips
  };
}
