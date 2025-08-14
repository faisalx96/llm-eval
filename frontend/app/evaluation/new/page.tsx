'use client';

import React, { useState } from 'react';
import { Container } from '@/components/layout/container';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs } from '@/components/ui/tabs';
import { DatasetBrowser } from '@/components/ui/dataset-browser';
import { TemplateMarketplace } from '@/components/ui/template-marketplace';
import { MetricSelector } from '@/components/ui/metric-selector';
import { TaskConfigurationWizard } from '@/components/ui/task-configuration-wizard';
import { Dataset, EvaluationTemplate, MetricSelection, TaskConfiguration } from '@/types';

type SetupStep = 'dataset' | 'template' | 'metrics' | 'task' | 'review';

interface EvaluationSetup {
  dataset?: Dataset;
  template?: EvaluationTemplate;
  metrics: MetricSelection[];
  taskConfig?: TaskConfiguration;
}

export default function NewEvaluationPage() {
  const [currentStep, setCurrentStep] = useState<SetupStep>('dataset');
  const [setup, setSetup] = useState<EvaluationSetup>({
    metrics: []
  });
  const [showTaskWizard, setShowTaskWizard] = useState(false);

  const steps = [
    { id: 'dataset' as const, label: 'Select Dataset', description: 'Choose your evaluation dataset' },
    { id: 'template' as const, label: 'Choose Template', description: 'Pick an evaluation template' },
    { id: 'metrics' as const, label: 'Select Metrics', description: 'Configure evaluation metrics' },
    { id: 'task' as const, label: 'Setup Task', description: 'Configure your API endpoint' },
    { id: 'review' as const, label: 'Review & Launch', description: 'Review and start evaluation' }
  ];

  const currentStepIndex = steps.findIndex(s => s.id === currentStep);
  const canGoNext = currentStepIndex < steps.length - 1;
  const canGoPrev = currentStepIndex > 0;

  const handleNext = () => {
    if (canGoNext) {
      setCurrentStep(steps[currentStepIndex + 1].id);
    }
  };

  const handlePrevious = () => {
    if (canGoPrev) {
      setCurrentStep(steps[currentStepIndex - 1].id);
    }
  };

  const handleDatasetSelect = (dataset: Dataset) => {
    setSetup(prev => ({ ...prev, dataset }));
  };

  const handleTemplateSelect = (template: EvaluationTemplate) => {
    setSetup(prev => ({ ...prev, template }));
  };

  const handleMetricsChange = (metrics: MetricSelection[]) => {
    setSetup(prev => ({ ...prev, metrics }));
  };

  const handleTaskConfigComplete = (taskConfig: TaskConfiguration) => {
    setSetup(prev => ({ ...prev, taskConfig }));
    setShowTaskWizard(false);
  };

  const isStepComplete = (stepId: SetupStep): boolean => {
    switch (stepId) {
      case 'dataset':
        return !!setup.dataset;
      case 'template':
        return !!setup.template;
      case 'metrics':
        return setup.metrics.length > 0;
      case 'task':
        return !!setup.taskConfig;
      case 'review':
        return !!(setup.dataset && setup.template && setup.metrics.length > 0 && setup.taskConfig);
      default:
        return false;
    }
  };

  const renderStepContent = () => {
    switch (currentStep) {
      case 'dataset':
        return (
          <DatasetBrowser
            onSelectDataset={handleDatasetSelect}
            selectedDatasetId={setup.dataset?.id}
            selectionMode={true}
          />
        );

      case 'template':
        return (
          <TemplateMarketplace
            onSelectTemplate={handleTemplateSelect}
            selectedTemplateId={setup.template?.id}
            selectionMode={true}
            showRecommendations={true}
          />
        );

      case 'metrics':
        return (
          <MetricSelector
            onSelectionChange={handleMetricsChange}
            initialSelections={setup.metrics}
            datasetId={setup.dataset?.id}
            compatibleTasks={setup.template?.use_cases}
          />
        );

      case 'task':
        if (showTaskWizard) {
          return (
            <TaskConfigurationWizard
              onComplete={handleTaskConfigComplete}
              onCancel={() => setShowTaskWizard(false)}
            />
          );
        }

        return (
          <div className="space-y-6">
            <div className="text-center py-12">
              <div className="w-16 h-16 mx-auto mb-4 bg-primary-100 dark:bg-primary-900/20 rounded-full flex items-center justify-center">
                <svg className="w-8 h-8 text-primary-600 dark:text-primary-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
              </div>
              <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-2">
                Task Configuration Required
              </h3>
              <p className="text-neutral-500 dark:text-neutral-400 mb-6">
                Set up your API endpoint configuration to enable evaluation execution.
              </p>
              <Button variant="primary" onClick={() => setShowTaskWizard(true)}>
                Configure API Endpoint
              </Button>
            </div>

            {setup.taskConfig && (
              <Card className="p-6 bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800">
                <div className="flex items-center gap-3 mb-4">
                  <div className="w-8 h-8 bg-green-600 rounded-full flex items-center justify-center">
                    <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  </div>
                  <div>
                    <h4 className="font-medium text-green-800 dark:text-green-300">
                      Configuration Complete
                    </h4>
                    <p className="text-sm text-green-700 dark:text-green-400">
                      {setup.taskConfig.name} is ready for evaluation
                    </p>
                  </div>
                </div>
              </Card>
            )}
          </div>
        );

      case 'review':
        return (
          <div className="space-y-6">
            <div>
              <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-2">
                Review Your Evaluation Setup
              </h3>
              <p className="text-neutral-500 dark:text-neutral-400">
                Review all settings before launching your evaluation.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Dataset Summary */}
              <Card className="p-6">
                <div className="flex items-center gap-3 mb-4">
                  <svg className="w-6 h-6 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
                  </svg>
                  <h4 className="font-medium text-neutral-900 dark:text-white">Dataset</h4>
                </div>
                {setup.dataset ? (
                  <div>
                    <p className="font-medium text-neutral-900 dark:text-white">{setup.dataset.name}</p>
                    <p className="text-sm text-neutral-500 dark:text-neutral-400 mt-1">
                      {setup.dataset.item_count.toLocaleString()} items
                    </p>
                    {setup.dataset.description && (
                      <p className="text-sm text-neutral-600 dark:text-neutral-300 mt-2">
                        {setup.dataset.description}
                      </p>
                    )}
                  </div>
                ) : (
                  <p className="text-red-500">No dataset selected</p>
                )}
              </Card>

              {/* Template Summary */}
              <Card className="p-6">
                <div className="flex items-center gap-3 mb-4">
                  <svg className="w-6 h-6 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  <h4 className="font-medium text-neutral-900 dark:text-white">Template</h4>
                </div>
                {setup.template ? (
                  <div>
                    <p className="font-medium text-neutral-900 dark:text-white">{setup.template.display_name}</p>
                    <Badge className="mt-2" variant="neutral" size="sm">
                      {setup.template.category}
                    </Badge>
                    <p className="text-sm text-neutral-600 dark:text-neutral-300 mt-2">
                      {setup.template.description}
                    </p>
                  </div>
                ) : (
                  <p className="text-red-500">No template selected</p>
                )}
              </Card>

              {/* Metrics Summary */}
              <Card className="p-6">
                <div className="flex items-center gap-3 mb-4">
                  <svg className="w-6 h-6 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2-2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                  </svg>
                  <h4 className="font-medium text-neutral-900 dark:text-white">Metrics</h4>
                </div>
                {setup.metrics.length > 0 ? (
                  <div>
                    <p className="text-sm text-neutral-600 dark:text-neutral-300 mb-2">
                      {setup.metrics.length} metric{setup.metrics.length !== 1 ? 's' : ''} selected
                    </p>
                    <div className="flex flex-wrap gap-1">
                      {setup.metrics.slice(0, 3).map(metric => (
                        <Badge key={metric.metric_id} variant="neutral" size="sm">
                          {metric.metric_id}
                        </Badge>
                      ))}
                      {setup.metrics.length > 3 && (
                        <Badge variant="neutral" size="sm">
                          +{setup.metrics.length - 3} more
                        </Badge>
                      )}
                    </div>
                  </div>
                ) : (
                  <p className="text-red-500">No metrics selected</p>
                )}
              </Card>

              {/* Task Config Summary */}
              <Card className="p-6">
                <div className="flex items-center gap-3 mb-4">
                  <svg className="w-6 h-6 text-orange-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                  </svg>
                  <h4 className="font-medium text-neutral-900 dark:text-white">API Configuration</h4>
                </div>
                {setup.taskConfig ? (
                  <div>
                    <p className="font-medium text-neutral-900 dark:text-white">{setup.taskConfig.name}</p>
                    <div className="text-sm text-neutral-600 dark:text-neutral-300 mt-2 space-y-1">
                      <div>
                        <span className="font-medium">Endpoint:</span>{' '}
                        {setup.taskConfig.endpoint.method} {setup.taskConfig.endpoint.url}
                      </div>
                      <div>
                        <span className="font-medium">Auth:</span>{' '}
                        {setup.taskConfig.auth.type === 'none' ? 'None' : setup.taskConfig.auth.type.toUpperCase()}
                      </div>
                    </div>
                  </div>
                ) : (
                  <p className="text-red-500">No task configuration</p>
                )}
              </Card>
            </div>

            {/* Launch Button */}
            <div className="text-center pt-6 border-t border-neutral-200 dark:border-neutral-700">
              <Button
                variant="primary"
                size="lg"
                disabled={!isStepComplete('review')}
                className="px-8"
              >
                <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.828 14.828a4 4 0 01-5.656 0M9 10h1.586a1 1 0 01.707.293l2.414 2.414a1 1 0 00.707.293H15M9 10v4a1 1 0 001 1h4M9 10V9a1 1 0 011-1h4a1 1 0 011 1v1M13 7h6l1 1v4" />
                </svg>
                Launch Evaluation
              </Button>
            </div>
          </div>
        );

      default:
        return null;
    }
  };

  if (showTaskWizard) {
    return (
      <Container>
        <div className="space-y-6">
          {renderStepContent()}
        </div>
      </Container>
    );
  }

  return (
    <Container>
      <div className="space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-2xl font-bold text-neutral-900 dark:text-white">
            Create New Evaluation
          </h1>
          <p className="text-neutral-500 dark:text-neutral-400 mt-1">
            Set up and configure a new evaluation run for your LLM application
          </p>
        </div>

        {/* Progress Steps */}
        <Card className="p-6">
          <div className="flex items-center justify-between relative">
            {/* Progress Line */}
            <div className="absolute top-4 left-4 right-4 h-0.5 bg-neutral-200 dark:bg-neutral-700 -z-10">
              <div 
                className="h-full bg-primary-600 transition-all duration-300"
                style={{ 
                  width: `${(currentStepIndex / (steps.length - 1)) * 100}%` 
                }}
              />
            </div>

            {/* Step Indicators */}
            {steps.map((step, index) => {
              const isCompleted = isStepComplete(step.id);
              const isCurrent = step.id === currentStep;
              const isClickable = index <= currentStepIndex || isCompleted;
              
              return (
                <div key={step.id} className="flex flex-col items-center relative">
                  <button
                    onClick={isClickable ? () => setCurrentStep(step.id) : undefined}
                    className={`w-8 h-8 rounded-full flex items-center justify-center transition-all duration-200 ${
                      isCurrent
                        ? 'bg-primary-600 text-white'
                        : isCompleted
                        ? 'bg-green-600 text-white'
                        : 'bg-neutral-200 dark:bg-neutral-700 text-neutral-500 dark:text-neutral-400'
                    } ${isClickable ? 'cursor-pointer hover:scale-105' : 'cursor-default'}`}
                    disabled={!isClickable}
                  >
                    {isCompleted && !isCurrent ? (
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                    ) : (
                      <span className="text-sm font-medium">{index + 1}</span>
                    )}
                  </button>
                  <div className="mt-2 text-center max-w-20">
                    <p className={`text-xs font-medium ${
                      isCurrent ? 'text-primary-600 dark:text-primary-400' : 'text-neutral-500 dark:text-neutral-400'
                    }`}>
                      {step.label}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>

        {/* Step Content */}
        <div className="min-h-96">
          <div className="mb-6">
            <h2 className="text-xl font-semibold text-neutral-900 dark:text-white">
              {steps[currentStepIndex].label}
            </h2>
            <p className="text-sm text-neutral-500 dark:text-neutral-400">
              {steps[currentStepIndex].description}
            </p>
          </div>

          {renderStepContent()}
        </div>

        {/* Navigation */}
        <div className="flex items-center justify-between pt-6 border-t border-neutral-200 dark:border-neutral-700">
          <div>
            {canGoPrev && (
              <Button variant="neutral" onClick={handlePrevious}>
                <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                </svg>
                Previous
              </Button>
            )}
          </div>

          <div className="flex items-center gap-3">
            {canGoNext && currentStep !== 'review' && (
              <Button
                variant="primary"
                onClick={handleNext}
                disabled={!isStepComplete(currentStep)}
              >
                Next
                <svg className="w-4 h-4 ml-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </Button>
            )}
          </div>
        </div>
      </div>
    </Container>
  );
}