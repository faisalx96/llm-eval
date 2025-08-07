'use client';

import React from 'react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Container } from '@/components/layout/container';

const Compare: React.FC = () => {
  return (
    <div className="flex-1 overflow-auto">
      <Container className="py-8">
        <div className="text-center space-y-6">
          {/* Header */}
          <div>
            <h1 className="text-3xl font-bold text-neutral-900 dark:text-white">
              Compare Runs
            </h1>
            <p className="text-neutral-600 dark:text-neutral-300 mt-2">
              Side-by-side comparison of evaluation runs with detailed diff views
            </p>
          </div>

          {/* Coming Soon Card */}
          <Card className="max-w-2xl mx-auto p-12">
            <div className="text-center space-y-4">
              <div className="w-24 h-24 bg-primary-100 dark:bg-primary-900/30 rounded-full flex items-center justify-center mx-auto">
                <svg className="w-12 h-12 text-primary-600 dark:text-primary-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
              </div>
              
              <h2 className="text-2xl font-semibold text-neutral-900 dark:text-white">
                Coming Soon
              </h2>
              
              <p className="text-neutral-600 dark:text-neutral-300 max-w-lg mx-auto">
                Run comparison functionality is being developed as part of Sprint 2. 
                This will include side-by-side comparisons, diff views, and statistical analysis.
              </p>
              
              <div className="pt-4">
                <Button 
                  variant="default" 
                  size="md" 
                  onClick={() => window.history.back()}
                >
                  Go Back
                </Button>
              </div>
            </div>
          </Card>

          {/* Feature Preview */}
          <div className="max-w-4xl mx-auto pt-8">
            <h3 className="text-xl font-semibold text-neutral-900 dark:text-white mb-6">
              What&apos;s Coming in Sprint 2
            </h3>
            
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              <Card className="p-6">
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-8 h-8 bg-primary-100 dark:bg-primary-900/30 rounded-lg flex items-center justify-center">
                    <svg className="w-4 h-4 text-primary-600 dark:text-primary-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 14h.01M12 14h.01M15 11h.01M12 11h.01M9 11h.01M7 21h10a2 2 0 002-2V5a2 2 0 00-2-2H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
                    </svg>
                  </div>
                  <h4 className="font-medium text-neutral-900 dark:text-white">
                    Side-by-Side View
                  </h4>
                </div>
                <p className="text-sm text-neutral-600 dark:text-neutral-300">
                  Compare evaluation results in a clear side-by-side layout with metric breakdowns
                </p>
              </Card>

              <Card className="p-6">
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-8 h-8 bg-primary-100 dark:bg-primary-900/30 rounded-lg flex items-center justify-center">
                    <svg className="w-4 h-4 text-primary-600 dark:text-primary-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                  </div>
                  <h4 className="font-medium text-neutral-900 dark:text-white">
                    Diff Highlighting
                  </h4>
                </div>
                <p className="text-sm text-neutral-600 dark:text-neutral-300">
                  Visual diff highlighting to identify improvements and regressions
                </p>
              </Card>

              <Card className="p-6">
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-8 h-8 bg-primary-100 dark:bg-primary-900/30 rounded-lg flex items-center justify-center">
                    <svg className="w-4 h-4 text-primary-600 dark:text-primary-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                    </svg>
                  </div>
                  <h4 className="font-medium text-neutral-900 dark:text-white">
                    Statistical Analysis
                  </h4>
                </div>
                <p className="text-sm text-neutral-600 dark:text-neutral-300">
                  Statistical significance testing and confidence intervals
                </p>
              </Card>
            </div>
          </div>
        </div>
      </Container>
    </div>
  );
};

export default Compare;