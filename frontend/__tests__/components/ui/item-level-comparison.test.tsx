import React from 'react'
import { render, screen, fireEvent, waitFor } from '../../utils/test-utils'
import userEvent from '@testing-library/user-event'
import { ItemLevelComparison } from '@/components/ui/item-level-comparison'
import { mockRunComparison } from '../../utils/test-utils'

describe('ItemLevelComparison Component', () => {
  // Create a more comprehensive mock with multiple items for testing
  const createMockComparisonWithItems = (itemCount: number = 25) => {
    const baseComparison = mockRunComparison()
    const items = Array.from({ length: itemCount }, (_, index) => ({
      item_id: `item-${index + 1}`,
      run1_scores: {
        exact_match: Math.random(),
        answer_relevancy: Math.random() * 0.8 + 0.2
      },
      run2_scores: {
        exact_match: Math.random(),
        answer_relevancy: Math.random() * 0.8 + 0.2
      },
      differences: {
        exact_match: (Math.random() - 0.5) * 0.4,
        answer_relevancy: (Math.random() - 0.5) * 0.3
      },
      input_data: {
        question: `Sample question ${index + 1}`,
        context: `Context for question ${index + 1}`,
        additional_field: `Value ${index + 1}`
      },
      run1_status: index % 10 === 0 ? 'failed' as const : 'success' as const,
      run2_status: index % 8 === 0 ? 'failed' as const : 'success' as const,
    }))

    return {
      ...baseComparison,
      item_level_comparison: items
    }
  }

  const defaultComparison = createMockComparisonWithItems()

  describe('Basic Rendering', () => {
    it('renders component title and item count', () => {
      render(<ItemLevelComparison comparison={defaultComparison} />)

      expect(screen.getByText('Item-Level Comparison')).toBeInTheDocument()
      expect(screen.getByText('25 of 25 items')).toBeInTheDocument()
    })

    it('displays search input and filter controls', () => {
      render(<ItemLevelComparison comparison={defaultComparison} />)

      expect(screen.getByPlaceholderText('Search items...')).toBeInTheDocument()
      expect(screen.getByDisplayValue('All Items')).toBeInTheDocument()
      expect(screen.getByDisplayValue('Index')).toBeInTheDocument()
    })

    it('renders table headers correctly', () => {
      render(<ItemLevelComparison comparison={defaultComparison} />)

      expect(screen.getByText('#')).toBeInTheDocument()
      expect(screen.getByText('Input Data')).toBeInTheDocument()
      expect(screen.getByText('Status')).toBeInTheDocument()
      expect(screen.getByText('exact_match')).toBeInTheDocument()
      expect(screen.getByText('answer_relevancy')).toBeInTheDocument()
    })

    it('displays first page of items by default (20 items)', () => {
      render(<ItemLevelComparison comparison={defaultComparison} />)

      // Should show items 1-20 on first page
      expect(screen.getByText('1')).toBeInTheDocument() // First item index
      expect(screen.getByText('20')).toBeInTheDocument() // Last item on page 1
      expect(screen.queryByText('21')).not.toBeInTheDocument() // Should not show item 21
    })
  })

  describe('Search Functionality', () => {
    it('filters items based on search input', async () => {
      const user = userEvent.setup()
      render(<ItemLevelComparison comparison={defaultComparison} />)

      const searchInput = screen.getByPlaceholderText('Search items...')
      await user.type(searchInput, 'question 5')

      await waitFor(() => {
        expect(screen.getByText('1 of 25 items')).toBeInTheDocument()
        expect(screen.getByText('Sample question 5')).toBeInTheDocument()
      })
    })

    it('searches in item_id field', async () => {
      const user = userEvent.setup()
      render(<ItemLevelComparison comparison={defaultComparison} />)

      const searchInput = screen.getByPlaceholderText('Search items...')
      await user.type(searchInput, 'item-10')

      await waitFor(() => {
        expect(screen.getByText('1 of 25 items')).toBeInTheDocument()
      })
    })

    it('shows all items when search is cleared', async () => {
      const user = userEvent.setup()
      render(<ItemLevelComparison comparison={defaultComparison} />)

      const searchInput = screen.getByPlaceholderText('Search items...')

      // Search first
      await user.type(searchInput, 'question 1')
      await waitFor(() => {
        expect(screen.getByText(/\d+ of 25 items/)).toBeInTheDocument()
      })

      // Clear search
      await user.clear(searchInput)
      await waitFor(() => {
        expect(screen.getByText('25 of 25 items')).toBeInTheDocument()
      })
    })
  })

  describe('Status Filtering', () => {
    it('filters to show only improved items', async () => {
      const user = userEvent.setup()
      render(<ItemLevelComparison comparison={defaultComparison} />)

      const statusFilter = screen.getByDisplayValue('All Items')
      await user.selectOptions(statusFilter, 'improved')

      await waitFor(() => {
        const itemCount = screen.getByText(/\d+ of 25 items/)
        expect(itemCount.textContent).toMatch(/^\d+ of 25 items$/)
      })
    })

    it('filters to show only regressed items', async () => {
      const user = userEvent.setup()
      render(<ItemLevelComparison comparison={defaultComparison} />)

      const statusFilter = screen.getByDisplayValue('All Items')
      await user.selectOptions(statusFilter, 'regressed')

      await waitFor(() => {
        const itemCount = screen.getByText(/\d+ of 25 items/)
        expect(itemCount.textContent).toMatch(/^\d+ of 25 items$/)
      })
    })

    it('filters to show only failed items', async () => {
      const user = userEvent.setup()
      render(<ItemLevelComparison comparison={defaultComparison} />)

      const statusFilter = screen.getByDisplayValue('All Items')
      await user.selectOptions(statusFilter, 'failed')

      await waitFor(() => {
        // Should show items where either run failed
        const itemCount = screen.getByText(/\d+ of 25 items/)
        expect(itemCount.textContent).toMatch(/^\d+ of 25 items$/)
      })
    })

    it('returns to all items when "All Items" is selected', async () => {
      const user = userEvent.setup()
      render(<ItemLevelComparison comparison={defaultComparison} />)

      const statusFilter = screen.getByDisplayValue('All Items')

      // Filter first
      await user.selectOptions(statusFilter, 'improved')
      await waitFor(() => {
        const itemCount = screen.getByText(/\d+ of 25 items/)
        expect(itemCount).toBeInTheDocument()
      })

      // Return to all
      await user.selectOptions(statusFilter, 'all')
      await waitFor(() => {
        expect(screen.getByText('25 of 25 items')).toBeInTheDocument()
      })
    })
  })

  describe('Sorting Functionality', () => {
    it('sorts by index by default', () => {
      render(<ItemLevelComparison comparison={defaultComparison} />)

      const sortSelect = screen.getByDisplayValue('Index')
      expect(sortSelect).toBeInTheDocument()

      // First item should be index 1
      const firstRow = screen.getAllByRole('cell')[0]
      expect(firstRow).toHaveTextContent('1')
    })

    it('changes sort order when sort button is clicked', async () => {
      const user = userEvent.setup()
      render(<ItemLevelComparison comparison={defaultComparison} />)

      const sortOrderButton = screen.getByRole('button', { name: '↑' })
      expect(sortOrderButton).toBeInTheDocument()

      await user.click(sortOrderButton)
      expect(screen.getByRole('button', { name: '↓' })).toBeInTheDocument()
    })

    it('sorts by metric differences when metric is selected', async () => {
      const user = userEvent.setup()
      render(<ItemLevelComparison comparison={defaultComparison} />)

      const sortSelect = screen.getByDisplayValue('Index')
      await user.selectOptions(sortSelect, 'exact_match')

      await waitFor(() => {
        expect(screen.getByDisplayValue('exact_match diff')).toBeInTheDocument()
      })
    })
  })

  describe('Pagination', () => {
    it('shows pagination controls when there are more than 20 items', () => {
      render(<ItemLevelComparison comparison={defaultComparison} />)

      expect(screen.getByText('Previous')).toBeInTheDocument()
      expect(screen.getByText('Next')).toBeInTheDocument()
      expect(screen.getByText('Showing 1 to 20 of 25 items')).toBeInTheDocument()
    })

    it('navigates to next page correctly', async () => {
      const user = userEvent.setup()
      render(<ItemLevelComparison comparison={defaultComparison} />)

      const nextButton = screen.getByText('Next')
      await user.click(nextButton)

      await waitFor(() => {
        expect(screen.getByText('Showing 21 to 25 of 25 items')).toBeInTheDocument()
        expect(screen.getByText('21')).toBeInTheDocument() // First item on page 2
      })
    })

    it('disables Previous button on first page', () => {
      render(<ItemLevelComparison comparison={defaultComparison} />)

      const previousButton = screen.getByText('Previous')
      expect(previousButton).toBeDisabled()
    })

    it('disables Next button on last page', async () => {
      const user = userEvent.setup()
      render(<ItemLevelComparison comparison={defaultComparison} />)

      // Navigate to last page
      const nextButton = screen.getByText('Next')
      await user.click(nextButton)

      await waitFor(() => {
        expect(nextButton).toBeDisabled()
      })
    })

    it('shows page numbers', () => {
      render(<ItemLevelComparison comparison={defaultComparison} />)

      expect(screen.getByRole('button', { name: '1' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: '2' })).toBeInTheDocument()
    })

    it('navigates to specific page when page number is clicked', async () => {
      const user = userEvent.setup()
      render(<ItemLevelComparison comparison={defaultComparison} />)

      const page2Button = screen.getByRole('button', { name: '2' })
      await user.click(page2Button)

      await waitFor(() => {
        expect(screen.getByText('Showing 21 to 25 of 25 items')).toBeInTheDocument()
      })
    })
  })

  describe('Data Display', () => {
    it('displays formatted scores correctly', () => {
      render(<ItemLevelComparison comparison={defaultComparison} />)

      // Should show percentage formatted scores
      const scoreElements = screen.getAllByText(/%/)
      expect(scoreElements.length).toBeGreaterThan(0)
    })

    it('shows score changes with arrows and formatting', () => {
      render(<ItemLevelComparison comparison={defaultComparison} />)

      // Check for score transition format (run1 → run2)
      const transitionElements = screen.getAllByText(/→/)
      expect(transitionElements.length).toBeGreaterThan(0)
    })

    it('displays differences with proper formatting and colors', () => {
      render(<ItemLevelComparison comparison={defaultComparison} />)

      // Should show differences in pp format for percentages
      const diffElements = document.querySelectorAll('[class*="text-success"], [class*="text-danger"], [class*="text-neutral"]')
      expect(diffElements.length).toBeGreaterThan(0)
    })

    it('truncates long input data appropriately', () => {
      const longDataComparison = {
        ...defaultComparison,
        item_level_comparison: [{
          ...defaultComparison.item_level_comparison[0],
          input_data: {
            very_long_field: 'This is a very long string that should be truncated to avoid breaking the table layout and ensure readability'
          }
        }]
      }

      render(<ItemLevelComparison comparison={longDataComparison} />)

      expect(screen.getByText(/This is a very long string.*\.\.\./)).toBeInTheDocument()
    })

    it('displays status badges for both runs', () => {
      render(<ItemLevelComparison comparison={defaultComparison} />)

      expect(screen.getByText(/R1: success/)).toBeInTheDocument()
      expect(screen.getByText(/R2: success/)).toBeInTheDocument()
    })
  })

  describe('Edge Cases and Error Handling', () => {
    it('handles items without some scores gracefully', () => {
      const incompleteComparison = {
        ...defaultComparison,
        item_level_comparison: [{
          item_id: 'incomplete-item',
          run1_scores: {},
          run2_scores: {},
          differences: {},
          input_data: { question: 'Test' },
          run1_status: 'success' as const,
          run2_status: 'success' as const,
        }]
      }

      render(<ItemLevelComparison comparison={incompleteComparison} />)

      expect(screen.getByText('0.0%')).toBeInTheDocument() // Default score
    })

    it('displays message when no items match filters', async () => {
      const user = userEvent.setup()
      render(<ItemLevelComparison comparison={defaultComparison} />)

      const searchInput = screen.getByPlaceholderText('Search items...')
      await user.type(searchInput, 'nonexistent search term')

      await waitFor(() => {
        expect(screen.getByText('0 of 25 items')).toBeInTheDocument()
      })
    })

    it('handles empty input_data objects', () => {
      const emptyDataComparison = {
        ...defaultComparison,
        item_level_comparison: [{
          ...defaultComparison.item_level_comparison[0],
          input_data: {}
        }]
      }

      render(<ItemLevelComparison comparison={emptyDataComparison} />)

      expect(screen.getByText('-')).toBeInTheDocument()
    })
  })

  describe('Performance and Responsive Design', () => {
    it('applies custom className', () => {
      const { container } = render(
        <ItemLevelComparison comparison={defaultComparison} className="custom-comparison-class" />
      )

      expect(container.firstChild).toHaveClass('custom-comparison-class')
    })

    it('has mobile-responsive table classes', () => {
      render(<ItemLevelComparison comparison={defaultComparison} />)

      const table = document.querySelector('.mobile-scroll-table')
      expect(table).toBeInTheDocument()

      const mobileButtons = document.querySelectorAll('.mobile-touch-target')
      expect(mobileButtons.length).toBeGreaterThan(0)
    })

    it('maintains performance with large datasets', () => {
      const largeComparison = createMockComparisonWithItems(100)

      // Should not crash or hang
      render(<ItemLevelComparison comparison={largeComparison} />)

      expect(screen.getByText('Item-Level Comparison')).toBeInTheDocument()
      expect(screen.getByText('100 of 100 items')).toBeInTheDocument()
    })
  })

  describe('Accessibility', () => {
    it('has proper table structure with headers', () => {
      render(<ItemLevelComparison comparison={defaultComparison} />)

      expect(screen.getByRole('table')).toBeInTheDocument()
      expect(screen.getAllByRole('columnheader')).toHaveLength(5) // #, Input Data, Status, exact_match, answer_relevancy
    })

    it('has accessible form controls', () => {
      render(<ItemLevelComparison comparison={defaultComparison} />)

      expect(screen.getByRole('textbox')).toBeInTheDocument() // Search input
      expect(screen.getAllByRole('combobox')).toHaveLength(2) // Status filter and sort select
      expect(screen.getAllByRole('button')).toContain(screen.getByText('Previous'))
    })

    it('provides proper button labels', () => {
      render(<ItemLevelComparison comparison={defaultComparison} />)

      expect(screen.getByRole('button', { name: '↑' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Previous' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Next' })).toBeInTheDocument()
    })
  })
})
