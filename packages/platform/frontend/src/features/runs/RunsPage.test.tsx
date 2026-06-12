import '@/components/ui/testPolyfills'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { RunSummary } from '@/api/runs'
import { dismissAllToasts } from '@/components/ui'
import RunsPage from './RunsPage'

/* ── Fixtures ──────────────────────────────────────────────────────────── */

const PROJECT = {
  id: 'p1',
  name: 'Customer Support Copilot',
  slug: 'support-copilot',
  description: '',
  is_active: true,
  member_count: 1,
  run_count: 6,
  role: 'MANAGER',
  created_at: '2026-06-10T00:00:00Z',
  updated_at: '2026-06-10T00:00:00Z',
}

const ME = {
  id: 'u1',
  email: 'dev@local',
  display_name: 'Dev User',
  title: '',
  role: 'ADMIN',
  auth_type: 'none',
  auth_provider: null,
  needs_admin_bootstrap: false,
  can_bootstrap_admin: false,
  projects: [PROJECT],
  default_project: PROJECT,
}

const STATS = {
  project_id: 'p1',
  total_runs: 6,
  by_status: { COMPLETED: 4, APPROVED: 1, REJECTED: 1 },
  models: ['gpt-4o', 'gpt-4o-mini', 'claude-sonnet-4-6', 'llama-3.1-70b'],
  total_items: 72,
  metric_averages: {},
  last_run_at: null,
}

function makeRun(overrides: Partial<RunSummary> & { id: string; name: string }): RunSummary {
  return {
    task: 'support_rag',
    dataset: 'support_qa.csv',
    model: 'gpt-4o',
    status: 'COMPLETED',
    created_at: '2026-06-10T10:00:00Z',
    started_at: '2026-06-10T10:00:00Z',
    ended_at: '2026-06-10T10:20:00Z',
    duration_ms: 1_200_000,
    owner: { id: 'u1', email: 'dev@local', display_name: 'Dev User' },
    total_items: 12,
    completed_items: 12,
    error_items: 0,
    progress_pct: 1,
    metric_averages: { exact_match: 0.9 },
    version: { branch: 'main', commit: '9001ac4' },
    group_key: 'support_rag|support_qa.csv|gpt-4o',
    ...overrides,
  }
}

// Newest first, the way the server returns -created_at.
const RUNS: RunSummary[] = [
  makeRun({
    id: 'run-c',
    name: 'live-run',
    status: 'RUNNING',
    group_key: '',
    created_at: '2026-06-12T09:00:00Z',
    completed_items: 4,
    progress_pct: 4 / 12,
    metric_averages: {},
  }),
  makeRun({
    id: 'run-b',
    name: 'candidate-eval',
    created_at: '2026-06-11T10:00:00Z',
    started_at: '2026-06-11T10:00:00Z',
    metric_averages: { exact_match: 0.9 },
  }),
  makeRun({
    id: 'run-a',
    name: 'baseline-eval',
    created_at: '2026-06-10T10:00:00Z',
    started_at: '2026-06-10T10:00:00Z',
    metric_averages: { exact_match: 0.8 },
  }),
]

/* ── Fetch stub ────────────────────────────────────────────────────────── */

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

interface FetchOptions {
  patchResponse?: () => Promise<Response>
  runsResponse?: () => Response
  needsReviewTotal?: number
}

let fetchMock: ReturnType<typeof vi.fn>

