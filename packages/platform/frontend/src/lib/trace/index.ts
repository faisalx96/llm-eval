/**
 * Pure trace-viewer logic ported from
 * qym_platform/_static/dashboard/trace_viewer.js. See each module for the
 * legacy line ranges the algorithms came from.
 */

export { normalizeAttempts, selectAttempt } from './attempts'
export {
  SPAN_KIND_HUES,
  classifySpan,
  extractErrorInfo,
  extractMessages,
  extractReasoning,
  extractScores,
  isErrorSpan,
  spanCost,
  spanHasReasoning,
  spanModel,
  spanReasoningTokens,
  spanStatus,
  spanTokens,
} from './spans'
export type { SpanMessage, SpanMessageToolCall } from './spans'
export {
  aggregateStats,
  buildSpanTree,
  countRealErrors,
  detectRetries,
  expandableSpanIds,
  extractErrorInfoDeep,
  flattenVisibleNodes,
  overlapRatio,
  subtreeHasError,
} from './tree'
export type { RetryMarkers, TraceAggregates } from './tree'
export { MIN_BAR_WIDTH_PCT, computeBounds, waterfallSegment } from './waterfall'
export type {
  SpanErrorInfo,
  SpanEvent,
  SpanKind,
  SpanNode,
  SpanScore,
  SpanStatus,
  SpanTree,
  TraceAttempt,
  TraceBounds,
  TraceData,
  TraceItemMeta,
  TraceSpan,
  TraceSummary,
  WaterfallSegment,
} from './types'
