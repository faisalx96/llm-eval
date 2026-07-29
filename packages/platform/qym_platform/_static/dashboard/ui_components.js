/**
 * Qym shared UI component behavior.
 *
 * Keeps interaction and accessibility behavior paired with ui_components.css,
 * including standalone run/comparison exports where the application shell is
 * intentionally unavailable.
 */
(function () {
  'use strict';

  if (window.QymUIComponents) return;

  var helpId = 0;
  var dropdownId = 0;
  var helpPortal = null;
  var helpPortalMarker = null;

  function helpMarkers() {
    return document.querySelectorAll('.qym-help-marker, .stat-info-icon');
  }

  function ensureHelpMarker(marker) {
    if (!marker) return;
    var tooltip = marker.querySelector('.qym-help-tooltip, .stat-info-tooltip');
    if (!tooltip) return;
    if (!tooltip.id) {
      helpId += 1;
      tooltip.id = 'qym-help-tooltip-' + helpId;
    }
    marker.setAttribute('aria-describedby', tooltip.id);
    marker.classList.add('qym-help-marker--portal');
    if (!marker.hasAttribute('aria-expanded')) {
      marker.setAttribute('aria-expanded', 'false');
    }
  }

  function hideHelpPortal() {
    if (helpPortal) helpPortal.classList.remove('is-open');
    helpPortalMarker = null;
  }

  function showHelpPortal(marker) {
    ensureHelpMarker(marker);
    var tooltip = marker && marker.querySelector('.qym-help-tooltip, .stat-info-tooltip');
    if (!tooltip) return;
    if (!helpPortal) {
      helpPortal = document.createElement('div');
      helpPortal.className = 'qym-help-tooltip qym-help-tooltip-portal';
      helpPortal.setAttribute('aria-hidden', 'true');
      document.body.appendChild(helpPortal);
    }
    helpPortal.textContent = tooltip.textContent;
    helpPortal.classList.add('is-open');
    helpPortalMarker = marker;

    var rect = marker.getBoundingClientRect();
    var half = Math.min(110, Math.max(0, window.innerWidth / 2 - 8));
    var center = rect.left + rect.width / 2;
    var left = Math.max(half + 8, Math.min(window.innerWidth - half - 8, center));
    helpPortal.style.left = Math.round(left) + 'px';
    helpPortal.style.top = Math.round(rect.top - 8) + 'px';
    helpPortal.style.transform = 'translate(-50%, -100%)';
    if (rect.top < helpPortal.offsetHeight + 16) {
      helpPortal.style.top = Math.round(rect.bottom + 8) + 'px';
      helpPortal.style.transform = 'translateX(-50%)';
    }
  }

  function closeHelpMarkers(except) {
    helpMarkers().forEach(function (marker) {
      if (marker === except) return;
      marker.classList.remove('is-open');
      marker.setAttribute('aria-expanded', 'false');
    });
    if (helpPortalMarker && helpPortalMarker !== except) hideHelpPortal();
  }

  function toggleHelpMarker(marker) {
    ensureHelpMarker(marker);
    var wasOpen = marker.classList.contains('is-open');
    closeHelpMarkers(marker);
    marker.classList.toggle('is-open', !wasOpen);
    marker.setAttribute('aria-expanded', wasOpen ? 'false' : 'true');
    if (wasOpen) {
      hideHelpPortal();
    } else {
      marker.focus({ preventScroll: true });
      showHelpPortal(marker);
    }
  }

  function directTabs(tablist) {
    return Array.from(tablist.querySelectorAll('[role="tab"]')).filter(function (tab) {
      return tab.closest('[role="tablist"]') === tablist && !tab.disabled;
    });
  }

  function syncTablist(tablist) {
    if (!tablist || !tablist.matches('.qym-tabs[role="tablist"]')) return;
    var tabs = directTabs(tablist);
    if (!tabs.length) return;
    var active = tabs.find(function (tab) {
      return tab.getAttribute('aria-selected') === 'true' || tab.classList.contains('active');
    }) || tabs[0];
    tabs.forEach(function (tab) {
      tab.setAttribute('tabindex', tab === active ? '0' : '-1');
    });
  }

  function ensureDropdownButton(button) {
    if (!button) return;
    var wrapper = button.closest('.multi-select-wrapper');
    var dropdown = wrapper && wrapper.querySelector('.multi-select-dropdown, .qym-dropdown');
    if (!dropdown) return;
    if (!dropdown.id) {
      dropdownId += 1;
      dropdown.id = 'qym-dropdown-' + dropdownId;
    }
    button.setAttribute('aria-haspopup', 'dialog');
    button.setAttribute('aria-controls', dropdown.id);
    button.setAttribute('aria-expanded', dropdown.classList.contains('open') ? 'true' : 'false');
    dropdown.setAttribute('role', 'dialog');
    if (!dropdown.hasAttribute('aria-label')) {
      dropdown.setAttribute('aria-label', (button.textContent || 'Filter').trim() + ' options');
    }
  }

  function refresh(root) {
    var scope = root && root.querySelectorAll ? root : document;
    if (scope.matches && scope.matches('.qym-help-marker, .stat-info-icon')) {
      ensureHelpMarker(scope);
    }
    scope.querySelectorAll('.qym-help-marker, .stat-info-icon').forEach(ensureHelpMarker);
    if (scope.matches && scope.matches('.qym-tabs[role="tablist"]')) {
      syncTablist(scope);
    }
    scope.querySelectorAll('.qym-tabs[role="tablist"]').forEach(syncTablist);
    if (scope.matches && scope.matches('.multi-select-btn, [aria-controls]')) {
      ensureDropdownButton(scope);
    }
    if (scope.matches && scope.matches('.multi-select-dropdown, .qym-dropdown')) {
      var wrapper = scope.closest('.multi-select-wrapper');
      ensureDropdownButton(wrapper && wrapper.querySelector('.multi-select-btn'));
    }
    scope.querySelectorAll('.multi-select-btn').forEach(ensureDropdownButton);
  }

  document.addEventListener('click', function (event) {
    var marker = event.target.closest('.qym-help-marker, .stat-info-icon');
    if (!marker) {
      closeHelpMarkers(null);
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    toggleHelpMarker(marker);
  }, true);

  document.addEventListener('mouseover', function (event) {
    var marker = event.target.closest('.qym-help-marker, .stat-info-icon');
    if (marker) showHelpPortal(marker);
  });

  document.addEventListener('mouseout', function (event) {
    var marker = event.target.closest('.qym-help-marker, .stat-info-icon');
    if (!marker || marker.contains(event.relatedTarget) || marker.classList.contains('is-open')) return;
    hideHelpPortal();
  });

  document.addEventListener('focusin', function (event) {
    var marker = event.target.closest('.qym-help-marker, .stat-info-icon');
    if (marker) showHelpPortal(marker);
  });

  document.addEventListener('focusout', function (event) {
    var marker = event.target.closest('.qym-help-marker, .stat-info-icon');
    if (marker && !marker.classList.contains('is-open')) hideHelpPortal();
  });

  document.addEventListener('click', function (event) {
    var tab = event.target.closest('.qym-tabs[role="tablist"] [role="tab"]');
    if (!tab) return;
    var tablist = tab.closest('.qym-tabs[role="tablist"]');
    window.setTimeout(function () { syncTablist(tablist); }, 0);
  });

  document.addEventListener('click', function () {
    window.setTimeout(function () {
      document.querySelectorAll('.multi-select-btn').forEach(ensureDropdownButton);
    }, 0);
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      var dropdownWrapper = event.target.closest('.multi-select-wrapper');
      var openDropdown = dropdownWrapper && dropdownWrapper.querySelector('.multi-select-dropdown.open, .qym-dropdown.open');
      if (openDropdown) {
        event.preventDefault();
        event.stopPropagation();
        openDropdown.classList.remove('open');
        var dropdownButton = dropdownWrapper.querySelector('.multi-select-btn');
        ensureDropdownButton(dropdownButton);
        if (dropdownButton) dropdownButton.focus({ preventScroll: true });
        return;
      }
    }

    var marker = event.target.closest('.qym-help-marker, .stat-info-icon');
    if (marker && (event.key === 'Enter' || event.key === ' ' || event.key === 'Escape')) {
      event.preventDefault();
      event.stopPropagation();
      if (event.key === 'Escape') {
        closeHelpMarkers(null);
      } else {
        toggleHelpMarker(marker);
      }
      return;
    }

    var tab = event.target.closest('.qym-tabs[role="tablist"] [role="tab"]');
    if (!tab || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    var tablist = tab.closest('.qym-tabs[role="tablist"]');
    var tabs = directTabs(tablist);
    var current = tabs.indexOf(tab);
    if (current < 0 || !tabs.length) return;

    event.preventDefault();
    event.stopPropagation();
    var next = current;
    if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    else if (event.key === 'ArrowRight') next = (current + 1) % tabs.length;
    else next = (current - 1 + tabs.length) % tabs.length;
    var tablistId = tablist.id;
    var tablistLabel = tablist.getAttribute('aria-label');
    tabs[next].focus();
    tabs[next].click();
    window.setTimeout(function () {
      var replacement = tablist.isConnected ? tablist : null;
      if (!replacement && tablistId) replacement = document.getElementById(tablistId);
      if (!replacement && tablistLabel) {
        replacement = Array.from(document.querySelectorAll('.qym-tabs[role="tablist"]')).find(function (candidate) {
          return candidate.getAttribute('aria-label') === tablistLabel;
        }) || null;
      }
      if (!replacement) return;
      syncTablist(replacement);
      var replacementTabs = directTabs(replacement);
      var active = replacementTabs.find(function (candidate) {
        return candidate.getAttribute('aria-selected') === 'true' || candidate.classList.contains('active');
      }) || replacementTabs[next];
      if (active) active.focus({ preventScroll: true });
    }, 0);
  }, true);

  function dismissHelpOnViewportChange() {
    if (helpPortalMarker) closeHelpMarkers(null);
  }

  window.addEventListener('resize', dismissHelpOnViewportChange);
  window.addEventListener('scroll', dismissHelpOnViewportChange, true);

  function start() {
    refresh(document);
    if (!window.MutationObserver) return;
    var observer = new MutationObserver(function (records) {
      records.forEach(function (record) {
        if (record.type === 'childList') {
          record.addedNodes.forEach(function (node) {
            if (node.nodeType === 1) refresh(node);
          });
          syncTablist(record.target.closest && record.target.closest('.qym-tabs[role="tablist"]'));
        } else if (record.target.closest) {
          syncTablist(record.target.closest('.qym-tabs[role="tablist"]'));
          if (record.target.matches('.multi-select-dropdown, .qym-dropdown')) {
            var wrapper = record.target.closest('.multi-select-wrapper');
            ensureDropdownButton(wrapper && wrapper.querySelector('.multi-select-btn'));
          }
        }
      });
    });
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['aria-selected', 'class'],
    });
  }

  window.QymUIComponents = {
    closeHelpMarkers: closeHelpMarkers,
    refresh: refresh,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true });
  } else {
    start();
  }
})();
