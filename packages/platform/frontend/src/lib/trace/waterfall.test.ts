import { describe, expect, it } from 'vitest'
import { buildSpanTree, flattenVisibleNodes, expandableSpanIds } from './tree'
import { MIN_BAR_WIDTH_PCT, computeBounds, waterfallSegment } from './waterfall'
import type { TraceData, TraceSpan } from './types'
// tsconfig has no resolveJsonModule — fixtures load via Vite ?raw (see metrics.test.ts).
import traceOkRaw from './__fixtures__/trace-item-ok.json?raw'

const okData = JSON.parse(traceOkRaw) as TraceData

function span(partial: Partial<TraceSpan> & { span_id: string }): TraceSpan {
  return { name: partial.span_id, attributes: {}, events: [], ...partial }
}

describe('computeBounds', () => {
  it('prefers the summary window (fixture parity)', () => {
    const b = computeBounds(okData.spans, okData.summary)
    expect(b.start).toBe(okData.summary?.started_at_ns)
    expect(b.end).toBe(okData.summary?.ended_at_ns)
    expect(b.total).toBe(Number(b.end) - Number(b.start))
  })

  it('falls back to span min/max when summary stamps are missing', () => {
    const b = computeBounds(
      [span({ span_id: 'a', start_time_ns: 100, end_time_ns: 200 }), span({ span_id: 'b', start_time_ns: 50, end_time_ns: 150 })],
      {},
    )
    expect(b).toEqual({ start: 50, end: 200, total: 150 })
  })

  it('returns a null window with safe total for empty/timeless spans', () => {
    expect(computeBounds([], null)).toEqual({ start: null, end: null, total: 1 })
    expect(computeBounds([span({ span_id: 'a' })], {})).toEqual({ start: null, end: null, total: 1 })
  })

  it('clamps total to >= 1 for a zero-length window (single instant span)', () => {
    const b = computeBounds([span({ span_id: 'a', start_time_ns: 5, end_time_ns: 5 })], {})
    expect(b.total).toBe(1)
  })
})

describe('waterfallSegment', () => {
  it('fixture parity: root fills the window, children stay inside it', () => {
    const bounds = computeBounds(okData.spans, okData.summary)
    const tree = buildSpanTree(okData.spans)
    const rows = flattenVisibleNodes(tree, new Set(expandableSpanIds(tree)))
    const segments = rows.map((r) => waterfallSegment(r, bounds))

    // Root span spans (almost exactly) the full window.
    expect(segments[0].leftPct).toBeCloseTo(0, 3)
    expect(segments[0].widthPct).toBeCloseTo(100, 0)

    for (const seg of segments) {
      expect(seg.leftPct).toBeGreaterThanOrEqual(0)
      expect(seg.widthPct).toBeGreaterThanOrEqual(MIN_BAR_WIDTH_PCT)
      expect(seg.leftPct + seg.widthPct).toBeLessThanOrEqual(100 + MIN_BAR_WIDTH_PCT)
    }

    // Children start no earlier than the root and offsets are monotonic
    // (rows are in start-time order for this fixture).
    const lefts = segments.map((s) => s.leftPct)
    expect([...lefts].sort((a, b) => a - b)).toEqual(lefts)
  })

  it('zero-duration span gets the minimum visible width', () => {
    const bounds = { start: 0, end: 1000, total: 1000 }
    const seg = waterfallSegment(span({ span_id: 'z', start_time_ns: 500, end_time_ns: 500 }), bounds)
    expect(seg.widthPct).toBe(MIN_BAR_WIDTH_PCT)
    expect(seg.leftPct).toBe(50)
  })

  it('missing timestamps render a full-width bar at offset 0 (legacy default)', () => {
    const bounds = { start: 0, end: 1000, total: 1000 }
    expect(waterfallSegment(span({ span_id: 'n' }), bounds)).toEqual({ leftPct: 0, widthPct: 100 })
  })

  it('null bounds (no window) → full-width bar', () => {
    const seg = waterfallSegment(span({ span_id: 'a', start_time_ns: 1, end_time_ns: 2 }), {
      start: null,
      end: null,
      total: 1,
    })
    expect(seg).toEqual({ leftPct: 0, widthPct: 100 })
  })

  it('clamps overflowing spans to the track', () => {
    const bounds = { start: 0, end: 100, total: 100 }
    const seg = waterfallSegment(span({ span_id: 'big', start_time_ns: 0, end_time_ns: 500 }), bounds)
    expect(seg.widthPct).toBe(100)
    const late = waterfallSegment(span({ span_id: 'late', start_time_ns: 200, end_time_ns: 201 }), bounds)
    expect(late.leftPct).toBeLessThanOrEqual(100 - MIN_BAR_WIDTH_PCT)
  })

  it('offsets of sequential halves sum to the full window', () => {
    const bounds = { start: 0, end: 100, total: 100 }
    const first = waterfallSegment(span({ span_id: 'a', start_time_ns: 0, end_time_ns: 50 }), bounds)
    const second = waterfallSegment(span({ span_id: 'b', start_time_ns: 50, end_time_ns: 100 }), bounds)
    expect(first.leftPct).toBe(0)
    expect(first.widthPct).toBe(50)
    expect(second.leftPct).toBe(50)
    expect(second.widthPct).toBe(50)
    expect(first.widthPct + second.widthPct).toBe(100)
  })
})
