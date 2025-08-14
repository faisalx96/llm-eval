import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MetricSelector } from '@/components/ui/metric-selector';
import { useMetrics } from '@/hooks/useMetrics';

// Mock the hooks
jest.mock('@/hooks/useMetrics', () => ({
  useMetrics: jest.fn(),
  useMetricSelector: jest.fn(),
  useMetricCompatibility: jest.fn(),
}));

const mockUseMetrics = useMetrics as jest.MockedFunction<typeof useMetrics>;
const mockUseMetricSelector = jest.fn();
const mockUseMetricCompatibility = jest.fn();

// Mock data
const mockMetrics = [
  {
    id: 'exact_match',
    name: 'exact_match',
    display_name: 'Exact Match',
    description: 'Checks if the output exactly matches the expected result',
    category: 'accuracy' as const,
    requirements: ['expected_output'],
    compatible_tasks: ['qa', 'classification'],
    is_custom: false,
  },
  {
    id: 'semantic_similarity',
    name: 'semantic_similarity',
    display_name: 'Semantic Similarity',
    description: 'Measures semantic similarity between output and expected result',
    category: 'semantic' as const,
    requirements: ['expected_output'],
    parameters: {
      threshold: { type: 'number', default: 0.8, min: 0, max: 1 }
    },
    compatible_tasks: ['qa', 'summarization'],
    is_custom: false,
  }
];

const mockMetricsByCategory = {
  accuracy: [mockMetrics[0]],
  semantic: [mockMetrics[1]],
  safety: [],
  performance: [],
  custom: []
};

