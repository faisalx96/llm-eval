import '@/components/ui/testPolyfills'
import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'
import { ItemsPanel } from './ItemsPanel'
import type { Segment } from './lib'
import { makeItems, makeRun } from './__fixtures__/runDetail'

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** Emulates GET /v1/runs/{id}/items incl. the server-side `q` substring filter. */
function installFetch(): Mock {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/api/corrections')) return jsonResponse({ corrections: [] })
    if (url.includes('/items')) {
      const q = new URL(url, 'http://test').searchParams.get('q')?.toLowerCase()
      const items = makeItems().filter(
        (item) =>
          !q ||
          item.input_preview.toLowerCase().includes(q) ||
          item.output_preview.toLowerCase().includes(q),
      )
      return jsonResponse({ items, total: items.length, limit: 100, offset: 0 })
    }
    return jsonResponse({})
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** Parent harness owning the lifted segment/metric state, like the page. */
function Harness() {
  const [segment, setSegment] = useState<Segment | null>(null)
  const [metric, setMetric] = useState<string | null>(null)
  return (
    <ItemsPanel
      slug="support-copilot"
      run={makeRun()}
      segment={segment}
      onSegmentChange={setSegment}
      metric={metric}
      onMetricChange={setMetric}
      canReview={false}
    />
  )
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  installFetch()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('ItemsPanel toolbar', () => {
  it('defaults to the Failures segment when failures exist', async () => {
    renderPanel()

    const failuresBtn = await screen.findByRole('button', { name: 'Failures (2)' })
    expect(failuresBtn).toHaveAttribute('aria-pressed', 'true')

    // Failure rows visible, passing row filtered out.
    expect(screen.getByText('Why was my card charged twice?')).toBeInTheDocument()
    expect(screen.getByText('benchmark query 2')).toBeInTheDocument()
    expect(screen.queryByText('How do I reset my password?')).not.toBeInTheDocument()
  })

  it('All shows every row; failures-first sort keeps the task error on top', async () => {
    renderPanel()
    fireEvent.click(await screen.findByRole('button', { name: 'All (3)' }))

    expect(await screen.findByText('How do I reset my password?')).toBeInTheDocument()
    const rows = screen.getAllByRole('row').slice(1) // drop header
    // Default sort = failures first: error item (index 2), then metric fail, then pass.
    expect(rows[0]).toHaveTextContent('benchmark query 2')
    expect(rows[1]).toHaveTextContent('Why was my card charged twice?')
    expect(rows[2]).toHaveTextContent('How do I reset my password?')
  })

  it('metric select narrows to items failing THAT metric', async () => {
    renderPanel()
    fireEvent.click(await screen.findByRole('button', { name: 'All (3)' }))
    fireEvent.change(screen.getByRole('combobox', { name: /metric/i }), {
      target: { value: 'exact_match' },
    })

    await waitFor(() => {
      expect(screen.queryByText('How do I reset my password?')).not.toBeInTheDocument()
    })
    expect(screen.getByText('Why was my card charged twice?')).toBeInTheDocument()
    // The task error has no exact_match score at all → excluded by the metric filter.
    expect(screen.queryByText('benchmark query 2')).not.toBeInTheDocument()
  })

  it('search box is wired to the server q param (debounced)', async () => {
    const fetchMock = installFetch()
    renderPanel()
    await screen.findByRole('button', { name: 'All (3)' })

    fireEvent.change(screen.getByRole('searchbox', { name: /search items/i }), {
      target: { value: 'card' },
    })

    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((call) => String(call[0]))
      expect(calls.some((url) => url.includes('/items') && url.includes('q=card'))).toBe(true)
    })
    // The server-filtered set leaves only the matching item.
    expect(await screen.findByText('Why was my card charged twice?')).toBeInTheDocument()
    expect(screen.queryByText('benchmark query 2')).not.toBeInTheDocument()
  })

  it('index sort orders by item index', async () => {
    renderPanel()
    fireEvent.click(await screen.findByRole('button', { name: 'All (3)' }))
    fireEvent.change(screen.getByRole('combobox', { name: /sort/i }), {
      target: { value: 'index' },
    })

    await waitFor(() => {
      const rows = screen.getAllByRole('row').slice(1)
      expect(rows[0]).toHaveTextContent('How do I reset my password?')
      expect(rows[2]).toHaveTextContent('benchmark query 2')
    })
  })
})
