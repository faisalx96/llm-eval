/**
 * Runs list — the core daily screen of a project (route /projects/:slug).
 *
 * Server-paginated /v1/runs table with status/task/model/dataset/owner
 * facets, a needs-review queue toggle, client-side run grouping by
 * group_key, inline rename, the review workflow (submit/approve/reject),
 * HTML export and truthful soft-delete.
 */
import { useCallback, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Check,
  ChevronDown,
  ChevronRight,
  Columns3,
  FlaskConical,
  MoreVertical,
  Pencil,
} from 'lucide-react'
import { useMe, useProjects } from '@/api/queries'
import {
  exportHtmlUrl,
  useApproveRun,
  useDeleteRuns,
  useNeedsReviewCount,
  useProjectOverviewStats,
  useRejectRun,
  useRenameRun,
  useRunsList,
  useSubmitRun,
  type RunListParams,
  type RunSummary,
} from '@/api/runs'
import {
  DataTable,
  FilterBar,
  MetricDelta,
  Pagination,
  computeZeroEntropyColumns,
  createSelectionColumn,
  EMPTY_FILTER_STATE,
  type DataTableColumn,
  type FacetConfig,
  type FilterBarState,
  type Row,
  type RowSelectionState,
  type VisibilityState,
} from '@/components/data'
import {
  Button,
  ConfirmModal,
  DropdownMenu,
  DropdownMenuItem,
  DropdownMenuSeparator,
  EmptyState,
  IconButton,
  StatusBadge,
  STATUSES,
  Toaster,
  type Status,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import {
  fmtCount,
  fmtMs,
  fmtPercent,
  fmtRelativeTimeWithTitle,
  middleEllipsis,
} from '@/lib/format'
import { count } from '@/lib/pluralize'
import {
  applyClientFilters,
  buildCompareUrl,
  collapsedStorageKey,
  columnsStorageKey,
  computeBaselines,
  computeMetricColumns,
  groupLabel,
  loadJson,
  modelHue,
  organizeRuns,
  ownerInitials,
  rowId,
  runDisplayName,
  saveJson,
  successRate,
  versionLabel,
  type RunRow,
} from './lib'
import styles from './RunsPage.module.css'

const NAME_MAX_CHARS = 48

const SDK_SNIPPET =
  'pip install qym\nqym run create --task-file my_task.py --task-function my_task --dataset my-dataset --metrics exact_match'

/** Columns the visibility menu lists under "System". Status and Name are
 *  always shown and intentionally not toggleable. */
const SYSTEM_COLUMNS: ReadonlyArray<{ id: string; label: string }> = [
  { id: 'task', label: 'Task' },
  { id: 'model', label: 'Model' },
  { id: 'dataset', label: 'Dataset' },
  { id: 'version', label: 'Version' },
  { id: 'date', label: 'Date' },
  { id: 'duration', label: 'Duration' },
  { id: 'owner', label: 'Owner' },
]

/** Candidates for zero-entropy auto-hide (identical across the page). */
const ZERO_ENTROPY_CANDIDATES = ['dataset', 'version'] as const

type PendingAction =
  | { type: 'approve' | 'reject'; run: RunSummary }
  | { type: 'delete'; runs: RunSummary[] }

function isKnownStatus(status: string): status is Status {
  return (STATUSES as readonly string[]).includes(status)
}

function metricLabel(metric: string): string {
  return metric.replace(/_/g, ' ')
}

/** Stable ref callback so React only focuses on mount, not every render. */
function focusAndSelect(el: HTMLInputElement | null): void {
  if (el) {
    el.focus()
    el.select()
  }
}

function zeroEntropyValue(run: RunSummary, id: string): unknown {
  return id === 'version' ? versionLabel(run) : run.dataset
}

/* ── Small presentational bits ─────────────────────────────────────────── */

function StatChip({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.statChip}>
      <span className={styles.statLabel}>{label}</span>
      <span className={styles.statValue}>{value}</span>
    </div>
  )
}

function OwnerCell({ run }: { run: RunSummary }) {
  const name = run.owner?.display_name || run.owner?.email || ''
  if (!name) return <span className={styles.dim}>—</span>
  return (
    <span className={styles.owner}>
      <span className={styles.avatar} aria-hidden="true">
        {ownerInitials(name)}
      </span>
      <span className={styles.ownerName}>{name}</span>
    </span>
  )
}

