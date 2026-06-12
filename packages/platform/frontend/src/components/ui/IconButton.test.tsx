import './testPolyfills'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Trash2 } from 'lucide-react'
import { IconButton } from './IconButton'

// The shared vitest setup has no auto-cleanup (globals disabled).
afterEach(cleanup)

describe('IconButton', () => {
  it('exposes the required aria-label as its accessible name', () => {
    render(<IconButton aria-label="Delete dataset" icon={<Trash2 />} />)
    expect(screen.getByRole('button', { name: 'Delete dataset' })).toBeInTheDocument()
  })

  it('fires onClick', () => {
    const onClick = vi.fn()
    render(<IconButton aria-label="Delete dataset" icon={<Trash2 />} onClick={onClick} />)
    fireEvent.click(screen.getByRole('button', { name: 'Delete dataset' }))
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('shows the built-in tooltip (defaulting to the aria-label) on keyboard focus', async () => {
    render(<IconButton aria-label="Delete dataset" icon={<Trash2 />} />)
    const button = screen.getByRole('button', { name: 'Delete dataset' })
    fireEvent.focus(button)
    const tooltip = await screen.findByRole('tooltip')
    expect(tooltip).toHaveTextContent('Delete dataset')
    // a11y: the trigger is described by the tooltip while open.
    expect(button).toHaveAttribute('aria-describedby', tooltip.id)
  })

  it('renders without a tooltip wrapper when tooltip is null', () => {
    render(<IconButton aria-label="Close" icon={<Trash2 />} tooltip={null} />)
    const button = screen.getByRole('button', { name: 'Close' })
    fireEvent.focus(button)
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })
})
