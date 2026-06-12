import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { Tabs, TabsContent, TabsList, TabsTrigger } from './Tabs'

// The shared vitest setup has no auto-cleanup (globals disabled).
afterEach(cleanup)

function renderTabs() {
  return render(
    <Tabs defaultValue="results">
      <TabsList aria-label="Run sections">
        <TabsTrigger value="results" count={42}>
          Results
        </TabsTrigger>
        <TabsTrigger value="failures" count={3}>
          Failures
        </TabsTrigger>
        <TabsTrigger value="config">Config</TabsTrigger>
      </TabsList>
      <TabsContent value="results">Results panel</TabsContent>
      <TabsContent value="failures">Failures panel</TabsContent>
      <TabsContent value="config">Config panel</TabsContent>
    </Tabs>,
  )
}

describe('Tabs', () => {
  it('selects the default tab and shows only its panel', () => {
    renderTabs()
    expect(screen.getByRole('tab', { name: /Results/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('Results panel')).toBeInTheDocument()
    expect(screen.queryByText('Failures panel')).not.toBeInTheDocument()
  })

  it('switches panels on click and updates aria-selected', () => {
    renderTabs()
    fireEvent.mouseDown(screen.getByRole('tab', { name: /Failures/ }))
    fireEvent.click(screen.getByRole('tab', { name: /Failures/ }))
    expect(screen.getByRole('tab', { name: /Failures/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: /Results/ })).toHaveAttribute('aria-selected', 'false')
    expect(screen.getByText('Failures panel')).toBeInTheDocument()
  })

  it('renders count badges', () => {
    renderTabs()
    expect(screen.getByRole('tab', { name: /Results/ })).toHaveTextContent('42')
    expect(screen.getByRole('tab', { name: /Failures/ })).toHaveTextContent('3')
  })

  it('moves selection with arrow keys (a11y keyboard navigation)', async () => {
    renderTabs()
    const first = screen.getByRole('tab', { name: /Results/ })
    first.focus()
    fireEvent.keyDown(first, { key: 'ArrowRight' })
    const second = screen.getByRole('tab', { name: /Failures/ })
    // Radix roving focus moves focus in a deferred task.
    await waitFor(() => {
      expect(second).toHaveFocus()
    })
    expect(second).toHaveAttribute('aria-selected', 'true')
  })

  it('exposes the tablist with its accessible name', () => {
    renderTabs()
    expect(screen.getByRole('tablist', { name: 'Run sections' })).toBeInTheDocument()
  })
})
