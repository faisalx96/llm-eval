/**
 * Pure helpers behind the Runs list page: naming, grouping assembly,
 * client-side filters the server cannot express, metric baselines, and
 * small presentation utilities. Kept free of React for testability.
 */
import type { ProjectOverviewStats, RunSummary } from '@/api/runs'
import type { FilterBarState, TimeKey } from '@/components/data'
import { deriveRunName } from '@/lib/runIdentity'
import { count } from '@/lib/pluralize'

/** The single naming rule, adapted to the /v1 RunSummary shape.
 *  Never returns a UUID (see lib/runIdentity). */
export function runDisplayName(run: RunSummary): string {
  return deriveRunName({
    run_id: run.id,
    run_name: run.name,
    task_name: run.task,
    model_name: run.model ?? null,
    created_at: run.created_at ?? null,
    started_at: run.started_at ?? null,
  })
}

function runTimestamp(run: RunSummary): number {
  const raw = run.created_at ?? run.started_at
  const ts = raw ? new Date(raw).getTime() : NaN
  return Number.isNaN(ts) ? 0 : ts
}

/* ── Grouping ──────────────────────────────────────────────────────────── */

export interface RunGroup {
  key: string
  task: string
  dataset: string
  model: string | null
  /** Members, newest first. */
  runs: RunSummary[]
  /** Timestamp of the newest member — orders the group among other rows. */
  latestTs: number
}

export type RunRow =
  | { kind: 'run'; run: RunSummary; inGroup: boolean }
  | { kind: 'group'; group: RunGroup; collapsed: boolean }

/** Stable row id for DataTable selection/keyboard. */
export function rowId(row: RunRow): string {
  return row.kind === 'group' ? `group:${row.group.key}` : row.run.id
}

/** 'task · dataset · model · N runs' band label. */
export function groupLabel(group: RunGroup): string {
  const parts = [group.task, group.dataset]
  if (group.model) parts.push(group.model)
  parts.push(count(group.runs.length, 'run'))
  return parts.join(' · ')
}

/**
 * Organize a loaded page into display rows: runs sharing a non-empty
 * group_key with ≥2 members get a group header row followed by their
 * members (unless collapsed); everything else stays flat. Ordering is
 * -created_at within groups and across rows (groups sort by their newest
 * member).
 */
export function organizeRuns(
  runs: readonly RunSummary[],
  collapsedKeys: ReadonlySet<string> = new Set(),
): RunRow[] {
  const byKey = new Map<string, RunSummary[]>()
  for (const run of runs) {
    if (!run.group_key) continue
    const list = byKey.get(run.group_key)
    if (list) list.push(run)
    else byKey.set(run.group_key, [run])
  }

  type Unit = { ts: number; rows: RunRow[] }
  const units: Unit[] = []
  const grouped = new Set<string>()

  for (const [key, members] of byKey) {
    if (members.length < 2) continue
    const sorted = [...members].sort((a, b) => runTimestamp(b) - runTimestamp(a))
    const first = sorted[0]
    const group: RunGroup = {
      key,
      task: first.task,
      dataset: first.dataset,
      model: first.model ?? null,
      runs: sorted,
      latestTs: runTimestamp(first),
    }
    const collapsed = collapsedKeys.has(key)
    const rows: RunRow[] = [{ kind: 'group', group, collapsed }]
    if (!collapsed) {
      for (const run of sorted) rows.push({ kind: 'run', run, inGroup: true })
    }
    units.push({ ts: group.latestTs, rows })
    for (const run of sorted) grouped.add(run.id)
  }

  for (const run of runs) {
    if (grouped.has(run.id)) continue
    units.push({ ts: runTimestamp(run), rows: [{ kind: 'run', run, inGroup: false }] })
  }

  units.sort((a, b) => b.ts - a.ts)
  return units.flatMap((unit) => unit.rows)
}

/* ── Metric columns + baselines ────────────────────────────────────────── */

/** Union of metric names across the loaded page, alphabetical. */
export function computeMetricColumns(runs: readonly RunSummary[]): string[] {
  const names = new Set<string>()
  for (const run of runs) {
    for (const name of Object.keys(run.metric_averages ?? {})) names.add(name)
  }
  return [...names].sort()
}

function baselineTimestamp(run: RunSummary): number {
  const raw = run.started_at ?? run.created_at
  const ts = raw ? new Date(raw).getTime() : NaN
  return Number.isNaN(ts) ? 0 : ts
}

/**
 * For every run that shares a non-empty group_key with others on the page,
 * the previous run in that group by started_at — the delta baseline.
 */
export function computeBaselines(
  runs: readonly RunSummary[],
): Map<string, RunSummary> {
  const byKey = new Map<string, RunSummary[]>()
  for (const run of runs) {
    if (!run.group_key) continue
    const list = byKey.get(run.group_key)
    if (list) list.push(run)
    else byKey.set(run.group_key, [run])
  }
  const baselines = new Map<string, RunSummary>()
  for (const members of byKey.values()) {
    if (members.length < 2) continue
    const sorted = [...members].sort(
      (a, b) => baselineTimestamp(a) - baselineTimestamp(b),
    )
    for (let i = 1; i < sorted.length; i++) {
      baselines.set(sorted[i].id, sorted[i - 1])
    }
  }
  return baselines
}

