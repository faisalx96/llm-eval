import type { RunDetail, RunItemDetail, RunItemSlim, RunSummary } from '@/api/runDetail'

/**
 * Pure run-detail logic, isolated for unit tests:
 * pass/fail semantics, failures-first ordering, min-n verdict gating,
 * trace-stats collapse rule, previous-run resolution, analysis aggregations.
 */

/** A metric score below this is a fail (matches the backend pass_count rule). */
export const METRIC_THRESHOLD = 0.5

/** While RUNNING, the verdict band stays gated until this many items scored. */
export const MIN_SCORED_FOR_VERDICT = 5

export type ItemOutcome = 'pass' | 'fail' | 'error'

export function metricScore(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/**
 * Item outcome semantics:
 *  - error: the task itself errored (item status 'failed')
 *  - fail:  completed, but at least one metric scored below threshold
 *  - pass:  completed with all metric scores at/above threshold
 */
export function itemOutcome(item: Pick<RunItemSlim, 'status' | 'metric_values'>): ItemOutcome {
  if (item.status === 'failed') return 'error'
  for (const value of Object.values(item.metric_values ?? {})) {
    const score = metricScore(value)
    if (score !== null && score < METRIC_THRESHOLD) return 'fail'
  }
  return 'pass'
}

/** Errors + metric failures — the count shown on the Failures segment. */
export function failureCount(items: ReadonlyArray<Pick<RunItemSlim, 'status' | 'metric_values'>>): number {
  return items.reduce((acc, item) => (itemOutcome(item) === 'pass' ? acc : acc + 1), 0)
}

export type Segment = 'failures' | 'all'

/** Default toolbar segment: Failures when any exist, otherwise All. */
export function defaultSegment(
  items: ReadonlyArray<Pick<RunItemSlim, 'status' | 'metric_values'>>,
): Segment {
  return failureCount(items) > 0 ? 'failures' : 'all'
}

/** Lowest metric score on the item, or null when nothing is scored. */
export function minMetricScore(item: Pick<RunItemSlim, 'metric_values'>): number | null {
  let min: number | null = null
  for (const value of Object.values(item.metric_values ?? {})) {
    const score = metricScore(value)
    if (score !== null && (min === null || score < min)) min = score
  }
  return min
}

/**
 * Failures-first ordering: task errors first, then ascending minimum metric
 * score (worst items surface), then stable by index.
 */
export function failuresFirstCompare(
  a: Pick<RunItemSlim, 'status' | 'metric_values' | 'index'>,
  b: Pick<RunItemSlim, 'status' | 'metric_values' | 'index'>,
): number {
  const errA = a.status === 'failed' ? 0 : 1
  const errB = b.status === 'failed' ? 0 : 1
  if (errA !== errB) return errA - errB
  const minA = minMetricScore(a)
  const minB = minMetricScore(b)
  const scoreA = minA === null ? Number.POSITIVE_INFINITY : minA
  const scoreB = minB === null ? Number.POSITIVE_INFINITY : minB
  if (scoreA !== scoreB) return scoreA - scoreB
  return a.index - b.index
}

export type SortKey = 'failures' | 'index' | 'latency' | '-latency'

export interface ClientView {
  segment: Segment
  metric: string | null
  sort: SortKey
}

/** Client-side filter + sort pipeline (runs ≤ cap, all items loaded). */
export function applyClientView(items: readonly RunItemSlim[], view: ClientView): RunItemSlim[] {
  let out = items.slice()
  if (view.segment === 'failures') {
    out = out.filter((item) => itemOutcome(item) !== 'pass')
  }
  if (view.metric) {
    out = out.filter((item) => {
      const score = metricScore(item.metric_values?.[view.metric as string])
      return score !== null && score < METRIC_THRESHOLD
    })
  }
  switch (view.sort) {
    case 'failures':
      out.sort(failuresFirstCompare)
      break
    case 'index':
      out.sort((a, b) => a.index - b.index)
      break
    case 'latency':
      out.sort((a, b) => (a.latency_ms ?? Number.POSITIVE_INFINITY) - (b.latency_ms ?? Number.POSITIVE_INFINITY))
      break
    case '-latency':
      out.sort((a, b) => (b.latency_ms ?? Number.NEGATIVE_INFINITY) - (a.latency_ms ?? Number.NEGATIVE_INFINITY))
      break
  }
  return out
}

/** Items that have at least one numeric metric score. */
export function scoredItemCount(items: ReadonlyArray<Pick<RunItemSlim, 'metric_values'>>): number {
  return items.reduce((acc, item) => (minMetricScore(item) === null ? acc : acc + 1), 0)
}

/**
 * Min-n gating: while a run is still RUNNING with fewer than
 * MIN_SCORED_FOR_VERDICT scored items, the verdict band must not render
 * judgable pass rates.
 */
export function isVerdictGated(status: string, scored: number): boolean {
  return status === 'RUNNING' && scored < MIN_SCORED_FOR_VERDICT
}

/**
 * Trace-stats collapse rule: when tokens, LLM calls and tool calls are all
 * zero/null the task is not instrumented — show the one-line hint instead
 * of a stat grid.
 */
export function isTraceStatsEmpty(stats: RunDetail['trace_stats']): boolean {
  if (!stats) return true
  const keys = ['avg_tokens', 'avg_llm_calls', 'avg_tool_calls'] as const
  return keys.every((key) => {
    const value = (stats as Record<string, unknown>)[key]
    return value === null || value === undefined || value === 0
  })
}

/** Statuses that mark a run as finished enough to compare against. */
const FINISHED_STATUSES = new Set(['COMPLETED', 'APPROVED', 'REJECTED', 'SUBMITTED'])

export function isFinishedStatus(status: string): boolean {
  return FINISHED_STATUSES.has(status)
}

/**
 * The previous comparable run: same group_key, earlier started_at, finished.
 * Returns the most recent such run, or null.
 */
export function findPreviousRun(
  current: Pick<RunDetail, 'id' | 'group_key' | 'started_at'>,
  candidates: readonly RunSummary[],
): RunSummary | null {
  const startedAt = current.started_at ? Date.parse(current.started_at) : Number.NaN
  if (!current.group_key || Number.isNaN(startedAt)) return null
  let best: RunSummary | null = null
  let bestTime = Number.NEGATIVE_INFINITY
  for (const run of candidates) {
    if (run.id === current.id || run.group_key !== current.group_key) continue
    if (!isFinishedStatus(run.status)) continue
    const time = run.started_at ? Date.parse(run.started_at) : Number.NaN
    if (Number.isNaN(time) || time >= startedAt) continue
    if (time > bestTime) {
      best = run
      bestTime = time
    }
  }
  return best
}

/** First line of an error message, trimmed for banner display. */
export function firstErrorLine(text: string): string {
  return text.split('\n', 1)[0]?.trim() ?? ''
}

/**
 * Planned item total: prefer run_metadata.total_items when larger than the
 * ingested count (a crashed run only ingests the items it got through).
 */
export function plannedTotalItems(run: Pick<RunDetail, 'total_items' | 'run_metadata'>): number {
  const planned = run.run_metadata?.['total_items']
  if (typeof planned === 'number' && Number.isFinite(planned) && planned > run.total_items) {
    return planned
  }
  return run.total_items
}

/** 'Failed after {completed} of {total} items — {first error line}'. */
export function failedBannerText(
  run: Pick<RunDetail, 'completed_items' | 'total_items' | 'run_metadata' | 'error_summary'>,
): string {
  const total = plannedTotalItems(run)
  const types = run.error_summary?.types ?? {}
  const first = Object.keys(types)[0]
  const head = `Failed after ${run.completed_items} of ${total} items`
  return first ? `${head} — ${firstErrorLine(first)}` : head
}

/**
 * Distribution bucket fail rule: a bucket is tinted red ONLY when its whole
 * range sits below the pass threshold (labels look like '0.25-0.50').
 */
export function bucketIsFailing(label: string): boolean {
  const upper = Number.parseFloat(label.split('-')[1] ?? '')
  return Number.isFinite(upper) && upper <= METRIC_THRESHOLD
}

/* ── Analysis aggregations ─────────────────────────────────────────────── */

/** item_metadata keys that are bookkeeping, not user-facing categories. */
const INTERNAL_METADATA_KEYS = new Set([
  'trace_stats',
  'task_started_at_ms',
  'retry_count',
  'root_cause',
  'root_cause_detail',
  'root_cause_note',
  'root_cause_source',
  'solution',
  'solution_note',
  'solution_source',
])

export function isDisplayMetadataEntry(key: string, value: unknown): boolean {
  if (INTERNAL_METADATA_KEYS.has(key)) return false
  return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
}

export interface CategoryRow {
  key: string
  value: string
  n: number
  avgScore: number | null
  avgLatencyMs: number | null
}

/**
 * Per metadata key (e.g. 'category', 'difficulty'), the average of the
 * selected metric + item count + average latency for each distinct value.
 */
export function aggregateByMetadata(details: readonly RunItemDetail[], metric: string): CategoryRow[] {
  const groups = new Map<
    string,
    { key: string; value: string; n: number; scoreSum: number; scoreN: number; latSum: number; latN: number }
  >()
  for (const item of details) {
    const metadata = item.item_metadata ?? {}
    for (const [key, raw] of Object.entries(metadata)) {
      if (!isDisplayMetadataEntry(key, raw)) continue
      const value = String(raw)
      const groupKey = `${key} ${value}`
      let group = groups.get(groupKey)
      if (!group) {
        group = { key, value, n: 0, scoreSum: 0, scoreN: 0, latSum: 0, latN: 0 }
        groups.set(groupKey, group)
      }
      group.n += 1
      const score = metricScore(item.metric_values?.[metric])
      if (score !== null) {
        group.scoreSum += score
        group.scoreN += 1
      }
      if (typeof item.latency_ms === 'number' && Number.isFinite(item.latency_ms)) {
        group.latSum += item.latency_ms
        group.latN += 1
      }
    }
  }
  return Array.from(groups.values())
    .map((g) => ({
      key: g.key,
      value: g.value,
      n: g.n,
      avgScore: g.scoreN > 0 ? g.scoreSum / g.scoreN : null,
      avgLatencyMs: g.latN > 0 ? g.latSum / g.latN : null,
    }))
    .sort((a, b) => a.key.localeCompare(b.key) || a.value.localeCompare(b.value))
}

export interface RootCauseRow {
  tag: string
  count: number
  /** 'ai' when any tagging came from the analyzer, else 'human'. */
  source: 'ai' | 'human'
}

export function rootCauseCounts(
  items: ReadonlyArray<Pick<RunItemSlim, 'root_cause' | 'root_cause_source'>>,
): RootCauseRow[] {
  const counts = new Map<string, { count: number; ai: boolean }>()
  for (const item of items) {
    const tag = item.root_cause?.trim()
    if (!tag) continue
    const entry = counts.get(tag) ?? { count: 0, ai: false }
    entry.count += 1
    if (item.root_cause_source === 'ai') entry.ai = true
    counts.set(tag, entry)
  }
  return Array.from(counts.entries())
    .map(([tag, { count, ai }]) => ({ tag, count, source: ai ? ('ai' as const) : ('human' as const) }))
    .sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag))
}

/** Error distribution rows from the run's error_summary.types map. */
export function errorDistribution(run: Pick<RunDetail, 'error_summary'>): Array<{ line: string; count: number }> {
  const types = run.error_summary?.types ?? {}
  return Object.entries(types)
    .map(([line, count]) => ({ line: firstErrorLine(line), count }))
    .sort((a, b) => b.count - a.count || a.line.localeCompare(b.line))
}

/* ── Expanded-row helpers ──────────────────────────────────────────────── */

/** Render any input/output/expected payload as text for a CodePanel. */
export function payloadToText(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

const DIFF_MAX_CHARS = 2000

/** Word-diff is offered only for two short, non-JSON text payloads. */
export function canWordDiff(output: unknown, expected: unknown): boolean {
  if (typeof output !== 'string' || typeof expected !== 'string') return false
  if (!output.trim() || !expected.trim()) return false
  if (output.length > DIFF_MAX_CHARS || expected.length > DIFF_MAX_CHARS) return false
  const looksJson = (s: string) => {
    const t = s.trim()
    return t.startsWith('{') || t.startsWith('[')
  }
  return !looksJson(output) && !looksJson(expected)
}
