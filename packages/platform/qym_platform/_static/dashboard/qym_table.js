(() => {
  'use strict';

  const STORAGE_PREFIX = 'qym:data-table:widths:';

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const key in attrs) {
        const value = attrs[key];
        if (key === 'className') node.className = value;
        else if (key === 'style' && typeof value === 'object') Object.assign(node.style, value);
        else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2).toLowerCase(), value);
        else if (key === 'html') node.innerHTML = value;
        else if (value !== undefined && value !== null && value !== false) node.setAttribute(key, value);
      }
    }
    if (children !== undefined && children !== null) {
      if (Array.isArray(children)) {
        children.forEach(child => {
          if (child == null) return;
          node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
        });
      } else if (typeof children === 'string') {
        node.appendChild(document.createTextNode(children));
      } else {
        node.appendChild(children);
      }
    }
    return node;
  }

  function loadWidths(storageKey) {
    if (!storageKey) return {};
    try {
      const raw = window.localStorage.getItem(STORAGE_PREFIX + storageKey);
      const parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch (_) {
      return {};
    }
  }

  function saveWidths(storageKey, widths) {
    if (!storageKey) return;
    try {
      window.localStorage.setItem(STORAGE_PREFIX + storageKey, JSON.stringify(widths || {}));
    } catch (_) {}
  }

  function columnWidth(widths, column) {
    const stored = Number((widths || {})[column.id]);
    const minWidth = Number(column.minWidth || column.min || 44);
    const fallback = Number(column.width || minWidth);
    return Number.isFinite(stored) && stored > 0 ? Math.max(minWidth, stored) : fallback;
  }

  function columnFlex(column) {
    const flex = Number(column.flex);
    return Number.isFinite(flex) && flex > 0 ? flex : 0;
  }

  function sortArrow(state) {
    if (state === 'ascending') return '↑';
    if (state === 'descending') return '↓';
    return '';
  }

  function render(options) {
    const host = options && options.host;
    if (!host) throw new Error('QymDataTable.render requires a host element');

    const columns = (options.columns || []).filter(Boolean);
    const rows = options.rows || [];
    const storageKey = options.storageKey || '';
    const widths = loadWidths(storageKey);
    let suppressSortClickUntil = 0;

    host.innerHTML = '';

    const table = el('table', { className: ['qdt-table', options.tableClass || ''].filter(Boolean).join(' ') });
    const colRefs = new Map();
    const effectiveWidths = new Map();
    const widthFor = column => columnWidth(widths, column);
    // Leftover host space is handed to flex columns explicitly (instead of
    // letting the browser silently redistribute it across every column), so
    // the rendered width of each column always matches what we track here.
    const applyTableWidth = () => {
      const bases = columns.map(widthFor);
      const content = bases.reduce((sum, w) => sum + w, 0);
      const target = Math.max(options.minWidth || 0, host.clientWidth || 0, content);
      const extra = Math.max(0, target - content);
      const shares = new Map();
      // Columns the user resized keep their exact width; the remaining flex
      // columns absorb the leftover proportionally to their flex weight. If
      // the user has sized every flex column, the table stops stretching.
      const recipients = columns.filter(column => columnFlex(column) && widths[column.id] == null);
      const totalFlex = recipients.reduce((sum, column) => sum + columnFlex(column), 0);
      if (extra > 0 && totalFlex > 0) {
        let assigned = 0;
        recipients.forEach((column, index) => {
          const share = index === recipients.length - 1
            ? extra - assigned
            : Math.floor(extra * columnFlex(column) / totalFlex);
          assigned += share;
          shares.set(column.id, share);
        });
      }
      let total = 0;
      columns.forEach((column, index) => {
        const width = bases[index] + (shares.get(column.id) || 0);
        effectiveWidths.set(column.id, width);
        const col = colRefs.get(column.id);
        if (col) col.style.width = width + 'px';
        total += width;
      });
      table.style.width = total + 'px';
      table.style.minWidth = total + 'px';
    };

    const colgroup = el('colgroup');
    columns.forEach(column => {
      const col = el('col');
      colgroup.appendChild(col);
      colRefs.set(column.id, col);
    });
    table.appendChild(colgroup);
    applyTableWidth();

    if (host.__qdtResizeObserver) host.__qdtResizeObserver.disconnect();
    if (typeof ResizeObserver === 'function') {
      const observer = new ResizeObserver(() => {
        if (!host.contains(table)) { observer.disconnect(); return; }
        applyTableWidth();
      });
      observer.observe(host);
      host.__qdtResizeObserver = observer;
    }

    function startResize(column, th, event) {
      event.preventDefault();
      event.stopPropagation();
      suppressSortClickUntil = Date.now() + 350;
      const col = colRefs.get(column.id);
      if (!col) return;
      const startX = event.clientX;
      // Start from the rendered width (base + flex share), not the stored
      // width — otherwise the column snaps the moment the drag begins.
      const startWidth = effectiveWidths.get(column.id) || widthFor(column);
      const prevCursor = document.body.style.cursor;
      const prevUserSelect = document.body.style.userSelect;
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      th.classList.add('resizing');

      function onMove(moveEvent) {
        const nextWidth = Math.max(Number(column.minWidth || column.min || 44), Math.round(startWidth + moveEvent.clientX - startX));
        widths[column.id] = nextWidth;
        applyTableWidth();
      }

      function onUp() {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        document.body.style.cursor = prevCursor;
        document.body.style.userSelect = prevUserSelect;
        th.classList.remove('resizing');
        suppressSortClickUntil = Date.now() + 350;
        saveWidths(storageKey, widths);
      }

      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    }

    const thead = el('thead');
    const headerRow = el('tr');
    columns.forEach(column => {
      const sortKey = column.sortKey || column.key;
      const th = el('th', { className: [column.className || column.cls || '', sortKey ? 'sortable' : ''].filter(Boolean).join(' ') });
      if (sortKey && options.onSort) {
        const current = options.sortState ? options.sortState(sortKey, column) : 'none';
        const nextDirection = current === 'ascending' ? 'desc' : 'asc';
        const triggerSort = () => options.onSort(column, nextDirection, sortKey);
        th.setAttribute('role', 'button');
        th.setAttribute('tabindex', '0');
        th.addEventListener('click', event => {
          if (Date.now() < suppressSortClickUntil || event.target.closest('.qdt-col-resize, .col-resize')) return;
          triggerSort();
        });
        th.addEventListener('keydown', event => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            triggerSort();
          }
        });
        th.appendChild(el('button', { className: 'sort-btn qdt-sort-btn', type: 'button', 'aria-sort': current, tabindex: '-1' }, [
          el('span', { title: column.label || null }, column.label || ''),
          el('span', { className: 'sort-arrow qdt-sort-arrow' }, sortArrow(current)),
        ]));
      } else {
        th.textContent = column.label || '';
        if (column.label) th.title = column.label;
      }
      if (column.resizable !== false) {
        const resizeHandle = el('span', {
          className: 'col-resize qdt-col-resize',
          title: 'Drag to resize column',
          onmousedown: event => startResize(column, th, event),
        });
        resizeHandle.addEventListener('click', event => {
          event.preventDefault();
          event.stopPropagation();
        });
        th.appendChild(resizeHandle);
      }
      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    const tbody = el('tbody');
    rows.forEach((row, index) => {
      const tr = options.renderRow
        ? options.renderRow(row, { columns, rowIndex: index })
        : el('tr', null, columns.map(column => el('td', { className: column.className || column.cls || '' }, row[column.id] == null ? '' : String(row[column.id]))));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    host.appendChild(table);

    if (options.scrollLeft != null) host.scrollLeft = options.scrollLeft;
    return { table, columns, widths };
  }

  window.QymDataTable = { render, loadWidths, saveWidths };
})();
