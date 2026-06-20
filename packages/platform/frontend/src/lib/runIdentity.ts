/**
 * Run naming: a single rule for what to call a run anywhere in the UI.
 *
 * The legacy dashboard derived run labels ad hoc in at least four places
 * (`runName()` in admin.html, `getRunDisplayName()` in dashboard.js,
 * `getCompareRunDisplayNameById()` in compare.html, plus inline fallbacks).
 * This module standardizes the rule:
 *
 *   1. Prefer a human-given name: top-level `display_name`, then
 *      `run_metadata.display_name` / `.name` / `.run_name`, then `run_name`,
 *      then `external_run_id` — first non-empty candidate that is NOT a UUID.
 *   2. Otherwise compose 'task · model · MMM D HH:mm' from whatever of
 *      task name, model name (provider prefix stripped) and start timestamp
 *      is available.
 *   3. Otherwise fall back to a non-UUID `run_id`, or 'Run <first8>' for a
 *      UUID id, or 'Untitled run'.
 *
 * INVARIANT: deriveRunName never returns a bare UUID.
 */

import { fmtShortDateTime, toDate, type DateInput } from './format'

/** Canonical hyphenated UUID (any version), case-insensitive. */
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** True when `str` (trimmed) is a canonical hyphenated UUID. */
export function isUuid(str: string | null | undefined): boolean {
  if (typeof str !== 'string') return false
  return UUID_RE.test(str.trim())
}

/**
 * Remove a provider prefix from a model name:
 * 'qwen/qwen3-235b' -> 'qwen3-235b'. (Ported from legacy dashboard.js.)
 */
export function stripModelProvider(modelName: string | null | undefined): string {
  if (!modelName) return ''
  const slashIdx = modelName.indexOf('/')
  return slashIdx > 0 ? modelName.slice(slashIdx + 1) : modelName
}

export interface RunMetadataLike {
  name?: string | null
  display_name?: string | null
  run_name?: string | null
  [key: string]: unknown
}

/** Minimal run shape accepted by {@link deriveRunName}. */
export interface RunLike {
  run_id?: string | null
  run_name?: string | null
  display_name?: string | null
  external_run_id?: string | null
  run_metadata?: RunMetadataLike | null
  task_name?: string | null
  model_name?: string | null
  created_at?: DateInput
  started_at?: DateInput
  timestamp?: DateInput
  [key: string]: unknown
}

function cleanCandidate(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  if (!trimmed || isUuid(trimmed)) return null
  return trimmed
}

/**
 * Derive the display name for a run. Never returns a UUID; see the module
 * docstring for the full preference order.
 */
export function deriveRunName(run: RunLike | null | undefined): string {
  if (!run) return 'Untitled run'

  const metadata = run.run_metadata || {}
  const candidates: unknown[] = [
    run.display_name,
    metadata.display_name,
    metadata.name,
    metadata.run_name,
    run.run_name,
    run.external_run_id,
  ]
  for (const candidate of candidates) {
    const cleaned = cleanCandidate(candidate)
    if (cleaned) return cleaned
  }

  // Compose 'task · model · MMM D HH:mm' from whatever is available.
  const parts: string[] = []
  const task = typeof run.task_name === 'string' ? run.task_name.trim() : ''
  if (task) parts.push(task)
  const model = stripModelProvider(
    typeof run.model_name === 'string' ? run.model_name.trim() : '',
  )
  if (model) parts.push(model)
  const startedAt = toDate(run.created_at) ?? toDate(run.started_at) ?? toDate(run.timestamp)
  if (startedAt) parts.push(fmtShortDateTime(startedAt))
  if (parts.length > 0) return parts.join(' · ')

  // Last resorts — still never a UUID.
  const runId = typeof run.run_id === 'string' ? run.run_id.trim() : ''
  if (runId) {
    if (!isUuid(runId)) return runId
    return `Run ${runId.slice(0, 8)}`
  }
  return 'Untitled run'
}
