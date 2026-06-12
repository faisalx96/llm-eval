import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useNavigation } from 'react-router-dom'
import { Sidebar } from '@/app/Sidebar'
import { Topbar } from '@/app/Topbar'
import { useShellContext } from '@/app/shellContext'
import styles from './AppShell.module.css'

const COLLAPSE_KEY = 'qym.sidebar.collapsed'

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSE_KEY) === '1'
  } catch {
    return false
  }
}

/** Content-area skeleton shown while a lazy route chunk loads. */
function ContentSkeleton() {
  return (
    <div className={styles.skeleton} aria-hidden>
      <div className={styles.skeletonBar} style={{ width: '32%' }} />
      <div className={styles.skeletonBar} style={{ width: '58%' }} />
      <div className={styles.skeletonGrid}>
        <div className={styles.skeletonCard} />
        <div className={styles.skeletonCard} />
        <div className={styles.skeletonCard} />
      </div>
    </div>
  )
}

/**
 * Application shell: sidebar (global or project context, resolved from the
 * route) + topbar breadcrumb + scrollable content area. Sidebar collapse is
 * persisted in localStorage.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const context = useShellContext()
  const navigation = useNavigation()
  const [collapsed, setCollapsed] = useState(readCollapsed)

  useEffect(() => {
    try {
      window.localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0')
    } catch {
      // localStorage unavailable (private mode etc.) — collapse is per-session.
    }
  }, [collapsed])

  const toggleCollapsed = useCallback(() => setCollapsed((value) => !value), [])

  return (
    <div className={styles.shell}>
      <Sidebar context={context} collapsed={collapsed} onToggleCollapsed={toggleCollapsed} />
      <div className={styles.main}>
        <Topbar context={context} />
        <main className={styles.content}>
          {navigation.state === 'loading' ? <ContentSkeleton /> : children}
        </main>
      </div>
    </div>
  )
}
