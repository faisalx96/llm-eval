# QymDataTable

`QymDataTable` is the shared dashboard table component for dense platform data grids. It standardizes the look and interaction model used by the datasets items table:

- single-line cells with ellipsis
- horizontal overflow through the parent container
- full-header click sorting
- resizable columns with persisted widths
- sticky headers
- compact platform typography and colors

The implementation lives in:

- `packages/platform/qym_platform/_static/dashboard/qym_table.js`
- shared CSS hooks in `packages/platform/qym_platform/_static/dashboard/dashboard.css`

Load it after `shell.js`:

```html
<script src="/static/qym_table.js"></script>
```

## Basic Usage

```js
QymDataTable.render({
  host: tableWrap,
  tableClass: 'my-page-table',
  storageKey: 'runs.main',
  minWidth: 1200,
  columns: [
    { id: 'run', label: 'Run', className: 'col-run', sortKey: 'run', width: 240, minWidth: 140 },
    { id: 'status', label: 'Status', className: 'col-status', sortKey: 'status', width: 100, minWidth: 80 },
    { id: 'actions', label: '', className: 'col-actions', width: 44, minWidth: 44, resizable: false },
  ],
  rows,
  sortState: sortKey => state.sort === sortKey + '_asc' ? 'ascending' : 'none',
  onSort: (_column, nextDir, sortKey) => {
    state.sort = sortKey + '_' + nextDir;
    reloadRows();
  },
  renderRow: row => {
    const tr = document.createElement('tr');
    tr.appendChild(cell(row.name, 'col-run'));
    tr.appendChild(cell(row.status, 'col-status'));
    tr.appendChild(actionsCell(row));
    return tr;
  },
});
```

## Column Contract

Each column supports:

- `id`: stable identifier used for persisted width storage.
- `label`: header text.
- `className`: class applied to the header cell. Body cells should use matching classes from `renderRow`.
- `sortKey`: optional key passed to `sortState` and `onSort`.
- `width`: default width in pixels.
- `minWidth`: minimum width while resizing.
- `resizable`: set to `false` for action/menu columns.

Use stable `id` values. Changing them resets saved widths.

## Sorting

The whole header cell is clickable when `sortKey` is provided. The resize handle stops event propagation, so dragging a column does not sort it.

Sortable headers are also keyboard reachable. Press `Enter` or `Space` on a focused sortable header to toggle direction.

`sortState(sortKey, column)` must return:

- `'ascending'`
- `'descending'`
- `'none'`

`onSort(column, nextDir, sortKey)` receives `nextDir` as `'asc'` or `'desc'`.

## Column Resizing

Widths are saved to local storage under:

```text
qym:data-table:widths:<storageKey>
```

Use a unique `storageKey` per table surface, for example:

- `datasets.items`
- `runs.index`
- `reviews.queue`

Dragging a resize handle must not change sorting. `QymDataTable` suppresses the click event emitted after a resize gesture, so pages should use the built-in resize handles instead of adding their own header drag listeners.

## Migration Checklist

1. Add `<script src="/static/qym_table.js"></script>` to the page.
2. Wrap the table in an overflow container.
3. Define columns with stable `id`, `width`, and `minWidth`.
4. Move sorting state into `sortState` and `onSort`.
5. Render rows through `renderRow`.
6. Keep body cells single-line unless the table is explicitly not a data grid.
7. Disable resizing for menu/action columns.

## Current Adoption

The datasets items table and dataset-version runs tab are the reference implementations. New or upgraded platform tables should use `QymDataTable` unless they require a specialized visualization rather than a data grid.
