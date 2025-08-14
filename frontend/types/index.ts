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

// Dataset types for Langfuse integration
export interface Dataset {
  id: string;
  name: string;
  description?: string;
  created_at: string;
  updated_at?: string;
  item_count: number;
  last_used?: string;
  metadata?: Record<string, any>;
  project_id?: string;
}

export interface DatasetItem {
  id: string;
  dataset_id: string;
  input: Record<string, any>;
  expected_output?: Record<string, any>;
  metadata?: Record<string, any>;
  created_at: string;
}

// Metrics catalog types
export type MetricCategory = 'accuracy' | 'semantic' | 'safety' | 'performance' | 'custom';

export interface MetricInfo {
  id: string;
  name: string;
  display_name: string;
  description: string;
  category: MetricCategory;
  requirements: string[];
  parameters?: Record<string, any>;
  compatible_tasks: string[];
  examples?: {
    input: any;
    output: any;
    score: number;
    explanation: string;
  }[];
  is_custom: boolean;
}

export interface MetricSelection {
  metric_id: string;
  parameters?: Record<string, any>;
  weight?: number;
}

// Template types
export interface EvaluationTemplate {
  id: string;
  name: string;
  display_name: string;
  description: string;
  category: 'qa' | 'summarization' | 'classification' | 'general' | 'custom';
  use_cases: string[];
  metrics: string[];
  required_fields: string[];
  optional_fields: string[];
  popularity_score: number;
  created_at: string;
  updated_at?: string;
  author?: string;
  tags: string[];
  sample_config?: Record<string, any>;
}

export interface TemplateRecommendation {
  template: EvaluationTemplate;
  confidence: number;
  reasons: string[];
  matching_keywords: string[];
}

// Task configuration types
export interface EndpointConfig {
  url: string;
  method: 'GET' | 'POST' | 'PUT' | 'PATCH';
  headers?: Record<string, string>;
  timeout?: number;
}

export interface AuthConfig {
  type: 'none' | 'bearer' | 'api_key' | 'oauth';
  credentials?: {
    token?: string;
    key?: string;
    secret?: string;
    header_name?: string;
  };
}

export interface RequestMapping {
  input_field: string;
  input_transformation?: string;
  additional_fields?: Record<string, any>;
}

export interface ResponseMapping {
  output_field: string;
  output_transformation?: string;
  error_field?: string;
}

export interface TaskConfiguration {
  id?: string;
  name: string;
  description?: string;
  endpoint: EndpointConfig;
  auth: AuthConfig;
  request_mapping: RequestMapping;
  response_mapping: ResponseMapping;
  test_input?: Record<string, any>;
  created_at?: string;
  updated_at?: string;
}

// Configuration wizard state
export interface WizardStep {
  id: string;
  title: string;
  description: string;
  is_completed: boolean;
  is_current: boolean;
  validation_errors?: string[];
}

export interface ConfigurationWizardState {
  current_step: number;
  steps: WizardStep[];
  configuration: Partial<TaskConfiguration>;
  test_results?: {
    success: boolean;
    response?: any;
    error?: string;
    response_time?: number;
  };
}
