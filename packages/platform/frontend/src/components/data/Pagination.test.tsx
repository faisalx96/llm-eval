import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Pagination } from './Pagination'

// vitest runs with globals off, so RTL cannot auto-register cleanup.
afterEach(cleanup)

describe('Pagination', () => {
  it('renders the one dialect: Prev · Page N of M · Next', () => {
    render(<Pagination page={2} pageCount={9} onPageChange={() => {}} />)
    expect(screen.getByRole('button', { name: '‹ Prev' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Next ›' })).toBeInTheDocument()
    expect(screen.getByText('Page', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.getByText('9')).toBeInTheDocument()
  })

  it('fires onPageChange for prev/next', () => {
    const onPageChange = vi.fn()
    render(<Pagination page={3} pageCount={9} onPageChange={onPageChange} />)
    fireEvent.click(screen.getByRole('button', { name: 'Next ›' }))
    expect(onPageChange).toHaveBeenCalledWith(4)
    fireEvent.click(screen.getByRole('button', { name: '‹ Prev' }))
    expect(onPageChange).toHaveBeenCalledWith(2)
  })

  it('disables prev on the first page and next on the last', () => {
    const { rerender } = render(<Pagination page={1} pageCount={5} onPageChange={() => {}} />)
    expect(screen.getByRole('button', { name: '‹ Prev' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Next ›' })).toBeEnabled()

    rerender(<Pagination page={5} pageCount={5} onPageChange={() => {}} />)
    expect(screen.getByRole('button', { name: '‹ Prev' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Next ›' })).toBeDisabled()
  })

  it('shows "Showing X–Y of Z" when pageSize and totalItems are given', () => {
    render(
      <Pagination
        page={2}
        pageCount={10}
        onPageChange={() => {}}
        pageSize={25}
        onPageSizeChange={() => {}}
        totalItems={230}
      />,
    )
    expect(screen.getByText('26–50')).toBeInTheDocument()
    expect(screen.getByText('230')).toBeInTheDocument()
  })

  it('clamps the range end on the final partial page and zero items', () => {
    const { rerender } = render(
      <Pagination
        page={10}
        pageCount={10}
        onPageChange={() => {}}
        pageSize={25}
        onPageSizeChange={() => {}}
        totalItems={230}
      />,
    )
    expect(screen.getByText('226–230')).toBeInTheDocument()

    rerender(
      <Pagination
        page={1}
        pageCount={0}
        onPageChange={() => {}}
        pageSize={25}
        onPageSizeChange={() => {}}
        totalItems={0}
      />,
    )
    expect(screen.getByText('0–0')).toBeInTheDocument()
  })

  it('renders the page-size select with 25/50/100 and emits changes', () => {
    const onPageSizeChange = vi.fn()
    render(
      <Pagination
        page={1}
        pageCount={10}
        onPageChange={() => {}}
        pageSize={25}
        onPageSizeChange={onPageSizeChange}
        totalItems={230}
      />,
    )
    const select = screen.getByRole('combobox', { name: 'Rows per page' })
    expect(
      Array.from((select as HTMLSelectElement).options).map((o) => o.value),
    ).toEqual(['25', '50', '100'])
    fireEvent.change(select, { target: { value: '100' } })
    expect(onPageSizeChange).toHaveBeenCalledWith(100)
  })

  it('omits the size select and range without the optional props', () => {
    render(<Pagination page={1} pageCount={3} onPageChange={() => {}} />)
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(screen.queryByText(/showing/i)).not.toBeInTheDocument()
  })
})
