'use client';

import React from 'react';
import { Card } from '../card';
import { Input } from '../input';
import { Select } from '../select';
import { Badge } from '../badge';
import { TaskConfiguration, AuthConfig } from '@/types';

interface AuthStepProps {
  configuration: Partial<TaskConfiguration>;
  onUpdate: (updates: Partial<TaskConfiguration>) => void;
  errors: string[];
}

const AUTH_TYPES = [
  {
    value: 'none',
    label: 'No Authentication',
    description: 'API does not require authentication'
  },
  {
    value: 'bearer',
    label: 'Bearer Token',
    description: 'Authorization: Bearer {token}'
  },
  {
    value: 'api_key',
    label: 'API Key',
    description: 'Custom header with API key'
  },
  {
    value: 'oauth',
    label: 'OAuth 2.0',
    description: 'OAuth 2.0 client credentials flow (coming soon)',
    disabled: true
  }
];

export function AuthStep({ configuration, onUpdate, errors }: AuthStepProps) {
  const authType = configuration.auth?.type || 'none';

  const handleAuthTypeChange = (type: string) => {
    const baseAuth: AuthConfig = { type: type as AuthConfig['type'] };
    
    // Initialize credentials based on type
    if (type === 'bearer') {
      baseAuth.credentials = { token: '' };
    } else if (type === 'api_key') {
      baseAuth.credentials = { key: '', header_name: 'X-API-Key' };
    } else if (type === 'oauth') {
      baseAuth.credentials = { key: '', secret: '' };
    }

    onUpdate({ auth: baseAuth });
  };

  const handleCredentialChange = (field: string, value: string) => {
    onUpdate({
      auth: {
        ...configuration.auth!,
        credentials: {
          ...configuration.auth?.credentials,
          [field]: value
        }
      }
    });
  };

  const renderAuthFields = () => {
    switch (authType) {
      case 'bearer':
        return (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
                Bearer Token *
              </label>
              <Input
                type="password"
                value={configuration.auth?.credentials?.token || ''}
                onChange={(e) => handleCredentialChange('token', e.target.value)}
                placeholder="Enter your bearer token"
                error={errors.some(e => e.includes('Bearer token'))}
              />
              <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-1">
                This will be sent as: Authorization: Bearer {'{'}token{'}'}
              </p>
            </div>
          </div>
        );

      case 'api_key':
        return (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
                API Key *
              </label>
              <Input
                type="password"
                value={configuration.auth?.credentials?.key || ''}
                onChange={(e) => handleCredentialChange('key', e.target.value)}
                placeholder="Enter your API key"
                error={errors.some(e => e.includes('API key'))}
              />
            </div>
            
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
                Header Name *
              </label>
              <Input
                type="text"
                value={configuration.auth?.credentials?.header_name || 'X-API-Key'}
                onChange={(e) => handleCredentialChange('header_name', e.target.value)}
                placeholder="X-API-Key"
                error={errors.some(e => e.includes('Header name'))}
              />
              <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-1">
                The header name where the API key will be sent
              </p>
            </div>

            <div className="bg-neutral-50 dark:bg-neutral-800 rounded p-3">
              <p className="text-xs text-neutral-600 dark:text-neutral-400">
                <strong>Preview:</strong> {configuration.auth?.credentials?.header_name || 'X-API-Key'}: {'{'}api_key{'}'}
              </p>
            </div>
          </div>
        );

      case 'oauth':
        return (
          <div className="space-y-4">
            <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <Badge variant="warning" size="sm">Coming Soon</Badge>
                <span className="font-medium text-yellow-800 dark:text-yellow-300">OAuth 2.0 Support</span>
              </div>
              <p className="text-sm text-yellow-700 dark:text-yellow-400">
                OAuth 2.0 authentication will be available in a future update. For now, please use Bearer Token or API Key authentication.
              </p>
            </div>
          </div>
        );

      default:
        return (
          <div className="bg-neutral-50 dark:bg-neutral-800 rounded-lg p-6 text-center">
            <div className="w-12 h-12 mx-auto mb-3 bg-neutral-200 dark:bg-neutral-700 rounded-full flex items-center justify-center">
              <svg className="w-6 h-6 text-neutral-500 dark:text-neutral-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
            </div>
            <h3 className="font-medium text-neutral-900 dark:text-white mb-1">
              No Authentication Required
            </h3>
            <p className="text-sm text-neutral-500 dark:text-neutral-400">
              Your API endpoint will be called without any authentication headers.
            </p>
          </div>
        );
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-2">
          Authentication Method
        </h3>
        <p className="text-sm text-neutral-500 dark:text-neutral-400 mb-4">
          Choose how to authenticate with your API endpoint.
        </p>

        {/* Authentication Type Selection */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          {AUTH_TYPES.map((type) => (
            <Card
              key={type.value}
              className={`p-4 cursor-pointer transition-all duration-200 ${
                authType === type.value
                  ? 'ring-2 ring-primary-500 border-primary-500 bg-primary-50 dark:bg-primary-900/20'
                  : 'hover:border-neutral-300 dark:hover:border-neutral-600'
              } ${
                type.disabled ? 'opacity-60 cursor-not-allowed' : ''
              }`}
              onClick={type.disabled ? undefined : () => handleAuthTypeChange(type.value)}
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-2">
                  <div className={`w-4 h-4 rounded-full border-2 ${
                    authType === type.value
                      ? 'border-primary-500 bg-primary-500'
                      : 'border-neutral-300 dark:border-neutral-600'
                  }`}>
                    {authType === type.value && (
                      <div className="w-full h-full rounded-full bg-white scale-50"></div>
                    )}
                  </div>
                  <h4 className="font-medium text-neutral-900 dark:text-white">
                    {type.label}
                  </h4>
                </div>
                {type.disabled && (
                  <Badge variant="warning" size="sm">Soon</Badge>
                )}
              </div>
              <p className="text-sm text-neutral-500 dark:text-neutral-400">
                {type.description}
              </p>
            </Card>
          ))}
        </div>

        {/* Authentication Configuration */}
        <Card className="p-6">
          {renderAuthFields()}
        </Card>
      </div>

      {/* Security Notice */}
      {authType !== 'none' && (
        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
          <div className="flex items-start gap-3">
            <svg className="w-5 h-5 text-blue-600 dark:text-blue-400 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.732-.833-2.464 0L4.35 16.5c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
            <div>
              <h4 className="font-medium text-blue-800 dark:text-blue-300 mb-1">
                Security Notice
              </h4>
              <p className="text-sm text-blue-700 dark:text-blue-400">
                Your authentication credentials are stored securely and encrypted. They are only used when making API calls during evaluations.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Common API Examples */}
      <div>
        <h4 className="font-medium text-neutral-900 dark:text-white mb-3">
          Common API Examples
        </h4>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Card className="p-4">
            <h5 className="font-medium text-neutral-900 dark:text-white mb-2">OpenAI API</h5>
            <div className="text-sm text-neutral-600 dark:text-neutral-400 space-y-1">
              <p><strong>Type:</strong> Bearer Token</p>
              <p><strong>Token:</strong> sk-...</p>
            </div>
          </Card>
          
          <Card className="p-4">
            <h5 className="font-medium text-neutral-900 dark:text-white mb-2">Anthropic API</h5>
            <div className="text-sm text-neutral-600 dark:text-neutral-400 space-y-1">
              <p><strong>Type:</strong> API Key</p>
              <p><strong>Header:</strong> x-api-key</p>
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