import { forwardRef } from 'react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { Tooltip } from './Tooltip'
import styles from './IconButton.module.css'

export interface IconButtonProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children' | 'aria-label'> {
  /** Required accessible name — icon-only buttons must always have one. */
  'aria-label': string
  /** The icon element (lucide icon). Rendered decorative. */
  icon: ReactNode
  size?: 'sm' | 'md'
  variant?: 'ghost' | 'danger'
  /** Tooltip text. Defaults to the aria-label. Pass null to disable. */
  tooltip?: string | null
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { icon, size = 'md', variant = 'ghost', tooltip, className, type, ...rest },
  ref,
) {
  const label = rest['aria-label']
  const button = (
    <button
      ref={ref}
      type={type ?? 'button'}
      className={cn(styles.iconButton, styles[size], styles[variant], className)}
      {...rest}
    >
      <span className={styles.icon} aria-hidden="true">
        {icon}
      </span>
    </button>
  )

  if (tooltip === null) return button
  return <Tooltip content={tooltip ?? label}>{button}</Tooltip>
})
