/**
 * Shared metrics calculation utilities for LLM Eval Dashboard
 *
 * This module provides consistent metric calculations across:
 * - Compare view
 * - Models view
 * - Aggregate publish
 */

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
    consistency: 0,
    reliability: 0,
    avgScore: 0,
    avgLatency: 0,
    totalItems: 0,
    K: K,
    totalScoreSum: 0,
    totalScoreCount: 0,
    totalLatencySum: 0,
    totalLatencyCount: 0,
    correctDistribution: trackDistribution ? new Array(K + 1).fill(0) : null
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
  let totalReliabilitySum = 0;  // Sum of per-item reliability (pass_count / K)
  let maxScoreSum = 0;
  let totalScoreSum = 0;
  let totalScoreCount = 0;
  let totalLatencySum = 0;
  let totalLatencyCount = 0;
  let itemsWithData = 0;
  let itemsWithMultipleRuns = 0;  // Only count items with K > 1 for consistency

  // Build item map for matching by ID if available
  const itemIds = new Set();
  for (const runData of runsData) {
    const rows = runData?.snapshot?.rows || [];
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
      const rows = runData?.snapshot?.rows || [];
      const row = rows.find(r => {
        const id = getItemId ? getItemId(r) : String(r.index);
        return id === itemId;
      });

      if (!row) continue;

      const metricIdx = getMetricIndex(runData);
      if (metricIdx < 0) continue;

      const metricValues = row?.metric_values || [];
      const metricValue = metricValues[metricIdx];

      if (metricValue !== undefined && metricValue !== null) {
        const score = parseFloat(metricValue);
        if (!isNaN(score)) {
          scores.push(score);
          totalScoreSum += score;
          totalScoreCount++;
        }
      }

      // Collect latency
      const latency = row?.latency_ms;
      if (latency && latency > 0) {
        totalLatencySum += latency;
        totalLatencyCount++;
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

      // Reliability: average pass rate per item
      // Formula: pass_count / K for each item, then average
      const itemReliability = numCorrect / numScores;
      totalReliabilitySum += itemReliability;
    }
  }

  // Calculate final stats
  result.totalItems = itemsWithData;
  result.passAtK = itemsWithData > 0 ? passAtKCount / itemsWithData : 0;
  result.passHatK = itemsWithData > 0 ? passHatKCount / itemsWithData : 0;
  result.maxAtK = itemsWithData > 0 ? maxScoreSum / itemsWithData : 0;
  // Consistency = average of per-item binary agreement scores
  result.consistency = itemsWithMultipleRuns > 0 ? totalConsistencySum / itemsWithMultipleRuns : 0;
  // Reliability = average of per-item pass rates
  result.reliability = itemsWithMultipleRuns > 0 ? totalReliabilitySum / itemsWithMultipleRuns : 0;
  result.avgScore = totalScoreCount > 0 ? totalScoreSum / totalScoreCount : 0;
  result.avgLatency = totalLatencyCount > 0 ? totalLatencySum / totalLatencyCount : 0;
  result.totalScoreSum = totalScoreSum;
  result.totalScoreCount = totalScoreCount;
  result.totalLatencySum = totalLatencySum;
  result.totalLatencyCount = totalLatencyCount;

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
    const minutes = Math.floor(ms / 60000);
    const seconds = (ms % 60000) / 1000;
    return `${minutes}m ${seconds.toFixed(0)}s`;
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
  if (score >= 0.8) return 'score-high';
  if (score >= 0.5) return 'score-medium';
  return 'score-low';
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
    reliability: `Average pass rate per item across ${K} runs. 100% = all runs pass on every item, 0% = no runs pass.`,
    avgScore: `The mean score across all items and all runs.`,
    avgLatency: `The mean response time across all items and all runs.`
  };
}

// Export for use in other modules (if using ES modules)
if (typeof window !== 'undefined') {
  window.LLMEvalMetrics = {
    calculateItemLevelMetrics,
    formatPercent,
    formatLatency,
    getScoreColorClass,
    getMetricTooltips
  };
}
