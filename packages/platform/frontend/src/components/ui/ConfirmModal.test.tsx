import { useState } from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ConfirmModal } from './ConfirmModal'
import type { ConfirmModalProps } from './ConfirmModal'

// The shared vitest setup has no auto-cleanup (globals disabled).
afterEach(cleanup)

function Harness(props: Partial<ConfirmModalProps>) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button onClick={() => setOpen(true)}>open modal</button>
      <ConfirmModal
        open={open}
        onOpenChange={setOpen}
        title="Delete run"
        itemLabel="run-2026-06-11-a"
        confirmLabel="Delete run"
        onConfirm={() => {}}
        {...props}
      >
        This permanently removes all results.
      </ConfirmModal>
    </>
  )
}

describe('ConfirmModal', () => {
  it('shows title, explicit item label, and body', () => {
    render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: 'open modal' }))
    const dialog = screen.getByRole('dialog', { name: 'Delete run' })
    expect(dialog).toHaveTextContent('run-2026-06-11-a')
    expect(dialog).toHaveTextContent('This permanently removes all results.')
  })

  it('traps focus inside on open and returns it to the trigger on close (a11y)', async () => {
    render(<Harness />)
    const trigger = screen.getByRole('button', { name: 'open modal' })
    // jsdom clicks do not move focus; focus explicitly as a real user would.
    trigger.focus()
    fireEvent.click(trigger)
    const dialog = screen.getByRole('dialog')
    await waitFor(() => {
      expect(dialog.contains(document.activeElement)).toBe(true)
    })
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
    await waitFor(() => {
      expect(trigger).toHaveFocus()
    })
  })

  it('closes on Escape', async () => {
    render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: 'open modal' }))
    const dialog = screen.getByRole('dialog')
    fireEvent.keyDown(dialog, { key: 'Escape' })
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
  })

  it('calls onConfirm and closes on confirm', async () => {
    const onConfirm = vi.fn()
    render(<Harness onConfirm={onConfirm} />)
    fireEvent.click(screen.getByRole('button', { name: 'open modal' }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete run' }))
    expect(onConfirm).toHaveBeenCalledWith({})
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
  })

  it('disables confirm until the typeToConfirm text matches exactly', () => {
    const onConfirm = vi.fn()
    render(<Harness onConfirm={onConfirm} typeToConfirm="support-copilot" />)
    fireEvent.click(screen.getByRole('button', { name: 'open modal' }))
    const confirm = screen.getByRole('button', { name: 'Delete run' })
    expect(confirm).toBeDisabled()

    const input = screen.getByLabelText(/to confirm/)
    fireEvent.change(input, { target: { value: 'support' } })
    expect(confirm).toBeDisabled()

    fireEvent.change(input, { target: { value: 'support-copilot' } })
    expect(confirm).toBeEnabled()
    fireEvent.click(confirm)
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })

  it('requires a non-empty comment and passes it to onConfirm', () => {
    const onConfirm = vi.fn()
    render(
      <Harness
        onConfirm={onConfirm}
        requireComment={{ label: 'Reason for rejection', placeholder: 'Explain why…' }}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'open modal' }))
    const confirm = screen.getByRole('button', { name: 'Delete run' })
    expect(confirm).toBeDisabled()

    const textarea = screen.getByLabelText('Reason for rejection')
    fireEvent.change(textarea, { target: { value: '   ' } })
    expect(confirm).toBeDisabled()

    fireEvent.change(textarea, { target: { value: 'Scores look fabricated' } })
    expect(confirm).toBeEnabled()
    fireEvent.click(confirm)
    expect(onConfirm).toHaveBeenCalledWith({ comment: 'Scores look fabricated' })
  })

  it('resets inputs after closing', async () => {
    render(<Harness typeToConfirm="text2sql" />)
    fireEvent.click(screen.getByRole('button', { name: 'open modal' }))
    fireEvent.change(screen.getByLabelText(/to confirm/), { target: { value: 'text2sql' } })
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: 'open modal' }))
    expect(screen.getByLabelText(/to confirm/)).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Delete run' })).toBeDisabled()
  })
})
