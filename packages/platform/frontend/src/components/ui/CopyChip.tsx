import { Check, Copy } from 'lucide-react'
import { cn } from '@/lib/cn'
import { useClipboard } from './useClipboard'
import styles from './CopyChip.module.css'

/** Middle-ellipsis: 'a1b2c3d4-e5f6-…-9j0k' style truncation for IDs. */
export function middleEllipsis(value: string, max = 17): string {
  if (value.length <= max) return value
  const head = Math.ceil((max - 1) / 2)
  const tail = Math.floor((max - 1) / 2)
  return `${value.slice(0, head)}…${value.slice(value.length - tail)}`
}

export interface CopyChipProps {
  /** Full value copied to the clipboard (UUID, ID, hash…). */
  value: string
  /** Optional display override; defaults to the middle-ellipsized value. */
  display?: string
  /** Max characters before middle-ellipsis kicks in. */
  maxChars?: number
  className?: string
}

/** Small mono chip for IDs: shows a truncated value, copies the full
 *  value on click, and announces 'Copied'. */
export function CopyChip({ value, display, maxChars = 17, className }: CopyChipProps) {
  const { copied, copy } = useClipboard()

  return (
    <button
      type="button"
      className={cn(styles.chip, copied && styles.copied, className)}
      onClick={() => void copy(value)}
      title={value}
      aria-label={`Copy ${value}`}
    >
      <span className={styles.value}>{display ?? middleEllipsis(value, maxChars)}</span>
      {copied ? (
        <Check className={styles.icon} aria-hidden="true" />
      ) : (
        <Copy className={styles.icon} aria-hidden="true" />
      )}
      <span role="status" className={styles.flag}>
        {copied ? 'Copied' : ''}
      </span>
    </button>
  )
}
