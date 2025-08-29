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
import http.server
import shutil
import socketserver
import threading


def generate_html_table(
    item_statuses: Dict[int, Dict],
    items: List[Any],
    dataset_name: str,
    run_name: str,
    metric_names: Iterable[str],
) -> str:
    """Generate a modern HTML page for live evaluation results.

    Args:
        item_statuses: Per-item status dicts produced by the evaluator.
        items: Dataset items in evaluation order.
        dataset_name: Name of the evaluated dataset.
        run_name: Name/ID of this evaluation run.
        metric_names: Iterable of metric names in display order.

    Returns:
        Complete HTML document as a string.
    """
    # Summary statistics
    total_items = len(items)
    completed = sum(1 for s in item_statuses.values() if s['status'] == 'completed')
    in_progress = sum(1 for s in item_statuses.values() if s['status'] == 'in_progress')
    failed = sum(1 for s in item_statuses.values() if s['status'] == 'error')
    pending = total_items - completed - in_progress - failed
    success_rate = (completed / total_items * 100) if total_items > 0 else 0

    # Build table rows
    table_rows: List[str] = []
    for idx in range(len(items)):
        status = item_statuses[idx]

        # Row classes and icon
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

        # Metric cells
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

        # Time cell cleanup
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

        # Content cells
        input_text = html_lib.escape(str(status['input'])[:100])

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
        output_text = html_lib.escape(output_text[:100])

        expected_text = html_lib.escape(str(status['expected'])[:100])

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

    # Headers
    metric_headers = "".join([f'<th>{name}</th>' for name in metric_names])

    # HTML document
    html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="2">
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
            overflow: hidden;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
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
            max-width: 300px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            cursor: help;
        }}
        
        .time-cell {{
            width: 100px;
            text-align: right;
            font-family: 'Monaco', 'Consolas', monospace;
            font-size: 0.9rem;
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
        
        tr.pending {{ opacity: 0.6; }}
        tr.pending .status-icon {{ color: #60a5fa; }}
        
        .metric-pending {{ opacity: 0.4; }}
        .metric-computing {{ 
            color: #fbbf24;
            animation: pulse 1s ease-in-out infinite;
        }}
        .metric-error {{ color: #f87171; }}
        
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
        
        @media (max-width: 768px) {{
            .stats-grid {{
                grid-template-columns: repeat(2, 1fr);
            }}
            
            .content-cell {{
                max-width: 150px;
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
                <div class="value">{completed}</div>
                <div class="label">Completed</div>
            </div>
            <div class="stat-card in-progress">
                <div class="value">{in_progress}</div>
                <div class="label">In Progress</div>
            </div>
            <div class="stat-card failed">
                <div class="value">{failed}</div>
                <div class="label">Failed</div>
            </div>
            <div class="stat-card pending">
                <div class="value">{pending}</div>
                <div class="label">Pending</div>
            </div>
            <div class="stat-card success-rate">
                <div class="value">{success_rate:.1f}%</div>
                <div class="label">Success Rate</div>
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


