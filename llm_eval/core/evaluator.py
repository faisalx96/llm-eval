"""Main Evaluator class for LLM evaluation."""

import asyncio
import functools
import logging
import os
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Union

from langfuse import Langfuse
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from rich.text import Text

from ..adapters.base import TaskAdapter, auto_detect_task
from ..metrics.registry import get_metric
from ..templates.base import EvaluationTemplate
from ..utils.errors import DatasetNotFoundError, LangfuseConnectionError
from .dataset import LangfuseDataset
from .results import EvaluationResult

console = Console()
logger = logging.getLogger(__name__)


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
        config: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
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
                - store_runs: Whether to store runs in database (default: True)
                - project_id: Project ID for run organization
                - created_by: User identifier for run attribution
                - tags: List of tags for run organization
            run_id: Optional run ID for WebSocket progress updates
        """
        self.config = config or {}
        self.task = task
        self.dataset_name = dataset
        self.metrics = self._prepare_metrics(metrics)
        self.run_id = run_id  # Store run_id for WebSocket updates

        # Initialize Langfuse client
        self.client = self._init_langfuse()

        # Load and validate dataset
        self.dataset = LangfuseDataset(self.client, dataset)

        # Prepare task adapter
        self.task_adapter = auto_detect_task(task, self.client)

        # Configuration
        self.max_concurrency = self.config.get("max_concurrency", 10)
        self.timeout = self.config.get("timeout", 30.0)
        self.run_name = self.config.get(
            "run_name", f"eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )
        self.run_metadata = self.config.get("run_metadata", {})

        # Storage configuration
        self.store_runs = self.config.get("store_runs", True)
        self.project_id = self.config.get("project_id", None)
        self.created_by = self.config.get("created_by", None)
        self.tags = self.config.get("tags", [])
        self.database_run_id = None  # Will be set when run is stored

    @classmethod
    def from_template(
        cls,
        template: EvaluationTemplate,
        task: Any,
        dataset: str,
        custom_metrics: Optional[List[Union[str, Callable]]] = None,
        **kwargs,
    ) -> "Evaluator":
        """
        Create an evaluator using a pre-built evaluation template.

        This method provides a convenient way to get started with best-practice
        evaluation patterns for common LLM evaluation scenarios.

        Args:
            template: EvaluationTemplate instance with pre-configured metrics and settings
            task: The LLM task to evaluate (function, chain, agent, etc.)
            dataset: Name of the Langfuse dataset to use
            custom_metrics: Override template metrics with custom ones (optional)
            **kwargs: Additional configuration options passed to Evaluator

        Returns:
            Configured Evaluator instance ready to run

        Example:
            from llm_eval.templates import get_template

            # Get Q&A template
            qa_template = get_template('qa')

            # Create evaluator using template
            evaluator = Evaluator.from_template(
                qa_template,
                task=my_qa_system,
                dataset="qa-test-set"
            )

            # Run evaluation
            results = evaluator.run()
        """
        # Use template metrics unless custom ones are provided
        metrics = (
            custom_metrics if custom_metrics is not None else template.get_metrics()
        )

        # Create evaluator config from template
        evaluator_config = template.create_evaluator_config(
            task=task, dataset=dataset, custom_metrics=metrics, **kwargs
        )

        # Extract task, dataset, and metrics for the constructor
        task = evaluator_config.pop("task")
        dataset = evaluator_config.pop("dataset")
        metrics = evaluator_config.pop("metrics")

        # Use remaining config as the config parameter
        config = evaluator_config

        # Add template metadata to run metadata
        run_metadata = config.get("run_metadata", {})
        run_metadata.update(
            {
                "template_name": template.config.name,
                "template_metrics": template.get_metrics(),
                "template_use_cases": template.config.use_cases,
            }
        )
        config["run_metadata"] = run_metadata

        # Create and return evaluator instance
        return cls(task=task, dataset=dataset, metrics=metrics, config=config)

    def _init_langfuse(self) -> Langfuse:
        """Initialize Langfuse client with error handling."""
        # Auto-load .env file if it exists
        if os.path.exists(".env"):
            try:
                from dotenv import load_dotenv

                load_dotenv()
            except ImportError:
                pass  # dotenv not installed, skip

        # Get credentials from config or environment
        public_key = self.config.get("langfuse_public_key") or os.getenv(
            "LANGFUSE_PUBLIC_KEY"
        )
        secret_key = self.config.get("langfuse_secret_key") or os.getenv(
            "LANGFUSE_SECRET_KEY"
        )
        host = self.config.get("langfuse_host") or os.getenv("LANGFUSE_HOST")

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
            client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
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

    def _prepare_metrics(
        self, metrics: List[Union[str, Callable]]
    ) -> Dict[str, Callable]:
        """Convert metric list to dict of callables."""
        prepared = {}
        for metric in metrics:
            if isinstance(metric, str):
                prepared[metric] = get_metric(metric)
            elif callable(metric):
                name = getattr(metric, "__name__", f"custom_metric_{len(prepared)}")
                prepared[name] = metric
            else:
                raise ValueError(
                    f"Metric must be string or callable, got {type(metric)}"
                )
        return prepared

    async def _emit_progress_update(self, event_type: str, data: Dict[str, Any]):
        """
        Emit a progress update via WebSocket if run_id is available.

        Args:
            event_type: Type of update (progress, result, error, completed)
            data: Update data
        """
        if not self.run_id:
            return

        try:
            # Dynamically import to avoid circular imports
            from ..api.websockets import emit_progress_update

            await emit_progress_update(self.run_id, event_type, data)
        except ImportError:
            # WebSocket functionality not available
            pass
        except Exception as e:
            # Log error but don't break evaluation
            logger.warning(f"Failed to emit progress update: {e}")

    def run(
        self,
        show_progress: bool = True,
        show_table: bool = True,
        auto_save: bool = False,
        save_format: str = "json",
    ) -> EvaluationResult:
        """
        Run the evaluation synchronously.

        Args:
            show_progress: Whether to show progress bar
            show_table: Whether to show live per-item status table
            auto_save: Whether to automatically save results after evaluation
            save_format: Format for auto-save ("json", "csv", or "excel")

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

        if sys.platform == "win32":
            # Use SelectorEventLoop on Windows to avoid ProactorEventLoop issues
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        # Run the async evaluation
        result = asyncio.run(
            self.arun(show_progress, show_table, auto_save, save_format)
        )

        # Always print summary
        result.print_summary()

        return result

    async def arun(
        self,
        show_progress: bool = True,
        show_table: bool = True,
        auto_save: bool = False,
        save_format: str = "json",
    ) -> EvaluationResult:
        """
        Run the evaluation asynchronously.

        Args:
            show_progress: Whether to show progress bar
            show_table: Whether to show live per-item status table
            auto_save: Whether to automatically save results after evaluation
            save_format: Format for auto-save ("json", "csv", or "excel")

        Returns:
            EvaluationResult object with scores and statistics
        """
        result = EvaluationResult(
            dataset_name=self.dataset_name,
            run_name=self.run_name,
            metrics=list(self.metrics.keys()),
        )

        items = self.dataset.get_items()
        if not items:
            console.print("[yellow]Warning: Dataset is empty[/yellow]")
            # Emit completion for empty dataset
            await self._emit_progress_update(
                "completed",
                {
                    "total_items": 0,
                    "completed_items": 0,
                    "success_rate": 0.0,
                    "message": "Dataset is empty",
                },
            )
            return result

        # Emit evaluation started
        await self._emit_progress_update(
            "progress",
            {
                "total_items": len(items),
                "completed_items": 0,
                "success_rate": 0.0,
                "status": "started",
                "message": f"Starting evaluation of {len(items)} items with {len(self.metrics)} metrics",
            },
        )

        # Initialize status tracking for each item
        item_statuses = {}
        for idx, item in enumerate(items):
            # More generous truncation - let Rich handle the ellipsis
            input_text = str(item.input)
            expected_text = str(getattr(item, "expected_output", "N/A"))

            item_statuses[idx] = {
                "input": input_text,
                "output": "[dim]pending[/dim]",
                "expected": expected_text,
                "metrics": {
                    metric: "[dim]pending[/dim]" for metric in self.metrics.keys()
                },
                "status": "pending",
                "time": "[dim]pending[/dim]",
                "start_time": None,
                "end_time": None,
            }

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
                expand=False,
            )

            # Calculate total work: items * metrics per item
            total_work = len(items) * len(self.metrics)
            task_progress = progress.add_task(
                f"Evaluating {len(items)} items with {len(self.metrics)} metrics",
                total=total_work,
            )

            if show_table:

                def generate_display():
                    # Create status table
                    table = Table(
                        title="Evaluation Status",
                        expand=True,
                        show_lines=True,
                        width=None,
                    )
                    table.add_column(
                        "Input",
                        style="cyan",
                        ratio=3,
                        max_width=50,
                        overflow="ellipsis",
                    )
                    table.add_column(
                        "Output",
                        style="green",
                        ratio=3,
                        max_width=50,
                        overflow="ellipsis",
                    )
                    table.add_column(
                        "Expected",
                        style="yellow",
                        ratio=3,
                        max_width=50,
                        overflow="ellipsis",
                    )

                    # Add metric columns
                    for metric_name in self.metrics.keys():
                        table.add_column(
                            metric_name, style="magenta", ratio=1, max_width=15
                        )

                    # Add time column
                    table.add_column("Time", style="blue", ratio=1, max_width=10)

                    # Add rows for each item
                    for idx in range(len(items)):
                        status = item_statuses[idx]
                        row_data = [
                            status["input"],
                            status["output"],
                            status["expected"],
                        ]

                        # Add metric values
                        for metric_name in self.metrics.keys():
                            row_data.append(status["metrics"][metric_name])

                        # Add time
                        row_data.append(status["time"])

                        # Color the row based on status
                        if status["status"] == "completed":
                            table.add_row(*row_data, style="green")
                        elif status["status"] == "error":
                            table.add_row(*row_data, style="red")
                        elif status["status"] == "in_progress":
                            table.add_row(*row_data, style="yellow")
                        else:
                            table.add_row(*row_data)

                    # Create a simple vertical group instead of layout
                    from rich.console import Group

                    return Group(progress, table)

                # Start live display with table
                with Live(
                    generate_display(), console=console, refresh_per_second=10
                ) as live:
                    # Run evaluations
                    semaphore = asyncio.Semaphore(self.max_concurrency)
                    tasks = []

                    for idx, item in enumerate(items):
                        task = self._evaluate_item_with_status(
                            item,
                            idx,
                            semaphore,
                            progress,
                            task_progress,
                            item_statuses,
                            live,
                            generate_display,
                        )
                        tasks.append(task)

                    # Gather results
                    eval_results = await asyncio.gather(*tasks, return_exceptions=True)

                    # Process results and track progress
                    completed_items = 0
                    successful_items = 0
                    for idx, eval_result in enumerate(eval_results):
                        completed_items += 1
                        if isinstance(eval_result, Exception):
                            result.add_error(f"item_{idx}", str(eval_result))
                        else:
                            result.add_result(f"item_{idx}", eval_result)
                            successful_items += 1

                    # Emit progress update
                    success_rate = (
                        successful_items / completed_items
                        if completed_items > 0
                        else 0.0
                    )
                    await self._emit_progress_update(
                        "progress",
                        {
                            "total_items": len(items),
                            "completed_items": completed_items,
                            "successful_items": successful_items,
                            "success_rate": success_rate,
                            "status": "processing_complete",
                        },
                    )
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

                    # Process results and track progress
                    completed_items = 0
                    successful_items = 0
                    for idx, eval_result in enumerate(eval_results):
                        completed_items += 1
                        if isinstance(eval_result, Exception):
                            result.add_error(f"item_{idx}", str(eval_result))
                        else:
                            result.add_result(f"item_{idx}", eval_result)
                            successful_items += 1

                    # Emit progress update
                    success_rate = (
                        successful_items / completed_items
                        if completed_items > 0
                        else 0.0
                    )
                    await self._emit_progress_update(
                        "progress",
                        {
                            "total_items": len(items),
                            "completed_items": completed_items,
                            "successful_items": successful_items,
                            "success_rate": success_rate,
                            "status": "processing_complete",
                        },
                    )

            console.print()  # Empty line for spacing
            console.print(
                f"[green]✅ Evaluation complete![/green] Processed {len(items)} items with {len(self.metrics)} metrics",
                style="bold",
            )
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

            # Process results and track progress
            completed_items = 0
            successful_items = 0
            for idx, eval_result in enumerate(eval_results):
                completed_items += 1
                if isinstance(eval_result, Exception):
                    result.add_error(f"item_{idx}", str(eval_result))
                else:
                    result.add_result(f"item_{idx}", eval_result)
                    successful_items += 1

            # Emit progress update
            success_rate = (
                successful_items / completed_items if completed_items > 0 else 0.0
            )
            await self._emit_progress_update(
                "progress",
                {
                    "total_items": len(items),
                    "completed_items": completed_items,
                    "successful_items": successful_items,
                    "success_rate": success_rate,
                    "status": "processing_complete",
                },
            )

        # Mark evaluation as finished
        result.finish()

        # Emit final completion event
        final_stats = result.get_summary()
        await self._emit_progress_update(
            "completed",
            {
                "total_items": len(items),
                "completed_items": len(items),
                "successful_items": len(
                    [
                        r
                        for r in result.results.values()
                        if not isinstance(r, dict) or "error" not in r
                    ]
                ),
                "success_rate": final_stats.get("success_rate", 0.0),
                "average_scores": final_stats.get("average_scores", {}),
                "execution_time": final_stats.get("execution_time", 0.0),
                "status": "completed",
                "message": "Evaluation completed successfully",
            },
        )

        # Auto-save if requested
        if auto_save:
            try:
                saved_path = result.save(format=save_format)
                console.print(f"[blue]Auto-saved results to: {saved_path}[/blue]")
                console.print()  # Empty line for spacing
            except Exception as e:
                console.print(
                    f"[yellow]Warning: Failed to auto-save results: {e}[/yellow]"
                )
                console.print()  # Empty line for spacing

        # Store run in database if requested
        if self.store_runs:
            try:
                run_id = await self._store_evaluation_run(result)
                self.database_run_id = run_id
                logger.info(f"Stored evaluation run in database with ID: {run_id}")
            except Exception as e:
                logger.warning(f"Failed to store evaluation run in database: {e}")
                # Don't break evaluation flow for storage errors

        return result

    async def _store_evaluation_run(self, result: EvaluationResult) -> str:
        """
        Store evaluation run in database using the migration utility.

        Args:
            result: EvaluationResult instance to store

        Returns:
            Database run ID (UUID string)
        """
        try:
            from ..storage.migration import migrate_from_evaluation_result

            # Store the evaluation result in database
            run_id = migrate_from_evaluation_result(
                evaluation_result=result,
                project_id=self.project_id,
                created_by=self.created_by,
                tags=self.tags,
                store_individual_items=True,  # Store individual items for detailed analysis
            )

            return run_id

        except ImportError:
            logger.warning(
                "Database storage not available - storage components not installed"
            )
            raise
        except Exception as e:
            logger.error(f"Failed to store evaluation run: {e}")
            raise

    async def _evaluate_item(
        self,
        item: Any,
        index: int,
        semaphore: asyncio.Semaphore,
        progress=None,
        task_progress=None,
    ) -> Dict[str, Any]:
        """Evaluate a single dataset item."""
        async with semaphore:
            try:
                # Run task with Langfuse tracing
                with item.run(
                    run_name=self.run_name,
                    run_metadata={**self.run_metadata, "item_index": index},
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
                                getattr(item, "expected_output", None),
                                item.input,
                            )
                            scores[metric_name] = score

                            # Log score to Langfuse
                            trace.score_trace(
                                name=metric_name,
                                value=(
                                    score
                                    if isinstance(score, (int, float, bool))
                                    else str(score)
                                ),
                                data_type=self._get_score_type(score),
                            )

                            # Update progress after each metric
                            if progress and task_progress is not None:
                                progress.update(task_progress, advance=1)

                        except Exception as e:
                            scores[metric_name] = {"error": str(e)}
                            # Still advance progress even on error
                            if progress and task_progress is not None:
                                progress.update(task_progress, advance=1)

                    return {"output": output, "scores": scores, "success": True}

            except asyncio.TimeoutError:
                raise TimeoutError(f"Evaluation timed out after {self.timeout}s")
            except Exception as e:
                raise RuntimeError(f"Task execution failed: {e}")

    async def _compute_metric(
        self, metric: Callable, output: Any, expected: Any, input_data: Any = None
    ) -> Any:
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
            kwargs = {"output": output, "expected": expected, "input_data": input_data}
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
        generate_display: Callable,
    ) -> Dict[str, Any]:
        """Evaluate a single dataset item with live status updates."""
        async with semaphore:
            try:
                # Start timing and update status to in_progress
                start_time = time.time()
                item_statuses[index]["start_time"] = start_time
                item_statuses[index]["status"] = "in_progress"
                item_statuses[index]["time"] = "[yellow]running...[/yellow]"
                live.update(generate_display())

                # Run task with Langfuse tracing
                with item.run(
                    run_name=self.run_name,
                    run_metadata={**self.run_metadata, "item_index": index},
                ) as trace:
                    # Execute task
                    output = await self.task_adapter.arun(item.input, trace)

                    # Update output in status
                    item_statuses[index]["output"] = str(output)
                    live.update(generate_display())

                    # Compute metrics
                    scores = {}
                    for metric_name, metric_func in self.metrics.items():
                        try:
                            # Update metric status to computing
                            item_statuses[index]["metrics"][
                                metric_name
                            ] = "[yellow]computing...[/yellow]"
                            live.update(generate_display())

                            score = await self._compute_metric(
                                metric_func,
                                output,
                                getattr(item, "expected_output", None),
                                item.input,
                            )
                            scores[metric_name] = score

                            # Update metric value in status
                            if isinstance(score, bool):
                                item_statuses[index]["metrics"][metric_name] = (
                                    "✓" if score else "✗"
                                )
                            elif isinstance(score, (int, float)):
                                item_statuses[index]["metrics"][
                                    metric_name
                                ] = f"{score:.3f}"
                            else:
                                item_statuses[index]["metrics"][metric_name] = str(
                                    score
                                )[:20]

                            # Log score to Langfuse
                            trace.score_trace(
                                name=metric_name,
                                value=(
                                    score
                                    if isinstance(score, (int, float, bool))
                                    else str(score)
                                ),
                                data_type=self._get_score_type(score),
                            )

                            # Update progress
                            if progress and task_progress is not None:
                                progress.update(task_progress, advance=1)

                            live.update(generate_display())

                        except Exception as e:
                            scores[metric_name] = {"error": str(e)}
                            item_statuses[index]["metrics"][
                                metric_name
                            ] = "[red]error[/red]"
                            # Still advance progress even on error
                            if progress and task_progress is not None:
                                progress.update(task_progress, advance=1)
                            live.update(generate_display())

                    # Update status to completed with timing
                    end_time = time.time()
                    item_statuses[index]["end_time"] = end_time
                    item_statuses[index]["status"] = "completed"
                    elapsed = end_time - start_time
                    item_statuses[index]["time"] = f"{elapsed:.2f}s"
                    live.update(generate_display())

                    # Emit individual item completion
                    await self._emit_progress_update(
                        "result",
                        {
                            "item_index": index,
                            "output": str(output),
                            "scores": scores,
                            "execution_time": elapsed,
                            "status": "completed",
                        },
                    )

                    return {
                        "output": output,
                        "scores": scores,
                        "success": True,
                        "time": elapsed,
                    }

            except asyncio.TimeoutError:
                end_time = time.time()
                item_statuses[index]["end_time"] = end_time
                item_statuses[index]["status"] = "error"
                item_statuses[index]["output"] = "[red]timeout[/red]"
                item_statuses[index][
                    "time"
                ] = f"[red]{end_time - start_time:.2f}s[/red]"
                for metric_name in self.metrics.keys():
                    item_statuses[index]["metrics"][metric_name] = "[red]N/A[/red]"
                live.update(generate_display())

                # Emit error event
                await self._emit_progress_update(
                    "error",
                    {
                        "item_index": index,
                        "error": "timeout",
                        "message": f"Item {index} evaluation timed out after {self.timeout}s",
                        "execution_time": end_time - start_time,
                    },
                )

                raise TimeoutError(f"Evaluation timed out after {self.timeout}s")
            except Exception as e:
                end_time = time.time()
                item_statuses[index]["end_time"] = end_time
                item_statuses[index]["status"] = "error"
                item_statuses[index]["output"] = f"[red]error: {str(e)[:30]}[/red]"
                item_statuses[index][
                    "time"
                ] = f"[red]{end_time - start_time:.2f}s[/red]"
                for metric_name in self.metrics.keys():
                    item_statuses[index]["metrics"][metric_name] = "[red]N/A[/red]"
                live.update(generate_display())

                # Emit error event
                await self._emit_progress_update(
                    "error",
                    {
                        "item_index": index,
                        "error": "execution_failed",
                        "message": f"Task execution failed: {str(e)}",
                        "execution_time": end_time - start_time,
                    },
                )

                raise RuntimeError(f"Task execution failed: {e}")

    async def _evaluate_item_with_progress_only(
        self,
        item: Any,
        index: int,
        semaphore: asyncio.Semaphore,
        progress,
        task_progress,
    ) -> Dict[str, Any]:
        """Evaluate a single dataset item with progress bar only (no table)."""
        async with semaphore:
            try:
                # Start timing
                start_time = time.time()

                # Run task with Langfuse tracing
                with item.run(
                    run_name=self.run_name,
                    run_metadata={**self.run_metadata, "item_index": index},
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
                                getattr(item, "expected_output", None),
                                item.input,
                            )
                            scores[metric_name] = score

                            # Log score to Langfuse
                            trace.score_trace(
                                name=metric_name,
                                value=(
                                    score
                                    if isinstance(score, (int, float, bool))
                                    else str(score)
                                ),
                                data_type=self._get_score_type(score),
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
                        "time": elapsed,
                    }

            except asyncio.TimeoutError:
                raise TimeoutError(f"Evaluation timed out after {self.timeout}s")
            except Exception as e:
                raise RuntimeError(f"Task execution failed: {e}")