function installFetch(options: FetchOptions = {}) {
  fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url.includes('/v1/me')) return json(ME)
    if (url.includes('/overview-stats')) return json(STATS)
    if (url.includes('/v1/projects')) return json({ projects: [PROJECT] })
    if (method === 'PATCH' && /\/v1\/runs\/[^/?]+$/.test(url)) {
      return options.patchResponse
        ? options.patchResponse()
        : json({ id: 'run-a', name: 'renamed' })
    }
    if (url.includes('/api/runs/delete')) return json({ ok: true })
    if (url.includes('needs_review=true') && url.includes('limit=1&')) {
      return json({ runs: [], total: options.needsReviewTotal ?? 2, limit: 1, offset: 0 })
    }
    if (url.includes('/v1/runs?')) {
      return options.runsResponse
        ? options.runsResponse()
        : json({ runs: RUNS, total: RUNS.length, limit: 50, offset: 0 })
    }
    throw new Error(`Unhandled fetch: ${method} ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/projects/support-copilot']}>
        <Routes>
          <Route path="/projects/:slug" element={<RunsPage />} />
          <Route path="*" element={<div />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function openMenu(trigger: HTMLElement) {
  fireEvent.keyDown(trigger, { key: 'Enter' })
  return await screen.findByRole('menu')
}

beforeEach(() => {
  window.localStorage.clear()
  installFetch()
})

afterEach(() => {
  cleanup()
  dismissAllToasts()
  vi.unstubAllGlobals()
})

/* ── Tests ─────────────────────────────────────────────────────────────── */

describe('RunsPage', () => {
  it('renders stat chips, status badges with progress, and group headers', async () => {
    renderPage()

    expect(await screen.findByText('baseline-eval')).toBeInTheDocument()
    // Stat chips from overview-stats (loads after the project resolves).
    expect(screen.getByText('Total runs')).toBeInTheDocument()
    expect(await screen.findByText('6')).toBeInTheDocument()
    expect(await screen.findByText('100%')).toBeInTheDocument()
    // RUNNING badge carries inline progress.
    expect(screen.getByText('RUNNING · 33% · 4/12')).toBeInTheDocument()
    // Grouping assembled from group_key (2 members share the key).
    expect(
      screen.getByText('support_rag · support_qa.csv · gpt-4o · 2 runs'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Compare all' })).toBeInTheDocument()
    // The naming rule holds: no bare UUID anywhere.
    expect(document.body.textContent).not.toMatch(
      /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i,
    )
  })

  it('needs-review toggle requests needs_review=true for the list', async () => {
    renderPage()
    // Count comes from the cheap limit=1 query.
    const chip = await screen.findByRole('button', { name: 'Needs review (2)' })
    expect(chip).toHaveAttribute('aria-pressed', 'false')

    fireEvent.click(chip)
    expect(chip).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() => {
      const listCall = fetchMock.mock.calls.find(([u]) => {
        const url = String(u)
        return url.includes('needs_review=true') && url.includes('limit=50')
      })
      expect(listCall).toBeTruthy()
    })
  })

  it('auto-hides zero-entropy columns and explains why in the Columns menu', async () => {
    renderPage()
    await screen.findByText('baseline-eval')

    // Dataset and version are identical across the page → hidden by default.
    expect(screen.queryByRole('columnheader', { name: 'Dataset' })).not.toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Version' })).not.toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Task' })).toBeInTheDocument()

    const menu = await openMenu(screen.getByRole('button', { name: 'Columns' }))
    const datasetItem = within(menu).getByRole('menuitem', { name: /Dataset/ })
    expect(datasetItem).toHaveTextContent('(hidden — same for all)')

    // Re-enabling from the menu brings the column back. Close the menu
    // first — an open Radix menu aria-hides the rest of the page.
    fireEvent.click(datasetItem)
    fireEvent.keyDown(menu, { key: 'Escape' })
    await waitFor(() => {
      expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    })
    expect(await screen.findByRole('columnheader', { name: 'Dataset' })).toBeInTheDocument()
  })

  it('renames optimistically and PATCHes display_name', async () => {
    // PATCH never resolves — the immediate UI update must be optimistic.
    installFetch({ patchResponse: () => new Promise<Response>(() => {}) })
    renderPage()
    await screen.findByText('baseline-eval')

    fireEvent.click(screen.getByRole('button', { name: 'Rename baseline-eval' }))
    const input = screen.getByRole('textbox', { name: 'Run name' })
    fireEvent.change(input, { target: { value: 'renamed-by-me' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(await screen.findByText('renamed-by-me')).toBeInTheDocument()
    expect(screen.queryByText('baseline-eval')).not.toBeInTheDocument()

    const patchCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')
    expect(patchCall).toBeTruthy()
    expect(String(patchCall![0])).toContain('/v1/runs/run-a')
    expect(JSON.parse(String(patchCall![1]!.body))).toEqual({ display_name: 'renamed-by-me' })
  })

  it('rolls the rename back and toasts when the PATCH fails', async () => {
    installFetch({
      patchResponse: () =>
        Promise.resolve(json({ detail: 'Only the run owner or a project manager can rename' }, 403)),
    })
    renderPage()
    await screen.findByText('baseline-eval')

    fireEvent.click(screen.getByRole('button', { name: 'Rename baseline-eval' }))
    const input = screen.getByRole('textbox', { name: 'Run name' })
    fireEvent.change(input, { target: { value: 'doomed-rename' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(await screen.findByText('Rename failed')).toBeInTheDocument()
    expect(
      screen.getByText('Only the run owner or a project manager can rename'),
    ).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByText('baseline-eval')).toBeInTheDocument()
    })
    expect(screen.queryByText('doomed-rename')).not.toBeInTheDocument()
  })

  it('delete modal uses the truthful soft-delete copy, with a warning for running runs', async () => {
    renderPage()
    await screen.findByText('live-run')

    // RUNNING run → warning line present.
    await openMenu(screen.getByRole('button', { name: 'Actions for live-run' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
    let dialog = await screen.findByRole('dialog', { name: 'Move run to Deleted Runs' })
    expect(dialog).toHaveTextContent('live-run')
    expect(dialog).toHaveTextContent('Admins can restore it later.')
    expect(dialog).toHaveTextContent('This run is still executing.')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })

    // Finished run → same copy, no warning; confirming POSTs the soft delete.
    await openMenu(screen.getByRole('button', { name: 'Actions for candidate-eval' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
    dialog = await screen.findByRole('dialog', { name: 'Move run to Deleted Runs' })
    expect(dialog).toHaveTextContent('candidate-eval')
    expect(dialog).not.toHaveTextContent('This run is still executing.')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete' }))

    await waitFor(() => {
      const deleteCall = fetchMock.mock.calls.find(([u]) =>
        String(u).includes('/api/runs/delete'),
      )
      expect(deleteCall).toBeTruthy()
      expect(JSON.parse(String(deleteCall![1]!.body))).toEqual({ file_path: 'run-b' })
    })
  })

  it('selection toolbar lists selected names and enables compare at ≥2', async () => {
    renderPage()
    await screen.findByText('baseline-eval')

    fireEvent.click(screen.getAllByRole('checkbox', { name: 'Select row' })[0])
    expect(await screen.findByText('1 run selected')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Compare' })).toBeDisabled()

    // Re-query: the table re-renders once the selection toolbar appears.
    fireEvent.click(screen.getAllByRole('checkbox', { name: 'Select row' })[1])
    expect(await screen.findByText('2 runs selected')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Compare' })).toBeEnabled()
    const toolbar = screen.getByRole('toolbar', { name: 'Selected runs' })
    expect(within(toolbar).getByText('live-run')).toBeInTheDocument()
    expect(within(toolbar).getByText('candidate-eval')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
    expect(screen.queryByText('2 runs selected')).not.toBeInTheDocument()
  })

  it('shows the SDK empty state for a project with no runs at all', async () => {
    installFetch({
      runsResponse: () => json({ runs: [], total: 0, limit: 50, offset: 0 }),
      needsReviewTotal: 0,
    })
    renderPage()

    expect(await screen.findByText('No runs yet')).toBeInTheDocument()
    expect(
      screen.getByText('Run an evaluation with the SDK to populate this project.'),
    ).toBeInTheDocument()
    expect(screen.getByText(/pip install qym/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Read the docs/ })).toHaveAttribute(
      'href',
      '/docs/',
    )
  })
})
