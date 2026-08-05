(() => {
  'use strict';

  const state = {
    projectSlug: '',
    payload: null,
    direction: 'all',
    query: '',
    evidence: {
      relationshipId: '',
      page: 0,
      pageSize: 20,
      payload: null,
    },
  };

  const el = id => document.getElementById(id);

  function escapeHtml(value) {
    const node = document.createElement('div');
    node.textContent = value == null ? '' : String(value);
    return node.innerHTML;
  }

  function escapeAttr(value) {
    return escapeHtml(value)
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;')
      .replace(/`/g, '&#96;');
  }

  function apiUrl(path) {
    const prefix = (window.__QYM_ROOT_PATH__ || '').replace(/\/$/, '');
    return window.location.origin + prefix + '/' + String(path || '').replace(/^\/+/, '');
  }

  function appUrl(path) {
    const prefix = (window.__QYM_ROOT_PATH__ || '').replace(/\/$/, '');
    return prefix + '/' + String(path || '').replace(/^\/+/, '');
  }

  function projectSlugFromPage() {
    const path = window.location.pathname.replace(/\/+$/, '');
    const match = path.match(/\/projects\/([^/]+)\/analysis$/);
    if (match) return decodeURIComponent(match[1]);
    if (window.QymShell) {
      const context = window.QymShell.getPageContext && window.QymShell.getPageContext();
      const project = window.QymShell.getProject && window.QymShell.getProject();
      return (context && context.projectSlug) || (project && project.slug) || '';
    }
    return '';
  }

  function formatCount(value) {
    return Number(value || 0).toLocaleString();
  }

  function formatPercent(value) {
    return (Number(value || 0) * 100).toFixed(1) + '%';
  }

  function formatP(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 'not available';
    if (number < 0.001) return number.toExponential(2);
    return number.toFixed(3);
  }

  function formatRelativeRisk(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(2) + '×' : 'unbounded';
  }

  function directionClass(direction) {
    return direction === 'more_common' ? 'qym-badge--info' : 'qym-badge--neutral';
  }

  function directionLabel(direction) {
    return direction === 'more_common' ? 'More common' : 'Less common';
  }

  function targetLabel(relationship) {
    if (relationship.target_level === 'detail' && relationship.detail) return relationship.detail;
    return relationship.category || 'This issue';
  }

  function effectPhrase(relationship) {
    const relativeRisk = Number(relationship.relative_risk);
    if (Number.isFinite(relativeRisk) && relativeRisk > 0) {
      if (relationship.direction === 'less_common') return (1 / relativeRisk).toFixed(1) + '× less often';
      if (relationship.direction === 'more_common') return relativeRisk.toFixed(1) + '× more often';
    }
    return relationship.direction === 'more_common' ? 'more often' : 'less often';
  }

  function conditionIsCompound(relationship) {
    return Number(relationship.arity || (relationship.factors || []).length) > 1;
  }

  function conditionBarLabel(relationship, present) {
    if (conditionIsCompound(relationship)) return present ? 'All conditions present' : 'At least one missing';
    return present ? 'With condition' : 'Without condition';
  }

  function conditionComparisonNote(relationship) {
    if (conditionIsCompound(relationship)) return 'All conditions present vs at least one missing';
    return 'With condition vs without condition';
  }

  function formatPercentagePoints(value) {
    return Math.abs(Number(value || 0) * 100).toFixed(1) + ' percentage points';
  }

  function differencePhrase(relationship) {
    const difference = Number(relationship.rate_difference || 0);
    return formatPercentagePoints(difference) + (difference >= 0 ? ' higher' : ' lower');
  }

  function setDirection(direction) {
    state.direction = direction;
    document.querySelectorAll('[data-candidate-direction]').forEach(button => {
      const selected = button.dataset.candidateDirection === direction;
      button.setAttribute('aria-pressed', selected ? 'true' : 'false');
    });
    renderGroups();
  }

  function summary(payload) {
    const counts = payload && payload.counts ? payload.counts : {};
    if (el('candidate-relationship-count')) {
      el('candidate-relationship-count').textContent = formatCount(counts.surviving_candidates) + ' candidate' + (Number(counts.surviving_candidates) === 1 ? '' : 's');
    }
    if (el('candidate-surviving-count')) el('candidate-surviving-count').textContent = formatCount(counts.surviving_candidates);
    if (el('candidate-category-count')) el('candidate-category-count').textContent = formatCount(counts.represented_categories);
    if (el('candidate-analyzed-count')) el('candidate-analyzed-count').textContent = formatCount(counts.analyzed);
    if (el('candidate-coverage-value')) el('candidate-coverage-value').textContent = formatPercent(counts.diagnosis_coverage);
    if (el('candidate-scope-note')) {
      const policy = payload && payload.policy ? payload.policy : {};
      el('candidate-scope-note').textContent = formatCount(counts.total) + ' stable executions · ' + formatCount(policy.minimum_support) + '+ support · project-wide scope';
    }
  }

  function filteredCategories() {
    const query = state.query.trim().toLocaleLowerCase();
    const categories = (state.payload && state.payload.categories) || [];
    return categories.map(category => {
      const categoryMatches = !query
        || String(category.category || '').toLocaleLowerCase().includes(query);
      const relationships = (category.relationships || []).filter(relationship => (
        state.direction === 'all' || relationship.direction === state.direction
      ));
      const detailGroups = (category.detail_groups || []).map(group => ({
        ...group,
        relationships: (group.relationships || []).filter(relationship => (
          state.direction === 'all' || relationship.direction === state.direction
        )),
      })).filter(group => group.relationships.length && (categoryMatches || String(group.detail || '').toLocaleLowerCase().includes(query)));
      if ((!categoryMatches && !detailGroups.length) || (!relationships.length && !detailGroups.length)) return null;
      return { ...category, relationships: categoryMatches ? relationships : [], detail_groups: detailGroups };
    }).filter(Boolean);
  }

  function factorMarkup(relationship) {
    const factors = relationship.factors || [];
    return '<div class="candidate-factor-row" aria-label="Relationship factors">'
      + factors.map((factor, index) => (
        (index ? '<span class="candidate-factor-and" aria-label="and">AND</span>' : '')
        + '<span class="qym-tag qym-tag--data candidate-factor-chip" title="' + escapeAttr(factor.text || '') + '">' + escapeHtml(factor.text || '') + '</span>'
      )).join('')
      + '</div>';
  }

  function barMarkup(label, rate, comparison) {
    const width = Math.max(0, Math.min(100, Number(rate || 0) * 100));
    return '<div class="candidate-bar-row">'
      + '<span class="candidate-bar-label">' + escapeHtml(label) + '</span>'
      + '<div class="candidate-bar-track" role="img" aria-label="' + escapeAttr(label + ': ' + formatPercent(rate)) + '">'
      + '<div class="candidate-bar-fill' + (comparison ? ' is-comparison' : '') + '" style="--candidate-bar-width:' + width + '%"></div>'
      + '</div>'
      + '<span class="candidate-bar-value">' + escapeHtml(formatPercent(rate)) + '</span>'
      + '</div>';
  }

  function relationshipMarkup(relationship) {
    const breadth = relationship.breadth || {};
    const target = targetLabel(relationship);
    const difference = differencePhrase(relationship);
    const impactDirection = Number(relationship.rate_difference || 0) >= 0 ? 'is-higher' : 'is-lower';
    const details = [
      formatCount(relationship.support) + ' executions',
      formatCount(breadth.runs) + ' runs',
      formatCount(breadth.items) + ' items',
      formatCount(breadth.models) + ' models',
      formatCount(breadth.dataset_versions) + ' dataset versions',
    ].join(' · ');
    return '<article class="candidate-relationship">'
      + '<div class="candidate-relationship-header">'
      + '<div class="candidate-relationship-title">'
      + '<h3 class="candidate-relationship-target">' + escapeHtml(target) + '</h3>'
      + '<p class="candidate-relationship-statement">Appears <strong>' + escapeHtml(effectPhrase(relationship)) + '</strong> when this condition is true.</p>'
      + '</div>'
      + '<span class="qym-badge ' + directionClass(relationship.direction) + '">' + escapeHtml(directionLabel(relationship.direction)) + '</span>'
      + '</div>'
      + '<div class="candidate-condition">'
      + '<span class="candidate-section-label">Condition</span>'
      + factorMarkup(relationship)
      + '</div>'
      + '<div class="candidate-comparison-heading">'
      + '<span class="candidate-comparison-title">Issue rate</span>'
      + '<span class="candidate-comparison-note">Longer bar = more occurrences</span>'
      + '</div>'
      + '<div class="candidate-bars">'
      + barMarkup(conditionBarLabel(relationship, true), relationship.observed_rate, false)
      + barMarkup(conditionBarLabel(relationship, false), relationship.comparison_rate, true)
      + '</div>'
      + '<div class="candidate-impact ' + impactDirection + '" role="status" aria-label="' + escapeAttr(difference + ': ' + conditionComparisonNote(relationship)) + '">'
      + '<span class="candidate-impact-arrow" aria-hidden="true">' + (impactDirection === 'is-higher' ? '↑' : '↓') + '</span>'
      + '<div class="candidate-impact-copy">'
      + '<span class="candidate-section-label">Difference</span>'
      + '<strong class="candidate-impact-value">' + escapeHtml(difference) + '</strong>'
      + '<span class="candidate-impact-note">' + escapeHtml(conditionComparisonNote(relationship)) + '</span>'
      + '</div>'
      + '</div>'
      + '<div class="candidate-relationship-footer">'
      + '<span class="candidate-evidence"><strong>Evidence:</strong> ' + escapeHtml(details) + '</span>'
      + '<details class="candidate-stat-details">'
      + '<summary class="qym-inline-action qym-inline-action--neutral">Analysis details</summary>'
      + '<div class="candidate-detail-meta">Difference ' + escapeHtml(difference)
      + ' · relative risk ' + escapeHtml(formatRelativeRisk(relationship.relative_risk))
      + ' · odds ratio ' + escapeHtml(formatRelativeRisk(relationship.odds_ratio))
      + ' · p-value ' + escapeHtml(formatP(relationship.p_value))
      + ' · adjusted q-value ' + escapeHtml(formatP(relationship.q_value)) + '</div>'
      + '</details>'
      + '<button class="qym-inline-action qym-inline-action--accent" type="button" data-candidate-evidence="' + escapeAttr(relationship.relationship_id) + '">See matching executions</button>'
      + '</div>'
      + '</article>';
  }

  function emptyMarkup(title, copy) {
    return '<div class="candidate-empty"><span class="candidate-empty-title">' + escapeHtml(title) + '</span><span>' + escapeHtml(copy) + '</span></div>';
  }

  function emptyStateMarkup() {
    const stateKey = state.payload && state.payload.empty_state;
    const copy = {
      no_root_cause_diagnoses: ['No root-cause diagnoses yet', 'Run metric-scoped analysis to make diagnosed executions available for relationship inspection.'],
      diagnoses_below_threshold: ['Diagnoses are below the relationship threshold', 'A category or exact detail needs at least 10 executions before it can be analyzed.'],
      insufficient_coverage: ['Coverage is insufficient for trustworthy analysis', 'Optional fields are too incomplete or coverage-correlated to support a reliable association.'],
      no_surviving_relationships: ['No surviving candidate relationships', 'The available associations were normal, weak, redundant, biased, or statistically unreliable under the project policy.'],
    }[stateKey] || ['No candidate relationships match', 'Try a different direction or clear the category search.'];
    return emptyMarkup(copy[0], copy[1]);
  }

  function renderGroups() {
    const host = el('candidate-groups');
    if (!host || !state.payload) return;
    const categories = filteredCategories();
    if (!categories.length) {
      host.innerHTML = emptyStateMarkup();
      return;
    }
    host.innerHTML = categories.map(category => {
      const relationshipRows = category.relationships.map(relationshipMarkup).join('');
      const detailRows = category.detail_groups.map(group => (
        '<section class="candidate-detail-group">'
        + '<div><div class="candidate-detail-heading">' + escapeHtml(group.detail || 'Exact detail') + '</div>'
        + '<div class="candidate-detail-meta">' + escapeHtml(formatCount(group.count) + ' executions in this detail subgroup') + '</div></div>'
        + group.relationships.map(relationshipMarkup).join('')
        + '</section>'
      )).join('');
      const below = (category.below_threshold_details || []).map(detail => (
        '<span class="candidate-below-threshold">'
        + escapeHtml(detail.detail || 'Unspecified detail') + ': ' + escapeHtml(formatCount(detail.count))
        + '</span>'
      )).join('');
      return '<details class="candidate-category" open>'
        + '<summary class="candidate-category-header">'
        + '<span class="candidate-category-heading"><span class="candidate-category-title">' + escapeHtml(category.category) + '</span>'
        + '<span class="candidate-category-meta">' + escapeHtml(formatCount(category.count) + ' diagnosed executions') + '</span></span>'
        + '<span class="qym-tag qym-tag--count">' + escapeHtml(formatCount(category.relationships.length + category.detail_groups.reduce((sum, group) => sum + group.relationships.length, 0))) + ' associations</span>'
        + '</summary>'
        + '<div class="candidate-category-body">'
        + relationshipRows
        + detailRows
        + (below ? '<div class="candidate-below-threshold">Details below threshold · ' + below + '</div>' : '')
        + '</div></details>';
    }).join('');
    if (window.QymUIComponents && window.QymUIComponents.refresh) window.QymUIComponents.refresh(host);
  }

  function renderEvidence() {
    const payload = state.evidence.payload;
    const list = el('candidate-evidence-list');
    if (!payload || !list) return;
    const relationship = payload.relationship || {};
    el('candidate-evidence-title').textContent = 'Matching executions';
    el('candidate-evidence-copy').textContent = relationship.statement || 'Executions that match this condition.';
    const rows = payload.occurrences || [];
    list.innerHTML = rows.length ? rows.map(row => (
      '<article class="candidate-evidence-row">'
      + '<div class="candidate-evidence-primary">'
      + '<a href="' + escapeAttr(appUrl(row.run_url || '')) + '">' + escapeHtml(row.run_name || row.run_id || 'Run') + '</a>'
      + '<span class="qym-tag qym-tag--data">' + escapeHtml(row.metric || 'Metric') + '</span>'
      + '<span class="qym-badge qym-badge--neutral">' + escapeHtml(row.outcome || 'unscored') + '</span>'
      + '</div>'
      + '<div class="candidate-evidence-meta">'
      + escapeHtml((row.category || 'No category') + (row.detail ? ' · ' + row.detail : '') + ' · item ' + (row.item_id || row.item_index || ''))
      + '</div>'
      + '<div class="candidate-evidence-meta">'
      + escapeHtml((row.model || 'No model') + ' · ' + (row.dataset || 'No dataset') + (row.dataset_version || ''))
      + ' · score ' + escapeHtml(row.score == null ? '—' : Number(row.score).toFixed(3))
      + '</div>'
      + '</article>'
    )).join('') : emptyMarkup('No occurrences on this page', 'The relationship may have changed; refresh the analysis if this persists.');
    const total = Number(payload.total || 0);
    const page = Number(payload.offset || 0) / Number(payload.limit || state.evidence.pageSize);
    const pageSize = Number(payload.limit || state.evidence.pageSize);
    const pageCount = Math.max(1, Math.ceil(total / pageSize));
    const currentPage = Math.min(pageCount - 1, Math.max(0, Math.floor(page)));
    el('candidate-evidence-range').textContent = total ? (formatCount((currentPage * pageSize) + 1) + '–' + formatCount(Math.min(total, (currentPage + 1) * pageSize)) + ' of ' + formatCount(total)) : '0 occurrences';
    const pager = el('candidate-evidence-pagination');
    if (window.QymUIComponents && window.QymUIComponents.renderPagination) {
      window.QymUIComponents.renderPagination(pager, {
        total,
        pageSize,
        page: currentPage,
      });
    } else {
      pager.innerHTML = [
        ['First', 0, currentPage === 0],
        ['Previous', currentPage - 1, currentPage === 0],
        ['Next', currentPage + 1, currentPage >= pageCount - 1],
        ['Last', pageCount - 1, currentPage >= pageCount - 1],
      ].map(([label, target, disabled]) => '<button class="qym-icon-action" type="button" aria-label="' + label + ' occurrence page" data-qym-page="' + target + '"' + (disabled ? ' disabled' : '') + '>' + escapeHtml(label === 'Previous' ? '‹' : label === 'Next' ? '›' : label === 'First' ? '«' : '»') + '</button>').join('');
    }
  }

  async function loadEvidence(relationshipId, page) {
    state.evidence.relationshipId = relationshipId;
    state.evidence.page = page;
    state.evidence.payload = null;
    el('candidate-evidence-drawer').hidden = false;
    el('candidate-evidence-list').innerHTML = emptyMarkup('Loading matching executions', 'Fetching the executions that match this condition.');
    const offset = page * state.evidence.pageSize;
    const endpoint = 'api/projects/' + encodeURIComponent(state.projectSlug) + '/insights/relationships/' + encodeURIComponent(relationshipId) + '/occurrences?limit=' + state.evidence.pageSize + '&offset=' + offset;
    const response = await fetch(apiUrl(endpoint));
    if (response.status === 410) {
      el('candidate-evidence-list').innerHTML = emptyMarkup('This analysis is out of date', 'The project changed while these executions were loading. Refreshing the analysis.');
      await loadAnalysis();
      return;
    }
    if (!response.ok) throw new Error('Matching execution request failed (' + response.status + ')');
    state.evidence.payload = await response.json();
    renderEvidence();
  }

  async function loadAnalysis() {
    const host = el('candidate-groups');
    if (host) host.innerHTML = emptyMarkup('Loading candidate relationships', 'Analyzing stable run-item-metric executions across the project.');
    const endpoint = 'api/projects/' + encodeURIComponent(state.projectSlug) + '/insights/relationships';
    const response = await fetch(apiUrl(endpoint));
    if (!response.ok) throw new Error('Relationship analysis request failed (' + response.status + ')');
    state.payload = await response.json();
    summary(state.payload);
    renderGroups();
  }

  function closeEvidence() {
    const drawer = el('candidate-evidence-drawer');
    if (drawer) drawer.hidden = true;
    state.evidence.payload = null;
  }

  function bind() {
    document.querySelectorAll('[data-candidate-direction]').forEach(button => {
      button.addEventListener('click', () => setDirection(button.dataset.candidateDirection || 'all'));
    });
    const search = el('candidate-category-search');
    if (search) search.addEventListener('input', event => {
      state.query = event.target.value || '';
      renderGroups();
    });
    el('candidate-groups').addEventListener('click', event => {
      const button = event.target.closest('[data-candidate-evidence]');
      if (!button) return;
      loadEvidence(button.dataset.candidateEvidence, 0).catch(error => {
        el('candidate-evidence-list').innerHTML = emptyMarkup('Evidence unavailable', error.message || 'Could not load relationship occurrences.');
      });
    });
    el('candidate-evidence-close').addEventListener('click', closeEvidence);
    el('candidate-evidence-drawer').addEventListener('click', event => {
      if (event.target === el('candidate-evidence-drawer')) closeEvidence();
    });
    el('candidate-evidence-pagination').addEventListener('click', event => {
      const button = event.target.closest('[data-qym-page]');
      if (!button || button.disabled) return;
      loadEvidence(state.evidence.relationshipId, Number(button.dataset.qymPage)).catch(error => {
        el('candidate-evidence-list').innerHTML = emptyMarkup('Evidence unavailable', error.message || 'Could not load relationship occurrences.');
      });
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !el('candidate-evidence-drawer').hidden) closeEvidence();
    });
  }

  async function init() {
    if (!el('candidate-relationships-card')) return;
    if (window.QymShell && !window.__QYM_USER__) {
      await new Promise(resolve => document.addEventListener('qym:shell-ready', resolve, { once: true }));
    }
    state.projectSlug = projectSlugFromPage();
    if (!state.projectSlug) {
      el('candidate-groups').innerHTML = emptyMarkup('Choose a project', 'Candidate relationships are scoped to a project.');
      return;
    }
    bind();
    try {
      await loadAnalysis();
    } catch (error) {
      el('candidate-groups').innerHTML = emptyMarkup('Candidate relationships are unavailable', error.message || 'The project analysis could not be loaded.');
      if (el('candidate-scope-note')) el('candidate-scope-note').textContent = 'Unavailable';
    }
  }

  init();
})();
