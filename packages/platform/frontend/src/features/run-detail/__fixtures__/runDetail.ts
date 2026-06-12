import type { ApprovalContext, RunDetail, RunItemDetail, RunItemSlim } from '@/api/runDetail'
import type { Me, Project } from '@/api/types'

/**
 * Test fixtures mirroring the live /v1 payload shapes (captured from the
 * seeded backend on 2026-06-12).
 */

export const OWNER = {
  id: 'user-owner',
  email: 'owner@local',
  display_name: 'Olive Owner',
}

export const REVIEWER = {
  id: 'user-reviewer',
  email: 'reviewer@local',
  display_name: 'Renata Reviewer',
}

const PROJECT_BASE: Project = {
  id: 'p1',
  name: 'Support Copilot',
  slug: 'support-copilot',
  description: '',
  is_active: true,
  member_count: 2,
  run_count: 6,
  role: 'MEMBER',
  created_at: '2026-06-01T00:00:00Z',
  updated_at: '2026-06-01T00:00:00Z',
}

export function makeMe(overrides: Partial<Me> & { projectRole?: string } = {}): Me {
  const { projectRole, ...rest } = overrides
  return {
    id: OWNER.id,
    email: OWNER.email,
    display_name: OWNER.display_name,
    title: '',
    role: 'MEMBER',
    auth_type: 'none',
    auth_provider: null,
    needs_admin_bootstrap: false,
    can_bootstrap_admin: false,
    projects: [{ ...PROJECT_BASE, role: projectRole ?? 'MEMBER' }],
    default_project: null,
    ...rest,
  }
}

export function makeApproval(overrides: Partial<ApprovalContext> = {}): ApprovalContext {
  return {
    status: 'SUBMITTED',
    submitted_by: OWNER,
    submitted_at: '2026-06-11T07:47:50Z',
    decided_by: null,
    decided_at: null,
    comment: '',
    ...overrides,
  }
}

export function makeRun(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    id: '0ea0b594-de57-42f6-9c89-010b681baa6f',
    name: 'support-rag-llama-3.1-70b',
    task: 'support_rag',
    dataset: 'support_qa.csv',
    model: 'llama-3.1-70b',
    status: 'COMPLETED',
    created_at: '2026-05-21T05:51:16Z',
    started_at: '2026-05-21T05:43:42Z',
    ended_at: '2026-05-21T06:01:16Z',
    duration_ms: 1053640,
    owner: OWNER,
    total_items: 3,
    completed_items: 3,
    error_items: 1,
    progress_pct: 1,
    metric_averages: { exact_match: 0.5 },
    version: { branch: 'main', commit: 'abc1234' },
    group_key: 'support_rag|support_qa.csv|llama-3.1-70b',
    run_config: {},
    run_metadata: {},
    metrics: ['exact_match', 'answer_relevancy'],
    metric_stats: [
      {
        name: 'exact_match',
        avg: 0.5,
        pass_count: 6,
        fail_count: 6,
        distribution: [
          { label: '0.00-0.25', count: 6 },
          { label: '0.25-0.50', count: 0 },
          { label: '0.50-0.75', count: 0 },
          { label: '0.75-1.00', count: 6 },
        ],
      },
      {
        name: 'answer_relevancy',
        avg: 0.53,
        pass_count: 6,
        fail_count: 6,
        distribution: [
          { label: '0.00-0.25', count: 6 },
          { label: '0.25-0.50', count: 0 },
          { label: '0.50-0.75', count: 0 },
          { label: '0.75-1.00', count: 6 },
        ],
      },
    ],
    trace_stats: { avg_tokens: 0, avg_llm_calls: 0, avg_tool_calls: 0 },
    approval: null,
    error_summary: { task_errors: 0, types: {} },
    ...overrides,
  }
}

export function makeItem(overrides: Partial<RunItemSlim> = {}): RunItemSlim {
  return {
    item_id: `item_${overrides.index ?? 0}`,
    index: 0,
    status: 'completed',
    input_preview: 'How do I reset my password?',
    output_preview: 'Go to Settings > Security.',
    expected_preview: 'Go to Settings > Security.',
    latency_ms: 250,
    retry_count: 0,
    metric_values: { exact_match: 1, answer_relevancy: 1 },
    has_trace: true,
    root_cause: null,
    root_cause_source: null,
    review_correction_status: null,
    ...overrides,
  }
}

/** One pass, one metric fail, one task error — failures-first fodder. */
export function makeItems(): RunItemSlim[] {
  return [
    makeItem({ index: 0, item_id: 'item_pass' }),
    makeItem({
      index: 1,
      item_id: 'item_fail',
      input_preview: 'Why was my card charged twice?',
      metric_values: { exact_match: 0, answer_relevancy: 0.05 },
    }),
    makeItem({
      index: 2,
      item_id: 'item_error',
      status: 'failed',
      input_preview: 'benchmark query 2',
      output_preview: '',
      metric_values: {},
      has_trace: false,
      latency_ms: null,
    }),
  ]
}

export function makeItemDetail(overrides: Partial<RunItemDetail> = {}): RunItemDetail {
  return {
    item_id: 'item_fail',
    index: 1,
    status: 'completed',
    input: 'Why was my card charged twice?',
    output: 'I do not have enough information to answer that.',
    expected: 'Duplicate authorization holds release within 3-5 business days.',
    error: null,
    latency_ms: 129.2,
    retry_count: 0,
    item_metadata: {
      category: 'billing',
      difficulty: 'medium',
      root_cause: 'retrieval_miss',
      root_cause_source: 'human',
      root_cause_detail: 'Retriever surfaced the wrong doc',
      solution: 're-chunk_billing_corpus',
    },
    metric_values: { exact_match: 0, answer_relevancy: 0.05 },
    metric_meta: { answer_relevancy: { judge: 'word-overlap-v2' } },
    trace: { has_trace: true, trace_id: 'trace-1', trace_url: '' },
    review_correction_status: 'pending',
    ...overrides,
  }
}
