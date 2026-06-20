/**
 * Pure span-level helpers ported from the legacy trace viewer
 * (qym_platform/_static/dashboard/trace_viewer.js). Each function notes the
 * legacy line range it was ported from.
 *
 * Hue policy (differs from legacy hex literals, L47-50): colors are emitted
 * as EXISTING design tokens only.
 *   LLM        legacy #f472b6 → var(--chart-4)        (same pink hue)
 *   TOOL       legacy #fbbf24 → var(--chart-5)        (same amber hue)
 *   AGENT      legacy #34d399 → var(--accent-primary) (teal; legacy emerald
 *              is in the reserved pass/fail green family, so it moves to the
 *              neutral teal family per the design rules)
 *   CHAIN      legacy #60a5fa → var(--info)           (blue)
 *   EVALUATOR  legacy #a78bfa → var(--accent-tertiary) (purple — kept ONLY
 *              because legacy used purple for these AI/LLM-judge spans)
 *   RETRIEVER  legacy #38bdf8 → var(--accent-secondary) (sky blue)
 *   EMBED      legacy #94a3b8 → var(--text-muted)     (neutral)
 *   DEFAULT    legacy #6b7280 → var(--text-dim)       (neutral)
 */

import type {
  SpanErrorInfo,
  SpanKind,
  SpanScore,
  SpanStatus,
  TraceSpan,
} from './types'

const KNOWN_KINDS: ReadonlySet<string> = new Set([
  'LLM',
  'TOOL',
  'AGENT',
  'CHAIN',
  'EVALUATOR',
  'RETRIEVER',
  'EMBED',
])

/** Kind → CSS color token (legacy KIND_COLORS, L47-50 — see header). */
export const SPAN_KIND_HUES: Record<SpanKind, string> = {
  LLM: 'var(--chart-4)',
  TOOL: 'var(--chart-5)',
  AGENT: 'var(--accent-primary)',
  CHAIN: 'var(--info)',
  EVALUATOR: 'var(--accent-tertiary)',
  RETRIEVER: 'var(--accent-secondary)',
  EMBED: 'var(--text-muted)',
  DEFAULT: 'var(--text-dim)',
}

function attrs(span: TraceSpan): Record<string, unknown> {
  return span.attributes ?? {}
}

function str(value: unknown): string {
  return value == null ? '' : String(value)
}

/**
 * Classify a span into a display kind.
 * Ported from legacy `spanKind` (trace_viewer.js L111-119): reads the
 * OpenInference / gen_ai attribute aliases, uppercases, strips non-letters,
 * then maps EMBEDDING→EMBED and RETRIEVE/RETRIEVER→RETRIEVER.
 */
export function classifySpan(span: TraceSpan): SpanKind {
  const a = attrs(span)
  const raw =
    a['openinference.span.kind'] ??
    a['ai.openinference.span.kind'] ??
    a['span.kind'] ??
    span.kind ??
    ''
  const k = String(raw)
    .toUpperCase()
    .replace(/[^A-Z]/g, '')
  if (KNOWN_KINDS.has(k)) return k as SpanKind
  if (k === 'EMBEDDING') return 'EMBED'
  if (k === 'RETRIEVE' || k === 'RETRIEVER') return 'RETRIEVER'
  return 'DEFAULT'
}

/**
 * Model name for LLM spans, basename of provider/model paths.
 * Ported from legacy `spanModel` (L121-126).
 */
export function spanModel(span: TraceSpan): string {
  const a = attrs(span)
  const m = a['llm.model_name'] ?? a['gen_ai.request.model'] ?? a['gen_ai.response.model'] ?? ''
  if (typeof m === 'string' && m.includes('/')) return m.split('/').pop() ?? ''
  return typeof m === 'string' ? m : ''
}

/** Total token count of an LLM span. Ported from legacy `spanTokens` (L128-131). */
export function spanTokens(span: TraceSpan): number | null {
  const a = attrs(span)
  const n = Number(a['llm.token_count.total'] ?? a['gen_ai.usage.total_tokens'] ?? 0)
  return Number.isFinite(n) && n !== 0 ? n : null
}

/** Total cost of an LLM span. Ported from legacy `spanCost` (L133-136). */
export function spanCost(span: TraceSpan): number | null {
  const n = Number(attrs(span)['llm.cost.total'] ?? 0)
  return Number.isFinite(n) && n !== 0 ? n : null
}

/**
 * Normalize the span status string to ok/error/unset.
 * Ported from legacy `statusCls` (L145-148).
 */
export function spanStatus(span: Pick<TraceSpan, 'status'> | null | undefined): SpanStatus {
  const u = String(span?.status ?? '').toUpperCase()
  return u === 'ERROR' ? 'error' : u === 'OK' ? 'ok' : 'unset'
}

/** True when the span itself carries ERROR status (legacy `_nodeIsError`, L210-212). */
export function isErrorSpan(span: TraceSpan): boolean {
  return spanStatus(span) === 'error'
}

export interface SpanMessageToolCall {
  name: string
  arguments: string
  id: string
}

export interface SpanMessage {
  role: string
  content: string
  toolCalls: SpanMessageToolCall[]
  toolCallId: string
  reasoning: string
}

/**
 * Extract chat messages from flattened OpenInference attributes
 * (`{prefix}.{i}.message.*`). Ported from legacy `extractMessages` (L501-536),
 * including multi-part `message.contents.{j}.message_content.text` joining
 * and tool_call extraction. Caps (50 messages / 20 parts / 20 tool calls)
 * match legacy.
 */
