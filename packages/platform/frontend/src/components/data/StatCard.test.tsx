import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { StatCard } from './StatCard'

// vitest runs with globals off, so RTL cannot auto-register cleanup.
afterEach(cleanup)

describe('StatCard', () => {
  it('renders label, value and sub', () => {
    render(<StatCard label="Pass rate" value="94.2%" sub="last 7 days" />)
    expect(screen.getByText('Pass rate')).toBeInTheDocument()
    expect(screen.getByText('94.2%')).toBeInTheDocument()
    expect(screen.getByText('last 7 days')).toBeInTheDocument()
  })

  it('is a non-interactive div without onClick', () => {
    render(<StatCard label="Runs" value={12} />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('renders as a real button when clickable and fires onClick', () => {
    const onClick = vi.fn()
    render(<StatCard label="Failures" value={3} onClick={onClick} />)
    const button = screen.getByRole('button', { name: /failures/i })
    expect(button).toHaveAttribute('type', 'button')
    fireEvent.click(button)
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('omits sub when not provided', () => {
    const { container } = render(<StatCard label="Runs" value={12} />)
    // label + value only
    expect(container.querySelectorAll('span')).toHaveLength(2)
  })
})
