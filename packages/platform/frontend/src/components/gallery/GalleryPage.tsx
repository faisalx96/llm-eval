import { useState } from 'react'
import type { ReactNode } from 'react'
import {
  BookOpen,
  Copy,
  Download,
  Inbox,
  MoreVertical,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
} from 'lucide-react'
import {
  Button,
  ConfirmModal,
  CopyChip,
  Drawer,
  DropdownMenu,
  DropdownMenuItem,
  DropdownMenuSeparator,
  EmptyState,
  IconButton,
  ProgressBar,
  Skeleton,
  SkeletonText,
  STATUSES,
  StatusBadge,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Toaster,
  Tooltip,
  useToast,
} from '../ui'
import { count } from '@/lib/pluralize'
import styles from './GalleryPage.module.css'

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className={styles.section}>
      <h2 className={styles.sectionTitle}>{title}</h2>
      {children}
    </section>
  )
}

function Example({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className={styles.example}>
      <span className={styles.exampleLabel}>{label}</span>
      <div className={styles.exampleBody}>{children}</div>
    </div>
  )
}

/** Dev-only component gallery, served at /__components. */
export default function GalleryPage() {
  const { toast } = useToast()
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [dangerConfirmOpen, setDangerConfirmOpen] = useState(false)
  const [commentConfirmOpen, setCommentConfirmOpen] = useState(false)
  const [drawerSize, setDrawerSize] = useState<'md' | 'lg' | 'full' | null>(null)

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.pageTitle}>Component gallery</h1>
        <p className={styles.pageSubtitle}>
          Dev-only reference for every design-system primitive. Not linked from the app shell.
        </p>
      </header>

      <Section title="Button">
        <Example label="Variants (md)">
          <Button variant="primary">Create run</Button>
          <Button variant="secondary">Export results</Button>
          <Button variant="ghost">Cancel</Button>
          <Button variant="danger">Delete run</Button>
          <Button variant="link">View raw output</Button>
        </Example>
        <Example label="Size sm">
          <Button variant="primary" size="sm">
            Create run
          </Button>
          <Button variant="secondary" size="sm">
            Export results
          </Button>
          <Button variant="danger" size="sm">
            Delete run
          </Button>
        </Example>
        <Example label="With icon / loading / disabled">
          <Button variant="primary" icon={<Plus />}>
            New project
          </Button>
          <Button variant="secondary" icon={<Download />}>
            Download report
          </Button>
          <Button variant="primary" loading>
            Submitting
          </Button>
          <Button variant="secondary" disabled>
            Unavailable
          </Button>
        </Example>
        <Example label="IconButton (tooltip = aria-label)">
          <IconButton aria-label="Edit name" icon={<Pencil />} />
          <IconButton aria-label="Refresh data" icon={<RefreshCw />} size="sm" />
          <IconButton aria-label="Delete dataset" icon={<Trash2 />} variant="danger" />
        </Example>
      </Section>

      <Section title="StatusBadge — the single status→hue map">
        <Example label="All statuses (sm)">
          {STATUSES.map((status) => (
            <StatusBadge key={status} status={status} />
          ))}
        </Example>
        <Example label="Hero size (md) — same hues">
          {STATUSES.map((status) => (
            <StatusBadge key={status} status={status} size="md" />
          ))}
        </Example>
        <Example label="Running with inline progress">
          <StatusBadge status="RUNNING" progress={{ pct: 33, done: 4, total: 12 }} />
          <StatusBadge status="RUNNING" size="md" progress={{ pct: 75, done: 9, total: 12 }} />
        </Example>
      </Section>

      <Section title="Tabs — underline, the one tab paradigm">
        <Tabs defaultValue="results">
          <TabsList aria-label="Gallery tabs demo">
            <TabsTrigger value="results" count={128}>
              Results
            </TabsTrigger>
            <TabsTrigger value="failures" count={7}>
              Failures
            </TabsTrigger>
            <TabsTrigger value="config">Config</TabsTrigger>
            <TabsTrigger value="disabled" disabled>
              Disabled
            </TabsTrigger>
          </TabsList>
          <TabsContent value="results" className={styles.tabPanel}>
            Results panel content
          </TabsContent>
          <TabsContent value="failures" className={styles.tabPanel}>
            Failures panel content
          </TabsContent>
          <TabsContent value="config" className={styles.tabPanel}>
            Config panel content
          </TabsContent>
        </Tabs>
      </Section>

      <Section title="Tooltip">
        <Example label="Hover or focus the trigger">
          <Tooltip content="Stops the run after the current task finishes">
            <Button variant="secondary">Stop run</Button>
          </Tooltip>
        </Example>
      </Section>

      <Section title="Toast">
        <Example label="Fire a toast (auto-dismisses)">
          <Button
            variant="secondary"
            onClick={() => toast({ title: 'Run started', description: '12 tasks queued', variant: 'info' })}
          >
            Info toast
          </Button>
          <Button
            variant="secondary"
            onClick={() => toast({ title: 'Settings saved', variant: 'success' })}
          >
            Success toast
          </Button>
          <Button
            variant="secondary"
            onClick={() =>
              toast({ title: 'Export failed', description: 'Disk quota exceeded', variant: 'error' })
            }
          >
            Error toast
          </Button>
        </Example>
      </Section>

      <Section title="ConfirmModal">
        <Example label="Basic / danger + type-to-confirm / require comment">
          <Button variant="secondary" onClick={() => setConfirmOpen(true)}>
            Stop run…
          </Button>
          <Button variant="danger" onClick={() => setDangerConfirmOpen(true)}>
            Delete project…
          </Button>
          <Button variant="secondary" onClick={() => setCommentConfirmOpen(true)}>
            Reject submission…
          </Button>
        </Example>
        <ConfirmModal
          open={confirmOpen}
          onOpenChange={setConfirmOpen}
          title="Stop run"
          itemLabel="run-2026-06-11-a"
          confirmLabel="Stop run"
          onConfirm={() => toast({ title: 'Run stopped', variant: 'info' })}
        >
          In-flight tasks finish, queued tasks are cancelled.
        </ConfirmModal>
        <ConfirmModal
          open={dangerConfirmOpen}
          onOpenChange={setDangerConfirmOpen}
          title="Delete project"
          itemLabel="support-copilot"
          confirmLabel="Delete project"
          danger
          typeToConfirm="support-copilot"
          onConfirm={() => toast({ title: 'Project deleted', variant: 'error' })}
        >
          This permanently removes all runs, datasets, and review history.
        </ConfirmModal>
        <ConfirmModal
          open={commentConfirmOpen}
          onOpenChange={setCommentConfirmOpen}
          title="Reject submission"
          itemLabel="run-2026-06-10-c"
          confirmLabel="Reject"
          danger
          requireComment={{ label: 'Reason for rejection', placeholder: 'Visible to the submitter' }}
          onConfirm={({ comment }) =>
            toast({ title: 'Submission rejected', description: comment, variant: 'info' })
          }
        >
          The submitter is notified with your reason.
        </ConfirmModal>
      </Section>

      <Section title="DropdownMenu — the app kebab menu">
        <Example label="Icons, separator, danger item">
          <DropdownMenu
            trigger={<IconButton aria-label="Run actions" icon={<MoreVertical />} tooltip={null} />}
          >
            <DropdownMenuItem icon={<Pencil />} onSelect={() => toast({ title: 'Rename selected' })}>
              Rename run
            </DropdownMenuItem>
            <DropdownMenuItem icon={<Copy />} onSelect={() => toast({ title: 'Duplicate selected' })}>
              Duplicate run
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              icon={<Trash2 />}
              danger
              onSelect={() => toast({ title: 'Delete selected', variant: 'error' })}
            >
              Delete run
            </DropdownMenuItem>
          </DropdownMenu>
        </Example>
      </Section>

      <Section title="Drawer">
        <Example label="Sizes">
          <Button variant="secondary" onClick={() => setDrawerSize('md')}>
            Open md drawer
          </Button>
          <Button variant="secondary" onClick={() => setDrawerSize('lg')}>
            Open lg drawer
          </Button>
          <Button variant="secondary" onClick={() => setDrawerSize('full')}>
            Open full drawer
          </Button>
        </Example>
        <Drawer
          open={drawerSize !== null}
          onOpenChange={(open) => {
            if (!open) setDrawerSize(null)
          }}
          title="Result detail"
          size={drawerSize ?? 'md'}
          description="Full trace and metadata for this result"
        >
          <p className={styles.drawerDemoText}>
            Scrollable body content. The drawer always covers the full viewport edge, over any
            sidebar.
          </p>
          <SkeletonText lines={12} />
        </Drawer>
      </Section>

      <Section title="Skeleton & ProgressBar">
        <Example label="Skeleton block + text lines">
          <div className={styles.skeletonDemo}>
            <Skeleton width={200} height={24} />
            <SkeletonText lines={3} />
          </div>
        </Example>
        <Example label="ProgressBar accent / neutral">
          <div className={styles.progressDemo}>
            <ProgressBar value={4} max={12} label={`Tasks complete — ${count(4, 'task')} of 12`} />
            <ProgressBar value={62} variant="neutral" label="Storage used" />
          </div>
        </Example>
      </Section>

      <Section title="EmptyState — the one empty-state contract">
        <EmptyState
          icon={<Inbox />}
          title="No runs yet"
          description="Kick off your first evaluation run from the CLI to see results here."
          action={<Button variant="primary" icon={<Plus />}>Create run</Button>}
          code="qym run --project sandbox"
          docsHref="https://example.com/docs/runs"
          docsLabel="Read the runs guide"
        />
      </Section>

      <Section title="CopyChip">
        <Example label="UUID, custom display, short value">
          <CopyChip value="7f3b9c2a-4e1d-4f6a-8b0c-2d9e5a7c1b3f" />
          <CopyChip value="7f3b9c2a-4e1d-4f6a-8b0c-2d9e5a7c1b3f" display="latest run id" />
          <CopyChip value="sandbox" />
        </Example>
      </Section>

      <Section title="pluralize">
        <Example label="count(n, word)">
          <code className={styles.mono}>{count(1, 'run')}</code>
          <code className={styles.mono}>{count(3, 'run')}</code>
          <code className={styles.mono}>{count(2, 'query')}</code>
          <code className={styles.mono}>{count(0, 'match')}</code>
          <code className={styles.mono}>{count(2, 'child')}</code>
        </Example>
        <Example label="Docs">
          <a className={styles.docsNote} href="https://example.com/docs" target="_blank" rel="noreferrer">
            <BookOpen className={styles.docsNoteIcon} aria-hidden="true" />
            Design-system usage notes
          </a>
        </Example>
      </Section>

      <Toaster />
    </main>
  )
}
