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
  var segmentResizeObservers = new WeakMap();
  var segmentSyncFrames = new WeakMap();
  var segmentPositions = new Map();
  var PAGINATION_ICONS = {
    first: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m11 17-5-5 5-5"/><path d="m18 17-5-5 5-5"/></svg>',
    prev: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 18-6-6 6-6"/></svg>',
    next: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg>',
    last: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 17 5-5-5-5"/><path d="m13 17 5-5-5-5"/></svg>'
  };

  function resetPaginationScroll(options) {
    var target = options && options.scrollHost;
    if (typeof target === 'string') target = document.getElementById(target);
    if (!target) return;
    target.scrollTop = 0;
  }

  function renderLegacyPagination(host, options) {
    var total = Math.max(0, Number(options.total) || 0);
    var pageSize = Math.max(1, Number(options.pageSize) || 20);
    var pageCount = Math.max(1, Math.ceil(total / pageSize));
    var page = Math.min(pageCount - 1, Math.max(0, Math.floor(Number(options.page) || 0)));
    var compact = options.variant === 'compact';

    host.classList.add('qym-pagination', compact ? 'qym-pagination--compact' : 'qym-pagination--run');
    host.classList.remove(compact ? 'qym-pagination--run' : 'qym-pagination--compact');
    if (compact) {
      host.innerHTML =
        '<button class="qym-icon-action" type="button" aria-label="Previous page" data-qym-page="' + (page - 1) + '"' + (page === 0 ? ' disabled' : '') + '>‹</button>' +
        '<span class="qym-pagination__page-static" aria-live="polite">Page ' + (page + 1) + ' of ' + pageCount + '</span>' +
        '<button class="qym-icon-action" type="button" aria-label="Next page" data-qym-page="' + (page + 1) + '"' + (page >= pageCount - 1 ? ' disabled' : '') + '>›</button>';
    } else {
      host.innerHTML =
        '<button class="qym-pagination__button" type="button" aria-label="Previous page" data-qym-page="' + (page - 1) + '"' + (page === 0 ? ' disabled' : '') + '>&larr; Prev</button>' +
        '<span class="qym-pagination__page-info" aria-live="polite">Page ' + (page + 1) + ' of ' + pageCount + '</span>' +
        '<button class="qym-pagination__button" type="button" aria-label="Next page" data-qym-page="' + (page + 1) + '"' + (page >= pageCount - 1 ? ' disabled' : '') + '>Next &rarr;</button>';
    }

    if (typeof options.onPageChange === 'function') {
      host.querySelectorAll('[data-qym-page]').forEach(function (button) {
        button.addEventListener('click', function (event) {
          if (button.disabled) return;
          var nextPage = Number(button.getAttribute('data-qym-page'));
          if (!Number.isFinite(nextPage)) return;
          event.preventDefault();
          event.stopPropagation();
          resetPaginationScroll(options);
          options.onPageChange(nextPage);
        });
      });
    }
    return { page: page, pageCount: pageCount };
  }

  function renderPagination(host, options) {
    if (!host) return;
    options = options || {};
    if (options.variant === 'run' || options.variant === 'compact') {
      return renderLegacyPagination(host, options);
    }

    var total = Math.max(0, Number(options.total) || 0);
    var pageSize = Math.max(1, Math.floor(Number(options.pageSize) || 1));
    var configuredPageCount = Math.floor(Number(options.pageCount));
    var pageCount = Math.max(1, configuredPageCount || Math.ceil(total / pageSize) || 1);
    var isEmpty = total === 0;
    var page = Math.min(pageCount, Math.max(1, Math.floor(Number(options.page) || 1)));
    var start = isEmpty ? 0 : Math.max(1, Number(options.start) || ((page - 1) * pageSize + 1));
    var end = isEmpty ? 0 : Math.min(total, Number(options.end) || (page * pageSize));
    var noun = String(options.noun || 'items');
    var atFirst = isEmpty || page <= 1;
    var atLast = isEmpty || page >= pageCount;
    var pageSizeOptions = Array.isArray(options.pageSizeOptions) ? options.pageSizeOptions : [];

    host.classList.add('qym-pagination');
    host.setAttribute('role', 'navigation');
    if (!host.hasAttribute('aria-label')) host.setAttribute('aria-label', noun + ' pagination');

    var sizeHtml = '';
    if (pageSizeOptions.length) {
      sizeHtml = '<select class="qym-pagination__size" aria-label="' + noun + ' per page">'
        + pageSizeOptions.map(function (size) {
          var numericSize = Math.max(1, Math.floor(Number(size) || 1));
          return '<option value="' + numericSize + '"' + (numericSize === pageSize ? ' selected' : '') + '>'
            + numericSize + '/page</option>';
        }).join('')
        + '</select>';
    }

    host.innerHTML =
      (options.showSummary === false ? '' :
        '<div class="qym-pagination__summary">' + start + '–' + end + ' of ' + total + ' ' + noun + '</div>') +
      '<div class="qym-pagination__controls">' +
        sizeHtml +
        '<button class="qym-pagination__button" type="button" data-qym-page="first" aria-label="First page" title="First page"' + (atFirst ? ' disabled' : '') + '>' + PAGINATION_ICONS.first + '</button>' +
        '<button class="qym-pagination__button" type="button" data-qym-page="prev" aria-label="Previous page" title="Previous page"' + (atFirst ? ' disabled' : '') + '>' + PAGINATION_ICONS.prev + '</button>' +
        '<label class="qym-pagination__page">' +
          '<input class="qym-pagination__input" type="number" min="1" max="' + pageCount + '" step="1" value="' + (isEmpty ? 0 : page) + '" style="--qym-page-digits:' + String(isEmpty ? 1 : pageCount).length + '" aria-label="Page number"' + (isEmpty ? ' disabled' : '') + '>' +
          '<span aria-hidden="true">of</span>' +
          '<span class="qym-pagination__total">' + (isEmpty ? 0 : pageCount) + '</span>' +
        '</label>' +
        '<button class="qym-pagination__button" type="button" data-qym-page="next" aria-label="Next page" title="Next page"' + (atLast ? ' disabled' : '') + '>' + PAGINATION_ICONS.next + '</button>' +
        '<button class="qym-pagination__button" type="button" data-qym-page="last" aria-label="Last page" title="Last page"' + (atLast ? ' disabled' : '') + '>' + PAGINATION_ICONS.last + '</button>' +
      '</div>';

    function requestPage(nextPage) {
      var normalized = Math.min(pageCount, Math.max(1, Math.floor(Number(nextPage) || 1)));
      if (normalized === page) {
        var input = host.querySelector('.qym-pagination__input');
        if (input) input.value = isEmpty ? 0 : page;
        return;
      }
      if (typeof options.onPageChange === 'function') {
        resetPaginationScroll(options);
        options.onPageChange(normalized);
      }
    }

    host.querySelectorAll('[data-qym-page]').forEach(function (button) {
      button.addEventListener('click', function (event) {
        if (button.disabled) return;
        event.preventDefault();
        event.stopPropagation();
        var action = button.getAttribute('data-qym-page');
        if (action === 'first') requestPage(1);
        else if (action === 'prev') requestPage(page - 1);
        else if (action === 'next') requestPage(page + 1);
        else if (action === 'last') requestPage(pageCount);
      });
    });

    var pageInput = host.querySelector('.qym-pagination__input');
    if (pageInput) {
      pageInput.addEventListener('focus', function () { pageInput.select(); });
      pageInput.addEventListener('change', function () { requestPage(pageInput.value); });
      pageInput.addEventListener('keydown', function (event) {
        if (event.key !== 'Enter') return;
        event.preventDefault();
        requestPage(pageInput.value);
      });
    }

    var pageSizeSelect = host.querySelector('.qym-pagination__size');
    if (pageSizeSelect) {
      pageSizeSelect.addEventListener('change', function () {
        if (typeof options.onPageSizeChange === 'function') {
          resetPaginationScroll(options);
          options.onPageSizeChange(Math.max(1, Number(pageSizeSelect.value) || pageSize));
        }
      });
    }
  }

  function alignMetricColumns(root, options) {
    if (!root || !root.querySelectorAll) return;
    options = options || {};
    var groupSelector = options.groupSelector || '[data-qym-metric-grid]';
    var cellSelector = options.cellSelector || '[data-qym-metric-column]';
    var columnAttribute = options.columnAttribute || 'data-qym-metric-column';
    var groups = Array.from(root.querySelectorAll(groupSelector));
    if (!groups.length) return;

    groups.forEach(function (group) {
      group.style.removeProperty('--qym-item-metric-columns');
    });

    var widths = [];
    groups.forEach(function (group) {
      group.querySelectorAll(cellSelector).forEach(function (cell) {
        var column = Number.parseInt(cell.getAttribute(columnAttribute), 10);
        if (!Number.isFinite(column) || column < 0) return;
        var measured = Math.ceil(cell.getBoundingClientRect().width);
        widths[column] = Math.max(widths[column] || 0, measured);
      });
    });
    if (!widths.length) return;

    var template = widths.map(function (width) {
      return Math.max(1, width || 0) + 'px';
    }).join(' ');
    groups.forEach(function (group) {
      group.style.setProperty('--qym-item-metric-columns', template);
    });
  }

  function setupScrollMirror(mirror) {
    if (!mirror || mirror.dataset.qymScrollMirrorReady === 'true') return;
    var targetId = mirror.getAttribute('data-qym-scroll-mirror-for');
    var target = targetId && document.getElementById(targetId);
    if (!target) return;
    target.classList.add('qym-scroll-mirror-target');
    var track = mirror.querySelector('.qym-scroll-mirror__track');
    var thumb = mirror.querySelector('.qym-scroll-mirror__thumb');
    if (!track || !thumb) return;

    mirror.dataset.qymScrollMirrorReady = 'true';
    var maxScroll = 0;
    var maxThumbTravel = 0;

    function updateThumb() {
      var ratio = maxScroll > 0 ? target.scrollLeft / maxScroll : 0;
      thumb.style.transform = 'translateX(' + Math.round(ratio * maxThumbTravel) + 'px)';
      mirror.setAttribute('aria-valuenow', String(Math.round(target.scrollLeft)));
    }

    function update() {
      var overflowWidth = target.scrollWidth;
      var targetRect = target.getBoundingClientRect();
      var isRendered = target.offsetParent !== null && targetRect.width > 0;
      mirror.hidden = !isRendered || overflowWidth <= target.clientWidth + 1;
      if (mirror.hidden) return;

      mirror.style.left = Math.round(targetRect.left) + 'px';
      mirror.style.width = Math.round(targetRect.width) + 'px';
      maxScroll = Math.max(0, overflowWidth - target.clientWidth);
      var trackWidth = track.clientWidth;
      var thumbWidth = Math.max(40, Math.round(trackWidth * target.clientWidth / overflowWidth));
      thumb.style.width = Math.min(trackWidth, thumbWidth) + 'px';
      maxThumbTravel = Math.max(0, trackWidth - Math.min(trackWidth, thumbWidth));
      mirror.setAttribute('aria-valuemax', String(Math.round(maxScroll)));
      updateThumb();
    }

    target.addEventListener('scroll', updateThumb, { passive: true });

    track.addEventListener('pointerdown', function (event) {
      if (event.target === thumb || maxThumbTravel <= 0) return;
      var rect = track.getBoundingClientRect();
      var thumbWidth = thumb.getBoundingClientRect().width;
      var next = (event.clientX - rect.left - thumbWidth / 2) / maxThumbTravel;
      target.scrollLeft = Math.max(0, Math.min(1, next)) * maxScroll;
    });

    var dragStartX = 0;
    var dragStartScroll = 0;
    thumb.addEventListener('pointerdown', function (event) {
      event.preventDefault();
      event.stopPropagation();
      dragStartX = event.clientX;
      dragStartScroll = target.scrollLeft;
      thumb.setPointerCapture(event.pointerId);
    });
    thumb.addEventListener('pointermove', function (event) {
      if (!thumb.hasPointerCapture(event.pointerId) || maxThumbTravel <= 0) return;
      target.scrollLeft = dragStartScroll + (event.clientX - dragStartX) * maxScroll / maxThumbTravel;
    });
    thumb.addEventListener('pointerup', function (event) {
      if (thumb.hasPointerCapture(event.pointerId)) thumb.releasePointerCapture(event.pointerId);
    });

    mirror.addEventListener('wheel', function (event) {
      event.preventDefault();
      var delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
      target.scrollLeft += delta;
    }, { passive: false });

    mirror.addEventListener('keydown', function (event) {
      var step = Math.max(40, Math.round(target.clientWidth * 0.2));
      if (event.key === 'Home') target.scrollLeft = 0;
      else if (event.key === 'End') target.scrollLeft = maxScroll;
      else if (event.key === 'ArrowLeft') target.scrollLeft -= step;
      else if (event.key === 'ArrowRight') target.scrollLeft += step;
      else return;
      event.preventDefault();
    });

    if (window.ResizeObserver) {
      var resizeObserver = new ResizeObserver(update);
      resizeObserver.observe(target);
      if (target.firstElementChild) resizeObserver.observe(target.firstElementChild);
    }
    if (window.MutationObserver) {
      new MutationObserver(update).observe(target, { childList: true, subtree: true });
    }
    window.addEventListener('resize', update);
    window.requestAnimationFrame(update);
  }

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

  function directSegmentOptions(segmented) {
    return Array.from(segmented.querySelectorAll('.qym-segmented__option')).filter(function (option) {
      return option.closest('.qym-segmented') === segmented;
    });
  }

  function segmentedHistoryKey(segmented) {
    var explicitKey = segmented.getAttribute('data-qym-segmented-key');
    if (explicitKey) return explicitKey;
    if (segmented.id) return 'id:' + segmented.id;
    return '';
  }

  function scheduleSegmentedSync(segmented, frames) {
    if (!segmented || !segmented.matches || !segmented.matches('.qym-segmented')) return;
    if (segmentSyncFrames.has(segmented)) return;
    var remainingFrames = Math.max(1, Number(frames) || 1);
    var schedule = window.requestAnimationFrame || function (callback) {
      return window.setTimeout(callback, 0);
    };
    var run = function () {
      if (remainingFrames > 1) {
        remainingFrames -= 1;
        // Commit the restored position before changing it to the new active
        // option so replacement renders retain the indicator's motion.
        void segmented.offsetWidth;
        segmentSyncFrames.set(segmented, schedule(run));
        return;
      }
      segmentSyncFrames.delete(segmented);
      syncSegmented(segmented);
    };
    segmentSyncFrames.set(segmented, schedule(run));
  }

  function syncSegmented(segmented) {
    if (!segmented || !segmented.matches('.qym-segmented')) return;
    var options = directSegmentOptions(segmented);
    var active = options.find(function (option) {
      return option.classList.contains('active')
        || option.getAttribute('aria-selected') === 'true'
        || option.getAttribute('aria-pressed') === 'true';
    });
    if (!active || active.offsetWidth <= 0) {
      segmented.classList.remove('qym-segmented--ready');
      return;
    }
    var nextX = active.offsetLeft + 'px';
    var nextWidth = active.offsetWidth + 'px';
    if (segmented.style.getPropertyValue('--qym-segment-x') !== nextX) {
      segmented.style.setProperty('--qym-segment-x', nextX);
    }
    if (segmented.style.getPropertyValue('--qym-segment-width') !== nextWidth) {
      segmented.style.setProperty('--qym-segment-width', nextWidth);
    }
    segmented.classList.add('qym-segmented--ready');
    var historyKey = segmentedHistoryKey(segmented);
    if (historyKey) {
      segmentPositions.set(historyKey, { x: nextX, width: nextWidth });
    }
  }

  function observeSegmented(segmented) {
    if (!window.ResizeObserver) return;
    var observer = segmentResizeObservers.get(segmented);
    if (!observer) {
      observer = new ResizeObserver(function (entries) {
        entries.forEach(function (entry) {
          var target = entry.target.closest && entry.target.closest('.qym-segmented');
          scheduleSegmentedSync(target || segmented);
        });
      });
      segmentResizeObservers.set(segmented, observer);
      observer.observe(segmented);
    }
    directSegmentOptions(segmented).forEach(function (option) {
      observer.observe(option);
    });
  }

  function cleanupSegmented(root) {
    if (!root || !root.querySelectorAll) return;
    var segments = [];
    if (root.matches && root.matches('.qym-segmented')) segments.push(root);
    root.querySelectorAll('.qym-segmented').forEach(function (segmented) {
      segments.push(segmented);
    });
    segments.forEach(function (segmented) {
      var observer = segmentResizeObservers.get(segmented);
      if (!observer) return;
      observer.disconnect();
      segmentResizeObservers.delete(segmented);
    });
  }

  function setupSegmented(segmented) {
    if (!segmented || !segmented.matches || !segmented.matches('.qym-segmented')) return;
    var isNew = segmented.dataset.qymSegmentedReady !== 'true';
    segmented.dataset.qymSegmentedReady = 'true';
    var historyKey = segmentedHistoryKey(segmented);
    var previous = isNew && historyKey ? segmentPositions.get(historyKey) : null;
    if (previous) {
      segmented.style.setProperty('--qym-segment-x', previous.x);
      segmented.style.setProperty('--qym-segment-width', previous.width);
      segmented.classList.add('qym-segmented--ready');
      scheduleSegmentedSync(segmented, 2);
    } else {
      syncSegmented(segmented);
    }
    observeSegmented(segmented);
  }

  function closeStructuredDropdown(dropdown, restoreFocus) {
    if (!dropdown) return;
    dropdown.classList.remove('is-open');
    var trigger = dropdown.querySelector('.qym-dropdown__trigger');
    if (trigger) {
      trigger.setAttribute('aria-expanded', 'false');
      if (restoreFocus) trigger.focus({ preventScroll: true });
    }
  }

  function closeOtherStructuredDropdowns(active) {
    document.querySelectorAll('.qym-dropdown.is-open').forEach(function (dropdown) {
      if (dropdown !== active) closeStructuredDropdown(dropdown, false);
    });
  }

  function toggleStructuredDropdown(dropdown) {
    if (!dropdown) return;
    var willOpen = !dropdown.classList.contains('is-open');
    closeOtherStructuredDropdowns(dropdown);
    dropdown.classList.toggle('is-open', willOpen);
    var trigger = dropdown.querySelector('.qym-dropdown__trigger');
    if (trigger) trigger.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
    if (willOpen) {
      var search = dropdown.querySelector('.qym-dropdown__search');
      if (search) window.requestAnimationFrame(function () { search.focus(); });
    }
  }

  function filterStructuredDropdown(search) {
    var dropdown = search && search.closest('.qym-dropdown');
    if (!dropdown) return;
    var query = search.value.trim().toLocaleLowerCase();
    dropdown.querySelectorAll('.qym-dropdown__option').forEach(function (option) {
      var text = (option.dataset.qymDropdownSearchText || option.textContent || '').toLocaleLowerCase();
      option.hidden = Boolean(query) && !text.includes(query);
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
    var isSingleSelect = wrapper.classList.contains('qym-review-select');
    button.setAttribute('aria-haspopup', isSingleSelect ? 'listbox' : 'dialog');
    button.setAttribute('aria-controls', dropdown.id);
    button.setAttribute('aria-expanded', dropdown.classList.contains('open') ? 'true' : 'false');
    dropdown.setAttribute('role', isSingleSelect ? 'listbox' : 'dialog');
    if (!dropdown.hasAttribute('aria-label')) {
      dropdown.setAttribute('aria-label', (button.textContent || 'Filter').trim() + ' options');
    }
  }

  function closeReviewSelector(wrapper, restoreFocus) {
    if (!wrapper) return;
    var dropdown = wrapper.querySelector('.multi-select-dropdown');
    var button = wrapper.querySelector('.multi-select-btn');
    if (dropdown) dropdown.classList.remove('open');
    if (button) {
      button.setAttribute('aria-expanded', 'false');
      if (restoreFocus) button.focus({ preventScroll: true });
    }
  }

  function closeOtherReviewSelectors(active) {
    document.querySelectorAll('.qym-review-selector').forEach(function (wrapper) {
      if (wrapper !== active) closeReviewSelector(wrapper, false);
    });
  }

  function syncEnhancedSelect(select) {
    if (!select || !select._qymReviewSelector) return;
    var wrapper = select._qymReviewSelector;
    var button = wrapper.querySelector('.multi-select-btn');
    var dropdown = wrapper.querySelector('.multi-select-dropdown');
    if (!button || !dropdown) return;
    var config = select._qymReviewSelectorConfig || {};
    var selectedOption = select.options[select.selectedIndex] || null;
    button.textContent = selectedOption ? selectedOption.textContent : (config.placeholder || 'Select an option');
    button.disabled = Boolean(select.disabled || !select.options.length);
    button.classList.toggle('has-selection', Boolean(config.highlightSelection && selectedOption));
    button.setAttribute('aria-label', (select.getAttribute('aria-label') || config.label || 'Select') + ': ' + button.textContent);

    dropdown.innerHTML = '';
    var searchable = config.search === true || (config.search !== false && select.options.length > 8);
    if (searchable) {
      var searchBox = document.createElement('div');
      searchBox.className = 'model-search-box qym-dropdown__search';
      var search = document.createElement('input');
      search.type = 'search';
      search.className = 'model-search-input qym-control qym-search';
      search.setAttribute('data-ms-search', '');
      search.setAttribute('aria-label', 'Search ' + (select.getAttribute('aria-label') || config.label || 'options'));
      search.placeholder = 'Search options';
      searchBox.appendChild(search);
      dropdown.appendChild(searchBox);
    }

    Array.prototype.forEach.call(select.options, function (nativeOption) {
      var option = document.createElement('button');
      option.type = 'button';
      option.className = 'multi-select-option qym-dropdown__option qym-review-select__option';
      option.dataset.value = nativeOption.value;
      option.dataset.qymDropdownSearchText = nativeOption.textContent || '';
      option.setAttribute('role', 'option');
      option.setAttribute('aria-selected', nativeOption === selectedOption ? 'true' : 'false');
      option.disabled = nativeOption.disabled;
      var label = document.createElement('span');
      label.className = 'qym-review-select__option-label';
      label.textContent = nativeOption.textContent;
      var check = document.createElement('span');
      check.className = 'qym-review-select__check';
      check.setAttribute('aria-hidden', 'true');
      check.textContent = '\u2713';
      option.appendChild(label);
      option.appendChild(check);
      option.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        if (nativeOption.disabled) return;
        var changed = select.value !== nativeOption.value;
        select.value = nativeOption.value;
        syncEnhancedSelect(select);
        closeReviewSelector(wrapper, true);
        if (changed) select.dispatchEvent(new Event('change', { bubbles: true }));
      });
      dropdown.appendChild(option);
    });
    ensureDropdownButton(button);
  }

  function enhanceSelect(select, options) {
    if (!select || select.tagName !== 'SELECT') return null;
    var config = options || {};
    select._qymReviewSelectorConfig = config;
    if (!select._qymReviewSelector) {
      var wrapper = document.createElement('div');
      wrapper.className = 'multi-select-wrapper qym-review-selector qym-review-select';
      if (config.className) wrapper.classList.add.apply(wrapper.classList, String(config.className).split(/\s+/).filter(Boolean));
      if (config.placement === 'top') wrapper.classList.add('qym-review-selector--dropup');
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'multi-select-btn';
      var dropdown = document.createElement('div');
      dropdown.className = 'multi-select-dropdown';
      dropdown.id = (select.id || ('qym-review-select-' + (++dropdownId))) + '-dropdown';
      wrapper.appendChild(button);
      wrapper.appendChild(dropdown);
      select.insertAdjacentElement('afterend', wrapper);
      select.hidden = true;
      select.tabIndex = -1;
      select.setAttribute('aria-hidden', 'true');
      select.dataset.qymReviewSelectReady = 'true';
      select._qymReviewSelector = wrapper;
      wrapper._qymNativeSelect = select;
      select.addEventListener('change', function () { syncEnhancedSelect(select); });
    }
    syncEnhancedSelect(select);
    return select._qymReviewSelector;
  }

  function enhanceSelects(root, selector, options) {
    var scope = root && root.querySelectorAll ? root : document;
    return Array.prototype.map.call(scope.querySelectorAll(selector || 'select[data-qym-review-select]'), function (select) {
      return enhanceSelect(select, typeof options === 'function' ? options(select) : options);
    });
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
    if (scope.matches && scope.matches('.qym-segmented')) {
      setupSegmented(scope);
    }
    scope.querySelectorAll('.qym-segmented').forEach(setupSegmented);
    if (scope.matches && scope.matches('.multi-select-btn, [aria-controls]')) {
      ensureDropdownButton(scope);
    }
    if (scope.matches && scope.matches('.multi-select-dropdown, .qym-dropdown')) {
      var wrapper = scope.closest('.multi-select-wrapper');
      ensureDropdownButton(wrapper && wrapper.querySelector('.multi-select-btn'));
    }
    scope.querySelectorAll('.multi-select-btn').forEach(ensureDropdownButton);
    if (scope.matches && scope.matches('[data-qym-scroll-mirror-for]')) {
      setupScrollMirror(scope);
    }
    scope.querySelectorAll('[data-qym-scroll-mirror-for]').forEach(setupScrollMirror);
  }

  document.addEventListener('click', function (event) {
    var trigger = event.target.closest('.qym-dropdown__trigger');
    if (trigger) {
      toggleStructuredDropdown(trigger.closest('.qym-dropdown'));
      return;
    }
    if (!event.target.closest('.qym-dropdown')) closeOtherStructuredDropdowns(null);
  });

  document.addEventListener('input', function (event) {
    if (event.target.matches('.qym-dropdown__search')) {
      filterStructuredDropdown(event.target);
    }
    if (event.target.matches('.qym-review-selector [data-ms-search]')) {
      var reviewSelector = event.target.closest('.qym-review-selector');
      var query = event.target.value.trim().toLocaleLowerCase();
      reviewSelector.querySelectorAll('.multi-select-option').forEach(function (option) {
        var text = (option.dataset.qymDropdownSearchText || option.textContent || '').toLocaleLowerCase();
        option.hidden = Boolean(query) && !text.includes(query);
      });
    }
  });

  document.addEventListener('click', function (event) {
    var trigger = event.target.closest('.qym-review-selector > .multi-select-btn');
    if (trigger) {
      event.preventDefault();
      event.stopPropagation();
      var wrapper = trigger.closest('.qym-review-selector');
      var dropdown = wrapper.querySelector('.multi-select-dropdown');
      var willOpen = dropdown && !dropdown.classList.contains('open');
      closeOtherReviewSelectors(wrapper);
      if (dropdown) dropdown.classList.toggle('open', willOpen);
      trigger.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
      if (willOpen) {
        var search = dropdown.querySelector('[data-ms-search]');
        if (search) window.requestAnimationFrame(function () { search.focus(); });
      }
      return;
    }
    if (!event.target.closest('.qym-review-selector')) closeOtherReviewSelectors(null);
  });

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

  document.addEventListener('click', function (event) {
    var option = event.target.closest('.qym-segmented__option');
    if (!option) return;
    var segmented = option.closest('.qym-segmented');
    window.setTimeout(function () { scheduleSegmentedSync(segmented); }, 0);
  });

  document.addEventListener('click', function () {
    window.setTimeout(function () {
      document.querySelectorAll('.multi-select-btn').forEach(ensureDropdownButton);
    }, 0);
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      var reviewSelector = event.target.closest('.qym-review-selector');
      if (reviewSelector && reviewSelector.querySelector('.multi-select-dropdown.open')) {
        event.preventDefault();
        event.stopPropagation();
        closeReviewSelector(reviewSelector, true);
        return;
      }
      var structuredDropdown = event.target.closest('.qym-dropdown.is-open') || document.querySelector('.qym-dropdown.is-open');
      if (structuredDropdown) {
        event.preventDefault();
        event.stopPropagation();
        closeStructuredDropdown(structuredDropdown, true);
        return;
      }

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

  function syncAllSegmented() {
    document.querySelectorAll('.qym-segmented').forEach(scheduleSegmentedSync);
  }

  window.addEventListener('resize', dismissHelpOnViewportChange);
  window.addEventListener('resize', syncAllSegmented);
  window.addEventListener('scroll', dismissHelpOnViewportChange, true);

  function start() {
    refresh(document);
    if (!window.MutationObserver) return;
    var observer = new MutationObserver(function (records) {
      records.forEach(function (record) {
        if (record.type === 'childList') {
          record.removedNodes.forEach(function (node) {
            if (node.nodeType === 1) cleanupSegmented(node);
          });
          record.addedNodes.forEach(function (node) {
            if (node.nodeType === 1) refresh(node);
          });
          syncTablist(record.target.closest && record.target.closest('.qym-tabs[role="tablist"]'));
          setupSegmented(record.target.closest && record.target.closest('.qym-segmented'));
        } else if (record.target.closest) {
          syncTablist(record.target.closest('.qym-tabs[role="tablist"]'));
          scheduleSegmentedSync(record.target.closest('.qym-segmented'));
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
      attributeFilter: ['aria-selected', 'aria-pressed', 'class'],
    });
  }

  window.QymUIComponents = {
    alignMetricColumns: alignMetricColumns,
    closeHelpMarkers: closeHelpMarkers,
    enhanceSelect: enhanceSelect,
    enhanceSelects: enhanceSelects,
    refresh: refresh,
    renderPagination: renderPagination,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true });
  } else {
    start();
  }
})();
