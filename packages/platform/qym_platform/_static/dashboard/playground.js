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
  var _CATEGORY_PAGE_SIZE = 10;
  var _categoryNavigationQuery = '';
  var _selectedTarget = null;
  var _customVars = [];
  var _configUnlocked = false;
  var _DEFAULT_MAX_ROOT_CAUSE_CATEGORIES = 3;
  var _MAX_ROOT_CAUSE_CATEGORIES = 10;
  var _referenceDocuments = [];
  var _selectedApprovedExampleIds = new Set();
  var _selectedApprovedExampleFields = new Set();
  var _selectedApprovedExampleCharacters = 0;
  var _approvedExampleCharacterById = {};
  var _examplePickerOverlay = null;
  var _examplePickerState = null;
  var _examplePickerOpener = null;
  var _analysisRules = [];
  var _analysisRulesPage = 1;
  var _RULES_PAGE_SIZE = 10;
  var _editingRuleIndex = null;
  var _analysisRuleSearch = '';
  var _ruleVersions = [];
  var _selectedRuleVersionId = null;
  var _canDeleteRuleVersions = false;
  var _canActivateRuleVersions = false;
  var _canRestoreRuleVersions = false;
  var _documentUploadsInFlight = 0;
  var _contextFeedbackTimer = null;
  var _analysisRuleSaveTimer = null;
  var _ruleCompareOriginalParent = null;
  var _ruleCompareOriginalNextSibling = null;
  var _analysisJobId = null;
  var _analysisPollTimer = null;
  var _analysisPollGeneration = 0;
  var _analysisCancelRequested = false;

  // Keep the examples picker on the same field-toggle convention used by
  // Variable Mapping. These are the fields already projected into the writer
  // payload; no separate field-discovery request is needed.
  var _APPROVED_EXAMPLE_FIELD_DEFINITIONS = [
    { key: 'input', label: 'Input' },
    { key: 'expected', label: 'Expected output' },
    { key: 'output', label: 'Actual output' },
    { key: 'previous_ai_root_cause', label: 'Previous AI root cause' },
    { key: 'previous_ai_root_causes', label: 'Previous AI root causes' },
    { key: 'approved_root_cause', label: 'Approved root cause' },
    { key: 'approved_root_causes', label: 'Approved root causes' },
    { key: 'approved_detail', label: 'Approved detail' },
    { key: 'reviewer_reasoning', label: 'Reviewer reasoning' },
  ];

  function _approvedExampleFieldKeys() {
    return _APPROVED_EXAMPLE_FIELD_DEFINITIONS.map(function (field) { return field.key; });
  }

  function _approvedExampleFieldMap(fields) {
    var selected = fields || _selectedApprovedExampleFields;
    var result = {};
    _approvedExampleFieldKeys().forEach(function (key) {
      result[key] = selected.has(key);
    });
    return result;
  }

  function _analysisProgressNodes() {
    return {
      progress: document.getElementById('pg-runall-progress'),
      fill: document.getElementById('pg-runall-progress-fill'),
      progressText: document.getElementById('pg-runall-progress-text'),
      subtext: document.getElementById('pg-runall-progress-subtext'),
      button: document.getElementById('pg-runall-btn'),
    };
  }

  function _analysisCategoryCount(data) {
    var categories = data && data.categories;
    if (Array.isArray(categories)) return categories.length;
    if (!categories || typeof categories !== 'object') return 0;
    return Object.keys(categories).length;
  }

  function _runLinkMarkup() {
    var href = _opts.getRunUrl ? _opts.getRunUrl() : '';
    if (!href) return '';
    return '<a class="qym-inline-action qym-inline-action--neutral pg-runall-open-run" href="' + _escAttr(href) +
      '">View run</a>';
  }

  function _updateAnalysisProgress(progressState) {
    var nodes = _analysisProgressNodes();
    var state = progressState || {};
    var total = Number(state.total || 0);
    var completed = Number(state.completed || 0);
    var errors = Number(state.errors || 0);
    var pct = total > 0 ? Math.round((completed / total) * 100) : 0;
    if (nodes.progress) nodes.progress.style.display = 'block';
    if (nodes.fill) {
      nodes.fill.style.transition = 'width 0.25s ease-out';
      nodes.fill.style.width = pct + '%';
      if (state.phase !== 'failed') nodes.fill.style.background = '';
    }
    if (state.phase === 'aggregating') {
      if (nodes.button) nodes.button.textContent = 'Aggregating…';
      if (nodes.progressText) nodes.progressText.textContent = 'Aggregating root causes…';
      if (nodes.subtext) {
        nodes.subtext.textContent = 'Analysis complete. Consolidating related categories, details, and solutions.' +
          (errors > 0 ? ' Errors: ' + errors : '');
      }
      return;
    }
    if (nodes.button) nodes.button.textContent = 'Analyzing…';
    if (nodes.progressText) {
      nodes.progressText.textContent = total > 0
        ? 'Analyzing metric failures: ' + completed + '/' + total + ' (' + pct + '%)'
        : 'Preparing analysis…';
    }
    if (nodes.subtext) {
      var itemText = state.item_id
        ? 'Last: ' + String(state.item_id).slice(0, 32) + (state.metric_name ? ' · ' + state.metric_name : '')
        : 'Running in the background. You can leave this page and return later.';
      nodes.subtext.textContent = itemText + (errors > 0 ? ' | Errors: ' + errors : '');
    }
  }

  function _finishRunAll(data) {
    data = data || {};
    var nodes = _analysisProgressNodes();
    var analyzed = Number(data.total_analyzed || 0);
    var categoryCount = _analysisCategoryCount(data);
    var categoryLabel = categoryCount === 1 ? 'category' : 'categories';
    var aggregationError = String(data.aggregation_error || '').trim();
    var runLink = _runLinkMarkup();
    var completionText = analyzed > 0
      ? 'Analyzed <strong>' + analyzed + '</strong> metric failures successfully'
      : 'Existing root-cause analysis checked successfully';
    if (!aggregationError) {
      completionText += '<div>Created <strong>' + categoryCount + '</strong> ' + categoryLabel + '</div>';
    }
    if (nodes.fill) {
      nodes.fill.style.transition = 'width 0.3s ease-out';
      nodes.fill.style.width = '100%';
    }
    if (nodes.progressText) {
      nodes.progressText.textContent = aggregationError
        ? 'Analysis saved; aggregation failed'
        : 'Analysis Complete!';
    }
    if (nodes.subtext) {
      nodes.subtext.textContent = aggregationError
        ? 'Raw diagnoses were saved without consolidation. You can retry from the run page.'
        : 'Finalizing results...';
    }
    var resultsEl = document.getElementById('pg-runall-results');
    if (resultsEl) {
      resultsEl.innerHTML = '<div class="pg-runall-done' + (aggregationError ? ' pg-runall-partial' : '') + '">' +
        '<div class="pg-runall-done-icon">' + (aggregationError ? '⚠️' : '✨') + '</div>' +
        '<div class="pg-runall-done-text">' + completionText +
        (data.errors > 0 ? '<div class="pg-runall-done-error">⚠️ ' + data.errors + ' metric analyses failed</div>' : '') +
        (aggregationError ? '<div class="pg-runall-aggregation-error">Aggregation failed: ' + _esc(aggregationError) + '</div>' : '') +
        '</div>' +
        (runLink ? '<div class="pg-runall-done-actions">' + runLink + '</div>' : '') +
        '</div></div>';
    }
    if (_opts.showToast) {
      if (aggregationError) {
        _opts.showToast('error', 'Aggregation Failed', 'Analysis was saved without label consolidation.');
      } else {
        var toastText = analyzed + ' metric failures analyzed';
        toastText += ' · Created ' + categoryCount + ' ' + categoryLabel;
        _opts.showToast('success', 'Analysis Complete', toastText);
      }
    }
    if (_opts.onAnalysisComplete) _opts.onAnalysisComplete(data);
    _onFilterChange();
    setTimeout(function () {
      if (nodes.progress) nodes.progress.style.display = 'none';
    }, 3000);
  }

  function _showAnalysisFailure(message) {
    var nodes = _analysisProgressNodes();
    var errorMessage = message || 'An error occurred during analysis.';
    if (nodes.progress) nodes.progress.style.display = 'block';
    if (nodes.progressText) nodes.progressText.textContent = 'Analysis failed';
    if (nodes.subtext) nodes.subtext.textContent = errorMessage;
    if (nodes.fill) {
      nodes.fill.style.transition = 'width 0.3s ease-out';
      nodes.fill.style.width = '0%';
      nodes.fill.style.background = 'var(--error)';
    }
    if (_opts.showToast) _opts.showToast('error', 'Analysis Failed', errorMessage);
  }

  function _showAnalysisCancelled() {
    var nodes = _analysisProgressNodes();
    if (nodes.progress) nodes.progress.style.display = 'block';
    if (nodes.progressText) nodes.progressText.textContent = 'Analysis cancelled';
    if (nodes.subtext) nodes.subtext.textContent = 'No further analysis requests will run.';
    if (nodes.fill) {
      nodes.fill.style.transition = 'width 0.3s ease-out';
      nodes.fill.style.background = 'var(--warning)';
    }
    if (_opts.showToast) _opts.showToast('warning', 'Analysis Cancelled', 'The background analysis was stopped.');
  }

  function _pollAnalysisJob(job, generation) {
    if (!job || !job.job_id || generation !== _analysisPollGeneration) return;
    _analysisJobId = job.job_id;
    _analysisCancelRequested = job.status === 'cancelling' || !!job.cancel_requested;
    _running = true;
    _updateAnalysisProgress(job.progress);
    _syncActionAvailability();
    if (job.status === 'completed') {
      _analysisJobId = null;
      _analysisCancelRequested = false;
      _running = false;
      _finishRunAll(job.result || {});
      _syncActionAvailability();
      return;
    }
    if (job.status === 'cancelled') {
      _analysisJobId = null;
      _analysisCancelRequested = false;
      _running = false;
      _showAnalysisCancelled();
      _syncActionAvailability();
      return;
    }
    if (job.status === 'failed') {
      _analysisJobId = null;
      _analysisCancelRequested = false;
      _running = false;
      _showAnalysisFailure(job.error || 'An error occurred during analysis.');
      _syncActionAvailability();
      return;
    }
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    _analysisPollTimer = setTimeout(function () {
      fetch(base(_analysisJobsPath(encodeURIComponent(job.job_id))))
        .then(function (response) {
          if (!response.ok) throw new Error('Analysis status: HTTP ' + response.status);
          return response.json();
        })
        .then(function (nextJob) { _pollAnalysisJob(nextJob, generation); })
        .catch(function (error) {
          if (generation !== _analysisPollGeneration) return;
          var nodes = _analysisProgressNodes();
          if (nodes.subtext) nodes.subtext.textContent = 'Reconnecting to background analysis…';
          _analysisPollTimer = setTimeout(function () {
            _pollAnalysisJob(job, generation);
          }, 1000);
          console.warn('Analysis status polling interrupted:', error.message);
        });
    }, 600);
  }

  function _resumeActiveAnalysis() {
    if (!_getRunId()) return;
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    var generation = ++_analysisPollGeneration;
    var activePath = _analysisJobsPath('active');
    var passNumber = _opts.getPassNumber ? _opts.getPassNumber() : null;
    if (passNumber != null) activePath += '?pass_number=' + encodeURIComponent(passNumber);
    fetch(base(activePath))
      .then(function (response) {
        if (!response.ok) throw new Error('Active analysis: HTTP ' + response.status);
        return response.json();
      })
      .then(function (data) {
        if (generation !== _analysisPollGeneration || !data || !data.job) return;
        _pollAnalysisJob(data.job, generation);
      })
      .catch(function (error) {
        console.warn('Could not resume background analysis:', error.message);
      });
  }

  function _cancelAnalysis() {
    if (!_analysisJobId || _analysisCancelRequested) return;
    var jobId = _analysisJobId;
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    _analysisCancelRequested = true;
    _syncActionAvailability();
    fetch(base(_analysisJobsPath(encodeURIComponent(jobId) + '/cancel')), { method: 'POST' })
      .then(function (response) {
        if (!response.ok) throw new Error('Cancel analysis: HTTP ' + response.status);
        return response.json();
      })
      .then(function (job) { _pollAnalysisJob(job, _analysisPollGeneration); })
      .catch(function (error) {
        _analysisCancelRequested = false;
        _syncActionAvailability();
        if (_opts.showToast) _opts.showToast('error', 'Cancellation Failed', error.message);
      });
  }

  function _runAll(skipHumanConfirmation) {
    if (_running) return;
    if (!skipHumanConfirmation) {
      var humanOverwriteEl = document.getElementById('pg-allow-human-overwrite');
      if (humanOverwriteEl && humanOverwriteEl.checked) {
        var humanTargets = _getHumanOverwriteTargets(_getMatchedItems());
        if (humanTargets.length > 0) {
          _running = true;
          _confirmHumanOverwrite(humanTargets).then(function (confirmed) {
            _running = false;
            if (confirmed) _runAll(true);
            else _updateFooterCount();
          }, function (error) {
            _running = false;
            if (_opts.showToast) _opts.showToast('error', 'Confirmation failed', error.message || 'Human labels were not overwritten.');
            _updateFooterCount();
          });
          return;
        }
      }
    }

    var runId = _getRunId();
    if (!runId) return;
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
    var requestedLimit = _getTargetLimit();
    if (requestedLimit != null && requestedLimit > 0) body.limit = requestedLimit;
    if (_opts.getMetrics) {
      body.metric = null;
      body.metrics = _getSelectedMetrics();
    }
    if (_opts.getPassNumber) {
      var passNumber = _opts.getPassNumber();
      if (passNumber != null) body.pass_number = Number(passNumber);
    }

    _running = true;
    _analysisCancelRequested = false;
    var nodes = _analysisProgressNodes();
    if (nodes.button) { nodes.button.disabled = true; nodes.button.textContent = 'Starting…'; }
    if (nodes.progress) nodes.progress.style.display = 'block';
    if (nodes.fill) {
      nodes.fill.style.transition = 'none';
      nodes.fill.style.width = '0%';
      nodes.fill.style.background = '';
      void nodes.fill.offsetWidth;
      nodes.fill.style.transition = 'width 0.25s ease-out';
    }
    if (nodes.progressText) nodes.progressText.textContent = 'Preparing analysis…';
    if (nodes.subtext) nodes.subtext.textContent = 'Starting a background analysis job…';
    _syncActionAvailability();

    var generation = ++_analysisPollGeneration;
    fetch(base(_analysisJobsPath()), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (data) {
          if (!response.ok) throw new Error(data.detail || 'Analysis failed');
          if (!data.job_id) throw new Error('Analysis did not return a job id.');
          return data;
        });
      })
      .then(function (job) { _pollAnalysisJob(job, generation); })
      .catch(function (error) {
        if (generation !== _analysisPollGeneration) return;
        _analysisJobId = null;
        _analysisCancelRequested = false;
        _running = false;
        _showAnalysisFailure(error.message);
        _syncActionAvailability();
      });
  }

  // ── Public API ──

  function init(opts) {
    if (_analysisPollTimer) clearTimeout(_analysisPollTimer);
    if (_analysisRuleSaveTimer) clearTimeout(_analysisRuleSaveTimer);
    _analysisPollGeneration += 1;
    _analysisPollTimer = null;
    _analysisRuleSaveTimer = null;
    _analysisJobId = null;
    _analysisCancelRequested = false;
    _running = false;
    _opts = opts || {};
  }

  function open() {
    if (_overlay) {
      _overlay.style.display = _opts.dedicatedPage ? 'block' : 'flex';
      return Promise.resolve();
    }
    return _fetchConfigAndOpen();
  }

  function close() {
    // Dedicated-page mode owns the page root; it is not a dismissible modal.
    if (_opts.dedicatedPage) return;
    if (_opts.onClose) {
      _opts.onClose();
      return;
    }
    if (_overlay) _overlay.style.display = 'none';
  }

  // ── Fetch analyzer configuration then build modal ──

  function _fetchConfigAndOpen() {
    if (!_hasAnalysisContext()) {
      return Promise.reject(new Error('Could not determine the analysis context.'));
    }
    var base = _opts.apiUrl || function (p) { return '/' + p; };

    return Promise.all([
      fetch(base(_analysisContextPath('analysis-config'))).then(function (r) { if (!r.ok) throw new Error('Config: HTTP ' + r.status); return r.json(); }),
      fetch(base(_analysisContextPath('analysis-documents'))).then(function (r) { if (!r.ok) throw new Error('Documents: HTTP ' + r.status); return r.json(); }),
      fetch(base(_analysisContextPath('analysis-rule-versions?include_deleted=true'))).then(function (r) { if (!r.ok) throw new Error('Rule versions: HTTP ' + r.status); return r.json(); }),
    ]).then(function (results) {
      _config = results[0];
      var _conns = (_config && _config.llm_connections) || [];
      _connectionId = (_config && _config.default_connection_id) || (_conns[0] && _conns[0].id) || null;
      _testResults = [];
      _matchedPage = 0;
      _selectedTarget = null;
      _customVars = [];
      _configUnlocked = true;
      _referenceDocuments = (results[1] && results[1].documents) || [];
      _selectedApprovedExampleIds = new Set();
      _selectedApprovedExampleFields = new Set(_approvedExampleFieldKeys());
      _selectedApprovedExampleCharacters = 0;
      _approvedExampleCharacterById = {};
      _examplePickerOverlay = null;
      _examplePickerState = null;
      _analysisRules = (_config && _config.analysis_rules) || [];
      _analysisRuleSearch = '';
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
      _overlay.style.display = _opts.dedicatedPage ? 'block' : 'flex';
      _resumeActiveAnalysis();
    }).catch(function (err) {
      console.error('Playground: failed to load config', err);
      if (_opts.showToast) _opts.showToast('error', 'Playground Error', 'Failed to load configuration');
      throw err;
    });
  }

  // ── Helpers ──

  function _getRunId() { return _opts.getRunId ? _opts.getRunId() : null; }

  function _hasAnalysisContext() {
    return !!_getRunId() || !!(_opts.projectScoped && _opts.projectSlug);
  }

  function _analysisContextPath(suffix) {
    if (_opts.projectScoped && _opts.projectSlug) {
      return 'api/projects/' + encodeURIComponent(_opts.projectSlug) + '/' + suffix;
    }
    return 'api/runs/' + _getRunId() + '/' + suffix;
  }

  function _analysisJobsPath(suffix) {
    var path = _analysisContextPath('analysis-jobs');
    return suffix ? path + '/' + suffix : path;
  }

  function _getSelectedMetrics() {
    if (_opts.getMetrics) {
      var selected = _opts.getMetrics();
      return Array.isArray(selected) ? selected : [];
    }
    var metric = _opts.getMetric ? _opts.getMetric() : null;
    return metric ? [metric] : null;
  }

  function _getPrimaryMetric(row) {
    var metricNames = row && Array.isArray(row._matched_metric_names)
      ? row._matched_metric_names : [];
    return metricNames[0] || '';
  }

  function _targetFromRow(row) {
    if (!row || row.item_id == null) return null;
    var metricName = _getPrimaryMetric(row);
    return { item_id: row.item_id, metric_name: metricName || null };
  }

  function _targetMatchesRow(target, row) {
    if (!target || !row || target.item_id == null || row.item_id == null) return false;
    return String(target.item_id) === String(row.item_id) &&
      String(target.metric_name || '') === String(_getPrimaryMetric(row) || '');
  }

  function _resolveSelectedTarget(matchedItems) {
    var matched = Array.isArray(matchedItems) ? matchedItems : [];
    if (_selectedTarget && matched.some(function (row) {
      return _targetMatchesRow(_selectedTarget, row);
    })) {
      return _selectedTarget;
    }
    _selectedTarget = matched.length > 0 ? _targetFromRow(matched[0]) : null;
    return _selectedTarget;
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

  function _rootCauseCategories(value) {
    var raw = value;
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      if (Object.prototype.hasOwnProperty.call(value, 'root_causes')) raw = value.root_causes;
      else if (Object.prototype.hasOwnProperty.call(value, 'root_cause_categories')) raw = value.root_cause_categories;
      else raw = value.root_cause;
    }
    var values = Array.isArray(raw) ? raw : (raw ? [raw] : []);
    var seen = {};
    return values.map(function (item) { return String(item || '').trim(); }).filter(function (item) {
      var key = item.toLocaleLowerCase();
      if (!item || seen[key]) return false;
      seen[key] = true;
      return true;
    });
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

  function _categoryTaxonomyFor(taxonomy, category) {
    var map = taxonomy && typeof taxonomy === 'object' ? taxonomy : {};
    var key = String(category || '').toLowerCase();
    var match = Object.keys(map).find(function (candidate) {
      return String(candidate || '').toLowerCase() === key;
    });
    var entry = match ? map[match] : null;
    return entry && typeof entry === 'object' ? entry : {};
  }

  function _categoryDomKey(category) {
    var encoded = encodeURIComponent(String(category || '').trim())
      .replace(/%/g, '-')
      .replace(/[^A-Za-z0-9_-]/g, '-');
    return encoded || 'category';
  }

  function _uniqueCategoryDomKey(category) {
    var base = 'category-' + _categoryDomKey(category);
    var used = _categoryGroups().map(function (group) { return group.dataset.categoryKey || ''; });
    var candidate = base;
    var suffix = 2;
    while (used.indexOf(candidate) !== -1) {
      candidate = base + '-' + suffix;
      suffix += 1;
    }
    return candidate;
  }

  function _detailExampleCount(examples, detail) {
    var normalized = String(detail || '').trim().toLocaleLowerCase();
    if (!normalized) return 0;
    return (Array.isArray(examples) ? examples : []).filter(function (example) {
      return String((example && example.detail) || '').trim().toLocaleLowerCase() === normalized;
    }).length;
  }

  function _detailCountLabel(count) {
    return count + (count === 1 ? ' example' : ' examples');
  }

  function _buildCategoryDetailItems(category, details, examples) {
    var catDetails = Array.isArray(details) ? details : [];
    return catDetails.map(function (detail) {
      var count = _detailExampleCount(examples, detail);
      return '<div class="pg-detail-item" data-detail="' + _escAttr(detail) + '" data-detail-example-count="' + count + '" data-parent-cat="' + _escAttr(category) + '">' +
        '<span class="pg-detail-copy"><span class="pg-detail-name" dir="auto">' + _esc(detail) + '</span>' +
          '<span class="qym-tag qym-tag--count pg-detail-example-count">' + _detailCountLabel(count) + '</span></span>' +
        '<button class="pg-detail-remove qym-icon-action" type="button" title="Remove detail" aria-label="Remove ' + _escAttr(detail) + ' detail">' + _icon('close') + '</button>' +
      '</div>';
    }).join('');
  }

  function _categoryTabMarkup(category, categoryKey, tab, label, countLabel) {
    var tabId = 'pg-category-' + categoryKey + '-' + tab + '-tab';
    var panelId = 'pg-category-' + categoryKey + '-' + tab + '-panel';
    return '<button class="pg-category-tab qym-tabs__tab" id="' + tabId + '" type="button" role="tab" data-category-tab="' + tab + '"' +
      ' aria-selected="' + (tab === 'guidance' ? 'true' : 'false') + '" aria-controls="' + panelId + '" tabindex="' + (tab === 'guidance' ? '0' : '-1') + '">' +
      _esc(label) + (countLabel ? '<span class="qym-tag qym-tag--count pg-category-tab-count">' + _esc(countLabel) + '</span>' : '') + '</button>';
  }

  function _buildCategoryGroup(category, details, examples, taxonomy, categoryKey) {
    var cat = String(category || '').trim();
    var catDetails = Array.isArray(details) ? details : [];
    var catExamples = Array.isArray(examples) ? examples : [];
    var catTaxonomy = _categoryTaxonomyFor(taxonomy, cat);
    var domKey = categoryKey || _categoryDomKey(cat);
    var guidancePanelId = 'pg-category-' + domKey + '-guidance-panel';
    var detailsPanelId = 'pg-category-' + domKey + '-details-panel';
    var examplesPanelId = 'pg-category-' + domKey + '-examples-panel';
    var html = '<article class="pg-category-group" data-cat="' + _escAttr(cat) + '" data-category-key="' + _escAttr(domKey) + '" data-example-count="' + catExamples.length + '" hidden aria-hidden="true">';
    html += '<div class="pg-category-panel-heading">' +
      '<div class="pg-category-panel-copy"><h3 class="pg-category-panel-name" dir="auto">' + _esc(cat) + '</h3></div>' +
    '</div>';
    html += '<div class="pg-category-tabs-row">' +
      '<div class="pg-category-tabs qym-tabs" role="tablist" aria-label="Edit ' + _escAttr(cat) + ' category">' +
      _categoryTabMarkup(cat, domKey, 'guidance', 'Guidance') +
      _categoryTabMarkup(cat, domKey, 'details', 'Details', String(catDetails.length)) +
      _categoryTabMarkup(cat, domKey, 'examples', 'Examples', String(catExamples.length)) +
      '</div>' +
      '<div class="pg-category-panel-actions">' +
        '<button class="pg-category-remove qym-icon-action qym-icon-action--danger" type="button" title="Remove category from this analysis" aria-label="Remove ' + _escAttr(cat) + ' category from this analysis">' + _icon('trash') + '</button>' +
      '</div>' +
    '</div>';
    html += '<div class="pg-category-content">';
    html += '<section class="pg-category-tab-panel pg-category-taxonomy" id="' + guidancePanelId + '" data-category-panel="guidance" role="tabpanel" aria-labelledby="pg-category-' + domKey + '-guidance-tab">' +
      '<h4>Category guidance</h4><p class="pg-category-taxonomy-hint">Define the meaning of this label and the signal that should trigger it. Both fields are required.</p>' +
      '<label class="pg-category-taxonomy-field"><span>Description <abbr title="Required" aria-label="Required">*</abbr></span><textarea data-taxonomy-field="description" rows="3" placeholder="What this category means..." spellcheck="true" required aria-required="true">' + _esc(catTaxonomy.description || '') + '</textarea></label>' +
      '<label class="pg-category-taxonomy-field"><span>Use when <abbr title="Required" aria-label="Required">*</abbr></span><textarea data-taxonomy-field="when_to_use" rows="3" placeholder="When the analyzer should use this category..." spellcheck="true" required aria-required="true">' + _esc(catTaxonomy.when_to_use || '') + '</textarea></label>' +
    '</section>';
    html += '<section class="pg-category-tab-panel pg-category-details" id="' + detailsPanelId + '" data-category-panel="details" role="tabpanel" aria-labelledby="pg-category-' + domKey + '-details-tab" hidden>' +
      '<div class="pg-category-tab-heading"><div><h4>Category details</h4><p>Keep recurring issue patterns distinct enough for reliable diagnosis.</p></div><span class="qym-tag qym-tag--count pg-detail-total-count">' + catDetails.length + '</span></div>' +
      '<div class="pg-category-details-tools"><label class="pg-detail-search-field"><span class="pg-filter-label">Search details</span><input class="pg-detail-search qym-control qym-input qym-search" type="search" data-detail-search placeholder="Filter by detail name" aria-label="Search ' + _escAttr(cat) + ' details" /></label>' +
        '<div class="pg-detail-filter-field"><span class="pg-filter-label" id="pg-detail-filter-' + _escAttr(domKey) + '-label">Show</span><select class="pg-detail-filter qym-control qym-select" data-detail-filter aria-labelledby="pg-detail-filter-' + _escAttr(domKey) + '-label" aria-label="Filter ' + _escAttr(cat) + ' details"><option value="all">All details</option><option value="with_examples">With examples</option><option value="without_examples">Needs examples</option></select></div>' +
        '<span class="pg-detail-result-count" data-detail-result-count aria-live="polite"></span></div>' +
      '<div class="pg-details-sublist" data-cat="' + _escAttr(cat) + '">' + _buildCategoryDetailItems(cat, catDetails, catExamples) + '</div>' +
      '<div class="qym-pagination pg-category-pagination" data-category-pagination="details" role="navigation" aria-label="' + _escAttr(cat) + ' details pagination" hidden></div>' +
      '<p class="pg-category-details-empty" data-detail-empty hidden>No details match this filter.</p>' +
      '<div class="pg-add-detail-row" data-cat="' + _escAttr(cat) + '"><input type="text" placeholder="Add detail..." aria-label="Add a detail to ' + _escAttr(cat) + '" class="pg-add-input pg-add-detail-input qym-control qym-input" />' +
        '<button type="button" class="pg-add-detail-btn pg-add-btn qym-inline-action qym-inline-action--neutral">Add detail</button></div>' +
    '</section>';
    html += '<section class="pg-category-tab-panel pg-category-examples" id="' + examplesPanelId + '" data-category-panel="examples" role="tabpanel" aria-labelledby="pg-category-' + domKey + '-examples-tab" hidden>' +
      '<div class="pg-category-tab-heading"><div><h4>Approved examples</h4><p>Use approved corrections as evidence for this category.</p></div><span class="qym-tag qym-tag--count">' + catExamples.length + '</span></div>' + _buildCategoryExamples(catExamples) +
      '<div class="qym-pagination pg-category-pagination" data-category-pagination="examples" role="navigation" aria-label="' + _escAttr(cat) + ' examples pagination" hidden></div>' +
    '</section></div></article>';
    return html;
  }

  function _categoryGroups() {
    var categoryList = document.getElementById('pg-categories-list');
    return categoryList
      ? Array.prototype.slice.call(categoryList.querySelectorAll('.pg-category-group'))
      : [];
  }

  function _setCategoryTab(group, tab, focus) {
    if (!group) return;
    var selectedTab = tab || group.dataset.activeTab || 'guidance';
    var tabs = Array.prototype.slice.call(group.querySelectorAll('[data-category-tab]'));
    var panels = Array.prototype.slice.call(group.querySelectorAll('[data-category-panel]'));
    var found = tabs.some(function (button) { return button.dataset.categoryTab === selectedTab; });
    if (!found) selectedTab = 'guidance';
    group.dataset.activeTab = selectedTab;
    tabs.forEach(function (button) {
      var selected = button.dataset.categoryTab === selectedTab;
      button.setAttribute('aria-selected', selected ? 'true' : 'false');
      button.tabIndex = selected ? 0 : -1;
      if (selected && focus) button.focus();
    });
    panels.forEach(function (panel) {
      panel.hidden = panel.dataset.categoryPanel !== selectedTab;
    });
  }

  function _categoryPageKey(tab) {
    return tab === 'examples' ? 'examplesPage' : 'detailsPage';
  }

  function _categoryPage(group, tab) {
    if (!group) return 0;
    var page = parseInt(group.dataset[_categoryPageKey(tab)], 10);
    return Number.isNaN(page) || page < 0 ? 0 : page;
  }

  function _setCategoryPage(group, tab, page, total) {
    if (!group) return 0;
    var pageCount = Math.max(1, Math.ceil(Math.max(0, Number(total) || 0) / _CATEGORY_PAGE_SIZE));
    var nextPage = parseInt(page, 10);
    if (Number.isNaN(nextPage)) nextPage = 0;
    nextPage = Math.min(pageCount - 1, Math.max(0, nextPage));
    group.dataset[_categoryPageKey(tab)] = String(nextPage);
    return nextPage;
  }

  function _resetCategoryPage(group, tab) {
    if (group) group.dataset[_categoryPageKey(tab)] = '0';
  }

  function _renderCategoryPagination(group, tab, total) {
    if (!group) return;
    var pagination = group.querySelector('[data-category-pagination="' + tab + '"]');
    if (!pagination) return;
    var page = _setCategoryPage(group, tab, _categoryPage(group, tab), total);
    if (total <= _CATEGORY_PAGE_SIZE || !window.QymUIComponents || typeof window.QymUIComponents.renderPagination !== 'function') {
      pagination.hidden = true;
      pagination.innerHTML = '';
      return;
    }
    pagination.hidden = false;
    window.QymUIComponents.renderPagination(pagination, {
      total: total,
      pageSize: _CATEGORY_PAGE_SIZE,
      page: page + 1,
      onPageChange: function (nextPage) {
        group.dataset[_categoryPageKey(tab)] = String(Math.max(0, nextPage - 1));
        if (tab === 'examples') _filterCategoryExamples(group);
        else _filterCategoryDetails(group);
      },
    });
  }

  function _filterCategoryDetails(group) {
    if (!group) return;
    var panel = group.querySelector('[data-category-panel="details"]');
    if (!panel) return;
    var search = panel.querySelector('[data-detail-search]');
    var filter = panel.querySelector('[data-detail-filter]');
    if (filter && window.QymUIComponents && typeof window.QymUIComponents.enhanceSelect === 'function') {
      window.QymUIComponents.enhanceSelect(filter, { className: 'pg-detail-review-selector', label: 'Show details', search: false });
    }
    var query = String(search && search.value || '').trim().toLocaleLowerCase();
    var mode = String(filter && filter.value || 'all');
    var items = Array.prototype.slice.call(panel.querySelectorAll('.pg-detail-item'));
    var matchingItems = items.filter(function (item) {
      var name = String(item.dataset.detail || '').toLocaleLowerCase();
      var count = Number(item.dataset.detailExampleCount || 0);
      var matchesSearch = !query || name.indexOf(query) !== -1;
      var matchesFilter = mode === 'all' || (mode === 'with_examples' && count > 0) || (mode === 'without_examples' && count === 0);
      return matchesSearch && matchesFilter;
    });
    var page = _setCategoryPage(group, 'details', _categoryPage(group, 'details'), matchingItems.length);
    var pageStart = page * _CATEGORY_PAGE_SIZE;
    var pageEnd = Math.min(pageStart + _CATEGORY_PAGE_SIZE, matchingItems.length);
    items.forEach(function (item) {
      var matchIndex = matchingItems.indexOf(item);
      item.hidden = matchIndex < 0 || matchIndex < pageStart || matchIndex >= pageEnd;
    });
    var empty = panel.querySelector('[data-detail-empty]');
    if (empty) {
      empty.hidden = matchingItems.length > 0;
      empty.textContent = items.length > 0 ? 'No details match this filter.' : 'No details configured yet.';
    }
    var count = panel.querySelector('[data-detail-result-count]');
    if (count) {
      count.textContent = matchingItems.length
        ? (pageStart + 1) + '–' + pageEnd + ' of ' + matchingItems.length + ' details'
        : '0 of ' + items.length + ' details';
    }
    _renderCategoryPagination(group, 'details', matchingItems.length);
  }

  function _filterCategoryExamples(group) {
    if (!group) return;
    var panel = group.querySelector('[data-category-panel="examples"]');
    if (!panel) return;
    var items = Array.prototype.slice.call(panel.querySelectorAll('.pg-category-example'));
    var page = _setCategoryPage(group, 'examples', _categoryPage(group, 'examples'), items.length);
    var pageStart = page * _CATEGORY_PAGE_SIZE;
    var pageEnd = Math.min(pageStart + _CATEGORY_PAGE_SIZE, items.length);
    items.forEach(function (item, index) {
      item.hidden = index < pageStart || index >= pageEnd;
    });
    _renderCategoryPagination(group, 'examples', items.length);
  }

  function _updateCategoryDetailCounts(group) {
    if (!group) return;
    var items = Array.prototype.slice.call(group.querySelectorAll('.pg-detail-item'));
    var total = group.querySelector('.pg-detail-total-count');
    if (total) total.textContent = String(items.length);
    var tabCount = group.querySelector('[data-category-tab="details"] .pg-category-tab-count');
    if (tabCount) tabCount.textContent = String(items.length);
    _filterCategoryDetails(group);
  }

  function _renderCategoryNavigation(selectedCategory) {
    var nav = document.getElementById('pg-category-nav');
    var empty = document.getElementById('pg-category-nav-empty');
    var count = document.getElementById('pg-category-nav-count');
    var groups = _categoryGroups();
    if (count) count.textContent = String(groups.length);
    if (!nav) return;
    var query = String(_categoryNavigationQuery || '').trim().toLocaleLowerCase();
    var matchingGroups = groups.filter(function (group) {
      return !query || String(group.dataset.cat || '').toLocaleLowerCase().indexOf(query) !== -1;
    });
    if (empty) {
      empty.hidden = matchingGroups.length > 0;
      empty.textContent = query ? 'No categories match this search.' : 'No categories configured yet.';
    }
    nav.innerHTML = matchingGroups.map(function (group) {
      var category = group.dataset.cat || '';
      var exampleCount = Number(group.dataset.exampleCount || 0);
      var selected = selectedCategory != null
        ? String(category) === String(selectedCategory)
        : !group.hidden;
      var status = exampleCount > 0 ? 'validated' : 'needs examples';
      return '<button class="pg-category-nav-item" type="button" data-category-select="' + _escAttr(category) + '"' +
        ' aria-current="' + (selected ? 'true' : 'false') + '" aria-label="' + _escAttr(category + ', ' + _detailCountLabel(exampleCount) + ', ' + status) + '">' +
        '<span class="pg-category-nav-copy"><span class="pg-category-nav-name" dir="auto">' + _esc(category) + '</span>' +
          '</span><span class="pg-category-nav-meta"><span class="pg-category-status-dot pg-category-status-dot--' + (exampleCount > 0 ? 'validated' : 'pending') + '" aria-hidden="true"></span><span class="pg-category-nav-count">' + exampleCount + '</span></span>' +
        '<span class="pg-category-nav-chevron" aria-hidden="true">' + _icon('chevron') + '</span>' +
      '</button>';
    }).join('');
  }

  function _filterCategoryNavigation(query) {
    _categoryNavigationQuery = String(query || '').trim();
    var active = _categoryGroups().find(function (group) { return !group.hidden; });
    _renderCategoryNavigation(active && active.dataset.cat);
  }

  function _confirmCategoryRemoval(category) {
    if (!window.QymShell || typeof window.QymShell.openConfirmDialog !== 'function') {
      if (_opts.showToast) {
        _opts.showToast('error', 'Confirmation unavailable', 'The category was not removed. Reload the page and try again.');
      }
      return Promise.resolve(false);
    }
    return window.QymShell.openConfirmDialog({
      mount: _overlay || document.body,
      title: 'Remove category?',
      description: [
        'Remove “' + category + '” from the category catalog?',
        'Its guidance and details will be removed from this unsaved catalog draft.',
      ],
      note: 'Save changes to apply the removal to future analyses.',
      cancelLabel: 'Keep category',
      confirmLabel: 'Remove category',
      confirmClass: 'shell-btn-danger',
    }).then(function (result) {
      return !!(result && result.confirmed);
    });
  }

  function _selectCategory(category, focus) {
    var groups = _categoryGroups();
    if (!groups.length) {
      _renderCategoryNavigation(null);
      var emptyActiveName = document.getElementById('pg-category-active-name');
      if (emptyActiveName) emptyActiveName.textContent = 'Select a category';
      return null;
    }
    var target = groups.find(function (group) {
      return String(group.dataset.cat || '') === String(category == null ? '' : category);
    }) || groups[0];
    groups.forEach(function (group) {
      var selected = group === target;
      group.hidden = !selected;
      group.setAttribute('aria-hidden', selected ? 'false' : 'true');
      group.classList.toggle('pg-category-group--active', selected);
    });
    _renderCategoryNavigation(target.dataset.cat || '');
    _setCategoryTab(target, target.dataset.activeTab || 'guidance', false);
    _filterCategoryDetails(target);
    _filterCategoryExamples(target);
    var activeName = document.getElementById('pg-category-active-name');
    if (activeName) activeName.textContent = target.dataset.cat || '';
    if (focus) {
      var panel = target.querySelector('[data-category-panel="' + (target.dataset.activeTab || 'guidance') + '"]');
      if (panel) panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
    return target;
  }

  function _initializeCategoryWorkspace() {
    var groups = _categoryGroups();
    groups.forEach(function (group) {
      group.dataset.activeTab = group.dataset.activeTab || 'guidance';
      _setCategoryTab(group, group.dataset.activeTab, false);
      _filterCategoryDetails(group);
      _filterCategoryExamples(group);
    });
    _selectCategory(groups[0] && groups[0].dataset.cat, false);
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
      arrow: '<path d="M5 12h14"></path><path d="m13 6 6 6-6 6"></path>',
      dots: '<circle cx="12" cy="5" r="1.4" fill="currentColor" stroke="none"></circle><circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none"></circle><circle cx="12" cy="19" r="1.4" fill="currentColor" stroke="none"></circle>',
      download: '<path d="M12 4v11"></path><path d="m7 11 5 5 5-5"></path><path d="M5 20h14"></path>',
      merge: '<path d="M6 4v4c0 4 2 6 6 6h6"></path><path d="M6 20v-4c0-4 2-6 6-6h6"></path><path d="m15 7 3 3-3 3"></path>',
      upload: '<path d="M12 14V4"></path><path d="m7 9 5-5 5 5"></path><path d="M5 14v6h14v-6"></path>',
      rocket: '<path d="M4.5 16.5c-1.5 1.3-2 5-2 5s3.7-.5 5-2a2.2 2.2 0 0 0-.1-2.9 2.2 2.2 0 0 0-2.9-.1Z"></path><path d="m12 15-3-3a22 22 0 0 1 2-4A13 13 0 0 1 22 2c0 2.7-.8 7.2-6 10a22 22 0 0 1-4 3Z"></path><path d="M9 12H4s.6-3 2-4c1.6-1.1 5 0 5 0"></path><path d="M12 15v5s3-.6 4-2c1.1-1.6 0-5 0-5"></path><circle cx="16" cy="8" r="1"></circle>',
      chevron: '<path d="m9 18 6-6-6-6"></path>',
      chevronUp: '<path d="m6 15 6-6 6 6"></path>',
      chevronDown: '<path d="m6 9 6 6 6-6"></path>',
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

  // Token-backed root-cause palette shared by prompt previews, corrections,
  // items, and test results. Matching is case-insensitive so catalog variants
  // do not silently change color.
  var _RC_COLORS = {
    'Hallucination': 'var(--score-1)', 'Incomplete Answer': 'var(--score-2)',
    'Wrong Format': 'var(--chart-1)', 'Context Missing': 'var(--info)',
    'Reasoning Error': 'var(--chart-3)', 'Tool Use Error': 'var(--chart-4)',
    'Instruction Following': 'var(--chart-1)', 'Knowledge Gap': 'var(--chart-2)',
    'Dataset Issue': 'var(--score-3)',
  };

  function _rootCauseColor(value, fallback) {
    var normalized = String(value || '').trim().toLowerCase();
    var names = Object.keys(_RC_COLORS);
    for (var i = 0; i < names.length; i++) {
      if (names[i].toLowerCase() === normalized) return _RC_COLORS[names[i]];
    }
    return fallback === undefined ? 'var(--chart-5)' : fallback;
  }

  function _highlightPreview(escaped) {
    // Keep project rules readable without changing the copied prompt text.
    escaped = escaped.replace(
      /(ANALYSIS RULES(?:\s*\([^\)\n]*\))?:\n)([\s\S]*?)(\n\n(?:EVALUATION ITEM DATA:|SUPPLIED ANALYSIS DATA|Respond ONLY))/m,
      function (section, heading, rules, nextSection) {
        return '<span class="pg-hl-label">' + heading.replace(/\n$/, '') + '</span>\n' +
          rules.replace(/^(\d+\. .+)$/gm, '<span class="pg-hl-rule-title">$1</span>') +
          nextSection;
      }
    );
    // Keep the configured category limit in the same yellow treatment as the
    // injected category vocabulary, whether it appears in the default prompt
    // sentence or the fallback section added for custom prompts.
    escaped = escaped.replace(
      /^(MAXIMUM ROOT-CAUSE CATEGORIES:\n)([^\n]+)$/m,
      '<span class="pg-hl-category">$1$2</span>'
    );
    escaped = escaped.replace(
      /(\bno more than )(\d+)( categories\b)/gi,
      '$1<span class="pg-hl-category">$2</span>$3'
    );
    // Highlight structural prompt labels, including trace headings and
    // per-step evidence labels such as TRACE EVIDENCE:, INPUT:, and RESULT:.
    // The leading whitespace stays outside the span so indentation remains
    // part of the copied prompt's visual structure.
    escaped = escaped.replace(
      /^([ \t]*)([A-Z][A-Z0-9_-]*(?:[ \t]+[A-Z0-9][A-Z0-9_-]*)*[ \t]*:)/gm,
      '$1<span class="pg-hl-label">$2</span>'
    );
    // Highlight the title-case labels emitted inside context blocks.
    escaped = escaped.replace(
      /^([ \t]*)(Description|Use when|Known root-cause detail guidance|Project|Evaluation task|Dataset):/gm,
      '$1<span class="pg-hl-label">$2:</span>'
    );
    // Highlight the numbered diagnosis fields in the instructions as labels.
    escaped = escaped.replace(
      /^(\d+\.\s+(?:root_causes|category_taxonomy|root_cause_detail|root_cause_reason|confidence|root_cause_note|root_cause)\b)/gm,
      '<span class="pg-hl-label">$1</span>'
    );
    // Use one yellow treatment for every root-cause category, including custom languages.
    escaped = escaped.replace(/^( *- .+)$/gm, '<span class="pg-hl-category">$1</span>');
    // Highlight category headers in grouped details (e.g. "  Gold Query:")
    escaped = escaped.replace(/^( {2}\S.+:)$/gm,
      '<span class="pg-hl-label">$1</span>');
    // Highlight Additional Instructions block (label + all content after it until end)
    escaped = escaped.replace(/(Additional Instructions:\n)([\s\S]*)$/m,
      '<span class="pg-hl-label">$1</span><span class="pg-hl-dynamic">$2</span>');
    // JSON keys are labels too; highlight every escaped object key rather
    // than maintaining a list that can drift as the response schema evolves.
    escaped = escaped.replace(/((?:&quot;|")[A-Za-z_][A-Za-z0-9_.-]*(?:&quot;|"))(?=\s*:)/g,
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

  function _isHumanMetricAnalysis(md, metricName) {
    if (!md || typeof md !== 'object') return false;
    var metricAnalyses = md.metric_analyses && typeof md.metric_analyses === 'object'
      ? md.metric_analyses : {};
    var analysis = metricAnalyses[metricName];
    var source = analysis && (analysis.source || analysis.root_cause_source);
    if (String(source || '').trim().toLowerCase() === 'human') return true;
    if (String(md.root_cause_source || '').trim().toLowerCase() !== 'human') return false;
    var legacyMetric = String(md.root_cause_metric_name || '').trim();
    return !legacyMetric || legacyMetric === String(metricName || '').trim();
  }

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
      var metricAnalyses = md && md.metric_analyses && typeof md.metric_analyses === 'object'
        ? md.metric_analyses : {};
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
          if ((isError || !metricPassed) &&
              (allowHumanOverwrite || !_isHumanMetricAnalysis(md, metricName))) {
            failedMetrics.push(metricName);
          }
        });
      }
      if (!metricScores && (isError || score == null || score < threshold)) {
        var fallbackMetric = _opts.getMetric ? (_opts.getMetric() || 'metric') : 'metric';
        if (allowHumanOverwrite || !_isHumanMetricAnalysis(md, fallbackMetric)) {
          failedMetrics.push(fallbackMetric);
        }
      }
      if (skipAnalyzed && failedMetrics.length > 0) {
        failedMetrics = failedMetrics.filter(function (metricName) {
          var existing = metricAnalyses[metricName];
          // The explicit human-overwrite option takes precedence over the
          // general "Skip analyzed" option for human-owned diagnoses.
          if (allowHumanOverwrite && _isHumanMetricAnalysis(md, metricName)) return true;
          return !(existing && existing.root_cause);
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

  function _getHumanOverwriteTargets(matchedItems) {
    var targets = [];
    (matchedItems || []).forEach(function (row) {
      var metricNames = Array.isArray(row._matched_metric_names) ? row._matched_metric_names : [];
      metricNames.forEach(function (metricName) {
        if (_isHumanMetricAnalysis(row.item_metadata, metricName)) {
          targets.push({ item_id: row.item_id, metric_name: metricName });
        }
      });
    });
    return targets;
  }

  function _getMatchedItemCount(matchedItems) {
    return (matchedItems || []).length;
  }

  function _formatAnalyzeItemCount(itemCount) {
    return 'Analyze ' + itemCount + (itemCount === 1 ? ' item' : ' items');
  }

  // ── Explicit modal and dedicated-page renderers ──

  function _createModal() {
    if (_overlay && _overlay.parentNode) { _overlay.parentNode.removeChild(_overlay); _overlay = null; }

    var pageContainer = null;
    if (_opts.container) {
      pageContainer = typeof _opts.container === 'string'
        ? document.querySelector(_opts.container)
        : _opts.container;
    }

    var dedicatedPage = !!(pageContainer && _opts.dedicatedPage);
    var overlay = document.createElement('div');
    overlay.className = dedicatedPage ? 'playground-page-root' : 'playground-overlay';
    if (!dedicatedPage) {
      overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
    }

    var surface = document.createElement('div');
    surface.className = dedicatedPage ? 'playground-page-content' : 'playground-modal';

    if (!dedicatedPage) {
      var header = document.createElement('div');
      header.className = 'playground-header';
      header.innerHTML =
        '<div class="playground-header-left">' +
          '<span class="playground-header-icon">&#x1F916;</span>' +
          '<span class="playground-header-title">LLM Analyzer</span>' +
        '</div>' +
        '<button class="playground-close" title="Close">&times;</button>';
      header.querySelector('.playground-close').addEventListener('click', close);
      surface.appendChild(header);
    }

    // LLM not configured banner
    if (_config && !_config.llm_configured) {
      var banner = document.createElement('div');
      banner.className = 'playground-banner playground-banner-warn';
      banner.textContent = 'No LLM connection for this project \u2014 add one in Project Settings \u2192 LLM Connections to enable Test and Run';
      surface.appendChild(banner);
    }

    // Scrollable content area
    var scroll = document.createElement('div');
    scroll.className = dedicatedPage ? 'playground-page-sections' : 'playground-scroll';
    scroll.innerHTML = _buildScrollContent();
    surface.appendChild(scroll);
    // Sticky footer
    var footer = document.createElement('div');
    footer.className = 'playground-footer';
    var llmOk = _config && _config.llm_configured;
    var conns = (_config && _config.llm_connections) || [];
    var connSelect = '';
    if (conns.length) {
      connSelect = '<div class="pg-connection" id="pg-connection-picker">' +
        '<span class="pg-connection-label" id="pg-connection-label">LLM connection</span>' +
        '<select id="pg-connection" class="pg-connection-select" aria-labelledby="pg-connection-label" aria-label="LLM connection">' +
        conns.map(function (c) {
          return '<option value="' + _esc(c.id) + '"' + (c.id === _connectionId ? ' selected' : '') +
            (c.llm_api_key_set ? '' : ' disabled') + '>' + _esc(c.name) + (c.llm_model ? ' · ' + _esc(c.llm_model) : '') + (c.llm_api_key_set ? '' : ' · key missing') + '</option>';
        }).join('') +
        '</select>' +
        '</div>';
    }
    footer.innerHTML =
      connSelect +
      '<button class="pg-footer-btn pg-footer-test qym-inline-action qym-inline-action--neutral" id="pg-test-btn" ' + (!llmOk ? 'disabled' : '') + '>Test Selected</button>' +
      '<button class="pg-footer-btn pg-footer-runall qym-inline-action qym-inline-action--accent" id="pg-runall-btn" ' + (!llmOk ? 'disabled' : '') + '>' + _formatAnalyzeItemCount(_getMatchedItemCount(_getMatchedItems())) + '</button>' +
      '<button class="pg-footer-btn pg-footer-cancel qym-inline-action" id="pg-cancel-btn" type="button" hidden>Cancel analysis</button>';
    footer.hidden = false;
    surface.appendChild(footer);
    var connEl = footer.querySelector('#pg-connection');
    if (connEl) {
      connEl.addEventListener('change', function () {
        _connectionId = connEl.value || null;
        _syncActionAvailability();
        _scheduleAutoPreview(0);
      });
      if (window.QymUIComponents && typeof window.QymUIComponents.enhanceSelect === 'function') {
        window.QymUIComponents.enhanceSelect(connEl, { className: 'pg-connection-selector', label: 'LLM connection', placement: 'top', search: conns.length > 8 });
      }
    }

    overlay.appendChild(surface);
    (pageContainer || document.body).appendChild(overlay);
    _overlay = overlay;

    // Wire all events
    _wireEvents();
    document.addEventListener('keydown', _onKeyDown);
    // Initialize once the controls are mounted so target matching reads their
    // real values instead of the pre-mount empty DOM.
    _onFilterChange();
    if (dedicatedPage && typeof _opts.composePage === 'function') {
      _opts.composePage({
        root: overlay,
        content: scroll,
        projectPanel: scroll.querySelector('.pg-context-panel'),
        runPanel: scroll.querySelector('.pg-analysis-main'),
        footer: footer,
      });
    }
  }

  function _onKeyDown(e) {
    if (e.key !== 'Escape' || !_overlay || _overlay.style.display === 'none') return;
    if (e.defaultPrevented) return;
    var nestedDialog = e.target && typeof e.target.closest === 'function'
      ? e.target.closest('[role="dialog"][aria-modal="true"]') : null;
    if (nestedDialog) return;
    var nestedDropdown = e.target && typeof e.target.closest === 'function'
      ? e.target.closest('.qym-dropdown, .qym-review-selector') : null;
    if (nestedDropdown) return;
    // In dedicated-page mode, nested overlays handle Escape but the page root
    // must remain mounted and visible.
    if (_opts.dedicatedPage) return;
    e.preventDefault();
    close();
  }

  function _categoryLimitInputValue(input) {
    if (!input) return null;
    var rawValue = String(input.value == null ? '' : input.value).trim();
    if (!rawValue) return null;
    var value = Number(rawValue);
    if (!Number.isFinite(value)) return null;
    return Math.min(_MAX_ROOT_CAUSE_CATEGORIES, Math.max(1, Math.trunc(value)));
  }

  function _normalizeCategoryLimitInput(input) {
    if (!input) return _DEFAULT_MAX_ROOT_CAUSE_CATEGORIES;
    var value = _categoryLimitInputValue(input);
    if (value == null) value = _DEFAULT_MAX_ROOT_CAUSE_CATEGORIES;
    input.value = String(value);
    return value;
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

  function _enabledReferenceDocumentCount() {
    return _referenceDocuments.filter(function (document) {
      return document.selected !== false && String(document.content || '').trim();
    }).length;
  }

  function _analysisLimits() {
    return (_config && _config.analysis_limits) || {};
  }

  function _documentPromptCharacterLimit() {
    var limits = _analysisLimits();
    return Number(limits.documents_prompt_characters || 80000);
  }

  function _documentPerFilePromptLimit() {
    var limits = _analysisLimits();
    return Number(limits.document_prompt_characters || 40000);
  }

  function _documentCountLimit() {
    var limits = _analysisLimits();
    return Number(limits.max_reference_documents || 8);
  }

  function _writerDocumentCharacterLimit() {
    var limits = _analysisLimits();
    return Number(limits.rule_writer_document_characters || 256000);
  }

  function _writerExampleCharacterLimit() {
    var limits = _analysisLimits();
    return Number(limits.rule_writer_example_characters || 256000);
  }

  function _selectedReferenceDocumentCharacters() {
    return _referenceDocuments.reduce(function (total, referenceDocument) {
      if (referenceDocument.selected === false || !String(referenceDocument.content || '').trim()) return total;
      return total + Number(referenceDocument.characters || String(referenceDocument.content || '').length);
    }, 0);
  }

  function _approvedExampleCount() {
    var raw = _config && _config.approved_example_count != null
      ? _config.approved_example_count
      : (_config && _config.correction_bank_size);
    var count = Number(raw);
    return Number.isFinite(count) && count > 0 ? Math.floor(count) : 0;
  }

  function _selectedApprovedExampleCount() {
    return _selectedApprovedExampleIds ? _selectedApprovedExampleIds.size : 0;
  }

  function _renderApprovedExampleSourceControl() {
    var button = document.getElementById('pg-add-examples');
    if (!button) return;
    var selectedCount = _selectedApprovedExampleCount();
    button.textContent = 'Add examples';
    button.setAttribute('aria-label', selectedCount > 0
      ? 'Edit approved examples, ' + selectedCount + ' selected'
      : 'Add approved examples');
    button.title = selectedCount > 0 ? 'Edit selected approved examples' : 'Add approved examples';
    button.classList.toggle('pg-example-source-control--selected', selectedCount > 0);
  }

  function _inferenceSourceState() {
    var documentsInput = document.getElementById('pg-infer-use-documents');
    var documentsAvailable = _enabledReferenceDocumentCount();
    var examplesAvailable = _approvedExampleCount();
    var includeDocuments = !documentsInput || documentsInput.checked;
    var selectedExampleCount = _selectedApprovedExampleCount();
    var includeExamples = selectedExampleCount > 0;
    var selectedDocuments = includeDocuments ? documentsAvailable : 0;
    var selectedExamples = selectedExampleCount;
    var selectedDocumentCharacters = includeDocuments ? _selectedReferenceDocumentCharacters() : 0;
    var hasUsableSource = selectedDocuments > 0 || selectedExamples > 0;
    var message;
    if (!hasUsableSource) {
      if (documentsAvailable === 0 && examplesAvailable === 0) {
        message = 'Rules cannot be generated yet. This project has neither an ' +
          'enabled project document nor an approved example. Add and enable a ' +
          'project document, or approve an example, then try again.';
      } else if (includeDocuments && documentsAvailable === 0) {
        message = 'Rules cannot be generated yet. No enabled project documents ' +
          'are available. Add an approved example, or add and enable a project ' +
          'document, then try again.';
      } else if (examplesAvailable > 0 && selectedExamples === 0) {
        message = 'Add at least one approved example before generating rules, or turn on Project documents.';
      } else {
        message = 'Rules cannot be generated yet. No approved examples are ' +
          'available, and Project documents are turned off. Add an approved ' +
          'example or turn on Project documents, then try again.';
      }
    } else {
      message = '';
    }
    return {
      documentsAvailable: documentsAvailable,
      examplesAvailable: examplesAvailable,
      includeDocuments: includeDocuments,
      includeExamples: includeExamples,
      selectedDocuments: selectedDocuments,
      selectedExamples: selectedExamples,
      selectedDocumentCharacters: selectedDocumentCharacters,
      selectedApprovedExampleCharacters: _selectedApprovedExampleCharacters,
      documentCharacterLimit: _documentPromptCharacterLimit(),
      documentCountLimit: _documentCountLimit(),
      writerDocumentCharacterLimit: _writerDocumentCharacterLimit(),
      writerExampleCharacterLimit: _writerExampleCharacterLimit(),
      hasUsableSource: hasUsableSource,
      message: message,
    };
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

  function _filteredAnalysisRuleEntries() {
    var query = String(_analysisRuleSearch || '').trim().toLowerCase();
    return _analysisRules.map(function (rule, index) {
      return { rule: rule, index: index };
    }).filter(function (entry) {
      if (!query) return true;
      return [entry.rule.title, entry.rule.instruction]
        .join(' ')
        .toLowerCase()
        .indexOf(query) >= 0;
    });
  }

  function _renderRuleFilterControls() {
    var search = document.getElementById('pg-rule-search');
    if (search && search.value !== _analysisRuleSearch) search.value = _analysisRuleSearch;
  }

  function _analysisRulesPageCount() {
    return Math.max(1, Math.ceil(_filteredAnalysisRuleEntries().length / _RULES_PAGE_SIZE));
  }

  function _setAnalysisRulesPage(page) {
    var pageCount = _analysisRulesPageCount();
    var nextPage = Number(page);
    if (!Number.isFinite(nextPage)) nextPage = 1;
    _analysisRulesPage = Math.min(pageCount, Math.max(1, Math.floor(nextPage)));
    return _analysisRulesPage;
  }

  function _analysisRulesPageForIndex(index) {
    var position = _filteredAnalysisRuleEntries().findIndex(function (entry) {
      return entry.index === index;
    });
    return _setAnalysisRulesPage(Math.floor(Math.max(0, position) / _RULES_PAGE_SIZE) + 1);
  }

  function _buildAnalysisRulesEditor() {
    var selected = _ruleVersions.find(function (version) { return version.id === _selectedRuleVersionId; });
    var readOnly = !selected || selected.status !== 'draft';
    if (_analysisRules.length === 0) {
      return '<div class="pg-rule-empty">' + (readOnly
        ? 'This version has no rules. Create a draft before editing.'
        : 'No rules yet. Generate rules after selecting reference documents, or add one manually.') + '</div>';
    }
    var entries = _filteredAnalysisRuleEntries();
    if (entries.length === 0) {
      return '<div class="pg-rule-empty">No rules match the current search.</div>';
    }
    var page = _setAnalysisRulesPage(_analysisRulesPage);
    var pageStart = (page - 1) * _RULES_PAGE_SIZE;
    return entries.slice(pageStart, pageStart + _RULES_PAGE_SIZE).map(function (entry) {
      var rule = entry.rule;
      var index = entry.index;
      var editing = _editingRuleIndex === index;
      var ruleName = rule.title || 'rule ' + (index + 1);
      var instruction = rule.instruction || 'No instruction yet.';
      var deleteAction = !readOnly
        ? '<button class="qym-icon-action qym-icon-action--danger pg-rule-remove" type="button" data-delete-rule="' + index + '" title="Delete ' + _escAttr(ruleName) + '" aria-label="Delete ' + _escAttr(ruleName) + '">' + _icon('trash') + '</button>'
        : '';
      return '<div class="pg-rule-item' + (editing ? ' pg-rule-item-editing' : '') + '" data-rule-index="' + index + '" data-rule-id="' + _escAttr(rule.id || '') + '">' +
        '<div class="pg-rule-item-head" role="group" aria-label="' + _escAttr(ruleName) + '">' +
          '<span class="pg-rule-item-number" aria-label="Rule ' + (index + 1) + '">' + (index + 1) + '</span>' +
          '<button class="pg-rule-toggle" data-toggle-rule="' + index + '" type="button" aria-expanded="' + (editing ? 'true' : 'false') + '" aria-controls="pg-rule-fields-' + index + '" aria-label="' + (editing ? 'Collapse ' : 'Expand ') + _escAttr(ruleName) + '">' +
            '<span class="pg-rule-item-summary"><strong title="' + _escAttr(rule.title || 'Untitled rule') + '">' + _esc(rule.title || 'Untitled rule') + '</strong><span title="' + _escAttr(instruction) + '" dir="auto">' + _esc(instruction) + '</span></span>' +
            '<span class="pg-rule-disclosure" aria-hidden="true">' + _icon('chevron') + '</span>' +
          '</button>' +
          deleteAction +
        '</div>' +
        '<div class="pg-rule-fields" id="pg-rule-fields-' + index + '"' + (editing ? '' : ' hidden') + '>' +
          '<label class="pg-rule-field"><span class="pg-rule-field-label">Rule title</span><input class="pg-rule-title" type="text" value="' + _escAttr(rule.title || '') + '" placeholder="Rule title" aria-label="Rule title" dir="auto"' + (readOnly ? ' disabled' : '') + ' /></label>' +
          '<label class="pg-rule-field"><span class="pg-rule-field-label">Instruction</span><textarea class="pg-rule-instruction" placeholder="What must be checked and how it affects the diagnosis" aria-label="Rule instruction" dir="auto"' + (readOnly ? ' disabled' : '') + '>' + _esc(rule.instruction || '') + '</textarea></label>' +
          '<div class="pg-rule-metadata" aria-label="Rule metadata">' +
            '<div class="pg-rule-metadata-item"><span class="pg-rule-metadata-label">Inferred from</span><p class="pg-rule-metadata-value" dir="auto">' + _esc(rule.inferred_from || 'Not provided by the rule writer.') + '</p></div>' +
            '<div class="pg-rule-metadata-item"><span class="pg-rule-metadata-label">Why this rule helps the analyzer</span><p class="pg-rule-metadata-value" dir="auto">' + _esc(rule.explanation || 'Not provided by the rule writer.') + '</p></div>' +
            '<span class="pg-rule-metadata-note">Metadata only · not included in the analyzer prompt.</span>' +
          '</div>' +
        '</div>' +
      '</div>';
    }).join('');
  }

  function _renderAnalysisRulePagination() {
    var pagination = document.getElementById('pg-rule-pagination');
    if (!pagination) return;
    if (_filteredAnalysisRuleEntries().length === 0) {
      pagination.hidden = true;
      pagination.innerHTML = '';
      return;
    }
    var page = _setAnalysisRulesPage(_analysisRulesPage);
    pagination.hidden = false;
    if (!window.QymUIComponents || typeof window.QymUIComponents.renderPagination !== 'function') return;
    window.QymUIComponents.renderPagination(pagination, {
      total: _filteredAnalysisRuleEntries().length,
      pageSize: _RULES_PAGE_SIZE,
      page: page,
      onPageChange: function (nextPage) {
        _analysisRules = _readAnalysisRuleDraftsFromEditor();
        _setAnalysisRulesPage(nextPage);
        _editingRuleIndex = null;
        _renderAnalysisRulesEditor(true);
      },
    });
  }

  function _ruleVersionStateLabel(version) {
    if (version && version.is_active) return 'Live';
    if (version && version.status === 'draft') return 'Draft';
    if (version && version.status === 'published') return 'Published';
    var raw = String((version && version.status) || 'Unknown');
    return raw.charAt(0).toUpperCase() + raw.slice(1).toLowerCase();
  }

  function _formatRelativeRuleDate(value) {
    if (!value) return 'Unknown date';
    var timestamp = new Date(value);
    if (Number.isNaN(timestamp.getTime())) return 'Unknown date';
    var delta = Date.now() - timestamp.getTime();
    var future = delta < 0;
    var seconds = Math.round(Math.abs(delta) / 1000);
    if (seconds < 60) return future ? 'in a moment' : 'just now';
    var units = [
      { amount: 60, label: 'minute' },
      { amount: 60, label: 'hour' },
      { amount: 24, label: 'day' },
      { amount: 7, label: 'week' },
      { amount: 4.345, label: 'month' },
      { amount: 12, label: 'year' },
    ];
    var valueInUnit = seconds;
    var label = 'second';
    for (var i = 0; i < units.length; i++) {
      if (valueInUnit < units[i].amount) break;
      valueInUnit /= units[i].amount;
      label = units[i].label;
    }
    var amount = Math.max(1, Math.round(valueInUnit));
    var text = amount + ' ' + label + (amount === 1 ? '' : 's');
    return future ? 'in ' + text : text + ' ago';
  }

  function _buildRuleVersionHistory() {
    if (_ruleVersions.length === 0) {
      return '<div class="pg-rule-empty">No saved versions yet.</div>';
    }
    var liveVersionCount = _ruleVersions.filter(function (version) { return !version.is_deleted; }).length;
    return _ruleVersions.map(function (version) {
      var state = _ruleVersionStateLabel(version);
      var created = _formatRelativeRuleDate(version.created_at);
      var createdFull = version.created_at ? new Date(version.created_at).toLocaleString() : 'Unknown date';
      var stateTone = version.is_active ? 'success' : (version.status === 'draft' ? 'warning' : 'neutral');
      var menuActions = [];
      if (!version.is_deleted) {
        menuActions.push('<button type="button" role="menuitem" data-download-rule-version="' + _escAttr(version.id) + '">' + _icon('download') + '<span>Download</span></button>');
      }
      if (liveVersionCount > 1 && !version.is_deleted) {
        menuActions.push('<button type="button" role="menuitem" data-compare-rule-version="' + _escAttr(version.id) + '">' + _icon('compare') + '<span>Compare with…</span></button>');
        menuActions.push('<button type="button" role="menuitem" data-merge-rule-version="' + _escAttr(version.id) + '">' + _icon('merge') + '<span>Merge with…</span></button>');
      }
      if (_canDeleteRuleVersions && !version.is_deleted && liveVersionCount > 1) {
        menuActions.push('<button class="pg-rule-version-menu-danger" type="button" role="menuitem" data-delete-rule-version="' + _escAttr(version.id) + '">' + _icon('trash') + '<span>Delete version</span></button>');
      }
      var versionDescription = state + ', ' + version.rules.length + ' rules, ' + created;
      var mergeParentIds = Array.isArray(version.merge_parent_ids) ? version.merge_parent_ids.join(',') : '';
      var menu = '<div class="pg-rule-version-overflow">' +
          '<button class="qym-icon-action pg-rule-version-menu-toggle" type="button" data-rule-version-menu-toggle title="More actions for v' + version.version + '" aria-label="More actions for version ' + version.version + '" aria-expanded="false">' + _icon('dots') + '</button>' +
          '<div class="pg-rule-version-menu" role="menu" hidden>' + menuActions.join('') + '</div>' +
        '</div>';
      return '<div class="pg-rule-version' + (version.id === _selectedRuleVersionId ? ' pg-rule-version-selected' : '') + '" role="group" aria-label="Version ' + version.version + '. ' + _escAttr(versionDescription) + '" ' +
        'data-rule-version-id="' + _escAttr(version.id) + '" data-rule-version-status="' + _escAttr(state) + '" data-rule-version-live="' + (version.is_active ? 'true' : 'false') + '" data-rule-parent-id="' + _escAttr(version.parent_version_id || '') + '" data-rule-merge-parent-ids="' + _escAttr(mergeParentIds) + '">' +
        '<button class="pg-rule-version-open" type="button" data-open-rule-version="' + _escAttr(version.id) + '" aria-label="Open version ' + version.version + '. ' + _escAttr(versionDescription) + '">' +
          '<span class="pg-rule-version-copy"><span class="pg-rule-version-heading"><span class="pg-rule-version-name">v' + version.version + '</span><span class="qym-badge qym-badge--' + stateTone + '">' + _esc(state) + '</span></span><span class="pg-rule-version-summary"><span class="qym-tag qym-tag--count pg-rule-version-rule-count">' + version.rules.length + ' rules</span><time class="pg-rule-version-created" datetime="' + _escAttr(version.created_at || '') + '" title="' + _escAttr(createdFull) + '">' + _esc(created) + '</time></span></span>' +
        '</button>' +
        '<span class="pg-rule-version-controls">' + menu + '</span>' +
      '</div>';
    }).join('');
  }

  function _buildReferenceDocumentList() {
    if (_referenceDocuments.length === 0) {
      return '<div class="pg-document-empty">No project documents yet. Add a document here and it becomes available to every analysis in this project.</div>';
    }
    return _referenceDocuments.map(function (document, index) {
      var meta = _formatCharacterCount(document.characters || document.content.length);
      if (document.content_over_limit || document.content_was_cut) {
        meta += ' · content capped at storage limit';
      } else if (document.truncated && Number(document.characters || 0) <= _documentPerFilePromptLimit()) {
        meta += ' · shortened to prompt-safe limit';
      } else if (Number(document.characters || 0) > _documentPerFilePromptLimit()) {
        meta += ' · full content retained; writer will patch it';
      }
      var selected = document.selected !== false;
      return '<div class="pg-document-item' + (selected ? '' : ' pg-document-item-excluded') + '" data-document-index="' + index + '">' +
        '<label class="pg-document-toggle" title="' + (selected ? 'Included in project analysis' : 'Excluded from project analysis') + '">' +
          '<input class="pg-document-select" type="checkbox" data-document-index="' + index + '"' + (selected ? ' checked' : '') + ' />' +
          '<span class="pg-document-check" aria-hidden="true"></span>' +
          '<span class="pg-document-state">' + (selected ? 'Included' : 'Excluded') + '</span>' +
        '</label>' +
        '<div class="pg-document-copy">' +
          '<span class="pg-document-name" dir="auto">' + _esc(document.name) + '</span>' +
          '<span class="pg-document-meta">' + _esc(meta) + '</span>' +
        '</div>' +
        '<button class="pg-document-remove qym-icon-action qym-icon-action--danger" type="button" data-document-index="' + index + '" title="Delete ' + _escAttr(document.name) + '" aria-label="Delete ' + _escAttr(document.name) + '">' + _icon('trash') + '</button>' +
      '</div>';
    }).join('');
  }

  function _examplePickerPayload(state) {
    var filters = state.filters || {};
    return {
      page: state.page,
      page_size: state.pageSize,
      task: filters.task || [],
      dataset: filters.dataset || [],
      model: filters.model || [],
      run_name: filters.run_name || [],
      user_id: filters.user_id || [],
      source: filters.source || null,
      conf_min: filters.conf_min == null ? 0 : filters.conf_min,
      conf_max: filters.conf_max == null ? 100 : filters.conf_max,
      search: filters.search || null,
      selected_ids: Array.from(_selectedApprovedExampleIds),
      selected_only: Boolean(state.viewSelected),
    };
  }

  function _examplePickerFilterValues(state, key) {
    return (state.filters && state.filters[key]) || [];
  }

  function _examplePickerActiveFilterEntries(state) {
    var filters = state.filters || {};
    var entries = [];
    if (filters.search) {
      entries.push({ key: 'search', label: 'Search', value: String(filters.search) });
    }
    [
      ['task', 'Task'],
      ['dataset', 'Dataset'],
      ['model', 'Model'],
      ['run_name', 'Run'],
      ['user_id', 'User'],
    ].forEach(function (definition) {
      var values = Array.isArray(filters[definition[0]]) ? filters[definition[0]] : [];
      if (!values.length) return;
      entries.push({
        key: definition[0],
        label: definition[1],
        value: values.length === 1 ? String(values[0]) : values.length.toLocaleString() + ' selected',
      });
    });
    var sourceLabels = {
      ai_only: 'AI only',
      human_only: 'Human only',
      corrected: 'Corrected',
    };
    if (filters.source) {
      entries.push({ key: 'source', label: 'Source', value: sourceLabels[filters.source] || String(filters.source) });
    }
    var confMin = Number(filters.conf_min == null ? 0 : filters.conf_min);
    var confMax = Number(filters.conf_max == null ? 100 : filters.conf_max);
    if (!Number.isFinite(confMin)) confMin = 0;
    if (!Number.isFinite(confMax)) confMax = 100;
    if (confMin > 0 || confMax < 100) {
      entries.push({ key: 'confidence', label: 'Confidence', value: confMin + '–' + confMax });
    }
    return entries;
  }

  function _examplePickerFilterChips(state) {
    var entries = _examplePickerActiveFilterEntries(state);
    return entries.length
      ? '<div class="pg-example-picker-filter-chips" role="list" aria-label="Active filters">' +
        entries.map(function (entry) {
          var text = entry.label + ': ' + entry.value;
          return '<span class="qym-chip" role="listitem"><span>' + _esc(text) + '</span><button class="pg-example-picker-filter-chip-remove" type="button" data-example-clear-filter="' + _escAttr(entry.key) + '" aria-label="Clear ' + _escAttr(entry.label) + ' filter">×</button></span>';
        }).join('') +
      '</div>'
      : '';
  }

  function _examplePickerDropdown(state, key, label, values, valueLabel) {
    var selected = _examplePickerFilterValues(state, key);
    var selectedValue = selected.length ? String(selected[0]) : '';
    var options = Array.isArray(values) ? values.slice() : [];
    var hasSelectedValue = options.some(function (value) {
      return String(typeof value === 'object' ? value.id : value) === selectedValue;
    });
    // Keep an active value visible even when another dimension makes its
    // result set empty. The selector must never silently look unfiltered.
    if (selectedValue && !hasSelectedValue) {
      options.push(typeof (values && values[0]) === 'object'
        ? { id: selectedValue, display_name: selectedValue }
        : selectedValue);
    }
    var optionHtml = options.map(function (value) {
      var rawValue = String(typeof value === 'object' ? value.id : value);
      var textValue = typeof value === 'object'
        ? (valueLabel ? valueLabel(value) : (value.display_name || value.email || value.id))
        : value;
      textValue = String(textValue == null ? rawValue : textValue);
      return '<option value="' + _escAttr(rawValue) + '"' + (rawValue === selectedValue ? ' selected' : '') + '>' + _esc(textValue) + '</option>';
    }).join('');
    if (!optionHtml) {
      optionHtml = '<option value="" disabled>No options available</option>';
    } else {
      optionHtml = '<option value="">All ' + _esc(label) + 's</option>' + optionHtml;
    }
    var labelId = 'pg-example-filter-label-' + key;
    return '<div class="pg-example-filter" data-example-filter="' + _escAttr(key) + '">' +
      '<span class="pg-example-picker-filter-field-label" id="' + labelId + '">' + _esc(label) + '</span>' +
      '<select class="qym-control qym-select pg-example-picker-filter-select" data-example-filter-select data-example-filter-key="' + _escAttr(key) + '" aria-labelledby="' + labelId + '" aria-label="' + _escAttr(label + ' filter') + '">' +
        optionHtml +
      '</select>' +
    '</div>';
  }

  function _examplePickerSourceControl(state) {
    var source = String((state.filters && state.filters.source) || '');
    return '<div class="pg-example-picker-source" role="group" aria-label="Example source filter">' +
      '<span class="pg-filter-label">Source</span>' +
      '<div class="qym-segmented" data-qym-segmented-key="pg-example-source">' +
        '<button class="qym-segmented__option" type="button" data-example-source="" aria-pressed="' + (!source ? 'true' : 'false') + '">All</button>' +
        '<button class="qym-segmented__option" type="button" data-example-source="ai_only" aria-pressed="' + (source === 'ai_only' ? 'true' : 'false') + '">AI only</button>' +
        '<button class="qym-segmented__option" type="button" data-example-source="human_only" aria-pressed="' + (source === 'human_only' ? 'true' : 'false') + '">Human only</button>' +
        '<button class="qym-segmented__option" type="button" data-example-source="corrected" aria-pressed="' + (source === 'corrected' ? 'true' : 'false') + '">Corrected</button>' +
      '</div>' +
      '</div>';
  }

  function _examplePickerFieldSelector(state) {
    var selected = state.exampleFields || new Set(_approvedExampleFieldKeys());
    var selectedCount = selected.size;
    var isOpen = Boolean(state.exampleFieldsOpen);
    return '<div class="pg-example-picker-fields" role="group" aria-labelledby="pg-example-picker-fields-title">' +
      '<button class="qym-inline-action qym-inline-action--accent pg-example-picker-fields-trigger" type="button" data-example-fields-toggle aria-expanded="' + (isOpen ? 'true' : 'false') + '" aria-controls="pg-example-picker-fields-panel">' +
        '<span class="pg-example-picker-fields-trigger-copy">' + _icon('edit') + '<span class="pg-example-picker-fields-trigger-label" id="pg-example-picker-fields-title">Choose prompt fields</span><span class="pg-example-picker-fields-count">' + selectedCount + ' selected</span></span>' +
        '<span class="pg-example-picker-fields-chevron" aria-hidden="true">' + (isOpen ? '▴' : '▾') + '</span>' +
      '</button>' +
      (isOpen ? '<div class="pg-mapping-additional pg-example-picker-fields-panel" id="pg-example-picker-fields-panel">' +
        '<div class="pg-example-picker-fields-head"><div><span class="pg-example-picker-fields-help">Choose what the rule writer sees from each approved example.</span></div>' +
          '<div class="pg-example-picker-fields-actions"><button class="qym-inline-action qym-inline-action--neutral" type="button" data-example-fields-action="all">Select all</button><button class="qym-inline-action qym-inline-action--neutral" type="button" data-example-fields-action="none">Clear</button></div></div>' +
        '<div class="pg-example-picker-fields-options">' +
          _APPROVED_EXAMPLE_FIELD_DEFINITIONS.map(function (field) {
            return _fieldToggleMarkup(field, selected.has(field.key), 'data-example-prompt-field');
          }).join('') +
        '</div>' +
      '</div>' : '') +
    '</div>';
  }

  function _examplePickerRow(example) {
    var id = Number(example.id);
    _approvedExampleCharacterById[id] = Number(example.source_characters || 0);
    var checked = _selectedApprovedExampleIds.has(id);
    var user = example.corrected_by || example.reviewed_by;
    var userText = user ? (user.display_name || user.email || user.id) : 'Unknown user';
    var categories = Array.isArray(example.root_causes) ? example.root_causes.join(', ') : '';
    var confidenceValue = Number(example.confidence);
    var confidence = Number.isFinite(confidenceValue)
      ? Math.round((confidenceValue <= 1 ? confidenceValue * 100 : confidenceValue)) + '%'
      : '—';
    var source = String(example.source || 'Unknown');
    var sourceTone = source === 'Corrected' ? 'success' : (source === 'Human' ? 'info' : 'neutral');
    return '<div class="pg-example-picker-row" role="row">' +
      '<div class="pg-example-picker-select" role="cell"><label class="pg-example-picker-check" aria-label="Select approved example ' + _escAttr(id) + '">' +
        '<input type="checkbox" data-approved-example-id="' + _escAttr(id) + '"' + (checked ? ' checked' : '') + ' />' +
        '<span class="pg-document-check" aria-hidden="true"></span></label></div>' +
      '<div class="pg-example-picker-main" role="cell"><strong>#' + _esc(id) + ' · ' + _esc(example.item_id || 'item') + '</strong><span>' + _esc(categories || example.detail || 'Approved correction') + '</span></div>' +
      '<div class="pg-example-picker-context" role="cell"><span>' + _esc(example.task || '—') + '</span><span>' + _esc(example.dataset || '—') + ' · ' + _esc(example.model || '—') + '</span></div>' +
      '<div class="pg-example-picker-user" role="cell"><span>' + _esc(userText) + '</span><span>' + _esc(example.run_name || '—') + '</span></div>' +
      '<div class="pg-example-picker-confidence-value" role="cell">' + _esc(confidence) + '</div>' +
      '<div class="pg-example-picker-source-value" role="cell"><span class="qym-tag qym-tag--' + sourceTone + '">' + _esc(source) + '</span></div>' +
      '<div class="pg-example-picker-size" role="cell">' + Number(example.source_characters || 0).toLocaleString() + ' chars</div>' +
    '</div>';
  }

  function _examplePickerFilteredSelection(data) {
    var sourceIds = data && Array.isArray(data.matching_ids)
      ? data.matching_ids
      : (data && data.examples || []).map(function (example) { return example.id; });
    var matchingIds = sourceIds.map(function (id) { return Number(id); }).filter(function (id) { return Number.isFinite(id); });
    var selectedCount = matchingIds.filter(function (id) { return _selectedApprovedExampleIds.has(id); }).length;
    return {
      ids: matchingIds,
      all: matchingIds.length > 0 && selectedCount === matchingIds.length,
      some: selectedCount > 0 && selectedCount < matchingIds.length,
    };
  }

  function _renderApprovedExamplePicker() {
    if (!_examplePickerOverlay || !_examplePickerState) return;
    var state = _examplePickerState;
    var data = state.data || { examples: [], total: 0, page: state.page, page_size: state.pageSize, page_count: 0, facets: { tasks: [], datasets: [], models: [], run_names: [], users: [] } };
    var limits = _analysisLimits();
    var selectedCharacters = Number(data.selected_characters != null ? data.selected_characters : _selectedApprovedExampleCharacters);
    _selectedApprovedExampleCharacters = selectedCharacters;
    var exampleLimit = Number(limits.rule_writer_example_characters || 256000);
    var overBudget = selectedCharacters > exampleLimit;
    var facets = data.facets || {};
    var selectedCount = _selectedApprovedExampleCount();
    var filteredSelection = _examplePickerFilteredSelection(data);
    var progress = exampleLimit > 0 ? Math.min(100, Math.round((selectedCharacters / exampleLimit) * 100)) : 0;
    var progressValue = Math.min(selectedCharacters, exampleLimit);
    var viewSelected = Boolean(state.viewSelected);
    var activeFilterEntries = _examplePickerActiveFilterEntries(state);
    var activeFilterCount = activeFilterEntries.length;
    var filterPanelOpen = Boolean(state.filtersOpen);
    var dialog = _examplePickerOverlay.querySelector('.pg-example-picker-dialog');
    if (!dialog) return;
    dialog.innerHTML =
      '<div class="pg-example-picker-header">' +
        '<div><p class="pg-eyebrow">Approved example library</p><h2 id="pg-example-picker-title">Choose examples for rule writing</h2>' +
        '<p class="pg-example-picker-lead">Selections persist across pages and filters.</p></div>' +
        '<button class="pg-example-picker-close qym-icon-action" type="button" data-example-picker-close aria-label="Close example picker">×</button>' +
      '</div>' +
      '<div class="pg-example-picker-scroll">' +
      '<div class="pg-example-picker-filters" role="search" aria-label="Filter approved examples">' +
        '<div class="pg-example-picker-filter-heading">' +
          '<div class="pg-example-picker-filter-heading-copy"><h3 class="pg-example-picker-filter-title">Filter approved examples</h3><p class="pg-example-picker-filter-help">Choose one value in each list. Filters from different lists are combined.</p></div>' +
          '<div class="pg-example-picker-filter-heading-actions"><span class="pg-example-picker-active-filter-count"><strong>' + activeFilterCount.toLocaleString() + '</strong> active</span><button class="qym-inline-action qym-inline-action--neutral" type="button" data-example-clear-all' + (activeFilterCount ? '' : ' disabled') + '>Clear all</button></div>' +
        '</div>' +
        '<div class="pg-example-picker-search-row">' +
          '<label class="pg-example-picker-search"><span class="pg-visually-hidden">Search examples</span><input class="qym-control qym-input qym-search" type="search" data-example-search placeholder="Search examples" aria-label="Search examples" value="' + _escAttr((state.filters && state.filters.search) || '') + '" /></label>' +
          '<button class="qym-control pg-example-picker-filter-panel-trigger" type="button" data-example-filter-panel-trigger aria-expanded="' + (filterPanelOpen ? 'true' : 'false') + '" aria-haspopup="true" aria-controls="pg-example-picker-filter-panel-menu"><span class="pg-example-picker-filter-panel-trigger-label">' + (filterPanelOpen ? 'Hide filters' : 'Show filters') + '</span>' + (activeFilterCount ? '<span class="qym-tag qym-tag--accent pg-example-picker-filter-count">' + activeFilterCount + '</span>' : '') + '</button>' +
        '</div>' +
        '<div class="pg-example-picker-filter-panel' + (filterPanelOpen ? ' is-open' : '') + '" data-example-filter-panel>' +
          '<div class="pg-example-picker-filter-panel-menu" id="pg-example-picker-filter-panel-menu" role="region" aria-label="Example filters">' +
            '<div class="pg-example-picker-filter-section" aria-labelledby="pg-example-picker-dimension-heading">' +
              '<div class="pg-example-picker-filter-section-heading"><span class="pg-example-picker-filter-section-title" id="pg-example-picker-dimension-heading">Example dimensions</span><span class="pg-example-picker-filter-section-help">Each selector accepts one value.</span></div>' +
              '<div class="pg-example-picker-dimension-filters">' +
                _examplePickerDropdown(state, 'task', 'Task', facets.tasks) +
                _examplePickerDropdown(state, 'dataset', 'Dataset', facets.datasets) +
                _examplePickerDropdown(state, 'model', 'Model', facets.models) +
                _examplePickerDropdown(state, 'run_name', 'Run', facets.run_names) +
                _examplePickerDropdown(state, 'user_id', 'User', facets.users, function (user) { return user.display_name || user.email || user.id; }) +
              '</div>' +
            '</div>' +
            '<div class="pg-example-picker-filter-section" aria-labelledby="pg-example-picker-secondary-heading">' +
              '<div class="pg-example-picker-filter-section-heading"><span class="pg-example-picker-filter-section-title" id="pg-example-picker-secondary-heading">Additional filters</span><span class="pg-example-picker-filter-section-help">Source is a single category; confidence uses a range.</span></div>' +
              '<div class="pg-example-picker-secondary-filters">' +
                _examplePickerSourceControl(state) +
                '<div class="pg-example-picker-confidence"><span class="pg-filter-label">Confidence range</span><div class="pg-example-picker-confidence-inputs"><label class="pg-example-picker-confidence-field"><span>From</span><input class="qym-control" type="number" min="0" max="100" data-example-conf-min value="' + _escAttr(state.filters.conf_min) + '" placeholder="0" aria-label="Minimum confidence percentage" /></label><span class="pg-example-picker-confidence-separator" aria-hidden="true">to</span><label class="pg-example-picker-confidence-field"><span>To</span><input class="qym-control" type="number" min="0" max="100" data-example-conf-max value="' + _escAttr(state.filters.conf_max) + '" placeholder="100" aria-label="Maximum confidence percentage" /></label></div></div>' +
              '</div>' +
            '</div>' +
          '</div>' +
        '</div>' +
        _examplePickerFilterChips(state) +
      '</div>' +
      _examplePickerFieldSelector(state) +
      '<div class="pg-example-picker-actions"><span class="pg-example-picker-selection-count" role="status" aria-live="polite"><strong>' + selectedCount.toLocaleString() + '</strong> selected</span></div>' +
      '<div class="pg-example-picker-table" role="table" aria-label="Approved examples">' +
        '<div class="pg-example-picker-table-head" role="row"><div class="pg-example-picker-page-select" role="columnheader"><label class="pg-example-picker-check" aria-label="Select all filtered examples"><input type="checkbox" data-example-select-filtered-toggle /><span class="pg-document-check" aria-hidden="true"></span></label><span class="pg-example-picker-table-menu-wrap" data-example-table-menu-wrap><button class="pg-example-picker-table-menu-trigger qym-icon-action" type="button" data-example-table-menu-trigger aria-expanded="false" aria-haspopup="menu" aria-controls="pg-example-picker-selection-menu" aria-label="Example selection actions"><span aria-hidden="true">▾</span></button><span class="pg-example-picker-table-menu" id="pg-example-picker-selection-menu" role="menu" aria-label="Example selection actions"><button class="pg-example-picker-table-menu-item" type="button" role="menuitem" data-example-select-filtered>Select all filtered (' + Number(data.total || 0).toLocaleString() + ')</button><button class="pg-example-picker-table-menu-item" type="button" role="menuitem" data-example-clear-filtered>Clear filtered</button></span></span></div><span role="columnheader">Example</span><span role="columnheader">Context</span><span role="columnheader">User / run</span><span role="columnheader">Confidence</span><span role="columnheader">Source</span><span role="columnheader">Size</span></div>' +
        (state.loading ? '<div class="pg-example-picker-empty">Loading approved examples…</div>' : (state.error ? '<div class="pg-example-picker-empty pg-budget-over">' + _esc(state.error) + '</div>' : ((data.examples || []).map(_examplePickerRow).join('') || '<div class="pg-example-picker-empty">No approved examples match these filters.</div>'))) +
      '</div>' +
      '</div>' +
      '<div class="pg-example-picker-footer">' +
        '<div class="pg-example-picker-budget' + (overBudget ? ' pg-example-picker-budget-over' : '') + '" role="status" aria-label="Selected example character budget" aria-live="polite"><span class="pg-example-picker-budget-value"><strong>' + selectedCharacters.toLocaleString() + ' / ' + exampleLimit.toLocaleString() + '</strong> chars</span><div class="pg-example-picker-budget-track" role="progressbar" aria-label="Selected example character budget" aria-valuemin="0" aria-valuemax="' + exampleLimit + '" aria-valuenow="' + progressValue + '" aria-valuetext="' + _escAttr(selectedCharacters.toLocaleString() + ' of ' + exampleLimit.toLocaleString() + ' characters') + '"><span class="pg-example-picker-budget-progress" style="width: ' + progress + '%"></span></div></div>' +
        '<div class="pg-example-picker-footer-pagination"><div class="qym-pagination" id="pg-example-picker-pagination" role="navigation" aria-label="Approved example pagination"></div></div>' +
        '<div class="pg-example-picker-footer-actions"><button class="qym-inline-action pg-example-picker-view-selected" type="button" data-example-view-selected>' + (viewSelected ? 'Show all examples' : 'View selected') + '</button><button class="qym-inline-action qym-inline-action--accent" type="button" data-example-picker-apply' + (selectedCount > 0 && (!state.exampleFields || state.exampleFields.size === 0) ? ' disabled' : '') + '>Use ' + selectedCount + ' selected example' + (selectedCount === 1 ? '' : 's') + (overBudget ? ' in patches' : '') + '</button></div>' +
      '</div>';
    var pagination = dialog.querySelector('#pg-example-picker-pagination');
    if (pagination && window.QymUIComponents && typeof window.QymUIComponents.renderPagination === 'function') {
      window.QymUIComponents.renderPagination(pagination, {
        total: Number(data.total || 0),
        pageSize: state.pageSize,
        page: Math.max(1, Number(data.page || state.page) || 1),
        onPageChange: function (nextPage) {
          if (!_examplePickerState) return;
          _examplePickerState.page = nextPage;
          _loadApprovedExamplePicker();
        },
      });
    }
    var filteredCheckbox = dialog.querySelector('[data-example-select-filtered-toggle]');
    if (filteredCheckbox) {
      filteredCheckbox.checked = filteredSelection.all;
      filteredCheckbox.indeterminate = filteredSelection.some;
      filteredCheckbox.disabled = filteredSelection.ids.length === 0;
    }
    if (window.QymUIComponents && typeof window.QymUIComponents.enhanceSelects === 'function') {
      window.QymUIComponents.enhanceSelects(dialog, 'select[data-example-filter-select]', function (select) {
        return {
          className: 'pg-example-picker-review-selector',
          label: select.getAttribute('aria-label') || 'Example filter',
          search: select.options.length > 8,
          highlightSelection: true,
        };
      });
    }
    if (window.QymUIComponents && typeof window.QymUIComponents.refresh === 'function') {
      window.QymUIComponents.refresh(dialog);
    }
  }

  function _loadApprovedExamplePicker() {
    if (!_examplePickerState) return Promise.resolve();
    var state = _examplePickerState;
    var requestGeneration = (state.loadGeneration || 0) + 1;
    state.loadGeneration = requestGeneration;
    state.loading = true;
    _renderApprovedExamplePicker();
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    return fetch(base(_analysisContextPath('analysis-examples')), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(_examplePickerPayload(state)),
    })
      .then(function (response) {
        return response.text().then(function (text) {
          var payload = {};
          try { payload = text ? JSON.parse(text) : {}; } catch (error) {}
          if (!response.ok) throw new Error(_responseErrorMessage(payload, text || 'Could not load approved examples'));
          return payload;
        });
      })
      .then(function (data) {
        if (!_examplePickerState || _examplePickerState !== state || state.loadGeneration !== requestGeneration) return;
        state.loading = false;
        state.error = '';
        state.data = data || {};
        (state.data.examples || []).forEach(function (example) {
          _approvedExampleCharacterById[Number(example.id)] = Number(example.source_characters || 0);
        });
        _selectedApprovedExampleCharacters = Number(state.data.selected_characters || 0);
        _renderApprovedExamplePicker();
      })
      .catch(function (error) {
        if (!_examplePickerState || _examplePickerState !== state || state.loadGeneration !== requestGeneration) return;
        state.loading = false;
        state.error = error.message || 'Could not load approved examples.';
        _renderApprovedExamplePicker();
        if (_opts.showToast) _opts.showToast('error', 'Example Picker Failed', state.error);
      });
  }

  function _closeApprovedExamplePicker() {
    if (!_examplePickerOverlay) return;
    var opener = _examplePickerOpener;
    _examplePickerOverlay.remove();
    _examplePickerOverlay = null;
    _examplePickerState = null;
    _examplePickerOpener = null;
    _syncInferenceSourceSummary();
    if (opener) opener.setAttribute('aria-expanded', 'false');
    if (opener && typeof opener.focus === 'function') opener.focus();
  }

  function _setExamplePickerFilterPanelOpen(open) {
    if (!_examplePickerOverlay) return;
    var panel = _examplePickerOverlay.querySelector('[data-example-filter-panel]');
    if (!panel) return;
    var isOpen = Boolean(open);
    panel.classList.toggle('is-open', isOpen);
    var trigger = _examplePickerOverlay.querySelector('[data-example-filter-panel-trigger]');
    if (trigger) {
      trigger.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
      var triggerLabel = trigger.querySelector('.pg-example-picker-filter-panel-trigger-label');
      if (triggerLabel) triggerLabel.textContent = isOpen ? 'Hide filters' : 'Show filters';
    }
    if (_examplePickerState) {
      _examplePickerState.filtersOpen = isOpen;
      if (!isOpen) _examplePickerState.openFilterKey = '';
    }
  }

  function _setExamplePickerTableMenuOpen(open) {
    if (!_examplePickerOverlay) return;
    var menuWrap = _examplePickerOverlay.querySelector('[data-example-table-menu-wrap]');
    if (!menuWrap) return;
    var isOpen = Boolean(open);
    menuWrap.classList.toggle('is-open', isOpen);
    var trigger = menuWrap.querySelector('[data-example-table-menu-trigger]');
    if (trigger) trigger.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
  }

  function _openApprovedExamplePicker() {
    if (_examplePickerOverlay) return;
    _examplePickerOpener = document.getElementById('pg-add-examples');
    if (_examplePickerOpener) _examplePickerOpener.setAttribute('aria-expanded', 'true');
    _examplePickerState = {
      page: 1,
      pageSize: 20,
      loading: true,
      data: null,
      filters: {
        search: '',
        task: [],
        dataset: [],
        model: [],
        run_name: [],
        user_id: [],
        source: '',
        conf_min: 0,
        conf_max: 100,
      },
      viewSelected: false,
      exampleFields: new Set(_selectedApprovedExampleFields),
      exampleFieldsOpen: false,
      filtersOpen: false,
      openFilterKey: '',
    };
    var overlay = document.createElement('div');
    overlay.className = 'pg-example-picker-backdrop';
    overlay.innerHTML = '<div class="pg-example-picker-dialog" role="dialog" aria-modal="true" aria-labelledby="pg-example-picker-title" tabindex="-1"></div>';
    (_overlay || document.body).appendChild(overlay);
    _examplePickerOverlay = overlay;
    overlay.addEventListener('click', function (event) {
      if (event.target === overlay || event.target.closest('[data-example-picker-close]')) {
        _closeApprovedExamplePicker();
        return;
      }
      var filterPanelTrigger = event.target.closest('[data-example-filter-panel-trigger]');
      if (filterPanelTrigger) {
        _setExamplePickerTableMenuOpen(false);
        _setExamplePickerFilterPanelOpen(filterPanelTrigger.getAttribute('aria-expanded') !== 'true');
        return;
      }
      var tableMenuTrigger = event.target.closest('[data-example-table-menu-trigger]');
      if (tableMenuTrigger) {
        _setExamplePickerFilterPanelOpen(false);
        _setExamplePickerTableMenuOpen(!tableMenuTrigger.closest('[data-example-table-menu-wrap]').classList.contains('is-open'));
        return;
      }
      if (!event.target.closest('.qym-review-selector') && _examplePickerState) _examplePickerState.openFilterKey = '';
      if (!event.target.closest('[data-example-filter-panel]') && !event.target.closest('.pg-example-picker-filters') && !event.target.closest('.pg-example-picker-fields')) _setExamplePickerFilterPanelOpen(false);
      if (!event.target.closest('[data-example-table-menu-wrap]')) _setExamplePickerTableMenuOpen(false);
      var clearAll = event.target.closest('[data-example-clear-all]');
      if (clearAll) {
        _examplePickerState.filters = {
          search: '',
          task: [],
          dataset: [],
          model: [],
          run_name: [],
          user_id: [],
          source: '',
          conf_min: 0,
          conf_max: 100,
        };
        _examplePickerState.openFilterKey = '';
        _examplePickerState.page = 1;
        _loadApprovedExamplePicker();
        return;
      }
      var clearFilter = event.target.closest('[data-example-clear-filter]');
      if (clearFilter) {
        var filterKeyToClear = clearFilter.dataset.exampleClearFilter;
        if (filterKeyToClear === 'source') _examplePickerState.filters.source = '';
        else if (filterKeyToClear === 'confidence') {
          _examplePickerState.filters.conf_min = 0;
          _examplePickerState.filters.conf_max = 100;
        } else if (filterKeyToClear === 'search') {
          _examplePickerState.filters.search = '';
        } else if (_examplePickerState.filters[filterKeyToClear]) {
          _examplePickerState.filters[filterKeyToClear] = [];
        }
        _examplePickerState.openFilterKey = '';
        _examplePickerState.page = 1;
        _loadApprovedExamplePicker();
        return;
      }
      var source = event.target.closest('[data-example-source]');
      if (source) {
        _examplePickerState.filters.source = source.dataset.exampleSource || '';
        _examplePickerState.page = 1;
        _loadApprovedExamplePicker();
        return;
      }
      var selectFiltered = event.target.closest('[data-example-select-filtered]');
      if (selectFiltered) {
        _examplePickerFilteredSelection(_examplePickerState.data || {}).ids.forEach(function (id) { _selectedApprovedExampleIds.add(id); });
        _loadApprovedExamplePicker();
        return;
      }
      var clearFiltered = event.target.closest('[data-example-clear-filtered]');
      if (clearFiltered) {
        _examplePickerFilteredSelection(_examplePickerState.data || {}).ids.forEach(function (id) { _selectedApprovedExampleIds.delete(id); });
        _loadApprovedExamplePicker();
        return;
      }
      var viewSelected = event.target.closest('[data-example-view-selected]');
      if (viewSelected) {
        _examplePickerState.viewSelected = !_examplePickerState.viewSelected;
        _examplePickerState.page = 1;
        _loadApprovedExamplePicker();
        return;
      }
      var fieldsToggle = event.target.closest('[data-example-fields-toggle]');
      if (fieldsToggle) {
        _examplePickerState.exampleFieldsOpen = !_examplePickerState.exampleFieldsOpen;
        _renderApprovedExamplePicker();
        return;
      }
      var fieldAction = event.target.closest('[data-example-fields-action]');
      if (fieldAction) {
        _examplePickerState.exampleFields = fieldAction.dataset.exampleFieldsAction === 'all'
          ? new Set(_approvedExampleFieldKeys())
          : new Set();
        _renderApprovedExamplePicker();
        return;
      }
      var pageButton = event.target.closest('[data-qym-page]');
      if (pageButton && !pageButton.disabled) {
        var nextPage = Number(pageButton.dataset.qymPage);
        if (Number.isFinite(nextPage) && nextPage >= 0) {
          _examplePickerState.page = nextPage + 1;
          _loadApprovedExamplePicker();
        }
        return;
      }
      var apply = event.target.closest('[data-example-picker-apply]');
      if (apply && !apply.disabled) {
        _selectedApprovedExampleFields = new Set(_examplePickerState.exampleFields || []);
        _closeApprovedExamplePicker();
      }
    });
    overlay.addEventListener('change', function (event) {
      var filteredCheckbox = event.target.closest('[data-example-select-filtered-toggle]');
      if (filteredCheckbox) {
        var filteredIds = _examplePickerFilteredSelection((_examplePickerState.data || {})).ids;
        filteredIds.forEach(function (id) {
          if (filteredCheckbox.checked) _selectedApprovedExampleIds.add(id);
          else _selectedApprovedExampleIds.delete(id);
        });
        _loadApprovedExamplePicker();
        return;
      }
      var checkbox = event.target.closest('[data-approved-example-id]');
      if (checkbox) {
        var id = Number(checkbox.dataset.approvedExampleId);
        if (checkbox.checked) _selectedApprovedExampleIds.add(id);
        else _selectedApprovedExampleIds.delete(id);
        _loadApprovedExamplePicker();
        return;
      }
      var fieldCheckbox = event.target.closest('[data-example-prompt-field]');
      if (fieldCheckbox) {
        var fieldKey = String(fieldCheckbox.dataset.examplePromptField || '');
        if (!_examplePickerState.exampleFields) _examplePickerState.exampleFields = new Set();
        if (fieldCheckbox.checked) _examplePickerState.exampleFields.add(fieldKey);
        else _examplePickerState.exampleFields.delete(fieldKey);
        _renderApprovedExamplePicker();
        return;
      }
      var filterSelect = event.target.closest('[data-example-filter-select]');
      if (filterSelect) {
        var key = filterSelect.dataset.exampleFilterKey;
        var value = String(filterSelect.value || '');
        _examplePickerState.filters[key] = value ? [value] : [];
        _examplePickerState.openFilterKey = '';
        _examplePickerState.page = 1;
        _loadApprovedExamplePicker();
        return;
      }
      var confMin = event.target.closest('[data-example-conf-min]');
      var confMax = event.target.closest('[data-example-conf-max]');
      if (confMin || confMax) {
        _examplePickerState.filters.conf_min = Math.max(0, Math.min(100, Number((overlay.querySelector('[data-example-conf-min]') || {}).value || 0)));
        _examplePickerState.filters.conf_max = Math.max(0, Math.min(100, Number((overlay.querySelector('[data-example-conf-max]') || {}).value || 100)));
        _examplePickerState.openFilterKey = '';
        _examplePickerState.page = 1;
        _loadApprovedExamplePicker();
      }
    });
    overlay.addEventListener('input', function (event) {
      var search = event.target.closest('[data-example-search]');
      if (!search) return;
      _examplePickerState.filters.search = search.value;
      _examplePickerState.openFilterKey = '';
      if (_examplePickerState.searchTimer) clearTimeout(_examplePickerState.searchTimer);
      _examplePickerState.searchTimer = setTimeout(function () {
        _examplePickerState.page = 1;
        _loadApprovedExamplePicker();
      }, 250);
    });
    overlay.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        if (overlay.querySelector('.qym-review-selector .multi-select-dropdown.open')) {
          if (_examplePickerState) _examplePickerState.openFilterKey = '';
          return;
        }
        if (overlay.querySelector('[data-example-table-menu-wrap].is-open')) {
          event.preventDefault();
          event.stopPropagation();
          _setExamplePickerTableMenuOpen(false);
          var tableMenuTrigger = overlay.querySelector('[data-example-table-menu-trigger]');
          if (tableMenuTrigger) tableMenuTrigger.focus();
          return;
        }
        if (overlay.querySelector('[data-example-filter-panel].is-open')) {
          event.preventDefault();
          event.stopPropagation();
          _setExamplePickerFilterPanelOpen(false);
          var filterPanelTrigger = overlay.querySelector('[data-example-filter-panel-trigger]');
          if (filterPanelTrigger) filterPanelTrigger.focus();
          return;
        }
        if (_examplePickerState && _examplePickerState.exampleFieldsOpen) {
          event.preventDefault();
          event.stopPropagation();
          _examplePickerState.exampleFieldsOpen = false;
          _renderApprovedExamplePicker();
          return;
        }
        event.preventDefault();
        event.stopPropagation();
        _closeApprovedExamplePicker();
      }
    });
    _renderApprovedExamplePicker();
    _loadApprovedExamplePicker();
    setTimeout(function () {
      var dialog = overlay.querySelector('.pg-example-picker-dialog');
      if (dialog) dialog.focus();
    }, 0);
  }

  function _buildScrollContent() {
    var cats = (_config && _config.default_categories) || [
      'Hallucination', 'Incomplete Answer', 'Wrong Format', 'Context Missing',
      'Reasoning Error', 'Tool Use Error', 'Instruction Following', 'Knowledge Gap',
      'Dataset Issue',
    ];
    var html = '<div class="pg-workspace">';

    var sourceState = _inferenceSourceState();
    var inferenceDisabled = sourceState.hasUsableSource ? '' : ' disabled';
    var rulesBody = '<div class="pg-rule-source-actions" role="group" aria-label="Rule sources">' +
        '<label class="pg-rule-source-checkbox">' +
          '<input id="pg-infer-use-documents" type="checkbox" checked />' +
          '<span class="pg-document-check" aria-hidden="true"></span>' +
          '<span>Add documents</span>' +
        '</label>' +
        '<button class="pg-example-source-control" id="pg-add-examples" type="button" aria-haspopup="dialog" aria-expanded="false" aria-label="Add approved examples">Add examples</button>' +
      '</div>' +
      '<div class="pg-rule-empty pg-rule-inference-empty" id="pg-infer-source-empty" role="alert" hidden></div>' +
      '<div class="pg-rule-filters" id="pg-rule-filters" role="search" aria-label="Filter rules">' +
        '<label class="pg-rule-filter-field pg-rule-filter-search"><span class="pg-visually-hidden">Search rules</span><input class="qym-control qym-input qym-search" id="pg-rule-search" type="search" placeholder="Search rules" autocomplete="off" /></label>' +
      '</div>' +
      '<div class="pg-rule-list" id="pg-rule-list">' + _buildAnalysisRulesEditor() + '</div>' +
      '<div class="qym-pagination" id="pg-rule-pagination" role="navigation" aria-label="Rule list pagination"></div>' +
      '<div class="pg-rule-version-actions" id="pg-rule-version-actions" role="group" aria-label="Selected version actions" hidden></div>' +
      '<div class="pg-rule-editor-actions">' +
        '<span class="pg-rule-count" id="pg-rule-count" aria-live="polite">' + _formatRuleCount() + '</span>' +
        '<button class="qym-inline-action qym-inline-action--neutral" id="pg-add-rule" type="button" title="Add rule" aria-label="Add rule">' + _icon('plus') + '<span>Add rule</span></button>' +
      '</div>' +
      '<div class="pg-context-divider"></div>' +
      '<h3 class="pg-context-title">Version history</h3>' +
      '<div class="pg-rule-version-list" id="pg-rule-version-list">' + _buildRuleVersionHistory() + '</div>' +
      '<div class="pg-rule-compare" id="pg-rule-version-compare" hidden></div>';
    html += '<section class="pg-context-panel" aria-labelledby="pg-context-title">' +
      '<h2 class="pg-context-title" id="pg-context-title">Analysis rules</h2>' + rulesBody +
      '<div class="pg-context-actions">' +
        '<div class="pg-context-action-group pg-context-action-group-manual" aria-label="Manual rule actions">' +
          '<button class="pg-context-secondary" id="pg-create-rule-version" type="button">Create draft</button>' +
        '</div>' +
        '<span class="pg-context-action-divider" aria-hidden="true"></span>' +
        '<div class="pg-context-action-group pg-context-action-group-generation" aria-label="Rule generation actions">' +
          '<button class="pg-context-primary" id="pg-infer-rules" type="button"' + inferenceDisabled + ' title="Generate additional non-redundant rules from the selected sources">Generate rules</button>' +
        '</div>' +
      '</div>' +
      '<div class="pg-context-status" id="pg-context-status" role="status" aria-live="polite"></div>' +
      '<div class="pg-context-feedback" id="pg-context-feedback" role="status" aria-live="polite" hidden></div>' +
    '</section>';
    html += '<div class="pg-analysis-main">';

    // ── Reference Documents ──
    var documentsBody = '';
    documentsBody += '<div class="pg-instructions-hint">Choose which documents belong in project analysis. The run workspace can then include or exclude all enabled documents with one switch. A document over ' + Number(_documentPerFilePromptLimit()).toLocaleString() + ' characters is called out before it is saved.</div>';
    documentsBody += '<label class="pg-document-dropzone" id="pg-document-dropzone" for="pg-document-input" role="button" tabindex="0" aria-controls="pg-document-input" aria-label="Upload project documents">' +
      '<span class="pg-document-upload-title">Choose documents or drop them here</span>' +
      '<span class="pg-document-upload-help">PDF, DOCX, TXT, Markdown, HTML, CSV, JSON, or YAML · up to 10 MB each · larger text requires a decision</span>' +
    '</label>';
    documentsBody += '<input class="pg-document-input" id="pg-document-input" type="file" multiple accept=".pdf,.docx,.txt,.text,.md,.markdown,.html,.htm,.csv,.json,.yaml,.yml,.log,.rst" aria-label="Choose project documents" />';
    documentsBody += '<div class="pg-document-upload-status" id="pg-document-upload-status" role="status" aria-live="polite"></div>';
    documentsBody += '<div class="pg-document-budget" id="pg-document-budget" role="status" aria-live="polite"></div>';
    documentsBody += '<div class="pg-document-list" id="pg-document-list">' + _buildReferenceDocumentList() + '</div>';
    var enabledDocumentCount = _referenceDocuments.filter(function (document) { return document.selected !== false; }).length;
    html += _section('Project documents', documentsBody, { badge: enabledDocumentCount + ' of ' + _referenceDocuments.length + ' enabled', badgeId: 'pg-documents-badge' });

    // ── Additional Instructions ──
    var instrBody = '';
    instrBody += '<div class="pg-instructions-hint">Customize how the AI analyzes items. Use <code>{variable_name}</code> to reference item data \u2014 detected variables appear in Variable Mapping below.</div>';
    instrBody += '<textarea class="pg-instructions-textarea" id="pg-additional-instructions" dir="auto" placeholder="e.g. Focus on whether the response addresses all parts of the question.\nPay special attention to the {rubric} criteria." spellcheck="false"></textarea>';
    html += _section('Additional Instructions', instrBody);

    // ── Root Cause Categories & Details ──
    var detailsMap = (_config && _config.category_details_map) || {};
    var categoryTaxonomy = (_config && (_config.category_taxonomy || _config.category_taxonomies)) || {};
    var categoryExamples = (_config && _config.category_examples) || {};
    var totalDetails = 0;
    var catDetBody = '';
    catDetBody += '<div class="pg-category-workspace" id="pg-category-workspace">';
    catDetBody += '<aside class="pg-category-sidebar" aria-labelledby="pg-category-sidebar-title"><div class="pg-category-sidebar-heading"><h3 id="pg-category-sidebar-title">Categories</h3></div><nav class="pg-category-nav" id="pg-category-nav" aria-label="Diagnosis categories"></nav>' +
      '<p class="pg-category-nav-empty" id="pg-category-nav-empty" hidden>No categories configured yet.</p><span class="pg-visually-hidden" id="pg-category-nav-count">0</span></aside>';
    var maxCategories = Number(_config && _config.max_root_cause_categories);
    if (!Number.isFinite(maxCategories) || maxCategories < 1) {
      maxCategories = _DEFAULT_MAX_ROOT_CAUSE_CATEGORIES;
    }
    maxCategories = Math.min(_MAX_ROOT_CAUSE_CATEGORIES, Math.max(1, Math.trunc(maxCategories)));
    catDetBody += '<div class="pg-category-editor"><div class="pg-category-editor-toolbar"><div class="pg-category-editor-heading"><span class="pg-category-panel-kicker">Category catalog</span><strong id="pg-category-active-name">Select a category</strong><span>Changes apply to future analyses after you save the catalog.</span></div>' +
      '<div class="pg-add-category-form"><label class="pg-visually-hidden" for="pg-new-category">New category</label><input type="text" id="pg-new-category" placeholder="New category..." class="pg-add-input qym-control qym-input" required aria-required="true" hidden /><button id="pg-add-category-btn" class="pg-add-btn qym-inline-action qym-inline-action--neutral" type="button">' + _icon('plus') + '<span>Add category</span></button></div>' +
      '<div class="pg-category-limit-field" data-category-limit-field role="group" aria-labelledby="pg-max-root-cause-categories-label"><label class="pg-category-limit-label" id="pg-max-root-cause-categories-label" for="pg-max-root-cause-categories">Max categories per item</label><button class="qym-help-marker" type="button" aria-label="How the category limit works">i<span class="qym-help-tooltip" role="tooltip">Limits how many diagnosis categories the analyzer can return for each item. Higher values allow multiple independent causes.</span></button><input class="qym-control qym-input" id="pg-max-root-cause-categories" type="number" min="1" max="10" step="1" inputmode="numeric" value="' + maxCategories + '" /></div></div>' +
      '<div id="pg-categories-list">';
    for (var i = 0; i < cats.length; i++) {
      var cat = cats[i];
      var catDets = detailsMap[cat] || [];
      totalDetails += catDets.length;
      catDetBody += _buildCategoryGroup(cat, catDets, categoryExamples[cat] || [], categoryTaxonomy, 'category-' + i + '-' + _categoryDomKey(cat));
    }
    catDetBody += '</div>';
    catDetBody += '</div></div>';
    html += _section('Root Cause Categories & Details', catDetBody, { open: false, badge: cats.length + ' / ' + totalDetails });

    // ── Variable Mapping ──
    html += _buildVariableMapping();

    // ── Filter & Matched Items ──
    var matchedCount = _getMatchedItemCount(_getMatchedItems());
    var filterBody = '';
    filterBody += '<div class="pg-filter-row">';
    filterBody += '<div class="pg-filter-group">';
    filterBody += '<label class="pg-filter-label" for="pg-max-score">Max Score <span class="pg-filter-direction-note" id="pg-max-score-direction-note">(applies only to higher-is-better metrics)</span></label>';
    filterBody += '<div class="pg-slider-control">';
    filterBody += '<input type="range" id="pg-max-score" class="pg-score-slider" min="0" max="100" step="5" value="80" />';
    filterBody += '<span class="pg-slider-value" id="pg-max-score-value">80%</span>';
    filterBody += '</div>';
    filterBody += '</div>';
    filterBody += '<div class="pg-filter-options-group"><span class="pg-filter-label">Options</span><div class="pg-filter-options">';
    filterBody += '<label class="pg-filter-check"><span class="custom-checkbox"><input type="checkbox" id="pg-skip-analyzed" checked /><span class="checkmark"></span></span><span>Skip analyzed</span></label>';
    filterBody += '<label class="pg-filter-check"><span class="custom-checkbox"><input type="checkbox" id="pg-allow-human-overwrite" /><span class="checkmark"></span></span><span>Re-analyze human labels</span></label>';
    filterBody += '</div></div>';
    filterBody += '<div class="pg-filter-limit pg-target-limit-group"><label class="pg-filter-label" for="pg-target-limit">Analyze limit</label>' +
      '<div class="pg-target-limit-row">' +
        '<div class="pg-target-limit-control">' +
          '<input type="text" id="pg-target-limit" inputmode="numeric" pattern="[0-9]*" maxlength="4" placeholder="All" autocomplete="off" />' +
          '<div class="pg-target-limit-steppers" role="group" aria-label="Adjust analyze limit">' +
            '<button class="pg-target-limit-step" type="button" data-target-limit-step="increase" aria-label="Increase analyze limit" aria-controls="pg-target-limit">' + _icon('chevronUp') + '</button>' +
            '<button class="pg-target-limit-step" type="button" data-target-limit-step="decrease" aria-label="Decrease analyze limit" aria-controls="pg-target-limit">' + _icon('chevronDown') + '</button>' +
          '</div>' +
        '</div>' +
        '<div class="qym-pagination" id="pg-target-pagination" role="navigation" aria-label="Analysis target pagination" hidden></div>' +
      '</div></div>';
    filterBody += '</div>';
    filterBody += '<div id="pg-matched-section">';
    filterBody += _buildMatchedItemsTable();
    filterBody += '</div>';
    html += _section('Filter & Items', filterBody, { badge: String(matchedCount), badgeId: 'pg-filter-badge' });

    // ── Prompt Preview ──
    var previewBody = '';
    previewBody += '<div class="pg-preview-loading" id="pg-preview-loading" hidden>Generating preview\u2026</div>';
    previewBody += '<div id="pg-prompt-budget" class="pg-prompt-budget" role="status" aria-live="polite">Final prompt budget is enforced before each provider request.</div>';
    previewBody += '<div id="pg-preview-content" class="pg-prompt-preview-content">Loading prompt preview\u2026</div>';
    previewBody += '<div class="pg-preview-actions">' +
      '<button class="pg-toggle-expand qym-icon-action" id="pg-preview-toggle" type="button" hidden title="Expand prompt preview" aria-label="Expand prompt preview">' + _icon('expand') + '</button>' +
      '<button class="pg-copy-btn qym-icon-action" id="pg-preview-copy" type="button" title="Copy prompt to clipboard" aria-label="Copy prompt to clipboard">' + _icon('copy') + '</button>' +
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

  function _fieldToggleMarkup(field, checked, dataAttribute) {
    var attribute = dataAttribute || 'data-field';
    return '<label class="pg-field-toggle">' +
      '<span class="custom-checkbox"><input type="checkbox" ' + attribute + '="' + _escAttr(field.key) + '"' + (checked ? ' checked' : '') + ' /><span class="checkmark"></span></span>' +
      '<span>' + _esc(field.label) + '</span>' +
    '</label>';
  }

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
      body += _fieldToggleMarkup(extras[e], true);
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

  function _renderTargetPagination(matched) {
    var pagination = document.getElementById('pg-target-pagination');
    if (!pagination) return;
    if (!matched || matched.length === 0) {
      pagination.hidden = true;
      pagination.innerHTML = '';
      return;
    }
    var pageCount = Math.max(1, Math.ceil(matched.length / _PAGE_SIZE));
    _matchedPage = Math.min(pageCount - 1, Math.max(0, _matchedPage));
    pagination.hidden = false;
    if (!window.QymUIComponents || typeof window.QymUIComponents.renderPagination !== 'function') return;
    window.QymUIComponents.renderPagination(pagination, {
      total: matched.length,
      pageSize: _PAGE_SIZE,
      page: _matchedPage + 1,
      onPageChange: function (nextPage) {
        _matchedPage = Math.max(0, nextPage - 1);
        _refreshMatchedTable(true);
      },
    });
  }

  function _buildMatchedItemsTable() {
    var matched = _getMatchedItems();
    var threshold = _opts.getThreshold ? _opts.getThreshold() : 0.8;

    var html = '';
    if (matched.length === 0) {
      var skipEl = document.getElementById('pg-skip-analyzed');
      if (skipEl && skipEl.checked) {
        html += '<div class="pg-empty-msg pg-zero-target"><strong>All matching targets already have analysis.</strong><span>Include previously analyzed targets to run them again, or open Reviews to inspect the saved diagnoses.</span><div class="pg-zero-target-actions"><button class="qym-inline-action qym-inline-action--neutral" type="button" id="pg-include-analyzed">Include analyzed targets</button>' +
          (_opts.reviewsUrl ? '<a href="' + _escAttr(_opts.reviewsUrl) + '">Open Reviews</a>' : '') +
          '</div></div>';
      } else {
        html += '<div class="pg-empty-msg pg-zero-target"><strong>No targets match the current scope.</strong><span>Adjust the metrics or maximum score to widen the analysis.</span></div>';
      }
      return html;
    }

    var pageCount = Math.max(1, Math.ceil(matched.length / _PAGE_SIZE));
    _matchedPage = Math.min(pageCount - 1, Math.max(0, _matchedPage));
    var pageStart = _matchedPage * _PAGE_SIZE;
    var pageEnd = Math.min(matched.length, pageStart + _PAGE_SIZE);
    html += '<div class="pg-items-list" role="listbox" aria-label="Matching analysis targets">';
    for (var i = pageStart; i < pageEnd; i++) {
      var r = matched[i];
      var failedMetricNames = Array.isArray(r._matched_metric_names) ? r._matched_metric_names : [];
      var primaryMetric = _getPrimaryMetric(r);
      var scoreNum = primaryMetric && r.metric_scores ? r.metric_scores[primaryMetric] : r.metric_score;
      var scoreStr = scoreNum != null ? scoreNum.toFixed(2) : '\u2014';
      var status = r.error ? 'error' : (scoreNum != null ? (scoreNum < threshold ? 'failed' : 'passed') : 'none');
      var isSelected = _targetMatchesRow(_selectedTarget, r);
      var md = r.item_metadata && typeof r.item_metadata === 'object' ? r.item_metadata : {};
      var rcCategories = _rootCauseCategories(md);
      var rc = rcCategories.join(', ');
      var rcDetail = md.root_cause_detail || '';
      var rcSource = md.root_cause_source || '';
      var rcConfidence = md.root_cause_confidence;
      var isAi = rcSource === 'ai';
      var rcColor = _rootCauseColor(rcCategories[0] || rc);
      var targetLabel = 'Target #' + (r.index != null ? r.index : i) + ', ' + (primaryMetric || 'all metrics') + ', ' + status;
      html += '<div class="pg-item-card' + (isSelected ? ' pg-item-selected' : '') + '" role="option" tabindex="0" aria-selected="' + (isSelected ? 'true' : 'false') + '" aria-label="' + _escAttr(targetLabel) + '" data-item-id="' + _escAttr(r.item_id) + '" data-metric-name="' + _escAttr(primaryMetric) + '">';

      // Top row: index, score, status
      html += '<div class="pg-item-top">';
      html += '<span class="pg-item-idx">#' + (r.index != null ? r.index : i) + '</span>';
      if (primaryMetric) html += '<span class="pg-item-metric qym-tag qym-tag--data">' + _esc(primaryMetric) + '</span>';
      if (scoreNum != null) html += '<span class="pg-item-score pg-status-' + status + '">' + scoreStr + '</span>';
      var statusTone = status === 'passed' ? 'success' : (status === 'failed' ? 'danger' : (status === 'error' ? 'warning' : 'neutral'));
      html += '<span class="qym-badge qym-badge--' + statusTone + '">' + (status === 'none' ? 'no score' : status) + '</span>';
      if (failedMetricNames.length > 1) html += '<span class="pg-item-target-count qym-tag qym-tag--count">+' + (failedMetricNames.length - 1) + ' metric target' + (failedMetricNames.length === 2 ? '' : 's') + '</span>';
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
            var confidenceTone = rcConfidence >= 0.8 ? 'high' : (rcConfidence >= 0.5 ? 'medium' : 'low');
            confDot = '<span class="pg-item-rc-conf pg-item-rc-conf--' + confidenceTone + '" title="Confidence: ' + Math.round(rcConfidence * 100) + '%"></span>';
          }
          html += rcCategories.map(function (category) {
            var categoryColor = _rootCauseColor(category);
            return '<span class="pg-item-rc-cat" style="--pg-root-cause-color:' + categoryColor + ';">' + _esc(category) + confDot + '</span>';
          }).join('');
        }
        html += '</div>';
      }

      // Input preview
      html += '<div class="pg-item-preview">';
      html += '<span class="pg-item-text" dir="auto">' + _esc(_truncate(r.input, 100)) + '</span>';
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

  function _analysisRuleForAnalyzer(rule) {
    return {
      id: rule && rule.id || undefined,
      title: rule && rule.title || '',
      instruction: rule && rule.instruction || '',
    };
  }

  function _buildConfigPayload() {
    var cfg = {};
    var rulesToggle = document.getElementById('pg-use-project-rules');
    var documentsToggle = document.getElementById('pg-use-project-documents');
    var traceToggle = document.getElementById('pg-use-trace');
    if (rulesToggle) cfg.include_project_rules = rulesToggle.checked;
    if (documentsToggle) cfg.include_project_documents = documentsToggle.checked;

    if (!_opts.dedicatedPage) {
      var rules = _readAnalysisRulesFromEditor();
      // Keep reviewer metadata in the version API, but never send it as part
      // of an analysis configuration.
      cfg.analysis_rules = rules.map(_analysisRuleForAnalyzer);
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
    var catGroups = _opts.dedicatedPage
      ? []
      : document.querySelectorAll('#pg-categories-list .pg-category-group');
    if (catGroups.length > 0) {
      var cats = [];
        var cdMap = {};
        var taxonomyMap = {};
        catGroups.forEach(function (group) {
        var cat = group.dataset.cat;
        cats.push(cat);
        var dets = [];
        group.querySelectorAll('.pg-detail-item').forEach(function (el) {
          dets.push(el.dataset.detail);
        });
          if (dets.length > 0) cdMap[cat] = dets;
          var taxonomy = {};
          group.querySelectorAll('[data-taxonomy-field]').forEach(function (field) {
            var value = field.value.trim();
            if (value) taxonomy[field.dataset.taxonomyField] = value;
          });
          if (taxonomy.description || taxonomy.when_to_use) taxonomyMap[cat] = taxonomy;
        });
        cfg.root_cause_categories = cats;
        cfg.category_details_map = cdMap;
        cfg.category_taxonomy = taxonomyMap;
    }
    var maxCategoriesEl = document.getElementById('pg-max-root-cause-categories');
    if (maxCategoriesEl) {
      var categoryLimit = _categoryLimitInputValue(maxCategoriesEl);
      if (categoryLimit != null) cfg.max_root_cause_categories = categoryLimit;
    }

    // Include fields
    var fieldChecks = _overlay ? _overlay.querySelectorAll('.pg-field-toggle input[type="checkbox"][data-field]') : [];
    if (fieldChecks.length > 0) {
      var fields = { input: true, expected: true, output: true };
      fieldChecks.forEach(function (cb) { fields[cb.dataset.field] = cb.checked; });
      if (traceToggle) fields.trace = traceToggle.checked;
      cfg.include_fields = fields;
      if (fields.metadata) {
        var metadataSelection = _getPathPickerSelection('pg-metadata-paths', 'metric_metadata');
        if (metadataSelection.custom) cfg.metadata_fields = metadataSelection.source;
      }
    } else if (traceToggle) {
      cfg.include_fields = { trace: traceToggle.checked };
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
    _syncInferenceSourceSummary();
    _syncActionAvailability();
  }

  function _setDocumentUploadStatus(message, isError) {
    var status = document.getElementById('pg-document-upload-status');
    if (!status) return;
    status.textContent = message || '';
    status.className = 'pg-document-upload-status' + (isError ? ' pg-document-upload-error' : '');
  }

  function _uploadReferenceDocument(file, largeDocumentAction) {
    if (!_hasAnalysisContext()) return Promise.reject(new Error('Could not determine the analysis context.'));
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    var form = new FormData();
    form.append('file', file, file.name);
    form.append('large_document_action', largeDocumentAction || 'ask');
    return fetch(base(_analysisContextPath('analysis-documents')), {
      method: 'POST',
      body: form,
    }).then(function (response) {
      return response.text().then(function (text) {
        var payload = {};
        try { payload = text ? JSON.parse(text) : {}; } catch (e) {}
        if (!response.ok) {
          var detail = payload.detail;
          var message = detail && typeof detail === 'object'
            ? detail.message
            : detail;
          var error = new Error(message || text || 'Document upload failed');
          error.code = detail && typeof detail === 'object' ? detail.code : '';
          error.detail = detail;
          throw error;
        }
        if (!payload.document) throw new Error('Document upload returned no extracted content.');
        return payload.document;
      });
    });
  }

  function _confirmLargeReferenceDocument(file, detail) {
    if (!window.QymShell || typeof window.QymShell.openConfirmDialog !== 'function') {
      return Promise.reject(new Error('Confirmation is unavailable, so the large document was not added.'));
    }
    var sourceCharacters = Number(detail && detail.source_characters || 0);
    var promptLimit = Number(detail && detail.prompt_limit || _documentPerFilePromptLimit());
    var contentLimit = Number(detail && detail.content_limit || 200000);
    var contentWillBeCut = !!(detail && detail.content_will_be_cut);
    return window.QymShell.openConfirmDialog({
      mount: _overlay || document.body,
      title: 'Large document needs a decision',
      description: [
        file.name + ' is about ' + sourceCharacters.toLocaleString() + ' characters, above the ' + promptLimit.toLocaleString() + '-character prompt-safe limit.',
        (contentWillBeCut
          ? 'This upload also exceeds the absolute content limit. Even the full option will retain only the first ' + contentLimit.toLocaleString() + ' extracted characters.'
          : 'Use the shortened version for normal analysis, or add up to ' + contentLimit.toLocaleString() + ' characters in full.'),
        'Full content is the evaluator owner’s responsibility and the rule writer will process it in patches.',
      ],
      cancelLabel: 'Use shortened version',
      confirmLabel: 'Add full content',
      confirmClass: 'shell-btn-danger',
    }).then(function (result) {
      return result && result.confirmed ? 'full' : 'truncate';
    });
  }

  function _uploadOneReferenceDocument(file) {
    return _uploadReferenceDocument(file, 'ask').catch(function (error) {
      if (error.code !== 'DOCUMENT_CONTENT_LIMIT') throw error;
      return _confirmLargeReferenceDocument(file, error.detail).then(function (action) {
        return _uploadReferenceDocument(file, action);
      });
    });
  }

  function _deleteReferenceDocument(document) {
    if (!_hasAnalysisContext() || !document.id) return Promise.reject(new Error('Could not identify the saved document.'));
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    return fetch(base(_analysisContextPath('analysis-documents/' + encodeURIComponent(document.id))), {
      method: 'DELETE',
    }).then(function (response) {
      if (!response.ok) return response.text().then(function (text) { throw new Error(text || 'Document deletion failed'); });
      return response.json();
    });
  }

  function _confirmReferenceDocumentDeletion(referenceDocument) {
    if (!window.QymShell || typeof window.QymShell.openConfirmDialog !== 'function') {
      if (_opts.showToast) {
        _opts.showToast('error', 'Confirmation unavailable', 'The document was not deleted. Reload the page and try again.');
      }
      return Promise.resolve(false);
    }
    return window.QymShell.openConfirmDialog({
      mount: _overlay || document.body,
      title: 'Delete document?',
      description: [
        'Remove “' + referenceDocument.name + '” from the project library?',
        'It will no longer be available to future analyses.',
      ],
      cancelLabel: 'Keep document',
      confirmLabel: 'Delete document',
      confirmClass: 'shell-btn-danger',
    }).then(function (result) {
      return !!(result && result.confirmed);
    });
  }

  function _updateReferenceDocumentSelection(document, selected) {
    if (!_hasAnalysisContext() || !document.id) return Promise.reject(new Error('Could not identify the saved document.'));
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    return fetch(base(_analysisContextPath('analysis-documents/' + encodeURIComponent(document.id))), {
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

    var uploads = [];
    var sequence = Promise.resolve();
    files.forEach(function (file) {
      sequence = sequence.then(function () {
        return _uploadOneReferenceDocument(file).then(function (document) {
          uploads.push({ document: document });
        }).catch(function (error) {
          uploads.push({ error: error, filename: file.name });
        });
      });
    });
    sequence.then(function () {
      var results = uploads;
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
    var rules = _analysisRules.map(function (rule) {
      return {
        id: rule && rule.id,
        title: rule && rule.title || '',
        instruction: rule && rule.instruction || '',
        inferred_from: rule && rule.inferred_from || undefined,
        explanation: rule && rule.explanation || undefined,
      };
    });
    list.querySelectorAll('.pg-rule-item').forEach(function (item) {
      var titleEl = item.querySelector('.pg-rule-title');
      var instructionEl = item.querySelector('.pg-rule-instruction');
      var index = parseInt(item.dataset.ruleIndex, 10);
      if (Number.isNaN(index) || index < 0 || index >= rules.length) return;
      var title = titleEl ? titleEl.value.trim() : '';
      var instruction = instructionEl ? instructionEl.value.trim() : '';
      var existing = rules[index] || {};
      rules[index] = {
        id: item.dataset.ruleId || undefined,
        title: title,
        instruction: instruction,
        inferred_from: existing.inferred_from || undefined,
        explanation: existing.explanation || undefined,
      };
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
    _analysisRules = _readAnalysisRuleDraftsFromEditor();
    var invalidIndex = -1;
    var invalidTitle = false;
    _analysisRules.some(function (rule, index) {
      var titleMissing = !rule.title;
      var instructionMissing = !rule.instruction;
      if (titleMissing || instructionMissing) {
        invalidIndex = index;
        invalidTitle = titleMissing;
        return true;
      }
      return false;
    });
    if (invalidIndex < 0) return true;

    _analysisRulesPageForIndex(invalidIndex);
    _editingRuleIndex = invalidIndex;
    _renderAnalysisRulesEditor();
    var invalidItem = list && list.querySelector('[data-rule-index="' + invalidIndex + '"]');
    var invalidField = null;
    if (invalidItem) {
      var titleEl = invalidItem.querySelector('.pg-rule-title');
      var instructionEl = invalidItem.querySelector('.pg-rule-instruction');
      var titleMissing = !titleEl || !titleEl.value.trim();
      var instructionMissing = !instructionEl || !instructionEl.value.trim();
      if (titleEl) titleEl.classList.toggle('pg-field-invalid', titleMissing);
      if (instructionEl) instructionEl.classList.toggle('pg-field-invalid', instructionMissing);
      invalidField = invalidTitle ? titleEl : instructionEl;
      if (!invalidField && (titleMissing || instructionMissing)) invalidField = titleMissing ? titleEl : instructionEl;
    }
    if (!invalidField) return false;
    invalidField.focus();
    _setContextStatus('Complete the title and instruction for every rule before changes can be saved.', true);
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

  function _renderAnalysisRulesEditor(scrollToTop) {
    var list = document.getElementById('pg-rule-list');
    _renderRuleFilterControls();
    if (list) list.innerHTML = _buildAnalysisRulesEditor();
    _renderAnalysisRulePagination();
    var count = document.getElementById('pg-rule-count');
    if (count) count.textContent = _formatRuleCount();
    var selected = _ruleVersions.find(function (version) { return version.id === _selectedRuleVersionId; });
    var editorTitle = document.getElementById('pg-rule-editor-title');
    if (editorTitle) editorTitle.textContent = selected ? 'Rules in v' + selected.version : 'Rules';
    var editable = !!selected && selected.status === 'draft';
    var addButton = document.getElementById('pg-add-rule');
    var createButton = document.getElementById('pg-create-rule-version');
    if (addButton) {
      addButton.disabled = !editable;
      addButton.title = editable ? 'Add rule' : 'Create a draft to add rules';
      addButton.setAttribute('aria-label', editable ? 'Add rule' : 'Create a draft to add rules');
    }
    if (createButton) {
      createButton.hidden = false;
      createButton.classList.remove('pg-context-primary');
      createButton.classList.add('pg-context-secondary');
    }
    var generateButton = document.getElementById('pg-infer-rules');
    if (generateButton) {
      generateButton.classList.remove('pg-context-secondary');
      generateButton.classList.add('pg-context-primary');
    }
    var viewState = document.getElementById('pg-rule-view-state');
    if (viewState) {
      viewState.textContent = editable ? 'Editable draft' : 'Read-only';
      viewState.classList.toggle('qym-badge--success', editable);
      viewState.classList.toggle('qym-badge--warning', !editable);
      viewState.classList.remove('qym-badge--neutral');
      viewState.title = editable ? 'Rules in this draft can be edited.' : 'Create a draft before editing these rules.';
    }
    _renderRuleVersionMeta(selected);
    _renderRuleVersionActions();
    _renderRuleViewStatus();
    if (scrollToTop && list) list.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function _renderRuleVersionActions() {
    var actions = document.getElementById('pg-rule-version-actions');
    if (!actions) return;
    var selected = _ruleVersions.find(function (version) { return version.id === _selectedRuleVersionId; });
    actions.innerHTML = '';
    actions.hidden = true;
    if (!selected || selected.is_deleted || !_canActivateRuleVersions) return;
    if (selected.status === 'draft') {
      actions.innerHTML = '<button class="qym-inline-action qym-inline-action--accent" id="pg-publish-rule-version" type="button" data-publish-rule-version="' + _escAttr(selected.id) + '">' + _icon('upload') + '<span>Publish</span></button>';
    } else if (selected.status === 'published' && !selected.is_active) {
      actions.innerHTML = '<button class="qym-inline-action qym-inline-action--accent" id="pg-promote-rule-version" type="button" data-activate-rule-version="' + _escAttr(selected.id) + '">' + _icon('rocket') + '<span>Promote</span></button>';
    } else {
      return;
    }
    actions.hidden = false;
  }

  function _syncInferenceSourceSummary() {
    return _syncInferenceSourceAvailability();
  }

  function _syncInferenceSourceAvailability() {
    var state = _inferenceSourceState();
    _renderApprovedExampleSourceControl();
    var empty = document.getElementById('pg-infer-source-empty');
    if (empty) {
      empty.textContent = state.message;
      empty.hidden = state.hasUsableSource;
    }
    var generateButton = document.getElementById('pg-infer-rules');
    if (generateButton) {
      generateButton.disabled = !state.hasUsableSource;
      generateButton.title = state.hasUsableSource ? 'Generate additional non-redundant rules from the selected sources' : state.message;
    }
    var documentBudget = document.getElementById('pg-document-budget');
    if (documentBudget) {
      var documentCharacters = Number(state.selectedDocumentCharacters || 0);
      var documentLimit = Number(state.documentCharacterLimit || 0);
      var documentCount = Number(state.selectedDocuments || 0);
      var documentCountLimit = Number(state.documentCountLimit || 0);
      documentBudget.textContent = 'Selected document content: ' + documentCharacters.toLocaleString() +
        ' / ' + documentLimit.toLocaleString() + ' prompt characters · ' + documentCount +
        ' / ' + documentCountLimit + ' documents in the final prompt. ' +
        (documentCharacters > documentLimit || documentCount > documentCountLimit
          ? 'The rule writer will divide this into patches; the final analyzer prompt will disclose any bounded documents.'
          : 'This selection fits the final analyzer document budget.');
      documentBudget.classList.toggle('pg-budget-over', documentCharacters > documentLimit);
    }
    return state;
  }

  function _setRuleEditorBusy(isBusy) {
    var list = document.getElementById('pg-rule-list');
    if (!list) return;
    list.querySelectorAll('input, textarea, button').forEach(function (control) {
      control.disabled = isBusy;
    });
    var addButton = document.getElementById('pg-add-rule');
    if (addButton) addButton.disabled = isBusy;
    var pagination = document.getElementById('pg-rule-pagination');
    if (pagination) {
      if (isBusy) {
        pagination.querySelectorAll('button, input, select').forEach(function (control) {
          control.disabled = true;
        });
      } else {
        _renderAnalysisRulePagination();
      }
    }
  }

  function _renderRuleVersionHistory() {
    var list = document.getElementById('pg-rule-version-list');
    if (list) {
      list.innerHTML = _buildRuleVersionHistory();
      document.dispatchEvent(new CustomEvent('qym:rule-version-history-rendered'));
    }
  }

  function _refreshRuleVersions(syncEditor) {
    if (!_hasAnalysisContext()) return Promise.reject(new Error('Could not determine the analysis context.'));
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    return fetch(base(_analysisContextPath('analysis-rule-versions?include_deleted=true')))
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
          _analysisRulesPage = 1;
          _editingRuleIndex = null;
          if (_config) _config.analysis_rules = _analysisRules;
          _renderAnalysisRulesEditor();
        }
        _renderRuleVersionHistory();
        _renderRuleVersionActions();
        _renderRuleViewStatus();
      });
  }

  function _changeRuleVersion(versionId, action) {
    if (!_hasAnalysisContext()) return Promise.reject(new Error('Could not determine the analysis context.'));
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    var suffix = action === 'restore'
      ? '/restore'
      : (action === 'activate' ? '/activate' : (action === 'permanent-delete' ? '/permanent' : ''));
    return fetch(base(_analysisContextPath('analysis-rule-versions/' + encodeURIComponent(versionId) + suffix)), {
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

  function _confirmAnalysisRuleDeletion(index) {
    var rule = _analysisRules[index];
    if (!rule) return Promise.resolve(false);
    if (!window.QymShell || typeof window.QymShell.openConfirmDialog !== 'function') {
      _setContextStatus('The confirmation dialog is unavailable. Reload the page and try again.', true);
      return Promise.resolve(false);
    }
    var name = rule.title || 'this rule';
    return window.QymShell.openConfirmDialog({
      mount: _overlay || document.body,
      title: 'Delete this rule?',
      description: [
        'Delete “' + name + '” from the current draft.',
        'This can\'t be undone.',
      ],
      cancelLabel: 'Cancel',
      confirmLabel: 'Delete rule',
      confirmClass: 'shell-btn-danger',
    }).then(function (result) {
      if (!result || !result.confirmed) return false;
      _analysisRules = _readAnalysisRuleDraftsFromEditor();
      _analysisRules.splice(index, 1);
      _editingRuleIndex = null;
      _renderAnalysisRulesEditor();
      _setRuleEditorBusy(true);
      _setContextStatus('Removing rule from the current version…', false);
      return _saveAnalysisContext().then(function () {
        _setContextStatus('Rule deleted.', false);
        return true;
      }).catch(function (error) {
        _setContextStatus(error.message || 'The rule was removed locally but could not be saved.', true);
        return false;
      }).finally(function () {
        _setRuleEditorBusy(false);
      });
    });
  }

  function _openRuleVersion(versionId) {
    var version = _ruleVersions.find(function (candidate) { return candidate.id === versionId; });
    if (!version) return;
    _selectedRuleVersionId = version.id;
    _analysisRules = (version.rules || []).slice();
    _analysisRulesPage = 1;
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
    if (!_hasAnalysisContext()) return Promise.reject(new Error('Could not determine the analysis context.'));
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    var sourceVersionId = fromVersionId || _selectedRuleVersionId;
    var selected = _ruleVersions.find(function (version) { return version.id === sourceVersionId; });
    if (!selected || selected.is_deleted) {
      return Promise.reject(new Error('Select an available version before creating a draft.'));
    }
    return fetch(base(_analysisContextPath('analysis-rule-versions')), {
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
    if (!_hasAnalysisContext()) return Promise.reject(new Error('Could not determine the analysis context.'));
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    return fetch(base(_analysisContextPath('analysis-rule-versions/' + encodeURIComponent(targetId) + ':merge')), {
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
    if (!select) return;
    if (window.QymUIComponents && typeof window.QymUIComponents.enhanceSelect === 'function') {
      window.QymUIComponents.enhanceSelect(select, { className: 'pg-rule-version-review-selector', label: select.getAttribute('aria-label') || 'Rule version', search: true });
    }
  }

  function _buildRuleVersionPicker(label, versions, selectedId, key, ariaLabel) {
    var selected = selectedId || (versions[0] && versions[0].id) || '';
    var optionHtml = versions.map(function (version) {
      var isSelected = version.id === selected;
      return '<option value="' + _escAttr(version.id) + '"' + (isSelected ? ' selected' : '') + '>v' + _esc(version.version) + ' · ' + _esc(_ruleVersionStateLabel(version)) + '</option>';
    }).join('');
    return '<div class="pg-rule-version-picker">' +
      '<div class="pg-rule-operation-field"><span id="pg-rule-' + _escAttr(key) + '-label">' + _esc(label) + '</span><select data-rule-' + key + ' aria-labelledby="pg-rule-' + _escAttr(key) + '-label" aria-label="' + _escAttr(ariaLabel) + '">' + optionHtml + '</select></div>' +
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
        '<div class="pg-rule-merge-choice"><span>Resolution</span><select data-merge-resolution aria-label="Conflict resolution">' +
          '<option value="target">Keep current</option>' +
          '<option value="source">Use incoming</option>' +
          '<option value="custom">Write custom</option>' +
        '</select></div>' +
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
      if (window.QymUIComponents && typeof window.QymUIComponents.enhanceSelect === 'function') {
        window.QymUIComponents.enhanceSelect(select, { className: 'pg-rule-resolution-selector', label: 'Conflict resolution', search: false });
      }
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
    panel.querySelector('.pg-rule-version-review-selector .multi-select-btn')?.focus();
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
    panel.querySelector('.pg-rule-version-review-selector .multi-select-btn')?.focus();
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

  function _downloadRuleVersion(versionId) {
    var version = _ruleVersions.find(function (candidate) { return candidate.id === versionId; });
    if (!version) return;
    var payload = {
      name: version.name || 'v' + version.version,
      version: version.version,
      status: version.status,
      created_at: version.created_at,
      rules: version.rules || [],
    };
    var blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var link = document.createElement('a');
    link.href = url;
    link.download = 'analysis-rules-v' + version.version + '.json';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 0);
    _setContextStatus('Downloaded v' + version.version + '.', false);
  }

  function _publishRuleVersion(versionId) {
    var version = _ruleVersions.find(function (candidate) { return candidate.id === versionId; });
    if (!version) return Promise.resolve();
    if (!window.QymShell || typeof window.QymShell.openFormDialog !== 'function') {
      _setContextStatus('The publish dialog is unavailable. Reload the page and try again.', true);
      return Promise.resolve();
    }
    if (!_hasAnalysisContext()) return Promise.reject(new Error('Could not determine the analysis context.'));
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
        return fetch(base(_analysisContextPath('analysis-rule-versions/' + encodeURIComponent(String(version.version)) + ':publish')), {
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
    if (!_hasAnalysisContext()) return Promise.reject(new Error('Could not determine the analysis context.'));
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    return fetch(base(_analysisContextPath('analysis-rule-versions/' + encodeURIComponent(String(version.version)) + ':compare?base=' + encodeURIComponent(String(parent.version)))))
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

  function _responseErrorMessage(data, fallback) {
    var detail = data && data.detail;
    if (detail && typeof detail === 'object') {
      return String(detail.message || detail.detail || fallback);
    }
    return String(detail || fallback);
  }

  function _scheduleAnalysisRuleAutoSave() {
    if (_analysisRuleSaveTimer) clearTimeout(_analysisRuleSaveTimer);
    _analysisRuleSaveTimer = null;
    var selected = _ruleVersions.find(function (version) { return version.id === _selectedRuleVersionId; });
    if (!selected || selected.status !== 'draft') return;
    _analysisRuleSaveTimer = setTimeout(function () {
      _analysisRuleSaveTimer = null;
      var drafts = _readAnalysisRuleDraftsFromEditor();
      if (drafts.some(function (rule) { return !rule.title || !rule.instruction; })) return;
      _saveAnalysisContext().catch(function () {});
    }, 700);
  }

  function _saveAnalysisContext(createNewVersion) {
    if (!_validateAnalysisRuleDrafts()) return Promise.reject(new Error('Every rule requires a title and instruction'));
    if (!_hasAnalysisContext()) return Promise.reject(new Error('Could not determine the analysis context.'));
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    var payload = {
      analysis_rules: _readAnalysisRulesFromEditor(),
      create_new_version: !!createNewVersion,
      rule_version_id: _selectedRuleVersionId,
    };
    var selectedVersion = _ruleVersions.find(function (version) { return version.id === _selectedRuleVersionId; });
    _setContextStatus(
      createNewVersion
        ? 'Creating a new rule version…'
        : (selectedVersion && selectedVersion.status === 'draft' ? 'Saving draft…' : 'Saving rules…'),
      false
    );
    return fetch(base(_analysisContextPath('analysis-context')), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(function (response) {
      if (!response.ok) return response.json().then(function (data) { throw new Error(data.detail || 'Could not save context'); });
      return response.json();
    }).then(function (data) {
      _selectedRuleVersionId = data.rule_version && data.rule_version.id;
      _analysisRules = data.analysis_rules || [];
      _analysisRulesPage = 1;
      if (_config) {
        _config.analysis_rules = _analysisRules;
      }
      _renderAnalysisRulesEditor();
      return _refreshRuleVersions(false).then(function () {
        _setContextStatus(
          createNewVersion
            ? 'Created draft v' + data.rule_version.version + '.'
            : (data.rule_version.status === 'draft'
              ? 'Changes saved automatically to draft v' + data.rule_version.version + '.'
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

  function _inferAnalysisRules() {
    var mode = 'generate';
    if (!_hasAnalysisContext()) {
      _setContextStatus('Could not determine the analysis context.', true);
      return;
    }
    var base = _opts.apiUrl || function (p) { return '/' + p; };
    var useDocumentsEl = document.getElementById('pg-infer-use-documents');
    var inferenceSources = {
      include_documents: !useDocumentsEl || useDocumentsEl.checked,
      include_examples: _selectedApprovedExampleCount() > 0,
    };
    if (!inferenceSources.include_documents && !inferenceSources.include_examples) {
      _setContextStatus('Select at least one source before running rule inference.', true);
      return;
    }
    var sourceState = _syncInferenceSourceAvailability();
    if (!sourceState.hasUsableSource) {
      _setContextStatus(sourceState.message, true);
      return;
    }
    var button = document.getElementById('pg-infer-rules');
    if (button) {
      button.disabled = true;
      button.textContent = 'Generating…';
    }
    _setContextStatus('Generating rules from the selected sources…', false);
    fetch(base(_analysisContextPath('analysis-rules/infer')), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        include_documents: inferenceSources.include_documents,
        include_examples: inferenceSources.include_examples,
        approved_example_ids: Array.from(_selectedApprovedExampleIds),
        include_fields: _approvedExampleFieldMap(),
        mode: mode,
        rule_version_id: _selectedRuleVersionId,
        connection_id: _connectionId,
      }),
    }).then(function (response) {
      if (!response.ok) return response.json().then(function (data) { throw new Error(_responseErrorMessage(data, 'Could not generate rules')); });
      return response.json();
    }).then(function (data) {
      _analysisRules = data.analysis_rules || [];
      _analysisRulesPage = 1;
      _selectedRuleVersionId = data.rule_version && data.rule_version.id;
      if (_config) {
        _config.analysis_rules = _analysisRules;
      }
      _renderAnalysisRulesEditor();
      return _refreshRuleVersions(false).then(function () {
        var inferenceStats = data.inference_stats || {};
        var addedCount = data.changes && Number.isFinite(Number(data.changes.added))
          ? Number(data.changes.added)
          : Number(data.generated_rule_count || 0);
        var patchText = inferenceStats.writer_calls
          ? ' · ' + inferenceStats.writer_calls + ' writer call' + (inferenceStats.writer_calls === 1 ? '' : 's') +
            (inferenceStats.patching_used ? ' across bounded patches' : '')
          : '';
        var version = data.rule_version || {};
        var versionText;
        if (addedCount === 0) {
          versionText = 'No new non-redundant rules were found; v' + version.version + ' is unchanged.';
        } else if (data.created_new_version) {
          versionText = 'Created draft v' + version.version + ' with ' + addedCount + ' additional ' + (addedCount === 1 ? 'rule' : 'rules') + '.';
        } else {
          versionText = 'Added ' + addedCount + ' new ' + (addedCount === 1 ? 'rule' : 'rules') + ' to draft v' + version.version + '.';
        }
        _setContextStatus(
          versionText + patchText + (addedCount > 0 ? ' Review and publish when ready.' : ''),
          false
        );
        _scheduleAutoPreview(0);
      });
    }).catch(function (error) {
      _setContextStatus(error.message || 'Could not generate rules.', true);
      if (_opts.showToast) _opts.showToast('error', 'Rule Generation Failed', error.message);
    }).finally(function () {
      if (button) {
        button.textContent = 'Generate rules';
      }
      _syncInferenceSourceAvailability();
    });
  }

  // ── Wire all events ──

  function _wireEvents() {
    document.querySelectorAll('#pg-infer-use-documents').forEach(function (input) {
      input.addEventListener('change', _syncInferenceSourceSummary);
    });
    var addExamples = document.getElementById('pg-add-examples');
    if (addExamples) addExamples.addEventListener('click', _openApprovedExamplePicker);
    var ruleVersionActions = document.getElementById('pg-rule-version-actions');
    if (ruleVersionActions) ruleVersionActions.addEventListener('click', function (event) {
      var publish = event.target.closest('[data-publish-rule-version]');
      var promote = event.target.closest('[data-activate-rule-version]');
      if (publish) {
        _publishRuleVersion(publish.dataset.publishRuleVersion).catch(function (error) {
          _setContextStatus(error.message || 'Could not publish rule version.', true);
        });
        return;
      }
      if (promote) {
        _changeRuleVersion(promote.dataset.activateRuleVersion, 'activate');
      }
    });
    _syncInferenceSourceSummary();
    var ruleList = document.getElementById('pg-rule-list');
    if (ruleList) {
      ruleList.addEventListener('input', function (event) {
        if (event.target) event.target.classList.remove('pg-field-invalid');
        _analysisRules = _readAnalysisRuleDraftsFromEditor();
        _scheduleAnalysisRuleAutoSave();
        _scheduleAutoPreview();
      });
      ruleList.addEventListener('click', function (event) {
        var remove = event.target.closest('[data-delete-rule]');
        if (remove) {
          var removeIndex = parseInt(remove.dataset.deleteRule, 10);
          if (!Number.isNaN(removeIndex)) _confirmAnalysisRuleDeletion(removeIndex);
          return;
        }
        var row = event.target.closest('.pg-rule-item');
        if (row && !event.target.closest('button, input, select, textarea')) {
          var rowToggle = row.querySelector('[data-toggle-rule]');
          if (rowToggle) rowToggle.click();
          return;
        }
        var toggle = event.target.closest('[data-toggle-rule]');
        if (!toggle) return;
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
    var ruleSearch = document.getElementById('pg-rule-search');
    if (ruleSearch) ruleSearch.addEventListener('input', function () {
      _analysisRules = _readAnalysisRuleDraftsFromEditor();
      _analysisRuleSearch = ruleSearch.value;
      _analysisRulesPage = 1;
      _editingRuleIndex = null;
      _renderAnalysisRulesEditor();
    });
    var addRule = document.getElementById('pg-add-rule');
    if (addRule) addRule.addEventListener('click', function () {
      var selected = _ruleVersions.find(function (version) { return version.id === _selectedRuleVersionId; });
      if (!selected || selected.status !== 'draft') {
        _setContextStatus('Create or open a draft before editing rules.', true);
        return;
      }
      _analysisRules = _readAnalysisRuleDraftsFromEditor();
      _analysisRuleSearch = '';
      _analysisRules.push({ title: '', instruction: '' });
      _editingRuleIndex = _analysisRules.length - 1;
      _analysisRulesPageForIndex(_editingRuleIndex);
      _renderAnalysisRulesEditor();
      var newRuleTitle = ruleList && ruleList.querySelector('[data-rule-index="' + _editingRuleIndex + '"] .pg-rule-title');
      if (newRuleTitle) {
        newRuleTitle.scrollIntoView({ block: 'nearest' });
        newRuleTitle.focus();
      }
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
    if (inferRules) inferRules.addEventListener('click', function () { _inferAnalysisRules(); });
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
      var download = event.target.closest('[data-download-rule-version]');
      var openVersion = event.target.closest('[data-open-rule-version]');
      if (versionId && (activate || publish || merge || compare || remove)) {
        _openRuleVersion(versionId);
      }
      if (versionId && download) _openRuleVersion(versionId);
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
            var candidateRow = candidate.closest('[data-rule-version-id]');
            if (candidateRow) candidateRow.classList.remove('pg-rule-version-menu-open');
            var otherToggle = candidate.closest('.pg-rule-version-overflow').querySelector('[data-rule-version-menu-toggle]');
            if (otherToggle) otherToggle.setAttribute('aria-expanded', 'false');
          }
        });
        if (menu) {
          menu.hidden = !menu.hidden;
          var menuOpen = !menu.hidden;
          if (versionRow) versionRow.classList.toggle('pg-rule-version-menu-open', menuOpen);
          menuToggle.setAttribute('aria-expanded', menu.hidden ? 'false' : 'true');
          if (menuOpen) {
            var firstAction = menu.querySelector('button');
            if (firstAction) firstAction.focus();
          }
        } else if (versionRow) {
          versionRow.classList.remove('pg-rule-version-menu-open');
        }
        return;
      }
      if (openVersion) {
        _openRuleVersion(openVersion.dataset.openRuleVersion);
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
      if (download) {
        _downloadRuleVersion(download.dataset.downloadRuleVersion);
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
      var openVersion = event.target.closest('[data-open-rule-version]');
      if (!openVersion || event.target !== openVersion || (event.key !== 'Enter' && event.key !== ' ')) return;
      event.preventDefault();
      _openRuleVersion(openVersion.dataset.openRuleVersion);
    });
    if (ruleVersionList) {
      (_overlay || document).addEventListener('click', function (event) {
        if (event.target.closest('[data-rule-version-menu-toggle], .pg-rule-version-menu')) return;
        ruleVersionList.querySelectorAll('.pg-rule-version-menu').forEach(function (menu) {
          menu.hidden = true;
          var row = menu.closest('[data-rule-version-id]');
          if (row) row.classList.remove('pg-rule-version-menu-open');
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
      event.stopPropagation();
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
      documentDropzone.addEventListener('keydown', function (event) {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        if (!documentInput || documentInput.disabled) return;
        event.preventDefault();
        documentInput.click();
      });
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
        _confirmReferenceDocumentDeletion(removed).then(function (confirmed) {
          if (!confirmed) return;
          remove.disabled = true;
          return _deleteReferenceDocument(removed).then(function () {
            var currentIndex = _referenceDocuments.indexOf(removed);
            if (currentIndex >= 0) _referenceDocuments.splice(currentIndex, 1);
            _setDocumentUploadStatus(removed.name + ' deleted from the project library.', false);
            _renderReferenceDocuments();
            _scheduleAutoPreview(0);
          });
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

    // Category navigation and editor interactions
    var catList = document.getElementById('pg-categories-list');
    var categoryNav = document.getElementById('pg-category-nav');
    if (categoryNav) categoryNav.addEventListener('click', function (event) {
      var button = event.target.closest('[data-category-select]');
      if (!button) return;
      _selectCategory(button.dataset.categorySelect, false);
    });
    var maxCategoriesInput = document.getElementById('pg-max-root-cause-categories');
    if (maxCategoriesInput) {
      maxCategoriesInput.addEventListener('input', function () {
        _scheduleAutoPreview();
      });
      maxCategoriesInput.addEventListener('blur', function () {
        _normalizeCategoryLimitInput(maxCategoriesInput);
        _scheduleAutoPreview();
      });
    }
    if (catList) catList.addEventListener('click', function (e) {
      var tabButton = e.target.closest('[data-category-tab]');
      if (tabButton) {
        _setCategoryTab(tabButton.closest('.pg-category-group'), tabButton.dataset.categoryTab, false);
        return;
      }
      var removeBtn = e.target.closest('.pg-category-remove');
      if (removeBtn) {
        var group = removeBtn.closest('.pg-category-group');
        if (group) {
          var category = String(group.dataset.cat || 'this category');
          removeBtn.disabled = true;
          _confirmCategoryRemoval(category).then(function (confirmed) {
            if (!confirmed) return;
            var nextGroup = group.nextElementSibling || group.previousElementSibling;
            var nextCategory = nextGroup && nextGroup.dataset ? nextGroup.dataset.cat : null;
            group.remove();
            _renderCategoryNavigation(nextCategory);
            _selectCategory(nextCategory, false);
            _scheduleAutoPreview();
          }).catch(function (error) {
            if (_opts.showToast) _opts.showToast('error', 'Category removal failed', error.message || 'The category was not removed.');
          }).finally(function () {
            removeBtn.disabled = false;
          });
        }
        return;
      }
      var detRemoveBtn = e.target.closest('.pg-detail-remove');
      if (detRemoveBtn) {
        var detItem = detRemoveBtn.closest('.pg-detail-item');
        var detGroup = detRemoveBtn.closest('.pg-category-group');
        if (detItem) {
          detItem.remove();
          _updateCategoryDetailCounts(detGroup);
          _scheduleAutoPreview();
        }
        return;
      }
      var addDetBtn = e.target.closest('.pg-add-detail-btn');
      if (addDetBtn) {
        var row = addDetBtn.closest('.pg-add-detail-row');
        var input = row && row.querySelector('.pg-add-detail-input');
        var detailGroup = addDetBtn.closest('.pg-category-group');
        if (input && detailGroup) {
          var val = input.value.trim();
          if (!val) return;
          var parentCat = row.dataset.cat;
          var sublist = row.parentElement.querySelector('.pg-details-sublist[data-cat="' + parentCat + '"]');
          var div = document.createElement('div');
          div.className = 'pg-detail-item';
          div.dataset.detail = val;
          div.dataset.detailExampleCount = '0';
          div.dataset.parentCat = parentCat;
          div.innerHTML = '<span class="pg-detail-copy"><span class="pg-detail-name" dir="auto">' + _esc(val) + '</span>' +
            '<span class="qym-tag qym-tag--count pg-detail-example-count">0 examples</span></span>' +
            '<button class="pg-detail-remove qym-icon-action" type="button" title="Remove detail" aria-label="Remove ' + _escAttr(val) + ' detail">' + _icon('close') + '</button>';
          sublist.appendChild(div);
          input.value = '';
          _updateCategoryDetailCounts(detailGroup);
          _scheduleAutoPreview();
        }
      }
    });

    // Keyboard behavior for category tabs and inline detail inputs
    if (catList) catList.addEventListener('keydown', function (e) {
      var tabButton = e.target.closest('[data-category-tab]');
      if (tabButton && (e.key === 'ArrowRight' || e.key === 'ArrowLeft' || e.key === 'Home' || e.key === 'End')) {
        e.preventDefault();
        var group = tabButton.closest('.pg-category-group');
        var tabs = Array.prototype.slice.call(group.querySelectorAll('[data-category-tab]'));
        var index = tabs.indexOf(tabButton);
        var nextIndex = e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : (index + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
        _setCategoryTab(group, tabs[nextIndex].dataset.categoryTab, true);
        return;
      }
      if (e.key === 'Enter') {
        var input = e.target.closest('.pg-add-detail-input');
        if (input) {
          var btn = input.parentElement.querySelector('.pg-add-detail-btn');
          if (btn) btn.click();
        }
      }
    });
    if (catList) catList.addEventListener('input', function (e) {
      if (e.target.closest('[data-taxonomy-field]')) _scheduleAutoPreview();
      var search = e.target.closest('[data-detail-search]');
      if (search) {
        var searchGroup = search.closest('.pg-category-group');
        _resetCategoryPage(searchGroup, 'details');
        _filterCategoryDetails(searchGroup);
      }
    });
    if (catList) catList.addEventListener('change', function (e) {
      var filter = e.target.closest('[data-detail-filter]');
      if (filter) {
        var filterGroup = filter.closest('.pg-category-group');
        _resetCategoryPage(filterGroup, 'details');
        _filterCategoryDetails(filterGroup);
      }
    });

    // Add category
    var addBtn = document.getElementById('pg-add-category-btn');
    var addInput = document.getElementById('pg-new-category');
    if (addBtn && addInput) {
      var addCat = function () {
        var val = addInput.value.trim();
        if (!val) {
          addInput.hidden = false;
          addInput.focus();
          return;
        }
        var wrapper = document.createElement('div');
        wrapper.innerHTML = _buildCategoryGroup(val, [], [], {}, _uniqueCategoryDomKey(val));
        var group = wrapper.firstElementChild;
        catList.appendChild(group);
        _setCategoryTab(group, 'guidance', false);
        _filterCategoryDetails(group);
        _filterCategoryExamples(group);
        _categoryNavigationQuery = '';
        var categorySearch = document.getElementById('analysis-category-search');
        if (categorySearch) categorySearch.value = '';
        _renderCategoryNavigation(val);
        _selectCategory(val, false);
        addInput.value = '';
        addInput.hidden = true;
        _scheduleAutoPreview();
      };
      addBtn.addEventListener('click', addCat);
      addInput.addEventListener('keydown', function (e) { if (e.key === 'Enter') addCat(); });
    }

    // Variable mapping field change
    _overlay.querySelectorAll('.pg-mapping-select:not(.pg-customvar-field)').forEach(function (sel) {
      if (window.QymUIComponents && typeof window.QymUIComponents.enhanceSelect === 'function') {
        window.QymUIComponents.enhanceSelect(sel, { className: 'pg-mapping-review-selector', label: 'Mapping source', search: false });
      }
      sel.addEventListener('change', function () {
        _onMappingFieldChange(sel);
        _scheduleAutoPreview();
      });
    });
    _overlay.querySelectorAll('.pg-customvar-field').forEach(function (sel) {
      if (window.QymUIComponents && typeof window.QymUIComponents.enhanceSelect === 'function') {
        window.QymUIComponents.enhanceSelect(sel, { className: 'pg-mapping-review-selector', label: 'Custom variable source', search: false });
      }
      sel.addEventListener('change', function () {
        _onCustomVarFieldChange(sel);
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
      document.querySelectorAll('[data-target-limit-step]').forEach(function (stepButton) {
        stepButton.addEventListener('click', function (event) {
          event.preventDefault();
          var direction = stepButton.dataset.targetLimitStep === 'decrease' ? -1 : 1;
          var current = parseInt(targetLimit.value, 10);
          var next = Number.isFinite(current) ? current + direction : (direction > 0 ? 1 : '');
          if (next !== '' && next < 1) next = '';
          if (next !== '') next = Math.min(next, Math.pow(10, targetLimit.maxLength || 4) - 1);
          targetLimit.value = next === '' ? '' : String(next);
          targetLimit.dispatchEvent(new Event('input', { bubbles: true }));
          targetLimit.focus();
        });
      });
      targetLimit.addEventListener('blur', function () {
        if (targetLimit.value && parseInt(targetLimit.value, 10) < 1) targetLimit.value = '';
        _updateFooterCount();
      });
    }
    ['pg-use-project-rules', 'pg-use-project-documents', 'pg-use-trace'].forEach(function (id) {
      var toggle = document.getElementById(id);
      if (toggle) toggle.addEventListener('change', function () {
        _syncActionAvailability();
        _scheduleAutoPreview(0);
      });
    });

    _initializeCategoryWorkspace();

    // Row selection
    _wireRowSelection();
    _wireMatchedItems();

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

    // Background analysis cancellation
    var cancelBtn = document.getElementById('pg-cancel-btn');
    if (cancelBtn) cancelBtn.addEventListener('click', _cancelAnalysis);
  }

  function _wireRowSelection() {
    if (!_overlay) return;
    _overlay.querySelectorAll('.pg-item-card').forEach(function (card) {
      card.addEventListener('click', function () {
        _selectTarget(card.dataset.itemId, card.dataset.metricName || null);
      });
      card.addEventListener('keydown', function (event) {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        card.click();
      });
    });
  }

  function _wireMatchedItems() {
    var includeAnalyzed = document.getElementById('pg-include-analyzed');
    if (includeAnalyzed) {
      includeAnalyzed.addEventListener('click', function () {
        var skipAnalyzed = document.getElementById('pg-skip-analyzed');
        if (skipAnalyzed) skipAnalyzed.checked = false;
        _onFilterChange();
      });
    }
  }

  function _selectTarget(itemId, metricName) {
    _selectedTarget = {
      item_id: itemId,
      metric_name: metricName || null,
    };
    _highlightSelectedRow();
    _scheduleAutoPreview();
    var testBtn = document.getElementById('pg-test-btn');
    if (testBtn) _syncActionAvailability();
  }

  function _highlightSelectedRow() {
    if (!_overlay) return;
    _overlay.querySelectorAll('.pg-item-card').forEach(function (card) {
      var sameItem = _selectedTarget && String(card.dataset.itemId) === String(_selectedTarget.item_id);
      var sameMetric = _selectedTarget && String(card.dataset.metricName || '') === String(_selectedTarget.metric_name || '');
      var selected = !!(sameItem && sameMetric);
      card.classList.toggle('pg-item-selected', selected);
      card.setAttribute('aria-selected', selected ? 'true' : 'false');
    });
  }

  function _onFilterChange() {
    _matchedPage = 0;
    var matched = _getMatchedItems();
    _resolveSelectedTarget(matched);
    _refreshMatchedTable(false, matched);
    _updateFooterCount();
    // Update badge on Filter section
    var filterBadge = document.getElementById('pg-filter-badge');
    if (filterBadge) filterBadge.textContent = String(_getMatchedItemCount(matched));
    _scheduleAutoPreview();
  }

  function _refreshMatchedTable(scrollToTop, matched) {
    var section = document.getElementById('pg-matched-section');
    var currentMatched = matched || _getMatchedItems();
    if (section) {
      section.innerHTML = _buildMatchedItemsTable();
      _wireRowSelection();
      _wireMatchedItems();
      _renderTargetPagination(currentMatched);
      if (scrollToTop) {
        var scrollTarget = section.closest('.analysis-target-card') || section;
        scrollTarget.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }
  }

  function _updateFooterCount() {
    _syncActionAvailability();
  }

  function _getTargetLimit() {
    var limitEl = document.getElementById('pg-target-limit');
    if (!limitEl || !String(limitEl.value || '').trim()) return null;
    var requested = parseInt(limitEl.value, 10);
    if (!Number.isFinite(requested) || requested < 1) return 0;
    return requested;
  }

  function _syncActionAvailability() {
    var matched = _getMatchedItems();
    var runAllBtn = document.getElementById('pg-runall-btn');
    var testBtn = document.getElementById('pg-test-btn');
    var cancelBtn = document.getElementById('pg-cancel-btn');
    var itemCount = _getMatchedItemCount(matched);
    var requestedLimit = _getTargetLimit();
    var analysisItemCount = requestedLimit == null ? itemCount : Math.min(requestedLimit, itemCount);
    var selectedTarget = _resolveSelectedTarget(matched);
    var selectedMetrics = _getSelectedMetrics();
    var metricsReady = selectedMetrics === null || selectedMetrics.length > 0;
    var ready = !!(
      _config &&
      _config.llm_configured &&
      _documentUploadsInFlight === 0 &&
      metricsReady
    );
    if (runAllBtn) {
      runAllBtn.textContent = _formatAnalyzeItemCount(analysisItemCount);
      runAllBtn.disabled = !ready || analysisItemCount === 0 || _running;
      var footer = runAllBtn.closest('.playground-footer');
      if (footer) {
        footer.dataset.noTargets = analysisItemCount === 0 ? 'true' : 'false';
        footer.hidden = analysisItemCount === 0;
      }
    }
    if (testBtn) testBtn.disabled = !ready || !selectedTarget || analysisItemCount === 0 || _running;
    if (cancelBtn) {
      cancelBtn.hidden = !_analysisJobId;
      cancelBtn.disabled = !_analysisJobId || _analysisCancelRequested;
      cancelBtn.textContent = _analysisCancelRequested ? 'Cancelling…' : 'Cancel analysis';
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
          if (window.QymUIComponents && typeof window.QymUIComponents.enhanceSelect === 'function') {
            window.QymUIComponents.enhanceSelect(sel, { className: 'pg-mapping-review-selector', label: 'Custom variable source', search: false });
          }
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
    var budget = document.getElementById('pg-prompt-budget');

    try {
      var matched = _getMatchedItems();
      var target = _resolveSelectedTarget(matched);
      var itemId = target && target.item_id;
      var metricName = target && target.metric_name;

      if (!itemId) {
        if (content) content.textContent = 'No items match current filters.';
        if (toggleBtn) toggleBtn.hidden = true;
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

      if (loading) loading.hidden = false;
      if (indicator) { indicator.textContent = 'updating\u2026'; indicator.className = 'pg-auto-indicator pg-auto-updating'; }
      if (content) content.textContent = 'Loading preview for ' + itemId + '\u2026';

      fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_id: itemId, metric: metricName || null, config: cfg, connection_id: _connectionId, pass_number: _opts.getPassNumber ? _opts.getPassNumber() : null }),
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
        if (budget && data.prompt_characters != null) {
          var promptCharacters = Number(data.prompt_characters || 0);
          var promptLimit = Number(data.prompt_limit || 0);
          budget.textContent = 'Final prompt: ' + promptCharacters.toLocaleString() + ' / ' + promptLimit.toLocaleString() + ' characters' +
            (data.prompt_at_limit ? ' · safety shortening applied before the request' : ' · within limit');
          budget.classList.toggle('pg-budget-over', !!data.prompt_at_limit);
        }
        if (data.messages && data.messages.length > 0) {
          var html = data.messages.map(function (m) {
            return '<div class="pg-preview-msg">' +
              '<div class="pg-preview-role pg-preview-role-' + _escAttr(m.role) + '">' + _esc(m.role.toUpperCase()) + '</div>' +
              '<div class="pg-preview-body" dir="auto">' + _highlightPreview(_esc(m.content)) + '</div>' +
            '</div>';
          }).join('');
          if (content) {
            content.innerHTML = html;
            content.classList.remove('expanded');
          }
          if (toggleBtn) {
            toggleBtn.hidden = false;
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
        if (loading) loading.hidden = true;
        if (indicator) { indicator.textContent = 'auto-updates'; indicator.className = 'pg-auto-indicator'; }
      });
    } catch (err) {
      console.error('Auto-preview sync error:', err);
      if (content) content.textContent = 'Preview error: ' + err.message;
    }
  }

  // ── Test (selected target) ──

  function _runTest() {
    if (_running) return;

    var matched = _getMatchedItems();
    var testTarget = _resolveSelectedTarget(matched);
    if (!testTarget) {
      if (_opts.showToast) _opts.showToast('warning', 'No Items', 'No items match current filters');
      return;
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
      body: JSON.stringify({ item_ids: [testTarget.item_id], metric: testTarget.metric_name || null, config: cfg, connection_id: _connectionId, pass_number: _opts.getPassNumber ? _opts.getPassNumber() : null }),
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
      var categories = _rootCauseCategories(r);
      var color = _rootCauseColor(categories[0] || r.root_cause);
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
        (r.root_cause_detail ? '<div class="pg-result-rc">' + _esc(r.root_cause_detail) + '</div>' : '') +
        '<div class="pg-result-rc pg-result-category' + (r.root_cause_detail ? ' pg-result-category-secondary' : '') + '" style="--pg-root-cause-color:' + color + ';">' + _esc(categories.join(', ')) + '</div>' +
        '<div class="pg-confidence-row">' +
          '<div class="pg-confidence-bar"><div class="pg-confidence-fill" style="--pg-root-cause-color:' + color + ';width:' + confPct + '%;"></div></div>' +
          '<span class="pg-confidence-val">' + (r.confidence != null ? r.confidence.toFixed(2) : '?') + '</span>' +
        '</div>' +
        (r.root_cause_reason ? '<details class="pg-result-note pg-result-reason"><summary>Why this category</summary><div class="pg-result-reason-copy">' + _esc(r.root_cause_reason) + '</div></details>' : '') +
        '<div class="pg-result-note">' + _esc(r.root_cause_note || '') + '</div>' +
        errorHtml +
        fieldsBadgesHtml +
        inputSectionHtml +
      '</div>';
    }).join('');
  }

  // ── Run All ──

  function _confirmHumanOverwrite(targets) {
    if (!window.QymShell || typeof window.QymShell.openConfirmDialog !== 'function') {
      if (_opts.showToast) {
        _opts.showToast('error', 'Confirmation unavailable', 'Human labels were not overwritten. Reload the page and try again.');
      }
      return Promise.resolve(false);
    }
    var metricNames = [];
    targets.forEach(function (target) {
      if (metricNames.indexOf(target.metric_name) === -1) metricNames.push(target.metric_name);
    });
    return window.QymShell.openConfirmDialog({
      mount: _overlay || document.body,
      title: 'Overwrite human diagnoses?',
      description: [
        'This will replace ' + targets.length + ' human metric ' + (targets.length === 1 ? 'diagnosis' : 'diagnoses') + ' with new AI results.',
        'Metrics affected: ' + (metricNames.length ? metricNames.join(', ') : 'selected metrics') + '.',
      ],
      note: 'Continue only if you intentionally want to replace reviewer corrections.',
      cancelLabel: 'Keep human labels',
      confirmLabel: 'Re-analyze human labels',
      confirmClass: 'shell-btn-danger',
    }).then(function (result) {
      return !!(result && result.confirmed);
    });
  }

  // ── Public API ──
  return {
    init: init,
    open: open,
    close: close,
    getConfig: function () { return _config; },
    refreshRuleView: function () {
      if (_overlay) _renderAnalysisRulesEditor();
    },
    filterCategories: function (query) {
      if (_overlay) _filterCategoryNavigation(query);
    },
    refreshFilters: function () {
      if (_overlay) _onFilterChange();
    },
  };
})();
