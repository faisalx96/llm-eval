import { ArrowDown, ArrowUp } from 'lucide-react'
import { cn } from '@/lib/cn'
import styles from './MetricDelta.module.css'

/**
 * Value + signed delta vs baseline. Text + small arrow only — never a solid
 * background fill (the anti-green-flood rule).
 *
 * Color encodes GOODNESS, arrow encodes DIRECTION:
 * - green when the change is an improvement, red when a regression
 *   (`higherIsBetter`, default true; pass false for latency-style metrics)
 * - neutral gray when there is no baseline or the delta is zero.
 */

export type MetricFormat = 'number' | 'percent' | 'ms' | ((v: number) => string)

export interface MetricDeltaProps {
  value: number
  /** Comparison baseline. Omit/null → value renders alone, neutral. */
  baseline?: number | null
  /** Default true. Set false when lower is better (latency, cost, errors). */
  higherIsBetter?: boolean
  /**
   * 'percent' expects a 0–1 ratio (0.831 → "83.1%"); 'ms' expects
   * milliseconds; 'number' is the default. A function fully customizes.
   */
  fmt?: MetricFormat
  className?: string
}

function trimZeros(s: string): string {
  return s.includes('.') ? s.replace(/\.?0+$/, '') : s
}

function formatMs(v: number): string {
  const abs = Math.abs(v)
  if (abs >= 1000) return `${trimZeros((v / 1000).toFixed(2))}s`
  if (abs >= 10) return `${Math.round(v)}ms`
  return `${trimZeros(v.toFixed(1))}ms`
}

export function formatMetric(v: number, fmt: MetricFormat = 'number'): string {
  if (typeof fmt === 'function') return fmt(v)
  switch (fmt) {
    case 'percent':
      return `${trimZeros((v * 100).toFixed(1))}%`
    case 'ms':
      return formatMs(v)
    default:
      if (Math.abs(v) >= 1000) {
        return v.toLocaleString('en-US', { maximumFractionDigits: 0 })
      }
      return trimZeros(v.toFixed(2))
  }
}

export function MetricDelta({
  value,
  baseline,
  higherIsBetter = true,
  fmt = 'number',
  className,
}: MetricDeltaProps) {
  const hasBaseline =
    baseline !== undefined && baseline !== null && Number.isFinite(baseline)
  const delta = hasBaseline ? value - baseline : 0
  const tone: 'good' | 'bad' | 'neutral' =
    !hasBaseline || delta === 0
      ? 'neutral'
      : delta > 0 === higherIsBetter
        ? 'good'
        : 'bad'
  const sign = delta > 0 ? '+' : delta < 0 ? '−' : '±'

  return (
    <span className={cn(styles.root, className)}>
      <span className={styles.value}>{formatMetric(value, fmt)}</span>
      {hasBaseline && (
        <span
          className={styles.delta}
          data-tone={tone}
          title={`Baseline ${formatMetric(baseline, fmt)}`}
        >
          {delta > 0 ? (
            <ArrowUp size={11} className={styles.arrow} aria-hidden="true" />
          ) : delta < 0 ? (
            <ArrowDown size={11} className={styles.arrow} aria-hidden="true" />
          ) : null}
          {sign}
          {formatMetric(Math.abs(delta), fmt)}
        </span>
      )}
    </span>
  )
}
