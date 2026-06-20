import { describe, expect, it } from 'vitest'
import { normalizeAttempts, selectAttempt } from './attempts'
import {
  aggregateStats,
  buildSpanTree,
  countRealErrors,
  detectRetries,
  expandableSpanIds,
  extractErrorInfoDeep,
  flattenVisibleNodes,
  subtreeHasError,
} from './tree'
import type { TraceData, TraceSpan } from './types'
// tsconfig has no resolveJsonModule — fixtures load via Vite ?raw (see metrics.test.ts).
import traceOkRaw from './__fixtures__/trace-item-ok.json?raw'
import traceErrorRaw from './__fixtures__/trace-item-error.json?raw'
import runSpansRaw from './__fixtures__/run-spans.json?raw'

const okData = JSON.parse(traceOkRaw) as TraceData
const errData = JSON.parse(traceErrorRaw) as TraceData
const allRunSpans = (JSON.parse(runSpansRaw) as { spans: TraceSpan[] }).spans

function span(partial: Partial<TraceSpan> & { span_id: string }): TraceSpan {
  return { name: partial.span_id, attributes: {}, events: [], ...partial }
}

describe('buildSpanTree — fixture parity', () => {
  it('builds the seeded 3-span tree: root CHAIN with AGENT + EVALUATOR children', () => {
    const tree = buildSpanTree(okData.spans)
    expect(tree.roots).toHaveLength(1)
    const root = tree.roots[0]
    expect(root.span_id).toBe('673ad1af94abb4ab')
    expect(root.depth).toBe(0)
    expect(root.orphan).toBe(false)
    expect(root.children.map((c) => c.name)).toEqual(['support_task', 'eval_metrics'])
    expect(root.children.map((c) => c.depth)).toEqual([1, 1])
    // children ordered by start_time_ns
    const starts = root.children.map((c) => Number(c.start_time_ns))
    expect(starts[0]).toBeLessThan(starts[1])
    expect(tree.byId.size).toBe(3)
  })

  it('matches the backend summary counts on the full-run span dump', () => {
    const tree = buildSpanTree(allRunSpans)
    // 36 spans = 12 items × (CHAIN root + AGENT + EVALUATOR)
    expect(tree.nodes).toHaveLength(36)
    expect(tree.roots).toHaveLength(12)
    for (const root of tree.roots) {
      expect(root.children).toHaveLength(2)
      expect(root.orphan).toBe(false)
    }
    // roots sorted by start time
    const rootStarts = tree.roots.map((r) => Number(r.start_time_ns))
    expect([...rootStarts].sort((a, b) => a - b)).toEqual(rootStarts)
  })

  it('flags errors on the failed-item fixture without exception events', () => {
    const tree = buildSpanTree(errData.spans)
    expect(tree.roots).toHaveLength(1)
    expect(subtreeHasError(tree.roots[0])).toBe(true)
    // ERROR status but no `exception` event → countRealErrors falls back to 1
    expect(errData.summary?.error_count).toBe(2)
    expect(countRealErrors(tree, errData.summary?.error_count)).toBe(1)
    expect(extractErrorInfoDeep(tree.roots[0])).toBeNull()
  })
})

