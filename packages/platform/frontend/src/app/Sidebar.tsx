import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import {
  Activity,
  ArrowLeft,
  BookOpen,
  ChartLine,
  ClipboardCheck,
  Database,
  ExternalLink,
  LayoutGrid,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  Shield,
} from 'lucide-react'
import { cn } from '@/lib/cn'
import { useMe } from '@/api/queries'
import { apiBase } from '@/api/client'
import type { ShellContext } from '@/app/shellContext'
import { ProjectSwitcher } from '@/app/ProjectSwitcher'
import { UserChip } from '@/app/UserChip'
import styles from './Sidebar.module.css'

const ICON_SIZE = 15

interface NavEntry {
  label: string
  to: string
  icon: React.ReactNode
  /** Exactly-one-active rule: a predicate over the current pathname. */
  isActive: (pathname: string) => boolean
}

function globalNav(): NavEntry[] {
  return [
    {
      label: 'Projects',
      to: '/',
      icon: <LayoutGrid size={ICON_SIZE} aria-hidden />,
      isActive: (p) => p === '/',
    },
  ]
}

function projectNav(slug: string): NavEntry[] {
  const base = `/projects/${slug}`
  return [
    {
      label: 'Runs',
      to: base,
      icon: <Activity size={ICON_SIZE} aria-hidden />,
      // The runs index lives at the project root; run detail under /runs/.
      isActive: (p) => p === base || p.startsWith(`${base}/runs`),
    },
    {
      label: 'Analysis',
      to: `${base}/analysis`,
      icon: <ChartLine size={ICON_SIZE} aria-hidden />,
      isActive: (p) => p.startsWith(`${base}/analysis`),
    },
    {
      label: 'Review',
      to: `${base}/review`,
      icon: <ClipboardCheck size={ICON_SIZE} aria-hidden />,
      isActive: (p) => p.startsWith(`${base}/review`),
    },
    {
      label: 'Datasets',
      to: `${base}/datasets`,
      icon: <Database size={ICON_SIZE} aria-hidden />,
      isActive: (p) => p.startsWith(`${base}/datasets`),
    },
    {
      label: 'Settings',
      to: `${base}/settings`,
      icon: <Settings size={ICON_SIZE} aria-hidden />,
      isActive: (p) => p.startsWith(`${base}/settings`),
    },
  ]
}

function NavItem({
  entry,
  pathname,
  collapsed,
}: {
  entry: NavEntry
  pathname: string
  collapsed: boolean
}) {
  const active = entry.isActive(pathname)
  return (
    <Link
      to={entry.to}
      className={cn(styles.navItem, active && styles.navItemActive)}
      aria-current={active ? 'page' : undefined}
      title={collapsed ? entry.label : undefined}
    >
      <span className={styles.navIcon}>{entry.icon}</span>
      {!collapsed && <span className={styles.navLabel}>{entry.label}</span>}
    </Link>
  )
}

export function Sidebar({
  context,
  collapsed,
  onToggleCollapsed,
}: {
  context: ShellContext
  collapsed: boolean
  onToggleCollapsed: () => void
}) {
  const { data: me } = useMe()
  const { pathname } = useLocation()
  const [brandIconFailed, setBrandIconFailed] = useState(false)

  const entries = context.kind === 'project' ? projectNav(context.slug ?? '') : globalNav()

  return (
    <aside className={cn(styles.sidebar, collapsed && styles.collapsed)} aria-label="Sidebar">
      {context.kind === 'global' ? (
        <Link to="/" className={styles.brand} title={collapsed ? 'qym' : undefined}>
          {!brandIconFailed ? (
            <img
              src={`${apiBase()}/static/qym_icon.png`}
              alt=""
              className={styles.brandIcon}
              onError={() => setBrandIconFailed(true)}
            />
          ) : (
            <span className={styles.brandIconFallback} aria-hidden>
              q
            </span>
          )}
          {!collapsed && <span className={styles.brandName}>qym</span>}
        </Link>
      ) : (
        <ProjectSwitcher currentSlug={context.slug ?? ''} collapsed={collapsed} />
      )}

      <nav className={styles.nav} aria-label="Primary">
        {entries.map((entry) => (
          <NavItem key={entry.to} entry={entry} pathname={pathname} collapsed={collapsed} />
        ))}

        {context.kind === 'global' && (
          <>
            <a
              href={`${apiBase()}/docs/`}
              className={styles.navItem}
              title={collapsed ? 'Docs' : undefined}
            >
              <span className={styles.navIcon}>
                <BookOpen size={ICON_SIZE} aria-hidden />
              </span>
              {!collapsed && (
                <span className={styles.navLabel}>
                  Docs
                  <ExternalLink size={11} aria-hidden className={styles.externalMark} />
                </span>
              )}
            </a>
            {me?.role === 'ADMIN' && (
              <NavItem
                entry={{
                  label: 'Admin',
                  to: '/admin',
                  icon: <Shield size={ICON_SIZE} aria-hidden />,
                  isActive: (p) => p.startsWith('/admin'),
                }}
                pathname={pathname}
                collapsed={collapsed}
              />
            )}
          </>
        )}

        {context.kind === 'project' && (
          <>
            <hr className={styles.divider} />
            <Link
              to="/"
              className={styles.navItem}
              title={collapsed ? 'All projects' : undefined}
            >
              <span className={styles.navIcon}>
                <ArrowLeft size={ICON_SIZE} aria-hidden />
              </span>
              {!collapsed && <span className={styles.navLabel}>All projects</span>}
            </Link>
          </>
        )}
      </nav>

      <div className={styles.footer}>
        <button
          type="button"
          className={styles.collapseButton}
          onClick={onToggleCollapsed}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? (
            <PanelLeftOpen size={ICON_SIZE} aria-hidden />
          ) : (
            <PanelLeftClose size={ICON_SIZE} aria-hidden />
          )}
          {!collapsed && <span className={styles.navLabel}>Collapse</span>}
        </button>
        <UserChip collapsed={collapsed} />
      </div>
    </aside>
  )
}
