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
    const sort = el('sort').value;
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
    if (state.sortKey && state.sortKey !== 'index') {
      rows.sort((a,b) => compareByKey(a,b,state.sortKey,state.sortDir));
    } else if (sort === 'time-asc') {
      rows.sort((a,b) => (a.latency_ms||0) - (b.latency_ms||0));
    } else if (sort === 'time-desc') {
      rows.sort((a,b) => (b.latency_ms||0) - (a.latency_ms||0));
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
      ${cols.map(c => `<th data-key="${c.key}" class="${c.key!=='index'?'sortable':''} ${state.sortKey===c.key?('sorted-'+state.sortDir):''}" title="Click to sort. Drag to reorder. Drag edge to resize." style="${c.width?`width:${c.width}px;min-width:${c.width}px;`:''}">${c.title}<span class="col-hint">↕</span><span class="col-resizer" data-key="${c.key}"></span></th>`).join('')}
    </tr>`;
    // Sorting
    cols.forEach(c => {
      if (c.key === 'index') return;
      const th = thead.querySelector(`th[data-key="${c.key}"]`);
      th && th.addEventListener('click', (e) => {
        if (e.target && e.target.classList.contains('col-resizer')) return;
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
    // Drag-and-drop reorder
    thead.querySelectorAll('th').forEach(th => {
      const key = th.getAttribute('data-key');
      if (key === 'index') return;
      th.setAttribute('draggable', 'true');
      th.addEventListener('dragstart', (e) => { e.dataTransfer.setData('text/plain', key); });
      th.addEventListener('dragover', (e) => { e.preventDefault(); });
      th.addEventListener('drop', (e) => {
        e.preventDefault();
        const fromKey = e.dataTransfer.getData('text/plain');
        const toKey = key;
        if (!fromKey || fromKey===toKey) return;
        const full = state.columns.slice();
        const fromIdx = full.findIndex(c=>c.key===fromKey);
        const toIdx = full.findIndex(c=>c.key===toKey);
        if (fromIdx<0 || toIdx<0) return;
        const [moved] = full.splice(fromIdx,1);
        full.splice(toIdx,0,moved);
        state.columns = full;
        buildHeader();
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

    // Bind row click for drawer
    el('rows').querySelectorAll('tr').forEach(tr => {
      tr.addEventListener('click', () => {
        const rawIdx = Number(tr.getAttribute('data-raw-index'))||0;
        const row = (state.snapshot.rows||[]).find(rr => Number(rr.index)===rawIdx);
        if (row) openDrawer(row);
      });
    });
  }

  function renderAll() {
    applyFilters();
    renderMeta();
    renderPanels();
    renderTable();
  }

  // Controls
  el('q').addEventListener('input', () => { state.page = 1; renderAll(); });
  el('status').addEventListener('change', () => { state.page = 1; renderAll(); });
  el('sort').addEventListener('change', () => { state.page = 1; renderAll(); });
  el('page-size').addEventListener('change', () => { state.pageSize = Number(el('page-size').value)||50; state.page = 1; renderAll(); });
  el('prev').addEventListener('click', () => { state.page = Math.max(1, state.page-1); renderTable(); });
  el('next').addEventListener('click', () => { state.page = state.page+1; renderTable(); });
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
  function diffWords(a, b) {
    try {
      const wa = String(a||'').split(/(\s+)/);
      const wb = String(b||'').split(/(\s+)/);
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
      $in.textContent = row.input_full || row.input || '';
      $out.classList.remove('diff');
      $exp.classList.remove('diff');
      $out.textContent = row.output_full || row.output || '';
      $exp.textContent = row.expected_full || row.expected || '';
    };
    const setDiff = () => {
      const d = diffWords(row.output_full || row.output || '', row.expected_full || row.expected || '');
      $in.textContent = row.input_full || row.input || '';
      $out.innerHTML = d.a; $out.classList.add('diff');
      $exp.innerHTML = d.b; $exp.classList.add('diff');
    };
    const apply = () => diffToggle.checked ? setDiff() : setRaw();
    diffToggle.onchange = apply;
    apply();
    overlay.classList.add('show');
    overlay.hidden = false;
  }
  function closeDrawer(){ overlay.classList.remove('show'); overlay.hidden = true; }
  btnClose.addEventListener('click', closeDrawer);
  overlay.addEventListener('click', (e)=>{ if (e.target === overlay) closeDrawer(); });

  // Bootstrap
  fetch('api/run').then(r=>r.json()).then(run => {
    state.run = run;
    state.metricNames = run.metric_names || [];
    try {
      const ds = run.dataset_name || 'Dataset';
      const rn = run.run_name || 'Run';
      document.title = `LLM Eval – ${ds} / ${rn}`;
    } catch {}
    initColumns();
    renderMeta();
    buildHeader();
    buildColumnMenu();
  }).catch(()=>{});
  fetch('api/snapshot').then(r=>r.json()).then(snap => { state.snapshot = snap || { rows:[], stats:{} }; renderAll(); }).catch(()=>{});

  // Live updates via SSE
  try {
    const es = new EventSource('api/rows/stream');
    es.addEventListener('snapshot', (evt) => {
      try {
        const data = JSON.parse(evt.data || '{}');
        state.snapshot = data;
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
