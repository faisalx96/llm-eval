import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { formatMetric, MetricDelta } from './MetricDelta'

// vitest runs with globals off, so RTL cannot auto-register cleanup.
afterEach(cleanup)

function deltaEl(container: HTMLElement): HTMLElement | null {
  return container.querySelector('[data-tone]')
}

describe('MetricDelta', () => {
  it('renders an improvement as a good (green) signed delta', () => {
    const { container } = render(<MetricDelta value={0.83} baseline={0.8} fmt="percent" />)
    expect(screen.getByText('83%')).toBeInTheDocument()
    const delta = deltaEl(container)
    expect(delta).toHaveAttribute('data-tone', 'good')
    expect(delta).toHaveTextContent('+3%')
  })

  it('renders a regression as a bad (red) signed delta', () => {
    const { container } = render(<MetricDelta value={0.7} baseline={0.8} fmt="percent" />)
    const delta = deltaEl(container)
    expect(delta).toHaveAttribute('data-tone', 'bad')
    expect(delta).toHaveTextContent('−10%')
  })

  it('inverts goodness when higherIsBetter is false (latency)', () => {
    const { container } = render(
      <MetricDelta value={120} baseline={100} higherIsBetter={false} fmt="ms" />,
    )
    // Latency went UP — that is bad, even though the delta is positive.
    const delta = deltaEl(container)
    expect(delta).toHaveAttribute('data-tone', 'bad')
    expect(delta).toHaveTextContent('+20ms')

    const { container: faster } = render(
      <MetricDelta value={80} baseline={100} higherIsBetter={false} fmt="ms" />,
    )
    expect(deltaEl(faster)).toHaveAttribute('data-tone', 'good')
    expect(deltaEl(faster)).toHaveTextContent('−20ms')
  })

  it('renders no delta at all without a baseline', () => {
    const { container } = render(<MetricDelta value={42} />)
    expect(screen.getByText('42')).toBeInTheDocument()
    expect(deltaEl(container)).toBeNull()
  })

  it('is neutral on zero delta', () => {
    const { container } = render(<MetricDelta value={0.5} baseline={0.5} fmt="percent" />)
    const delta = deltaEl(container)
    expect(delta).toHaveAttribute('data-tone', 'neutral')
    expect(delta).toHaveTextContent('±0%')
    // No direction arrow when nothing moved.
    expect(delta?.querySelector('svg')).toBeNull()
  })

  it('never paints a background (text + arrow only)', () => {
    const { container } = render(<MetricDelta value={0.9} baseline={0.1} fmt="percent" />)
    const delta = deltaEl(container)!
    expect(delta.style.background).toBe('')
    expect(delta.style.backgroundColor).toBe('')
  })

  it('supports a custom format function', () => {
    render(
      <MetricDelta value={1500} baseline={1000} fmt={(v) => `$${v.toFixed(0)}`} />,
    )
    expect(screen.getByText('$1500')).toBeInTheDocument()
    expect(screen.getByText(/\+\$500/)).toBeInTheDocument()
  })
})

describe('formatMetric', () => {
  it('formats percent from a 0-1 ratio', () => {
    expect(formatMetric(0.831, 'percent')).toBe('83.1%')
    expect(formatMetric(1, 'percent')).toBe('100%')
    expect(formatMetric(0, 'percent')).toBe('0%')
  })

  it('formats milliseconds with sensible precision', () => {
    expect(formatMetric(3.21, 'ms')).toBe('3.2ms')
    expect(formatMetric(245, 'ms')).toBe('245ms')
    expect(formatMetric(1240, 'ms')).toBe('1.24s')
  })

  it('formats plain numbers with grouping above 1000', () => {
    expect(formatMetric(0.5, 'number')).toBe('0.5')
    expect(formatMetric(12, 'number')).toBe('12')
    expect(formatMetric(12345, 'number')).toBe('12,345')
  })
})
