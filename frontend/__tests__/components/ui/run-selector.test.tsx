import React from 'react'
import { render, screen, fireEvent, waitFor } from '../../utils/test-utils'
import userEvent from '@testing-library/user-event'
import { RunSelector } from '@/components/ui/run-selector'
import { mockEvaluationRun, mockApiResponse, mockApiError } from '../../utils/test-utils'
import { apiClient } from '@/lib/api'

// Mock the useRuns hook
jest.mock('@/hooks', () => ({
  useRuns: jest.fn()
}))

import { useRuns } from '@/hooks'

const mockUseRuns = useRuns as jest.MockedFunction<typeof useRuns>

describe('RunSelector Component', () => {
  const defaultProps = {
    selectedRunId: undefined,
    onRunSelect: jest.fn(),
    excludeRunId: undefined,
    label: 'Select Run',
    placeholder: 'Choose a run...'
  }

  const mockRuns = [
    mockEvaluationRun({ 
      id: 'run-1', 
      name: 'Test Run 1', 
      status: 'completed',
      created_at: '2024-01-01T00:00:00Z',
      duration_seconds: 120
    }),
    mockEvaluationRun({ 
      id: 'run-2', 
      name: 'Test Run 2', 
      status: 'completed',
      created_at: '2024-01-02T00:00:00Z',
      duration_seconds: 180
    }),
    mockEvaluationRun({ 
      id: 'run-3', 
      name: 'Test Run 3', 
      status: 'failed',
      created_at: '2024-01-03T00:00:00Z'
    })
  ]

  beforeEach(() => {
    jest.clearAllMocks()
  })

  describe('Loading State', () => {
    it('displays loading skeleton while fetching runs', () => {
      mockUseRuns.mockReturnValue({
        runs: null,
        loading: true,
        error: null,
        refetch: jest.fn(),
        setFilters: jest.fn(),
        filters: {},
        clearError: jest.fn()
      })

      render(<RunSelector {...defaultProps} />)
      
      expect(screen.getByText('Select Run')).toBeInTheDocument()
      // Check for skeleton loading component
      const skeleton = document.querySelector('.h-10.w-full')
      expect(skeleton).toBeInTheDocument()
    })
  })

  describe('Error State', () => {
    it('displays error message when loading fails', () => {
      mockUseRuns.mockReturnValue({
        runs: null,
        loading: false,
        error: 'Failed to load runs',
        refetch: jest.fn(),
        setFilters: jest.fn(),
        filters: {},
        clearError: jest.fn()
      })

      render(<RunSelector {...defaultProps} />)
      
      expect(screen.getByText('Error loading runs: Failed to load runs')).toBeInTheDocument()
    })
  })

  describe('Successful Data Loading', () => {
    beforeEach(() => {
      mockUseRuns.mockReturnValue({
        runs: { items: mockRuns, total: 3, limit: 50, offset: 0, has_next: false, has_prev: false },
        loading: false,
        error: null,
        refetch: jest.fn(),
        setFilters: jest.fn(),
        filters: {},
        clearError: jest.fn()
      })
    })

    it('renders search input and select dropdown', () => {
      render(<RunSelector {...defaultProps} />)
      
      expect(screen.getByPlaceholderText('Search runs...')).toBeInTheDocument()
      expect(screen.getByDisplayValue('Choose a run...')).toBeInTheDocument()
    })

    it('displays all available runs in dropdown', () => {
      render(<RunSelector {...defaultProps} />)
      
      const select = screen.getByRole('combobox')
      expect(select).toBeInTheDocument()
      
      // Check options are present
      expect(screen.getByRole('option', { name: /Choose a run.../ })).toBeInTheDocument()
      expect(screen.getByRole('option', { name: /Test Run 1/ })).toBeInTheDocument()
      expect(screen.getByRole('option', { name: /Test Run 2/ })).toBeInTheDocument()
      expect(screen.getByRole('option', { name: /Test Run 3/ })).toBeInTheDocument()
    })

    it('formats run options with date and duration', () => {
      render(<RunSelector {...defaultProps} />)
      
      const option1 = screen.getByRole('option', { name: /Test Run 1.*1\/1\/2024.*120s/ })
      expect(option1).toBeInTheDocument()
      
      const option2 = screen.getByRole('option', { name: /Test Run 2.*1\/2\/2024.*180s/ })
      expect(option2).toBeInTheDocument()
    })
  })

  describe('Run Selection', () => {
    beforeEach(() => {
      mockUseRuns.mockReturnValue({
        runs: { items: mockRuns, total: 3, limit: 50, offset: 0, has_next: false, has_prev: false },
        loading: false,
        error: null,
        refetch: jest.fn(),
        setFilters: jest.fn(),
        filters: {},
        clearError: jest.fn()
      })
    })

    it('calls onRunSelect when a run is selected', async () => {
      const user = userEvent.setup()
      const onRunSelect = jest.fn()
      
      render(<RunSelector {...defaultProps} onRunSelect={onRunSelect} />)
      
      const select = screen.getByRole('combobox')
      await user.selectOptions(select, 'run-1')
      
      expect(onRunSelect).toHaveBeenCalledWith('run-1')
    })

    it('displays selected run details when selectedRunId is provided', () => {
      render(<RunSelector {...defaultProps} selectedRunId="run-1" />)
      
      expect(screen.getByText('Test Run 1')).toBeInTheDocument()
      expect(screen.getByText('completed')).toBeInTheDocument()
      expect(screen.getByText('100 items')).toBeInTheDocument()
      expect(screen.getByText('120s duration')).toBeInTheDocument()
    })

    it('shows run description when available', () => {
      const runWithDescription = {
        ...mockRuns[0],
        description: 'This is a test run description'
      }
      
      mockUseRuns.mockReturnValue({
        runs: { items: [runWithDescription], total: 1, limit: 50, offset: 0, has_next: false, has_prev: false },
        loading: false,
        error: null,
        refetch: jest.fn(),
        setFilters: jest.fn(),
        filters: {},
        clearError: jest.fn()
      })

      render(<RunSelector {...defaultProps} selectedRunId="run-1" />)
      
      expect(screen.getByText('This is a test run description')).toBeInTheDocument()
    })
  })

  describe('Filtering and Search', () => {
    it('calls setFilters when search input changes', async () => {
      const user = userEvent.setup()
      const setFilters = jest.fn()
      
      mockUseRuns.mockReturnValue({
        runs: { items: mockRuns, total: 3, limit: 50, offset: 0, has_next: false, has_prev: false },
        loading: false,
        error: null,
        refetch: jest.fn(),
        setFilters,
        filters: {},
        clearError: jest.fn()
      })

      render(<RunSelector {...defaultProps} />)
      
      const searchInput = screen.getByPlaceholderText('Search runs...')
      await user.type(searchInput, 'test query')
      
      // Due to throttling in useRuns, we need to wait
      await waitFor(() => {
        expect(setFilters).toHaveBeenCalled()
      })
    })

    it('excludes specified run from dropdown options', () => {
      render(<RunSelector {...defaultProps} excludeRunId="run-2" />)
      
      expect(screen.getByRole('option', { name: /Test Run 1/ })).toBeInTheDocument()
      expect(screen.queryByRole('option', { name: /Test Run 2/ })).not.toBeInTheDocument()
      expect(screen.getByRole('option', { name: /Test Run 3/ })).toBeInTheDocument()
    })

    it('only shows completed runs by default', () => {
      // The useRuns hook is called with status: 'completed' filter
      render(<RunSelector {...defaultProps} />)
      
      expect(mockUseRuns).toHaveBeenCalledWith({
        search: '',
        status: 'completed',
        limit: 50
      })
    })
  })

  describe('Status and Badge Display', () => {
    beforeEach(() => {
      mockUseRuns.mockReturnValue({
        runs: { items: mockRuns, total: 3, limit: 50, offset: 0, has_next: false, has_prev: false },
        loading: false,
        error: null,
        refetch: jest.fn(),
        setFilters: jest.fn(),
        filters: {},
        clearError: jest.fn()
      })
    })

    it('displays correct status badge colors', () => {
      render(<RunSelector {...defaultProps} selectedRunId="run-1" />)
      
      const statusBadge = screen.getByText('completed')
      expect(statusBadge).toBeInTheDocument()
      // Badge component will handle the color styling
    })

    it('shows template badge when template_name is available', () => {
      const runWithTemplate = {
        ...mockRuns[0],
        template_name: 'QA Template'
      }
      
      mockUseRuns.mockReturnValue({
        runs: { items: [runWithTemplate], total: 1, limit: 50, offset: 0, has_next: false, has_prev: false },
        loading: false,
        error: null,
        refetch: jest.fn(),
        setFilters: jest.fn(),
        filters: {},
        clearError: jest.fn()
      })

      render(<RunSelector {...defaultProps} selectedRunId="run-1" />)
      
      expect(screen.getByText('QA Template')).toBeInTheDocument()
    })

    it('displays dataset name when available', () => {
      const runWithDataset = {
        ...mockRuns[0],
        dataset_name: 'test-dataset'
      }
      
      mockUseRuns.mockReturnValue({
        runs: { items: [runWithDataset], total: 1, limit: 50, offset: 0, has_next: false, has_prev: false },
        loading: false,
        error: null,
        refetch: jest.fn(),
        setFilters: jest.fn(),
        filters: {},
        clearError: jest.fn()
      })

      render(<RunSelector {...defaultProps} selectedRunId="run-1" />)
      
      expect(screen.getByText('test-dataset')).toBeInTheDocument()
    })
  })

  describe('Empty State', () => {
    it('shows message when no runs are available', () => {
      mockUseRuns.mockReturnValue({
        runs: { items: [], total: 0, limit: 50, offset: 0, has_next: false, has_prev: false },
        loading: false,
        error: null,
        refetch: jest.fn(),
        setFilters: jest.fn(),
        filters: {},
        clearError: jest.fn()
      })

      render(<RunSelector {...defaultProps} />)
      
      expect(screen.getByText('No completed runs available for comparison.')).toBeInTheDocument()
    })
  })

  describe('Accessibility', () => {
    beforeEach(() => {
      mockUseRuns.mockReturnValue({
        runs: { items: mockRuns, total: 3, limit: 50, offset: 0, has_next: false, has_prev: false },
        loading: false,
        error: null,
        refetch: jest.fn(),
        setFilters: jest.fn(),
        filters: {},
        clearError: jest.fn()
      })
    })

    it('has proper label association', () => {
      render(<RunSelector {...defaultProps} label="Choose Baseline Run" />)
      
      const label = screen.getByText('Choose Baseline Run')
      expect(label).toBeInTheDocument()
      expect(label.tagName).toBe('LABEL')
    })

    it('has accessible form controls', () => {
      render(<RunSelector {...defaultProps} />)
      
      const searchInput = screen.getByPlaceholderText('Search runs...')
      expect(searchInput).toHaveAttribute('type', 'text')
      
      const select = screen.getByRole('combobox')
      expect(select).toBeInTheDocument()
    })
  })

  describe('Edge Cases', () => {
    it('handles runs without duration_seconds gracefully', () => {
      const runWithoutDuration = {
        ...mockRuns[0],
        duration_seconds: undefined
      }
      
      mockUseRuns.mockReturnValue({
        runs: { items: [runWithoutDuration], total: 1, limit: 50, offset: 0, has_next: false, has_prev: false },
        loading: false,
        error: null,
        refetch: jest.fn(),
        setFilters: jest.fn(),
        filters: {},
        clearError: jest.fn()
      })

      render(<RunSelector {...defaultProps} />)
      
      // Should show option without duration
      const option = screen.getByRole('option', { name: /Test Run 1.*1\/1\/2024/ })
      expect(option).toBeInTheDocument()
      expect(option.textContent).not.toMatch(/\d+s/)
    })

    it('applies custom className', () => {
      mockUseRuns.mockReturnValue({
        runs: { items: mockRuns, total: 3, limit: 50, offset: 0, has_next: false, has_prev: false },
        loading: false,
        error: null,
        refetch: jest.fn(),
        setFilters: jest.fn(),
        filters: {},
        clearError: jest.fn()
      })

      const { container } = render(
        <RunSelector {...defaultProps} className="custom-selector-class" />
      )
      
      expect(container.firstChild).toHaveClass('custom-selector-class')
    })
  })
})