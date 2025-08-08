// LLM-Eval platform type definitions

export type RunStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface EvaluationRun {
  id: string;
  name: string;
  description?: string;
  status: RunStatus;
  template_id?: string;
  template_name?: string;
  created_at: string;
  updated_at: string;
  started_at?: string;
  completed_at?: string;
  duration_seconds?: number;
  total_items: number;
  processed_items: number;
  failed_items: number;
  langfuse_session_id?: string;
  dataset_name?: string;
  metrics_config: Record<string, any>;
  metadata?: Record<string, any>;
  error_message?: string;
}

export interface RunMetrics {
  run_id: string;
  overall_scores: Record<string, number>;
  metric_details: Record<string, {
    score: number;
    passed_items: number;
    failed_items: number;
    distribution: number[];
  }>;
  performance_stats: {
    avg_response_time: number;
    total_tokens?: number;
    total_cost?: number;
  };
  error_analysis: {
    error_types: Record<string, number>;
    common_failures: string[];
  };
}

export interface FilterOptions {
  search?: string;
  status?: RunStatus;
  template?: string;
  dateFrom?: string;
  dateTo?: string;
  limit?: number;
  offset?: number;
  sortBy?: 'created_at' | 'updated_at' | 'name' | 'status' | 'duration_seconds';
  sortOrder?: 'asc' | 'desc';
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  has_next: boolean;
  has_prev: boolean;
}

export interface ChartData {
  labels: string[];
  datasets: {
    label: string;
    data: number[];
    backgroundColor?: string | string[];
    borderColor?: string | string[];
  }[];
}

export interface WebSocketMessage {
  type: 'run_update' | 'progress' | 'error' | 'completion';
  run_id: string;
  data: any;
  timestamp: string;
}

export interface RunItem {
  id: string;
  run_id: string;
  input_data: Record<string, any>;
  output_data?: Record<string, any>;
  expected_output?: Record<string, any>;
  scores: Record<string, number>;
  status: 'success' | 'failed' | 'pending';
  error_message?: string;
  response_time?: number;
  tokens_used?: number;
  cost?: number;
  created_at: string;
  processed_at?: string;
}

export interface RunComparison {
  run1: EvaluationRun & { metrics: RunMetrics };
  run2: EvaluationRun & { metrics: RunMetrics };
  comparison: {
    metrics: {
      [metricName: string]: {
        run1_score: number;
        run2_score: number;
        difference: number;
        percentage_change: number;
        improvement_direction: 'better' | 'worse' | 'neutral';
      };
    };
    overall_performance: {
      winner: 'run1' | 'run2' | 'tie';
      significant_improvements: number;
      significant_regressions: number;
    };
    statistical_analysis: {
      [metricName: string]: {
        p_value?: number;
        confidence_interval?: [number, number];
        is_significant: boolean;
        effect_size?: number;
      };
    };
  };
  item_level_comparison: Array<{
    item_id: string;
    run1_scores: Record<string, number>;
    run2_scores: Record<string, number>;
    differences: Record<string, number>;
    input_data: Record<string, any>;
    run1_status: 'success' | 'failed' | 'pending';
    run2_status: 'success' | 'failed' | 'pending';
  }>;
}
