'use client';

import React, { useState } from 'react';
import { Card } from '../card';
import { Button } from '../button';
import { Badge } from '../badge';
import { Textarea } from '../textarea';
import { Loading } from '../loading';
import { TaskConfiguration, ConfigurationWizardState } from '@/types';

interface TestStepProps {
  configuration: Partial<TaskConfiguration>;
  wizardState: ConfigurationWizardState;
  onTest: (testInput?: Record<string, any>) => Promise<any>;
  isTestLoading: boolean;
  errors: string[];
}

export function TestStep({ configuration, wizardState, onTest, isTestLoading, errors }: TestStepProps) {
  const [testInput, setTestInput] = useState(() => {
    return JSON.stringify({
      input: "What is the capital of France? Please provide a brief answer."
    }, null, 2);
  });

  const [customInput, setCustomInput] = useState(false);

  const handleTest = async () => {
    let inputData: Record<string, any> = {};
    
    if (customInput && testInput.trim()) {
      try {
        inputData = JSON.parse(testInput);
      } catch (err) {
        alert('Invalid JSON format in test input');
        return;
      }
    } else if (!customInput) {
      inputData = { input: "What is the capital of France? Please provide a brief answer." };
    }

    await onTest(inputData);
  };

  const getStatusIcon = () => {
    if (isTestLoading) {
      return <Loading size="sm" />;
    }

    if (wizardState.test_results?.success) {
      return (
        <svg className="w-5 h-5 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
      );
    }

    if (wizardState.test_results && !wizardState.test_results.success) {
      return (
        <svg className="w-5 h-5 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      );
    }

    return (
      <svg className="w-5 h-5 text-neutral-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    );
  };

  const formatResponseTime = (ms: number) => {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
  };

  const sampleInputs = [
    {
      label: 'Simple Question',
      data: { input: "What is the capital of France? Please provide a brief answer." }
    },
    {
      label: 'Complex Reasoning',
      data: { input: "Explain the difference between artificial intelligence and machine learning, including their relationship and key applications." }
    },
    {
      label: 'Creative Writing',
      data: { input: "Write a short poem about the changing seasons." }
    }
  ];

  const applySampleInput = (sampleData: Record<string, any>) => {
    setTestInput(JSON.stringify(sampleData, null, 2));
    setCustomInput(true);
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-2">
          Test Your Configuration
        </h3>
        <p className="text-sm text-neutral-500 dark:text-neutral-400 mb-4">
          Verify that your API configuration works correctly by running a test request.
        </p>
      </div>

      {/* Configuration Summary */}
      <Card className="p-4 bg-neutral-50 dark:bg-neutral-800">
        <h4 className="font-medium text-neutral-900 dark:text-white mb-3">Configuration Summary</h4>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
          <div>
            <span className="text-neutral-500 dark:text-neutral-400">Endpoint:</span>
            <span className="ml-2 font-mono text-neutral-900 dark:text-white">
              {configuration.endpoint?.method} {configuration.endpoint?.url}
            </span>
          </div>
          <div>
            <span className="text-neutral-500 dark:text-neutral-400">Authentication:</span>
            <span className="ml-2 text-neutral-900 dark:text-white">
              {configuration.auth?.type === 'none' ? 'None' : configuration.auth?.type?.toUpperCase()}
            </span>
          </div>
          <div>
            <span className="text-neutral-500 dark:text-neutral-400">Input Field:</span>
            <span className="ml-2 font-mono text-neutral-900 dark:text-white">
              {configuration.request_mapping?.input_field}
            </span>
          </div>
          <div>
            <span className="text-neutral-500 dark:text-neutral-400">Output Field:</span>
            <span className="ml-2 font-mono text-neutral-900 dark:text-white">
              {configuration.response_mapping?.output_field}
            </span>
          </div>
        </div>
      </Card>

      {/* Test Input Configuration */}
      <div>
        <h4 className="font-medium text-neutral-900 dark:text-white mb-3">Test Input</h4>
        
        <div className="space-y-4">
          {/* Input Type Selection */}
          <div className="flex gap-4">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                checked={!customInput}
                onChange={() => setCustomInput(false)}
                className="text-primary-600 focus:ring-primary-500"
              />
              <span className="text-sm text-neutral-700 dark:text-neutral-300">Use default test input</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                checked={customInput}
                onChange={() => setCustomInput(true)}
                className="text-primary-600 focus:ring-primary-500"
              />
              <span className="text-sm text-neutral-700 dark:text-neutral-300">Use custom JSON input</span>
            </label>
          </div>

          {/* Sample Inputs */}
          {customInput && (
            <div>
              <p className="text-sm text-neutral-500 dark:text-neutral-400 mb-2">
                Quick samples:
              </p>
              <div className="flex gap-2 flex-wrap">
                {sampleInputs.map((sample, index) => (
                  <Button
                    key={index}
                    variant="neutral"
                    size="sm"
                    onClick={() => applySampleInput(sample.data)}
                  >
                    {sample.label}
                  </Button>
                ))}
              </div>
            </div>
          )}

          {/* Custom Input */}
          {customInput && (
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
                Test Input (JSON)
              </label>
              <Textarea
                value={testInput}
                onChange={(e) => setTestInput(e.target.value)}
                placeholder='{"input": "Your test input here"}'
                rows={6}
                className="font-mono"
              />
              <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-1">
                JSON object that will be used as test data
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Test Button */}
      <div className="flex justify-center">
        <Button
          variant="primary"
          onClick={handleTest}
          disabled={isTestLoading}
          className="px-8"
        >
          {isTestLoading ? (
            <>
              <Loading size="sm" className="mr-2" />
              Testing Connection...
            </>
          ) : (
            <>
              <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.828 14.828a4 4 0 01-5.656 0M9 10h1.586a1 1 0 01.707.293l2.414 2.414a1 1 0 00.707.293H15M9 10v4a1 1 0 001 1h4M9 10V9a1 1 0 011-1h4a1 1 0 011 1v1M13 7h6l1 1v4" />
              </svg>
              Test Connection
            </>
          )}
        </Button>
      </div>

      {/* Test Results */}
      {wizardState.test_results && (
        <Card className={`p-6 ${
          wizardState.test_results.success
            ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800'
            : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'
        }`}>
          <div className="flex items-start gap-3 mb-4">
            {getStatusIcon()}
            <div className="flex-1">
              <h4 className={`font-medium ${
                wizardState.test_results.success
                  ? 'text-green-800 dark:text-green-300'
                  : 'text-red-800 dark:text-red-300'
              }`}>
                {wizardState.test_results.success ? 'Test Successful!' : 'Test Failed'}
              </h4>
              <p className={`text-sm ${
                wizardState.test_results.success
                  ? 'text-green-700 dark:text-green-400'
                  : 'text-red-700 dark:text-red-400'
              }`}>
                {wizardState.test_results.success
                  ? 'Your API configuration is working correctly.'
                  : wizardState.test_results.error || 'The test request failed.'
                }
              </p>
            </div>
            <Badge 
              variant={wizardState.test_results.success ? 'success' : 'danger'} 
              size="sm"
            >
              {formatResponseTime(wizardState.test_results.response_time)}
            </Badge>
          </div>

          {/* Response Data */}
          {wizardState.test_results.success && wizardState.test_results.response && (
            <div>
              <h5 className="font-medium text-neutral-900 dark:text-white mb-2">Response</h5>
              <div className="bg-white dark:bg-neutral-800 rounded border p-3">
                <pre className="text-sm text-neutral-700 dark:text-neutral-300 whitespace-pre-wrap font-mono overflow-x-auto">
                  {typeof wizardState.test_results.response === 'string' 
                    ? wizardState.test_results.response 
                    : JSON.stringify(wizardState.test_results.response, null, 2)
                  }
                </pre>
              </div>
            </div>
          )}
        </Card>
      )}

      {/* Next Steps */}
      {wizardState.test_results?.success && (
        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
          <div className="flex items-start gap-3">
            <svg className="w-5 h-5 text-blue-600 dark:text-blue-400 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <div>
              <h4 className="font-medium text-blue-800 dark:text-blue-300 mb-1">
                Configuration Ready!
              </h4>
              <p className="text-sm text-blue-700 dark:text-blue-400">
                Your task configuration has been tested successfully. You can now save it and use it for evaluations.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Troubleshooting */}
      {wizardState.test_results && !wizardState.test_results.success && (
        <div>
          <h4 className="font-medium text-neutral-900 dark:text-white mb-3">Troubleshooting Tips</h4>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Card className="p-4">
              <h5 className="font-medium text-neutral-900 dark:text-white mb-2">Common Issues</h5>
              <ul className="text-sm text-neutral-600 dark:text-neutral-400 space-y-1">
                <li>• Check if the API endpoint URL is correct</li>
                <li>• Verify authentication credentials</li>
                <li>• Ensure field mappings match API format</li>
                <li>• Check if the API is accessible from your network</li>
              </ul>
            </Card>
            
            <Card className="p-4">
              <h5 className="font-medium text-neutral-900 dark:text-white mb-2">Authentication Issues</h5>
              <ul className="text-sm text-neutral-600 dark:text-neutral-400 space-y-1">
                <li>• Verify API key or token is valid</li>
                <li>• Check if credentials have required permissions</li>
                <li>• Ensure correct authentication method</li>
                <li>• Verify header names and formats</li>
              </ul>
            </Card>
          </div>
        </div>
      )}

      {/* Validation Errors */}
      {errors.length > 0 && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
          <h4 className="font-medium text-red-800 dark:text-red-300 mb-2">
            Test Issues:
          </h4>
          <ul className="list-disc list-inside space-y-1 text-sm text-red-700 dark:text-red-400">
            {errors.map((error, index) => (
              <li key={index}>{error}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}