export function extractMessages(
  attributes: Record<string, unknown>,
  prefix: 'llm.input_messages' | 'llm.output_messages',
): SpanMessage[] {
  const msgs: SpanMessage[] = []
  for (let i = 0; i < 50; i++) {
    const role = attributes[`${prefix}.${i}.message.role`]
    if (role == null) break
    let content = str(attributes[`${prefix}.${i}.message.content`])
    if (!content) {
      const parts: string[] = []
      for (let j = 0; j < 20; j++) {
        const base = `${prefix}.${i}.message.contents.${j}.message_content`
        const type = attributes[`${base}.type`]
        if (type == null) break
        if (String(type) === 'text') {
          const text = attributes[`${base}.text`]
          if (text) parts.push(String(text))
        }
      }
      if (parts.length) content = parts.join('\n\n')
    }
    const toolCalls: SpanMessageToolCall[] = []
    for (let j = 0; j < 20; j++) {
      const tcName = attributes[`${prefix}.${i}.message.tool_calls.${j}.tool_call.function.name`]
      if (tcName == null) break
      toolCalls.push({
        name: String(tcName),
        arguments: str(attributes[`${prefix}.${i}.message.tool_calls.${j}.tool_call.function.arguments`]),
        id: str(attributes[`${prefix}.${i}.message.tool_calls.${j}.tool_call.id`]),
      })
    }
    msgs.push({
      role: String(role),
      content,
      toolCalls,
      toolCallId: str(attributes[`${prefix}.${i}.message.tool_call_id`]),
      reasoning: str(attributes[`${prefix}.${i}.message.reasoning`]),
    })
  }
  return msgs
}

/**
 * Extract `score.*` events into score chips.
 * Ported from legacy `extractScores` (L562-572).
 */
export function extractScores(span: TraceSpan): SpanScore[] {
  const events = Array.isArray(span.events) ? span.events : []
  return events
    .filter((ev) => typeof ev.name === 'string' && ev.name.startsWith('score.'))
    .map((ev) => {
      const a = ev.attributes ?? {}
      return {
        name: str(a['score.name']) || ev.name.replace('score.', ''),
        value: a['score.value'],
        label: str(a['score.label']),
        explanation: str(a['score.explanation']),
      }
    })
}

/**
 * Concrete error details for a span: prefers the OTEL `exception` event,
 * falls back to error.* / exception.* / otel.status_description attributes.
 * Ported from legacy `extractErrorInfo` (L1023-1034).
 */
export function extractErrorInfo(span: TraceSpan): SpanErrorInfo | null {
  const events = Array.isArray(span.events) ? span.events : []
  const ex = events.find((ev) => ev.name === 'exception')
  if (ex) {
    const a = ex.attributes ?? {}
    return {
      type: str(a['exception.type']),
      message: str(a['exception.message']),
      stacktrace: str(a['exception.stacktrace']),
    }
  }
  const a = attrs(span)
  const msg = str(a['error.message'] || a['exception.message'] || a['otel.status_description'])
  if (msg) {
    return {
      type: str(a['error.type'] || a['exception.type']),
      message: msg,
      stacktrace: str(a['exception.stacktrace']),
    }
  }
  return null
}

/**
 * Reasoning text attached to a span: `gen_ai.completion.{i}.reasoning`
 * attributes, else `output.value` JSON `choices[].message.reasoning`.
 * Ported from legacy `extractReasoning` (L1085-1106).
 */
export function extractReasoning(span: TraceSpan): string | null {
  const a = attrs(span)
  for (let i = 0; i < 5; i++) {
    const r = a[`gen_ai.completion.${i}.reasoning`]
    if (r) return String(r)
  }
  try {
    const ov = a['output.value']
    if (typeof ov === 'string') {
      const parsed: unknown = JSON.parse(ov)
      if (parsed && typeof parsed === 'object' && Array.isArray((parsed as { choices?: unknown }).choices)) {
        for (const c of (parsed as { choices: unknown[] }).choices) {
          const r = (c as { message?: { reasoning?: unknown } } | null)?.message?.reasoning
          if (r) return String(r)
        }
      }
    }
  } catch {
    // not JSON — fall through
  }
  return null
}

/**
 * Reasoning token count from usage attributes or the response JSON.
 * Ported from legacy `spanReasoningTokens` (L1108-1124).
 */
export function spanReasoningTokens(span: TraceSpan): number {
  const a = attrs(span)
  const direct =
    a['llm.token_count.completion_details.reasoning'] ??
    a['gen_ai.usage.completion_tokens_details.reasoning_tokens'] ??
    a['gen_ai.usage.output_tokens_details.reasoning'] ??
    a['gen_ai.usage.reasoning_tokens']
  const parsedDirect = Number(direct ?? 0)
  if (Number.isFinite(parsedDirect) && parsedDirect > 0) return parsedDirect
  try {
    const parsed: unknown = JSON.parse(String(a['output.value'] ?? ''))
    const tokens = (
      parsed as { usage?: { completion_tokens_details?: { reasoning_tokens?: unknown } } } | null
    )?.usage?.completion_tokens_details?.reasoning_tokens
    const parsedTokens = Number(tokens ?? 0)
    return Number.isFinite(parsedTokens) && parsedTokens > 0 ? parsedTokens : 0
  } catch {
    return 0
  }
}

/** Whether a span carries any reasoning signal (legacy `spanHasReasoning`, L1126-1128). */
export function spanHasReasoning(span: TraceSpan): boolean {
  return Boolean(extractReasoning(span)) || spanReasoningTokens(span) > 0
}
