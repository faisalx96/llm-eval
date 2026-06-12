import { describe, expect, it } from 'vitest'
import { buildRunsQuery, type RunSummary } from '@/api/runs'
import { isUuid } from '@/lib/runIdentity'
import {
  applyClientFilters,
  buildCompareUrl,
  computeBaselines,
  computeMetricColumns,
  groupLabel,
  organizeRuns,
  ownerInitials,
  runDisplayName,
  successRate,
  versionLabel,
} from './lib'

function makeRun(overrides: Partial<RunSummary> & { id: string }): RunSummary {
  return {
    name: `run-${overrides.id}`,
    task: 'support_rag',
    dataset: 'support_qa.csv',
    model: 'gpt-4o',
    status: 'COMPLETED',
    created_at: '2026-06-10T10:00:00Z',
    started_at: '2026-06-10T10:00:00Z',
    ended_at: '2026-06-10T10:20:00Z',
    duration_ms: 1_200_000,
    owner: { id: 'u1', email: 'dev@local', display_name: 'Dev User' },
    total_items: 12,
    completed_items: 12,
    error_items: 0,
    progress_pct: 1,
    metric_averages: {},
    version: { branch: 'main', commit: '9001ac4' },
    group_key: '',
    ...overrides,
  }
}

describe('organizeRuns (grouping assembly from group_key)', () => {
  const a = makeRun({ id: 'a', group_key: 'g1', created_at: '2026-06-10T12:00:00Z' })
  const b = makeRun({ id: 'b', group_key: 'g1', created_at: '2026-06-10T11:00:00Z' })
  const c = makeRun({ id: 'c', group_key: 'g2', created_at: '2026-06-10T11:30:00Z' })
  const d = makeRun({ id: 'd', group_key: '', created_at: '2026-06-10T12:30:00Z' })

  it('groups only keys with ≥2 members; singles and empty keys stay flat', () => {
    const rows = organizeRuns([d, a, c, b])
    expect(
      rows.map((r) => (r.kind === 'group' ? `group:${r.group.key}` : r.run.id)),
    ).toEqual(['d', 'group:g1', 'a', 'b', 'c'])
  })

  it('orders groups among rows by their newest member, -created_at inside', () => {
    const e = makeRun({ id: 'e', group_key: 'g1', created_at: '2026-06-10T13:00:00Z' })
    const rows = organizeRuns([d, a, c, b, e])
    // Group g1 now has the newest run (13:00) → the group leads.
    expect(
      rows.map((r) => (r.kind === 'group' ? `group:${r.group.key}` : r.run.id)),
    ).toEqual(['group:g1', 'e', 'a', 'b', 'd', 'c'])
  })

  it('collapsed groups emit only the header row', () => {
    const rows = organizeRuns([d, a, c, b], new Set(['g1']))
    expect(
      rows.map((r) => (r.kind === 'group' ? `group:${r.group.key}` : r.run.id)),
    ).toEqual(['d', 'group:g1', 'c'])
    const header = rows[1]
    expect(header.kind === 'group' && header.collapsed).toBe(true)
  })

  it('labels groups as task · dataset · model · N runs', () => {
    const rows = organizeRuns([a, b])
    const header = rows[0]
    if (header.kind !== 'group') throw new Error('expected group header first')
    expect(groupLabel(header.group)).toBe('support_rag · support_qa.csv · gpt-4o · 2 runs')
  })
})

describe('computeBaselines', () => {
  it('uses the previous run in the same group_key by started_at', () => {
    const first = makeRun({
      id: 'first',
      group_key: 'g',
      started_at: '2026-06-01T00:00:00Z',
      metric_averages: { exact_match: 0.5 },
    })
    const second = makeRun({
      id: 'second',
      group_key: 'g',
      started_at: '2026-06-02T00:00:00Z',
      metric_averages: { exact_match: 0.7 },
    })
    const lone = makeRun({ id: 'lone', group_key: 'other' })
    const baselines = computeBaselines([second, lone, first])
    expect(baselines.get('second')?.id).toBe('first')
    expect(baselines.has('first')).toBe(false)
    expect(baselines.has('lone')).toBe(false)
  })
})

describe('computeMetricColumns', () => {
  it('returns the alphabetical union of metric names', () => {
    const runs = [
      makeRun({ id: 'a', metric_averages: { exact_match: 1 } }),
      makeRun({ id: 'b', metric_averages: { answer_relevancy: 0.5, exact_match: 0.9 } }),
    ]
    expect(computeMetricColumns(runs)).toEqual(['answer_relevancy', 'exact_match'])
  })
})

