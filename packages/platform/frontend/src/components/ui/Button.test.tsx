import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Plus } from 'lucide-react'
import { Button } from './Button'

// The shared vitest setup has no auto-cleanup (globals disabled).
afterEach(cleanup)

describe('Button', () => {
  it('fires onClick and defaults to type="button"', () => {
    const onClick = vi.fn()
    render(<Button onClick={onClick}>Create run</Button>)
    const button = screen.getByRole('button', { name: 'Create run' })
    expect(button).toHaveAttribute('type', 'button')
    fireEvent.click(button)
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('applies variant and size classes', () => {
    render(
      <Button variant="danger" size="sm">
        Delete run
      </Button>,
    )
    const button = screen.getByRole('button', { name: 'Delete run' })
    expect(button.className).toContain('danger')
    expect(button.className).toContain('sm')
  })

  it('loading state disables the button, sets aria-busy, and shows a spinner', () => {
    const onClick = vi.fn()
    render(
      <Button loading onClick={onClick}>
        Saving
      </Button>,
    )
    const button = screen.getByRole('button', { name: 'Saving' })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('aria-busy', 'true')
    expect(screen.getByTestId('button-spinner')).toHaveAttribute('aria-hidden', 'true')
    fireEvent.click(button)
    expect(onClick).not.toHaveBeenCalled()
  })

  it('renders the icon slot as decorative so only the label is announced', () => {
    render(<Button icon={<Plus />}>Add dataset</Button>)
    const button = screen.getByRole('button', { name: 'Add dataset' })
    const iconWrap = button.querySelector('[aria-hidden="true"]')
    expect(iconWrap).not.toBeNull()
  })

  it('is keyboard focusable', () => {
    render(<Button>Focus me</Button>)
    const button = screen.getByRole('button', { name: 'Focus me' })
    button.focus()
    expect(button).toHaveFocus()
  })
})
