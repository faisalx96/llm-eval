import { useState, useEffect, useMemo } from 'react';
import { apiClient } from '@/lib/api';
import { TaskConfiguration, ConfigurationWizardState, WizardStep } from '@/types';

const WIZARD_STEPS: Omit<WizardStep, 'is_completed' | 'is_current' | 'validation_errors'>[] = [
  {
    id: 'endpoint',
    title: 'Endpoint Configuration',
    description: 'Configure your API endpoint details'
  },
  {
    id: 'auth',
    title: 'Authentication',
    description: 'Set up authentication credentials'
  },
  {
    id: 'mapping',
    title: 'Data Mapping',
    description: 'Map request and response fields'
  },
  {
    id: 'test',
    title: 'Test Connection',
    description: 'Verify your configuration works'
  }
];

export function useTaskConfigurations() {
  const [configurations, setConfigurations] = useState<TaskConfiguration[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchConfigurations = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const response = await apiClient.getTaskConfigurations();
      setConfigurations(response);
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Failed to fetch configurations'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConfigurations();
  }, []);

  const createConfiguration = async (config: Omit<TaskConfiguration, 'id' | 'created_at' | 'updated_at'>) => {
    try {
      const response = await apiClient.createTaskConfiguration(config);
      setConfigurations(prev => [...prev, response]);
      return response;
    } catch (err) {
      throw err instanceof Error ? err : new Error('Failed to create configuration');
    }
  };

  const updateConfiguration = async (id: string, updates: Partial<TaskConfiguration>) => {
    try {
      const response = await apiClient.updateTaskConfiguration(id, updates);
      setConfigurations(prev => prev.map(c => c.id === id ? response : c));
      return response;
    } catch (err) {
      throw err instanceof Error ? err : new Error('Failed to update configuration');
    }
  };

  const deleteConfiguration = async (id: string) => {
    try {
      await apiClient.deleteTaskConfiguration(id);
      setConfigurations(prev => prev.filter(c => c.id !== id));
    } catch (err) {
      throw err instanceof Error ? err : new Error('Failed to delete configuration');
    }
  };

  return {
    configurations,
    loading,
    error,
    refetch: fetchConfigurations,
    createConfiguration,
    updateConfiguration,
    deleteConfiguration
  };
}

export function useTaskConfiguration(configId: string | null) {
  const [configuration, setConfiguration] = useState<TaskConfiguration | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const fetchConfiguration = async () => {
    if (!configId) return;
    
    try {
      setLoading(true);
      setError(null);
      
      const response = await apiClient.getTaskConfiguration(configId);
      setConfiguration(response);
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Failed to fetch configuration'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConfiguration();
  }, [configId]);

  return {
    configuration,
    loading,
    error,
    refetch: fetchConfiguration
  };
}

