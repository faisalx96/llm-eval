'use client';

import React, { useState } from 'react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Container } from '@/components/layout/container';

const Settings: React.FC = () => {
  const [langfuseUrl, setLangfuseUrl] = useState('https://cloud.langfuse.com');
  const [langfuseKey, setLangfuseKey] = useState('');
  const [defaultModel, setDefaultModel] = useState('gpt-4-turbo');
  const [theme, setTheme] = useState('light');

  return (
    <div className="flex-1 overflow-auto">
      <Container className="py-8 space-y-8">
        {/* Header */}
        <div>
          <h1 className="text-3xl font-bold text-neutral-900 dark:text-white">
            Settings
          </h1>
          <p className="text-neutral-600 dark:text-neutral-300 mt-1">
            Configure your evaluation environment and preferences
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Main Settings */}
          <div className="lg:col-span-2 space-y-6">
            {/* Langfuse Configuration */}
            <Card>
              <div className="p-6 border-b border-neutral-200 dark:border-neutral-700">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-xl font-semibold text-neutral-900 dark:text-white">
                      Langfuse Configuration
                    </h2>
                    <p className="text-sm text-neutral-600 dark:text-neutral-300 mt-1">
                      Configure your Langfuse instance for dataset management and tracing
                    </p>
                  </div>
                  <Badge variant="success" size="sm">Connected</Badge>
                </div>
              </div>

              <div className="p-6 space-y-4">
                <div>
                  <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
                    Langfuse URL
                  </label>
                  <Input
                    type="url"
                    value={langfuseUrl}
                    onChange={(e) => setLangfuseUrl(e.target.value)}
                    placeholder="https://cloud.langfuse.com"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
                    API Key
                  </label>
                  <Input
                    type="password"
                    value={langfuseKey}
                    onChange={(e) => setLangfuseKey(e.target.value)}
                    placeholder="Enter your Langfuse API key"
                  />
                </div>

                <div className="flex gap-3 pt-2">
                  <Button variant="default" size="sm">
                    Test Connection
                  </Button>
                  <Button variant="secondary" size="sm">
                    Save Configuration
                  </Button>
                </div>
              </div>
            </Card>

            {/* Evaluation Defaults */}
            <Card>
              <div className="p-6 border-b border-neutral-200 dark:border-neutral-700">
                <h2 className="text-xl font-semibold text-neutral-900 dark:text-white">
                  Evaluation Defaults
                </h2>
                <p className="text-sm text-neutral-600 dark:text-neutral-300 mt-1">
                  Set default values for new evaluations
                </p>
              </div>

              <div className="p-6 space-y-4">
                <div>
                  <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
                    Default Model
                  </label>
                  <Select
                    value={defaultModel}
                    onChange={(e) => setDefaultModel(e.target.value)}
                    options={[
                      { value: 'gpt-4-turbo', label: 'GPT-4 Turbo' },
                      { value: 'gpt-3.5-turbo', label: 'GPT-3.5 Turbo' },
                      { value: 'claude-3-sonnet', label: 'Claude-3 Sonnet' },
                      { value: 'claude-3-haiku', label: 'Claude-3 Haiku' },
                      { value: 'gemini-pro', label: 'Gemini Pro' },
                    ]}
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
                    Default Metrics
                  </label>
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="secondary" size="sm">Relevance</Badge>
                    <Badge variant="secondary" size="sm">Coherence</Badge>
                    <Badge variant="secondary" size="sm">Faithfulness</Badge>
                    <Button variant="ghost" size="sm" className="h-6 px-2 text-xs">
                      + Add Metric
                    </Button>
                  </div>
                </div>

                <div className="flex gap-3 pt-2">
                  <Button variant="secondary" size="sm">
                    Reset to Defaults
                  </Button>
                  <Button variant="default" size="sm">
                    Save Defaults
                  </Button>
                </div>
              </div>
            </Card>

            {/* UI Preferences */}
            <Card>
              <div className="p-6 border-b border-neutral-200 dark:border-neutral-700">
                <h2 className="text-xl font-semibold text-neutral-900 dark:text-white">
                  UI Preferences
                </h2>
                <p className="text-sm text-neutral-600 dark:text-neutral-300 mt-1">
                  Customize your interface preferences
                </p>
              </div>

              <div className="p-6 space-y-4">
                <div>
                  <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
                    Theme
                  </label>
                  <Select
                    value={theme}
                    onChange={(e) => setTheme(e.target.value)}
                    options={[
                      { value: 'light', label: 'Light' },
                      { value: 'dark', label: 'Dark' },
                      { value: 'system', label: 'System' },
                    ]}
                  />
                </div>

                <div className="flex items-center justify-between">
                  <div>
                    <h4 className="text-sm font-medium text-neutral-900 dark:text-white">
                      Sidebar Collapsed by Default
                    </h4>
                    <p className="text-xs text-neutral-600 dark:text-neutral-300">
                      Start with sidebar in collapsed state
                    </p>
                  </div>
                  <button
                    className="relative inline-flex h-6 w-11 items-center rounded-full bg-neutral-200 transition-colors focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 dark:bg-neutral-700"
                  >
                    <span className="inline-block h-4 w-4 transform rounded-full bg-white transition-transform" />
                  </button>
                </div>

                <div className="flex gap-3 pt-2">
                  <Button variant="default" size="sm">
                    Save Preferences
                  </Button>
                </div>
              </div>
            </Card>
          </div>

          {/* Sidebar */}
          <div className="space-y-6">
            {/* System Status */}
            <Card className="p-6">
              <h2 className="text-xl font-semibold text-neutral-900 dark:text-white mb-4">
                System Status
              </h2>
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-neutral-600 dark:text-neutral-300">Langfuse</span>
                  <Badge variant="success" size="sm">Connected</Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-neutral-600 dark:text-neutral-300">DeepEval</span>
                  <Badge variant="success" size="sm">Available</Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-neutral-600 dark:text-neutral-300">API Server</span>
                  <Badge variant="success" size="sm">Online</Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-neutral-600 dark:text-neutral-300">Version</span>
                  <Badge variant="secondary" size="sm">v0.3.0</Badge>
                </div>
              </div>
            </Card>

            {/* Quick Actions */}
            <Card className="p-6">
              <h2 className="text-xl font-semibold text-neutral-900 dark:text-white mb-4">
                Quick Actions
              </h2>
              <div className="space-y-3">
                <Button variant="outline" size="md" className="w-full justify-start">
                  <svg className="w-4 h-4 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                  Export Settings
                </Button>

                <Button variant="outline" size="md" className="w-full justify-start">
                  <svg className="w-4 h-4 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                  </svg>
                  Import Settings
                </Button>

                <Button variant="outline" size="md" className="w-full justify-start">
                  <svg className="w-4 h-4 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                  Reset All Settings
                </Button>

                <Button variant="outline" size="md" className="w-full justify-start">
                  <svg className="w-4 h-4 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  View Documentation
                </Button>
              </div>
            </Card>

            {/* Help & Support */}
            <Card className="p-6">
              <h2 className="text-xl font-semibold text-neutral-900 dark:text-white mb-4">
                Help & Support
              </h2>
              <div className="space-y-3 text-sm">
                <div>
                  <p className="text-neutral-600 dark:text-neutral-300">
                    Need help? Check out our documentation or contact support.
                  </p>
                </div>
                <div className="space-y-2">
                  <Button variant="ghost" size="sm" className="w-full justify-start p-0 h-auto">
                    📚 Documentation
                  </Button>
                  <Button variant="ghost" size="sm" className="w-full justify-start p-0 h-auto">
                    💬 Community
                  </Button>
                  <Button variant="ghost" size="sm" className="w-full justify-start p-0 h-auto">
                    🐛 Report Issue
                  </Button>
                </div>
              </div>
            </Card>
          </div>
        </div>
      </Container>
    </div>
  );
};

export default Settings;
