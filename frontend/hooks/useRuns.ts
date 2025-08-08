import { useState, useEffect, useCallback } from 'react';
import { apiClient } from '../lib/api';
import { EvaluationRun, FilterOptions, PaginatedResponse } from '../types';

interface UseRunsState {
  runs: EvaluationRun[];
  loading: boolean;
  error: string | null;
  total: number;
  hasNext: boolean;
  hasPrev: boolean;
}

interface UseRunsReturn extends UseRunsState {
  refetch: () => Promise<void>;
  setFilters: (filters: FilterOptions) => void;
  filters: FilterOptions;
  clearError: () => void;
}

export function useRuns(initialFilters: FilterOptions = {}): UseRunsReturn {
  const [state, setState] = useState<UseRunsState>({
    runs: [],
    loading: true,
    error: null,
    total: 0,
    hasNext: false,
    hasPrev: false,
  });

  const [filters, setFilters] = useState<FilterOptions>({
    limit: 20,
    offset: 0,
    sortBy: 'created_at',
    sortOrder: 'desc',
    ...initialFilters,
  });

  const fetchRuns = useCallback(async (customFilters?: FilterOptions) => {
    setState(prev => ({ ...prev, loading: true, error: null }));

    try {
      const filtersToUse = customFilters || filters;
      const response: PaginatedResponse<EvaluationRun> = await apiClient.getRuns(filtersToUse);

      setState({
        runs: response.items,
        loading: false,
        error: null,
        total: response.total,
        hasNext: response.has_next || false,
        hasPrev: response.has_prev || false,
      });
    } catch (error) {
      setState(prev => ({
        ...prev,
        loading: false,
        error: error instanceof Error ? error.message : 'Failed to fetch runs',
      }));
    }
  }, [filters]);

  const refetch = useCallback(() => fetchRuns(), [fetchRuns]);

  const clearError = useCallback(() => {
    setState(prev => ({ ...prev, error: null }));
  }, []);

  // Fetch runs when filters change (with throttling)
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      fetchRuns();
    }, 300); // 300ms throttle

    return () => clearTimeout(timeoutId);
  }, [JSON.stringify(filters)]); // Use JSON.stringify to properly compare filters

  return {
    ...state,
    refetch,
    setFilters,
    filters,
    clearError,
  };
}
