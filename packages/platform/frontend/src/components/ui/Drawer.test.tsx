import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Drawer } from './Drawer'

// The shared vitest setup has no auto-cleanup (globals disabled).
afterEach(cleanup)

describe('Drawer', () => {
  it('renders a dialog labelled by its title (a11y)', () => {
    render(
      <Drawer open onOpenChange={() => {}} title="Result detail">
        <p>Body content</p>
      </Drawer>,
    )
    const dialog = screen.getByRole('dialog', { name: 'Result detail' })
    expect(dialog).toHaveTextContent('Body content')
  })

  it('applies the size class', () => {
    render(
      <Drawer open onOpenChange={() => {}} title="Wide drawer" size="lg">
        <p>Body</p>
      </Drawer>,
    )
    expect(screen.getByRole('dialog').className).toContain('lg')
  })

  it('closes via the labelled close button', () => {
    const onOpenChange = vi.fn()
    render(
      <Drawer open onOpenChange={onOpenChange} title="Result detail">
        <p>Body</p>
      </Drawer>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it('closes on Escape (a11y)', () => {
    const onOpenChange = vi.fn()
    render(
      <Drawer open onOpenChange={onOpenChange} title="Result detail">
        <p>Body</p>
      </Drawer>,
    )
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it('moves focus into the drawer when opened (a11y)', async () => {
    render(
      <Drawer open onOpenChange={() => {}} title="Result detail">
        <button>Inside action</button>
      </Drawer>,
    )
    const dialog = screen.getByRole('dialog')
    await waitFor(() => {
      expect(dialog.contains(document.activeElement)).toBe(true)
    })
  })

  it('announces the optional description', () => {
    render(
      <Drawer
        open
        onOpenChange={() => {}}
        title="Result detail"
        description="Full trace for this result"
      >
        <p>Body</p>
      </Drawer>,
    )
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAccessibleDescription('Full trace for this result')
  })
})
