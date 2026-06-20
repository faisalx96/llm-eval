/**
 * Span-tree construction ported from the legacy trace viewer
 * (qym_platform/_static/dashboard/trace_viewer.js). Pure: input spans are
 * never mutated — nodes are shallow copies with tree bookkeeping fields.
 *
 * Pipeline (legacy buildTree, L221-255):
 *   1. wrap spans into nodes, link children by parent_span_id; spans whose
 *      parent is missing become roots flagged `orphan`
 *   2. sort siblings by start_time_ns (nulls last), stable on input order
 *   3. collapse framework noise + dedupe sibling spans (L259-486)
 *   4. dedupe overlapping duplicate LLM spans globally (L387-406)
 *   5. recompute depths
 */

import {
  classifySpan,
  extractErrorInfo,
  extractMessages,
  isErrorSpan,
  spanHasReasoning,
  spanModel,
  spanReasoningTokens,
  spanTokens,
  spanCost,
} from './spans'
import type { SpanErrorInfo, SpanNode, SpanTree, TraceSpan } from './types'

/* ── error roll-ups ── */

/**
 * True when the node or any descendant has ERROR status.
 * Ported from legacy `_subtreeHasError` (L214-218).
 */
export function subtreeHasError(node: SpanNode | null | undefined): boolean {
  if (!node) return false
  if (isErrorSpan(node)) return true
  return node.children.some((child) => subtreeHasError(child))
}

/**
 * Walk descendants to find the first concrete error info when the span
 * itself has none. Ported from legacy `extractErrorInfoDeep` (L1036-1047).
 */
export function extractErrorInfoDeep(node: SpanNode): SpanErrorInfo | null {
  const direct = extractErrorInfo(node)
  if (direct) return direct
  for (const child of node.children) {
    if (!isErrorSpan(child)) continue
    const found = extractErrorInfoDeep(child)
    if (found) return found
  }
  return null
}

/**
 * Count "real" errors: spans with ERROR status AND an `exception` event —
 * not just inherited ERROR status. Falls back to 1 when the summary reported
 * errors but no span carries an exception event.
 * Ported from legacy renderHeader error counting (L1202-1206).
 */
export function countRealErrors(tree: SpanTree, summaryErrorCount = 0): number {
  const real = tree.nodes.filter(
    (n) =>
      isErrorSpan(n) && (Array.isArray(n.events) ? n.events : []).some((ev) => ev.name === 'exception'),
  ).length
  return real || (summaryErrorCount ? 1 : 0)
}

/* ── noise classification (legacy L257-287) ── */

/**
 * Span names that are always framework noise (LangChain/LangGraph internals).
 * Only these exact names get removed — user-defined graph nodes are kept.
 * Legacy `_NOISE_NAMES` (L259-264).
 */
const NOISE_NAMES: ReadonlySet<string> = new Set([
  'should_continue',
  'route',
  'router',
  'RunnableSequence',
  'call_model',
  'ChannelWrite',
  'ChannelRead',
  'Prompt',
  'RunnableParallel',
  'RunnableLambda',
  '__start__',
  '__end__',
])

/** Span kinds that are meaningful and never collapsed. Legacy `_KEEP_KINDS` (L266). */
const KEEP_KINDS: ReadonlySet<string> = new Set([
  'LLM',
  'TOOL',
  'AGENT',
  'EMBED',
  'RETRIEVER',
  'EVALUATOR',
  'GUARDRAIL',
])

/** Legacy `_isNoiseSpan` (L268-275). */
function isNoiseSpan(node: SpanNode): boolean {
  if (KEEP_KINDS.has(classifySpan(node))) return false
  return NOISE_NAMES.has((node.name ?? '').trim())
}

/** Legacy `_isPassThrough` (L277-287): single-child wrapper with no own data. */
function isPassThrough(node: SpanNode): boolean {
  if (node.children.length !== 1) return false
  if (KEEP_KINDS.has(classifySpan(node))) return false
  const a = node.attributes ?? {}
  if (a['input.value'] || a['output.value']) return false
  if (a['llm.model_name'] || a['gen_ai.request.model']) return false
  return true
}

/* ── duplicate-LLM heuristics (legacy L289-377) ── */

/** Legacy `_spanStart` (L289-291). */
function spanStart(node: TraceSpan): number | null {
  return node.start_time_ns == null ? null : Number(node.start_time_ns)
}

/** Legacy `_spanEnd` (L293-296). */
function spanEnd(node: TraceSpan): number | null {
  if (node.end_time_ns != null) return Number(node.end_time_ns)
  return spanStart(node)
}

