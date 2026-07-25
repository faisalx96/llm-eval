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
  var _ruleVersions = [];
  var _selectedRuleVersionId = null;
  var _canDeleteRuleVersions = false;
  var _canActivateRuleVersions = false;
  var _canRestoreRuleVersions = false;
  var _documentUploadsInFlight = 0;

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
    // Highlight section labels like INPUT:, EXPECTED OUTPUT:, ACTUAL OUTPUT:, etc.
    escaped = escaped.replace(/^(REFERENCE DOCUMENTS:|DOCUMENT:|INPUT:|EXPECTED OUTPUT:|ACTUAL OUTPUT:|ERROR:|SELECTED METRIC RESULT:|ITEM METADATA:|SELECTED METADATA:)/gm,
      '<span class="pg-hl-label">$1</span>');
    // Highlight bulleted list items (root cause categories and details, including indented)
    escaped = escaped.replace(/^( *- (.+))$/gm, function (line, fullLine, name) {
      var color = _rootCauseColor(name, '');
      return color
        ? '<span class="pg-hl-category" style="color:' + color + '">' + fullLine + '</span>'
        : '<span class="pg-hl-category">' + fullLine + '</span>';
    });
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
      return true;
    });
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
    var descriptionEl = scroll.querySelector('#pg-project-description');
    if (descriptionEl) descriptionEl.value = (_config && _config.project_description) || '';

    // Sticky footer
    var footer = document.createElement('div');
    footer.className = 'playground-footer';
    var llmOk = _config && _config.llm_configured;
    var conns = (_config && _config.llm_connections) || [];
    var connSelect = '';
    if (conns.length) {
      connSelect = '<div class="pg-connection" title="LLM connection used for analysis">' +
        '<span class="pg-connection-icon">◈</span>' +
        '<span class="pg-connection-label">LLM</span>' +
        '<select id="pg-connection" class="pg-connection-select">' +
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
      '<button class="pg-footer-btn pg-footer-runall" id="pg-runall-btn" ' + (!llmOk ? 'disabled' : '') + '>Analyze failures (' + _getMatchedItems().length + ' items)</button>';
    footer.hidden = false;
    modal.appendChild(footer);
    var connEl = footer.querySelector('#pg-connection');
    if (connEl) connEl.addEventListener('change', function () { _connectionId = connEl.value || null; });

    overlay.appendChild(modal);
    (pageContainer || document.body).appendChild(overlay);
    _overlay = overlay;

    // Wire all events
    _wireEvents();
    _syncActionAvailability();
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

  function _buildAnalysisRulesEditor() {
    var selected = _ruleVersions.find(function (version) { return version.id === _selectedRuleVersionId; });
    var readOnly = !selected || selected.status !== 'draft';
    if (_analysisRules.length === 0) {
      return '<div class="pg-rule-empty">' + (readOnly
        ? 'This version has no rules. Create a draft before editing.'
        : 'No rules yet. Generate rules after selecting reference documents, or add one manually.') + '</div>';
    }
    return _analysisRules.map(function (rule, index) {
      return '<div class="pg-rule-item" data-rule-index="' + index + '" data-rule-id="' + _escAttr(rule.id || '') + '">' +
        '<div class="pg-rule-item-head"><span>Rule ' + (index + 1) + '</span><button class="pg-rule-action pg-rule-action-danger pg-rule-remove" type="button" data-rule-index="' + index + '"' + (readOnly ? ' disabled' : '') + '>Remove</button></div>' +
        '<input class="pg-rule-title" type="text" value="' + _escAttr(rule.title || '') + '" placeholder="Rule title" aria-label="Rule title"' + (readOnly ? ' disabled' : '') + ' />' +
        '<textarea class="pg-rule-instruction" placeholder="What must be checked and how it affects the diagnosis" aria-label="Rule instruction"' + (readOnly ? ' disabled' : '') + '>' + _esc(rule.instruction || '') + '</textarea>' +
      '</div>';
    }).join('');
  }

  function _buildRuleVersionHistory() {
    if (_ruleVersions.length === 0) {
      return '<div class="pg-rule-empty">No saved versions yet.</div>';
    }
    return _ruleVersions.map(function (version) {
      var state = version.status === 'draft' ? 'Draft' : (version.is_active ? 'Production' : (version.status || 'Published'));
      var created = version.created_at ? new Date(version.created_at).toLocaleString() : 'Unknown date';
      var actions = [];
      if (version.id !== _selectedRuleVersionId) {
        actions.push('<button class="pg-rule-action" type="button" data-open-rule-version="' + _escAttr(version.id) + '">Open</button>');
      }
      if (version.status === 'draft' && _canActivateRuleVersions) {
        actions.push('<button class="pg-rule-action pg-rule-action-primary" type="button" data-publish-rule-version="' + _escAttr(version.id) + '">Publish</button>');
      }
      if (version.status === 'published' && !version.is_active && _canActivateRuleVersions) {
        actions.push('<button class="pg-rule-action pg-rule-action-primary" type="button" data-activate-rule-version="' + _escAttr(version.id) + '">Set production</button>');
      }
      if (version.parent_version_id) {
        actions.push('<button class="pg-rule-action" type="button" data-compare-rule-version="' + _escAttr(version.id) + '">Compare</button>');
      }
      return '<div class="pg-rule-version' + (version.id === _selectedRuleVersionId ? ' pg-rule-version-selected' : '') + '">' +
        '<div class="pg-rule-version-header"><span class="pg-rule-version-name">v' + version.version + '</span>' +
        '<span class="pg-rule-version-state">' + _esc(state) + '</span></div>' +
        '<div class="pg-rule-version-meta">' + _esc(version.name || version.source) + ' · ' + version.rules.length + ' rules · ' + _esc(created) + '</div>' +
        (actions.length ? '<div class="pg-rule-version-actions">' + actions.join('') + '</div>' : '') +
      '</div>';
    }).join('');
  }

  function _buildReferenceDocumentList() {
    if (_referenceDocuments.length === 0) {
      return '<div class="pg-document-empty">This project library is empty. Add documents once, then select the ones to use for this run.</div>';
    }
    return _referenceDocuments.map(function (document, index) {
      var meta = _formatCharacterCount(document.characters || document.content.length);
      if (document.truncated) meta += ' · shortened to prompt limit';
      return '<div class="pg-document-item" data-document-index="' + index + '">' +
        '<input class="pg-document-select" type="checkbox" data-document-index="' + index + '"' + (document.selected !== false ? ' checked' : '') + ' aria-label="Include ' + _escAttr(document.name) + ' in analyzer runs" />' +
        '<div class="pg-document-copy">' +
          '<span class="pg-document-name">' + _esc(document.name) + '</span>' +
          '<span class="pg-document-meta">' + _esc(meta) + '</span>' +
        '</div>' +
        '<button class="pg-document-remove" type="button" data-document-index="' + index + '" aria-label="Delete ' + _escAttr(document.name) + '">Delete</button>' +
      '</div>';
    }).join('');
  }

  function _buildScrollContent() {
    var cats = (_config && _config.default_categories) || [
      'Hallucination', 'Incomplete Answer', 'Wrong Format', 'Context Missing',
      'Reasoning Error', 'Tool Use Error', 'Instruction Following', 'Knowledge Gap',
    ];
    var html = '<div class="pg-workspace">';

    // ── Project Description ──
    var descriptionBody = '';
    descriptionBody += '<div class="pg-instructions-hint">Describe what the project does, who it serves, and what a correct output should accomplish. This context is included in every analyzer prompt.</div>';
    descriptionBody += '<textarea class="pg-instructions-textarea pg-project-description" id="pg-project-description" placeholder="e.g. This assistant converts natural-language analytics questions into read-only SQL for our warehouse. A correct response must use the provided schema, preserve the user intent, and avoid data-changing statements." spellcheck="true" required aria-required="true"></textarea>';
    descriptionBody += '<div class="pg-required-message" id="pg-project-description-error">Enter a project description before testing or running the analyzer.</div>';
    var rulesBody = '<div class="pg-instructions-hint">Rules are shared requirements and decision instructions applied during diagnosis.</div>' +
      '<div class="pg-rule-inference-options">' +
        '<div class="pg-rule-inference-heading">Generate rules from</div>' +
        '<label class="pg-inference-toggle">' +
          '<input id="pg-infer-use-description" type="checkbox" checked />' +
          '<span class="pg-inference-switch" aria-hidden="true"></span>' +
          '<span class="pg-inference-copy"><strong>Project description</strong><span>Use the saved business and correctness context.</span></span>' +
        '</label>' +
        '<label class="pg-inference-toggle">' +
          '<input id="pg-infer-use-documents" type="checkbox" checked />' +
          '<span class="pg-inference-switch" aria-hidden="true"></span>' +
          '<span class="pg-inference-copy"><strong>Selected documents</strong><span>Use documents currently selected for this run.</span></span>' +
        '</label>' +
        '<label class="pg-inference-toggle">' +
          '<input id="pg-infer-use-examples" type="checkbox" checked />' +
          '<span class="pg-inference-switch" aria-hidden="true"></span>' +
          '<span class="pg-inference-copy"><strong>Approved English examples</strong><span>Use every approved English correction for this project and task.</span></span>' +
        '</label>' +
      '</div>' +
      '<div class="pg-rule-list" id="pg-rule-list">' + _buildAnalysisRulesEditor() + '</div>' +
      '<button class="pg-context-secondary" id="pg-add-rule" type="button">Add rule</button>' +
      '<div class="pg-context-divider"></div>' +
      '<h3 class="pg-context-title">Version history</h3>' +
      '<div class="pg-rule-version-list" id="pg-rule-version-list">' + _buildRuleVersionHistory() + '</div>' +
      '<div class="pg-rule-compare" id="pg-rule-version-compare" hidden></div>';
    html += '<aside class="pg-context-panel">' +
      '<div class="pg-context-eyebrow">Project context</div>' +
      '<h2 class="pg-context-title">Description</h2>' + descriptionBody +
      '<div class="pg-context-divider"></div>' +
      '<h2 class="pg-context-title">Analysis rules</h2>' + rulesBody +
      '<div class="pg-context-actions">' +
        '<button class="pg-context-secondary" id="pg-save-context" type="button">Save draft</button>' +
        '<button class="pg-context-secondary" id="pg-create-rule-version" type="button">Create draft</button>' +
        '<button class="pg-context-primary" id="pg-infer-rules" type="button">Generate rules</button>' +
      '</div>' +
      '<div class="pg-context-status" id="pg-context-status" role="status" aria-live="polite"></div>' +
    '</aside>';
    html += '<div class="pg-analysis-main">';

    // ── Reference Documents ──
    var documentsBody = '';
    documentsBody += '<div class="pg-instructions-hint">Manage the shared project document library. Uploaded documents remain available to every project member; checked documents are included in the current analysis.</div>';
    documentsBody += '<label class="pg-document-dropzone" id="pg-document-dropzone" for="pg-document-input">' +
      '<span class="pg-document-upload-title">Choose documents or drop them here</span>' +
      '<span class="pg-document-upload-help">PDF, DOCX, TXT, Markdown, HTML, CSV, JSON, or YAML · up to 10 MB each</span>' +
    '</label>';
    documentsBody += '<input class="pg-document-input" id="pg-document-input" type="file" multiple accept=".pdf,.docx,.txt,.text,.md,.markdown,.html,.htm,.csv,.json,.yaml,.yml,.log,.rst" />';
    documentsBody += '<div class="pg-document-upload-status" id="pg-document-upload-status" role="status" aria-live="polite"></div>';
    documentsBody += '<div class="pg-document-list" id="pg-document-list">' + _buildReferenceDocumentList() + '</div>';
    var selectedDocumentCount = _referenceDocuments.filter(function (document) { return document.selected !== false; }).length;
    html += _section('Reference Document Library', documentsBody, { badge: selectedDocumentCount + ' selected', badgeId: 'pg-documents-badge' });

    // ── Additional Instructions ──
    var instrBody = '';
    instrBody += '<div class="pg-instructions-hint">Customize how the AI analyzes items. Use <code>{variable_name}</code> to reference item data \u2014 detected variables appear in Variable Mapping below.</div>';
    instrBody += '<textarea class="pg-instructions-textarea" id="pg-additional-instructions" placeholder="e.g. Focus on whether the response addresses all parts of the question.\nPay special attention to the {rubric} criteria." spellcheck="false"></textarea>';
    html += _section('Additional Instructions', instrBody);

    // ── Root Cause Categories & Details ──
    var detailsMap = (_config && _config.category_details_map) || {};
    var totalDetails = 0;
    var catDetBody = '';
    catDetBody += '<div id="pg-categories-list">';
    for (var i = 0; i < cats.length; i++) {
      var cat = cats[i];
      var catDets = detailsMap[cat] || [];
      totalDetails += catDets.length;
      catDetBody += '<div class="pg-category-group" data-cat="' + _escAttr(cat) + '">';
      catDetBody += '<div class="pg-category-item">' +
        '<span class="pg-category-name">' + _esc(cat) + '</span>' +
        '<button class="pg-category-remove" title="Remove category">&times;</button>' +
      '</div>';
      if (catDets.length > 0) {
        catDetBody += '<div class="pg-details-sublist" data-cat="' + _escAttr(cat) + '">';
        for (var di = 0; di < catDets.length; di++) {
          catDetBody += '<div class="pg-detail-item" data-detail="' + _escAttr(catDets[di]) + '" data-parent-cat="' + _escAttr(cat) + '">' +
            '<span class="pg-detail-name">' + _esc(catDets[di]) + '</span>' +
            '<button class="pg-detail-remove" title="Remove detail">&times;</button>' +
          '</div>';
        }
        catDetBody += '</div>';
      }
      catDetBody += '<div class="pg-add-detail-row" data-cat="' + _escAttr(cat) + '">' +
        '<input type="text" placeholder="Add detail..." class="pg-add-input pg-add-detail-input" />' +
        '<button class="pg-add-detail-btn pg-add-btn">+</button>' +
      '</div>';
      catDetBody += '</div>';
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
    var matchedCount = _getMatchedItems().length;
    var filterBody = '';
    filterBody += '<div class="pg-filter-row">';
    filterBody += '<div class="pg-filter-group">';
    filterBody += '<label class="pg-filter-label">Max Score</label>';
    filterBody += '<div class="pg-slider-control">';
    filterBody += '<input type="range" id="pg-max-score" class="pg-score-slider" min="0" max="100" step="5" value="80" />';
    filterBody += '<span class="pg-slider-value" id="pg-max-score-value">80%</span>';
    filterBody += '</div>';
    filterBody += '</div>';
    filterBody += '<label class="pg-filter-check"><span class="custom-checkbox"><input type="checkbox" id="pg-skip-analyzed" checked /><span class="checkmark"></span></span><span>Skip analyzed</span></label>';
    filterBody += '<label class="pg-filter-check"><span class="custom-checkbox"><input type="checkbox" id="pg-allow-human-overwrite" /><span class="checkmark"></span></span><span>Re-analyze human labels</span></label>';
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
      '<button class="pg-toggle-expand" id="pg-preview-toggle" style="display:none;">Expand</button>' +
      '<button class="pg-copy-btn" id="pg-preview-copy" title="Copy prompt to clipboard">Copy</button>' +
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
      html += '<div class="pg-empty-msg">No items match current filters</div>';
      return html;
    }

    html += '<div class="pg-items-list">';
    for (var i = 0; i < matched.length; i++) {
      var r = matched[i];
      var scoreNum = r.metric_score;
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
      if (scoreNum != null) html += '<span class="pg-item-score pg-status-' + status + '">' + scoreStr + '</span>';
      html += '<span class="pg-status-badge pg-status-' + status + '">' + (status === 'none' ? 'no score' : status) + '</span>';
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

    return html;
  }

  // ── Build Config Payload ──

  function _buildConfigPayload() {
    var cfg = {};

    var descriptionEl = document.getElementById('pg-project-description');
    if (descriptionEl && descriptionEl.value.trim()) {
      cfg.project_description = descriptionEl.value.trim();
    }

    var rules = _readAnalysisRulesFromEditor();
    cfg.analysis_rules = rules;

    var selectedDocuments = _referenceDocuments.filter(function (document) { return document.selected !== false; });
    if (selectedDocuments.length > 0) {
      cfg.reference_documents = selectedDocuments.map(function (document) {
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
      var selectedCount = _referenceDocuments.filter(function (document) { return document.selected !== false; }).length;
      badge.textContent = selectedCount + ' selected';
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

  function _updateReferenceDocumentSelection(document) {
    var runId = _getRunId();
    if (!runId || !document.id) return Promise.reject(new Error('Could not identify the saved document.'));
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    return fetch(base('api/runs/' + runId + '/analysis-documents/' + encodeURIComponent(document.id)), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ selected: document.selected !== false }),
    }).then(function (response) {
      if (!response.ok) return response.text().then(function (text) { throw new Error(text || 'Selection update failed'); });
      return response.json();
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
        _setDocumentUploadStatus(added + ' document' + (added === 1 ? '' : 's') + ' saved to the project library and selected.' + (failed ? ' ' + failed + ' failed.' : ''), false);
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
    return rules.slice(0, 20);
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

  function _renderAnalysisRulesEditor() {
    var list = document.getElementById('pg-rule-list');
    if (list) list.innerHTML = _buildAnalysisRulesEditor();
    var selected = _ruleVersions.find(function (version) { return version.id === _selectedRuleVersionId; });
    var editable = !!selected && selected.status === 'draft';
    var addButton = document.getElementById('pg-add-rule');
    var saveButton = document.getElementById('pg-save-context');
    if (addButton) addButton.disabled = !editable;
    if (saveButton) saveButton.disabled = !editable;
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
          if (_config) _config.analysis_rules = _analysisRules;
          _renderAnalysisRulesEditor();
        }
        _renderRuleVersionHistory();
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
            : 'Rule version deleted. The latest available version is now active.'));
      _setContextStatus(message, false);
      _scheduleAutoPreview(0);
    }).catch(function (error) {
      _setContextStatus(error.message || 'Could not update rule version.', true);
    });
  }

  function _openRuleVersion(versionId) {
    var version = _ruleVersions.find(function (candidate) { return candidate.id === versionId; });
    if (!version) return;
    _selectedRuleVersionId = version.id;
    _analysisRules = (version.rules || []).slice();
    if (_config) _config.analysis_rules = _analysisRules;
    _renderAnalysisRulesEditor();
    _renderRuleVersionHistory();
    _setContextStatus(
      'Opened v' + version.version + (version.status === 'draft' ? ' draft.' : ' (read-only).'),
      false
    );
    _scheduleAutoPreview(0);
  }

  function _createRuleDraft() {
    var runId = _getRunId();
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    var selected = _ruleVersions.find(function (version) { return version.id === _selectedRuleVersionId; });
    var draftName = window.prompt('Optional name for the new draft:', '') || '';
    return fetch(base('api/runs/' + runId + '/analysis-rule-versions'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        from_version: selected ? String(selected.version) : null,
        name: draftName.trim(),
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

  function _publishRuleVersion(versionId) {
    var version = _ruleVersions.find(function (candidate) { return candidate.id === versionId; });
    if (!version) return Promise.resolve();
    if (!window.confirm('Publish v' + version.version + ' as an immutable snapshot? Future edits will require a new draft.')) {
      return Promise.resolve();
    }
    var setProduction = window.confirm('Set v' + version.version + ' as the production ruleset after publishing?');
    var runId = _getRunId();
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    return fetch(base('api/runs/' + runId + '/analysis-rule-versions/' + encodeURIComponent(String(version.version)) + ':publish'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ set_alias: setProduction ? 'production' : null }),
    }).then(function (response) {
      if (!response.ok) return response.json().then(function (data) { throw new Error(data.detail || 'Could not publish rule version'); });
      return response.json();
    }).then(function () {
      return _refreshRuleVersions(true);
    }).then(function () {
      _setContextStatus(
        'Published v' + version.version + (setProduction ? ' and set it as production.' : '.'),
        false
      );
    });
  }

  function _compareRuleVersion(versionId) {
    var version = _ruleVersions.find(function (candidate) { return candidate.id === versionId; });
    var parent = version && _ruleVersions.find(function (candidate) { return candidate.id === version.parent_version_id; });
    if (!version || !parent) return;
    var runId = _getRunId();
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    fetch(base('api/runs/' + runId + '/analysis-rule-versions/' + encodeURIComponent(String(version.version)) + ':compare?base=' + encodeURIComponent(String(parent.version))))
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
          compare.innerHTML = '<div class="pg-rule-compare-header"><div><span class="pg-rule-compare-eyebrow">Comparison</span><strong>v' + _esc(String(parent.version)) + ' → v' + _esc(String(version.version)) + '</strong></div><button class="pg-rule-action" type="button" data-close-rule-compare>Close</button></div>' +
            '<div class="pg-rule-compare-stats"><span><strong>' + (summary.changed || 0) + '</strong> changed</span><span><strong>' + (summary.added || 0) + '</strong> added</span><span><strong>' + (summary.removed || 0) + '</strong> removed</span><span><strong>' + (summary.unchanged || 0) + '</strong> unchanged</span></div>' +
            (sections || '<div class="pg-rule-version-meta">No rule content changed.</div>');
          compare.hidden = false;
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
      });
  }

  function _setContextStatus(message, isError) {
    var status = document.getElementById('pg-context-status');
    if (!status) return;
    status.textContent = message || '';
    status.classList.toggle('pg-context-status-error', !!isError);
  }

  function _saveAnalysisContext(createNewVersion) {
    if (!_validateProjectDescription()) return Promise.reject(new Error('Project description is required'));
    if (!_validateAnalysisRuleDrafts()) return Promise.reject(new Error('Every rule requires a title and instruction'));
    var runId = _getRunId();
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    var descriptionEl = document.getElementById('pg-project-description');
    var payload = {
      project_description: descriptionEl ? descriptionEl.value.trim() : '',
      analysis_rules: _readAnalysisRulesFromEditor(),
      create_new_version: !!createNewVersion,
      rule_version_id: _selectedRuleVersionId,
    };
    _setContextStatus(createNewVersion ? 'Creating a new rule version…' : 'Saving project context…', false);
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
        _config.project_description = data.project_description || '';
        _config.analysis_rules = _analysisRules;
      }
      _renderAnalysisRulesEditor();
      return _refreshRuleVersions(false).then(function () {
        _setContextStatus(
          createNewVersion
            ? 'Created draft v' + data.rule_version.version + '.'
            : 'Saved draft v' + data.rule_version.version + '.',
          false
        );
        return data;
      });
    }).then(function (data) {
      _scheduleAutoPreview(0);
      return data;
    }).catch(function (error) {
      _setContextStatus(error.message || 'Could not save project context.', true);
      throw error;
    });
  }

  function _inferAnalysisRules() {
    if (!_validateProjectDescription()) return;
    var runId = _getRunId();
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    var descriptionEl = document.getElementById('pg-project-description');
    var useDescriptionEl = document.getElementById('pg-infer-use-description');
    var useDocumentsEl = document.getElementById('pg-infer-use-documents');
    var useExamplesEl = document.getElementById('pg-infer-use-examples');
    var inferenceSources = {
      include_project_description: !useDescriptionEl || useDescriptionEl.checked,
      include_documents: !useDocumentsEl || useDocumentsEl.checked,
      include_examples: !useExamplesEl || useExamplesEl.checked,
    };
    if (!inferenceSources.include_project_description && !inferenceSources.include_documents && !inferenceSources.include_examples) {
      _setContextStatus('Select at least one source before generating rules.', true);
      return;
    }
    var button = document.getElementById('pg-infer-rules');
    if (button) {
      button.disabled = true;
      button.textContent = 'Inferring…';
    }
    _setContextStatus('Reading the selected inference sources…', false);
    fetch(base('api/runs/' + runId + '/analysis-rules/infer'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project_description: descriptionEl ? descriptionEl.value.trim() : '',
        include_project_description: inferenceSources.include_project_description,
        include_documents: inferenceSources.include_documents,
        include_examples: inferenceSources.include_examples,
        connection_id: _connectionId,
      }),
    }).then(function (response) {
      if (!response.ok) return response.json().then(function (data) { throw new Error(data.detail || 'Could not generate rules'); });
      return response.json();
    }).then(function (data) {
      _analysisRules = data.analysis_rules || [];
      _selectedRuleVersionId = data.rule_version && data.rule_version.id;
      if (_config) {
        _config.project_description = data.project_description || '';
        _config.analysis_rules = _analysisRules;
      }
      _renderAnalysisRulesEditor();
      return _refreshRuleVersions(false).then(function () {
        _setContextStatus('Generated ' + _analysisRules.length + ' rules in draft v' + data.rule_version.version + ' from ' + data.documents_used + ' documents and ' + data.examples_used + ' approved examples. Review and publish the draft to use it in production.', false);
        _scheduleAutoPreview(0);
      });
    }).catch(function (error) {
      _setContextStatus(error.message || 'Could not generate rules.', true);
      if (_opts.showToast) _opts.showToast('error', 'Rule Generation Failed', error.message);
    }).finally(function () {
      if (button) {
        button.disabled = false;
        button.textContent = 'Generate rules';
      }
    });
  }

  // ── Wire all events ──

  function _wireEvents() {
    var descriptionEl = document.getElementById('pg-project-description');
    if (descriptionEl) {
      descriptionEl.addEventListener('input', function () {
        descriptionEl.classList.remove('pg-field-invalid');
        _syncActionAvailability();
        _scheduleAutoPreview();
      });
    }
    var ruleList = document.getElementById('pg-rule-list');
    if (ruleList) {
      ruleList.addEventListener('input', function (event) {
        if (event.target) event.target.classList.remove('pg-field-invalid');
        _analysisRules = _readAnalysisRuleDraftsFromEditor();
        _scheduleAutoPreview();
      });
      ruleList.addEventListener('click', function (event) {
        var remove = event.target.closest('.pg-rule-remove');
        if (!remove) return;
        _analysisRules = _readAnalysisRuleDraftsFromEditor();
        var index = parseInt(remove.dataset.ruleIndex, 10);
        if (Number.isNaN(index)) return;
        _analysisRules.splice(index, 1);
        _renderAnalysisRulesEditor();
        _setRuleEditorBusy(true);
        _setContextStatus('Removing rule from the current version…', false);
        _saveAnalysisContext().catch(function () {
          _setContextStatus('The rule was removed locally but could not be saved. Retry Save context before refreshing.', true);
        }).finally(function () {
          _setRuleEditorBusy(false);
        });
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
      if (_analysisRules.length >= 20) {
        _setContextStatus('A project can have at most 20 analysis rules.', true);
        return;
      }
      _analysisRules.push({ title: '', instruction: '' });
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
      createRuleVersion.disabled = true;
      _createRuleDraft().catch(function (error) {
        _setContextStatus(error.message || 'Could not create rule draft.', true);
      }).finally(function () { createRuleVersion.disabled = false; });
    });
    var inferRules = document.getElementById('pg-infer-rules');
    if (inferRules) inferRules.addEventListener('click', _inferAnalysisRules);
    var ruleVersionList = document.getElementById('pg-rule-version-list');
    if (ruleVersionList) ruleVersionList.addEventListener('click', function (event) {
      var open = event.target.closest('[data-open-rule-version]');
      var activate = event.target.closest('[data-activate-rule-version]');
      var publish = event.target.closest('[data-publish-rule-version]');
      var compare = event.target.closest('[data-compare-rule-version]');
      if (open) _openRuleVersion(open.dataset.openRuleVersion);
      if (activate) _changeRuleVersion(activate.dataset.activateRuleVersion, 'activate');
      if (publish) _publishRuleVersion(publish.dataset.publishRuleVersion).catch(function (error) {
        _setContextStatus(error.message || 'Could not publish rule version.', true);
      });
      if (compare) _compareRuleVersion(compare.dataset.compareRuleVersion);
    });
    var ruleVersionCompare = document.getElementById('pg-rule-version-compare');
    if (ruleVersionCompare) ruleVersionCompare.addEventListener('click', function (event) {
      if (event.target.closest('[data-close-rule-compare]')) {
        ruleVersionCompare.hidden = true;
      }
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
        var checkbox = event.target.closest('.pg-document-select');
        if (!checkbox) return;
        var index = parseInt(checkbox.dataset.documentIndex, 10);
        if (Number.isNaN(index) || index < 0 || index >= _referenceDocuments.length) return;
        var document = _referenceDocuments[index];
        var previous = document.selected !== false;
        document.selected = checkbox.checked;
        _renderReferenceDocuments();
        _updateReferenceDocumentSelection(document).then(function () {
          _setDocumentUploadStatus(document.name + (document.selected ? ' selected for analyzer runs.' : ' kept in the library but not selected.'), false);
          _scheduleAutoPreview(0);
        }).catch(function (error) {
          document.selected = previous;
          _renderReferenceDocuments();
          _setDocumentUploadStatus('Could not save the document selection.', true);
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
          }
          var div = document.createElement('div');
          div.className = 'pg-detail-item';
          div.dataset.detail = val;
          div.dataset.parentCat = parentCat;
          div.innerHTML = '<span class="pg-detail-name">' + _esc(val) + '</span>' +
            '<button class="pg-detail-remove" title="Remove detail">&times;</button>';
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
        var group = document.createElement('div');
        group.className = 'pg-category-group';
        group.dataset.cat = val;
        group.innerHTML = '<div class="pg-category-item">' +
          '<span class="pg-category-name">' + _esc(val) + '</span>' +
          '<button class="pg-category-remove" title="Remove category">&times;</button>' +
        '</div>' +
        '<div class="pg-add-detail-row" data-cat="' + _escAttr(val) + '">' +
          '<input type="text" placeholder="Add detail..." class="pg-add-input pg-add-detail-input" />' +
          '<button class="pg-add-detail-btn pg-add-btn">+</button>' +
        '</div>';
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

    // Copy prompt button
    var copyBtn = document.getElementById('pg-preview-copy');
    if (copyBtn) copyBtn.addEventListener('click', function () {
      var content = document.getElementById('pg-preview-content');
      if (!content) return;
      var text = content.innerText || content.textContent || '';
      navigator.clipboard.writeText(text).then(function () {
        copyBtn.textContent = 'Copied!';
        setTimeout(function () { copyBtn.textContent = 'Copy'; }, 1500);
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
    if (filterBadge) filterBadge.textContent = String(matched.length);
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

  function _hasProjectDescription() {
    var descriptionEl = document.getElementById('pg-project-description');
    return !!(descriptionEl && descriptionEl.value.trim());
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
      _hasProjectDescription() &&
      _documentUploadsInFlight === 0 &&
      metricsReady
    );
    if (runAllBtn) {
      runAllBtn.textContent = 'Analyze failures (' + matched.length + ' items)';
      runAllBtn.disabled = !ready || matched.length === 0 || _running;
    }
    if (testBtn) testBtn.disabled = !ready || _running;
  }

  function _validateProjectDescription() {
    if (_hasProjectDescription()) return true;
    var descriptionEl = document.getElementById('pg-project-description');
    if (descriptionEl) {
      descriptionEl.classList.add('pg-field-invalid');
      descriptionEl.focus();
    }
    if (_opts.showToast) {
      _opts.showToast('warning', 'Project Description Required', 'Describe the project before testing or running the analyzer.');
    }
    return false;
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
      if (!_hasProjectDescription()) {
        if (content) content.textContent = 'Enter the project description above to generate a prompt preview.';
        if (toggleBtn) toggleBtn.style.display = 'none';
        if (loading) loading.style.display = 'none';
        return;
      }

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
    if (!_validateProjectDescription()) return;

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
    if (!_validateProjectDescription()) return;
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
