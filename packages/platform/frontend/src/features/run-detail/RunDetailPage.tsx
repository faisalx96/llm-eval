import { useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { AlertTriangle } from 'lucide-react'
import { useMe } from '@/api/queries'
import { useRunDetail, useRunItems, type RunItemsParams } from '@/api/runDetail'
import { Button, EmptyState, Skeleton, SkeletonText } from '@/components/ui'
import { deriveRunName } from '@/lib/runIdentity'
import { AnalysisSections } from './AnalysisSections'
import { FailedBanner, GovernanceBanner } from './GovernanceBanner'
import { ItemsPanel } from './ItemsPanel'
import { RunHero } from './RunHero'
import { TraceStatsSection } from './TraceStatsSection'
import { VerdictBand } from './VerdictBand'
import { isVerdictGated, scoredItemCount, type Segment } from './lib'
import styles from './RunDetailPage.module.css'

/** Stable identity so this query shares its cache with the items panel. */
const UNFILTERED: RunItemsParams = {}

/**
 * Run detail (route /projects/:slug/runs/:runId).
 *
 * Structure per the approved redesign: verdict above the fold, failures-first
 * items table immediately after, analysis collapsed below, governance
 * context always visible.
 */
export default function RunDetailPage() {
  const { slug = '', runId = '' } = useParams()
  const me = useMe().data
  const runQuery = useRunDetail(runId)
  const run = runQuery.data

  // Toolbar state that outside surfaces (verdict band) can drive.
  const [segment, setSegment] = useState<Segment | null>(null)
  const [metric, setMetric] = useState<string | null>(null)
  const itemsRef = useRef<HTMLDivElement | null>(null)

  // Unfiltered items power min-n gating + the analysis aggregations; the
  // panel's own (identical) base query shares this cache entry.
  const baseItems = useRunItems(runId, UNFILTERED, { poll: run?.status === 'RUNNING' })
  const items = useMemo(() => baseItems.data?.items ?? [], [baseItems.data])

  if (runQuery.isPending) {
    return (
      <div className={styles.page} aria-busy="true">
        <p className={styles.srOnly} role="status">
          Loading run…
        </p>
        <Skeleton width={420} height={24} />
        <Skeleton width="100%" height={84} />
        <SkeletonText lines={6} />
      </div>
    )
  }

  if (runQuery.isError || !run) {
    return (
      <div className={styles.page}>
        <EmptyState
          icon={<AlertTriangle />}
          title="Could not load this run"
          description={runQuery.error instanceof Error ? runQuery.error.message : undefined}
          action={
            <Button variant="secondary" onClick={() => void runQuery.refetch()}>
              Retry
            </Button>
          }
        />
      </div>
    )
  }

  // deriveRunName never shows a UUID — falls back to task · model · time.
  const runName = deriveRunName({
    run_id: run.id,
    run_name: run.name,
    run_metadata: run.run_metadata,
    task_name: run.task,
    model_name: run.model,
    started_at: run.started_at,
    created_at: run.created_at,
  })

  const isManager = Boolean(
    me && (me.role === 'ADMIN' || me.projects.find((p) => p.slug === slug)?.role === 'MANAGER'),
  )

  // Min-n verdict gating: prefer the real scored count once items loaded.
  const scored = items.length > 0 ? scoredItemCount(items) : run.completed_items
  const gated = isVerdictGated(run.status, scored)

  const focusMetricFailures = (name: string) => {
    setMetric(name)
    setSegment('failures')
    itemsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className={styles.page}>
      <RunHero slug={slug} run={run} runName={runName} me={me} />
      <GovernanceBanner slug={slug} run={run} runName={runName} me={me} />
      <FailedBanner run={run} />
      <VerdictBand run={run} scored={scored} gated={gated} onMetricClick={focusMetricFailures} />
      <TraceStatsSection run={run} />

      <div ref={itemsRef} className={styles.items}>
        <h2 className={styles.sectionHeading}>Items</h2>
        <ItemsPanel
          slug={slug}
          run={run}
          segment={segment}
          onSegmentChange={setSegment}
          metric={metric}
          onMetricChange={setMetric}
          canReview={isManager}
        />
      </div>

      <AnalysisSections
        slug={slug}
        run={run}
        items={items}
        allItemsLoaded={Boolean(baseItems.data && !baseItems.data.truncated)}
        metric={metric}
      />
    </div>
  )
}
