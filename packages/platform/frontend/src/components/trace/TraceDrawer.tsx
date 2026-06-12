import { useQuery } from '@tanstack/react-query'
import { ChevronRight, AlertCircle, ListTree } from 'lucide-react'
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
} from 'react'
import { apiFetch, ApiError } from '@/api/client'
import { CodePanel } from '@/components/data'
import { Button, CopyChip, Drawer, EmptyState, Skeleton, SkeletonText, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui'
import { cn } from '@/lib/cn'
import { fmtMs, fmtTokens } from '@/lib/format'
import { count } from '@/lib/pluralize'
import { isUuid } from '@/lib/runIdentity'
import {
  SPAN_KIND_HUES,
  aggregateStats,
  buildSpanTree,
  classifySpan,
  computeBounds,
  countRealErrors,
  detectRetries,
  expandableSpanIds,
  extractErrorInfoDeep,
  extractScores,
  flattenVisibleNodes,
  normalizeAttempts,
  selectAttempt,
  spanModel,
  spanStatus,
  spanTokens,
  waterfallSegment,
} from '@/lib/trace'
import type { SpanNode, SpanTree, TraceAttempt, TraceBounds, TraceData } from '@/lib/trace'
import { KIND_LABELS, SpanIcon } from './SpanIcon'
import styles from './TraceDrawer.module.css'

/**
 * Trace viewer drawer — React port of the legacy
 * qym_platform/_static/dashboard/trace_viewer.js shell (L2158-2532).
 * All algorithms live in @/lib/trace; this file is presentation + state.
 *
 * Consumers (run detail) rely ONLY on this prop shape.
 */
export interface TraceDrawerProps {
  runId: string
  itemId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Optional drawer title (e.g. run or item label). Defaults to the item id. */
  title?: string
}

/** Query key for one item's trace payload. */
export function traceQueryKey(runId: string, itemId: string) {
  return ['trace', runId, itemId] as const
}

/**
 * Unwrap display values: input.value / output.value are often JSON-encoded
 * strings ("\"hi\"") — show the inner string; structured JSON stays as JSON
 * text for CodePanel's tree view. Ported from legacy `parseDisplayValue`
 * (trace_viewer.js L1580-1587).
 */
function toDisplayText(value: unknown): string {
  if (value == null) return ''
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2)
  try {
    const parsed: unknown = JSON.parse(text)
    if (typeof parsed === 'string') return parsed
    return text
  } catch {
    return text
  }
}

/** Strip tree bookkeeping for the Raw tab (legacy renderRaw, L2128-2156). */
function rawSpanPayload(node: SpanNode): Record<string, unknown> {
  const span: Record<string, unknown> = { ...node }
  delete span.children
  delete span.index
  delete span.depth
  delete span.orphan
  return span
}

