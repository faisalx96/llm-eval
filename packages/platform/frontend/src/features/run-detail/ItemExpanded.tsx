import { useState } from 'react'
import { ApiError } from '@/api/client'
import {
  useCorrectionDecision,
  useRunItemDetail,
  type CorrectionEntry,
  type RunItemDetail,
} from '@/api/runDetail'
import { CodePanel } from '@/components/data'
import { Button, SkeletonText, Tooltip, useToast } from '@/components/ui'
import { fmtPercent } from '@/lib/format'
import {
  METRIC_THRESHOLD,
  canWordDiff,
  isDisplayMetadataEntry,
  metricScore,
  payloadToText,
} from './lib'
import styles from './ItemExpanded.module.css'

function metaTooltip(meta: unknown): string {
  if (meta === null || meta === undefined) return ''
  if (typeof meta !== 'object') return String(meta)
  return Object.entries(meta as Record<string, unknown>)
    .map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`)
    .join('\n')
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

/** Root-cause / correction block with provenance + review actions. */
function CorrectionBlock({
  detail,
  correction,
  canReview,
  runId,
}: {
  detail: RunItemDetail
  correction: CorrectionEntry | undefined
  canReview: boolean
  runId: string
}) {
  const { toast } = useToast()
  const decision = useCorrectionDecision(runId)

  const metadata = detail.item_metadata ?? {}
  const rootCause = str(metadata['root_cause']) || correction?.human_root_cause || ''
  const category = str(metadata['root_cause_detail']) || correction?.human_root_cause_detail || ''
  const solution = str(metadata['solution']) || correction?.human_solution || ''
  if (!rootCause && !category && !solution) return null

  const source = str(metadata['root_cause_source']) === 'ai' ? 'ai' : 'human'
  const pending = detail.review_correction_status === 'pending'

  const decide = (action: 'approve' | 'reject') => {
    if (!correction) return
    decision.mutate(
      { correctionId: correction.id, action },
      {
        onSuccess: () =>
          toast({
            title: action === 'approve' ? 'Correction approved' : 'Correction rejected',
            variant: 'success',
          }),
        onError: (error) =>
          toast({
            title: 'Correction update failed',
            description:
              error instanceof ApiError && typeof error.detail === 'string'
                ? error.detail
                : 'Request failed',
            variant: 'error',
          }),
      },
    )
  }

  return (
    <div className={styles.correction}>
      <div className={styles.correctionHead}>
        <span className={styles.blockLabel}>Root cause</span>
        <span className={source === 'ai' ? styles.sourceAi : styles.sourceHuman}>
          {source === 'ai' ? 'AI' : 'Human'}
        </span>
        {pending && <span className={styles.pendingBadge}>Pending review</span>}
        {pending && canReview && correction && (
          <span className={styles.correctionActions}>
            <Button size="sm" variant="secondary" loading={decision.isPending} onClick={() => decide('approve')}>
              Approve
            </Button>
            <Button size="sm" variant="danger" disabled={decision.isPending} onClick={() => decide('reject')}>
              Reject
            </Button>
          </span>
        )}
      </div>
      <dl className={styles.correctionFields}>
        {rootCause && (
          <div className={styles.correctionField}>
            <dt>Root cause</dt>
            <dd>{rootCause}</dd>
          </div>
        )}
        {category && (
          <div className={styles.correctionField}>
            <dt>Category</dt>
            <dd>{category}</dd>
          </div>
        )}
        {solution && (
          <div className={styles.correctionField}>
            <dt>Solution</dt>
            <dd>{solution}</dd>
          </div>
        )}
      </dl>
    </div>
  )
}

export interface ItemExpandedProps {
  runId: string
  itemId: string
  correction: CorrectionEntry | undefined
  canReview: boolean
}

/**
 * Expanded row: lazily fetched full item detail. INPUT spans the row;
 * OUTPUT and EXPECTED render as visually EQUAL side-by-side panels
 * (neutral chrome — no winner styling), with an optional word diff for
 * short plain-text pairs.
 */
export function ItemExpanded({ runId, itemId, correction, canReview }: ItemExpandedProps) {
  const detailQuery = useRunItemDetail(runId, itemId)
  const [showDiff, setShowDiff] = useState(false)

  if (detailQuery.isPending) {
    return (
      <div className={styles.wrap} data-testid="item-expanded-loading">
        <SkeletonText lines={3} />
      </div>
    )
  }

  if (detailQuery.isError || !detailQuery.data) {
    return <p className={styles.loadError}>Could not load item detail.</p>
  }

  const detail = detailQuery.data
  const outputText = payloadToText(detail.output)
  const expectedText = payloadToText(detail.expected)
  const diffable = canWordDiff(detail.output, detail.expected)

  const metadataChips = Object.entries(detail.item_metadata ?? {}).filter(([key, value]) =>
    isDisplayMetadataEntry(key, value),
  )
  const metricEntries = Object.entries(detail.metric_values ?? {})

  return (
    <div className={styles.wrap}>
      {detail.error && <CodePanel label="Error" tone="fail" code={detail.error} />}

      <CodePanel label="Input" code={payloadToText(detail.input)} />

      {diffable && showDiff ? (
        <CodePanel label="Output vs expected" diff={{ a: expectedText, b: outputText }} />
      ) : (
        <div className={styles.sideBySide}>
          <CodePanel label="Output" code={outputText} className={styles.sidePanel} />
          <CodePanel label="Expected" code={expectedText} className={styles.sidePanel} />
        </div>
      )}
      {diffable && (
        <div>
          <Button size="sm" variant="ghost" onClick={() => setShowDiff((v) => !v)}>
            {showDiff ? 'Show side by side' : 'Show word diff'}
          </Button>
        </div>
      )}

      {(metadataChips.length > 0 || metricEntries.length > 0) && (
        <div className={styles.chips}>
          {metricEntries.map(([name, value]) => {
            const score = metricScore(value)
            const meta = detail.metric_meta?.[name]
            const inner = (
              <>
                <span className={styles.chipKey}>{name}</span>
                <span className={score !== null && score < METRIC_THRESHOLD ? styles.scoreFail : undefined}>
                  {score !== null ? fmtPercent(score) : String(value)}
                </span>
              </>
            )
            // With judge metadata the chip is a real (focusable) trigger
            // for the meta popover; otherwise it stays inert.
            return meta ? (
              <Tooltip key={name} content={<pre className={styles.metaPre}>{metaTooltip(meta)}</pre>}>
                <button type="button" className={styles.metricChip}>
                  {inner}
                </button>
              </Tooltip>
            ) : (
              <span key={name} className={styles.metricChip}>
                {inner}
              </span>
            )
          })}
          {metadataChips.map(([key, value]) => (
            <span key={key} className={styles.metaChip}>
              <span className={styles.chipKey}>{key}</span>
              {String(value)}
            </span>
          ))}
        </div>
      )}

      <CorrectionBlock detail={detail} correction={correction} canReview={canReview} runId={runId} />
    </div>
  )
}