/** Temporal overlap ratio relative to the shorter span. Legacy `_overlapRatio` (L298-304). */
export function overlapRatio(a: TraceSpan, b: TraceSpan): number {
  const as = spanStart(a)
  const ae = spanEnd(a)
  const bs = spanStart(b)
  const be = spanEnd(b)
  if (as == null || ae == null || bs == null || be == null) return 0
  const overlap = Math.max(0, Math.min(ae, be) - Math.max(as, bs))
  const base = Math.max(1, Math.min(ae - as, be - bs))
  return overlap / base
}

/** Legacy `_messageSig` (L306-310). */
function messageSig(attributes: Record<string, unknown>, prefix: 'llm.input_messages' | 'llm.output_messages'): string {
  const msgs = extractMessages(attributes, prefix)
  if (!msgs.length) return ''
  return msgs
    .map((m) => `${m.role.toLowerCase()}:${m.content}`)
    .join('|')
    .slice(0, 4000)
}

/** Legacy `_llmSignature` (L312-318). */
function llmSignature(node: SpanNode): string {
  const a = node.attributes ?? {}
  const model = spanModel(node)
  const input = String(a['input.value'] ?? messageSig(a, 'llm.input_messages') ?? '').slice(0, 4000)
  const output = String(a['output.value'] ?? messageSig(a, 'llm.output_messages') ?? '').slice(0, 4000)
  return `${model}::${input}::${output}`
}

/** How much display-worthy data a span carries. Legacy `_spanRichness` (L320-332). */
function spanRichness(node: SpanNode): number {
  const a = node.attributes ?? {}
  let score = 0
  if (a['input.value']) score += 2
  if (a['output.value']) score += 2
  if (messageSig(a, 'llm.input_messages')) score += 3
  if (messageSig(a, 'llm.output_messages')) score += 3
  if (spanModel(node)) score += 1
  if (spanHasReasoning(node)) score += 6
  if (spanReasoningTokens(node) > 0) score += 2
  score += Math.min(2, (Number(node.duration_ms) || 0) / 1000)
  return score
}

/** Legacy `_PROVIDER_LLM_NAME_RE` (L334). */
const PROVIDER_LLM_NAME_RE = /^(ChatCompletion|Completion|Responses?|response)$/i

/** Legacy `_llmKeepPriority` (L336-341). */
function llmKeepPriority(node: SpanNode): number {
  let score = spanRichness(node)
  if (PROVIDER_LLM_NAME_RE.test(String(node.name ?? ''))) score -= 4
  if (spanHasReasoning(node)) score += 8
  return score
}

/** Legacy `_durationSimilarity` (L343-347). */
function durationSimilarity(a: SpanNode, b: SpanNode): number {
  const ad = Math.max(1, Number(a.duration_ms) || 0)
  const bd = Math.max(1, Number(b.duration_ms) || 0)
  return Math.min(ad, bd) / Math.max(ad, bd)
}

/** Legacy `_tokenSimilarity` (L349-354). */
function tokenSimilarity(a: SpanNode, b: SpanNode): boolean {
  const at = spanTokens(a)
  const bt = spanTokens(b)
  if (at == null || bt == null) return true
  return Math.abs(at - bt) <= Math.max(2, Math.round(Math.max(at, bt) * 0.02))
}

/** Legacy `_sameModel` (L356-360). */
function sameModel(a: SpanNode, b: SpanNode): boolean {
  const am = spanModel(a)
  const bm = spanModel(b)
  return Boolean(am) && Boolean(bm) && am === bm
}

/**
 * Framework + provider double-instrumentation detector.
 * Legacy `_llmLooksDuplicate` (L362-377).
 */
function llmLooksDuplicate(a: SpanNode, b: SpanNode): boolean {
  if (classifySpan(a) !== 'LLM' || classifySpan(b) !== 'LLM') return false
  if (subtreeHasError(a) || subtreeHasError(b)) return false
  if (!sameModel(a, b)) return false
  if (overlapRatio(a, b) < 0.9) return false
  if (durationSimilarity(a, b) < 0.85) return false
  if (!tokenSimilarity(a, b)) return false

  const as = llmSignature(a)
  const bs = llmSignature(b)
  if (as && bs && as === bs) return true

  const aProviderish = PROVIDER_LLM_NAME_RE.test(String(a.name ?? ''))
  const bProviderish = PROVIDER_LLM_NAME_RE.test(String(b.name ?? ''))
  return aProviderish !== bProviderish
}

