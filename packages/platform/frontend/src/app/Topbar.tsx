import type { ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useProjects } from '@/api/queries'
import { sectionLabel, type ShellContext } from '@/app/shellContext'
import styles from './Topbar.module.css'

/**
 * Topbar: breadcrumb (Project name / Section) on the left, reserved
 * actions slot (children) on the right for page-level controls.
 */
export function Topbar({ context, children }: { context: ShellContext; children?: ReactNode }) {
  const { pathname } = useLocation()
  const { data: projects } = useProjects()

  const section = sectionLabel(context, pathname)
  const projectName =
    context.kind === 'project'
      ? (projects?.find((p) => p.slug === context.slug)?.name ?? context.slug)
      : null

  return (
    <header className={styles.topbar}>
      <nav className={styles.breadcrumb} aria-label="Breadcrumb">
        {projectName !== null ? (
          <>
            <Link to={`/projects/${context.slug}`} className={styles.crumbLink}>
              {projectName}
            </Link>
            <span className={styles.crumbSeparator} aria-hidden>
              /
            </span>
            <span className={styles.crumbCurrent} aria-current="page">
              {section}
            </span>
          </>
        ) : (
          <span className={styles.crumbCurrent} aria-current="page">
            {section}
          </span>
        )}
      </nav>
      <div className={styles.actions}>{children}</div>
    </header>
  )
}
