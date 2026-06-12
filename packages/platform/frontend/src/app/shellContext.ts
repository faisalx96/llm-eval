import { useMatch } from 'react-router-dom'

/**
 * Shell context resolution. The shell renders one of two sidebars:
 * - GLOBAL  (/, /admin, /profile, /__components)
 * - PROJECT (/projects/:slug/*)
 */
export interface ShellContext {
  kind: 'global' | 'project'
  /** Present only in project context. */
  slug?: string
  /** Trailing path inside the project ('' for the runs index). */
  section: string
}

export function useShellContext(): ShellContext {
  const match = useMatch('/projects/:slug/*')
  if (match?.params.slug) {
    return {
      kind: 'project',
      slug: match.params.slug,
      section: match.params['*'] ?? '',
    }
  }
  return { kind: 'global', section: '' }
}

/** Human label for the current section, used by the topbar breadcrumb. */
export function sectionLabel(ctx: ShellContext, pathname: string): string {
  if (ctx.kind === 'project') {
    const head = ctx.section.split('/')[0]
    switch (head) {
      case '':
      case 'runs':
        return 'Runs'
      case 'analysis':
        return 'Analysis'
      case 'review':
        return 'Review'
      case 'datasets':
        return 'Datasets'
      case 'settings':
        return 'Settings'
      default:
        return head
    }
  }
  if (pathname.startsWith('/admin')) return 'Admin'
  if (pathname.startsWith('/profile')) return 'Profile'
  if (pathname.startsWith('/__components')) return 'Components'
  return 'Projects'
}