describe('buildSpanTree — synthetic edge cases', () => {
  it('handles a single span', () => {
    const tree = buildSpanTree([span({ span_id: 'a', start_time_ns: 1, end_time_ns: 2 })])
    expect(tree.roots).toHaveLength(1)
    expect(tree.roots[0].depth).toBe(0)
    expect(tree.roots[0].children).toEqual([])
    expect(expandableSpanIds(tree)).toEqual([])
  })

  it('promotes spans with a missing parent to orphan roots', () => {
    const tree = buildSpanTree([
      span({ span_id: 'root', start_time_ns: 0, end_time_ns: 10 }),
      span({ span_id: 'lost', parent_span_id: 'ghost', start_time_ns: 5, end_time_ns: 6 }),
    ])
    expect(tree.roots.map((r) => r.span_id)).toEqual(['root', 'lost'])
    expect(tree.roots[0].orphan).toBe(false)
    expect(tree.roots[1].orphan).toBe(true)
  })

  it('keeps zero-duration and missing-timestamp spans, nulls sorted last', () => {
    const tree = buildSpanTree([
      span({ span_id: 'p', start_time_ns: 0, end_time_ns: 100 }),
      span({ span_id: 'no-time', parent_span_id: 'p' }),
      span({ span_id: 'zero', parent_span_id: 'p', start_time_ns: 50, end_time_ns: 50 }),
      span({ span_id: 'early', parent_span_id: 'p', start_time_ns: 10, end_time_ns: 20 }),
    ])
    expect(tree.roots[0].children.map((c) => c.span_id)).toEqual(['early', 'zero', 'no-time'])
  })

  it('does not mutate the input spans', () => {
    const input = [
      span({ span_id: 'a', start_time_ns: 0, end_time_ns: 2 }),
      span({ span_id: 'b', parent_span_id: 'a', start_time_ns: 1, end_time_ns: 2 }),
    ]
    const snapshot = JSON.parse(JSON.stringify(input)) as TraceSpan[]
    buildSpanTree(input)
    expect(input).toEqual(snapshot)
  })

  it('removes leaf framework-noise spans but keeps user-named ones', () => {
    const tree = buildSpanTree([
      // input.value keeps the root from being spliced as a pass-through
      // wrapper once it is left with a single child (legacy L277-287).
      span({ span_id: 'root', start_time_ns: 0, end_time_ns: 10, attributes: { 'input.value': 'x' } }),
      span({ span_id: 'noise', parent_span_id: 'root', name: 'should_continue', start_time_ns: 1, end_time_ns: 2 }),
      span({ span_id: 'user', parent_span_id: 'root', name: 'my_node', start_time_ns: 3, end_time_ns: 4 }),
    ])
    expect(tree.roots[0].children.map((c) => c.name)).toEqual(['my_node'])
  })

  it('splices pass-through wrappers and promotes children of noisy parents', () => {
    const tree = buildSpanTree([
      span({ span_id: 'root', start_time_ns: 0, end_time_ns: 10, attributes: { 'input.value': 'x' } }),
      // wrapper: single child, no data → replaced by its child
      span({ span_id: 'wrap', parent_span_id: 'root', name: 'wrapper', start_time_ns: 1, end_time_ns: 9 }),
      span({
        span_id: 'llm',
        parent_span_id: 'wrap',
        name: 'ChatCompletion',
        start_time_ns: 2,
        end_time_ns: 8,
        attributes: { 'openinference.span.kind': 'LLM' },
      }),
    ])
    expect(tree.roots[0].children.map((c) => c.span_id)).toEqual(['llm'])
    expect(tree.roots[0].children[0].depth).toBe(1)
  })

  it('never collapses noise inside an errored subtree', () => {
    const tree = buildSpanTree([
      span({ span_id: 'root', start_time_ns: 0, end_time_ns: 10, attributes: { 'input.value': 'x' } }),
      span({
        span_id: 'noise-err',
        parent_span_id: 'root',
        name: 'RunnableSequence',
        status: 'ERROR',
        start_time_ns: 1,
        end_time_ns: 2,
      }),
    ])
    expect(tree.roots[0].children.map((c) => c.span_id)).toEqual(['noise-err'])
  })

  it('dedupes overlapping duplicate LLM spans, keeping the richer one', () => {
    const shared = {
      'openinference.span.kind': 'LLM',
      'llm.model_name': 'gpt-4o',
      'input.value': 'Q',
      'output.value': 'A',
    }
    const tree = buildSpanTree([
      span({ span_id: 'root', start_time_ns: 0, end_time_ns: 100, attributes: { 'input.value': 'x' } }),
      span({
        span_id: 'framework-llm',
        parent_span_id: 'root',
        name: 'my_model_call',
        start_time_ns: 10,
        end_time_ns: 90,
        duration_ms: 80,
        attributes: { ...shared, 'llm.input_messages.0.message.role': 'user', 'llm.input_messages.0.message.content': 'Q' },
      }),
      span({
        span_id: 'provider-llm',
        parent_span_id: 'root',
        name: 'ChatCompletion',
        start_time_ns: 11,
        end_time_ns: 89,
        duration_ms: 78,
        attributes: { ...shared },
      }),
    ])
    expect(tree.roots[0].children.map((c) => c.span_id)).toEqual(['framework-llm'])
  })

  it('empty input → empty tree', () => {
    const tree = buildSpanTree([])
    expect(tree.roots).toEqual([])
    expect(tree.nodes).toEqual([])
  })
})

