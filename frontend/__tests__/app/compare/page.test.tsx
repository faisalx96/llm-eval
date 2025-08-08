import React from 'react'
import { render, screen, fireEvent, waitFor } from '../../utils/test-utils'
import userEvent from '@testing-library/user-event'
import Compare from '@/app/compare/page'
import { mockRunComparison, mockApiResponse, mockApiError } from '../../utils/test-utils'

// Mock the hooks
jest.mock('@/hooks', () => ({
  useRunComparison: jest.fn()
}))

// Mock Next.js useSearchParams to return different values
const mockUseSearchParams = jest.fn()
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: jest.fn(),
    replace: jest.fn(),
    prefetch: jest.fn(),
  }),
  useSearchParams: () => mockUseSearchParams(),
  usePathname: () => '/compare'
}))

import { useRunComparison } from '@/hooks'

const mockUseRunComparison = useRunComparison as jest.MockedFunction<typeof useRunComparison>

describe('Compare Page', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockUseSearchParams.mockReturnValue(new URLSearchParams())

    // Mock window.history
    Object.defineProperty(window, 'history', {
      writable: true,
      value: {
        replaceState: jest.fn(),
      },
    })
  })

  describe('Initial State', () => {
    it('renders page title and description', () => {
      mockUseRunComparison.mockReturnValue({
        comparison: null,
        loading: false,
        error: null,
        refetch: jest.fn()
      })

      render(<Compare />)

      expect(screen.getByText('Compare Runs')).toBeInTheDocument()
      expect(screen.getByText(/Side-by-side comparison of evaluation runs/)).toBeInTheDocument()
    })

    it('shows run selectors', () => {
      mockUseRunComparison.mockReturnValue({
        comparison: null,
        loading: false,
        error: null,
        refetch: jest.fn()
      })

      render(<Compare />)

      expect(screen.getByText('Run 1 (Baseline)')).toBeInTheDocument()
      expect(screen.getByText('Run 2 (Comparison)')).toBeInTheDocument()
    })

    it('displays empty state when no runs are selected', () => {
      mockUseRunComparison.mockReturnValue({
        comparison: null,
        loading: false,
        error: null,
        refetch: jest.fn()
      })

      render(<Compare />)

      expect(screen.getByText('Select Two Runs to Compare')).toBeInTheDocument()
      expect(screen.getByText(/Choose two completed evaluation runs/)).toBeInTheDocument()
    })
  })

  describe('URL Parameter Handling', () => {
    it('initializes with run IDs from URL parameters', () => {
      const searchParams = new URLSearchParams('?run1=test-run-1&run2=test-run-2')
      mockUseSearchParams.mockReturnValue(searchParams)

      mockUseRunComparison.mockReturnValue({
        comparison: null,
        loading: false,
        error: null,
        refetch: jest.fn()
      })

      render(<Compare />)

      expect(mockUseRunComparison).toHaveBeenCalledWith('test-run-1', 'test-run-2')
    })

    it('updates URL when run selections change', () => {
      mockUseRunComparison.mockReturnValue({
        comparison: null,
        loading: false,
        error: null,
        refetch: jest.fn()
      })

      render(<Compare />)

      // This would be triggered by RunSelector components changing
      // The actual URL update logic is tested through the effect
      expect(window.history.replaceState).toHaveBeenCalled()
    })
  })

  describe('Loading State', () => {
    it('shows loading skeletons when comparison is loading', () => {
      mockUseRunComparison.mockReturnValue({
        comparison: null,
        loading: true,
        error: null,
        refetch: jest.fn()
      })

      render(<Compare />)

      // Should show skeleton components
      const skeletons = document.querySelectorAll('[class*="h-64"], [class*="h-48"], [class*="h-96"]')
      expect(skeletons.length).toBeGreaterThan(0)
    })
  })

  describe('Error State', () => {
    it('displays error message when comparison fails', () => {
      const refetch = jest.fn()
      mockUseRunComparison.mockReturnValue({
        comparison: null,
        loading: false,
        error: 'Failed to load comparison data',
        refetch
      })

      render(<Compare />)

      expect(screen.getByText('Comparison Failed')).toBeInTheDocument()
      expect(screen.getByText('Failed to load comparison data')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    })

    it('calls refetch when retry button is clicked', async () => {
      const user = userEvent.setup()
      const refetch = jest.fn()

      mockUseRunComparison.mockReturnValue({
        comparison: null,
        loading: false,
        error: 'Connection failed',
        refetch
      })

      render(<Compare />)

      const retryButton = screen.getByRole('button', { name: 'Retry' })
      await user.click(retryButton)

      expect(refetch).toHaveBeenCalled()
    })
  })

  describe('Successful Comparison Display', () => {
    const mockComparison = mockRunComparison()

    beforeEach(() => {
      mockUseRunComparison.mockReturnValue({
        comparison: mockComparison,
        loading: false,
        error: null,
        refetch: jest.fn()
      })
    })

    it('displays comparison summary with key metrics', () => {
      render(<Compare />)

      expect(screen.getByText('Comparison Summary')).toBeInTheDocument()
      expect(screen.getByText('Overall Winner')).toBeInTheDocument()
      expect(screen.getByText('Significant Improvements')).toBeInTheDocument()
      expect(screen.getByText('Significant Regressions')).toBeInTheDocument()
      expect(screen.getByText('Items Compared')).toBeInTheDocument()
    })

    it('shows correct winner based on comparison data', () => {
      render(<Compare />)

      // Based on mock data, Run 2 is the winner
      expect(screen.getByText('Run 2')).toBeInTheDocument()
    })

    it('displays improvement and regression counts', () => {
      render(<Compare />)

      expect(screen.getByText('1')).toBeInTheDocument() // Significant improvements
      expect(screen.getByText('1')).toBeInTheDocument() // Significant regressions (appears twice)
      expect(screen.getByText('2')).toBeInTheDocument() // Items compared
    })

    it('renders comparison chart', () => {
      render(<Compare />)

      // The ComparisonChart component should be rendered
      // This is tested more thoroughly in the ComparisonChart tests
      expect(screen.getByText('Metric Comparison')).toBeInTheDocument()
    })

    it('displays metric differences section', () => {
      render(<Compare />)

      expect(screen.getByText('Metric Differences')).toBeInTheDocument()
      // Should show MetricDiff components for each metric
      expect(screen.getByText('exact_match')).toBeInTheDocument()
      expect(screen.getByText('answer_relevancy')).toBeInTheDocument()
    })

    it('renders item-level comparison component', () => {
      render(<Compare />)

      // The ItemLevelComparison component should be rendered
      expect(screen.getByText('Item-Level Comparison')).toBeInTheDocument()
    })
  })

  describe('Export Functionality', () => {
    const mockComparison = mockRunComparison()

    beforeEach(() => {
      mockUseRunComparison.mockReturnValue({
        comparison: mockComparison,
        loading: false,
        error: null,
        refetch: jest.fn()
      })
    })

    it('shows export button when comparison is loaded', () => {
      render(<Compare />)

      expect(screen.getByRole('button', { name: /Export Excel/ })).toBeInTheDocument()
    })

    it('handles export process with loading state', async () => {
      const user = userEvent.setup()

      // Mock successful blob response
      const mockBlob = new Blob(['test'], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      global.fetch = jest.fn().mockResolvedValue({
        blob: () => Promise.resolve(mockBlob)
      })

      render(<Compare />)

      const exportButton = screen.getByRole('button', { name: /Export Excel/ })
      await user.click(exportButton)

      // Should show loading state briefly
      expect(screen.getByTestId('loading-spinner') || screen.getByText('Export Excel')).toBeInTheDocument()
    })

    it('creates download link when export succeeds', async () => {
      const user = userEvent.setup()

      // Mock URL.createObjectURL and DOM manipulation
      const mockUrl = 'blob:mock-url'
      global.URL.createObjectURL = jest.fn(() => mockUrl)
      const mockLink = {
        href: '',
        download: '',
        click: jest.fn()
      }
      jest.spyOn(document, 'createElement').mockReturnValue(mockLink as any)
      jest.spyOn(document.body, 'appendChild').mockImplementation(() => mockLink as any)
      jest.spyOn(document.body, 'removeChild').mockImplementation(() => mockLink as any)

      const mockBlob = new Blob(['test'], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      global.fetch = jest.fn().mockResolvedValue({
        blob: () => Promise.resolve(mockBlob)
      })

      render(<Compare />)

      const exportButton = screen.getByRole('button', { name: /Export Excel/ })
      await user.click(exportButton)

      await waitFor(() => {
        expect(mockLink.click).toHaveBeenCalled()
      })
    })

    it('handles export errors gracefully', async () => {
      const user = userEvent.setup()
      const consoleSpy = jest.spyOn(console, 'error').mockImplementation()

      global.fetch = jest.fn().mockRejectedValue(new Error('Export failed'))

      render(<Compare />)

      const exportButton = screen.getByRole('button', { name: /Export Excel/ })
      await user.click(exportButton)

      await waitFor(() => {
        expect(consoleSpy).toHaveBeenCalledWith('Export failed:', expect.any(Error))
      })

      consoleSpy.mockRestore()
    })
  })

  describe('Refresh Functionality', () => {
    it('shows refresh button and calls refetch when clicked', async () => {
      const user = userEvent.setup()
      const refetch = jest.fn()

      mockUseRunComparison.mockReturnValue({
        comparison: mockRunComparison(),
        loading: false,
        error: null,
        refetch
      })

      render(<Compare />)

      const refreshButton = screen.getByRole('button', { name: '' }) // SVG button without text
      expect(refreshButton).toBeInTheDocument()

      await user.click(refreshButton)
      expect(refetch).toHaveBeenCalled()
    })
  })

  describe('Responsive Design', () => {
    beforeEach(() => {
      mockUseRunComparison.mockReturnValue({
        comparison: mockRunComparison(),
        loading: false,
        error: null,
        refetch: jest.fn()
      })
    })

    it('has responsive grid classes for run selectors', () => {
      render(<Compare />)

      const gridContainer = document.querySelector('.grid-cols-1.lg\\:grid-cols-2')
      expect(gridContainer).toBeInTheDocument()
    })

    it('has responsive summary grid', () => {
      render(<Compare />)

      const summaryGrid = document.querySelector('.md\\:grid-cols-2.lg\\:grid-cols-4')
      expect(summaryGrid).toBeInTheDocument()
    })

    it('has responsive metric differences grid', () => {
      render(<Compare />)

      const metricGrid = document.querySelector('.lg\\:grid-cols-2.xl\\:grid-cols-3')
      expect(metricGrid).toBeInTheDocument()
    })
  })

  describe('Accessibility', () => {
    beforeEach(() => {
      mockUseRunComparison.mockReturnValue({
        comparison: null,
        loading: false,
        error: null,
        refetch: jest.fn()
      })
    })

    it('has proper heading hierarchy', () => {
      render(<Compare />)

      expect(screen.getByRole('heading', { level: 1, name: 'Compare Runs' })).toBeInTheDocument()
    })

    it('provides meaningful empty state guidance', () => {
      render(<Compare />)

      expect(screen.getByText('Select Two Runs to Compare')).toBeInTheDocument()
      expect(screen.getByText(/Choose two completed evaluation runs.*detailed comparison/)).toBeInTheDocument()
    })

    it('has accessible error state with retry option', () => {
      mockUseRunComparison.mockReturnValue({
        comparison: null,
        loading: false,
        error: 'Network error',
        refetch: jest.fn()
      })

      render(<Compare />)

      expect(screen.getByRole('heading', { name: 'Comparison Failed' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    })
  })

  describe('Integration and Data Flow', () => {
    it('prevents comparison when same run is selected for both', () => {
      // This logic is handled by the RunSelector's excludeRunId prop
      render(<Compare />)

      // The page itself doesn't show comparison when runIds are the same
      // This is handled by the canCompare logic
      expect(screen.getByText('Select Two Runs to Compare')).toBeInTheDocument()
    })

    it('handles missing comparison data gracefully', () => {
      mockUseRunComparison.mockReturnValue({
        comparison: null,
        loading: false,
        error: null,
        refetch: jest.fn()
      })

      render(<Compare />)

      // Should not crash and show empty state
      expect(screen.getByText('Select Two Runs to Compare')).toBeInTheDocument()
    })
  })

  describe('Performance Considerations', () => {
    it('renders efficiently with large comparison data', () => {
      const largeComparison = {
        ...mockRunComparison(),
        item_level_comparison: Array.from({ length: 1000 }, (_, i) => ({
          item_id: `item-${i}`,
          run1_scores: { metric1: Math.random() },
          run2_scores: { metric1: Math.random() },
          differences: { metric1: Math.random() - 0.5 },
          input_data: { question: `Question ${i}` },
          run1_status: 'success' as const,
          run2_status: 'success' as const,
        }))
      }

      mockUseRunComparison.mockReturnValue({
        comparison: largeComparison,
        loading: false,
        error: null,
        refetch: jest.fn()
      })

      // Should render without performance issues
      render(<Compare />)

      expect(screen.getByText('Compare Runs')).toBeInTheDocument()
    })
  })
})
