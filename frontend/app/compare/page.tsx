'use client';

import React, { useState, useEffect } from 'react';
import { useSearchParams } from 'next/navigation';
import { Card, Button, Container, Loading, Skeleton } from '@/components';
import {
  RunSelector,
  MetricDiff,
  ComparisonChart,
  ItemLevelComparison
} from '@/components';
import { useRunComparison } from '@/hooks';
import { apiClient } from '@/lib/api';

const Compare: React.FC = () => {
  const searchParams = useSearchParams();
  const [runId1, setRunId1] = useState<string>(searchParams?.get('run1') || '');
  const [runId2, setRunId2] = useState<string>(searchParams?.get('run2') || '');
  const [exporting, setExporting] = useState(false);

  const { comparison, loading, error, refetch } = useRunComparison(
    runId1 || null,
    runId2 || null
  );

  // Update URL when run selections change
  useEffect(() => {
    const params = new URLSearchParams();
    if (runId1) params.set('run1', runId1);
    if (runId2) params.set('run2', runId2);

    const newUrl = `/compare${params.toString() ? `?${params.toString()}` : ''}`;
    window.history.replaceState({}, '', newUrl);
  }, [runId1, runId2]);

  const handleExport = async (format: 'excel' | 'json' | 'csv' = 'excel') => {
    if (!runId1 || !runId2) return;

    setExporting(true);
    try {
      const blob = await apiClient.exportComparison(runId1, runId2, format);
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `comparison_${runId1.slice(0, 8)}_vs_${runId2.slice(0, 8)}.${format === 'excel' ? 'xlsx' : format}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Export failed:', err);
    } finally {
      setExporting(false);
    }
  };

  const canCompare = runId1 && runId2 && runId1 !== runId2;

  return (
    <div className="flex-1 overflow-auto">
      <Container className="py-8">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-neutral-900 dark:text-white mb-2">
            Compare Runs
          </h1>
          <p className="text-neutral-600 dark:text-neutral-300">
            Side-by-side comparison of evaluation runs with detailed diff views and statistical analysis
          </p>
        </div>

        {/* Run Selection */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
          <RunSelector
            selectedRunId={runId1}
            onRunSelect={setRunId1}
            excludeRunId={runId2}
            label="Run 1 (Baseline)"
            placeholder="Select baseline run..."
          />

          <RunSelector
            selectedRunId={runId2}
            onRunSelect={setRunId2}
            excludeRunId={runId1}
            label="Run 2 (Comparison)"
            placeholder="Select comparison run..."
          />
        </div>

        {!canCompare && (
          <Card className="p-12 text-center">
            <div className="w-16 h-16 bg-primary-100 dark:bg-primary-900/30 rounded-full flex items-center justify-center mx-auto mb-4">
              <svg className="w-8 h-8 text-primary-600 dark:text-primary-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
            </div>
            <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-2">
              Select Two Runs to Compare
            </h3>
            <p className="text-neutral-600 dark:text-neutral-300 max-w-lg mx-auto">
              Choose two completed evaluation runs from the selectors above to see a detailed comparison with
              metric differences, statistical analysis, and item-level breakdowns.
            </p>
          </Card>
        )}

        {canCompare && error && (
          <Card className="p-6 border-danger-200 dark:border-danger-800 bg-danger-50 dark:bg-danger-950">
            <div className="flex items-center gap-3">
              <svg className="w-5 h-5 text-danger-600 dark:text-danger-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <div>
                <h4 className="font-medium text-danger-900 dark:text-danger-100">
                  Comparison Failed
                </h4>
                <p className="text-danger-700 dark:text-danger-300 text-sm mt-1">
                  {error}
                </p>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={refetch}
                className="ml-auto"
              >
                Retry
              </Button>
            </div>
          </Card>
        )}

        {canCompare && loading && (
          <div className="space-y-6">
            <Skeleton className="h-64" />
            <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
              <Skeleton className="h-48" />
              <Skeleton className="h-48" />
              <Skeleton className="h-48" />
            </div>
            <Skeleton className="h-96" />
          </div>
        )}

        {canCompare && comparison && (
          <div className="space-y-8">
            {/* Summary Stats */}
            <Card className="p-6">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-xl font-semibold text-neutral-900 dark:text-white">
                  Comparison Summary
                </h2>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleExport('excel')}
                    disabled={exporting}
                  >
                    {exporting ? (
                      <Loading size="sm" />
                    ) : (
                      <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                      </svg>
                    )}
                    Export Excel
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={refetch}
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                  </Button>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                <div className="text-center">
                  <div className="text-2xl font-bold text-neutral-900 dark:text-white">
                    {comparison.comparison.overall_performance.winner === 'run1'
                      ? comparison.run1.name
                      : comparison.comparison.overall_performance.winner === 'run2'
                      ? comparison.run2.name
                      : 'Tie'
                    }
                  </div>
                  <div className="text-sm text-neutral-600 dark:text-neutral-400">
                    Overall Winner
                  </div>
                </div>

                <div className="text-center">
                  <div className="text-2xl font-bold text-success-600 dark:text-success-400">
                    {comparison.comparison.overall_performance.significant_improvements}
                  </div>
                  <div className="text-sm text-neutral-600 dark:text-neutral-400">
                    Significant Improvements
                  </div>
                </div>

                <div className="text-center">
                  <div className="text-2xl font-bold text-danger-600 dark:text-danger-400">
                    {comparison.comparison.overall_performance.significant_regressions}
                  </div>
                  <div className="text-sm text-neutral-600 dark:text-neutral-400">
                    Significant Regressions
                  </div>
                </div>

                <div className="text-center">
                  <div className="text-2xl font-bold text-neutral-900 dark:text-white">
                    {comparison.item_level_comparison.length}
                  </div>
                  <div className="text-sm text-neutral-600 dark:text-neutral-400">
                    Items Compared
                  </div>
                </div>
              </div>
            </Card>

            {/* Visual Comparison Chart */}
            <ComparisonChart comparison={comparison} />

            {/* Metric Diffs */}
            <div>
              <h2 className="text-xl font-semibold text-neutral-900 dark:text-white mb-6">
                Metric Differences
              </h2>
              <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
                {Object.entries(comparison.comparison.metrics).map(([metricName, metricData]) => {
                  const stats = comparison.comparison.statistical_analysis[metricName];

                  return (
                    <MetricDiff
                      key={metricName}
                      metricName={metricName}
                      run1Score={metricData.run1_score}
                      run2Score={metricData.run2_score}
                      difference={metricData.difference}
                      percentageChange={metricData.percentage_change}
                      direction={metricData.improvement_direction}
                      isSignificant={stats?.is_significant}
                      pValue={stats?.p_value}
                      confidenceInterval={stats?.confidence_interval}
                    />
                  );
                })}
              </div>
            </div>

            {/* Item-Level Comparison */}
            <ItemLevelComparison comparison={comparison} />
          </div>
        )}
      </Container>
    </div>
  );
};

export default Compare;
