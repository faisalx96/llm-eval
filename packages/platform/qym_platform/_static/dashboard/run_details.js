/* Keep analytical rows complete while loading large item bodies as needed. */
(() => {
  'use strict';
  let activeRequests = 0;
  const requestQueue = [];

  async function withRequestSlot(request) {
    if (activeRequests >= 3) await new Promise(resolve => requestQueue.push(resolve));
    else activeRequests++;
    try { return await request(); }
    finally {
      const next = requestQueue.shift();
      if (next) next();
      else activeRequests--;
    }
  }

  function create(options) {
    const loaded = new Map();
    const pending = new Map();
    const searches = new Map();
    const searchPending = new Map();
    const abort = new AbortController();
    const bodyFields = ['input', 'input_full', 'expected', 'expected_full', 'output', 'output_full'];
    const maxLoaded = options.maxLoaded || 200;
    let stopped = false;

    function itemId(row) { return String(row.item_id ?? row.index); }
    function searchKey(condition) { return JSON.stringify([condition.field, String(condition.value || '').toLowerCase()]); }
    function captureBodies(row) {
      return {
        fields: Object.fromEntries(bodyFields.map(key => [key, row[key]])),
        metricMeta: Object.fromEntries(Object.entries(row.metric_meta || {}).map(([name, meta]) => [name, meta?.explanation])),
        passMetricMeta: Object.fromEntries(Object.entries(row.pass_metric_meta || {}).map(([name, values]) => [name, values.map(meta => meta?.explanation)])),
        attempts: (row.pass_attempts || []).map(attempt => attempt?.output),
      };
    }
    function release(entry) {
      const { row, original } = entry;
      for (const key of bodyFields) {
        if (original.fields[key] === undefined) delete row[key];
        else row[key] = original.fields[key];
      }
      for (const [name, meta] of Object.entries(row.metric_meta || {})) {
        if (!meta || typeof meta !== 'object') continue;
        if (original.metricMeta[name] === undefined) delete meta.explanation;
        else meta.explanation = original.metricMeta[name];
      }
      (row.pass_attempts || []).forEach((attempt, i) => {
        if (!attempt) return;
        if (original.attempts[i] === undefined) delete attempt.output;
        else attempt.output = original.attempts[i];
      });
      for (const [name, values] of Object.entries(row.pass_metric_meta || {})) {
        values.forEach((meta, i) => {
          if (!meta || typeof meta !== 'object') return;
          const value = original.passMetricMeta[name]?.[i];
          if (value === undefined) delete meta.explanation;
          else meta.explanation = value;
        });
      }
      row.__details_loaded = false;
    }
    function trim(keepIds = new Set(), limit = maxLoaded) {
      for (const [id, entry] of loaded) {
        if (loaded.size <= limit) break;
        if (keepIds.has(id)) continue;
        release(entry);
        loaded.delete(id);
      }
    }
    async function post(suffix, body) {
      return withRequestSlot(async () => {
        const response = await fetch(options.apiUrl('api/runs/' + encodeURIComponent(options.runId) + '/items/' + suffix), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          signal: abort.signal,
        });
        if (!response.ok) throw new Error('Could not load item ' + suffix + ' (HTTP ' + response.status + ')');
        const data = await response.json();
        if (data.error) throw new Error(data.error);
        return data;
      });
    }
    function ensureRows(rows, settings = {}) {
      if (stopped) return null;
      const requested = new Map(rows.map(row => [itemId(row), row]));
      const waiting = new Set();
      const missing = [];
      for (const [id, row] of requested) {
        if (row.__details_loaded !== false) {
          const entry = loaded.get(id);
          if (entry) { entry.row = row; loaded.delete(id); loaded.set(id, entry); }
        } else if (pending.has(id)) {
          waiting.add(pending.get(id));
        } else {
          missing.push(row);
        }
      }
      // A sequential batch loop bounds requests as well as response buffers.
      if (missing.length) {
        const promise = (async () => {
          for (let offset = 0; offset < missing.length; offset += 100) {
            const batch = missing.slice(offset, offset + 100);
            const data = await post('details', { item_ids: batch.map(itemId) });
            if (stopped) return;
            const patches = new Map((data.rows || []).map(row => [itemId(row), row]));
            for (const row of batch) {
              const id = itemId(row);
              const full = patches.get(id);
              if (!full) throw new Error('Item details are no longer available. Reload the run to refresh its items.');
              const original = captureBodies(row);
              const identity = {};
              for (const key of ['compare_item_id', 'compare_alignment_source', 'alignment_source']) {
                if (Object.prototype.hasOwnProperty.call(row, key)) identity[key] = row[key];
              }
              Object.assign(row, options.transformRow ? options.transformRow(full) : full, identity, { __details_loaded: true });
              loaded.set(id, { row, original });
            }
          }
          if (!settings.retainAll) trim(new Set(requested.keys()));
        })();
        for (const row of missing) pending.set(itemId(row), promise);
        promise.finally(() => {
          for (const row of missing) if (pending.get(itemId(row)) === promise) pending.delete(itemId(row));
        }).catch(() => {});
        waiting.add(promise);
      }
      return waiting.size ? Promise.all(waiting) : null;
    }
    function ensureSearch(conditions) {
      if (stopped) return null;
      const waiting = new Set();
      const missing = new Map();
      for (const condition of conditions) {
        const key = searchKey(condition);
        if (searches.has(key)) continue;
        if (searchPending.has(key)) waiting.add(searchPending.get(key));
        else missing.set(key, condition);
      }
      if (missing.size) {
        const entries = [...missing.entries()];
        const promise = (async () => {
          for (let offset = 0; offset < entries.length; offset += 32) {
            const batch = entries.slice(offset, offset + 32);
            const data = await post('search', {
              conditions: batch.map(([, condition], index) => ({ id: String(index), field: condition.field, operator: 'contains', value: condition.value })),
              ...(options.passNumber ? { pass_number: options.passNumber } : {}),
            });
            if (stopped) return;
            batch.forEach(([key], index) => {
              if (!Array.isArray(data.matches?.[String(index)])) throw new Error('Incomplete item search response');
              searches.set(key, new Set(data.matches[String(index)].map(String)));
            });
          }
          const active = new Set(conditions.map(searchKey));
          for (const key of searches.keys()) {
            if (searches.size <= Math.max(32, active.size)) break;
            if (!active.has(key)) searches.delete(key);
          }
        })();
        for (const [key] of entries) searchPending.set(key, promise);
        promise.finally(() => {
          for (const [key] of entries) if (searchPending.get(key) === promise) searchPending.delete(key);
        }).catch(() => {});
        waiting.add(promise);
      }
      return waiting.size ? Promise.all(waiting) : null;
    }
    return {
      ensureRows,
      ensureSearch,
      adoptRow(row, previous) {
        const id = itemId(row);
        const original = loaded.get(id)?.original || captureBodies(previous);
        row.__details_loaded = true;
        loaded.set(id, { row, original });
      },
      matches: (condition, row) => searches.get(searchKey(condition))?.has(itemId(row)) || false,
      releaseExcept(rows) { trim(new Set(rows.map(itemId)), rows.length); },
      stop() {
        stopped = true;
        abort.abort();
        for (const entry of loaded.values()) release(entry);
        loaded.clear(); pending.clear(); searches.clear(); searchPending.clear();
      },
    };
  }
  window.QymRunDetails = { create };
})();
