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
    search: "",
    activeTab: null,
    viewMode: "formatted",  // "formatted" (structured key-value) or "raw" (syntax-highlighted JSON)
  };

  /* ── icons (inline SVG, 16×16) ── */
  const ICONS = {
    LLM:       `<svg viewBox="0 0 16 16" fill="none"><path d="M8 1.5a2 2 0 0 1 2 2v1a2 2 0 0 1-4 0v-1a2 2 0 0 1 2-2Zm-3.5 6A1.5 1.5 0 0 1 6 6h4a1.5 1.5 0 0 1 1.5 1.5v4a3.5 3.5 0 0 1-7 0v-4Z" fill="currentColor" opacity=".85"/></svg>`,
    TOOL:      `<svg viewBox="0 0 16 16" fill="none"><path d="M6.5 1a.5.5 0 0 1 .5.5V3h2V1.5a.5.5 0 0 1 1 0V3h1.5A1.5 1.5 0 0 1 13 4.5V6h1.5a.5.5 0 0 1 0 1H13v2h1.5a.5.5 0 0 1 0 1H13v1.5a1.5 1.5 0 0 1-1.5 1.5H10v1.5a.5.5 0 0 1-1 0V13H7v1.5a.5.5 0 0 1-1 0V13H4.5A1.5 1.5 0 0 1 3 11.5V10H1.5a.5.5 0 0 1 0-1H3V7H1.5a.5.5 0 0 1 0-1H3V4.5A1.5 1.5 0 0 1 4.5 3H6V1.5a.5.5 0 0 1 .5-.5ZM5 5.5v5a.5.5 0 0 0 .5.5h5a.5.5 0 0 0 .5-.5v-5a.5.5 0 0 0-.5-.5h-5a.5.5 0 0 0-.5.5Z" fill="currentColor" opacity=".85"/></svg>`,
    AGENT:     `<svg viewBox="0 0 16 16" fill="none"><circle cx="8" cy="5" r="3" fill="currentColor" opacity=".7"/><path d="M3 13.5C3 11 5.2 9 8 9s5 2 5 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" fill="none"/></svg>`,
    CHAIN:     `<svg viewBox="0 0 16 16" fill="none"><path d="M6.354 3.818a3 3 0 0 1 4.243 0l1.585 1.586a3 3 0 0 1 0 4.243l-.707.707a1 1 0 0 1-1.414-1.414l.707-.707a1 1 0 0 0 0-1.415L9.183 5.233a1 1 0 0 0-1.415 0l-.707.707A1 1 0 0 1 5.647 4.525l.707-.707Zm-2.536 3.84a1 1 0 0 1 0 1.415l-1.586 1.585a1 1 0 0 0 0 1.414l1.586 1.586a1 1 0 0 0 1.414 0l.707-.707a1 1 0 0 1 1.414 1.414l-.707.707a3 3 0 0 1-4.242 0L.818 11.487a3 3 0 0 1 0-4.243l1.586-1.585a1 1 0 0 1 1.414 0Z" fill="currentColor" opacity=".85"/></svg>`,
    EVALUATOR: `<svg viewBox="0 0 16 16" fill="none"><path d="M8 1l2.35 4.76 5.25.76-3.8 3.7.9 5.24L8 13.27l-4.7 2.5.9-5.25-3.8-3.7 5.25-.76Z" fill="currentColor" opacity=".75"/></svg>`,
    RETRIEVER: `<svg viewBox="0 0 16 16" fill="none"><circle cx="7" cy="7" r="4.5" stroke="currentColor" stroke-width="1.5" fill="none"/><path d="m10.5 10.5 3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,
    EMBED:     `<svg viewBox="0 0 16 16" fill="none"><rect x="2" y="2" width="5" height="5" rx="1" fill="currentColor" opacity=".6"/><rect x="9" y="2" width="5" height="5" rx="1" fill="currentColor" opacity=".4"/><rect x="2" y="9" width="5" height="5" rx="1" fill="currentColor" opacity=".4"/><rect x="9" y="9" width="5" height="5" rx="1" fill="currentColor" opacity=".6"/></svg>`,
    DEFAULT:   `<svg viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="3" fill="currentColor" opacity=".5"/></svg>`,
  };

  const KIND_COLORS = {
    LLM: "#f472b6", TOOL: "#fbbf24", AGENT: "#34d399", CHAIN: "#60a5fa",
    EVALUATOR: "#a78bfa", RETRIEVER: "#38bdf8", EMBED: "#94a3b8", DEFAULT: "#6b7280",
  };

  /* ── helpers ── */
  function esc(v) {
    return String(v == null ? "" : v).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }

  function fmtDur(ms) {
    if (ms == null) return "—";
    const n = Number(ms);
    if (!Number.isFinite(n)) return "—";
    if (n >= 1000) return (n/1000).toFixed(n>=10000?1:2) + "s";
    if (n >= 10) return n.toFixed(1) + "ms";
    if (n >= 1) return n.toFixed(2) + "ms";
    return n.toFixed(3) + "ms";
  }

  function fmtTokens(n) {
    if (n == null) return null;
    const num = Number(n);
    if (!Number.isFinite(num)) return null;
    if (num >= 1000) return (num/1000).toFixed(1) + "k";
    return String(num);
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

  function statusCls(s) {
    const u = String(s||"").toUpperCase();
    return u === "ERROR" ? "error" : u === "OK" ? "ok" : "unset";
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
    function walk(n, d) { n._depth = d; n._children.sort(sortFn); n._children.forEach(c => walk(c, d+1)); }
    roots.sort(sortFn);
    roots.forEach(r => walk(r, 0));
    return { roots, byId, nodes };
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
      const content = attrs[`${prefix}.${i}.message.content`] || "";
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
      msgs.push({ role, content, toolCalls, toolCallId });
    }
    return msgs;
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

  /* ── error path expand ── */
  function autoExpandErrors(tree) {
    const firstError = tree.nodes.find(n => statusCls(n.status) === "error");
    if (!firstError) return null;
    // expand all ancestors
    let cur = firstError;
    while (cur) {
      S.expanded.add(cur.span_id);
      cur = cur.parent_span_id ? tree.byId.get(cur.parent_span_id) : null;
    }
    return firstError.span_id;
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
    const sum = data?.summary || {};
    const item = data?.item || {};
    const tree = data?._tree;
    const stats = tree ? aggregateStats(tree) : { totalTokens: 0, totalCost: 0 };

    S.el.title.textContent = meta.itemLabel || item.item_id || "Trace";

    // Score pills from root span events
    const rootSpan = tree?.roots?.[0];
    const scores = rootSpan ? extractScores(rootSpan) : [];

    let chips = `<span class="tv-chip">${sum.span_count||0} spans</span>`;
    chips += `<span class="tv-chip">${esc(fmtDur(sum.duration_ms))}</span>`;
    if (stats.totalTokens > 0) chips += `<span class="tv-chip tv-chip-tokens">${fmtTokens(stats.totalTokens)} tokens</span>`;
    const costStr = fmtCost(stats.totalCost);
    if (costStr) chips += `<span class="tv-chip">${costStr}</span>`;
    if (sum.error_count) chips += `<span class="tv-chip tv-chip-error">${sum.error_count} error${sum.error_count>1?"s":""}</span>`;
    scores.forEach(sc => {
      const v = typeof sc.value === "number" ? sc.value.toFixed(2) : sc.value;
      chips += `<span class="tv-chip tv-chip-score">${esc(sc.name)}: ${esc(v)}</span>`;
    });
    if (item.trace_id) chips += `<button type="button" class="tv-chip tv-chip-copy" data-trace-copy="${esc(item.trace_id)}" title="Copy Trace ID">ID</button>`;

    S.el.meta.innerHTML = chips;

    // External link
    const url = meta.traceUrl || item.trace_url;
    if (url) { S.el.link.href = url; S.el.link.style.display = ""; }
    else { S.el.link.removeAttribute("href"); S.el.link.style.display = "none"; }

    // Warning
    if (sum.has_orphans) { S.el.warning.textContent = `${sum.orphan_count} orphan span${sum.orphan_count===1?"":"s"}`; S.el.warning.style.display = ""; }
    else { S.el.warning.style.display = "none"; }
  }

  /* ── rendering: span tree ── */
  function renderTree() {
    const tree = S.data?._tree;
    if (!tree || !tree.nodes.length) {
      S.el.list.innerHTML = `<div class="tv-empty"><div class="tv-empty-t">No trace data</div><div class="tv-empty-d">This item may not have tracing enabled.</div></div>`;
      S.el.detail.innerHTML = "";
      return;
    }
    applySearch(tree);
    const bounds = computeBounds(S.data);
    const rows = [];

    function visit(node) {
      if (!node._visible) return;
      const kids = node._children || [];
      const exp = S.expanded.has(node.span_id);
      const sel = S.selected === node.span_id;
      const kind = spanKind(node);
      const model = spanModel(node);
      const tokens = spanTokens(node);
      const color = KIND_COLORS[kind] || KIND_COLORS.DEFAULT;

      // waterfall
      let left = 0, width = 100;
      if (bounds.start != null && node.start_time_ns != null) left = ((Number(node.start_time_ns)-Number(bounds.start))/bounds.total)*100;
      if (bounds.start != null && node.end_time_ns != null && node.start_time_ns != null) width = ((Number(node.end_time_ns)-Number(node.start_time_ns))/bounds.total)*100;
      width = Math.max(width, 0.75);

      const visibleKids = kids.filter(c => c._visible);
      const toggleHtml = visibleKids.length
        ? `<span class="tv-toggle ${exp?"open":""}" data-toggle="${esc(node.span_id)}"><svg viewBox="0 0 10 10" width="10" height="10"><path d="M3 2l4 3-4 3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></span>`
        : `<span class="tv-toggle leaf"></span>`;

      // Inline meta for LLM spans
      let inlineMeta = "";
      if (kind === "LLM" && model) inlineMeta += `<span class="tv-inline-model">${esc(model)}</span>`;
      if (kind === "LLM" && tokens) inlineMeta += `<span class="tv-inline-tokens">${fmtTokens(tokens)}</span>`;

      const stCls = statusCls(node.status);

      rows.push(
        `<button type="button" class="tv-row ${sel?"sel":""} ${stCls==="error"?"row-err":""}" data-span="${esc(node.span_id)}" style="--d:${node._depth}">` +
          toggleHtml +
          `<span class="tv-icon" style="color:${color}">${ICONS[kind]||ICONS.DEFAULT}</span>` +
          `<span class="tv-name">${esc(node.name||"(unnamed)")}</span>` +
          inlineMeta +
          `<span class="tv-dur">${esc(fmtDur(node.duration_ms))}</span>` +
          `<span class="tv-wf"><span class="tv-wf-track"></span><span class="tv-wf-bar ${stCls}" style="left:${left}%;width:${Math.min(width,100)}%"></span></span>` +
        `</button>`
      );
      if (exp) visibleKids.forEach(visit);
    }
    tree.roots.forEach(visit);
    S.el.list.innerHTML = rows.join("");
    renderDetail();
  }

  /* ── rendering: detail panel ── */
  function renderDetail() {
    const tree = S.data?._tree;
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
    const inputMsgs = extractMessages(attrs, "llm.input_messages");
    const outputMsgs = extractMessages(attrs, "llm.output_messages");
    const reasoning = extractReasoning(span);
    const scores = extractScores(span);

    if (kind === "LLM") {
      if (inputMsgs.length || outputMsgs.length) tabs.push({ id: "messages", label: "Messages" });
      if (reasoning) tabs.push({ id: "reasoning", label: "Reasoning" });
      tabs.push({ id: "params", label: "Params" });
    } else if (kind === "TOOL") {
      tabs.push({ id: "tool-io", label: "Input / Output" });
    } else {
      if (attrs["input.value"]) tabs.push({ id: "io", label: "Input / Output" });
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
    if (model) header += `<span>${esc(model)}</span><span class="tv-dot"></span>`;
    header += `<span>${esc(fmtDur(span.duration_ms))}</span>`;
    if (tokens) header += `<span class="tv-dot"></span><span>${fmtTokens(tokens)} tokens</span>`;
    const costStr = fmtCost(cost);
    if (costStr) header += `<span class="tv-dot"></span><span>${costStr}</span>`;
    header += `</div></div>`;
    header += `<span class="tv-chip tv-chip-status-${stCls}">${esc(String(span.status||"UNSET").toUpperCase())}</span>`;
    header += `</div>`;

    // Tabs + view mode toggle
    let tabBar = `<div class="tv-tabs">`;
    tabs.forEach(t => {
      tabBar += `<button type="button" class="tv-tab ${S.activeTab===t.id?"active":""}" data-tab="${t.id}">${esc(t.label)}</button>`;
    });
    tabBar += `<span class="tv-tabs-spacer"></span>`;
    tabBar += `<span class="tv-view-toggle">`;
    tabBar += `<button type="button" class="tv-view-btn ${S.viewMode==="formatted"?"active":""}" data-viewmode="formatted" title="Structured view">Formatted</button>`;
    tabBar += `<button type="button" class="tv-view-btn ${S.viewMode==="raw"?"active":""}" data-viewmode="raw" title="Raw JSON">Raw</button>`;
    tabBar += `</span>`;
    tabBar += `</div>`;

    // Tab content
    let content = `<div class="tv-tab-content">`;
    if (S.activeTab === "messages") content += renderMessages(inputMsgs.concat(outputMsgs));
    else if (S.activeTab === "reasoning") content += renderReasoning(reasoning);
    else if (S.activeTab === "params") content += renderParams(span);
    else if (S.activeTab === "tool-io") content += renderToolIO(span);
    else if (S.activeTab === "io") content += renderIO(span);
    else if (S.activeTab === "scores") content += renderScores(scores);
    else if (S.activeTab === "raw") content += renderRaw(span);
    content += `</div>`;

    S.el.detail.innerHTML = header + tabBar + content;
  }

  /* ── tab renderers ── */
  function renderMessages(msgs) {
    if (!msgs.length) return `<div class="tv-empty-d">No messages</div>`;
    return msgs.map(m => {
      const role = String(m.role).toLowerCase();
      let bubble = `<div class="tv-msg tv-msg-${role}">`;
      bubble += `<div class="tv-msg-role">${esc(role)}${m.toolCallId ? ` <span class="tv-msg-tcid">${esc(m.toolCallId)}</span>` : ""}</div>`;
      if (m.content) {
        const text = String(m.content);
        const trimmed = text.trim();
        // If content looks like JSON, render through the view mode system
        if ((trimmed.startsWith("{") && trimmed.endsWith("}")) || (trimmed.startsWith("[") && trimmed.endsWith("]"))) {
          try { JSON.parse(trimmed); bubble += `<div class="tv-msg-body">${renderJsonBlock(text)}</div>`; }
          catch (_) { bubble += `<div class="tv-msg-body">${esc(text)}</div>`; }
        } else if (text.includes("```")) {
          bubble += `<div class="tv-msg-body">${renderMarkdownLite(text)}</div>`;
        } else {
          bubble += `<div class="tv-msg-body">${esc(text)}</div>`;
        }
      }
      if (m.toolCalls && m.toolCalls.length) {
        m.toolCalls.forEach(tc => {
          bubble += `<div class="tv-toolcall">`;
          bubble += `<div class="tv-toolcall-name">${esc(tc.name)}</div>`;
          if (tc.arguments) {
            bubble += renderJsonBlock(tc.arguments);
          }
          bubble += `</div>`;
        });
      }
      bubble += `</div>`;
      return bubble;
    }).join("");
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

  function renderReasoning(text) {
    if (!text) return `<div class="tv-empty-d">No reasoning content</div>`;
    return `<div class="tv-reasoning">${esc(text)}</div>`;
  }

  function renderParams(span) {
    const a = span.attributes || {};
    const rows = [];
    function add(label, value) { if (value != null && value !== "" && value !== 0) rows.push([label, value]); }
    add("Model", spanModel(span));
    add("Prompt Tokens", a["llm.token_count.prompt"] || a["gen_ai.usage.prompt_tokens"]);
    add("Completion Tokens", a["llm.token_count.completion"] || a["gen_ai.usage.completion_tokens"]);
    add("Reasoning Tokens", a["llm.token_count.completion_details.reasoning"]);
    add("Total Tokens", spanTokens(span));
    add("Cost", fmtCost(spanCost(span)));
    add("Duration", fmtDur(span.duration_ms));
    // Invocation parameters
    try {
      const ip = a["llm.invocation_parameters"];
      if (ip) {
        const parsed = typeof ip === "string" ? JSON.parse(ip) : ip;
        Object.entries(parsed).forEach(([k,v]) => { if (k !== "model") add(k, v); });
      }
    } catch (_) {}
    add("Finish Reason", a["gen_ai.completion.0.finish_reason"]);
    add("Span ID", span.span_id);
    if (!rows.length) return `<div class="tv-empty-d">No parameters</div>`;
    return `<div class="tv-params">${rows.map(([k,v]) => `<div class="tv-param"><span class="tv-param-k">${esc(k)}</span><span class="tv-param-v">${esc(String(v))}</span></div>`).join("")}</div>`;
  }

  function renderToolIO(span) {
    const a = span.attributes || {};
    const toolName = a["tool.name"] || span.name || "tool";
    const inp = a["input.value"];
    const out = a["output.value"];
    let html = "";

    // Tool call arguments — rendered as an assistant tool_call bubble
    if (inp) {
      html += `<div class="tv-msg tv-msg-assistant">`;
      html += `<div class="tv-msg-role">tool call</div>`;
      html += `<div class="tv-toolcall">`;
      html += `<div class="tv-toolcall-name">${esc(toolName)}</div>`;
      html += renderJsonBlock(inp);
      html += `</div></div>`;
    }

    // Tool result — rendered as a tool result bubble
    if (out) {
      html += `<div class="tv-msg tv-msg-tool">`;
      html += `<div class="tv-msg-role">result</div>`;
      html += `<div class="tv-msg-body">${renderJsonBlock(out)}</div>`;
      html += `</div>`;
    }

    if (!inp && !out) html = `<div class="tv-empty-d">No input/output data</div>`;
    return html;
  }

  function renderIO(span) {
    const a = span.attributes || {};
    let html = "";
    const inp = a["input.value"];
    const out = a["output.value"];
    if (inp) {
      html += `<div class="tv-io-section"><div class="tv-io-label tv-io-label-input">Input</div>`;
      html += renderJsonBlock(inp);
      html += `</div>`;
    }
    if (out) {
      html += `<div class="tv-io-section"><div class="tv-io-label tv-io-label-output">Output</div>`;
      html += renderJsonBlock(out);
      html += `</div>`;
    }
    if (!inp && !out) html = `<div class="tv-empty-d">No input/output data</div>`;
    return html;
  }

  /* ── JSON/value rendering ── */

  function syntaxHighlight(json) {
    return json
      .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
      .replace(/("(?:\\.|[^"\\])*")\s*:/g, '<span class="tv-json-key">$1</span>:')
      .replace(/:\s*("(?:\\.|[^"\\])*")/g, ': <span class="tv-json-str">$1</span>')
      .replace(/:\s*(\d+\.?\d*)/g, ': <span class="tv-json-num">$1</span>')
      .replace(/:\s*(true|false)/g, ': <span class="tv-json-bool">$1</span>')
      .replace(/:\s*(null)/g, ': <span class="tv-json-null">$1</span>');
  }

  let _fmtId = 0;

  function formatStructured(obj) {
    if (obj === null || obj === undefined) return '<span class="tv-fmt-null">null</span>';
    if (typeof obj === "boolean") return `<span class="tv-fmt-bool">${obj}</span>`;
    if (typeof obj === "number") return `<span class="tv-fmt-num">${obj}</span>`;
    if (typeof obj === "string") {
      const trimmed = obj.trim();
      if ((trimmed.startsWith("{") && trimmed.endsWith("}")) || (trimmed.startsWith("[") && trimmed.endsWith("]"))) {
        try { const p = JSON.parse(trimmed); if (typeof p === "object" && p !== null) return formatStructured(p); } catch (_) {}
      }
      // Collapse long strings
      if (obj.length > 300) {
        const id = `tv-fmtc-${++_fmtId}`;
        return `<span class="tv-fmt-str"><span class="tv-fmt-collapsed-text" id="${id}">${esc(obj.slice(0, 300))}<span class="tv-fmt-hidden" style="display:none">${esc(obj.slice(300))}</span></span> <button type="button" class="tv-fmt-toggle" onclick="var h=document.querySelector('#${id} .tv-fmt-hidden');if(h.style.display==='none'){h.style.display='inline';this.textContent='Show less'}else{h.style.display='none';this.textContent='Show more (${Math.ceil(obj.length/1000)}k chars)'}">Show more (${Math.ceil(obj.length/1000)}k chars)</button></span>`;
      }
      return `<span class="tv-fmt-str">${esc(obj)}</span>`;
    }
    if (Array.isArray(obj)) {
      if (!obj.length) return '<span class="tv-fmt-null">[]</span>';
      const limit = 10;
      const items = obj.slice(0, limit).map((item, i) =>
        `<div class="tv-fmt-arr-item"><span class="tv-fmt-idx">[${i}]</span>${formatStructured(item)}</div>`
      ).join("");
      if (obj.length > limit) {
        const id = `tv-fmta-${++_fmtId}`;
        const rest = obj.slice(limit).map((item, i) =>
          `<div class="tv-fmt-arr-item"><span class="tv-fmt-idx">[${i + limit}]</span>${formatStructured(item)}</div>`
        ).join("");
        return `<div class="tv-fmt-arr">${items}<div id="${id}" style="display:none">${rest}</div><button type="button" class="tv-fmt-toggle" onclick="var el=document.getElementById('${id}');if(el.style.display==='none'){el.style.display='block';this.textContent='Show less'}else{el.style.display='none';this.textContent='Show ${obj.length - limit} more items'}">Show ${obj.length - limit} more items</button></div>`;
      }
      return `<div class="tv-fmt-arr">${items}</div>`;
    }
    const entries = Object.entries(obj);
    if (!entries.length) return '<span class="tv-fmt-null">{}</span>';
    const limit = 15;
    const visible = entries.slice(0, limit).map(([k, v]) =>
      `<div class="tv-fmt-row"><span class="tv-fmt-key">${esc(k)}</span><div class="tv-fmt-val">${formatStructured(v)}</div></div>`
    ).join("");
    if (entries.length > limit) {
      const id = `tv-fmto-${++_fmtId}`;
      const rest = entries.slice(limit).map(([k, v]) =>
        `<div class="tv-fmt-row"><span class="tv-fmt-key">${esc(k)}</span><div class="tv-fmt-val">${formatStructured(v)}</div></div>`
      ).join("");
      return `<div class="tv-fmt-obj">${visible}<div id="${id}" style="display:none">${rest}</div><button type="button" class="tv-fmt-toggle" onclick="var el=document.getElementById('${id}');if(el.style.display==='none'){el.style.display='block';this.textContent='Show less'}else{el.style.display='none';this.textContent='Show ${entries.length - limit} more fields'}">Show ${entries.length - limit} more fields</button></div>`;
    }
    return `<div class="tv-fmt-obj">${visible}</div>`;
  }

  function renderJsonBlock(value) {
    let parsed;
    try {
      parsed = typeof value === "string" ? JSON.parse(value) : value;
    } catch (_) {
      return `<pre class="tv-code">${esc(String(value))}</pre>`;
    }
    const raw = JSON.stringify(parsed, null, 2);
    const highlighted = syntaxHighlight(raw);
    const lines = raw.split("\n").length;
    const collapsed = lines > 20;

    if (S.viewMode === "raw") {
      return `<pre class="tv-code ${collapsed?"tv-json-collapsed":""}">${highlighted}</pre>` +
        (collapsed ? `<button type="button" class="tv-json-expand">Show all ${lines} lines</button>` : "");
    }
    // Formatted (structured key-value)
    return `<div class="tv-fmt-block">${formatStructured(parsed)}</div>`;
  }

  function renderScores(scores) {
    if (!scores.length) return `<div class="tv-empty-d">No scores</div>`;
    return `<div class="tv-scores">${scores.map(sc => {
      const v = typeof sc.value === "number" ? sc.value.toFixed(2) : sc.value;
      return `<div class="tv-score-card"><div class="tv-score-head"><span class="tv-score-name">${esc(sc.name)}</span><span class="tv-score-val">${esc(v)}</span></div>${sc.explanation ? `<div class="tv-score-exp">${esc(sc.explanation)}</div>` : ""}</div>`;
    }).join("")}</div>`;
  }

  function renderRaw(span) {
    const allAttrs = span.attributes || {};
    const events = span.events || [];
    let html = `<div class="tv-io-section"><div class="tv-io-label">Attributes</div>${renderJsonBlock(allAttrs)}</div>`;
    if (events.length) {
      html += `<div class="tv-io-section"><div class="tv-io-label">Events</div>${renderJsonBlock(events)}</div>`;
    }
    html += `<div class="tv-io-section"><div class="tv-io-label">Span Metadata</div>${renderJsonBlock({ span_id: span.span_id, parent_span_id: span.parent_span_id, trace_id: span.trace_id, kind: span.kind, status: span.status, duration_ms: span.duration_ms })}</div>`;
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
            <div class="tv-meta"></div>
            <div class="tv-warning" style="display:none"></div>
          </div>
          <div class="tv-header-right">
            <div class="tv-search-wrap">
              <input type="text" class="tv-search" placeholder="Filter spans..." aria-label="Search spans">
              <span class="tv-search-icon"><svg viewBox="0 0 16 16" width="14" height="14"><circle cx="7" cy="7" r="4.5" stroke="currentColor" stroke-width="1.5" fill="none"/><path d="m10.5 10.5 3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></span>
            </div>
            <a class="tv-ext-link" target="_blank" rel="noopener" style="display:none">External ↗</a>
            <button type="button" class="tv-close" data-trace-close="1" aria-label="Close">
              <svg viewBox="0 0 16 16" width="16" height="16"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
            </button>
          </div>
        </div>
        <div class="tv-body">
          <div class="tv-list"></div>
          <div class="tv-detail"></div>
        </div>
        <div class="tv-footer">
          <span class="tv-shortcut"><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
          <span class="tv-shortcut"><kbd>Enter</kbd> expand</span>
          <span class="tv-shortcut"><kbd>/</kbd> search</span>
          <span class="tv-shortcut"><kbd>Esc</kbd> close</span>
        </div>
      </aside>
    `;
    document.body.appendChild(el);
    S.shell = el;
    S.el.title = el.querySelector(".tv-title");
    S.el.meta = el.querySelector(".tv-meta");
    S.el.link = el.querySelector(".tv-ext-link");
    S.el.warning = el.querySelector(".tv-warning");
    S.el.list = el.querySelector(".tv-list");
    S.el.detail = el.querySelector(".tv-detail");
    S.el.search = el.querySelector(".tv-search");

    // Search input
    S.el.search.addEventListener("input", () => {
      S.search = S.el.search.value;
      renderTree();
    });
  }

  /* ── open / close ── */
  function openDrawer() { ensureShell(); S.shell.classList.add("open"); document.body.classList.add("tv-open"); }
  function closeDrawer() { if (!S.shell) return; S.shell.classList.remove("open"); document.body.classList.remove("tv-open"); }

  async function fetchTrace(meta) {
    if (!meta.endpoint) throw new Error("Missing endpoint");
    if (cache.has(meta.endpoint)) return cache.get(meta.endpoint);
    const res = await fetch(meta.endpoint, { credentials: "same-origin" });
    if (!res.ok) throw new Error(await res.text() || `HTTP ${res.status}`);
    const data = await res.json();
    cache.set(meta.endpoint, data);
    return data;
  }

  async function open(meta) {
    if (S.exportMode) return;
    S.meta = meta;
    S.data = null;
    S.selected = null;
    S.expanded = new Set();
    S.search = "";
    S.activeTab = null;
    openDrawer();
    S.el.search.value = "";

    // Loading state
    S.el.title.textContent = meta.itemLabel || "Trace";
    S.el.meta.innerHTML = `<span class="tv-chip">Loading...</span>`;
    S.el.list.innerHTML = `<div class="tv-loading">Loading trace...</div>`;
    S.el.detail.innerHTML = "";

    try {
      const data = await fetchTrace(meta);
      data._tree = buildTree(data.spans);
      S.data = data;

      // Auto-expand roots
      data._tree.roots.forEach(r => S.expanded.add(r.span_id));

      // Auto-expand error path or select first
      const errorId = autoExpandErrors(data._tree);
      S.selected = errorId || data._tree.roots[0]?.span_id || null;

      // Also expand children of first root for nice default view
      if (!errorId && data._tree.roots[0]) {
        data._tree.roots[0]._children.forEach(c => S.expanded.add(c.span_id));
      }

      renderHeader(meta, data);
      renderTree();
    } catch (err) {
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
    if (e.target.closest("[data-trace-close]")) { e.preventDefault(); closeDrawer(); return; }
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
    // View mode toggle (formatted/raw) — applies to entire detail panel
    if (e.target.closest("[data-viewmode]")) {
      e.preventDefault();
      S.viewMode = e.target.closest("[data-viewmode]").getAttribute("data-viewmode");
      renderDetail();
      return;
    }
    // JSON expand (show all lines in raw mode)
    if (e.target.closest(".tv-json-expand")) {
      e.preventDefault();
      const pre = e.target.closest(".tv-json-expand").previousElementSibling;
      if (pre) pre.classList.remove("tv-json-collapsed");
      e.target.closest(".tv-json-expand").remove();
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
      if (S.el.search === document.activeElement && S.search) { S.search = ""; S.el.search.value = ""; renderTree(); }
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
  function init(opts) {
    S.exportMode = !!(opts && opts.exportMode);
    ensureShell();
    if (S.ready) return;
    document.addEventListener("click", handleClick);
    document.addEventListener("keydown", handleKey);
    S.ready = true;
  }

  window.QymTraceViewer = { init, open, openFromButton, close: closeDrawer };
})();
