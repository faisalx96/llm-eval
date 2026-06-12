import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { GitBranch, MoreVertical, Pencil, Send, Share2, Trash2 } from 'lucide-react'
import type { Me } from '@/api/types'
import {
  exportHtmlUrl,
  useDeleteRun,
  useRenameRun,
  useRunSiblings,
  useSubmitRun,
  type RunDetail,
} from '@/api/runDetail'
import {
  Button,
  ConfirmModal,
  CopyChip,
  DropdownMenu,
  DropdownMenuItem,
  DropdownMenuSeparator,
  IconButton,
  STATUSES,
  StatusBadge,
  Tooltip,
  useToast,
  type Status,
} from '@/components/ui'
import { ApiError } from '@/api/client'
import { fmtDateTime, fmtMs } from '@/lib/format'
import { findPreviousRun } from './lib'
import styles from './RunHero.module.css'

function toStatus(status: string): Status {
  return (STATUSES as readonly string[]).includes(status) ? (status as Status) : 'PENDING'
}

function errorDetail(error: unknown): string {
  if (error instanceof ApiError && typeof error.detail === 'string') return error.detail
  return error instanceof Error ? error.message : 'Request failed'
}

export interface RunHeroProps {
  slug: string
  run: RunDetail
  runName: string
  me: Me | undefined
}

