import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { TemplateMarketplace } from '@/components/ui/template-marketplace';
import { useTemplates, useTemplateRecommendations } from '@/hooks/useTemplates';

// Mock the hooks
jest.mock('@/hooks/useTemplates', () => ({
  useTemplates: jest.fn(),
  useTemplateRecommendations: jest.fn(),
}));

const mockUseTemplates = useTemplates as jest.MockedFunction<typeof useTemplates>;
const mockUseTemplateRecommendations = useTemplateRecommendations as jest.MockedFunction<typeof useTemplateRecommendations>;

// Mock data
const mockTemplates = [
  {
    id: 'qa-template',
    name: 'qa',
    display_name: 'Q&A Evaluation',
    description: 'Template for evaluating question-answering systems',
    category: 'qa' as const,
    use_cases: ['Customer Support', 'Knowledge Base'],
    metrics: ['exact_match', 'semantic_similarity'],
    required_fields: ['input', 'expected_output'],
    optional_fields: ['context'],
    popularity_score: 0.8,
    created_at: '2024-01-15T10:00:00Z',
    author: 'LLM-Eval Team',
    tags: ['qa', 'chatbot'],
  },
  {
    id: 'summarization-template',
    name: 'summarization',
    display_name: 'Text Summarization',
    description: 'Template for evaluating text summarization models',
    category: 'summarization' as const,
    use_cases: ['Document Summarization', 'News Articles'],
    metrics: ['rouge', 'bleu'],
    required_fields: ['input', 'expected_output'],
    optional_fields: ['length_limit'],
    popularity_score: 0.7,
    created_at: '2024-01-10T09:00:00Z',
    author: 'LLM-Eval Team',
    tags: ['summarization', 'nlp'],
  }
];

const mockTemplatesByCategory = {
  qa: [mockTemplates[0]],
  summarization: [mockTemplates[1]],
  classification: [],
  general: [],
  custom: []
};

