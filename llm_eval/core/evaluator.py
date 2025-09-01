"""Main Evaluator class for LLM evaluation."""

import asyncio
import os
from typing import Any, Callable, Dict, List, Optional, Union
from datetime import datetime
import time
import subprocess
from pathlib import Path

from langfuse import Langfuse
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich.console import Console
from rich.live import Live
from rich.panel import Panel

from .results import EvaluationResult
from .dataset import LangfuseDataset
from ..adapters.base import TaskAdapter, auto_detect_task
from ..metrics.registry import get_metric
from ..utils.errors import LangfuseConnectionError, DatasetNotFoundError
from ..utils.frontend import cleanup_old_html_files
from ..server.app import UIServer
import json


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

    def _build_run_info(self, result: Optional[EvaluationResult] = None) -> Dict[str, Any]:
        """Assemble run-level metadata for the frontend."""
        # Version
        version = None
        try:
            from .. import __version__ as _v
            version = _v
        except Exception:
            try:
                import importlib.metadata as _im
                version = _im.version("llm-eval")
            except Exception:
                version = None

        # Git SHA (best-effort)
        git_sha = None
        try:
            sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL)
            git_sha = sha.decode().strip()
        except Exception:
            git_sha = None

        run_block: Dict[str, Any] = {
            "dataset_name": self.dataset_name,
            "run_name": self.run_name,
            "config": {
                "max_concurrency": self.max_concurrency,
                "timeout": self.timeout,
                "run_metadata": self.run_metadata,
            },
            "version": version,
            "git_sha": git_sha,
            "cli_invocation": self.config.get("cli_invocation"),
            "metric_names": list(self.metrics.keys()),
            "langfuse_host": getattr(self, 'langfuse_host', None),
            "langfuse_project_id": getattr(self, 'langfuse_project_id', None),
        }

        if result is not None:
            try:
                run_block["started_at"] = result.start_time.isoformat() if result.start_time else None
                run_block["ended_at"] = result.end_time.isoformat() if result.end_time else None
                run_block["total_items"] = result.total_items
            except Exception:
                pass

        return run_block
    
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
            # Expose host for frontend links (default to cloud)
            try:
                self.langfuse_host = host or 'https://cloud.langfuse.com'
            except Exception:
                self.langfuse_host = 'https://cloud.langfuse.com'
            # Optional project id for deep-links
            try:
                self.langfuse_project_id = (
                    self.config.get('langfuse_project_id')
                    or os.getenv('LANGFUSE_PROJECT_ID')
                )
            except Exception:
                self.langfuse_project_id = None
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
    
    def run(self, show_progress: bool = True, show_table: bool = True, auto_save: bool = False, save_format: str = "json", keep_server_alive: bool = True) -> EvaluationResult:
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
        console.print()  # Add spacing after evaluation panel
        html_url = getattr(result, 'html_url', None)
        result.print_summary(html_url)
        
        # Keep the web UI open until the user confirms, unless disabled
        if html_url and show_table:
            import os
            no_prompt = os.environ.get("LLM_EVAL_NO_PROMPT", "").lower() in ("1", "true", "yes")
            if keep_server_alive and not no_prompt:
                console.print("\n[dim]Press Enter to close the web UI and exit...[/dim]")
                try:
                    input()
                except EOFError:
                    pass

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
        
        # Web UI setup
        html_url = None
        ui_server = None
        if show_table:
            desired_port = 0
            try:
                desired_port = int(self.config.get('ui_port', 0))
            except Exception:
                desired_port = 0
            ui_server = UIServer(host="127.0.0.1", port=desired_port)
            host, port = ui_server.start()
            html_url = f"http://{host}:{port}/"
            run_info = self._build_run_info(result)
            ui_server.run_state.set_run_info({
                "dataset_name": self.dataset_name,
                "run_name": self.run_name,
                "config": {"max_concurrency": self.max_concurrency, "timeout": self.timeout},
                **({} if run_info is None else run_info),
            })
        
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

[bold magenta]Success Rate:[/bold magenta] {success_rate:.0f}%

