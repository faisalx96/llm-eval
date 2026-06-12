import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { FolderKanban, Plus, Search } from 'lucide-react'
import { useProjects } from '@/api/queries'
import type { Project } from '@/api/types'
import { projectColor } from '@/app/projectColor'
import { Button, EmptyState } from '@/components/ui'
import { fmtRelativeTimeWithTitle } from '@/lib/format'
import { CreateProjectDialog } from './CreateProjectDialog'
import styles from './ProjectsHome.module.css'

function ProjectCard({ project }: { project: Project }) {
  const updated = fmtRelativeTimeWithTitle(project.updated_at)
  return (
    <li>
      <Link to={`/projects/${project.slug}`} className={styles.card}>
        <div className={styles.cardHeader}>
          <span
            className={styles.cardDot}
            style={{ background: projectColor(project.slug) }}
            aria-hidden
          />
          <span className={styles.cardName}>{project.name}</span>
          <span className={styles.roleBadge}>{project.role.toLowerCase()}</span>
        </div>
        <span className={styles.cardSlug}>{project.slug}</span>
        <p className={styles.cardDescription}>{project.description || 'No description'}</p>
        <div className={styles.cardMeta}>
          <span>
            <span className={styles.metaValue}>{project.member_count}</span>{' '}
            {project.member_count === 1 ? 'member' : 'members'}
          </span>
          <span>
            <span className={styles.metaValue}>{project.run_count}</span>{' '}
            {project.run_count === 1 ? 'run' : 'runs'}
          </span>
          <span className={styles.metaUpdated} title={updated.title}>
            updated {updated.label}
          </span>
        </div>
      </Link>
    </li>
  )
}

function CardSkeletons() {
  return (
    <ul className={styles.grid} aria-hidden>
      {[0, 1, 2].map((i) => (
        <li key={i} className={styles.cardSkeleton} />
      ))}
    </ul>
  )
}

/** Projects landing (route: /). */
export default function ProjectsHome() {
  const { data: projects, isPending, isError, error, refetch } = useProjects()
  const [query, setQuery] = useState('')
  const [createOpen, setCreateOpen] = useState(false)

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return projects ?? []
    return (projects ?? []).filter((p) => p.name.toLowerCase().includes(needle))
  }, [projects, query])

  return (
    <section className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.heading}>Projects</h1>
        <div className={styles.controls}>
          <div className={styles.search}>
            <Search size={13} aria-hidden className={styles.searchIcon} />
            <input
              type="search"
              className={styles.searchInput}
              placeholder="Search projects"
              aria-label="Search projects by name"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <Button icon={<Plus />} onClick={() => setCreateOpen(true)}>
            New project
          </Button>
        </div>
      </header>

      {isPending && <CardSkeletons />}

      {isError && (
        <div className={styles.errorCard} role="alert">
          <p className={styles.errorText}>
            Could not load projects{error instanceof Error ? `: ${error.message}` : '.'}
          </p>
          <Button variant="secondary" onClick={() => void refetch()}>
            Retry
          </Button>
        </div>
      )}

      {!isPending && !isError && projects?.length === 0 && (
        <EmptyState
          icon={<FolderKanban />}
          title="No projects yet"
          description="Create a project to start tracking eval runs."
          action={
            <Button icon={<Plus />} onClick={() => setCreateOpen(true)}>
              New project
            </Button>
          }
        />
      )}

      {!isPending && !isError && (projects?.length ?? 0) > 0 && (
        <>
          {filtered.length > 0 ? (
            <ul className={styles.grid}>
              {filtered.map((project) => (
                <ProjectCard key={project.id} project={project} />
              ))}
            </ul>
          ) : (
            <p className={styles.noMatches}>No projects match “{query.trim()}”.</p>
          )}
        </>
      )}

      <CreateProjectDialog open={createOpen} onOpenChange={setCreateOpen} />
    </section>
  )
}