describe('TemplateMarketplace', () => {
  beforeEach(() => {
    mockUseTemplates.mockReturnValue({
      templates: mockTemplates,
      templatesByCategory: mockTemplatesByCategory,
      loading: false,
      error: null,
      pagination: {
        total: 2,
        hasNext: false,
        hasPrev: false,
      },
      refetch: jest.fn(),
    });

    mockUseTemplateRecommendations.mockReturnValue({
      recommendations: [],
      loading: false,
      error: null,
      getRecommendations: jest.fn(),
      clearRecommendations: jest.fn(),
    });
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('renders template marketplace with header', () => {
    render(<TemplateMarketplace />);
    
    expect(screen.getByText('Template Marketplace')).toBeInTheDocument();
    expect(screen.getByText('Choose from pre-built evaluation templates or get AI recommendations')).toBeInTheDocument();
  });

  it('displays search input', () => {
    render(<TemplateMarketplace />);
    
    expect(screen.getByPlaceholderText('Search templates by name, description, or use case...')).toBeInTheDocument();
  });

  it('shows AI recommendations button', () => {
    render(<TemplateMarketplace showRecommendations={true} />);
    
    expect(screen.getByText('Get AI Recommendations')).toBeInTheDocument();
  });

  it('renders category tabs', () => {
    render(<TemplateMarketplace />);
    
    expect(screen.getByText('All Templates (2)')).toBeInTheDocument();
    expect(screen.getByText('Q&A (1)')).toBeInTheDocument();
    expect(screen.getByText('Summarization (1)')).toBeInTheDocument();
  });

  it('renders template cards', () => {
    render(<TemplateMarketplace />);
    
    expect(screen.getByText('Q&A Evaluation')).toBeInTheDocument();
    expect(screen.getByText('Text Summarization')).toBeInTheDocument();
  });

  it('shows loading state', () => {
    mockUseTemplates.mockReturnValue({
      templates: [],
      templatesByCategory: {
        qa: [], summarization: [], classification: [], general: [], custom: []
      },
      loading: true,
      error: null,
      pagination: { total: 0, hasNext: false, hasPrev: false },
      refetch: jest.fn(),
    });

    render(<TemplateMarketplace />);
    
    expect(screen.getByText('Loading templates...')).toBeInTheDocument();
  });

  it('shows error state', () => {
    const mockError = new Error('Failed to load templates');
    mockUseTemplates.mockReturnValue({
      templates: [],
      templatesByCategory: {
        qa: [], summarization: [], classification: [], general: [], custom: []
      },
      loading: false,
      error: mockError,
      pagination: { total: 0, hasNext: false, hasPrev: false },
      refetch: jest.fn(),
    });

    render(<TemplateMarketplace />);
    
    expect(screen.getByText('Failed to load templates: Failed to load templates')).toBeInTheDocument();
  });

  it('handles search input', () => {
    render(<TemplateMarketplace />);
    
    const searchInput = screen.getByPlaceholderText('Search templates by name, description, or use case...');
    fireEvent.change(searchInput, { target: { value: 'qa' } });
    
    expect(searchInput).toHaveValue('qa');
  });

  it('opens AI recommendations panel', () => {
    render(<TemplateMarketplace showRecommendations={true} />);
    
    const recommendationsButton = screen.getByText('Get AI Recommendations');
    fireEvent.click(recommendationsButton);
    
    expect(screen.getByText('AI Template Recommendations')).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/e\.g\., I want to evaluate a chatbot that answers customer support questions about our product/)).toBeInTheDocument();
  });

  it('calls onSelectTemplate when template is selected', () => {
    const mockOnSelect = jest.fn();
    render(
      <TemplateMarketplace
        onSelectTemplate={mockOnSelect}
        selectionMode={true}
      />
    );
    
    const templateCard = screen.getByText('Q&A Evaluation').closest('.cursor-pointer');
    fireEvent.click(templateCard!);
    
    expect(mockOnSelect).toHaveBeenCalledWith(mockTemplates[0]);
  });

  it('shows selected template in selection mode', () => {
    render(
      <TemplateMarketplace
        selectedTemplateId="qa-template"
        selectionMode={true}
      />
    );
    
    expect(screen.getByText('Selected')).toBeInTheDocument();
  });

  it('filters templates by category', () => {
    render(<TemplateMarketplace />);
    
    const qaTab = screen.getByText('Q&A (1)');
    fireEvent.click(qaTab);
    
    // Would verify the category description appears
    expect(screen.getByText('Q&A Templates')).toBeInTheDocument();
  });

  it('changes sort order', () => {
    render(<TemplateMarketplace />);
    
    const sortSelect = screen.getByRole('combobox');
    fireEvent.change(sortSelect, { target: { value: 'name' } });
    
    expect(sortSelect).toHaveValue('name');
  });

  it('shows empty state when no templates', () => {
    mockUseTemplates.mockReturnValue({
      templates: [],
      templatesByCategory: {
        qa: [], summarization: [], classification: [], general: [], custom: []
      },
      loading: false,
      error: null,
      pagination: { total: 0, hasNext: false, hasPrev: false },
      refetch: jest.fn(),
    });

    render(<TemplateMarketplace />);
    
    expect(screen.getByText('No templates found')).toBeInTheDocument();
  });

  it('handles AI recommendations workflow', async () => {
    const mockGetRecommendations = jest.fn();
    mockUseTemplateRecommendations.mockReturnValue({
      recommendations: [],
      loading: false,
      error: null,
      getRecommendations: mockGetRecommendations,
      clearRecommendations: jest.fn(),
    });

    render(<TemplateMarketplace showRecommendations={true} />);
    
    // Open recommendations panel
    const recommendationsButton = screen.getByText('Get AI Recommendations');
    fireEvent.click(recommendationsButton);
    
    // Enter description
    const textarea = screen.getByPlaceholderText(/e\.g\., I want to evaluate a chatbot that answers customer support questions about our product/);
    fireEvent.change(textarea, { 
      target: { value: 'I want to evaluate a chatbot for customer support' } 
    });
    
    // Get recommendations
    const getRecommendationsButton = screen.getByText('Get Recommendations');
    fireEvent.click(getRecommendationsButton);
    
    expect(mockGetRecommendations).toHaveBeenCalledWith(
      'I want to evaluate a chatbot for customer support'
    );
  });

  it('displays recommendations when available', () => {
    const mockRecommendations = [
      {
        template: mockTemplates[0],
        confidence: 0.95,
        reasons: ['Keywords suggest Q&A task: chatbot, support'],
        matching_keywords: ['chatbot', 'support']
      }
    ];

    mockUseTemplateRecommendations.mockReturnValue({
      recommendations: mockRecommendations,
      loading: false,
      error: null,
      getRecommendations: jest.fn(),
      clearRecommendations: jest.fn(),
    });

    render(<TemplateMarketplace showRecommendations={true} />);
    
    // Open recommendations panel
    const recommendationsButton = screen.getByText('Get AI Recommendations');
    fireEvent.click(recommendationsButton);
    
    expect(screen.getByText('Recommended Templates (1)')).toBeInTheDocument();
    expect(screen.getByText('95% match')).toBeInTheDocument();
  });

  it('refreshes templates when refresh button is clicked', () => {
    const mockRefetch = jest.fn();
    mockUseTemplates.mockReturnValue({
      templates: mockTemplates,
      templatesByCategory: mockTemplatesByCategory,
      loading: false,
      error: null,
      pagination: { total: 2, hasNext: false, hasPrev: false },
      refetch: mockRefetch,
    });

    render(<TemplateMarketplace />);
    
    const refreshButton = screen.getByText('Refresh');
    fireEvent.click(refreshButton);
    
    expect(mockRefetch).toHaveBeenCalled();
  });
});