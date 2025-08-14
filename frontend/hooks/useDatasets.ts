import { useState, useEffect, useMemo } from 'react';
import { apiClient } from '@/lib/api';
import { Dataset, DatasetItem, PaginatedResponse } from '@/types';

interface UseDatasetFilters {
  search?: string;
  project_id?: string;
  limit?: number;
  offset?: number;
}

export function useDatasets(filters: UseDatasetFilters = {}) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [pagination, setPagination] = useState({
    total: 0,
    hasNext: false,
    hasPrev: false
  });

  const fetchDatasets = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const response: PaginatedResponse<Dataset> = await apiClient.getDatasets({
        search: filters.search,
        project_id: filters.project_id,
        limit: filters.limit || 20,
        offset: filters.offset || 0
      });
      
      setDatasets(response.items);
      setPagination({
        total: response.total,
        hasNext: response.has_next,
        hasPrev: response.has_prev
      });
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Failed to fetch datasets'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDatasets();
  }, [filters.search, filters.project_id, filters.limit, filters.offset]);

  return {
    datasets,
    loading,
    error,
    pagination,
    refetch: fetchDatasets
  };
}

export function useDataset(datasetId: string | null) {
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const fetchDataset = async () => {
    if (!datasetId) return;
    
    try {
      setLoading(true);
      setError(null);
      
      const response = await apiClient.getDataset(datasetId);
      setDataset(response);
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Failed to fetch dataset'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDataset();
  }, [datasetId]);

  return {
    dataset,
    loading,
    error,
    refetch: fetchDataset
  };
}

export function useDatasetItems(datasetId: string | null, filters: { limit?: number; offset?: number } = {}) {
  const [items, setItems] = useState<DatasetItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [pagination, setPagination] = useState({
    total: 0,
    hasNext: false,
    hasPrev: false
  });

  const fetchItems = async () => {
    if (!datasetId) return;
    
    try {
      setLoading(true);
      setError(null);
      
      const response: PaginatedResponse<DatasetItem> = await apiClient.getDatasetItems(datasetId, {
        limit: filters.limit || 10,
        offset: filters.offset || 0
      });
      
      setItems(response.items);
      setPagination({
        total: response.total,
        hasNext: response.has_next,
        hasPrev: response.has_prev
      });
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Failed to fetch dataset items'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchItems();
  }, [datasetId, filters.limit, filters.offset]);

  return {
    items,
    loading,
    error,
    pagination,
    refetch: fetchItems
  };
}