import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'
import styles from './ProgressBar.module.css'

export interface ProgressBarProps {
  /** Current value, clamped to [0, max]. */
  value: number
  max?: number
  /** Visible label slot rendered above the track. */
  label?: ReactNode
  /** Accessible name when the label is absent or non-textual. */
  'aria-label'?: string
  /** accent: teal · neutral: gray (for non-semantic quantities). */
  variant?: 'accent' | 'neutral'
  className?: string
}

export function ProgressBar({
  value,
  max = 100,
  label,
  variant = 'accent',
  className,
  ...rest
}: ProgressBarProps) {
  const clamped = Math.min(Math.max(value, 0), max)
  const pct = max > 0 ? (clamped / max) * 100 : 0
  const ariaLabel = rest['aria-label'] ?? (typeof label === 'string' ? label : undefined)

  return (
    <div className={cn(styles.wrap, className)}>
      {label != null && <div className={styles.label}>{label}</div>}
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={clamped}
        aria-label={ariaLabel}
        className={cn(styles.track, styles[variant])}
      >
        <div className={styles.fill} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}
