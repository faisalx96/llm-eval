import '@/components/ui/testPolyfills'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FailedBanner, GovernanceBanner } from './GovernanceBanner'
import { makeApproval, makeMe, makeRun, OWNER, REVIEWER } from './__fixtures__/runDetail'

function renderBanner(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('GovernanceBanner', () => {
  it('REJECTED: red banner with reviewer, date, comment — and Resubmit for the owner', () => {
    const run = makeRun({
      status: 'REJECTED',
      approval: makeApproval({
        status: 'REJECTED',
        decided_by: REVIEWER,
        decided_at: '2026-06-11T07:47:50Z',
        comment: 'Pass rate too low on hard tickets, investigate retrieval',
      }),
    })
    renderBanner(
      <GovernanceBanner slug="support-copilot" run={run} runName="my run" me={makeMe()} />,
    )

    expect(screen.getByText(/rejected by renata reviewer on jun 11, 2026/i)).toBeInTheDocument()
    expect(
      screen.getByText(/pass rate too low on hard tickets, investigate retrieval/i),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Resubmit' })).toBeInTheDocument()
  })

  it('REJECTED: hides Resubmit from non-owners', () => {
    const run = makeRun({
      status: 'REJECTED',
      approval: makeApproval({ status: 'REJECTED', decided_by: REVIEWER }),
    })
    renderBanner(
      <GovernanceBanner
        slug="support-copilot"
        run={run}
        runName="my run"
        me={makeMe({ id: 'someone-else' })}
      />,
    )
    expect(screen.queryByRole('button', { name: 'Resubmit' })).not.toBeInTheDocument()
  })

  it('APPROVED: subtle banner with reviewer, date and comment, no actions', () => {
    const run = makeRun({
      status: 'APPROVED',
      approval: makeApproval({
        status: 'APPROVED',
        decided_by: REVIEWER,
        decided_at: '2026-06-11T00:00:00Z',
        comment: 'Clear win, ship it',
      }),
    })
    renderBanner(
      <GovernanceBanner slug="support-copilot" run={run} runName="my run" me={makeMe()} />,
    )
    expect(screen.getByText(/approved by renata reviewer on jun 11, 2026/i)).toBeInTheDocument()
    expect(screen.getByText(/clear win, ship it/i)).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('SUBMITTED: awaiting review with Approve/Reject for project managers', () => {
    const run = makeRun({ status: 'SUBMITTED', approval: makeApproval() })
    renderBanner(
      <GovernanceBanner
        slug="support-copilot"
        run={run}
        runName="my run"
        me={makeMe({ projectRole: 'MANAGER' })}
      />,
    )
    expect(screen.getByText('Awaiting review')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reject' })).toBeInTheDocument()
  })

  it('SUBMITTED: plain members see no decision buttons', () => {
    const run = makeRun({ status: 'SUBMITTED', approval: makeApproval() })
    renderBanner(
      <GovernanceBanner slug="support-copilot" run={run} runName="my run" me={makeMe()} />,
    )
    expect(screen.getByText('Awaiting review')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
  })

  it('SUBMITTED: Reject opens a confirm dialog that requires a comment', () => {
    const run = makeRun({ status: 'SUBMITTED', approval: makeApproval() })
    renderBanner(
      <GovernanceBanner
        slug="support-copilot"
        run={run}
        runName="my run"
        me={makeMe({ role: 'ADMIN' })}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    // Confirm stays disabled until a comment is typed.
    const confirm = screen.getByRole('button', { name: 'Reject run' })
    expect(confirm).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/why is this run rejected/i), {
      target: { value: 'needs another pass' },
    })
    expect(confirm).toBeEnabled()
  })

  it('renders nothing without approval context', () => {
    const { container } = renderBanner(
      <GovernanceBanner
        slug="support-copilot"
        run={makeRun({ approval: null })}
        runName="my run"
        me={makeMe()}
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })
})

describe('FailedBanner', () => {
  it('shows progress + first error line for FAILED runs only', () => {
    const failed = makeRun({
      status: 'FAILED',
      completed_items: 3,
      total_items: 3,
      run_metadata: { total_items: 10 },
      error_summary: { task_errors: 1, types: { 'CUDA out of memory': 1 } },
    })
    renderBanner(<FailedBanner run={failed} />)
    expect(
      screen.getByText('Failed after 3 of 10 items — CUDA out of memory'),
    ).toBeInTheDocument()

    const { container } = renderBanner(<FailedBanner run={makeRun()} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('OWNER fixture sanity: resubmit visibility keys off owner id', () => {
    expect(makeMe().id).toBe(OWNER.id)
  })
})
