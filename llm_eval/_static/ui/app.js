(() => {
  const state = {
    run: {},
    snapshot: { rows: [], stats: {} },
    filtered: [],
    pageSize: 50,
    page: 1,
  };

  const el = (id) => document.getElementById(id);
  const qs = (sel, root=document) => root.querySelector(sel);
  const fmtTime = (ms) => {
    if (!ms || ms < 1) return '—';
    if (ms < 1000) return `${ms|0} ms`;
    const s = Math.round(ms/1000);
    return `${s}s`;
  };

  function applyFilters() {
    const q = (el('q').value || '').toLowerCase();
    const status = el('status').value;
    let rows = Array.isArray(state.snapshot.rows) ? state.snapshot.rows.slice() : [];
    if (q) {
      rows = rows.filter(r =>
        (r.input_full || '').toLowerCase().includes(q) ||
        (r.output_full || '').toLowerCase().includes(q) ||
        (r.expected_full || '').toLowerCase().includes(q)
      );
    }
    if (status !== 'all') {
      rows = rows.filter(r => (r.status || '') === status);
    }
    if (state.sortKey) {
      rows.sort((a,b) => compareByKey(a,b,state.sortKey,state.sortDir));
    } else {
      rows.sort((a,b) => (a.index||0) - (b.index||0));
    }
    state.filtered = rows;
  }

  // Generic comparator for header-driven sorting
  function compareByKey(a,b,key,dir){
    const isMetric = key.startsWith('metric:');
    let av, bv;
    if (isMetric){
      const name = key.slice(7);
      const idx = (state.metricNames||[]).indexOf(name);
      av = (a.metric_values||[])[idx];
      bv = (b.metric_values||[])[idx];
      const na = Number(av); const nb = Number(bv);
      if (!Number.isNaN(na) && !Number.isNaN(nb)) { av = na; bv = nb; }
      else { av = String(av||''); bv = String(bv||''); }
    } else if (key==='time') { av = a.latency_ms||0; bv = b.latency_ms||0; }
    else if (key==='index') { av = a.index||0; bv = b.index||0; }
    else if (key==='status') { const order = {completed:3,in_progress:2,pending:1,error:0}; av = order[a.status]||-1; bv = order[b.status]||-1; }
    else { av = String(a[key]||''); bv = String(b[key]||''); }
    const cmp = (av>bv) ? 1 : (av<bv) ? -1 : 0;
    return dir==='desc' ? -cmp : cmp;
  }

  function renderMeta() {
    const m = state.run || {};
    el('run-meta').innerHTML = `
      <span class="chips">
        <span class="chip"><span class="label">Dataset</span>${m.dataset_name||'—'}</span>
        <span class="chip"><span class="label">Run</span>${m.run_name||'—'}</span>
        <span class="chip"><span class="label">Concurrency</span>${(m.config&&m.config.max_concurrency)||'—'}</span>
        <span class="chip"><span class="label">Timeout</span>${(m.config&&m.config.timeout)||'—'}s</span>
      </span>
    `;
    const s = state.snapshot.stats || {};
    const completion = Number(s.success_rate||0).toFixed(1);
    const statHTML = `
      <div class="stat-card">
        <div class="stat-icon ok">✓</div>
        <div class="stat-content"><div class="stat-label">Completed</div><div class="stat-value">${s.completed ?? '—'}</div></div>
      </div>
      <div class="stat-card">
        <div class="stat-icon warn">⟳</div>
        <div class="stat-content"><div class="stat-label">In Progress</div><div class="stat-value">${s.in_progress ?? '—'}</div></div>
      </div>
      <div class="stat-card">
        <div class="stat-icon err">✗</div>
        <div class="stat-content"><div class="stat-label">Failed</div><div class="stat-value">${s.failed ?? '—'}</div></div>
      </div>
      <div class="stat-card">
        <div class="stat-icon info">◯</div>
        <div class="stat-content"><div class="stat-label">Pending</div><div class="stat-value">${s.pending ?? '—'}</div></div>
      </div>
      <div class="stat-card">
        <div class="stat-icon ok">%</div>
        <div class="stat-content">
          <div class="stat-label">Completion</div>
          <div class="progress">
            <div class="bar"><div class="bar-fill" style="--pct:${completion}"></div></div>
            <div class="bar-label">${completion}%</div>
          </div>
        </div>
      </div>
    `;
    el('stats').innerHTML = statHTML;
  }

  // Column state and header
  state.columns = [];
  state.sortKey = 'index';
  state.sortDir = 'asc';
  function initColumns() {
    const metrics = (state.metricNames || []).map((name, i) => ({ key: `metric:${name}`, title: name, visible: true, metricIndex: i }));
    const base = [
      { key:'index', title:'#', visible:true, fixed:true, width:64 },
      { key:'status', title:'Status', visible:true },
      { key:'input', title:'Input', visible:true },
      { key:'output', title:'Output', visible:true },
      { key:'expected', title:'Expected', visible:true },
      ...metrics,
      { key:'time', title:'Time', visible:true },
    ];
    state.columns = base;
  }
  function buildHeader() {
    const thead = el('thead');
    const cols = state.columns.filter(c => c.visible);
    thead.innerHTML = `<tr>
      ${cols.map(c => {
        const canDrag = c.key !== 'index';
        const sortable = true; // all columns sortable, including index
        const sortedCls = (state.sortKey===c.key) ? ('sorted-'+state.sortDir) : '';
        const dragHandle = canDrag ? `<span class=\"col-drag\" data-key=\"${c.key}\" draggable=\"true\">⋮⋮</span>` : '';
        const tooltip = canDrag ? 'Click to sort. Drag handle to reorder. Drag edge to resize.' : 'Click to sort. Index cannot be moved.';
        return `<th data-key=\"${c.key}\" class=\"${sortable?'sortable':''} ${sortedCls}\" title=\"${tooltip}\" style=\"${c.width?`width:${c.width}px;min-width:${c.width}px;`:''}\">${dragHandle}${c.title}<span class=\"col-resizer\" data-key=\"${c.key}\"></span></th>`;
      }).join('')}
    </tr>`;
    // Sorting
    cols.forEach(c => {
      const th = thead.querySelector(`th[data-key="${c.key}"]`);
      th && th.addEventListener('click', (e) => {
        if (e.target && (e.target.classList.contains('col-resizer') || e.target.classList.contains('col-drag'))) return;
        if (state.sortKey === c.key) state.sortDir = (state.sortDir === 'asc') ? 'desc' : 'asc';
        else { state.sortKey = c.key; state.sortDir = 'asc'; }
        renderAll();
      });
    });
    // Resize
    thead.querySelectorAll('.col-resizer').forEach(handle => {
      let startX = 0, startW = 0, key = '';
      function onMove(ev){
        const dx = ev.clientX - startX;
        const w = Math.max(48, startW + dx);
        const col = state.columns.find(x => x.key===key); if (col){ col.width = w; }
        const th = thead.querySelector(`th[data-key="${key}"]`);
        if (th){ th.style.width = w+'px'; th.style.minWidth = w+'px'; }
      }
      function onUp(){ document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp); }
      handle.addEventListener('mousedown', (ev) => {
        key = handle.getAttribute('data-key');
        const th = thead.querySelector(`th[data-key="${key}"]`);
        startW = (th && th.getBoundingClientRect().width) || 120;
        startX = ev.clientX;
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
        ev.preventDefault(); ev.stopPropagation();
      });
    });
    // Drag-and-drop reorder via handle
    thead.querySelectorAll('.col-drag').forEach(handle => {
      const key = handle.getAttribute('data-key');
      if (key === 'index') return;
      handle.addEventListener('dragstart', (e) => { e.dataTransfer.setData('text/plain', key); });
    });
    thead.querySelectorAll('th').forEach(th => {
      th.addEventListener('dragover', (e) => { e.preventDefault(); });
      th.addEventListener('drop', (e) => {
        e.preventDefault();
        const toKey = th.getAttribute('data-key');
        const fromKey = e.dataTransfer.getData('text/plain');
        if (!fromKey || fromKey===toKey || toKey==='index') return;
        const full = state.columns.slice();
        const fromIdx = full.findIndex(c=>c.key===fromKey);
        const toIdx = full.findIndex(c=>c.key===toKey);
        if (fromIdx<0 || toIdx<0) return;
        const [moved] = full.splice(fromIdx,1);
        full.splice(toIdx,0,moved);
        state.columns = full;
        buildHeader();
        buildColumnMenu();
        renderTable();
      });
    });
  }

  function renderPanels() {
    const rows = state.filtered;
    const completed = rows.filter(r => (r.status||'')==='completed' && r.latency_ms);
    const lats = completed.map(r => r.latency_ms||0).sort((a,b)=>a-b);
    const q = (p) => {
      if (!lats.length) return 0;
      const pos = (lats.length - 1) * p;
      const base = Math.floor(pos);
      const rest = pos - base;
      return lats[base+1] !== undefined ? (lats[base] + rest*(lats[base+1]-lats[base])) : lats[base];
    };
    const mean = lats.length ? (lats.reduce((a,b)=>a+b,0)/lats.length) : 0;
    el('lat-mean').textContent = fmtTime(mean);
    el('lat-p50').textContent = fmtTime(q(0.5));
    el('lat-p90').textContent = fmtTime(q(0.9));
    el('lat-p99').textContent = fmtTime(q(0.99));

    const errors = rows.filter(r => (r.status||'')==='error');
    const classify = (r) => {
      const t = (r.output_full||'').toLowerCase();
      if (t.includes('timeout')) return 'timeout';
      if (t.includes('error:')) return 'runtime';
      return 'unknown';
    };
    const metricErr = rows.filter(r => (r.metric_values||[]).some(v => String(v||'').toLowerCase() === 'error' || String(v||'').toLowerCase() === 'n/a')).length;
    el('err-timeout').textContent = String(errors.filter(r=>classify(r)==='timeout').length);
    el('err-runtime').textContent = String(errors.filter(r=>classify(r)==='runtime').length);
    el('err-unknown').textContent = String(Math.max(0, errors.length - errors.filter(r=>classify(r)==='timeout').length - errors.filter(r=>classify(r)==='runtime').length));
    el('err-metric').textContent = String(metricErr);
  }

  function renderTable() {
    const pageSize = state.pageSize;
    const total = state.filtered.length;
    const totalPages = Math.max(1, Math.ceil(total/pageSize));
    if (state.page > totalPages) state.page = totalPages;
    const start = (state.page-1)*pageSize;
    const end = Math.min(start+pageSize, total);
    const rows = state.filtered.slice(start, end);
    el('pageinfo').textContent = `Page ${state.page} of ${totalPages} | ${start+1}-${end} of ${total}`;
    const visible = state.columns.filter(c=>c.visible);
    const html = rows.map(r => {
      const st = r.status||'pending';
      function tdMetricByIndex(i){
        const v = (r.metric_values||[])[i];
        const raw = (v ?? '').toString();
        const t = raw.trim().toLowerCase();
        let cls = '';
        if (t === '✓' || t === 'true' || t === 'yes' || t === '1' || t === '1.0') cls = 'metric-yes';
        else if (t === '✗' || t === 'false' || t === 'no' || t === '0' || t === '0.0') cls = 'metric-no';
        else if (t === 'n/a' || t === 'pending' || t === 'error' || t === 'computing...') cls = 'metric-na';
        else { const n = Number(raw); if (!Number.isNaN(n)) { if (Math.abs(n-1)<1e-9) cls='metric-yes'; else if (Math.abs(n)<1e-9) cls='metric-no'; } }
        return `<td class="${cls}">${raw}</td>`;
      }
      const tds = visible.map(c => {
        if (c.key==='index') return `<td>${(r.index||0)+1}</td>`;
        if (c.key==='status') return `<td><span class="badge ${st}">${st.replace('_',' ')}</span></td>`;
        if (c.key==='input') return `<td class="ellipsis" title="${r.input_full||''}">${r.input||''}</td>`;
        if (c.key==='output') return `<td class="ellipsis" title="${r.output_full||''}">${r.output||''}</td>`;
        if (c.key==='expected') return `<td class="ellipsis" title="${r.expected_full||''}">${r.expected||''}</td>`;
        if (c.key==='time') return `<td>${r.time||''}</td>`;
        if (c.key.startsWith('metric:')) { const name=c.key.slice(7); const idx=(state.metricNames||[]).indexOf(name); return tdMetricByIndex(idx); }
        return `<td></td>`;
      }).join('');
      return `<tr data-raw-index="${r.index||0}">${tds}</tr>`;
    }).join('');
    el('rows').innerHTML = html;
    // Empty state
    const es = document.getElementById('empty-state');
    if (es) es.style.display = rows.length ? 'none' : 'block';

    // Delegated row click for drawer (robust across re-renders)
    const rowsEl = el('rows');
    if (!rowsEl._delegatedClick) {
      rowsEl.addEventListener('click', (ev) => {
        const tr = ev.target.closest('tr');
        if (!tr) return;
        const rawIdx = Number(tr.getAttribute('data-raw-index'))||0;
        let row = (state.rowByIndex && state.rowByIndex.get(rawIdx)) || null;
        if (!row) { row = (state.snapshot.rows||[]).find(rr => Number(rr.index)===rawIdx) || null; }
        if (row) openDrawer(row);
      });
      rowsEl._delegatedClick = true;
    }
  }

  function renderAll() {
    applyFilters();
    renderMeta();
    renderPanels();
    buildHeader();
    renderTable();
  }

  // Controls
  el('q').addEventListener('input', () => { state.page = 1; renderAll(); });
  el('status').addEventListener('change', () => { state.page = 1; renderAll(); });
  // Removed order dropdown; sorting is header-driven
  el('page-size').addEventListener('change', () => { state.pageSize = Number(el('page-size').value)||50; state.page = 1; renderAll(); });
  el('prev').addEventListener('click', () => { state.page = Math.max(1, state.page-1); renderTable(); });
  el('next').addEventListener('click', () => { state.page = state.page+1; renderTable(); });
  // Using Material header style by default (B)
  function buildColumnMenu(){
    const menu = el('col-menu');
    if (!menu) return;
    const cols = state.columns.slice();
    menu.innerHTML = cols.map(c => `
      <label title="Toggle column visibility"><input type="checkbox" data-key="${c.key}" ${c.visible?'checked':''} ${c.fixed?'disabled':''}/> ${c.title}</label>
    `).join('');
    menu.querySelectorAll('input[type=checkbox]').forEach(cb => {
      cb.addEventListener('change', () => {
        const key = cb.getAttribute('data-key');
        const col = state.columns.find(x=>x.key===key); if (!col) return;
        col.visible = cb.checked || !!col.fixed;
        buildHeader(); renderTable();
      });
    });
    const dd = el('col-dropdown');
    const btn = el('col-menu-btn');
    if (btn && dd){
      btn.addEventListener('click', () => {
        const open = dd.classList.toggle('open');
        btn.setAttribute('aria-expanded', open? 'true':'false');
      });
      document.addEventListener('click', (e)=>{
        if (!dd.contains(e.target)) dd.classList.remove('open');
      });
    }
  }

  // Drawer and diff
  const overlay = el('drawer-overlay');
  const btnClose = el('drawer-close');
  const diffToggle = el('diff-toggle');
  function stripMarkup(text){
    try {
      return String(text||'').replace(/\[(?:\/)?(?:dim|red|yellow)\]/g, '');
    } catch { return String(text||''); }
  }
  function classifyMetric(raw){
    const t = String(raw||'').trim().toLowerCase();
    if (t === '✓' || t === 'true' || t === 'yes' || t === '1' || t === '1.0') return 'metric-yes';
    if (t === '✗' || t === 'false' || t === 'no' || t === '0' || t === '0.0') return 'metric-no';
    if (t === 'n/a' || t === 'pending' || t === 'error' || t === 'computing...') return 'metric-na';
    const n = Number(raw);
    if (!Number.isNaN(n)) { if (Math.abs(n-1)<1e-9) return 'metric-yes'; if (Math.abs(n)<1e-9) return 'metric-no'; }
    return '';
  }
  function diffWords(a, b) {
    try {
      const wa = stripMarkup(a).split(/(\s+)/);
      const wb = stripMarkup(b).split(/(\s+)/);
      const n = Math.max(wa.length, wb.length);
      let outA = '', outB = '';
      for (let i=0;i<n;i++) {
        const ta = wa[i]||''; const tb = wb[i]||'';
        if (ta === tb) { outA += ta; outB += tb; }
        else { outA += `<del>${ta}</del>`; outB += `<ins>${tb}</ins>`; }
      }
      return { a: outA, b: outB };
    } catch { return { a: a||'', b: b||'' }; }
  }
  function openDrawer(row) {
    qs('#drawer-title').textContent = `Row ${(Number(row.index)||0)+1}`;
    const $in = el('drawer-input'), $out = el('drawer-output'), $exp = el('drawer-expected');
    const setRaw = () => {
      $in.textContent = stripMarkup(row.input_full || row.input || '');
      $out.classList.remove('diff');
      $exp.classList.remove('diff');
      $out.textContent = stripMarkup(row.output_full || row.output || '');
      $exp.textContent = stripMarkup(row.expected_full || row.expected || '');
    };
    const setDiff = () => {
      const d = diffWords(row.output_full || row.output || '', row.expected_full || row.expected || '');
      $in.textContent = stripMarkup(row.input_full || row.input || '');
      $out.innerHTML = d.a; $out.classList.add('diff');
      $exp.innerHTML = d.b; $exp.classList.add('diff');
    };
    const apply = () => diffToggle.checked ? setDiff() : setRaw();
    diffToggle.onchange = apply;
    apply();
    // Trace info
    const $trace = el('drawer-trace');
    const $btnLF = el('drawer-open-langfuse');
    const tid = row.trace_id || '';
    let turl = row.trace_url || '';
    if (!turl && tid) {
      const host = (state.langfuseHost || 'https://cloud.langfuse.com').replace(/\/$/, '');
      const pid = state.langfuseProjectId || '';
      if (pid) turl = `${host}/project/${pid}/traces/${tid}`;
    }
    if ($trace){
      if (turl) {
        $trace.innerHTML = `<a href="${turl}" target="_blank" rel="noopener">${tid || '(open trace)'}</a>`;
      } else if (tid) {
        $trace.textContent = tid;
      } else {
        $trace.innerHTML = '<span class="muted">N/A</span>';
      }
    }
    if ($btnLF){
      if (turl) { $btnLF.href = turl; $btnLF.style.display = 'inline-block'; }
      else if (state.langfuseHost && state.langfuseProjectId) {
        const host = String(state.langfuseHost).replace(/\/$/, '');
        $btnLF.href = `${host}/project/${state.langfuseProjectId}/traces`;
        $btnLF.style.display = 'inline-block';
      } else { $btnLF.style.display = 'none'; }
    }
    // Time
    const $time = el('drawer-time');
    if ($time) {
      const ms = Number(row.latency_ms)||0;
      $time.textContent = ms ? humanDuration(ms) : stripMarkup(row.time || '');
    }
    // Metrics list
    const names = state.metricNames || [];
    const vals = row.metric_values || [];
    const $ml = el('drawer-metrics');
    if ($ml){
      const items = names.map((n, i) => {
        const v = vals[i];
        const cls = classifyMetric(v);
        const txt = (v==null||v==='') ? '—' : String(v);
        return `<div class="metric-row"><span class="name">${n}</span><span class="value ${cls}">${txt}</span></div>`;
      }).join('');
      $ml.innerHTML = items || '<div class="muted">No metrics</div>';
    }
    overlay.classList.add('show');
    overlay.hidden = false;
    try { document.body.classList.add('no-scroll'); } catch {}
  }
  function closeDrawer(){
    overlay.classList.remove('show');
    overlay.hidden = true;
    try { document.body.classList.remove('no-scroll'); } catch {}
  }
  btnClose.addEventListener('click', closeDrawer);
  overlay.addEventListener('click', (e)=>{ if (e.target === overlay) closeDrawer(); });

  // Bootstrap
  fetch('api/run').then(r=>r.json()).then(run => {
    state.run = run;
    state.metricNames = run.metric_names || [];
    state.langfuseHost = run.langfuse_host || 'https://cloud.langfuse.com';
    state.langfuseProjectId = run.langfuse_project_id || '';
    try {
      const ds = run.dataset_name || 'Dataset';
      const rn = run.run_name || 'Run';
      document.title = `LLM Eval – ${ds} / ${rn}`;
    } catch {}
    // Apply Material header style (B) by default
    try {
      document.body.setAttribute('data-header-style', 'b');
      try { localStorage.setItem('headerStyle', 'b'); } catch {}
    } catch {}
    initColumns();
    renderMeta();
    buildHeader();
    buildColumnMenu();
  }).catch(()=>{});
  fetch('api/snapshot').then(r=>r.json()).then(snap => { state.snapshot = snap || { rows:[], stats:{} }; renderAll(); }).catch(()=>{});
  // Build initial row map if available
  try {
    const map = new Map();
    (state.snapshot.rows||[]).forEach(r => map.set(Number(r.index)||0, r));
    state.rowByIndex = map;
  } catch {}

  // Live updates via SSE
  try {
    const es = new EventSource('api/rows/stream');
    es.addEventListener('snapshot', (evt) => {
      try {
        const data = JSON.parse(evt.data || '{}');
        state.snapshot = data;
        // Rebuild fast row index map for robust clicks
        try {
          const map = new Map();
          (state.snapshot.rows||[]).forEach(r => map.set(Number(r.index)||0, r));
          state.rowByIndex = map;
        } catch {}
        // Ensure header/columns exist if events arrive early
        if (!state.columns || state.columns.length === 0) {
          initColumns();
          buildHeader();
          buildColumnMenu();
        }
        renderAll();
      } catch (e) {
        console.error('SSE snapshot render error', e);
      }
    });
    es.addEventListener('done', () => { /* no-op */ });
  } catch (e) {}
})();
