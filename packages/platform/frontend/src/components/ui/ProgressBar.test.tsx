import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { ProgressBar } from './ProgressBar'

// The shared vitest setup has no auto-cleanup (globals disabled).
afterEach(cleanup)

describe('ProgressBar', () => {
  it('exposes progressbar semantics with value attributes (a11y)', () => {
    render(<ProgressBar value={4} max={12} aria-label="Tasks complete" />)
    const bar = screen.getByRole('progressbar', { name: 'Tasks complete' })
    expect(bar).toHaveAttribute('aria-valuemin', '0')
    expect(bar).toHaveAttribute('aria-valuemax', '12')
    expect(bar).toHaveAttribute('aria-valuenow', '4')
  })

  it('uses a string label as the accessible name', () => {
    render(<ProgressBar value={50} label="Ingest progress" />)
    expect(screen.getByRole('progressbar', { name: 'Ingest progress' })).toBeInTheDocument()
    expect(screen.getByText('Ingest progress')).toBeInTheDocument()
  })

  it('clamps out-of-range values', () => {
    render(<ProgressBar value={150} aria-label="Overflow" />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
  })

  it('clamps negative values to zero', () => {
    render(<ProgressBar value={-5} aria-label="Underflow" />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '0')
  })

  it('applies the neutral variant class', () => {
    render(<ProgressBar value={30} variant="neutral" aria-label="Storage used" />)
    expect(screen.getByRole('progressbar').className).toContain('neutral')
  })
})
