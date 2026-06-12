import { describe, expect, it } from 'vitest'
import {
  applyClientView,
  bucketIsFailing,
  canWordDiff,
  defaultSegment,
  failedBannerText,
  failureCount,
  failuresFirstCompare,
  findPreviousRun,
  firstErrorLine,
  isTraceStatsEmpty,
  isVerdictGated,
  itemOutcome,
  minMetricScore,
  scoredItemCount,
} from './lib'
import { makeItem, makeItems, makeRun } from './__fixtures__/runDetail'
import type { RunSummary } from '@/api/runDetail'

describe('itemOutcome', () => {
  it('classifies task errors as error', () => {
    expect(itemOutcome(makeItem({ status: 'failed', metric_values: {} }))).toBe('error')
  })

  it('classifies any metric below 0.5 as fail', () => {
    expect(itemOutcome(makeItem({ metric_values: { a: 1, b: 0.49 } }))).toBe('fail')
  })

  it('classifies all-passing metrics as pass (0.5 itself passes)', () => {
    expect(itemOutcome(makeItem({ metric_values: { a: 0.5, b: 1 } }))).toBe('pass')
  })

  it('treats unscored completed items as pass (no judgement)', () => {
    expect(itemOutcome(makeItem({ metric_values: {} }))).toBe('pass')
  })
})

describe('failures-first default selection', () => {
  it('counts errors + metric fails as failures', () => {
    expect(failureCount(makeItems())).toBe(2)
  })

  it('defaults to Failures when any exist', () => {
    expect(defaultSegment(makeItems())).toBe('failures')
  })

  it('defaults to All when everything passed', () => {
    expect(defaultSegment([makeItem({ index: 0 }), makeItem({ index: 1 })])).toBe('all')
  })
})

describe('failuresFirstCompare', () => {
  it('orders task errors first, then ascending min metric score, then index', () => {
    const error = makeItem({ index: 5, item_id: 'e', status: 'failed', metric_values: {} })
    const worst = makeItem({ index: 3, item_id: 'w', metric_values: { m: 0.1 } })
    const mid = makeItem({ index: 1, item_id: 'm', metric_values: { m: 0.4 } })
    const pass = makeItem({ index: 0, item_id: 'p', metric_values: { m: 1 } })
    const sorted = [pass, mid, worst, error].sort(failuresFirstCompare)
    expect(sorted.map((i) => i.item_id)).toEqual(['e', 'w', 'm', 'p'])
  })

  it('breaks score ties by index', () => {
    const a = makeItem({ index: 2, item_id: 'a', metric_values: { m: 0.2 } })
    const b = makeItem({ index: 1, item_id: 'b', metric_values: { m: 0.2 } })
    expect([a, b].sort(failuresFirstCompare).map((i) => i.item_id)).toEqual(['b', 'a'])
  })

  it('minMetricScore returns the lowest score or null', () => {
    expect(minMetricScore(makeItem({ metric_values: { a: 0.9, b: 0.2 } }))).toBe(0.2)
    expect(minMetricScore(makeItem({ metric_values: {} }))).toBeNull()
  })
})

describe('applyClientView', () => {
  it('failures segment keeps errors and metric fails only', () => {
    const view = applyClientView(makeItems(), { segment: 'failures', metric: null, sort: 'index' })
    expect(view.map((i) => i.item_id)).toEqual(['item_fail', 'item_error'])
  })

  it('metric filter keeps items where THAT metric is below threshold', () => {
    const view = applyClientView(makeItems(), {
      segment: 'all',
      metric: 'exact_match',
      sort: 'index',
    })
    expect(view.map((i) => i.item_id)).toEqual(['item_fail'])
  })

  it('failures sort puts the task error before the metric fail', () => {
    const view = applyClientView(makeItems(), { segment: 'all', metric: null, sort: 'failures' })
    expect(view.map((i) => i.item_id)).toEqual(['item_error', 'item_fail', 'item_pass'])
  })
})

