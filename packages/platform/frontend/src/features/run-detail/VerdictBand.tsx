import { StatCard } from '@/components/data'
import { ProgressBar } from '@/components/ui'
import { fmtPercent } from '@/lib/format'
import type { MetricStats, RunDetail } from '@/api/runDetail'
import { bucketIsFailing } from './lib'
import styles from './VerdictBand.module.css'

/** Mini 4-bucket distribution: neutral gray bars, failing buckets red only. */
function DistributionBar({ stat }: { stat: MetricStats }) {
  const buckets = stat.distribution ?? []
  if (buckets.length === 0) return null
  const max = Math.max(1, ...buckets.map((b) => b.count))
  return (
    <span className={styles.distribution} aria-hidden="true">
      {buckets.map((bucket) => (
        <span
          key={bucket.label}
          className={`${styles.bucket} ${bucketIsFailing(bucket.label) && bucket.count > 0 ? styles.bucketFail : ''}`}
          style={{ height: `${Math.max(8, (bucket.count / max) * 100)}%` }}
          title={`${bucket.label}: ${bucket.count}`}
        />
      ))}
    </span>
  )
}

export interface VerdictBandProps {
  run: RunDetail
  /** Items scored so far (drives min-n gating while RUNNING). */
  scored: number
  gated: boolean
  /** Clicking a metric card focuses the items table on that metric's failures. */
  onMetricClick: (metric: string) => void
}

/**
 * The above-the-fold verdict: one StatCard per metric with pass rate,
 * pass/fail counts and a mini score distribution. While RUNNING with fewer
 * than the minimum scored items it renders a neutral in-progress band
 * instead — no early judgement.
 */
export function VerdictBand({ run, scored, gated, onMetricClick }: VerdictBandProps) {
  const stats = run.metric_stats ?? []

  if (gated) {
    return (
      <section className={styles.gated} aria-label="Verdict (in progress)">
        <p className={styles.gatedCaption}>
          {scored} of {run.total_items} scored — too early to judge
        </p>
        <ProgressBar
          value={run.completed_items}
          max={Math.max(run.total_items, 1)}
          variant="neutral"
          label={`item ${run.completed_items} of ${run.total_items}`}
        />
      </section>
    )
  }

  if (stats.length === 0) return null

  return (
    <section className={styles.band} aria-label="Verdict">
      {stats.map((stat) => {
        const judged = stat.pass_count + stat.fail_count
        const passRate = judged > 0 ? stat.pass_count / judged : null
        return (
          <StatCard
            key={stat.name}
            className={styles.card}
            label={stat.name}
            value={fmtPercent(passRate)}
            sub={
              <span className={styles.sub}>
                <span>
                  {stat.pass_count} pass · {stat.fail_count} fail
                </span>
                <DistributionBar stat={stat} />
              </span>
            }
            onClick={() => onMetricClick(stat.name)}
          />
        )
      })}
    </section>
  )
}
