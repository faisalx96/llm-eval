import { useEffect, useMemo, useState } from 'react'
import { Activity, ChevronRight, Inbox } from 'lucide-react'
import { DataTable, type DataTableColumn, type Row } from '@/components/data'
import { EmptyState, IconButton, Tooltip } from '@/components/ui'
import { TraceDrawer } from '@/components/trace'
import {
  CLIENT_ITEMS_CAP,
  useRunCorrections,
  useRunItems,
  type RunDetail,
  type RunItemSlim,
  type RunItemsParams,
} from '@/api/runDetail'
import { fmtMs, fmtPercent } from '@/lib/format'
import {
  METRIC_THRESHOLD,
  applyClientView,
  defaultSegment,
  failureCount,
  itemOutcome,
  metricScore,
  type Segment,
  type SortKey,
} from './lib'
import { ItemExpanded } from './ItemExpanded'
import styles from './ItemsPanel.module.css'

const SEARCH_DEBOUNCE_MS = 300

export interface ItemsPanelProps {
  slug: string
  run: RunDetail
  /** null = automatic default (Failures when any exist, else All). */
  segment: Segment | null
  onSegmentChange: (segment: Segment) => void
  metric: string | null
  onMetricChange: (metric: string | null) => void
  canReview: boolean
}

/**
 * The items table — the centerpiece of the page.
 *
 * Data strategy: items are paged 100/request server-side; for runs at/below
 * CLIENT_ITEMS_CAP (500) every page is fetched up front so segment/metric
 * filtering and sorting run instantly client-side (only the search `q` hits
 * the server). Above the cap the toolbar filters are translated to the
 * server query params (failed_only / metric+below / sort) and only the
 * first 500 matching rows are shown, with a note.
 */
