/**
 * QymPlayground — AI Evaluator Playground modal
 * Single-column scrollable layout with variable mapping, auto-preview, matched items table
 * Shared module used by run.html and compare.html
 */
window.QymPlayground = (function () {
  'use strict';

  var _opts = {};
  var _overlay = null;
  var _config = null;       // analysis-config response
  var _corrections = [];    // correction bank entries
  var _testResults = [];
  var _running = false;
  var _previewTimer = null;  // debounce timer for auto-preview
  var _matchedPage = 0;      // pagination for matched items table
  var _PAGE_SIZE = 10;

  // ── Public API ──

  function init(opts) {
    _opts = opts || {};
  }

  function open() {
    if (_overlay) { _overlay.style.display = 'flex'; return; }
    _fetchConfigAndOpen();
  }

  function close() {
    if (_overlay) _overlay.style.display = 'none';
  }

  // ── Fetch config + corrections then build modal ──

  function _fetchConfigAndOpen() {
    var runId = _getRunId();
    if (!runId) return;
    var base = _opts.apiUrl || function (p) { return '/' + p; };

    Promise.all([
      fetch(base('api/runs/' + encodeURIComponent(runId) + '/analysis-config')).then(function (r) { return r.json(); }),
      fetch(base('api/runs/' + encodeURIComponent(runId) + '/corrections')).then(function (r) { return r.json(); }),
    ]).then(function (results) {
      _config = results[0];
      _corrections = (results[1] && results[1].corrections) || [];
      _testResults = [];
      _matchedPage = 0;
      _createModal();
      _overlay.style.display = 'flex';
    }).catch(function (err) {
      console.error('Playground: failed to load config', err);
      if (_opts.showToast) _opts.showToast('error', 'Playground Error', 'Failed to load configuration');
    });
  }

  // ── Helpers ──

  function _getRunId() {
    return _opts.getRunId ? _opts.getRunId() : null;
  }

  function _esc(text) {
    if (_opts.escapeHtml) return _opts.escapeHtml(text);
    var d = document.createElement('div');
    d.textContent = text || '';
    return d.innerHTML;
  }

  function _escAttr(text) {
    return String(text || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function _tryParseObj(val) {
    if (val && typeof val === 'object' && !Array.isArray(val)) return val;
    if (typeof val === 'string') {
      try { var p = JSON.parse(val); if (p && typeof p === 'object' && !Array.isArray(p)) return p; } catch (e) {}
    }
    return null;
  }

  // ── Get full rows from the host page ──

  function _getRows() {
    return _opts.getRows ? _opts.getRows() : [];
  }

  // ── Client-side filtering ──

  function _getMatchedItems() {
    var rows = _getRows();
    var filterEl = document.getElementById('pg-filter-select');
    var maxScoreEl = document.getElementById('pg-max-score');
    var skipEl = document.getElementById('pg-skip-analyzed');

    var itemFilter = filterEl ? filterEl.value : 'all';
    var maxScore = maxScoreEl ? parseFloat(maxScoreEl.value) : NaN;
    var skipAnalyzed = skipEl ? skipEl.checked : false;
    var threshold = _opts.getThreshold ? _opts.getThreshold() : 0.8;

    return rows.filter(function (r) {
      // Skip analyzed
      if (skipAnalyzed) {
        var md = r.item_metadata;
        if (md && typeof md === 'object' && md.root_cause) return false;
      }

      var isError = !!r.error;
      var score = r.metric_score;

      // Item filter
      if (itemFilter === 'errors' && !isError) return false;
      if (itemFilter === 'failed') {
        if (!isError && score != null && score >= threshold) return false;
      }
      if (itemFilter === 'passed') {
        if (isError) return false;
        if (score == null || score < threshold) return false;
      }

      // Max score
      if (!isNaN(maxScore) && score != null && score > maxScore) return false;

      return true;
    });
  }

  // ── Scan JSON keys from first few items for a given field ──

  function _scanJsonKeys(fieldName) {
    var rows = _getRows();
    var keys = {};
    var limit = Math.min(rows.length, 5);
    for (var i = 0; i < limit; i++) {
      var val = rows[i][fieldName];
      var obj = _tryParseObj(val);
      if (obj) {
        var objKeys = Object.keys(obj);
        for (var k = 0; k < objKeys.length; k++) keys[objKeys[k]] = true;
      }
    }
    return Object.keys(keys).sort();
  }

  // ── Create modal DOM — single column layout ──

  function _createModal() {
    if (_overlay) { document.body.removeChild(_overlay); _overlay = null; }

    var overlay = document.createElement('div');
    overlay.className = 'playground-overlay';
    overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });

    var modal = document.createElement('div');
    modal.className = 'playground-modal';

    // Header
    var header = document.createElement('div');
    header.className = 'playground-header';
    header.innerHTML =
      '<div class="playground-header-left">' +
        '<span class="playground-header-icon">&#x1F916;</span>' +
        '<span class="playground-header-title">AI Evaluator Playground</span>' +
      '</div>' +
      '<button class="playground-close" title="Close">&times;</button>';
    header.querySelector('.playground-close').addEventListener('click', close);
    modal.appendChild(header);

    // LLM not configured banner
    if (_config && !_config.llm_configured) {
      var banner = document.createElement('div');
      banner.className = 'playground-banner playground-banner-warn';
      banner.textContent = 'LLM not configured \u2014 set up in Profile to enable Test and Run';
      modal.appendChild(banner);
    }

    // Scrollable content area
    var scroll = document.createElement('div');
    scroll.className = 'playground-scroll';
    scroll.innerHTML = _buildScrollContent();
    modal.appendChild(scroll);

    // Sticky footer
    var footer = document.createElement('div');
    footer.className = 'playground-footer';
    var matched = _getMatchedItems();
    var llmOk = _config && _config.llm_configured;
    footer.innerHTML =
      '<button class="pg-footer-btn pg-footer-test" id="pg-test-btn" ' + (!llmOk ? 'disabled' : '') + '>Test (first 3 matched)</button>' +
      '<button class="pg-footer-btn pg-footer-runall" id="pg-runall-btn" ' + (!llmOk ? 'disabled' : '') + '>Run All (' + matched.length + ' items)</button>';
    modal.appendChild(footer);

    overlay.appendChild(modal);
    document.body.appendChild(overlay);
    _overlay = overlay;

    // Wire all events
    _wireEvents();

    // Keyboard
    document.addEventListener('keydown', _onKeyDown);

    // Initial auto-preview
    _scheduleAutoPreview();
  }

  function _onKeyDown(e) {
    if (e.key === 'Escape' && _overlay && _overlay.style.display !== 'none') {
      close();
    }
  }

  // ── Build scrollable content ──

  function _buildScrollContent() {
    var cats = (_config && _config.default_categories) || [
      'Hallucination', 'Incomplete Answer', 'Wrong Format', 'Context Missing',
      'Reasoning Error', 'Tool Use Error', 'Instruction Following', 'Knowledge Gap',
    ];
    var defaultPrompt = (_config && _config.default_system_prompt) || '';
    var html = '';

    // ── System Prompt Section ──
    html += '<div class="playground-section">';
    html += '<div class="playground-section-header"><span>System Prompt</span><button class="pg-reset-btn" id="pg-reset-prompt" title="Reset to default">Reset</button></div>';
    html += '<textarea class="pg-prompt-textarea" id="pg-system-prompt" spellcheck="false">' + _esc(defaultPrompt) + '</textarea>';
    html += '</div>';

    // ── Root Cause Categories Section ──
    html += '<div class="playground-section">';
    html += '<div class="playground-section-header"><span>Root Cause Categories</span></div>';
    html += '<div id="pg-categories-list">';
    for (var i = 0; i < cats.length; i++) {
      html += '<div class="pg-category-item" data-cat="' + _escAttr(cats[i]) + '">' +
        '<span class="pg-category-name">' + _esc(cats[i]) + '</span>' +
        '<button class="pg-category-remove" title="Remove">&times;</button>' +
      '</div>';
    }
    html += '</div>';
    html += '<div class="pg-add-category">' +
      '<input type="text" id="pg-new-category" placeholder="New category..." class="pg-add-input" />' +
      '<button id="pg-add-category-btn" class="pg-add-btn">+ Add</button>' +
    '</div>';
    html += '</div>';

    // ── Variable Mapping Section ──
    html += _buildVariableMapping();

    // ── Few-Shot Examples Section ──
    html += '<div class="playground-section">';
    html += '<div class="playground-section-header">' +
      '<span>Few-Shot Examples (' + _corrections.length + ' available)</span>' +
      (_corrections.length > 0 ? '<button class="pg-reset-btn" id="pg-toggle-all-corrections">Toggle All</button>' : '') +
    '</div>';
    html += '<div id="pg-corrections-list">';
    if (_corrections.length === 0) {
      html += '<div class="pg-empty-msg">No corrections yet \u2014 corrections are created when you manually edit an AI-assigned root cause</div>';
    } else {
      for (var c = 0; c < _corrections.length; c++) {
        var cor = _corrections[c];
        var summary = cor.human_root_cause + (cor.human_root_cause_note ? ' \u2014 "' + cor.human_root_cause_note.slice(0, 50) + '..."' : '');
        html += '<div class="pg-correction-card">' +
          '<label class="pg-correction-card-header">' +
            '<input type="checkbox" data-correction-id="' + cor.id + '" checked /> ' +
            '<span class="pg-correction-label">#' + (c + 1) + ' ' + _esc(cor.human_root_cause) + '</span>' +
            '<span class="pg-correction-note">' + _esc((cor.human_root_cause_note || '').slice(0, 60)) + '</span>' +
          '</label>' +
          '<details class="pg-correction-details">' +
            '<summary>Show details</summary>' +
            '<div class="pg-correction-details-content">' +
              (cor.ai_root_cause ? '<div><strong>AI suggested:</strong> ' + _esc(cor.ai_root_cause) + '</div>' : '') +
              (cor.ai_root_cause_note ? '<div><strong>AI note:</strong> ' + _esc(cor.ai_root_cause_note) + '</div>' : '') +
              '<div><strong>Human correction:</strong> ' + _esc(cor.human_root_cause) + '</div>' +
              (cor.human_root_cause_note ? '<div><strong>Human note:</strong> ' + _esc(cor.human_root_cause_note) + '</div>' : '') +
            '</div>' +
          '</details>' +
        '</div>';
      }
    }
    html += '</div>';
    html += '</div>';

    // ── Model Settings Section ──
    html += '<div class="playground-section">';
    html += '<div class="playground-section-header"><span>Model Settings</span></div>';
    html += '<div class="pg-model-info">Model: ' + _esc((_config && _config.model) || 'Not set') + ' <span style="color:var(--text-dim);">(Profile)</span></div>';
    html += '<div class="pg-setting-row">' +
      '<label class="pg-setting-label">Temperature</label>' +
      '<input type="range" id="pg-temperature" min="0" max="1" step="0.05" value="0.2" class="pg-range" />' +
      '<span id="pg-temp-val" class="pg-range-val">0.2</span>' +
    '</div>';
    html += '<div class="pg-setting-row">' +
      '<label class="pg-setting-label">Max Tokens</label>' +
      '<input type="number" id="pg-max-tokens" value="16384" min="256" max="65536" class="pg-number-input" />' +
    '</div>';
    html += '</div>';

    // ── Section Divider — Filter & Preview ──
    html += '<div class="pg-section-divider"><span>Filter & Preview</span></div>';

    // ── Filter Bar ──
    html += '<div class="pg-filter-bar">';
    html += '<select id="pg-filter-select" class="pg-select">' +
      '<option value="all">All Items</option>' +
      '<option value="failed" selected>Failed Items</option>' +
      '<option value="passed">Passed Items</option>' +
      '<option value="errors">Error Items</option>' +
    '</select>';
    html += '<div class="pg-filter-score-group">' +
      '<label class="pg-setting-label">Score &lt;</label>' +
      '<input type="number" id="pg-max-score" value="0.8" min="0" max="1" step="0.1" class="pg-number-input" style="width:70px;" />' +
    '</div>';
    html += '<label class="pg-field-toggle"><input type="checkbox" id="pg-skip-analyzed" checked /> Skip analyzed</label>';
    html += '</div>';

    // ── Matched Items Table ──
    html += '<div id="pg-matched-section">';
    html += _buildMatchedItemsTable();
    html += '</div>';

    // ── Prompt Preview (auto-updates) ──
    html += '<div class="pg-section-divider"><span>Prompt Preview</span><span class="pg-auto-indicator" id="pg-preview-indicator">auto-updates</span></div>';
    html += '<div class="pg-auto-preview" id="pg-auto-preview">';
    html += '<div class="pg-preview-loading" id="pg-preview-loading" style="display:none;">Generating preview...</div>';
    html += '<pre class="pg-prompt-preview-content" id="pg-preview-content">Select filters to see matched items and preview the prompt.</pre>';
    html += '<button class="pg-toggle-expand" id="pg-preview-toggle" style="display:none;">Expand</button>';
    html += '</div>';

    // ── Test Results ──
    html += '<div class="pg-section-divider" id="pg-results-divider" style="display:none;"><span>Test Results</span></div>';
    html += '<div id="pg-test-results" class="pg-test-results"></div>';

    // ── Run All Progress ──
    html += '<div id="pg-runall-progress" class="pg-runall-progress" style="display:none;">' +
      '<div class="pg-progress-text" id="pg-runall-progress-text">Analyzing...</div>' +
      '<div class="pg-progress-bar"><div class="pg-progress-fill" id="pg-runall-progress-fill"></div></div>' +
    '</div>';
    html += '<div id="pg-runall-results" class="pg-runall-results"></div>';

    return html;
  }

  // ── Variable Mapping Section ──

  function _buildVariableMapping() {
    var sourceFields = ['input', 'output', 'expected', 'error', 'item_metadata'];
    var mappingRows = [
      { label: 'INPUT', defaultField: 'input' },
      { label: 'EXPECTED OUTPUT', defaultField: 'expected' },
      { label: 'ACTUAL OUTPUT', defaultField: 'output' },
    ];

    var html = '<div class="playground-section">';
    html += '<div class="playground-section-header"><span>Variable Mapping</span></div>';

    for (var i = 0; i < mappingRows.length; i++) {
      var row = mappingRows[i];
      var rowId = 'pg-mapping-' + i;
      var keys = _scanJsonKeys(row.defaultField);

      html += '<div class="pg-mapping-row">';
      html += '<span class="pg-mapping-label">' + row.label + '</span>';
      html += '<span class="pg-mapping-arrow">\u2192</span>';
      html += '<select class="pg-mapping-select" id="' + rowId + '-field" data-mapping-idx="' + i + '">';
      for (var s = 0; s < sourceFields.length; s++) {
        var sel = sourceFields[s] === row.defaultField ? ' selected' : '';
        html += '<option value="' + sourceFields[s] + '"' + sel + '>' + sourceFields[s] + '</option>';
      }
      html += '</select>';
      html += '<span class="pg-mapping-dot">.</span>';
      html += '<select class="pg-mapping-key-select" id="' + rowId + '-key" data-mapping-idx="' + i + '">';
      html += '<option value="">\u2014</option>';
      for (var k = 0; k < keys.length; k++) {
        html += '<option value="' + _escAttr(keys[k]) + '">' + _esc(keys[k]) + '</option>';
      }
      html += '</select>';
      html += '</div>';
    }

    // Additional fields checkboxes
    html += '<div class="pg-mapping-additional">';
    html += '<span class="pg-mapping-additional-label">Additional fields:</span>';
    var extras = [
      { key: 'error', label: 'Error' },
      { key: 'scores', label: 'Scores' },
      { key: 'metadata', label: 'Metadata' },
    ];
    for (var e = 0; e < extras.length; e++) {
      html += '<label class="pg-field-toggle">' +
        '<input type="checkbox" data-field="' + extras[e].key + '" checked /> ' +
        extras[e].label +
      '</label>';
    }
    html += '</div>';
    html += '</div>';
    return html;
  }

  // ── Matched Items Table ──

  function _buildMatchedItemsTable() {
    var matched = _getMatchedItems();
    var html = '<div class="pg-matched-count">Matched: <strong>' + matched.length + '</strong> items</div>';

    if (matched.length === 0) {
      html += '<div class="pg-empty-msg">No items match filters</div>';
      return html;
    }

    var end = Math.min((_matchedPage + 1) * _PAGE_SIZE, matched.length);
    var visible = matched.slice(0, end);

    html += '<table class="pg-matched-table">';
    html += '<thead><tr><th>#</th><th>Item ID</th><th>Score</th><th>Status</th></tr></thead>';
    html += '<tbody>';
    for (var i = 0; i < visible.length; i++) {
      var r = visible[i];
      var score = r.metric_score != null ? r.metric_score.toFixed(2) : '\u2014';
      var status = r.error ? 'error' : (r.metric_score != null && r.metric_score < (_opts.getThreshold ? _opts.getThreshold() : 0.8) ? 'failed' : 'passed');
      html += '<tr class="pg-matched-row" data-item-id="' + _escAttr(r.item_id) + '">' +
        '<td>' + (r.index != null ? r.index : i) + '</td>' +
        '<td class="pg-matched-id">' + _esc(r.item_id.slice(0, 20)) + '</td>' +
        '<td class="pg-matched-score">' + score + '</td>' +
        '<td><span class="pg-status-badge pg-status-' + status + '">' + status + '</span></td>' +
      '</tr>';
    }
    html += '</tbody></table>';

    if (end < matched.length) {
      html += '<button class="pg-show-more" id="pg-show-more">Showing ' + end + ' of ' + matched.length + ' \u2014 Show more</button>';
    }

    return html;
  }

  // ── Build Config Payload ──

  function _buildConfigPayload() {
    var cfg = {};

    // System prompt
    var ta = document.getElementById('pg-system-prompt');
    if (ta) {
      var prompt = ta.value.trim();
      var defaultPrompt = (_config && _config.default_system_prompt) || '';
      if (prompt && prompt !== defaultPrompt) cfg.system_prompt = prompt;
    }

    // Categories
    var catItems = document.querySelectorAll('#pg-categories-list .pg-category-item');
    if (catItems.length > 0) {
      var cats = [];
      catItems.forEach(function (el) { cats.push(el.dataset.cat); });
      cfg.root_cause_categories = cats;
    }

    // Include fields (from additional fields checkboxes)
    var fieldChecks = _overlay.querySelectorAll('.pg-field-toggle input[type="checkbox"][data-field]');
    if (fieldChecks.length > 0) {
      var fields = { input: true, expected: true, output: true };
      fieldChecks.forEach(function (cb) { fields[cb.dataset.field] = cb.checked; });
      cfg.include_fields = fields;
    }

    // Field mapping
    var fieldMapping = _getFieldMapping();
    if (fieldMapping) {
      cfg.field_mapping = fieldMapping;
    }

    // Corrections
    var correctionChecks = _overlay.querySelectorAll('#pg-corrections-list input[type="checkbox"][data-correction-id]');
    if (correctionChecks.length > 0) {
      var allChecked = true;
      var noneChecked = true;
      var ids = [];
      correctionChecks.forEach(function (cb) {
        if (cb.checked) { noneChecked = false; ids.push(parseInt(cb.dataset.correctionId, 10)); }
        else { allChecked = false; }
      });
      if (noneChecked) {
        cfg.corrections_enabled = false;
      } else if (!allChecked) {
        cfg.correction_ids = ids;
      }
    }

    // Temperature
    var tempRange = document.getElementById('pg-temperature');
    if (tempRange) cfg.temperature = parseFloat(tempRange.value);

    // Max tokens
    var maxTokens = document.getElementById('pg-max-tokens');
    if (maxTokens) cfg.max_tokens = parseInt(maxTokens.value, 10) || 16384;

    return cfg;
  }

  function _getFieldMapping() {
    var mappingDefs = [
      { idx: 0, key: 'input', defaultField: 'input' },
      { idx: 1, key: 'expected', defaultField: 'expected' },
      { idx: 2, key: 'output', defaultField: 'output' },
    ];
    var mapping = {};
    var hasCustom = false;

    for (var i = 0; i < mappingDefs.length; i++) {
      var def = mappingDefs[i];
      var fieldEl = document.getElementById('pg-mapping-' + def.idx + '-field');
      var keyEl = document.getElementById('pg-mapping-' + def.idx + '-key');
      if (!fieldEl) continue;

      var field = fieldEl.value;
      var key = keyEl ? keyEl.value : '';
      var source = key ? field + '.' + key : field;

      if (source !== def.defaultField) hasCustom = true;
      mapping[def.key] = source;
    }

    return hasCustom ? mapping : null;
  }

  // ── Wire all events ──

  function _wireEvents() {
    // Reset prompt
    var resetBtn = document.getElementById('pg-reset-prompt');
    if (resetBtn) resetBtn.addEventListener('click', function () {
      var ta = document.getElementById('pg-system-prompt');
      if (ta) ta.value = (_config && _config.default_system_prompt) || '';
      _scheduleAutoPreview();
    });

    // Remove category
    var catList = document.getElementById('pg-categories-list');
    if (catList) catList.addEventListener('click', function (e) {
      var removeBtn = e.target.closest('.pg-category-remove');
      if (removeBtn) {
        var item = removeBtn.closest('.pg-category-item');
        if (item) { item.remove(); _scheduleAutoPreview(); }
      }
    });

    // Add category
    var addBtn = document.getElementById('pg-add-category-btn');
    var addInput = document.getElementById('pg-new-category');
    if (addBtn && addInput) {
      var addCat = function () {
        var val = addInput.value.trim();
        if (!val) return;
        var div = document.createElement('div');
        div.className = 'pg-category-item';
        div.dataset.cat = val;
        div.innerHTML = '<span class="pg-category-name">' + _esc(val) + '</span>' +
          '<button class="pg-category-remove" title="Remove">&times;</button>';
        catList.appendChild(div);
        addInput.value = '';
        _scheduleAutoPreview();
      };
      addBtn.addEventListener('click', addCat);
      addInput.addEventListener('keydown', function (e) { if (e.key === 'Enter') addCat(); });
    }

    // Temperature slider
    var tempRange = document.getElementById('pg-temperature');
    var tempVal = document.getElementById('pg-temp-val');
    if (tempRange && tempVal) {
      tempRange.addEventListener('input', function () { tempVal.textContent = tempRange.value; });
    }

    // Variable mapping change → re-scan keys + auto-preview
    _overlay.querySelectorAll('.pg-mapping-select').forEach(function (sel) {
      sel.addEventListener('change', function () {
        var idx = sel.dataset.mappingIdx;
        var keys = _scanJsonKeys(sel.value);
        var keyEl = document.getElementById('pg-mapping-' + idx + '-key');
        if (keyEl) {
          keyEl.innerHTML = '<option value="">\u2014</option>';
          for (var k = 0; k < keys.length; k++) {
            keyEl.innerHTML += '<option value="' + _escAttr(keys[k]) + '">' + _esc(keys[k]) + '</option>';
          }
        }
        _scheduleAutoPreview();
      });
    });
    _overlay.querySelectorAll('.pg-mapping-key-select').forEach(function (sel) {
      sel.addEventListener('change', function () { _scheduleAutoPreview(); });
    });

    // Additional fields checkboxes → auto-preview
    _overlay.querySelectorAll('.pg-field-toggle input[type="checkbox"][data-field]').forEach(function (cb) {
      cb.addEventListener('change', function () { _scheduleAutoPreview(); });
    });

    // Correction toggles → auto-preview
    _overlay.querySelectorAll('#pg-corrections-list input[type="checkbox"]').forEach(function (cb) {
      cb.addEventListener('change', function () { _scheduleAutoPreview(); });
    });

    // Toggle all corrections
    var toggleAllBtn = document.getElementById('pg-toggle-all-corrections');
    if (toggleAllBtn) {
      toggleAllBtn.addEventListener('click', function () {
        var checks = _overlay.querySelectorAll('#pg-corrections-list input[type="checkbox"][data-correction-id]');
        var anyChecked = false;
        checks.forEach(function (cb) { if (cb.checked) anyChecked = true; });
        checks.forEach(function (cb) { cb.checked = !anyChecked; });
        _scheduleAutoPreview();
      });
    }

    // System prompt change → auto-preview (debounced)
    var sysPrompt = document.getElementById('pg-system-prompt');
    if (sysPrompt) {
      sysPrompt.addEventListener('input', function () { _scheduleAutoPreview(); });
    }

    // Filter changes → refresh table + auto-preview
    var filterSelect = document.getElementById('pg-filter-select');
    var maxScore = document.getElementById('pg-max-score');
    var skipAnalyzed = document.getElementById('pg-skip-analyzed');
    if (filterSelect) filterSelect.addEventListener('change', _onFilterChange);
    if (maxScore) maxScore.addEventListener('change', _onFilterChange);
    if (skipAnalyzed) skipAnalyzed.addEventListener('change', _onFilterChange);

    // Show more button
    _wireShowMore();

    // Preview toggle
    var toggleBtn = document.getElementById('pg-preview-toggle');
    if (toggleBtn) toggleBtn.addEventListener('click', function () {
      var content = document.getElementById('pg-preview-content');
      if (content) {
        var expanded = content.classList.toggle('expanded');
        toggleBtn.textContent = expanded ? 'Collapse' : 'Expand';
      }
    });

    // Test button
    var testBtn = document.getElementById('pg-test-btn');
    if (testBtn) testBtn.addEventListener('click', _runTest);

    // Run All button
    var runAllBtn = document.getElementById('pg-runall-btn');
    if (runAllBtn) runAllBtn.addEventListener('click', _runAll);
  }

  function _wireShowMore() {
    var showMore = document.getElementById('pg-show-more');
    if (showMore) {
      showMore.addEventListener('click', function () {
        _matchedPage++;
        _refreshMatchedTable();
      });
    }
  }

  function _onFilterChange() {
    _matchedPage = 0;
    _refreshMatchedTable();
    _updateFooterCount();
    _scheduleAutoPreview();
  }

  function _refreshMatchedTable() {
    var section = document.getElementById('pg-matched-section');
    if (section) {
      section.innerHTML = _buildMatchedItemsTable();
      _wireShowMore();
    }
  }

  function _updateFooterCount() {
    var matched = _getMatchedItems();
    var runAllBtn = document.getElementById('pg-runall-btn');
    if (runAllBtn) {
      runAllBtn.textContent = 'Run All (' + matched.length + ' items)';
      if (matched.length === 0) runAllBtn.disabled = true;
      else if (_config && _config.llm_configured) runAllBtn.disabled = false;
    }
    var testBtn = document.getElementById('pg-test-btn');
    if (testBtn) {
      var testCount = Math.min(matched.length, 3);
      testBtn.textContent = 'Test (first ' + testCount + ' matched)';
      if (matched.length === 0) testBtn.disabled = true;
      else if (_config && _config.llm_configured) testBtn.disabled = false;
    }
  }

  // ── Auto Preview (debounced) ──

  function _scheduleAutoPreview() {
    if (_previewTimer) clearTimeout(_previewTimer);
    _previewTimer = setTimeout(_autoPreview, 500);
  }

  function _autoPreview() {
    var matched = _getMatchedItems();
    if (matched.length === 0) {
      var content = document.getElementById('pg-preview-content');
      if (content) content.textContent = 'No items match current filters.';
      var toggleBtn = document.getElementById('pg-preview-toggle');
      if (toggleBtn) toggleBtn.style.display = 'none';
      return;
    }

    var firstItem = matched[0];
    var runId = _getRunId();
    if (!runId) return;
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    var cfg = _buildConfigPayload();

    var loading = document.getElementById('pg-preview-loading');
    var indicator = document.getElementById('pg-preview-indicator');
    if (loading) loading.style.display = 'block';
    if (indicator) { indicator.textContent = 'updating...'; indicator.className = 'pg-auto-indicator pg-auto-updating'; }

    fetch(base('api/runs/' + encodeURIComponent(runId) + '/analyze-preview'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_id: firstItem.item_id, config: cfg }),
    })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var content = document.getElementById('pg-preview-content');
      var toggleBtn = document.getElementById('pg-preview-toggle');
      if (content && data.messages) {
        var text = data.messages.map(function (m) {
          return '=== ' + m.role.toUpperCase() + ' ===\n' + m.content;
        }).join('\n\n');
        content.textContent = text;
        content.classList.remove('expanded');
        if (toggleBtn) { toggleBtn.style.display = 'inline-block'; toggleBtn.textContent = 'Expand'; }
      }
    })
    .catch(function (err) {
      console.error('Auto-preview error:', err);
      var content = document.getElementById('pg-preview-content');
      if (content) content.textContent = 'Preview failed: ' + err.message;
    })
    .finally(function () {
      if (loading) loading.style.display = 'none';
      if (indicator) { indicator.textContent = 'auto-updates'; indicator.className = 'pg-auto-indicator'; }
    });
  }

  // ── Test (first 3 matched) ──

  function _runTest() {
    var matched = _getMatchedItems();
    if (matched.length === 0) {
      if (_opts.showToast) _opts.showToast('warning', 'No Items', 'No items match current filters');
      return;
    }
    if (_running) return;
    _running = true;

    var testItems = matched.slice(0, 3);
    var itemIds = testItems.map(function (r) { return r.item_id; });

    var runId = _getRunId();
    if (!runId) { _running = false; return; }
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    var cfg = _buildConfigPayload();

    var btn = document.getElementById('pg-test-btn');
    if (btn) { btn.disabled = true; btn.textContent = '\u23F3 Testing...'; }

    var divider = document.getElementById('pg-results-divider');
    if (divider) divider.style.display = '';
    var results = document.getElementById('pg-test-results');
    if (results) results.innerHTML = '<div class="pg-loading">Running analysis on ' + itemIds.length + ' items...</div>';

    fetch(base('api/runs/' + encodeURIComponent(runId) + '/analyze-test'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_ids: itemIds, config: cfg }),
    })
    .then(function (r) {
      if (!r.ok) return r.json().then(function (d) { throw new Error(d.detail || 'Test failed'); });
      return r.json();
    })
    .then(function (data) {
      _testResults = data.results || [];
      _renderTestResults();
    })
    .catch(function (err) {
      console.error('Test error:', err);
      if (results) results.innerHTML = '<div class="pg-error-msg">' + _esc(err.message) + '</div>';
      if (_opts.showToast) _opts.showToast('error', 'Test Failed', err.message);
    })
    .finally(function () {
      _running = false;
      _updateFooterCount();
    });
  }

  function _renderTestResults() {
    var container = document.getElementById('pg-test-results');
    if (!container) return;

    if (_testResults.length === 0) {
      container.innerHTML = '<div class="pg-empty-msg">No results</div>';
      return;
    }

    var RC_COLORS = {
      'Hallucination': '#ef4444', 'Incomplete Answer': '#f97316',
      'Wrong Format': '#00d4aa', 'Context Missing': '#3b82f6',
      'Reasoning Error': '#a855f7', 'Tool Use Error': '#ec4899',
      'Instruction Following': '#14b8a6', 'Knowledge Gap': '#6366f1',
    };

    container.innerHTML = _testResults.map(function (r) {
      var color = RC_COLORS[r.root_cause] || '#e07a5f';
      var confPct = Math.round((r.confidence || 0) * 100);
      var errorHtml = r.error ? '<div class="pg-result-error">' + _esc(r.error) + '</div>' : '';

      // Extract item context and few-shot examples from messages
      var fieldsBadgesHtml = '';
      var inputSectionHtml = '';
      var fewShotHtml = '';
      if (r.messages && r.messages.length > 0) {
        var userMsg = '';
        for (var m = 0; m < r.messages.length; m++) {
          if (r.messages[m].role === 'user') userMsg = r.messages[m].content || '';
        }

        var examples = [];
        var examplePattern = /--- Example ---\n([\s\S]*?)--- End Example ---/g;
        var match;
        while ((match = examplePattern.exec(userMsg)) !== null) {
          examples.push(match[1].trim());
        }

        var itemCtxMatch = userMsg.match(/Now analyze this evaluation item:\n\n([\s\S]*?)\n\nDetermine the root cause/);
        var itemCtx = itemCtxMatch ? itemCtxMatch[1].trim() : '';

        var fieldDefs = [
          { key: 'input', label: 'Input', pattern: /^INPUT:/m },
          { key: 'expected', label: 'Expected', pattern: /^EXPECTED OUTPUT:/m },
          { key: 'output', label: 'Output', pattern: /^ACTUAL OUTPUT:/m },
          { key: 'error', label: 'Error', pattern: /^ERROR:/m },
          { key: 'scores', label: 'Scores', pattern: /^METRIC SCORES:/m },
          { key: 'metadata', label: 'Metadata', pattern: /^METADATA:/m },
        ];
        var badges = fieldDefs.map(function (fd) {
          var present = fd.pattern.test(itemCtx);
          return '<span class="pg-field-badge' + (present ? ' pg-field-on' : ' pg-field-off') + '">' + fd.label + '</span>';
        }).join('');
        fieldsBadgesHtml = '<div class="pg-fields-used"><span class="pg-fields-label">Fields:</span>' + badges + '</div>';

        if (itemCtx) {
          inputSectionHtml =
            '<details class="pg-result-details">' +
              '<summary class="pg-result-details-summary">Item Input</summary>' +
              '<pre class="pg-result-details-content">' + _esc(itemCtx) + '</pre>' +
            '</details>';
        }

        if (examples.length > 0) {
          fewShotHtml =
            '<details class="pg-result-details">' +
              '<summary class="pg-result-details-summary">Few-Shot Examples (' + examples.length + ')</summary>' +
              '<div class="pg-result-details-content">' +
                examples.map(function (ex, i) {
                  var correctMatch = ex.match(/CORRECT answer:\s*(.+)/);
                  var correctLabel = correctMatch ? correctMatch[1].trim() : 'Example ' + (i + 1);
                  return '<div class="pg-fewshot-example">' +
                    '<div class="pg-fewshot-header">Example ' + (i + 1) + ' \u2014 <span style="color:#c084fc;">' + _esc(correctLabel) + '</span></div>' +
                    '<pre class="pg-fewshot-content">' + _esc(ex) + '</pre>' +
                  '</div>';
                }).join('') +
              '</div>' +
            '</details>';
        }
      }

      return '<div class="pg-test-result-card">' +
        '<div class="pg-result-header">' +
          '<span class="pg-result-item-id">' + _esc(r.item_id.slice(0, 24)) + '</span>' +
        '</div>' +
        '<div class="pg-result-rc" style="color:' + color + ';">' + _esc(r.root_cause) + '</div>' +
        '<div class="pg-confidence-row">' +
          '<div class="pg-confidence-bar"><div class="pg-confidence-fill" style="width:' + confPct + '%;background:' + color + ';"></div></div>' +
          '<span class="pg-confidence-val">' + (r.confidence != null ? r.confidence.toFixed(2) : '?') + '</span>' +
        '</div>' +
        '<div class="pg-result-note">' + _esc(r.root_cause_note || '') + '</div>' +
        errorHtml +
        fieldsBadgesHtml +
        inputSectionHtml +
        fewShotHtml +
      '</div>';
    }).join('');
  }

  // ── Run All ──

  function _runAll() {
    if (_running) return;
    _running = true;

    var runId = _getRunId();
    if (!runId) { _running = false; return; }
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    var cfg = _buildConfigPayload();

    var filterEl = document.getElementById('pg-filter-select');
    var maxScoreEl = document.getElementById('pg-max-score');
    var skipEl = document.getElementById('pg-skip-analyzed');

    var body = {
      metric: _opts.getMetric ? _opts.getMetric() : null,
      item_filter: filterEl ? filterEl.value : 'failed',
      max_score: maxScoreEl ? parseFloat(maxScoreEl.value) || undefined : undefined,
      only_unanalyzed: skipEl ? skipEl.checked : true,
      threshold: _opts.getThreshold ? _opts.getThreshold() : 0.8,
      config: cfg,
    };

    var btn = document.getElementById('pg-runall-btn');
    if (btn) { btn.disabled = true; btn.textContent = '\u23F3 Running...'; }

    var progress = document.getElementById('pg-runall-progress');
    var fill = document.getElementById('pg-runall-progress-fill');
    var progressText = document.getElementById('pg-runall-progress-text');
    if (progress) progress.style.display = 'block';
    if (fill) fill.style.width = '30%';
    if (progressText) progressText.textContent = 'Analyzing items...';

    fetch(base('api/runs/' + encodeURIComponent(runId) + '/analyze'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    .then(function (r) {
      if (fill) fill.style.width = '90%';
      if (!r.ok) return r.json().then(function (d) { throw new Error(d.detail || 'Analysis failed'); });
      return r.json();
    })
    .then(function (data) {
      if (fill) fill.style.width = '100%';
      if (progressText) progressText.textContent = 'Complete!';

      var resultsEl = document.getElementById('pg-runall-results');
      if (resultsEl) {
        resultsEl.innerHTML = '<div class="pg-runall-done">' +
          'Analyzed <strong>' + data.total_analyzed + '</strong> items' +
          (data.errors > 0 ? ' (<span style="color:#ef4444;">' + data.errors + ' errors</span>)' : '') +
        '</div>';
      }

      if (_opts.showToast) _opts.showToast('success', 'Analysis Complete', data.total_analyzed + ' items analyzed');
      if (_opts.onAnalysisComplete) _opts.onAnalysisComplete(data);

      setTimeout(function () {
        if (progress) progress.style.display = 'none';
      }, 2000);
    })
    .catch(function (err) {
      console.error('Run All error:', err);
      if (progressText) progressText.textContent = 'Failed';
      if (fill) fill.style.width = '0%';
      if (_opts.showToast) _opts.showToast('error', 'Analysis Failed', err.message);
      setTimeout(function () {
        if (progress) progress.style.display = 'none';
      }, 3000);
    })
    .finally(function () {
      _running = false;
      _updateFooterCount();
    });
  }

  // ── Public API ──
  return { init: init, open: open, close: close };
})();
