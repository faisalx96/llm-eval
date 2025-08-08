"""Command-line interface for llm-eval."""

import argparse
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

import click
from rich.console import Console

from .core.evaluator import Evaluator
from .models.run_models import create_tables, drop_tables
from .storage.database import get_database_manager, reset_database_manager
from .storage.migration import migrate_json_export

console = Console()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_function_from_file(file_path: str, function_name: str):
    """Load a function from a Python file."""
    try:
        spec = importlib.util.spec_from_file_location("user_module", file_path)
        if spec is None or spec.loader is None:
            raise ValueError(f"Cannot load module from {file_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if not hasattr(module, function_name):
            raise ValueError(f"Function '{function_name}' not found in {file_path}")

        return getattr(module, function_name)
    except FileNotFoundError:
        raise ValueError(f"Cannot load module from {file_path}: File not found")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Evaluate LLM tasks using Langfuse datasets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Evaluate a function from a Python file
  llm-eval --task-file my_bot.py --task-function ask_question \\
           --dataset qa-test-set --metrics exact_match,fuzzy_match

  # Use custom configuration
  llm-eval --task-file bot.py --task-function chat \\
           --dataset conversations --metrics contains \\
           --config '{"max_concurrency": 5, "timeout": 10}'

  # Save results to file
  llm-eval --task-file agent.py --task-function run \\
           --dataset test-cases --metrics exact_match \\
           --output results.json
        """,
    )

    # Required arguments
    parser.add_argument(
        "--task-file", required=True, help="Python file containing the task function"
    )
    parser.add_argument(
        "--task-function", required=True, help="Name of the function to evaluate"
    )
    parser.add_argument("--dataset", required=True, help="Name of the Langfuse dataset")
    parser.add_argument(
        "--metrics",
        required=True,
        help="Comma-separated list of metrics (e.g., 'exact_match,fuzzy_match')",
    )

    # Optional arguments
    parser.add_argument("--config", help="JSON configuration string for the evaluator")
    parser.add_argument("--output", help="File to save detailed results (JSON format)")
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Only show final summary, no progress",
    )
    parser.add_argument(
        "--no-progress", action="store_true", help="Disable progress bar"
    )

    args = parser.parse_args()

    try:
        # Load the task function
        console.print(
            f"Loading task function '{args.task_function}' from {args.task_file}"
        )
        task_function = load_function_from_file(args.task_file, args.task_function)

        # Parse metrics
        metrics = [m.strip() for m in args.metrics.split(",")]

        # Parse config if provided
        config = {}
        if args.config:
            try:
                config = json.loads(args.config)
            except json.JSONDecodeError as e:
                console.print(f"[red]Error parsing config JSON: {e}[/red]")
                sys.exit(1)

        # Create evaluator
        console.print(f"Setting up evaluation for dataset '{args.dataset}'")
        evaluator = Evaluator(
            task=task_function, dataset=args.dataset, metrics=metrics, config=config
        )

        # Run evaluation
        console.print("Starting evaluation...")
        show_progress = not args.no_progress and not args.quiet
        results = evaluator.run(show_progress=show_progress)

        # Show results
        if args.quiet:
            # Just print key metrics
            console.print(f"Success Rate: {results.success_rate:.1%}")
            for metric in metrics:
                stats = results.get_metric_stats(metric)
                console.print(f"{metric}: {stats['mean']:.3f}")
        else:
            # Full summary
            results.print_summary()

        # Save detailed results if requested
        if args.output:
            output_path = Path(args.output)
            with open(output_path, "w") as f:
                json.dump(results.to_dict(), f, indent=2, default=str)
            console.print(f"Detailed results saved to {output_path}")

        # Exit with error code if success rate is too low
        if results.success_rate < 0.5:
            console.print("[yellow]Warning: Success rate below 50%[/yellow]")
            sys.exit(2)

    except KeyboardInterrupt:
        console.print("\n[yellow]Evaluation interrupted by user[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


# Database management CLI commands


@click.group()
def db():
    """Database management commands."""
    pass


@db.command()
@click.option("--database-url", help="Database connection URL")
@click.option("--force", is_flag=True, help="Force recreate existing tables")
def init(database_url, force):
    """Initialize the LLM-Eval database."""
    try:
        if database_url:
            reset_database_manager()
            db_manager = get_database_manager(database_url)
        else:
            db_manager = get_database_manager()

        if force:
            console.print("Dropping existing tables...")
            drop_tables(db_manager.engine)

        console.print("Creating database tables...")
        create_tables(db_manager.engine)

        # Verify setup
        health = db_manager.health_check()
        if health["status"] == "healthy":
            console.print("✅ Database initialized successfully!")
            console.print(f"Database: {health['database_url']}")
            console.print("Tables created with proper indexes and constraints.")
        else:
            console.print(f"❌ Database health check failed: {health.get('error')}")
            sys.exit(1)

    except Exception as e:
        console.print(f"❌ Failed to initialize database: {e}")
        sys.exit(1)


@db.command()
@click.option("--database-url", help="Database connection URL")
def health(database_url):
    """Check database health and connectivity."""
    try:
        if database_url:
            reset_database_manager()
            db_manager = get_database_manager(database_url)
        else:
            db_manager = get_database_manager()

        health = db_manager.health_check()

        if health["status"] == "healthy":
            console.print("✅ Database is healthy")
            console.print(f"Database: {health['database_url']}")

            stats = health.get("statistics", {})
            if stats:
                console.print(f"Runs: {stats.get('run_count', 0)}")
                console.print(f"Items: {stats.get('item_count', 0)}")
                console.print(f"Metrics: {stats.get('metric_count', 0)}")

                if stats.get("latest_run_date"):
                    console.print(
                        f"Latest run: {stats.get('latest_run_name')} ({stats.get('latest_run_date')})"
                    )
        else:
            console.print(f"❌ Database is unhealthy: {health.get('error')}")
            sys.exit(1)

    except Exception as e:
        console.print(f"❌ Health check failed: {e}")
        sys.exit(1)


@db.command()
@click.argument("json_file")
@click.option("--project-id", help="Project ID for the migrated run")
@click.option("--created-by", help="User who created the run")
@click.option("--tags", help="Comma-separated list of tags")
def migrate(json_file, project_id, created_by, tags):
    """Migrate evaluation results from JSON export file."""
    try:
        json_path = Path(json_file)
        if not json_path.exists():
            console.print(f"❌ JSON file not found: {json_file}")
            sys.exit(1)

        tag_list = [tag.strip() for tag in tags.split(",")] if tags else None

        console.print(f"Migrating {json_file} to database...")
        run_id = migrate_json_export(
            str(json_path), project_id=project_id, created_by=created_by, tags=tag_list
        )

        console.print(f"✅ Successfully migrated to run ID: {run_id}")

    except Exception as e:
        console.print(f"❌ Migration failed: {e}")
        sys.exit(1)


@db.command()
@click.option("--database-url", help="Database connection URL")
@click.option("--limit", default=10, help="Number of recent runs to show")
def list(database_url, limit):
    """List recent evaluation runs."""
    try:
        if database_url:
            reset_database_manager()
            get_database_manager(database_url)

        from .storage.run_repository import RunRepository

        repo = RunRepository()
        runs = repo.list_runs(limit=limit, order_by="created_at", descending=True)

        if not runs:
            console.print("No evaluation runs found.")
            return

        console.print(
            f"Recent evaluation runs (showing {len(runs)} of {repo.count_runs()}):"
        )
        console.print()

        for run in runs:
            status_icon = (
                "✅"
                if run.status == "completed"
                else "⏳" if run.status == "running" else "❌"
            )
            console.print(f"{status_icon} {run.name}")
            console.print(f"   ID: {run.id}")
            console.print(f"   Dataset: {run.dataset_name}")
            console.print(f"   Created: {run.created_at}")
            if run.success_rate is not None:
                console.print(f"   Success Rate: {run.success_rate:.1%}")
            console.print(
                f"   Items: {run.total_items} total, {run.successful_items} successful"
            )
            console.print()

    except Exception as e:
        console.print(f"❌ Failed to list runs: {e}")
        sys.exit(1)


# Run management CLI commands


@click.group()
def runs():
    """Run management commands."""
    pass


@runs.command()
@click.option("--project-id", help="Filter by project ID")
@click.option("--dataset", help="Filter by dataset name")
@click.option("--model", help="Filter by model name")
@click.option("--status", help="Filter by status (running, completed, failed)")
@click.option("--created-by", help="Filter by creator")
@click.option("--tags", help="Filter by tags (comma-separated)")
@click.option("--limit", default=20, help="Number of runs to show")
@click.option(
    "--format",
    "output_format",
    default="table",
    type=click.Choice(["table", "json", "csv"]),
    help="Output format",
)
def list(project_id, dataset, model, status, created_by, tags, limit, output_format):
    """List evaluation runs with filtering options."""
    try:
        from .storage.run_repository import RunRepository

        repo = RunRepository()

        # Parse tags
        tag_list = [tag.strip() for tag in tags.split(",")] if tags else None

        runs = repo.list_runs(
            project_id=project_id,
            dataset_name=dataset,
            model_name=model,
            status=status,
            created_by=created_by,
            tags=tag_list,
            limit=limit,
            order_by="created_at",
            descending=True,
        )

        if not runs:
            console.print("No evaluation runs found matching criteria.")
            return

        if output_format == "json":
            import json

            output = [run.to_dict() for run in runs]
            console.print(json.dumps(output, indent=2, default=str))
        elif output_format == "csv":
            import csv
            import sys

            writer = csv.writer(sys.stdout)
            # Header
            writer.writerow(
                [
                    "ID",
                    "Name",
                    "Dataset",
                    "Model",
                    "Status",
                    "Success Rate",
                    "Duration",
                    "Created",
                ]
            )

            # Data
            for run in runs:
                writer.writerow(
                    [
                        str(run.id),
                        run.name,
                        run.dataset_name,
                        run.model_name or "",
                        run.status,
                        (
                            f"{run.success_rate:.1%}"
                            if run.success_rate is not None
                            else ""
                        ),
                        f"{run.duration_seconds:.1f}s" if run.duration_seconds else "",
                        run.created_at.isoformat() if run.created_at else "",
                    ]
                )
        else:  # table format
            from rich.table import Table

            table = Table(
                title=f"Evaluation Runs (showing {len(runs)} of {repo.count_runs()})"
            )
            table.add_column("Name", style="cyan")
            table.add_column("Dataset", style="green")
            table.add_column("Model", style="blue")
            table.add_column("Status", style="yellow")
            table.add_column("Success Rate", justify="right")
            table.add_column("Duration", justify="right")
            table.add_column("Created", style="dim")

            for run in runs:
                status_color = {
                    "completed": "green",
                    "running": "yellow",
                    "failed": "red",
                    "cancelled": "dim",
                }.get(run.status, "white")

                table.add_row(
                    run.name,
                    run.dataset_name,
                    run.model_name or "-",
                    f"[{status_color}]{run.status}[/{status_color}]",
                    f"{run.success_rate:.1%}" if run.success_rate is not None else "-",
                    f"{run.duration_seconds:.1f}s" if run.duration_seconds else "-",
                    (
                        run.created_at.strftime("%Y-%m-%d %H:%M")
                        if run.created_at
                        else "-"
                    ),
                )

            console.print(table)

    except Exception as e:
        console.print(f"❌ Failed to list runs: {e}")
        sys.exit(1)


@runs.command()
@click.argument("run_id")
@click.option(
    "--format",
    "output_format",
    default="detailed",
    type=click.Choice(["detailed", "json", "summary"]),
    help="Output format",
)
def show(run_id, output_format):
    """Show detailed information about a specific run."""
    try:
        from .storage.run_repository import RunRepository

        repo = RunRepository()
        run = repo.get_run(run_id)

        if not run:
            console.print(f"❌ Run not found: {run_id}")
            sys.exit(1)

        if output_format == "json":
            import json

            console.print(json.dumps(run.to_dict(), indent=2, default=str))
        elif output_format == "summary":
            console.print(f"Run: {run.name}")
            console.print(f"Status: {run.status}")
            console.print(f"Dataset: {run.dataset_name}")
            if run.model_name:
                console.print(f"Model: {run.model_name}")
            if run.success_rate is not None:
                console.print(f"Success Rate: {run.success_rate:.1%}")
            console.print(
                f"Items: {run.total_items} total, {run.successful_items} successful, {run.failed_items} failed"
            )
            if run.duration_seconds:
                console.print(f"Duration: {run.duration_seconds:.1f}s")
        else:  # detailed format
            from rich.columns import Columns
            from rich.panel import Panel

            # Basic info panel
            basic_info = [
                f"[bold]Name:[/bold] {run.name}",
                f"[bold]ID:[/bold] {run.id}",
                f"[bold]Status:[/bold] {run.status}",
                f"[bold]Dataset:[/bold] {run.dataset_name}",
            ]

            if run.model_name:
                basic_info.append(f"[bold]Model:[/bold] {run.model_name}")
            if run.model_version:
                basic_info.append(f"[bold]Model Version:[/bold] {run.model_version}")
            if run.task_type:
                basic_info.append(f"[bold]Task Type:[/bold] {run.task_type}")

            # Performance panel
            perf_info = []
            if run.success_rate is not None:
                perf_info.append(f"[bold]Success Rate:[/bold] {run.success_rate:.1%}")
            perf_info.extend(
                [
                    f"[bold]Total Items:[/bold] {run.total_items}",
                    f"[bold]Successful:[/bold] {run.successful_items}",
                    f"[bold]Failed:[/bold] {run.failed_items}",
                ]
            )

            if run.duration_seconds:
                perf_info.append(f"[bold]Duration:[/bold] {run.duration_seconds:.1f}s")
            if run.avg_response_time:
                perf_info.append(
                    f"[bold]Avg Response Time:[/bold] {run.avg_response_time:.2f}s"
                )

            # Timing panel
            timing_info = []
            if run.created_at:
                timing_info.append(f"[bold]Created:[/bold] {run.created_at}")
            if run.started_at:
                timing_info.append(f"[bold]Started:[/bold] {run.started_at}")
            if run.completed_at:
                timing_info.append(f"[bold]Completed:[/bold] {run.completed_at}")

            # Metadata panel
            meta_info = []
            if run.created_by:
                meta_info.append(f"[bold]Created By:[/bold] {run.created_by}")
            if run.project_id:
                meta_info.append(f"[bold]Project:[/bold] {run.project_id}")
            if run.tags:
                meta_info.append(f"[bold]Tags:[/bold] {', '.join(run.tags)}")

            # Metrics panel
            metrics = repo.get_run_metrics(run_id)
            metric_info = []
            if metrics:
                metric_info.append("[bold]Metrics:[/bold]")
                for metric in metrics:
                    metric_info.append(
                        f"  {metric.metric_name}: {metric.mean_score:.3f} (±{metric.std_dev:.3f})"
                        if metric.std_dev
                        else f"  {metric.metric_name}: {metric.mean_score:.3f}"
                    )
            else:
                metric_info.append("[bold]Metrics:[/bold] None computed")

            # Create panels
            panels = [
                Panel(
                    "\n".join(basic_info),
                    title="Basic Information",
                    border_style="blue",
                ),
                Panel("\n".join(perf_info), title="Performance", border_style="green"),
            ]

            if timing_info:
                panels.append(
                    Panel("\n".join(timing_info), title="Timing", border_style="yellow")
                )

            if meta_info:
                panels.append(
                    Panel("\n".join(meta_info), title="Metadata", border_style="cyan")
                )

            if metric_info:
                panels.append(
                    Panel(
                        "\n".join(metric_info), title="Metrics", border_style="magenta"
                    )
                )

            # Display in columns
            console.print(Columns(panels, equal=True, expand=True))

    except Exception as e:
        console.print(f"❌ Failed to show run: {e}")
        sys.exit(1)


@runs.command()
@click.argument("query")
@click.option("--project-id", help="Filter by project ID")
@click.option("--limit", default=10, help="Number of results to show")
def search(query, project_id, limit):
    """Search evaluation runs using natural language queries."""
    try:
        from .core.search import RunSearchEngine

        search_engine = RunSearchEngine()
        results = search_engine.search_runs(
            query=query, project_id=project_id, limit=limit
        )

        if "error" in results:
            console.print(f"❌ Search failed: {results['error']}")
            sys.exit(1)

        runs = results.get("runs", [])
        if not runs:
            console.print(f"No runs found matching query: '{query}'")
            return

        console.print(f"Found {len(runs)} runs matching '{query}':")
        console.print()

        for run_data in runs:
            status_icon = (
                "✅"
                if run_data["status"] == "completed"
                else "⏳" if run_data["status"] == "running" else "❌"
            )
            console.print(f"{status_icon} {run_data['name']}")
            console.print(f"   Dataset: {run_data['dataset_name']}")
            console.print(f"   Created: {run_data['created_at']}")
            if run_data.get("success_rate") is not None:
                console.print(f"   Success Rate: {run_data['success_rate']:.1%}")
            console.print()

    except Exception as e:
        console.print(f"❌ Search failed: {e}")
        sys.exit(1)


@runs.command()
@click.argument("run1_id")
@click.argument("run2_id")
@click.option(
    "--format",
    "output_format",
    default="detailed",
    type=click.Choice(["detailed", "json", "summary"]),
    help="Output format",
)
def compare(run1_id, run2_id, output_format):
    """Compare two evaluation runs."""
    try:
        from .core.search import RunSearchEngine

        search_engine = RunSearchEngine()
        comparison = search_engine.get_run_comparison(run1_id, run2_id)

        if "error" in comparison:
            console.print(f"❌ Comparison failed: {comparison['error']}")
            sys.exit(1)

        comp_data = comparison["comparison"]

        if output_format == "json":
            import json

            console.print(json.dumps(comp_data, indent=2, default=str))
        elif output_format == "summary":
            summary = comp_data["summary"]
            console.print(
                f"Run 1: {summary['run1_name']} (Success: {summary['run1_success_rate']:.1%})"
            )
            console.print(
                f"Run 2: {summary['run2_name']} (Success: {summary['run2_success_rate']:.1%})"
            )
            console.print(f"Success Rate Delta: {summary['success_rate_delta']:+.1%}")
            if summary.get("duration_delta"):
                console.print(f"Duration Delta: {summary['duration_delta']:+.1f}s")
        else:  # detailed format
            from rich.table import Table

            summary = comp_data["summary"]
            console.print(
                f"[bold]Comparison: {summary['run1_name']} vs {summary['run2_name']}[/bold]"
            )
            console.print()

            # Summary table
            summary_table = Table(title="Overall Comparison")
            summary_table.add_column("Metric", style="cyan")
            summary_table.add_column("Run 1", justify="right")
            summary_table.add_column("Run 2", justify="right")
            summary_table.add_column("Delta", justify="right")

            summary_table.add_row(
                "Success Rate",
                f"{summary['run1_success_rate']:.1%}",
                f"{summary['run2_success_rate']:.1%}",
                f"{summary['success_rate_delta']:+.1%}",
            )

            if summary.get("run1_duration") and summary.get("run2_duration"):
                summary_table.add_row(
                    "Duration",
                    f"{summary['run1_duration']:.1f}s",
                    f"{summary['run2_duration']:.1f}s",
                    f"{summary['duration_delta']:+.1f}s",
                )

            console.print(summary_table)
            console.print()

            # Metric comparison table
            metric_comparisons = comp_data.get("metric_comparisons", {})
            if metric_comparisons:
                metric_table = Table(title="Metric Comparison")
                metric_table.add_column("Metric", style="cyan")
                metric_table.add_column("Run 1", justify="right")
                metric_table.add_column("Run 2", justify="right")
                metric_table.add_column("Delta", justify="right")
                metric_table.add_column("Status")

                for metric_name, metric_data in metric_comparisons.items():
                    run1_val = metric_data.get("run1_mean")
                    run2_val = metric_data.get("run2_mean")
                    delta = metric_data.get("delta", 0)

                    run1_str = f"{run1_val:.3f}" if run1_val is not None else "N/A"
                    run2_str = f"{run2_val:.3f}" if run2_val is not None else "N/A"
                    delta_str = f"{delta:+.3f}" if delta != 0 else "0.000"

                    # Status based on availability and improvement
                    if not metric_data.get("run1_available"):
                        status = "[dim]Missing in Run 1[/dim]"
                    elif not metric_data.get("run2_available"):
                        status = "[dim]Missing in Run 2[/dim]"
                    elif delta > 0.01:
                        status = "[green]Improved[/green]"
                    elif delta < -0.01:
                        status = "[red]Degraded[/red]"
                    else:
                        status = "[yellow]No Change[/yellow]"

                    metric_table.add_row(
                        metric_name, run1_str, run2_str, delta_str, status
                    )

                console.print(metric_table)

    except Exception as e:
        console.print(f"❌ Comparison failed: {e}")
        sys.exit(1)


@runs.command()
@click.argument("run_id")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt")
def delete(run_id, confirm):
    """Delete an evaluation run and all associated data."""
    try:
        from .storage.run_repository import RunRepository

        repo = RunRepository()
        run = repo.get_run(run_id)

        if not run:
            console.print(f"❌ Run not found: {run_id}")
            sys.exit(1)

        if not confirm:
            import click

            if not click.confirm(
                f"Are you sure you want to delete run '{run.name}' ({run_id})? This cannot be undone."
            ):
                console.print("Operation cancelled.")
                return

        success = repo.delete_run(run_id)

        if success:
            console.print(f"✅ Successfully deleted run: {run.name}")
        else:
            console.print(f"❌ Failed to delete run: {run_id}")
            sys.exit(1)

    except Exception as e:
        console.print(f"❌ Delete failed: {e}")
        sys.exit(1)


@click.group()
def cli():
    """LLM-Eval: Local UI-first evaluation platform for LLMs."""
    pass


@cli.command()
@click.option("--docker/--no-docker", default=True, help="Use Docker for setup")
@click.option("--port", default=8000, help="API port")
@click.option("--frontend-port", default=3000, help="Frontend port")
def start(docker, port, frontend_port):
    """Start LLM-Eval locally (one-command setup)."""
    try:
        if docker:
            # Check for docker-compose
            if not shutil.which("docker-compose"):
                console.print("[red]❌ docker-compose not found.[/red]")
                console.print(
                    "Please install Docker Desktop from https://www.docker.com/products/docker-desktop"
                )
                sys.exit(1)

            # Check for .env file
            env_path = Path(".env")
            if not env_path.exists():
                console.print("[yellow]📝 Creating .env from template...[/yellow]")
                env_example = Path(".env.example")
                if env_example.exists():
                    shutil.copy(".env.example", ".env")
                    console.print(
                        "[yellow]⚠️  Please add your Langfuse credentials to .env file[/yellow]"
                    )
                    console.print("Then run 'llm-eval start' again.")
                    sys.exit(1)
                else:
                    console.print("[red]❌ .env.example not found[/red]")
                    sys.exit(1)

            # Start Docker containers
            console.print("[green]🐳 Starting Docker containers...[/green]")
            try:
                subprocess.run(["docker-compose", "up", "-d"], check=True)
                console.print("[green]✅ Docker containers started![/green]")
                console.print(f"")
                console.print(f"🎉 LLM-Eval is running!")
                console.print(
                    f"📊 Open [bold cyan]http://localhost:{frontend_port}[/bold cyan] in your browser"
                )
                console.print(f"")
                console.print(f"To stop: docker-compose down")
                console.print(f"To view logs: docker-compose logs -f")
            except subprocess.CalledProcessError as e:
                console.print(f"[red]❌ Failed to start Docker containers: {e}[/red]")
                sys.exit(1)
        else:
            # Manual start (for development)
            console.print(
                "[yellow]Starting in development mode (no Docker)...[/yellow]"
            )
            console.print(f"")
            console.print("Run these commands in separate terminals:")
            console.print(f"1. API:      python -m llm_eval.api.main")
            console.print(f"2. Frontend: cd frontend && npm run dev")
            console.print(f"")
            console.print(
                f"Then open [bold cyan]http://localhost:{frontend_port}[/bold cyan]"
            )

    except KeyboardInterrupt:
        console.print("\n[yellow]Startup interrupted[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        sys.exit(1)


@cli.command()
def stop():
    """Stop running LLM-Eval containers."""
    try:
        if shutil.which("docker-compose"):
            console.print("[yellow]Stopping Docker containers...[/yellow]")
            subprocess.run(["docker-compose", "down"], check=True)
            console.print("[green]✅ LLM-Eval stopped[/green]")
        else:
            console.print(
                "[yellow]Docker not found. If running manually, stop with Ctrl+C[/yellow]"
            )
    except subprocess.CalledProcessError as e:
        console.print(f"[red]❌ Failed to stop containers: {e}[/red]")
        sys.exit(1)


@cli.command()
def status():
    """Check status of LLM-Eval services."""
    try:
        import requests

        # Check API
        try:
            api_response = requests.get("http://localhost:8000/api/health", timeout=2)
            if api_response.status_code == 200:
                console.print(
                    "[green]✅ API is running at http://localhost:8000[/green]"
                )
            else:
                console.print(
                    "[yellow]⚠️  API returned status {api_response.status_code}[/yellow]"
                )
        except requests.exceptions.RequestException:
            console.print("[red]❌ API is not running[/red]")

        # Check Frontend
        try:
            frontend_response = requests.get("http://localhost:3000", timeout=2)
            if frontend_response.status_code == 200:
                console.print(
                    "[green]✅ Frontend is running at http://localhost:3000[/green]"
                )
            else:
                console.print(
                    "[yellow]⚠️  Frontend returned status {frontend_response.status_code}[/yellow]"
                )
        except requests.exceptions.RequestException:
            console.print("[red]❌ Frontend is not running[/red]")

        # Check Docker
        if shutil.which("docker-compose"):
            result = subprocess.run(
                ["docker-compose", "ps"], capture_output=True, text=True
            )
            if result.returncode == 0:
                console.print("\n[bold]Docker containers:[/bold]")
                console.print(result.stdout)

    except Exception as e:
        console.print(f"[red]❌ Error checking status: {e}[/red]")
        sys.exit(1)


# Add existing command groups
cli.add_command(db)
cli.add_command(runs)


# Legacy support for direct evaluation
@cli.command(name="evaluate")
@click.option(
    "--task-file", required=True, help="Python file containing the task function"
)
@click.option("--task-function", required=True, help="Name of the function to evaluate")
@click.option("--dataset", required=True, help="Name of the Langfuse dataset")
@click.option("--metrics", required=True, help="Comma-separated list of metrics")
@click.option("--config", help="JSON configuration string")
@click.option("--output", help="File to save results")
@click.option("--quiet", "-q", is_flag=True, help="Only show summary")
def evaluate(task_file, task_function, dataset, metrics, config, output, quiet):
    """Run an evaluation (legacy CLI interface)."""
    # Call the original main() with constructed argv
    original_argv = sys.argv
    sys.argv = [
        "llm-eval",
        "--task-file",
        task_file,
        "--task-function",
        task_function,
        "--dataset",
        dataset,
        "--metrics",
        metrics,
    ]
    if config:
        sys.argv.extend(["--config", config])
    if output:
        sys.argv.extend(["--output", output])
    if quiet:
        sys.argv.append("--quiet")

    try:
        main()
    finally:
        sys.argv = original_argv


# Main entry point
def cli_main():
    """Main CLI entry point."""
    # If no arguments or help, show click CLI
    if len(sys.argv) == 1 or (
        len(sys.argv) > 1
        and sys.argv[1]
        in ["--help", "-h", "start", "stop", "status", "db", "runs", "evaluate"]
    ):
        cli()
    else:
        # Legacy argparse mode for backward compatibility
        main()


if __name__ == "__main__":
    cli_main()
