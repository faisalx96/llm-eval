import { Check, Copy, ExternalLink } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { IconButton } from './IconButton'
import { useClipboard } from './useClipboard'
import styles from './EmptyState.module.css'

export interface EmptyStateProps {
  /** Decorative icon (lucide element). */
  icon?: ReactNode
  title: string
  description?: ReactNode
  /** Primary action — pass a <Button>. */
  action?: ReactNode
  /** Optional code snippet (e.g. the CLI command to get started). */
  code?: string
  docsHref?: string
  docsLabel?: string
  className?: string
}

/** The ONE empty-state contract: icon, title, description, optional
 *  primary action, optional copyable code snippet, optional docs link. */
export function EmptyState({
  icon,
  title,
  description,
  action,
  code,
  docsHref,
  docsLabel = 'View docs',
  className,
}: EmptyStateProps) {
  const { copied, copy } = useClipboard()

  return (
    <div className={cn(styles.emptyState, className)}>
      {icon != null && (
        <div className={styles.icon} aria-hidden="true">
          {icon}
        </div>
      )}
      <h3 className={styles.title}>{title}</h3>
      {description != null && <p className={styles.description}>{description}</p>}
      {code != null && (
        <div className={styles.codeBlock}>
          <pre className={styles.code}>
            <code>{code}</code>
          </pre>
          <IconButton
            aria-label="Copy snippet"
            icon={copied ? <Check /> : <Copy />}
            size="sm"
            tooltip={copied ? 'Copied' : 'Copy snippet'}
            onClick={() => void copy(code)}
          />
          <span role="status" className={styles.srOnly}>
            {copied ? 'Copied' : ''}
          </span>
        </div>
      )}
      {action != null && <div className={styles.action}>{action}</div>}
      {docsHref != null && (
        <a className={styles.docsLink} href={docsHref} target="_blank" rel="noreferrer">
          {docsLabel}
          <ExternalLink className={styles.docsIcon} aria-hidden="true" />
        </a>
      )}
    </div>
  )
}