describe('min-n verdict gating', () => {
  it('gates a RUNNING run below 5 scored items', () => {
    expect(isVerdictGated('RUNNING', 4)).toBe(true)
  })

  it('opens at 5 scored items', () => {
    expect(isVerdictGated('RUNNING', 5)).toBe(false)
  })

  it('never gates finished runs, even with few items', () => {
    expect(isVerdictGated('COMPLETED', 1)).toBe(false)
    expect(isVerdictGated('FAILED', 0)).toBe(false)
  })

  it('scoredItemCount counts only items with at least one numeric score', () => {
    expect(scoredItemCount(makeItems())).toBe(2)
  })
})

describe('trace-stats collapse rule', () => {
  it('is empty when tokens/llm/tool calls are all zero', () => {
    expect(isTraceStatsEmpty({ avg_tokens: 0, avg_llm_calls: 0, avg_tool_calls: 0 })).toBe(true)
  })

  it('is empty for null/missing stats', () => {
    expect(isTraceStatsEmpty(null)).toBe(true)
    expect(isTraceStatsEmpty({ avg_tokens: null, avg_llm_calls: null })).toBe(true)
  })

  it('is non-empty as soon as any of the three has data', () => {
    expect(isTraceStatsEmpty({ avg_tokens: 812, avg_llm_calls: 0, avg_tool_calls: 0 })).toBe(false)
  })
})

describe('findPreviousRun', () => {
  const summary = (over: Partial<RunSummary>): RunSummary => ({
    id: 'r',
    name: 'r',
    task: 'support_rag',
    dataset: 'support_qa.csv',
    model: 'llama-3.1-70b',
    status: 'COMPLETED',
    started_at: '2026-05-01T00:00:00Z',
    created_at: '2026-05-01T00:00:00Z',
    ended_at: null,
    duration_ms: 1,
    owner: null,
    total_items: 1,
    completed_items: 1,
    error_items: 0,
    progress_pct: 1,
    metric_averages: {},
    version: null,
    group_key: 'g',
    ...over,
  })
  const current = { id: 'me', group_key: 'g', started_at: '2026-05-21T00:00:00Z' }

  it('picks the most recent earlier finished run in the same group', () => {
    const found = findPreviousRun(current, [
      summary({ id: 'older', started_at: '2026-05-10T00:00:00Z' }),
      summary({ id: 'oldest', started_at: '2026-05-01T00:00:00Z' }),
      summary({ id: 'newer', started_at: '2026-05-30T00:00:00Z' }),
    ])
    expect(found?.id).toBe('older')
  })

  it('ignores other groups, unfinished runs, and itself', () => {
    expect(
      findPreviousRun(current, [
        summary({ id: 'me', started_at: '2026-05-21T00:00:00Z' }),
        summary({ id: 'other-group', group_key: 'x', started_at: '2026-05-10T00:00:00Z' }),
        summary({ id: 'running', status: 'RUNNING', started_at: '2026-05-10T00:00:00Z' }),
        summary({ id: 'stopped', status: 'STOPPED', started_at: '2026-05-10T00:00:00Z' }),
      ]),
    ).toBeNull()
  })
})

describe('failed banner', () => {
  it('uses the planned total and the first error line', () => {
    const run = makeRun({
      status: 'FAILED',
      completed_items: 3,
      total_items: 3,
      run_metadata: { total_items: 10 },
      error_summary: { task_errors: 1, types: { 'CUDA out of memory\nstack…': 1 } },
    })
    expect(failedBannerText(run)).toBe('Failed after 3 of 10 items — CUDA out of memory')
  })

  it('firstErrorLine trims to the first line', () => {
    expect(firstErrorLine('boom\ntrace')).toBe('boom')
  })
})

describe('distribution + diff helpers', () => {
  it('marks only buckets fully below the threshold as failing', () => {
    expect(bucketIsFailing('0.00-0.25')).toBe(true)
    expect(bucketIsFailing('0.25-0.50')).toBe(true)
    expect(bucketIsFailing('0.50-0.75')).toBe(false)
    expect(bucketIsFailing('0.75-1.00')).toBe(false)
  })

  it('offers word diff only for short non-JSON text pairs', () => {
    expect(canWordDiff('a b c', 'a b d')).toBe(true)
    expect(canWordDiff('{"a":1}', 'plain')).toBe(false)
    expect(canWordDiff('x'.repeat(3000), 'short')).toBe(false)
    expect(canWordDiff({ a: 1 }, 'short')).toBe(false)
  })
})
