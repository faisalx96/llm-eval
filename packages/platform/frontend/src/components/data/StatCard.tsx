import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'
import styles from './StatCard.module.css'

/**
 * Labeled stat tile. With `onClick` it renders as a real <button> with an
 * unmistakably interactive treatment — accent border on hover plus focus
 * ring (the anti-"secret tabs" rule: clickable things must look clickable).
 */

export interface StatCardProps {
  label: string
  value: ReactNode
  sub?: ReactNode
  onClick?: () => void
  className?: string
}

export function StatCard({ label, value, sub, onClick, className }: StatCardProps) {
  const inner = (
    <>
      <span className={styles.label}>{label}</span>
      <span className={styles.value}>{value}</span>
      {sub != null && <span className={styles.sub}>{sub}</span>}
    </>
  )

  if (onClick) {
    return (
      <button
        type="button"
        className={cn(styles.card, styles.clickable, className)}
        onClick={onClick}
      >
        {inner}
      </button>
    )
  }

  return <div className={cn(styles.card, className)}>{inner}</div>
}