🌐 [bold cyan]View detailed results in your browser:[/bold cyan]
👉 [bold blue underline]{html_url}[/bold blue underline]"""
                    
                    # Combine progress bar and summary text
                    content = Group(
                        progress,
                        summary_text
                    )
                    
                    panel = Panel(
                        content, 
                        title="[bold cyan][yellow]⚡[/yellow] Evaluation Progress[/bold cyan]",
                        expand=False, 
                        border_style="cyan", 
                        padding=(1, 2),
                        width=100
                    )
                    
                    return panel
                
                # Start live display with summary panel
                with Live(generate_display(), console=console, refresh_per_second=10) as live:
                    # Create a function to push snapshots to the UI server
                    async def update_html():
                        while True:
                            try:
                                from datetime import datetime as dt
                                total_items = len(items)
                                completed = sum(1 for s in item_statuses.values() if s['status'] == 'completed')
                                in_progress = sum(1 for s in item_statuses.values() if s['status'] == 'in_progress')
                                failed = sum(1 for s in item_statuses.values() if s['status'] == 'error')
                                pending = total_items - completed - in_progress - failed
                                success_rate = (completed / total_items * 100) if total_items > 0 else 0
                                rows = []
                                for idx in range(len(items)):
                                    s = item_statuses[idx]
                                    tval = str(s['time'])
                                    if any(tag in tval for tag in ('[red]','[yellow]','[dim]')):
                                        tval = tval.replace('[red]','').replace('[/red]','').replace('[yellow]','').replace('[/yellow]','').replace('[dim]','').replace('[/dim]','')
                                    oval = str(s['output'])
                                    if oval == '[dim]pending[/dim]':
                                        oval = 'pending'
                                    oval = oval.replace('[red]','').replace('[/red]','').replace('[yellow]','').replace('[/yellow]','').replace('[dim]','').replace('[/dim]','')
                                    mvals = []
                                    for m in self.metrics.keys():
                                        mv = str(s['metrics'][m])
                                        if mv == '[dim]pending[/dim]': mv = 'pending'
                                        elif mv == '[yellow]computing...[/yellow]': mv = 'computing...'
                                        elif mv == '[red]error[/red]': mv = 'error'
                                        elif mv == '[red]N/A[/red]': mv = 'N/A'
                                        mvals.append(mv)
                                    rows.append({
                                        'index': idx,
                                        'status': s['status'],
                                        'input': str(s['input']),
                                        'input_full': str(s['input']),
                                        'output': oval,
                                        'output_full': str(s['output']),
                                        'expected': str(s['expected']),
                                        'expected_full': str(s['expected']),
                                        'metric_values': mvals,
                                        'time': tval,
                                        'latency_ms': int(((s.get('end_time') or 0) - (s.get('start_time') or 0)) * 1000) if s.get('end_time') and s.get('start_time') else None,
                                        'trace_id': s.get('trace_id'),
                                        'trace_url': s.get('trace_url'),
                                    })
                                snap = {
                                    'rows': rows,
                                    'stats': {
                                        'total': total_items,
                                        'completed': completed,
                                        'in_progress': in_progress,
                                        'failed': failed,
                                        'pending': pending,
                                        'success_rate': success_rate,
                                    },
                                    'last_updated': dt.now().strftime('%Y-%m-%d %H:%M:%S'),
                                }
                                if ui_server is not None:
                                    ui_server.run_state.set_snapshot(snap)
                                    ui_server.broadcast_snapshot()
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
                    
                    # Final broadcast
                    try:
                        if ui_server is not None:
                            ui_server.broadcast_snapshot()
                    except Exception:
                        pass
                    
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
        
        # Store UI URL if available
        if html_url:
            result.html_url = html_url
        
        # Auto-save if requested
        if auto_save:
            try:
                saved_path = result.save(format=save_format)
                console.print(f"[blue]📁 Auto-saved results to: {saved_path}[/blue]")
            except Exception as e:
                console.print(f"[yellow]⚠️  Warning: Failed to auto-save results: {e}[/yellow]")
        
        # Keep HTTP server running - don't shut it down
        # The server will be cleaned up when the process exits
        
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
                    # Capture Langfuse trace identifiers if available
                    try:
                        item_statuses[index]['trace_id'] = getattr(trace, 'id', None) or getattr(trace, 'trace_id', None)
                    except Exception:
                        item_statuses[index]['trace_id'] = None
                    try:
                        url = getattr(trace, 'url', None)
                        if not url and hasattr(trace, 'get_url'):
                            url = trace.get_url()
                        item_statuses[index]['trace_url'] = url
                    except Exception:
                        item_statuses[index]['trace_url'] = None
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
    
    # Frontend concerns moved to llm_eval.utils.frontend
    
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
                                item_statuses[index]['metrics'][metric_name] = f"{int(score)}"
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
                    item_statuses[index]['time'] = f"{int(elapsed)}s"
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
                item_statuses[index]['time'] = f"[red]{int(end_time - start_time)}s[/red]"
                for metric_name in self.metrics.keys():
                    item_statuses[index]['metrics'][metric_name] = '[red]N/A[/red]'
                live.update(generate_display())
                raise TimeoutError(f"Evaluation timed out after {self.timeout}s")
            except Exception as e:
                end_time = time.time()
                item_statuses[index]['end_time'] = end_time
                item_statuses[index]['status'] = 'error'
                item_statuses[index]['output'] = f'[red]error: {str(e)[:30]}[/red]'
                item_statuses[index]['time'] = f"[red]{int(end_time - start_time)}s[/red]"
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
