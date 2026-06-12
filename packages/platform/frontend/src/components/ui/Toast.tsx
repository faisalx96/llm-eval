import * as RadixToast from '@radix-ui/react-toast'
import { useEffect, useState } from 'react'
import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react'
import { cn } from '@/lib/cn'
import styles from './Toast.module.css'

export type ToastVariant = 'success' | 'error' | 'info'

export interface ToastOptions {
  title: string
  description?: string
  variant?: ToastVariant
  /** Auto-dismiss after this many ms. Defaults to 4000. */
  duration?: number
}

interface ToastItem extends ToastOptions {
  id: number
}

/* Module-level store so `toast()` is callable from anywhere (event
 * handlers, query callbacks) without threading context. <Toaster/> is the
 * single render outlet. */
let nextId = 0
let items: ToastItem[] = []
const listeners = new Set<(items: ToastItem[]) => void>()

function emit() {
  for (const listener of listeners) listener(items)
}

/** Enqueue a toast. Returns its id (usable with dismissToast). */
export function toast(options: ToastOptions): number {
  const id = ++nextId
  items = [...items, { variant: 'info', duration: 4000, ...options, id }]
  emit()
  return id
}

export function dismissToast(id: number): void {
  items = items.filter((item) => item.id !== id)
  emit()
}

/** Remove every queued toast (used by tests between cases). */
export function dismissAllToasts(): void {
  items = []
  emit()
}

const api = { toast, dismiss: dismissToast }

/** Hook flavor of the imperative API, for component ergonomics. */
export function useToast(): typeof api {
  return api
}

const VARIANT_ICONS: Record<ToastVariant, typeof Info> = {
  success: CheckCircle2,
  error: AlertCircle,
  info: Info,
}

/** Mount once near the app root. Renders all queued toasts. */
export function Toaster() {
  const [current, setCurrent] = useState<ToastItem[]>(items)

  useEffect(() => {
    listeners.add(setCurrent)
    setCurrent(items)
    return () => {
      listeners.delete(setCurrent)
    }
  }, [])

  return (
    <RadixToast.Provider swipeDirection="right">
      {current.map((item) => {
        const variant = item.variant ?? 'info'
        const Icon = VARIANT_ICONS[variant]
        return (
          <RadixToast.Root
            key={item.id}
            className={cn(styles.toast, styles[variant])}
            // Radix announces via its own one-shot visually-hidden announcer;
            // keep role=status on the visible toast for semantics/queries but
            // silence its live region to avoid double announcements.
            role="status"
            aria-live="off"
            duration={item.duration}
            onOpenChange={(open) => {
              if (!open) dismissToast(item.id)
            }}
          >
            <Icon className={styles.icon} aria-hidden="true" />
            <div className={styles.body}>
              <RadixToast.Title className={styles.title}>{item.title}</RadixToast.Title>
              {item.description && (
                <RadixToast.Description className={styles.description}>
                  {item.description}
                </RadixToast.Description>
              )}
            </div>
            <RadixToast.Close className={styles.close} aria-label="Dismiss notification">
              <X aria-hidden="true" />
            </RadixToast.Close>
          </RadixToast.Root>
        )
      })}
      <RadixToast.Viewport className={styles.viewport} label="Notifications ({hotkey})" />
    </RadixToast.Provider>
  )
}
