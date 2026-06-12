import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { STATUSES, STATUS_HUES, StatusBadge, resolveStatusHue } from './StatusBadge'

// The shared vitest setup has no auto-cleanup (globals disabled).
afterEach(cleanup)

describe('StatusBadge', () => {
  it('renders the status text', () => {
    render(<StatusBadge status="PENDING" />)
    expect(screen.getByText('PENDING')).toBeInTheDocument()
  })

  it("renders progress as 'RUNNING · 33% · 4/12'", () => {
    const { container } = render(
      <StatusBadge status="RUNNING" progress={{ pct: 33, done: 4, total: 12 }} />,
    )
    expect(container.firstElementChild).toHaveTextContent('RUNNING · 33% · 4/12')
  })

  it('marks the running pulse dot as decorative (a11y)', () => {
    const { container } = render(<StatusBadge status="RUNNING" />)
    const dot = container.querySelector('[aria-hidden="true"]')
    expect(dot).not.toBeNull()
  })

  it('shows a decorative icon for FAILED', () => {
    const { container } = render(<StatusBadge status="FAILED" />)
    const icon = container.querySelector('svg')
    expect(icon).not.toBeNull()
    expect(icon).toHaveAttribute('aria-hidden', 'true')
    // The accessible text is still just the status word.
    expect(container.firstElementChild).toHaveTextContent('FAILED')
  })

  it('applies the hero size class without changing hue class', () => {
    const { container } = render(<StatusBadge status="APPROVED" size="md" />)
    const badge = container.firstElementChild as HTMLElement
    expect(badge.className).toContain('md')
    expect(badge.className).toContain('approved')
  })
})

describe('STATUS_HUES contract', () => {
  it('covers every status', () => {
    for (const status of STATUSES) {
      expect(STATUS_HUES[status]).toMatch(/^var\(--[\w-]+\)$/)
    }
  })

  it('reserves red for fail outcomes and green for pass outcomes only', () => {
    expect(STATUS_HUES.FAILED).toBe('var(--error)')
    expect(STATUS_HUES.REJECTED).toBe('var(--error)')
    expect(STATUS_HUES.APPROVED).toBe('var(--success)')
    const redOrGreen = Object.entries(STATUS_HUES).filter(([, hue]) =>
      ['var(--error)', 'var(--success)'].includes(hue),
    )
    expect(redOrGreen.map(([status]) => status).sort()).toEqual([
      'APPROVED',
      'FAILED',
      'REJECTED',
    ])
  })

  it('uses blue for in-flight and amber for needs-attention', () => {
    expect(STATUS_HUES.RUNNING).toBe('var(--info)')
    expect(STATUS_HUES.SUBMITTED).toBe('var(--warning)')
  })

  it('resolveStatusHue falls back to the var() expression when unresolvable', () => {
    // jsdom does not resolve custom properties → fallback path.
    expect(resolveStatusHue('FAILED')).toBe('var(--error)')
  })
})
