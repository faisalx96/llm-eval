import { XCircle } from 'lucide-react'
import { cn } from '@/lib/cn'
import styles from './StatusBadge.module.css'

/** Every lifecycle status the platform renders. */
export const STATUSES = [
  'RUNNING',
  'PENDING',
  'COMPLETED',
  'FAILED',
  'STOPPED',
  'DRAFT',
  'SUBMITTED',
  'APPROVED',
  'REJECTED',
] as const

export type Status = (typeof STATUSES)[number]

/**
 * THE single status→hue map for the whole app. Charts, badges, and any
 * other status-colored UI must read from here — never invent a hue.
 *
 * Reserved semantics: red/green = fail/pass outcomes only, blue =
 * in-flight, amber = needs-attention, gray = inert metadata.
 */
export const STATUS_HUES: Record<Status, string> = {
  RUNNING: 'var(--info)',
  PENDING: 'var(--text-muted)',
  COMPLETED: 'var(--accent-secondary)',
  FAILED: 'var(--error)',
  STOPPED: 'var(--warning-dim)',
  DRAFT: 'var(--text-dim)',
  SUBMITTED: 'var(--warning)',
  APPROVED: 'var(--success)',
  REJECTED: 'var(--error)',
}

/**
 * Resolve a status hue to a concrete color string for canvas renderers
 * (echarts) that cannot consume CSS variables. Falls back to the raw
 * var() expression when the token cannot be resolved (e.g. jsdom).
 */
export function resolveStatusHue(status: Status, element?: Element): string {
  const raw = STATUS_HUES[status]
  const match = /^var\((--[\w-]+)\)$/.exec(raw)
  if (!match) return raw
  const ref = element ?? document.documentElement
  const resolved = getComputedStyle(ref).getPropertyValue(match[1]).trim()
  return resolved || raw
}

export interface StatusProgress {
  /** Percent complete, 0–100. */
  pct: number
  done: number
  total: number
}

export interface StatusBadgeProps {
  status: Status
  /** sm: tables/lists · md: hero size (run detail header) — same hues. */
  size?: 'sm' | 'md'
  /** Inline progress, rendered as 'RUNNING · 33% · 4/12'. */
  progress?: StatusProgress
  className?: string
}

export function StatusBadge({ status, size = 'sm', progress, className }: StatusBadgeProps) {
  return (
    <span className={cn(styles.badge, styles[size], styles[status.toLowerCase()], className)}>
      {status === 'RUNNING' && <span className={styles.pulseDot} aria-hidden="true" />}
      {(status === 'FAILED' || status === 'REJECTED') && (
        <XCircle className={styles.statusIcon} aria-hidden="true" />
      )}
      {progress
        ? `${status} · ${Math.round(progress.pct)}% · ${progress.done}/${progress.total}`
        : status}
    </span>
  )
}
