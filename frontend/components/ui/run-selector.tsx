'use client';

import React, { useState, useMemo } from 'react';
import { Input } from './input';
import { Badge } from './badge';
import { SkeletonBox } from './skeleton';
import { useRuns } from '@/hooks';
import { EvaluationRun } from '@/types';

interface RunSelectorProps {
  selectedRunId?: string;
  onRunSelect: (runId: string) => void;
  excludeRunId?: string;
  label: string;
  placeholder?: string;
  className?: string;
}

export const RunSelector: React.FC<RunSelectorProps> = ({
  selectedRunId,
  onRunSelect,
  excludeRunId,
  label,
  placeholder = "Select a run...",
  className = '',
}) => {
  const [search, setSearch] = useState('');
  const { runs, loading, error } = useRuns({
    search,
    status: 'completed', // Only allow comparing completed runs
    limit: 50,
  });

  const filteredRuns = useMemo(() => {
    if (!runs?.items) return [];
    return runs.items.filter(run => run.id !== excludeRunId);
  }, [runs?.items, excludeRunId]);

  const selectedRun = useMemo(() => {
    return filteredRuns.find(run => run.id === selectedRunId);
  }, [filteredRuns, selectedRunId]);

  const formatRunOption = (run: EvaluationRun) => {
    const date = new Date(run.created_at).toLocaleDateString();
    const duration = run.duration_seconds
      ? `${Math.round(run.duration_seconds)}s`
      : '';

    return `${run.name} (${date}${duration ? `, ${duration}` : ''})`;
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'success';
      case 'failed': return 'danger';
      case 'running': return 'warning';
      default: return 'secondary';
    }
  };

  if (loading) {
    return (
      <div className={className}>
        <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
          {label}
        </label>
        <SkeletonBox className="h-10 w-full" />
      </div>
    );
  }

  if (error) {
    return (
      <div className={className}>
        <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
          {label}
        </label>
        <div className="text-sm text-danger-600 dark:text-danger-400">
          Error loading runs: {error}
        </div>
      </div>
    );
  }

  return (
    <div className={className}>
      <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
        {label}
      </label>

      {/* Search input */}
      <div className="mb-2">
        <Input
          type="text"
          placeholder="Search runs..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="text-sm"
        />
      </div>

      {/* Selected run display */}
      {selectedRun && (
        <div className="mb-3 p-3 border border-neutral-200 dark:border-neutral-700 rounded-lg bg-neutral-50 dark:bg-neutral-800">
          <div className="flex items-center justify-between">
            <div>
              <div className="font-medium text-neutral-900 dark:text-white">
                {selectedRun.name}
              </div>
              <div className="text-sm text-neutral-500 dark:text-neutral-400">
                {new Date(selectedRun.created_at).toLocaleString()}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant={getStatusColor(selectedRun.status)} size="sm">
                {selectedRun.status}
              </Badge>
              {selectedRun.template_name && (
                <Badge variant="secondary" size="sm">
                  {selectedRun.template_name}
                </Badge>
              )}
            </div>
          </div>

          {selectedRun.description && (
            <div className="text-sm text-neutral-600 dark:text-neutral-300 mt-1">
              {selectedRun.description}
            </div>
          )}

          <div className="flex items-center gap-4 mt-2 text-xs text-neutral-500 dark:text-neutral-400">
            <span>{selectedRun.total_items} items</span>
            {selectedRun.duration_seconds && (
              <span>{Math.round(selectedRun.duration_seconds)}s duration</span>
            )}
            {selectedRun.dataset_name && (
              <span>{selectedRun.dataset_name}</span>
            )}
          </div>
        </div>
      )}

      {/* Run selection dropdown */}
      <select
        value={selectedRunId || ''}
        onChange={(e) => onRunSelect(e.target.value)}
        className="flex h-10 w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:border-neutral-600 dark:bg-neutral-800 dark:ring-offset-neutral-800"
      >
        <option value="">{placeholder}</option>
        {filteredRuns.map((run) => (
          <option key={run.id} value={run.id}>
            {formatRunOption(run)}
          </option>
        ))}
      </select>

      {filteredRuns.length === 0 && !loading && (
        <div className="mt-2 text-sm text-neutral-500 dark:text-neutral-400">
          No completed runs available for comparison.
        </div>
      )}
    </div>
  );
};
