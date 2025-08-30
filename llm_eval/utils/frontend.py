"""Frontend utilities for HTML generation and lightweight HTTP serving.

This module separates presentation and server responsibilities away from the
core evaluator logic. It provides:
- generate_html_table: render a live results HTML page
- cleanup_old_html_files: prune previous result folders
- start_http_server: serve a directory over HTTP on a random local port
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple
from datetime import datetime, timedelta
import html as html_lib
import json
import http.server
import shutil
import socketserver
import threading


def _compute_summary(item_statuses: Dict[int, Dict], items: List[Any]) -> Dict[str, Any]:
    total_items = len(items)
    completed = sum(1 for s in item_statuses.values() if s['status'] == 'completed')
    in_progress = sum(1 for s in item_statuses.values() if s['status'] == 'in_progress')
    failed = sum(1 for s in item_statuses.values() if s['status'] == 'error')
    pending = total_items - completed - in_progress - failed
    success_rate = (completed / total_items * 100) if total_items > 0 else 0
    return {
        'total': total_items,
        'completed': completed,
        'in_progress': in_progress,
        'failed': failed,
        'pending': pending,
        'success_rate': success_rate,
    }


def _build_table_rows_html(item_statuses: Dict[int, Dict], items: List[Any], metric_names: Iterable[str]) -> List[str]:
    table_rows: List[str] = []
    for idx in range(len(items)):
        status = item_statuses[idx]

        row_class = ""
        status_icon = ""
        if status['status'] == 'completed':
            row_class = "completed"
            status_icon = "✓"
        elif status['status'] == 'error':
            row_class = "error"
            status_icon = "✗"
        elif status['status'] == 'in_progress':
            row_class = "in-progress"
            status_icon = "⟳"
        else:
            row_class = "pending"
            status_icon = "◯"

        metric_cells: List[str] = []
        for metric_name in metric_names:
            metric_value = status['metrics'][metric_name]
            metric_class = ""
            if metric_value == '[dim]pending[/dim]':
                if status['status'] == 'in_progress':
                    metric_value = 'running...'
                    metric_class = "metric-computing"
                else:
                    metric_value = 'pending'
                    metric_class = "metric-pending"
            elif metric_value == '[yellow]computing...[/yellow]':
                metric_value = 'computing...'
                metric_class = "metric-computing"
            elif metric_value == '[red]error[/red]' or metric_value == '[red]N/A[/red]':
                metric_value = 'error'
                metric_class = "metric-error"
            metric_cells.append(f'<td class="{metric_class}">{metric_value}</td>')

        time_value = status['time']
        time_class = ""
        if '[yellow]running...[/yellow]' in str(time_value):
            time_value = 'running...'
            time_class = "metric-computing"
        elif '[red]' in str(time_value):
            time_value = str(time_value).replace('[red]', '').replace('[/red]', '')
            time_class = "metric-error"
        elif time_value == '[dim]pending[/dim]':
            time_value = 'pending'
            time_class = "metric-pending"

        input_text = html_lib.escape(str(status['input']))

        output_text = str(status['output'])
        output_class = ""
        if output_text == '[dim]pending[/dim]':
            if status['status'] == 'in_progress':
                output_text = 'running...'
                output_class = "metric-computing"
            else:
                output_text = 'pending'
                output_class = "metric-pending"
        elif '[red]' in output_text:
            output_text = output_text.replace('[red]', '').replace('[/red]', '')
            output_class = "metric-error"
        elif '[yellow]' in output_text:
            output_text = output_text.replace('[yellow]', '').replace('[/yellow]', '')
            output_class = "metric-computing"
        output_text = html_lib.escape(output_text)

        expected_text = html_lib.escape(str(status['expected']))

        row_html = f'''
            <tr class="{row_class}">
                <td class="status-cell"><span class="status-icon">{status_icon}</span></td>
                <td class="index-cell">{idx + 1}</td>
                <td class="content-cell" title="{html_lib.escape(str(status['input']))}">{input_text}</td>
                <td class="content-cell {output_class}" title="{html_lib.escape(str(status['output']))}">{output_text}</td>
                <td class="content-cell" title="{html_lib.escape(str(status['expected']))}">{expected_text}</td>
                {"".join(metric_cells)}
                <td class="time-cell {time_class}">{time_value}</td>
            </tr>
        '''
        table_rows.append(row_html)
    return table_rows


def _compute_metrics_accuracy(item_statuses: Dict[int, Dict], items: List[Any], metric_names: Iterable[str]) -> Dict[str, float]:
    total_items = len(items)
    metrics_acc: Dict[str, float] = {}
    for metric_name in metric_names:
        boolean_correct = 0
        boolean_total = 0
        numeric_values: List[float] = []
        for idx in range(total_items):
            s = item_statuses[idx]
            if s.get('status') != 'completed':
                continue
            v = s['metrics'].get(metric_name)
            if v in (None, '[dim]pending[/dim]', '[yellow]computing...[/yellow]', '[red]error[/red]', '[red]N/A[/red]'):
                continue
            if v == '✓':
                boolean_correct += 1
                boolean_total += 1
            elif v == '✗':
                boolean_total += 1
            else:
                try:
                    cleaned = str(v).replace('%', '').strip()
                    numeric_values.append(float(cleaned))
                except Exception:
                    pass
        # Coverage-weighted accuracy so the ring doesn't jump to 100% after one success
        pct = 0.0
        if total_items > 0:
            if boolean_total > 0 and len(numeric_values) == 0:
                completed_acc = boolean_correct / max(1, boolean_total)
                coverage = boolean_total / total_items
                pct = completed_acc * coverage * 100.0
            elif len(numeric_values) > 0:
                avg = sum(numeric_values) / len(numeric_values)
                # Interpret 0..1 as ratio; >1 as percent
                avg_ratio = avg if 0.0 <= avg <= 1.0 else (avg / 100.0)
                coverage = (len(numeric_values)) / total_items
                pct = avg_ratio * coverage * 100.0
        pct = max(0.0, min(100.0, pct))
        metrics_acc[metric_name] = pct
    return metrics_acc


def _build_metric_cards_html(metrics_acc: Dict[str, float]) -> List[str]:
    metric_cards: List[str] = []
    for metric_name, acc_total_pct in metrics_acc.items():
        hue = int(140 * (acc_total_pct / 100.0))
        ring_color = f"hsl({hue}, 85%, 55%)"
        metric_cards.append(
            f'''\
            <div class="metric-card" data-metric="{html_lib.escape(str(metric_name))}" style="--acc-total: {acc_total_pct:.2f}%; --ring-color: {ring_color};">
                <div class="metric-header-row minimal">
                    <div class="metric-title">{metric_name} Accuracy</div>
                </div>
                <div class="metric-donut">
                    <div class="metric-donut-inner"></div>
                    <div class="metric-donut-label"><span class="big">{acc_total_pct:.0f}%</span></div>
                </div>
            </div>
            '''
        )
    return metric_cards


def build_json_payload(item_statuses: Dict[int, Dict], items: List[Any], metric_names: Iterable[str]) -> str:
    """Serialize a compact JSON snapshot consumed by the frontend."""
    from datetime import datetime as dt
    summary = _compute_summary(item_statuses, items)
    metrics_acc = _compute_metrics_accuracy(item_statuses, items, metric_names)
    rows: List[Dict[str, Any]] = []
    for idx in range(len(items)):
        s = item_statuses[idx]
        status_icon = '◯'
        if s['status'] == 'completed':
            status_icon = '✓'
        elif s['status'] == 'error':
            status_icon = '✗'
        elif s['status'] == 'in_progress':
            status_icon = '⟳'

        time_val = str(s['time'])
        time_class = ''
        if '[yellow]' in time_val:
            time_class = 'metric-computing'
        elif '[red]' in time_val:
            time_class = 'metric-error'

        output_val = str(s['output'])
        output_class = ''
        if '[red]' in output_val:
            output_class = 'metric-error'
        elif '[yellow]' in output_val or s['status'] == 'in_progress':
            output_class = 'metric-computing'
        # Normalize output similar to HTML
        if output_val == '[dim]pending[/dim]':
            output_val = 'running...' if s['status'] == 'in_progress' else 'pending'
        else:
            output_val = (
                output_val
                .replace('[red]', '').replace('[/red]', '')
                .replace('[yellow]', '').replace('[/yellow]', '')
                .replace('[dim]', '').replace('[/dim]', '')
            )

        # Normalize metric values similar to HTML rendering
        normalized_metric_values: List[str] = []
        for m in metric_names:
            mv = str(s['metrics'][m])
            if mv == '[dim]pending[/dim]':
                mv = 'running...' if s['status'] == 'in_progress' else 'pending'
            elif mv == '[yellow]computing...[/yellow]':
                mv = 'computing...'
            elif mv == '[red]error[/red]':
                mv = 'error'
            elif mv == '[red]N/A[/red]':
                mv = 'N/A'
            normalized_metric_values.append(mv)
        rows.append({
            'status': s['status'],
            'status_icon': status_icon,
            'input': html_lib.escape(str(s['input'])),
            'input_full': html_lib.escape(str(s['input'])),
            'output': html_lib.escape(output_val),
            'output_full': html_lib.escape(str(s['output'])),
            'output_class': output_class,
            'expected': html_lib.escape(str(s['expected'])),
            'expected_full': html_lib.escape(str(s['expected'])),
            'metric_values': normalized_metric_values,
            'time': time_val.replace('[red]', '').replace('[/red]', '').replace('[yellow]', '').replace('[/yellow]', '').replace('[dim]', '').replace('[/dim]', ''),
            'time_class': time_class,
        })

    payload = {
        'stats': summary,
        'metrics_accuracy': metrics_acc,
        'rows': rows,
        'last_updated': dt.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    try:
        return json.dumps(payload, ensure_ascii=False)
    except Exception:
        return '{"rows":[]}'

def generate_html_table(
    item_statuses: Dict[int, Dict],
    items: List[Any],
    dataset_name: str,
    run_name: str,
    metric_names: Iterable[str],
) -> str:
    """Generate a modern HTML page for live evaluation results."""
    summary = _compute_summary(item_statuses, items)
    table_rows = _build_table_rows_html(item_statuses, items, metric_names)
    metrics_acc = _compute_metrics_accuracy(item_statuses, items, metric_names)
    metric_cards = _build_metric_cards_html(metrics_acc)

    # Headers
    metric_headers = "".join([f'<th>{name}</th>' for name in metric_names])

    # Build script separately to avoid escaping braces in f-string
    script_block = '''
    <script>
    (function() {
        const overlay = document.getElementById('modal-overlay');
        const closeBtn = document.getElementById('modal-close');
        
        const mInput = document.getElementById('m-input');
        const mOutput = document.getElementById('m-output');
        const mExpected = document.getElementById('m-expected');
        const mTime = document.getElementById('m-time');
        const mMetrics = document.getElementById('m-metrics');
        const mTitle = document.getElementById('modal-title');

        function openModal(data) {
            mTitle.textContent = 'Row ' + (data.index + 1);
            
            mInput.textContent = data.input || '';
            mOutput.textContent = data.output || '';
            mExpected.textContent = data.expected || '';
            mTime.textContent = data.time || '';
            mMetrics.innerHTML = '';
            const metrics = data.metrics || {};
            Object.keys(metrics).forEach((k) => {
                const div = document.createElement('div');
                div.className = 'modal-metric';
                const name = document.createElement('div');
                name.className = 'name';
                name.textContent = k;
                const value = document.createElement('div');
                value.className = 'value';
                value.textContent = metrics[k];
                div.appendChild(name);
                div.appendChild(value);
                mMetrics.appendChild(div);
            });

            overlay.style.display = 'flex';
            overlay.setAttribute('aria-hidden', 'false');
        }

        function closeModal() {
            overlay.style.display = 'none';
            overlay.setAttribute('aria-hidden', 'true');
        }

        closeBtn.addEventListener('click', closeModal);
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) closeModal();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeModal();
        });

        function extractRowData(tr) {
            const tds = Array.from(tr.querySelectorAll('td'));
            // Assuming table structure: [status, index, input, output, expected, ...metrics..., time]
            const idxCell = tds[1];
            const index = idxCell ? (parseInt((idxCell.textContent || '').trim() || '0', 10) - 1) : 0;
            const inputCell = tds[2];
            const outputCell = tds[3];
            const expectedCell = tds[4];
            const timeCell = tds[tds.length - 1];
            const input = inputCell ? (inputCell.getAttribute('title') || inputCell.textContent || '') : '';
            const output = outputCell ? (outputCell.getAttribute('title') || outputCell.textContent || '') : '';
            const expected = expectedCell ? (expectedCell.getAttribute('title') || expectedCell.textContent || '') : '';
            const time = timeCell ? (timeCell.textContent || '') : '';
            const metrics = {};
            for (let i = 5; i < tds.length - 1; i++) {
                const header = document.querySelector('thead th:nth-child(' + (i + 1) + ')');
                const name = header ? header.textContent.trim() : ('metric_' + (i - 4));
                const cell = tds[i];
                metrics[name] = cell ? (cell.textContent || '') : '';
            }
            return { index, input, output, expected, time, metrics };
        }

        function bindRowClicks() {
            document.querySelectorAll('tbody tr').forEach((tr) => {
                tr.querySelectorAll('.content-cell').forEach((cell) => {
                    cell.addEventListener('click', () => {
                        const data = extractRowData(tr);
                        openModal(data);
                    });
                });
            });
        }

        bindRowClicks();

        const REFRESH_INTERVAL_MS = 2000;
        const liveIndicator = document.getElementById('live-indicator');
        const liveText = document.getElementById('live-text');

        function refreshFromHTML() {
            const u = new URL(window.location.href);
            u.hash = '';
            u.searchParams.set('t', Date.now().toString());
            return fetch(u.toString(), { cache: 'no-store', headers: { 'Cache-Control': 'no-cache' } })
                .then((r) => r.text())
                .then((html) => {
                    const parser = new DOMParser();
                    const doc = parser.parseFromString(html, 'text/html');
                    const newStats = doc.querySelector('.stats-grid');
                    const newMetrics = doc.querySelector('.metrics-grid');
                    const newTbody = doc.querySelector('tbody');
                    const newUpdated = doc.querySelector('.last-updated');
                    if (newStats && document.querySelector('.stats-grid')) {
                        document.querySelector('.stats-grid').innerHTML = newStats.innerHTML;
                    }
                    if (newMetrics && document.querySelector('.metrics-grid')) {
                        document.querySelector('.metrics-grid').innerHTML = newMetrics.innerHTML;
                    }
                    const modalOpen = overlay && overlay.style.display === 'flex';
                    if (!modalOpen && newTbody && document.querySelector('tbody')) {
                        document.querySelector('tbody').innerHTML = newTbody.innerHTML;
                    }
                    if (newUpdated && document.querySelector('.last-updated')) {
                        document.querySelector('.last-updated').innerHTML = newUpdated.innerHTML;
                    }
                    bindRowClicks();
                });
        }

        function refreshPartial() {
            try {
                // Prefer JSON endpoint for reliable updates
                const dataUrl = new URL('data.json', window.location.href);
                dataUrl.searchParams.set('t', Date.now().toString());
                if (liveText) liveText.textContent = 'Refreshing…';
                fetch(dataUrl.toString(), { cache: 'no-store', headers: { 'Cache-Control': 'no-cache' } })
                .then((r) => {
                    if (!r.ok) throw new Error('HTTP ' + r.status);
                    return r.json();
                })
                .then((data) => {
                    if (liveIndicator) {
                        liveIndicator.classList.remove('error');
                        liveText && (liveText.textContent = 'Live');
                    }
                    // Update stats
                    const s = data.stats || {};
                    const statsEls = document.querySelectorAll('.stats-grid .stat-card .value');
                    if (statsEls && statsEls.length >= 5) {
                        statsEls[0].textContent = String(s.completed ?? '');
                        statsEls[1].textContent = String(s.in_progress ?? '');
                        statsEls[2].textContent = String(s.failed ?? '');
                        statsEls[3].textContent = String(s.pending ?? '');
                        statsEls[4].textContent = ((s.success_rate ?? 0).toFixed(1)) + '%';
                    }

                    // Update metric rings
                    const metricsAcc = data.metrics_accuracy || {};
                    Object.keys(metricsAcc).forEach((name) => {
                        const card = document.querySelector('.metric-card[data-metric="' + name + '"]');
                        if (card) {
                            const pct = Math.max(0, Math.min(100, Number(metricsAcc[name]) || 0));
                            const hue = Math.floor(140 * (pct / 100));
                            card.style.setProperty('--acc-total', pct + '%');
                            card.style.setProperty('--ring-color', 'hsl(' + hue + ', 85%, 55%)');
                            const label = card.querySelector('.metric-donut-label .big');
                            if (label) label.textContent = String(Math.round(pct)) + '%';
                        }
                    });

                    // Update last updated
                    const updatedEl = document.querySelector('.last-updated');
                    if (updatedEl && data.last_updated) {
                        updatedEl.textContent = 'Last updated: ' + data.last_updated;
                    }

                    // Update table if modal closed
                    const modalOpen = overlay && overlay.style.display === 'flex';
                    if (!modalOpen && Array.isArray(data.rows)) {
                        const tbody = document.querySelector('tbody');
                        if (tbody) {
                            tbody.innerHTML = data.rows.map((row, idx) => {
                                const metricCells = (row.metric_values || []).map(v => {
                                    const text = String(v ?? '').trim().toLowerCase();
                                    let cls = '';
                                    if (text === 'running...' || text === 'computing...') {
                                        cls = 'metric-computing';
                                    } else if (text === 'pending') {
                                        cls = 'metric-pending';
                                    } else if (text === 'error' || text === 'n/a') {
                                        cls = 'metric-error';
                                    }
                                    return '<td class="' + cls + '">' + (v ?? '') + '</td>';
                                }).join('');
                                return (
                                    '<tr class="' + ((row.status === 'in_progress') ? 'in-progress' : (row.status || '')) + '">' +
                                    '<td class="status-cell"><span class="status-icon">' + (row.status_icon || '') + '</span></td>' +
                                    '<td class="index-cell">' + (idx + 1) + '</td>' +
                                    '<td class="content-cell" title="' + (row.input_full || '') + '">' + (row.input || '') + '</td>' +
                                    '<td class="content-cell ' + (row.output_class || '') + '" title="' + (row.output_full || '') + '">' + (row.output || '') + '</td>' +
                                    '<td class="content-cell" title="' + (row.expected_full || '') + '">' + (row.expected || '') + '</td>' +
                                    metricCells +
                                    '<td class="time-cell ' + (row.time_class || '') + '">' + (row.time || '') + '</td>' +
                                    '</tr>'
                                );
                            }).join('');
                            bindRowClicks();
                        }
                    }
                    bindRowClicks();
                })
                .catch(() => {
                    // Fallback to HTML fetch if JSON unavailable
                    return refreshFromHTML()
                        .then(() => {
                            if (liveIndicator) {
                                liveIndicator.classList.remove('error');
                                liveText && (liveText.textContent = 'Live');
                            }
                        })
                        .catch(() => {
                            if (liveIndicator) {
                                liveIndicator.classList.add('error');
                                liveText && (liveText.textContent = 'Refresh failed');
                            }
                        });
                });
            } catch (e) {
                // swallow errors to keep UI responsive
            }
        }

        // Kick off immediate refresh and then at interval
        refreshPartial();
        // Use document visibility to avoid unnecessary work in background tabs
        let refreshTimer = setInterval(refreshPartial, REFRESH_INTERVAL_MS);
        document.addEventListener('visibilitychange', function() {
            if (document.hidden) {
                clearInterval(refreshTimer);
            } else {
                refreshPartial();
                refreshTimer = setInterval(refreshPartial, REFRESH_INTERVAL_MS);
            }
        });
    })();
    </script>
    '''

    # Build script separately to avoid f-string brace parsing
    script_block = '''
    <script>
    (function() {
        const overlay = document.getElementById('modal-overlay');
        const closeBtn = document.getElementById('modal-close');
        
        const mInput = document.getElementById('m-input');
        const mOutput = document.getElementById('m-output');
        const mExpected = document.getElementById('m-expected');
        const mTime = document.getElementById('m-time');
        const mMetrics = document.getElementById('m-metrics');
        const mTitle = document.getElementById('modal-title');

        function openModal(data) {
            mTitle.textContent = 'Row ' + (data.index + 1);
            
            mInput.textContent = data.input || '';
            mOutput.textContent = data.output || '';
            mExpected.textContent = data.expected || '';
            mTime.textContent = data.time || '';
            mMetrics.innerHTML = '';
            const metrics = data.metrics || {};
            Object.keys(metrics).forEach((k) => {
                const div = document.createElement('div');
                div.className = 'modal-metric';
                const name = document.createElement('div');
                name.className = 'name';
                name.textContent = k;
                const value = document.createElement('div');
                value.className = 'value';
                value.textContent = metrics[k];
                div.appendChild(name);
                div.appendChild(value);
                mMetrics.appendChild(div);
            });

            overlay.style.display = 'flex';
            overlay.setAttribute('aria-hidden', 'false');
        }

        function closeModal() {
            overlay.style.display = 'none';
            overlay.setAttribute('aria-hidden', 'true');
        }

        closeBtn.addEventListener('click', closeModal);
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) closeModal();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeModal();
        });

        function extractRowData(tr) {
            const tds = Array.from(tr.querySelectorAll('td'));
            // Assuming table structure: [status, index, input, output, expected, ...metrics..., time]
            const idxCell = tds[1];
            const index = idxCell ? (parseInt((idxCell.textContent || '').trim() || '0', 10) - 1) : 0;
            const inputCell = tds[2];
            const outputCell = tds[3];
            const expectedCell = tds[4];
            const timeCell = tds[tds.length - 1];
            const input = inputCell ? (inputCell.getAttribute('title') || inputCell.textContent || '') : '';
            const output = outputCell ? (outputCell.getAttribute('title') || outputCell.textContent || '') : '';
            const expected = expectedCell ? (expectedCell.getAttribute('title') || expectedCell.textContent || '') : '';
            const time = timeCell ? (timeCell.textContent || '') : '';
            const metrics = {};
            for (let i = 5; i < tds.length - 1; i++) {
                const header = document.querySelector('thead th:nth-child(' + (i + 1) + ')');
                const name = header ? header.textContent.trim() : ('metric_' + (i - 4));
                const cell = tds[i];
                metrics[name] = cell ? (cell.textContent || '') : '';
            }
            return { index, input, output, expected, time, metrics };
        }

        function bindRowClicks() {
            document.querySelectorAll('tbody tr').forEach((tr) => {
                tr.querySelectorAll('.content-cell').forEach((cell) => {
                    cell.addEventListener('click', () => {
                        const data = extractRowData(tr);
                        openModal(data);
                    });
                });
            });
        }

        bindRowClicks();

        function styleComputingCells() {
            try {
                document.querySelectorAll('tbody td').forEach((td) => {
                    const text = (td.textContent || '').trim().toLowerCase();
                    if (text === 'running...' || text === 'computing...') {
                        td.classList.add('metric-computing');
                        td.classList.remove('metric-pending');
                    }
                });
            } catch (_) {}
        }

        const REFRESH_INTERVAL_MS = 2000;
        const liveIndicator = document.getElementById('live-indicator');
        const liveText = document.getElementById('live-text');

        function refreshFromHTML() {
            const u = new URL(window.location.href);
            u.hash = '';
            u.searchParams.set('t', Date.now().toString());
            return fetch(u.toString(), { cache: 'no-store', headers: { 'Cache-Control': 'no-cache' } })
                .then((r) => r.text())
                .then((html) => {
                    const parser = new DOMParser();
                    const doc = parser.parseFromString(html, 'text/html');
                    const newStats = doc.querySelector('.stats-grid');
                    const newMetrics = doc.querySelector('.metrics-grid');
                    const newTbody = doc.querySelector('tbody');
                    const newUpdated = doc.querySelector('.last-updated');
                    if (newStats && document.querySelector('.stats-grid')) {
                        document.querySelector('.stats-grid').innerHTML = newStats.innerHTML;
                    }
                    if (newMetrics && document.querySelector('.metrics-grid')) {
                        document.querySelector('.metrics-grid').innerHTML = newMetrics.innerHTML;
                    }
                    const modalOpen = overlay && overlay.style.display === 'flex';
                    if (!modalOpen && newTbody && document.querySelector('tbody')) {
                        document.querySelector('tbody').innerHTML = newTbody.innerHTML;
                        styleComputingCells();
                    }
                    if (newUpdated && document.querySelector('.last-updated')) {
                        document.querySelector('.last-updated').innerHTML = newUpdated.innerHTML;
                    }
                    bindRowClicks();
                });
        }

        function refreshPartial() {
            try {
                // Prefer JSON endpoint for reliable updates
                const dataUrl = new URL('data.json', window.location.href);
                dataUrl.searchParams.set('t', Date.now().toString());
                if (liveText) liveText.textContent = 'Refreshing…';
                fetch(dataUrl.toString(), { cache: 'no-store', headers: { 'Cache-Control': 'no-cache' } })
                .then((r) => {
                    if (!r.ok) throw new Error('HTTP ' + r.status);
                    return r.json();
                })
                .then((data) => {
                    if (liveIndicator) {
                        liveIndicator.classList.remove('error');
                        liveText && (liveText.textContent = 'Live');
                    }
                    // Update stats
                    const s = data.stats || {};
                    const statsEls = document.querySelectorAll('.stats-grid .stat-card .value');
                    if (statsEls && statsEls.length >= 5) {
                        statsEls[0].textContent = String(s.completed ?? '');
                        statsEls[1].textContent = String(s.in_progress ?? '');
                        statsEls[2].textContent = String(s.failed ?? '');
                        statsEls[3].textContent = String(s.pending ?? '');
                        statsEls[4].textContent = ((s.success_rate ?? 0).toFixed(1)) + '%';
                    }

                    // Update metric rings
                    const metricsAcc = data.metrics_accuracy || {};
                    Object.keys(metricsAcc).forEach((name) => {
                        const card = document.querySelector('.metric-card[data-metric="' + name + '"]');
                        if (card) {
                            const pct = Math.max(0, Math.min(100, Number(metricsAcc[name]) || 0));
                            const hue = Math.floor(140 * (pct / 100));
                            card.style.setProperty('--acc-total', pct + '%');
                            card.style.setProperty('--ring-color', 'hsl(' + hue + ', 85%, 55%)');
                            const label = card.querySelector('.metric-donut-label .big');
                            if (label) label.textContent = String(Math.round(pct)) + '%';
                        }
                    });

                    // Update last updated
                    const updatedEl = document.querySelector('.last-updated');
                    if (updatedEl && data.last_updated) {
                        updatedEl.textContent = 'Last updated: ' + data.last_updated;
                    }

                    // Update table if modal closed
                    const modalOpen = overlay && overlay.style.display === 'flex';
                    if (!modalOpen && Array.isArray(data.rows)) {
                        const tbody = document.querySelector('tbody');
                        if (tbody) {
                            tbody.innerHTML = data.rows.map((row, idx) => {
                                const metricCells = (row.metric_values || []).map(v => {
                                    const text = String(v ?? '').trim().toLowerCase();
                                    let cls = '';
                                    if (text === 'running...' || text === 'computing...') {
                                        cls = 'metric-computing';
                                    } else if (text === 'pending') {
                                        cls = 'metric-pending';
                                    } else if (text === 'error' || text === 'n/a') {
                                        cls = 'metric-error';
                                    }
                                    return '<td class="' + cls + '">' + (v ?? '') + '</td>';
                                }).join('');
                                return (
                                    '<tr class="' + ((row.status === 'in_progress') ? 'in-progress' : (row.status || '')) + '">' +
                                    '<td class="status-cell"><span class="status-icon">' + (row.status_icon || '') + '</span></td>' +
                                    '<td class="index-cell">' + (idx + 1) + '</td>' +
                                    '<td class="content-cell" title="' + (row.input_full || '') + '">' + (row.input || '') + '</td>' +
                                    '<td class="content-cell ' + (row.output_class || '') + '" title="' + (row.output_full || '') + '">' + (row.output || '') + '</td>' +
                                    '<td class="content-cell" title="' + (row.expected_full || '') + '">' + (row.expected || '') + '</td>' +
                                    metricCells +
                                    '<td class="time-cell ' + (row.time_class || '') + '">' + (row.time || '') + '</td>' +
                                    '</tr>'
                                );
                            }).join('');
                            bindRowClicks();
                            styleComputingCells();
                        }
                    }
                    bindRowClicks();
                })
                .catch(() => {
                    // Fallback to HTML fetch if JSON unavailable
                    return refreshFromHTML()
                        .then(() => {
                            if (liveIndicator) {
                                liveIndicator.classList.remove('error');
                                liveText && (liveText.textContent = 'Live');
                            }
                        })
                        .catch(() => {
                            if (liveIndicator) {
                                liveIndicator.classList.add('error');
                                liveText && (liveText.textContent = 'Refresh failed');
                            }
                        });
                });
            } catch (e) {
                // swallow errors to keep UI responsive
            }
        }

        // Kick off immediate refresh and then at interval
        refreshPartial();
        // Use document visibility to avoid unnecessary work in background tabs
        let refreshTimer = setInterval(refreshPartial, REFRESH_INTERVAL_MS);
        document.addEventListener('visibilitychange', function() {
            if (document.hidden) {
                clearInterval(refreshTimer);
            } else {
                refreshPartial();
                refreshTimer = setInterval(refreshPartial, REFRESH_INTERVAL_MS);
            }
        });
    })();
    </script>
    '''

    # HTML document
    html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    
    <title>LLM Evaluation Results - {dataset_name}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: #0a0a0a;
            color: #e0e0e0;
            line-height: 1.6;
            padding: 20px;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        
        .header {{
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            padding: 30px;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
            margin-bottom: 30px;
        }}
        
        .header h1 {{
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }}
        
        .header .subtitle {{
            font-size: 1.1rem;
            opacity: 0.9;
        }}
        
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        
        .stat-card {{
            background: #1a1a1a;
            border: 1px solid #333;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        
        .stat-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(0,0,0,0.3);
        }}
        
        .stat-card .value {{
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 5px;
        }}
        
        .stat-card .label {{
            font-size: 0.9rem;
            opacity: 0.7;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        
        .stat-card.completed .value {{ color: #4ade80; }}
        .stat-card.in-progress .value {{ color: #fbbf24; }}
        .stat-card.failed .value {{ color: #f87171; }}
        .stat-card.pending .value {{ color: #60a5fa; }}
        .stat-card.success-rate .value {{ color: #a78bfa; }}
        
        .table-wrapper {{
            background: #1a1a1a;
            border: 1px solid #333;
            border-radius: 10px;
            overflow: auto;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            table-layout: auto;
        }}
        
        th {{
            background: #2a2a2a;
            padding: 15px 10px;
            text-align: left;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.85rem;
            letter-spacing: 0.5px;
            border-bottom: 2px solid #444;
            position: sticky;
            top: 0;
            z-index: 10;
        }}
        
        td {{
            padding: 12px 10px;
            border-bottom: 1px solid #2a2a2a;
        }}
        
        tr:hover {{
            background: #252525;
        }}
        
        .status-cell {{
            text-align: center;
            width: 40px;
        }}
        
        .status-icon {{
            font-size: 1.2rem;
            font-weight: bold;
        }}
        
        .index-cell {{
            width: 60px;
            text-align: center;
            opacity: 0.6;
        }}
        
        .content-cell {{
            max-width: none;
            overflow: visible;
            white-space: normal;
            word-break: break-word;
            cursor: pointer;
        }}
        
        .time-cell {{
            width: 100px;
            text-align: right;
            font-family: inherit;
            font-size: 0.9rem;
        }}

        /* Modal styles */
        .modal-overlay {{
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.6);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 1000;
            backdrop-filter: blur(2px);
        }}
        .modal {{
            width: min(900px, 92vw);
            max-height: 80vh;
            background: #0f0f10;
            border: 1px solid #262626;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.5);
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }}
        .modal-header {{
            padding: 14px 16px;
            background: linear-gradient(180deg, #141417, #101012);
            border-bottom: 1px solid #202022;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .modal-title {{
            font-weight: 700;
        }}
        .modal-close {{
            background: transparent;
            border: none;
            color: #9ca3af;
            font-size: 1.2rem;
            cursor: pointer;
        }}
        .modal-content {{
            padding: 16px;
            overflow: auto;
            display: grid;
            grid-template-columns: 1fr;
            gap: 12px;
        }}
        .modal-row {{
            display: grid;
            grid-template-columns: 140px 1fr;
            gap: 12px;
        }}
        .modal-label {{
            opacity: 0.7;
            text-transform: uppercase;
            font-size: 0.75rem;
            letter-spacing: 0.6px;
        }}
        .modal-value {{
            background: #111113;
            border: 1px solid #1f1f22;
            border-radius: 8px;
            padding: 12px;
            white-space: pre-wrap;
            word-break: break-word;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
            font-size: 0.9rem;
        }}
        .modal-metrics {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 10px;
        }}
        .modal-metric {{
            background: #111113;
            border: 1px solid #1f1f22;
            border-radius: 8px;
            padding: 10px 12px;
        }}
        .modal-metric .name {{
            opacity: 0.75;
            font-size: 0.8rem;
            margin-bottom: 6px;
        }}
        .modal-metric .value {{
            font-weight: 700;
        }}
        
        tr.completed {{ background: rgba(74, 222, 128, 0.05); }}
        tr.completed .status-icon {{ color: #4ade80; }}
        
        tr.error {{ background: rgba(248, 113, 113, 0.05); }}
        tr.error .status-icon {{ color: #f87171; }}
        
        tr.in-progress {{ background: rgba(251, 191, 36, 0.1); }}
        tr.in-progress .status-icon {{ 
            color: #fbbf24;
            animation: spin 1s linear infinite;
        }}
        /* Only highlight specific columns when running, similar to Output */
        tr.in-progress td:nth-child(4),
        tr.in-progress td.time-cell {{
            color: #fbbf24;
            animation: pulse 1s ease-in-out infinite;
        }}
        tr.in-progress td.metric-error {{
            color: #f87171 !important;
            animation: none;
            text-shadow: none;
        }}
        
        tr.pending {{ opacity: 0.6; }}
        tr.pending .status-icon {{ color: #60a5fa; }}
        
        .metric-pending {{ opacity: 0.6; color: #9ca3af; }}
        .metric-computing {{ 
            color: #fbbf24;
            animation: pulse 1s ease-in-out infinite;
            font-weight: 600;
        }}
        .metric-error {{ color: #f87171; font-weight: 700; }}
        
        @keyframes spin {{
            from {{ transform: rotate(0deg); }}
            to {{ transform: rotate(360deg); }}
        }}
        
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.5; }}
        }}
        
        .last-updated {{
            text-align: center;
            margin-top: 20px;
            opacity: 0.6;
            font-size: 0.9rem;
        }}

        /* Live indicator */
        .live-indicator {{
            position: fixed;
            right: 16px;
            bottom: 16px;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: #111113;
            border: 1px solid #1f1f22;
            border-radius: 9999px;
            padding: 6px 10px;
            font-size: 0.78rem;
            opacity: 0.8;
            box-shadow: 0 10px 30px rgba(0,0,0,0.25);
        }}
        .live-dot {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #22c55e;
            box-shadow: 0 0 8px rgba(34,197,94,0.6);
        }}
        .live-indicator.error .live-dot {{
            background: #ef4444;
            box-shadow: 0 0 8px rgba(239,68,68,0.6);
        }}

        /* Metrics accuracy section */
        .metrics-accuracy {{
            margin-top: 20px;
            margin-bottom: 20px;
        }}
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 16px;
        }}
        .metric-card {{
            background: transparent;
            border: none;
            border-radius: 0;
            padding: 10px 8px 14px 8px;
            box-shadow: none;
            text-align: center;
        }}
        .metric-title {{
            font-weight: 600;
            margin-bottom: 8px;
        }}
        .metric-header-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 8px;
            margin-bottom: 6px;
        }}
        .metric-header-row.minimal {{
            justify-content: center;
        }}
        .metric-dot {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            display: inline-block;
            box-shadow: 0 0 0 3px rgba(34,197,94,0.12);
        }}
        .metric-donut {{
            width: 104px;
            height: 104px;
            position: relative;
            border-radius: 50%;
            background: conic-gradient(var(--ring-color) var(--acc-total), #232323 0);
            margin: 6px auto 8px auto;
            box-shadow: 0 0 0 6px rgba(0,0,0,0.25);
        }}
        .metric-donut-inner {{
            position: absolute;
            inset: 14px;
            background: radial-gradient(100% 100% at 50% 0%, #101010 0%, #0b0b0b 100%);
            border-radius: 50%;
            box-shadow: inset 0 0 0 1px #1a1a1a, 0 10px 30px rgba(0,0,0,0.25);
        }}
        .metric-donut-label {{
            position: absolute;
            inset: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            text-align: center;
            flex-direction: column;
            gap: 2px;
        }}
        .metric-donut-label .big {{
            font-size: 1.15rem;
            letter-spacing: 0.2px;
        }}
        .metric-donut-label .small {{
            font-size: 0.7rem;
            font-weight: 600;
            opacity: 0.7;
            text-transform: uppercase;
            letter-spacing: 0.6px;
        }}
        .metric-caption {{ display: none; }}
        
        @media (max-width: 768px) {{
            .stats-grid {{
                grid-template-columns: repeat(2, 1fr);
            }}
            
            .content-cell {{
                max-width: none;
            }}
            
            th, td {{
                padding: 8px 5px;
                font-size: 0.85rem;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔬 LLM Evaluation Results</h1>
            <div class="subtitle">
                Dataset: <strong>{dataset_name}</strong> | 
                Run: <strong>{run_name}</strong>
            </div>
        </div>
        
        <div class="stats-grid">
            <div class="stat-card completed">
                <div class="value">{summary['completed']}</div>
                <div class="label">Completed</div>
            </div>
            <div class="stat-card in-progress">
                <div class="value">{summary['in_progress']}</div>
                <div class="label">In Progress</div>
            </div>
            <div class="stat-card failed">
                <div class="value">{summary['failed']}</div>
                <div class="label">Failed</div>
            </div>
            <div class="stat-card pending">
                <div class="value">{summary['pending']}</div>
                <div class="label">Pending</div>
            </div>
            <div class="stat-card success-rate">
                <div class="value">{summary['success_rate']:.1f}%</div>
                <div class="label">Success Rate</div>
            </div>
        </div>

        <div class="metrics-accuracy">
            <div class="metrics-grid">
                {''.join(metric_cards)}
            </div>
        </div>
        
        <div class="table-wrapper">
            <table>
                <thead>
                    <tr>
                        <th></th>
                        <th>#</th>
                        <th>Input</th>
                        <th>Output</th>
                        <th>Expected</th>
                        {metric_headers}
                        <th>Time</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(table_rows)}
                </tbody>
            </table>
        </div>
        
        <div class="last-updated">
            Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </div>
    </div>

    <!-- Modal root -->
    <div id="modal-overlay" class="modal-overlay" role="dialog" aria-modal="true" aria-hidden="true">
        <div class="modal" role="document">
            <div class="modal-header">
                <div class="modal-title" id="modal-title">Row Details</div>
                <button class="modal-close" id="modal-close" aria-label="Close">✕</button>
            </div>
            <div class="modal-content">
                
                <div class="modal-row"><div class="modal-label">Input</div><div class="modal-value" id="m-input"></div></div>
                <div class="modal-row"><div class="modal-label">Output</div><div class="modal-value" id="m-output"></div></div>
                <div class="modal-row"><div class="modal-label">Expected</div><div class="modal-value" id="m-expected"></div></div>
                <div class="modal-row"><div class="modal-label">Time</div><div class="modal-value" id="m-time"></div></div>
                <div class="modal-row"><div class="modal-label">Metrics</div>
                    <div class="modal-metrics" id="m-metrics"></div>
                </div>
            </div>
        </div>
    </div>

    <div class="live-indicator" id="live-indicator"><span class="live-dot"></span><span id="live-text">Live</span></div>

    {script_block}
</body>
</html>'''

    return html_content


def cleanup_old_html_files(base_dir: Path, max_age_hours: int = 1) -> None:
    """Remove result subdirectories older than a threshold.

    Errors are swallowed intentionally to keep the UI resilient.
    """
    now = datetime.now()
    cutoff_time = now - timedelta(hours=max_age_hours)
    try:
        for item in base_dir.iterdir():
            if item.is_dir():
                mtime = datetime.fromtimestamp(item.stat().st_mtime)
                if mtime < cutoff_time:
                    shutil.rmtree(item)
    except Exception:
        pass


def start_http_server(directory: Path) -> Tuple[int, socketserver.TCPServer]:
    """Start a quiet HTTP server that serves the provided directory.

    Returns a tuple of (port, server). The server runs in a daemon thread.
    """

    class QuietHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(directory), **kwargs)

        def log_message(self, format, *args):
            # Suppress log messages
            pass

    httpd = socketserver.TCPServer(("", 0), QuietHTTPRequestHandler)
    port = httpd.server_address[1]

    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    return port, httpd


