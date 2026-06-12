import { useState } from 'react'
import { AlertTriangle, CheckCircle2, Clock3, XCircle } from 'lucide-react'
import type { Me } from '@/api/types'
import { ApiError } from '@/api/client'
import { useApproveRun, useRejectRun, useSubmitRun, type RunDetail } from '@/api/runDetail'
import { Button, ConfirmModal, useToast } from '@/components/ui'
import { fmtDate } from '@/lib/format'
import { failedBannerText } from './lib'
import styles from './GovernanceBanner.module.css'

function errorDetail(error: unknown): string {
  if (error instanceof ApiError && typeof error.detail === 'string') return error.detail
  return error instanceof Error ? error.message : 'Request failed'
}

export interface GovernanceBannerProps {
  slug: string
  run: RunDetail
  runName: string
  me: Me | undefined
}

/**
 * Approval context banner: REJECTED (red, with the reviewer's comment and a
 * Resubmit path), APPROVED (subtle green), SUBMITTED (amber, with
 * Approve/Reject for managers/admins).
 */
export function GovernanceBanner({ slug, run, runName, me }: GovernanceBannerProps) {
  const { toast } = useToast()
  const [rejectOpen, setRejectOpen] = useState(false)
  const approve = useApproveRun(run.id)
  const reject = useRejectRun(run.id)
  const submit = useSubmitRun(run.id)

  const approval = run.approval
  if (!approval) return null

  const isOwner = Boolean(me && run.owner && me.id === run.owner.id)
  const isManager = Boolean(
    me && (me.role === 'ADMIN' || me.projects.find((p) => p.slug === slug)?.role === 'MANAGER'),
  )

  const reviewer = approval.decided_by?.display_name || approval.decided_by?.email || 'a reviewer'
  const decidedOn = fmtDate(approval.decided_at)

  if (approval.status === 'REJECTED') {
    return (
      <div className={`${styles.banner} ${styles.rejected}`} role="status">
        <XCircle className={styles.icon} aria-hidden="true" />
        <div className={styles.body}>
          <p className={styles.headline}>
            Rejected by {reviewer} on {decidedOn}
          </p>
          {approval.comment && <p className={styles.comment}>“{approval.comment}”</p>}
        </div>
        {isOwner && (
          <Button
            variant="secondary"
            size="sm"
            loading={submit.isPending}
            onClick={() =>
              submit.mutate(undefined, {
                onSuccess: () => toast({ title: 'Resubmitted for review', variant: 'success' }),
                onError: (error) =>
                  toast({ title: 'Resubmit failed', description: errorDetail(error), variant: 'error' }),
              })
            }
          >
            Resubmit
          </Button>
        )}
      </div>
    )
  }

  if (approval.status === 'APPROVED') {
    return (
      <div className={`${styles.banner} ${styles.approved}`} role="status">
        <CheckCircle2 className={styles.icon} aria-hidden="true" />
        <div className={styles.body}>
          <p className={styles.headline}>
            Approved by {reviewer} on {decidedOn}
          </p>
          {approval.comment && <p className={styles.comment}>“{approval.comment}”</p>}
        </div>
      </div>
    )
  }

  if (approval.status === 'SUBMITTED') {
    const submitter =
      approval.submitted_by?.display_name || approval.submitted_by?.email || 'the owner'
    return (
      <div className={`${styles.banner} ${styles.submitted}`} role="status">
        <Clock3 className={styles.icon} aria-hidden="true" />
        <div className={styles.body}>
          <p className={styles.headline}>Awaiting review</p>
          <p className={styles.comment}>
            Submitted by {submitter} on {fmtDate(approval.submitted_at)}
          </p>
        </div>
        {isManager && (
          <div className={styles.actions}>
            <Button
              size="sm"
              loading={approve.isPending}
              onClick={() =>
                approve.mutate('', {
                  onSuccess: () => toast({ title: 'Run approved', variant: 'success' }),
                  onError: (error) =>
                    toast({ title: 'Approve failed', description: errorDetail(error), variant: 'error' }),
                })
              }
            >
              Approve
            </Button>
            <Button variant="danger" size="sm" onClick={() => setRejectOpen(true)}>
              Reject
            </Button>
            <ConfirmModal
              open={rejectOpen}
              onOpenChange={setRejectOpen}
              title="Reject run"
              itemLabel={runName}
              confirmLabel="Reject run"
              danger
              requireComment={{
                label: 'Why is this run rejected?',
                placeholder: 'The owner sees this comment on the run.',
              }}
              onConfirm={({ comment }) =>
                reject.mutate(comment ?? '', {
                  onSuccess: () => toast({ title: 'Run rejected', variant: 'success' }),
                  onError: (error) =>
                    toast({ title: 'Reject failed', description: errorDetail(error), variant: 'error' }),
                })
              }
            >
              <p>The run returns to its owner with your comment.</p>
            </ConfirmModal>
          </div>
        )}
      </div>
    )
  }

  return null
}

/** Red banner for FAILED runs: progress reached + the first error line. */
export function FailedBanner({ run }: { run: RunDetail }) {
  if (run.status !== 'FAILED') return null
  return (
    <div className={`${styles.banner} ${styles.failed}`} role="status">
      <AlertTriangle className={styles.icon} aria-hidden="true" />
      <div className={styles.body}>
        <p className={styles.headline}>{failedBannerText(run)}</p>
      </div>
    </div>
  )
}
