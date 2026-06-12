import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Project } from '@/api/types'
import ProjectsHome from './ProjectsHome'

const PROJECTS: Project[] = [
  {
    id: 'p1',
    name: 'Customer Support Copilot',
    slug: 'support-copilot',
    description: 'Evals for the support assistant RAG pipeline',
    is_active: true,
    member_count: 1,
    run_count: 6,
    role: 'MANAGER',
    created_at: '2026-06-10T00:00:00Z',
    updated_at: '2026-06-10T00:00:00Z',
  },
  {
    id: 'p2',
    name: 'Text2SQL Bench',
    slug: 'text2sql',
    description: 'SQL generation quality across models',
    is_active: true,
    member_count: 3,
    run_count: 5,
    role: 'MEMBER',
    created_at: '2026-06-09T00:00:00Z',
    updated_at: '2026-06-09T00:00:00Z',
  },
]

function renderHome() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ProjectsHome />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      new Response(JSON.stringify({ projects: PROJECTS }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    ),
  )
})

afterEach(() => {
  // RTL auto-cleanup is inactive without vitest `globals: true`.
  cleanup()
  vi.unstubAllGlobals()
})

describe('ProjectsHome', () => {
  it('renders a card per project with slug, counts and role', async () => {
    renderHome()

    expect(await screen.findByText('Customer Support Copilot')).toBeInTheDocument()
    expect(screen.getByText('Text2SQL Bench')).toBeInTheDocument()
    expect(screen.getByText('support-copilot')).toBeInTheDocument()
    expect(screen.getByText('manager')).toBeInTheDocument()

    const link = screen.getByRole('link', { name: /customer support copilot/i })
    expect(link).toHaveAttribute('href', '/projects/support-copilot')
  })

  it('filters cards by name', async () => {
    renderHome()
    await screen.findByText('Customer Support Copilot')

    fireEvent.change(screen.getByRole('searchbox', { name: /search projects/i }), {
      target: { value: 'sql' },
    })

    expect(screen.getByText('Text2SQL Bench')).toBeInTheDocument()
    expect(screen.queryByText('Customer Support Copilot')).not.toBeInTheDocument()
  })

  it('shows the empty state when there are no projects', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ projects: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    renderHome()

    expect(await screen.findByText('No projects yet')).toBeInTheDocument()
  })

  it('opens the create dialog from the header button', async () => {
    renderHome()
    await screen.findByText('Customer Support Copilot')

    fireEvent.click(screen.getByRole('button', { name: /new project/i }))

    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(screen.getByLabelText('Name')).toBeInTheDocument()
    expect(screen.getByLabelText('Slug')).toBeInTheDocument()
  })
})
