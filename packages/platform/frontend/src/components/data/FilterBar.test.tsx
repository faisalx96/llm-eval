import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import {
  EMPTY_FILTER_STATE,
  FilterBar,
  type FacetConfig,
  type FilterBarState,
} from './FilterBar'
import { stubResizeObserver } from './testUtils'

beforeAll(() => {
  stubResizeObserver()
})

// vitest runs with globals off, so RTL cannot auto-register cleanup.
afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

const statusFacet: FacetConfig = {
  id: 'status',
  label: 'Status',
  options: [{ value: 'pass' }, { value: 'fail' }, { value: 'error', label: 'Errored' }],
}

const envFacet: FacetConfig = {
  id: 'env',
  label: 'Environment',
  options: [{ value: 'prod' }, { value: 'staging' }],
}

function Harness({
  spy,
  facets = [statusFacet, envFacet],
  initial = EMPTY_FILTER_STATE,
}: {
  spy?: (s: FilterBarState) => void
  facets?: FacetConfig[]
  initial?: FilterBarState
}) {
  const [state, setState] = useState<FilterBarState>(initial)
  return (
    <FilterBar
      value={state}
      onChange={(s) => {
        setState(s)
        spy?.(s)
      }}
      facets={facets}
    />
  )
}

describe('FilterBar', () => {
  it('debounces search input before emitting onChange', () => {
    vi.useFakeTimers()
    const onChange = vi.fn()
    render(<FilterBar value={EMPTY_FILTER_STATE} onChange={onChange} facets={[statusFacet]} />)

    fireEvent.change(screen.getByRole('searchbox', { name: 'Search' }), {
      target: { value: 'timeout' },
    })
    expect(onChange).not.toHaveBeenCalled()

    act(() => {
      vi.advanceTimersByTime(249)
    })
    expect(onChange).not.toHaveBeenCalled()

    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith({ q: 'timeout', facets: {}, time: 'all' })
  })

  it('resets the timer on every keystroke (single emit)', () => {
    vi.useFakeTimers()
    const onChange = vi.fn()
    render(<FilterBar value={EMPTY_FILTER_STATE} onChange={onChange} />)
    const input = screen.getByRole('searchbox', { name: 'Search' })

    fireEvent.change(input, { target: { value: 'a' } })
    act(() => {
      vi.advanceTimersByTime(200)
    })
    fireEvent.change(input, { target: { value: 'ab' } })
    act(() => {
      vi.advanceTimersByTime(200)
    })
    expect(onChange).not.toHaveBeenCalled()

    act(() => {
      vi.advanceTimersByTime(50)
    })
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange.mock.calls[0][0].q).toBe('ab')
  })

  it('adds a facet chip from the filter popover', () => {
    const spy = vi.fn()
    render(<Harness spy={spy} />)

    fireEvent.click(screen.getByRole('button', { name: /filter/i }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'pass' }))

    expect(spy).toHaveBeenCalledWith({ q: '', facets: { status: ['pass'] }, time: 'all' })
    expect(
      screen.getByRole('button', { name: 'Remove filter Status: pass' }),
    ).toBeInTheDocument()
  })

  it('uses option labels in chips when provided', () => {
    render(<Harness initial={{ q: '', facets: { status: ['error'] }, time: 'all' }} />)
    expect(
      screen.getByRole('button', { name: 'Remove filter Status: Errored' }),
    ).toBeInTheDocument()
  })

  it('removes a chip via its remove button', () => {
    const spy = vi.fn()
    render(
      <Harness spy={spy} initial={{ q: '', facets: { status: ['pass', 'fail'] }, time: 'all' }} />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Remove filter Status: pass' }))
    expect(spy).toHaveBeenCalledWith({ q: '', facets: { status: ['fail'] }, time: 'all' })
    expect(
      screen.queryByRole('button', { name: 'Remove filter Status: pass' }),
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Remove filter Status: fail' }),
    ).toBeInTheDocument()
  })

  it('shows Clear all only when facets are active, and clears them', () => {
    const spy = vi.fn()
    render(
      <Harness
        spy={spy}
        initial={{ q: '', facets: { status: ['pass'], env: ['prod'] }, time: 'all' }}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Clear all' }))
    expect(spy).toHaveBeenCalledWith({ q: '', facets: {}, time: 'all' })
    expect(screen.queryByRole('button', { name: 'Clear all' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /remove filter/i })).not.toBeInTheDocument()
  })

  it('hides Clear all when nothing is active', () => {
    render(<Harness />)
    expect(screen.queryByRole('button', { name: 'Clear all' })).not.toBeInTheDocument()
  })

  it('switches the time quick-toggle', () => {
    const spy = vi.fn()
    render(<Harness spy={spy} />)

    const seven = screen.getByRole('button', { name: '7d' })
    expect(seven).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(seven)
    expect(spy).toHaveBeenCalledWith({ q: '', facets: {}, time: '7d' })
    expect(screen.getByRole('button', { name: '7d' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'All' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('loads async facet options when the popover opens', async () => {
    const loadOptions = vi
      .fn()
      .mockResolvedValue([{ value: 'm1', label: 'Model one' }, { value: 'm2' }])
    render(<Harness facets={[{ id: 'model', label: 'Model', loadOptions }]} />)

    fireEvent.click(screen.getByRole('button', { name: /filter/i }))
    expect(loadOptions).toHaveBeenCalledTimes(1)
    expect(await screen.findByRole('checkbox', { name: 'Model one' })).toBeInTheDocument()

    // Re-opening does not refetch.
    fireEvent.click(screen.getByRole('button', { name: /filter/i }))
    fireEvent.click(screen.getByRole('button', { name: /filter/i }))
    expect(loadOptions).toHaveBeenCalledTimes(1)
  })

  it('closes the facet popover with Escape (keyboard dismiss)', () => {
    render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: /filter/i }))
    expect(screen.getByRole('checkbox', { name: 'pass' })).toBeInTheDocument()

    fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' })
    expect(screen.queryByRole('checkbox', { name: 'pass' })).not.toBeInTheDocument()
  })

  it('exposes every control as a native keyboard-operable element', () => {
    const { container } = render(
      <Harness initial={{ q: '', facets: { status: ['pass'] }, time: 'all' }} />,
    )
    // Search input, filter trigger, chip remove, clear all, 5 time segments —
    // all native <input>/<button>, hence focusable + keyboard operable.
    expect(screen.getByRole('searchbox', { name: 'Search' })).toBeInTheDocument()
    const buttons = container.querySelectorAll('button')
    expect(buttons.length).toBeGreaterThanOrEqual(8)
    for (const b of buttons) {
      expect(b).toHaveAttribute('type', 'button')
    }
  })
})
