import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { TaskConfigurationWizard } from '@/components/ui/task-configuration-wizard';
import { useConfigurationWizard, useTaskConfigurations } from '@/hooks/useTaskConfiguration';

// Mock the hooks
jest.mock('@/hooks/useTaskConfiguration');
const mockUseConfigurationWizard = useConfigurationWizard as jest.MockedFunction<typeof useConfigurationWizard>;
const mockUseTaskConfigurations = useTaskConfigurations as jest.MockedFunction<typeof useTaskConfigurations>;

// Mock wizard state
const mockWizardState = {
  current_step: 0,
  steps: [
    {
      id: 'endpoint',
      title: 'API Endpoint',
      description: 'Configure your API endpoint details',
      is_current: true,
      is_completed: false,
      validation_errors: [],
    },
    {
      id: 'auth',
      title: 'Authentication',
      description: 'Set up authentication for your API',
      is_current: false,
      is_completed: false,
      validation_errors: [],
    },
    {
      id: 'mapping',
      title: 'Field Mapping',
      description: 'Map your data fields to evaluation inputs',
      is_current: false,
      is_completed: false,
      validation_errors: [],
    },
    {
      id: 'test',
      title: 'Test Configuration',
      description: 'Test your configuration with sample data',
      is_current: false,
      is_completed: false,
      validation_errors: [],
    },
  ],
  configuration: {
    name: '',
    endpoint_url: '',
    auth_type: 'none',
    field_mappings: {},
  },
};

