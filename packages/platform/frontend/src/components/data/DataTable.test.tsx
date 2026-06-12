import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { useState } from 'react'
import type { RowSelectionState } from '@tanstack/react-table'
import {
  computeZeroEntropyColumns,
  createSelectionColumn,
  DataTable,
  type DataTableColumn,
} from './DataTable'
import { stubResizeObserver } from './testUtils'

beforeAll(() => {
  stubResizeObserver()
})

// vitest runs with globals off, so RTL cannot auto-register cleanup.
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

interface Item {
  id: string
  name: string
  score: number
  env: string
}

const items: Item[] = [
  { id: 'r1', name: 'bravo', score: 50, env: 'prod' },
  { id: 'r2', name: 'alpha', score: 90, env: 'prod' },
  { id: 'r3', name: 'charlie', score: 10, env: 'prod' },
]

const baseColumns: DataTableColumn<Item>[] = [
  { accessorKey: 'name', header: 'Name' },
  { accessorKey: 'score', header: 'Score' },
]

function dataRows(container: HTMLElement): HTMLTableRowElement[] {
  return Array.from(container.querySelectorAll<HTMLTableRowElement>('tbody tr[data-index]'))
}

describe('DataTable', () => {
  it('renders headers and cell values', () => {
    render(<DataTable data={items} columns={baseColumns} getRowId={(r) => r.id} />)
    expect(screen.getByRole('columnheader', { name: /name/i })).toBeInTheDocument()
    expect(screen.getByText('bravo')).toBeInTheDocument()
    expect(screen.getByText('90')).toBeInTheDocument()
  })

  it('sorts on header click with aria-sort indicator', () => {
    const { container } = render(
      <DataTable data={items} columns={baseColumns} getRowId={(r) => r.id} />,
    )
    const scoreHeader = screen.getByRole('button', { name: /score/i })

    // TanStack auto-sorts numeric columns descending first.
    fireEvent.click(scoreHeader)
    let names = dataRows(container).map((tr) => tr.cells[0].textContent)
    expect(names).toEqual(['alpha', 'bravo', 'charlie']) // score desc: 90, 50, 10
    expect(screen.getByRole('columnheader', { name: /score/i })).toHaveAttribute(
      'aria-sort',
      'descending',
    )

    fireEvent.click(scoreHeader)
    names = dataRows(container).map((tr) => tr.cells[0].textContent)
    expect(names).toEqual(['charlie', 'bravo', 'alpha']) // score asc: 10, 50, 90
    expect(screen.getByRole('columnheader', { name: /score/i })).toHaveAttribute(
      'aria-sort',
      'ascending',
    )
  })

  it('lifts selection state through the checkbox column', () => {
    function Harness() {
      const [selection, setSelection] = useState<RowSelectionState>({})
      return (
        <>
          <DataTable
            data={items}
            columns={[createSelectionColumn<Item>(), ...baseColumns]}
            getRowId={(r) => r.id}
            rowSelection={selection}
            onRowSelectionChange={setSelection}
          />
          <output data-testid="selected">{Object.keys(selection).sort().join(',')}</output>
        </>
      )
    }
    render(<Harness />)

    const rowBoxes = screen.getAllByRole('checkbox', { name: 'Select row' })
    expect(rowBoxes).toHaveLength(3)

    fireEvent.click(rowBoxes[0])
    expect(screen.getByTestId('selected')).toHaveTextContent('r1')

    fireEvent.click(screen.getByRole('checkbox', { name: 'Select all rows' }))
    expect(screen.getByTestId('selected')).toHaveTextContent('r1,r2,r3')
  })

  it('renders the empty slot when there are no rows', () => {
    render(
      <DataTable
        data={[]}
        columns={baseColumns}
        empty={<div data-testid="empty-state">No results found</div>}
      />,
    )
    expect(screen.getByTestId('empty-state')).toHaveTextContent('No results found')
  })

  it('renders skeleton rows while loading', () => {
    render(<DataTable data={[]} columns={baseColumns} loading skeletonRows={5} />)
    expect(screen.getAllByTestId('skeleton-row')).toHaveLength(5)
  })

  it('expands a row full-width via getRowCanExpand + renderSubComponent', () => {
    const columns: DataTableColumn<Item>[] = [
      {
        id: 'expander',
        header: () => null,
        enableSorting: false,
        cell: ({ row }) =>
          row.getCanExpand() ? (
            <button
              type="button"
              aria-label={`Toggle details for ${row.original.name}`}
              onClick={row.getToggleExpandedHandler()}
            >
              +
            </button>
          ) : null,
      },
      ...baseColumns,
    ]
    const { container } = render(
      <DataTable
        data={items}
        columns={columns}
        getRowId={(r) => r.id}
        getRowCanExpand={() => true}
        renderSubComponent={(row) => (
          <div data-testid="sub">details for {row.original.name}</div>
        )}
      />,
    )

    expect(screen.queryByTestId('sub')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Toggle details for bravo' }))
    expect(screen.getByTestId('sub')).toHaveTextContent('details for bravo')

    // Sub row spans the full table width.
    const subCell = container.querySelector('tbody td[colspan]')
    expect(subCell).toHaveAttribute('colspan', '3')
  })

  it('fires onRowClick for plain row clicks but not for inner controls', () => {
    const onRowClick = vi.fn()
    function Harness() {
      const [selection, setSelection] = useState<RowSelectionState>({})
      return (
        <DataTable
          data={items}
          columns={[createSelectionColumn<Item>(), ...baseColumns]}
          getRowId={(r) => r.id}
          rowSelection={selection}
          onRowSelectionChange={setSelection}
          onRowClick={onRowClick}
        />
      )
    }
    const { container } = render(<Harness />)

    fireEvent.click(screen.getByText('bravo'))
    expect(onRowClick).toHaveBeenCalledTimes(1)
    expect(onRowClick.mock.calls[0][0].original.id).toBe('r1')

    // Clicking the row checkbox must NOT also fire onRowClick.
    fireEvent.click(within(dataRows(container)[1]).getByRole('checkbox'))
    expect(onRowClick).toHaveBeenCalledTimes(1)
  })

  describe('keyboard navigation', () => {
    it('moves row focus with ArrowDown / ArrowUp (roving tabindex)', () => {
      const { container } = render(
        <DataTable data={items} columns={baseColumns} getRowId={(r) => r.id} />,
      )
      const rows = dataRows(container)
      expect(rows[0]).toHaveAttribute('tabindex', '0')
      expect(rows[1]).toHaveAttribute('tabindex', '-1')

      rows[0].focus()
      fireEvent.keyDown(rows[0], { key: 'ArrowDown' })
      expect(document.activeElement).toBe(rows[1])
      expect(rows[1]).toHaveAttribute('tabindex', '0')
      expect(rows[0]).toHaveAttribute('tabindex', '-1')

      fireEvent.keyDown(rows[1], { key: 'ArrowDown' })
      expect(document.activeElement).toBe(rows[2])
      // Clamped at the last row.
      fireEvent.keyDown(rows[2], { key: 'ArrowDown' })
      expect(document.activeElement).toBe(rows[2])

      fireEvent.keyDown(rows[2], { key: 'ArrowUp' })
      expect(document.activeElement).toBe(rows[1])
    })

    it('triggers onRowClick with Enter', () => {
      const onRowClick = vi.fn()
      const { container } = render(
        <DataTable
          data={items}
          columns={baseColumns}
          getRowId={(r) => r.id}
          onRowClick={onRowClick}
        />,
      )
      const rows = dataRows(container)
      rows[0].focus()
      fireEvent.keyDown(rows[0], { key: 'Enter' })
      expect(onRowClick).toHaveBeenCalledTimes(1)
      expect(onRowClick.mock.calls[0][0].original.id).toBe('r1')
    })

    it('toggles selection with Space when selectable', () => {
      function Harness() {
        const [selection, setSelection] = useState<RowSelectionState>({})
        return (
          <DataTable
            data={items}
            columns={[createSelectionColumn<Item>(), ...baseColumns]}
            getRowId={(r) => r.id}
            rowSelection={selection}
            onRowSelectionChange={setSelection}
          />
        )
      }
      const { container } = render(<Harness />)
      const row = dataRows(container)[0]
      row.focus()

      fireEvent.keyDown(row, { key: ' ' })
      expect(within(dataRows(container)[0]).getByRole('checkbox')).toBeChecked()
      expect(dataRows(container)[0]).toHaveAttribute('aria-selected', 'true')

      fireEvent.keyDown(dataRows(container)[0], { key: ' ' })
      expect(within(dataRows(container)[0]).getByRole('checkbox')).not.toBeChecked()
    })
  })

  describe('virtualization', () => {
    it('renders only a window of rows for 1000 rows', () => {
      // jsdom reports 0×0 element sizes, which makes the virtualizer compute
      // an empty range — give the scroll container a real viewport
      // (virtual-core reads offsetWidth/offsetHeight).
      vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(400)
      vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(800)
      const big: Item[] = Array.from({ length: 1000 }, (_, i) => ({
        id: `id-${i}`,
        name: `row-${i}`,
        score: i,
        env: 'prod',
      }))
      const { container } = render(
        <DataTable
          data={big}
          columns={baseColumns}
          getRowId={(r) => r.id}
          virtualized
          maxHeight={400}
        />,
      )
      const rendered = dataRows(container)
      expect(rendered.length).toBeGreaterThan(0)
      expect(rendered.length).toBeLessThan(100)
      expect(screen.getByText('row-0')).toBeInTheDocument()
      expect(screen.queryByText('row-999')).not.toBeInTheDocument()
    })

    it('renders all rows when below the virtualization threshold', () => {
      const { container } = render(
        <DataTable data={items} columns={baseColumns} getRowId={(r) => r.id} virtualized />,
      )
      expect(dataRows(container)).toHaveLength(3)
    })
  })
})

describe('computeZeroEntropyColumns', () => {
  const rows = [
    { env: 'prod', model: 'gpt-x', score: 1 },
    { env: 'prod', model: 'gpt-y', score: 2 },
    { env: 'prod', model: 'gpt-x', score: 3 },
  ]

  it('returns ids whose values are identical across all rows', () => {
    expect(computeZeroEntropyColumns(rows, ['env', 'model', 'score'])).toEqual(['env'])
  })

  it('returns [] for fewer than 2 rows (identical is vacuous)', () => {
    expect(computeZeroEntropyColumns([rows[0]], ['env', 'model'])).toEqual([])
    expect(computeZeroEntropyColumns([], ['env'])).toEqual([])
  })

  it('distinguishes null, undefined and missing-vs-empty values', () => {
    const tricky = [
      { a: null, b: undefined, c: '' },
      { a: null, b: '', c: '' },
    ]
    expect(computeZeroEntropyColumns(tricky, ['a', 'b', 'c'])).toEqual(['a', 'c'])
  })

  it('compares object values structurally', () => {
    const objs = [{ meta: { k: 1 } }, { meta: { k: 1 } }]
    expect(computeZeroEntropyColumns(objs, ['meta'])).toEqual(['meta'])
    const diff = [{ meta: { k: 1 } }, { meta: { k: 2 } }]
    expect(computeZeroEntropyColumns(diff, ['meta'])).toEqual([])
  })

  it('supports a custom value accessor', () => {
    const nested = [{ tags: ['x'] }, { tags: ['x'] }]
    expect(
      computeZeroEntropyColumns(nested, ['tag0'], (row) => row.tags[0]),
    ).toEqual(['tag0'])
  })
})
