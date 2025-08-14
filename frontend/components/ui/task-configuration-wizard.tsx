'use client';

import React from 'react';
import { Card } from './card';
import { Button } from './button';
import { Badge } from './badge';
import { Loading } from './loading';
import { EndpointStep } from './wizard-steps/endpoint-step';
import { AuthStep } from './wizard-steps/auth-step';
import { MappingStep } from './wizard-steps/mapping-step';
import { TestStep } from './wizard-steps/test-step';
import { useConfigurationWizard, useTaskConfigurations } from '@/hooks/useTaskConfiguration';
import { TaskConfiguration } from '@/types';
import { cn } from '@/lib/utils';

interface TaskConfigurationWizardProps {
  onComplete?: (configuration: TaskConfiguration) => void;
  onCancel?: () => void;
  initialConfig?: Partial<TaskConfiguration>;
  className?: string;
}

export function TaskConfigurationWizard({
  onComplete,
  onCancel,
  initialConfig,
  className
}: TaskConfigurationWizardProps) {
  const {
    wizardState,
    updateConfiguration,
    validateCurrentStep,
    nextStep,
    prevStep,
    goToStep,
    testConfiguration,
    testLoading,
    reset,
    isComplete
  } = useConfigurationWizard(initialConfig);

  const { createConfiguration } = useTaskConfigurations();
  const [saving, setSaving] = React.useState(false);

  const currentStep = wizardState.steps[wizardState.current_step];
  const canGoNext = wizardState.current_step < wizardState.steps.length - 1;
  const canGoPrev = wizardState.current_step > 0;
  const isLastStep = wizardState.current_step === wizardState.steps.length - 1;

  const handleNext = () => {
    if (nextStep() && isLastStep) {
      // Auto-run test when reaching test step
      setTimeout(() => {
        testConfiguration();
      }, 500);
    }
  };

  const handleSave = async () => {
    if (!validateCurrentStep()) return;

    try {
      setSaving(true);
      const config = await createConfiguration(
        wizardState.configuration as Omit<TaskConfiguration, 'id' | 'created_at' | 'updated_at'>
      );
      onComplete?.(config);
    } catch (err) {
      console.error('Failed to save configuration:', err);
      alert('Failed to save configuration. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  const renderStepContent = () => {
    const stepProps = {
      configuration: wizardState.configuration,
      onUpdate: updateConfiguration,
      errors: currentStep.validation_errors || []
    };

    switch (currentStep.id) {
      case 'endpoint':
        return <EndpointStep {...stepProps} />;
      case 'auth':
        return <AuthStep {...stepProps} />;
      case 'mapping':
        return <MappingStep {...stepProps} />;
      case 'test':
        return (
          <TestStep
            {...stepProps}
            wizardState={wizardState}
            onTest={testConfiguration}
            isTestLoading={testLoading}
          />
        );
      default:
        return null;
    }
  };

  const getStepStatus = (step: typeof wizardState.steps[0]) => {
    if (step.is_current) return 'current';
    if (step.is_completed) return 'completed';
    if ((step.validation_errors?.length || 0) > 0) return 'error';
    return 'pending';
  };

  const getStepIcon = (step: typeof wizardState.steps[0], status: string) => {
    if (status === 'current') {
      return (
        <div className="w-8 h-8 bg-primary-600 text-white rounded-full flex items-center justify-center">
          <span className="text-sm font-medium">{wizardState.current_step + 1}</span>
        </div>
      );
    } else if (status === 'completed') {
      return (
        <div className="w-8 h-8 bg-green-600 text-white rounded-full flex items-center justify-center">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        </div>
      );
    } else if (status === 'error') {
      return (
        <div className="w-8 h-8 bg-red-600 text-white rounded-full flex items-center justify-center">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </div>
      );
    } else {
      return (
        <div className="w-8 h-8 bg-neutral-200 dark:bg-neutral-700 text-neutral-500 dark:text-neutral-400 rounded-full flex items-center justify-center">
          <span className="text-sm font-medium">{wizardState.steps.indexOf(step) + 1}</span>
        </div>
      );
    }
  };

  return (
    <div className={cn('max-w-6xl mx-auto', className)}>
      <Card className="p-6">
        {/* Header */}
        <div className="mb-8">
          <h2 className="text-2xl font-semibold text-neutral-900 dark:text-white mb-2">
            Task Configuration Wizard
          </h2>
          <p className="text-neutral-500 dark:text-neutral-400">
            Set up a new API endpoint configuration for evaluation tasks
          </p>
        </div>

        {/* Progress Steps */}
        <div className="mb-8">
          <div className="flex items-center justify-between relative">
            {/* Progress Line */}
            <div className="absolute top-4 left-4 right-4 h-0.5 bg-neutral-200 dark:bg-neutral-700 -z-10">
              <div 
                className="h-full bg-primary-600 transition-all duration-300"
                style={{ 
                  width: `${(wizardState.current_step / (wizardState.steps.length - 1)) * 100}%` 
                }}
              />
            </div>

            {/* Step Indicators */}
            {wizardState.steps.map((step, index) => {
              const status = getStepStatus(step);
              const isClickable = index <= wizardState.current_step || step.is_completed;
              
              return (
                <div key={step.id} className="flex flex-col items-center relative">
                  <button
                    onClick={isClickable ? () => goToStep(index) : undefined}
                    className={cn(
                      'transition-all duration-200',
                      isClickable ? 'cursor-pointer hover:scale-105' : 'cursor-default'
                    )}
                    disabled={!isClickable}
                  >
                    {getStepIcon(step, status)}
                  </button>
                  <div className="mt-2 text-center max-w-24">
                    <p className={cn(
                      'text-xs font-medium',
                      status === 'current' && 'text-primary-600 dark:text-primary-400',
                      status === 'completed' && 'text-green-600 dark:text-green-400',
                      status === 'error' && 'text-red-600 dark:text-red-400',
                      status === 'pending' && 'text-neutral-500 dark:text-neutral-400'
                    )}>
                      {step.title}
                    </p>
                  </div>
                  
                  {/* Error indicator */}
                  {(step.validation_errors?.length || 0) > 0 && (
                    <Badge variant="danger" size="sm" className="mt-1">
                      {step.validation_errors!.length} error{step.validation_errors!.length !== 1 ? 's' : ''}
                    </Badge>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Step Content */}
        <div className="mb-8">
          <div className="mb-4">
            <h3 className="text-lg font-semibold text-neutral-900 dark:text-white">
              {currentStep.title}
            </h3>
            <p className="text-sm text-neutral-500 dark:text-neutral-400">
              {currentStep.description}
            </p>
          </div>

          {renderStepContent()}
        </div>

        {/* Navigation */}
        <div className="flex items-center justify-between pt-6 border-t border-neutral-200 dark:border-neutral-700">
          <div>
            {canGoPrev && (
              <Button variant="neutral" onClick={prevStep}>
                <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                </svg>
                Previous
              </Button>
            )}
          </div>

          <div className="flex items-center gap-3">
            <Button variant="neutral" onClick={onCancel}>
              Cancel
            </Button>

            {isLastStep ? (
              <Button
                variant="primary"
                onClick={handleSave}
                disabled={!isComplete || saving}
              >
                {saving ? (
                  <>
                    <Loading size="sm" className="mr-2" />
                    Saving...
                  </>
                ) : (
                  <>
                    <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                    Save Configuration
                  </>
                )}
              </Button>
            ) : (
              <Button
                variant="primary"
                onClick={handleNext}
                disabled={!canGoNext}
              >
                Next
                <svg className="w-4 h-4 ml-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </Button>
            )}
          </div>
        </div>

        {/* Debug Info (development only) */}
        {process.env.NODE_ENV === 'development' && (
          <details className="mt-4">
            <summary className="cursor-pointer text-xs text-neutral-500">Debug Info</summary>
            <pre className="mt-2 p-2 bg-neutral-100 dark:bg-neutral-800 rounded text-xs overflow-auto">
              {JSON.stringify(wizardState, null, 2)}
            </pre>
          </details>
        )}
      </Card>
    </div>
  );
}