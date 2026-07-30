/**
 * QymPlayground — AI Evaluator Playground
 * Single-column layout with variable mapping, auto-preview, and matched items.
 * It can render as a modal or inside a dedicated page container.
 */
window.QymPlayground = (function () {
  'use strict';

  var _opts = {};
  var _overlay = null;
  var _config = null;
  var _connectionId = null;
  var _testResults = [];
  var _running = false;
  var _previewTimer = null;
  var _matchedPage = 0;
  var _PAGE_SIZE = 10;
  var _selectedItemId = null;
  var _customVars = [];
  var _configUnlocked = false;
  var _referenceDocuments = [];
  var _analysisRules = [];
  var _editingRuleIndex = null;
  var _ruleVersions = [];
  var _selectedRuleVersionId = null;
  var _canDeleteRuleVersions = false;
  var _canActivateRuleVersions = false;
  var _canRestoreRuleVersions = false;
  var _documentUploadsInFlight = 0;
  var _contextFeedbackTimer = null;
  var _ruleCompareOriginalParent = null;
  var _ruleCompareOriginalNextSibling = null;

  // ── Public API ──

  function init(opts) { _opts = opts || {}; }

  function open() {
    if (_overlay) { _overlay.style.display = 'flex'; return; }
    _fetchConfigAndOpen();
  }

  function close() {
    if (_opts.onClose) {
      _opts.onClose();
      return;
    }
    if (_overlay) _overlay.style.display = 'none';
  }

  // ── Fetch analyzer configuration then build modal ──

  function _fetchConfigAndOpen() {
    var runId = _getRunId();
    if (!runId) return;
    var base = _opts.apiUrl || function (p) { return '/' + p; };

    Promise.all([
      fetch(base('api/runs/' + runId + '/analysis-config')).then(function (r) { if (!r.ok) throw new Error('Config: HTTP ' + r.status); return r.json(); }),
      fetch(base('api/runs/' + runId + '/analysis-documents')).then(function (r) { if (!r.ok) throw new Error('Documents: HTTP ' + r.status); return r.json(); }),
      fetch(base('api/runs/' + runId + '/analysis-rule-versions?include_deleted=true')).then(function (r) { if (!r.ok) throw new Error('Rule versions: HTTP ' + r.status); return r.json(); }),
    ]).then(function (results) {
      _config = results[0];
      var _conns = (_config && _config.llm_connections) || [];
      _connectionId = (_config && _config.default_connection_id) || (_conns[0] && _conns[0].id) || null;
      _testResults = [];
      _matchedPage = 0;
      _selectedItemId = null;
      _customVars = [];
      _configUnlocked = true;
      _referenceDocuments = (results[1] && results[1].documents) || [];
      _analysisRules = (_config && _config.analysis_rules) || [];
      _editingRuleIndex = null;
      _ruleVersions = (results[2] && results[2].versions) || [];
      _selectedRuleVersionId = (_config && _config.analysis_rule_version && _config.analysis_rule_version.id)
        || (results[2] && results[2].production_version_id)
        || (_ruleVersions[0] && _ruleVersions[0].id)
        || null;
      var selectedRuleVersion = _ruleVersions.find(function (version) { return version.id === _selectedRuleVersionId; });
      if (selectedRuleVersion) _analysisRules = selectedRuleVersion.rules || [];
      _canDeleteRuleVersions = !!(results[2] && results[2].can_delete);
      _canActivateRuleVersions = !!(results[2] && results[2].can_activate);
      _canRestoreRuleVersions = !!(results[2] && results[2].can_restore);
      _documentUploadsInFlight = 0;
      _createModal();
      _overlay.style.display = 'flex';
    }).catch(function (err) {
      console.error('Playground: failed to load config', err);
      if (_opts.showToast) _opts.showToast('error', 'Playground Error', 'Failed to load configuration');
    });
  }

  // ── Helpers ──

  function _getRunId() { return _opts.getRunId ? _opts.getRunId() : null; }

  function _getSelectedMetrics() {
    if (_opts.getMetrics) {
      var selected = _opts.getMetrics();
      return Array.isArray(selected) ? selected : [];
    }
    var metric = _opts.getMetric ? _opts.getMetric() : null;
    return metric ? [metric] : null;
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

  function _formatCategoryExampleValue(value) {
    if (value == null || value === '') return '\u2014';
    if (typeof value === 'string') return value;
    try {
      return JSON.stringify(value, null, 2);
    } catch (error) {
      return String(value);
    }
  }

  function _buildCategoryExamples(examples) {
    var rows = Array.isArray(examples) ? examples : [];
    if (!rows.length) {
      return '<div class="pg-category-examples-empty">No approved examples in this category yet.</div>';
    }
    return '<div class="pg-category-example-list">' + rows.map(function (example) {
      var meta = [example.metric_name, example.run_name].filter(Boolean).join(' \u00b7 ');
      return '<details class="pg-category-example">' +
        '<summary class="pg-category-example-summary">' +
          '<span class="pg-category-example-title">Item ' + _esc(example.item_id || '\u2014') + '</span>' +
          '<span class="pg-category-example-meta">' + _esc(meta || 'Approved example') + '</span>' +
        '</summary>' +
        '<div class="pg-category-example-body">' +
          (example.detail ? '<div class="pg-category-example-field"><span>Detail</span><strong>' + _esc(example.detail) + '</strong></div>' : '') +
          (example.note ? '<div class="pg-category-example-field"><span>Reviewer reasoning</span><p>' + _esc(example.note) + '</p></div>' : '') +
          '<div class="pg-category-example-data">' +
            '<div><span>Input</span><pre>' + _esc(_formatCategoryExampleValue(example.input)) + '</pre></div>' +
            '<div><span>Expected</span><pre>' + _esc(_formatCategoryExampleValue(example.expected)) + '</pre></div>' +
            '<div><span>Output</span><pre>' + _esc(_formatCategoryExampleValue(example.output)) + '</pre></div>' +
          '</div>' +
          (example.solution || example.solution_note
            ? '<div class="pg-category-example-field"><span>Approved solution</span><strong>' + _esc(example.solution || '\u2014') + '</strong>' +
                (example.solution_note ? '<p>' + _esc(example.solution_note) + '</p>' : '') + '</div>'
            : '') +
        '</div>' +
      '</details>';
    }).join('') + '</div>';
  }

  function _buildCategoryGroup(category, details, examples) {
    var cat = String(category || '').trim();
    var catDetails = Array.isArray(details) ? details : [];
    var catExamples = Array.isArray(examples) ? examples : [];
    var html = '<article class="pg-category-group" data-cat="' + _escAttr(cat) + '" data-example-count="' + catExamples.length + '">';
    html += '<div class="pg-category-item">' +
      '<div class="pg-category-heading"><span class="pg-category-name">' + _esc(cat) + '</span>' +
        '<span class="pg-category-example-count">' + catExamples.length + (catExamples.length === 1 ? ' example' : ' examples') + '</span></div>' +
      '<button class="pg-category-remove" type="button" title="Remove category from this analysis" aria-label="Remove ' + _escAttr(cat) + ' category from this analysis">Remove</button>' +
    '</div>';
    html += '<div class="pg-category-content"><section class="pg-category-details"><h4>Category details</h4>';
    if (catDetails.length > 0) {
      html += '<div class="pg-details-sublist" data-cat="' + _escAttr(cat) + '">';
      for (var i = 0; i < catDetails.length; i++) {
        html += '<div class="pg-detail-item" data-detail="' + _escAttr(catDetails[i]) + '" data-parent-cat="' + _escAttr(cat) + '">' +
          '<span class="pg-detail-name">' + _esc(catDetails[i]) + '</span>' +
          '<button class="pg-detail-remove" type="button" title="Remove detail" aria-label="Remove ' + _escAttr(catDetails[i]) + ' detail">&times;</button>' +
        '</div>';
      }
      html += '</div>';
    } else {
      html += '<p class="pg-category-details-empty">No details configured.</p>';
    }
    html += '<div class="pg-add-detail-row" data-cat="' + _escAttr(cat) + '">' +
      '<input type="text" placeholder="Add detail..." aria-label="Add a detail to ' + _escAttr(cat) + '" class="pg-add-input pg-add-detail-input" />' +
      '<button type="button" class="pg-add-detail-btn pg-add-btn">Add</button>' +
    '</div></section>';
    html += '<section class="pg-category-examples"><div class="pg-category-examples-heading"><h4>Approved examples</h4>' +
      '<span>' + catExamples.length + '</span></div>' + _buildCategoryExamples(catExamples) + '</section></div></article>';
    return html;
  }

  function _icon(name) {
    var paths = {
      check: '<path d="m5 12 4 4L19 6"></path>',
      checkFilled: '<circle cx="12" cy="12" r="9" fill="currentColor" stroke="none"></circle><path d="m8 12 2.5 2.5L16 9" stroke="var(--bg-void)" fill="none"></path>',
      close: '<path d="M18 6 6 18M6 6l12 12"></path>',
      compare: '<path d="M7 7h11l-3-3m3 3-3 3M17 17H6l3 3m-3-3 3-3"></path>',
      copy: '<rect x="9" y="9" width="11" height="11" rx="2"></rect><path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3"></path>',
      edit: '<path d="M12 20h9"></path><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z"></path>',
      expand: '<path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"></path>',
      eye: '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"></path><circle cx="12" cy="12" r="2.5"></circle>',
      dots: '<circle cx="12" cy="5" r="1.4" fill="currentColor" stroke="none"></circle><circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none"></circle><circle cx="12" cy="19" r="1.4" fill="currentColor" stroke="none"></circle>',
      merge: '<path d="M6 4v4c0 4 2 6 6 6h6"></path><path d="M6 20v-4c0-4 2-6 6-6h6"></path><path d="m15 7 3 3-3 3"></path>',
      upload: '<path d="M12 14V4"></path><path d="m7 9 5-5 5 5"></path><path d="M5 14v6h14v-6"></path>',
      rocket: '<path d="M4.5 16.5c-1.5 1.3-2 5-2 5s3.7-.5 5-2a2.2 2.2 0 0 0-.1-2.9 2.2 2.2 0 0 0-2.9-.1Z"></path><path d="m12 15-3-3a22 22 0 0 1 2-4A13 13 0 0 1 22 2c0 2.7-.8 7.2-6 10a22 22 0 0 1-4 3Z"></path><path d="M9 12H4s.6-3 2-4c1.6-1.1 5 0 5 0"></path><path d="M12 15v5s3-.6 4-2c1.1-1.6 0-5 0-5"></path><circle cx="16" cy="8" r="1"></circle>',
      chevron: '<path d="m9 18 6-6-6-6"></path>',
      plus: '<path d="M12 5v14M5 12h14"></path>',
      trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v5M14 11v5"></path>',
    };
    return '<svg class="pg-action-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' +
      (paths[name] || paths.close) + '</svg>';
  }

  function _tryParseJsonValue(val) {
    if (val && typeof val === 'object') {
      return val;
    }
    if (typeof val === 'string') {
      var s = val.trim();
      if (!s) return null;
      try {
        var p = JSON.parse(s);
        if (p && typeof p === 'object') return p;
      } catch (e) {}
      return _tryParsePythonLiteralValue(s);
    }
    return null;
  }

  function _tryParsePythonLiteralValue(text) {
    if (!text || (text[0] !== '{' && text[0] !== '[')) return null;
    var out = '';
    var i = 0;
    while (i < text.length) {
      var ch = text[i];
      if (ch === "'" || ch === '"') {
        var parsed = _readPythonString(text, i);
        if (!parsed) return null;
        out += JSON.stringify(parsed.value);
        i = parsed.next;
        continue;
      }
      if (/[A-Za-z_]/.test(ch)) {
        var start = i;
        while (i < text.length && /[A-Za-z_]/.test(text[i])) i++;
        var word = text.slice(start, i);
        if (word === 'True') out += 'true';
        else if (word === 'False') out += 'false';
        else if (word === 'None') out += 'null';
        else return null;
        continue;
      }
      out += ch;
      i++;
    }
    try {
      var parsedValue = JSON.parse(out);
      return parsedValue && typeof parsedValue === 'object' ? parsedValue : null;
    } catch (e) {
      return null;
    }
  }

  function _readPythonString(text, start) {
    var quote = text[start];
    var value = '';
    for (var i = start + 1; i < text.length; i++) {
      var ch = text[i];
      if (ch === '\\') {
        i++;
        if (i >= text.length) return null;
        var esc = text[i];
        if (esc === 'n') value += '\n';
        else if (esc === 'r') value += '\r';
        else if (esc === 't') value += '\t';
        else if (esc === 'b') value += '\b';
        else if (esc === 'f') value += '\f';
        else if (esc === 'u' && i + 4 < text.length) {
          var hex = text.slice(i + 1, i + 5);
          if (/^[0-9a-fA-F]{4}$/.test(hex)) {
            value += String.fromCharCode(parseInt(hex, 16));
            i += 4;
          } else {
            value += esc;
          }
        } else {
          value += esc;
        }
        continue;
      }
      if (ch === quote) return { value: value, next: i + 1 };
      value += ch;
    }
    return null;
  }

  function _getRows() { return _opts.getRows ? _opts.getRows() : []; }

  function _truncate(val, maxLen) {
    if (val == null) return '\u2014';
    var s = (typeof val === 'object') ? JSON.stringify(val) : String(val);
    return s.length > maxLen ? s.slice(0, maxLen) + '\u2026' : s;
  }

  // Legacy root-cause palette shared by prompt previews, corrections, items,
  // and test results. Matching is case-insensitive so catalog variants do not
  // silently change color.
  var _RC_COLORS = {
    'Hallucination': '#ef4444', 'Incomplete Answer': '#f97316',
    'Wrong Format': '#00d4aa', 'Context Missing': '#3b82f6',
    'Reasoning Error': '#a855f7', 'Tool Use Error': '#ec4899',
    'Instruction Following': '#14b8a6', 'Knowledge Gap': '#6366f1',
    'Dataset Issue': '#eab308',
  };

  function _rootCauseColor(value, fallback) {
    var normalized = String(value || '').trim().toLowerCase();
    var names = Object.keys(_RC_COLORS);
    for (var i = 0; i < names.length; i++) {
      if (names[i].toLowerCase() === normalized) return _RC_COLORS[names[i]];
    }
    return fallback === undefined ? '#e07a5f' : fallback;
  }

  function _highlightPreview(escaped) {
    // Keep project rules readable without changing the copied prompt text.
    escaped = escaped.replace(
      /(ANALYSIS RULES:\n)([\s\S]*?)(\n\nBUSINESS CONTEXT:)/m,
      function (section, heading, rules, nextSection) {
        return heading +
          rules.replace(/^(\d+\. .+)$/gm, '<span class="pg-hl-rule-title">$1</span>') +
          nextSection;
      }
    );
    // Highlight section labels like INPUT:, EXPECTED OUTPUT:, ACTUAL OUTPUT:, etc.
    escaped = escaped.replace(/^(REFERENCE DOCUMENTS:|DOCUMENT:|INPUT:|EXPECTED OUTPUT:|ACTUAL OUTPUT:|ERROR:|SELECTED METRIC RESULT:|ITEM METADATA:|SELECTED METADATA:)/gm,
      '<span class="pg-hl-label">$1</span>');
    // Use one yellow treatment for every root-cause category, including custom languages.
    escaped = escaped.replace(/^( *- .+)$/gm, '<span class="pg-hl-category">$1</span>');
    // Highlight category headers in grouped details (e.g. "  Gold Query:")
    escaped = escaped.replace(/^( {2}\S.+:)$/gm,
      '<span class="pg-hl-label">$1</span>');
    // Highlight Additional Instructions block (label + all content after it until end)
    escaped = escaped.replace(/(Additional Instructions:\n)([\s\S]*)$/m,
      '<span class="pg-hl-label">$1</span><span class="pg-hl-dynamic">$2</span>');
    // Highlight JSON response format hints
    escaped = escaped.replace(/(&quot;root_cause&quot;|&quot;root_cause_detail&quot;|&quot;root_cause_note&quot;|&quot;confidence&quot;)/g,
      '<span class="pg-hl-json-key">$1</span>');
    return escaped;
  }

  function _isFieldJson(fieldName) {
    return _scanJsonPaths(fieldName).length > 0;
  }

  function _scanJsonPaths(fieldName) {
    var rows = _getRows();
    var paths = {};
    var limit = Math.min(rows.length, 20);
    for (var i = 0; i < limit; i++) {
      // Try the field directly, then the _full variant (raw object before stringify)
      var val = rows[i][fieldName];
      var fullVal = rows[i][fieldName + '_full'];
      var obj = _tryParseJsonValue(fullVal) || _tryParseJsonValue(val);
      if (obj) _collectJsonPaths(obj, '', paths, 0);
    }
    return Object.keys(paths).sort();
  }

  function _collectJsonPaths(val, prefix, paths, depth) {
    if (depth > 5 || val == null || typeof val !== 'object') return;
    if (Array.isArray(val)) {
      var arrPrefix = prefix ? prefix + '[]' : '[]';
      var hasNestedObject = false;
      for (var i = 0; i < Math.min(val.length, 5); i++) {
        if (val[i] && typeof val[i] === 'object') {
          hasNestedObject = true;
          _collectJsonPaths(val[i], arrPrefix, paths, depth + 1);
        }
      }
      if (prefix && !hasNestedObject) paths[prefix] = true;
      if (!prefix && !hasNestedObject) paths['[]'] = true;
      return;
    }
    Object.keys(val).sort().forEach(function (key) {
      var path = prefix ? prefix + '.' + key : key;
      if (val[key] && typeof val[key] === 'object') {
        _collectJsonPaths(val[key], path, paths, depth + 1);
      } else {
        paths[path] = true;
      }
    });
  }

  function _formatPathLabel(path) {
    return String(path || '').replace(/\[\]/g, '[*]');
  }

  function _pathsToTree(paths) {
    var root = { children: [], byLabel: {} };
    function ensureChild(parent, label, path) {
      var key = label + '\u0000' + path;
      if (!parent.byLabel[key]) {
        parent.byLabel[key] = { label: label, path: path, children: [], byLabel: {} };
        parent.children.push(parent.byLabel[key]);
      }
      return parent.byLabel[key];
    }
    for (var i = 0; i < paths.length; i++) {
      var rawParts = String(paths[i]).split('.');
      var parent = root;
      var built = '';
      for (var p = 0; p < rawParts.length; p++) {
        var part = rawParts[p];
        if (!part) continue;
        if (part.slice(-2) === '[]') {
          var base = part.slice(0, -2);
          if (base) {
            built = built ? built + '.' + base : base;
            parent = ensureChild(parent, base, built);
          }
          var arrayPath = built ? built + '[]' : '[]';
          parent = ensureChild(parent, '[*]', arrayPath);
          built = arrayPath;
        } else {
          built = built ? built + '.' + part : part;
          parent = ensureChild(parent, part, built);
        }
      }
    }
    function sortNodes(nodes) {
      nodes.sort(function (a, b) { return a.label.localeCompare(b.label); });
      for (var n = 0; n < nodes.length; n++) sortNodes(nodes[n].children);
    }
    sortNodes(root.children);
    return root.children;
  }

  function _renderPathTree(paths, valuePrefix, checkedByDefault) {
    var tree = _pathsToTree(paths);
    if (tree.length === 0) return '';
    return '<div class="pg-path-tree">' + _renderPathTreeNodes(tree, valuePrefix || '', 0, !!checkedByDefault) + '</div>';
  }

  function _renderPathTreeNodes(nodes, valuePrefix, level, checkedByDefault) {
    var html = '';
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      var value = valuePrefix ? valuePrefix + node.path : node.path;
      var hasChildren = node.children.length > 0;
      var indent = ' style="--pg-path-level:' + level + ';"';
      var checked = checkedByDefault ? ' checked' : '';
      var row = '<span class="pg-path-tree-row"' + indent + '>' +
        '<span class="custom-checkbox"><input type="checkbox" value="' + _escAttr(value) + '"' + checked + ' /><span class="checkmark"></span></span>' +
        '<span class="pg-path-name">' + _esc(_formatPathLabel(node.label)) + '</span>' +
        (hasChildren ? '<span class="pg-path-node-type">group</span>' : '') +
      '</span>';
      if (hasChildren) {
        html += '<details class="pg-path-tree-node" open><summary>' + row + '</summary>' +
          _renderPathTreeNodes(node.children, valuePrefix, level + 1, checkedByDefault) +
        '</details>';
      } else {
        html += '<div class="pg-path-tree-leaf">' + row + '</div>';
      }
    }
    return html;
  }

  function _buildPathPicker(id, fieldName) {
    if (fieldName === 'metric_metadata') return _buildMetricMetadataPicker(id);
    var paths = _scanJsonPaths(fieldName);
    if (paths.length === 0) return '';
    var html = '<div class="pg-path-picker" id="' + _escAttr(id) + '" data-field="' + _escAttr(fieldName) + '">';
    html += '<div class="pg-path-picker-head"><div><span class="pg-path-title">JSON fields</span><span class="pg-path-subtitle">Choose the exact keys to send</span></div><span class="pg-path-summary" id="' + _escAttr(id) + '-summary">Full value</span></div>';
    html += '<label class="pg-path-full-row"><span class="custom-checkbox"><input type="checkbox" data-full="1" checked /><span class="checkmark"></span></span><span><strong>Use full value</strong><small>Send the complete JSON object for this variable</small></span></label>';
    html += '<div class="pg-path-list">';
    html += _renderPathTree(paths, '');
    html += '</div></div>';
    return html;
  }

  function _scanMetricMetadataGroups() {
    var rows = _getRows();
    var groups = {};
    var selectedMetric = _opts.getMetric ? _opts.getMetric() : null;
    var limit = Math.min(rows.length, 20);
    for (var i = 0; i < limit; i++) {
      var byMetric = rows[i].metric_metadata_by_metric;
      if (byMetric && typeof byMetric === 'object' && !Array.isArray(byMetric)) {
        Object.keys(byMetric).forEach(function (metricName) {
          var obj = _tryParseJsonValue(byMetric[metricName]);
          if (!obj) return;
          if (!groups[metricName]) groups[metricName] = {};
          _collectJsonPaths(obj, '', groups[metricName], 0);
        });
      } else {
        var fallback = _tryParseJsonValue(rows[i].metric_metadata);
        if (fallback) {
          var name = selectedMetric || 'metric metadata';
          if (!groups[name]) groups[name] = {};
          _collectJsonPaths(fallback, '', groups[name], 0);
        }
      }
    }
    var names = Object.keys(groups).sort(function (a, b) {
      if (selectedMetric && a === selectedMetric) return -1;
      if (selectedMetric && b === selectedMetric) return 1;
      return a.localeCompare(b);
    });
    return names.map(function (name) {
      return { metric: name, paths: Object.keys(groups[name]).sort() };
    }).filter(function (group) { return group.paths.length > 0; });
  }

  function _buildMetricMetadataPicker(id) {
    var groups = _scanMetricMetadataGroups();
    if (groups.length === 0) return '';
    var selectedMetric = _opts.getMetric ? _opts.getMetric() : null;
    var html = '<div class="pg-path-picker pg-metric-path-picker" id="' + _escAttr(id) + '" data-field="metric_metadata" data-grouped="metric" data-default-all="1">';
    html += '<div class="pg-path-picker-head"><div><span class="pg-path-title">Metric metadata fields</span><span class="pg-path-subtitle">All fields are selected by default</span></div><span class="pg-path-summary" id="' + _escAttr(id) + '-summary">All selected</span></div>';
    html += '<div class="pg-metric-path-groups">';
    for (var g = 0; g < groups.length; g++) {
      var group = groups[g];
      var metricLabel = group.metric;
      html += '<details class="pg-metric-path-group"' + (selectedMetric && group.metric === selectedMetric ? ' open' : '') + '>';
      html += '<summary><span class="pg-metric-path-name">' + _esc(metricLabel) + '</span><span class="pg-metric-path-count">' + group.paths.length + '</span></summary>';
      html += '<div class="pg-path-list">';
      var encodedMetric = encodeURIComponent(group.metric).replace(/\./g, '%2E');
      html += _renderPathTree(group.paths, 'metric_metadata:' + encodedMetric + '.', true);
      html += '</div></details>';
    }
    html += '</div></div>';
    return html;
  }

  function _getPathPickerSelection(id, fieldName) {
    var picker = document.getElementById(id);
    if (!picker) return { source: fieldName, custom: false };
    var full = picker.querySelector('input[data-full="1"]');
    if (full && full.checked) return { source: fieldName, custom: false };
    var selected = [];
    picker.querySelectorAll('.pg-path-list input[type="checkbox"]:checked').forEach(function (cb) {
      if (!cb.value) return;
      selected.push(picker.dataset.grouped === 'metric' ? cb.value : fieldName + '.' + cb.value);
    });
    if (picker.dataset.defaultAll === '1') {
      var allBoxes = picker.querySelectorAll('.pg-path-list input[type="checkbox"][value]');
      if (allBoxes.length > 0 && selected.length === allBoxes.length) {
        return { source: fieldName, custom: false };
      }
    }
    return { source: _pruneSelectedPaths(selected), custom: true };
  }

  function _pruneSelectedPaths(paths) {
    var sorted = paths.slice().sort(function (a, b) { return a.length - b.length; });
    var kept = [];
    for (var i = 0; i < sorted.length; i++) {
      var path = sorted[i];
      var covered = false;
      for (var k = 0; k < kept.length; k++) {
        if (path.indexOf(kept[k] + '.') === 0 || path.indexOf(kept[k] + '[]') === 0) {
          covered = true;
          break;
        }
      }
      if (!covered) kept.push(path);
    }
    return kept;
  }

  function _updatePathPickerSummary(picker) {
    if (!picker) return;
    var summary = picker.querySelector('.pg-path-summary');
    if (!summary) return;
    var full = picker.querySelector('input[data-full="1"]');
    var count = picker.querySelectorAll('.pg-path-list input[type="checkbox"]:checked').length;
    var total = parseInt(picker.dataset.totalPathBoxes || '0', 10);
    if (!total) {
      total = picker.querySelectorAll('.pg-path-list input[type="checkbox"][value]').length;
      picker.dataset.totalPathBoxes = String(total);
    }
    if (picker.dataset.defaultAll === '1') {
      summary.textContent = count === total ? 'All selected' : (count === 0 ? 'No fields' : count + ' of ' + total);
      return;
    }
    var fullText = picker.dataset.grouped === 'metric' ? 'All metrics' : 'Full value';
    summary.textContent = full && full.checked ? fullText : (count === 0 ? 'No fields' : count + ' selected');
  }

  function _setTreeDescendants(cb, checked) {
    var node = cb.closest('.pg-path-tree-node');
    if (!node) return;
    var inputs = node.querySelectorAll('input[type="checkbox"][value]');
    inputs.forEach(function (child) {
      if (child !== cb) {
        child.checked = checked;
        child.indeterminate = false;
      }
    });
  }

  function _syncTreeNodeState(node) {
    var summary = node.querySelector('summary');
    var parentCb = summary ? summary.querySelector('input[type="checkbox"][value]') : null;
    if (!parentCb) return;
    var descendants = Array.prototype.slice.call(node.querySelectorAll('input[type="checkbox"][value]')).filter(function (input) {
      return input !== parentCb;
    });
    if (descendants.length === 0) return;
    var checkedCount = 0;
    var hasIndeterminate = false;
    for (var i = 0; i < descendants.length; i++) {
      if (descendants[i].checked) checkedCount++;
      if (descendants[i].indeterminate) hasIndeterminate = true;
    }
    parentCb.checked = checkedCount === descendants.length && !hasIndeterminate;
    parentCb.indeterminate = (checkedCount > 0 && checkedCount < descendants.length) || hasIndeterminate;
  }

  function _syncTreeAncestors(cb) {
    var node = cb.closest('.pg-path-tree-node');
    while (node) {
      _syncTreeNodeState(node);
      node = node.parentElement ? node.parentElement.closest('.pg-path-tree-node') : null;
    }
  }

  function _wirePathPickers(root) {
    (root || document).querySelectorAll('.pg-path-picker input[type="checkbox"]').forEach(function (cb) {
      if (cb.dataset.pgWired) return;
      cb.dataset.pgWired = '1';
      cb.addEventListener('click', function (e) { e.stopPropagation(); });
      cb.addEventListener('change', function () {
        var picker = cb.closest('.pg-path-picker');
        if (!picker) return;
        var full = picker.querySelector('input[data-full="1"]');
        if (cb.dataset.full === '1' && cb.checked) {
          picker.querySelectorAll('.pg-path-list input[type="checkbox"]').forEach(function (pathCb) { pathCb.checked = false; });
        } else if (cb.checked && full) {
          full.checked = false;
        }
        if (cb.value) {
          cb.indeterminate = false;
          _setTreeDescendants(cb, cb.checked);
          _syncTreeAncestors(cb);
        }
        _updatePathPickerSummary(picker);
        _scheduleAutoPreview(900);
      });
    });
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
    var maxScoreEl = document.getElementById('pg-max-score');
    var skipEl = document.getElementById('pg-skip-analyzed');

    var itemFilter = 'failed';
    var maxScore = maxScoreEl ? parseFloat(maxScoreEl.value) / 100 : NaN;
    var skipAnalyzed = skipEl ? skipEl.checked : true;
    var humanOverwriteEl = document.getElementById('pg-allow-human-overwrite');
    var allowHumanOverwrite = humanOverwriteEl ? humanOverwriteEl.checked : false;
    var threshold = _opts.getThreshold ? _opts.getThreshold() : 0.8;
    var selectedMetrics = _getSelectedMetrics();

    return rows.filter(function (r) {
      var md = r.item_metadata;
      if (!allowHumanOverwrite && md && typeof md === 'object' && md.root_cause_source === 'human') return false;
      var isError = !!r.error;
      var score = r.metric_score;
      var metricScores = r.metric_scores && typeof r.metric_scores === 'object' ? r.metric_scores : null;
      var metricThresholds = r.metric_thresholds && typeof r.metric_thresholds === 'object' ? r.metric_thresholds : {};
      var metricDirections = r.metric_directions && typeof r.metric_directions === 'object' ? r.metric_directions : {};
      var failedMetrics = [];
      if (metricScores) {
        Object.keys(metricScores).forEach(function (metricName) {
          if (selectedMetrics && selectedMetrics.indexOf(metricName) === -1) return;
          var metricScore = metricScores[metricName];
          var metricThreshold = metricThresholds[metricName] == null ? threshold : Number(metricThresholds[metricName]);
          var direction = String(metricDirections[metricName] || 'maximize').toLowerCase();
          var metricPassed = metricScore != null && (
            direction === 'minimize' || direction === 'lower' || direction === 'lower_is_better'
              ? Number(metricScore) <= metricThreshold
              : Number(metricScore) >= metricThreshold
          );
          if (isError || !metricPassed) failedMetrics.push(metricName);
        });
      }
      if (!metricScores && (isError || score == null || score < threshold)) {
        failedMetrics.push(_opts.getMetric ? (_opts.getMetric() || 'metric') : 'metric');
      }
      if (skipAnalyzed && failedMetrics.length > 0) {
        var existing = md && typeof md.metric_analyses === 'object' ? md.metric_analyses : {};
        failedMetrics = failedMetrics.filter(function (metricName) {
          return !(existing[metricName] && existing[metricName].root_cause);
        });
      }
      if (itemFilter === 'errors') {
        if (!isError) return false;
      } else if (itemFilter === 'failed') {
        if (failedMetrics.length === 0) return false;
      } else if (itemFilter === 'passed') {
        if (isError) return false;
        if (failedMetrics.length > 0) return false;
      }
      if (!isNaN(maxScore)) {
        if (metricScores) {
          var hasScoreAtOrBelowMax = failedMetrics.some(function (metricName) {
            var metricScore = metricScores[metricName];
            var direction = String(metricDirections[metricName] || 'maximize').toLowerCase();
            var isMinimize = direction === 'minimize' || direction === 'lower' || direction === 'lower_is_better';
            return isMinimize || metricScore == null || Number(metricScore) <= maxScore;
          });
          if (!hasScoreAtOrBelowMax) return false;
        } else if (score != null && score > maxScore) {
          return false;
        }
      }
      r._matched_metric_names = failedMetrics;
      return true;
    });
  }

  function _getMatchedTargetCount(matchedItems) {
    return (matchedItems || []).reduce(function (total, row) {
      var metrics = Array.isArray(row._matched_metric_names) ? row._matched_metric_names : [];
      return total + Math.max(metrics.length, 1);
    }, 0);
  }

  // ── Create modal DOM ──

  function _createModal() {
    if (_overlay && _overlay.parentNode) { _overlay.parentNode.removeChild(_overlay); _overlay = null; }

    var pageContainer = null;
    if (_opts.container) {
      pageContainer = typeof _opts.container === 'string'
        ? document.querySelector(_opts.container)
        : _opts.container;
    }

    var overlay = document.createElement('div');
    overlay.className = 'playground-overlay' + (pageContainer ? ' playground-page-overlay' : '');
    if (!pageContainer) {
      overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
    }

    var modal = document.createElement('div');
    modal.className = 'playground-modal';

    // Header
    var header = document.createElement('div');
    header.className = 'playground-header';
    header.innerHTML =
      '<div class="playground-header-left">' +
        '<span class="playground-header-icon">&#x1F916;</span>' +
        '<span class="playground-header-title">LLM Analyzer</span>' +
      '</div>' +
      '<button class="playground-close" title="Close">&times;</button>';
    header.querySelector('.playground-close').addEventListener('click', close);
    modal.appendChild(header);

    // LLM not configured banner
    if (_config && !_config.llm_configured) {
      var banner = document.createElement('div');
      banner.className = 'playground-banner playground-banner-warn';
      banner.textContent = 'No LLM connection for this project \u2014 add one in Project Settings \u2192 LLM Connections to enable Test and Run';
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
    var conns = (_config && _config.llm_connections) || [];
    var connSelect = '';
    if (conns.length) {
      var selectedConnection = conns.find(function (connection) { return connection.id === _connectionId; }) || conns[0];
      connSelect = '<div class="pg-connection" id="pg-connection-picker">' +
        '<button class="pg-connection-trigger" id="pg-connection-trigger" type="button" aria-haspopup="listbox" aria-expanded="false">' +
          '<span class="pg-connection-icon" aria-hidden="true">◈</span>' +
          '<span class="pg-connection-copy"><span class="pg-connection-label">LLM connection</span>' +
          '<span class="pg-connection-value" id="pg-connection-value">' + _esc(selectedConnection.name) +
            (selectedConnection.llm_model ? ' · ' + _esc(selectedConnection.llm_model) : '') + '</span></span>' +
          '<span class="pg-connection-chevron" aria-hidden="true">⌄</span>' +
        '</button>' +
        '<div class="pg-connection-menu" id="pg-connection-menu" role="listbox" aria-label="LLM connections" hidden>' +
          conns.map(function (c) {
            var selected = c.id === _connectionId;
            return '<button class="pg-connection-option" type="button" role="option" data-connection-id="' + _escAttr(c.id) + '"' +
              ' aria-selected="' + (selected ? 'true' : 'false') + '"' + (c.llm_api_key_set ? '' : ' disabled') + '>' +
              '<span class="pg-connection-option-copy"><strong>' + _esc(c.name) + '</strong>' +
                '<span>' + _esc(c.llm_model || 'Model not set') + '</span></span>' +
              '<span class="pg-connection-option-state">' + (c.llm_api_key_set ? (selected ? 'Selected' : 'Available') : 'Key missing') + '</span>' +
            '</button>';
          }).join('') +
        '</div>' +
        '<select id="pg-connection" class="pg-connection-select" tabindex="-1" aria-hidden="true">' +
        conns.map(function (c) {
          return '<option value="' + _esc(c.id) + '"' + (c.id === _connectionId ? ' selected' : '') +
            (c.llm_api_key_set ? '' : ' disabled') + '>' + _esc(c.name) + (c.llm_model ? ' (' + _esc(c.llm_model) + ')' : '') + '</option>';
        }).join('') +
        '</select>' +
        '</div>';
    }
    footer.innerHTML =
      connSelect +
      '<button class="pg-footer-btn pg-footer-test" id="pg-test-btn" ' + (!llmOk ? 'disabled' : '') + '>Test Selected</button>' +
      '<button class="pg-footer-btn pg-footer-runall" id="pg-runall-btn" ' + (!llmOk ? 'disabled' : '') + '>Analyze ' + _getTargetLimit(_getMatchedTargetCount(_getMatchedItems())) + ' targets</button>';
    footer.hidden = false;
    modal.appendChild(footer);
    var connEl = footer.querySelector('#pg-connection');
    if (connEl) connEl.addEventListener('change', function () { _connectionId = connEl.value || null; });
    _wireConnectionPicker(footer);

    overlay.appendChild(modal);
    (pageContainer || document.body).appendChild(overlay);
    _overlay = overlay;

    // Wire all events
    _wireEvents();
    document.addEventListener('keydown', _onKeyDown);
    // Initialize once the controls are mounted so target matching reads their
    // real values instead of the pre-mount empty DOM.
    _onFilterChange();
  }

  function _onKeyDown(e) {
    if (e.key !== 'Escape' || !_overlay || _overlay.style.display === 'none') return;
    var connectionMenu = document.getElementById('pg-connection-menu');
    if (connectionMenu && !connectionMenu.hidden) {
      _setConnectionMenuOpen(false);
      return;
    }
    close();
  }

  function _setConnectionMenuOpen(open) {
    var trigger = document.getElementById('pg-connection-trigger');
    var menu = document.getElementById('pg-connection-menu');
    if (!trigger || !menu) return;
    menu.hidden = !open;
    trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) {
      var selected = menu.querySelector('[aria-selected="true"]:not(:disabled)');
      var first = menu.querySelector('.pg-connection-option:not(:disabled)');
      (selected || first || menu).focus();
    }
  }

  function _wireConnectionPicker(footer) {
    var picker = footer.querySelector('#pg-connection-picker');
    var trigger = footer.querySelector('#pg-connection-trigger');
    var menu = footer.querySelector('#pg-connection-menu');
    var select = footer.querySelector('#pg-connection');
    if (!picker || !trigger || !menu || !select) return;
    trigger.addEventListener('click', function () {
      _setConnectionMenuOpen(menu.hidden);
    });
    menu.addEventListener('click', function (event) {
      var option = event.target.closest('.pg-connection-option');
      if (!option || option.disabled) return;
      var connection = ((_config && _config.llm_connections) || []).find(function (item) {
        return item.id === option.dataset.connectionId;
      });
      if (!connection) return;
      _connectionId = connection.id;
      select.value = connection.id;
      var value = footer.querySelector('#pg-connection-value');
      if (value) value.textContent = connection.name + (connection.llm_model ? ' · ' + connection.llm_model : '');
      menu.querySelectorAll('.pg-connection-option').forEach(function (candidate) {
        var selected = candidate === option;
        candidate.setAttribute('aria-selected', selected ? 'true' : 'false');
        var state = candidate.querySelector('.pg-connection-option-state');
        if (state && !candidate.disabled) state.textContent = selected ? 'Selected' : 'Available';
      });
      _setConnectionMenuOpen(false);
      trigger.focus();
      _syncActionAvailability();
      _scheduleAutoPreview(0);
    });
    var modal = footer.closest('.playground-modal');
    if (modal) {
      modal.addEventListener('click', function (event) {
        if (!picker.contains(event.target) && !menu.hidden) _setConnectionMenuOpen(false);
      });
    }
  }

  // ── Build scrollable content ──

  function _section(title, body, opts) {
    var o = opts || {};
    var open = o.open !== false ? ' open' : '';
    var badgeId = o.badgeId ? ' id="' + o.badgeId + '"' : '';
    var badge = o.badge ? '<span class="pg-section-badge"' + badgeId + '>' + o.badge + '</span>' : '';
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

  function _formatCharacterCount(value) {
    return Number(value || 0).toLocaleString() + ' characters';
  }

  function _formatRuleCount() {
    var count = _analysisRules.length;
    var characters = _analysisRules.reduce(function (total, rule) {
      return total + String(rule.title || '').length + String(rule.instruction || '').length;
    }, 0);
    var estimatedTokens = Math.ceil(characters / 4);
    return count + ' ' + (count === 1 ? 'rule' : 'rules') +
      ' · ~' + estimatedTokens.toLocaleString() + ' prompt tokens · no rule count limit';
  }

  function _buildAnalysisRulesEditor() {
    var selected = _ruleVersions.find(function (version) { return version.id === _selectedRuleVersionId; });
    var readOnly = !selected || selected.status !== 'draft';
    if (_analysisRules.length === 0) {
      return '<div class="pg-rule-empty">' + (readOnly
        ? 'This version has no rules. Create a draft before editing.'
        : 'No rules yet. Generate rules after selecting reference documents, or add one manually.') + '</div>';
    }
    return _analysisRules.map(function (rule, index) {
      var editing = _editingRuleIndex === index;
      var ruleName = rule.title || 'rule ' + (index + 1);
      var instruction = rule.instruction || 'No instruction yet.';
      return '<div class="pg-rule-item' + (editing ? ' pg-rule-item-editing' : '') + '" data-rule-index="' + index + '" data-rule-id="' + _escAttr(rule.id || '') + '">' +
        '<div class="pg-rule-item-head" data-toggle-rule="' + index + '" role="button" tabindex="0" aria-expanded="' + (editing ? 'true' : 'false') + '" aria-label="' + (editing ? 'Collapse ' : 'Expand ') + _escAttr(ruleName) + '">' +
          '<span class="pg-rule-item-number">' + (index + 1) + '</span>' +
          '<span class="pg-rule-item-summary"><strong title="' + _escAttr(rule.title || 'Untitled rule') + '">' + _esc(rule.title || 'Untitled rule') + '</strong><span title="' + _escAttr(instruction) + '">' + _esc(instruction) + '</span></span>' +
          '<span class="pg-rule-disclosure" aria-hidden="true">' + _icon('chevron') + '</span>' +
          (!readOnly ? '<button class="pg-rule-action pg-rule-action-danger pg-icon-button pg-rule-remove" type="button" data-rule-index="' + index + '" title="Remove ' + _escAttr(ruleName) + '" aria-label="Remove ' + _escAttr(ruleName) + '">' + _icon('trash') + '</button>' : '') + '</div>' +
        '<div class="pg-rule-fields"' + (editing ? '' : ' hidden') + '>' +
          '<input class="pg-rule-title" type="text" value="' + _escAttr(rule.title || '') + '" placeholder="Rule title" aria-label="Rule title"' + (readOnly ? ' disabled' : '') + ' />' +
          '<textarea class="pg-rule-instruction" placeholder="What must be checked and how it affects the diagnosis" aria-label="Rule instruction"' + (readOnly ? ' disabled' : '') + '>' + _esc(rule.instruction || '') + '</textarea>' +
        '</div>' +
      '</div>';
    }).join('');
  }

  function _ruleVersionStateLabel(version) {
    if (version && version.is_active) return 'Live';
    if (version && version.status === 'draft') return 'Draft';
    if (version && version.status === 'published') return 'Published';
    var raw = String((version && version.status) || 'Unknown');
    return raw.charAt(0).toUpperCase() + raw.slice(1).toLowerCase();
  }

  function _buildRuleVersionHistory() {
    if (_ruleVersions.length === 0) {
      return '<div class="pg-rule-empty">No saved versions yet.</div>';
    }
    var liveVersionCount = _ruleVersions.filter(function (version) { return !version.is_deleted; }).length;
    var versionById = {};
    _ruleVersions.forEach(function (version) { versionById[version.id] = version; });
    return _ruleVersions.map(function (version) {
      var state = _ruleVersionStateLabel(version);
      var created = version.created_at ? new Date(version.created_at).toLocaleString() : 'Unknown date';
      var lifecycleAction = '';
      if (version.status === 'draft' && _canActivateRuleVersions) {
        lifecycleAction = '<button class="pg-rule-version-lifecycle pg-rule-version-lifecycle-draft" type="button" data-publish-rule-version="' + _escAttr(version.id) + '" title="Publish v' + version.version + '" aria-label="Publish version ' + version.version + '">' + _icon('upload') + '<span class="pg-rule-version-lifecycle-label">Publish</span></button>';
      } else if (version.status === 'published' && !version.is_active && _canActivateRuleVersions) {
        lifecycleAction = '<button class="pg-rule-version-lifecycle pg-rule-version-lifecycle-published" type="button" data-activate-rule-version="' + _escAttr(version.id) + '" title="Promote v' + version.version + ' to production" aria-label="Promote version ' + version.version + ' to production">' + _icon('rocket') + '<span class="pg-rule-version-lifecycle-label">Promote</span></button>';
      } else if (version.is_active) {
        lifecycleAction = '<span class="pg-rule-version-lifecycle pg-rule-version-production" title="Live version" aria-label="Live version">' + _icon('checkFilled') + '<span class="pg-rule-version-lifecycle-label">Live</span></span>';
      } else {
        lifecycleAction = '<span class="pg-rule-version-lifecycle" title="' + _escAttr(state) + '" aria-label="' + _escAttr(state) + '">' + _icon('check') + '<span class="pg-rule-version-lifecycle-label">' + _esc(state) + '</span></span>';
      }

      var menuActions = [];
      if (liveVersionCount > 1 && !version.is_deleted) {
        menuActions.push('<button type="button" role="menuitem" data-compare-rule-version="' + _escAttr(version.id) + '">' + _icon('compare') + '<span>Compare with…</span></button>');
        menuActions.push('<button type="button" role="menuitem" data-merge-rule-version="' + _escAttr(version.id) + '">' + _icon('merge') + '<span>Merge with…</span></button>');
      }
      if (_canDeleteRuleVersions && !version.is_deleted && liveVersionCount > 1) {
        menuActions.push('<button class="pg-rule-version-menu-danger" type="button" role="menuitem" data-delete-rule-version="' + _escAttr(version.id) + '">' + _icon('trash') + '<span>Delete version</span></button>');
      }
      var parent = versionById[version.parent_version_id];
      var mergeParents = (version.merge_parent_ids || []).map(function (id) { return versionById[id]; }).filter(Boolean);
      var lineage = [];
      if (parent) lineage.push('forked from v' + parent.version);
      if (mergeParents.length) lineage.push('merged ' + mergeParents.map(function (item) { return 'v' + item.version; }).join(', '));
      var versionDescription = state + ', ' + version.rules.length + ' rules, ' + created;
      var menu = menuActions.length
        ? '<div class="pg-rule-version-overflow">' +
            '<button class="pg-rule-version-menu-toggle" type="button" data-rule-version-menu-toggle title="More actions for v' + version.version + '" aria-label="More actions for version ' + version.version + '" aria-expanded="false">' + _icon('dots') + '</button>' +
            '<div class="pg-rule-version-menu" role="menu" hidden>' + menuActions.join('') + '</div>' +
          '</div>'
        : '';
      return '<div class="pg-rule-version' + (version.id === _selectedRuleVersionId ? ' pg-rule-version-selected' : '') + '" role="button" tabindex="0" aria-label="Open version ' + version.version + '. ' + _escAttr(versionDescription) + '" ' +
        'data-rule-version-id="' + _escAttr(version.id) + '" data-rule-parent-id="' + _escAttr(version.parent_version_id || '') + '" ' +
        'data-rule-version-status="' + _escAttr(state) + '" data-rule-merge-parent-ids="' + _escAttr((version.merge_parent_ids || []).join(',')) + '">' +
        '<span class="pg-rule-node" data-version-node="' + _escAttr(version.id) + '" aria-hidden="true"></span>' +
        '<span class="pg-rule-version-name">v' + version.version + '</span>' +
        '<span class="pg-visually-hidden pg-rule-version-state">' + _esc(state) + '</span>' +
        (lineage.length ? '<span class="pg-visually-hidden pg-rule-version-lineage">' + _esc(lineage.join(' · ')) + '</span>' : '') +
        '<span class="pg-rule-version-controls">' + lifecycleAction + menu + '</span>' +
      '</div>';
    }).join('');
  }

  function _buildReferenceDocumentList() {
    if (_referenceDocuments.length === 0) {
      return '<div class="pg-document-empty">No project documents yet. Add a document here and it becomes available to every analysis in this project.</div>';
    }
    return _referenceDocuments.map(function (document, index) {
      var meta = _formatCharacterCount(document.characters || document.content.length);
      if (document.truncated) meta += ' · shortened to prompt limit';
      var selected = document.selected !== false;
      return '<div class="pg-document-item' + (selected ? '' : ' pg-document-item-excluded') + '" data-document-index="' + index + '">' +
        '<label class="pg-document-toggle" title="' + (selected ? 'Included in project analysis' : 'Excluded from project analysis') + '">' +
          '<input class="pg-document-select" type="checkbox" data-document-index="' + index + '"' + (selected ? ' checked' : '') + ' />' +
          '<span class="pg-document-check" aria-hidden="true"></span>' +
          '<span class="pg-document-state">' + (selected ? 'Included' : 'Excluded') + '</span>' +
        '</label>' +
        '<div class="pg-document-copy">' +
          '<span class="pg-document-name">' + _esc(document.name) + '</span>' +
          '<span class="pg-document-meta">' + _esc(meta) + '</span>' +
        '</div>' +
        '<button class="pg-document-remove pg-icon-button" type="button" data-document-index="' + index + '" title="Delete ' + _escAttr(document.name) + '" aria-label="Delete ' + _escAttr(document.name) + '">' + _icon('trash') + '</button>' +
      '</div>';
    }).join('');
  }

  function _buildScrollContent() {
    var cats = (_config && _config.default_categories) || [
      'Hallucination', 'Incomplete Answer', 'Wrong Format', 'Context Missing',
      'Reasoning Error', 'Tool Use Error', 'Instruction Following', 'Knowledge Gap',
    ];
    var html = '<div class="pg-workspace">';

    var rulesBody = '<details class="pg-rule-inference-options">' +
        '<summary class="pg-rule-inference-heading"><span>Generate rules from</span><span class="pg-rule-inference-summary"><span id="pg-infer-source-summary">2 of 2 sources enabled</span><span class="pg-rule-inference-chevron" aria-hidden="true">' + _icon('chevron') + '</span></span></summary>' +
        '<div class="pg-rule-inference-content">' +
          '<label class="pg-inference-toggle">' +
            '<input id="pg-infer-use-documents" type="checkbox" checked />' +
            '<span class="pg-inference-switch" aria-hidden="true"></span>' +
            '<span class="pg-inference-copy"><strong>Project documents</strong><span>Use the documents enabled for this project.</span></span>' +
          '</label>' +
          '<label class="pg-inference-toggle">' +
            '<input id="pg-infer-use-examples" type="checkbox" checked />' +
            '<span class="pg-inference-switch" aria-hidden="true"></span>' +
            '<span class="pg-inference-copy"><strong>Approved examples</strong><span>Use every approved correction for this project and task.</span></span>' +
          '</label>' +
        '</div>' +
      '</details>' +
      '<div class="pg-rule-list" id="pg-rule-list">' + _buildAnalysisRulesEditor() + '</div>' +
      '<div class="pg-rule-editor-actions">' +
        '<span class="pg-rule-count" id="pg-rule-count" aria-live="polite">' + _formatRuleCount() + '</span>' +
        '<button class="pg-context-secondary pg-icon-button" id="pg-add-rule" type="button" title="Add rule" aria-label="Add rule">' + _icon('plus') + '</button>' +
      '</div>' +
      '<div class="pg-context-divider"></div>' +
      '<h3 class="pg-context-title">Version history</h3>' +
      '<div class="pg-rule-version-list" id="pg-rule-version-list">' + _buildRuleVersionHistory() + '</div>' +
      '<div class="pg-rule-compare" id="pg-rule-version-compare" hidden></div>';
    html += '<aside class="pg-context-panel">' +
      '<h2 class="pg-context-title">Analysis rules</h2>' + rulesBody +
      '<div class="pg-context-actions">' +
        '<div class="pg-context-action-group pg-context-action-group-manual" aria-label="Manual rule actions">' +
          '<button class="pg-context-secondary" id="pg-save-context" type="button">Save changes</button>' +
          '<button class="pg-context-secondary" id="pg-create-rule-version" type="button">Create draft</button>' +
        '</div>' +
        '<span class="pg-context-action-divider" aria-hidden="true"></span>' +
        '<div class="pg-context-action-group pg-context-action-group-generation" aria-label="Rule generation actions">' +
          '<button class="pg-context-secondary" id="pg-update-rules" type="button" title="Incrementally update the current rules from the selected sources">Update rules</button>' +
          '<button class="pg-context-primary" id="pg-infer-rules" type="button" title="Generate a fresh draft from the selected sources">Generate rules</button>' +
        '</div>' +
      '</div>' +
      '<div class="pg-context-status" id="pg-context-status" role="status" aria-live="polite"></div>' +
      '<div class="pg-context-feedback" id="pg-context-feedback" role="status" aria-live="polite" hidden></div>' +
    '</aside>';
    html += '<div class="pg-analysis-main">';

    // ── Reference Documents ──
    var documentsBody = '';
    documentsBody += '<div class="pg-instructions-hint">Choose which documents belong in project analysis. The run workspace can then include or exclude all enabled documents with one switch.</div>';
    documentsBody += '<label class="pg-document-dropzone" id="pg-document-dropzone" for="pg-document-input">' +
      '<span class="pg-document-upload-title">Choose documents or drop them here</span>' +
      '<span class="pg-document-upload-help">PDF, DOCX, TXT, Markdown, HTML, CSV, JSON, or YAML · up to 10 MB each</span>' +
    '</label>';
    documentsBody += '<input class="pg-document-input" id="pg-document-input" type="file" multiple accept=".pdf,.docx,.txt,.text,.md,.markdown,.html,.htm,.csv,.json,.yaml,.yml,.log,.rst" />';
    documentsBody += '<div class="pg-document-upload-status" id="pg-document-upload-status" role="status" aria-live="polite"></div>';
    documentsBody += '<div class="pg-document-list" id="pg-document-list">' + _buildReferenceDocumentList() + '</div>';
    var enabledDocumentCount = _referenceDocuments.filter(function (document) { return document.selected !== false; }).length;
    html += _section('Project documents', documentsBody, { badge: enabledDocumentCount + ' of ' + _referenceDocuments.length + ' enabled', badgeId: 'pg-documents-badge' });

    // ── Additional Instructions ──
    var instrBody = '';
    instrBody += '<div class="pg-instructions-hint">Customize how the AI analyzes items. Use <code>{variable_name}</code> to reference item data \u2014 detected variables appear in Variable Mapping below.</div>';
    instrBody += '<textarea class="pg-instructions-textarea" id="pg-additional-instructions" placeholder="e.g. Focus on whether the response addresses all parts of the question.\nPay special attention to the {rubric} criteria." spellcheck="false"></textarea>';
    html += _section('Additional Instructions', instrBody);

    // ── Root Cause Categories & Details ──
    var detailsMap = (_config && _config.category_details_map) || {};
    var categoryExamples = (_config && _config.category_examples) || {};
    var totalDetails = 0;
    var catDetBody = '';
    catDetBody += '<div id="pg-categories-list">';
    for (var i = 0; i < cats.length; i++) {
      var cat = cats[i];
      var catDets = detailsMap[cat] || [];
      totalDetails += catDets.length;
      catDetBody += _buildCategoryGroup(cat, catDets, categoryExamples[cat] || []);
    }
    catDetBody += '</div>';
    catDetBody += '<div class="pg-add-category">' +
      '<input type="text" id="pg-new-category" placeholder="New category..." class="pg-add-input" />' +
      '<button id="pg-add-category-btn" class="pg-add-btn">+ Add</button>' +
    '</div>';
    html += _section('Root Cause Categories & Details', catDetBody, { open: false, badge: cats.length + ' / ' + totalDetails });

    // ── Variable Mapping ──
    html += _buildVariableMapping();

    // ── Filter & Matched Items ──
    var matchedCount = _getMatchedTargetCount(_getMatchedItems());
    var filterBody = '';
    filterBody += '<div class="pg-filter-row">';
    filterBody += '<div class="pg-filter-group">';
    filterBody += '<label class="pg-filter-label" for="pg-max-score">Max Score</label>';
    filterBody += '<div class="pg-slider-control">';
    filterBody += '<input type="range" id="pg-max-score" class="pg-score-slider" min="0" max="100" step="5" value="80" />';
    filterBody += '<span class="pg-slider-value" id="pg-max-score-value">80%</span>';
    filterBody += '</div>';
    filterBody += '</div>';
    filterBody += '<div class="pg-filter-options-group"><span class="pg-filter-label">Options</span><div class="pg-filter-options">';
    filterBody += '<label class="pg-filter-check"><span class="custom-checkbox"><input type="checkbox" id="pg-skip-analyzed" checked /><span class="checkmark"></span></span><span>Skip analyzed</span></label>';
    filterBody += '<label class="pg-filter-check"><span class="custom-checkbox"><input type="checkbox" id="pg-allow-human-overwrite" /><span class="checkmark"></span></span><span>Re-analyze human labels</span></label>';
    filterBody += '</div></div>';
    filterBody += '<div class="pg-filter-limit"><label class="pg-filter-label" for="pg-target-limit">Analyze limit</label>' +
      '<input type="text" id="pg-target-limit" inputmode="numeric" pattern="[0-9]*" maxlength="4" placeholder="All" autocomplete="off" /></div>';
    filterBody += '</div>';
    filterBody += '<div id="pg-matched-section">';
    filterBody += _buildMatchedItemsTable();
    filterBody += '</div>';
    html += _section('Filter & Items', filterBody, { badge: String(matchedCount), badgeId: 'pg-filter-badge' });

    // ── Prompt Preview ──
    var previewBody = '';
    previewBody += '<div id="pg-preview-loading" style="display:none;padding:8px 14px;font-size:var(--font-base);color:var(--accent-tertiary);background:rgba(168,85,247,0.06);border-bottom:1px solid rgba(168,85,247,0.15);">Generating preview\u2026</div>';
    previewBody += '<div id="pg-preview-content" class="pg-prompt-preview-content">Loading prompt preview\u2026</div>';
    previewBody += '<div class="pg-preview-actions">' +
      '<button class="pg-toggle-expand pg-icon-button" id="pg-preview-toggle" type="button" style="display:none;" title="Expand prompt preview" aria-label="Expand prompt preview">' + _icon('expand') + '</button>' +
      '<button class="pg-copy-btn pg-icon-button" id="pg-preview-copy" type="button" title="Copy prompt to clipboard" aria-label="Copy prompt to clipboard">' + _icon('copy') + '</button>' +
    '</div>';
    html += _section('Prompt Preview', previewBody, {
      extraSummary: '<span class="pg-auto-indicator" id="pg-preview-indicator">auto-updates</span>',
    });

    // Test Results (not collapsible — dynamically shown)
    html += '<div class="pg-section-divider" id="pg-results-divider" style="display:none;"><span>Test Results</span></div>';
    html += '<div id="pg-test-results" class="pg-test-results"></div>';

    // Run All Progress
    html += '<div id="pg-runall-progress" class="pg-runall-progress" style="display:none;">' +
      '<div class="pg-progress-icon-container"><div class="pg-progress-icon">✨</div></div>' +
      '<div class="pg-progress-text" id="pg-runall-progress-text">Analyzing items…</div>' +
      '<div class="pg-progress-subtext" id="pg-runall-progress-subtext">This might take a moment depending on batch size.</div>' +
      '<div class="pg-progress-bar"><div class="pg-progress-fill" id="pg-runall-progress-fill"></div></div>' +
    '</div>';
    html += '<div id="pg-runall-results" class="pg-runall-results"></div>';

    html += '</div></div>';

    return html;
  }

  // ── Variable Mapping Section ──

  function _buildVariableMapping() {
    var sourceFields = ['input', 'output', 'expected', 'error', 'metric_metadata'];
    var standardRows = [
      { label: 'INPUT', defaultField: 'input' },
      { label: 'EXPECTED OUTPUT', defaultField: 'expected' },
      { label: 'ACTUAL OUTPUT', defaultField: 'output' },
    ];

    var body = '';
    body += '<div class="pg-mapping-layout">';
    body += '<div class="pg-mapping-core">';
    for (var i = 0; i < standardRows.length; i++) {
      var row = standardRows[i];
      var rowId = 'pg-mapping-' + i;
      var isJson = _isFieldJson(row.defaultField);

      body += '<div class="pg-mapping-row">';
      body += '<span class="pg-mapping-label">' + row.label + '</span>';
      body += '<span class="pg-mapping-arrow">\u2192</span>';
      body += '<select class="pg-mapping-select" id="' + rowId + '-field" data-mapping-idx="' + i + '">';
      for (var s = 0; s < sourceFields.length; s++) {
        var sel = sourceFields[s] === row.defaultField ? ' selected' : '';
        body += '<option value="' + sourceFields[s] + '"' + sel + '>' + sourceFields[s] + '</option>';
      }
      body += '</select>';
      body += '<span class="pg-path-picker-wrap" id="' + rowId + '-path-wrap">' + (isJson ? _buildPathPicker(rowId + '-paths', row.defaultField) : '') + '</span>';
      body += '</div>';
    }
    body += '</div>';

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
      { key: 'metadata', label: 'Metric Metadata' },
    ];
    for (var e = 0; e < extras.length; e++) {
      body += '<label class="pg-field-toggle">' +
        '<span class="custom-checkbox"><input type="checkbox" data-field="' + extras[e].key + '" checked /><span class="checkmark"></span></span>' +
        '<span>' + extras[e].label + '</span>' +
      '</label>';
    }
    body += '</div>';
    var metadataPicker = _buildPathPicker('pg-metadata-paths', 'metric_metadata');
    if (metadataPicker) {
      body += '<div class="pg-metadata-path-row" id="pg-metadata-path-row">' + metadataPicker + '</div>';
    }
    body += '</div>';
    return _section('Variable Mapping', body, { open: false });
  }

  function _buildCustomVarsMapping() {
    if (_customVars.length === 0) return '';

    var sourceFields = ['input', 'output', 'expected', 'error', 'metric_metadata'];
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

  // ── Matched Items Table ──

  function _buildMatchedItemsTable() {
    var matched = _getMatchedItems();
    var threshold = _opts.getThreshold ? _opts.getThreshold() : 0.8;

    var html = '';
    if (matched.length === 0) {
      var skipEl = document.getElementById('pg-skip-analyzed');
      if (skipEl && skipEl.checked) {
        html += '<div class="pg-empty-msg pg-zero-target"><strong>All matching targets already have analysis.</strong><span>Include previously analyzed targets to run them again, or open Reviews to inspect the saved diagnoses.</span><div class="pg-zero-target-actions"><button type="button" id="pg-include-analyzed">Include analyzed targets</button>' +
          (_opts.reviewsUrl ? '<a href="' + _escAttr(_opts.reviewsUrl) + '">Open Reviews</a>' : '') +
          '</div></div>';
      } else {
        html += '<div class="pg-empty-msg pg-zero-target"><strong>No targets match the current scope.</strong><span>Adjust the metrics or maximum score to widen the analysis.</span></div>';
      }
      return html;
    }

    html += '<div class="pg-items-list">';
    var visibleCount = Math.min(matched.length, (_matchedPage + 1) * _PAGE_SIZE);
    for (var i = 0; i < visibleCount; i++) {
      var r = matched[i];
      var failedMetricNames = Array.isArray(r._matched_metric_names) ? r._matched_metric_names : [];
      var primaryMetric = failedMetricNames[0] || '';
      var scoreNum = primaryMetric && r.metric_scores ? r.metric_scores[primaryMetric] : r.metric_score;
      var scoreStr = scoreNum != null ? scoreNum.toFixed(2) : '\u2014';
      var status = r.error ? 'error' : (scoreNum != null ? (scoreNum < threshold ? 'failed' : 'passed') : 'none');
      var isSelected = r.item_id === _selectedItemId;
      var md = r.item_metadata && typeof r.item_metadata === 'object' ? r.item_metadata : {};
      var rc = md.root_cause || '';
      var rcDetail = md.root_cause_detail || '';
      var rcSource = md.root_cause_source || '';
      var rcConfidence = md.root_cause_confidence;
      var isAi = rcSource === 'ai';
      var rcColor = _rootCauseColor(rc);
      html += '<div class="pg-item-card' + (isSelected ? ' pg-item-selected' : '') + '" data-item-id="' + _escAttr(r.item_id) + '">';

      // Top row: index, score, status
      html += '<div class="pg-item-top">';
      html += '<span class="pg-item-idx">#' + (r.index != null ? r.index : i) + '</span>';
      if (primaryMetric) html += '<span class="pg-item-metric">' + _esc(primaryMetric) + '</span>';
      if (scoreNum != null) html += '<span class="pg-item-score pg-status-' + status + '">' + scoreStr + '</span>';
      html += '<span class="pg-status-badge pg-status-' + status + '">' + (status === 'none' ? 'no score' : status) + '</span>';
      if (failedMetricNames.length > 1) html += '<span class="pg-item-target-count">+' + (failedMetricNames.length - 1) + ' metric target' + (failedMetricNames.length === 2 ? '' : 's') + '</span>';
      html += '</div>';

      // Root cause row (matching item-by-item style)
      if (rc || rcDetail) {
        html += '<div class="pg-item-rc-row">';
        if (rcDetail) {
          html += '<span class="pg-item-rc-detail' + (isAi ? ' pg-item-rc-ai' : '') + '">' + _esc(rcDetail) + '</span>';
        }
        if (rc) {
          var confDot = '';
          if (isAi && rcConfidence != null) {
            var dotColor = rcConfidence >= 0.8 ? '#22c55e' : (rcConfidence >= 0.5 ? '#eab308' : '#ef4444');
            confDot = '<span class="pg-item-rc-conf" style="background:' + dotColor + ';" title="Confidence: ' + Math.round(rcConfidence * 100) + '%"></span>';
          }
          html += '<span class="pg-item-rc-cat" style="border-color:' + rcColor + '40;color:' + rcColor + ';background:' + rcColor + '15;">' + _esc(rc) + confDot + '</span>';
        }
        html += '</div>';
      }

      // Input preview
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
    if (visibleCount < matched.length) {
      html += '<button class="pg-show-more" id="pg-show-more" type="button">Show ' +
        Math.min(_PAGE_SIZE, matched.length - visibleCount) + ' more</button>';
    }

    return html;
  }

  // ── Build Config Payload ──

  function _buildConfigPayload() {
    var cfg = {};
    var rulesToggle = document.getElementById('pg-use-project-rules');
    var documentsToggle = document.getElementById('pg-use-project-documents');
    if (rulesToggle) cfg.include_project_rules = rulesToggle.checked;
    if (documentsToggle) cfg.include_project_documents = documentsToggle.checked;

    if (!_opts.dedicatedPage) {
      var rules = _readAnalysisRulesFromEditor();
      cfg.analysis_rules = rules;
    }

    if (!_opts.dedicatedPage && _referenceDocuments.length > 0) {
      cfg.reference_documents = _referenceDocuments.map(function (document) {
        return { name: document.name, content: document.content };
      });
    }

    // Additional instructions
    var instrEl = document.getElementById('pg-additional-instructions');
    if (instrEl && instrEl.value.trim()) {
      cfg.additional_instructions = instrEl.value.trim();
    }

    // Categories & Details (grouped)
    var catGroups = document.querySelectorAll('#pg-categories-list .pg-category-group');
    if (catGroups.length > 0) {
      var cats = [];
      var cdMap = {};
      catGroups.forEach(function (group) {
        var cat = group.dataset.cat;
        cats.push(cat);
        var dets = [];
        group.querySelectorAll('.pg-detail-item').forEach(function (el) {
          dets.push(el.dataset.detail);
        });
        if (dets.length > 0) cdMap[cat] = dets;
      });
      cfg.root_cause_categories = cats;
      cfg.category_details_map = cdMap;
    }

    // Include fields
    var fieldChecks = _overlay ? _overlay.querySelectorAll('.pg-field-toggle input[type="checkbox"][data-field]') : [];
    if (fieldChecks.length > 0) {
      var fields = { input: true, expected: true, output: true };
      fieldChecks.forEach(function (cb) { fields[cb.dataset.field] = cb.checked; });
      cfg.include_fields = fields;
      if (fields.metadata) {
        var metadataSelection = _getPathPickerSelection('pg-metadata-paths', 'metric_metadata');
        if (metadataSelection.custom) cfg.metadata_fields = metadataSelection.source;
      }
    }

    // Field mapping (standard)
    var fieldMapping = _getFieldMapping();
    if (fieldMapping) cfg.field_mapping = fieldMapping;

    // Custom variable mapping
    var customMapping = _getCustomVarMapping();
    if (customMapping) cfg.custom_variable_mapping = customMapping;

    return cfg;
  }

  function _renderReferenceDocuments() {
    var list = document.getElementById('pg-document-list');
    var badge = document.getElementById('pg-documents-badge');
    if (list) list.innerHTML = _buildReferenceDocumentList();
    if (badge) {
      var enabled = _referenceDocuments.filter(function (document) { return document.selected !== false; }).length;
      badge.textContent = enabled + ' of ' + _referenceDocuments.length + ' enabled';
    }
    _syncActionAvailability();
  }

  function _setDocumentUploadStatus(message, isError) {
    var status = document.getElementById('pg-document-upload-status');
    if (!status) return;
    status.textContent = message || '';
    status.className = 'pg-document-upload-status' + (isError ? ' pg-document-upload-error' : '');
  }

  function _uploadReferenceDocument(file) {
    var runId = _getRunId();
    if (!runId) return Promise.reject(new Error('Could not determine the run ID.'));
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    var form = new FormData();
    form.append('file', file, file.name);
    return fetch(base('api/runs/' + runId + '/analysis-documents'), {
      method: 'POST',
      body: form,
    }).then(function (response) {
      return response.text().then(function (text) {
        var payload = {};
        try { payload = text ? JSON.parse(text) : {}; } catch (e) {}
        if (!response.ok) throw new Error(payload.detail || text || 'Document upload failed');
        if (!payload.document) throw new Error('Document upload returned no extracted content.');
        return payload.document;
      });
    });
  }

  function _deleteReferenceDocument(document) {
    var runId = _getRunId();
    if (!runId || !document.id) return Promise.reject(new Error('Could not identify the saved document.'));
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    return fetch(base('api/runs/' + runId + '/analysis-documents/' + encodeURIComponent(document.id)), {
      method: 'DELETE',
    }).then(function (response) {
      if (!response.ok) return response.text().then(function (text) { throw new Error(text || 'Document deletion failed'); });
      return response.json();
    });
  }

  function _updateReferenceDocumentSelection(document, selected) {
    var runId = _getRunId();
    if (!runId || !document.id) return Promise.reject(new Error('Could not identify the saved document.'));
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    return fetch(base('api/runs/' + runId + '/analysis-documents/' + encodeURIComponent(document.id)), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ selected: selected }),
    }).then(function (response) {
      return response.text().then(function (text) {
        var payload = {};
        try { payload = text ? JSON.parse(text) : {}; } catch (e) {}
        if (!response.ok) throw new Error(payload.detail || text || 'Document selection failed');
        return payload.document;
      });
    });
  }

  function _handleReferenceDocumentFiles(fileList) {
    var files = Array.prototype.slice.call(fileList || []);
    if (files.length === 0) return;
    _documentUploadsInFlight += files.length;
    _setDocumentUploadStatus('Extracting ' + files.length + ' document' + (files.length === 1 ? '' : 's') + '…', false);
    _renderReferenceDocuments();

    Promise.all(files.map(function (file) {
      return _uploadReferenceDocument(file).then(function (document) {
        return { document: document };
      }).catch(function (error) {
        return { error: error, filename: file.name };
      });
    })).then(function (results) {
      var added = 0;
      var failed = 0;
      results.forEach(function (result) {
        if (result.document) {
          _referenceDocuments.push(result.document);
          added++;
        } else {
          failed++;
          if (_opts.showToast) _opts.showToast('error', 'Document Upload Failed', result.filename + ': ' + result.error.message);
        }
      });
      _documentUploadsInFlight -= results.length;
      _renderReferenceDocuments();
      if (added > 0) {
        _setDocumentUploadStatus(added + ' project document' + (added === 1 ? '' : 's') + ' saved.' + (failed ? ' ' + failed + ' failed.' : ''), false);
        _scheduleAutoPreview(0);
      } else {
        _setDocumentUploadStatus('No documents were added.', true);
      }
    });
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
      if (!fieldEl) continue;
      var field = fieldEl.value;
      var selection = _getPathPickerSelection('pg-mapping-' + def.idx + '-paths', field);
      var source = selection.source;
      if (selection.custom || source !== def.defaultField) hasCustom = true;
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
      var selection = _getPathPickerSelection('pg-customvar-' + i + '-paths', field);
      mapping[_customVars[i]] = selection.source;
      hasAny = true;
    }
    return hasAny ? mapping : null;
  }

  function _readAnalysisRuleDraftsFromEditor() {
    var list = document.getElementById('pg-rule-list');
    if (!list) return _analysisRules.slice();
    var rules = [];
    list.querySelectorAll('.pg-rule-item').forEach(function (item) {
      var titleEl = item.querySelector('.pg-rule-title');
      var instructionEl = item.querySelector('.pg-rule-instruction');
      var title = titleEl ? titleEl.value.trim() : '';
      var instruction = instructionEl ? instructionEl.value.trim() : '';
      rules.push({ id: item.dataset.ruleId || undefined, title: title, instruction: instruction });
    });
    return rules;
  }

  function _readAnalysisRulesFromEditor() {
    return _readAnalysisRuleDraftsFromEditor().filter(function (rule) {
      return rule.title && rule.instruction;
    });
  }

  function _validateAnalysisRuleDrafts() {
    var list = document.getElementById('pg-rule-list');
    if (!list) return true;
    var invalidField = null;
    list.querySelectorAll('.pg-rule-item').forEach(function (item) {
      var titleEl = item.querySelector('.pg-rule-title');
      var instructionEl = item.querySelector('.pg-rule-instruction');
      var titleMissing = !titleEl || !titleEl.value.trim();
      var instructionMissing = !instructionEl || !instructionEl.value.trim();
      if (titleEl) titleEl.classList.toggle('pg-field-invalid', titleMissing);
      if (instructionEl) instructionEl.classList.toggle('pg-field-invalid', instructionMissing);
      if (!invalidField && (titleMissing || instructionMissing)) {
        invalidField = titleMissing ? titleEl : instructionEl;
      }
    });
    if (!invalidField) return true;
    invalidField.focus();
    _setContextStatus('Complete the title and instruction for every rule before saving.', true);
    return false;
  }

  function _renderRuleViewStatus() {
    var status = document.getElementById('pg-context-status');
    if (!status) return;
    status.classList.remove('pg-context-status-error');
    var version = _ruleVersions.find(function (candidate) { return candidate.id === _selectedRuleVersionId; });
    if (!version) {
      status.textContent = 'No rule version selected.';
      status.classList.remove('pg-context-status-readonly', 'pg-context-status-editable');
      return;
    }
    var editable = version.status === 'draft';
    status.textContent = 'Opened v' + version.version + (editable ? ' (editable).' : ' (read-only).');
    status.classList.toggle('pg-context-status-readonly', !editable);
    status.classList.toggle('pg-context-status-editable', editable);
  }

  function _formatRuleVersionTimestamp(value) {
    if (!value) return 'Unknown';
    var timestamp = new Date(value);
    if (Number.isNaN(timestamp.getTime())) return 'Unknown';
    return timestamp.toLocaleString([], {
      dateStyle: 'medium',
      timeStyle: 'short',
    });
  }

  function _renderRuleVersionMeta(version) {
    var meta = document.getElementById('pg-rule-version-meta');
    if (!meta) return;
    meta.innerHTML = '';
    if (!version) return;

    var values = [
      { label: 'Created at', value: _formatRuleVersionTimestamp(version.created_at), timestamp: version.created_at },
      { label: 'Updated at', value: _formatRuleVersionTimestamp(version.updated_at), timestamp: version.updated_at },
      {
        label: 'By',
        value: (version.created_by && version.created_by.display_name) || 'Unknown user',
      },
    ];
    values.forEach(function (item) {
      var entry = document.createElement('span');
      entry.className = 'analysis-rule-version-meta-item';
      entry.append(document.createTextNode(item.label + ' '));
      if (item.timestamp) {
        var time = document.createElement('time');
        time.dateTime = item.timestamp;
        time.textContent = item.value;
        entry.append(time);
      } else {
        entry.append(document.createTextNode(item.value));
      }
      meta.append(entry);
    });
  }

  function _renderAnalysisRulesEditor() {
    var list = document.getElementById('pg-rule-list');
    if (list) list.innerHTML = _buildAnalysisRulesEditor();
    var count = document.getElementById('pg-rule-count');
    if (count) count.textContent = _formatRuleCount();
    var selected = _ruleVersions.find(function (version) { return version.id === _selectedRuleVersionId; });
    var editable = !!selected && selected.status === 'draft';
    var addButton = document.getElementById('pg-add-rule');
    var saveButton = document.getElementById('pg-save-context');
    if (addButton) {
      addButton.disabled = !editable;
      addButton.title = editable ? 'Add rule' : 'Create a draft to add rules';
      addButton.setAttribute('aria-label', editable ? 'Add rule' : 'Create a draft to add rules');
    }
    if (saveButton) {
      saveButton.disabled = !editable;
      saveButton.title = editable ? 'Save changes to this draft' : 'Create a draft to edit rules';
      saveButton.setAttribute('aria-label', editable ? 'Save changes to this draft' : 'Create a draft to edit rules');
    }
    var viewState = document.getElementById('pg-rule-view-state');
    if (viewState) {
      viewState.textContent = editable ? 'Editable draft' : 'Read-only';
      viewState.classList.toggle('analysis-rule-view-state-editable', editable);
      viewState.classList.toggle('analysis-rule-view-state-readonly', !editable);
      viewState.title = editable ? 'Rules in this draft can be edited.' : 'Create a draft before editing these rules.';
    }
    _renderRuleVersionMeta(selected);
    _renderRuleViewStatus();
  }

  function _syncInferenceSourceSummary() {
    var summary = document.getElementById('pg-infer-source-summary');
    if (!summary) return;
    var inputs = [
      document.getElementById('pg-infer-use-documents'),
      document.getElementById('pg-infer-use-examples'),
    ].filter(Boolean);
    var enabled = inputs.filter(function (input) { return input.checked; }).length;
    summary.textContent = enabled + ' of ' + inputs.length + ' sources enabled';
  }

  function _setRuleEditorBusy(isBusy) {
    var list = document.getElementById('pg-rule-list');
    if (!list) return;
    list.querySelectorAll('input, textarea, button').forEach(function (control) {
      control.disabled = isBusy;
    });
    var addButton = document.getElementById('pg-add-rule');
    if (addButton) addButton.disabled = isBusy;
  }

  function _renderRuleVersionHistory() {
    var list = document.getElementById('pg-rule-version-list');
    if (list) list.innerHTML = _buildRuleVersionHistory();
  }

  function _refreshRuleVersions(syncEditor) {
    var runId = _getRunId();
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    return fetch(base('api/runs/' + runId + '/analysis-rule-versions?include_deleted=true'))
      .then(function (response) {
        if (!response.ok) throw new Error('Could not load rule version history');
        return response.json();
      })
      .then(function (data) {
        _ruleVersions = data.versions || [];
        _canDeleteRuleVersions = !!data.can_delete;
        _canActivateRuleVersions = !!data.can_activate;
        _canRestoreRuleVersions = !!data.can_restore;
        if (syncEditor) {
          var selected = _ruleVersions.find(function (version) { return version.id === _selectedRuleVersionId; });
          if (!selected) {
            selected = _ruleVersions.find(function (version) { return version.is_active; }) || _ruleVersions[0];
            _selectedRuleVersionId = selected ? selected.id : null;
          }
          _analysisRules = selected ? selected.rules : [];
          _editingRuleIndex = null;
          if (_config) _config.analysis_rules = _analysisRules;
          _renderAnalysisRulesEditor();
        }
        _renderRuleVersionHistory();
        _renderRuleViewStatus();
      });
  }

  function _changeRuleVersion(versionId, action) {
    var runId = _getRunId();
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    var suffix = action === 'restore'
      ? '/restore'
      : (action === 'activate' ? '/activate' : (action === 'permanent-delete' ? '/permanent' : ''));
    return fetch(base('api/runs/' + runId + '/analysis-rule-versions/' + encodeURIComponent(versionId) + suffix), {
      method: action === 'delete' || action === 'permanent-delete' ? 'DELETE' : 'POST',
    }).then(function (response) {
      if (!response.ok) return response.json().then(function (data) { throw new Error(data.detail || 'Could not update rule version'); });
      return _refreshRuleVersions(true);
    }).then(function () {
      var message = action === 'restore'
        ? 'Rule version restored.'
        : (action === 'activate'
          ? 'Production rule version changed.'
          : (action === 'permanent-delete'
            ? 'Rule version permanently deleted.'
            : 'Rule version permanently deleted.'));
      _setContextStatus(message, false);
      _scheduleAutoPreview(0);
    }).catch(function (error) {
      _setContextStatus(error.message || 'Could not update rule version.', true);
    });
  }

  function _confirmRuleVersionDeletion(versionId) {
    var version = _ruleVersions.find(function (candidate) { return candidate.id === versionId; });
    if (!version) return Promise.resolve();
    if (!window.QymShell || typeof window.QymShell.openConfirmDialog !== 'function') {
      _setContextStatus('The confirmation dialog is unavailable. Reload the page and try again.', true);
      return Promise.resolve();
    }
    return window.QymShell.openConfirmDialog({
      mount: _overlay || document.body,
      title: 'Delete v' + version.version + ' permanently?',
      description: [
        'This permanently removes this rules version and its rules.',
        'Other versions will remain. This action cannot be undone.',
      ],
      cancelLabel: 'Keep version',
      confirmLabel: 'Delete version',
      confirmClass: 'shell-btn-danger',
    }).then(function (result) {
      if (!result || !result.confirmed) return;
      return _changeRuleVersion(versionId, 'delete');
    });
  }

  function _openRuleVersion(versionId) {
    var version = _ruleVersions.find(function (candidate) { return candidate.id === versionId; });
    if (!version) return;
    _selectedRuleVersionId = version.id;
    _analysisRules = (version.rules || []).slice();
    _editingRuleIndex = null;
    if (_config) _config.analysis_rules = _analysisRules;
    _renderAnalysisRulesEditor();
    _renderRuleVersionHistory();
    _setContextStatus(
      'Opened v' + version.version + (version.status === 'draft' ? ' draft.' : ' (read-only).'),
      false
    );
    _scheduleAutoPreview(0);
  }

  function _createRuleDraft(fromVersionId) {
    var runId = _getRunId();
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    var sourceVersionId = fromVersionId || _selectedRuleVersionId;
    var selected = _ruleVersions.find(function (version) { return version.id === sourceVersionId; });
    if (!selected || selected.is_deleted) {
      return Promise.reject(new Error('Select an available version before creating a draft.'));
    }
    return fetch(base('api/runs/' + runId + '/analysis-rule-versions'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        from_version: String(selected.id),
      }),
    }).then(function (response) {
      if (!response.ok) return response.json().then(function (data) { throw new Error(data.detail || 'Could not create draft'); });
      return response.json();
    }).then(function (data) {
      _selectedRuleVersionId = data.version.id;
      return _refreshRuleVersions(true).then(function () {
        _setContextStatus('Created draft v' + data.version.version + '.', false);
      });
    });
  }

  function _mergeRuleVersion(targetId, sourceId, apply, resolutions) {
    var runId = _getRunId();
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    return fetch(base('api/runs/' + runId + '/analysis-rule-versions/' + encodeURIComponent(targetId) + ':merge'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_version: sourceId,
        apply: !!apply,
        resolutions: resolutions || {},
      }),
    }).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok) {
          var detail = data.detail;
          if (detail && typeof detail === 'object') {
            var error = new Error(detail.message || 'Could not merge rule versions');
            error.preview = detail.preview;
            throw error;
          }
          throw new Error(detail || 'Could not merge rule versions');
        }
        return data;
      });
    });
  }

  function _closeRuleCompareDialog(panel) {
    if (!panel) return;
    panel.hidden = true;
    panel.classList.remove('pg-rule-compare-picker');
    panel.classList.remove('pg-rule-compare-portal');
    if (_ruleCompareOriginalParent && panel.parentNode === document.body) {
      _ruleCompareOriginalParent.insertBefore(panel, _ruleCompareOriginalNextSibling);
    }
  }

  function _mountRuleComparePortal(panel) {
    if (!panel) return;
    if (!_ruleCompareOriginalParent) {
      _ruleCompareOriginalParent = panel.parentNode;
      _ruleCompareOriginalNextSibling = panel.nextSibling;
    }
    if (panel.parentNode !== document.body) document.body.appendChild(panel);
    panel.classList.add('pg-rule-compare-portal');
  }

  function _renderRuleCompareDialog(panel, content) {
    if (!panel) return;
    _mountRuleComparePortal(panel);
    panel.classList.add('pg-rule-compare-picker');
    panel.innerHTML =
      '<div class="pg-rule-compare-backdrop" data-rule-compare-backdrop aria-hidden="true"></div>' +
      '<div class="pg-rule-compare-dialog" role="dialog" aria-modal="true" aria-labelledby="pg-rule-compare-dialog-title">' +
        content +
      '</div>';
    panel.hidden = false;
  }

  function _wireRuleVersionSearch(panel, selectSelector, searchSelector, emptySelector) {
    var select = panel.querySelector(selectSelector);
    var search = panel.querySelector(searchSelector);
    var empty = panel.querySelector(emptySelector);
    if (!select || !search) return;
    var options = Array.prototype.slice.call(panel.querySelectorAll('[data-rule-version-option]'));
    var selectOption = function (option, focus) {
      select.value = option.dataset.ruleVersionOption;
      options.forEach(function (candidate) {
        var selected = candidate === option;
        candidate.classList.toggle('pg-rule-version-option-selected', selected);
        candidate.setAttribute('aria-selected', selected ? 'true' : 'false');
      });
      if (focus) option.focus();
    };
    var filterOptions = function () {
      var query = String(search.value || '').trim().toLowerCase();
      var visible = 0;
      options.forEach(function (option) {
        var matches = !query || String(option.textContent || '').toLowerCase().indexOf(query) !== -1;
        option.hidden = !matches;
        if (matches) visible += 1;
      });
      if (empty) empty.hidden = visible > 0;
    };
    options.forEach(function (option) {
      option.addEventListener('click', function () { selectOption(option, true); });
      option.addEventListener('keydown', function (event) {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        selectOption(option, true);
      });
    });
    search.addEventListener('input', filterOptions);
    search.addEventListener('keydown', function (event) {
      if (event.key === 'ArrowDown' || event.key === 'Enter') {
        event.preventDefault();
        var firstVisible = options.find(function (option) { return !option.hidden; });
        if (firstVisible) firstVisible.focus();
      }
    });
    filterOptions();
  }

  function _buildRuleVersionPicker(label, versions, selectedId, key, ariaLabel) {
    var selected = selectedId || (versions[0] && versions[0].id) || '';
    var optionHtml = versions.map(function (version) {
      var isSelected = version.id === selected;
      return '<button type="button" role="option" class="pg-rule-version-option' + (isSelected ? ' pg-rule-version-option-selected' : '') + '" data-rule-version-option="' + _escAttr(version.id) + '" aria-selected="' + (isSelected ? 'true' : 'false') + '">' +
        '<span class="pg-rule-version-option-name">v' + _esc(version.version) + '</span>' +
        '<span class="pg-rule-version-option-state">' + _esc(_ruleVersionStateLabel(version)) + '</span>' +
      '</button>';
    }).join('');
    return '<div class="pg-rule-version-picker">' +
      '<label class="pg-rule-operation-field"><span>Search versions</span><input type="search" data-rule-' + key + '-search placeholder="Search by version or status" autocomplete="off" /></label>' +
      '<label class="pg-rule-operation-field"><span>' + _esc(label) + '</span><div class="pg-rule-version-options" role="listbox" aria-label="' + _escAttr(ariaLabel) + '">' + optionHtml + '</div><input type="hidden" data-rule-' + key + ' value="' + _escAttr(selected) + '" /><span class="pg-rule-version-picker-empty" data-rule-' + key + '-empty hidden>No matching versions.</span></label>' +
    '</div>';
  }

  function _renderRuleMergePreview(target, source, preview) {
    var panel = document.getElementById('pg-rule-version-compare');
    if (!panel) return;
    var summary = (preview && preview.summary) || {};
    var conflicts = (preview && preview.conflicts) || [];
    var conflictHtml = conflicts.map(function (conflict, index) {
      var current = conflict.target || {};
      var incoming = conflict.source || {};
      var fallbackTitle = current.title || incoming.title || 'Deleted rule';
      return '<div class="pg-rule-merge-conflict" data-merge-conflict="' + _escAttr(conflict.key) + '">' +
        '<div class="pg-rule-merge-conflict-head"><strong>' + _esc(fallbackTitle) + '</strong><span>Conflict ' + (index + 1) + '</span></div>' +
        '<div class="pg-rule-merge-sides">' +
          '<div><span>Current</span><p>' + _esc(current.instruction || 'Delete this rule') + '</p></div>' +
          '<div><span>Incoming</span><p>' + _esc(incoming.instruction || 'Delete this rule') + '</p></div>' +
        '</div>' +
        '<label class="pg-rule-merge-choice">Resolution<select data-merge-resolution>' +
          '<option value="target">Keep current</option>' +
          '<option value="source">Use incoming</option>' +
          '<option value="custom">Write custom</option>' +
        '</select></label>' +
        '<div class="pg-rule-merge-custom" hidden>' +
          '<input type="text" data-merge-custom-title value="' + _escAttr(fallbackTitle) + '" placeholder="Rule title" />' +
          '<textarea data-merge-custom-instruction placeholder="Rule instruction">' + _esc(current.instruction || incoming.instruction || '') + '</textarea>' +
        '</div>' +
      '</div>';
    }).join('');
    _renderRuleCompareDialog(panel,
      '<div class="pg-rule-compare-header"><div><span class="pg-rule-compare-eyebrow">Merge preview</span>' +
        '<strong id="pg-rule-compare-dialog-title">v' + target.version + ' ← v' + source.version + '</strong></div>' +
        '<button class="pg-rule-action" type="button" data-close-rule-compare>Close</button></div>' +
      '<div class="pg-rule-compare-stats"><span><strong>' + (summary.changed || 0) + '</strong> changed</span>' +
        '<span><strong>' + (summary.added || 0) + '</strong> added</span>' +
        '<span><strong>' + (summary.removed || 0) + '</strong> removed</span>' +
        '<span><strong>' + (summary.conflicts || 0) + '</strong> conflicts</span></div>' +
      (conflictHtml || '<div class="pg-rule-version-meta">No conflicts. The merge is ready to apply.</div>') +
      '<div class="pg-rule-merge-actions"><button class="pg-context-primary" type="button" data-apply-rule-merge>Apply merge</button></div>');
    panel.querySelectorAll('[data-merge-resolution]').forEach(function (select) {
      select.addEventListener('change', function () {
        var custom = select.closest('.pg-rule-merge-conflict').querySelector('.pg-rule-merge-custom');
        custom.hidden = select.value !== 'custom';
      });
    });
    var applyButton = panel.querySelector('[data-apply-rule-merge]');
    if (applyButton) applyButton.addEventListener('click', function () {
      var resolutions = {};
      panel.querySelectorAll('[data-merge-conflict]').forEach(function (conflictNode) {
        var key = conflictNode.dataset.mergeConflict;
        var choice = conflictNode.querySelector('[data-merge-resolution]').value;
        if (choice === 'custom') {
          resolutions[key] = {
            title: conflictNode.querySelector('[data-merge-custom-title]').value.trim(),
            instruction: conflictNode.querySelector('[data-merge-custom-instruction]').value.trim(),
          };
        } else {
          resolutions[key] = choice;
        }
      });
      applyButton.disabled = true;
      applyButton.textContent = 'Merging…';
      _mergeRuleVersion(target.id, source.id, true, resolutions).then(function (data) {
        _selectedRuleVersionId = data.version.id;
        return _refreshRuleVersions(true).then(function () { return data; });
      }).then(function (data) {
        _closeRuleCompareDialog(panel);
        _setContextStatus(
          data.merge && !data.merge.created_new_draft
            ? 'Merged v' + source.version + ' into draft v' + target.version + '.'
            : 'Created a new draft by merging v' + source.version + ' into v' + target.version + '.',
          false
        );
      }).catch(function (error) {
        applyButton.disabled = false;
        applyButton.textContent = 'Apply merge';
        _setContextStatus(error.message || 'Could not apply the merge.', true);
      });
    });
  }

  function _openRuleMerge(targetId) {
    var target = _ruleVersions.find(function (version) { return version.id === targetId; });
    var sources = _ruleVersions.filter(function (version) {
      return version.id !== targetId && !version.is_deleted;
    });
    var panel = document.getElementById('pg-rule-version-compare');
    if (!target || !panel || sources.length === 0) return;
    _renderRuleCompareDialog(panel,
        '<div class="pg-rule-compare-header"><div><span class="pg-rule-compare-eyebrow">Merge versions</span>' +
        '<strong id="pg-rule-compare-dialog-title">Merge into v' + target.version + '</strong></div>' +
        '<button class="pg-rule-action" type="button" data-close-rule-compare>Close</button></div>' +
        '<p class="pg-rule-operation-help">Choose the version whose rules should be merged into v' + target.version + '. You can review all changes and resolve conflicts before applying.</p>' +
        _buildRuleVersionPicker('Merge with', sources, sources[0].id, 'merge-source', 'Version to merge into v' + target.version) +
        '<div class="pg-rule-merge-actions"><button class="pg-context-primary" type="button" data-preview-rule-merge>Preview merge</button></div>');
    _wireRuleVersionSearch(panel, '[data-rule-merge-source]', '[data-rule-merge-source-search]', '[data-rule-merge-source-empty]');
    panel.querySelector('[data-rule-merge-source-search]').focus();
    panel.querySelector('[data-preview-rule-merge]').addEventListener('click', function () {
      var sourceId = panel.querySelector('[data-rule-merge-source]').value;
      var source = sources.find(function (version) { return version.id === sourceId; });
      var previewButton = panel.querySelector('[data-preview-rule-merge]');
      if (!source) {
        _setContextStatus('Choose a version to merge before previewing.', true);
        return;
      }
      previewButton.disabled = true;
      previewButton.textContent = 'Previewing…';
      _mergeRuleVersion(target.id, sourceId, false, {}).then(function (data) {
        _renderRuleMergePreview(target, source, data.preview);
      }).catch(function (error) {
        previewButton.disabled = false;
        previewButton.textContent = 'Preview merge';
        _setContextStatus(error.message || 'Could not preview the merge.', true);
      });
    });
  }

  function _openRuleCompare(versionId) {
    var version = _ruleVersions.find(function (candidate) { return candidate.id === versionId; });
    var candidates = _ruleVersions.filter(function (candidate) {
      return candidate.id !== versionId && !candidate.is_deleted;
    });
    var panel = document.getElementById('pg-rule-version-compare');
    if (!version || !panel || candidates.length === 0) return;
    var preferred = candidates.find(function (candidate) {
      return candidate.is_active;
    }) || candidates.find(function (candidate) {
      return candidate.id === version.parent_version_id;
    }) || candidates[0];
    _renderRuleCompareDialog(panel,
        '<div class="pg-rule-compare-header"><div><span class="pg-rule-compare-eyebrow">Compare versions</span>' +
        '<strong id="pg-rule-compare-dialog-title">Compare v' + version.version + '</strong></div>' +
        '<button class="pg-rule-action" type="button" data-close-rule-compare>Close</button></div>' +
        '<p class="pg-rule-operation-help">Choose a version to use as the baseline. The comparison shows what changed from that version to v' + version.version + '.</p>' +
        _buildRuleVersionPicker('Compare with', candidates, preferred.id, 'compare-base', 'Version to compare with v' + version.version) +
        '<div class="pg-rule-merge-actions"><button class="pg-context-primary" type="button" data-run-rule-compare>Show differences</button></div>');
    _wireRuleVersionSearch(panel, '[data-rule-compare-base]', '[data-rule-compare-base-search]', '[data-rule-compare-base-empty]');
    panel.querySelector('[data-rule-compare-base-search]').focus();
    panel.querySelector('[data-run-rule-compare]').addEventListener('click', function () {
      var button = panel.querySelector('[data-run-rule-compare]');
      var baseId = panel.querySelector('[data-rule-compare-base]').value;
      if (!baseId) {
        _setContextStatus('Choose a version to compare before continuing.', true);
        return;
      }
      button.disabled = true;
      button.textContent = 'Comparing…';
      _compareRuleVersion(version.id, baseId).catch(function () {
        button.disabled = false;
        button.textContent = 'Show differences';
      });
    });
  }

  function _publishRuleVersion(versionId) {
    var version = _ruleVersions.find(function (candidate) { return candidate.id === versionId; });
    if (!version) return Promise.resolve();
    if (!window.QymShell || typeof window.QymShell.openFormDialog !== 'function') {
      _setContextStatus('The publish dialog is unavailable. Reload the page and try again.', true);
      return Promise.resolve();
    }
    var runId = _getRunId();
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    var setProduction = false;
    return window.QymShell.openFormDialog({
      mount: _overlay || document.body,
      title: 'Publish v' + version.version + '?',
      description: 'Publishing creates an immutable snapshot. Future edits will require a new draft.',
      fields: [
        {
          name: 'setProduction',
          type: 'checkbox',
          value: false,
          checkboxLabel: 'Set as production',
          help: 'Use this version for future analysis runs.',
        },
      ],
      cancelLabel: 'Keep draft',
      confirmLabel: 'Publish version',
      submittingLabel: 'Publishing…',
      onSubmit: function (values) {
        return fetch(base('api/runs/' + runId + '/analysis-rule-versions/' + encodeURIComponent(String(version.version)) + ':publish'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ set_alias: values.setProduction ? 'production' : null }),
        }).then(function (response) {
          if (!response.ok) return response.json().then(function (data) { throw new Error(data.detail || 'Could not publish rule version'); });
          return response.json();
        });
      },
    }).then(function (result) {
      if (!result || !result.confirmed) return false;
      setProduction = !!(result.values && result.values.setProduction);
      return _refreshRuleVersions(true).then(function () { return true; });
    }).then(function (didPublish) {
      if (!didPublish) return;
      _setContextStatus(
        'Published v' + version.version + (setProduction ? ' and set it as production.' : '.'),
        false
      );
    });
  }

  function _compareRuleVersion(versionId, baseVersionId) {
    var version = _ruleVersions.find(function (candidate) { return candidate.id === versionId; });
    var parent = version && _ruleVersions.find(function (candidate) { return candidate.id === baseVersionId; });
    if (!version || !parent) return Promise.resolve();
    var runId = _getRunId();
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    return fetch(base('api/runs/' + runId + '/analysis-rule-versions/' + encodeURIComponent(String(version.version)) + ':compare?base=' + encodeURIComponent(String(parent.version))))
      .then(function (response) {
        if (!response.ok) return response.json().then(function (data) { throw new Error(data.detail || 'Could not compare rule versions'); });
        return response.json();
      })
      .then(function (data) {
        var summary = data.summary || {};
        var compare = document.getElementById('pg-rule-version-compare');
        if (compare) {
          function compactRuleTitle(rule) {
            return _esc((rule && rule.title) || 'Untitled rule');
          }
          function renderEntry(item, kind) {
            var rule = kind === 'changed' ? (item.after || item.before || {}) : item;
            var detail = kind === 'changed'
              ? '<div class="pg-rule-compare-detail-grid"><div><span>Before</span><p>' + _esc((item.before && item.before.instruction) || '') + '</p></div><div><span>After</span><p>' + _esc((item.after && item.after.instruction) || '') + '</p></div></div>'
              : '<p>' + _esc(rule.instruction || '') + '</p>';
            return '<details class="pg-rule-compare-entry pg-rule-compare-' + kind + '"><summary><span class="pg-rule-compare-kind">' + (kind === 'changed' ? 'Changed' : (kind === 'added' ? 'Added' : 'Removed')) + '</span><strong>' + compactRuleTitle(rule) + '</strong><span class="pg-rule-compare-chevron">›</span></summary><div class="pg-rule-compare-entry-body">' + detail + '</div></details>';
          }
          function renderSection(title, key, items, kind, open) {
            if (!items.length) return '';
            var entries = items.map(function (item) { return renderEntry(item, kind); }).join('');
            return '<details class="pg-rule-compare-group"' + (open ? ' open' : '') + '><summary><span>' + title + '</span><span class="pg-rule-compare-count">' + items.length + '</span></summary><div class="pg-rule-compare-group-body">' + entries + '</div></details>';
          }
          var sections = [
            renderSection('Changed rules', 'changed', data.changed_rules || [], 'changed', true),
            renderSection('Added rules', 'added', data.added_rules || [], 'added', false),
            renderSection('Removed rules', 'removed', data.removed_rules || [], 'removed', false),
          ].join('');
          _renderRuleCompareDialog(compare, '<div class="pg-rule-compare-header"><div><span class="pg-rule-compare-eyebrow">Comparison</span><strong id="pg-rule-compare-dialog-title">v' + _esc(String(parent.version)) + ' → v' + _esc(String(version.version)) + '</strong></div><button class="pg-rule-action" type="button" data-close-rule-compare>Close</button></div>' +
            '<div class="pg-rule-compare-stats"><span><strong>' + (summary.changed || 0) + '</strong> changed</span><span><strong>' + (summary.added || 0) + '</strong> added</span><span><strong>' + (summary.removed || 0) + '</strong> removed</span><span><strong>' + (summary.unchanged || 0) + '</strong> unchanged</span></div>' +
            (sections || '<div class="pg-rule-version-meta">No rule content changed.</div>'));
        }
        _setContextStatus(
          'v' + parent.version + ' → v' + version.version + ': ' +
          (summary.added || 0) + ' added, ' +
          (summary.removed || 0) + ' removed, ' +
          (summary.changed || 0) + ' changed, ' +
          (summary.unchanged || 0) + ' unchanged.',
          false
        );
      })
      .catch(function (error) {
        _setContextStatus(error.message || 'Could not compare rule versions.', true);
        throw error;
      });
  }

  function _showContextFeedback(message, isError) {
    var feedback = document.getElementById('pg-context-feedback');
    if (!feedback) return;
    if (_contextFeedbackTimer) clearTimeout(_contextFeedbackTimer);
    feedback.textContent = message || '';
    feedback.classList.toggle('pg-context-feedback-error', !!isError);
    feedback.hidden = !message;
    if (!message) return;
    _contextFeedbackTimer = setTimeout(function () {
      feedback.hidden = true;
      _contextFeedbackTimer = null;
    }, 3500);
  }

  function _setContextStatus(message, isError) {
    _renderRuleViewStatus();
    if (/^Opened v/.test(String(message || ''))) return;
    _showContextFeedback(message, isError);
  }

  function _saveAnalysisContext(createNewVersion) {
    if (!_validateAnalysisRuleDrafts()) return Promise.reject(new Error('Every rule requires a title and instruction'));
    var runId = _getRunId();
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    var payload = {
      analysis_rules: _readAnalysisRulesFromEditor(),
      create_new_version: !!createNewVersion,
      rule_version_id: _selectedRuleVersionId,
    };
    _setContextStatus(createNewVersion ? 'Creating a new rule version…' : 'Saving production rules…', false);
    return fetch(base('api/runs/' + runId + '/analysis-context'), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(function (response) {
      if (!response.ok) return response.json().then(function (data) { throw new Error(data.detail || 'Could not save context'); });
      return response.json();
    }).then(function (data) {
      _selectedRuleVersionId = data.rule_version && data.rule_version.id;
      _analysisRules = data.analysis_rules || [];
      if (_config) {
        _config.analysis_rules = _analysisRules;
      }
      _renderAnalysisRulesEditor();
      return _refreshRuleVersions(false).then(function () {
        _setContextStatus(
          createNewVersion
            ? 'Created draft v' + data.rule_version.version + '.'
            : (data.rule_version.status === 'draft'
              ? 'Saved draft v' + data.rule_version.version + '.'
              : 'Saved rules. Production remains on v' + data.rule_version.version + '.'),
          false
        );
        return data;
      });
    }).then(function (data) {
      _scheduleAutoPreview(0);
      return data;
    }).catch(function (error) {
      _setContextStatus(error.message || 'Could not save production rules.', true);
      throw error;
    });
  }

  function _inferAnalysisRules(mode) {
    mode = mode === 'update' ? 'update' : 'generate';
    var runId = _getRunId();
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    var useDocumentsEl = document.getElementById('pg-infer-use-documents');
    var useExamplesEl = document.getElementById('pg-infer-use-examples');
    var inferenceSources = {
      include_documents: !useDocumentsEl || useDocumentsEl.checked,
      include_examples: !useExamplesEl || useExamplesEl.checked,
    };
    if (!inferenceSources.include_documents && !inferenceSources.include_examples) {
      _setContextStatus('Select at least one source before running rule inference.', true);
      return;
    }
    var button = document.getElementById(mode === 'update' ? 'pg-update-rules' : 'pg-infer-rules');
    if (button) {
      button.disabled = true;
      button.textContent = mode === 'update' ? 'Updating…' : 'Generating…';
    }
    _setContextStatus(
      mode === 'update'
        ? 'Updating the current rules from the selected sources…'
        : 'Generating rules from the selected sources…',
      false
    );
    fetch(base('api/runs/' + runId + '/analysis-rules/infer'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        include_documents: inferenceSources.include_documents,
        include_examples: inferenceSources.include_examples,
        mode: mode,
        rule_version_id: _selectedRuleVersionId,
        connection_id: _connectionId,
      }),
    }).then(function (response) {
      if (!response.ok) return response.json().then(function (data) { throw new Error(data.detail || 'Could not generate rules'); });
      return response.json();
    }).then(function (data) {
      _analysisRules = data.analysis_rules || [];
      _selectedRuleVersionId = data.rule_version && data.rule_version.id;
      if (_config) {
        _config.analysis_rules = _analysisRules;
      }
      _renderAnalysisRulesEditor();
      return _refreshRuleVersions(false).then(function () {
        var changes = data.changes || {};
        var changeText = mode === 'update'
          ? (changes.added || 0) + ' added, ' + (changes.changed || 0) + ' changed, ' + (changes.removed || 0) + ' removed'
          : _analysisRules.length + ' rules generated';
        _setContextStatus(
          (mode === 'update' ? 'Updated' : 'Generated') + ' draft v' + data.rule_version.version +
          ' · ' + changeText + '. Review and publish when ready.',
          false
        );
        _scheduleAutoPreview(0);
      });
    }).catch(function (error) {
      _setContextStatus(error.message || 'Could not generate rules.', true);
      if (_opts.showToast) _opts.showToast('error', 'Rule Generation Failed', error.message);
    }).finally(function () {
      if (button) {
        button.disabled = false;
        button.textContent = mode === 'update' ? 'Update rules' : 'Generate rules';
      }
    });
  }

  // ── Wire all events ──

  function _wireEvents() {
    document.querySelectorAll('#pg-infer-use-documents, #pg-infer-use-examples').forEach(function (input) {
      input.addEventListener('change', _syncInferenceSourceSummary);
    });
    _syncInferenceSourceSummary();
    var ruleList = document.getElementById('pg-rule-list');
    if (ruleList) {
      ruleList.addEventListener('input', function (event) {
        if (event.target) event.target.classList.remove('pg-field-invalid');
        _analysisRules = _readAnalysisRuleDraftsFromEditor();
        _scheduleAutoPreview();
      });
      ruleList.addEventListener('click', function (event) {
        var remove = event.target.closest('.pg-rule-remove');
        if (remove) {
          _analysisRules = _readAnalysisRuleDraftsFromEditor();
          var index = parseInt(remove.dataset.ruleIndex, 10);
          if (Number.isNaN(index)) return;
          _analysisRules.splice(index, 1);
          _editingRuleIndex = null;
          _renderAnalysisRulesEditor();
          _setRuleEditorBusy(true);
          _setContextStatus('Removing rule from the current version…', false);
          _saveAnalysisContext().catch(function () {
            _setContextStatus('The rule was removed locally but could not be saved. Retry Save context before refreshing.', true);
          }).finally(function () {
            _setRuleEditorBusy(false);
          });
          return;
        }
        var toggle = event.target.closest('[data-toggle-rule]');
        if (!toggle || event.target.closest('input, textarea, select, button')) return;
        _analysisRules = _readAnalysisRuleDraftsFromEditor();
        var toggleIndex = parseInt(toggle.dataset.toggleRule, 10);
        if (Number.isNaN(toggleIndex)) return;
        _editingRuleIndex = _editingRuleIndex === toggleIndex ? null : toggleIndex;
        _renderAnalysisRulesEditor();
      });
      ruleList.addEventListener('keydown', function (event) {
        var toggle = event.target.closest('[data-toggle-rule]');
        if (!toggle || event.target !== toggle || (event.key !== 'Enter' && event.key !== ' ')) return;
        event.preventDefault();
        toggle.click();
      });
    }
    var addRule = document.getElementById('pg-add-rule');
    if (addRule) addRule.addEventListener('click', function () {
      var selected = _ruleVersions.find(function (version) { return version.id === _selectedRuleVersionId; });
      if (!selected || selected.status !== 'draft') {
        _setContextStatus('Create or open a draft before editing rules.', true);
        return;
      }
      _analysisRules = _readAnalysisRuleDraftsFromEditor();
      _analysisRules.push({ title: '', instruction: '' });
      _editingRuleIndex = _analysisRules.length - 1;
      _renderAnalysisRulesEditor();
      var newRuleTitle = ruleList.querySelector('.pg-rule-item:last-child .pg-rule-title');
      if (newRuleTitle) {
        newRuleTitle.scrollIntoView({ block: 'nearest' });
        newRuleTitle.focus();
      }
    });
    var saveContext = document.getElementById('pg-save-context');
    if (saveContext) saveContext.addEventListener('click', function () {
      saveContext.disabled = true;
      _saveAnalysisContext().catch(function () {}).finally(function () { saveContext.disabled = false; });
    });
    _renderAnalysisRulesEditor();
    var createRuleVersion = document.getElementById('pg-create-rule-version');
    if (createRuleVersion) createRuleVersion.addEventListener('click', function () {
      var selected = _ruleVersions.find(function (version) { return version.id === _selectedRuleVersionId; });
      if (!selected || selected.is_deleted) {
        _setContextStatus('Select an available version before creating a draft.', true);
        return;
      }
      createRuleVersion.disabled = true;
      _createRuleDraft(selected.id).catch(function (error) {
        _setContextStatus(error.message || 'Could not create rule draft.', true);
      }).finally(function () { createRuleVersion.disabled = false; });
    });
    var inferRules = document.getElementById('pg-infer-rules');
    if (inferRules) inferRules.addEventListener('click', function () { _inferAnalysisRules('generate'); });
    var updateRules = document.getElementById('pg-update-rules');
    if (updateRules) updateRules.addEventListener('click', function () { _inferAnalysisRules('update'); });
    var ruleVersionList = document.getElementById('pg-rule-version-list');
    if (ruleVersionList) ruleVersionList.addEventListener('click', function (event) {
      var versionRow = event.target.closest('[data-rule-version-id]');
      var versionId = versionRow && versionRow.dataset.ruleVersionId;
      var menuToggle = event.target.closest('[data-rule-version-menu-toggle]');
      var activate = event.target.closest('[data-activate-rule-version]');
      var publish = event.target.closest('[data-publish-rule-version]');
      var merge = event.target.closest('[data-merge-rule-version]');
      var compare = event.target.closest('[data-compare-rule-version]');
      var remove = event.target.closest('[data-delete-rule-version]');
      if (versionId && (activate || publish || merge || compare || remove)) {
        _openRuleVersion(versionId);
      }
      if (menuToggle) {
        if (versionId && versionId !== _selectedRuleVersionId) {
          _openRuleVersion(versionId);
          versionRow = Array.from(ruleVersionList.querySelectorAll('[data-rule-version-id]')).find(function (row) {
            return row.dataset.ruleVersionId === versionId;
          });
          menuToggle = versionRow && versionRow.querySelector('[data-rule-version-menu-toggle]');
        }
        if (!menuToggle) return;
        var overflow = menuToggle.closest('.pg-rule-version-overflow');
        var menu = overflow && overflow.querySelector('.pg-rule-version-menu');
        ruleVersionList.querySelectorAll('.pg-rule-version-menu').forEach(function (candidate) {
          if (candidate !== menu) {
            candidate.hidden = true;
            var otherToggle = candidate.closest('.pg-rule-version-overflow').querySelector('[data-rule-version-menu-toggle]');
            if (otherToggle) otherToggle.setAttribute('aria-expanded', 'false');
          }
        });
        if (menu) {
          menu.hidden = !menu.hidden;
          menuToggle.setAttribute('aria-expanded', menu.hidden ? 'false' : 'true');
          if (!menu.hidden) {
            var firstAction = menu.querySelector('button');
            if (firstAction) firstAction.focus();
          }
        }
        return;
      }
      if (activate) {
        _changeRuleVersion(activate.dataset.activateRuleVersion, 'activate');
        return;
      }
      if (publish) _publishRuleVersion(publish.dataset.publishRuleVersion).catch(function (error) {
        _setContextStatus(error.message || 'Could not publish rule version.', true);
      });
      if (publish) return;
      if (merge) {
        _openRuleMerge(merge.dataset.mergeRuleVersion);
        return;
      }
      if (compare) {
        _openRuleCompare(compare.dataset.compareRuleVersion);
        return;
      }
      if (remove) {
        _confirmRuleVersionDeletion(remove.dataset.deleteRuleVersion);
        return;
      }
      if (event.target.closest('button, input, select, textarea, .pg-rule-version-menu')) return;
      var versionRow = event.target.closest('[data-rule-version-id]');
      if (versionRow) _openRuleVersion(versionRow.dataset.ruleVersionId);
    });
    if (ruleVersionList) ruleVersionList.addEventListener('keydown', function (event) {
      var versionRow = event.target.closest('[data-rule-version-id]');
      if (!versionRow || event.target !== versionRow || (event.key !== 'Enter' && event.key !== ' ')) return;
      event.preventDefault();
      _openRuleVersion(versionRow.dataset.ruleVersionId);
    });
    if (ruleVersionList) {
      (_overlay || document).addEventListener('click', function (event) {
        if (event.target.closest('[data-rule-version-menu-toggle], .pg-rule-version-menu')) return;
        ruleVersionList.querySelectorAll('.pg-rule-version-menu').forEach(function (menu) {
          menu.hidden = true;
          var toggle = menu.closest('.pg-rule-version-overflow').querySelector('[data-rule-version-menu-toggle]');
          if (toggle) toggle.setAttribute('aria-expanded', 'false');
        });
      });
    }
    var ruleVersionCompare = document.getElementById('pg-rule-version-compare');
    if (ruleVersionCompare) ruleVersionCompare.addEventListener('click', function (event) {
      if (event.target.closest('[data-close-rule-compare], [data-rule-compare-backdrop]')) {
        _closeRuleCompareDialog(ruleVersionCompare);
      }
    });
    if (ruleVersionCompare) ruleVersionCompare.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape' || !ruleVersionCompare.classList.contains('pg-rule-compare-picker')) return;
      event.preventDefault();
      _closeRuleCompareDialog(ruleVersionCompare);
    });

    var documentInput = document.getElementById('pg-document-input');
    if (documentInput) {
      documentInput.addEventListener('change', function () {
        _handleReferenceDocumentFiles(documentInput.files);
        documentInput.value = '';
      });
    }
    var documentDropzone = document.getElementById('pg-document-dropzone');
    if (documentDropzone) {
      ['dragenter', 'dragover'].forEach(function (eventName) {
        documentDropzone.addEventListener(eventName, function (event) {
          event.preventDefault();
          if (!documentInput || !documentInput.disabled) documentDropzone.classList.add('pg-document-dropzone-active');
        });
      });
      ['dragleave', 'drop'].forEach(function (eventName) {
        documentDropzone.addEventListener(eventName, function (event) {
          event.preventDefault();
          documentDropzone.classList.remove('pg-document-dropzone-active');
        });
      });
      documentDropzone.addEventListener('drop', function (event) {
        if (documentInput && !documentInput.disabled) {
          _handleReferenceDocumentFiles(event.dataTransfer && event.dataTransfer.files);
        }
      });
    }
    var documentList = document.getElementById('pg-document-list');
    if (documentList) {
      documentList.addEventListener('change', function (event) {
        var select = event.target.closest('.pg-document-select');
        if (!select) return;
        var index = parseInt(select.dataset.documentIndex, 10);
        if (Number.isNaN(index) || index < 0 || index >= _referenceDocuments.length) return;
        var document = _referenceDocuments[index];
        var selected = select.checked;
        select.disabled = true;
        _updateReferenceDocumentSelection(document, selected).then(function (updated) {
          document.selected = updated ? updated.selected : selected;
          _setDocumentUploadStatus(document.name + (document.selected ? ' included in' : ' excluded from') + ' project analysis.', false);
          _renderReferenceDocuments();
          _scheduleAutoPreview(0);
        }).catch(function (error) {
          document.selected = !selected;
          _renderReferenceDocuments();
          _setDocumentUploadStatus('Could not update ' + document.name + '.', true);
          if (_opts.showToast) _opts.showToast('error', 'Document Update Failed', error.message);
        });
      });
      documentList.addEventListener('click', function (event) {
        var remove = event.target.closest('.pg-document-remove');
        if (!remove) return;
        var index = parseInt(remove.dataset.documentIndex, 10);
        if (Number.isNaN(index) || index < 0 || index >= _referenceDocuments.length) return;
        var removed = _referenceDocuments[index];
        remove.disabled = true;
        _deleteReferenceDocument(removed).then(function () {
          var currentIndex = _referenceDocuments.indexOf(removed);
          if (currentIndex >= 0) _referenceDocuments.splice(currentIndex, 1);
          _setDocumentUploadStatus(removed.name + ' deleted from the project library.', false);
          _renderReferenceDocuments();
          _scheduleAutoPreview(0);
        }).catch(function (error) {
          remove.disabled = false;
          _setDocumentUploadStatus('Could not delete ' + removed.name + '.', true);
          if (_opts.showToast) _opts.showToast('error', 'Document Delete Failed', error.message);
        });
      });
    }

    // Additional instructions
    var instrEl = document.getElementById('pg-additional-instructions');
    if (instrEl) {
      instrEl.addEventListener('input', function () {
        _onAdditionalInstructionsChange();
        _scheduleAutoPreview();
      });
    }

    // Remove category (removes entire group including its details)
    var catList = document.getElementById('pg-categories-list');
    if (catList) catList.addEventListener('click', function (e) {
      var removeBtn = e.target.closest('.pg-category-remove');
      if (removeBtn) {
        var group = removeBtn.closest('.pg-category-group');
        if (group) { group.remove(); _scheduleAutoPreview(); }
      }
      // Remove individual detail
      var detRemoveBtn = e.target.closest('.pg-detail-remove');
      if (detRemoveBtn) {
        var detItem = detRemoveBtn.closest('.pg-detail-item');
        if (detItem) { detItem.remove(); _scheduleAutoPreview(); }
      }
      // Add detail to a category
      var addDetBtn = e.target.closest('.pg-add-detail-btn');
      if (addDetBtn) {
        var row = addDetBtn.closest('.pg-add-detail-row');
        var input = row && row.querySelector('.pg-add-detail-input');
        if (input) {
          var val = input.value.trim();
          if (!val) return;
          var parentCat = row.dataset.cat;
          var sublist = row.parentElement.querySelector('.pg-details-sublist[data-cat="' + parentCat + '"]');
          if (!sublist) {
            sublist = document.createElement('div');
            sublist.className = 'pg-details-sublist';
            sublist.dataset.cat = parentCat;
            row.parentElement.insertBefore(sublist, row);
            var emptyDetails = row.parentElement.querySelector('.pg-category-details-empty');
            if (emptyDetails) emptyDetails.remove();
          }
          var div = document.createElement('div');
          div.className = 'pg-detail-item';
          div.dataset.detail = val;
          div.dataset.parentCat = parentCat;
          div.innerHTML = '<span class="pg-detail-name">' + _esc(val) + '</span>' +
            '<button class="pg-detail-remove" type="button" title="Remove detail" aria-label="Remove ' + _escAttr(val) + ' detail">&times;</button>';
          sublist.appendChild(div);
          input.value = '';
          _scheduleAutoPreview();
        }
      }
    });

    // Enter key for inline detail inputs
    if (catList) catList.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        var input = e.target.closest('.pg-add-detail-input');
        if (input) {
          var btn = input.parentElement.querySelector('.pg-add-detail-btn');
          if (btn) btn.click();
        }
      }
    });

    // Add category
    var addBtn = document.getElementById('pg-add-category-btn');
    var addInput = document.getElementById('pg-new-category');
    if (addBtn && addInput) {
      var addCat = function () {
        var val = addInput.value.trim();
        if (!val) return;
        var wrapper = document.createElement('div');
        wrapper.innerHTML = _buildCategoryGroup(val, [], []);
        var group = wrapper.firstElementChild;
        catList.appendChild(group);
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
    _wirePathPickers(_overlay);

    // Additional fields checkboxes
    _overlay.querySelectorAll('.pg-field-toggle input[type="checkbox"][data-field]').forEach(function (cb) {
      cb.addEventListener('change', function () {
        if (cb.dataset.field === 'metadata') {
          var metaRow = document.getElementById('pg-metadata-path-row');
          if (metaRow) metaRow.style.display = cb.checked ? '' : 'none';
        }
        _scheduleAutoPreview();
      });
    });

    // Filter changes
    var maxScore = document.getElementById('pg-max-score');
    var skipAnalyzed = document.getElementById('pg-skip-analyzed');
    if (maxScore) {
      maxScore.addEventListener('input', function () {
        var valEl = document.getElementById('pg-max-score-value');
        if (valEl) valEl.textContent = maxScore.value + '%';
        _onFilterChange();
      });
    }
    if (skipAnalyzed) skipAnalyzed.addEventListener('change', _onFilterChange);
    var humanOverwrite = document.getElementById('pg-allow-human-overwrite');
    if (humanOverwrite) humanOverwrite.addEventListener('change', _onFilterChange);
    var targetLimit = document.getElementById('pg-target-limit');
    if (targetLimit) {
      targetLimit.addEventListener('input', function () {
        var digits = targetLimit.value.replace(/\D/g, '').slice(0, 4);
        if (targetLimit.value !== digits) targetLimit.value = digits;
        _updateFooterCount();
      });
      targetLimit.addEventListener('blur', function () {
        if (targetLimit.value && parseInt(targetLimit.value, 10) < 1) targetLimit.value = '';
        _updateFooterCount();
      });
    }
    ['pg-use-project-rules', 'pg-use-project-documents'].forEach(function (id) {
      var toggle = document.getElementById(id);
      if (toggle) toggle.addEventListener('change', function () {
        _syncActionAvailability();
        _scheduleAutoPreview(0);
      });
    });

    // Row selection
    _wireRowSelection();
    _wireShowMore();

    // Preview toggle
    var toggleBtn = document.getElementById('pg-preview-toggle');
    if (toggleBtn) toggleBtn.addEventListener('click', function () {
      var content = document.getElementById('pg-preview-content');
      if (content) {
        var expanded = content.classList.toggle('expanded');
        var label = expanded ? 'Collapse prompt preview' : 'Expand prompt preview';
        toggleBtn.innerHTML = _icon(expanded ? 'close' : 'expand');
        toggleBtn.title = label;
        toggleBtn.setAttribute('aria-label', label);
      }
    });

    // Copy prompt button
    var copyBtn = document.getElementById('pg-preview-copy');
    if (copyBtn) copyBtn.addEventListener('click', function () {
      var content = document.getElementById('pg-preview-content');
      if (!content) return;
      var text = content.innerText || content.textContent || '';
      navigator.clipboard.writeText(text).then(function () {
        copyBtn.innerHTML = _icon('check');
        copyBtn.title = 'Prompt copied';
        copyBtn.setAttribute('aria-label', 'Prompt copied');
        setTimeout(function () {
          copyBtn.innerHTML = _icon('copy');
          copyBtn.title = 'Copy prompt to clipboard';
          copyBtn.setAttribute('aria-label', 'Copy prompt to clipboard');
        }, 1500);
      });
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
    var includeAnalyzed = document.getElementById('pg-include-analyzed');
    if (includeAnalyzed) {
      includeAnalyzed.addEventListener('click', function () {
        var skipAnalyzed = document.getElementById('pg-skip-analyzed');
        if (skipAnalyzed) skipAnalyzed.checked = false;
        _onFilterChange();
      });
    }
  }

  function _selectItem(itemId) {
    _selectedItemId = itemId;
    _highlightSelectedRow();
    _scheduleAutoPreview();
    var testBtn = document.getElementById('pg-test-btn');
    if (testBtn) _syncActionAvailability();
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
    var filterBadge = document.getElementById('pg-filter-badge');
    if (filterBadge) filterBadge.textContent = String(_getMatchedTargetCount(matched));
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
    _syncActionAvailability();
  }

  function _getTargetLimit(matchedCount) {
    var limitEl = document.getElementById('pg-target-limit');
    if (!limitEl || !String(limitEl.value || '').trim()) return matchedCount;
    var requested = parseInt(limitEl.value, 10);
    if (!Number.isFinite(requested) || requested < 1) return 0;
    return Math.min(requested, matchedCount);
  }

  function _syncActionAvailability() {
    var matched = _getMatchedItems();
    var runAllBtn = document.getElementById('pg-runall-btn');
    var testBtn = document.getElementById('pg-test-btn');
    var selectedMetrics = _getSelectedMetrics();
    var metricsReady = selectedMetrics === null || selectedMetrics.length > 0;
    var ready = !!(
      _config &&
      _config.llm_configured &&
      _documentUploadsInFlight === 0 &&
      metricsReady
    );
    if (runAllBtn) {
      var targetCount = _getTargetLimit(_getMatchedTargetCount(matched));
      runAllBtn.textContent = 'Analyze ' + targetCount + (targetCount === 1 ? ' target' : ' targets');
      runAllBtn.disabled = !ready || targetCount === 0 || _running;
    }
    if (testBtn) testBtn.disabled = !ready || _running;
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
        _wirePathPickers(section);
      }
    }
  }

  function _onMappingFieldChange(sel) {
    var idx = sel.dataset.mappingIdx;
    var wrapper = document.getElementById('pg-mapping-' + idx + '-path-wrap');
    if (!wrapper) return;
    wrapper.innerHTML = _buildPathPicker('pg-mapping-' + idx + '-paths', sel.value);
    _wirePathPickers(wrapper);
  }

  function _onCustomVarFieldChange(sel) {
    var idx = sel.dataset.customvarIdx;
    var field = sel.value;
    var wrapper = document.getElementById('pg-customvar-' + idx + '-key-wrapper');
    if (!wrapper) return;

    if (!field) { wrapper.innerHTML = ''; return; }

    wrapper.innerHTML = _buildPathPicker('pg-customvar-' + idx + '-paths', field);
    _wirePathPickers(wrapper);
  }

  // ── Auto Preview (debounced) ──

  function _scheduleAutoPreview(delayMs) {
    if (_previewTimer) clearTimeout(_previewTimer);
    _previewTimer = setTimeout(_autoPreview, delayMs || 500);
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
        body: JSON.stringify({ item_id: itemId, metric: _opts.getMetric ? _opts.getMetric() : null, config: cfg, connection_id: _connectionId }),
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
          if (toggleBtn) {
            toggleBtn.style.display = 'inline-grid';
            toggleBtn.innerHTML = _icon('expand');
            toggleBtn.title = 'Expand prompt preview';
            toggleBtn.setAttribute('aria-label', 'Expand prompt preview');
          }
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
      body: JSON.stringify({ item_ids: [testItemId], metric: _opts.getMetric ? _opts.getMetric() : null, config: cfg, connection_id: _connectionId }),
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
      }
      _syncActionAvailability();
    });
  }

  function _renderTestResults() {
    var container = document.getElementById('pg-test-results');
    if (!container) return;

    if (_testResults.length === 0) {
      container.innerHTML = '<div class="pg-empty-msg">No results</div>';
      return;
    }

    container.innerHTML = _testResults.map(function (r) {
      var color = _rootCauseColor(r.root_cause);
      var confPct = Math.round((r.confidence || 0) * 100);
      var errorHtml = r.error ? '<div class="pg-result-error">' + _esc(r.error) + '</div>' : '';

      var fieldsBadgesHtml = '';
      var inputSectionHtml = '';
      if (r.messages && r.messages.length > 0) {
        var userMsg = '';
        var systemMsg = '';
        for (var m = 0; m < r.messages.length; m++) {
          if (r.messages[m].role === 'user') userMsg = r.messages[m].content || '';
          if (r.messages[m].role === 'system') systemMsg = r.messages[m].content || '';
        }

        var itemCtxMatch = systemMsg.match(/EVALUATION ITEM DATA:\n([\s\S]*?)\n\nRespond ONLY/)
          || userMsg.match(/Now analyze this evaluation item:\n\n([\s\S]*?)\n\nDetermine the root cause/)
          || userMsg.match(/Now analyze this evaluation item:\n\n([\s\S]*?)\n\n/);
        var itemCtx = itemCtxMatch ? itemCtxMatch[1].trim() : '';

        var fieldDefs = [
          { key: 'input', label: 'Input', pattern: /^INPUT:/m },
          { key: 'expected', label: 'Expected', pattern: /^EXPECTED OUTPUT:/m },
          { key: 'output', label: 'Output', pattern: /^ACTUAL OUTPUT:/m },
          { key: 'error', label: 'Error', pattern: /^ERROR:/m },
          { key: 'metric', label: 'Metric', pattern: /^SELECTED METRIC RESULT:/m },
          { key: 'metadata', label: 'Metadata', pattern: /^(?:ITEM METADATA:|SELECTED METADATA:)/m },
          { key: 'trace', label: 'Trace', pattern: /^TRACE EVIDENCE:/m },
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

      }


      return '<div class="pg-test-result-card">' +
        '<div class="pg-result-header">' +
          '<span class="pg-result-item-id">' + _esc(r.item_id.slice(0, 24)) + (r.metric_name ? ' · ' + _esc(r.metric_name) : '') + '</span>' +
        '</div>' +
        (r.root_cause_detail ? '<div class="pg-result-rc" style="color:var(--text-primary, #eee);">' + _esc(r.root_cause_detail) + '</div>' : '') +
        '<div class="pg-result-rc" style="color:' + color + ';' + (r.root_cause_detail ? 'font-size:var(--font-base);opacity:0.8;margin-top:2px;' : '') + '">' + _esc(r.root_cause) + '</div>' +
        '<div class="pg-confidence-row">' +
          '<div class="pg-confidence-bar"><div class="pg-confidence-fill" style="width:' + confPct + '%;background:' + color + ';"></div></div>' +
          '<span class="pg-confidence-val">' + (r.confidence != null ? r.confidence.toFixed(2) : '?') + '</span>' +
        '</div>' +
        '<div class="pg-result-note">' + _esc(r.root_cause_note || '') + '</div>' +
        errorHtml +
        fieldsBadgesHtml +
        inputSectionHtml +
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

    var maxScoreEl = document.getElementById('pg-max-score');
    var skipEl = document.getElementById('pg-skip-analyzed');
    var humanOverwriteEl = document.getElementById('pg-allow-human-overwrite');

    var body = {
      metric: _opts.getMetric ? _opts.getMetric() : null,
      item_filter: 'failed',
      max_score: maxScoreEl ? (parseFloat(maxScoreEl.value) / 100) || undefined : undefined,
      only_unanalyzed: skipEl ? skipEl.checked : true,
      allow_human_overwrite: humanOverwriteEl ? humanOverwriteEl.checked : false,
      threshold: _opts.getThreshold ? _opts.getThreshold() : 0.8,
      config: cfg,
      connection_id: _connectionId,
    };
    var requestedLimit = _getTargetLimit(_getMatchedTargetCount(_getMatchedItems()));
    body.limit = requestedLimit || undefined;
    if (_opts.getMetrics) {
      body.metric = null;
      body.metrics = _getSelectedMetrics();
    }

    var btn = document.getElementById('pg-runall-btn');
    if (btn) { btn.disabled = true; btn.textContent = '\u23F3 Analyzing\u2026'; }

    var progress = document.getElementById('pg-runall-progress');
    var fill = document.getElementById('pg-runall-progress-fill');
    var progressText = document.getElementById('pg-runall-progress-text');
    var subtext = document.getElementById('pg-runall-progress-subtext');
    if (progress) progress.style.display = 'block';
    
    if (fill) {
      fill.style.transition = 'none';
      fill.style.width = '0%';
      fill.style.background = '';
      // Force reflow
      void fill.offsetWidth;
      fill.style.transition = 'width 0.25s ease-out';
    }
    
    if (progressText) progressText.textContent = 'Preparing analysis\u2026';
    if (subtext) subtext.textContent = 'Starting LLM analysis...';

    function updateProgress(evt) {
      var total = Number(evt.total || 0);
      var completed = Number(evt.completed || 0);
      var errors = Number(evt.errors || 0);
      var pct = total > 0 ? Math.round((completed / total) * 100) : 0;
      if (fill) fill.style.width = pct + '%';
      if (evt.type === 'aggregating') {
        if (btn) btn.textContent = '\u23F3 Aggregating\u2026';
        if (progressText) progressText.textContent = 'Aggregating root causes\u2026';
        if (subtext) {
          subtext.textContent = 'Analysis complete. Consolidating related categories, details, and solutions.' +
            (errors > 0 ? ' Errors: ' + errors : '');
        }
        return;
      }
      if (progressText) {
        progressText.textContent = total > 0
          ? 'Analyzing metric failures: ' + completed + '/' + total + ' (' + pct + '%)'
          : 'No matching items to analyze';
      }
      if (subtext) {
        if (evt.type === 'started') {
          subtext.textContent = total > 0
            ? 'Running up to ' + (evt.concurrency || 20) + ' LLM calls concurrently.'
            : 'All matching items are already analyzed or filtered out.';
        } else {
          var itemText = evt.item_id ? 'Last: ' + String(evt.item_id).slice(0, 32) + (evt.metric_name ? ' · ' + evt.metric_name : '') : 'Waiting for results...';
          subtext.textContent = itemText + (errors > 0 ? ' | Errors: ' + errors : '');
        }
      }
    }

    function finishRunAll(data) {
      var analyzed = Number(data.total_analyzed || 0);
      var aggregated = Number(data.aggregated || 0);
      var completionText = analyzed > 0
        ? 'Analyzed <strong>' + analyzed + '</strong> metric failures successfully'
        : 'Existing root-cause analysis checked successfully';
      if (aggregated > 0) {
        completionText += '<div>Consolidated <strong>' + aggregated + '</strong> category/detail/solution labels</div>';
      }
      if (fill) {
        fill.style.transition = 'width 0.3s ease-out';
        fill.style.width = '100%';
      }
      if (progressText) progressText.textContent = 'Analysis Complete!';
      if (subtext) subtext.textContent = 'Finalizing results...';

      var resultsEl = document.getElementById('pg-runall-results');
      if (resultsEl) {
        resultsEl.innerHTML = '<div class="pg-runall-done">' +
          '<div class="pg-runall-done-icon">\u2728</div>' +
          '<div class="pg-runall-done-text">' + completionText +
          (data.errors > 0 ? '<div class="pg-runall-done-error">\u26A0\uFE0F ' + data.errors + ' metric analyses failed</div>' : '') +
          '</div></div>';
      }

      if (_opts.showToast) {
        var toastText = analyzed + ' metric failures analyzed';
        if (aggregated > 0) toastText += ' · ' + aggregated + ' labels consolidated';
        _opts.showToast('success', 'Analysis Complete', toastText);
      }
      if (_opts.onAnalysisComplete) _opts.onAnalysisComplete(data);

      setTimeout(function () {
        if (progress) progress.style.display = 'none';
      }, 3000);
    }

    function readProgressStream(response) {
      if (!response.body || !window.TextDecoder) {
        throw new Error('Streaming progress is not supported by this browser.');
      }
      var reader = response.body.getReader();
      var decoder = new TextDecoder();
      var buffer = '';
      var finalData = null;

      function consume(text) {
        buffer += text;
        var lines = buffer.split('\n');
        buffer = lines.pop() || '';
        lines.forEach(function (line) {
          if (!line.trim()) return;
          var evt = JSON.parse(line);
          if (evt.type === 'started' || evt.type === 'progress' || evt.type === 'aggregating') {
            updateProgress(evt);
          } else if (evt.type === 'done') {
            finalData = evt;
          } else if (evt.type === 'error') {
            throw new Error(evt.message || 'Analysis failed');
          }
        });
      }

      function pump() {
        return reader.read().then(function (result) {
          if (result.done) {
            if (buffer.trim()) consume('\n');
            if (!finalData) throw new Error('Analysis ended without a completion event.');
            return finalData;
          }
          consume(decoder.decode(result.value, { stream: true }));
          return pump();
        });
      }

      return pump();
    }

    fetch(base('api/runs/' + runId + '/analyze-stream'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    .then(function (r) {
      if (!r.ok) return r.json().then(function (d) { throw new Error(d.detail || 'Analysis failed'); });
      return readProgressStream(r);
    })
    .then(finishRunAll)
    .catch(function (err) {
      console.error('Run All error:', err);
      if (progressText) progressText.textContent = 'Failed';
      if (subtext) subtext.textContent = err.message || 'An error occurred during analysis.';
      if (fill) {
        fill.style.transition = 'width 0.3s ease-out';
        fill.style.width = '0%';
        fill.style.background = 'var(--error)';
      }
      if (_opts.showToast) _opts.showToast('error', 'Analysis Failed', err.message);
      setTimeout(function () {
        if (progress) progress.style.display = 'none';
      }, 4000);
    })
    .finally(function () {
      _running = false;
      _updateFooterCount();
    });
  }

  // ── Public API ──
  return {
    init: init,
    open: open,
    close: close,
    refreshFilters: function () {
      if (_overlay) _onFilterChange();
    },
  };
})();
