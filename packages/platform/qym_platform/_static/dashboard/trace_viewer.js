(function () {
  const cache = new Map();
  const state = {
    initialized: false,
    exportMode: false,
    shell: null,
    listEl: null,
    detailEl: null,
    titleEl: null,
    metaEl: null,
    linkEl: null,
    warningEl: null,
    currentData: null,
    currentMeta: null,
    expandedIds: new Set(),
    selectedSpanId: null,
  };

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatDurationMs(value) {
    if (value == null || value === "") return "—";
    const num = Number(value);
    if (!Number.isFinite(num)) return "—";
    if (num >= 1000) return (num / 1000).toFixed(num >= 10000 ? 1 : 2) + "s";
    if (num >= 10) return num.toFixed(1) + "ms";
    if (num >= 1) return num.toFixed(2) + "ms";
    return num.toFixed(3) + "ms";
  }

  function formatOffsetNs(value, base) {
    if (value == null || base == null) return "—";
    return formatDurationMs((Number(value) - Number(base)) / 1_000_000);
  }

  function formatJson(value) {
    try {
      return JSON.stringify(value, null, 2);
    } catch (_err) {
      return String(value);
    }
  }

  function renderValue(value) {
    if (value == null) return '<span class="trace-inline-muted">null</span>';
    if (typeof value === "string") return `<span>${escapeHtml(value)}</span>`;
    if (typeof value === "number" || typeof value === "boolean") return `<span>${escapeHtml(String(value))}</span>`;
    return `<pre class="trace-json">${escapeHtml(formatJson(value))}</pre>`;
  }

  function displayKind(span) {
    const attrs = span.attributes || {};
    const candidates = [
      attrs["openinference.span.kind"],
      attrs["ai.openinference.span.kind"],
      attrs["span.kind"],
      attrs["gen_ai.operation.name"],
      span.kind,
    ];
    const raw = candidates.find((value) => value != null && String(value).trim() !== "");
    const normalized = String(raw || "internal").trim().toUpperCase().replace(/[^A-Z0-9]+/g, "_");
    const labels = {
      AGENT: "AGENT",
      CHAIN: "CHAIN",
      CLIENT: "CLIENT",
      EMBEDDING: "EMBED",
      INTERNAL: "INTERNAL",
      LLM: "LLM",
      RETRIEVER: "RETRIEVE",
      SERVER: "SERVER",
      TOOL: "TOOL",
    };
    return labels[normalized] || normalized.slice(0, 12);
  }

  function statusClass(status) {
    const normalized = String(status || "UNSET").toUpperCase();
    if (normalized === "ERROR") return "error";
    if (normalized === "OK") return "ok";
    return "unset";
  }

  function computeBounds(data) {
    const summary = (data && data.summary) || {};
    let start = summary.started_at_ns;
    let end = summary.ended_at_ns;
    if (start != null && end != null) return { start, end, total: Math.max(end - start, 1) };

    const spans = (data && data.spans) || [];
    const starts = spans.map((span) => span.start_time_ns).filter((value) => value != null);
    const ends = spans.map((span) => span.end_time_ns).filter((value) => value != null);
    if (!starts.length || !ends.length) return { start: null, end: null, total: 1 };
    start = Math.min.apply(null, starts);
    end = Math.max.apply(null, ends);
    return { start, end, total: Math.max(end - start, 1) };
  }

  function buildTree(data) {
    const spans = Array.isArray(data?.spans) ? data.spans.slice() : [];
    const byId = new Map();
    const nodes = spans.map((span, index) => ({
      ...span,
      _index: index,
      _children: [],
      _depth: 0,
      _is_orphan: false,
    }));
    nodes.forEach((node) => byId.set(node.span_id, node));

    const roots = [];
    nodes.forEach((node) => {
      const parentId = node.parent_span_id;
      if (parentId && byId.has(parentId)) {
        byId.get(parentId)._children.push(node);
      } else {
        node._is_orphan = !!parentId;
        roots.push(node);
      }
    });

    const byStart = (a, b) => {
      const aStart = a.start_time_ns == null ? Number.MAX_SAFE_INTEGER : Number(a.start_time_ns);
      const bStart = b.start_time_ns == null ? Number.MAX_SAFE_INTEGER : Number(b.start_time_ns);
      if (aStart !== bStart) return aStart - bStart;
      return a._index - b._index;
    };

    function assign(node, depth) {
      node._depth = depth;
      node._children.sort(byStart);
      node._children.forEach((child) => assign(child, depth + 1));
    }

    roots.sort(byStart);
    roots.forEach((root) => assign(root, 0));
    return { roots, byId, nodes };
  }

  function renderSummary(meta, data) {
    const summary = (data && data.summary) || {};
    const item = (data && data.item) || {};
    state.titleEl.textContent = meta.itemLabel || item.item_id || "Trace";

    const chips = [
      `<span class="trace-chip">${escapeHtml(String(summary.span_count ?? 0))} spans</span>`,
      `<span class="trace-chip">${escapeHtml(String(summary.root_count ?? 0))} roots</span>`,
      `<span class="trace-chip ${summary.error_count ? "error" : ""}">${escapeHtml(String(summary.error_count ?? 0))} errors</span>`,
      `<span class="trace-chip">${escapeHtml(formatDurationMs(summary.duration_ms))}</span>`,
    ];
    if (item.trace_id) {
      chips.unshift(`<button type="button" class="trace-chip trace-copy-chip" data-trace-copy="${escapeHtml(item.trace_id)}">Copy Trace ID</button>`);
    }
    state.metaEl.innerHTML = chips.join("");

    if (meta.traceUrl || item.trace_url) {
      state.linkEl.href = meta.traceUrl || item.trace_url;
      state.linkEl.style.display = "";
    } else {
      state.linkEl.removeAttribute("href");
      state.linkEl.style.display = "none";
    }

    if (summary.has_orphans) {
      state.warningEl.textContent = `${summary.orphan_count || 0} orphan span${summary.orphan_count === 1 ? "" : "s"} shown as root`;
      state.warningEl.style.display = "";
    } else {
      state.warningEl.textContent = "";
      state.warningEl.style.display = "none";
    }
  }

  function renderList(meta, data) {
    const tree = buildTree(data);
    state.currentData = { ...data, _tree: tree };
    const bounds = computeBounds(data);
    if (!state.expandedIds.size) {
      tree.roots.forEach((root) => state.expandedIds.add(root.span_id));
    }
    if (!state.selectedSpanId && tree.roots[0]) {
      state.selectedSpanId = tree.roots[0].span_id;
    }

    if (!tree.nodes.length) {
      state.listEl.innerHTML = `
        <div class="trace-empty-state">
          <div class="trace-empty-title">No native trace data recorded for this item</div>
          <div class="trace-empty-copy">This item may only have an external trace link, or tracing may not have been captured.</div>
        </div>
      `;
      state.detailEl.innerHTML = `
        <div class="trace-detail-empty">
          <div class="trace-empty-title">Nothing to inspect yet</div>
          <div class="trace-empty-copy">Open the external trace link if you need the full remote trace.</div>
        </div>
      `;
      return;
    }

    const rows = [];
    function visit(node) {
      const children = node._children || [];
      const expanded = state.expandedIds.has(node.span_id);
      const selected = state.selectedSpanId === node.span_id;
      let leftPct = 0;
      let widthPct = 100;
      if (bounds.start != null && node.start_time_ns != null) {
        leftPct = ((Number(node.start_time_ns) - Number(bounds.start)) / bounds.total) * 100;
      }
      if (bounds.start != null && node.end_time_ns != null && node.start_time_ns != null) {
        widthPct = ((Number(node.end_time_ns) - Number(node.start_time_ns)) / bounds.total) * 100;
      }
      widthPct = Math.max(widthPct, 0.75);
      rows.push(`
        <button type="button" class="trace-span-row ${selected ? "selected" : ""}" data-trace-span-row="${escapeHtml(node.span_id)}" style="--trace-depth:${node._depth};">
          <span class="trace-span-toggle-wrap">
            ${children.length ? `<span class="trace-span-toggle ${expanded ? "expanded" : ""}" data-trace-toggle="${escapeHtml(node.span_id)}">▾</span>` : '<span class="trace-span-toggle placeholder">•</span>'}
          </span>
          <span class="trace-kind-badge">${escapeHtml(displayKind(node))}</span>
          <span class="trace-span-name">${escapeHtml(node.name || "(unnamed span)")}</span>
          <span class="trace-span-duration">${escapeHtml(formatDurationMs(node.duration_ms))}</span>
          <span class="trace-span-waterfall">
            <span class="trace-span-waterfall-track"></span>
            <span class="trace-span-waterfall-bar ${statusClass(node.status)}" style="left:${leftPct}%;width:${Math.min(widthPct, 100)}%;"></span>
          </span>
          <span class="trace-span-status ${statusClass(node.status)}">${escapeHtml(String(node.status || "UNSET").toUpperCase())}</span>
        </button>
      `);
      if (children.length && expanded) {
        children.forEach(visit);
      }
    }
    tree.roots.forEach(visit);
    state.listEl.innerHTML = rows.join("");
    renderDetail(bounds);
  }

  function renderKvRows(obj) {
    const entries = Object.entries(obj || {});
    if (!entries.length) {
      return '<div class="trace-section-empty">None</div>';
    }
    return entries
      .map(([key, value]) => `
        <div class="trace-kv-row">
          <div class="trace-kv-key">${escapeHtml(key)}</div>
          <div class="trace-kv-value">${renderValue(value)}</div>
        </div>
      `)
      .join("");
  }

  function renderEvents(span, bounds) {
    const events = Array.isArray(span.events) ? span.events : [];
    if (!events.length) return '<div class="trace-section-empty">None</div>';
    return events
      .map((event) => {
        const attrs = event.attributes && typeof event.attributes === "object" ? event.attributes : {};
        const ts = event.time_unix_nano ?? event.timestamp_ns ?? event.timestamp;
        return `
          <div class="trace-event-card">
            <div class="trace-event-head">
              <span class="trace-event-name">${escapeHtml(event.name || "event")}</span>
              <span class="trace-event-time">${escapeHtml(formatOffsetNs(ts, bounds.start))}</span>
            </div>
            <div class="trace-event-body">${renderKvRows(attrs)}</div>
          </div>
        `;
      })
      .join("");
  }

  function renderDetail(bounds) {
    const tree = state.currentData?._tree;
    const span = tree?.byId?.get(state.selectedSpanId) || tree?.roots?.[0];
    if (!span) {
      state.detailEl.innerHTML = `
        <div class="trace-detail-empty">
          <div class="trace-empty-title">Select a span</div>
          <div class="trace-empty-copy">Choose a span on the left to inspect its details.</div>
        </div>
      `;
      return;
    }
    state.selectedSpanId = span.span_id;
    state.detailEl.innerHTML = `
      <div class="trace-detail-header">
        <div>
          <div class="trace-detail-title">${escapeHtml(span.name || "(unnamed span)")}</div>
          <div class="trace-detail-subtitle">${escapeHtml(displayKind(span))} · ${escapeHtml(String(span.status || "UNSET").toUpperCase())}</div>
        </div>
        <span class="trace-chip ${statusClass(span.status)}">${escapeHtml(formatDurationMs(span.duration_ms))}</span>
      </div>
      <div class="trace-detail-section">
        <div class="trace-section-title">Overview</div>
        ${renderKvRows({
          "Span ID": span.span_id,
          "Parent Span ID": span.parent_span_id || "",
          "Kind": span.kind || "",
          "Display Kind": displayKind(span),
          "Status": String(span.status || "UNSET").toUpperCase(),
          "Start Offset": formatOffsetNs(span.start_time_ns, bounds.start),
          "End Offset": formatOffsetNs(span.end_time_ns, bounds.start),
          "Duration": formatDurationMs(span.duration_ms),
        })}
      </div>
      <div class="trace-detail-section">
        <div class="trace-section-title">Attributes</div>
        ${renderKvRows(span.attributes || {})}
      </div>
      <div class="trace-detail-section">
        <div class="trace-section-title">Events</div>
        ${renderEvents(span, bounds)}
      </div>
    `;
  }

  function showLoading(meta) {
    state.currentMeta = meta;
    state.currentData = null;
    state.selectedSpanId = null;
    state.expandedIds = new Set();
    state.titleEl.textContent = meta.itemLabel || "Trace";
    state.metaEl.innerHTML = '<span class="trace-chip">Loading trace…</span>';
    state.warningEl.style.display = "none";
    if (meta.traceUrl) {
      state.linkEl.href = meta.traceUrl;
      state.linkEl.style.display = "";
    } else {
      state.linkEl.style.display = "none";
    }
    state.listEl.innerHTML = '<div class="trace-loading-state">Loading trace…</div>';
    state.detailEl.innerHTML = '<div class="trace-detail-empty"><div class="trace-empty-title">Loading</div></div>';
  }

  function showError(message) {
    state.listEl.innerHTML = `<div class="trace-error-state">${escapeHtml(message)}</div>`;
    state.detailEl.innerHTML = `
      <div class="trace-detail-empty">
        <div class="trace-empty-title">Trace unavailable</div>
        <div class="trace-empty-copy">${escapeHtml(message)}</div>
      </div>
    `;
  }

  function openShell() {
    ensureShell();
    state.shell.classList.add("open");
    document.body.classList.add("trace-drawer-open");
  }

  function closeShell() {
    if (!state.shell) return;
    state.shell.classList.remove("open");
    document.body.classList.remove("trace-drawer-open");
  }

  function ensureShell() {
    if (state.shell) return;
    const shell = document.createElement("div");
    shell.className = "trace-drawer-shell";
    shell.innerHTML = `
      <div class="trace-drawer-backdrop" data-trace-close="1"></div>
      <aside class="trace-drawer" role="dialog" aria-modal="true" aria-label="Trace details">
        <div class="trace-drawer-header">
          <div class="trace-drawer-title-wrap">
            <div class="trace-drawer-eyebrow">Trace</div>
            <h3 class="trace-drawer-title">Trace</h3>
            <div class="trace-drawer-meta"></div>
            <div class="trace-drawer-warning" style="display:none;"></div>
          </div>
          <div class="trace-drawer-actions">
            <a class="trace-drawer-link" target="_blank" rel="noopener" style="display:none;">Langfuse ↗</a>
            <button type="button" class="trace-drawer-close" data-trace-close="1" aria-label="Close trace drawer">×</button>
          </div>
        </div>
        <div class="trace-drawer-body">
          <div class="trace-drawer-list"></div>
          <div class="trace-drawer-detail"></div>
        </div>
      </aside>
    `;
    document.body.appendChild(shell);
    state.shell = shell;
    state.listEl = shell.querySelector(".trace-drawer-list");
    state.detailEl = shell.querySelector(".trace-drawer-detail");
    state.titleEl = shell.querySelector(".trace-drawer-title");
    state.metaEl = shell.querySelector(".trace-drawer-meta");
    state.linkEl = shell.querySelector(".trace-drawer-link");
    state.warningEl = shell.querySelector(".trace-drawer-warning");
  }

  async function fetchTrace(meta) {
    if (!meta.endpoint) {
      throw new Error("Missing trace endpoint");
    }
    if (cache.has(meta.endpoint)) {
      return cache.get(meta.endpoint);
    }
    const response = await fetch(meta.endpoint, { credentials: "same-origin" });
    if (!response.ok) {
      const body = await response.text();
      throw new Error(body || `Failed to load trace (${response.status})`);
    }
    const data = await response.json();
    cache.set(meta.endpoint, data);
    return data;
  }

  async function open(meta) {
    if (state.exportMode) return;
    openShell();
    showLoading(meta);
    try {
      const data = await fetchTrace(meta);
      renderSummary(meta, data);
      renderList(meta, data);
    } catch (err) {
      renderSummary(meta, { item: { trace_id: meta.traceId || "", trace_url: meta.traceUrl || "" }, summary: {}, spans: [] });
      showError(err && err.message ? err.message : "Failed to load trace");
    }
  }

  function openFromButton(button) {
    const meta = {
      endpoint: button.getAttribute("data-trace-endpoint") || "",
      itemLabel: button.getAttribute("data-trace-item-label") || button.getAttribute("data-trace-title") || "Trace",
      traceId: button.getAttribute("data-trace-id") || "",
      traceUrl: button.getAttribute("data-trace-url") || "",
    };
    open(meta);
  }

  function handleDocumentClick(event) {
    const closeEl = event.target.closest("[data-trace-close]");
    if (closeEl) {
      event.preventDefault();
      closeShell();
      return;
    }

    const copyEl = event.target.closest("[data-trace-copy]");
    if (copyEl) {
      event.preventDefault();
      const value = copyEl.getAttribute("data-trace-copy") || "";
      if (navigator.clipboard && value) {
        navigator.clipboard.writeText(value).catch(() => {});
      }
      return;
    }

    const traceButton = event.target.closest(".trace-drawer-btn");
    if (traceButton) {
      event.preventDefault();
      openFromButton(traceButton);
      return;
    }

    const toggleEl = event.target.closest("[data-trace-toggle]");
    if (toggleEl) {
      event.preventDefault();
      event.stopPropagation();
      const spanId = toggleEl.getAttribute("data-trace-toggle");
      if (state.expandedIds.has(spanId)) state.expandedIds.delete(spanId);
      else state.expandedIds.add(spanId);
      renderList(state.currentMeta || {}, state.currentData || { spans: [], summary: {}, item: {} });
      return;
    }

    const rowEl = event.target.closest("[data-trace-span-row]");
    if (rowEl) {
      event.preventDefault();
      state.selectedSpanId = rowEl.getAttribute("data-trace-span-row");
      renderList(state.currentMeta || {}, state.currentData || { spans: [], summary: {}, item: {} });
    }
  }

  function handleKeydown(event) {
    if (event.key === "Escape") {
      closeShell();
    }
  }

  function init(options) {
    const nextOptions = options || {};
    state.exportMode = !!nextOptions.exportMode;
    ensureShell();
    if (state.initialized) return;
    document.addEventListener("click", handleDocumentClick);
    document.addEventListener("keydown", handleKeydown);
    state.initialized = true;
  }

  window.QymTraceViewer = {
    init,
    open,
    openFromButton,
    close: closeShell,
  };
})();
