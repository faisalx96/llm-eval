/* Page-only adapters for the Auto-analysis controller. */
(function (global) {
  'use strict';

  function syncTabs(view, root) {
    (root || document).querySelectorAll('[data-analysis-view]').forEach(function (tab) {
      var active = tab.dataset.analysisView === view;
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
      tab.tabIndex = active ? 0 : -1;
      tab.classList.toggle('active', active);
    });
  }

  function updateViewUrl(view) {
    var params = new URLSearchParams(window.location.search);
    params.set('scope', view);
    history.replaceState(history.state, '', window.location.pathname + '?' + params.toString());
  }

  function renderCompletion(summary) {
    var runView = document.getElementById('analysis-run-view');
    if (!runView) return;
    var region = document.getElementById('analysis-completion-summary');
    if (!region) {
      region = document.createElement('div');
      region.id = 'analysis-completion-summary';
      region.className = 'qym-alert qym-alert--success';
      region.setAttribute('role', 'status');
      region.setAttribute('aria-live', 'polite');
      var footer = runView.querySelector('.playground-footer');
      runView.insertBefore(region, footer || null);
    }
    region.className = 'qym-alert ' + (summary && summary.partial ? 'qym-alert--warning' : 'qym-alert--success');
    region.hidden = false;
    region.textContent = (summary && summary.message) || 'Analysis results were saved.';
  }

  // Dedicated workspace mounting is kept out of Playground's modal adapter.
  // The page renderer owns its route host and mounts the fully-built workspace
  // once, without observing or reparenting live child nodes later.
  function mountDedicatedWorkspace(container, workspace) {
    if (!container || !workspace) return false;
    container.replaceChildren(workspace);
    return true;
  }

  global.QymAnalysisPage = {
    syncTabs: syncTabs,
    updateViewUrl: updateViewUrl,
    renderCompletion: renderCompletion,
    mountDedicatedWorkspace: mountDedicatedWorkspace,
    bindTabs: function (tablist, select) {
      if (global.QymAnalysisController) global.QymAnalysisController.bindTabs(tablist, select);
    },
  };
})(window);
