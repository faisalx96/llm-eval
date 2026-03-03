/**
 * QymPlayground — AI Evaluator Playground modal
 * Single-column scrollable layout with variable mapping, auto-preview, matched items table
 * Shared module used by run.html and compare.html
 */
window.QymPlayground = (function () {
  'use strict';

  var _opts = {};
  var _overlay = null;
  var _config = null;
  var _corrections = [];
  var _testResults = [];
  var _running = false;
  var _previewTimer = null;
  var _matchedPage = 0;
  var _PAGE_SIZE = 10;
  var _selectedItemId = null;
  var _customVars = [];

  // ── Public API ──

  function init(opts) { _opts = opts || {}; }

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
      fetch(base('api/runs/' + runId + '/analysis-config')).then(function (r) { if (!r.ok) throw new Error('Config: HTTP ' + r.status); return r.json(); }),
      fetch(base('api/runs/' + runId + '/corrections')).then(function (r) { if (!r.ok) throw new Error('Corrections: HTTP ' + r.status); return r.json(); }),
    ]).then(function (results) {
      _config = results[0];
      _corrections = (results[1] && results[1].corrections) || [];
      _testResults = [];
      _matchedPage = 0;
      _selectedItemId = null;
      _customVars = [];
      _createModal();
      _overlay.style.display = 'flex';
    }).catch(function (err) {
      console.error('Playground: failed to load config', err);
      if (_opts.showToast) _opts.showToast('error', 'Playground Error', 'Failed to load configuration');
    });
  }

  // ── Helpers ──

  function _getRunId() { return _opts.getRunId ? _opts.getRunId() : null; }

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
    // Returns a plain object for key scanning. Handles raw objects, JSON strings, and arrays.
    if (val && typeof val === 'object') {
      if (Array.isArray(val)) {
        // For arrays, try to find the first object element
        for (var a = 0; a < Math.min(val.length, 3); a++) {
          if (val[a] && typeof val[a] === 'object' && !Array.isArray(val[a])) return val[a];
        }
        return null;
      }
      return val;
    }
    if (typeof val === 'string') {
      var s = val.trim();
      if (!s) return null;
      try {
        var p = JSON.parse(s);
        if (p && typeof p === 'object') {
          if (Array.isArray(p)) {
            for (var a = 0; a < Math.min(p.length, 3); a++) {
              if (p[a] && typeof p[a] === 'object' && !Array.isArray(p[a])) return p[a];
            }
            return null;
          }
          return p;
        }
      } catch (e) {}
    }
    return null;
  }

  function _getRows() { return _opts.getRows ? _opts.getRows() : []; }

  function _truncate(val, maxLen) {
    if (val == null) return '\u2014';
    var s = (typeof val === 'object') ? JSON.stringify(val) : String(val);
    return s.length > maxLen ? s.slice(0, maxLen) + '\u2026' : s;
  }

  function _highlightPreview(escaped) {
    // Highlight section labels like INPUT:, EXPECTED OUTPUT:, ACTUAL OUTPUT:, etc.
    escaped = escaped.replace(/^(INPUT:|EXPECTED OUTPUT:|ACTUAL OUTPUT:|ERROR:|METRIC SCORES:|METADATA:)/gm,
      '<span class="pg-hl-label">$1</span>');
    // Highlight --- Example --- / --- End Example --- blocks
    escaped = escaped.replace(/^(--- (?:Example|End Example) ---)/gm,
      '<span class="pg-hl-example">$1</span>');
    // Highlight CORRECT answer: lines
    escaped = escaped.replace(/^(CORRECT answer:.*)/gm,
      '<span class="pg-hl-correct">$1</span>');
    // Highlight category list items (root cause and solution categories)
    escaped = escaped.replace(/^(- (?:Hallucination|Incomplete Answer|Wrong Format|Context Missing|Reasoning Error|Tool Use Error|Instruction Following|Knowledge Gap|Improve Retrieval Context|Add Guardrails|Refine Prompt Instructions|Expand Training Data|Fix Tool Configuration|Add Output Validation|Restructure Chain-of-Thought|Update Knowledge Base)\b.*)/gm,
      '<span class="pg-hl-category">$1</span>');
    // Highlight CORRECT solution: lines
    escaped = escaped.replace(/^(CORRECT solution:.*)/gm,
      '<span class="pg-hl-correct">$1</span>');
    // Highlight JSON response format hints
    escaped = escaped.replace(/(&quot;root_cause&quot;|&quot;root_cause_detail&quot;|&quot;root_cause_note&quot;|&quot;confidence&quot;|&quot;solution&quot;|&quot;solution_note&quot;)/g,
      '<span class="pg-hl-json-key">$1</span>');
    return escaped;
  }

  function _isFieldJson(fieldName) {
    return _scanJsonKeys(fieldName).length > 0;
  }

  function _scanJsonKeys(fieldName) {
    var rows = _getRows();
    var keys = {};
    var limit = Math.min(rows.length, 20);
    for (var i = 0; i < limit; i++) {
      // Try the field directly, then the _full variant (raw object before stringify)
      var val = rows[i][fieldName];
      var fullVal = rows[i][fieldName + '_full'];
      var obj = _tryParseObj(fullVal) || _tryParseObj(val);
      if (obj) {
        var objKeys = Object.keys(obj);
        for (var k = 0; k < objKeys.length; k++) keys[objKeys[k]] = true;
      }
    }
    return Object.keys(keys).sort();
  }

  function _detectCustomVars(text) {
    if (!text) return [];
    var re = /\{(\w+)\}/g;
    var vars = [];
    var seen = {};
    var reserved = { categories: true };
    var m;
    while ((m = re.exec(text)) !== null) {
      if (!reserved[m[1]] && !seen[m[1]]) {
        seen[m[1]] = true;
        vars.push(m[1]);
      }
    }
    return vars;
  }

  // ── Client-side filtering ──

  function _getMatchedItems() {
    var rows = _getRows();
    var filterEl = document.getElementById('pg-filter-select');
    var maxScoreEl = document.getElementById('pg-max-score');
    var skipEl = document.getElementById('pg-skip-analyzed');

    var itemFilter = filterEl ? filterEl.value : 'failed';
    var maxScore = maxScoreEl ? parseFloat(maxScoreEl.value) : NaN;
    var skipAnalyzed = skipEl ? skipEl.checked : true;
    var threshold = _opts.getThreshold ? _opts.getThreshold() : 0.8;

    return rows.filter(function (r) {
      if (skipAnalyzed) {
        var md = r.item_metadata;
        if (md && typeof md === 'object' && md.root_cause) return false;
      }
      var isError = !!r.error;
      var score = r.metric_score;
      if (itemFilter === 'errors') {
        if (!isError) return false;
      } else if (itemFilter === 'failed') {
        // Include errors, null scores (unknown), and scores below threshold
        if (isError) { /* include errors */ }
        else if (score == null) { /* include — score unknown */ }
        else if (score < threshold) { /* include — below threshold */ }
        else return false;
      } else if (itemFilter === 'passed') {
        if (isError) return false;
        if (score == null || score < threshold) return false;
      }
      if (!isNaN(maxScore) && score != null && score > maxScore) return false;
      return true;
    });
  }

  // ── Create modal DOM ──

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
    var llmOk = _config && _config.llm_configured;
    footer.innerHTML =
      '<button class="pg-footer-btn pg-footer-test" id="pg-test-btn" ' + (!llmOk ? 'disabled' : '') + '>Test Selected</button>' +
      '<button class="pg-footer-btn pg-footer-runall" id="pg-runall-btn" ' + (!llmOk ? 'disabled' : '') + '>Run All (' + _getMatchedItems().length + ' items)</button>';
    modal.appendChild(footer);

    overlay.appendChild(modal);
    document.body.appendChild(overlay);
    _overlay = overlay;

    // Wire all events
    _wireEvents();
    document.addEventListener('keydown', _onKeyDown);

    // Auto-select first matched item
    var initialMatched = _getMatchedItems();
    if (initialMatched.length > 0) {
      _selectedItemId = initialMatched[0].item_id;
      _highlightSelectedRow();
    }
    _scheduleAutoPreview();
  }

  function _onKeyDown(e) {
    if (e.key === 'Escape' && _overlay && _overlay.style.display !== 'none') close();
  }

  // ── Build scrollable content ──

  function _section(title, body, opts) {
    var o = opts || {};
    var open = o.open !== false ? ' open' : '';
    var badge = o.badge ? '<span class="pg-section-badge">' + o.badge + '</span>' : '';
    var extra = o.extraSummary || '';
    return '<details class="pg-section"' + open + '>' +
      '<summary class="pg-section-summary">' +
        '<span class="pg-section-chevron"></span>' +
        '<span class="pg-section-title">' + title + '</span>' +
        badge + extra +
      '</summary>' +
      '<div class="pg-section-body">' + body + '</div>' +
    '</details>';
  }

  function _buildScrollContent() {
    var cats = (_config && _config.default_categories) || [
      'Hallucination', 'Incomplete Answer', 'Wrong Format', 'Context Missing',
      'Reasoning Error', 'Tool Use Error', 'Instruction Following', 'Knowledge Gap',
    ];
    var html = '';

    // ── Additional Instructions ──
    var instrBody = '';
    instrBody += '<div class="pg-instructions-hint">Customize how the AI analyzes items. Use <code>{variable_name}</code> to reference item data \u2014 detected variables appear in Variable Mapping below.</div>';
    instrBody += '<textarea class="pg-instructions-textarea" id="pg-additional-instructions" placeholder="e.g. Focus on whether the response addresses all parts of the question.\nPay special attention to the {rubric} criteria." spellcheck="false"></textarea>';
    html += _section('Additional Instructions', instrBody);

    // ── Root Cause Categories ──
    var catBody = '';
    catBody += '<div id="pg-categories-list">';
    for (var i = 0; i < cats.length; i++) {
      catBody += '<div class="pg-category-item" data-cat="' + _escAttr(cats[i]) + '">' +
        '<span class="pg-category-name">' + _esc(cats[i]) + '</span>' +
        '<button class="pg-category-remove" title="Remove">&times;</button>' +
      '</div>';
    }
    catBody += '</div>';
    catBody += '<div class="pg-add-category">' +
      '<input type="text" id="pg-new-category" placeholder="New category..." class="pg-add-input" />' +
      '<button id="pg-add-category-btn" class="pg-add-btn">+ Add</button>' +
    '</div>';
    html += _section('Root Cause Categories', catBody, { open: false, badge: String(cats.length) });

    // ── Variable Mapping ──
    html += _buildVariableMapping();

    // ── Few-Shot Examples ──
    html += _buildFewShotExamples();

    // ── Filter & Matched Items ──
    var matchedCount = _getMatchedItems().length;
    var filterBody = '';
    filterBody += '<div class="pg-filter-row">';
    filterBody += '<div class="pg-filter-group">';
    filterBody += '<label class="pg-filter-label">Show</label>';
    filterBody += '<select id="pg-filter-select" class="pg-select">' +
      '<option value="all">All Items</option>' +
      '<option value="failed" selected>Failed Items</option>' +
      '<option value="passed">Passed Items</option>' +
      '<option value="errors">Error Items</option>' +
    '</select>';
    filterBody += '</div>';
    filterBody += '<div class="pg-filter-group">';
    filterBody += '<label class="pg-filter-label">Max Score</label>';
    filterBody += '<input type="number" id="pg-max-score" value="0.8" min="0" max="1" step="0.1" class="pg-number-input pg-filter-score" />';
    filterBody += '</div>';
    filterBody += '<label class="pg-filter-check"><input type="checkbox" id="pg-skip-analyzed" checked /> <span>Skip analyzed</span></label>';
    filterBody += '</div>';
    filterBody += '<div id="pg-matched-section">';
    filterBody += _buildMatchedItemsTable();
    filterBody += '</div>';
    html += _section('Filter & Items', filterBody, { badge: String(matchedCount) });

    // ── Prompt Preview ──
    var previewBody = '';
    previewBody += '<div id="pg-preview-loading" style="display:none;padding:8px 14px;font-size:12px;color:#a855f7;background:rgba(168,85,247,0.06);border-bottom:1px solid rgba(168,85,247,0.15);">Generating preview\u2026</div>';
    previewBody += '<div id="pg-preview-content" class="pg-prompt-preview-content">Loading prompt preview\u2026</div>';
    previewBody += '<button class="pg-toggle-expand" id="pg-preview-toggle" style="display:none;">Expand</button>';
    html += _section('Prompt Preview', previewBody, {
      extraSummary: '<span class="pg-auto-indicator" id="pg-preview-indicator">auto-updates</span>',
    });

    // Test Results (not collapsible — dynamically shown)
    html += '<div class="pg-section-divider" id="pg-results-divider" style="display:none;"><span>Test Results</span></div>';
    html += '<div id="pg-test-results" class="pg-test-results"></div>';

    // Run All Progress
    html += '<div id="pg-runall-progress" class="pg-runall-progress" style="display:none;">' +
      '<div class="pg-progress-text" id="pg-runall-progress-text">Analyzing\u2026</div>' +
      '<div class="pg-progress-bar"><div class="pg-progress-fill" id="pg-runall-progress-fill"></div></div>' +
    '</div>';
    html += '<div id="pg-runall-results" class="pg-runall-results"></div>';

    return html;
  }

  // ── Variable Mapping Section ──

  function _buildVariableMapping() {
    var sourceFields = ['input', 'output', 'expected', 'error', 'item_metadata'];
    var standardRows = [
      { label: 'INPUT', defaultField: 'input' },
      { label: 'EXPECTED OUTPUT', defaultField: 'expected' },
      { label: 'ACTUAL OUTPUT', defaultField: 'output' },
    ];

    var body = '';
    for (var i = 0; i < standardRows.length; i++) {
      var row = standardRows[i];
      var rowId = 'pg-mapping-' + i;
      var isJson = _isFieldJson(row.defaultField);
      var keys = isJson ? _scanJsonKeys(row.defaultField) : [];

      body += '<div class="pg-mapping-row">';
      body += '<span class="pg-mapping-label">' + row.label + '</span>';
      body += '<span class="pg-mapping-arrow">\u2192</span>';
      body += '<select class="pg-mapping-select" id="' + rowId + '-field" data-mapping-idx="' + i + '">';
      for (var s = 0; s < sourceFields.length; s++) {
        var sel = sourceFields[s] === row.defaultField ? ' selected' : '';
        body += '<option value="' + sourceFields[s] + '"' + sel + '>' + sourceFields[s] + '</option>';
      }
      body += '</select>';

      if (isJson) {
        body += '<span class="pg-mapping-dot" id="' + rowId + '-dot">.</span>';
        body += '<select class="pg-mapping-key-select" id="' + rowId + '-key" data-mapping-idx="' + i + '">';
        body += '<option value="">(full object)</option>';
        for (var k = 0; k < keys.length; k++) {
          body += '<option value="' + _escAttr(keys[k]) + '">' + _esc(keys[k]) + '</option>';
        }
        body += '</select>';
      }
      body += '</div>';
    }

    // Custom variables from additional instructions
    body += '<div id="pg-custom-vars-section">';
    body += _buildCustomVarsMapping();
    body += '</div>';

    // Additional fields checkboxes
    body += '<div class="pg-mapping-additional">';
    body += '<span class="pg-mapping-additional-label">Include in prompt:</span>';
    var extras = [
      { key: 'error', label: 'Error' },
      { key: 'scores', label: 'Scores' },
      { key: 'metadata', label: 'Metadata' },
    ];
    for (var e = 0; e < extras.length; e++) {
      body += '<label class="pg-field-toggle">' +
        '<input type="checkbox" data-field="' + extras[e].key + '" checked /> ' +
        extras[e].label +
      '</label>';
    }
    body += '</div>';
    return _section('Variable Mapping', body, { open: false });
  }

  function _buildCustomVarsMapping() {
    if (_customVars.length === 0) return '';

    var sourceFields = ['input', 'output', 'expected', 'error', 'item_metadata'];
    var html = '<div class="pg-custom-vars-divider">Custom Variables</div>';

    for (var i = 0; i < _customVars.length; i++) {
      var varName = _customVars[i];
      var rowId = 'pg-customvar-' + i;

      html += '<div class="pg-mapping-row pg-mapping-custom">';
      html += '<span class="pg-mapping-label pg-mapping-var-label">{' + _esc(varName) + '}</span>';
      html += '<span class="pg-mapping-arrow">\u2192</span>';
      html += '<select class="pg-mapping-select pg-customvar-field" id="' + rowId + '-field" data-customvar-idx="' + i + '" data-var-name="' + _escAttr(varName) + '">';
      html += '<option value="">\u2014 select source \u2014</option>';
      for (var s = 0; s < sourceFields.length; s++) {
        html += '<option value="' + sourceFields[s] + '">' + sourceFields[s] + '</option>';
      }
      html += '</select>';
      html += '<span class="pg-customvar-key-wrapper" id="' + rowId + '-key-wrapper"></span>';
      html += '</div>';
    }
    return html;
  }

  // ── Few-Shot Examples Section ──

  function _buildFewShotExamples() {
    var body = '';

    if (_corrections.length === 0) {
      body += '<div class="pg-empty-msg">No corrections yet \u2014 corrections are created when you manually edit an AI-assigned root cause in the items table</div>';
    } else {
      body += '<div id="pg-corrections-list">';
      for (var c = 0; c < _corrections.length; c++) {
        var cor = _corrections[c];
        body += '<div class="pg-example-card">';

        // Header: checkbox + correction flow
        body += '<label class="pg-example-header">';
        body += '<input type="checkbox" data-correction-id="' + cor.id + '" checked />';
        body += '<span class="pg-example-num">#' + (c + 1) + '</span>';
        if (cor.ai_root_cause && cor.ai_root_cause !== 'Unanalyzed') {
          body += '<span class="pg-example-ai-tag">' + _esc(cor.ai_root_cause) + '</span>';
          body += '<span class="pg-example-flow-arrow">\u2192</span>';
        }
        body += '<span class="pg-example-human-tag">' + _esc(cor.human_root_cause) + '</span>';
        body += '</label>';

        // Data preview
        body += '<div class="pg-example-body">';

        if (cor.input_snapshot != null) {
          body += '<div class="pg-example-field">';
          body += '<span class="pg-example-field-lbl">Input</span>';
          body += '<span class="pg-example-field-val">' + _esc(_truncate(cor.input_snapshot, 120)) + '</span>';
          body += '</div>';
        }

        var midRow = '';
        if (cor.expected_snapshot != null) {
          midRow += '<div class="pg-example-field pg-example-half">';
          midRow += '<span class="pg-example-field-lbl">Expected</span>';
          midRow += '<span class="pg-example-field-val">' + _esc(_truncate(cor.expected_snapshot, 80)) + '</span>';
          midRow += '</div>';
        }
        if (cor.output_snapshot != null) {
          midRow += '<div class="pg-example-field pg-example-half">';
          midRow += '<span class="pg-example-field-lbl">Output</span>';
          midRow += '<span class="pg-example-field-val">' + _esc(_truncate(cor.output_snapshot, 80)) + '</span>';
          midRow += '</div>';
        }
        if (midRow) body += '<div class="pg-example-row">' + midRow + '</div>';

        if (cor.human_root_cause_note) {
          body += '<div class="pg-example-feedback">';
          body += '<span class="pg-example-field-lbl">Feedback</span>';
          body += '<span class="pg-example-feedback-text">' + _esc(cor.human_root_cause_note) + '</span>';
          body += '</div>';
        }

        body += '</div>'; // pg-example-body
        body += '</div>'; // pg-example-card
      }
      body += '</div>';
    }
    return _section('Few-Shot Examples', body, {
      open: false,
      badge: String(_corrections.length),
      extraSummary: _corrections.length > 0 ? '<button class="pg-reset-btn" id="pg-toggle-all-corrections">Toggle All</button>' : '',
    });
  }

  // ── Matched Items Table ──

  function _buildMatchedItemsTable() {
    var matched = _getMatchedItems();
    var threshold = _opts.getThreshold ? _opts.getThreshold() : 0.8;

    var html = '';
    if (matched.length === 0) {
      html += '<div class="pg-empty-msg">No items match current filters</div>';
      return html;
    }

    html += '<div class="pg-items-list">';
    for (var i = 0; i < matched.length; i++) {
      var r = visible[i];
      var scoreNum = r.metric_score;
      var scoreStr = scoreNum != null ? scoreNum.toFixed(2) : '\u2014';
      var status = r.error ? 'error' : (scoreNum != null ? (scoreNum < threshold ? 'failed' : 'passed') : 'none');
      var isSelected = r.item_id === _selectedItemId;
      var md = r.item_metadata && typeof r.item_metadata === 'object' ? r.item_metadata : {};
      var rc = md.root_cause || '';
      var rcSource = md.root_cause_source || '';
      var sol = md.solution || '';

      html += '<div class="pg-item-card' + (isSelected ? ' pg-item-selected' : '') + '" data-item-id="' + _escAttr(r.item_id) + '">';

      // Top row: index, score, status, root cause, solution
      html += '<div class="pg-item-top">';
      html += '<span class="pg-item-idx">#' + (r.index != null ? r.index : i) + '</span>';
      if (scoreNum != null) html += '<span class="pg-item-score pg-status-' + status + '">' + scoreStr + '</span>';
      html += '<span class="pg-status-badge pg-status-' + status + '">' + (status === 'none' ? 'no score' : status) + '</span>';
      var rcDetail = md.root_cause_detail || '';
      if (rcDetail) html += '<span class="pg-rc-tag pg-rc-' + rcSource + '">' + _esc(rcDetail) + '</span>';
      if (rc) html += '<span class="pg-rc-tag pg-rc-category" style="opacity:0.7;font-size:10px;">' + _esc(rc) + '</span>';
      if (sol) html += '<span class="pg-sol-tag">' + _esc(sol) + '</span>';
      html += '</div>';

      // Input + output on one line
      html += '<div class="pg-item-preview">';
      html += '<span class="pg-item-text">' + _esc(_truncate(r.input, 100)) + '</span>';
      html += '</div>';

      // Error
      if (r.error) {
        html += '<div class="pg-item-error-line">' + _esc(_truncate(r.error, 100)) + '</div>';
      }

      html += '</div>'; // pg-item-card
    }
    html += '</div>';

    return html;
  }

  // ── Build Config Payload ──

  function _buildConfigPayload() {
    var cfg = {};

    // Additional instructions
    var instrEl = document.getElementById('pg-additional-instructions');
    if (instrEl && instrEl.value.trim()) {
      cfg.additional_instructions = instrEl.value.trim();
    }

    // Categories
    var catItems = document.querySelectorAll('#pg-categories-list .pg-category-item');
    if (catItems.length > 0) {
      var cats = [];
      catItems.forEach(function (el) { cats.push(el.dataset.cat); });
      cfg.root_cause_categories = cats;
    }

    // Include fields
    var fieldChecks = _overlay ? _overlay.querySelectorAll('.pg-field-toggle input[type="checkbox"][data-field]') : [];
    if (fieldChecks.length > 0) {
      var fields = { input: true, expected: true, output: true };
      fieldChecks.forEach(function (cb) { fields[cb.dataset.field] = cb.checked; });
      cfg.include_fields = fields;
    }

    // Field mapping (standard)
    var fieldMapping = _getFieldMapping();
    if (fieldMapping) cfg.field_mapping = fieldMapping;

    // Custom variable mapping
    var customMapping = _getCustomVarMapping();
    if (customMapping) cfg.custom_variable_mapping = customMapping;

    // Corrections
    var correctionChecks = _overlay ? _overlay.querySelectorAll('#pg-corrections-list input[type="checkbox"][data-correction-id]') : [];
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

  function _getCustomVarMapping() {
    if (_customVars.length === 0) return null;
    var mapping = {};
    var hasAny = false;

    for (var i = 0; i < _customVars.length; i++) {
      var fieldEl = document.getElementById('pg-customvar-' + i + '-field');
      if (!fieldEl || !fieldEl.value) continue;
      var field = fieldEl.value;
      var keyEl = document.getElementById('pg-customvar-' + i + '-key');
      var key = keyEl ? keyEl.value : '';
      mapping[_customVars[i]] = key ? field + '.' + key : field;
      hasAny = true;
    }
    return hasAny ? mapping : null;
  }

  // ── Wire all events ──

  function _wireEvents() {
    // Additional instructions
    var instrEl = document.getElementById('pg-additional-instructions');
    if (instrEl) {
      instrEl.addEventListener('input', function () {
        _onAdditionalInstructionsChange();
        _scheduleAutoPreview();
      });
    }

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

    // Variable mapping field change
    _overlay.querySelectorAll('.pg-mapping-select:not(.pg-customvar-field)').forEach(function (sel) {
      sel.addEventListener('change', function () {
        _onMappingFieldChange(sel);
        _scheduleAutoPreview();
      });
    });
    _overlay.querySelectorAll('.pg-mapping-key-select').forEach(function (sel) {
      sel.addEventListener('change', function () { _scheduleAutoPreview(); });
    });

    // Additional fields checkboxes
    _overlay.querySelectorAll('.pg-field-toggle input[type="checkbox"][data-field]').forEach(function (cb) {
      cb.addEventListener('change', function () { _scheduleAutoPreview(); });
    });

    // Correction toggles
    var corrList = _overlay.querySelector('#pg-corrections-list');
    if (corrList) {
      corrList.querySelectorAll('input[type="checkbox"]').forEach(function (cb) {
        cb.addEventListener('change', function () { _scheduleAutoPreview(); });
      });
    }

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

    // Filter changes
    var filterSelect = document.getElementById('pg-filter-select');
    var maxScore = document.getElementById('pg-max-score');
    var skipAnalyzed = document.getElementById('pg-skip-analyzed');
    if (filterSelect) filterSelect.addEventListener('change', _onFilterChange);
    if (maxScore) { maxScore.addEventListener('change', _onFilterChange); maxScore.addEventListener('input', _onFilterChange); }
    if (skipAnalyzed) skipAnalyzed.addEventListener('change', _onFilterChange);

    // Row selection
    _wireRowSelection();
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

  function _wireRowSelection() {
    if (!_overlay) return;
    _overlay.querySelectorAll('.pg-item-card').forEach(function (card) {
      card.addEventListener('click', function () {
        _selectItem(card.dataset.itemId);
      });
    });
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

  function _selectItem(itemId) {
    _selectedItemId = itemId;
    _highlightSelectedRow();
    _scheduleAutoPreview();
    var testBtn = document.getElementById('pg-test-btn');
    if (testBtn && _config && _config.llm_configured) testBtn.disabled = false;
  }

  function _highlightSelectedRow() {
    if (!_overlay) return;
    _overlay.querySelectorAll('.pg-item-card').forEach(function (card) {
      card.classList.toggle('pg-item-selected', card.dataset.itemId === _selectedItemId);
    });
  }

  function _onFilterChange() {
    _matchedPage = 0;
    var matched = _getMatchedItems();
    _selectedItemId = matched.length > 0 ? matched[0].item_id : null;
    _refreshMatchedTable();
    _updateFooterCount();
    // Update badge on Filter section
    var filterSection = document.getElementById('pg-matched-section');
    if (filterSection) {
      var badge = filterSection.closest('.pg-section');
      if (badge) {
        var b = badge.querySelector('.pg-section-badge');
        if (b) b.textContent = String(matched.length);
      }
    }
    _scheduleAutoPreview();
  }

  function _refreshMatchedTable() {
    var section = document.getElementById('pg-matched-section');
    if (section) {
      section.innerHTML = _buildMatchedItemsTable();
      _wireRowSelection();
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
  }

  function _onAdditionalInstructionsChange() {
    var instrEl = document.getElementById('pg-additional-instructions');
    if (!instrEl) return;
    var newVars = _detectCustomVars(instrEl.value);
    if (JSON.stringify(newVars) !== JSON.stringify(_customVars)) {
      _customVars = newVars;
      var section = document.getElementById('pg-custom-vars-section');
      if (section) {
        section.innerHTML = _buildCustomVarsMapping();
        section.querySelectorAll('.pg-customvar-field').forEach(function (sel) {
          sel.addEventListener('change', function () {
            _onCustomVarFieldChange(sel);
            _scheduleAutoPreview();
          });
        });
      }
    }
  }

  function _onMappingFieldChange(sel) {
    var idx = sel.dataset.mappingIdx;
    var keys = _scanJsonKeys(sel.value);
    var keyEl = document.getElementById('pg-mapping-' + idx + '-key');
    var dotEl = document.getElementById('pg-mapping-' + idx + '-dot');

    if (keys.length > 0) {
      if (!keyEl) {
        var wrapper = sel.parentNode;
        var dot = document.createElement('span');
        dot.className = 'pg-mapping-dot';
        dot.id = 'pg-mapping-' + idx + '-dot';
        dot.textContent = '.';
        var keySelect = document.createElement('select');
        keySelect.className = 'pg-mapping-key-select';
        keySelect.id = 'pg-mapping-' + idx + '-key';
        keySelect.dataset.mappingIdx = idx;
        keySelect.innerHTML = '<option value="">(full object)</option>';
        for (var k = 0; k < keys.length; k++) {
          keySelect.innerHTML += '<option value="' + _escAttr(keys[k]) + '">' + _esc(keys[k]) + '</option>';
        }
        wrapper.appendChild(dot);
        wrapper.appendChild(keySelect);
        keySelect.addEventListener('change', function () { _scheduleAutoPreview(); });
      } else {
        keyEl.innerHTML = '<option value="">(full object)</option>';
        for (var k = 0; k < keys.length; k++) {
          keyEl.innerHTML += '<option value="' + _escAttr(keys[k]) + '">' + _esc(keys[k]) + '</option>';
        }
        keyEl.style.display = '';
        if (dotEl) dotEl.style.display = '';
      }
    } else {
      if (keyEl) { keyEl.style.display = 'none'; }
      if (dotEl) { dotEl.style.display = 'none'; }
    }
  }

  function _onCustomVarFieldChange(sel) {
    var idx = sel.dataset.customvarIdx;
    var field = sel.value;
    var wrapper = document.getElementById('pg-customvar-' + idx + '-key-wrapper');
    if (!wrapper) return;

    if (!field) { wrapper.innerHTML = ''; return; }

    var keys = _scanJsonKeys(field);
    if (keys.length > 0) {
      var html = '<span class="pg-mapping-dot">.</span>';
      html += '<select class="pg-mapping-key-select" id="pg-customvar-' + idx + '-key">';
      html += '<option value="">(full object)</option>';
      for (var k = 0; k < keys.length; k++) {
        html += '<option value="' + _escAttr(keys[k]) + '">' + _esc(keys[k]) + '</option>';
      }
      html += '</select>';
      wrapper.innerHTML = html;
      wrapper.querySelector('.pg-mapping-key-select').addEventListener('change', function () {
        _scheduleAutoPreview();
      });
    } else {
      wrapper.innerHTML = '';
    }
  }

  // ── Auto Preview (debounced) ──

  function _scheduleAutoPreview() {
    if (_previewTimer) clearTimeout(_previewTimer);
    _previewTimer = setTimeout(_autoPreview, 500);
  }

  function _autoPreview() {
    var content = document.getElementById('pg-preview-content');
    var toggleBtn = document.getElementById('pg-preview-toggle');
    var loading = document.getElementById('pg-preview-loading');
    var indicator = document.getElementById('pg-preview-indicator');

    try {
      var itemId = _selectedItemId;
      if (!itemId) {
        var matched = _getMatchedItems();
        if (matched.length > 0) itemId = matched[0].item_id;
      }

      if (!itemId) {
        if (content) content.textContent = 'No items match current filters.';
        if (toggleBtn) toggleBtn.style.display = 'none';
        return;
      }

      var runId = _getRunId();
      if (!runId) {
        if (content) content.textContent = 'Error: could not determine run ID.';
        return;
      }

      var base = _opts.apiUrl || function (p) { return '/' + p; };
      var cfg = _buildConfigPayload();
      var url = base('api/runs/' + runId + '/analyze-preview');

      if (loading) loading.style.display = 'block';
      if (indicator) { indicator.textContent = 'updating\u2026'; indicator.className = 'pg-auto-indicator pg-auto-updating'; }
      if (content) content.textContent = 'Loading preview for ' + itemId + '\u2026';

      fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_id: itemId, config: cfg }),
      })
      .then(function (r) {
        if (!r.ok) {
          return r.text().then(function (txt) {
            var detail;
            try { detail = JSON.parse(txt).detail; } catch (e) { detail = txt; }
            if (content) content.textContent = 'Error (HTTP ' + r.status + '): ' + (detail || 'Unknown error');
            return null;
          });
        }
        return r.json();
      })
      .then(function (data) {
        if (!data) return;
        if (data.messages && data.messages.length > 0) {
          var html = data.messages.map(function (m) {
            return '<div class="pg-preview-msg">' +
              '<div class="pg-preview-role pg-preview-role-' + _escAttr(m.role) + '">' + _esc(m.role.toUpperCase()) + '</div>' +
              '<div class="pg-preview-body">' + _highlightPreview(_esc(m.content)) + '</div>' +
            '</div>';
          }).join('');
          if (content) {
            content.innerHTML = html;
            content.classList.remove('expanded');
          }
          if (toggleBtn) { toggleBtn.style.display = 'inline-block'; toggleBtn.textContent = 'Expand'; }
        } else if (data.detail) {
          if (content) content.textContent = 'Error: ' + data.detail;
        } else {
          if (content) content.textContent = 'Preview returned empty response. Keys: ' + Object.keys(data).join(', ');
        }
      })
      .catch(function (err) {
        console.error('Auto-preview fetch error:', err);
        if (content) content.textContent = 'Preview failed: ' + err.message;
      })
      .finally(function () {
        if (loading) loading.style.display = 'none';
        if (indicator) { indicator.textContent = 'auto-updates'; indicator.className = 'pg-auto-indicator'; }
      });
    } catch (err) {
      console.error('Auto-preview sync error:', err);
      if (content) content.textContent = 'Preview error: ' + err.message;
    }
  }

  // ── Test (selected item) ──

  function _runTest() {
    if (_running) return;

    var testItemId = _selectedItemId;
    if (!testItemId) {
      var matched = _getMatchedItems();
      if (matched.length === 0) {
        if (_opts.showToast) _opts.showToast('warning', 'No Items', 'No items match current filters');
        return;
      }
      testItemId = matched[0].item_id;
    }

    _running = true;
    var runId = _getRunId();
    if (!runId) { _running = false; return; }
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    var cfg = _buildConfigPayload();

    var btn = document.getElementById('pg-test-btn');
    if (btn) { btn.disabled = true; btn.textContent = '\u23F3 Testing\u2026'; }

    var divider = document.getElementById('pg-results-divider');
    if (divider) divider.style.display = '';
    var results = document.getElementById('pg-test-results');
    if (results) results.innerHTML = '<div class="pg-loading">Running analysis\u2026</div>';

    fetch(base('api/runs/' + runId + '/analyze-test'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_ids: [testItemId], config: cfg }),
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
      if (btn) {
        btn.textContent = 'Test Selected';
        if (_config && _config.llm_configured) btn.disabled = false;
      }
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
    var SOL_COLORS = {
      'Improve Retrieval Context': '#3b82f6', 'Add Guardrails': '#ef4444',
      'Refine Prompt Instructions': '#f97316', 'Expand Training Data': '#10b981',
      'Fix Tool Configuration': '#ec4899', 'Add Output Validation': '#00d4aa',
      'Restructure Chain-of-Thought': '#a855f7', 'Update Knowledge Base': '#6366f1',
    };

    container.innerHTML = _testResults.map(function (r) {
      var color = RC_COLORS[r.root_cause] || '#e07a5f';
      var confPct = Math.round((r.confidence || 0) * 100);
      var errorHtml = r.error ? '<div class="pg-result-error">' + _esc(r.error) + '</div>' : '';

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

        var itemCtxMatch = userMsg.match(/Now analyze this evaluation item:\n\n([\s\S]*?)\n\nDetermine the root cause/)
          || userMsg.match(/Now analyze this evaluation item:\n\n([\s\S]*?)\n\n/);
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
              '<summary class="pg-result-details-summary">Item Context</summary>' +
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

      var solHtml = '';
      if (r.solution) {
        var solColor = SOL_COLORS[r.solution] || '#60a5fa';
        solHtml = '<div class="pg-result-solution" style="margin-top:10px;padding-top:8px;border-top:1px solid var(--modal-border, #333);">' +
          '<span style="color:var(--text-muted, #888);font-size:11px;text-transform:uppercase;letter-spacing:0.5px;">Solution</span>' +
          '<div style="color:' + solColor + ';font-weight:600;margin-top:2px;">' + _esc(r.solution) + '</div>' +
          (r.solution_note ? '<div class="pg-result-note" style="margin-top:2px;">' + _esc(r.solution_note) + '</div>' : '') +
        '</div>';
      }

      return '<div class="pg-test-result-card">' +
        '<div class="pg-result-header">' +
          '<span class="pg-result-item-id">' + _esc(r.item_id.slice(0, 24)) + '</span>' +
        '</div>' +
        (r.root_cause_detail ? '<div class="pg-result-rc" style="color:var(--text-primary, #eee);">' + _esc(r.root_cause_detail) + '</div>' : '') +
        '<div class="pg-result-rc" style="color:' + color + ';' + (r.root_cause_detail ? 'font-size:12px;opacity:0.8;margin-top:2px;' : '') + '">' + _esc(r.root_cause) + '</div>' +
        '<div class="pg-confidence-row">' +
          '<div class="pg-confidence-bar"><div class="pg-confidence-fill" style="width:' + confPct + '%;background:' + color + ';"></div></div>' +
          '<span class="pg-confidence-val">' + (r.confidence != null ? r.confidence.toFixed(2) : '?') + '</span>' +
        '</div>' +
        '<div class="pg-result-note">' + _esc(r.root_cause_note || '') + '</div>' +
        solHtml +
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
    if (btn) { btn.disabled = true; btn.textContent = '\u23F3 Running\u2026'; }

    var progress = document.getElementById('pg-runall-progress');
    var fill = document.getElementById('pg-runall-progress-fill');
    var progressText = document.getElementById('pg-runall-progress-text');
    if (progress) progress.style.display = 'block';
    if (fill) fill.style.width = '30%';
    if (progressText) progressText.textContent = 'Analyzing items\u2026';

    fetch(base('api/runs/' + runId + '/analyze'), {
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