describe('applyClientFilters', () => {
  const now = new Date('2026-06-12T12:00:00Z').getTime()
  const today = makeRun({ id: 'today', created_at: '2026-06-12T08:00:00Z' })
  const lastWeek = makeRun({ id: 'week', created_at: '2026-06-08T08:00:00Z' })
  const old = makeRun({ id: 'old', created_at: '2026-04-01T08:00:00Z' })

  it('applies the time quick-range client-side', () => {
    const base = { facets: {}, time: 'all' as const }
    expect(applyClientFilters([today, lastWeek, old], base, now)).toHaveLength(3)
    expect(
      applyClientFilters([today, lastWeek, old], { ...base, time: '7d' }, now).map((r) => r.id),
    ).toEqual(['today', 'week'])
    expect(
      applyClientFilters([today, lastWeek, old], { ...base, time: '30d' }, now).map((r) => r.id),
    ).toEqual(['today', 'week'])
  })

  it('filters multi-value facets client-side, leaves single values to the server', () => {
    const gpt = makeRun({ id: 'gpt', model: 'gpt-4o' })
    const claude = makeRun({ id: 'claude', model: 'claude-sonnet-4-6' })
    const llama = makeRun({ id: 'llama', model: 'llama-3.1-70b' })
    const multi = applyClientFilters(
      [gpt, claude, llama],
      { facets: { model: ['gpt-4o', 'claude-sonnet-4-6'] }, time: 'all' },
      now,
    )
    expect(multi.map((r) => r.id)).toEqual(['gpt', 'claude'])
    // Single selection is a server-side param — no client filtering.
    const single = applyClientFilters(
      [gpt, claude, llama],
      { facets: { model: ['gpt-4o'] }, time: 'all' },
      now,
    )
    expect(single).toHaveLength(3)
  })
})

describe('buildRunsQuery', () => {
  it('builds the needs-review count query', () => {
    const qs = buildRunsQuery({ projectSlug: 'support-copilot', needsReview: true, limit: 1 })
    const params = new URLSearchParams(qs)
    expect(params.get('project_slug')).toBe('support-copilot')
    expect(params.get('needs_review')).toBe('true')
    expect(params.get('limit')).toBe('1')
    expect(params.get('sort')).toBe('-created_at')
  })

  it('joins statuses comma-separated and omits empty filters', () => {
    const qs = buildRunsQuery({
      projectSlug: 'p',
      statuses: ['COMPLETED', 'FAILED'],
      q: 'nightly',
      limit: 50,
      offset: 100,
    })
    const params = new URLSearchParams(qs)
    expect(params.get('status')).toBe('COMPLETED,FAILED')
    expect(params.get('q')).toBe('nightly')
    expect(params.get('offset')).toBe('100')
    expect(params.get('needs_review')).toBeNull()
    expect(params.get('task')).toBeNull()
  })
})

describe('runDisplayName', () => {
  it('never shows a UUID — composes task · model · time instead', () => {
    const run = makeRun({
      id: '55d7867b-8d68-4203-8da7-5a9e2e496904',
      name: '55d7867b-8d68-4203-8da7-5a9e2e496904',
      task: 'text2sql',
      model: 'llama-3.1-70b',
    })
    const name = runDisplayName(run)
    expect(isUuid(name)).toBe(false)
    expect(name).toContain('text2sql')
    expect(name).toContain('llama-3.1-70b')
  })

  it('prefers the human-given name', () => {
    expect(runDisplayName(makeRun({ id: 'x', name: 'nightly regression' }))).toBe(
      'nightly regression',
    )
  })
})

describe('stat helpers', () => {
  it('successRate ignores in-flight runs and counts FAILED/STOPPED as failures', () => {
    expect(
      successRate({
        project_id: 'p',
        total_runs: 6,
        total_items: 0,
        by_status: { COMPLETED: 4, APPROVED: 1, REJECTED: 1 },
      }),
    ).toBe(1)
    expect(
      successRate({
        project_id: 'p',
        total_runs: 5,
        total_items: 0,
        by_status: { COMPLETED: 2, SUBMITTED: 1, FAILED: 1, STOPPED: 1 },
      }),
    ).toBe(0.6)
    expect(
      successRate({
        project_id: 'p',
        total_runs: 2,
        total_items: 0,
        by_status: { RUNNING: 2 },
      }),
    ).toBeNull()
    expect(successRate(undefined)).toBeNull()
  })

  it('ownerInitials / versionLabel / buildCompareUrl', () => {
    expect(ownerInitials('Dev User')).toBe('DU')
    expect(ownerInitials('plato')).toBe('PL')
    expect(ownerInitials('')).toBe('?')
    expect(versionLabel(makeRun({ id: 'v' }))).toBe('main · 9001ac4')
    expect(versionLabel(makeRun({ id: 'v', version: null }))).toBeNull()
    expect(buildCompareUrl('proj', ['a', 'b'])).toBe('/projects/proj/compare?runs=a&runs=b')
  })
})
