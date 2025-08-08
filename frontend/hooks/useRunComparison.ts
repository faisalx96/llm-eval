'use client';

import { useState, useEffect } from 'react';
import { apiClient, RunComparison, APIError } from '../lib/api';

interface UseRunComparisonResult {
  comparison: RunComparison | null;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

export function useRunComparison(runId1: string | null, runId2: string | null): UseRunComparisonResult {
  const [comparison, setComparison] = useState<RunComparison | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchComparison = async () => {
    if (!runId1 || !runId2) {
      setComparison(null);
      setError(null);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const result = await apiClient.compareRuns(runId1, runId2);
      setComparison(result);
    } catch (err) {
      const errorMessage = err instanceof APIError ? err.message : 'Failed to load comparison';
      setError(errorMessage);
      setComparison(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchComparison();
  }, [runId1, runId2]);

  const refetch = async () => {
    await fetchComparison();
  };

  return {
    comparison,
    loading,
    error,
    refetch,
  };
}
