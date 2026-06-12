import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { CodePanel } from './CodePanel'
import { JsonView } from './JsonView'

// vitest runs with globals off, so RTL cannot auto-register cleanup.
afterEach(cleanup)

describe('CodePanel', () => {
  describe('XSS safety', () => {
    it('renders an <img onerror> payload as inert text — no element is created', () => {
      const payload = '<img src=x onerror="window.__pwned = true">'
      const { container } = render(<CodePanel code={payload} />)
      expect(container.querySelector('img')).toBeNull()
      expect(screen.getByText(payload)).toBeInTheDocument()
      expect((window as unknown as Record<string, unknown>).__pwned).toBeUndefined()
    })

    it('renders a <script> payload as inert text', () => {
      const payload = '<script>window.__pwned2 = true</script>'
      const { container } = render(<CodePanel code={payload} />)
      expect(container.querySelector('script')).toBeNull()
      expect((window as unknown as Record<string, unknown>).__pwned2).toBeUndefined()
    })

    it('keeps HTML inside JSON string values inert too', () => {
      const code = '{"html": "<img src=x onerror=alert(1)>"}'
      const { container } = render(<CodePanel code={code} />)
      expect(container.querySelector('img')).toBeNull()
      expect(screen.getByText(/onerror=alert\(1\)/)).toBeInTheDocument()
    })
  })

  describe('JSON auto-detection', () => {
    it('pretty-prints parseable JSON as a collapsible tree', () => {
      render(<CodePanel code='{"name":"qym","count":3,"ok":true}' />)
      expect(screen.getByText('"name"')).toBeInTheDocument()
      expect(screen.getByText('"qym"')).toBeInTheDocument()
      expect(screen.getByText('3')).toBeInTheDocument()
      expect(screen.getByText('true')).toBeInTheDocument()
      // Root node is expandable.
      expect(screen.getByRole('button', { name: /collapse value/i })).toBeInTheDocument()
    })

    it('falls back to plain text for invalid JSON', () => {
      const { container } = render(<CodePanel code='{"broken": tru' />)
      expect(container.querySelector('pre')).toHaveTextContent('{"broken": tru')
      expect(screen.queryByRole('button', { name: /collapse/i })).not.toBeInTheDocument()
    })

    it('leaves non-JSON text (SQL) as plain text', () => {
      const sql = 'SELECT * FROM runs WHERE status = "fail"'
      const { container } = render(<CodePanel code={sql} />)
      expect(container.querySelector('pre')).toHaveTextContent(sql)
    })

    it('respects detectJson={false}', () => {
      const { container } = render(<CodePanel code='{"a":1}' detectJson={false} />)
      expect(container.querySelector('pre')).toHaveTextContent('{"a":1}')
      expect(screen.queryByRole('button', { name: /collapse/i })).not.toBeInTheDocument()
    })

    it('collapses and re-expands nodes via keyboard-accessible buttons', () => {
      render(<CodePanel code='{"outer":{"inner":42}}' />)
      expect(screen.getByText('"inner"')).toBeInTheDocument()

      const outerToggle = screen.getByRole('button', { name: 'Collapse outer' })
      expect(outerToggle).toHaveAttribute('aria-expanded', 'true')
      fireEvent.click(outerToggle)
      expect(screen.queryByText('"inner"')).not.toBeInTheDocument()
      expect(screen.getByText(/1 key/)).toBeInTheDocument()

      fireEvent.click(screen.getByRole('button', { name: 'Expand outer' }))
      expect(screen.getByText('"inner"')).toBeInTheDocument()
    })
  })

  describe('diff mode', () => {
    it('highlights word-level insertions and deletions with data-diff markers', () => {
      const { container } = render(
        <CodePanel diff={{ a: 'status is pass today', b: 'status is fail today' }} />,
      )
      const dels = Array.from(container.querySelectorAll('[data-diff="del"]'))
      const inss = Array.from(container.querySelectorAll('[data-diff="ins"]'))
      expect(dels.map((d) => d.textContent).join('')).toContain('pass')
      expect(inss.map((d) => d.textContent).join('')).toContain('fail')
      // Unchanged text is not wrapped in diff markers.
      expect(container.querySelector('pre')?.textContent).toBe('status is passfail today')
    })

    it('renders identical sides without any diff markers', () => {
      const { container } = render(<CodePanel diff={{ a: 'same text', b: 'same text' }} />)
      expect(container.querySelector('[data-diff]')).toBeNull()
      expect(screen.getByText('same text')).toBeInTheDocument()
    })
  })

  describe('header chrome', () => {
    it('renders the label', () => {
      render(<CodePanel code="x" label="Output" />)
      expect(screen.getByText('Output')).toBeInTheDocument()
    })

    it('copies the raw code to the clipboard', async () => {
      const writeText = vi.fn().mockResolvedValue(undefined)
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText },
        configurable: true,
      })
      render(<CodePanel code='{"a":1}' label="Output" />)

      fireEvent.click(screen.getByRole('button', { name: 'Copy to clipboard' }))
      expect(writeText).toHaveBeenCalledWith('{"a":1}')
      await waitFor(() => expect(screen.getByText('Copied')).toBeInTheDocument())
    })

    it('copies side b in diff mode', async () => {
      const writeText = vi.fn().mockResolvedValue(undefined)
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText },
        configurable: true,
      })
      render(<CodePanel diff={{ a: 'old', b: 'new' }} />)
      fireEvent.click(screen.getByRole('button', { name: 'Copy to clipboard' }))
      expect(writeText).toHaveBeenCalledWith('new')
      await waitFor(() => expect(screen.getByText('Copied')).toBeInTheDocument())
    })

    it('hides the copy button when copyable is false', () => {
      render(<CodePanel code="x" label="Output" copyable={false} />)
      expect(screen.queryByRole('button', { name: /copy/i })).not.toBeInTheDocument()
    })
  })
})

describe('JsonView', () => {
  it('renders arrays with item-count summaries when collapsed', () => {
    render(<JsonView value={{ tags: ['a', 'b', 'c'] }} defaultExpandDepth={1} />)
    // Depth 1 array starts collapsed with a summary.
    expect(screen.getByText(/3 items/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Expand tags' }))
    expect(screen.getByText('"a"')).toBeInTheDocument()
  })

  it('renders empty containers inline without a toggle', () => {
    render(<JsonView value={{ empty: {}, list: [] }} />)
    expect(screen.getByText('{}')).toBeInTheDocument()
    expect(screen.getByText('[]')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /empty/ })).not.toBeInTheDocument()
  })

  it('renders null and booleans as keywords', () => {
    render(<JsonView value={{ a: null, b: false }} />)
    expect(screen.getByText('null')).toBeInTheDocument()
    expect(screen.getByText('false')).toBeInTheDocument()
  })
})
