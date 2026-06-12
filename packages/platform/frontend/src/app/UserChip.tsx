import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { useNavigate } from 'react-router-dom'
import { cn } from '@/lib/cn'
import { useMe } from '@/api/queries'
import { apiFetch } from '@/api/client'
import styles from './UserChip.module.css'

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

/**
 * Bottom-of-sidebar user chip: initials avatar, name, email. Dropdown with
 * Profile; in auth mode "none" there is no logout — the auth type is shown
 * instead.
 */
export function UserChip({ collapsed }: { collapsed: boolean }) {
  const { data: me } = useMe()
  const navigate = useNavigate()

  if (!me) {
    return (
      <div className={cn(styles.chip, styles.chipLoading)} aria-hidden>
        <span className={styles.avatar} />
      </div>
    )
  }

  const name = me.display_name || me.email

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          className={cn(styles.chip, collapsed && styles.chipCollapsed)}
          aria-label={`User menu (${name})`}
          title={collapsed ? name : undefined}
        >
          <span className={styles.avatar} aria-hidden>
            {initials(name)}
          </span>
          {!collapsed && (
            <span className={styles.identity}>
              <span className={styles.name}>{name}</span>
              <span className={styles.email}>{me.email}</span>
            </span>
          )}
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className={styles.content} align="start" side="top" sideOffset={4}>
          <DropdownMenu.Item className={styles.item} onSelect={() => navigate('/profile')}>
            Profile
          </DropdownMenu.Item>
          {me.auth_type !== 'none' && (
            <DropdownMenu.Item
              className={styles.item}
              onSelect={() => {
                void apiFetch('/v1/auth/logout', { method: 'POST' }).finally(() => {
                  window.location.reload()
                })
              }}
            >
              Log out
            </DropdownMenu.Item>
          )}
          <DropdownMenu.Separator className={styles.separator} />
          {/* Auth mode "none" has no session to log out of — surface the mode. */}
          <div className={styles.meta}>
            <span>Auth</span>
            <span className={styles.metaValue}>{me.auth_type}</span>
          </div>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