/** H1 + rename, UUID chip, status, meta strip, compare/share/kebab actions. */
export function RunHero({ slug, run, runName, me }: RunHeroProps) {
  const navigate = useNavigate()
  const { toast } = useToast()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [deleteOpen, setDeleteOpen] = useState(false)

  const rename = useRenameRun(run.id)
  const submit = useSubmitRun(run.id)
  const deleteRun = useDeleteRun()
  const siblings = useRunSiblings(slug, run)
  const previous = findPreviousRun(run, siblings.data ?? [])

  const isOwner = Boolean(me && run.owner && me.id === run.owner.id)
  const isManager = Boolean(
    me && (me.role === 'ADMIN' || me.projects.find((p) => p.slug === slug)?.role === 'MANAGER'),
  )
  const canSubmit = isOwner && ['COMPLETED', 'FAILED', 'REJECTED'].includes(run.status)
  const canRename = isOwner || isManager
  const canDelete = isOwner || isManager

  const startEditing = () => {
    setDraft(runName)
    setEditing(true)
  }

  const saveRename = () => {
    const name = draft.trim()
    setEditing(false)
    if (!name || name === runName) return
    rename.mutate(name, {
      onError: (error) =>
        toast({ title: 'Rename failed', description: errorDetail(error), variant: 'error' }),
    })
  }

  const handleSubmit = () => {
    submit.mutate(undefined, {
      onSuccess: () => toast({ title: 'Submitted for review', variant: 'success' }),
      onError: (error) =>
        toast({ title: 'Submit failed', description: errorDetail(error), variant: 'error' }),
    })
  }

  const handleDelete = () => {
    deleteRun.mutate(run.id, {
      onSuccess: () => {
        toast({ title: 'Run deleted', description: runName, variant: 'success' })
        navigate(`/projects/${slug}`)
      },
      onError: (error) =>
        toast({ title: 'Delete failed', description: errorDetail(error), variant: 'error' }),
    })
  }

  const status = toStatus(run.status)
  const progress =
    status === 'RUNNING'
      ? {
          pct: (run.progress_pct ?? 0) * 100,
          done: run.completed_items,
          total: run.total_items,
        }
      : undefined

  const compareButton = (
    <Button
      variant="secondary"
      disabled={!previous}
      onClick={() => {
        if (previous) navigate(`/projects/${slug}/compare?runs=${previous.id}&runs=${run.id}`)
      }}
    >
      Compare vs previous
    </Button>
  )

  return (
    <header className={styles.hero}>
      <div className={styles.main}>
        <div className={styles.titleRow}>
          {editing ? (
            <input
              className={styles.titleInput}
              value={draft}
              // Focus management on entering edit mode (not page-load autofocus).
              ref={(el) => el?.focus()}
              aria-label="Run name"
              onChange={(e) => setDraft(e.target.value)}
              onBlur={saveRename}
              onKeyDown={(e) => {
                if (e.key === 'Enter') saveRename()
                if (e.key === 'Escape') setEditing(false)
              }}
            />
          ) : (
            <>
              <h1 className={styles.title}>{runName}</h1>
              {canRename && (
                <IconButton
                  aria-label="Rename run"
                  icon={<Pencil />}
                  size="sm"
                  className={styles.pencil}
                  onClick={startEditing}
                />
              )}
            </>
          )}
          <CopyChip value={run.id} className={styles.idChip} />
          <StatusBadge status={status} size="md" progress={progress} />
        </div>

        <dl className={styles.meta}>
          <div className={styles.metaItem}>
            <dt>Task</dt>
            <dd>{run.task}</dd>
          </div>
          <div className={styles.metaItem}>
            <dt>Dataset</dt>
            <dd>{run.dataset}</dd>
          </div>
          {run.model && (
            <div className={styles.metaItem}>
              <dt>Model</dt>
              <dd>{run.model}</dd>
            </div>
          )}
          {run.owner && (
            <div className={styles.metaItem}>
              <dt>Owner</dt>
              <dd className={styles.sans}>{run.owner.display_name || run.owner.email}</dd>
            </div>
          )}
          <div className={styles.metaItem}>
            <dt>Started</dt>
            <dd>{fmtDateTime(run.started_at)}</dd>
          </div>
          <div className={styles.metaItem}>
            <dt>Runtime</dt>
            <dd>{fmtMs(run.duration_ms)}</dd>
          </div>
          {run.version?.commit && (
            <div className={styles.metaItem}>
              <dt>Version</dt>
              <dd>
                <span className={styles.versionChip}>
                  <GitBranch size={11} aria-hidden="true" />
                  {run.version.branch ? `${run.version.branch}@` : ''}
                  {run.version.commit}
                </span>
              </dd>
            </div>
          )}
        </dl>
      </div>

      <div className={styles.actions}>
        {previous ? (
          compareButton
        ) : (
          <Tooltip content="No earlier run to compare">
            {/* Hover surface — disabled buttons swallow pointer events. */}
            <span className={styles.disabledWrap}>{compareButton}</span>
          </Tooltip>
        )}

        <DropdownMenu
          trigger={
            <Button variant="secondary" icon={<Share2 />}>
              Share
            </Button>
          }
        >
          <DropdownMenuItem onSelect={() => window.open(exportHtmlUrl(run.id), '_blank')}>
            Export HTML
          </DropdownMenuItem>
          {/* CSV: the legacy export was client-side JS only — no server route
              to link. Omitted per the redesign spec. */}
        </DropdownMenu>

        {(canSubmit || canDelete) && (
          <DropdownMenu
            trigger={<IconButton aria-label="Run actions" icon={<MoreVertical />} tooltip={null} />}
          >
            {canSubmit && (
              <DropdownMenuItem icon={<Send />} onSelect={handleSubmit}>
                Submit for review
              </DropdownMenuItem>
            )}
            {canSubmit && canDelete && <DropdownMenuSeparator />}
            {canDelete && (
              <DropdownMenuItem icon={<Trash2 />} danger onSelect={() => setDeleteOpen(true)}>
                Delete
              </DropdownMenuItem>
            )}
          </DropdownMenu>
        )}
      </div>

      <ConfirmModal
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title="Delete run"
        itemLabel={runName}
        confirmLabel="Delete run"
        danger
        onConfirm={handleDelete}
      >
        <p>
          The run is removed from the project for everyone. An admin can restore it from the
          trash.
        </p>
      </ConfirmModal>
    </header>
  )
}
