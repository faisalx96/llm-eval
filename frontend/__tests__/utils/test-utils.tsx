import React, { ReactElement } from 'react'
import { render, RenderOptions } from '@testing-library/react'
import { EvaluationRun, RunComparison, RunMetrics } from '@/types'

// Mock data factories for testing
export const mockEvaluationRun = (overrides: Partial<EvaluationRun> = {}): EvaluationRun => ({
  id: 'test-run-id',
  name: 'Test Run',
  description: 'Test description',
  status: 'completed',
  template_id: 'template-1',
  template_name: 'Test Template',
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T01:00:00Z',
  started_at: '2024-01-01T00:01:00Z',
  completed_at: '2024-01-01T01:00:00Z',
  duration_seconds: 3540,
  total_items: 100,
  processed_items: 100,
  failed_items: 5,
  langfuse_session_id: 'session-123',
  dataset_name: 'test-dataset',
  metrics_config: {
    exact_match: { enabled: true },
    answer_relevancy: { enabled: true }
  },
  metadata: { version: '1.0' },
  ...overrides
})

export const mockRunMetrics = (overrides: Partial<RunMetrics> = {}): RunMetrics => ({
  run_id: 'test-run-id',
  overall_scores: {
    exact_match: 0.85,
    answer_relevancy: 0.92
  },
  metric_details: {
    exact_match: {
      score: 0.85,
      passed_items: 85,
      failed_items: 15,
      distribution: [0.1, 0.2, 0.3, 0.4]
    },
    answer_relevancy: {
      score: 0.92,
      passed_items: 92,
      failed_items: 8,
      distribution: [0.05, 0.15, 0.25, 0.55]
    }
  },
  performance_stats: {
    avg_response_time: 1.2,
    total_tokens: 50000,
    total_cost: 12.5
  },
  error_analysis: {
    error_types: {
      'timeout': 3,
      'api_error': 2
    },
    common_failures: ['Request timeout', 'Rate limit exceeded']
  },
  ...overrides
})

export const mockRunComparison = (overrides: Partial<RunComparison> = {}): RunComparison => {
  const run1 = mockEvaluationRun({ id: 'run-1', name: 'Run 1' })
  const run2 = mockEvaluationRun({ id: 'run-2', name: 'Run 2' })
  const metrics1 = mockRunMetrics({ run_id: 'run-1' })
  const metrics2 = mockRunMetrics({
    run_id: 'run-2',
    overall_scores: {
      exact_match: 0.90,
      answer_relevancy: 0.88
    }
  })

  return {
    run1: { ...run1, metrics: metrics1 },
    run2: { ...run2, metrics: metrics2 },
    comparison: {
      metrics: {
        exact_match: {
          run1_score: 0.85,
          run2_score: 0.90,
          difference: 0.05,
          percentage_change: 5.88,
          improvement_direction: 'better' as const
        },
        answer_relevancy: {
          run1_score: 0.92,
          run2_score: 0.88,
          difference: -0.04,
          percentage_change: -4.35,
          improvement_direction: 'worse' as const
        }
      },
      overall_performance: {
        winner: 'run2' as const,
        significant_improvements: 1,
        significant_regressions: 1
      },
      statistical_analysis: {
        exact_match: {
          p_value: 0.02,
          confidence_interval: [0.01, 0.09] as [number, number],
          is_significant: true,
          effect_size: 0.3
        },
        answer_relevancy: {
          p_value: 0.08,
          confidence_interval: [-0.08, 0.00] as [number, number],
          is_significant: false,
          effect_size: 0.1
        }
      }
    },
    item_level_comparison: [
      {
        item_id: 'item-1',
        run1_scores: { exact_match: 1.0, answer_relevancy: 0.95 },
        run2_scores: { exact_match: 1.0, answer_relevancy: 0.85 },
        differences: { exact_match: 0.0, answer_relevancy: -0.10 },
        input_data: { question: 'What is the capital of France?', context: 'Geography facts' },
        run1_status: 'success' as const,
        run2_status: 'success' as const
      },
      {
        item_id: 'item-2',
        run1_scores: { exact_match: 0.0, answer_relevancy: 0.70 },
        run2_scores: { exact_match: 1.0, answer_relevancy: 0.90 },
        differences: { exact_match: 1.0, answer_relevancy: 0.20 },
        input_data: { question: 'What is machine learning?', context: 'Technology concepts' },
        run1_status: 'failed' as const,
        run2_status: 'success' as const
      }
    ],
    ...overrides
  }
}

// Custom render function that includes common providers
interface CustomRenderOptions extends Omit<RenderOptions, 'wrapper'> {
  // Add any provider props here if needed
}

const customRender = (ui: ReactElement, options?: CustomRenderOptions) => {
  const Wrapper = ({ children }: { children: React.ReactNode }) => {
    // Add providers here if needed (e.g., ThemeProvider, QueryClient, etc.)
    return <>{children}</>
  }

  return render(ui, { wrapper: Wrapper, ...options })
}

// Re-export everything
export * from '@testing-library/react'
export { customRender as render }

// Helper functions for common testing scenarios
export const waitForLoadingToFinish = () => {
  return new Promise(resolve => setTimeout(resolve, 0))
}

export const mockApiResponse = <T>(data: T, delay = 0): Promise<T> => {
  return new Promise(resolve => {
    setTimeout(() => resolve(data), delay)
  })
}

export const mockApiError = (message: string, delay = 0): Promise<never> => {
  return new Promise((_, reject) => {
    setTimeout(() => reject(new Error(message)), delay)
  })
}
