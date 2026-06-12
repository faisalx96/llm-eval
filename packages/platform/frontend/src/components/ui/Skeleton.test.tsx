import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { Skeleton, SkeletonText } from './Skeleton'

// The shared vitest setup has no auto-cleanup (globals disabled).
afterEach(cleanup)

describe('Skeleton', () => {
  it('is hidden from assistive technology (a11y)', () => {
    render(<Skeleton width={120} height={16} />)
    expect(screen.getByTestId('skeleton')).toHaveAttribute('aria-hidden', 'true')
  })

  it('applies explicit dimensions', () => {
    render(<Skeleton width={120} height={16} />)
    const el = screen.getByTestId('skeleton')
    expect(el.style.width).toBe('120px')
    expect(el.style.height).toBe('16px')
  })
})

describe('SkeletonText', () => {
  it('renders the requested number of lines, all decorative', () => {
    render(<SkeletonText lines={4} />)
    const lines = screen.getAllByTestId('skeleton')
    expect(lines).toHaveLength(4)
    for (const line of lines) {
      expect(line).toHaveAttribute('aria-hidden', 'true')
    }
  })

  it('shortens the last line', () => {
    render(<SkeletonText lines={3} />)
    const lines = screen.getAllByTestId('skeleton')
    expect(lines[2].style.width).toBe('60%')
    expect(lines[0].style.width).toBe('100%')
  })
})