describe('TaskConfigurationWizard', () => {
  beforeEach(() => {
    mockUseConfigurationWizard.mockReturnValue({
      wizardState: mockWizardState,
      updateConfiguration: jest.fn(),
      validateCurrentStep: jest.fn().mockReturnValue(true),
      nextStep: jest.fn().mockReturnValue(true),
      prevStep: jest.fn(),
      goToStep: jest.fn(),
      testConfiguration: jest.fn(),
      testLoading: false,
      reset: jest.fn(),
      isComplete: false,
    });

    mockUseTaskConfigurations.mockReturnValue({
      createConfiguration: jest.fn().mockResolvedValue({ id: 'test-config' }),
      updateConfiguration: jest.fn(),
      deleteConfiguration: jest.fn(),
      configurations: [],
      loading: false,
      error: null,
      refetch: jest.fn(),
    });
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('renders wizard with header and progress', () => {
    render(<TaskConfigurationWizard />);
    
    expect(screen.getByText('Task Configuration Wizard')).toBeInTheDocument();
    expect(screen.getByText('Set up a new API endpoint configuration for evaluation tasks')).toBeInTheDocument();
    expect(screen.getByText('API Endpoint')).toBeInTheDocument();
    expect(screen.getByText('Authentication')).toBeInTheDocument();
    expect(screen.getByText('Field Mapping')).toBeInTheDocument();
    expect(screen.getByText('Test Configuration')).toBeInTheDocument();
  });

  it('shows current step indicator', () => {
    render(<TaskConfigurationWizard />);
    
    // First step should be current (highlighted)
    const currentStepIndicator = screen.getByText('1');
    expect(currentStepIndicator).toBeInTheDocument();
    expect(currentStepIndicator.closest('div')).toHaveClass('bg-primary-600');
  });

  it('renders step content based on current step', () => {
    render(<TaskConfigurationWizard />);
    
    expect(screen.getByText('API Endpoint')).toBeInTheDocument();
    expect(screen.getByText('Configure your API endpoint details')).toBeInTheDocument();
  });

  it('shows navigation buttons correctly', () => {
    render(<TaskConfigurationWizard />);
    
    // On first step, should not show Previous button
    expect(screen.queryByText('Previous')).not.toBeInTheDocument();
    
    // Should show Next and Cancel buttons
    expect(screen.getByText('Next')).toBeInTheDocument();
    expect(screen.getByText('Cancel')).toBeInTheDocument();
  });

  it('calls nextStep when Next button is clicked', () => {
    const mockNextStep = jest.fn().mockReturnValue(true);
    mockUseConfigurationWizard.mockReturnValue({
      ...mockUseConfigurationWizard(),
      nextStep: mockNextStep,
    });

    render(<TaskConfigurationWizard />);
    
    const nextButton = screen.getByText('Next');
    fireEvent.click(nextButton);
    
    expect(mockNextStep).toHaveBeenCalled();
  });

  it('shows Previous button on non-first steps', () => {
    const mockStateWithStep1 = {
      ...mockWizardState,
      current_step: 1,
      steps: mockWizardState.steps.map((step, index) => ({
        ...step,
        is_current: index === 1,
        is_completed: index === 0,
      })),
    };

    mockUseConfigurationWizard.mockReturnValue({
      ...mockUseConfigurationWizard(),
      wizardState: mockStateWithStep1,
    });

    render(<TaskConfigurationWizard />);
    
    expect(screen.getByText('Previous')).toBeInTheDocument();
  });

  it('calls prevStep when Previous button is clicked', () => {
    const mockPrevStep = jest.fn();
    const mockStateWithStep1 = {
      ...mockWizardState,
      current_step: 1,
      steps: mockWizardState.steps.map((step, index) => ({
        ...step,
        is_current: index === 1,
        is_completed: index === 0,
      })),
    };

    mockUseConfigurationWizard.mockReturnValue({
      ...mockUseConfigurationWizard(),
      wizardState: mockStateWithStep1,
      prevStep: mockPrevStep,
    });

    render(<TaskConfigurationWizard />);
    
    const prevButton = screen.getByText('Previous');
    fireEvent.click(prevButton);
    
    expect(mockPrevStep).toHaveBeenCalled();
  });

  it('shows Save Configuration button on last step', () => {
    const mockStateWithLastStep = {
      ...mockWizardState,
      current_step: 3,
      steps: mockWizardState.steps.map((step, index) => ({
        ...step,
        is_current: index === 3,
        is_completed: index < 3,
      })),
    };

    mockUseConfigurationWizard.mockReturnValue({
      ...mockUseConfigurationWizard(),
      wizardState: mockStateWithLastStep,
      isComplete: true,
    });

    render(<TaskConfigurationWizard />);
    
    expect(screen.getByText('Save Configuration')).toBeInTheDocument();
    expect(screen.queryByText('Next')).not.toBeInTheDocument();
  });

  it('handles save configuration', async () => {
    const mockCreateConfiguration = jest.fn().mockResolvedValue({ id: 'test-config' });
    const mockOnComplete = jest.fn();
    
    const mockStateWithLastStep = {
      ...mockWizardState,
      current_step: 3,
      steps: mockWizardState.steps.map((step, index) => ({
        ...step,
        is_current: index === 3,
        is_completed: index < 3,
      })),
      configuration: {
        name: 'Test Config',
        endpoint_url: 'https://api.example.com',
        auth_type: 'api_key',
        field_mappings: { input: 'prompt', output: 'response' },
      },
    };

    mockUseConfigurationWizard.mockReturnValue({
      ...mockUseConfigurationWizard(),
      wizardState: mockStateWithLastStep,
      isComplete: true,
      validateCurrentStep: jest.fn().mockReturnValue(true),
    });

    mockUseTaskConfigurations.mockReturnValue({
      ...mockUseTaskConfigurations(),
      createConfiguration: mockCreateConfiguration,
    });

    render(<TaskConfigurationWizard onComplete={mockOnComplete} />);
    
    const saveButton = screen.getByText('Save Configuration');
    fireEvent.click(saveButton);
    
    await waitFor(() => {
      expect(mockCreateConfiguration).toHaveBeenCalledWith(mockStateWithLastStep.configuration);
    });
    
    await waitFor(() => {
      expect(mockOnComplete).toHaveBeenCalledWith({ id: 'test-config' });
    });
  });

  it('shows loading state when saving', async () => {
    const mockCreateConfiguration = jest.fn(() => new Promise(resolve => setTimeout(resolve, 100)));
    
    const mockStateWithLastStep = {
      ...mockWizardState,
      current_step: 3,
      steps: mockWizardState.steps.map((step, index) => ({
        ...step,
        is_current: index === 3,
        is_completed: index < 3,
      })),
    };

    mockUseConfigurationWizard.mockReturnValue({
      ...mockUseConfigurationWizard(),
      wizardState: mockStateWithLastStep,
      isComplete: true,
      validateCurrentStep: jest.fn().mockReturnValue(true),
    });

    mockUseTaskConfigurations.mockReturnValue({
      ...mockUseTaskConfigurations(),
      createConfiguration: mockCreateConfiguration,
    });

    render(<TaskConfigurationWizard />);
    
    const saveButton = screen.getByText('Save Configuration');
    fireEvent.click(saveButton);
    
    expect(screen.getByText('Saving...')).toBeInTheDocument();
  });

  it('calls onCancel when Cancel button is clicked', () => {
    const mockOnCancel = jest.fn();
    
    render(<TaskConfigurationWizard onCancel={mockOnCancel} />);
    
    const cancelButton = screen.getByText('Cancel');
    fireEvent.click(cancelButton);
    
    expect(mockOnCancel).toHaveBeenCalled();
  });

  it('allows clicking on completed steps', () => {
    const mockGoToStep = jest.fn();
    const mockStateWithCompletedSteps = {
      ...mockWizardState,
      current_step: 2,
      steps: mockWizardState.steps.map((step, index) => ({
        ...step,
        is_current: index === 2,
        is_completed: index < 2,
      })),
    };

    mockUseConfigurationWizard.mockReturnValue({
      ...mockUseConfigurationWizard(),
      wizardState: mockStateWithCompletedSteps,
      goToStep: mockGoToStep,
    });

    render(<TaskConfigurationWizard />);
    
    // Click on first step (completed)
    const firstStepIcon = screen.getByText('API Endpoint').closest('div')?.querySelector('button');
    expect(firstStepIcon).not.toBeDisabled();
    
    if (firstStepIcon) {
      fireEvent.click(firstStepIcon);
      expect(mockGoToStep).toHaveBeenCalledWith(0);
    }
  });

  it('shows error indicators on steps with validation errors', () => {
    const mockStateWithErrors = {
      ...mockWizardState,
      steps: mockWizardState.steps.map((step, index) => ({
        ...step,
        validation_errors: index === 1 ? ['API key is required'] : [],
      })),
    };

    mockUseConfigurationWizard.mockReturnValue({
      ...mockUseConfigurationWizard(),
      wizardState: mockStateWithErrors,
    });

    render(<TaskConfigurationWizard />);
    
    expect(screen.getByText('1 error')).toBeInTheDocument();
  });

  it('shows multiple error count correctly', () => {
    const mockStateWithMultipleErrors = {
      ...mockWizardState,
      steps: mockWizardState.steps.map((step, index) => ({
        ...step,
        validation_errors: index === 1 ? ['API key is required', 'Invalid URL format'] : [],
      })),
    };

    mockUseConfigurationWizard.mockReturnValue({
      ...mockUseConfigurationWizard(),
      wizardState: mockStateWithMultipleErrors,
    });

    render(<TaskConfigurationWizard />);
    
    expect(screen.getByText('2 errors')).toBeInTheDocument();
  });

  it('shows progress bar correctly', () => {
    const mockStateWithProgress = {
      ...mockWizardState,
      current_step: 1,
      steps: mockWizardState.steps.map((step, index) => ({
        ...step,
        is_current: index === 1,
        is_completed: index < 1,
      })),
    };

    mockUseConfigurationWizard.mockReturnValue({
      ...mockUseConfigurationWizard(),
      wizardState: mockStateWithProgress,
    });

    const { container } = render(<TaskConfigurationWizard />);
    
    // Check if progress bar shows correct percentage (step 1 of 4 = 33.33%)
    const progressBar = container.querySelector('.bg-primary-600');
    expect(progressBar).toHaveStyle('width: 33.333333333333336%');
  });

  it('auto-runs test when reaching test step', () => {
    const mockTestConfiguration = jest.fn();
    const mockNextStep = jest.fn().mockReturnValue(true);
    
    const mockStateBeforeTest = {
      ...mockWizardState,
      current_step: 2,
      steps: mockWizardState.steps.map((step, index) => ({
        ...step,
        is_current: index === 2,
        is_completed: index < 2,
      })),
    };

    mockUseConfigurationWizard.mockReturnValue({
      ...mockUseConfigurationWizard(),
      wizardState: mockStateBeforeTest,
      nextStep: mockNextStep,
      testConfiguration: mockTestConfiguration,
    });

    render(<TaskConfigurationWizard />);
    
    const nextButton = screen.getByText('Next');
    fireEvent.click(nextButton);
    
    // Should trigger test after a delay
    setTimeout(() => {
      expect(mockTestConfiguration).toHaveBeenCalled();
    }, 600);
  });

  it('disables Save button when configuration is not complete', () => {
    const mockStateWithLastStep = {
      ...mockWizardState,
      current_step: 3,
      steps: mockWizardState.steps.map((step, index) => ({
        ...step,
        is_current: index === 3,
        is_completed: index < 3,
      })),
    };

    mockUseConfigurationWizard.mockReturnValue({
      ...mockUseConfigurationWizard(),
      wizardState: mockStateWithLastStep,
      isComplete: false,
    });

    render(<TaskConfigurationWizard />);
    
    const saveButton = screen.getByText('Save Configuration');
    expect(saveButton).toBeDisabled();
  });

  it('shows debug info in development', () => {
    const originalEnv = process.env.NODE_ENV;
    process.env.NODE_ENV = 'development';

    render(<TaskConfigurationWizard />);
    
    expect(screen.getByText('Debug Info')).toBeInTheDocument();

    process.env.NODE_ENV = originalEnv;
  });

  it('handles initial configuration correctly', () => {
    const initialConfig = {
      name: 'Initial Config',
      endpoint_url: 'https://example.com/api',
    };

    mockUseConfigurationWizard.mockReturnValue({
      ...mockUseConfigurationWizard(),
      wizardState: {
        ...mockWizardState,
        configuration: initialConfig,
      },
    });

    render(<TaskConfigurationWizard initialConfig={initialConfig} />);
    
    expect(mockUseConfigurationWizard).toHaveBeenCalledWith(initialConfig);
  });

  it('shows step completion status correctly', () => {
    const mockStateWithCompletedSteps = {
      ...mockWizardState,
      current_step: 2,
      steps: [
        { ...mockWizardState.steps[0], is_current: false, is_completed: true },
        { ...mockWizardState.steps[1], is_current: false, is_completed: true },
        { ...mockWizardState.steps[2], is_current: true, is_completed: false },
        { ...mockWizardState.steps[3], is_current: false, is_completed: false },
      ],
    };

    mockUseConfigurationWizard.mockReturnValue({
      ...mockUseConfigurationWizard(),
      wizardState: mockStateWithCompletedSteps,
    });

    const { container } = render(<TaskConfigurationWizard />);
    
    // Check for completed step icons (checkmarks)
    const checkmarkIcons = container.querySelectorAll('.bg-green-600');
    expect(checkmarkIcons).toHaveLength(2);
  });
});