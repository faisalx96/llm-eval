import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { Toaster, dismissAllToasts, toast } from './Toast'

afterEach(() => {
  act(() => {
    dismissAllToasts()
  })
  // The shared vitest setup has no auto-cleanup (globals disabled).
  cleanup()
})

/** The visible toast element (Radix also mounts a transient hidden announcer). */
function visibleToast(title: string): HTMLElement {
  const li = screen.getByText(title).closest('li')
  if (!li) throw new Error(`No toast <li> found for "${title}"`)
  return li
}

describe('Toast', () => {
  it('exposes the toast as a status live region (a11y)', () => {
    render(<Toaster />)
    act(() => {
      toast({ title: 'Run started', variant: 'info' })
    })
    const el = visibleToast('Run started')
    expect(el).toHaveAttribute('role', 'status')
    expect(el).toHaveTextContent('Run started')
  })

  it('renders title and description with the variant class', () => {
    render(<Toaster />)
    act(() => {
      toast({ title: 'Export failed', description: 'Disk quota exceeded', variant: 'error' })
    })
    const el = visibleToast('Export failed')
    expect(el).toHaveTextContent('Disk quota exceeded')
    expect(el.className).toContain('error')
  })

  it('dismisses via the labelled close button', async () => {
    render(<Toaster />)
    act(() => {
      toast({ title: 'Saved', variant: 'success' })
    })
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss notification' }))
    await waitFor(() => {
      expect(screen.queryByText('Saved')).not.toBeInTheDocument()
    })
  })

  it('auto-dismisses after its duration', async () => {
    render(<Toaster />)
    act(() => {
      toast({ title: 'Ephemeral', duration: 30 })
    })
    expect(visibleToast('Ephemeral')).toBeInTheDocument()
    await waitFor(
      () => {
        expect(screen.queryByText('Ephemeral')).not.toBeInTheDocument()
      },
      { timeout: 3000 },
    )
  })

  it('stacks multiple toasts', () => {
    render(<Toaster />)
    act(() => {
      toast({ title: 'First' })
      toast({ title: 'Second' })
    })
    expect(visibleToast('First')).toBeInTheDocument()
    expect(visibleToast('Second')).toBeInTheDocument()
  })
})
