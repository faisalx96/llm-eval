import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { DatasetBrowser } from '@/components/ui/dataset-browser';
import { useDatasets } from '@/hooks/useDatasets';

// Mock the hook
jest.mock('@/hooks/useDatasets', () => ({
  useDatasets: jest.fn(),
  useDatasetItems: jest.fn(),
}));

const mockUseDatasets = useDatasets as jest.MockedFunction<typeof useDatasets>;
const mockUseDatasetItems = jest.fn();

// Mock data
const mockDatasets = [
  {
    id: 'dataset-1',
    name: 'Customer Support QA',
    description: 'Questions and answers for customer support scenarios',
    created_at: '2024-01-15T10:00:00Z',
    item_count: 1500,
    last_used: '2024-01-20T15:30:00Z',
  },
  {
    id: 'dataset-2',
    name: 'Product Reviews',
    description: 'Product review sentiment analysis dataset',
    created_at: '2024-01-10T09:00:00Z',
    item_count: 3200,
    last_used: '2024-01-18T11:45:00Z',
  }
];

describe('DatasetBrowser', () => {
  beforeEach(() => {
    mockUseDatasets.mockReturnValue({
      datasets: mockDatasets,
      loading: false,
      error: null,
      pagination: {
        total: 2,
        hasNext: false,
        hasPrev: false,
      },
      refetch: jest.fn(),
    });

    // Mock useDatasetItems
    require('@/hooks/useDatasets').useDatasetItems = mockUseDatasetItems;
    mockUseDatasetItems.mockReturnValue({
      items: [],
      loading: false,
      error: null,
    });
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('renders dataset browser with header', () => {
    render(<DatasetBrowser />);
    
    expect(screen.getByText('Dataset Browser')).toBeInTheDocument();
    expect(screen.getByText('Browse and explore your Langfuse datasets')).toBeInTheDocument();
  });

  it('displays search input', () => {
    render(<DatasetBrowser />);
    
    expect(screen.getByPlaceholderText('Search datasets by name or description...')).toBeInTheDocument();
  });

  it('renders dataset cards', () => {
    render(<DatasetBrowser />);
    
    expect(screen.getByText('Customer Support QA')).toBeInTheDocument();
    expect(screen.getByText('Product Reviews')).toBeInTheDocument();
    expect(screen.getByText('1,500')).toBeInTheDocument(); // item count
    expect(screen.getByText('3,200')).toBeInTheDocument(); // item count
  });

  it('shows loading state', () => {
    mockUseDatasets.mockReturnValue({
      datasets: [],
      loading: true,
      error: null,
      pagination: { total: 0, hasNext: false, hasPrev: false },
      refetch: jest.fn(),
    });

    render(<DatasetBrowser />);
    
    expect(screen.getByText('Loading datasets...')).toBeInTheDocument();
  });

  it('shows error state', () => {
    const mockError = new Error('Failed to load datasets');
    mockUseDatasets.mockReturnValue({
      datasets: [],
      loading: false,
      error: mockError,
      pagination: { total: 0, hasNext: false, hasPrev: false },
      refetch: jest.fn(),
    });

    render(<DatasetBrowser />);
    
    expect(screen.getByText('Failed to load datasets: Failed to load datasets')).toBeInTheDocument();
  });

  it('shows empty state when no datasets', () => {
    mockUseDatasets.mockReturnValue({
      datasets: [],
      loading: false,
      error: null,
      pagination: { total: 0, hasNext: false, hasPrev: false },
      refetch: jest.fn(),
    });

    render(<DatasetBrowser />);
    
    expect(screen.getByText('No datasets available')).toBeInTheDocument();
  });

  it('handles search input', async () => {
    render(<DatasetBrowser />);
    
    const searchInput = screen.getByPlaceholderText('Search datasets by name or description...');
    fireEvent.change(searchInput, { target: { value: 'support' } });
    
    expect(searchInput).toHaveValue('support');
  });

  it('calls onSelectDataset when dataset is clicked in selection mode', () => {
    const mockOnSelect = jest.fn();
    render(
      <DatasetBrowser
        onSelectDataset={mockOnSelect}
        selectionMode={true}
      />
    );
    
    const datasetCard = screen.getByText('Customer Support QA').closest('.cursor-pointer');
    fireEvent.click(datasetCard!);
    
    expect(mockOnSelect).toHaveBeenCalledWith(mockDatasets[0]);
  });

  it('shows selected dataset in selection mode', () => {
    render(
      <DatasetBrowser
        selectedDatasetId="dataset-1"
        selectionMode={true}
      />
    );
    
    expect(screen.getByText('Selected')).toBeInTheDocument();
  });

  it('shows pagination when available', () => {
    mockUseDatasets.mockReturnValue({
      datasets: mockDatasets,
      loading: false,
      error: null,
      pagination: {
        total: 25,
        hasNext: true,
        hasPrev: false,
      },
      refetch: jest.fn(),
    });

    render(<DatasetBrowser />);
    
    expect(screen.getByText('Showing 1 to 12 of 25 results')).toBeInTheDocument();
    expect(screen.getByText('Next')).toBeInTheDocument();
  });

  it('refreshes data when refresh button is clicked', () => {
    const mockRefetch = jest.fn();
    mockUseDatasets.mockReturnValue({
      datasets: mockDatasets,
      loading: false,
      error: null,
      pagination: { total: 2, hasNext: false, hasPrev: false },
      refetch: mockRefetch,
    });

    render(<DatasetBrowser />);
    
    const refreshButton = screen.getByText('Refresh');
    fireEvent.click(refreshButton);
    
    expect(mockRefetch).toHaveBeenCalled();
  });

  it('opens preview modal when preview button is clicked', async () => {
    render(<DatasetBrowser />);
    
    const previewButtons = screen.getAllByTitle('Preview dataset');
    fireEvent.click(previewButtons[0]);
    
    await waitFor(() => {
      expect(screen.getByText('Dataset Preview: Customer Support QA')).toBeInTheDocument();
    });
  });
});