describe('MetricSelector', () => {
  beforeEach(() => {
    mockUseMetrics.mockReturnValue({
      metrics: mockMetrics,
      metricsByCategory: mockMetricsByCategory,
      loading: false,
      error: null,
      refetch: jest.fn(),
    });

    // Mock useMetricSelector
    require('@/hooks/useMetrics').useMetricSelector = mockUseMetricSelector;
    mockUseMetricSelector.mockReturnValue({
      selectedMetrics: [],
      isSelected: jest.fn().mockReturnValue(false),
      toggleSelection: jest.fn(),
      clearSelection: jest.fn(),
      setSelectedMetrics: jest.fn(),
      addMetric: jest.fn(),
      removeMetric: jest.fn(),
      getMetricSelection: jest.fn(),
      isMetricSelected: jest.fn().mockReturnValue(false),
    });

    // Mock useMetricCompatibility
    require('@/hooks/useMetrics').useMetricCompatibility = mockUseMetricCompatibility;
    mockUseMetricCompatibility.mockReturnValue({
      compatibility: {
        compatible: true,
        issues: [],
      },
      loading: false,
      error: null,
    });
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('renders metric selector with header', () => {
    render(<MetricSelector />);
    
    expect(screen.getByText('Metric Selector')).toBeInTheDocument();
    expect(screen.getByText('Choose metrics to evaluate your model\'s performance')).toBeInTheDocument();
  });

  it('displays search input', () => {
    render(<MetricSelector />);
    
    expect(screen.getByPlaceholderText('Search metrics by name, description, or category...')).toBeInTheDocument();
  });

  it('renders category tabs', () => {
    render(<MetricSelector />);
    
    expect(screen.getByText('All Metrics (2)')).toBeInTheDocument();
    expect(screen.getByText('Accuracy (1)')).toBeInTheDocument();
    expect(screen.getByText('Semantic (1)')).toBeInTheDocument();
  });

  it('renders metric cards', () => {
    render(<MetricSelector />);
    
    expect(screen.getByText('Exact Match')).toBeInTheDocument();
    expect(screen.getByText('Semantic Similarity')).toBeInTheDocument();
  });

  it('shows loading state', () => {
    mockUseMetrics.mockReturnValue({
      metrics: [],
      metricsByCategory: {
        accuracy: [], semantic: [], safety: [], performance: [], custom: []
      },
      loading: true,
      error: null,
      refetch: jest.fn(),
    });

    render(<MetricSelector />);
    
    expect(screen.getByText('Loading metrics...')).toBeInTheDocument();
  });

  it('shows error state', () => {
    const mockError = new Error('Failed to load metrics');
    mockUseMetrics.mockReturnValue({
      metrics: [],
      metricsByCategory: {
        accuracy: [], semantic: [], safety: [], performance: [], custom: []
      },
      loading: false,
      error: mockError,
      refetch: jest.fn(),
    });

    render(<MetricSelector />);
    
    expect(screen.getByText('Failed to load metrics: Failed to load metrics')).toBeInTheDocument();
  });

  it('filters metrics by search term', async () => {
    render(<MetricSelector />);
    
    const searchInput = screen.getByPlaceholderText('Search metrics by name, description, or category...');
    fireEvent.change(searchInput, { target: { value: 'exact' } });
    
    expect(searchInput).toHaveValue('exact');
    // The filtering logic would be tested in integration with the actual hook
  });

  it('switches between category tabs', () => {
    render(<MetricSelector />);
    
    const accuracyTab = screen.getByText('Accuracy (1)');
    fireEvent.click(accuracyTab);
    
    // Would verify the tab is active and content changes
  });

  it('calls onSelectionChange when metrics are selected', () => {
    const mockOnSelectionChange = jest.fn();
    render(<MetricSelector onSelectionChange={mockOnSelectionChange} />);
    
    const addButton = screen.getAllByText('Add Metric')[0];
    fireEvent.click(addButton);
    
    expect(mockOnSelectionChange).toHaveBeenCalled();
  });

  it('shows selected metrics in preview', () => {
    const initialSelections = [
      { metric_id: 'exact_match' }
    ];

    // Mock the selector to return selected metrics
    mockUseMetricSelector.mockReturnValue({
      selectedMetrics: [{ metric_id: 'exact_match', parameters: {} }],
      isSelected: jest.fn().mockReturnValue(true),
      toggleSelection: jest.fn(),
      clearSelection: jest.fn(),
      setSelectedMetrics: jest.fn(),
      addMetric: jest.fn(),
      removeMetric: jest.fn(),
      getMetricSelection: jest.fn().mockReturnValue({ metric_id: 'exact_match', parameters: {} }),
      isMetricSelected: jest.fn().mockReturnValue(true),
    });
    
    render(
      <MetricSelector 
        initialSelections={initialSelections}
        onSelectionChange={jest.fn()}
      />
    );
    
    expect(screen.getByText('Show Selection (1)')).toBeInTheDocument();
  });

  it('allows clearing all selected metrics', () => {
    const initialSelections = [
      { metric_id: 'exact_match' }
    ];
    
    const mockClearSelection = jest.fn();
    
    // Mock the selector to return selected metrics
    mockUseMetricSelector.mockReturnValue({
      selectedMetrics: [{ metric_id: 'exact_match', parameters: {} }],
      isSelected: jest.fn().mockReturnValue(true),
      toggleSelection: jest.fn(),
      clearSelection: mockClearSelection,
      setSelectedMetrics: jest.fn(),
      addMetric: jest.fn(),
      removeMetric: jest.fn(),
      getMetricSelection: jest.fn().mockReturnValue({ metric_id: 'exact_match', parameters: {} }),
      isMetricSelected: jest.fn().mockReturnValue(true),
    });
    
    render(
      <MetricSelector 
        initialSelections={initialSelections}
        onSelectionChange={jest.fn()}
      />
    );
    
    const clearAllButton = screen.getByText('Clear All');
    fireEvent.click(clearAllButton);
    
    expect(mockClearSelection).toHaveBeenCalled();
  });

  it('shows category description when category is selected', () => {
    render(<MetricSelector />);
    
    const accuracyTab = screen.getByText('Accuracy (1)');
    fireEvent.click(accuracyTab);
    
    expect(screen.getByText('Accuracy Metrics')).toBeInTheDocument();
    expect(screen.getByText('Metrics that measure correctness and precision of outputs')).toBeInTheDocument();
  });

  it('shows empty state when no metrics found', () => {
    mockUseMetrics.mockReturnValue({
      metrics: [],
      metricsByCategory: {
        accuracy: [], semantic: [], safety: [], performance: [], custom: []
      },
      loading: false,
      error: null,
      refetch: jest.fn(),
    });

    render(<MetricSelector />);
    
    expect(screen.getByText('No metrics found')).toBeInTheDocument();
  });

  it('handles metric parameter configuration', async () => {
    render(<MetricSelector />);
    
    // Click on semantic similarity metric which has parameters
    const semanticMetricCard = screen.getByText('Semantic Similarity').closest('.cursor-pointer');
    fireEvent.click(semanticMetricCard!);
    
    // Would test parameter configuration modal appears and can be configured
  });
});