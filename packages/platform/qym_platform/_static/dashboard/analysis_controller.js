/*
 * AnalysisController is intentionally DOM-free.  It keeps route/view rules in
 * one place so the project page and the focused run workspace do not need to
 * infer each other's state from DOM placement.
 */
(function (global) {
  'use strict';

  var PROJECT_VIEWS = ['dashboard', 'categories', 'rules', 'documents'];
  var RUN_VIEW = 'run';

  function validView(view, hasRun) {
    if (PROJECT_VIEWS.indexOf(view) !== -1) return view;
    if (view === RUN_VIEW) return RUN_VIEW;
    return hasRun ? RUN_VIEW : 'dashboard';
  }

  function create(options) {
    options = options || {};
    var hasRun = !!options.hasRun;
    // A focused run owns a single workspace. Project configuration must not
    // leak into that route merely because a stale `scope` query remains.
    var currentView = hasRun ? RUN_VIEW : validView(options.initialView, false);
    var requestSequences = {};
    var destroyed = false;
    var listeners = [];
    var requests = {};
    var state = {
      view: currentView,
      phase: 'idle',
      error: null,
      filters: {},
      selection: null,
      preview: null,
      result: null,
      requests: {},
    };

    function snapshot() {
      return {
        view: state.view,
        phase: state.phase,
        error: state.error,
        filters: Object.assign({}, state.filters),
        selection: state.selection && Object.assign({}, state.selection),
        preview: state.preview,
        result: state.result,
        requests: Object.assign({}, state.requests),
      };
    }

    function publish() {
      var next = snapshot();
      listeners.slice().forEach(function (listener) { listener(next); });
    }

    function syncPhase() {
      state.phase = Object.keys(state.requests).length ? 'loading' : 'ready';
    }

    function run(key, loader) {
      if (destroyed) return Promise.reject(new Error('Analysis controller has been destroyed.'));
      if (requests[key]) requests[key].abort();
      var abort = new AbortController();
      var token = (requestSequences[key] || 0) + 1;
      requestSequences[key] = token;
      requests[key] = abort;
      state.requests[key] = 'loading';
      syncPhase();
      state.error = null;
      publish();
      return Promise.resolve(loader({ signal: abort.signal, token: token })).then(function (value) {
        if (destroyed || token !== requestSequences[key] || abort.signal.aborted) return undefined;
        delete requests[key];
        delete state.requests[key];
        syncPhase();
        state.result = value;
        publish();
        return value;
      }, function (error) {
        if (abort.signal.aborted || destroyed || token !== requestSequences[key]) return undefined;
        delete requests[key];
        delete state.requests[key];
        // A sibling request can still be loading; retain that meaningful
        // lifecycle phase while exposing the error to subscribed renderers.
        state.phase = Object.keys(state.requests).length ? 'loading' : 'error';
        state.error = error;
        publish();
        throw error;
      });
    }

    return {
      getView: function () { return state.view; },
      getState: snapshot,
      subscribe: function (listener) {
        listeners.push(listener);
        listener(snapshot());
        return function () { listeners = listeners.filter(function (item) { return item !== listener; }); };
      },
      setView: function (view) {
        currentView = hasRun ? RUN_VIEW : validView(view, false);
        state.view = currentView;
        publish();
        return currentView;
      },
      setFilters: function (filters) { state.filters = Object.assign({}, filters || {}); publish(); },
      selectTarget: function (target) { state.selection = target ? Object.assign({}, target) : null; publish(); },
      setPreview: function (preview) { state.preview = preview; publish(); },
      run: run,
      preview: function (loader) {
        return run('preview', loader).then(function (preview) {
          if (preview !== undefined) { state.preview = preview; publish(); }
          return preview;
        });
      },
      test: function (loader) { return run('test', loader); },
      analyzeStream: function (loader) { return run('analyze-stream', loader); },
      dashboard: function (loader) { return run('dashboard', loader); },
      cancel: function (key) {
        if (requests[key]) requests[key].abort();
        delete state.requests[key];
        syncPhase();
        publish();
      },
      destroy: function () {
        destroyed = true;
        Object.keys(requests).forEach(function (key) { requests[key].abort(); });
        requests = {};
        listeners = [];
      },
      isProjectView: function (view) {
        return PROJECT_VIEWS.indexOf(view) !== -1;
      },
      nextRequest: function (key) {
        key = key || 'default';
        requestSequences[key] = (requestSequences[key] || 0) + 1;
        return requestSequences[key];
      },
      isCurrentRequest: function (token, key) { return token === requestSequences[key || 'default']; },
    };
  }

  function bindTabs(tablist, onSelect) {
    if (!tablist || tablist.dataset.analysisTabKeysBound === 'true') return;
    tablist.dataset.analysisTabKeysBound = 'true';
    tablist.addEventListener('keydown', function (event) {
      var keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End'];
      if (keys.indexOf(event.key) === -1) return;
      var tabs = Array.prototype.slice.call(tablist.querySelectorAll('[role="tab"]'))
        .filter(function (tab) { return !tab.hidden && !tab.disabled && tab.getAttribute('aria-disabled') !== 'true'; });
      if (!tabs.length) return;
      var index = tabs.indexOf(document.activeElement);
      if (index < 0) index = tabs.findIndex(function (tab) { return tab.getAttribute('aria-selected') === 'true'; });
      if (event.key === 'Home') index = 0;
      else if (event.key === 'End') index = tabs.length - 1;
      else index = (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      event.preventDefault();
      event.stopPropagation();
      var tab = tabs[index];
      onSelect(tab.dataset.analysisView, { focus: true });
    });
  }

  global.QymAnalysisController = { create: create, bindTabs: bindTabs, PROJECT_VIEWS: PROJECT_VIEWS.slice() };
})(window);
