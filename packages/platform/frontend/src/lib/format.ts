/**
 * App-wide formatting ruleset — the SINGLE source of truth for rendering
 * data values in the UI. Ported from the useful legacy helpers
 * (`_static/dashboard/dashboard.js`, `metrics.js`, `trace_viewer.js`,
 * overview/admin inline scripts) and then standardized. New UI code should
 * import from here; `metrics.ts` keeps its own legacy formatters only for
 * golden parity with the old dashboard.
 *
 * PRECISION RULES (keep this table in sync with the implementations):
 *
 * - Missing/invalid values ALWAYS render the em dash '—' (never 'NaN',
 *   'null', 'Invalid Date' or empty string).
 * - Percentages ({@link fmtPercent}): input is a fraction (0..1). One decimal
 *   place by default ('52.8%'); exact 0 and exact 1 render '0%' and '100%'
 *   with no decimals. Pass `{ dp }` only when adjacent values would collide.
 * - Durations ({@link fmtMs}):
 *     < 1s   -> integer milliseconds        '129ms'
 *     < 10s  -> one decimal of seconds      '2.3s'
 *     < 60s  -> integer seconds             '42s'
 *     < 1h   -> minutes + seconds           '1m 46s'
 *     >= 1h  -> hours + minutes             '3h 10m'
 *   Negative durations are invalid -> '—'.
 * - Counts ({@link fmtCount}): grouped integer below 10,000 ('9,999'), then
 *   abbreviated with one decimal: '12.3K', '1.2M'.
 * - Token counts ({@link fmtTokens}): always exact, grouped with en-US
 *   thousands separators ('1,234,567') — token spend must stay auditable.
 * - Dates: absolute datetimes are 'MMM D, YYYY HH:mm' (24-hour, zero-padded
 *   minutes/hours, {@link fmtDateTime}); short form 'MMM D HH:mm'
 *   ({@link fmtShortDateTime}); date only 'MMM D, YYYY' ({@link fmtDate}).
 *   All in the viewer's local timezone.
 * - Relative time ({@link fmtRelativeTime}): 'just now' under a minute, then
 *   'Xm ago' / 'Xh ago' / 'Xd ago'; older than 30 days falls back to the
 *   absolute date. Future timestamps clamp to 'just now'. ALWAYS pair with
 *   an absolute `title` attribute — use {@link fmtRelativeTimeWithTitle}.
 * - Truncation ({@link middleEllipsis}): output is never longer than `max`
 *   characters, with a single '…' in the middle so both the start and the
 *   end of an id stay visible.
 *
 * All numeric strings use the en-US locale (pinned for determinism).
 */

const EM_DASH = '—'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export type DateInput = Date | string | number | null | undefined

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

/** Coerce to a valid Date or null (rejects empty strings and NaN dates). */
export function toDate(value: DateInput): Date | null {
  if (value === null || value === undefined || value === '') return null
  const d = value instanceof Date ? value : new Date(value)
  return Number.isNaN(d.getTime()) ? null : d
}

/**
 * Format a fraction (0..1) as a percentage. '52.8%' by default; exact 0/1
 * render '0%'/'100%'.
 */
export function fmtPercent(
  value: number | null | undefined,
  { dp = 1 }: { dp?: number } = {},
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EM_DASH
  if (value === 0) return '0%'
  if (value === 1) return '100%'
  return (value * 100).toFixed(dp) + '%'
}

/**
 * Format a duration in milliseconds: '129ms' / '2.3s' / '42s' / '1m 46s' /
 * '3h 10m'. Invalid or negative -> '—'.
 */
export function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms) || ms < 0) return EM_DASH
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)}s`
  const totalSeconds = Math.round(ms / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m ${seconds}s`
}

/**
 * Format an item/row count: grouped integer below 10K ('9,999'), then
 * '12.3K' / '1.2M'.
 */
export function fmtCount(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return EM_DASH
  const abs = Math.abs(n)
  if (abs >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (abs >= 10_000) return (n / 1_000).toFixed(1) + 'K'
  return Math.round(n).toLocaleString('en-US')
}

/**
 * Format a token count exactly with thousands separators ('1,234,567').
 * Token spend is auditable data — never abbreviate it.
 */
export function fmtTokens(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return EM_DASH
  return Math.round(n).toLocaleString('en-US')
}

/** Absolute datetime: 'Jun 11, 2026 14:30' (local time, 24-hour). */
export function fmtDateTime(value: DateInput): string {
  const d = toDate(value)
  if (!d) return EM_DASH
  return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`
}

/** Short datetime without year: 'Jun 11 14:30' (local time, 24-hour). */
export function fmtShortDateTime(value: DateInput): string {
  const d = toDate(value)
  if (!d) return EM_DASH
  return `${MONTHS[d.getMonth()]} ${d.getDate()} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`
}

/** Date only: 'Jun 11, 2026' (local time). */
export function fmtDate(value: DateInput): string {
  const d = toDate(value)
  if (!d) return EM_DASH
  return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`
}

const MINUTE = 60
const HOUR = 3600
const DAY = 86400
const RELATIVE_CUTOFF_DAYS = 30

/**
 * Relative time: 'just now' / '5m ago' / '2h ago' / '3d ago'; older than 30
 * days falls back to the absolute date ('Jun 11, 2026'). Future timestamps
 * clamp to 'just now'.
 *
 * Pair the rendered string with an absolute `title` attribute so the exact
 * timestamp is hoverable — see {@link fmtRelativeTimeWithTitle}.
 *
 * @param now - Injection point for tests; defaults to the current time.
 */
export function fmtRelativeTime(value: DateInput, now: DateInput = Date.now()): string {
  const d = toDate(value)
  const nowDate = toDate(now)
  if (!d || !nowDate) return EM_DASH
  const diff = Math.max(0, Math.floor((nowDate.getTime() - d.getTime()) / 1000))
  if (diff < MINUTE) return 'just now'
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)}m ago`
  if (diff < DAY) return `${Math.floor(diff / HOUR)}h ago`
  if (diff < RELATIVE_CUTOFF_DAYS * DAY) return `${Math.floor(diff / DAY)}d ago`
  return fmtDate(d)
}

/**
 * Relative label plus the absolute datetime for the `title` attribute:
 * `<span title={title}>{label}</span>`.
 */
export function fmtRelativeTimeWithTitle(
  value: DateInput,
  now: DateInput = Date.now(),
): { label: string; title: string } {
  return { label: fmtRelativeTime(value, now), title: fmtDateTime(value) }
}

/**
 * Truncate the middle of a long string, keeping head and tail visible:
 * middleEllipsis('0123456789abcdef', 9) -> '0123…cdef'. The result is never
 * longer than `max` characters. Null/undefined -> ''.
 */
export function middleEllipsis(str: string | null | undefined, max: number): string {
  const text = str ?? ''
  if (text.length <= max) return text
  if (max <= 1) return '…'
  const front = Math.ceil((max - 1) / 2)
  const back = max - 1 - front
  return text.slice(0, front) + '…' + (back > 0 ? text.slice(-back) : '')
}
