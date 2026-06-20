/**
 * Trace domain types, modelled 1:1 on the payload of
 * `GET /api/runs/{run_id}/items/{item_id}/trace` (and the `spans` arrays of
 * `GET /api/runs/{run_id}/spans`). The endpoint is typed `unknown` in
 * src/api/generated.d.ts, so these interfaces are the narrowing contract —
 * shapes verified against live captures in __fixtures__/.
 *
 * Ported from the implicit data model of the legacy viewer
 * (qym_platform/_static/dashboard/trace_viewer.js, "S.data" usage throughout).
 */

/** A single OTEL span event (legacy trace_viewer.js L562-572, L1023-1034). */
export interface SpanEvent {
  name: string
  timestamp_ns?: number | null
  attributes?: Record<string, unknown>
}

/** A raw span as returned by the backend. */
export interface TraceSpan {
  trace_id?: string | null
  span_id: string
  parent_span_id?: string | null
  name?: string | null
  /** OTEL span kind (INTERNAL/CLIENT/...) — display kind comes from attributes. */
  kind?: string | null
  start_time_ns?: number | null
  end_time_ns?: number | null
  duration_ms?: number | null
  status?: string | null
  attributes?: Record<string, unknown>
  events?: SpanEvent[]
  links?: unknown[]
}

/** Trace-level rollup emitted by the backend (legacy L488-498, L1197-1207). */
export interface TraceSummary {
  span_count?: number
  root_count?: number
  error_count?: number
  duration_ms?: number | null
  started_at_ns?: number | null
  ended_at_ns?: number | null
  has_orphans?: boolean
  orphan_count?: number
}

/** One retry attempt of a run item (legacy normalizeAttempts, L150-187). */
export interface TraceAttempt {
  attempt_number: number
  status?: string | null
  latency_ms?: number | null
  task_started_at_ms?: number | null
  trace_id?: string | null
  trace_url?: string | null
  error?: string | null
  is_last_attempt?: boolean
  summary?: TraceSummary
  spans?: TraceSpan[]
}

export interface TraceItemMeta {
  run_id?: string
  item_id?: string
  trace_id?: string | null
  trace_url?: string | null
  retry_count?: number
  latency_ms?: number | null
}

/** Full payload of GET /api/runs/{run_id}/items/{item_id}/trace. */
export interface TraceData {
  item?: TraceItemMeta
  summary?: TraceSummary
  spans?: TraceSpan[]
  attempts?: TraceAttempt[]
}

/**
 * Display categories of a span (legacy ICONS/KIND_COLORS keys, L36-50).
 * Derived from `attributes["openinference.span.kind"]` — see classifySpan.
 */
export type SpanKind =
  | 'LLM'
  | 'TOOL'
  | 'AGENT'
  | 'CHAIN'
  | 'EVALUATOR'
  | 'RETRIEVER'
  | 'EMBED'
  | 'DEFAULT'

/** Normalized span status (legacy statusCls, L145-148). */
export type SpanStatus = 'ok' | 'error' | 'unset'

/** A span decorated with tree bookkeeping (legacy buildTree node fields, L221-228). */
export interface SpanNode extends TraceSpan {
  /** Original index in the flat span list (stable sort tiebreak). */
  index: number
  children: SpanNode[]
  depth: number
  /** True when parent_span_id is set but the parent span is missing. */
  orphan: boolean
}

/** Result of buildSpanTree (legacy `tree` object, L247). */
export interface SpanTree {
  roots: SpanNode[]
  byId: Map<string, SpanNode>
  /** Every node in original input order (including pruned-from-roots ones removed). */
  nodes: SpanNode[]
}

/** Score extracted from `score.*` span events (legacy extractScores, L562-572). */
export interface SpanScore {
  name: string
  value: unknown
  label: string
  explanation: string
}

/** Error details from exception events / error attributes (legacy L1023-1034). */
export interface SpanErrorInfo {
  type: string
  message: string
  stacktrace: string
}

/** Normalized horizontal waterfall geometry, in percent of the trace window. */
export interface WaterfallSegment {
  leftPct: number
  widthPct: number
}

/** Time bounds of a trace (legacy computeBounds, L488-498). */
export interface TraceBounds {
  start: number | null
  end: number | null
  total: number
}
