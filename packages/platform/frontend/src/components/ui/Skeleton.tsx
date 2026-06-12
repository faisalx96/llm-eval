import type { CSSProperties } from 'react'
import { cn } from '@/lib/cn'
import styles from './Skeleton.module.css'

export interface SkeletonProps {
  width?: CSSProperties['width']
  height?: CSSProperties['height']
  radius?: CSSProperties['borderRadius']
  className?: string
}

/** Shimmer placeholder block. Hidden from assistive tech — pair with a
 *  visible loading announcement at the page level. */
export function Skeleton({ width, height = 14, radius, className }: SkeletonProps) {
  return (
    <div
      className={cn(styles.skeleton, className)}
      style={{ width, height, borderRadius: radius }}
      aria-hidden="true"
      data-testid="skeleton"
    />
  )
}

export interface SkeletonTextProps {
  /** Number of text lines to render. */
  lines?: number
  className?: string
}

/** Multi-line text placeholder; last line is shorter for realism. */
export function SkeletonText({ lines = 3, className }: SkeletonTextProps) {
  return (
    <div className={cn(styles.text, className)} aria-hidden="true">
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton key={index} width={index === lines - 1 ? '60%' : '100%'} height={12} />
      ))}
    </div>
  )
}
