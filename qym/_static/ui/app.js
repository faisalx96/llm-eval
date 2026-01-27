(() => {
  // Base URL handling for proxy/subpath compatibility
  // Find the base URL by looking for '/run/' in the pathname
  const BASE_URL = (() => {
    const loc = window.location;
    const pathname = loc.pathname;
    const runIndex = pathname.indexOf('/run/');
    if (runIndex >= 0) {
      // Base is everything BEFORE /run/, plus trailing slash
      // runIndex is the position of '/' in '/run/', so substring(0, runIndex) gives us the prefix
      return loc.origin + pathname.substring(0, runIndex) + '/';
    }
    // Fallback: use directory of current path
    let base = pathname;
    if (!base.endsWith('/')) {
      base = base.substring(0, base.lastIndexOf('/') + 1) || '/';
    }
    return loc.origin + base;
  })();

  function apiUrl(path) {
    const cleanPath = path.replace(/^\.?\.?\//, '');
    return BASE_URL + cleanPath;
  }

  // Detect if we're in dashboard mode (viewing historical run)
  const isDashboardMode = window.location.pathname.includes('/run/');
  // Extract file path from URL (preferred) or fallback to sessionStorage
  const getDashboardRunFile = () => {
    if (!isDashboardMode) return null;
    // Try to extract from URL first: /run/{encodedFilePath}
    const urlPath = window.location.pathname;
    const runIndex = urlPath.indexOf('/run/');
    if (runIndex >= 0) {
      let filePath = urlPath.slice(runIndex + 5); // Remove everything up to and including '/run/'
      if (filePath) {
        // Decode URL encoding - may need multiple passes if double-encoded
        try {
          let decoded = decodeURIComponent(filePath);
          while (decoded !== filePath && decoded.includes('%')) {
            filePath = decoded;
            decoded = decodeURIComponent(filePath);
          }
          return decoded;
        } catch (e) {
          console.error('[qym] Failed to decode file path:', e);
          return filePath;
        }
      }
    }
    // Fallback to sessionStorage
    return sessionStorage.getItem('dashboardRunFile');
  };
  const dashboardRunFile = getDashboardRunFile();

  const state = {
    run: {},
    snapshot: { rows: [], stats: {} },
    filtered: [],
    pageSize: 50,
    page: 1,
    isDashboardMode,
  };

  const el = (id) => document.getElementById(id);
  const qs = (sel, root=document) => root.querySelector(sel);
  const fmtTime = (ms) => {
    if (!ms || ms < 1) return '—';
    if (ms < 1000) return `${ms|0} ms`;
    const s = Math.round(ms/1000);
    return `${s}s`;
  };

  // Best-effort metric name discovery from a snapshot
  function deriveMetricNamesFromSnapshot(snap){
    try {
      if (Array.isArray(snap && snap.metric_names) && snap.metric_names.length){
        return snap.metric_names.slice();
      }
      const rows = (snap && snap.rows) || [];
      if (!rows.length) return null;
      // Prefer a row that actually has metric_meta keys
      let r0 = null;
      for (let i=0;i<rows.length;i++){
        const rr = rows[i]||{};
        if (rr.metric_meta && Object.keys(rr.metric_meta||{}).length){ r0 = rr; break; }
      }
      if (!r0) r0 = rows[0] || null;
      if (!r0) return null;
      const meta = r0.metric_meta || {};
      const metaNames = Object.keys(meta||{});
      if (metaNames && metaNames.length) return metaNames;
      const mvals = Array.isArray(r0.metric_values) ? r0.metric_values : [];
      if (mvals.length) return Array.from({length: mvals.length}, (_,i)=> `metric_${i+1}`);
      return null;
    } catch { return null; }
  }

  // Merge any newly discovered names into state.metricNames and refresh columns
  function syncMetricNamesFromSnapshot(snap){
    try {
      const found = deriveMetricNamesFromSnapshot(snap) || [];
      const have = Array.isArray(state.metricNames) ? state.metricNames.slice() : [];
      const set = new Set(have);
      let changed = false;
      for (const n of found){ if (!set.has(n)) { have.push(n); set.add(n); changed = true; } }
      if (changed){
        state.metricNames = have;
        initColumns();
        buildHeader();
        buildColumnMenu();
        renderMetricCharts();
      }
    } catch {}
  }
  // (No global preferences; keep UI minimal)
  // Human-readable h/m/s formatter for durations
  const humanDuration = (ms) => {
    if (!ms || ms < 1) return '—';
    const total = Math.round(ms/1000);
    const h = Math.floor(total/3600);
    const m = Math.floor((total%3600)/60);
    const s = total % 60;
    if (h) return `${h}h ${m}m ${s}s`;
    if (m) return `${m}m ${s}s`;
    return `${s}s`;
  };

  function applyFilters() {
    const q = (el('q').value || '').toLowerCase();
    const status = state.filterStatus || (el('status') ? el('status').value : 'all');
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
      const parts = key.split(':');
      const name = parts[1];
      if (parts.length === 2){
        const idx = (state.metricNames||[]).indexOf(name);
        av = (a.metric_values||[])[idx];
        bv = (b.metric_values||[])[idx];
      } else {
        const field = parts.slice(2).join(':');
        const ma = (a.metric_meta && a.metric_meta[name]) || {};
        const mb = (b.metric_meta && b.metric_meta[name]) || {};
        av = ma[field];
        bv = mb[field];
      }
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
    const prevTimer = (() => { try { const n = document.getElementById('run-timer'); return n && n.textContent ? n.textContent : '—'; } catch { return '—'; } })();
    el('run-meta').innerHTML = `
      <span class="chips">
        <span class="chip"><span class="label">Dataset</span>${m.dataset_name||'—'}</span>
        <span class="chip"><span class="label">Run</span>${m.run_name||'—'}</span>
        <span class="chip"><span class="label">Concurrency</span>${(m.config&&m.config.max_concurrency)||'—'}</span>
        <span class="chip"><span class="label">Timeout</span>${(m.config&&m.config.timeout)||'—'}s</span>
        <span class="chip"><span class="label">Elapsed</span><span id="run-timer">${prevTimer}</span></span>
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
      <div class="stat-card completion">
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

  function renderQuickBar(){
    const container = el('quickbar');
    if (!container) return;
    const fmtShort = (ms) => {
      if (!ms || ms < 1) return '—';
      if (ms < 1000) return `${ms|0}<span class="unit">ms</span>`;
      const s = Math.round(ms/1000);
      return `${s}<span class="unit">s</span>`;
    };
    const rows = (state.snapshot && state.snapshot.rows) || [];
    const completed = rows.filter(r => (r.status||'')==='completed' && r.latency_ms!=null);
    const lats = completed.map(r => r.latency_ms||0).sort((a,b)=>a-b);
    const min = lats.length ? lats[0] : 0;
    const max = lats.length ? lats[lats.length-1] : 0;
    const q = (p) => {
      if (!lats.length) return 0;
      const pos = (lats.length - 1) * p; const base = Math.floor(pos); const rest = pos - base;
      return lats[base+1] !== undefined ? (lats[base] + rest*(lats[base+1]-lats[base])) : lats[base];
    };
    const errors = rows.filter(r => (r.status||'')==='error');
    const classify = (r) => {
      const t = (r.output_full||'').toLowerCase();
      if (t.includes('timeout')) return 'timeout';
      if (t.includes('error:')) return 'runtime';
      return 'unknown';
    };
    const errTimeout = errors.filter(r=>classify(r)==='timeout').length;
    const errRuntime = errors.filter(r=>classify(r)==='runtime').length;
    const errUnknown = errors.filter(r=>classify(r)==='unknown').length;
    const metricErr = rows.filter(r => (r.metric_values||[]).some(v => String(v||'').toLowerCase() === 'error' || String(v||'').toLowerCase() === 'n/a')).length;

    container.innerHTML = `
      <div class="qb-group">
        <span class="qb-title">⏱ Latency</span>
        <span class="qb-item"><span class="lbl">Min</span><span class="val">${fmtShort(min)}</span></span>
        <span class="qb-item"><span class="lbl">P50</span><span class="val">${fmtShort(q(0.5))}</span></span>
        <span class="qb-item"><span class="lbl">P90</span><span class="val">${fmtShort(q(0.9))}</span></span>
        <span class="qb-item"><span class="lbl">P99</span><span class="val">${fmtShort(q(0.99))}</span></span>
        <span class="qb-item"><span class="lbl">Max</span><span class="val">${fmtShort(max)}</span></span>
      </div>
      <span class="qb-sep"></span>
      <div class="qb-group">
        <span class="qb-title">⚠ Errors</span>
        <span class="qb-badge err">Timeout <b>${errTimeout}</b></span>
        <span class="qb-badge warn">Runtime <b>${errRuntime}</b></span>
        <span class="qb-badge neutral">Unknown <b>${errUnknown}</b></span>
        <span class="qb-badge info">Metric <b>${metricErr}</b></span>
      </div>
    `;
  }

  // Column state and header
  state.columns = [];
  state.sortKey = 'index';
  state.sortDir = 'asc';
  function initColumns() {
    const metrics = (state.metricNames || []).map((name, i) => ({ key: `metric:${name}`, title: `${name}_score`, visible: true, metricIndex: i }));
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
    ensureMetricSubColumns();
  }
  function ensureMetricSubColumns(){
    try {
      const sub = collectMetricSubFields();
      if (!sub) return;
      const existing = new Set(state.columns.map(c => c.key));
      const newCols = [];
      state.columns.forEach(c => {
        newCols.push(c);
        if (c.key.startsWith('metric:') && c.key.split(':').length===2){
          const name = c.key.split(':')[1];
          const fields = sub[name] || [];
          fields.forEach(f => {
            const k = `metric:${name}:${f}`;
            if (!existing.has(k)){
              newCols.push({ key: k, title: `${name}_${f}`, visible: true });
              existing.add(k);
            }
          });
        }
      });
      state.columns = newCols;
    } catch {}
  }
  function collectMetricSubFields(){
    const out = {};
    try {
      const rows = (state.snapshot && state.snapshot.rows) || [];
      const names = state.metricNames || [];
      names.forEach(n => out[n] = new Set());
      rows.forEach(r => {
        const mm = r.metric_meta || {};
        Object.keys(mm||{}).forEach(name => {
          const obj = mm[name] || {};
          Object.keys(obj).forEach(field => out[name] && out[name].add(field));
        });
      });
      const res = {};
      Object.keys(out).forEach(name => { res[name] = Array.from(out[name]||[]); });
      return res;
    } catch { return null; }
  }
  function buildHeader() {
    const thead = el('thead');
    ensureMetricSubColumns();
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
    const rows = (state.snapshot && state.snapshot.rows) || [];
    const completed = rows.filter(r => (r.status||'')==='completed' && r.latency_ms != null);
    const lats = completed.map(r => r.latency_ms||0).sort((a,b)=>a-b);
    const min = lats.length ? lats[0] : 0;
    const max = lats.length ? lats[lats.length-1] : 0;
    const q = (p) => {
      if (!lats.length) return 0;
      const pos = (lats.length - 1) * p;
      const base = Math.floor(pos);
      const rest = pos - base;
      return lats[base+1] !== undefined ? (lats[base] + rest*(lats[base+1]-lats[base])) : lats[base];
    };
    const minEl = el('lat-min'); if (minEl) minEl.textContent = fmtTime(min);
    const maxEl = el('lat-max'); if (maxEl) maxEl.textContent = fmtTime(max);
    const p50El = el('lat-p50'); if (p50El) p50El.textContent = fmtTime(q(0.5));
    const p90El = el('lat-p90'); if (p90El) p90El.textContent = fmtTime(q(0.9));
    const p99El = el('lat-p99'); if (p99El) p99El.textContent = fmtTime(q(0.99));

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
      function tdMetricField(name, field){
        const mm = (r.metric_meta && r.metric_meta[name]) || {};
        const v = mm[field];
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
        if (c.key.startsWith('metric:')) {
          const parts = c.key.split(':');
          const name = parts[1];
          if (parts.length===2){ const idx=(state.metricNames||[]).indexOf(name); return tdMetricByIndex(idx); }
          const field = parts.slice(2).join(':');
          return tdMetricField(name, field);
        }
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
    renderQuickBar();
    renderMetricCharts();
    buildHeader();
    buildColumnMenu();
    renderTable();
  }

  // Controls
  // Filters
  const qEl = el('q'); if (qEl) qEl.addEventListener('input', () => { state.page = 1; renderAll(); });
  const statusSel = el('status'); if (statusSel) statusSel.addEventListener('change', () => { state.filterStatus = statusSel.value || 'all'; state.page = 1; renderAll(); });
  // Removed order dropdown; sorting is header-driven
  const pageSizeSel = el('page-size'); if (pageSizeSel) pageSizeSel.addEventListener('change', () => { state.pageSize = Number(pageSizeSel.value)||50; state.page = 1; renderAll(); });
  const prevBtn = el('prev'); if (prevBtn) prevBtn.addEventListener('click', () => { state.page = Math.max(1, state.page-1); renderTable(); });
  const nextBtn = el('next'); if (nextBtn) nextBtn.addEventListener('click', () => { state.page = state.page+1; renderTable(); });
  // Using Material header style by default (B)
  function buildColumnMenu(){
    // Ensure dynamic metric sub-columns are present before building menu
    ensureMetricSubColumns();
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
      if (!btn._wired) {
        btn.addEventListener('click', (ev) => {
          ev.stopPropagation();
          closeAllDropdowns(dd);
          const open = dd.classList.toggle('open');
          btn.setAttribute('aria-expanded', open? 'true':'false');
        });
        btn._wired = true;
      }
      if (!state._docDropdownWired) {
        document.addEventListener('click', (e)=>{
          const within = e.target && e.target.closest ? e.target.closest('.dropdown') : null;
          document.querySelectorAll('.dropdown.open').forEach(openDd => {
            if (openDd !== within) {
              openDd.classList.remove('open');
              const b = openDd.querySelector('.dropdown-toggle');
              if (b) b.setAttribute('aria-expanded', 'false');
            }
          });
        });
        state._docDropdownWired = true;
      }
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
  function escapeAttr(text){
    return String(text ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
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
    // Copy helpers
    function copyText(txt){
      try { if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(txt); return true; } } catch {}
      try {
        const ta = document.createElement('textarea');
        ta.value = txt; ta.style.position='fixed'; ta.style.opacity='0';
        document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); return true;
      } catch { return false; }
    }
    function wireCopy(id, getter){
      const b = el(id); if (!b) return;
      b.onclick = () => {
        const ok = copyText(getter());
        const prev = b.textContent; b.textContent = ok? '✓' : '!';
        setTimeout(()=>{ b.textContent = prev; }, 900);
      };
    }
    wireCopy('copy-input', () => stripMarkup(row.input_full || row.input || ''));
    wireCopy('copy-output', () => stripMarkup(row.output_full || row.output || ''));
    wireCopy('copy-expected', () => stripMarkup(row.expected_full || row.expected || ''));
    wireCopy('copy-trace', () => {
      const tid = row.trace_id || '';
      let turl = row.trace_url || '';
      if (!turl && tid) {
        const host = (state.langfuseHost || 'https://cloud.langfuse.com').replace(/\/$/, '');
        const pid = state.langfuseProjectId || '';
        if (pid) turl = `${host}/project/${pid}/traces/${tid}`;
      }
      return turl || tid || '';
    });
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
    const meta = row.metric_meta || {};
    const $ml = el('drawer-metrics');
    if ($ml){
      const canEditMetrics = Boolean(state.isDashboardMode && ((state.run && state.run.file_path) || dashboardRunFile));
      const items = names.map((n, i) => {
        const v = vals[i];
        const cls = classifyMetric(v);
        const txt = (v==null||v==='') ? '—' : String(v);
        const extrasObj = meta[n] || {};
        const modifiedRaw = extrasObj.modified;
        const originalRaw = extrasObj.original_score;
        const hasOriginal = !(originalRaw == null || originalRaw === '');
        const modified = String(modifiedRaw || '').toLowerCase() === 'true';
        const modifiedNote = hasOriginal
          ? `<div class="metric-modified">${modified ? 'Modified' : 'Original'} · original: ${escapeAttr(String(originalRaw))}</div>`
          : '';
        const extras = Object.keys(extrasObj).filter(k => !['modified','original_score'].includes(k)).map(k => {
          const vv = extrasObj[k];
          const c = classifyMetric(vv);
          const t = (vv==null||vv==='') ? '—' : String(vv);
          return `<div class="metric-row"><span class="name">${n}_${k}</span><span class="value ${c}">${t}</span></div>`;
        }).join('');
        if (canEditMetrics){
          const val = (v==null||v==='') ? '' : String(v);
          const header = `<div class="metric-row metric-edit-row">
            <span class="name">${n}_score</span>
            <div class="metric-edit-controls">
              <input class="metric-edit-input" type="text" value="${escapeAttr(val)}" data-metric="${escapeAttr(n)}" />
              <button class="metric-edit-save" data-metric="${escapeAttr(n)}">Save</button>
              <span class="metric-edit-status" aria-live="polite"></span>
            </div>
          </div>`;
          return `<div class="metric-edit-block" data-metric="${escapeAttr(n)}">${header}${modifiedNote}${extras}</div>`;
        }
        const header = `<div class="metric-row"><span class="name">${n}_score</span><span class="value ${cls}">${txt}</span></div>`;
        return header + modifiedNote + extras;
      }).join('');
      $ml.innerHTML = items || '<div class="muted">No metrics</div>';
      if (canEditMetrics){
        $ml.querySelectorAll('.metric-edit-save').forEach(btn => {
          btn.onclick = async () => {
            const block = btn.closest('.metric-edit-block');
            const input = block ? block.querySelector('.metric-edit-input') : null;
            const status = block ? block.querySelector('.metric-edit-status') : null;
            const metric = btn.dataset.metric || (input ? input.dataset.metric : '');
            const filePath = (state.run && state.run.file_path) || dashboardRunFile || '';
            const rowIndex = Number(row.index) || 0;
            if (!filePath || !metric || !input){
              if (status) status.textContent = 'Unavailable';
              return;
            }
            btn.disabled = true;
            if (status) status.textContent = 'Saving...';
            try {
              const result = await updateMetricScore(filePath, rowIndex, metric, input.value);
              if (result && result.row){
                applyUpdatedRow(result.row);
                setTimeout(() => openDrawer(result.row), 200);
              }
              if (status) status.textContent = 'Saved';
              setTimeout(() => { if (status) status.textContent = ''; }, 1500);
            } catch (err) {
              if (status) status.textContent = 'Error';
            } finally {
              btn.disabled = false;
            }
          };
        });
      }
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

  // Header tools: export only
  const expBtn = el('export-btn');
  if (expBtn) expBtn.addEventListener('click', exportCSV);

  async function updateMetricScore(filePath, rowIndex, metricName, newScore){
    const res = await fetch(apiUrl('api/runs/update_metric'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        file_path: filePath,
        row_index: rowIndex,
        metric_name: metricName,
        new_score: newScore,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) {
      throw new Error(data.error || 'Failed to update metric');
    }
    return data;
  }

  function applyUpdatedRow(updatedRow){
    try {
      const idx = Number(updatedRow.index) || 0;
      const rows = state.snapshot.rows || [];
      if (idx >= 0 && idx < rows.length) {
        rows[idx] = updatedRow;
      } else {
        const pos = rows.findIndex(r => Number(r.index) === idx);
        if (pos >= 0) rows[pos] = updatedRow;
      }
      try {
        state.rowByIndex = state.rowByIndex || new Map();
        state.rowByIndex.set(idx, updatedRow);
      } catch {}
      updateMetricSeriesFromSnapshot(state.snapshot);
      renderMetricCharts();
      renderQuickBar();
      renderAll();
    } catch {}
  }

  function csvEscape(v){
    const s = (v==null) ? '' : String(v);
    if (s.includes('"') || s.includes(',') || s.includes('\n')) return `"${s.replace(/"/g,'""')}"`;
    return s;
  }

  // Toolbar simple dropdowns (Status, Rows)
  function closeAllDropdowns(except){
    try {
      document.querySelectorAll('.dropdown.open').forEach(dd => {
        if (except && dd === except) return;
        dd.classList.remove('open');
        const btn = dd.querySelector('.dropdown-toggle');
        if (btn) btn.setAttribute('aria-expanded', 'false');
      });
    } catch {}
  }
  function wireSimpleMenu(btnId, menuId, items, onSelect){
    const btn = el(btnId); const menu = el(menuId);
    if (!btn || !menu) return;
    menu.innerHTML = items.map(it => `<label><input type="radio" name="${menuId}" value="${it.value}"> ${it.label}</label>`).join('');
    const openCls = () => btn.parentElement && btn.parentElement.classList.toggle('open');
    btn.addEventListener('click', (ev) => { ev.stopPropagation(); closeAllDropdowns(btn.parentElement); openCls(); btn.setAttribute('aria-expanded', btn.parentElement.classList.contains('open') ? 'true':'false'); });
    document.addEventListener('click', (e)=>{ if (!btn.parentElement.contains(e.target)) { btn.parentElement.classList.remove('open'); btn.setAttribute('aria-expanded', 'false'); } });
    menu.querySelectorAll('input[type=radio]').forEach(r => {
      r.addEventListener('change', () => { onSelect(r.value, r); btn.parentElement.classList.remove('open'); });
    });
  }

  function initToolbarMenus(){
    // Status
    const statusItems = [
      {value:'all', label:'All'},
      {value:'completed', label:'Completed'},
      {value:'in_progress', label:'In Progress'},
      {value:'error', label:'Failed'},
      {value:'pending', label:'Pending'},
    ];
    wireSimpleMenu('status-menu-btn','status-menu', statusItems, (val) => {
      state.filterStatus = val || 'all';
      const s = el('status'); if (s) s.value = state.filterStatus;
      const btn = el('status-menu-btn'); if (btn) btn.textContent = `${statusItems.find(i=>i.value===val).label} ▾`;
      state.page = 1; renderAll();
    });
    // set initial status button label
    try {
      const cur = state.filterStatus || (el('status') ? el('status').value : 'all');
      const btn = el('status-menu-btn'); if (btn) btn.textContent = `${statusItems.find(i=>i.value===cur).label} ▾`;
    } catch {}
    // Rows
    const rowItems = ['25','50','100','200'].map(v => ({value:v, label:v}));
    wireSimpleMenu('rows-menu-btn','rows-menu', rowItems, (val) => {
      state.pageSize = Number(val)||50;
      const s = el('page-size'); if (s) s.value = String(state.pageSize);
      const btn = el('rows-menu-btn'); if (btn) btn.textContent = `${state.pageSize} ▾`;
      state.page = 1; renderAll();
    });
    // set initial rows button label
    try {
      const cur = el('page-size') ? el('page-size').value : '50';
      const btn = el('rows-menu-btn'); if (btn) btn.textContent = `${cur} ▾`;
    } catch {}
  }
  function exportCSV(){
    try {
      const cols = state.columns.filter(c=>c.visible);
      const header = cols.map(c => {
        if (!c.key.startsWith('metric:')) return c.title;
        const parts = c.key.split(':');
        if (parts.length===2) return c.title || `${parts[1]}_score`;
        return `${parts[1]}_${parts.slice(2).join(':')}`;
      });
      const rows = state.filtered.slice();
      const lines = [header.map(csvEscape).join(',')];
      rows.forEach(r => {
        const cells = cols.map(c => {
          if (c.key==='index') return (Number(r.index)||0)+1;
          if (c.key==='status') return r.status||'';
          if (c.key==='input') return r.input_full || r.input || '';
          if (c.key==='output') return r.output_full || r.output || '';
          if (c.key==='expected') return r.expected_full || r.expected || '';
          if (c.key==='time') return r.time || (r.latency_ms!=null? `${r.latency_ms}ms` : '');
          if (c.key.startsWith('metric:')) {
            const parts = c.key.split(':');
            const name = parts[1];
            if (parts.length===2){ const i=(state.metricNames||[]).indexOf(name); return (r.metric_values||[])[i] ?? ''; }
            const field = parts.slice(2).join(':');
            const mm = (r.metric_meta && r.metric_meta[name]) || {};
            return mm[field] ?? '';
          }
          return '';
        });
        lines.push(cells.map(csvEscape).join(','));
      });
      const blob = new Blob([lines.join('\n')], {type:'text/csv'});
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      const ds = (state.run && state.run.dataset_name) || 'dataset';
      const rn = (state.run && state.run.run_name) || 'run';
      a.download = `qym_${ds}_${rn}.csv`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(()=>URL.revokeObjectURL(a.href), 3000);
    } catch (e) { console.error('CSV export failed', e); }
  }

  // (No global keyboard shortcuts; keep UI simple)

  // Bootstrap
  function bootstrapLive() {
    // Live mode: fetch from regular API
    fetch('api/run').then(r=>r.json()).then(run => {
      state.run = run;
      state.metricNames = run.metric_names || [];
      state.langfuseHost = run.langfuse_host || 'https://cloud.langfuse.com';
      state.langfuseProjectId = run.langfuse_project_id || '';
      // Setup run start for timer
      try {
        const s = run.started_at || run.start_time || null;
        state.runStartMs = s ? Date.parse(s) : Date.now();
        state.runEndMs = null;
      } catch { state.runStartMs = Date.now(); state.runEndMs = null; }
      try {
        const ds = run.dataset_name || 'Dataset';
        const rn = run.run_name || 'Run';
        document.title = `قيِّم – ${ds} / ${rn}`;
      } catch {}
      // Apply default header style (B)
      try { document.body.setAttribute('data-header-style', 'b'); } catch {}
      initColumns();
      renderMeta();
      startRunTimer();
      renderQuickBar();
      renderMetricCharts();
      buildHeader();
      buildColumnMenu();
      initToolbarMenus();
      // After run info is ready (metric names set), fetch initial snapshot
      return fetch('api/snapshot')
        .then(r=>r.json())
        .then(snap => {
          state.snapshot = snap || { rows:[], stats:{} };
          // If metric names missing or incomplete, infer from snapshot
          syncMetricNamesFromSnapshot(state.snapshot);
          updateMetricSeriesFromSnapshot(state.snapshot);
          renderAll();
          // If any snapshot arrived before run finished loading, apply it now
          if (state._pendingSnapshot){
            updateMetricSeriesFromSnapshot(state._pendingSnapshot);
            renderAll();
            state._pendingSnapshot = null;
          }
        })
        .catch(()=>{});
    }).catch(()=>{});
  }

  function bootstrapDashboard(filePath) {
    // Dashboard mode: fetch historical run data from dashboard API
    const url = apiUrl('api/runs/' + encodeURIComponent(filePath));
    console.log('[qym] Dashboard mode - fetching:', url, 'filePath:', filePath);
    fetch(url)
      .then(r => r.json())
      .then(data => {
        console.log('[qym] API response:', data);
        if (data.error) {
          console.error('Failed to load run:', data.error);
          return;
        }
        const run = data.run || {};
        const snap = data.snapshot || { rows: [], stats: {} };
        console.log('[qym] Run:', run, 'Snapshot rows:', snap.rows?.length);

        state.run = run;
        state.snapshot = snap;
        state.metricNames = run.metric_names || snap.metric_names || [];
        state.langfuseHost = run.langfuse_host || '';
        state.langfuseProjectId = run.langfuse_project_id || '';

        // Mark as finished (historical data)
        state.runStartMs = Date.now();
        state.runEndMs = Date.now();

        try {
          const ds = run.dataset_name || 'Dataset';
          const rn = run.run_name || 'Run';
          document.title = `قيِّم – ${ds} / ${rn} (Historical)`;
        } catch {}

        try { document.body.setAttribute('data-header-style', 'b'); } catch {}

        initColumns();
        renderMeta();
        renderQuickBar();
        renderMetricCharts();
        buildHeader();
        buildColumnMenu();
        initToolbarMenus();
        syncMetricNamesFromSnapshot(snap);
        updateMetricSeriesFromSnapshot(snap);
        renderAll();

        // Build row index map
        try {
          const map = new Map();
          (snap.rows || []).forEach(r => map.set(Number(r.index) || 0, r));
          state.rowByIndex = map;
        } catch {}
      })
      .catch(err => {
        console.error('Failed to fetch run data:', err);
      });
  }

  // Choose bootstrap mode
  console.log('[qym] Bootstrap check - isDashboardMode:', isDashboardMode, 'dashboardRunFile:', dashboardRunFile, 'BASE_URL:', BASE_URL);
  if (isDashboardMode && dashboardRunFile) {
    bootstrapDashboard(dashboardRunFile);
  } else {
    bootstrapLive();
  }
  // Build initial row map if available
  try {
    const map = new Map();
    (state.snapshot.rows||[]).forEach(r => map.set(Number(r.index)||0, r));
    state.rowByIndex = map;
  } catch {}

  // Live updates via SSE (skip in dashboard mode)
  if (!isDashboardMode) try {
    const es = new EventSource('api/rows/stream');
    es.addEventListener('snapshot', (evt) => {
      try {
        const data = JSON.parse(evt.data || '{}');
        // If metric names not ready yet, hold onto this snapshot
        syncMetricNamesFromSnapshot(data);
        if (!state.metricNames || state.metricNames.length===0){
          state._pendingSnapshot = data;
        }
        state.snapshot = data;
        updateMetricSeriesFromSnapshot(data);
        renderMetricCharts();
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
    es.addEventListener('done', () => {
      // On server finish, fetch a final snapshot to avoid stale in-progress
      if (state._finalFetched) return;
      state._finalFetched = true;
      // stop timer at end
      try { state.runEndMs = Date.now(); stopRunTimer(); } catch {}
      fetch('api/snapshot')
        .then(r=>r.json())
        .then(snap => { state.snapshot = snap || { rows:[], stats:{} }; updateMetricSeriesFromSnapshot(state.snapshot); renderAll(); })
        .catch(()=>{});
    });
    es.onerror = () => {
      if (state._finalFetched) return;
      state._finalFetched = true;
      fetch('api/snapshot').then(r=>r.json()).then(snap => { state.snapshot = snap || { rows:[], stats:{} }; renderAll(); }).catch(()=>{});
    };
  } catch (e) {}

  // Run timer helpers
  function updateTimerOnce(){
    const span = document.getElementById('run-timer');
    if (!span) return;
    const start = Number(state.runStartMs||0);
    const end = Number(state.runEndMs||0);
    const now = end && end>start ? end : Date.now();
    const elapsed = Math.max(0, now - start);
    span.textContent = humanDuration(elapsed);
  }
  function startRunTimer(){
    if (state._timerId) clearInterval(state._timerId);
    updateTimerOnce();
    state._timerId = setInterval(() => {
      // stop automatically if finished
      try {
        const st = (state.snapshot && state.snapshot.stats) || {};
        const done = st && typeof st.total==='number' && (st.pending||0)===0 && (st.in_progress||0)===0;
        if (done) { state.runEndMs = state.runEndMs || Date.now(); stopRunTimer(); }
      } catch {}
      updateTimerOnce();
    }, 1000);
  }
  function stopRunTimer(){ if (state._timerId) { clearInterval(state._timerId); state._timerId = null; } }

  // Metric charts logic
  state.metricSeries = {}; // name -> number[]
  function toNumber(val){
    if (val == null) return null;
    const raw = String(val).trim();
    const t = raw.toLowerCase();
    if (t==='✓' || t==='true' || t==='yes') return 1;
    if (t==='✗' || t==='false' || t==='no') return 0;
    if (t==='n/a' || t==='pending' || t==='computing...' || t==='error') return null;
    // Strip percent sign
    const pct = /^(\d+(?:\.\d+)?)%$/.exec(raw);
    if (pct) return Number(pct[1]) / 100;
    const n = Number(raw);
    if (!Number.isNaN(n)) return n;
    return null;
  }
  function updateMetricSeriesFromSnapshot(snap){
    try {
      const names = state.metricNames || [];
      if (!names.length) return;
      const rows = (snap && snap.rows) || [];
      // Compute average score for each metric across all rows
      names.forEach((name, i) => {
        let sum = 0, cnt = 0;
        for (const r of rows){
          const v = (r.metric_values||[])[i];
          const n = toNumber(v);
          if (n == null) continue;
          sum += n; cnt++;
        }
        const val = cnt ? (sum / cnt) : 0;
        if (!state.metricSeries[name]) state.metricSeries[name] = [];
        const arr = state.metricSeries[name];
        arr.push(val);
        if (arr.length > 120) arr.shift();
      });
    } catch {}
  }
  function fmtMetricVal(v){
    if (v==null || Number.isNaN(v)) return '—';
    if (v>=0 && v<=1) return `${Math.round(v*100)}%`;
    const n = Number(v);
    if (Math.abs(n) >= 100) return n.toFixed(0);
    if (Math.abs(n) >= 10) return n.toFixed(1);
    return n.toFixed(2);
  }
  function renderMetricCharts(){
    const wrap = document.getElementById('metric-charts');
    if (!wrap) return;
    const names = state.metricNames || [];
    if (!names.length){ wrap.innerHTML = '<div class="muted">No metrics</div>'; return; }
    const items = names.map(name => {
      const series = (state.metricSeries && state.metricSeries[name]) || [];
      const {svg, lastVal} = sparklineSVG(series, 220, 48);
      return `<div class="metric-chart"><div class="metric-chart-header"><span class="name">${name}</span><span class="val">${fmtMetricVal(lastVal)}</span></div>${svg}</div>`;
    }).join('');
    wrap.innerHTML = items;
  }
  function sparklineSVG(series, width, height){
    const w = Math.max(220, width|0), h = Math.max(32, height|0);
    const data = series.slice(-60); // last 60 points
    const lastVal = data.length ? data[data.length-1] : null;
    if (data.length < 2){
      const y = h/2;
      const d = `M 0 ${y.toFixed(2)} L ${w} ${y.toFixed(2)}`;
      const svg = `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><rect class="bg" x="0" y="0" width="${w}" height="${h}" /><path class="spark" d="${d}"/></svg>`;
      return { svg, lastVal };
    }
    let min = Infinity, max = -Infinity;
    data.forEach(v => { if (v==null) return; if (v<min) min=v; if (v>max) max=v; });
    if (!isFinite(min) || !isFinite(max) || min===max){ min = (min===max && isFinite(min)) ? min-1 : 0; max = (min===max && isFinite(min)) ? max+1 : 1; }
    const n = data.length;
    const dx = w/(n-1);
    const ys = (v) => {
      if (v==null) return h/2;
      const t = (v - min) / (max - min);
      return (1 - t) * (h-6) + 3; // padding 3px
    };
    let d = '';
    for (let i=0;i<n;i++){
      const x = i*dx;
      const y = ys(data[i]);
      d += (i===0? 'M':' L') + x.toFixed(2) + ' ' + y.toFixed(2);
    }
    const svg = `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><rect class="bg" x="0" y="0" width="${w}" height="${h}" /><path class="spark" d="${d}"/></svg>`;
    return { svg, lastVal };
  }
})();
