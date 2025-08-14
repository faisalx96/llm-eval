'use client';

import React, { useState } from 'react';
import { Card } from '../card';
import { Input } from '../input';
import { Button } from '../button';
import { Badge } from '../badge';
import { Textarea } from '../textarea';
import { TaskConfiguration } from '@/types';

interface MappingStepProps {
  configuration: Partial<TaskConfiguration>;
  onUpdate: (updates: Partial<TaskConfiguration>) => void;
  errors: string[];
}

export function MappingStep({ configuration, onUpdate, errors }: MappingStepProps) {
  const [additionalFields, setAdditionalFields] = useState(() => {
    const fields = configuration.request_mapping?.additional_fields || {};
    return Object.entries(fields).map(([key, value], index) => ({
      id: index,
      key,
      value: typeof value === 'string' ? value : JSON.stringify(value)
    }));
  });

  const [nextFieldId, setNextFieldId] = useState(additionalFields.length);
  const [samplePayload, setSamplePayload] = useState('');

  const handleRequestMappingChange = (field: string, value: string) => {
    onUpdate({
      request_mapping: {
        ...configuration.request_mapping!,
        [field]: value
      }
    });
  };

  const handleResponseMappingChange = (field: string, value: string) => {
    onUpdate({
      response_mapping: {
        ...configuration.response_mapping!,
        [field]: value
      }
    });
  };

  const addAdditionalField = () => {
    setAdditionalFields(prev => [...prev, { id: nextFieldId, key: '', value: '' }]);
    setNextFieldId(prev => prev + 1);
  };

  const updateAdditionalField = (id: number, field: 'key' | 'value', value: string) => {
    setAdditionalFields(prev => {
      const updated = prev.map(item => 
        item.id === id ? { ...item, [field]: value } : item
      );
      
      // Update configuration
      const additionalFields: Record<string, any> = {};
      updated.forEach(item => {
        if (item.key && item.value) {
          try {
            // Try to parse as JSON, fall back to string
            additionalFields[item.key] = JSON.parse(item.value);
          } catch {
            additionalFields[item.key] = item.value;
          }
        }
      });
      
      onUpdate({
        request_mapping: {
          ...configuration.request_mapping!,
          additional_fields: additionalFields
        }
      });
      
      return updated;
    });
  };

  const removeAdditionalField = (id: number) => {
    setAdditionalFields(prev => {
      const filtered = prev.filter(item => item.id !== id);
      
      // Update configuration
      const additionalFields: Record<string, any> = {};
      filtered.forEach(item => {
        if (item.key && item.value) {
          try {
            additionalFields[item.key] = JSON.parse(item.value);
          } catch {
            additionalFields[item.key] = item.value;
          }
        }
      });
      
      onUpdate({
        request_mapping: {
          ...configuration.request_mapping!,
          additional_fields: additionalFields
        }
      });
      
      return filtered;
    });
  };

  const generateSamplePayload = () => {
    const payload: Record<string, any> = {};
    
    // Add input field
    const inputField = configuration.request_mapping?.input_field || 'input';
    payload[inputField] = "Sample input text for evaluation";
    
    // Add additional fields
    const additionalFields = configuration.request_mapping?.additional_fields || {};
    Object.entries(additionalFields).forEach(([key, value]) => {
      payload[key] = value;
    });
    
    setSamplePayload(JSON.stringify(payload, null, 2));
  };

  const commonMappings = {
    openai: {
      name: 'OpenAI Chat Completions',
      request: {
        input_field: 'messages[0].content',
        additional_fields: {
          model: 'gpt-4',
          max_tokens: 1000,
          temperature: 0.7
        }
      },
      response: {
        output_field: 'choices[0].message.content',
        error_field: 'error.message'
      }
    },
    anthropic: {
      name: 'Anthropic Claude',
      request: {
        input_field: 'prompt',
        additional_fields: {
          model: 'claude-3-sonnet-20240229',
          max_tokens: 1000
        }
      },
      response: {
        output_field: 'content[0].text',
        error_field: 'error.message'
      }
    },
    custom: {
      name: 'Simple Custom API',
      request: {
        input_field: 'text',
        additional_fields: {}
      },
      response: {
        output_field: 'response',
        error_field: 'error'
      }
    }
  };

  const applyCommonMapping = (mappingKey: keyof typeof commonMappings) => {
    const mapping = commonMappings[mappingKey];
    
    onUpdate({
      request_mapping: {
        ...configuration.request_mapping!,
        input_field: mapping.request.input_field,
        additional_fields: mapping.request.additional_fields
      },
      response_mapping: {
        ...configuration.response_mapping!,
        output_field: mapping.response.output_field,
        error_field: mapping.response.error_field
      }
    });

    // Update additional fields state
    const fields = Object.entries(mapping.request.additional_fields).map(([key, value], index) => ({
      id: index,
      key,
      value: typeof value === 'string' ? value : JSON.stringify(value)
    }));
    setAdditionalFields(fields);
    setNextFieldId(fields.length);
  };

  React.useEffect(() => {
    generateSamplePayload();
  }, [configuration.request_mapping]);

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-2">
          Request & Response Mapping
        </h3>
        <p className="text-sm text-neutral-500 dark:text-neutral-400 mb-4">
          Configure how data flows between LLM-Eval and your API endpoint.
        </p>

        {/* Common Mappings */}
        <div className="mb-6">
          <h4 className="font-medium text-neutral-900 dark:text-white mb-3">
            Quick Setup for Common APIs
          </h4>
          <div className="flex gap-2 flex-wrap">
            {Object.entries(commonMappings).map(([key, mapping]) => (
              <Button
                key={key}
                variant="neutral"
                size="sm"
                onClick={() => applyCommonMapping(key as keyof typeof commonMappings)}
              >
                {mapping.name}
              </Button>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Request Mapping */}
        <Card className="p-6">
          <h4 className="font-medium text-neutral-900 dark:text-white mb-4">
            Request Mapping
          </h4>
          <p className="text-sm text-neutral-500 dark:text-neutral-400 mb-4">
            Configure how evaluation data is sent to your API.
          </p>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
                Input Field Path *
              </label>
              <Input
                type="text"
                value={configuration.request_mapping?.input_field || ''}
                onChange={(e) => handleRequestMappingChange('input_field', e.target.value)}
                placeholder="input"
                error={errors.some(e => e.includes('Input field'))}
              />
              <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-1">
                JSON path where the input text will be placed (e.g., "input", "messages[0].content")
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
                Input Transformation
              </label>
              <Textarea
                value={configuration.request_mapping?.input_transformation || ''}
                onChange={(e) => handleRequestMappingChange('input_transformation', e.target.value)}
                placeholder="Optional JavaScript transformation function"
                rows={3}
              />
              <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-1">
                Optional: JavaScript code to transform input before sending (advanced)
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
                Additional Fields
              </label>
              <div className="space-y-2 mb-3">
                {additionalFields.map((field) => (
                  <div key={field.id} className="flex gap-2 items-center">
                    <div className="flex-1">
                      <Input
                        type="text"
                        value={field.key}
                        onChange={(e) => updateAdditionalField(field.id, 'key', e.target.value)}
                        placeholder="Field name"
                        size="sm"
                      />
                    </div>
                    <div className="flex-1">
                      <Input
                        type="text"
                        value={field.value}
                        onChange={(e) => updateAdditionalField(field.id, 'value', e.target.value)}
                        placeholder="Field value (JSON or string)"
                        size="sm"
                      />
                    </div>
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => removeAdditionalField(field.id)}
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </Button>
                  </div>
                ))}
              </div>
              
              <Button
                variant="neutral"
                size="sm"
                onClick={addAdditionalField}
                className="w-full"
              >
                <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                Add Field
              </Button>
              
              <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-2">
                Static fields to include in every request (e.g., model, temperature)
              </p>
            </div>
          </div>
        </Card>

        {/* Response Mapping */}
        <Card className="p-6">
          <h4 className="font-medium text-neutral-900 dark:text-white mb-4">
            Response Mapping
          </h4>
          <p className="text-sm text-neutral-500 dark:text-neutral-400 mb-4">
            Configure how to extract results from API responses.
          </p>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
                Output Field Path *
              </label>
              <Input
                type="text"
                value={configuration.response_mapping?.output_field || ''}
                onChange={(e) => handleResponseMappingChange('output_field', e.target.value)}
                placeholder="output"
                error={errors.some(e => e.includes('Output field'))}
              />
              <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-1">
                JSON path to extract the response (e.g., "response", "choices[0].message.content")
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
                Error Field Path
              </label>
              <Input
                type="text"
                value={configuration.response_mapping?.error_field || ''}
                onChange={(e) => handleResponseMappingChange('error_field', e.target.value)}
                placeholder="error"
              />
              <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-1">
                JSON path to extract error messages (optional)
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
                Output Transformation
              </label>
              <Textarea
                value={configuration.response_mapping?.output_transformation || ''}
                onChange={(e) => handleResponseMappingChange('output_transformation', e.target.value)}
                placeholder="Optional JavaScript transformation function"
                rows={3}
              />
              <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-1">
                Optional: JavaScript code to transform output after extraction (advanced)
              </p>
            </div>
          </div>
        </Card>
      </div>

      {/* Sample Payload Preview */}
      {samplePayload && (
        <div>
          <h4 className="font-medium text-neutral-900 dark:text-white mb-3">
            Sample Request Payload
          </h4>
          <Card className="p-4 bg-neutral-50 dark:bg-neutral-800">
            <div className="flex items-start justify-between mb-2">
              <Badge variant="neutral" size="sm">JSON</Badge>
              <Button
                variant="neutral"
                size="sm"
                onClick={() => navigator.clipboard.writeText(samplePayload)}
              >
                Copy
              </Button>
            </div>
            <pre className="text-xs text-neutral-700 dark:text-neutral-300 whitespace-pre-wrap font-mono overflow-x-auto">
              {samplePayload}
            </pre>
          </Card>
        </div>
      )}

      {/* Field Path Examples */}
      <div>
        <h4 className="font-medium text-neutral-900 dark:text-white mb-3">
          Field Path Examples
        </h4>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Card className="p-4">
            <h5 className="font-medium text-neutral-900 dark:text-white mb-2">Simple Paths</h5>
            <div className="text-sm text-neutral-600 dark:text-neutral-400 space-y-1 font-mono">
              <div><code>input</code> → {"{"}"input": "text"{"}"}</div>
              <div><code>data.message</code> → {"{"}"data": {"{"}"message": "text"{"}"}{"}"}</div>
              <div><code>response</code> → {"{"}"response": "output"{"}"}</div>
            </div>
          </Card>
          
          <Card className="p-4">
            <h5 className="font-medium text-neutral-900 dark:text-white mb-2">Array Paths</h5>
            <div className="text-sm text-neutral-600 dark:text-neutral-400 space-y-1 font-mono">
              <div><code>messages[0].content</code> → array access</div>
              <div><code>choices[0].text</code> → first choice</div>
              <div><code>results[0].value</code> → first result</div>
            </div>
          </Card>
        </div>
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