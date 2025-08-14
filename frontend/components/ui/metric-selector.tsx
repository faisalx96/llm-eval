'use client';

import React, { useState, useMemo } from 'react';
import { Card } from './card';
import { Input } from './input';
import { Button } from './button';
import { Badge } from './badge';
import { Loading } from './loading';
import { Tabs } from './tabs';
import { MetricCard } from './metric-card';
import { useMetrics, useMetricSelector, useMetricCompatibility } from '@/hooks/useMetrics';
import { MetricInfo, MetricCategory, MetricSelection } from '@/types';
import { cn } from '@/lib/utils';

interface MetricSelectorProps {
  onSelectionChange?: (selections: MetricSelection[]) => void;
  initialSelections?: MetricSelection[];
  datasetId?: string;
  compatibleTasks?: string[];
  className?: string;
}

const CATEGORY_INFO = {
  accuracy: {
    label: 'Accuracy',
    description: 'Metrics that measure correctness and precision of outputs',
    icon: '🎯'
  },
  semantic: {
    label: 'Semantic',
    description: 'Metrics that evaluate meaning and context understanding',
    icon: '🧠'
  },
  safety: {
    label: 'Safety',
    description: 'Metrics for detecting harmful, biased, or inappropriate content',
    icon: '🛡️'
  },
  performance: {
    label: 'Performance',
    description: 'Metrics that measure speed, cost, and resource usage',
    icon: '⚡'
  },
  custom: {
    label: 'Custom',
    description: 'User-defined and specialized evaluation metrics',
    icon: '🔧'
  }
};

