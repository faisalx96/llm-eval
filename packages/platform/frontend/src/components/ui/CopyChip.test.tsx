import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CopyChip, middleEllipsis } from './CopyChip'

// The shared vitest setup has no auto-cleanup (globals disabled).
afterEach(cleanup)

const UUID = '7f3b9c2a-4e1d-4f6a-8b0c-2d9e5a7c1b3f'

const writeText = vi.fn().mockResolvedValue(undefined)

beforeEach(() => {
  writeText.mockClear()
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText },
    configurable: true,
  })
})

describe('middleEllipsis', () => {
  it('returns short values unchanged', () => {
    expect(middleEllipsis('abc123', 17)).toBe('abc123')
  })

  it('truncates the middle, keeping head and tail', () => {
    const result = middleEllipsis(UUID, 17)
    expect(result).toHaveLength(17)
    expect(result).toContain('…')
    expect(result.startsWith(UUID.slice(0, 8))).toBe(true)
    expect(result.endsWith(UUID.slice(-8))).toBe(true)
  })
})

describe('CopyChip', () => {
  it('shows the truncated value but copies the full value', async () => {
    render(<CopyChip value={UUID} />)
    const chip = screen.getByRole('button', { name: `Copy ${UUID}` })
    expect(chip).not.toHaveTextContent(UUID)
    expect(chip.textContent).toContain('…')
    fireEvent.click(chip)
    expect(writeText).toHaveBeenCalledWith(UUID)
    expect(await screen.findByText('Copied')).toBeInTheDocument()
  })

  it('exposes the full value in the accessible name and title (a11y)', () => {
    render(<CopyChip value={UUID} />)
    const chip = screen.getByRole('button', { name: `Copy ${UUID}` })
    expect(chip).toHaveAttribute('title', UUID)
  })

  it("announces 'Copied' via a status live region (a11y)", async () => {
    render(<CopyChip value={UUID} />)
    const status = screen.getByRole('status')
    expect(status).toHaveTextContent('')
    fireEvent.click(screen.getByRole('button', { name: `Copy ${UUID}` }))
    await screen.findByText('Copied')
    expect(status).toHaveTextContent('Copied')
  })

  it('respects a display override', () => {
    render(<CopyChip value={UUID} display="latest run" />)
    expect(screen.getByRole('button', { name: `Copy ${UUID}` })).toHaveTextContent('latest run')
  })
})
