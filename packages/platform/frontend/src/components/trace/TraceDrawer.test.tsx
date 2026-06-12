import '@/components/ui/testPolyfills'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { TraceData } from '@/lib/trace'
import traceOkRaw from '@/lib/trace/__fixtures__/trace-item-ok.json?raw'
import traceErrorRaw from '@/lib/trace/__fixtures__/trace-item-error.json?raw'
import { TraceDrawer } from './TraceDrawer'

const okTrace = JSON.parse(traceOkRaw) as TraceData
const errTrace = JSON.parse(traceErrorRaw) as TraceData

const RUN_ID = 'f42571bf-99ba-4224-b5b3-33c061e197ac'
const ITEM_ID = 'csv_398751a709b0a447b0b3__0001'
const ROOT_NAME = 'eval-support-rag-claude-sonnet-4-6-claude-sonnet-4-6-260611-1043-item-0-attempt-1'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderDrawer(props: Partial<Parameters<typeof TraceDrawer>[0]> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <TraceDrawer
        runId={RUN_ID}
        itemId={ITEM_ID}
        open
        onOpenChange={() => {}}
        {...props}
      />
    </QueryClientProvider>,
  )
}

const fetchMock = vi.fn()

beforeEach(() => {
  fetchMock.mockReset()
  fetchMock.mockImplementation(async () => jsonResponse(okTrace))
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('TraceDrawer', () => {
  it('fetches the trace endpoint only while open', async () => {
    const { rerender } = renderDrawer({ open: false })
    expect(fetchMock).not.toHaveBeenCalled()

    rerender(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <TraceDrawer runId={RUN_ID} itemId={ITEM_ID} open onOpenChange={() => {}} />
      </QueryClientProvider>,
    )
    await screen.findByRole('tree', { name: 'Trace spans' })
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/runs/${RUN_ID}/items/${ITEM_ID}/trace`,
      expect.anything(),
    )
  })

  it('renders the span tree fully expanded with the root selected', async () => {
    renderDrawer()
    const tree = await screen.findByRole('tree', { name: 'Trace spans' })
    const rows = within(tree).getAllByRole('treeitem')
    expect(rows).toHaveLength(3)
    expect(rows[0]).toHaveAccessibleName(expect.stringContaining(ROOT_NAME))
    expect(rows[0]).toHaveAttribute('aria-selected', 'true')
    expect(rows[0]).toHaveAttribute('aria-expanded', 'true')
    expect(rows[0]).toHaveAttribute('aria-level', '1')
    expect(rows[1]).toHaveAttribute('aria-level', '2')
    // leaf rows have no aria-expanded
    expect(rows[1]).not.toHaveAttribute('aria-expanded')
    // durations rendered via fmtMs
    expect(within(rows[0]).getByText('262ms')).toBeInTheDocument()
  })

  it('shows summary chips: span count, duration, scores and trace id', async () => {
    renderDrawer()
    await screen.findByRole('tree', { name: 'Trace spans' })
    expect(screen.getByText('3 spans')).toBeInTheDocument()
    // duration appears in the summary chip AND as the root row duration
    expect(screen.getAllByText('262ms').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('exact_match')).toBeInTheDocument()
    expect(screen.getAllByText('1.00')).toHaveLength(3)
    expect(
      screen.getByRole('button', { name: `Copy ${okTrace.item?.trace_id ?? ''}` }),
    ).toBeInTheDocument()
  })

  it('uses the title prop, falling back to the item id', async () => {
    renderDrawer({ title: 'support-rag run' })
    expect(await screen.findByText('support-rag run')).toBeInTheDocument()
    cleanup()
    renderDrawer()
    expect(await screen.findByText(ITEM_ID)).toBeInTheDocument()
  })

  it('shows the selected span in the detail pane with Input / output tab', async () => {
    renderDrawer()
    await screen.findByRole('tree', { name: 'Trace spans' })
    const detail = screen.getByLabelText('Span details')
    expect(within(detail).getByText(ROOT_NAME)).toBeInTheDocument()
    expect(within(detail).getByRole('tab', { name: 'Input / output' })).toBeInTheDocument()
    // input.value is a JSON-encoded string — shown unwrapped
    expect(within(detail).getByText('How do I reset my password?')).toBeInTheDocument()
    expect(
      within(detail).getByText('Go to Settings > Security and click Reset Password. A reset link is emailed to you.'),
    ).toBeInTheDocument()
  })

  it('switches detail tabs to Attributes (key-value) and Raw (JSON)', async () => {
    renderDrawer()
    await screen.findByRole('tree', { name: 'Trace spans' })
    const detail = screen.getByLabelText('Span details')

    // Radix Tabs activate on mousedown (see Tabs.test.tsx)
    const attrsTab = within(detail).getByRole('tab', { name: /Attributes/ })
    fireEvent.mouseDown(attrsTab)
    fireEvent.click(attrsTab)
    expect(await within(detail).findByText('openinference.span.kind')).toBeInTheDocument()
    expect(within(detail).getByText('CHAIN')).toBeInTheDocument()

    const rawTab = within(detail).getByRole('tab', { name: 'Raw' })
    fireEvent.mouseDown(rawTab)
    fireEvent.click(rawTab)
    expect(await within(detail).findByText('Span JSON')).toBeInTheDocument()
  })

  it('selects spans by click and updates the detail pane', async () => {
    renderDrawer()
    const tree = await screen.findByRole('tree', { name: 'Trace spans' })
    fireEvent.click(within(tree).getByRole('treeitem', { name: /support_task/ }))
    const detail = screen.getByLabelText('Span details')
    await waitFor(() => {
      expect(within(detail).getByText('support_task')).toBeInTheDocument()
    })
    expect(within(detail).getByText('Agent')).toBeInTheDocument()
  })

  it('keyboard: arrows move selection / collapse / expand, Enter focuses detail', async () => {
    renderDrawer()
    const tree = await screen.findByRole('tree', { name: 'Trace spans' })

    fireEvent.keyDown(tree, { key: 'ArrowDown' })
    await waitFor(() => {
      expect(within(tree).getByRole('treeitem', { name: /support_task/ })).toHaveAttribute(
        'aria-selected',
        'true',
      )
    })

    fireEvent.keyDown(tree, { key: 'ArrowUp' })
    await waitFor(() => {
      expect(within(tree).getAllByRole('treeitem')[0]).toHaveAttribute('aria-selected', 'true')
    })

    // Left collapses the expanded root → only one visible row.
    fireEvent.keyDown(tree, { key: 'ArrowLeft' })
    await waitFor(() => {
      expect(within(tree).getAllByRole('treeitem')).toHaveLength(1)
    })

    // Right expands it again.
    fireEvent.keyDown(tree, { key: 'ArrowRight' })
    await waitFor(() => {
      expect(within(tree).getAllByRole('treeitem')).toHaveLength(3)
    })

    fireEvent.keyDown(tree, { key: 'Enter' })
    expect(screen.getByLabelText('Span details')).toHaveFocus()
  })

  it('renders error traces: error chip, red rows, error box and attempts', async () => {
    fetchMock.mockImplementation(async () => jsonResponse(errTrace))
    renderDrawer({ itemId: 'csv_5c1d637f351eac9ca02e__0001' })
    const tree = await screen.findByRole('tree', { name: 'Trace spans' })

    // summary error chip (status fallback when spans carry no exception event)
    expect(screen.getByText('1 error')).toBeInTheDocument()
    // error badges on rows
    expect(within(tree).getAllByLabelText('Error').length).toBeGreaterThan(0)

    // detail error box falls back to the attempt error
    const detail = screen.getByLabelText('Span details')
    expect(within(detail).getByRole('alert')).toHaveTextContent('attempt 3/3')

    // attempt switcher present; switching shows attempt 1's error
    const attempt1 = screen.getByRole('button', { name: /Attempt 1/ })
    fireEvent.click(attempt1)
    await waitFor(() => {
      expect(within(screen.getByLabelText('Span details')).getByRole('alert')).toHaveTextContent(
        'attempt 1/3',
      )
    })
  })

  it('shows the empty state when no spans were recorded', async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse({ item: { trace_id: '' }, summary: { span_count: 0 }, spans: [], attempts: [] }),
    )
    renderDrawer()
    expect(await screen.findByText('No spans recorded')).toBeInTheDocument()
  })

  it('shows the error state with a retry action on request failure', async () => {
    fetchMock.mockImplementation(async () => jsonResponse({ detail: 'trace not found' }, 404))
    renderDrawer()
    expect(await screen.findByText('Failed to load trace')).toBeInTheDocument()
    expect(screen.getByText('trace not found')).toBeInTheDocument()

    fetchMock.mockImplementation(async () => jsonResponse(okTrace))
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('tree', { name: 'Trace spans' })).toBeInTheDocument()
  })
})