export function useConfigurationWizard(initialConfig?: Partial<TaskConfiguration>) {
  const [wizardState, setWizardState] = useState<ConfigurationWizardState>(() => {
    return {
      current_step: 0,
      steps: WIZARD_STEPS.map((step, index) => ({
        ...step,
        is_completed: false,
        is_current: index === 0,
        validation_errors: []
      })),
      configuration: initialConfig || {
        name: '',
        description: '',
        endpoint: {
          url: '',
          method: 'POST',
          headers: {},
          timeout: 30000
        },
        auth: {
          type: 'none'
        },
        request_mapping: {
          input_field: 'input',
          additional_fields: {}
        },
        response_mapping: {
          output_field: 'output'
        }
      }
    };
  });

  const [testLoading, setTestLoading] = useState(false);

  const updateConfiguration = (updates: Partial<TaskConfiguration>) => {
    setWizardState(prev => ({
      ...prev,
      configuration: {
        ...prev.configuration,
        ...updates
      }
    }));
  };

  const validateCurrentStep = () => {
    const currentStep = wizardState.steps[wizardState.current_step];
    const config = wizardState.configuration;
    const errors: string[] = [];

    switch (currentStep.id) {
      case 'endpoint':
        if (!config.name?.trim()) errors.push('Configuration name is required');
        if (!config.endpoint?.url?.trim()) errors.push('API endpoint URL is required');
        if (config.endpoint?.url && !isValidUrl(config.endpoint.url)) errors.push('Please enter a valid URL');
        break;

      case 'auth':
        if (config.auth?.type === 'bearer' && !config.auth?.credentials?.token) {
          errors.push('Bearer token is required');
        }
        if (config.auth?.type === 'api_key') {
          if (!config.auth?.credentials?.key) errors.push('API key is required');
          if (!config.auth?.credentials?.header_name) errors.push('Header name is required');
        }
        break;

      case 'mapping':
        if (!config.request_mapping?.input_field?.trim()) {
          errors.push('Input field mapping is required');
        }
        if (!config.response_mapping?.output_field?.trim()) {
          errors.push('Output field mapping is required');
        }
        break;

      case 'test':
        // Test step validation happens during test execution
        break;
    }

    setWizardState(prev => ({
      ...prev,
      steps: prev.steps.map((step, index) =>
        index === prev.current_step
          ? { ...step, validation_errors: errors }
          : step
      )
    }));

    return errors.length === 0;
  };

  const nextStep = () => {
    if (!validateCurrentStep()) return false;

    setWizardState(prev => {
      const nextStepIndex = Math.min(prev.current_step + 1, prev.steps.length - 1);
      
      return {
        ...prev,
        current_step: nextStepIndex,
        steps: prev.steps.map((step, index) => ({
          ...step,
          is_completed: index < nextStepIndex,
          is_current: index === nextStepIndex
        }))
      };
    });

    return true;
  };

  const prevStep = () => {
    setWizardState(prev => {
      const prevStepIndex = Math.max(prev.current_step - 1, 0);
      
      return {
        ...prev,
        current_step: prevStepIndex,
        steps: prev.steps.map((step, index) => ({
          ...step,
          is_completed: index < prevStepIndex,
          is_current: index === prevStepIndex,
          validation_errors: index === prevStepIndex ? [] : step.validation_errors
        }))
      };
    });
  };

  const goToStep = (stepIndex: number) => {
    if (stepIndex < 0 || stepIndex >= wizardState.steps.length) return;

    setWizardState(prev => ({
      ...prev,
      current_step: stepIndex,
      steps: prev.steps.map((step, index) => ({
        ...step,
        is_completed: index < stepIndex,
        is_current: index === stepIndex,
        validation_errors: index === stepIndex ? [] : step.validation_errors
      }))
    }));
  };

  const testConfiguration = async (testInput?: Record<string, any>) => {
    try {
      setTestLoading(true);
      
      const response = await apiClient.testTaskConfiguration(
        wizardState.configuration as Omit<TaskConfiguration, 'id' | 'created_at' | 'updated_at'>,
        testInput
      );
      
      setWizardState(prev => ({
        ...prev,
        test_results: response
      }));

      // Mark test step as completed if successful
      if (response.success) {
        setWizardState(prev => ({
          ...prev,
          steps: prev.steps.map((step, index) =>
            step.id === 'test'
              ? { ...step, is_completed: true, validation_errors: [] }
              : step
          )
        }));
      } else {
        setWizardState(prev => ({
          ...prev,
          steps: prev.steps.map((step, index) =>
            step.id === 'test'
              ? { ...step, validation_errors: [response.error || 'Test failed'] }
              : step
          )
        }));
      }

      return response;
    } catch (err) {
      const error = err instanceof Error ? err.message : 'Test failed';
      
      setWizardState(prev => ({
        ...prev,
        test_results: {
          success: false,
          error,
          response_time: 0
        },
        steps: prev.steps.map((step, index) =>
          step.id === 'test'
            ? { ...step, validation_errors: [error] }
            : step
        )
      }));
      
      throw err;
    } finally {
      setTestLoading(false);
    }
  };

  const reset = () => {
    setWizardState(prev => ({
      ...prev,
      current_step: 0,
      steps: prev.steps.map((step, index) => ({
        ...step,
        is_completed: false,
        is_current: index === 0,
        validation_errors: []
      })),
      test_results: undefined
    }));
  };

  const isValid = useMemo(() => {
    return wizardState.steps.every(step => step.validation_errors?.length === 0);
  }, [wizardState.steps]);

  const isComplete = useMemo(() => {
    return wizardState.steps.every(step => step.is_completed);
  }, [wizardState.steps]);

  return {
    wizardState,
    updateConfiguration,
    validateCurrentStep,
    nextStep,
    prevStep,
    goToStep,
    testConfiguration,
    testLoading,
    reset,
    isValid,
    isComplete
  };
}

function isValidUrl(string: string): boolean {
  try {
    new URL(string);
    return true;
  } catch (_) {
    return false;
  }
}