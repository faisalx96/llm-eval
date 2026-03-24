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
  };

  /* ── icons (inline SVG, 16×16) ── */
  const ICONS = {
    LLM:       `<svg viewBox="0 0 16 16"><rect x="2" y="2" width="12" height="8.5" rx="2" fill="currentColor"/><polygon points="5,10.5 5,14 8.5,10.5" fill="currentColor"/></svg>`,
    TOOL:      `<svg viewBox="0 0 16 16"><path d="M9.7 7.7L5.3 12.1a1.6 1.6 0 0 1-2.3 0l-.1-.1a1.6 1.6 0 0 1 0-2.3l4.4-4.4a3.2 3.2 0 0 1 4.6-3.7L10 3.5l.3 1.2 1.2.3 1.9-1.9a3.2 3.2 0 0 1-3.7 4.6z" fill="currentColor"/></svg>`,
    AGENT:     `<svg viewBox="0 0 16 16"><circle cx="8" cy="4" r="3" fill="currentColor"/><path d="M2.5 14.5c0-3 2.5-5.5 5.5-5.5s5.5 2.5 5.5 5.5z" fill="currentColor" opacity=".75"/></svg>`,
    CHAIN:     `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M7 9l-1.2 1.2a2.4 2.4 0 0 1-3.4-3.4L5.2 4a2.4 2.4 0 0 1 3.4 3.4"/><path d="M9 7l1.2-1.2a2.4 2.4 0 0 1 3.4 3.4L10.8 12a2.4 2.4 0 0 1-3.4-3.4"/></svg>`,
    EVALUATOR: `<svg viewBox="0 0 16 16"><path d="M8 1.5l2 4 4.4.7-3.2 3.1.75 4.4L8 11.5l-3.95 2.2.75-4.4-3.2-3.1L7 5.5z" fill="currentColor"/></svg>`,
    RETRIEVER: `<svg viewBox="0 0 16 16"><circle cx="6.8" cy="6.8" r="4.3" fill="currentColor" opacity=".3"/><circle cx="6.8" cy="6.8" r="2.5" fill="currentColor"/><rect x="10" y="10.2" width="2.2" height="4.5" rx="1" transform="rotate(-45 11 12.5)" fill="currentColor"/></svg>`,
    EMBED:     `<svg viewBox="0 0 16 16"><rect x="1.5" y="1.5" width="5.5" height="5.5" rx="1.5" fill="currentColor" opacity=".85"/><rect x="9" y="1.5" width="5.5" height="5.5" rx="1.5" fill="currentColor" opacity=".45"/><rect x="1.5" y="9" width="5.5" height="5.5" rx="1.5" fill="currentColor" opacity=".45"/><rect x="9" y="9" width="5.5" height="5.5" rx="1.5" fill="currentColor" opacity=".85"/></svg>`,
    DEFAULT:   `<svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="4.5" fill="currentColor" opacity=".7"/></svg>`,
  };

  const KIND_COLORS = {
    LLM: "#f472b6", TOOL: "#fbbf24", AGENT: "#34d399", CHAIN: "#60a5fa",
    EVALUATOR: "#a78bfa", RETRIEVER: "#38bdf8", EMBED: "#94a3b8", DEFAULT: "#6b7280",
  };

  /* ── helpers ── */
  const COPY_ICON = `<svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="5.5" y="5.5" width="8" height="8" rx="1.5"/><path d="M3 10.5V3a1.5 1.5 0 0 1 1.5-1.5H10"/></svg>`;

  function copyBtn(textOrFn, label) {
    const id = `tv-cb-${++_copyId}`;
    _copyData[id] = textOrFn;
    return `<button type="button" class="tv-copy-btn" data-copy-id="${id}" title="${label || "Copy"}">${COPY_ICON}</button>`;
  }
  let _copyId = 0;
  const _copyData = {};

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

  function statusCls(s) {
    const u = String(s||"").toUpperCase();
    return u === "ERROR" ? "error" : u === "OK" ? "ok" : "unset";
  }

  function laneOpacity(depthIndex) {
    if (depthIndex <= 0) return "0.24";
    if (depthIndex === 1) return "0.18";
    return "0.14";
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

  function metricToneClass(value) {
    if (typeof value === "boolean") return value ? "pass" : "fail";
    if (typeof value !== "number" || !Number.isFinite(value)) return "";
    if (value === 0) return "fail";
    if (value >= 0.5 && value <= 1) return "pass";
    return "";
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
      const tone = metricToneClass(sc.value);
      chips += `<span class="tv-chip tv-chip-score ${tone}">${esc(sc.name)}: ${esc(v)}</span>`;
    });
    if (item.trace_id) chips += `<button type="button" class="tv-chip tv-chip-copy" data-trace-copy="${esc(item.trace_id)}" title="Copy Trace ID">ID</button>`;

    S.el.meta.innerHTML = chips;

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
    detectRetries(tree);
    const bounds = computeBounds(S.data);
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
        const guideStyle = ` style="--tv-guide-opacity:${laneOpacity(i)}"`;
        guidesHtml += `<span class="tv-guide ${prefix[i] ? 'pipe' : 'space'}"${guideStyle}></span>`;
      }
      if (node._depth > 0) {
        guidesHtml += `<span class="tv-guide ${isLast ? 'elbow' : 'branch'}" style="--tv-guide-opacity:${laneOpacity(prefix.length)}"></span>`;
      }

      // Toggle (expand/collapse) — right side
      const toggleHtml = visibleKids.length
        ? `<span class="tv-toggle ${exp?"open":""}" data-toggle="${esc(node.span_id)}"><svg viewBox="0 0 10 10" width="10" height="10"><path d="M3 2l4 3-4 3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></span>`
        : `<span class="tv-toggle tv-toggle-empty"></span>`;

      // Inline meta for LLM spans
      let inlineMeta = "";
      const model = kind === "LLM" ? spanModel(node) : "";
      if (kind === "LLM" && model) inlineMeta += `<span class="tv-inline-model">${esc(model)}</span>`;
      if (kind === "LLM" && tokens) inlineMeta += `<span class="tv-inline-tokens"><svg class="tv-tokens-icon" viewBox="0 0 16 16" width="13" height="13"><ellipse cx="9" cy="10.5" rx="5.5" ry="2.8" fill="currentColor" opacity=".45"/><ellipse cx="7.5" cy="7.5" rx="5.5" ry="2.8" transform="rotate(-15 7.5 7.5)" fill="currentColor" opacity=".7"/><ellipse cx="6.5" cy="4.5" rx="5" ry="2.5" transform="rotate(-25 6.5 4.5)" fill="currentColor"/></svg>${fmtTokens(tokens)}</span>`;

      const stCls = statusCls(node.status);

      // Error indicator
      let errHtml = "";
      if (stCls === "error") {
        const errInfo = extractErrorInfo(node);
        errHtml = `<span class="tv-err-badge" title="${esc(errInfo?.message || 'Error')}"><svg viewBox="0 0 16 16" width="12" height="12"><circle cx="8" cy="8" r="7" fill="currentColor" opacity=".15"/><path d="M8 4v5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="8" cy="11.5" r="1" fill="currentColor"/></svg></span>`;
      }

      // Retry badge
      let retryHtml = "";
      if (node._retry > 0) {
        retryHtml = `<span class="tv-retry-badge">↻ retry${node._retry > 1 ? " #" + node._retry : ""}</span>`;
      }

      const rowCls = [
        "tv-row",
        sel ? "sel" : "",
        stCls === "error" ? "row-err" : "",
        node._retry > 0 ? "row-retry" : "",
        node._failed ? "row-failed" : "",
      ].filter(Boolean).join(" ");

      rows.push(
        `<button type="button" class="${rowCls}" data-span="${esc(node.span_id)}">` +
          `<span class="tv-tree-gutter">${guidesHtml}</span>` +
          `<span class="tv-row-main">` +
            `<span class="tv-icon" style="background:${color}20;color:${color}">${ICONS[kind]||ICONS.DEFAULT}</span>` +
            `<span class="tv-name-group"><span class="tv-name">${esc(node.name||"(unnamed)")}</span>${errHtml}${retryHtml}${inlineMeta}</span>` +
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
      if (attrs["output.value"]) tabs.push({ id: "llm-output", label: "Output" });
      tabs.push({ id: "params", label: "Params" });
    } else if (kind === "TOOL") {
      tabs.push({ id: "tool-io", label: "Input / Output" });
    } else if (kind === "EVALUATOR" && attrs["output.value"]) {
      tabs.push({ id: "metrics", label: "Metrics" });
      if (attrs["input.value"]) tabs.push({ id: "io", label: "Input / Output" });
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
    if (model) header += `<span>${esc(model)}</span><span class="tv-dot"></span>`;
    header += `<span>${esc(fmtDur(span.duration_ms))}</span>`;
    if (tokens) header += `<span class="tv-dot"></span><span>${fmtTokens(tokens)} tokens</span>`;
    const costStr = fmtCost(cost);
    if (costStr) header += `<span class="tv-dot"></span><span>${costStr}</span>`;
    header += `</div></div>`;
    header += `<span class="tv-chip tv-chip-status-${stCls}">${esc(String(span.status||"UNSET").toUpperCase())}</span>`;
    if (span._retry > 0) header += `<span class="tv-chip tv-chip-retry">↻ retry${span._retry > 1 ? " #" + span._retry : ""}</span>`;
    header += `</div>`;

    // Error detail block
    if (stCls === "error") {
      const errInfo = extractErrorInfo(span);
      header += `<div class="tv-det-error">`;
      header += `<div class="tv-det-error-title">Error</div>`;
      if (errInfo) {
        if (errInfo.type) header += `<div class="tv-det-error-type">${esc(errInfo.type)}</div>`;
        if (errInfo.message) header += `<div class="tv-det-error-msg">${esc(errInfo.message)}</div>`;
        if (errInfo.stacktrace) header += `<details class="tv-det-error-stack"><summary>Stack trace</summary><pre class="tv-code">${esc(errInfo.stacktrace)}</pre></details>`;
      } else {
        header += `<div class="tv-det-error-msg">This span completed with ERROR status</div>`;
      }
      header += `</div>`;
    }

    // Tabs + view mode toggle
    let tabBar = `<div class="tv-tabs">`;
    tabs.forEach(t => {
      tabBar += `<button type="button" class="tv-tab ${S.activeTab===t.id?"active":""}" data-tab="${t.id}">${esc(t.label)}</button>`;
    });
    tabBar += `</div>`;

    // Tab content
    let content = `<div class="tv-tab-content">`;
    if (S.activeTab === "messages") content += renderMessages(inputMsgs.concat(outputMsgs), reasoning);
    else if (S.activeTab === "llm-output") content += renderLLMOutput(span);
    else if (S.activeTab === "params") content += renderParams(span);
    else if (S.activeTab === "tool-io") content += renderToolIO(span);
    else if (S.activeTab === "metrics") content += renderMetrics(span);
    else if (S.activeTab === "io") content += renderIO(span);
    else if (S.activeTab === "scores") content += renderScores(scores);
    else if (S.activeTab === "raw") content += renderRaw(span);
    content += `</div>`;

    S.el.detail.innerHTML = header + tabBar + content;
    mountJsonFormatters(S.el.detail);
  }

  /* ── tab renderers ── */
  function renderMessages(msgs, reasoning) {
    if (!msgs.length && !reasoning) return `<div class="tv-empty-d">No messages</div>`;
    let html = msgs.map(m => {
      const role = String(m.role).toLowerCase();
      const msgText = m.content ? String(m.content) : "";
      let bubble = `<div class="tv-msg tv-msg-${role}">`;
      bubble += `<div class="tv-msg-role">${esc(role)}${m.toolCallId ? ` <span class="tv-msg-tcid">${esc(m.toolCallId)}</span>` : ""}${msgText ? copyBtn(msgText, "Copy message") : ""}</div>`;
      if (m.content) {
        const text = String(m.content).trim();
        const trimmed = text;
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
          bubble += `<div class="tv-toolcall-name">${esc(tc.name)}${tc.arguments ? copyBtn(tc.arguments, "Copy arguments") : ""}</div>`;
          if (tc.arguments) {
            bubble += renderJsonBlock(tc.arguments);
          }
          bubble += `</div>`;
        });
      }
      bubble += `</div>`;
      return bubble;
    }).join("");

    // Reasoning: inline expander after messages (not a separate tab)
    if (reasoning) {
      html += `<details class="tv-reasoning-expander"><summary class="tv-reasoning-summary">Reasoning ${copyBtn(reasoning, "Copy reasoning")}</summary>`;
      html += `<div class="tv-reasoning">${esc(reasoning)}</div>`;
      html += `</details>`;
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

  function renderLLMOutput(span) {
    const a = span.attributes || {};
    const raw = a["output.value"];
    if (!raw) return `<div class="tv-empty-d">No output data</div>`;
    let parsed;
    try { parsed = deepParseJson(typeof raw === "string" ? JSON.parse(raw) : raw); } catch (_) { return renderJsonBlock(raw); }
    if (!parsed || typeof parsed !== "object") return renderJsonBlock(raw);

    let html = "";

    // Usage section
    const usage = parsed.usage;
    if (usage && typeof usage === "object") {
      html += `<div class="tv-io-section"><div class="tv-io-label">Usage ${copyBtn(() => JSON.stringify(usage, null, 2), "Copy usage")}</div>`;
      const rows = [];
      function addRow(label, val, cls) { if (val != null && val !== 0 && val !== "") rows.push([label, val, cls || ""]); }
      addRow("Prompt Tokens", usage.prompt_tokens);
      addRow("Completion Tokens", usage.completion_tokens);
      const rd = usage.completion_tokens_details;
      if (rd) {
        addRow("  Reasoning Tokens", rd.reasoning_tokens);
        addRow("  Image Tokens", rd.image_tokens);
        addRow("  Audio Tokens", rd.audio_tokens);
      }
      const pd = usage.prompt_tokens_details;
      if (pd) {
        addRow("  Cached Tokens", pd.cached_tokens || pd.cache_read_tokens);
        addRow("  Cache Write Tokens", pd.cache_write_tokens);
      }
      addRow("Total Tokens", usage.total_tokens);
      // Cost info
      if (usage.cost != null) addRow("Cost", "$" + Number(usage.cost).toFixed(6), "tv-llm-cost");
      const cd = usage.cost_details;
      if (cd) {
        if (cd.upstream_inference_cost != null) addRow("  Inference Cost", "$" + Number(cd.upstream_inference_cost).toFixed(6));
        if (cd.upstream_inference_prompt_cost != null) addRow("    Prompt Cost", "$" + Number(cd.upstream_inference_prompt_cost).toFixed(6));
        if (cd.upstream_inference_completions_cost != null) addRow("    Completions Cost", "$" + Number(cd.upstream_inference_completions_cost).toFixed(6));
      }
      if (usage.is_byok != null) addRow("BYOK", String(usage.is_byok));
      html += `<div class="tv-params">${rows.map(([k,v,c]) => `<div class="tv-param${k.startsWith("  ") ? " tv-param-indent" : ""}"><span class="tv-param-k ${c}">${esc(k.trim())}</span><span class="tv-param-v ${c}">${esc(String(v))}</span></div>`).join("")}</div>`;
      html += `</div>`;
    }

    // Provider / model / metadata section
    const meta = [];
    if (parsed.provider) meta.push(["Provider", parsed.provider]);
    if (parsed.model) meta.push(["Model", parsed.model]);
    if (parsed.id) meta.push(["Response ID", parsed.id]);
    if (parsed.object) meta.push(["Object", parsed.object]);
    if (parsed.created) meta.push(["Created", new Date(parsed.created * 1000).toISOString()]);
    if (parsed.system_fingerprint) meta.push(["System Fingerprint", parsed.system_fingerprint]);
    const choice = parsed.choices?.[0];
    if (choice) {
      if (choice.finish_reason) meta.push(["Finish Reason", choice.finish_reason]);
      if (choice.native_finish_reason) meta.push(["Native Finish Reason", choice.native_finish_reason]);
    }
    if (meta.length) {
      html += `<div class="tv-io-section"><div class="tv-io-label">Response Metadata ${copyBtn(() => JSON.stringify(parsed, null, 2), "Copy full response")}</div>`;
      html += `<div class="tv-params">${meta.map(([k,v]) => `<div class="tv-param"><span class="tv-param-k">${esc(k)}</span><span class="tv-param-v">${esc(String(v))}</span></div>`).join("")}</div>`;
      html += `</div>`;
    }

    // Full raw response
    html += `<div class="tv-io-section"><div class="tv-io-label">Full Response ${copyBtn(() => JSON.stringify(parsed, null, 2), "Copy full response")}</div>`;
    html += renderJsonBlock(raw);
    html += `</div>`;

    return html;
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
      html += `<div class="tv-msg-role">tool call ${copyBtn(inp, "Copy input")}</div>`;
      html += `<div class="tv-toolcall">`;
      html += `<div class="tv-toolcall-name">${esc(toolName)}</div>`;
      html += renderJsonBlock(inp);
      html += `</div></div>`;
    }

    // Tool result — rendered as a tool result bubble
    if (out) {
      html += `<div class="tv-msg tv-msg-tool">`;
      html += `<div class="tv-msg-role">result ${copyBtn(out, "Copy output")}</div>`;
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
      html += `<div class="tv-io-section"><div class="tv-io-label tv-io-label-input">Input ${copyBtn(inp, "Copy input")}</div>`;
      html += renderJsonBlock(inp);
      html += `</div>`;
    }
    if (out) {
      html += `<div class="tv-io-section"><div class="tv-io-label tv-io-label-output">Output ${copyBtn(out, "Copy output")}</div>`;
      html += renderJsonBlock(out);
      html += `</div>`;
    }
    if (!inp && !out) html = `<div class="tv-empty-d">No input/output data</div>`;
    return html;
  }

  /* ── JSON/value rendering (CodeMirror 6) ── */

  let _cmId = 0;
  const _cmData = {};
  let _cmModules = null;
  let _cmLoading = null;

  function loadCodeMirror() {
    if (_cmModules) return Promise.resolve(_cmModules);
    if (_cmLoading) return _cmLoading;
    _cmLoading = Promise.all([
      import("https://esm.sh/@codemirror/state@6"),
      import("https://esm.sh/@codemirror/view@6"),
      import("https://esm.sh/@codemirror/language@6"),
      import("https://esm.sh/@codemirror/lang-json@6"),
      import("https://esm.sh/@codemirror/commands@6"),
      import("https://esm.sh/@lezer/highlight@1"),
    ]).then(([state, view, language, langJson, commands, highlight]) => {
      _cmModules = { state, view, language, langJson, commands, highlight };
      return _cmModules;
    });
    return _cmLoading;
  }

  // Start loading immediately
  loadCodeMirror();

  function renderJsonPlaceholder(jsonStr) {
    const id = `tv-cm-${++_cmId}`;
    _cmData[id] = jsonStr;
    return `<div class="tv-cm" data-cm-id="${id}"></div>`;
  }

  function mountJsonFormatters(root) {
    const els = root.querySelectorAll("[data-cm-id]");
    if (!els.length) return;
    loadCodeMirror().then(cm => {
      els.forEach(el => {
        const id = el.getAttribute("data-cm-id");
        const doc = _cmData[id];
        if (doc == null) return;
        delete _cmData[id];
        const edState = cm.state.EditorState.create({
          doc,
          extensions: [
            cm.view.lineNumbers(),
            cm.language.foldGutter(),
            cm.view.drawSelection(),
            cm.language.bracketMatching(),
            cm.langJson.json(),
            cm.view.keymap.of([...cm.commands.defaultKeymap, ...cm.language.foldKeymap]),
            cm.state.EditorState.readOnly.of(true),
            cm.view.EditorView.editable.of(false),
            // qym theme
            cm.view.EditorView.theme({
              "&": { fontSize: "12px", maxHeight: "500px", background: "var(--bg-void)", color: "var(--text-secondary)" },
              ".cm-scroller": { overflow: "auto", fontFamily: "var(--font-mono)" },
              ".cm-gutters": { background: "var(--bg-void)", border: "none", minWidth: "auto" },
              ".cm-lineNumbers .cm-gutterElement": { color: "#50505e", minWidth: "1.8em", padding: "0 4px 0 4px", fontSize: "11px" },
              ".cm-foldGutter .cm-gutterElement": { color: "#7a7a90", padding: "0 2px 0 0", width: "12px" },
              ".cm-line": { padding: "0 8px" },
              ".cm-activeLine": { background: "rgba(255,255,255,.03)" },
              ".cm-activeLineGutter": { background: "rgba(255,255,255,.03)" },
              ".cm-selectionBackground": { background: "rgba(0,168,255,.15) !important" },
              ".cm-cursor": { borderLeftColor: "#00d4aa" },
              "&.cm-focused .cm-selectionBackground": { background: "rgba(0,168,255,.2) !important" },
              ".cm-matchingBracket": { background: "rgba(0,212,170,.15)", outline: "1px solid rgba(0,212,170,.3)" },
            }, { dark: true }),
            cm.language.syntaxHighlighting(cm.language.HighlightStyle.define([
              { tag: cm.highlight.tags.propertyName, color: "#00a8ff" },
              { tag: cm.highlight.tags.string, color: "#00d4aa" },
              { tag: cm.highlight.tags.number, color: "#a855f7" },
              { tag: cm.highlight.tags.bool, color: "#00a8ff" },
              { tag: cm.highlight.tags.null, color: "#50505e" },
              { tag: cm.highlight.tags.punctuation, color: "#7a7a90" },
              { tag: cm.highlight.tags.brace, color: "#7a7a90" },
              { tag: cm.highlight.tags.squareBracket, color: "#7a7a90" },
            ])),
          ],
        });
        new cm.view.EditorView({ state: edState, parent: el });
      });
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

  function renderJsonBlock(value) {
    let parsed;
    try {
      parsed = typeof value === "string" ? JSON.parse(value) : value;
    } catch (_) {
      return `<pre class="tv-code">${esc(String(value))}</pre>`;
    }
    parsed = deepParseJson(parsed);
    if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
      parsed = nestDottedKeys(parsed);
    }
    return renderJsonPlaceholder(JSON.stringify(parsed, null, 2));
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
      const score = data && typeof data === "object" ? data.score : data;
      const meta = data && typeof data === "object" ? data.metadata : null;
      const isNum = typeof score === "number";
      const displayVal = isNum ? (Number.isInteger(score) || score > 10 ? score.toLocaleString("en-US") : score.toFixed(2)) : String(score ?? "—");
      const cls = metricToneClass(score);
      const metaId = `tv-metric-${++id}`;
      let card = `<div class="tv-metric-card ${cls}">`;
      card += `<div class="tv-metric-head${meta ? " tv-metric-expandable" : ""}" ${meta ? `data-metric-toggle="${metaId}"` : ""}>`;
      card += `<span class="tv-metric-name">${esc(name.replace(/_/g, " "))}</span>`;
      card += `<span class="tv-metric-val">${esc(displayVal)}</span>`;
      if (meta) card += `<span class="tv-metric-chevron"><svg viewBox="0 0 10 10" width="10" height="10"><path d="M3 2l4 3-4 3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></span>`;
      card += `</div>`;
      if (meta) {
        const metaEntries = Object.entries(meta);
        card += `<div class="tv-metric-detail" id="${metaId}" style="display:none">`;
        card += metaEntries.map(([k, v]) => {
          let valStr, valCls = "";
          if (typeof v === "boolean") { valStr = String(v); valCls = v ? "tv-metric-true" : "tv-metric-false"; }
          else if (typeof v === "number") { valStr = v.toLocaleString("en-US"); }
          else { valStr = String(v); }
          return `<div class="tv-metric-meta-row"><span class="tv-metric-meta-key">${esc(k)}</span><span class="tv-metric-meta-val ${valCls}">${esc(valStr)}</span></div>`;
        }).join("");
        card += `</div>`;
      }
      card += `</div>`;
      return card;
    }).join("")}</div>`;
  }

  function renderScores(scores) {
    if (!scores.length) return `<div class="tv-empty-d">No scores</div>`;
    return `<div class="tv-scores">${scores.map(sc => {
      const v = typeof sc.value === "number" ? sc.value.toFixed(2) : sc.value;
      const tone = metricToneClass(sc.value);
      return `<div class="tv-score-card ${tone}"><div class="tv-score-head"><span class="tv-score-name">${esc(sc.name)}</span><span class="tv-score-val ${tone}">${esc(v)}</span></div>${sc.explanation ? `<div class="tv-score-exp">${esc(sc.explanation)}</div>` : ""}</div>`;
    }).join("")}</div>`;
  }

  function renderRaw(span) {
    const allAttrs = span.attributes || {};
    const events = span.events || [];
    const metaObj = { span_id: span.span_id, parent_span_id: span.parent_span_id, trace_id: span.trace_id, kind: span.kind, status: span.status, duration_ms: span.duration_ms };
    let html = `<div class="tv-io-section"><div class="tv-io-label">Attributes ${copyBtn(() => JSON.stringify(allAttrs, null, 2), "Copy attributes")}</div>${renderJsonBlock(allAttrs)}</div>`;
    if (events.length) {
      html += `<div class="tv-io-section"><div class="tv-io-label">Events ${copyBtn(() => JSON.stringify(events, null, 2), "Copy events")}</div>${renderJsonBlock(events)}</div>`;
    }
    html += `<div class="tv-io-section"><div class="tv-io-label">Span Metadata ${copyBtn(() => JSON.stringify(metaObj, null, 2), "Copy metadata")}</div>${renderJsonBlock(metaObj)}</div>`;
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
            <button type="button" class="tv-close" data-trace-close="1" aria-label="Close">
              <svg viewBox="0 0 16 16" width="16" height="16"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
            </button>
          </div>
        </div>
        <div class="tv-body">
          <div class="tv-list"></div>
          <div class="tv-divider"></div>
          <div class="tv-detail"></div>
        </div>
      </aside>
    `;
    document.body.appendChild(el);
    S.shell = el;
    S.el.title = el.querySelector(".tv-title");
    S.el.meta = el.querySelector(".tv-meta");
    S.el.warning = el.querySelector(".tv-warning");
    S.el.list = el.querySelector(".tv-list");
    S.el.detail = el.querySelector(".tv-detail");
    S.el.search = el.querySelector(".tv-search");

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
      const startW = S.el.list.getBoundingClientRect().width;
      const bodyW = body.getBoundingClientRect().width;
      const onMove = (ev) => {
        const dx = ev.clientX - startX;
        const newW = Math.max(200, Math.min(bodyW - 200, startW + dx));
        S.el.list.style.flex = `0 0 ${newW}px`;
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
    if (e.target.closest("[data-copy-id]")) {
      e.preventDefault(); e.stopPropagation();
      const btn = e.target.closest("[data-copy-id]");
      const id = btn.getAttribute("data-copy-id");
      const raw = _copyData[id];
      const text = typeof raw === "function" ? raw() : String(raw || "");
      if (text && navigator.clipboard) {
        navigator.clipboard.writeText(text).catch(()=>{});
        btn.classList.add("tv-copy-ok");
        setTimeout(() => btn.classList.remove("tv-copy-ok"), 1200);
      }
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
