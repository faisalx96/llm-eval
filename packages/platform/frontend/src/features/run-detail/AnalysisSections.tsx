import { useState } from 'react'
import { Sparkles } from 'lucide-react'
import { ApiError } from '@/api/client'
import {
  CLIENT_ITEMS_CAP,
  useAllItemDetails,
  useAnalyzeRun,
  useRunCorrections,
  type RunDetail,
  type RunItemSlim,
} from '@/api/runDetail'
import { Button, Skeleton, useToast } from '@/components/ui'
import { fmtMs, fmtPercent } from '@/lib/format'
import { count } from '@/lib/pluralize'
import {
  aggregateByMetadata,
  errorDistribution,
  failureCount,
  rootCauseCounts,
} from './lib'
import styles from './AnalysisSections.module.css'

/**
 * Collapsed-by-default analysis accordions below the items table. Each
 * section is suppressed entirely when it has nothing to say.
 *
 * 'Performance by category' needs full item metadata, which only exists on
 * the per-item detail endpoint — it is fan-out fetched lazily on first open
 * and only offered for runs where every item is loaded (≤500).
 */
export function AnalysisSections({
  slug,
  run,
  items,
  allItemsLoaded,
  metric,
}: {
  slug: string
  run: RunDetail
  items: RunItemSlim[]
  allItemsLoaded: boolean
  metric: string | null
}) {
  const { toast } = useToast()
  const [categoryOpen, setCategoryOpen] = useState(false)
  const analyze = useAnalyzeRun(run.id)
  const corrections = useRunCorrections(slug, run.id)

  const selectedMetric = metric ?? run.metrics?.[0] ?? ''
  const categoryEligible = run.total_items <= CLIENT_ITEMS_CAP && allItemsLoaded
  const detailsQuery = useAllItemDetails(
    run.id,
    items.map((item) => item.item_id),
    categoryOpen && categoryEligible,
  )
  const categoryRows = detailsQuery.data ? aggregateByMetadata(detailsQuery.data, selectedMetric) : []

  const errorRows = errorDistribution(run)
  const rootCauses = rootCauseCounts(items)
  const failures = failureCount(items)
  const solutions = new Map<string, number>()
  for (const entry of corrections.data?.values() ?? []) {
    const solution = entry.human_solution || entry.ai_solution
    if (solution) solutions.set(solution, (solutions.get(solution) ?? 0) + 1)
  }

  const showCategory = categoryEligible && items.length > 0
  const showErrors = errorRows.length > 0 || run.error_items > 0
  const showRootCause = rootCauses.length > 0 || failures > 0

  if (!showCategory && !showErrors && !showRootCause && run.total_items <= CLIENT_ITEMS_CAP) {
    return null
  }

  return (
    <section className={styles.analysis} aria-label="Analysis">
      <h2 className={styles.heading}>Analysis</h2>

      {run.total_items > CLIENT_ITEMS_CAP && (
        <p className={styles.note}>
          Performance by category is hidden — it needs all items loaded and this run has more
          than {CLIENT_ITEMS_CAP}.
        </p>
      )}

      {showCategory && (
        <details
          className={styles.section}
          onToggle={(e) => setCategoryOpen((e.target as HTMLDetailsElement).open)}
        >
          <summary className={styles.summary}>Performance by category</summary>
          <div className={styles.sectionBody}>
            {detailsQuery.isLoading && <Skeleton height={64} />}
            {detailsQuery.isError && <p className={styles.note}>Could not load item metadata.</p>}
            {detailsQuery.isSuccess &&
              (categoryRows.length === 0 ? (
                <p className={styles.note}>No item metadata recorded on this run.</p>
              ) : (
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th scope="col">Group</th>
                      <th scope="col">Value</th>
                      <th scope="col" className={styles.num}>
                        Items
                      </th>
                      <th scope="col" className={styles.num}>
                        Avg {selectedMetric}
                      </th>
                      <th scope="col" className={styles.num}>
                        Avg latency
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {categoryRows.map((row) => (
                      <tr key={`${row.key}:${row.value}`}>
                        <td>{row.key}</td>
                        <td className={styles.mono}>{row.value}</td>
                        <td className={`${styles.num} ${styles.mono}`}>{row.n}</td>
                        <td className={`${styles.num} ${styles.mono}`}>{fmtPercent(row.avgScore)}</td>
                        <td className={`${styles.num} ${styles.mono}`}>{fmtMs(row.avgLatencyMs)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ))}
          </div>
        </details>
      )}

      {showErrors && (
        <details className={styles.section}>
          <summary className={styles.summary}>
            Error distribution ({count(run.error_items, 'item')})
          </summary>
          <div className={styles.sectionBody}>
            {errorRows.length === 0 ? (
              <p className={styles.note}>No error details recorded.</p>
            ) : (
              <ul className={styles.errorList}>
                {errorRows.map((row) => (
                  <li key={row.line} className={styles.errorRow}>
                    <span className={`${styles.mono} ${styles.errorLine}`}>{row.line}</span>
                    <span className={styles.errorCount}>{row.count}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </details>
      )}

      {showRootCause && (
        <details className={styles.section}>
          <summary className={styles.summary}>Root cause analysis</summary>
          <div className={styles.sectionBody}>
            {rootCauses.length === 0 ? (
              <p className={styles.note}>No root causes tagged yet.</p>
            ) : (
              <ul className={styles.tagList}>
                {rootCauses.map((row) => (
                  <li key={row.tag} className={styles.tagRow}>
                    <span className={`${styles.tag} ${row.source === 'ai' ? styles.tagAi : ''}`}>
                      {row.tag}
                    </span>
                    <span className={styles.mono}>{count(row.count, 'item')}</span>
                  </li>
                ))}
              </ul>
            )}
            {solutions.size > 0 && (
              <div className={styles.solutions}>
                <span className={styles.subLabel}>Proposed solutions</span>
                <ul className={styles.tagList}>
                  {Array.from(solutions.entries()).map(([solution, n]) => (
                    <li key={solution} className={styles.tagRow}>
                      <span className={styles.tag}>{solution}</span>
                      <span className={styles.mono}>{count(n, 'item')}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div>
              <Button
                size="sm"
                variant="secondary"
                icon={<Sparkles />}
                loading={analyze.isPending}
                onClick={() =>
                  analyze.mutate(undefined, {
                    onSuccess: () =>
                      toast({ title: 'Analysis started', variant: 'success' }),
                    onError: (error) =>
                      toast({
                        title: 'Auto-analyze unavailable',
                        description:
                          error instanceof ApiError && typeof error.detail === 'string'
                            ? error.detail
                            : 'Request failed',
                        variant: 'error',
                      }),
                  })
                }
              >
                Auto-analyze
              </Button>
            </div>
          </div>
        </details>
      )}
    </section>
  )
}
