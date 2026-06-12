import * as Dialog from '@radix-ui/react-dialog'
import { useEffect, useId, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Button } from './Button'
import styles from './ConfirmModal.module.css'

export interface ConfirmModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  /** The named thing being acted on (run name, project slug, …).
   *  Required so confirms are never about a generic 'this item'. */
  itemLabel: string
  confirmLabel: string
  /** Body content explaining consequences. */
  children?: ReactNode
  /** Destructive action → red confirm button. */
  danger?: boolean
  /** When set, the user must type this exact string to enable confirm. */
  typeToConfirm?: string
  /** When set, a non-empty comment is required and passed to onConfirm. */
  requireComment?: { label: string; placeholder?: string }
  onConfirm: (details: { comment?: string }) => void
}

export function ConfirmModal({
  open,
  onOpenChange,
  title,
  itemLabel,
  confirmLabel,
  children,
  danger = false,
  typeToConfirm,
  requireComment,
  onConfirm,
}: ConfirmModalProps) {
  const typeInputId = useId()
  const commentId = useId()
  const [typed, setTyped] = useState('')
  const [comment, setComment] = useState('')
  // This dialog is opened from arbitrary UI (no Radix Dialog.Trigger), so
  // Radix cannot restore focus on close by itself — capture/restore manually.
  const returnFocusRef = useRef<HTMLElement | null>(null)

  // Reset transient input state whenever the modal closes.
  useEffect(() => {
    if (!open) {
      setTyped('')
      setComment('')
    }
  }, [open])

  const typeSatisfied = !typeToConfirm || typed === typeToConfirm
  const commentSatisfied = !requireComment || comment.trim().length > 0
  const canConfirm = typeSatisfied && commentSatisfied

  function handleConfirm() {
    onConfirm(requireComment ? { comment: comment.trim() } : {})
    onOpenChange(false)
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content
          className={styles.content}
          onOpenAutoFocus={() => {
            // Fires before focus moves into the dialog.
            returnFocusRef.current = document.activeElement as HTMLElement | null
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault()
            returnFocusRef.current?.focus()
          }}
        >
          <Dialog.Title className={styles.title}>{title}</Dialog.Title>
          <code className={styles.itemLabel}>{itemLabel}</code>
          <Dialog.Description asChild>
            <div className={styles.body}>{children}</div>
          </Dialog.Description>

          {requireComment && (
            <div className={styles.field}>
              <label className={styles.fieldLabel} htmlFor={commentId}>
                {requireComment.label}
              </label>
              <textarea
                id={commentId}
                className={styles.textarea}
                placeholder={requireComment.placeholder}
                value={comment}
                rows={3}
                onChange={(event) => setComment(event.target.value)}
              />
            </div>
          )}

          {typeToConfirm && (
            <div className={styles.field}>
              <label className={styles.fieldLabel} htmlFor={typeInputId}>
                Type <code className={styles.typeTarget}>{typeToConfirm}</code> to confirm
              </label>
              <input
                id={typeInputId}
                className={styles.input}
                value={typed}
                autoComplete="off"
                spellCheck={false}
                onChange={(event) => setTyped(event.target.value)}
              />
            </div>
          )}

          <div className={styles.footer}>
            <Dialog.Close asChild>
              <Button variant="ghost">Cancel</Button>
            </Dialog.Close>
            <Button
              variant={danger ? 'danger' : 'primary'}
              disabled={!canConfirm}
              onClick={handleConfirm}
            >
              {confirmLabel}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