/** Legacy `_pruneNodes` (L379-385). */
function pruneNodes(childList: SpanNode[], toRemove: Set<SpanNode>): void {
  for (let i = childList.length - 1; i >= 0; i--) {
    const node = childList[i]
    pruneNodes(node.children, toRemove)
    if (toRemove.has(node)) childList.splice(i, 1)
  }
}

/** Legacy `_dedupeGlobalLlmSpans` (L387-406). */
function dedupeGlobalLlmSpans(tree: SpanTree): void {
  const llms = tree.nodes.filter((n) => classifySpan(n) === 'LLM')
  if (llms.length < 2) return

  const toRemove = new Set<SpanNode>()
  for (let i = 0; i < llms.length; i++) {
    const a = llms[i]
    if (toRemove.has(a)) continue
    for (let j = i + 1; j < llms.length; j++) {
      const b = llms[j]
      if (toRemove.has(b)) continue
      if (!llmLooksDuplicate(a, b)) continue
      const keep = llmKeepPriority(a) >= llmKeepPriority(b) ? a : b
      toRemove.add(keep === a ? b : a)
    }
  }

  if (!toRemove.size) return
  pruneNodes(tree.roots, toRemove)
}

/** Legacy `_dedupeSiblingSpans` (L408-457). */
function dedupeSiblingSpans(childList: SpanNode[]): void {
  if (childList.length < 2) return

  const toRemove = new Set<SpanNode>()

  // Hide low-level chroma DB calls when an overlapping retriever sibling
  // already represents the same retrieval (L415-426).
  for (const node of childList) {
    const a = node.attributes ?? {}
    if (String(a['db.system'] ?? '').toLowerCase() !== 'chroma') continue
    if (subtreeHasError(node)) continue
    const hasRetrieverSibling = childList.some(
      (other) =>
        other !== node &&
        classifySpan(other) === 'RETRIEVER' &&
        !subtreeHasError(other) &&
        overlapRatio(node, other) > 0.5,
    )
    if (hasRetrieverSibling) toRemove.add(node)
  }

  // Collapse duplicate LLM siblings sharing a signature (L428-451).
  const llmGroups = new Map<string, SpanNode[]>()
  for (const node of childList) {
    if (classifySpan(node) !== 'LLM') continue
    if (subtreeHasError(node)) continue
    const sig = llmSignature(node)
    if (!sig || sig === '::') continue
    const group = llmGroups.get(sig)
    if (group) group.push(node)
    else llmGroups.set(sig, [node])
  }
  for (const group of llmGroups.values()) {
    if (group.length < 2) continue
    const overlapping = group.filter((a) => group.some((b) => a !== b && overlapRatio(a, b) > 0.85))
    if (overlapping.length < 2) continue
    let keep = overlapping[0]
    for (const node of overlapping.slice(1)) {
      if (spanRichness(node) > spanRichness(keep)) keep = node
    }
    for (const node of overlapping) {
      if (node !== keep) toRemove.add(node)
    }
  }

  if (!toRemove.size) return
  for (let i = childList.length - 1; i >= 0; i--) {
    if (toRemove.has(childList[i])) childList.splice(i, 1)
  }
}

/**
 * Remove framework noise bottom-up: prune leaf noise spans, splice
 * pass-through wrappers, promote children of noisy parents, then dedupe
 * siblings. Subtrees containing errors are never touched.
 * Legacy `_collapseNoise` (L459-486).
 */
function collapseNoise(childList: SpanNode[]): void {
  for (let i = childList.length - 1; i >= 0; i--) {
    const node = childList[i]
    collapseNoise(node.children)
    if (subtreeHasError(node)) continue
    if (isNoiseSpan(node) && node.children.length === 0) {
      childList.splice(i, 1)
      continue
    }
    if (isPassThrough(node)) {
      const child = node.children[0]
      child.parent_span_id = node.parent_span_id
      childList.splice(i, 1, child)
      continue
    }
    if (isNoiseSpan(node)) {
      for (const child of node.children) {
        child.parent_span_id = node.parent_span_id
      }
      childList.splice(i, 1, ...node.children)
    }
  }
  dedupeSiblingSpans(childList)
}

/* ── tree building (legacy buildTree, L221-255) ── */

