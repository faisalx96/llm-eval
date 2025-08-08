'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs } from '@/components/ui/tabs';
import { Loading } from '@/components/ui/loading';
import { Container } from '@/components/layout/container';
import { useRunDetail, useWebSocket } from '@/hooks';
import { RunStatus } from '@/types';
import { RunItemsTable } from '@/components/ui/run-items-table';
import { MetricChart } from '@/components/ui/metric-chart';
import { CompareButton } from '@/components/ui/compare-button';
import { RunDetailSkeleton, MetricsSkeleton, RunItemsTableSkeleton } from '@/components/ui/skeleton';
import { ErrorBoundary, ChartErrorBoundary, TableErrorBoundary } from '@/components/ui/error-boundary';

const RunDetailPage: React.FC = () => {
  const params = useParams();
  const router = useRouter();
  const runId = params.id as string;
  const [activeTab, setActiveTab] = useState('overview');

  const { 
    run, 
    metrics, 
    items,
    loading, 
    error, 
    refetch, 
    fetchItems,
    exportRun, 
    clearError 
  } = useRunDetail(runId);

  // WebSocket for real-time updates
  const { lastMessage } = useWebSocket({ 
    runId, 
    autoConnect: run?.status === 'running' 
  });

  // Update run when WebSocket receives updates
  React.useEffect(() => {
    if (lastMessage?.type === 'run_update' && lastMessage?.run_id === runId) {
      refetch();
    }
  }, [lastMessage, runId, refetch]);

  // Memoized computed values for performance
  const progressPercentage = React.useMemo(() => {
    if (!run || run.total_items === 0) return 0;
    return Math.round((run.processed_items / run.total_items) * 100);
  }, [run?.processed_items, run?.total_items]);

  const metricsChartData = React.useMemo(() => {
    if (!metrics?.metric_details) return [];
    return Object.entries(metrics.metric_details).map(([metric, details]) => ({
      metric,
      score: details.score,
      passed: details.passed_items,
      failed: details.failed_items,
    }));
  }, [metrics?.metric_details]);

  const getStatusBadge = React.useCallback((status: RunStatus) => {
    switch (status) {
      case 'completed':
        return <Badge variant="success" size="md">Completed</Badge>;
      case 'failed':
        return <Badge variant="danger" size="md">Failed</Badge>;
      case 'running':
        return <Badge variant="warning" size="md">Running</Badge>;
      case 'pending':
        return <Badge variant="secondary" size="md">Pending</Badge>;
      case 'cancelled':
        return <Badge variant="secondary" size="md">Cancelled</Badge>;
      default:
        return <Badge variant="secondary" size="md">Unknown</Badge>;
    }
  }, []);

  const formatTimestamp = React.useCallback((timestamp: string) => {
    return new Date(timestamp).toLocaleString();
  }, []);

  const formatDuration = React.useCallback((seconds?: number) => {
    if (!seconds) return 'N/A';
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    if (mins > 60) {
      const hours = Math.floor(mins / 60);
      const remainingMins = mins % 60;
      return `${hours}h ${remainingMins}m ${secs}s`;
    }
    return `${mins}m ${secs}s`;
  }, []);

  const handleExport = async (format: 'excel' | 'json' | 'csv') => {
    await exportRun(format);
  };

  if (loading && !run) {
    return (
      <div className="flex-1 overflow-auto">
        <Container className="py-8">
          <RunDetailSkeleton />
        </Container>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 overflow-auto">
        <Container className="py-8">
          <Card className="p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-destructive-600 dark:text-destructive-400">
                Error Loading Run
              </h2>
              <Button variant="outline" size="sm" onClick={clearError}>
                Dismiss
              </Button>
            </div>
            <p className="text-neutral-600 dark:text-neutral-300 mb-4">{error}</p>
            <div className="flex gap-3">
              <Button onClick={refetch} variant="default" size="sm">
                Retry
              </Button>
              <Button onClick={() => router.back()} variant="outline" size="sm">
                Go Back
              </Button>
            </div>
          </Card>
        </Container>
      </div>
    );
  }

  if (!run) {
    return (
      <div className="flex-1 overflow-auto">
        <Container className="py-8">
          <Card className="p-6 text-center">
            <h2 className="text-lg font-semibold text-neutral-900 dark:text-white mb-2">
              Run Not Found
            </h2>
            <p className="text-neutral-600 dark:text-neutral-300 mb-4">
              The evaluation run you're looking for doesn't exist or has been deleted.
            </p>
            <Button onClick={() => router.back()} variant="default" size="sm">
              Go Back
            </Button>
          </Card>
        </Container>
      </div>
    );
  }

  const getTabContent = (tabId: string) => {
    switch (tabId) {
      case 'overview':
        return (
          <div className="space-y-6">
            {/* Quick Stats */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <div className="bg-neutral-50 dark:bg-neutral-800/50 p-4 rounded-lg">
                <div className="text-sm text-neutral-600 dark:text-neutral-300">Total Items</div>
                <div className="text-2xl font-bold text-neutral-900 dark:text-white">
                  {run.total_items}
                </div>
              </div>
              <div className="bg-neutral-50 dark:bg-neutral-800/50 p-4 rounded-lg">
                <div className="text-sm text-neutral-600 dark:text-neutral-300">Processed</div>
                <div className="text-2xl font-bold text-success-600 dark:text-success-400">
                  {run.processed_items}
                </div>
              </div>
              <div className="bg-neutral-50 dark:bg-neutral-800/50 p-4 rounded-lg">
                <div className="text-sm text-neutral-600 dark:text-neutral-300">Failed</div>
                <div className="text-2xl font-bold text-destructive-600 dark:text-destructive-400">
                  {run.failed_items}
                </div>
              </div>
              <div className="bg-neutral-50 dark:bg-neutral-800/50 p-4 rounded-lg">
                <div className="text-sm text-neutral-600 dark:text-neutral-300">Success Rate</div>
                <div className="text-2xl font-bold text-neutral-900 dark:text-white">
                  {run.total_items > 0 
                    ? Math.round(((run.processed_items - run.failed_items) / run.total_items) * 100) 
                    : 0}%
                </div>
              </div>
            </div>

            {/* Run Details */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div>
                <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-4">
                  Run Information
                </h3>
                <div className="space-y-3">
                  <div className="flex justify-between">
                    <span className="text-neutral-600 dark:text-neutral-300">ID:</span>
                    <span className="text-neutral-900 dark:text-white font-mono text-sm">{run.id}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-neutral-600 dark:text-neutral-300">Status:</span>
                    {getStatusBadge(run.status)}
                  </div>
                  <div className="flex justify-between">
                    <span className="text-neutral-600 dark:text-neutral-300">Created:</span>
                    <span className="text-neutral-900 dark:text-white">{formatTimestamp(run.created_at)}</span>
                  </div>
                  {run.started_at && (
                    <div className="flex justify-between">
                      <span className="text-neutral-600 dark:text-neutral-300">Started:</span>
                      <span className="text-neutral-900 dark:text-white">{formatTimestamp(run.started_at)}</span>
                    </div>
                  )}
                  {run.completed_at && (
                    <div className="flex justify-between">
                      <span className="text-neutral-600 dark:text-neutral-300">Completed:</span>
                      <span className="text-neutral-900 dark:text-white">{formatTimestamp(run.completed_at)}</span>
                    </div>
                  )}
                  {run.duration_seconds && (
                    <div className="flex justify-between">
                      <span className="text-neutral-600 dark:text-neutral-300">Duration:</span>
                      <span className="text-neutral-900 dark:text-white">{formatDuration(run.duration_seconds)}</span>
                    </div>
                  )}
                </div>
              </div>

              <div>
                <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-4">
                  Configuration
                </h3>
                <div className="space-y-3">
                  {run.template_name && (
                    <div className="flex justify-between">
                      <span className="text-neutral-600 dark:text-neutral-300">Template:</span>
                      <span className="text-neutral-900 dark:text-white">{run.template_name}</span>
                    </div>
                  )}
                  {run.dataset_name && (
                    <div className="flex justify-between">
                      <span className="text-neutral-600 dark:text-neutral-300">Dataset:</span>
                      <span className="text-neutral-900 dark:text-white">{run.dataset_name}</span>
                    </div>
                  )}
                  {run.langfuse_session_id && (
                    <div className="flex justify-between">
                      <span className="text-neutral-600 dark:text-neutral-300">Session ID:</span>
                      <span className="text-neutral-900 dark:text-white font-mono text-sm">
                        {run.langfuse_session_id.slice(0, 8)}...
                      </span>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        );
      
      case 'metrics':
        return (
          <div className="space-y-6">
            {loading && !metrics ? (
              <MetricsSkeleton />
            ) : metrics ? (
              <>
                {/* Overall Scores */}
                <div>
                  <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-4">
                    Overall Scores
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {Object.entries(metrics.overall_scores).map(([metric, score]) => (
                      <div key={metric} className="bg-neutral-50 dark:bg-neutral-800/50 p-4 rounded-lg">
                        <div className="text-sm text-neutral-600 dark:text-neutral-300 capitalize">
                          {metric.replace(/_/g, ' ')}
                        </div>
                        <div className="text-2xl font-bold text-neutral-900 dark:text-white">
                          {(score * 100).toFixed(1)}%
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Metric Details */}
                <div>
                  <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-4">
                    Detailed Metrics
                  </h3>
                  
                  {/* Visual Chart */}
                  <div className="mb-6">
                    <h4 className="text-md font-medium text-neutral-900 dark:text-white mb-3">
                      Score Distribution
                    </h4>
                    <ChartErrorBoundary>
                      <MetricChart
                        data={metricsChartData}
                      />
                    </ChartErrorBoundary>
                  </div>

                  {/* Detailed Table */}
                  <div className="space-y-4">
                    {Object.entries(metrics.metric_details).map(([metric, details]) => (
                      <div key={metric} className="border border-neutral-200 dark:border-neutral-700 rounded-lg p-4">
                        <div className="flex items-center justify-between mb-3">
                          <h4 className="font-medium text-neutral-900 dark:text-white capitalize">
                            {metric.replace(/_/g, ' ')}
                          </h4>
                          <span className="text-lg font-semibold text-neutral-900 dark:text-white">
                            {(details.score * 100).toFixed(1)}%
                          </span>
                        </div>
                        <div className="grid grid-cols-3 gap-4 text-sm">
                          <div>
                            <span className="text-neutral-600 dark:text-neutral-300">Passed:</span>
                            <span className="ml-2 text-success-600 dark:text-success-400 font-medium">
                              {details.passed_items}
                            </span>
                          </div>
                          <div>
                            <span className="text-neutral-600 dark:text-neutral-300">Failed:</span>
                            <span className="ml-2 text-destructive-600 dark:text-destructive-400 font-medium">
                              {details.failed_items}
                            </span>
                          </div>
                          <div>
                            <span className="text-neutral-600 dark:text-neutral-300">Total:</span>
                            <span className="ml-2 text-neutral-900 dark:text-white font-medium">
                              {details.passed_items + details.failed_items}
                            </span>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Performance Stats */}
                {metrics.performance_stats && (
                  <div>
                    <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-4">
                      Performance Statistics
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                      <div className="bg-neutral-50 dark:bg-neutral-800/50 p-4 rounded-lg">
                        <div className="text-sm text-neutral-600 dark:text-neutral-300">Avg Response Time</div>
                        <div className="text-2xl font-bold text-neutral-900 dark:text-white">
                          {metrics.performance_stats.avg_response_time.toFixed(2)}s
                        </div>
                      </div>
                      {metrics.performance_stats.total_tokens && (
                        <div className="bg-neutral-50 dark:bg-neutral-800/50 p-4 rounded-lg">
                          <div className="text-sm text-neutral-600 dark:text-neutral-300">Total Tokens</div>
                          <div className="text-2xl font-bold text-neutral-900 dark:text-white">
                            {metrics.performance_stats.total_tokens.toLocaleString()}
                          </div>
                        </div>
                      )}
                      {metrics.performance_stats.total_cost && (
                        <div className="bg-neutral-50 dark:bg-neutral-800/50 p-4 rounded-lg">
                          <div className="text-sm text-neutral-600 dark:text-neutral-300">Total Cost</div>
                          <div className="text-2xl font-bold text-neutral-900 dark:text-white">
                            ${metrics.performance_stats.total_cost.toFixed(4)}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="text-center py-8">
                <div className="text-neutral-500 dark:text-neutral-400 mb-4">
                  {run.status === 'completed' 
                    ? 'No metrics data available for this run.'
                    : 'Metrics will be available after the run completes.'}
                </div>
                {run.status !== 'completed' && (
                  <Button variant="outline" onClick={refetch}>
                    Refresh
                  </Button>
                )}
              </div>
            )}
          </div>
        );
      
      case 'errors':
        return (
          <div className="space-y-6">
            {run.error_message ? (
              <div className="bg-destructive-50 dark:bg-destructive-900/20 border border-destructive-200 dark:border-destructive-800 rounded-lg p-4">
                <h3 className="text-lg font-semibold text-destructive-700 dark:text-destructive-300 mb-2">
                  Run Error
                </h3>
                <pre className="text-sm text-destructive-600 dark:text-destructive-400 whitespace-pre-wrap">
                  {run.error_message}
                </pre>
              </div>
            ) : run.failed_items > 0 ? (
              <div>
                <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-4">
                  Error Analysis
                </h3>
                {metrics?.error_analysis ? (
                  <div className="space-y-4">
                    {/* Error Types */}
                    <div>
                      <h4 className="font-medium text-neutral-900 dark:text-white mb-3">Error Types</h4>
                      <div className="space-y-2">
                        {Object.entries(metrics.error_analysis.error_types).map(([type, count]) => (
                          <div key={type} className="flex items-center justify-between p-3 bg-neutral-50 dark:bg-neutral-800/50 rounded">
                            <span className="text-neutral-900 dark:text-white">{type}</span>
                            <span className="text-destructive-600 dark:text-destructive-400 font-medium">
                              {count} occurrences
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Common Failures */}
                    {metrics.error_analysis.common_failures.length > 0 && (
                      <div>
                        <h4 className="font-medium text-neutral-900 dark:text-white mb-3">Common Failure Messages</h4>
                        <div className="space-y-2">
                          {metrics.error_analysis.common_failures.map((failure, index) => (
                            <div key={index} className="p-3 bg-neutral-50 dark:bg-neutral-800/50 rounded">
                              <pre className="text-sm text-neutral-700 dark:text-neutral-300 whitespace-pre-wrap">
                                {failure}
                              </pre>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="text-neutral-600 dark:text-neutral-300">
                    Error analysis will be available once the run completes.
                  </p>
                )}
              </div>
            ) : (
              <div className="text-center py-8">
                <svg className="w-12 h-12 text-success-500 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <h3 className="text-lg font-medium text-neutral-900 dark:text-white mb-2">
                  No Errors Found
                </h3>
                <p className="text-neutral-600 dark:text-neutral-300">
                  This evaluation run completed successfully without any errors.
                </p>
              </div>
            )}
          </div>
        );
      
      case 'items':
        return (
          <div className="space-y-6">
            <div>
              <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-4">
                Evaluation Items
              </h3>
              {loading && !items ? (
                <RunItemsTableSkeleton />
              ) : (
                <TableErrorBoundary>
                  <RunItemsTable
                    items={items}
                    loading={loading}
                    onFetchItems={fetchItems}
                  />
                </TableErrorBoundary>
              )}
            </div>
          </div>
        );
      
      case 'configuration':
        return (
          <div className="space-y-6">
            <div>
              <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-4">
                Metrics Configuration
              </h3>
              <div className="bg-neutral-50 dark:bg-neutral-800/50 rounded-lg p-4">
                <pre className="text-sm text-neutral-700 dark:text-neutral-300 whitespace-pre-wrap overflow-auto">
                  {JSON.stringify(run.metrics_config, null, 2)}
                </pre>
              </div>
            </div>

            {run.metadata && Object.keys(run.metadata).length > 0 && (
              <div>
                <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-4">
                  Metadata
                </h3>
                <div className="bg-neutral-50 dark:bg-neutral-800/50 rounded-lg p-4">
                  <pre className="text-sm text-neutral-700 dark:text-neutral-300 whitespace-pre-wrap overflow-auto">
                    {JSON.stringify(run.metadata, null, 2)}
                  </pre>
                </div>
              </div>
            )}
          </div>
        );
      
      default:
        return null;
    }
  };

  const tabItems = [
    { id: 'overview', label: 'Overview', content: getTabContent('overview') },
    { id: 'metrics', label: 'Metrics', content: getTabContent('metrics') },
    { id: 'items', label: 'Items', content: getTabContent('items') },
    { id: 'errors', label: 'Errors', content: getTabContent('errors') },
    { id: 'configuration', label: 'Configuration', content: getTabContent('configuration') },
  ];

  return (
    <ErrorBoundary>
      <div className="flex-1 overflow-auto">
        <Container className="py-8 space-y-8">
          {/* Header */}
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-3 mb-2">
                <Link 
                  href="/dashboard" 
                  className="text-neutral-600 dark:text-neutral-300 hover:text-neutral-900 dark:hover:text-white transition-colors"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                  </svg>
                </Link>
                <h1 className="text-3xl font-bold text-neutral-900 dark:text-white truncate">
                  {run.name}
                </h1>
                {getStatusBadge(run.status)}
              </div>
              
              {run.description && (
                <p className="text-neutral-600 dark:text-neutral-300">
                  {run.description}
                </p>
              )}
              
              <div className="flex items-center gap-4 mt-3 text-sm text-neutral-500 dark:text-neutral-400">
                <span>Created: {formatTimestamp(run.created_at)}</span>
                {run.duration_seconds && (
                  <>
                    <span>•</span>
                    <span>Duration: {formatDuration(run.duration_seconds)}</span>
                  </>
                )}
                {run.template_name && (
                  <>
                    <span>•</span>
                    <span>Template: {run.template_name}</span>
                  </>
                )}
              </div>
            </div>
            
            <div className="flex flex-col sm:flex-row gap-3">
              {run.langfuse_session_id && (
                <a 
                  href={`https://cloud.langfuse.com/project/sessions/${run.langfuse_session_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Button variant="outline" size="md" className="w-full sm:w-auto">
                    <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                    </svg>
                    View in Langfuse
                  </Button>
                </a>
              )}
              
              <div className="flex gap-2">
                <CompareButton 
                  runId={runId} 
                  variant="outline" 
                  size="md"
                />
                <Button 
                  variant="outline" 
                  size="md"
                  onClick={() => handleExport('excel')}
                  disabled={run.status !== 'completed' || loading}
                >
                  Export Excel
                </Button>
                <Button 
                  variant="outline" 
                  size="md"
                  onClick={() => handleExport('json')}
                  disabled={run.status !== 'completed' || loading}
                >
                  Export JSON
                </Button>
              </div>
            </div>
          </div>

          {/* Progress Bar (for running evaluations) */}
          {run.status === 'running' && (
            <Card className="p-6">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-lg font-semibold text-neutral-900 dark:text-white">
                  Evaluation Progress
                </h3>
                <span className="text-sm text-neutral-600 dark:text-neutral-300">
                  {run.processed_items} / {run.total_items} items processed
                </span>
              </div>
              <div className="w-full bg-neutral-200 dark:bg-neutral-700 rounded-full h-3">
                <div 
                  className="bg-warning-500 h-3 rounded-full transition-all duration-1000 ease-out"
                  style={{ width: `${progressPercentage}%` }}
                />
              </div>
              <div className="flex justify-between text-sm text-neutral-500 dark:text-neutral-400 mt-2">
                <span>{progressPercentage}% complete</span>
                {run.failed_items > 0 && (
                  <span className="text-destructive-600 dark:text-destructive-400">
                    {run.failed_items} failed
                  </span>
                )}
              </div>
            </Card>
          )}

          {/* Main Content Tabs */}
          <Card>
            <Tabs
              items={tabItems}
              activeTab={activeTab}
              onTabChange={setActiveTab}
            />
          </Card>
        </Container>
      </div>
    </ErrorBoundary>
  );
};

export default RunDetailPage;