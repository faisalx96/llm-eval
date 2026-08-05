(() => {
  'use strict';

  const segmentedState = new Map();
  const observedSegmented = new WeakSet();
  let helpTooltipSequence = 0;
  let refreshQueued = false;

  function enabledItems(container, selector) {
    return Array.from(container.querySelectorAll(selector)).filter(item => !item.disabled);
  }

  function syncTablist(tablist) {
    const tabs = enabledItems(tablist, '.qym-tabs__tab');
    if (!tabs.length) return;
    const selected = tabs.find(tab => tab.getAttribute('aria-selected') === 'true') || tabs[0];
    tabs.forEach(tab => { tab.tabIndex = tab === selected ? 0 : -1; });
  }

  function segmentedKey(control) {
    return control.dataset.qymSegmentedKey || control.id || '';
  }

  function positionSegmented(control) {
    const selected = control.querySelector('.qym-segmented__option[aria-pressed="true"]');
    const indicator = control.querySelector('.qym-segmented__indicator');
    if (!selected || !indicator || !control.offsetWidth || !selected.offsetWidth) return;

    const next = { left: selected.offsetLeft, width: selected.offsetWidth };
    const key = segmentedKey(control);
    const previous = key ? segmentedState.get(key) : null;
    if (!control.classList.contains('qym-segmented--enhanced') && previous) {
      indicator.style.width = previous.width + 'px';
      indicator.style.transform = 'translateX(' + previous.left + 'px)';
    }
    control.classList.add('qym-segmented--enhanced');
    requestAnimationFrame(() => {
      indicator.style.width = next.width + 'px';
      indicator.style.transform = 'translateX(' + next.left + 'px)';
      if (key) segmentedState.set(key, next);
    });
  }

  function enhanceSegmented(control) {
    if (!control.querySelector('.qym-segmented__indicator')) {
      const indicator = document.createElement('span');
      indicator.className = 'qym-segmented__indicator';
      indicator.setAttribute('aria-hidden', 'true');
      control.prepend(indicator);
    }
    positionSegmented(control);
    if (!observedSegmented.has(control) && window.ResizeObserver) {
      const observer = new ResizeObserver(() => positionSegmented(control));
      observer.observe(control);
      observedSegmented.add(control);
    }
  }

  function enhanceHelpMarker(marker) {
    const tooltip = marker.querySelector('.qym-help-tooltip');
    if (!tooltip) return;
    if (!tooltip.id) tooltip.id = 'qym-help-tooltip-' + (++helpTooltipSequence);
    marker.tabIndex = marker.tabIndex >= 0 ? marker.tabIndex : 0;
    marker.setAttribute('aria-describedby', tooltip.id);
  }

  function closeDropdown(dropdown, restoreFocus = false) {
    if (!dropdown) return;
    dropdown.classList.remove('is-open');
    const trigger = dropdown.querySelector('.qym-dropdown__trigger');
    if (trigger) {
      trigger.setAttribute('aria-expanded', 'false');
      if (restoreFocus) trigger.focus();
    }
  }

  function closeOtherDropdowns(active) {
    document.querySelectorAll('.qym-dropdown.is-open').forEach(dropdown => {
      if (dropdown !== active) closeDropdown(dropdown);
    });
  }

  function toggleDropdown(dropdown) {
    const willOpen = !dropdown.classList.contains('is-open');
    closeOtherDropdowns(dropdown);
    dropdown.classList.toggle('is-open', willOpen);
    const trigger = dropdown.querySelector('.qym-dropdown__trigger');
    if (trigger) trigger.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
    if (willOpen) {
      const search = dropdown.querySelector('.qym-dropdown__search');
      if (search) requestAnimationFrame(() => search.focus());
    }
  }

  function filterDropdown(search) {
    const dropdown = search.closest('.qym-dropdown');
    if (!dropdown) return;
    const query = search.value.trim().toLocaleLowerCase();
    dropdown.querySelectorAll('.qym-dropdown__option').forEach(option => {
      const text = (option.dataset.qymDropdownSearchText || option.textContent || '').toLocaleLowerCase();
      option.hidden = Boolean(query) && !text.includes(query);
    });
  }

  function refresh(root = document) {
    const scope = root.querySelectorAll ? root : document;
    scope.querySelectorAll('.qym-tabs').forEach(syncTablist);
    scope.querySelectorAll('.qym-segmented').forEach(enhanceSegmented);
    scope.querySelectorAll('.qym-help-marker').forEach(enhanceHelpMarker);
  }

  function queueRefresh() {
    if (refreshQueued) return;
    refreshQueued = true;
    requestAnimationFrame(() => {
      refreshQueued = false;
      refresh(document);
    });
  }

  function renderPagination(host, options = {}) {
    if (!host) return;
    const total = Math.max(0, Number(options.total || 0));
    const pageSize = Math.max(1, Number(options.pageSize || 20));
    const pageCount = Math.max(1, Math.ceil(total / pageSize));
    const page = Math.min(pageCount - 1, Math.max(0, Number(options.page || 0)));
    const controls = [
      ['First', 0, page === 0, '«'],
      ['Previous', page - 1, page === 0, '‹'],
      ['Next', page + 1, page >= pageCount - 1, '›'],
      ['Last', pageCount - 1, page >= pageCount - 1, '»'],
    ];
    host.classList.add('qym-pagination');
    host.innerHTML = controls.map(([label, target, disabled, glyph]) => (
      '<button class="qym-icon-action" type="button" aria-label="' + label + ' page" data-qym-page="' + target + '"' + (disabled ? ' disabled' : '') + '>' + glyph + '</button>'
    )).join('');
    return { page, pageCount };
  }

  document.addEventListener('click', event => {
    const trigger = event.target.closest('.qym-dropdown__trigger');
    if (trigger) {
      const dropdown = trigger.closest('.qym-dropdown');
      if (dropdown) toggleDropdown(dropdown);
      return;
    }

    const helpMarker = event.target.closest('.qym-help-marker');
    if (helpMarker) {
      document.querySelectorAll('.qym-help-marker.is-pinned').forEach(marker => {
        if (marker !== helpMarker) marker.classList.remove('is-pinned');
      });
      helpMarker.classList.toggle('is-pinned');
      return;
    }

    if (!event.target.closest('.qym-dropdown')) closeOtherDropdowns(null);
    if (!event.target.closest('.qym-help-marker')) {
      document.querySelectorAll('.qym-help-marker.is-pinned').forEach(marker => marker.classList.remove('is-pinned'));
    }

    const segmentedOption = event.target.closest('.qym-segmented__option');
    if (segmentedOption) requestAnimationFrame(() => positionSegmented(segmentedOption.closest('.qym-segmented')));
  });

  document.addEventListener('input', event => {
    if (event.target.matches('.qym-dropdown__search')) filterDropdown(event.target);
  });

  document.addEventListener('keydown', event => {
    const tab = event.target.closest('.qym-tabs__tab');
    if (tab && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
      const tablist = tab.closest('.qym-tabs');
      const tabs = enabledItems(tablist, '.qym-tabs__tab');
      if (!tabs.length) return;
      event.preventDefault();
      const currentIndex = Math.max(tabs.indexOf(tab), 0);
      const nextIndex = event.key === 'Home'
        ? 0
        : (event.key === 'End'
          ? tabs.length - 1
          : (currentIndex + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length);
      tabs[nextIndex].focus();
      tabs[nextIndex].click();
      return;
    }

    const option = event.target.closest('.qym-segmented__option');
    if (option && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
      const control = option.closest('.qym-segmented');
      const options = enabledItems(control, '.qym-segmented__option');
      if (!options.length) return;
      event.preventDefault();
      const currentIndex = Math.max(options.indexOf(option), 0);
      const nextIndex = event.key === 'Home'
        ? 0
        : (event.key === 'End'
          ? options.length - 1
          : (currentIndex + (event.key === 'ArrowRight' ? 1 : -1) + options.length) % options.length);
      options[nextIndex].focus();
      options[nextIndex].click();
      return;
    }

    if (event.key === 'Escape') {
      const dropdown = event.target.closest('.qym-dropdown') || document.querySelector('.qym-dropdown.is-open');
      if (dropdown) {
        event.preventDefault();
        closeDropdown(dropdown, true);
      }
      document.querySelectorAll('.qym-help-marker.is-pinned').forEach(marker => marker.classList.remove('is-pinned'));
    }
  });

  const observer = new MutationObserver(queueRefresh);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['aria-pressed', 'aria-selected', 'disabled', 'hidden'],
    childList: true,
    subtree: true,
  });

  const api = window.QymUIComponents || {};
  api.refresh = refresh;
  api.closeDropdowns = () => closeOtherDropdowns(null);
  api.renderPagination = renderPagination;
  window.QymUIComponents = api;

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => refresh(document));
  else refresh(document);
})();
