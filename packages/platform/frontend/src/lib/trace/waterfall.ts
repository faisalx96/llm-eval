/**
 * Waterfall layout math ported from the legacy trace viewer
 * (qym_platform/_static/dashboard/trace_viewer.js).
 *
 * All geometry is normalized to percent of the trace time window so the
 * track can be any pixel width.
 */

import type { TraceBounds, TraceSpan, TraceSummary, WaterfallSegment } from './types'

/**
 * Minimum bar width in percent so zero/near-zero-duration spans stay visible.
 * Legacy `width = Math.max(width, 0.75)` (trace_viewer.js L1296).
 */
export const MIN_BAR_WIDTH_PCT = 0.75

/**
 * Compute the trace time window. Prefers the summary's started/ended
 * nanosecond stamps; falls back to min(start)/max(end) over the spans;
 * total is clamped to >= 1 so divisions are safe.
 * Ported from legacy `computeBounds` (L488-498).
 */
export function computeBounds(
  spans: TraceSpan[] | null | undefined,
  summary?: TraceSummary | null,
): TraceBounds {
  let s = summary?.started_at_ns
  let e = summary?.ended_at_ns
  if (s != null && e != null) return { start: s, end: e, total: Math.max(e - s, 1) }

  const list = spans ?? []
  const ss = list.map((x) => x.start_time_ns).filter((x): x is number => x != null)
  const es = list.map((x) => x.end_time_ns).filter((x): x is number => x != null)
  if (!ss.length || !es.length) return { start: null, end: null, total: 1 }
  s = Math.min(...ss)
  e = Math.max(...es)
  return { start: s, end: e, total: Math.max(e - s, 1) }
}

/**
 * Normalized offset/width of one span inside the trace window.
 * Ported from the waterfall block of legacy `renderTree`/`visit`
 * (L1292-1296): left defaults to 0 and width to 100 when timestamps are
 * missing; width is clamped to [MIN_BAR_WIDTH_PCT, 100] and the bar never
 * overflows the right edge (legacy rendered `width:${Math.min(width,100)}%`).
 */
export function waterfallSegment(span: TraceSpan, bounds: TraceBounds): WaterfallSegment {
  let left = 0
  let width = 100
  if (bounds.start != null && span.start_time_ns != null) {
    left = ((Number(span.start_time_ns) - Number(bounds.start)) / bounds.total) * 100
  }
  if (bounds.start != null && span.end_time_ns != null && span.start_time_ns != null) {
    width = ((Number(span.end_time_ns) - Number(span.start_time_ns)) / bounds.total) * 100
  }
  width = Math.min(Math.max(width, MIN_BAR_WIDTH_PCT), 100)
  left = Math.min(Math.max(left, 0), 100 - MIN_BAR_WIDTH_PCT)
  return { leftPct: left, widthPct: width }
}
