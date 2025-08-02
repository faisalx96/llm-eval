"""Main Evaluator class for LLM evaluation."""

import asyncio
import os
from typing import Any, Callable, Dict, List, Optional, Union
from datetime import datetime
import functools
import time
import tempfile
import webbrowser
from pathlib import Path
import json
import threading
import http.server
import socketserver
import socket

from langfuse import Langfuse
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn, TimeElapsedColumn
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich.table import Table

from .results import EvaluationResult
from .dataset import LangfuseDataset
from ..adapters.base import TaskAdapter, auto_detect_task
from ..metrics.registry import get_metric
from ..utils.errors import LangfuseConnectionError, DatasetNotFoundError


console = Console()


class Evaluator:
    """
    Simple evaluator for LLM tasks using Langfuse datasets.
    
    Example:
        evaluator = Evaluator(
            task=my_llm_function,
            dataset="qa-test-set",
            metrics=["exact_match", "response_time"]
        )
        results = evaluator.run()
    """
    
    def __init__(
        self,
        task: Any,
        dataset: str, 
        metrics: List[Union[str, Callable]],
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the evaluator.
        
        Args:
            task: The LLM task to evaluate (function, chain, agent, etc.)
            dataset: Name of the Langfuse dataset to use
            metrics: List of metric names or callable functions
            config: Optional configuration dict with keys:
                - langfuse_public_key: Override env variable
                - langfuse_secret_key: Override env variable
                - langfuse_host: Override env variable
                - max_concurrency: Max parallel evaluations (default: 10)
                - timeout: Timeout per evaluation in seconds (default: 30)
                - run_name: Name for this evaluation run
                - run_metadata: Metadata to attach to the run
        """
        self.config = config or {}
        self.task = task
        self.dataset_name = dataset
        self.metrics = self._prepare_metrics(metrics)
        
        # Initialize Langfuse client
        self.client = self._init_langfuse()
        
        # Load and validate dataset
        self.dataset = LangfuseDataset(self.client, dataset)
        
        # Prepare task adapter
        self.task_adapter = auto_detect_task(task, self.client)
        
        # Configuration
        self.max_concurrency = self.config.get('max_concurrency', 10)
        self.timeout = self.config.get('timeout', 30.0)
        self.run_name = self.config.get('run_name', f"eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        self.run_metadata = self.config.get('run_metadata', {})
    
    def _init_langfuse(self) -> Langfuse:
        """Initialize Langfuse client with error handling."""
        # Auto-load .env file if it exists
        if os.path.exists('.env'):
            try:
                from dotenv import load_dotenv
                load_dotenv()
            except ImportError:
                pass  # dotenv not installed, skip
        
        # Get credentials from config or environment
        public_key = self.config.get('langfuse_public_key') or os.getenv('LANGFUSE_PUBLIC_KEY')
        secret_key = self.config.get('langfuse_secret_key') or os.getenv('LANGFUSE_SECRET_KEY')
        host = self.config.get('langfuse_host') or os.getenv('LANGFUSE_HOST')
        
        # Validate required credentials
        if not public_key:
            raise LangfuseConnectionError(
                "Missing Langfuse public key. Please:\n"
                "1. Set LANGFUSE_PUBLIC_KEY environment variable, or\n"
                "2. Add 'langfuse_public_key' to evaluator config, or\n"
                "3. Create a .env file with LANGFUSE_PUBLIC_KEY=your_key"
            )
        
        if not secret_key:
            raise LangfuseConnectionError(
                "Missing Langfuse secret key. Please:\n"
                "1. Set LANGFUSE_SECRET_KEY environment variable, or\n"
                "2. Add 'langfuse_secret_key' to evaluator config, or\n"
                "3. Create a .env file with LANGFUSE_SECRET_KEY=your_key"
            )
        
        try:
            client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=host
            )
            return client
        except Exception as e:
            if "401" in str(e) or "unauthorized" in str(e).lower():
                raise LangfuseConnectionError(
                    "Invalid Langfuse credentials. Please check your:\n"
                    "- LANGFUSE_PUBLIC_KEY\n"
                    "- LANGFUSE_SECRET_KEY\n"
                    "- LANGFUSE_HOST (if using custom instance)"
                )
            raise LangfuseConnectionError(f"Failed to connect to Langfuse: {e}")
    
    def _prepare_metrics(self, metrics: List[Union[str, Callable]]) -> Dict[str, Callable]:
        """Convert metric list to dict of callables."""
        prepared = {}
        for metric in metrics:
            if isinstance(metric, str):
                prepared[metric] = get_metric(metric)
            elif callable(metric):
                name = getattr(metric, '__name__', f'custom_metric_{len(prepared)}')
                prepared[name] = metric
            else:
                raise ValueError(f"Metric must be string or callable, got {type(metric)}")
        return prepared
    
    def run(self, show_progress: bool = True, show_table: bool = True, auto_save: bool = False, save_format: str = "json") -> EvaluationResult:
        """
        Run the evaluation synchronously.
        
        Args:
            show_progress: Whether to show progress bar
            show_table: Whether to show live per-item status table
            auto_save: Whether to automatically save results after evaluation
            save_format: Format for auto-save ("json" or "csv")
            
        Returns:
            EvaluationResult object with scores and statistics
        """
        # Check if we're already in an event loop (e.g., Jupyter notebook)
        try:
            asyncio.get_running_loop()
            # We're in a running loop (like Jupyter), use nest_asyncio
            import nest_asyncio
            nest_asyncio.apply()
        except RuntimeError:
            # No event loop running, which is fine
            pass
        
        # Fix Windows event loop issues
        import sys
        if sys.platform == 'win32':
            # Use SelectorEventLoop on Windows to avoid ProactorEventLoop issues
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
        # Run the async evaluation
        result = asyncio.run(self.arun(show_progress, show_table, auto_save, save_format))
        
        # Always print summary
        result.print_summary()
        
        return result
    
    async def arun(self, show_progress: bool = True, show_table: bool = True, auto_save: bool = False, save_format: str = "json") -> EvaluationResult:
        """
        Run the evaluation asynchronously.
        
        Args:
            show_progress: Whether to show progress bar
            show_table: Whether to show live per-item status table
            auto_save: Whether to automatically save results after evaluation
            save_format: Format for auto-save ("json" or "csv")
            
        Returns:
            EvaluationResult object with scores and statistics
        """
        result = EvaluationResult(
            dataset_name=self.dataset_name,
            run_name=self.run_name,
            metrics=list(self.metrics.keys())
        )
        
        items = self.dataset.get_items()
        if not items:
            console.print("[yellow]Warning: Dataset is empty[/yellow]")
            return result
        
        # Initialize status tracking for each item
        item_statuses = {}
        for idx, item in enumerate(items):
            # More generous truncation - let Rich handle the ellipsis
            input_text = str(item.input)
            expected_text = str(getattr(item, 'expected_output', 'N/A'))
            
            item_statuses[idx] = {
                'input': input_text,
                'output': '[dim]pending[/dim]',
                'expected': expected_text,
                'metrics': {metric: '[dim]pending[/dim]' for metric in self.metrics.keys()},
                'status': 'pending',
                'time': '[dim]pending[/dim]',
                'start_time': None,
                'end_time': None
            }
        
        # HTML file setup for table view
        html_file = None
        html_url = None
        http_server = None
        http_port = None
        
        if show_table:
            # Create a temporary directory for the HTML file
            temp_dir = Path(tempfile.mkdtemp(prefix='llm_eval_'))
            html_file = temp_dir / 'index.html'
            
            # Write initial HTML
            html_content = self._generate_html_table(item_statuses, items)
            html_file.write_text(html_content)
            
            # Start HTTP server
            http_port, http_server = self._start_http_server(temp_dir)
            html_url = f"http://localhost:{http_port}/"
        
        # Progress tracking with live display
        if show_progress:
            # Progress bar
            progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}", style="cyan"),
                TextColumn("│", style="dim"),  # Separator
                BarColumn(bar_width=40),
                TextColumn("│", style="dim"),  # Separator
                TaskProgressColumn(),
                TextColumn("│", style="dim"),  # Separator
                TimeElapsedColumn(),
                expand=False
            )
            
            # Calculate total work: items * metrics per item
            total_work = len(items) * len(self.metrics)
            task_progress = progress.add_task(f"Evaluating {len(items)} items with {len(self.metrics)} metrics", total=total_work)
            
            if show_table:
                
                def generate_display():
                    # Calculate summary statistics
                    total_items = len(items)
                    completed = sum(1 for s in item_statuses.values() if s['status'] == 'completed')
                    in_progress = sum(1 for s in item_statuses.values() if s['status'] == 'in_progress')
                    failed = sum(1 for s in item_statuses.values() if s['status'] == 'error')
                    pending = total_items - completed - in_progress - failed
                    success_rate = (completed / total_items * 100) if total_items > 0 else 0
                    
                    # Create summary content with progress bar at the top
                    from rich.console import Group
                    
                    summary_text = f"""
[green]✓ Completed:[/green] {completed}/{total_items}
[yellow]⟳ In Progress:[/yellow] {in_progress}
[red]✗ Failed:[/red] {failed}
[blue]◯ Pending:[/blue] {pending}

[bold magenta]Success Rate:[/bold magenta] {success_rate:.1f}%

📊 [bold cyan]View detailed results in your browser:[/bold cyan]
👉 [bold blue underline]{html_url}[/bold blue underline]"""
                    
                    # Combine progress bar and summary text
                    content = Group(
                        progress,
                        summary_text
                    )
                    
                    panel = Panel(
                        content, 
                        title="[bold cyan]📊 Evaluation Summary[/bold cyan]",
                        expand=False, 
                        border_style="cyan", 
                        padding=(1, 2)
                    )
                    
                    return panel
                
                # Start live display with summary panel
                with Live(generate_display(), console=console, refresh_per_second=10) as live:
                    # Create a function to update HTML
                    async def update_html():
                        while True:
                            try:
                                html_content = self._generate_html_table(item_statuses, items)
                                html_file.write_text(html_content)
                            except Exception:
                                pass  # Ignore errors in HTML update
                            await asyncio.sleep(2)  # Update every 2 seconds
                    
                    # Start HTML update task
                    html_update_task = asyncio.create_task(update_html())
                    
                    # Run evaluations
                    semaphore = asyncio.Semaphore(self.max_concurrency)
                    tasks = []
                    
                    for idx, item in enumerate(items):
                        task = self._evaluate_item_with_status(
                            item, idx, semaphore, progress, task_progress, 
                            item_statuses, live, generate_display
                        )
                        tasks.append(task)
                    
                    # Gather results
                    eval_results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # Cancel HTML update task
                    html_update_task.cancel()
                    try:
                        await html_update_task
                    except asyncio.CancelledError:
                        pass
                    
                    # Final HTML update
                    html_content = self._generate_html_table(item_statuses, items)
                    html_file.write_text(html_content)
                    
                    # Process results
                    for idx, eval_result in enumerate(eval_results):
                        if isinstance(eval_result, Exception):
                            result.add_error(f"item_{idx}", str(eval_result))
                        else:
                            result.add_result(f"item_{idx}", eval_result)
            else:
                # Start live display with progress bar only
                with Live(progress, console=console, refresh_per_second=10) as live:
                    # Run evaluations
                    semaphore = asyncio.Semaphore(self.max_concurrency)
                    tasks = []
                    
                    for idx, item in enumerate(items):
                        task = self._evaluate_item_with_progress_only(
                            item, idx, semaphore, progress, task_progress
                        )
                        tasks.append(task)
                    
                    # Gather results
                    eval_results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # Process results
                    for idx, eval_result in enumerate(eval_results):
                        if isinstance(eval_result, Exception):
                            result.add_error(f"item_{idx}", str(eval_result))
                        else:
                            result.add_result(f"item_{idx}", eval_result)
            
            console.print()  # Empty line for spacing
            console.print(f"[green]✅ Evaluation complete![/green] Processed {len(items)} items with {len(self.metrics)} metrics", style="bold")
            console.print()  # Empty line for spacing
        else:
            # Run without progress display
            semaphore = asyncio.Semaphore(self.max_concurrency)
            tasks = []
            
            for idx, item in enumerate(items):
                task = self._evaluate_item(item, idx, semaphore, None, None)
                tasks.append(task)
            
            # Gather results
            eval_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            for idx, eval_result in enumerate(eval_results):
                if isinstance(eval_result, Exception):
                    result.add_error(f"item_{idx}", str(eval_result))
                else:
                    result.add_result(f"item_{idx}", eval_result)
        
        # Mark evaluation as finished
        result.finish()
        
        # Auto-save if requested
        if auto_save:
            try:
                saved_path = result.save(format=save_format)
                console.print(f"[blue]📁 Auto-saved results to: {saved_path}[/blue]")
                console.print()  # Empty line for spacing
            except Exception as e:
                console.print(f"[yellow]⚠️  Warning: Failed to auto-save results: {e}[/yellow]")
                console.print()  # Empty line for spacing
        
        # Clean up HTTP server if it was started
        if http_server:
            try:
                http_server.shutdown()
            except:
                pass
        
        return result
    
    async def _evaluate_item(self, item: Any, index: int, semaphore: asyncio.Semaphore, progress=None, task_progress=None) -> Dict[str, Any]:
        """Evaluate a single dataset item."""
        async with semaphore:
            try:
                # Run task with Langfuse tracing
                with item.run(
                    run_name=self.run_name,
                    run_metadata={**self.run_metadata, "item_index": index}
                ) as trace:
                    # Execute task
                    output = await self.task_adapter.arun(item.input, trace)
                    
                    # Compute metrics
                    scores = {}
                    for metric_name, metric_func in self.metrics.items():
                        try:
                            score = await self._compute_metric(
                                metric_func, 
                                output, 
                                getattr(item, 'expected_output', None),
                                item.input
                            )
                            scores[metric_name] = score
                            
                            # Log score to Langfuse
                            trace.score_trace(
                                name=metric_name,
                                value=score if isinstance(score, (int, float, bool)) else str(score),
                                data_type=self._get_score_type(score)
                            )
                            
                            # Update progress after each metric
                            if progress and task_progress is not None:
                                progress.update(task_progress, advance=1)
                                
                        except Exception as e:
                            scores[metric_name] = {"error": str(e)}
                            # Still advance progress even on error
                            if progress and task_progress is not None:
                                progress.update(task_progress, advance=1)
                    
                    return {
                        "output": output,
                        "scores": scores,
                        "success": True
                    }
                    
            except asyncio.TimeoutError:
                raise TimeoutError(f"Evaluation timed out after {self.timeout}s")
            except Exception as e:
                raise RuntimeError(f"Task execution failed: {e}")
    
    async def _compute_metric(self, metric: Callable, output: Any, expected: Any, input_data: Any = None) -> Any:
        """Compute a metric, handling both sync and async functions."""
        import inspect
        
        # Determine metric signature
        sig = inspect.signature(metric)
        params = list(sig.parameters.keys())
        
        # Prepare arguments based on metric signature
        if len(params) == 1:
            args = (output,)
        elif len(params) == 2:
            args = (output, expected)
        elif len(params) == 3:
            # For DeepEval metrics that need input_data
            args = (output, expected, input_data)
        else:
            # Try with keyword arguments for flexibility
            kwargs = {'output': output, 'expected': expected, 'input_data': input_data}
            filtered_kwargs = {k: v for k, v in kwargs.items() if k in params}
            args = tuple(filtered_kwargs.values())
        
        # Call metric (async or sync)
        if inspect.iscoroutinefunction(metric):
            result = await metric(*args)
        else:
            result = metric(*args)
        return result
    
    def _get_score_type(self, score: Any) -> str:
        """Determine Langfuse score data type."""
        if isinstance(score, bool):
            return "BOOLEAN"
        elif isinstance(score, (int, float)):
            return "NUMERIC"
        else:
            return "CATEGORICAL"
    
    def _generate_html_table(self, item_statuses: Dict[int, Dict], items: List[Any]) -> str:
        """Generate a beautiful HTML page with live evaluation results."""
        # Calculate summary statistics
        total_items = len(items)
        completed = sum(1 for s in item_statuses.values() if s['status'] == 'completed')
        in_progress = sum(1 for s in item_statuses.values() if s['status'] == 'in_progress')
        failed = sum(1 for s in item_statuses.values() if s['status'] == 'error')
        pending = total_items - completed - in_progress - failed
        success_rate = (completed / total_items * 100) if total_items > 0 else 0
        
        # Generate table rows
        table_rows = []
        for idx in range(len(items)):
            status = item_statuses[idx]
            
            # Determine row class based on status
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
            
            # Build metric cells
            metric_cells = []
            for metric_name in self.metrics.keys():
                metric_value = status['metrics'][metric_name]
                metric_class = ""
                if metric_value == '[dim]pending[/dim]':
                    metric_value = '-'
                    metric_class = "metric-pending"
                elif metric_value == '[yellow]computing...[/yellow]':
                    metric_value = '...'
                    metric_class = "metric-computing"
                elif metric_value == '[red]error[/red]' or metric_value == '[red]N/A[/red]':
                    metric_value = 'error'
                    metric_class = "metric-error"
                metric_cells.append(f'<td class="{metric_class}">{metric_value}</td>')
            
            # Clean up time value
            time_value = status['time']
            if '[yellow]running...[/yellow]' in str(time_value):
                time_value = 'running...'
            elif '[red]' in str(time_value):
                time_value = time_value.replace('[red]', '').replace('[/red]', '')
            elif time_value == '[dim]pending[/dim]':
                time_value = '-'
            
            # Escape HTML in content
            import html
            input_text = html.escape(str(status['input'])[:100])
            output_text = html.escape(str(status['output'])[:100])
            expected_text = html.escape(str(status['expected'])[:100])
            
            row_html = f'''
            <tr class="{row_class}">
                <td class="status-cell"><span class="status-icon">{status_icon}</span></td>
                <td class="index-cell">{idx + 1}</td>
                <td class="content-cell" title="{html.escape(str(status['input']))}">{input_text}</td>
                <td class="content-cell" title="{html.escape(str(status['output']))}">{output_text}</td>
                <td class="content-cell" title="{html.escape(str(status['expected']))}">{expected_text}</td>
                {"".join(metric_cells)}
                <td class="time-cell">{time_value}</td>
            </tr>
            '''
            table_rows.append(row_html)
        
        # Build metric headers
        metric_headers = "".join([f'<th>{name}</th>' for name in self.metrics.keys()])
        
        # HTML template with modern styling
        html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="2">
    <title>LLM Evaluation Results - {self.dataset_name}</title>
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
                Dataset: <strong>{self.dataset_name}</strong> | 
                Run: <strong>{self.run_name}</strong>
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
    
    def _start_http_server(self, directory: Path) -> tuple[int, socketserver.TCPServer]:
        """Start a simple HTTP server to serve the HTML file."""
        
        class QuietHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(directory), **kwargs)
                
            def log_message(self, format, *args):
                # Suppress log messages
                pass
        
        # Find an available port
        httpd = socketserver.TCPServer(("", 0), QuietHTTPRequestHandler)
        port = httpd.server_address[1]
        
        # Start server in a daemon thread
        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()
        
        return port, httpd
    
    async def _evaluate_item_with_status(
        self, 
        item: Any, 
        index: int, 
        semaphore: asyncio.Semaphore, 
        progress, 
        task_progress,
        item_statuses: Dict[int, Dict],
        live,
        generate_display: Callable
    ) -> Dict[str, Any]:
        """Evaluate a single dataset item with live status updates."""
        async with semaphore:
            try:
                # Start timing and update status to in_progress
                start_time = time.time()
                item_statuses[index]['start_time'] = start_time
                item_statuses[index]['status'] = 'in_progress'
                item_statuses[index]['time'] = '[yellow]running...[/yellow]'
                live.update(generate_display())
                
                # Run task with Langfuse tracing
                with item.run(
                    run_name=self.run_name,
                    run_metadata={**self.run_metadata, "item_index": index}
                ) as trace:
                    # Execute task
                    output = await self.task_adapter.arun(item.input, trace)
                    
                    # Update output in status
                    item_statuses[index]['output'] = str(output)
                    live.update(generate_display())
                    
                    # Compute metrics
                    scores = {}
                    for metric_name, metric_func in self.metrics.items():
                        try:
                            # Update metric status to computing
                            item_statuses[index]['metrics'][metric_name] = '[yellow]computing...[/yellow]'
                            live.update(generate_display())
                            
                            score = await self._compute_metric(
                                metric_func, 
                                output, 
                                getattr(item, 'expected_output', None),
                                item.input
                            )
                            scores[metric_name] = score
                            
                            # Update metric value in status
                            if isinstance(score, bool):
                                item_statuses[index]['metrics'][metric_name] = '✓' if score else '✗'
                            elif isinstance(score, (int, float)):
                                item_statuses[index]['metrics'][metric_name] = f"{score:.3f}"
                            else:
                                item_statuses[index]['metrics'][metric_name] = str(score)[:20]
                            
                            # Log score to Langfuse
                            trace.score_trace(
                                name=metric_name,
                                value=score if isinstance(score, (int, float, bool)) else str(score),
                                data_type=self._get_score_type(score)
                            )
                            
                            # Update progress
                            if progress and task_progress is not None:
                                progress.update(task_progress, advance=1)
                            
                            live.update(generate_display())
                                
                        except Exception as e:
                            scores[metric_name] = {"error": str(e)}
                            item_statuses[index]['metrics'][metric_name] = '[red]error[/red]'
                            # Still advance progress even on error
                            if progress and task_progress is not None:
                                progress.update(task_progress, advance=1)
                            live.update(generate_display())
                    
                    # Update status to completed with timing
                    end_time = time.time()
                    item_statuses[index]['end_time'] = end_time
                    item_statuses[index]['status'] = 'completed'
                    elapsed = end_time - start_time
                    item_statuses[index]['time'] = f"{elapsed:.2f}s"
                    live.update(generate_display())
                    
                    return {
                        "output": output,
                        "scores": scores,
                        "success": True,
                        "time": elapsed
                    }
                    
            except asyncio.TimeoutError:
                end_time = time.time()
                item_statuses[index]['end_time'] = end_time
                item_statuses[index]['status'] = 'error'
                item_statuses[index]['output'] = '[red]timeout[/red]'
                item_statuses[index]['time'] = f"[red]{end_time - start_time:.2f}s[/red]"
                for metric_name in self.metrics.keys():
                    item_statuses[index]['metrics'][metric_name] = '[red]N/A[/red]'
                live.update(generate_display())
                raise TimeoutError(f"Evaluation timed out after {self.timeout}s")
            except Exception as e:
                end_time = time.time()
                item_statuses[index]['end_time'] = end_time
                item_statuses[index]['status'] = 'error'
                item_statuses[index]['output'] = f'[red]error: {str(e)[:30]}[/red]'
                item_statuses[index]['time'] = f"[red]{end_time - start_time:.2f}s[/red]"
                for metric_name in self.metrics.keys():
                    item_statuses[index]['metrics'][metric_name] = '[red]N/A[/red]'
                live.update(generate_display())
                raise RuntimeError(f"Task execution failed: {e}")
    
    async def _evaluate_item_with_progress_only(
        self, 
        item: Any, 
        index: int, 
        semaphore: asyncio.Semaphore, 
        progress, 
        task_progress
    ) -> Dict[str, Any]:
        """Evaluate a single dataset item with progress bar only (no table)."""
        async with semaphore:
            try:
                # Start timing
                start_time = time.time()
                
                # Run task with Langfuse tracing
                with item.run(
                    run_name=self.run_name,
                    run_metadata={**self.run_metadata, "item_index": index}
                ) as trace:
                    # Execute task
                    output = await self.task_adapter.arun(item.input, trace)
                    
                    # Compute metrics
                    scores = {}
                    for metric_name, metric_func in self.metrics.items():
                        try:
                            score = await self._compute_metric(
                                metric_func, 
                                output, 
                                getattr(item, 'expected_output', None),
                                item.input
                            )
                            scores[metric_name] = score
                            
                            # Log score to Langfuse
                            trace.score_trace(
                                name=metric_name,
                                value=score if isinstance(score, (int, float, bool)) else str(score),
                                data_type=self._get_score_type(score)
                            )
                            
                            # Update progress after each metric
                            if progress and task_progress is not None:
                                progress.update(task_progress, advance=1)
                                
                        except Exception as e:
                            scores[metric_name] = {"error": str(e)}
                            # Still advance progress even on error
                            if progress and task_progress is not None:
                                progress.update(task_progress, advance=1)
                    
                    # Calculate elapsed time
                    end_time = time.time()
                    elapsed = end_time - start_time
                    
                    return {
                        "output": output,
                        "scores": scores,
                        "success": True,
                        "time": elapsed
                    }
                    
            except asyncio.TimeoutError:
                raise TimeoutError(f"Evaluation timed out after {self.timeout}s")
            except Exception as e:
                raise RuntimeError(f"Task execution failed: {e}")