export function buildSpanTree(spans: TraceSpan[] | null | undefined): SpanTree {
  const byId = new Map<string, SpanNode>()
  const nodes: SpanNode[] = (spans ?? []).map((sp, i) => {
    const n: SpanNode = { ...sp, index: i, children: [], depth: 0, orphan: false }
    byId.set(n.span_id, n)
    return n
  })

  const roots: SpanNode[] = []
  for (const n of nodes) {
    const p = n.parent_span_id
    const parent = p ? byId.get(p) : undefined
    if (parent) {
      parent.children.push(n)
    } else {
      n.orphan = Boolean(p)
      roots.push(n)
    }
  }

  // Sort siblings by start time (nulls last), stable on input order (L234-241).
  const sortFn = (a: SpanNode, b: SpanNode): number => {
    const as = a.start_time_ns == null ? Infinity : Number(a.start_time_ns)
    const bs = b.start_time_ns == null ? Infinity : Number(b.start_time_ns)
    return as !== bs ? as - bs : a.index - b.index
  }
  const sortChildren = (n: SpanNode): void => {
    n.children.sort(sortFn)
    n.children.forEach(sortChildren)
  }
  roots.sort(sortFn)
  roots.forEach(sortChildren)

  collapseNoise(roots)

  const tree: SpanTree = { roots, byId, nodes }
  dedupeGlobalLlmSpans(tree)

  // Recompute depths after collapsing (L250-252).
  const setDepths = (n: SpanNode, d: number): void => {
    n.depth = d
    n.children.forEach((c) => setDepths(c, d + 1))
  }
  roots.forEach((r) => setDepths(r, 0))

  return tree
}

/* ── retry detection (legacy detectRetries, L1049-1083) ── */

export interface RetryMarkers {
  /** span_id → retry ordinal (>=1 when the span is a re-execution). */
  retries: Map<string, number>
  /** span_ids of failed attempts (and their descendants, propagated). */
  failed: Set<string>
}

/**
 * Detect retried sibling spans: same-named siblings after an errored one are
 * marked as retries; failed markers propagate to descendants so the whole
 * attempt stays visually grouped. Ported from legacy `detectRetries`
 * (L1049-1083) — returns marker collections instead of mutating nodes.
 */
export function detectRetries(tree: SpanTree): RetryMarkers {
  const retries = new Map<string, number>()
  const failed = new Set<string>()

  const processChildren = (children: SpanNode[]): void => {
    const seen = new Map<string, SpanNode[]>()
    for (const c of children) {
      const name = c.name ?? ''
      const group = seen.get(name)
      if (group) group.push(c)
      else seen.set(name, [c])
    }
    for (const group of seen.values()) {
      if (group.length <= 1) continue
      let retryNum = 0
      for (const span of group) {
        if (retryNum > 0) retries.set(span.span_id, retryNum)
        if (isErrorSpan(span)) {
          failed.add(span.span_id)
          retryNum++
        }
      }
    }
  }

  processChildren(tree.roots)
  for (const n of tree.nodes) {
    if (n.children.length) processChildren(n.children)
  }

  const propagate = (node: SpanNode): void => {
    for (const c of node.children) {
      if (failed.has(node.span_id)) failed.add(c.span_id)
      propagate(c)
    }
  }
  tree.roots.forEach(propagate)

  return { retries, failed }
}

/* ── aggregate stats (legacy aggregateStats, L1131-1140) ── */

export interface TraceAggregates {
  totalTokens: number
  totalCost: number
}

/** Sum tokens/cost across LLM spans. Ported from legacy `aggregateStats` (L1131-1140). */
export function aggregateStats(tree: SpanTree): TraceAggregates {
  let totalTokens = 0
  let totalCost = 0
  for (const n of tree.nodes) {
    if (classifySpan(n) === 'LLM') {
      totalTokens += spanTokens(n) ?? 0
      totalCost += spanCost(n) ?? 0
    }
  }
  return { totalTokens, totalCost }
}

/* ── visible-row flattening ── */

/**
 * Depth-first flatten of the tree honoring an expanded-id set — the row
 * order the tree panel renders and keyboard navigation walks. Mirrors the
 * traversal of legacy `renderTree`/`visit` (L1283-1370) with search and
 * guide-rendering concerns removed.
 */
export function flattenVisibleNodes(tree: SpanTree, expanded: ReadonlySet<string>): SpanNode[] {
  const rows: SpanNode[] = []
  const visit = (node: SpanNode): void => {
    rows.push(node)
    if (expanded.has(node.span_id)) {
      node.children.forEach(visit)
    }
  }
  tree.roots.forEach(visit)
  return rows
}

/** All span ids that have children (legacy `allExpandableSpanIds`, L1223-1227). */
export function expandableSpanIds(tree: SpanTree): string[] {
  return tree.nodes.filter((n) => n.children.length > 0).map((n) => n.span_id)
}
