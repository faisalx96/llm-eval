import { useState, useEffect, useMemo } from 'react';
import { apiClient } from '@/lib/api';
import { EvaluationTemplate, TemplateRecommendation, PaginatedResponse } from '@/types';

interface UseTemplateFilters {
  category?: string;
  search?: string;
  limit?: number;
}

export function useTemplates(filters: UseTemplateFilters = {}) {
  const [templates, setTemplates] = useState<EvaluationTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [pagination, setPagination] = useState({
    total: 0,
    hasNext: false,
    hasPrev: false
  });

  const fetchTemplates = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const response: PaginatedResponse<EvaluationTemplate> = await apiClient.getTemplates({
        category: filters.category,
        search: filters.search,
        limit: filters.limit || 20
      });
      
      setTemplates(response.items);
      setPagination({
        total: response.total,
        hasNext: response.has_next,
        hasPrev: response.has_prev
      });
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Failed to fetch templates'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTemplates();
  }, [filters.category, filters.search, filters.limit]);

  const templatesByCategory = useMemo(() => {
    const grouped: Record<string, EvaluationTemplate[]> = {
      qa: [],
      summarization: [],
      classification: [],
      general: [],
      custom: []
    };

    templates.forEach(template => {
      if (grouped[template.category]) {
        grouped[template.category].push(template);
      }
    });

    return grouped;
  }, [templates]);

  return {
    templates,
    templatesByCategory,
    loading,
    error,
    pagination,
    refetch: fetchTemplates
  };
}

export function useTemplate(templateId: string | null) {
  const [template, setTemplate] = useState<EvaluationTemplate | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const fetchTemplate = async () => {
    if (!templateId) return;
    
    try {
      setLoading(true);
      setError(null);
      
      const response = await apiClient.getTemplate(templateId);
      setTemplate(response);
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Failed to fetch template'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTemplate();
  }, [templateId]);

  return {
    template,
    loading,
    error,
    refetch: fetchTemplate
  };
}

export function useTemplateRecommendations() {
  const [recommendations, setRecommendations] = useState<TemplateRecommendation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const getRecommendations = async (
    description: string, 
    sampleData?: Record<string, any>, 
    useCase?: string
  ) => {
    if (!description.trim()) {
      setRecommendations([]);
      return;
    }

    try {
      setLoading(true);
      setError(null);
      
      const response = await apiClient.recommendTemplates(description, sampleData, useCase);
      setRecommendations(response);
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Failed to get recommendations'));
    } finally {
      setLoading(false);
    }
  };

  const clearRecommendations = () => {
    setRecommendations([]);
  };

  return {
    recommendations,
    loading,
    error,
    getRecommendations,
    clearRecommendations
  };
}