/* ── Client-side filters (server has no equivalents) ───────────────────── */

const DAY_MS = 86_400_000

function withinTime(run: RunSummary, time: TimeKey, now: number): boolean {
  if (time === 'all' || time === 'custom') return true
  const ts = runTimestamp(run)
  if (ts === 0) return false
  if (time === 'today') {
    const a = new Date(ts)
    const b = new Date(now)
    return (
      a.getFullYear() === b.getFullYear() &&
      a.getMonth() === b.getMonth() &&
      a.getDate() === b.getDate()
    )
  }
  const windowMs = time === '7d' ? 7 * DAY_MS : 30 * DAY_MS
  return now - ts <= windowMs
}

function facetValue(run: RunSummary, facetId: string): string {
  switch (facetId) {
    case 'task':
      return run.task
    case 'model':
      return run.model ?? ''
    case 'dataset':
      return run.dataset
    case 'owner':
      return run.owner?.display_name ?? ''
    default:
      return ''
  }
}

/** Facets the server only accepts as single values. */
export const SINGLE_VALUE_FACETS = ['task', 'model', 'dataset', 'owner'] as const

/**
 * Apply the filters /v1/runs cannot express server-side: the time
 * quick-range, and task/model/dataset/owner facets when MORE than one value
 * is selected (single selections go to the server; status always does).
 */
export function applyClientFilters(
  runs: readonly RunSummary[],
  filter: Pick<FilterBarState, 'facets' | 'time'>,
  now: number = Date.now(),
): RunSummary[] {
  return runs.filter((run) => {
    if (!withinTime(run, filter.time, now)) return false
    for (const facetId of SINGLE_VALUE_FACETS) {
      const selected = filter.facets[facetId]
      if (selected && selected.length > 1 && !selected.includes(facetValue(run, facetId))) {
        return false
      }
    }
    return true
  })
}

/* ── Overview stat helpers ─────────────────────────────────────────────── */

/**
 * Share of finished runs that did not fail: everything that reached a
 * terminal state except FAILED/STOPPED, over all terminal runs. Null while
 * nothing has finished.
 */
export function successRate(stats: ProjectOverviewStats | undefined): number | null {
  if (!stats) return null
  const byStatus = stats.by_status ?? {}
  const inFlight =
    (byStatus.RUNNING ?? 0) + (byStatus.PENDING ?? 0) + (byStatus.DRAFT ?? 0)
  const finished = stats.total_runs - inFlight
  if (finished <= 0) return null
  const failed = (byStatus.FAILED ?? 0) + (byStatus.STOPPED ?? 0)
  return (finished - failed) / finished
}

/* ── Presentation helpers ──────────────────────────────────────────────── */

const MODEL_HUES = [
  'var(--chart-1)',
  'var(--chart-2)',
  'var(--chart-3)',
  'var(--chart-4)',
  'var(--chart-5)',
] as const

/** Deterministic chart-token hue for a model dot. */
export function modelHue(model: string): string {
  let hash = 0
  for (let i = 0; i < model.length; i++) {
    hash = (hash * 31 + model.charCodeAt(i)) | 0
  }
  return MODEL_HUES[Math.abs(hash) % MODEL_HUES.length]
}

/** 'Dev User' → 'DU'; single word → first two letters; empty → '?'. */
export function ownerInitials(name: string | null | undefined): string {
  const trimmed = (name ?? '').trim()
  if (!trimmed) return '?'
  const words = trimmed.split(/\s+/)
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase()
  return (words[0][0] + words[words.length - 1][0]).toUpperCase()
}

/** 'branch · short-commit' chip text, or null when no version info. */
export function versionLabel(run: RunSummary): string | null {
  const branch = run.version?.branch ?? null
  const commit = run.version?.commit ?? null
  if (!branch && !commit) return null
  const parts: string[] = []
  if (branch) parts.push(branch)
  if (commit) parts.push(commit.slice(0, 7))
  return parts.join(' · ')
}

/** Compare URL contract: /projects/:slug/compare?runs=a&runs=b… */
export function buildCompareUrl(slug: string, runIds: readonly string[]): string {
  const search = new URLSearchParams()
  for (const id of runIds) search.append('runs', id)
  return `/projects/${slug}/compare?${search.toString()}`
}

/* ── localStorage (per-project view preferences) ───────────────────────── */

export function columnsStorageKey(slug: string): string {
  return `qym.runs.columns.${slug}`
}

export function collapsedStorageKey(slug: string): string {
  return `qym.runs.collapsed.${slug}`
}

export function loadJson<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

export function saveJson(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Private mode etc. — preferences become per-session.
  }
}