export function ItemsPanel({
  slug,
  run,
  segment,
  onSegmentChange,
  metric,
  onMetricChange,
  canReview,
}: ItemsPanelProps) {
  const [q, setQ] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const [sort, setSort] = useState<SortKey>('failures')
  const [traceItemId, setTraceItemId] = useState<string | null>(null)

  useEffect(() => {
    const handle = window.setTimeout(() => setDebouncedQ(q.trim()), SEARCH_DEBOUNCE_MS)
    return () => window.clearTimeout(handle)
  }, [q])

  const clientMode = run.total_items <= CLIENT_ITEMS_CAP

  const params = useMemo<RunItemsParams>(() => {
    if (clientMode) {
      return debouncedQ ? { q: debouncedQ } : {}
    }
    // Server-mode approximations for >cap runs: 'failures' maps to task
    // errors (failed_only) unless a metric is chosen, which maps exactly.
    const out: RunItemsParams = {}
    if (debouncedQ) out.q = debouncedQ
    if (metric) {
      out.metric = metric
      out.below = METRIC_THRESHOLD
    } else if ((segment ?? 'failures') === 'failures') {
      out.failed_only = true
    }
    out.sort = sort === 'failures' ? 'score' : sort
    return out
  }, [clientMode, debouncedQ, metric, segment, sort])

  const itemsQuery = useRunItems(run.id, params, { poll: run.status === 'RUNNING' })
  const items = useMemo(() => itemsQuery.data?.items ?? [], [itemsQuery.data])
  const total = itemsQuery.data?.total ?? run.total_items
  const truncated = itemsQuery.data?.truncated ?? false

  const failures = failureCount(items)
  const effectiveSegment: Segment = segment ?? defaultSegment(items)

  const view = useMemo(
    () =>
      clientMode
        ? applyClientView(items, { segment: effectiveSegment, metric, sort })
        : items,
    [clientMode, items, effectiveSegment, metric, sort],
  )

  const corrections = useRunCorrections(slug, run.id)

  const columns = useMemo<DataTableColumn<RunItemSlim>[]>(() => {
    const metricNames = run.metrics ?? []
    const cols: DataTableColumn<RunItemSlim>[] = [
      {
        id: 'expand',
        size: 30,
        enableSorting: false,
        header: '',
        cell: ({ row }) => (
          <button
            type="button"
            className={styles.expander}
            aria-label={row.getIsExpanded() ? 'Collapse item' : 'Expand item'}
            aria-expanded={row.getIsExpanded()}
            onClick={() => row.toggleExpanded()}
          >
            <ChevronRight
              size={13}
              className={row.getIsExpanded() ? styles.chevronOpen : styles.chevron}
              aria-hidden="true"
            />
          </button>
        ),
      },
      {
        id: 'index',
        accessorKey: 'index',
        header: '#',
        size: 44,
        enableSorting: false,
        meta: { mono: true, align: 'right' },
      },
      {
        id: 'status',
        size: 44,
        enableSorting: false,
        header: 'Status',
        cell: ({ row }) => {
          const outcome = itemOutcome(row.original)
          return (
            <span className={styles.dotWrap}>
              <span className={`${styles.dot} ${styles[`dot_${outcome}`]}`} aria-hidden="true" />
              <span className={styles.srOnly}>{outcome}</span>
            </span>
          )
        },
      },
      {
        id: 'input',
        accessorKey: 'input_preview',
        header: 'Input',
        enableSorting: false,
        cell: ({ getValue }) => (
          <span className={styles.preview}>{String(getValue() ?? '')}</span>
        ),
        meta: { mono: true },
      },
      {
        id: 'output',
        accessorKey: 'output_preview',
        header: 'Output',
        enableSorting: false,
        cell: ({ getValue }) => (
          <span className={styles.preview}>{String(getValue() ?? '')}</span>
        ),
        meta: { mono: true },
      },
      ...metricNames.map(
        (name): DataTableColumn<RunItemSlim> => ({
          id: `metric:${name}`,
          header: name,
          size: 96,
          enableSorting: false,
          meta: { mono: true, align: 'right' },
          cell: ({ row }) => {
            const score = metricScore(row.original.metric_values?.[name])
            if (score === null) return <span className={styles.noScore}>—</span>
            // Red text is allowed here: below-threshold IS the fail semantic.
            return (
              <span className={score < METRIC_THRESHOLD ? styles.scoreFail : undefined}>
                {fmtPercent(score)}
              </span>
            )
          },
        }),
      ),
      {
        id: 'latency',
        header: 'Latency',
        size: 76,
        enableSorting: false,
        meta: { mono: true, align: 'right' },
        cell: ({ row }) => fmtMs(row.original.latency_ms),
      },
      {
        id: 'rootCause',
        header: 'Root cause',
        size: 130,
        enableSorting: false,
        cell: ({ row }) => {
          const tag = row.original.root_cause
          if (!tag) return null
          const ai = row.original.root_cause_source === 'ai'
          return <span className={`${styles.tag} ${ai ? styles.tagAi : ''}`}>{tag}</span>
        },
      },
      {
        id: 'trace',
        header: '',
        size: 40,
        enableSorting: false,
        meta: { pinRight: true, align: 'center' },
        cell: ({ row }) => {
          if (!row.original.has_trace) {
            return (
              <Tooltip content="No trace recorded">
                <span className={styles.traceDisabled}>
                  <IconButton
                    aria-label="No trace recorded"
                    icon={<Activity />}
                    size="sm"
                    tooltip={null}
                    disabled
                  />
                </span>
              </Tooltip>
            )
          }
          return (
            <IconButton
              aria-label="View trace"
              icon={<Activity />}
              size="sm"
              tooltip="View trace"
              onClick={() => setTraceItemId(row.original.item_id)}
            />
          )
        },
      },
    ]
    return cols
  }, [run.metrics])

  return (
    <section className={styles.panel} aria-label="Run items">
      <div className={styles.toolbar}>
        <div className={styles.segmented} role="group" aria-label="Item subset">
          <button
            type="button"
            className={styles.segment}
            aria-pressed={effectiveSegment === 'failures'}
            onClick={() => onSegmentChange('failures')}
          >
            Failures ({failures})
          </button>
          <button
            type="button"
            className={styles.segment}
            aria-pressed={effectiveSegment === 'all'}
            onClick={() => onSegmentChange('all')}
          >
            All ({total})
          </button>
        </div>

        <label className={styles.control}>
          <span className={styles.controlLabel}>Metric</span>
          <select
            className={styles.select}
            value={metric ?? ''}
            onChange={(e) => onMetricChange(e.target.value || null)}
          >
            <option value="">All metrics</option>
            {(run.metrics ?? []).map((name) => (
              <option key={name} value={name}>
                {name} below {METRIC_THRESHOLD}
              </option>
            ))}
          </select>
        </label>

        <input
          type="search"
          className={styles.search}
          placeholder="Search input/output"
          aria-label="Search items"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />

        <label className={styles.control}>
          <span className={styles.controlLabel}>Sort</span>
          <select
            className={styles.select}
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
          >
            <option value="failures">Failures first</option>
            <option value="index">Index</option>
            <option value="latency">Fastest first</option>
            <option value="-latency">Slowest first</option>
          </select>
        </label>
      </div>

      {truncated && (
        <p className={styles.truncatedNote}>
          Showing the first {CLIENT_ITEMS_CAP} of {total} items — filters run server-side for
          large runs.
        </p>
      )}

      <DataTable<RunItemSlim>
        data={view}
        columns={columns}
        getRowId={(item) => item.item_id}
        virtualized
        estimateRowHeight={34}
        maxHeight={580}
        loading={itemsQuery.isPending}
        aria-label="Run items table"
        getRowCanExpand={() => true}
        onRowClick={(row) => row.toggleExpanded()}
        renderSubComponent={(row: Row<RunItemSlim>) => (
          <ItemExpanded
            runId={run.id}
            itemId={row.original.item_id}
            correction={corrections.data?.get(row.original.item_id)}
            canReview={canReview}
          />
        )}
        empty={
          <EmptyState
            icon={<Inbox />}
            title="No items match"
            description={
              effectiveSegment === 'failures' && !metric && !debouncedQ
                ? 'Every item passed — switch to All to browse them.'
                : 'Try clearing the metric filter or search.'
            }
          />
        }
      />

      <TraceDrawer
        runId={run.id}
        itemId={traceItemId ?? ''}
        open={traceItemId !== null}
        onOpenChange={(open) => {
          if (!open) setTraceItemId(null)
        }}
      />
    </section>
  )
}
