import { useState, useEffect, useCallback } from 'react';
import { apiClient } from '../lib/api';
import { EvaluationRun, RunMetrics, RunItem, PaginatedResponse } from '../types';

interface UseRunDetailState {
  run: EvaluationRun | null;
  metrics: RunMetrics | null;
  items: PaginatedResponse<RunItem> | null;
  loading: boolean;
  error: string | null;
}

interface UseRunDetailReturn extends UseRunDetailState {
  refetch: () => Promise<void>;
  fetchItems: (limit?: number, offset?: number, status?: 'success' | 'failed' | 'pending') => Promise<void>;
  exportRun: (format?: 'excel' | 'json' | 'csv') => Promise<void>;
  clearError: () => void;
}

export function useRunDetail(runId: string): UseRunDetailReturn {
  const [state, setState] = useState<UseRunDetailState>({
    run: null,
    metrics: null,
    items: null,
    loading: true,
    error: null,
  });

  const fetchRunDetail = useCallback(async () => {
    if (!runId) return;

    setState(prev => ({ ...prev, loading: true, error: null }));

    try {
      // Fetch run details and metrics in parallel
      const [runResponse, metricsResponse] = await Promise.all([
        apiClient.getRun(runId),
        apiClient.getRunMetrics(runId).catch(() => null), // Metrics might not be available yet
      ]);

      setState({
        run: runResponse,
        metrics: metricsResponse,
        items: null, // Items will be fetched separately
        loading: false,
        error: null,
      });
    } catch (error) {
      setState(prev => ({
        ...prev,
        loading: false,
        error: error instanceof Error ? error.message : 'Failed to fetch run details',
      }));
    }
  }, [runId]);

  const refetch = useCallback(() => fetchRunDetail(), [fetchRunDetail]);

  const fetchItems = useCallback(async (limit: number = 20, offset: number = 0, status?: 'success' | 'failed' | 'pending') => {
    if (!runId) return;

    try {
      const itemsResponse = await apiClient.getRunItems(runId, { limit, offset, status });
      setState(prev => ({
        ...prev,
        items: itemsResponse,
        error: null,
      }));
    } catch (error) {
      setState(prev => ({
        ...prev,
        error: error instanceof Error ? error.message : 'Failed to fetch run items',
      }));
    }
  }, [runId]);

  const exportRun = useCallback(async (format: 'excel' | 'json' | 'csv' = 'excel') => {
    if (!runId) return;

    try {
      const blob = await apiClient.exportRun(runId, format);
      
      // Create download link
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `run-${runId}.${format === 'excel' ? 'xlsx' : format}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (error) {
      setState(prev => ({
        ...prev,
        error: error instanceof Error ? error.message : 'Failed to export run',
      }));
    }
  }, [runId]);

  const clearError = useCallback(() => {
    setState(prev => ({ ...prev, error: null }));
  }, []);

  // Fetch run details when runId changes
  useEffect(() => {
    fetchRunDetail();
  }, [fetchRunDetail]);

  return {
    ...state,
    refetch,
    fetchItems,
    exportRun,
    clearError,
  };
}