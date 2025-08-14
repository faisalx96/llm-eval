import { useState, useEffect, useMemo } from 'react';
import { apiClient } from '@/lib/api';
import { MetricInfo, MetricCategory, MetricSelection } from '@/types';

export function useMetrics(category?: MetricCategory) {
  const [metrics, setMetrics] = useState<MetricInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchMetrics = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const response = await apiClient.getMetrics(category);
      setMetrics(response);
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Failed to fetch metrics'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMetrics();
  }, [category]);

  const metricsByCategory = useMemo(() => {
    const grouped: Record<MetricCategory, MetricInfo[]> = {
      accuracy: [],
      semantic: [],
      safety: [],
      performance: [],
      custom: []
    };

    metrics.forEach(metric => {
      if (grouped[metric.category]) {
        grouped[metric.category].push(metric);
      }
    });

    return grouped;
  }, [metrics]);

  return {
    metrics,
    metricsByCategory,
    loading,
    error,
    refetch: fetchMetrics
  };
}

export function useMetric(metricId: string | null) {
  const [metric, setMetric] = useState<MetricInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const fetchMetric = async () => {
    if (!metricId) return;
    
    try {
      setLoading(true);
      setError(null);
      
      const response = await apiClient.getMetric(metricId);
      setMetric(response);
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Failed to fetch metric'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMetric();
  }, [metricId]);

  return {
    metric,
    loading,
    error,
    refetch: fetchMetric
  };
}

export function useMetricCompatibility(metricId: string | null, datasetId: string | null) {
  const [compatibility, setCompatibility] = useState<{ compatible: boolean; issues: string[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const checkCompatibility = async () => {
    if (!metricId || !datasetId) return;
    
    try {
      setLoading(true);
      setError(null);
      
      const response = await apiClient.validateMetricCompatibility(metricId, datasetId);
      setCompatibility(response);
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Failed to check compatibility'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    checkCompatibility();
  }, [metricId, datasetId]);

  return {
    compatibility,
    loading,
    error,
    refetch: checkCompatibility
  };
}

export function useMetricSelector(initialSelections: MetricSelection[] = []) {
  const [selectedMetrics, setSelectedMetrics] = useState<MetricSelection[]>(initialSelections);

  const addMetric = (metricId: string, parameters?: Record<string, any>, weight?: number) => {
    setSelectedMetrics(prev => {
      const existing = prev.find(m => m.metric_id === metricId);
      if (existing) {
        return prev.map(m => 
          m.metric_id === metricId 
            ? { ...m, parameters, weight }
            : m
        );
      }
      return [...prev, { metric_id: metricId, parameters, weight }];
    });
  };

  const removeMetric = (metricId: string) => {
    setSelectedMetrics(prev => prev.filter(m => m.metric_id !== metricId));
  };

  const updateMetricParameters = (metricId: string, parameters: Record<string, any>) => {
    setSelectedMetrics(prev => 
      prev.map(m => 
        m.metric_id === metricId 
          ? { ...m, parameters }
          : m
      )
    );
  };

  const updateMetricWeight = (metricId: string, weight: number) => {
    setSelectedMetrics(prev => 
      prev.map(m => 
        m.metric_id === metricId 
          ? { ...m, weight }
          : m
      )
    );
  };

  const isMetricSelected = (metricId: string) => {
    return selectedMetrics.some(m => m.metric_id === metricId);
  };

  const getMetricSelection = (metricId: string) => {
    return selectedMetrics.find(m => m.metric_id === metricId);
  };

  const clearSelection = () => {
    setSelectedMetrics([]);
  };

  return {
    selectedMetrics,
    addMetric,
    removeMetric,
    updateMetricParameters,
    updateMetricWeight,
    isMetricSelected,
    getMetricSelection,
    clearSelection,
    setSelectedMetrics
  };
}