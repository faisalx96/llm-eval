/**
 * qym Trace Viewer — Production-grade LLM trace inspector.
 *
 * Features:
 *   - Span tree with typed SVG icons (LLM/TOOL/AGENT/CHAIN/EVALUATOR)
 *   - Inline model name + token counts on LLM spans
 *   - Chat bubble rendering for LLM messages
 *   - Tabbed detail panel (Messages/Output/Reasoning/Params/Raw)
 *   - Keyboard navigation (j/k/↑↓/Enter/Escape)
 *   - Search/filter spans
 *   - Score pills in header from span events
 *   - Error path auto-expand
 *   - Waterfall duration bars
 *   - Responsive layout
 */
(function () {
  "use strict";

  /* ── state ── */
  const cache = new Map();
  const S = {
    ready: false,
    exportMode: false,
    shell: null,
    el: {},            // named DOM refs
    data: null,        // { item, summary, spans, _tree }
    meta: null,
    expanded: new Set(),
    selected: null,
    selectedAttempt: null,
    search: "",
    activeTab: null,
  };

  /* ── icons (inline SVG, 16×16) ── */
  const ICONS = {
    LLM:       `<svg viewBox="0 0 16 16"><rect x="2" y="2" width="12" height="8.5" rx="2" fill="currentColor"/><polygon points="5,10.5 5,14 8.5,10.5" fill="currentColor"/></svg>`,
    TOOL:      `<svg viewBox="0 0 16 16"><path d="M9.7 7.7L5.3 12.1a1.6 1.6 0 0 1-2.3 0l-.1-.1a1.6 1.6 0 0 1 0-2.3l4.4-4.4a3.2 3.2 0 0 1 4.6-3.7L10 3.5l.3 1.2 1.2.3 1.9-1.9a3.2 3.2 0 0 1-3.7 4.6z" fill="currentColor"/></svg>`,
    AGENT:     `<svg viewBox="0 0 16 16"><circle cx="8" cy="4" r="3" fill="currentColor"/><path d="M2.5 14.5c0-3 2.5-5.5 5.5-5.5s5.5 2.5 5.5 5.5z" fill="currentColor" opacity=".75"/></svg>`,
    CHAIN:     `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M7 9l-1.2 1.2a2.4 2.4 0 0 1-3.4-3.4L5.2 4a2.4 2.4 0 0 1 3.4 3.4"/><path d="M9 7l1.2-1.2a2.4 2.4 0 0 1 3.4 3.4L10.8 12a2.4 2.4 0 0 1-3.4-3.4"/></svg>`,
    EVALUATOR: `<svg viewBox="0 0 16 16"><path d="M8 1.5l2 4 4.4.7-3.2 3.1.75 4.4L8 11.5l-3.95 2.2.75-4.4-3.2-3.1L7 5.5z" fill="currentColor"/></svg>`,
    RETRIEVER: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"><ellipse cx="8" cy="3.5" rx="4.5" ry="2"/><path d="M3.5 3.5v7c0 1.1 2 2 4.5 2s4.5-.9 4.5-2v-7"/><path d="M3.5 7c0 1.1 2 2 4.5 2s4.5-.9 4.5-2"/><path d="M3.5 10.5c0 1.1 2 2 4.5 2s4.5-.9 4.5-2"/></svg>`,
    EMBED:     `<svg viewBox="0 0 16 16"><rect x="1.5" y="1.5" width="5.5" height="5.5" rx="1.5" fill="currentColor" opacity=".85"/><rect x="9" y="1.5" width="5.5" height="5.5" rx="1.5" fill="currentColor" opacity=".45"/><rect x="1.5" y="9" width="5.5" height="5.5" rx="1.5" fill="currentColor" opacity=".45"/><rect x="9" y="9" width="5.5" height="5.5" rx="1.5" fill="currentColor" opacity=".85"/></svg>`,
    DEFAULT:   `<svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="4.5" fill="currentColor" opacity=".7"/></svg>`,
  };

  const KIND_COLORS = {
    LLM: "#f472b6", TOOL: "#fbbf24", AGENT: "#34d399", CHAIN: "#60a5fa",
    EVALUATOR: "#a78bfa", RETRIEVER: "#38bdf8", EMBED: "#94a3b8", DEFAULT: "#6b7280",
  };

  /* ── helpers ── */
  const COPY_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`;
  const CHECK_ICON = `<svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 8.5 6.5 11.5 12.5 4.5"/></svg>`;
  const EXPAND_ICON = `<svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3H3v3"/><path d="M10 3h3v3"/><path d="M13 10v3h-3"/><path d="M3 10v3h3"/><path d="M3 6l4-4"/><path d="M13 6L9 2"/><path d="M3 10l4 4"/><path d="M13 10l-4 4"/></svg>`;
  const EXPAND_ALL_ICON = `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 4.5 8 9l4.5-4.5"/><path d="M3.5 8.5 8 13l4.5-4.5"/></svg>`;
  const COLLAPSE_ALL_ICON = `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 11.5 8 7l4.5 4.5"/><path d="M3.5 7.5 8 3l4.5 4.5"/></svg>`;

  function copyBtn(textOrFn, label) {
    const id = `tv-cb-${++_copyId}`;
    _copyData[id] = textOrFn;
    return `<button type="button" class="tv-copy-btn qym-icon-action" data-copy-id="${id}" title="${label || "Copy"}" aria-label="${label || "Copy"}">${COPY_ICON}</button>`;
  }
  let _copyId = 0;
  const _copyData = {};

  function expandBtn(payload, label) {
    const id = `tv-xb-${++_expandId}`;
    _expandData[id] = payload;
    return `<button type="button" class="tv-expand-btn qym-icon-action" data-expand-id="${id}" title="${label || "Expand"}" aria-label="${label || "Expand"}">${EXPAND_ICON}</button>`;
  }
  let _expandId = 0;
  const _expandData = {};

  function actionGroup(buttons, cls) {
    const inner = (buttons || []).filter(Boolean).join("");
    if (!inner) return "";
    return `<span class="${cls || "tv-inline-actions"}">${inner}</span>`;
  }

  function hasChildren(node) {
    return !!(node && Array.isArray(node._children) && node._children.length);
  }

  function esc(v) {
    return String(v == null ? "" : v).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }

  function fmtDur(ms) {
    if (ms == null) return "—";
    const n = Number(ms);
    if (!Number.isFinite(n)) return "—";
    if (n >= 1000) return (n/1000).toFixed(1) + "s";
    return Math.round(n) + "ms";
  }

  function fmtTokens(n) {
    if (n == null) return null;
    const num = Number(n);
    if (!Number.isFinite(num)) return null;
    return num.toLocaleString("en-US");
  }

  function fmtCost(n) {
    if (n == null || n === 0) return null;
    const num = Number(n);
    if (!Number.isFinite(num) || num <= 0) return null;
    return "$" + (num < 0.01 ? num.toFixed(4) : num.toFixed(3));
  }

  function spanKind(span) {
    const a = span.attributes || {};
    const raw = a["openinference.span.kind"] || a["ai.openinference.span.kind"] || a["span.kind"] || span.kind || "";
    const k = String(raw).toUpperCase().replace(/[^A-Z]/g,"");
    if (ICONS[k]) return k;
    if (k === "EMBEDDING") return "EMBED";
    if (k === "RETRIEVE" || k === "RETRIEVER") return "RETRIEVER";
    return "DEFAULT";
  }

  function spanModel(span) {
    const a = span.attributes || {};
    let m = a["llm.model_name"] || a["gen_ai.request.model"] || a["gen_ai.response.model"] || "";
    if (typeof m === "string" && m.includes("/")) m = m.split("/").pop();
    return m;
  }

  function spanTokens(span) {
    const a = span.attributes || {};
    return Number(a["llm.token_count.total"] || a["gen_ai.usage.total_tokens"] || 0) || null;
  }

  function spanCost(span) {
    const a = span.attributes || {};
    return Number(a["llm.cost.total"] || 0) || null;
  }

  const MODEL_REASONING_BADGE_TITLE = "Reasoning model";
  const MODEL_REASONING_BADGE_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18h6"/><path d="M10 21h4"/><path d="M12 2a7 7 0 0 0-4.2 12.6c.7.5 1.2 1.4 1.2 2.3V18h6v-1.1c0-.9.5-1.8 1.2-2.3A7 7 0 0 0 12 2Z"/></svg>`;

  function renderModelReasoningBadge() {
    return `<span class="model-reasoning-badge" title="${esc(MODEL_REASONING_BADGE_TITLE)}" aria-label="${esc(MODEL_REASONING_BADGE_TITLE)}">${MODEL_REASONING_BADGE_ICON}</span>`;
  }

  function statusCls(s) {
    const u = String(s||"").toUpperCase();
    return u === "ERROR" ? "error" : u === "OK" ? "ok" : "unset";
  }

  function normalizeAttempts(data) {
    if (!data) return data;
    const attempts = Array.isArray(data.attempts) && data.attempts.length ? data.attempts : [{
      attempt_number: 1,
      status: data?.item?.trace_id ? "completed" : "failed",
      latency_ms: data?.item?.latency_ms ?? null,
      task_started_at_ms: null,
      trace_id: data?.item?.trace_id || "",
      trace_url: data?.item?.trace_url || "",
      error: null,
      is_last_attempt: true,
      summary: data?.summary || {},
      spans: Array.isArray(data?.spans) ? data.spans : [],
    }];
    data.attempts = attempts.map((attempt, idx) => {
      const spans = Array.isArray(attempt.spans) ? attempt.spans : [];
      return {
        ...attempt,
        attempt_number: Number(attempt.attempt_number || (idx + 1)),
        summary: attempt.summary || {},
        spans,
        _tree: buildTree(spans),
      };
    });
    const lastAttempt = data.attempts.find(a => a.is_last_attempt) || data.attempts[data.attempts.length - 1] || null;
    if (data.item) {
      data.item.retry_count = Number(data.item.retry_count || Math.max(0, data.attempts.length - 1));
      if (lastAttempt) {
        data.item.trace_id = lastAttempt.trace_id || data.item.trace_id || "";
        data.item.trace_url = lastAttempt.trace_url || data.item.trace_url || "";
      }
    }
    if (lastAttempt) {
      data.summary = lastAttempt.summary || {};
      data.spans = lastAttempt.spans || [];
    }
    return data;
  }

  function currentAttemptData() {
    if (!S.data) return null;
    const attempts = Array.isArray(S.data.attempts) ? S.data.attempts : [];
    if (!attempts.length) return S.data;
    const selectedAttempt = Number(S.selectedAttempt || 0);
    return attempts.find(a => Number(a.attempt_number) === selectedAttempt)
      || attempts.find(a => a.is_last_attempt)
      || attempts[attempts.length - 1]
      || attempts[0];
  }

  function currentTree() {
    return currentAttemptData()?._tree || null;
  }

  function laneOpacity(depthIndex) {
    if (depthIndex <= 0) return "0.24";
    if (depthIndex === 1) return "0.18";
    return "0.14";
  }

  function _nodeIsError(node) {
    return statusCls(node?.status) === "error";
  }

  function _subtreeHasError(node) {
    if (!node) return false;
    if (_nodeIsError(node)) return true;
    return Array.isArray(node._children) && node._children.some(child => _subtreeHasError(child));
  }

  /* ── tree building ── */
  function buildTree(spans) {
    const byId = new Map();
    const nodes = (spans||[]).map((sp, i) => {
      const n = { ...sp, _i: i, _children: [], _depth: 0, _orphan: false, _visible: true };
      byId.set(n.span_id, n);
      return n;
    });
    const roots = [];
    nodes.forEach(n => {
      const p = n.parent_span_id;
      if (p && byId.has(p)) byId.get(p)._children.push(n);
      else { n._orphan = !!p; roots.push(n); }
    });
    const sortFn = (a,b) => {
      const as = a.start_time_ns == null ? Infinity : Number(a.start_time_ns);
      const bs = b.start_time_ns == null ? Infinity : Number(b.start_time_ns);
      return as !== bs ? as - bs : a._i - b._i;
    };
    function sortChildren(n) { n._children.sort(sortFn); n._children.forEach(sortChildren); }
    roots.sort(sortFn);
    roots.forEach(sortChildren);

    // Collapse framework noise: remove pass-through wrapper spans and
    // trivially short routing spans from LangChain/LangGraph internals.
    _collapseNoise(roots, byId);

    const tree = { roots, byId, nodes };
    _dedupeGlobalLlmSpans(tree);

    // Recompute depths after collapsing
    function setDepths(n, d) { n._depth = d; n._children.forEach(c => setDepths(c, d+1)); }
    roots.forEach(r => setDepths(r, 0));

    return tree;
  }

  // Names of spans that are always noise from framework internals.
  // Only these exact names get removed — user-defined graph nodes are kept.
  const _NOISE_NAMES = new Set([
    "should_continue", "route", "router", "RunnableSequence",
    "call_model", "ChannelWrite", "ChannelRead",
    "Prompt", "RunnableParallel", "RunnableLambda",
    "__start__", "__end__",
  ]);
  // Span kinds that are meaningful (never collapse)
  const _KEEP_KINDS = new Set(["LLM", "TOOL", "AGENT", "EMBED", "RETRIEVER", "EVALUATOR", "GUARDRAIL"]);

  function _isNoiseSpan(node) {
    const kind = spanKind(node);
    if (_KEEP_KINDS.has(kind)) return false;
    const name = (node.name || "").trim();
    // Only remove spans with known framework-internal names
    if (_NOISE_NAMES.has(name)) return true;
    return false;
  }

  function _isPassThrough(node) {
    // A span that has exactly one child and adds nothing meaningful
    if (node._children.length !== 1) return false;
    const kind = spanKind(node);
    if (_KEEP_KINDS.has(kind)) return false;
    const attrs = node.attributes || {};
    // Has its own input/output? Keep it.
    if (attrs["input.value"] || attrs["output.value"]) return false;
    if (attrs["llm.model_name"] || attrs["gen_ai.request.model"]) return false;
    return true;
  }

  function _spanStart(node) {
    return node?.start_time_ns == null ? null : Number(node.start_time_ns);
  }

  function _spanEnd(node) {
    if (node?.end_time_ns != null) return Number(node.end_time_ns);
    return _spanStart(node);
  }

  function _overlapRatio(a, b) {
    const as = _spanStart(a), ae = _spanEnd(a), bs = _spanStart(b), be = _spanEnd(b);
    if (as == null || ae == null || bs == null || be == null) return 0;
    const overlap = Math.max(0, Math.min(ae, be) - Math.max(as, bs));
    const base = Math.max(1, Math.min(ae - as, be - bs));
    return overlap / base;
  }

  function _messageSig(attrs, prefix) {
    const msgs = extractMessages(attrs || {}, prefix);
    if (!msgs.length) return "";
    return msgs.map(m => `${String(m.role || "").toLowerCase()}:${String(m.content || "")}`).join("|").slice(0, 4000);
  }

  function _llmSignature(node) {
    const attrs = node.attributes || {};
    const model = spanModel(node) || "";
    const input = String(attrs["input.value"] || _messageSig(attrs, "llm.input_messages") || "").slice(0, 4000);
    const output = String(attrs["output.value"] || _messageSig(attrs, "llm.output_messages") || "").slice(0, 4000);
    return `${model}::${input}::${output}`;
  }

  function _spanRichness(node) {
    const attrs = node.attributes || {};
    let score = 0;
    if (attrs["input.value"]) score += 2;
    if (attrs["output.value"]) score += 2;
    if (_messageSig(attrs, "llm.input_messages")) score += 3;
    if (_messageSig(attrs, "llm.output_messages")) score += 3;
    if (spanModel(node)) score += 1;
    if (spanHasReasoning(node)) score += 6;
    if (spanReasoningTokens(node) > 0) score += 2;
    score += Math.min(2, (Number(node.duration_ms) || 0) / 1000);
    return score;
  }

  const _PROVIDER_LLM_NAME_RE = /^(ChatCompletion|Completion|Responses?|response)$/i;

  function _llmKeepPriority(node) {
    let score = _spanRichness(node);
    if (_PROVIDER_LLM_NAME_RE.test(String(node?.name || ""))) score -= 4;
    if (spanHasReasoning(node)) score += 8;
    return score;
  }

  function _durationSimilarity(a, b) {
    const ad = Math.max(1, Number(a?.duration_ms) || 0);
    const bd = Math.max(1, Number(b?.duration_ms) || 0);
    return Math.min(ad, bd) / Math.max(ad, bd);
  }

  function _tokenSimilarity(a, b) {
    const at = spanTokens(a);
    const bt = spanTokens(b);
    if (at == null || bt == null) return true;
    return Math.abs(at - bt) <= Math.max(2, Math.round(Math.max(at, bt) * 0.02));
  }

  function _sameModel(a, b) {
    const am = spanModel(a);
    const bm = spanModel(b);
    return !!am && !!bm && am === bm;
  }

  function _llmLooksDuplicate(a, b) {
    if (spanKind(a) !== "LLM" || spanKind(b) !== "LLM") return false;
    if (_subtreeHasError(a) || _subtreeHasError(b)) return false;
    if (!_sameModel(a, b)) return false;
    if (_overlapRatio(a, b) < 0.9) return false;
    if (_durationSimilarity(a, b) < 0.85) return false;
    if (!_tokenSimilarity(a, b)) return false;

    const as = _llmSignature(a);
    const bs = _llmSignature(b);
    if (as && bs && as === bs) return true;

    const aProviderish = _PROVIDER_LLM_NAME_RE.test(String(a.name || ""));
    const bProviderish = _PROVIDER_LLM_NAME_RE.test(String(b.name || ""));
    return aProviderish !== bProviderish;
  }

  function _pruneNodes(childList, toRemove) {
    for (let i = childList.length - 1; i >= 0; i--) {
      const node = childList[i];
      _pruneNodes(node._children || [], toRemove);
      if (toRemove.has(node)) childList.splice(i, 1);
    }
  }

  function _dedupeGlobalLlmSpans(tree) {
    const llms = (tree?.nodes || []).filter(n => spanKind(n) === "LLM");
    if (llms.length < 2) return;

    const toRemove = new Set();
    for (let i = 0; i < llms.length; i++) {
      const a = llms[i];
      if (toRemove.has(a)) continue;
      for (let j = i + 1; j < llms.length; j++) {
        const b = llms[j];
        if (toRemove.has(b)) continue;
        if (!_llmLooksDuplicate(a, b)) continue;
        const keep = _llmKeepPriority(a) >= _llmKeepPriority(b) ? a : b;
        toRemove.add(keep === a ? b : a);
      }
    }

    if (!toRemove.size) return;
    _pruneNodes(tree.roots, toRemove);
  }

  function _dedupeSiblingSpans(childList) {
    if (!Array.isArray(childList) || childList.length < 2) return;

    const toRemove = new Set();

    // Hide low-level chroma DB calls when a higher-level retriever span already
    // represents the same retrieval operation under the same parent.
    for (const node of childList) {
      const attrs = node.attributes || {};
      if (String(attrs["db.system"] || "").toLowerCase() !== "chroma") continue;
      if (_subtreeHasError(node)) continue;
      const hasRetrieverSibling = childList.some(other =>
        other !== node &&
        spanKind(other) === "RETRIEVER" &&
        !_subtreeHasError(other) &&
        _overlapRatio(node, other) > 0.5
      );
      if (hasRetrieverSibling) toRemove.add(node);
    }

    // Collapse duplicate LLM siblings from framework + provider instrumentation.
    const llmGroups = new Map();
    for (const node of childList) {
      if (spanKind(node) !== "LLM") continue;
      if (_subtreeHasError(node)) continue;
      const sig = _llmSignature(node);
      if (!sig || sig === "::") continue;
      if (!llmGroups.has(sig)) llmGroups.set(sig, []);
      llmGroups.get(sig).push(node);
    }
    for (const group of llmGroups.values()) {
      if (group.length < 2) continue;
      const overlapping = group.filter(a =>
        group.some(b => a !== b && _overlapRatio(a, b) > 0.85)
      );
      if (overlapping.length < 2) continue;
      let keep = overlapping[0];
      for (const node of overlapping.slice(1)) {
        if (_spanRichness(node) > _spanRichness(keep)) keep = node;
      }
      for (const node of overlapping) {
        if (node !== keep) toRemove.add(node);
      }
    }

    if (!toRemove.size) return;
    for (let i = childList.length - 1; i >= 0; i--) {
      if (toRemove.has(childList[i])) childList.splice(i, 1);
    }
  }

  function _collapseNoise(childList, byId) {
    for (let i = childList.length - 1; i >= 0; i--) {
      const node = childList[i];
      // Recurse first (bottom-up)
      _collapseNoise(node._children, byId);
      if (_subtreeHasError(node)) continue;
      // Remove pure noise spans (promote their children up)
      if (_isNoiseSpan(node) && node._children.length === 0) {
        childList.splice(i, 1);
        continue;
      }
      // Collapse pass-through wrappers (single child, no data)
      if (_isPassThrough(node)) {
        const child = node._children[0];
        child.parent_span_id = node.parent_span_id;
        childList.splice(i, 1, child);
        continue;
      }
      // Remove noise spans that have children by promoting children
      if (_isNoiseSpan(node)) {
        for (const child of node._children) {
          child.parent_span_id = node.parent_span_id;
        }
        childList.splice(i, 1, ...node._children);
      }
    }
    _dedupeSiblingSpans(childList);
  }

  function computeBounds(data) {
    const sum = data?.summary || {};
    let s = sum.started_at_ns, e = sum.ended_at_ns;
    if (s != null && e != null) return { start: s, end: e, total: Math.max(e-s,1) };
    const spans = data?.spans || [];
    const ss = spans.map(x=>x.start_time_ns).filter(x=>x!=null);
    const es = spans.map(x=>x.end_time_ns).filter(x=>x!=null);
    if (!ss.length||!es.length) return { start:null, end:null, total:1 };
    s = Math.min(...ss); e = Math.max(...es);
    return { start:s, end:e, total: Math.max(e-s,1) };
  }

  /* ── extract structured data from attributes ── */
  function extractMessages(attrs, prefix) {
    // prefix = "llm.input_messages" or "llm.output_messages"
    const msgs = [];
    for (let i = 0; i < 50; i++) {
      const role = attrs[`${prefix}.${i}.message.role`];
      if (role == null) break;
      let content = attrs[`${prefix}.${i}.message.content`] || "";
      if (!content) {
        const parts = [];
        for (let j = 0; j < 20; j++) {
          const base = `${prefix}.${i}.message.contents.${j}.message_content`;
          const type = attrs[`${base}.type`];
          if (type == null) break;
          if (String(type) === "text") {
            const text = attrs[`${base}.text`];
            if (text) parts.push(String(text));
          }
        }
        if (parts.length) content = parts.join("\n\n");
      }
      const toolCalls = [];
      for (let j = 0; j < 20; j++) {
        const tcName = attrs[`${prefix}.${i}.message.tool_calls.${j}.tool_call.function.name`];
        if (tcName == null) break;
        toolCalls.push({
          name: tcName,
          arguments: attrs[`${prefix}.${i}.message.tool_calls.${j}.tool_call.function.arguments`] || "",
          id: attrs[`${prefix}.${i}.message.tool_calls.${j}.tool_call.id`] || "",
        });
      }
      const toolCallId = attrs[`${prefix}.${i}.message.tool_call_id`];
      const reasoning = attrs[`${prefix}.${i}.message.reasoning`] || "";
      msgs.push({ role, content, toolCalls, toolCallId, reasoning });
    }
    return msgs;
  }

  function enrichReasoning(msgs, rawValue) {
    if (!rawValue || !msgs.length) return;
    try {
      const parsed = typeof rawValue === "string" ? JSON.parse(rawValue) : rawValue;
      // input.value has .messages[], output.value has .choices[].message
      const srcMsgs = parsed.messages || (parsed.choices || []).map(c => c.message).filter(Boolean);
      if (!srcMsgs || !srcMsgs.length) return;
      // Match by index — flat attrs and JSON messages are in same order
      let ai = 0;
      for (let i = 0; i < msgs.length && ai < srcMsgs.length; i++) {
        const m = msgs[i];
        const role = String(m.role || "").toLowerCase();
        // Find corresponding source message by walking both lists
        while (ai < srcMsgs.length && String(srcMsgs[ai].role || "").toLowerCase() !== role) ai++;
        if (ai >= srcMsgs.length) break;
        const src = srcMsgs[ai];
        if (!m.reasoning && src.reasoning) {
          m.reasoning = typeof src.reasoning === "string" ? src.reasoning : JSON.stringify(src.reasoning);
        }
        ai++;
      }
    } catch (_) {}
  }

  function extractScores(span) {
    const events = Array.isArray(span.events) ? span.events : [];
    return events
      .filter(ev => ev.name && ev.name.startsWith("score."))
      .map(ev => ({
        name: (ev.attributes || {})["score.name"] || ev.name.replace("score.", ""),
        value: (ev.attributes || {})["score.value"],
        label: (ev.attributes || {})["score.label"] || "",
        explanation: (ev.attributes || {})["score.explanation"] || "",
      }));
  }

  function metricToneClass(value) {
    if (typeof value === "boolean") return value ? "pass" : "fail";
    if (typeof value !== "number" || !Number.isFinite(value)) return "";
    if (value === 0) return "fail";
    if (value >= 0.5 && value <= 1) return "pass";
    return "";
  }

  function renderLabeledSection(label, bodyHtml, labelClass, actionsHtml) {
    const cls = labelClass ? ` ${labelClass}` : "";
    return `<div class="tv-io-section"><div class="tv-io-label${cls}">${esc(label)}${actionsHtml || ""}</div>${bodyHtml}</div>`;
  }

  function parseValue(value) {
    if (value == null) return null;
    try {
      return deepParseJson(typeof value === "string" ? JSON.parse(value) : value);
    } catch (_) {
      return value;
    }
  }

  function summarizeDocMeta(meta) {
    if (!meta || typeof meta !== "object" || Array.isArray(meta)) return [];
    const keys = ["source", "title", "id", "document_id", "chunk", "chunk_id", "page", "section"];
    const items = [];
    keys.forEach((key) => {
      if (meta[key] != null && meta[key] !== "") items.push([key, meta[key]]);
    });
    return items.slice(0, 4);
  }

  function normalizeRetrieverDoc(candidate, index) {
    if (candidate == null) return null;
    if (typeof candidate === "string") {
      const text = candidate.trim();
      if (!text) return null;
      return { title: "Document", text, metadata: {}, score: null, raw: candidate, index };
    }
    if (typeof candidate !== "object") {
      const text = String(candidate).trim();
      if (!text) return null;
      return { title: "Document", text, metadata: {}, score: null, raw: candidate, index };
    }

    const meta = candidate.metadata && typeof candidate.metadata === "object" ? candidate.metadata : {};
    const nested = candidate.document && typeof candidate.document === "object" ? candidate.document : null;
    const text =
      candidate.page_content ||
      candidate.pageContent ||
      candidate.content ||
      candidate.text ||
      candidate.document_text ||
      candidate.chunk_text ||
      (typeof candidate.document === "string" ? candidate.document : "") ||
      (nested ? (nested.page_content || nested.pageContent || nested.content || nested.text || "") : "");

    const title =
      meta.title ||
      candidate.title ||
      meta.name ||
      candidate.name ||
      meta.source ||
      nested?.title ||
      "Document";

    const score =
      candidate.score ??
      candidate.relevance_score ??
      candidate.relevanceScore ??
      candidate.distance ??
      nested?.score ??
      null;

    const mergedMeta = { ...(nested?.metadata || {}), ...meta };
    const docText = String(text || "").trim();
    if (!docText) return null;
    return {
      title: String(title || "document"),
      text: docText,
      metadata: mergedMeta,
      score: score == null || score === "" ? null : score,
      raw: candidate,
      index,
    };
  }

  function extractRetrieverDocs(span) {
    const attrs = span.attributes || {};
    const out = parseValue(attrs["output.value"]);
    const candidates = [];

    function pushMany(value) {
      if (value == null) return;
      if (Array.isArray(value)) candidates.push(...value);
      else candidates.push(value);
    }

    if (Array.isArray(out)) {
      pushMany(out);
    } else if (out && typeof out === "object") {
      [
        "documents",
        "docs",
        "source_documents",
        "sourceDocuments",
        "retrieved_documents",
        "retrievedDocs",
        "matches",
        "results",
        "items",
        "contexts",
      ].forEach((key) => pushMany(out[key]));
      if (!candidates.length) pushMany(out);
    }

    return candidates
      .map((candidate, index) => normalizeRetrieverDoc(candidate, index))
      .filter(Boolean);
  }

  function formatDocScore(score) {
    if (score == null || score === "") return null;
    const n = Number(score);
    if (!Number.isFinite(n)) return String(score);
    return n.toFixed(Math.abs(n) < 1 ? 3 : 2);
  }

  function renderDocMetaChips(doc) {
    const chips = summarizeDocMeta(doc.metadata).map(([key, value]) =>
      `<span class="tv-chip tv-doc-chip qym-tag qym-tag--data"><span class="tv-doc-chip-k">${esc(key)}</span><span class="tv-doc-chip-v">${esc(String(value))}</span></span>`
    );
    const score = formatDocScore(doc.score);
    if (score) chips.unshift(`<span class="tv-chip tv-doc-chip tv-doc-chip-score qym-tag qym-tag--data">Score ${esc(score)}</span>`);
    return chips.join("");
  }

  function renderDocuments(span) {
    const attrs = span.attributes || {};
    const docs = extractRetrieverDocs(span);
    const query = attrs["input.value"] == null ? "" : String(attrs["input.value"]);
    if (!docs.length) return `<div class="tv-empty-d">No documents found in span output</div>`;

    let html = `<div class="tv-docs-shell">`;
    html += `<div class="tv-docs-head">`;
    html += `<div class="tv-docs-title-wrap"><div class="tv-docs-title">Retrieved Documents</div><div class="tv-docs-meta"><div class="tv-docs-sub">Context returned by this retriever span</div><span class="tv-chip tv-docs-count qym-tag qym-tag--count">${docs.length} retrieved</span></div></div>`;
    html += actionGroup([
      copyBtn(() => JSON.stringify(docs.map(d => d.raw), null, 2), "Copy documents"),
      expandBtn({
        title: "Retrieved Documents",
        render: () => renderExpandedContent(renderDocuments(span)),
      }, "Expand documents"),
    ], "tv-card-actions");
    html += `</div>`;

    if (query) {
      html += renderLabeledSection(
        "Query",
        `<div class="tv-doc-query tv-markdown">${esc(query)}</div>`,
        "tv-io-label-input"
      );
    }

    html += `<div class="tv-doc-grid">`;
    docs.forEach((doc, index) => {
      const metaHtml = renderDocMetaChips(doc);
      const title = String(doc.title || "Document");
      const secondary = `Document ${index + 1}`;
      const expandPayload = {
        title: `${title} #${index + 1}`,
        render: () => renderExpandedContent(
          `<div class="tv-doc-card tv-doc-card-expanded">` +
            `<div class="tv-doc-card-head"><div class="tv-doc-title-wrap"><span class="tv-doc-icon">${ICONS.RETRIEVER}</span><div class="tv-doc-title-block"><div class="tv-doc-title">${esc(title)}</div><div class="tv-doc-index">${esc(secondary)}</div></div></div></div>` +
            `<div class="tv-doc-body tv-markdown">${esc(doc.text)}</div>` +
            (metaHtml ? `<div class="tv-doc-meta">${metaHtml}</div>` : "") +
          `</div>`
        ),
      };

      html += `<article class="tv-doc-card">`;
      html += `<div class="tv-doc-card-head">`;
      html += `<div class="tv-doc-title-wrap">`;
      html += `<span class="tv-doc-icon">${ICONS.RETRIEVER}</span>`;
      html += `<div class="tv-doc-title-block"><div class="tv-doc-title">${esc(title)}</div><div class="tv-doc-index">${esc(secondary)}</div></div>`;
      html += `</div>`;
      html += actionGroup([
        copyBtn(doc.text, "Copy document text"),
        expandBtn(expandPayload, "Expand document"),
      ], "tv-card-actions");
      html += `</div>`;
      html += `<div class="tv-doc-body tv-markdown">${esc(doc.text)}</div>`;
      if (metaHtml) html += `<div class="tv-doc-meta">${metaHtml}</div>`;
      html += `</article>`;
    });
    html += `</div></div>`;
    return html;
  }

  function findLastDescendantMessagesSpan(span) {
    let latest = null;
    function latestTime(node) {
      if (node?.end_time_ns != null) return Number(node.end_time_ns);
      if (node?.start_time_ns != null) return Number(node.start_time_ns);
      return -Infinity;
    }
    function visit(node) {
      (node?._children || []).forEach(child => {
        visit(child);
        if (spanKind(child) !== "LLM") return;
        const childAttrs = child.attributes || {};
        const hasMessages =
          extractMessages(childAttrs, "llm.input_messages").length ||
          extractMessages(childAttrs, "llm.output_messages").length;
        if (!hasMessages) return;
        if (!latest || latestTime(child) > latestTime(latest) || (latestTime(child) === latestTime(latest) && child._i > latest._i)) {
          latest = child;
        }
      });
    }
    visit(span);
    return latest;
  }

  function messageSignatures(message) {
    const role = String(message?.role || "").toLowerCase();
    if (role !== "assistant") return [];
    const content = message?.content == null ? "" : String(message.content);
    const toolCalls = Array.isArray(message?.toolCalls)
      ? message.toolCalls.map(tc => ({
          id: tc?.id == null ? "" : String(tc.id),
          name: tc?.name == null ? "" : String(tc.name),
          arguments: tc?.arguments == null ? "" : String(tc.arguments),
        }))
      : [];
    const base = { role, content, toolCalls };
    const noIds = { role, content, toolCalls: toolCalls.map(tc => ({ name: tc.name, arguments: tc.arguments })) };
    return [JSON.stringify(base), JSON.stringify(noIds)];
  }

  function assistantReasoningIndex() {
    const attemptData = currentAttemptData();
    if (attemptData?._assistantReasoningIndex) return attemptData._assistantReasoningIndex;
    const index = new Map();
    const nodes = currentTree()?.nodes || [];

    nodes.forEach(span => {
      const attrs = span.attributes || {};
      const outputMsgs = extractMessages(attrs, "llm.output_messages").map(m => ({ ...m, _reasoning: m.reasoning || null }));
      let spanReasoning = extractReasoning(span);

      if (spanReasoning) {
        for (let i = outputMsgs.length - 1; i >= 0; i--) {
          if (String(outputMsgs[i].role || "").toLowerCase() === "assistant" && !outputMsgs[i]._reasoning) {
            outputMsgs[i]._reasoning = spanReasoning;
            spanReasoning = null;
            break;
          }
        }
      }

      outputMsgs.forEach(message => {
        if (!message._reasoning) return;
        messageSignatures(message).forEach(sig => {
          if (sig && !index.has(sig)) index.set(sig, message._reasoning);
        });
      });
    });

    if (attemptData) attemptData._assistantReasoningIndex = index;
    return index;
  }

  function renderMessageContent(text, jsonClassName) {
    const body = String(text || "").trim();
    if (!body) return "";
    if ((body.startsWith("{") && body.endsWith("}")) || (body.startsWith("[") && body.endsWith("]"))) {
      try {
        JSON.parse(body);
        return `<div class="tv-msg-body">${renderJsonBlock(body, jsonClassName)}</div>`;
      } catch (_) {
        return `<div class="tv-msg-body">${esc(body)}</div>`;
      }
    }
    if (body.includes("```")) return `<div class="tv-msg-body">${renderMarkdownLite(body)}</div>`;
    return `<div class="tv-msg-body">${esc(body)}</div>`;
  }

  function renderToolCallCard(tc, actionsHtml, jsonClassName) {
    let html = `<div class="tv-toolcall">`;
    html += `<div class="tv-toolcall-name">${esc(tc.name)} <span class="tv-toolcall-label">call</span>${actionsHtml || ""}</div>`;
    if (tc.arguments) html += renderJsonBlock(tc.arguments, jsonClassName);
    html += `</div>`;
    return html;
  }

  function renderExpandedContent(bodyHtml) {
    return `<div class="tv-modal-content">${bodyHtml}</div>`;
  }

  function renderToolHeader(name, badge, toolCallId, actionsHtml) {
    return `<div class="tv-msg-role">${esc(name)} <span class="tv-toolcall-label">${esc(badge)}</span>${toolCallId ? ` <span class="tv-msg-tcid">${esc(toolCallId)}</span>` : ""}${actionsHtml || ""}</div>`;
  }

  function directToolCallId(attrs) {
    return attrs["tool_call.id"] || attrs["tool.call.id"] || attrs["tool_call_id"] || attrs["tool.call_id"] || "";
  }

  function inferToolCallId(span) {
    const attrs = span.attributes || {};
    const direct = directToolCallId(attrs);
    if (direct) return direct;
    if (span._resolvedToolCallId !== undefined) return span._resolvedToolCallId || "";

    const toolName = attrs["tool.name"] || span.name || "";
    const inputValue = attrs["input.value"] == null ? "" : String(attrs["input.value"]);
    const outputValue = attrs["output.value"] == null ? "" : String(attrs["output.value"]);
    const nodes = currentTree()?.nodes || [];

    for (const node of nodes) {
      const nodeAttrs = node.attributes || {};
      const messages = extractMessages(nodeAttrs, "llm.input_messages").concat(extractMessages(nodeAttrs, "llm.output_messages"));
      if (!messages.length) continue;

      const toolInfoById = {};
      messages.forEach(msg => {
        if (!msg.toolCalls || !msg.toolCalls.length) return;
        msg.toolCalls.forEach(tc => {
          if (tc.id) toolInfoById[tc.id] = { name: tc.name || "", arguments: tc.arguments == null ? "" : String(tc.arguments) };
        });
      });

      for (const msg of messages) {
        if (String(msg.role || "").toLowerCase() !== "tool" || !msg.toolCallId) continue;
        const info = toolInfoById[msg.toolCallId] || {};
        const msgContent = msg.content == null ? "" : String(msg.content);
        if (toolName && info.name && info.name !== toolName) continue;
        if (outputValue && msgContent === outputValue) {
          span._resolvedToolCallId = msg.toolCallId;
          return msg.toolCallId;
        }
        if (inputValue && info.arguments && info.arguments === inputValue) {
          span._resolvedToolCallId = msg.toolCallId;
          return msg.toolCallId;
        }
      }

      if (inputValue) {
        for (const [id, info] of Object.entries(toolInfoById)) {
          if (toolName && info.name && info.name !== toolName) continue;
          if (info.arguments && info.arguments === inputValue) {
            span._resolvedToolCallId = id;
            return id;
          }
        }
      }
    }

    span._resolvedToolCallId = "";
    return "";
  }

  function renderMessageBubble(message, headerActions, includeNestedActions) {
    const role = String(message.role).toLowerCase();
    const msgText = message.content ? String(message.content) : "";
    const resolvedName = message._resolvedToolName || "";
    let bubble = `<div class="tv-msg tv-msg-${role}">`;
    if (role === "tool" && resolvedName) {
        bubble += renderToolHeader(resolvedName, "result", message.toolCallId, headerActions);
    } else {
      bubble += `<div class="tv-msg-role">${esc(role)}${message.toolCallId ? ` <span class="tv-msg-tcid">${esc(message.toolCallId)}</span>` : ""}${headerActions || ""}</div>`;
    }
    if (message._reasoning) {
      const r = message._reasoning;
      bubble += `<details class="tv-thinking"><summary class="tv-thinking-toggle"><span class="tv-thinking-label"><span class="tv-thinking-label-text"><span class="tv-thinking-label-closed">Show Thinking</span><span class="tv-thinking-label-open">Hide Thinking</span></span></span></summary><div class="tv-thinking-body">${esc(r)}</div></details>`;
    }
    if (msgText) bubble += renderMessageContent(msgText, role === "tool" ? "tv-json-preview tv-json-preview-output" : "");
    if (message.toolCalls && message.toolCalls.length) {
      message.toolCalls.forEach(tc => {
        let actions = "";
        if (includeNestedActions) {
          actions = actionGroup([
            tc.arguments ? copyBtn(tc.arguments, "Copy arguments") : "",
            expandBtn({
              title: tc.name || "Tool Call",
              render: () => renderExpandedContent(renderJsonBlock(tc.arguments || "")),
            }, "Expand tool call"),
          ]);
        }
        bubble += renderToolCallCard(tc, actions, "tv-json-preview");
      });
    }
    bubble += `</div>`;
    return bubble;
  }

  function renderReasoningBlock(reasoning, actionsHtml, open) {
    return `<details class="tv-reasoning-expander"${open ? " open" : ""}><summary class="tv-reasoning-summary"><span class="tv-reasoning-title">Reasoning</span>${actionsHtml || ""}</summary><div class="tv-reasoning">${esc(reasoning)}</div></details>`;
  }

  function renderErrorBox(errInfo, actionsHtml, attemptError) {
    let html = `<div class="tv-det-error">`;
    html += `<div class="tv-det-error-head"><div class="tv-det-error-title">Error</div>${actionsHtml || ""}</div>`;
    if (errInfo) {
      if (errInfo.type) html += `<div class="tv-det-error-type">${esc(errInfo.type)}</div>`;
      if (errInfo.message) html += `<div class="tv-det-error-msg">${esc(errInfo.message)}</div>`;
      if (errInfo.stacktrace) html += `<details class="tv-det-error-stack"><summary>Stack trace</summary><pre class="tv-code">${esc(errInfo.stacktrace)}</pre></details>`;
    } else if (attemptError) {
      html += `<div class="tv-det-error-msg">${esc(attemptError)}</div>`;
    } else {
      html += `<div class="tv-det-error-msg">This span completed with ERROR status</div>`;
    }
    html += `</div>`;
    return html;
  }

  function renderMetricMeta(meta) {
    const metaEntries = Object.entries(meta || {});
    return metaEntries.map(([k, v]) => {
      let valStr, valCls = "";
      if (typeof v === "boolean") { valStr = String(v); valCls = v ? "tv-metric-true" : "tv-metric-false"; }
      else if (typeof v === "number") { valStr = v.toLocaleString("en-US"); }
      else { valStr = String(v); }
      return `<div class="tv-metric-meta-row"><span class="tv-metric-meta-key">${esc(k)}</span><span class="tv-metric-meta-val ${valCls}">${esc(valStr)}</span></div>`;
    }).join("");
  }

  function renderMetricCard(name, data, metaId, actionsHtml) {
    const score = data && typeof data === "object" ? data.score : data;
    const meta = data && typeof data === "object" ? data.metadata : null;
    const isNum = typeof score === "number";
    const displayVal = isNum ? (Number.isInteger(score) || score > 10 ? score.toLocaleString("en-US") : score.toFixed(2)) : String(score ?? "—");
    const cls = metricToneClass(score);
    let card = `<div class="tv-metric-card ${cls}">`;
    card += `<div class="tv-metric-head${meta ? " tv-metric-expandable" : ""}" ${meta ? `data-metric-toggle="${metaId}"` : ""}>`;
    card += `<span class="tv-metric-name">${esc(name.replace(/_/g, " "))}</span>`;
    card += `<span class="tv-metric-side"><span class="tv-metric-val">${esc(displayVal)}</span>${actionsHtml || ""}</span>`;
    if (meta) card += `<span class="tv-metric-chevron"><svg viewBox="0 0 10 10" width="10" height="10"><path d="M3 2l4 3-4 3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></span>`;
    card += `</div>`;
    if (meta) card += `<div class="tv-metric-detail" id="${metaId}" style="display:none">${renderMetricMeta(meta)}</div>`;
    card += `</div>`;
    return card;
  }

  function renderScoreCard(sc, actionsHtml) {
    const v = typeof sc.value === "number" ? sc.value.toFixed(2) : sc.value;
    const tone = metricToneClass(sc.value);
    return `<div class="tv-score-card ${tone}"><div class="tv-score-head"><span class="tv-score-name">${esc(sc.name)}</span><span class="tv-score-side"><span class="tv-score-val ${tone}">${esc(v)}</span>${actionsHtml || ""}</span></div>${sc.explanation ? `<div class="tv-score-exp">${esc(sc.explanation)}</div>` : ""}</div>`;
  }

  function extractErrorInfo(span) {
    const events = Array.isArray(span.events) ? span.events : [];
    const ex = events.find(ev => ev.name === "exception");
    if (ex) {
      const a = ex.attributes || {};
      return { type: a["exception.type"] || "", message: a["exception.message"] || "", stacktrace: a["exception.stacktrace"] || "" };
    }
    const a = span.attributes || {};
    const msg = a["error.message"] || a["exception.message"] || a["otel.status_description"] || "";
    if (msg) return { type: a["error.type"] || a["exception.type"] || "", message: msg, stacktrace: a["exception.stacktrace"] || "" };
    return null;
  }

  /** Walk descendants to find the first concrete error info when the span itself has none. */
  function extractErrorInfoDeep(span) {
    const direct = extractErrorInfo(span);
    if (direct) return direct;
    const children = span._children || [];
    for (const child of children) {
      if (statusCls(child.status) !== "error") continue;
      const found = extractErrorInfoDeep(child);
      if (found) return found;
    }
    return null;
  }

  function detectRetries(tree) {
    tree.nodes.forEach(n => { n._retry = 0; n._failed = false; });
    function processChildren(children) {
      const seen = {};
      children.forEach(c => {
        const name = c.name || "";
        if (!seen[name]) seen[name] = [];
        seen[name].push(c);
      });
      Object.values(seen).forEach(group => {
        if (group.length <= 1) return;
        let retryNum = 0;
        for (const span of group) {
          if (retryNum > 0) span._retry = retryNum;
          if (statusCls(span.status) === "error") {
            span._failed = true;
            retryNum++;
          }
        }
      });
    }
    processChildren(tree.roots);
    tree.nodes.forEach(n => { if (n._children.length) processChildren(n._children); });

    // Propagate the failed-attempt marker to descendants so the whole
    // attempt stays visually grouped in the tree.
    function propagate(node) {
      if (!node._children) return;
      node._children.forEach(c => {
        if (node._failed) c._failed = true;
        propagate(c);
      });
    }
    tree.roots.forEach(propagate);
  }

  function extractReasoning(span) {
    const a = span.attributes || {};
    // Check gen_ai.completion.N.reasoning
    for (let i = 0; i < 5; i++) {
      const r = a[`gen_ai.completion.${i}.reasoning`];
      if (r) return r;
    }
    // Check output.value for reasoning field
    try {
      const ov = a["output.value"];
      if (typeof ov === "string") {
        const parsed = JSON.parse(ov);
        if (parsed?.choices) {
          for (const c of parsed.choices) {
            const r = c?.message?.reasoning;
            if (r) return r;
          }
        }
      }
    } catch (_) {}
    return null;
  }

  function spanReasoningTokens(span) {
    const a = span.attributes || {};
    const direct = a["llm.token_count.completion_details.reasoning"]
      || a["gen_ai.usage.completion_tokens_details.reasoning_tokens"]
      || a["gen_ai.usage.output_tokens_details.reasoning"]
      || a["gen_ai.usage.reasoning_tokens"];
    const parsedDirect = Number(direct || 0);
    if (Number.isFinite(parsedDirect) && parsedDirect > 0) return parsedDirect;
    try {
      const parsed = JSON.parse(String(a["output.value"] || ""));
      const tokens = parsed?.usage?.completion_tokens_details?.reasoning_tokens;
      const parsedTokens = Number(tokens || 0);
      return Number.isFinite(parsedTokens) && parsedTokens > 0 ? parsedTokens : 0;
    } catch (_) {
      return 0;
    }
  }

  function spanHasReasoning(span) {
    return !!(extractReasoning(span) || spanReasoningTokens(span) > 0);
  }

  /* ── aggregate stats ── */
  function aggregateStats(tree) {
    let totalTokens = 0, totalCost = 0;
    tree.nodes.forEach(n => {
      if (spanKind(n) === "LLM") {
        totalTokens += spanTokens(n) || 0;
        totalCost += spanCost(n) || 0;
      }
    });
    return { totalTokens, totalCost };
  }

  /* ── search filter ── */
  function applySearch(tree) {
    const q = S.search.toLowerCase().trim();
    if (!q) { tree.nodes.forEach(n => n._visible = true); return; }
    tree.nodes.forEach(n => n._visible = false);
    tree.nodes.forEach(n => {
      if (n.name && n.name.toLowerCase().includes(q)) {
        n._visible = true;
        // show ancestors
        let cur = n.parent_span_id ? tree.byId.get(n.parent_span_id) : null;
        while (cur) { cur._visible = true; S.expanded.add(cur.span_id); cur = cur.parent_span_id ? tree.byId.get(cur.parent_span_id) : null; }
      }
    });
  }

  /* ── rendering: header ── */
  function renderHeader(meta, data) {
    const attempt = currentAttemptData();
    const sum = attempt?.summary || data?.summary || {};
    const item = data?.item || {};
    const tree = attempt?._tree;
    const stats = tree ? aggregateStats(tree) : { totalTokens: 0, totalCost: 0 };

    S.el.title.textContent = meta.itemLabel || item.item_id || "Trace";
    if (S.el.attempts) {
      const attempts = Array.isArray(data?.attempts) ? data.attempts : [];
      if (attempts.length <= 1) {
        S.el.attempts.innerHTML = "";
        S.el.attempts.style.display = "none";
      } else {
        const selectedAttempt = Number(attempt?.attempt_number || 0);
        S.el.attempts.innerHTML = attempts.map(att => {
          const isActive = Number(att.attempt_number) === selectedAttempt;
          const isFailed = !att.is_last_attempt;
          const errReason = !att.is_last_attempt && att.error ? att.error : "";
          const badge = att.is_last_attempt
            ? `<span class="tv-attempt-badge qym-badge qym-badge--neutral">latest</span>`
            : `<span class="tv-attempt-badge qym-badge qym-badge--danger failed">failed</span>`;
          const tooltip = errReason ? ` title="${esc(errReason)}"` : "";
          return (
            `<button type="button" class="tv-attempt-btn ${isActive ? "active" : ""} ${isFailed ? "failed" : ""}" data-attempt="${esc(att.attempt_number)}"${tooltip}>` +
              `Attempt ${esc(att.attempt_number)}` +
              `<span class="tv-attempt-dur">${esc(fmtDur(att.latency_ms))}</span>` +
              badge +
            `</button>`
          );
        }).join("");
        S.el.attempts.style.display = "";
      }
    }

    // Score pills from root span events
    const rootSpan = tree?.roots?.[0];
    const scores = rootSpan ? extractScores(rootSpan) : [];

    let chips = `<span class="tv-chip qym-tag qym-tag--count">${sum.span_count||0} spans</span>`;
    chips += `<span class="tv-chip qym-tag qym-tag--data">${esc(fmtDur(sum.duration_ms))}</span>`;
    if (stats.totalTokens > 0) chips += `<span class="tv-chip tv-chip-tokens qym-tag qym-tag--data qym-tag--info">${fmtTokens(stats.totalTokens)} tokens</span>`;
    const costStr = fmtCost(stats.totalCost);
    if (costStr) chips += `<span class="tv-chip qym-tag qym-tag--data">${costStr}</span>`;
    // Count only spans with an actual exception event (not just inherited ERROR status)
    const realErrorCount = tree ? tree.nodes.filter(n =>
      statusCls(n.status) === "error" && (Array.isArray(n.events) ? n.events : []).some(ev => ev.name === "exception")
    ).length : (sum.error_count || 0);
    const displayErrorCount = realErrorCount || (sum.error_count ? 1 : 0);
    if (displayErrorCount) chips += `<span class="tv-chip tv-chip-error qym-badge qym-badge--danger">${displayErrorCount} error${displayErrorCount>1?"s":""}</span>`;
    scores.forEach(sc => {
      const v = typeof sc.value === "number" ? sc.value.toFixed(2) : sc.value;
      const tone = metricToneClass(sc.value);
      chips += `<span class="tv-chip tv-chip-score qym-badge ${tone === "pass" ? "qym-badge--success" : tone === "fail" ? "qym-badge--danger" : "qym-badge--neutral"} ${tone}">${esc(sc.name)}: ${esc(v)}</span>`;
    });
    const traceId = attempt ? (attempt.trace_id || "") : (item.trace_id || "");
    if (traceId) chips += `<button type="button" class="tv-chip tv-chip-copy qym-chip" data-trace-copy="${esc(traceId)}" title="Copy Trace ID">ID</button>`;

    S.el.meta.innerHTML = chips;

    // Warning
    if (sum.has_orphans) { S.el.warning.textContent = `${sum.orphan_count} orphan span${sum.orphan_count===1?"":"s"}`; S.el.warning.style.display = ""; }
    else { S.el.warning.style.display = "none"; }
  }

  function allExpandableSpanIds() {
    const tree = currentTree();
    if (!tree) return [];
    return tree.nodes.filter(hasChildren).map(node => node.span_id);
  }

  function areAllSpansExpanded() {
    const ids = allExpandableSpanIds();
    return !!ids.length && ids.every(id => S.expanded.has(id));
  }

  function updateTreeToggleButton() {
    const btn = S.el.treeToggle;
    const tree = currentTree();
    if (!btn) return;
    if (!tree || !tree.nodes.length) {
      btn.disabled = true;
      btn.innerHTML = EXPAND_ALL_ICON;
      btn.setAttribute("data-tree-toggle-mode", "expand");
      btn.setAttribute("title", "Expand spans");
      btn.setAttribute("aria-label", "Expand spans");
      return;
    }
    const allExpanded = areAllSpansExpanded();
    btn.disabled = false;
    btn.innerHTML = allExpanded ? COLLAPSE_ALL_ICON : EXPAND_ALL_ICON;
    btn.setAttribute("data-tree-toggle-mode", allExpanded ? "collapse" : "expand");
    btn.setAttribute("title", allExpanded ? "Collapse spans" : "Expand spans");
    btn.setAttribute("aria-label", allExpanded ? "Collapse spans" : "Expand spans");
  }

  function setTreeExpansion(expandAll) {
    const tree = currentTree();
    if (!tree) return;
    if (expandAll) {
      S.expanded = new Set(allExpandableSpanIds());
    } else {
      S.expanded = new Set(tree.roots.filter(hasChildren).map(node => node.span_id));
      if (tree.roots[0]) {
        S.selected = tree.roots[0].span_id;
        S.activeTab = null;
      }
    }
    renderTree();
  }

  /* ── rendering: span tree ── */
  function renderTree() {
    const tree = currentTree();
    if (!tree || !tree.nodes.length) {
      S.el.list.innerHTML = `<div class="tv-empty"><div class="tv-empty-t">No trace data</div><div class="tv-empty-d">This item may not have tracing enabled.</div></div>`;
      S.el.detail.innerHTML = "";
      updateTreeToggleButton();
      return;
    }
    applySearch(tree);
    detectRetries(tree);
    const bounds = computeBounds(currentAttemptData());
    const rows = [];

    function visit(node, isLast, prefix) {
      if (!node._visible) return;
      const kids = node._children || [];
      const exp = S.expanded.has(node.span_id);
      const sel = S.selected === node.span_id;
      const kind = spanKind(node);
      const tokens = spanTokens(node);
      const color = KIND_COLORS[kind] || KIND_COLORS.DEFAULT;

      // waterfall
      let left = 0, width = 100;
      if (bounds.start != null && node.start_time_ns != null) left = ((Number(node.start_time_ns)-Number(bounds.start))/bounds.total)*100;
      if (bounds.start != null && node.end_time_ns != null && node.start_time_ns != null) width = ((Number(node.end_time_ns)-Number(node.start_time_ns))/bounds.total)*100;
      width = Math.max(width, 0.75);

      const visibleKids = kids.filter(c => c._visible);

      // Tree connector guides
      let guidesHtml = '';
      for (let i = 0; i < prefix.length; i++) {
        const seg = prefix[i];
        const isPipe = typeof seg === "object" ? !!seg.pipe : !!seg;
        const opacity = typeof seg === "object" && seg.opacity != null ? seg.opacity : laneOpacity(i);
        let guideStyle = `--tv-guide-opacity:${opacity}`;
        if (typeof seg === "object" && seg.color) guideStyle += `;--tv-guide-color:${seg.color}`;
        guidesHtml += `<span class="tv-guide ${isPipe ? 'pipe' : 'space'}" style="${guideStyle}"></span>`;
      }
      if (node._depth > 0) {
        const guideType = isLast ? 'elbow' : 'branch';
        const isErr = statusCls(node.status) === "error";
        const hasException = isErr && (Array.isArray(node.events) ? node.events : []).some(ev => ev.name === "exception");
        if (hasException) {
          guidesHtml += `<span class="tv-guide ${guideType}" style="--tv-guide-opacity:1;--tv-guide-color:#ef4444"></span>`;
        } else {
          guidesHtml += `<span class="tv-guide ${guideType}" style="--tv-guide-opacity:${laneOpacity(prefix.length)}"></span>`;
        }
      }

      // Toggle (expand/collapse) — right side
      const toggleHtml = visibleKids.length
        ? `<span class="tv-toggle ${exp?"open":""}" data-toggle="${esc(node.span_id)}"><svg viewBox="0 0 10 10" width="10" height="10"><path d="M3 2l4 3-4 3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></span>`
        : `<span class="tv-toggle tv-toggle-empty"></span>`;

      // Inline meta for LLM spans
      let inlineMeta = "";
      const model = kind === "LLM" ? spanModel(node) : "";
      if (kind === "LLM" && model) inlineMeta += `<span class="tv-inline-model model-label"><span class="model-label-text">${esc(model)}</span>${spanHasReasoning(node) ? renderModelReasoningBadge() : ""}</span>`;
      if (kind === "LLM" && tokens) inlineMeta += `<span class="tv-inline-tokens"><svg class="tv-tokens-icon" viewBox="0 0 16 16" width="13" height="13"><ellipse cx="9" cy="10.5" rx="5.5" ry="2.8" fill="currentColor" opacity=".45"/><ellipse cx="7.5" cy="7.5" rx="5.5" ry="2.8" transform="rotate(-15 7.5 7.5)" fill="currentColor" opacity=".7"/><ellipse cx="6.5" cy="4.5" rx="5" ry="2.5" transform="rotate(-25 6.5 4.5)" fill="currentColor"/></svg>${fmtTokens(tokens)}</span>`;

      const stCls = statusCls(node.status);

      // Error indicator
      let errHtml = "";
      if (stCls === "error") {
        const errInfo = extractErrorInfoDeep(node);
        errHtml = `<span class="tv-err-badge" title="${esc(errInfo?.message || 'Error')}"><svg viewBox="0 0 16 16" width="12" height="12"><circle cx="8" cy="8" r="7" fill="currentColor" opacity=".15"/><path d="M8 4v5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="8" cy="11.5" r="1" fill="currentColor"/></svg></span>`;
      }

      const rowCls = [
        "tv-row",
        sel ? "sel" : "",
        stCls === "error" ? "row-err" : "",
        node._failed ? "row-failed" : "",
      ].filter(Boolean).join(" ");

      const iconHtml = `<span class="tv-icon" style="background:${color}20;color:${color}">${ICONS[kind]||ICONS.DEFAULT}</span>`;

      rows.push(
        `<button type="button" class="${rowCls}" data-span="${esc(node.span_id)}">` +
          `<span class="tv-tree-gutter">${guidesHtml}${iconHtml}</span>` +
          `<span class="tv-row-main">` +
            `<span class="tv-name-group"><span class="tv-name">${esc(node.name||"(unnamed)")}</span>${errHtml}${inlineMeta}</span>` +
            `<span class="tv-dur">${esc(fmtDur(node.duration_ms))}</span>` +
            `<span class="tv-wf"><span class="tv-wf-track"></span><span class="tv-wf-bar ${stCls}" style="left:${left}%;width:${Math.min(width,100)}%;background:${color}"></span></span>` +
            toggleHtml +
          `</span>` +
        `</button>`
      );
      if (exp) {
        const childPrefix = [...prefix];
        if (node._depth > 0) childPrefix.push(!isLast);
        visibleKids.forEach((child, i) => {
          visit(child, i === visibleKids.length - 1, childPrefix);
        });
      }
    }
    const visibleRoots = tree.roots.filter(r => r._visible);
    visibleRoots.forEach((r, i) => visit(r, i === visibleRoots.length - 1, []));
    S.el.list.innerHTML = rows.join("");
    updateTreeToggleButton();
    renderDetail();
  }

  /* ── rendering: detail panel ── */
  function renderDetail() {
    const tree = currentTree();
    const span = tree?.byId?.get(S.selected);
    if (!span) {
      S.el.detail.innerHTML = `<div class="tv-empty"><div class="tv-empty-t">Select a span</div></div>`;
      return;
    }

    const kind = spanKind(span);
    const model = spanModel(span);
    const attrs = span.attributes || {};
    const stCls = statusCls(span.status);
    const color = KIND_COLORS[kind] || KIND_COLORS.DEFAULT;
    const tokens = spanTokens(span);
    const cost = spanCost(span);

    // Build tabs based on span kind
    const tabs = [];
    const messageSourceSpan = kind === "AGENT" ? (findLastDescendantMessagesSpan(span) || null) : span;
    const messageAttrs = messageSourceSpan?.attributes || {};
    const inputMsgs = extractMessages(messageAttrs, "llm.input_messages");
    const outputMsgs = extractMessages(messageAttrs, "llm.output_messages");
    // Enrich messages with reasoning from input.value / output.value JSON
    enrichReasoning(inputMsgs, messageAttrs["input.value"]);
    enrichReasoning(outputMsgs, messageAttrs["output.value"]);
    const reasoning = extractReasoning(messageSourceSpan || span);
    const scores = extractScores(span);

    if (kind === "LLM") {
      if (inputMsgs.length || outputMsgs.length) tabs.push({ id: "messages", label: "Messages" });
      tabs.push({ id: "response", label: "Response" });
    } else if (kind === "AGENT") {
      if (attrs["input.value"] || attrs["output.value"]) tabs.push({ id: "io", label: "Input / Output" });
      if (inputMsgs.length || outputMsgs.length) tabs.push({ id: "messages", label: "Messages" });
    } else if (kind === "TOOL") {
      tabs.push({ id: "tool-io", label: "Input / Output" });
    } else if (kind === "RETRIEVER") {
      if (extractRetrieverDocs(span).length) tabs.push({ id: "documents", label: "Documents" });
      if (attrs["input.value"] || attrs["output.value"]) tabs.push({ id: "io", label: "Input / Output" });
    } else if (kind === "EVALUATOR" && attrs["output.value"]) {
      tabs.push({ id: "metrics", label: "Metrics" });
      if (scores.length) tabs.push({ id: "scores", label: "Scores" });
    } else {
      if (attrs["input.value"] || attrs["output.value"]) tabs.push({ id: "io", label: "Input / Output" });
      if (scores.length) tabs.push({ id: "scores", label: "Scores" });
    }
    tabs.push({ id: "raw", label: "Raw" });
    if (scores.length && kind !== "TOOL") {
      if (!tabs.find(t => t.id === "scores")) tabs.splice(tabs.length - 1, 0, { id: "scores", label: "Scores" });
    }

    // Default tab
    if (!S.activeTab || !tabs.find(t => t.id === S.activeTab)) {
      S.activeTab = tabs[0]?.id || "raw";
    }

    // Header
    let header = `<div class="tv-det-head">`;
    header += `<div class="tv-det-icon" style="color:${color}">${ICONS[kind]||ICONS.DEFAULT}</div>`;
    header += `<div class="tv-det-info"><div class="tv-det-name">${esc(span.name)}</div>`;
    header += `<div class="tv-det-sub">`;
    if (model) header += `<span class="model-label"><span class="model-label-text">${esc(model)}</span>${spanHasReasoning(span) ? renderModelReasoningBadge() : ""}</span><span class="tv-dot"></span>`;
    header += `<span>${esc(fmtDur(span.duration_ms))}</span>`;
    if (tokens) header += `<span class="tv-dot"></span><span>${fmtTokens(tokens)} tokens</span>`;
    const costStr = fmtCost(cost);
    if (costStr) header += `<span class="tv-dot"></span><span>${costStr}</span>`;
    header += `</div></div>`;
    if (stCls !== "unset") header += `<span class="tv-chip tv-chip-status-${stCls} qym-badge ${stCls === "error" ? "qym-badge--danger" : "qym-badge--success"}">${esc(String(span.status).toUpperCase())}</span>`;
    header += `</div>`;

    // Error detail block
    if (stCls === "error") {
      const errInfo = extractErrorInfoDeep(span);
      const attemptErr = currentAttemptData()?.error || "";
      const fallbackMsg = attemptErr || "This span completed with ERROR status";
      const copyPayload = errInfo ? () => JSON.stringify(errInfo, null, 2) : fallbackMsg;
      header += renderErrorBox(errInfo, actionGroup([
        copyBtn(copyPayload, "Copy error"),
        expandBtn({
          title: `${span.name} Error`,
          render: () => renderErrorBox(errInfo, "", attemptErr),
        }, "Expand error"),
      ]), attemptErr);
    }

    // Tabs + view mode toggle
    let tabBar = `<div class="tv-tabs qym-tabs" role="tablist" aria-label="Trace detail sections">`;
    tabs.forEach(t => {
      tabBar += `<button type="button" role="tab" id="tv-detail-tab-${t.id}" aria-controls="tv-detail-panel" class="tv-tab qym-tabs__tab ${S.activeTab===t.id?"active":""}" data-tab="${t.id}" aria-selected="${S.activeTab===t.id}">${esc(t.label)}</button>`;
    });
    tabBar += `</div>`;

    // Tab content
    let content = `<div class="tv-tab-content" id="tv-detail-panel" role="tabpanel" aria-labelledby="tv-detail-tab-${S.activeTab}">`;
    if (S.activeTab === "messages") content += renderMessages(inputMsgs.concat(outputMsgs), reasoning);
    else if (S.activeTab === "response") content += renderResponse(span);
    else if (S.activeTab === "tool-io") content += renderToolIO(span);
    else if (S.activeTab === "metrics") content += renderMetrics(span);
    else if (S.activeTab === "documents") content += renderDocuments(span);
    else if (S.activeTab === "io") content += renderIO(span);
    else if (S.activeTab === "scores") content += renderScores(scores);
    else if (S.activeTab === "raw") content += renderRaw(span);
    content += `</div>`;

    S.el.detail.innerHTML = header + tabBar + content;
    mountJsonFormatters(S.el.detail);
  }

  /* ── tab renderers ── */
  function decorateMessages(msgs, reasoning) {
    const reasoningIndex = assistantReasoningIndex();
    const decorated = (msgs || []).map(m => ({
      ...m,
      _reasoning: m.reasoning || null,
      _resolvedToolName: m._resolvedToolName || "",
    }));

    const tcMap = {};
    decorated.forEach(m => {
      if (!m.toolCalls) return;
      m.toolCalls.forEach(tc => {
        if (tc.id && tc.name) tcMap[tc.id] = tc.name;
      });
    });

    decorated.forEach(m => {
      if (m.toolCallId && tcMap[m.toolCallId]) m._resolvedToolName = tcMap[m.toolCallId];
    });

    decorated.forEach(m => {
      if (m._reasoning) return;
      const sigs = messageSignatures(m);
      for (const sig of sigs) {
        const matched = reasoningIndex.get(sig);
        if (matched) {
          m._reasoning = matched;
          break;
        }
      }
    });

    if (reasoning) {
      for (let i = decorated.length - 1; i >= 0; i--) {
        if (String(decorated[i].role || "").toLowerCase() === "assistant" && !decorated[i]._reasoning) {
          decorated[i]._reasoning = reasoning;
          reasoning = null;
          break;
        }
      }
    }

    return { msgs: decorated, remainingReasoning: reasoning };
  }

  function renderMessages(msgs, reasoning) {
    if (!msgs.length && !reasoning) return `<div class="tv-empty-d">No messages</div>`;
    const decorated = decorateMessages(msgs, reasoning);
    const reasoningAttached = decorated.msgs.some(m => !!m._reasoning);
    let html = decorated.msgs.map(m => {
      const msgText = m.content ? String(m.content) : "";
      const role = String(m.role || "").toLowerCase();
      const expandTitle = role === "tool" && m._resolvedToolName
        ? `${m._resolvedToolName} Result`
        : `${String(m.role || "message")} Message`;
      const expandRender = role === "tool" && msgText
        ? () => renderExpandedContent(renderValueBlock(msgText))
        : () => renderMessageBubble(m, "", false);
      const actions = actionGroup([
        msgText ? copyBtn(msgText, "Copy message") : "",
        expandBtn({
          title: expandTitle,
          render: expandRender,
        }, "Expand message"),
      ]);
      return renderMessageBubble(m, actions, true);
    }).join("");

    // Fallback: if no assistant message found, show reasoning standalone
    if (decorated.remainingReasoning && !reasoningAttached) {
      html += renderReasoningBlock(decorated.remainingReasoning, actionGroup([
        copyBtn(decorated.remainingReasoning, "Copy reasoning"),
        expandBtn({
          title: "Reasoning",
          render: () => renderReasoningBlock(decorated.remainingReasoning, "", true),
        }, "Expand reasoning"),
      ]), false);
    }

    return html;
  }

  function renderMarkdownLite(text) {
    // Very basic: handle ```code``` blocks
    const parts = text.split(/(```[\s\S]*?```)/g);
    return parts.map(p => {
      if (p.startsWith("```")) {
        const inner = p.replace(/^```\w*\n?/, "").replace(/```$/, "");
        return `<pre class="tv-code">${esc(inner)}</pre>`;
      }
      return `<span>${esc(p)}</span>`;
    }).join("");
  }

  function parseDisplayValue(value) {
    try {
      const parsed = typeof value === "string" ? JSON.parse(value) : value;
      return deepParseJson(parsed);
    } catch (_) {
      return value == null ? "" : String(value);
    }
  }

  function looksLikeCode(text) {
    const body = String(text || "").trim();
    if (!body) return false;
    if (body.includes("```")) return true;
    if (/\b(SELECT|WITH|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\b[\s\S]*\b(FROM|WHERE|JOIN|VALUES|SET)\b/i.test(body)) return true;
    if (/^\s*(def |class |function |async function |const |let |var |import |from |return |if |for |while )/m.test(body)) return true;
    if ((body.match(/\n/g) || []).length >= 2 && /[{}();<>]/.test(body)) return true;
    return false;
  }

  function renderAgentOutputBody(value, className) {
    return renderValueBlock(value, className);
  }

  function valueToneClass(className) {
    const cls = String(className || "");
    if (cls.includes("tv-json-preview-output")) return " tv-value-block-output";
    if (cls.includes("tv-json-preview")) return " tv-value-block-input";
    return "";
  }

  function renderValueBlock(value, className) {
    const parsed = parseDisplayValue(value);
    if (typeof parsed !== "string") return renderJsonBlock(value, className);
    const body = parsed.trim();
    if (!body) return `<div class="tv-markdown${className ? ` ${className}` : ""}"></div>`;
    if (looksLikeCode(body)) return renderTextPlaceholder(body, `${className || ""} tv-json-preview-output`.trim());
    return `<div class="tv-value-block${valueToneClass(className)}"><div class="tv-markdown">${renderMarkdownLite(body)}</div></div>`;
  }

  function renderResponse(span) {
    const a = span.attributes || {};
    const raw = a["output.value"];
    let parsed = null;
    try { if (raw) parsed = deepParseJson(typeof raw === "string" ? JSON.parse(raw) : raw); } catch (_) {}

    let html = "";

    // ── Usage section ──
    // Primary: output.value.usage, fallback: llm.token_count.* attrs
    const usage = parsed?.usage;
    const usageRows = [];
    function addUsage(label, val, cls) { if (val != null && val !== 0 && val !== "") usageRows.push([label, val, cls || ""]); }
    if (usage && typeof usage === "object") {
      addUsage("Prompt Tokens", usage.prompt_tokens);
      addUsage("Completion Tokens", usage.completion_tokens);
      const rd = usage.completion_tokens_details;
      if (rd) {
        addUsage("  Reasoning Tokens", rd.reasoning_tokens);
        addUsage("  Image Tokens", rd.image_tokens);
        addUsage("  Audio Tokens", rd.audio_tokens);
      }
      const pd = usage.prompt_tokens_details;
      if (pd) {
        addUsage("  Cached Tokens", pd.cached_tokens || pd.cache_read_tokens);
        addUsage("  Cache Write Tokens", pd.cache_write_tokens);
      }
      addUsage("Total Tokens", usage.total_tokens);
      if (usage.cost != null) addUsage("Cost", "$" + Number(usage.cost).toFixed(6), "tv-llm-cost");
      const cd = usage.cost_details;
      if (cd) {
        if (cd.upstream_inference_cost != null) addUsage("  Inference Cost", "$" + Number(cd.upstream_inference_cost).toFixed(6));
        if (cd.upstream_inference_prompt_cost != null) addUsage("    Prompt Cost", "$" + Number(cd.upstream_inference_prompt_cost).toFixed(6));
        if (cd.upstream_inference_completions_cost != null) addUsage("    Completions Cost", "$" + Number(cd.upstream_inference_completions_cost).toFixed(6));
      }
      if (usage.is_byok != null) addUsage("BYOK", String(usage.is_byok));
    } else {
      // Fallback to flat attrs
      addUsage("Prompt Tokens", a["llm.token_count.prompt"] || a["gen_ai.usage.prompt_tokens"]);
      addUsage("Completion Tokens", a["llm.token_count.completion"] || a["gen_ai.usage.completion_tokens"]);
      addUsage("Reasoning Tokens", a["llm.token_count.completion_details.reasoning"]);
      addUsage("Total Tokens", spanTokens(span));
      const c = spanCost(span);
      if (c) addUsage("Cost", fmtCost(c), "tv-llm-cost");
    }
    addUsage("Duration", fmtDur(span.duration_ms));
    if (usageRows.length) {
      const usageBody = `<div class="tv-params">${usageRows.map(([k,v,c]) => `<div class="tv-param${k.startsWith("  ") ? " tv-param-indent" : ""}"><span class="tv-param-k ${c}">${esc(k.trim())}</span><span class="tv-param-v ${c}">${esc(String(v))}</span></div>`).join("")}</div>`;
      html += renderLabeledSection("Usage", usageBody, "", actionGroup([
        copyBtn(() => JSON.stringify(usage || {}, null, 2), "Copy usage"),
        expandBtn({ title: "Usage", render: () => renderExpandedContent(usageBody) }, "Expand usage"),
      ]));
    }

    // ── Metadata section ──
    const choice = parsed?.choices?.[0];
    const metaRows = [];
    if (parsed?.provider) metaRows.push(["Provider", parsed.provider]);
    metaRows.push(["Model", parsed?.model || spanModel(span)]);
    if (parsed?.id) metaRows.push(["Response ID", parsed.id]);
    if (choice) {
      if (choice.finish_reason) metaRows.push(["Finish Reason", choice.finish_reason]);
      if (choice.native_finish_reason) metaRows.push(["Native Finish Reason", choice.native_finish_reason]);
    } else {
      const fr = a["gen_ai.completion.0.finish_reason"];
      if (fr) metaRows.push(["Finish Reason", fr]);
    }
    if (parsed?.created) metaRows.push(["Created", new Date(parsed.created * 1000).toISOString()]);
    if (parsed?.system_fingerprint) metaRows.push(["System Fingerprint", parsed.system_fingerprint]);
    metaRows.push(["Span ID", span.span_id]);
    const filteredMeta = metaRows.filter(([,v]) => v != null && v !== "");
    if (filteredMeta.length) {
      const metaBody = `<div class="tv-params">${filteredMeta.map(([k,v]) => `<div class="tv-param"><span class="tv-param-k">${esc(k)}</span><span class="tv-param-v">${esc(String(v))}</span></div>`).join("")}</div>`;
      html += renderLabeledSection("Metadata", metaBody, "", actionGroup([
        copyBtn(() => JSON.stringify(Object.fromEntries(filteredMeta), null, 2), "Copy metadata"),
      ]));
    }

    // ── Invocation section ──
    try {
      const ip = a["llm.invocation_parameters"];
      if (ip) {
        const params = typeof ip === "string" ? JSON.parse(ip) : ip;
        const ipRows = Object.entries(params).filter(([,v]) => v != null && v !== "");
        if (ipRows.length) {
          const ipBody = `<div class="tv-params">${ipRows.map(([k,v]) => `<div class="tv-param"><span class="tv-param-k">${esc(k)}</span><span class="tv-param-v">${esc(String(v))}</span></div>`).join("")}</div>`;
          html += renderLabeledSection("Invocation Parameters", ipBody, "", actionGroup([
            copyBtn(ip, "Copy invocation params"),
          ]));
        }
      }
    } catch (_) {}

    // ── Full Response JSON ──
    if (raw) {
      html += renderLabeledSection("Full Response", renderJsonBlock(raw, "tv-json-preview tv-json-preview-output"), "", actionGroup([
        copyBtn(() => JSON.stringify(parsed || raw, null, 2), "Copy full response"),
        expandBtn({ title: "Full Response", render: () => renderExpandedContent(renderJsonBlock(raw)) }, "Expand response"),
      ]));
    }

    if (!html) return `<div class="tv-empty-d">No response data</div>`;
    return html;
  }

  function renderToolIO(span) {
    const a = span.attributes || {};
    const toolName = a["tool.name"] || span.name || "tool";
    const toolCallId = inferToolCallId(span);
    const inp = a["input.value"];
    const out = a["output.value"];
    let html = "";

    // Tool call arguments — rendered as an assistant tool_call bubble
    if (inp) {
      html += `<div class="tv-msg tv-msg-assistant">`;
      html += renderToolHeader(toolName, "call", toolCallId, actionGroup([
        copyBtn(inp, "Copy input"),
        expandBtn({
          title: `${toolName} Input`,
          render: () => renderExpandedContent(renderValueBlock(inp)),
        }, "Expand tool call"),
      ]));
      html += `<div class="tv-msg-body">${renderValueBlock(inp, "tv-json-preview")}</div>`;
      html += `</div>`;
    }

    // Tool result — rendered as a tool result bubble
    if (out) {
      html += `<div class="tv-msg tv-msg-tool">`;
      html += renderToolHeader(toolName, "result", toolCallId, actionGroup([
        copyBtn(out, "Copy output"),
        expandBtn({
          title: `${toolName} Result`,
          render: () => renderExpandedContent(renderValueBlock(out)),
        }, "Expand result"),
      ]));
      html += `<div class="tv-msg-body">${renderValueBlock(out, "tv-json-preview tv-json-preview-output")}</div>`;
      html += `</div>`;
    }

    if (!inp && !out) html = `<div class="tv-empty-d">No input/output data</div>`;
    return html;
  }

  function renderIO(span) {
    const a = span.attributes || {};
    const kind = spanKind(span);
    let html = "";
    const inp = a["input.value"];
    const out = a["output.value"];
    if (inp) {
      html += renderLabeledSection("Input", renderValueBlock(inp, "tv-json-preview"), "tv-io-label-input", actionGroup([
        copyBtn(inp, "Copy input"),
        expandBtn({
          title: "Input",
          render: () => renderExpandedContent(renderValueBlock(inp)),
        }, "Expand input"),
      ]));
    }
    if (out) {
      const outputBody = kind === "AGENT"
        ? renderAgentOutputBody(out, "tv-json-preview-output")
        : renderValueBlock(out, "tv-json-preview tv-json-preview-output");
      html += renderLabeledSection("Output", outputBody, "tv-io-label-output", actionGroup([
        copyBtn(out, "Copy output"),
        expandBtn({
          title: "Output",
          render: () => renderExpandedContent(kind === "AGENT"
            ? renderAgentOutputBody(out, "")
            : renderValueBlock(out)),
        }, "Expand output"),
      ]));
    }
    if (!inp && !out) html = `<div class="tv-empty-d">No input/output data</div>`;
    return html;
  }

  /* ── JSON/value rendering (CodeMirror 6) ── */

  let _cmId = 0;
  const _cmData = {};
  let _cmModules = null;
  let _cmLoading = null;
  const _tvScriptSrc = document.currentScript && document.currentScript.src;

  function loadCodeMirror() {
    if (_cmModules) return Promise.resolve(_cmModules);
    if (_cmLoading) return _cmLoading;
    const fromCdn = () => Promise.all([
      import("https://esm.sh/@codemirror/state@6"),
      import("https://esm.sh/@codemirror/view@6"),
      import("https://esm.sh/@codemirror/language@6"),
      import("https://esm.sh/@codemirror/lang-json@6"),
      import("https://esm.sh/@codemirror/commands@6"),
      import("https://esm.sh/@lezer/highlight@1"),
    ]).then(([state, view, language, langJson, commands, highlight]) =>
      ({ state, view, language, langJson, commands, highlight }));
    // Prefer the vendored bundle, resolved relative to this script so it works
    // under any mount prefix (e.g. behind a reverse proxy); fall back to CDN.
    const bundleUrl = _tvScriptSrc
      ? new URL("codemirror-bundle.js", _tvScriptSrc).href
      : "/static/codemirror-bundle.js";
    _cmLoading = import(bundleUrl)
      .then((m) => ({ state: m.state, view: m.view, language: m.language,
                      langJson: m.langJson, commands: m.commands, highlight: m.highlight }))
      .catch(fromCdn)
      .then((mods) => { _cmModules = mods; return _cmModules; });
    return _cmLoading;
  }

  function renderCodeMirrorPlaceholder(doc, className, options = {}) {
    const id = `tv-cm-${++_cmId}`;
    _cmData[id] = {
      doc,
      mode: options.mode || "json",
    };
    return `<div class="tv-cm${className ? ` ${className}` : ""}" data-cm-id="${id}"></div>`;
  }

  function renderJsonPlaceholder(jsonStr, className) {
    return renderCodeMirrorPlaceholder(jsonStr, className, { mode: "json" });
  }

  function renderTextPlaceholder(text, className) {
    return renderCodeMirrorPlaceholder(text, `${className || ""} tv-cm-text`.trim(), { mode: "text" });
  }

  const PREVIEW_SCROLL_ROOT_SELECTOR = [
    ".tv-cm.tv-json-preview",
    ".tv-cm.tv-json-preview-output",
    ".tv-code.tv-json-preview",
    ".tv-code.tv-json-preview-output",
  ].join(", ");

  const PREVIEW_SCROLL_TARGET_SELECTOR = [
    ".tv-cm.tv-json-preview .cm-scroller",
    ".tv-cm.tv-json-preview-output .cm-scroller",
    ".tv-code.tv-json-preview",
    ".tv-code.tv-json-preview-output",
  ].join(", ");

  function previewScrollRoot(el) {
    return el?.closest ? el.closest(PREVIEW_SCROLL_ROOT_SELECTOR) : null;
  }

  function clearPreviewScrollActivation(scope) {
    if (!scope) return;
    scope.querySelectorAll(".tv-preview-scroll-active").forEach(el => {
      el.classList.remove("tv-preview-scroll-active");
    });
  }

  function activatePreviewScroll(previewEl) {
    if (!previewEl) return;
    const scope = previewEl.closest(".tv-detail, .tv-modal-body, .tv-modal-content") || previewEl.parentElement;
    clearPreviewScrollActivation(scope);
    previewEl.classList.add("tv-preview-scroll-active");
  }

  function canScrollInDirection(el, deltaY) {
    if (!el || !deltaY) return false;
    if (el.scrollHeight <= el.clientHeight + 1) return false;
    if (deltaY < 0) return el.scrollTop > 0;
    return el.scrollTop + el.clientHeight < el.scrollHeight - 1;
  }

  function findVerticalScrollParent(startEl) {
    let el = startEl;
    while (el && el !== document.body) {
      const style = window.getComputedStyle(el);
      const overflowY = style.overflowY;
      if ((overflowY === "auto" || overflowY === "scroll") && el.scrollHeight > el.clientHeight + 1) {
        return el;
      }
      el = el.parentElement;
    }
    return null;
  }

  function handleNestedPreviewWheel(event) {
    if (event.defaultPrevented || event.ctrlKey || !event.deltaY) return;
    if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
    const previewEl = previewScrollRoot(event.currentTarget);
    if (previewEl?.classList.contains("tv-preview-scroll-active")) return;
    const outerScroller = findVerticalScrollParent(previewEl?.parentElement || event.currentTarget.parentElement);
    event.preventDefault();
    if (!canScrollInDirection(outerScroller, event.deltaY)) return;
    outerScroller.scrollTop += event.deltaY;
  }

  function bindPreviewActivation(root) {
    if (!root || root.dataset.tvPreviewActivationBound === "1") return;
    root.dataset.tvPreviewActivationBound = "1";
    root.addEventListener("pointerdown", event => {
      const previewEl = previewScrollRoot(event.target);
      if (previewEl) {
        activatePreviewScroll(previewEl);
        return;
      }
      clearPreviewScrollActivation(root);
    });
    root.addEventListener("focusin", event => {
      const previewEl = previewScrollRoot(event.target);
      if (previewEl) {
        activatePreviewScroll(previewEl);
        return;
      }
      clearPreviewScrollActivation(root);
    });
    root.addEventListener("focusout", event => {
      if (previewScrollRoot(event.target) && !previewScrollRoot(event.relatedTarget)) {
        clearPreviewScrollActivation(root);
      }
    });
  }

  function preparePreviewRoot(el) {
    if (!el || el.dataset.tvPreviewPrepared === "1") return;
    el.dataset.tvPreviewPrepared = "1";
    if (el.matches(".tv-code") && !el.hasAttribute("tabindex")) {
      el.tabIndex = 0;
    }
  }

  function bindPreviewWheelTargets(root) {
    if (!root) return;
    root.querySelectorAll(PREVIEW_SCROLL_TARGET_SELECTOR).forEach(el => {
      if (el.dataset.tvWheelBound === "1") return;
      el.dataset.tvWheelBound = "1";
      el.addEventListener("wheel", handleNestedPreviewWheel, { passive: false });
    });
  }

  function bindPreviewScrollDelegation(root) {
    if (!root) return;
    bindPreviewActivation(root);
    root.querySelectorAll(PREVIEW_SCROLL_ROOT_SELECTOR).forEach(preparePreviewRoot);
    bindPreviewWheelTargets(root);
  }

  function mountJsonFormatters(root) {
    const els = root.querySelectorAll("[data-cm-id]");
    bindPreviewScrollDelegation(root);
    if (!els.length) return;
    loadCodeMirror().then(cm => {
      els.forEach(el => {
        const id = el.getAttribute("data-cm-id");
        const payload = _cmData[id];
        if (payload == null) return;
        delete _cmData[id];
        const doc = typeof payload === "string" ? payload : payload.doc;
        const mode = typeof payload === "string" ? "json" : (payload.mode || "json");
        const extensions = [
          cm.view.lineNumbers(),
          cm.view.drawSelection(),
          cm.view.keymap.of([...cm.commands.defaultKeymap]),
          cm.state.EditorState.readOnly.of(true),
          cm.view.EditorView.editable.of(false),
          cm.view.EditorView.theme({
            "&": { fontSize: "12px", background: "var(--bg-void)", color: "var(--text-secondary)" },
            ".cm-scroller": { overflow: "auto", fontFamily: "var(--font-mono)" },
            ".cm-gutters": { background: "var(--bg-void)", border: "none", minWidth: "auto" },
            ".cm-lineNumbers .cm-gutterElement": { color: "#6b6b80", minWidth: "1.8em", padding: "0 4px 0 4px", fontSize: "11px" },
            ".cm-line": { padding: "0 8px" },
            ".cm-activeLine": { background: "rgba(255,255,255,.03)" },
            ".cm-activeLineGutter": { background: "rgba(255,255,255,.03)" },
            ".cm-selectionBackground": { background: "rgba(0,168,255,.15) !important" },
            ".cm-cursor": { borderLeftColor: "#00d4aa" },
            "&.cm-focused .cm-selectionBackground": { background: "rgba(0,168,255,.2) !important" },
          }, { dark: true }),
        ];
        if (mode === "json") {
          extensions.push(
            cm.language.foldGutter(),
            cm.language.bracketMatching(),
            cm.langJson.json(),
            cm.view.keymap.of(cm.language.foldKeymap),
            cm.view.EditorView.theme({
              ".cm-foldGutter .cm-gutterElement": { color: "#9a9ab2", padding: "0 2px 0 0", width: "12px" },
              ".cm-matchingBracket": { background: "rgba(0,212,170,.15)", outline: "1px solid rgba(0,212,170,.3)" },
            }, { dark: true }),
            cm.language.syntaxHighlighting(cm.language.HighlightStyle.define([
              { tag: cm.highlight.tags.propertyName, color: "#00a8ff" },
              { tag: cm.highlight.tags.string, color: "#00d4aa" },
              { tag: cm.highlight.tags.number, color: "#a855f7" },
              { tag: cm.highlight.tags.bool, color: "#00a8ff" },
              { tag: cm.highlight.tags.null, color: "#6b6b80" },
              { tag: cm.highlight.tags.punctuation, color: "#9a9ab2" },
              { tag: cm.highlight.tags.brace, color: "#9a9ab2" },
              { tag: cm.highlight.tags.squareBracket, color: "#9a9ab2" },
            ]))
          );
        }
        const edState = cm.state.EditorState.create({
          doc,
          extensions,
        });
        new cm.view.EditorView({ state: edState, parent: el });
      });
      bindPreviewScrollDelegation(root);
    }).catch(() => {
      // CodeMirror unavailable (bundle missing and CDN unreachable): degrade to plain text.
      els.forEach(el => {
        const id = el.getAttribute("data-cm-id");
        const payload = _cmData[id];
        if (payload == null) return;
        delete _cmData[id];
        const doc = typeof payload === "string" ? payload : payload.doc;
        const pre = document.createElement("pre");
        pre.style.cssText = "white-space:pre-wrap;margin:0;font-family:var(--font-mono);font-size:12px";
        pre.textContent = doc == null ? "" : String(doc);
        el.appendChild(pre);
      });
      bindPreviewScrollDelegation(root);
    });
  }

  function nestDottedKeys(obj) {
    if (!obj || typeof obj !== "object" || Array.isArray(obj)) return obj;
    const hasDots = Object.keys(obj).some(k => k.includes("."));
    if (!hasDots) return obj;
    const root = {};
    for (const [key, val] of Object.entries(obj)) {
      const parts = key.split(".");
      let cur = root;
      for (let i = 0; i < parts.length - 1; i++) {
        if (!(parts[i] in cur) || typeof cur[parts[i]] !== "object" || cur[parts[i]] === null) {
          cur[parts[i]] = {};
        }
        cur = cur[parts[i]];
      }
      cur[parts[parts.length - 1]] = val;
    }
    // Convert objects with all-numeric keys to arrays (recursive)
    return objectsToArrays(root);
  }

  function objectsToArrays(obj) {
    if (!obj || typeof obj !== "object") return obj;
    if (Array.isArray(obj)) return obj.map(objectsToArrays);
    const keys = Object.keys(obj);
    const allNumeric = keys.length > 0 && keys.every(k => /^\d+$/.test(k));
    if (allNumeric) {
      const arr = [];
      keys.sort((a, b) => Number(a) - Number(b)).forEach(k => { arr[Number(k)] = objectsToArrays(obj[k]); });
      return arr;
    }
    const out = {};
    for (const [k, v] of Object.entries(obj)) out[k] = objectsToArrays(v);
    return out;
  }

  function deepParseJson(obj) {
    if (typeof obj === "string") {
      const t = obj.trim();
      if ((t[0] === "{" && t[t.length - 1] === "}") || (t[0] === "[" && t[t.length - 1] === "]")) {
        try { return deepParseJson(JSON.parse(t)); } catch (_) {}
      }
      return obj;
    }
    if (Array.isArray(obj)) return obj.map(deepParseJson);
    if (obj && typeof obj === "object") {
      const out = {};
      for (const [k, v] of Object.entries(obj)) out[k] = deepParseJson(v);
      return out;
    }
    return obj;
  }

  function renderJsonBlock(value, className) {
    let parsed;
    try {
      parsed = typeof value === "string" ? JSON.parse(value) : value;
    } catch (_) {
      return renderTextPlaceholder(String(value), className);
    }
    parsed = deepParseJson(parsed);
    if (typeof parsed === "string") {
      return renderTextPlaceholder(parsed, className);
    }
    if (parsed == null || typeof parsed !== "object") {
      return renderTextPlaceholder(String(parsed), className);
    }
    if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
      parsed = nestDottedKeys(parsed);
    }
    return renderJsonPlaceholder(JSON.stringify(parsed, null, 2), className);
  }

  function renderMetrics(span) {
    const a = span.attributes || {};
    const raw = a["output.value"];
    if (!raw) return `<div class="tv-empty-d">No metrics data</div>`;
    let parsed;
    try { parsed = deepParseJson(typeof raw === "string" ? JSON.parse(raw) : raw); } catch (_) { return renderJsonBlock(raw); }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return renderJsonBlock(raw);

    const entries = Object.entries(parsed);
    if (!entries.length) return `<div class="tv-empty-d">No metrics</div>`;

    let id = 0;
    return `<div class="tv-metrics">${entries.map(([name, data]) => {
      const metaId = `tv-metric-${++id}`;
      const actions = actionGroup([
        copyBtn(() => JSON.stringify({ [name]: data }, null, 2), "Copy metric"),
        expandBtn({
          title: name.replace(/_/g, " "),
          render: () => renderMetricCard(name, data, `tv-metric-modal-${id}`, ""),
        }, "Expand metric"),
      ], "tv-card-actions");
      return renderMetricCard(name, data, metaId, actions);
    }).join("")}</div>`;
  }

  function renderScores(scores) {
    if (!scores.length) return `<div class="tv-empty-d">No scores</div>`;
    return `<div class="tv-scores">${scores.map(sc => {
      const actions = actionGroup([
        copyBtn(() => JSON.stringify(sc, null, 2), "Copy score"),
        expandBtn({
          title: sc.name || "Score",
          render: () => renderScoreCard(sc, ""),
        }, "Expand score"),
      ], "tv-card-actions");
      return renderScoreCard(sc, actions);
    }).join("")}</div>`;
  }

  function renderRaw(span) {
    const allAttrs = span.attributes || {};
    const events = span.events || [];
    const metaObj = { span_id: span.span_id, parent_span_id: span.parent_span_id, trace_id: span.trace_id, kind: span.kind, status: span.status, duration_ms: span.duration_ms };
    let html = renderLabeledSection("Attributes", renderJsonBlock(allAttrs, "tv-json-preview tv-json-preview-output"), "", actionGroup([
      copyBtn(() => JSON.stringify(allAttrs, null, 2), "Copy attributes"),
      expandBtn({
        title: "Attributes",
        render: () => renderExpandedContent(renderJsonBlock(allAttrs)),
      }, "Expand attributes"),
    ]));
    if (events.length) {
      html += renderLabeledSection("Events", renderJsonBlock(events, "tv-json-preview tv-json-preview-output"), "", actionGroup([
        copyBtn(() => JSON.stringify(events, null, 2), "Copy events"),
        expandBtn({
          title: "Events",
          render: () => renderExpandedContent(renderJsonBlock(events)),
        }, "Expand events"),
      ]));
    }
    html += renderLabeledSection("Span Metadata", renderJsonBlock(metaObj, "tv-json-preview"), "", actionGroup([
      copyBtn(() => JSON.stringify(metaObj, null, 2), "Copy metadata"),
      expandBtn({
        title: "Span Metadata",
        render: () => renderExpandedContent(renderJsonBlock(metaObj)),
      }, "Expand metadata"),
    ]));
    return html;
  }

  /* ── shell (drawer container) ── */
  function ensureShell() {
    if (S.shell) return;
    const el = document.createElement("div");
    el.className = "tv-shell";
    el.innerHTML = `
      <div class="tv-backdrop" data-trace-close="1"></div>
      <aside class="tv-drawer" role="dialog" aria-modal="true" aria-label="Trace viewer">
        <div class="tv-header">
          <div class="tv-header-left">
            <div class="tv-eyebrow">TRACE</div>
            <h3 class="tv-title">Trace</h3>
            <div class="tv-attempts" style="display:none"></div>
            <div class="tv-meta"></div>
            <div class="tv-warning" style="display:none"></div>
          </div>
          <div class="tv-header-right">
            <button type="button" class="tv-close qym-icon-action" data-trace-close="1" aria-label="Close">
              <svg viewBox="0 0 16 16" width="16" height="16"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
            </button>
          </div>
        </div>
        <div class="tv-body">
          <div class="tv-list-pane">
            <div class="tv-list-toolbar">
              <div class="tv-search-wrap">
                <input type="text" class="tv-search" placeholder="Filter spans..." aria-label="Search spans">
                <span class="tv-search-icon"><svg viewBox="0 0 16 16" width="14" height="14"><circle cx="7" cy="7" r="4.5" stroke="currentColor" stroke-width="1.5" fill="none"/><path d="m10.5 10.5 3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></span>
              </div>
              <button type="button" class="tv-header-btn tv-icon-btn qym-icon-action" data-tree-toggle-mode="expand" title="Expand spans" aria-label="Expand spans">${EXPAND_ALL_ICON}</button>
            </div>
            <div class="tv-list"></div>
          </div>
          <div class="tv-divider"></div>
          <div class="tv-detail-pane">
            <div class="tv-detail"></div>
          </div>
        </div>
      </aside>
      <div class="tv-modal-layer" aria-hidden="true">
        <div class="tv-modal-backdrop" data-trace-modal-close="1"></div>
        <section class="tv-modal" role="dialog" aria-modal="true" aria-label="Expanded trace content">
          <div class="tv-modal-header">
            <div class="tv-modal-title-wrap">
              <div class="tv-modal-eyebrow">EXPANDED</div>
              <div class="tv-modal-title">Expanded Trace Content</div>
            </div>
            <button type="button" class="tv-close qym-icon-action" data-trace-modal-close="1" aria-label="Close expanded view">
              <svg viewBox="0 0 16 16" width="16" height="16"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
            </button>
          </div>
          <div class="tv-modal-body"></div>
        </section>
      </div>
    `;
    document.body.appendChild(el);
    S.shell = el;
    S.el.title = el.querySelector(".tv-title");
    S.el.attempts = el.querySelector(".tv-attempts");
    S.el.meta = el.querySelector(".tv-meta");
    S.el.warning = el.querySelector(".tv-warning");
    S.el.listPane = el.querySelector(".tv-list-pane");
    S.el.list = el.querySelector(".tv-list");
    S.el.detail = el.querySelector(".tv-detail");
    S.el.search = el.querySelector(".tv-search");
    S.el.treeToggle = el.querySelector(".tv-header-btn");
    S.el.modalLayer = el.querySelector(".tv-modal-layer");
    S.el.modalTitle = el.querySelector(".tv-modal-title");
    S.el.modalBody = el.querySelector(".tv-modal-body");

    // Search input
    S.el.search.addEventListener("input", () => {
      S.search = S.el.search.value;
      renderTree();
    });

    // Resizable divider
    const divider = el.querySelector(".tv-divider");
    const body = el.querySelector(".tv-body");
    divider.addEventListener("mousedown", (e) => {
      e.preventDefault();
      divider.classList.add("active");
      const startX = e.clientX;
      const startW = S.el.listPane.getBoundingClientRect().width;
      const bodyW = body.getBoundingClientRect().width;
      const onMove = (ev) => {
        const dx = ev.clientX - startX;
        const newW = Math.max(200, Math.min(bodyW - 200, startW + dx));
        S.el.listPane.style.flex = `0 0 ${newW}px`;
      };
      const onUp = () => {
        divider.classList.remove("active");
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  }

  /* ── open / close ── */
  function openDrawer() { ensureShell(); S.shell.classList.add("open"); document.body.classList.add("tv-open"); }
  function closeExpandModal() {
    if (!S.el.modalLayer) return;
    S.el.modalLayer.classList.remove("open");
    S.el.modalLayer.setAttribute("aria-hidden", "true");
    if (S.el.modalBody) S.el.modalBody.innerHTML = "";
  }
  function openExpandModal(payload) {
    ensureShell();
    if (!payload) return;
    S.el.modalTitle.textContent = payload.title || "Expanded Trace Content";
    S.el.modalBody.innerHTML = payload.render ? payload.render() : "";
    S.el.modalLayer.classList.add("open");
    S.el.modalLayer.setAttribute("aria-hidden", "false");
    mountJsonFormatters(S.el.modalBody);
  }
  function closeDrawer() {
    if (!S.shell) return;
    closeExpandModal();
    S.shell.classList.remove("open");
    document.body.classList.remove("tv-open");
    _clearTraceUrl();
  }

  async function fetchTrace(meta) {
    if (!meta.endpoint) throw new Error("Missing endpoint");
    if (cache.has(meta.endpoint)) return cache.get(meta.endpoint);
    const res = await fetch(meta.endpoint, { credentials: "same-origin" });
    if (!res.ok) throw new Error(await res.text() || `HTTP ${res.status}`);
    const data = await res.json();
    cache.set(meta.endpoint, data);
    return data;
  }

  function _pushTraceUrl(meta) {
    if (S.exportMode) return;
    try {
      const url = new URL(window.location);
      // Use itemId extracted from endpoint: .../items/{itemId}/trace
      const m = (meta.endpoint || "").match(/\/items\/([^/]+)\/trace/);
      if (m) url.searchParams.set("trace", m[1]);
      history.replaceState(null, "", url);
    } catch (_) {}
  }

  function _clearTraceUrl() {
    try {
      const url = new URL(window.location);
      url.searchParams.delete("trace");
      history.replaceState(null, "", url);
    } catch (_) {}
  }

  async function open(meta) {
    if (S.exportMode) return;
    S.meta = meta;
    S.data = null;
    S.selected = null;
    S.selectedAttempt = null;
    S.expanded = new Set();
    S.search = "";
    S.activeTab = null;
    openDrawer();
    S.el.search.value = "";
    _pushTraceUrl(meta);

    // Loading state
    S.el.title.textContent = meta.itemLabel || "Trace";
    S.el.meta.innerHTML = `<span class="tv-chip qym-tag">Loading...</span>`;
    S.el.list.innerHTML = `<div class="tv-loading">Loading trace...</div>`;
    S.el.detail.innerHTML = "";
    updateTreeToggleButton();

    try {
      const data = await fetchTrace(meta);
      S.data = normalizeAttempts(data);

      const currentAttempt = currentAttemptData();
      S.selectedAttempt = currentAttempt?.attempt_number
        || S.data?.attempts?.find(a => a.is_last_attempt)?.attempt_number
        || S.data?.attempts?.[S.data.attempts.length - 1]?.attempt_number
        || 1;

      // Default to a fully expanded tree.
      S.expanded = new Set(allExpandableSpanIds());

      // Default selection is the root span.
      S.selected = currentTree()?.roots?.[0]?.span_id || null;

      renderHeader(meta, S.data);
      renderTree();
    } catch (err) {
      if (S.el.attempts) {
        S.el.attempts.innerHTML = "";
        S.el.attempts.style.display = "none";
      }
      renderHeader(meta, { item: { trace_id: meta.traceId, trace_url: meta.traceUrl }, summary: {}, spans: [] });
      S.el.list.innerHTML = `<div class="tv-empty"><div class="tv-empty-t">Failed to load</div><div class="tv-empty-d">${esc(err.message)}</div></div>`;
    }
  }

  /* ── keyboard navigation ── */
  function getVisibleSpanIds() {
    if (!S.el.list) return [];
    return Array.from(S.el.list.querySelectorAll("[data-span]")).map(el => el.getAttribute("data-span"));
  }

  function navigate(dir) {
    const ids = getVisibleSpanIds();
    if (!ids.length) return;
    const idx = ids.indexOf(S.selected);
    const next = idx + dir;
    if (next >= 0 && next < ids.length) {
      S.selected = ids[next];
      S.activeTab = null;
      renderTree();
      // Scroll into view
      const row = S.el.list.querySelector(`[data-span="${S.selected}"]`);
      if (row) row.scrollIntoView({ block: "nearest" });
    }
  }

  function toggleExpand() {
    if (!S.selected) return;
    if (S.expanded.has(S.selected)) S.expanded.delete(S.selected);
    else S.expanded.add(S.selected);
    renderTree();
  }

  /* ── event handling ── */
  function handleClick(e) {
    if (e.target.closest("[data-trace-modal-close]")) { e.preventDefault(); closeExpandModal(); return; }
    if (e.target.closest("[data-trace-close]")) { e.preventDefault(); closeDrawer(); return; }
    if (e.target.closest("[data-copy-id]")) {
      e.preventDefault(); e.stopPropagation();
      const btn = e.target.closest("[data-copy-id]");
      const id = btn.getAttribute("data-copy-id");
      const raw = _copyData[id];
      const text = typeof raw === "function" ? raw() : String(raw || "");
      if (text && navigator.clipboard) {
        navigator.clipboard.writeText(text).catch(()=>{});
        btn.innerHTML = CHECK_ICON;
        btn.classList.add("copied");
        setTimeout(() => {
          btn.innerHTML = COPY_ICON;
          btn.classList.remove("copied");
        }, 1500);
      }
      return;
    }
    if (e.target.closest("[data-expand-id]")) {
      e.preventDefault(); e.stopPropagation();
      const btn = e.target.closest("[data-expand-id]");
      openExpandModal(_expandData[btn.getAttribute("data-expand-id")]);
      return;
    }
    if (e.target.closest("[data-tree-toggle-mode]")) {
      e.preventDefault();
      const btn = e.target.closest("[data-tree-toggle-mode]");
      setTreeExpansion(btn.getAttribute("data-tree-toggle-mode") === "expand");
      return;
    }
    if (e.target.closest("[data-trace-copy]")) {
      e.preventDefault();
      const v = e.target.closest("[data-trace-copy]").getAttribute("data-trace-copy");
      if (v && navigator.clipboard) {
        navigator.clipboard.writeText(v).catch(()=>{});
        const btn = e.target.closest("[data-trace-copy]");
        const orig = btn.textContent;
        btn.textContent = "Copied!";
        setTimeout(() => { btn.textContent = orig; }, 1200);
      }
      return;
    }
    if (e.target.closest("[data-attempt]")) {
      e.preventDefault();
      const attemptNumber = Number(e.target.closest("[data-attempt]").getAttribute("data-attempt"));
      if (!Number.isFinite(attemptNumber) || attemptNumber === Number(S.selectedAttempt || 0)) return;
      S.selectedAttempt = attemptNumber;
      S.expanded = new Set(allExpandableSpanIds());
      S.selected = currentTree()?.roots?.[0]?.span_id || null;
      S.activeTab = null;
      renderHeader(S.meta || {}, S.data || {});
      renderTree();
      return;
    }
    // Metric card expand/collapse
    if (e.target.closest("[data-metric-toggle]")) {
      e.preventDefault();
      const id = e.target.closest("[data-metric-toggle]").getAttribute("data-metric-toggle");
      const el = document.getElementById(id);
      if (el) {
        const open = el.style.display !== "none";
        el.style.display = open ? "none" : "";
        e.target.closest(".tv-metric-card").classList.toggle("expanded", !open);
      }
      return;
    }
    if (e.target.closest(".trace-drawer-btn")) { e.preventDefault(); openFromButton(e.target.closest(".trace-drawer-btn")); return; }
    if (e.target.closest("[data-toggle]")) {
      e.preventDefault(); e.stopPropagation();
      const id = e.target.closest("[data-toggle]").getAttribute("data-toggle");
      if (S.expanded.has(id)) S.expanded.delete(id); else S.expanded.add(id);
      renderTree();
      return;
    }
    if (e.target.closest("[data-tab]")) {
      e.preventDefault();
      S.activeTab = e.target.closest("[data-tab]").getAttribute("data-tab");
      renderDetail();
      S.el.detail.querySelector(`#tv-detail-tab-${S.activeTab}`)?.focus({ preventScroll: true });
      return;
    }
    if (e.target.closest("[data-span]")) {
      e.preventDefault();
      S.selected = e.target.closest("[data-span]").getAttribute("data-span");
      S.activeTab = null;
      renderTree();
      return;
    }
  }

  function handleKey(e) {
    if (!S.shell || !S.shell.classList.contains("open")) return;
    if (e.key === "Escape") {
      if (S.el.modalLayer && S.el.modalLayer.classList.contains("open")) closeExpandModal();
      else if (S.el.search === document.activeElement && S.search) { S.search = ""; S.el.search.value = ""; renderTree(); }
      else closeDrawer();
      e.preventDefault(); return;
    }
    // Don't handle keys if search is focused (except Escape)
    if (S.el.search === document.activeElement) return;
    if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); navigate(1); }
    else if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); navigate(-1); }
    else if (e.key === "Enter" || e.key === "ArrowRight") { e.preventDefault(); if (S.selected && !S.expanded.has(S.selected)) { S.expanded.add(S.selected); renderTree(); } }
    else if (e.key === "ArrowLeft") { e.preventDefault(); if (S.selected && S.expanded.has(S.selected)) { S.expanded.delete(S.selected); renderTree(); } }
    else if (e.key === "/") { e.preventDefault(); S.el.search.focus(); }
  }

  function openFromButton(btn) {
    open({
      endpoint: btn.getAttribute("data-trace-endpoint") || "",
      itemLabel: btn.getAttribute("data-trace-item-label") || btn.getAttribute("data-trace-title") || "Trace",
      traceId: btn.getAttribute("data-trace-id") || "",
      traceUrl: btn.getAttribute("data-trace-url") || "",
    });
  }

  /* ── init ── */
  function restoreFromUrl() {
    // Called by the host page after items have rendered.
    // Finds the trace button for the item ID in ?trace= and opens it.
    try {
      const params = new URLSearchParams(window.location.search);
      const itemId = params.get("trace");
      if (!itemId) return;
      // Find the trace button whose endpoint contains this item ID
      const btn = document.querySelector(
        `.trace-drawer-btn[data-trace-endpoint*="/items/${CSS.escape(itemId)}/trace"]`
      );
      if (btn) openFromButton(btn);
    } catch (_) {}
  }

  function init(opts) {
    S.exportMode = !!(opts && opts.exportMode);
    ensureShell();
    if (S.ready) return;
    document.addEventListener("click", handleClick);
    document.addEventListener("keydown", handleKey);
    S.ready = true;
  }

  window.QymTraceViewer = { init, open, openFromButton, close: closeDrawer, restoreFromUrl };
})();