export function TraceDrawer({ runId, itemId, open, onOpenChange, title }: TraceDrawerProps) {
  const query = useQuery({
    queryKey: traceQueryKey(runId, itemId),
    queryFn: () =>
      apiFetch<TraceData>(
        `/api/runs/${encodeURIComponent(runId)}/items/${encodeURIComponent(itemId)}/trace`,
      ),
    enabled: open,
  })

  const data = useMemo(
    () => (query.data ? normalizeAttempts(query.data) : null),
    [query.data],
  )

  // Attempt selection (legacy S.selectedAttempt, L2312-2340).
  const [attemptNumber, setAttemptNumber] = useState<number | null>(null)
  useEffect(() => setAttemptNumber(null), [runId, itemId])
  const attempts = useMemo(() => data?.attempts ?? [], [data])
  const attempt = useMemo(() => selectAttempt(attempts, attemptNumber), [attempts, attemptNumber])

  const tree = useMemo(() => (attempt ? buildSpanTree(attempt.spans ?? []) : null), [attempt])
  const bounds = useMemo(
    () => computeBounds(attempt?.spans ?? null, attempt?.summary),
    [attempt],
  )
  const retryMarkers = useMemo(() => (tree ? detectRetries(tree) : null), [tree])

  // Selection + expansion state; default fully expanded, root selected
  // (legacy open(), L2342-2346).
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set())
  const [selectedId, setSelectedId] = useState<string | null>(null)
  useEffect(() => {
    if (!tree) return
    setExpanded(new Set(expandableSpanIds(tree)))
    setSelectedId(tree.roots[0]?.span_id ?? null)
  }, [tree])

  const visibleRows = useMemo(
    () => (tree ? flattenVisibleNodes(tree, expanded) : []),
    [tree, expanded],
  )
  const selectedNode = (selectedId && tree?.byId.get(selectedId)) || null

  const rowRefs = useRef(new Map<string, HTMLButtonElement>())
  const detailRef = useRef<HTMLDivElement | null>(null)

  const selectAndFocus = useCallback((spanId: string) => {
    setSelectedId(spanId)
    // Focus after state applies so the roving tabindex has moved.
    requestAnimationFrame(() => rowRefs.current.get(spanId)?.focus())
  }, [])

  const toggleExpand = useCallback((spanId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(spanId)) next.delete(spanId)
      else next.add(spanId)
      return next
    })
  }, [])

  // Keyboard: up/down move selection, right/left expand/collapse (left on a
  // collapsed node jumps to its parent), Enter focuses the detail pane.
  const handleTreeKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      if (!tree || !visibleRows.length) return
      const idx = selectedId ? visibleRows.findIndex((r) => r.span_id === selectedId) : -1
      const current = idx >= 0 ? visibleRows[idx] : null

      const moveTo = (nextIdx: number): void => {
        const next = visibleRows[Math.min(Math.max(nextIdx, 0), visibleRows.length - 1)]
        if (next) selectAndFocus(next.span_id)
      }

      switch (event.key) {
        case 'ArrowDown':
          event.preventDefault()
          moveTo(idx + 1)
          break
        case 'ArrowUp':
          event.preventDefault()
          moveTo(idx - 1)
          break
        case 'ArrowRight':
          event.preventDefault()
          if (!current) break
          if (current.children.length && !expanded.has(current.span_id)) {
            toggleExpand(current.span_id)
          } else if (current.children.length) {
            selectAndFocus(current.children[0].span_id)
          }
          break
        case 'ArrowLeft': {
          event.preventDefault()
          if (!current) break
          if (current.children.length && expanded.has(current.span_id)) {
            toggleExpand(current.span_id)
          } else if (current.parent_span_id && tree.byId.has(current.parent_span_id)) {
            selectAndFocus(current.parent_span_id)
          }
          break
        }
        case 'Home':
          event.preventDefault()
          moveTo(0)
          break
        case 'End':
          event.preventDefault()
          moveTo(visibleRows.length - 1)
          break
        case 'Enter':
          event.preventDefault()
          detailRef.current?.focus()
          break
        default:
          break
      }
    },
    [tree, visibleRows, selectedId, expanded, selectAndFocus, toggleExpand],
  )

  const drawerTitle = title ?? (isUuid(itemId) ? 'Trace' : itemId)

  return (
    <Drawer open={open} onOpenChange={onOpenChange} title={drawerTitle} size="full">
      <div className={styles.root}>
        {query.isPending ? (
          <LoadingState />
        ) : query.isError ? (
          <div className={styles.stateWrap}>
            <EmptyState
              icon={<AlertCircle />}
              title="Failed to load trace"
              description={
                query.error instanceof ApiError || query.error instanceof Error
                  ? query.error.message
                  : 'Unexpected error'
              }
              action={
                <Button variant="secondary" onClick={() => void query.refetch()}>
                  Retry
                </Button>
              }
            />
          </div>
        ) : !tree || tree.roots.length === 0 ? (
          <div className={styles.stateWrap}>
            <EmptyState
              icon={<ListTree />}
              title="No spans recorded"
              description="This item may not have tracing enabled."
            />
          </div>
        ) : (
          <>
            <SummaryBar
              tree={tree}
              attempt={attempt}
              attempts={attempts}
              attemptNumber={attemptNumber}
              onSelectAttempt={setAttemptNumber}
            />
            <div className={styles.split}>
              <div className={styles.treePane}>
                <div
                  role="tree"
                  aria-label="Trace spans"
                  className={styles.tree}
                  // Focus lives on the rows (roving tabindex); -1 keeps the
                  // container itself out of the tab order but focusable.
                  tabIndex={-1}
                  onKeyDown={handleTreeKeyDown}
                >
                  {visibleRows.map((node) => (
                    <SpanRow
                      key={node.span_id}
                      node={node}
                      bounds={bounds}
                      selected={node.span_id === selectedId}
                      expanded={expanded.has(node.span_id)}
                      retry={retryMarkers?.retries.get(node.span_id) ?? 0}
                      failed={retryMarkers?.failed.has(node.span_id) ?? false}
                      rowRefs={rowRefs}
                      onSelect={setSelectedId}
                      onToggle={toggleExpand}
                    />
                  ))}
                </div>
              </div>
              <div
                ref={detailRef}
                className={styles.detailPane}
                tabIndex={-1}
                aria-label="Span details"
              >
                {selectedNode ? (
                  <SpanDetail node={selectedNode} attemptError={attempt?.error ?? null} />
                ) : (
                  <p className={styles.emptyHint}>Select a span to inspect it</p>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </Drawer>
  )
}

function LoadingState() {
  return (
    <div className={styles.loading}>
      <span role="status" className={styles.srOnly}>
        Loading trace
      </span>
      <div className={styles.loadingTree}>
        {Array.from({ length: 8 }, (_, i) => (
          <Skeleton key={i} height={22} width={`${92 - (i % 4) * 12}%`} />
        ))}
      </div>
      <div className={styles.loadingDetail}>
        <Skeleton height={22} width="55%" />
        <div style={{ height: 'var(--space-md)' }} />
        <SkeletonText lines={6} />
      </div>
    </div>
  )
}

/** Header chips: span count, duration, tokens, errors, scores, trace id
 *  (legacy renderHeader, L1158-1221) + attempt switcher (L1166-1191). */
function SummaryBar({
  tree,
  attempt,
  attempts,
  attemptNumber,
  onSelectAttempt,
}: {
  tree: SpanTree
  attempt: TraceAttempt | null
  attempts: TraceAttempt[]
  attemptNumber: number | null
  onSelectAttempt: (n: number) => void
}) {
  const summary = attempt?.summary ?? {}
  const stats = aggregateStats(tree)
  const errorCount = countRealErrors(tree, summary.error_count ?? 0)
  const scores = tree.roots[0] ? extractScores(tree.roots[0]) : []
  const traceId = attempt?.trace_id ?? ''
  const selected = attempt?.attempt_number ?? attemptNumber ?? 0

  return (
    <div className={styles.summaryBar}>
      <span className={styles.chip}>
        <span className={styles.chipValue}>{count(summary.span_count ?? tree.nodes.length, 'span')}</span>
      </span>
      <span className={styles.chip}>
        <span className={styles.chipValue}>{fmtMs(summary.duration_ms)}</span>
      </span>
      {stats.totalTokens > 0 && (
        <span className={styles.chip}>
          <span className={styles.chipValue}>{fmtTokens(stats.totalTokens)}</span> tokens
        </span>
      )}
      {errorCount > 0 && (
        <span className={cn(styles.chip, styles.chipError)}>{count(errorCount, 'error')}</span>
      )}
      {summary.has_orphans && (
        <span className={cn(styles.chip, styles.chipWarning)}>
          {count(summary.orphan_count ?? 0, 'orphan span')}
        </span>
      )}
      {scores.map((score) => (
        <span key={score.name} className={cn(styles.chip, styles.chipScore)} title={score.explanation || undefined}>
          {score.name}{' '}
          <span className={styles.chipValue}>
            {typeof score.value === 'number' ? score.value.toFixed(2) : String(score.value ?? '—')}
          </span>
        </span>
      ))}
      {traceId && <CopyChip value={traceId} />}
      {attempts.length > 1 && (
        <span className={styles.attemptGroup} role="group" aria-label="Attempts">
          {attempts.map((a) => {
            const isActive = Number(a.attempt_number) === Number(selected)
            return (
              <button
                key={a.attempt_number}
                type="button"
                className={cn(styles.attemptBtn, isActive && styles.attemptBtnActive)}
                aria-pressed={isActive}
                title={a.error ?? undefined}
                onClick={() => onSelectAttempt(Number(a.attempt_number))}
              >
                Attempt {a.attempt_number}
                <span className={cn(styles.attemptTag, !a.is_last_attempt && styles.attemptTagFailed)}>
                  {a.is_last_attempt ? 'latest' : 'failed'}
                </span>
              </button>
            )
          })}
        </span>
      )}
    </div>
  )
}

/** One tree row: chevron, kind icon, name, duration (mono), waterfall bar
 *  (legacy renderTree/visit, L1283-1370). */
function SpanRow({
  node,
  bounds,
  selected,
  expanded,
  retry,
  failed,
  rowRefs,
  onSelect,
  onToggle,
}: {
  node: SpanNode
  bounds: TraceBounds
  selected: boolean
  expanded: boolean
  retry: number
  failed: boolean
  rowRefs: { current: Map<string, HTMLButtonElement> }
  onSelect: (id: string) => void
  onToggle: (id: string) => void
}) {
  const kind = classifySpan(node)
  const hue = SPAN_KIND_HUES[kind]
  const isError = spanStatus(node) === 'error'
  const segment = waterfallSegment(node, bounds)
  const hasChildren = node.children.length > 0

  return (
    <button
      type="button"
      role="treeitem"
      aria-level={node.depth + 1}
      aria-selected={selected}
      aria-expanded={hasChildren ? expanded : undefined}
      tabIndex={selected ? 0 : -1}
      ref={(el) => {
        if (el) rowRefs.current.set(node.span_id, el)
        else rowRefs.current.delete(node.span_id)
      }}
      className={cn(
        styles.row,
        selected && styles.rowSelected,
        isError && styles.rowError,
        failed && !isError && styles.rowFailed,
      )}
      style={{ '--row-indent': `${node.depth * 16}px` } as CSSProperties}
      onClick={(event) => {
        onSelect(node.span_id)
        if (hasChildren && (event.target as HTMLElement).closest('[data-toggle]')) {
          onToggle(node.span_id)
        }
      }}
    >
      {hasChildren ? (
        <span data-toggle="true">
          <ChevronRight
            className={cn(styles.chevron, expanded && styles.chevronOpen)}
            aria-hidden="true"
          />
        </span>
      ) : (
        <span className={styles.chevronStub} />
      )}
      <SpanIcon kind={kind} />
      <span className={styles.name}>{node.name || '(unnamed)'}</span>
      {retry > 0 && <span className={styles.retryTag}>retry {retry}</span>}
      {isError && <AlertCircle className={styles.errBadge} aria-label="Error" />}
      <span className={styles.dur}>{fmtMs(node.duration_ms)}</span>
      <span className={styles.wf} aria-hidden="true" style={{ color: isError ? 'var(--error)' : hue }}>
        <span
          className={styles.wfBar}
          style={{ left: `${segment.leftPct}%`, width: `${segment.widthPct}%` }}
        />
      </span>
    </button>
  )
}

/** Detail pane: header, error box, Input / output · Attributes · Raw tabs
 *  (legacy renderDetail/renderIO/renderRaw, L1377-1483, L1764-1795, L2128-2156). */
function SpanDetail({ node, attemptError }: { node: SpanNode; attemptError: string | null }) {
  const kind = classifySpan(node)
  const status = spanStatus(node)
  const model = spanModel(node)
  const tokens = spanTokens(node)
  const attrs = node.attributes ?? {}
  const attrEntries = Object.entries(attrs).sort(([a], [b]) => a.localeCompare(b))
  const input = attrs['input.value']
  const output = attrs['output.value']
  const errorInfo = status === 'error' ? extractErrorInfoDeep(node) : null

  return (
    <div>
      <div className={styles.detailHead}>
        <SpanIcon kind={kind} />
        <div className={styles.detailInfo}>
          <div className={styles.detailName}>{node.name || '(unnamed)'}</div>
          <div className={styles.detailSub}>
            <span>{KIND_LABELS[kind]}</span>
            {model && <span className={styles.mono}>{model}</span>}
            <span className={styles.mono}>{fmtMs(node.duration_ms)}</span>
            {tokens != null && <span className={styles.mono}>{fmtTokens(tokens)} tokens</span>}
          </div>
        </div>
        {status !== 'unset' && (
          <span className={status === 'error' ? styles.statusError : styles.statusOk}>
            {status === 'error' ? 'Error' : 'OK'}
          </span>
        )}
      </div>

      {status === 'error' && (
        <div className={styles.errorBox} role="alert">
          <div className={styles.errorTitle}>Error</div>
          {errorInfo?.type && <div className={styles.errorType}>{errorInfo.type}</div>}
          <div className={styles.errorMsg}>
            {errorInfo?.message || attemptError || 'This span completed with ERROR status'}
          </div>
          {errorInfo?.stacktrace && (
            <details className={styles.errorStack}>
              <summary>Stack trace</summary>
              <pre>{errorInfo.stacktrace}</pre>
            </details>
          )}
        </div>
      )}

      <Tabs defaultValue="io" key={node.span_id}>
        <TabsList aria-label="Span detail sections">
          <TabsTrigger value="io">Input / output</TabsTrigger>
          <TabsTrigger value="attrs" count={attrEntries.length}>
            Attributes
          </TabsTrigger>
          <TabsTrigger value="raw">Raw</TabsTrigger>
        </TabsList>
        <TabsContent value="io">
          <div className={styles.tabBody}>
            {input != null && <CodePanel label="Input" code={toDisplayText(input)} />}
            {output != null && <CodePanel label="Output" code={toDisplayText(output)} />}
            {input == null && output == null && (
              <p className={styles.emptyHint}>No input or output recorded</p>
            )}
          </div>
        </TabsContent>
        <TabsContent value="attrs">
          <div className={styles.tabBody}>
            {attrEntries.length ? (
              <table className={styles.attrTable}>
                <thead>
                  <tr>
                    <th scope="col">Key</th>
                    <th scope="col">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {attrEntries.map(([key, value]) => (
                    <tr key={key}>
                      <td className={styles.attrKey}>{key}</td>
                      <td className={styles.attrVal}>
                        {typeof value === 'string' ? value : JSON.stringify(value)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className={styles.emptyHint}>No attributes</p>
            )}
          </div>
        </TabsContent>
        <TabsContent value="raw">
          <div className={styles.tabBody}>
            <CodePanel
              label="Span JSON"
              code={JSON.stringify(rawSpanPayload(node), null, 2)}
              jsonExpandDepth={2}
              maxHeight={480}
            />
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}