export function MetricSelector({
  onSelectionChange,
  initialSelections = [],
  datasetId,
  compatibleTasks = [],
  className
}: MetricSelectorProps) {
  const [search, setSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<MetricCategory | 'all'>('all');
  const [showPreview, setShowPreview] = useState(false);

  const { metrics, metricsByCategory, loading, error, refetch } = useMetrics();
  const {
    selectedMetrics,
    addMetric,
    removeMetric,
    updateMetricParameters,
    isMetricSelected,
    getMetricSelection,
    clearSelection,
    setSelectedMetrics
  } = useMetricSelector(initialSelections);

  // Update parent when selection changes
  React.useEffect(() => {
    onSelectionChange?.(selectedMetrics);
  }, [selectedMetrics, onSelectionChange]);

  const filteredMetrics = useMemo(() => {
    let filtered = selectedCategory === 'all' ? metrics : metricsByCategory[selectedCategory];

    if (search) {
      const searchLower = search.toLowerCase();
      filtered = filtered.filter(metric =>
        metric.display_name.toLowerCase().includes(searchLower) ||
        metric.description.toLowerCase().includes(searchLower) ||
        metric.category.toLowerCase().includes(searchLower)
      );
    }

    if (compatibleTasks.length > 0) {
      filtered = filtered.filter(metric =>
        metric.compatible_tasks.some(task => compatibleTasks.includes(task))
      );
    }

    return filtered;
  }, [metrics, metricsByCategory, selectedCategory, search, compatibleTasks]);

  const categoryTabs = [
    { id: 'all', label: 'All Metrics', count: metrics.length },
    ...Object.entries(CATEGORY_INFO).map(([key, info]) => ({
      id: key as MetricCategory,
      label: info.label,
      count: metricsByCategory[key as MetricCategory]?.length || 0
    }))
  ];

  const getSelectedMetricsPreview = () => {
    return selectedMetrics.map(selection => {
      const metric = metrics.find(m => m.id === selection.metric_id);
      return metric ? { metric, selection } : null;
    }).filter(Boolean);
  };

  if (loading && metrics.length === 0) {
    return (
      <div className={cn('space-y-6', className)}>
        <div className="text-center py-12">
          <Loading size="lg" text="Loading metrics..." />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={cn('space-y-6', className)}>
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-6 text-center">
          <p className="text-red-600 dark:text-red-400 mb-4">
            Failed to load metrics: {error.message}
          </p>
          <Button variant="primary" onClick={refetch}>
            Try Again
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className={cn('space-y-6', className)}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-neutral-900 dark:text-white">
            Metric Selector
          </h2>
          <p className="text-sm text-neutral-500 dark:text-neutral-400 mt-1">
            Choose metrics to evaluate your model's performance
          </p>
        </div>

        <div className="flex items-center gap-3">
          {selectedMetrics.length > 0 && (
            <Button variant="neutral" onClick={() => setShowPreview(!showPreview)}>
              {showPreview ? 'Hide' : 'Show'} Selection ({selectedMetrics.length})
            </Button>
          )}
          
          {selectedMetrics.length > 0 && (
            <Button variant="danger" onClick={clearSelection}>
              Clear All
            </Button>
          )}
        </div>
      </div>

      {/* Selected Metrics Preview */}
      {showPreview && selectedMetrics.length > 0 && (
        <Card className="p-4 bg-primary-50 dark:bg-primary-900/20 border-primary-200 dark:border-primary-800">
          <h3 className="font-medium text-neutral-900 dark:text-white mb-3">
            Selected Metrics ({selectedMetrics.length})
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {getSelectedMetricsPreview().map(({ metric, selection }) => (
              <div
                key={selection.metric_id}
                className="flex items-center justify-between p-3 bg-white dark:bg-neutral-800 rounded border"
              >
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-sm text-neutral-900 dark:text-white truncate">
                    {metric.display_name}
                  </p>
                  <p className="text-xs text-neutral-500 dark:text-neutral-400">
                    {metric.category}
                  </p>
                </div>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => removeMetric(selection.metric_id)}
                  className="ml-2"
                >
                  Remove
                </Button>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Search and Filters */}
      <div className="space-y-4">
        <Input
          type="text"
          placeholder="Search metrics by name, description, or category..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          leftIcon={
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          }
          rightElement={
            search && (
              <button
                onClick={() => setSearch('')}
                className="text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            )
          }
        />

        <Tabs
          value={selectedCategory}
          onValueChange={(value) => setSelectedCategory(value as MetricCategory | 'all')}
          tabs={categoryTabs.map(tab => ({
            value: tab.id,
            label: `${tab.label} (${tab.count})`,
            disabled: tab.count === 0
          }))}
        />
      </div>

      {/* Category Description */}
      {selectedCategory !== 'all' && (
        <Card className="p-4 bg-neutral-50 dark:bg-neutral-800">
          <div className="flex items-center gap-3">
            <span className="text-2xl">{CATEGORY_INFO[selectedCategory].icon}</span>
            <div>
              <h3 className="font-medium text-neutral-900 dark:text-white">
                {CATEGORY_INFO[selectedCategory].label} Metrics
              </h3>
              <p className="text-sm text-neutral-500 dark:text-neutral-400">
                {CATEGORY_INFO[selectedCategory].description}
              </p>
            </div>
          </div>
        </Card>
      )}

      {/* Results Summary */}
      {filteredMetrics.length > 0 && (
        <div className="flex items-center justify-between text-sm text-neutral-500 dark:text-neutral-400">
          <span>
            Showing {filteredMetrics.length} metric{filteredMetrics.length !== 1 ? 's' : ''}
            {search && ` matching "${search}"`}
          </span>
        </div>
      )}

      {/* Empty State */}
      {filteredMetrics.length === 0 && (
        <div className="text-center py-12">
          <div className="w-16 h-16 mx-auto mb-4 bg-neutral-100 dark:bg-neutral-800 rounded-full flex items-center justify-center">
            <svg className="w-8 h-8 text-neutral-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2-2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          </div>
          <h3 className="text-lg font-medium text-neutral-900 dark:text-white mb-2">
            No metrics found
          </h3>
          <p className="text-neutral-500 dark:text-neutral-400 mb-4">
            {search 
              ? `No metrics match "${search}". Try adjusting your search terms.`
              : 'No metrics available in this category.'
            }
          </p>
          {search && (
            <Button variant="neutral" onClick={() => setSearch('')}>
              Clear Search
            </Button>
          )}
        </div>
      )}

      {/* Metrics Grid */}
      {filteredMetrics.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredMetrics.map((metric) => (
            <MetricCompatibilityCard
              key={metric.id}
              metric={metric}
              datasetId={datasetId}
              isSelected={isMetricSelected(metric.id)}
              selection={getMetricSelection(metric.id)}
              onSelect={addMetric}
              onDeselect={removeMetric}
              onParametersChange={updateMetricParameters}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// Wrapper component that handles compatibility checking
function MetricCompatibilityCard({
  metric,
  datasetId,
  isSelected,
  selection,
  onSelect,
  onDeselect,
  onParametersChange
}: {
  metric: MetricInfo;
  datasetId?: string;
  isSelected: boolean;
  selection?: MetricSelection;
  onSelect: (metricId: string, parameters?: Record<string, any>) => void;
  onDeselect: (metricId: string) => void;
  onParametersChange?: (metricId: string, parameters: Record<string, any>) => void;
}) {
  const { compatibility } = useMetricCompatibility(
    datasetId && metric.id ? metric.id : null,
    datasetId || null
  );

  return (
    <MetricCard
      metric={metric}
      isSelected={isSelected}
      selection={selection}
      onSelect={onSelect}
      onDeselect={onDeselect}
      onParametersChange={onParametersChange}
      compatibility={compatibility}
    />
  );
}