import * as Dialog from '@radix-ui/react-dialog'
import { useRef } from 'react'
import { X } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { IconButton } from './IconButton'
import styles from './Drawer.module.css'

export interface DrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  /** md: 480px · lg: 760px · full: edge-to-edge. Always full height. */
  size?: 'md' | 'lg' | 'full'
  /** Optional accessible description announced on open. */
  description?: string
  children: ReactNode
}

/** Right-side overlay panel. Covers the full viewport edge (over any
 *  sidebar), header with title + close, scrollable body. */
export function Drawer({
  open,
  onOpenChange,
  title,
  size = 'md',
  description,
  children,
}: DrawerProps) {
  // Opened from arbitrary UI (no Radix Dialog.Trigger), so Radix cannot
  // restore focus on close by itself — capture/restore manually.
  const returnFocusRef = useRef<HTMLElement | null>(null)

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content
          className={cn(styles.content, styles[size])}
          onOpenAutoFocus={() => {
            // Fires before focus moves into the drawer.
            returnFocusRef.current = document.activeElement as HTMLElement | null
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault()
            returnFocusRef.current?.focus()
          }}
          // Radix warns when no Description is present unless explicitly opted out.
          {...(description ? {} : { 'aria-describedby': undefined })}
        >
          <header className={styles.header}>
            <Dialog.Title className={styles.title}>{title}</Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label="Close" icon={<X />} size="sm" tooltip={null} />
            </Dialog.Close>
          </header>
          {description && (
            <Dialog.Description className={styles.description}>{description}</Dialog.Description>
          )}
          <div className={styles.body}>{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