function StatusCell({ run }: { run: RunSummary }) {
  const status = run.status
  const inFlight = status === 'RUNNING' || status === 'PENDING'
  const progress =
    status === 'RUNNING' && run.total_items > 0
      ? {
          pct: (run.progress_pct ?? run.completed_items / run.total_items) * 100,
          done: run.completed_items,
          total: run.total_items,
        }
      : undefined
  return (
    <span className={styles.statusCell}>
      {isKnownStatus(status) ? (
        <StatusBadge status={status} size="sm" progress={progress} />
      ) : (
        <span>{status}</span>
      )}
      {!inFlight && run.error_items > 0 && (
        <span className={styles.errorChip}>· {count(run.error_items, 'error')}</span>
      )}
    </span>
  )
}

/* ── Page ──────────────────────────────────────────────────────────────── */

export default function RunsPage() {
  const { slug = '' } = useParams()
  // Remount per project so filters/selection/preferences re-initialize.
  return <RunsView key={slug} slug={slug} />
}

function RunsView({ slug }: { slug: string }) {
  const navigate = useNavigate()
  const { data: me } = useMe()
  const { data: projects } = useProjects()
  const project = projects?.find((p) => p.slug === slug)

  const stats = useProjectOverviewStats(project?.id)
  const needsReviewCount = useNeedsReviewCount(slug)

  /* View state. */
  const [filter, setFilter] = useState<FilterBarState>(EMPTY_FILTER_STATE)
  const [needsReviewOnly, setNeedsReviewOnly] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({})
  const [editingRunId, setEditingRunId] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null)
  const [collapsedGroups, setCollapsedGroups] = useState<ReadonlySet<string>>(
    () => new Set(loadJson<string[]>(collapsedStorageKey(slug), [])),
  )
  const [columnOverrides, setColumnOverrides] = useState<Record<string, boolean>>(() =>
    loadJson<Record<string, boolean>>(columnsStorageKey(slug), {}),
  )

  /* Server query. Single facet selections go to the server; multi-select
     falls back to client-side filtering (see lib.applyClientFilters). */
  const listParams: RunListParams = useMemo(
    () => ({
      projectSlug: slug,
      statuses: filter.facets.status,
      task: filter.facets.task?.length === 1 ? filter.facets.task[0] : undefined,
      model: filter.facets.model?.length === 1 ? filter.facets.model[0] : undefined,
      dataset:
        filter.facets.dataset?.length === 1 ? filter.facets.dataset[0] : undefined,
      owner: filter.facets.owner?.length === 1 ? filter.facets.owner[0] : undefined,
      q: filter.q || undefined,
      needsReview: needsReviewOnly || undefined,
      limit: pageSize,
      offset: (page - 1) * pageSize,
    }),
    [slug, filter, needsReviewOnly, page, pageSize],
  )
  const listQuery = useRunsList(listParams)
  const pageRuns = useMemo(() => listQuery.data?.runs ?? [], [listQuery.data])
  const total = listQuery.data?.total ?? 0

  /* Caches accumulated across pages/filter changes. Mutated during render
     on purpose: merges are additive and idempotent, and nothing re-renders
     from them — they only enrich facet options and selection chips. */
  const seenFacetValues = useRef({
    task: new Set<string>(),
    model: new Set<string>(),
    dataset: new Set<string>(),
    owner: new Set<string>(),
  })
  const knownRuns = useRef(new Map<string, RunSummary>())
  for (const run of pageRuns) {
    knownRuns.current.set(run.id, run)
    seenFacetValues.current.task.add(run.task)
    if (run.model) seenFacetValues.current.model.add(run.model)
    seenFacetValues.current.dataset.add(run.dataset)
    if (run.owner?.display_name) seenFacetValues.current.owner.add(run.owner.display_name)
  }
  for (const model of stats.data?.models ?? []) seenFacetValues.current.model.add(model)

  /* Derived rows. */
  const displayRuns = useMemo(
    () => applyClientFilters(pageRuns, filter),
    [pageRuns, filter],
  )
  const metricColumns = useMemo(() => computeMetricColumns(displayRuns), [displayRuns])
  const baselines = useMemo(() => computeBaselines(displayRuns), [displayRuns])
  const rows = useMemo(
    () => organizeRuns(displayRuns, collapsedGroups),
    [displayRuns, collapsedGroups],
  )
  const autoHidden = useMemo(
    () =>
      computeZeroEntropyColumns(displayRuns, ZERO_ENTROPY_CANDIDATES, zeroEntropyValue),
    [displayRuns],
  )

  const columnVisibility: VisibilityState = useMemo(() => {
    const visibility: VisibilityState = {}
    const hideable = [
      ...SYSTEM_COLUMNS.map((c) => c.id),
      ...metricColumns.map((m) => `metric:${m}`),
    ]
    for (const id of hideable) {
      visibility[id] = columnOverrides[id] ?? !autoHidden.includes(id)
    }
    return visibility
  }, [columnOverrides, autoHidden, metricColumns])

  const selectedRuns = useMemo(() => {
    const out: RunSummary[] = []
    for (const [id, selected] of Object.entries(rowSelection)) {
      if (!selected) continue
      const run = knownRuns.current.get(id)
      if (run) out.push(run)
    }
    return out
  }, [rowSelection])

  /* Mutations. The .mutate references are stable across renders — the
     column defs depend on them, not on the (per-render) mutation objects. */
  const renameRun = useRenameRun(slug)
  const submitRun = useSubmitRun(slug)
  const approveRun = useApproveRun(slug)
  const rejectRun = useRejectRun(slug)
  const deleteRuns = useDeleteRuns(slug)
  const renameMutate = renameRun.mutate
  const submitMutate = submitRun.mutate

  /* Handlers. */
  const handleFilterChange = (next: FilterBarState): void => {
    setFilter(next)
    setPage(1)
  }

  const clearFilters = (): void => {
    setFilter(EMPTY_FILTER_STATE)
    setNeedsReviewOnly(false)
    setPage(1)
  }

  const toggleNeedsReview = (): void => {
    setNeedsReviewOnly((v) => !v)
    setPage(1)
  }

  const toggleGroup = useCallback(
    (key: string): void => {
      setCollapsedGroups((prev) => {
        const next = new Set(prev)
        if (next.has(key)) next.delete(key)
        else next.add(key)
        saveJson(collapsedStorageKey(slug), [...next])
        return next
      })
    },
    [slug],
  )

  const toggleColumn = (id: string): void => {
    setColumnOverrides((prev) => {
      const currentlyVisible = prev[id] ?? !autoHidden.includes(id)
      const next = { ...prev, [id]: !currentlyVisible }
      saveJson(columnsStorageKey(slug), next)
      return next
    })
  }

  const commitRename = useCallback(
    (run: RunSummary, raw: string): void => {
      setEditingRunId(null)
      const next = raw.trim()
      if (!next || next === runDisplayName(run)) return
      renameMutate({ runId: run.id, displayName: next })
    },
    [renameMutate],
  )

  const handleRowClick = useCallback(
    (row: Row<RunRow>): void => {
      const r = row.original
      if (r.kind === 'group') toggleGroup(r.group.key)
      else navigate(`/projects/${slug}/runs/${r.run.id}`)
    },
    [navigate, slug, toggleGroup],
  )

  const canApprove = me?.role === 'ADMIN' || project?.role === 'MANAGER'
  const myUserId = me?.id

  /* Columns. */
  const columns: DataTableColumn<RunRow>[] = useMemo(() => {
    const base = createSelectionColumn<RunRow>()
    const selectColumn: DataTableColumn<RunRow> = {
      ...base,
      cell: (ctx) => {
        const r = ctx.row.original
        if (r.kind === 'group') {
          return (
            <IconButton
              size="sm"
              tooltip={null}
              aria-label={r.collapsed ? 'Expand group' : 'Collapse group'}
              aria-expanded={!r.collapsed}
              icon={r.collapsed ? <ChevronRight /> : <ChevronDown />}
              onClick={() => toggleGroup(r.group.key)}
            />
          )
        }
        return typeof base.cell === 'function' ? base.cell(ctx) : null
      },
    }

    const metricDefs: DataTableColumn<RunRow>[] = metricColumns.map((metric) => ({
      id: `metric:${metric}`,
      header: metricLabel(metric),
      enableSorting: false,
      meta: { align: 'right' as const, mono: true },
      cell: ({ row }) => {
        const r = row.original
        if (r.kind === 'group') return null
        const value = r.run.metric_averages?.[metric]
        if (value == null) return <span className={styles.dim}>—</span>
        const baseline = baselines.get(r.run.id)?.metric_averages?.[metric]
        return (
          <MetricDelta value={value} baseline={baseline ?? null} fmt={(v) => fmtPercent(v)} />
        )
      },
    }))

    const defs: DataTableColumn<RunRow>[] = [
      selectColumn,
      {
        id: 'status',
        header: 'Status',
        enableSorting: false,
        cell: ({ row }) =>
          row.original.kind === 'group' ? null : <StatusCell run={row.original.run} />,
      },
      {
        id: 'name',
        header: 'Name',
        enableSorting: false,
        size: 340,
        cell: ({ row }) => {
          const r = row.original
          if (r.kind === 'group') {
            return (
              <div className={styles.groupBand}>
                <span className={styles.groupLabel}>{groupLabel(r.group)}</span>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() =>
                    navigate(
                      buildCompareUrl(
                        slug,
                        r.group.runs.map((run) => run.id),
                      ),
                    )
                  }
                >
                  Compare all
                </Button>
              </div>
            )
          }
          const run = r.run
          const name = runDisplayName(run)
          if (editingRunId === run.id) {
            return (
              <input
                ref={focusAndSelect}
                className={styles.renameInput}
                defaultValue={name}
                aria-label="Run name"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitRename(run, e.currentTarget.value)
                  else if (e.key === 'Escape') setEditingRunId(null)
                }}
                onBlur={() => setEditingRunId(null)}
              />
            )
          }
          return (
            <span className={cn(styles.nameCell, r.inGroup && styles.nameIndent)}>
              <span className={styles.nameText} title={name}>
                {middleEllipsis(name, NAME_MAX_CHARS)}
              </span>
              <IconButton
                size="sm"
                className={styles.renameBtn}
                icon={<Pencil />}
                aria-label={`Rename ${name}`}
                tooltip="Rename"
                onClick={() => setEditingRunId(run.id)}
              />
            </span>
          )
        },
      },
      {
        id: 'task',
        header: 'Task',
        enableSorting: false,
        cell: ({ row }) => (row.original.kind === 'group' ? null : row.original.run.task),
      },
      {
        id: 'model',
        header: 'Model',
        enableSorting: false,
        meta: { mono: true },
        cell: ({ row }) => {
          const r = row.original
          if (r.kind === 'group') return null
          if (!r.run.model) return <span className={styles.dim}>—</span>
          return (
            <span className={styles.modelCell}>
              <span
                className={styles.modelDot}
                style={{ background: modelHue(r.run.model) }}
                aria-hidden="true"
              />
              {r.run.model}
            </span>
          )
        },
      },
      {
        id: 'dataset',
        header: 'Dataset',
        enableSorting: false,
        cell: ({ row }) =>
          row.original.kind === 'group' ? null : row.original.run.dataset,
      },
      {
        id: 'version',
        header: 'Version',
        enableSorting: false,
        cell: ({ row }) => {
          const r = row.original
          if (r.kind === 'group') return null
          const label = versionLabel(r.run)
          if (!label) return <span className={styles.dim}>—</span>
          return <span className={styles.versionChip}>{label}</span>
        },
      },
      ...metricDefs,
      {
        id: 'date',
        header: 'Date',
        enableSorting: false,
        cell: ({ row }) => {
          const r = row.original
          if (r.kind === 'group') return null
          const rel = fmtRelativeTimeWithTitle(r.run.created_at)
          return (
            <span title={rel.title} className={styles.dateText}>
              {rel.label}
            </span>
          )
        },
      },
      {
        id: 'duration',
        header: 'Duration',
        enableSorting: false,
        meta: { align: 'right' as const, mono: true },
        cell: ({ row }) =>
          row.original.kind === 'group' ? null : fmtMs(row.original.run.duration_ms),
      },
      {
        id: 'owner',
        header: 'Owner',
        enableSorting: false,
        cell: ({ row }) =>
          row.original.kind === 'group' ? null : <OwnerCell run={row.original.run} />,
      },
      {
        id: 'actions',
        header: '',
        enableSorting: false,
        enableHiding: false,
        size: 44,
        meta: { pinRight: true, align: 'center' as const },
        cell: ({ row }) => {
          const r = row.original
          if (r.kind === 'group') return null
          const run = r.run
          const name = runDisplayName(run)
          const canSubmit = run.status === 'COMPLETED' && run.owner?.id === myUserId
          const canDecide = run.status === 'SUBMITTED' && canApprove
          return (
            <DropdownMenu
              align="end"
              trigger={
                <IconButton
                  size="sm"
                  icon={<MoreVertical />}
                  aria-label={`Actions for ${name}`}
                  tooltip={null}
                />
              }
            >
              <DropdownMenuItem
                onSelect={() => navigate(`/projects/${slug}/runs/${run.id}`)}
              >
                Open
              </DropdownMenuItem>
              {canSubmit && (
                <DropdownMenuItem onSelect={() => submitMutate(run.id)}>
                  Submit for review
                </DropdownMenuItem>
              )}
              {canDecide && (
                <DropdownMenuItem
                  onSelect={() => setPendingAction({ type: 'approve', run })}
                >
                  Approve…
                </DropdownMenuItem>
              )}
              {canDecide && (
                <DropdownMenuItem
                  onSelect={() => setPendingAction({ type: 'reject', run })}
                >
                  Reject…
                </DropdownMenuItem>
              )}
              <DropdownMenuItem
                onSelect={() => window.open(exportHtmlUrl(run.id), '_blank', 'noopener')}
              >
                Export HTML
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                danger
                onSelect={() => setPendingAction({ type: 'delete', runs: [run] })}
              >
                Delete
              </DropdownMenuItem>
            </DropdownMenu>
          )
        },
      },
    ]
    return defs
  }, [
    metricColumns,
    baselines,
    editingRunId,
    canApprove,
    myUserId,
    slug,
    navigate,
    toggleGroup,
    commitRename,
    submitMutate,
  ])

  /* Facet configs: status is the full union; the rest are client-derived
     from every run seen this session (plus active selections). */
  const facetOptions = (values: ReadonlySet<string>, selected: string[] | undefined) => {
    const all = new Set(values)
    for (const v of selected ?? []) all.add(v)
    return [...all].sort().map((value) => ({ value }))
  }
  const facets: FacetConfig[] = [
    { id: 'status', label: 'Status', options: STATUSES.map((s) => ({ value: s })) },
    {
      id: 'task',
      label: 'Task',
      options: facetOptions(seenFacetValues.current.task, filter.facets.task),
    },
    {
      id: 'model',
      label: 'Model',
      options: facetOptions(seenFacetValues.current.model, filter.facets.model),
    },
    {
      id: 'dataset',
      label: 'Dataset',
      options: facetOptions(seenFacetValues.current.dataset, filter.facets.dataset),
    },
    {
      id: 'owner',
      label: 'Owner',
      options: facetOptions(seenFacetValues.current.owner, filter.facets.owner),
    },
  ]

  const filtersActive =
    filter.q !== '' ||
    Object.values(filter.facets).some((v) => v.length > 0) ||
    (filter.time !== 'all' && filter.time !== 'custom') ||
    needsReviewOnly
  const projectEmpty = !listQuery.isError && listQuery.data?.total === 0 && !filtersActive

  const reviewCount = needsReviewCount.data

  const pendingDeleteRuns = pendingAction?.type === 'delete' ? pendingAction.runs : []
  const anyDeleteRunning = pendingDeleteRuns.some(
    (run) => run.status === 'RUNNING' || run.status === 'PENDING',
  )

  return (
    <section className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.heading}>Runs</h1>
        <div className={styles.statChips}>
          <StatChip
            label="Total runs"
            value={stats.data ? fmtCount(stats.data.total_runs) : '—'}
          />
          <StatChip
            label="Models"
            value={stats.data ? fmtCount(stats.data.models?.length ?? 0) : '—'}
          />
          <StatChip label="Success" value={fmtPercent(successRate(stats.data))} />
        </div>
      </header>

      {listQuery.isError ? (
        <div className={styles.errorCard} role="alert">
          <p className={styles.errorText}>
            Could not load runs
            {listQuery.error instanceof Error ? `: ${listQuery.error.message}` : '.'}
          </p>
          <Button variant="secondary" onClick={() => void listQuery.refetch()}>
            Retry
          </Button>
        </div>
      ) : projectEmpty ? (
        <EmptyState
          icon={<FlaskConical />}
          title="No runs yet"
          description="Run an evaluation with the SDK to populate this project."
          code={SDK_SNIPPET}
          docsHref="/docs/"
          docsLabel="Read the docs"
        />
      ) : (
        <>
          <FilterBar
            value={filter}
            onChange={handleFilterChange}
            facets={facets}
            searchPlaceholder="Search runs"
            end={
              <div className={styles.barEnd}>
                <button
                  type="button"
                  className={cn(
                    styles.reviewToggle,
                    needsReviewOnly && styles.reviewToggleOn,
                    (reviewCount ?? 0) > 0 && styles.reviewToggleAttention,
                  )}
                  aria-pressed={needsReviewOnly}
                  onClick={toggleNeedsReview}
                >
                  Needs review{reviewCount != null ? ` (${reviewCount})` : ''}
                </button>
                <DropdownMenu
                  align="end"
                  trigger={
                    <Button size="sm" variant="secondary" icon={<Columns3 />}>
                      Columns
                    </Button>
                  }
                >
                  {metricColumns.length > 0 && (
                    <>
                      <div className={styles.menuGroupLabel}>Task metrics</div>
                      {metricColumns.map((metric) => {
                        const id = `metric:${metric}`
                        const visible = columnVisibility[id] !== false
                        return (
                          <DropdownMenuItem
                            key={id}
                            icon={<Check className={cn(!visible && styles.menuCheckOff)} />}
                            onSelect={(e) => {
                              e.preventDefault()
                              toggleColumn(id)
                            }}
                          >
                            {metricLabel(metric)}
                          </DropdownMenuItem>
                        )
                      })}
                      <DropdownMenuSeparator />
                    </>
                  )}
                  <div className={styles.menuGroupLabel}>System</div>
                  {SYSTEM_COLUMNS.map(({ id, label }) => {
                    const visible = columnVisibility[id] !== false
                    const autoHint = !visible && autoHidden.includes(id)
                    return (
                      <DropdownMenuItem
                        key={id}
                        icon={<Check className={cn(!visible && styles.menuCheckOff)} />}
                        onSelect={(e) => {
                          e.preventDefault()
                          toggleColumn(id)
                        }}
                      >
                        {label}
                        {autoHint && (
                          <span className={styles.menuHint}>(hidden — same for all)</span>
                        )}
                      </DropdownMenuItem>
                    )
                  })}
                </DropdownMenu>
              </div>
            }
          />

          {selectedRuns.length > 0 && (
            <div className={styles.selectionBar} role="toolbar" aria-label="Selected runs">
              <span className={styles.selectionCount}>
                {count(selectedRuns.length, 'run')} selected
              </span>
              <div className={styles.selectionChips}>
                {selectedRuns.map((run) => {
                  const name = runDisplayName(run)
                  return (
                    <span key={run.id} className={styles.selectionChip}>
                      <span title={name}>{middleEllipsis(name, 32)}</span>
                      <button
                        type="button"
                        className={styles.chipRemove}
                        aria-label={`Deselect ${name}`}
                        onClick={() =>
                          setRowSelection((prev) => {
                            const next = { ...prev }
                            delete next[run.id]
                            return next
                          })
                        }
                      >
                        ×
                      </button>
                    </span>
                  )
                })}
              </div>
              <Button
                size="sm"
                variant="secondary"
                disabled={selectedRuns.length < 2}
                onClick={() =>
                  navigate(
                    buildCompareUrl(
                      slug,
                      selectedRuns.map((run) => run.id),
                    ),
                  )
                }
              >
                Compare
              </Button>
              <Button
                size="sm"
                variant="danger"
                onClick={() => setPendingAction({ type: 'delete', runs: selectedRuns })}
              >
                Delete
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setRowSelection({})}>
                Clear
              </Button>
            </div>
          )}

          <div
            className={cn(styles.tableWrap, listQuery.isPlaceholderData && styles.tableStale)}
          >
            <DataTable<RunRow>
              data={rows}
              columns={columns}
              getRowId={rowId}
              enableRowSelection
              rowSelection={rowSelection}
              onRowSelectionChange={setRowSelection}
              columnVisibility={columnVisibility}
              onRowClick={handleRowClick}
              loading={listQuery.isPending}
              virtualized
              maxHeight="max(420px, calc(100vh - 290px))"
              aria-label="Runs"
              empty={
                <EmptyState
                  title="No matching runs"
                  description="No runs match the current filters."
                  action={
                    <Button size="sm" variant="secondary" onClick={clearFilters}>
                      Clear filters
                    </Button>
                  }
                />
              }
            />
          </div>

          <Pagination
            page={page}
            pageCount={Math.max(1, Math.ceil(total / pageSize))}
            onPageChange={setPage}
            pageSize={pageSize}
            onPageSizeChange={(size) => {
              setPageSize(size)
              setPage(1)
            }}
            totalItems={total}
          />
        </>
      )}

      {pendingAction?.type === 'approve' && (
        <ConfirmModal
          open
          onOpenChange={(open) => {
            if (!open) setPendingAction(null)
          }}
          title="Approve run"
          itemLabel={runDisplayName(pendingAction.run)}
          confirmLabel="Approve"
          onConfirm={() => {
            approveRun.mutate({ runId: pendingAction.run.id, comment: '' })
            setPendingAction(null)
          }}
        >
          <p>Marks this run as approved. The decision is recorded in the audit log.</p>
        </ConfirmModal>
      )}

      {pendingAction?.type === 'reject' && (
        <ConfirmModal
          open
          onOpenChange={(open) => {
            if (!open) setPendingAction(null)
          }}
          title="Reject run"
          itemLabel={runDisplayName(pendingAction.run)}
          confirmLabel="Reject"
          danger
          requireComment={{
            label: 'Reason',
            placeholder: 'Why is this run being rejected?',
          }}
          onConfirm={({ comment }) => {
            rejectRun.mutate({ runId: pendingAction.run.id, comment: comment ?? '' })
            setPendingAction(null)
          }}
        >
          <p>The owner can address the feedback and resubmit.</p>
        </ConfirmModal>
      )}

      {pendingAction?.type === 'delete' && (
        <ConfirmModal
          open
          onOpenChange={(open) => {
            if (!open) setPendingAction(null)
          }}
          title={
            pendingDeleteRuns.length === 1
              ? 'Move run to Deleted Runs'
              : 'Move runs to Deleted Runs'
          }
          itemLabel={
            pendingDeleteRuns.length === 1
              ? runDisplayName(pendingDeleteRuns[0])
              : count(pendingDeleteRuns.length, 'run')
          }
          confirmLabel="Delete"
          danger
          onConfirm={() => {
            const ids = pendingDeleteRuns.map((run) => run.id)
            deleteRuns.mutate(ids, {
              onSuccess: () => {
                setRowSelection((prev) => {
                  const next = { ...prev }
                  for (const id of ids) delete next[id]
                  return next
                })
              },
            })
            setPendingAction(null)
          }}
        >
          {pendingDeleteRuns.length > 1 && (
            <ul className={styles.deleteList}>
              {pendingDeleteRuns.map((run) => (
                <li key={run.id}>{runDisplayName(run)}</li>
              ))}
            </ul>
          )}
          <p>
            {pendingDeleteRuns.length === 1
              ? 'The run is removed from this list. Admins can restore it later.'
              : 'The runs are removed from this list. Admins can restore it later.'}
          </p>
          {anyDeleteRunning && (
            <p className={styles.deleteWarning}>
              {pendingDeleteRuns.length === 1
                ? 'This run is still executing.'
                : 'Some of these runs are still executing.'}
            </p>
          )}
        </ConfirmModal>
      )}

      <Toaster />
    </section>
  )
}
