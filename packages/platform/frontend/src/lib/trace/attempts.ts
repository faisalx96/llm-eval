/**
 * Attempt normalization ported from the legacy trace viewer
 * (qym_platform/_static/dashboard/trace_viewer.js `normalizeAttempts`,
 * L150-187), rewritten as a pure function: the input payload is not mutated.
 *
 * Guarantees of the returned shape:
 *  - `attempts` is always non-empty; payloads without attempts get a single
 *    synthetic attempt from the top-level item/summary/spans
 *  - every attempt has a numeric `attempt_number` (1-based fallback) and a
 *    spans array
 *  - top-level `summary`/`spans` mirror the LAST attempt (legacy kept the
 *    drawer header in sync with the latest attempt this way)
 *  - `item.retry_count` defaults to attempts.length - 1
 */

import type { TraceAttempt, TraceData } from './types'

export function normalizeAttempts(data: TraceData | null | undefined): TraceData {
  const source = data ?? {}
  const hasAttempts = Array.isArray(source.attempts) && source.attempts.length > 0

  // Legacy L152-163: synthesize a single attempt when the payload predates
  // the attempts field.
  const baseAttempts: TraceAttempt[] = hasAttempts
    ? (source.attempts as TraceAttempt[])
    : [
        {
          attempt_number: 1,
          status: source.item?.trace_id ? 'completed' : 'failed',
          latency_ms: source.item?.latency_ms ?? null,
          task_started_at_ms: null,
          trace_id: source.item?.trace_id ?? '',
          trace_url: source.item?.trace_url ?? '',
          error: null,
          is_last_attempt: true,
          summary: source.summary ?? {},
          spans: Array.isArray(source.spans) ? source.spans : [],
        },
      ]

  // Legacy L164-173: coerce attempt_number, default summary/spans.
  const attempts: TraceAttempt[] = baseAttempts.map((attempt, idx) => ({
    ...attempt,
    attempt_number: Number(attempt.attempt_number || idx + 1),
    summary: attempt.summary ?? {},
    spans: Array.isArray(attempt.spans) ? attempt.spans : [],
  }))

  // Legacy L174: the attempt the header/top-level fields mirror.
  const lastAttempt =
    attempts.find((a) => a.is_last_attempt) ?? attempts[attempts.length - 1] ?? null

  // Legacy L175-181: backfill item retry_count / trace ids from the last attempt.
  const item = source.item
    ? {
        ...source.item,
        retry_count: Number(source.item.retry_count || Math.max(0, attempts.length - 1)),
        trace_id: lastAttempt?.trace_id || source.item.trace_id || '',
        trace_url: lastAttempt?.trace_url || source.item.trace_url || '',
      }
    : source.item

  // Legacy L182-185: top-level summary/spans mirror the last attempt.
  return {
    ...source,
    item,
    attempts,
    summary: lastAttempt ? (lastAttempt.summary ?? {}) : source.summary,
    spans: lastAttempt ? (lastAttempt.spans ?? []) : source.spans,
  }
}

/**
 * Pick the attempt to display: the requested attempt number, else the last
 * attempt, else the final entry. Ported from legacy `currentAttemptData`
 * (L189-198).
 */
export function selectAttempt(
  attempts: TraceAttempt[] | undefined,
  attemptNumber: number | null | undefined,
): TraceAttempt | null {
  const list = attempts ?? []
  if (!list.length) return null
  return (
    list.find((a) => Number(a.attempt_number) === Number(attemptNumber ?? 0)) ??
    list.find((a) => a.is_last_attempt) ??
    list[list.length - 1] ??
    list[0]
  )
}
