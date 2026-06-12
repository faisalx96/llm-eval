import './testPolyfills'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Pencil, Trash2 } from 'lucide-react'
import { DropdownMenu, DropdownMenuItem, DropdownMenuSeparator } from './DropdownMenu'

// The shared vitest setup has no auto-cleanup (globals disabled).
afterEach(cleanup)

function renderMenu(onRename = vi.fn(), onDelete = vi.fn()) {
  render(
    <DropdownMenu trigger={<button aria-label="Run actions">⋮</button>}>
      <DropdownMenuItem icon={<Pencil />} onSelect={onRename}>
        Rename run
      </DropdownMenuItem>
      <DropdownMenuSeparator />
      <DropdownMenuItem icon={<Trash2 />} danger onSelect={onDelete}>
        Delete run
      </DropdownMenuItem>
    </DropdownMenu>,
  )
  return screen.getByRole('button', { name: 'Run actions' })
}

async function openMenu(trigger: HTMLElement) {
  fireEvent.keyDown(trigger, { key: 'Enter' })
  return await screen.findByRole('menu')
}

describe('DropdownMenu', () => {
  it('exposes menu semantics on the trigger (a11y)', async () => {
    const trigger = renderMenu()
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu')
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    await openMenu(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
  })

  it('opens with the keyboard and lists menu items', async () => {
    const trigger = renderMenu()
    await openMenu(trigger)
    const items = screen.getAllByRole('menuitem')
    expect(items.map((item) => item.textContent)).toEqual(['Rename run', 'Delete run'])
  })

  it('invokes onSelect when an item is activated and closes the menu', async () => {
    const onRename = vi.fn()
    const trigger = renderMenu(onRename)
    await openMenu(trigger)
    fireEvent.click(screen.getByRole('menuitem', { name: 'Rename run' }))
    expect(onRename).toHaveBeenCalledTimes(1)
    await waitFor(() => {
      expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    })
  })

  it('styles destructive items with the danger class', async () => {
    const trigger = renderMenu()
    await openMenu(trigger)
    expect(screen.getByRole('menuitem', { name: 'Delete run' }).className).toContain('danger')
    expect(screen.getByRole('menuitem', { name: 'Rename run' }).className).not.toContain('danger')
  })

  it('renders separators between item groups', async () => {
    const trigger = renderMenu()
    const menu = await openMenu(trigger)
    expect(menu.querySelector('[role="separator"]')).not.toBeNull()
  })

  it('closes on Escape and returns focus to the trigger (a11y)', async () => {
    const trigger = renderMenu()
    const menu = await openMenu(trigger)
    fireEvent.keyDown(menu, { key: 'Escape' })
    await waitFor(() => {
      expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    })
    await waitFor(() => {
      expect(trigger).toHaveFocus()
    })
  })
})