describe('flattenVisibleNodes', () => {
  it('walks depth-first honoring the expanded set', () => {
    const tree = buildSpanTree(okData.spans)
    const all = flattenVisibleNodes(tree, new Set(expandableSpanIds(tree)))
    expect(all.map((n) => n.name)).toEqual([
      'eval-support-rag-claude-sonnet-4-6-claude-sonnet-4-6-260611-1043-item-0-attempt-1',
      'support_task',
      'eval_metrics',
    ])
    const collapsed = flattenVisibleNodes(tree, new Set())
    expect(collapsed).toHaveLength(1)
  })
})

describe('detectRetries', () => {
  it('marks same-named siblings after an error as retries and propagates failed', () => {
    const tree = buildSpanTree([
      span({ span_id: 'root', start_time_ns: 0, end_time_ns: 100, attributes: { 'input.value': 'x' } }),
      span({ span_id: 't1', parent_span_id: 'root', name: 'task', status: 'ERROR', start_time_ns: 1, end_time_ns: 10 }),
      span({ span_id: 't1c', parent_span_id: 't1', name: 'inner', start_time_ns: 2, end_time_ns: 3, attributes: { 'input.value': 'y' }, status: 'ERROR' }),
      span({ span_id: 't2', parent_span_id: 'root', name: 'task', status: 'OK', start_time_ns: 20, end_time_ns: 30 }),
    ])
    const markers = detectRetries(tree)
    expect(markers.retries.get('t2')).toBe(1)
    expect(markers.retries.has('t1')).toBe(false)
    expect(markers.failed.has('t1')).toBe(true)
    expect(markers.failed.has('t1c')).toBe(true)
    expect(markers.failed.has('t2')).toBe(false)
  })
})

describe('aggregateStats', () => {
  it('sums tokens and cost over LLM spans only', () => {
    const tree = buildSpanTree([
      span({
        span_id: 'a',
        start_time_ns: 0,
        end_time_ns: 10,
        attributes: { 'openinference.span.kind': 'LLM', 'llm.token_count.total': 120, 'llm.cost.total': 0.002 },
      }),
      span({
        span_id: 'b',
        start_time_ns: 20,
        end_time_ns: 30,
        attributes: { 'openinference.span.kind': 'TOOL', 'llm.token_count.total': 999 },
      }),
    ])
    expect(aggregateStats(tree)).toEqual({ totalTokens: 120, totalCost: 0.002 })
  })

  it('is zero for the seeded fixture (no LLM token attrs)', () => {
    expect(aggregateStats(buildSpanTree(okData.spans))).toEqual({ totalTokens: 0, totalCost: 0 })
  })
})

describe('normalizeAttempts', () => {
  it('keeps existing attempts and mirrors the last attempt at top level', () => {
    const out = normalizeAttempts(errData)
    expect(out.attempts).toHaveLength(3)
    expect(out.attempts?.map((a) => a.attempt_number)).toEqual([1, 2, 3])
    const last = out.attempts?.find((a) => a.is_last_attempt)
    expect(last?.attempt_number).toBe(3)
    expect(out.spans).toBe(last?.spans)
    expect(out.summary).toBe(last?.summary)
    // pure: input untouched
    expect(errData.attempts).toHaveLength(3)
  })

  it('synthesizes a single attempt for payloads without attempts', () => {
    const out = normalizeAttempts({
      item: { trace_id: 'abc', latency_ms: 42 },
      summary: { span_count: 1 },
      spans: [span({ span_id: 'a' })],
    })
    expect(out.attempts).toHaveLength(1)
    expect(out.attempts?.[0]).toMatchObject({
      attempt_number: 1,
      status: 'completed',
      latency_ms: 42,
      is_last_attempt: true,
    })
    expect(out.item?.retry_count).toBe(0)
  })

  it('selectAttempt picks requested, then last, then final', () => {
    const out = normalizeAttempts(errData)
    expect(selectAttempt(out.attempts, 2)?.attempt_number).toBe(2)
    expect(selectAttempt(out.attempts, null)?.attempt_number).toBe(3)
    expect(selectAttempt(out.attempts, 99)?.attempt_number).toBe(3)
    expect(selectAttempt([], 1)).toBeNull()
  })
})
