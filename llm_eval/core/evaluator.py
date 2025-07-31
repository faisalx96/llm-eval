"""Main Evaluator class for LLM evaluation."""

import asyncio
import os
from typing import Any, Callable, Dict, List, Optional, Union
from datetime import datetime
import functools
import time

from langfuse import Langfuse
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn
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
    
    def run(self, show_progress: bool = True, auto_save: bool = False, save_format: str = "json") -> EvaluationResult:
        """
        Run the evaluation synchronously.
        
        Args:
            show_progress: Whether to show progress bar
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
        return asyncio.run(self.arun(show_progress, auto_save, save_format))
    
    async def arun(self, show_progress: bool = True, auto_save: bool = False, save_format: str = "json") -> EvaluationResult:
        """
        Run the evaluation asynchronously.
        
        Args:
            show_progress: Whether to show progress bar
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
            item_statuses[idx] = {
                'input': str(item.input)[:50] + '...' if len(str(item.input)) > 50 else str(item.input),
                'output': '[dim]pending[/dim]',
                'expected': str(getattr(item, 'expected_output', 'N/A'))[:50] + '...' if hasattr(item, 'expected_output') and len(str(getattr(item, 'expected_output', ''))) > 50 else str(getattr(item, 'expected_output', 'N/A')),
                'metrics': {metric: '[dim]pending[/dim]' for metric in self.metrics.keys()},
                'status': 'pending',
                'time': '[dim]pending[/dim]',
                'start_time': None,
                'end_time': None
            }
        
        # Progress tracking with live display
        if show_progress:
            # Create layout with progress bar and status table
            layout = Layout()
            
            # Progress bar
            progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(bar_width=40),
                TaskProgressColumn(),
                TimeRemainingColumn(),
                expand=False
            )
            
            # Calculate total work: items * metrics per item
            total_work = len(items) * len(self.metrics)
            task_progress = progress.add_task(f"Evaluating {len(items)} items with {len(self.metrics)} metrics", total=total_work)
            
            def generate_display():
                # Create status table
                table = Table(title="Evaluation Status", expand=True, show_lines=True)
                table.add_column("Input", style="cyan", ratio=2)
                table.add_column("Output", style="green", ratio=2)
                table.add_column("Expected", style="yellow", ratio=2)
                
                # Add metric columns
                for metric_name in self.metrics.keys():
                    table.add_column(metric_name, style="magenta", ratio=1)
                
                # Add time column
                table.add_column("Time", style="blue", ratio=1)
                
                # Add rows for each item
                for idx in range(len(items)):
                    status = item_statuses[idx]
                    row_data = [
                        status['input'],
                        status['output'],
                        status['expected']
                    ]
                    
                    # Add metric values
                    for metric_name in self.metrics.keys():
                        row_data.append(status['metrics'][metric_name])
                    
                    # Add time
                    row_data.append(status['time'])
                    
                    # Color the row based on status
                    if status['status'] == 'completed':
                        table.add_row(*row_data, style="green")
                    elif status['status'] == 'error':
                        table.add_row(*row_data, style="red")
                    elif status['status'] == 'in_progress':
                        table.add_row(*row_data, style="yellow")
                    else:
                        table.add_row(*row_data)
                
                # Create a simple vertical group instead of layout
                from rich.console import Group
                return Group(progress, table)
            
            # Start live display
            with Live(generate_display(), console=console, refresh_per_second=4) as live:
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
                
                # Process results
                for idx, eval_result in enumerate(eval_results):
                    if isinstance(eval_result, Exception):
                        result.add_error(f"item_{idx}", str(eval_result))
                    else:
                        result.add_result(f"item_{idx}", eval_result)
            
            console.print(f"[green]✅ Evaluation complete![/green] Processed {len(items)} items with {len(self.metrics)} metrics", style="bold")
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
            except Exception as e:
                console.print(f"[yellow]⚠️  Warning: Failed to auto-save results: {e}[/yellow]")
        
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
                    output_str = str(output)[:50] + '...' if len(str(output)) > 50 else str(output)
                    item_statuses[index]['output'] = output_str
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