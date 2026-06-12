import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { useNavigate } from 'react-router-dom'
import { Check, ChevronsUpDown } from 'lucide-react'
import { cn } from '@/lib/cn'
import { useProjects } from '@/api/queries'
import { projectColor } from '@/app/projectColor'
import styles from './ProjectSwitcher.module.css'

/**
 * Project context switcher at the top of the project sidebar: shows the
 * current project (identity dot derived from slug hash) and a dropdown of
 * all projects the user belongs to.
 */
export function ProjectSwitcher({
  currentSlug,
  collapsed,
}: {
  currentSlug: string
  collapsed: boolean
}) {
  const { data: projects } = useProjects()
  const navigate = useNavigate()

  const current = projects?.find((p) => p.slug === currentSlug)
  const label = current?.name ?? currentSlug

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          className={cn(styles.trigger, collapsed && styles.triggerCollapsed)}
          aria-label={`Switch project (current: ${label})`}
          title={collapsed ? label : undefined}
        >
          <span className={styles.dot} style={{ background: projectColor(currentSlug) }} aria-hidden />
          {!collapsed && (
            <>
              <span className={styles.name}>{label}</span>
              <ChevronsUpDown size={13} aria-hidden className={styles.chevron} />
            </>
          )}
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className={styles.content} align="start" sideOffset={4}>
          <DropdownMenu.Label className={styles.menuLabel}>Switch project</DropdownMenu.Label>
          {(projects ?? []).map((project) => (
            <DropdownMenu.Item
              key={project.id}
              className={styles.item}
              onSelect={() => {
                if (project.slug !== currentSlug) {
                  navigate(`/projects/${project.slug}`)
                }
              }}
            >
              <span
                className={styles.dot}
                style={{ background: projectColor(project.slug) }}
                aria-hidden
              />
              <span className={styles.itemName}>{project.name}</span>
              {project.slug === currentSlug && (
                <Check size={13} aria-hidden className={styles.check} />
              )}
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
