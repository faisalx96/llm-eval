import '@/components/ui/testPolyfills'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CorrectionEntry, RunItemDetail } from '@/api/runDetail'
import { ItemExpanded } from './ItemExpanded'
import { makeItemDetail } from './__fixtures__/runDetail'

function installFetch(detail: RunItemDetail) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      new Response(JSON.stringify(detail), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    ),
  )
}

function renderExpanded(props?: Partial<Parameters<typeof ItemExpanded>[0]>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ItemExpanded
        runId="run-1"
        itemId="item_fail"
        correction={undefined}
        canReview={false}
        {...props}
      />
    </QueryClientProvider>,
  )
}

/** Walk from a CodePanel label up to the panel root element. */
function panelRootOf(label: HTMLElement): HTMLElement {
  // label span → header div → panel root div
  return label.closest('div')?.parentElement as HTMLElement
}

beforeEach(() => {
  installFetch(makeItemDetail())
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('ItemExpanded', () => {
  it('renders OUTPUT and EXPECTED as sibling panels with identical styling', async () => {
    renderExpanded()

    const output = panelRootOf(await screen.findByText('Output'))
    const expected = panelRootOf(screen.getByText('Expected'))

    // Equal chrome: the exact same class list — no winner/loser styling.
    expect(output.className).toBe(expected.className)
    expect(output.className).toContain('sidePanel')
    // True siblings inside the side-by-side grid, nothing else between them.
    expect(output.parentElement).toBe(expected.parentElement)
    expect(output.parentElement?.children).toHaveLength(2)
    expect(output.nextElementSibling).toBe(expected)
  })

  it('renders INPUT full-width above the pair and metadata/metric chips', async () => {
    renderExpanded()
    const input = panelRootOf(await screen.findByText('Input'))
    const output = panelRootOf(screen.getByText('Output'))
    // Input is NOT inside the two-up grid.
    expect(input.parentElement).not.toBe(output.parentElement)

    expect(screen.getByText('category')).toBeInTheDocument()
    expect(screen.getByText('billing')).toBeInTheDocument()
    // Metric chip shows the failing score in the fail hue (value rendered).
    expect(screen.getByText('0%')).toBeInTheDocument()
  })

  it('offers a word diff toggle for short non-JSON output/expected', async () => {
    renderExpanded()
    const toggle = await screen.findByRole('button', { name: 'Show word diff' })
    fireEvent.click(toggle)
    expect(screen.getByText('Output vs expected')).toBeInTheDocument()
    expect(screen.queryByText('Expected')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show side by side' }))
    expect(screen.getByText('Expected')).toBeInTheDocument()
  })

  it('shows the correction block with provenance and pending badge', async () => {
    renderExpanded()
    expect(await screen.findByText('retrieval_miss')).toBeInTheDocument()
    expect(screen.getByText('Human')).toBeInTheDocument()
    expect(screen.getByText('Pending review')).toBeInTheDocument()
    expect(screen.getByText('re-chunk_billing_corpus')).toBeInTheDocument()
    // Without review rights there are no decision buttons.
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
  })

  it('shows Approve/Reject for reviewers when a pending correction record exists', async () => {
    const correction: CorrectionEntry = {
      id: 7,
      run_id: 'run-1',
      item_id: 'item_fail',
      status: 'pending',
      human_root_cause: 'retrieval_miss',
      human_root_cause_detail: '',
      human_solution: '',
      ai_root_cause: '',
      ai_root_cause_detail: '',
      ai_solution: '',
      is_active: true,
    }
    renderExpanded({ correction, canReview: true })
    expect(await screen.findByRole('button', { name: 'Approve' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Reject' })).toBeEnabled()
  })

  it('marks AI-tagged root causes with the AI provenance tag', async () => {
    installFetch(
      makeItemDetail({
        item_metadata: { root_cause: 'hallucination', root_cause_source: 'ai' },
      }),
    )
    renderExpanded()
    expect(await screen.findByText('AI')).toBeInTheDocument()
  })
})
