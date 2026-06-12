import './testPolyfills'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Inbox } from 'lucide-react'
import { Button } from './Button'
import { EmptyState } from './EmptyState'

// The shared vitest setup has no auto-cleanup (globals disabled).
afterEach(cleanup)

const writeText = vi.fn().mockResolvedValue(undefined)

beforeEach(() => {
  writeText.mockClear()
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText },
    configurable: true,
  })
})

describe('EmptyState', () => {
  it('renders title and description with a decorative icon', () => {
    const { container } = render(
      <EmptyState
        icon={<Inbox />}
        title="No runs yet"
        description="Kick off your first evaluation run to see results here."
      />,
    )
    expect(screen.getByRole('heading', { name: 'No runs yet' })).toBeInTheDocument()
    expect(screen.getByText(/first evaluation run/)).toBeInTheDocument()
    const icon = container.querySelector('[aria-hidden="true"]')
    expect(icon).not.toBeNull()
  })

  it('renders the primary action', () => {
    const onClick = vi.fn()
    render(
      <EmptyState
        title="No runs yet"
        action={<Button onClick={onClick}>Create run</Button>}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Create run' }))
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('shows the code snippet with a working copy button announcing Copied (a11y)', async () => {
    render(<EmptyState title="No runs yet" code="qym run --project sandbox" />)
    expect(screen.getByText('qym run --project sandbox')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Copy snippet' }))
    expect(writeText).toHaveBeenCalledWith('qym run --project sandbox')
    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent('Copied')
  })

  it('renders a safe external docs link', () => {
    render(
      <EmptyState title="No runs yet" docsHref="https://docs.example.com/runs" docsLabel="Read the runs guide" />,
    )
    const link = screen.getByRole('link', { name: /Read the runs guide/ })
    expect(link).toHaveAttribute('href', 'https://docs.example.com/runs')
    expect(link).toHaveAttribute('rel', 'noreferrer')
  })
})
