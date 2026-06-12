import './testPolyfills'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { Tooltip } from './Tooltip'

// The shared vitest setup has no auto-cleanup (globals disabled).
afterEach(cleanup)

describe('Tooltip', () => {
  it('is hidden until triggered', () => {
    render(
      <Tooltip content="Stops the run">
        <button>Stop</button>
      </Tooltip>,
    )
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('opens on keyboard focus and links via aria-describedby (a11y)', async () => {
    render(
      <Tooltip content="Stops the run">
        <button>Stop</button>
      </Tooltip>,
    )
    const trigger = screen.getByRole('button', { name: 'Stop' })
    fireEvent.focus(trigger)
    const tooltip = await screen.findByRole('tooltip')
    expect(tooltip).toHaveTextContent('Stops the run')
    expect(trigger).toHaveAttribute('aria-describedby', tooltip.id)
  })

  it('renders content when defaultOpen', () => {
    render(
      <Tooltip content="Pre-opened" defaultOpen>
        <button>Trigger</button>
      </Tooltip>,
    )
    expect(screen.getByRole('tooltip')).toHaveTextContent('Pre-opened')
  })
})
