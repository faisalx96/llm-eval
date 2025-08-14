'use client';

import React, { useState } from 'react';
import { Card } from '../card';
import { Input } from '../input';
import { Select } from '../select';
import { Button } from '../button';
import { Badge } from '../badge';
import { Textarea } from '../textarea';
import { TaskConfiguration } from '@/types';

interface EndpointStepProps {
  configuration: Partial<TaskConfiguration>;
  onUpdate: (updates: Partial<TaskConfiguration>) => void;
  errors: string[];
}

export function EndpointStep({ configuration, onUpdate, errors }: EndpointStepProps) {
  const [customHeaders, setCustomHeaders] = useState(() => {
    const headers = configuration.endpoint?.headers || {};
    return Object.entries(headers).map(([key, value], index) => ({
      id: index,
      key,
      value
    }));
  });

  const [nextHeaderId, setNextHeaderId] = useState(customHeaders.length);

  const handleBasicChange = (field: string, value: any) => {
    if (field === 'name' || field === 'description') {
      onUpdate({ [field]: value });
    } else {
      onUpdate({
        endpoint: {
          ...configuration.endpoint!,
          [field]: value
        }
      });
    }
  };

  const addHeader = () => {
    setCustomHeaders(prev => [...prev, { id: nextHeaderId, key: '', value: '' }]);
    setNextHeaderId(prev => prev + 1);
  };

  const updateHeader = (id: number, field: 'key' | 'value', value: string) => {
    setCustomHeaders(prev => {
      const updated = prev.map(header => 
        header.id === id ? { ...header, [field]: value } : header
      );
      
      // Update configuration
      const headers: Record<string, string> = {};
      updated.forEach(header => {
        if (header.key && header.value) {
          headers[header.key] = header.value;
        }
      });
      
      onUpdate({
        endpoint: {
          ...configuration.endpoint!,
          headers
        }
      });
      
      return updated;
    });
  };

  const removeHeader = (id: number) => {
    setCustomHeaders(prev => {
      const filtered = prev.filter(header => header.id !== id);
      
      // Update configuration
      const headers: Record<string, string> = {};
      filtered.forEach(header => {
        if (header.key && header.value) {
          headers[header.key] = header.value;
        }
      });
      
      onUpdate({
        endpoint: {
          ...configuration.endpoint!,
          headers
        }
      });
      
      return filtered;
    });
  };

  const commonHeaders = [
    { label: 'Content-Type: application/json', key: 'Content-Type', value: 'application/json' },
    { label: 'Accept: application/json', key: 'Accept', value: 'application/json' },
    { label: 'User-Agent: LLM-Eval/1.0', key: 'User-Agent', value: 'LLM-Eval/1.0' }
  ];

  const addCommonHeader = (key: string, value: string) => {
    const existingIndex = customHeaders.findIndex(h => h.key === key);
    if (existingIndex >= 0) {
      updateHeader(customHeaders[existingIndex].id, 'value', value);
    } else {
      setCustomHeaders(prev => {
        const newHeader = { id: nextHeaderId, key, value };
        setNextHeaderId(nextHeaderId + 1);
        
        // Update configuration
        onUpdate({
          endpoint: {
            ...configuration.endpoint!,
            headers: {
              ...configuration.endpoint?.headers,
              [key]: value
            }
          }
        });
        
        return [...prev, newHeader];
      });
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-2">
          Basic Configuration
        </h3>
        <p className="text-sm text-neutral-500 dark:text-neutral-400 mb-4">
          Provide basic information about your task configuration.
        </p>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
              Configuration Name *
            </label>
            <Input
              type="text"
              value={configuration.name || ''}
              onChange={(e) => handleBasicChange('name', e.target.value)}
              placeholder="e.g., My GPT-4 API"
              error={errors.some(e => e.includes('name'))}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
              Description
            </label>
            <Textarea
              value={configuration.description || ''}
              onChange={(e) => handleBasicChange('description', e.target.value)}
              placeholder="Optional description of this configuration..."
              rows={3}
            />
          </div>
        </div>
      </div>

      <div>
        <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-2">
          API Endpoint
        </h3>
        <p className="text-sm text-neutral-500 dark:text-neutral-400 mb-4">
          Configure the API endpoint that will be called for evaluation.
        </p>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
              Endpoint URL *
            </label>
            <Input
              type="url"
              value={configuration.endpoint?.url || ''}
              onChange={(e) => handleBasicChange('url', e.target.value)}
              placeholder="https://api.openai.com/v1/chat/completions"
              error={errors.some(e => e.includes('URL') || e.includes('url'))}
            />
            <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-1">
              The full URL to your API endpoint
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
                HTTP Method
              </label>
              <Select
                value={configuration.endpoint?.method || 'POST'}
                onValueChange={(value) => handleBasicChange('method', value)}
                options={[
                  { value: 'GET', label: 'GET' },
                  { value: 'POST', label: 'POST' },
                  { value: 'PUT', label: 'PUT' },
                  { value: 'PATCH', label: 'PATCH' }
                ]}
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
                Timeout (seconds)
              </label>
              <Input
                type="number"
                value={((configuration.endpoint?.timeout || 30000) / 1000).toString()}
                onChange={(e) => handleBasicChange('timeout', parseInt(e.target.value) * 1000)}
                min={1}
                max={300}
                placeholder="30"
              />
            </div>
          </div>
        </div>
      </div>

      <div>
        <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-2">
          Request Headers
        </h3>
        <p className="text-sm text-neutral-500 dark:text-neutral-400 mb-4">
          Add any custom headers required by your API.
        </p>

        {/* Common Headers */}
        <div className="mb-4">
          <p className="text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
            Common Headers
          </p>
          <div className="flex gap-2 flex-wrap">
            {commonHeaders.map((header) => (
              <Button
                key={header.key}
                variant="neutral"
                size="sm"
                onClick={() => addCommonHeader(header.key, header.value)}
                disabled={customHeaders.some(h => h.key === header.key)}
              >
                {header.label}
              </Button>
            ))}
          </div>
        </div>

        {/* Custom Headers */}
        <Card className="p-4">
          <div className="space-y-3">
            {customHeaders.map((header) => (
              <div key={header.id} className="flex gap-3 items-center">
                <div className="flex-1">
                  <Input
                    type="text"
                    value={header.key}
                    onChange={(e) => updateHeader(header.id, 'key', e.target.value)}
                    placeholder="Header name"
                  />
                </div>
                <div className="flex-1">
                  <Input
                    type="text"
                    value={header.value}
                    onChange={(e) => updateHeader(header.id, 'value', e.target.value)}
                    placeholder="Header value"
                  />
                </div>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => removeHeader(header.id)}
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </Button>
              </div>
            ))}
            
            {customHeaders.length === 0 && (
              <p className="text-sm text-neutral-500 dark:text-neutral-400 text-center py-4">
                No custom headers added yet
              </p>
            )}
            
            <Button
              variant="neutral"
              onClick={addHeader}
              className="w-full"
            >
              <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              Add Header
            </Button>
          </div>
        </Card>
      </div>

      {/* Validation Errors */}
      {errors.length > 0 && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
          <h4 className="font-medium text-red-800 dark:text-red-300 mb-2">
            Please fix the following errors:
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