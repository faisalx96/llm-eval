"""qym run commands."""

import asyncio
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any, List, Optional, Union

import typer

from ._exit_codes import ExitCode
from ._output import is_json_mode, output, output_error, err_console, status
from ._platform_api import PlatformAPIClient, PlatformAPIError
from ._legacy import load_function_from_file, load_multi_run_specs
from ..utils.env import get_platform_url_env

run_app = typer.Typer(help="Manage evaluation runs.")


# ── qym run create ──────────────────────────────────────────


@run_app.command("create")
def run_create(
    task_file: Optional[str] = typer.Option(None, "--task-file", help="Python file containing the task function"),
    task_function: Optional[str] = typer.Option(None, "--task-function", help="Name of the function to evaluate"),
    dataset: Optional[str] = typer.Option(None, "--dataset", help="Langfuse dataset name"),
    dataset_csv: Optional[str] = typer.Option(None, "--dataset-csv", help="Path to a local CSV dataset file"),
    metrics: Optional[str] = typer.Option(None, "--metrics", help="Comma-separated metric names"),
    csv_input_col: str = typer.Option("input", "--csv-input-col", help="CSV column for input"),
    csv_expected_col: str = typer.Option("expected_output", "--csv-expected-col", help="CSV column for expected output"),
    csv_id_col: Optional[str] = typer.Option(None, "--csv-id-col", help="CSV column for item ID"),
    csv_metadata_cols: Optional[str] = typer.Option(None, "--csv-metadata-cols", help="Comma-separated CSV metadata columns"),
    model: Optional[str] = typer.Option(None, "--model", help="Model name(s), comma-separated"),
    task_name: Optional[str] = typer.Option(None, "--task-name", help="Override auto-derived task name"),
    config_json: Optional[str] = typer.Option(None, "--config", help="JSON configuration string"),
    no_ui: bool = typer.Option(False, "--no-ui", help="Disable local web UI"),
    ui_port: int = typer.Option(0, "--ui-port", help="Port for local web UI (0 for auto)"),
    no_open: bool = typer.Option(False, "--no-open", help="Do not open browser automatically"),
    output_file: Optional[str] = typer.Option(None, "--output", help="Save results to JSON file"),
    platform_url: Optional[str] = typer.Option(None, "--platform-url", help="Override platform base URL"),
    platform_api_key: Optional[str] = typer.Option(None, "--platform-api-key", help="Platform API key"),
    live_mode: Optional[str] = typer.Option(None, "--live-mode", hidden=True, help="[DEPRECATED]"),
    resume_from: Optional[str] = typer.Option(None, "--resume-from", "--run-file", help="Checkpoint CSV to resume from"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Only show final summary"),
    no_progress: bool = typer.Option(False, "--no-progress", help="Disable progress bar"),
    runs_config: Optional[str] = typer.Option(None, "--runs-config", help="Multi-run YAML/JSON config"),
    git_branch: Optional[str] = typer.Option(None, "--git-branch", help="Override auto-detected git branch"),
    git_commit: Optional[str] = typer.Option(None, "--git-commit", help="Override auto-detected git commit hash"),
) -> None:
    """Execute an LLM evaluation run."""
    from ..core.evaluator import Evaluator, _graceful_interrupt_signals
    from ..core.multi_runner import MultiModelRunner
    from ..core.dataset import CsvDataset
    from ..core.checkpoint import load_checkpoint_state
    from ..utils.text import arabic_display

    is_multi_run = bool(runs_config)

    if is_multi_run and model:
        status("Ignoring --model because --runs-config is provided.")

    # Normalize model arg
    model_arg: Optional[Union[str, List[str]]] = None
    if model:
        from ..core.config import EvaluatorConfig
        parsed = EvaluatorConfig.normalize_models(model)
        if parsed:
            model_arg = parsed if len(parsed) > 1 else parsed[0]

    # ── Multi-run mode ──
    if is_multi_run:
        config_path = Path(runs_config).expanduser()
        if not config_path.exists():
            output_error("not_found", f"Runs config not found: {config_path}")
            raise typer.Exit(code=ExitCode.FAILURE)
        try:
            run_specs = load_multi_run_specs(config_path)
        except Exception as exc:
            output_error("failure", f"Failed to load runs config: {exc}")
            raise typer.Exit(code=ExitCode.FAILURE)
        if not run_specs:
            output_error("failure", "Runs config is empty")
            raise typer.Exit(code=ExitCode.FAILURE)

        show_tui = not quiet and not no_progress and not no_ui
        runner = MultiModelRunner(run_specs, console=err_console)
        try:
            with _graceful_interrupt_signals():
                results = asyncio.run(
                    runner.arun(show_tui=show_tui, auto_save=True, save_format="csv")
                )
        except RuntimeError as exc:
            output_error("failure", str(exc))
            raise typer.Exit(code=ExitCode.FAILURE)

        if is_json_mode():
            output([res.to_dict() for res in results])
        else:
            runner.print_summary(results)
            runner.print_saved_paths(results)

        interrupted_runs = [res for res in results if getattr(res, "interrupted", False)]
        if interrupted_runs:
            for res in interrupted_runs:
                resume_path = getattr(res, "last_saved_path", None)
                if resume_path:
                    err_console.print(f"[yellow]Partial results saved to {resume_path}[/yellow]")
                    err_console.print(f"[yellow]Resume with: qym run create --resume-from {resume_path} ...[/yellow]")
            raise typer.Exit(code=ExitCode.FAILURE)

        for spec, result in zip(run_specs, results):
            if spec.output_path:
                spec.output_path.parent.mkdir(parents=True, exist_ok=True)
                suffix = spec.output_path.suffix.lower()
                format_hint = "csv" if suffix == ".csv" else "json"
                saved_path = result.save(format=format_hint, filepath=str(spec.output_path))
                status(f"Saved {spec.run_name} results to {saved_path}")

        raise typer.Exit(code=ExitCode.SUCCESS)

    # ── Single-run mode ──
    missing_flags = []
    if not task_file:
        missing_flags.append("--task-file")
    if not task_function:
        missing_flags.append("--task-function")
    if not dataset and not dataset_csv:
        missing_flags.append("--dataset or --dataset-csv")
    if not metrics:
        missing_flags.append("--metrics")
    if missing_flags:
        output_error("usage_error", f"Missing required arguments: {', '.join(missing_flags)}")
        raise typer.Exit(code=ExitCode.USAGE_ERROR)

    if bool(dataset) == bool(dataset_csv):
        output_error("usage_error", "Provide exactly one of --dataset (Langfuse) or --dataset-csv (CSV).")
        raise typer.Exit(code=ExitCode.USAGE_ERROR)

    try:
        status(f"Loading task function '{task_function}' from {task_file}")
        fn = load_function_from_file(task_file, task_function)

        metrics_list = [m.strip() for m in metrics.split(",")]

        config: dict[str, Any] = {}
        if config_json:
            try:
                config = json.loads(config_json)
            except json.JSONDecodeError as e:
                output_error("usage_error", f"Invalid config JSON: {e}")
                raise typer.Exit(code=ExitCode.USAGE_ERROR)

        if resume_from:
            config["resume_from"] = resume_from
            if "run_name" not in config:
                resume_state = load_checkpoint_state(resume_from)
                if resume_state and resume_state.run_name:
                    config["run_name"] = resume_state.run_name

        # Record CLI invocation
        try:
            argv_str = " ".join(shlex.quote(a) for a in sys.argv[1:])
            config["cli_invocation"] = f"qym {argv_str}".strip()
        except Exception:
            pass

        config["ui_port"] = ui_port
        if task_name:
            config["task_name"] = task_name
        if platform_url:
            config["platform_url"] = platform_url
        if platform_api_key:
            config["platform_api_key"] = platform_api_key
        if git_branch:
            config["git_branch"] = git_branch
        if git_commit:
            config["git_commit"] = git_commit
        if live_mode:
            config["live_mode"] = live_mode
        else:
            purl = platform_url or get_platform_url_env()
            pkey = platform_api_key or os.getenv("QYM_API_KEY")
            if purl and pkey:
                config["live_mode"] = "auto"

        # Build dataset
        dataset_obj: Any = dataset
        if dataset_csv:
            md_cols: List[str] = []
            if csv_metadata_cols:
                md_cols = [c.strip() for c in csv_metadata_cols.split(",") if c.strip()]
            expected_col = csv_expected_col if csv_expected_col is not None else "expected_output"
            if expected_col.strip() == "":
                expected_col = None
            dataset_obj = CsvDataset(
                dataset_csv,
                input_col=csv_input_col,
                expected_col=expected_col,
                id_col=csv_id_col if csv_id_col else None,
                metadata_cols=md_cols,
            )

        dataset_label = getattr(dataset_obj, "name", None) or str(dataset_obj)
        status(f"Setting up evaluation for dataset '{dataset_label}'")

        evaluator = Evaluator(
            task=fn,
            dataset=dataset_obj,
            metrics=metrics_list,
            config=config,
            model=model_arg,
        )

        status("Starting evaluation...")
        show_progress = not no_progress and not quiet
        show_table = not no_ui
        raw_results = evaluator.run(show_progress=show_progress, show_table=show_table)
        run_results = raw_results if isinstance(raw_results, list) else [raw_results]

        # Output results
        if is_json_mode():
            if len(run_results) == 1:
                output(run_results[0].to_dict())
            else:
                output([res.to_dict() for res in run_results])
        elif quiet:
            for res in run_results:
                err_console.print(f"{res.run_name} Success Rate: {res.success_rate:.1%}")
                for metric_name in metrics_list:
                    stats = res.get_metric_stats(metric_name)
                    err_console.print(f"{res.run_name} {metric_name}: {stats['mean']:.3f}")
        else:
            for res in run_results:
                res.print_summary()

        # Save if requested
        if output_file:
            if len(run_results) > 1:
                err_console.print("[yellow]--output supports only single-model runs. Use --runs-config or per-run outputs.[/yellow]")
            else:
                output_path = Path(output_file)
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(run_results[0].to_dict(), f, indent=2, default=str, ensure_ascii=False)
                status(f"Detailed results saved to {output_path}")

        # Browser open
        primary_result = run_results[0]
        if getattr(primary_result, "interrupted", False):
            resume_path = getattr(primary_result, "last_saved_path", None)
            if resume_path:
                err_console.print(f"[yellow]Partial results saved to {resume_path}[/yellow]")
                err_console.print(f"[yellow]Resume with: qym run create --resume-from {resume_path} ...[/yellow]")
            raise typer.Exit(code=ExitCode.FAILURE)

        try:
            if getattr(primary_result, "html_url", None) and not no_open and not quiet and not is_json_mode():
                err_console.print(f"\n[blue]UI:[/blue] {primary_result.html_url}")
                import webbrowser
                webbrowser.open(primary_result.html_url)
        except Exception:
            pass

        low_success = [res for res in run_results if res.success_rate < 0.5]
        if low_success:
            names = ", ".join(res.run_name for res in low_success)
            err_console.print(f"[yellow]Warning: Success rate below 50% for runs: {names}[/yellow]")
            raise typer.Exit(code=2)

    except typer.Exit:
        raise
    except KeyboardInterrupt:
        err_console.print("\n[yellow]Evaluation interrupted by user[/yellow]")
        raise typer.Exit(code=ExitCode.FAILURE)
    except Exception as e:
        output_error("failure", str(e))
        raise typer.Exit(code=ExitCode.FAILURE)


# ── qym run tasks ───────────────────────────────────────────


@run_app.command("tasks")
def run_tasks() -> None:
    """List distinct task names from the platform."""
    client = PlatformAPIClient()

    try:
        data = client.list_runs()
    except PlatformAPIError as exc:
        output_error(
            error_type="connection_failed" if exc.status_code == 0 else "failure",
            message=exc.detail,
            suggestion=exc.suggestion,
        )
        raise typer.Exit(code=exc.exit_code)

    tasks = sorted(data.get("tasks", {}).keys())

    if is_json_mode():
        output({"tasks": tasks, "total": len(tasks)})
    else:
        if not tasks:
            err_console.print("[dim]No tasks found.[/dim]")
            return
        for t in tasks:
            err_console.print(t)


# ── qym run list ────────────────────────────────────────────


@run_app.command("list")
def run_list(
    limit: int = typer.Option(50, "--limit", help="Max runs to return"),
    task: Optional[str] = typer.Option(None, "--task", help="Filter by task name"),
    model_filter: Optional[str] = typer.Option(None, "--model", help="Filter by model name"),
    status_filter: Optional[str] = typer.Option(None, "--status", help="Filter by status"),
) -> None:
    """List recent evaluation runs from the platform."""
    client = PlatformAPIClient()

    try:
        data = client.list_runs()
    except PlatformAPIError as exc:
        output_error(
            error_type="connection_failed" if exc.status_code == 0 else "failure",
            message=exc.detail,
            suggestion=exc.suggestion,
        )
        raise typer.Exit(code=exc.exit_code)

    # Flatten the nested {tasks: {task_name: {model: [runs]}}} structure
    flat_runs: list[dict] = []
    tasks = data.get("tasks", {})
    for task_name, models in tasks.items():
        if task and task.lower() not in task_name.lower():
            continue
        for model_name, runs in models.items():
            if model_filter and model_filter.lower() not in model_name.lower():
                continue
            for run_summary in runs:
                if status_filter and run_summary.get("status", "").lower() != status_filter.lower():
                    continue
                flat_runs.append(run_summary)

    # Sort by timestamp descending, apply limit
    flat_runs.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    flat_runs = flat_runs[:limit]

    if is_json_mode():
        output({"runs": flat_runs, "total": len(flat_runs)})
    else:
        if not flat_runs:
            err_console.print("[dim]No runs found.[/dim]")
            return

        from rich.table import Table

        table = Table(title=f"Recent Runs ({len(flat_runs)})")
        table.add_column("Run ID", style="cyan", max_width=12)
        table.add_column("Task")
        table.add_column("Model")
        table.add_column("Status")
        table.add_column("Success Rate", justify="right")
        table.add_column("Items", justify="right")
        table.add_column("Timestamp")

        for r in flat_runs:
            sr = r.get("success_rate")
            sr_str = f"{sr:.1%}" if sr is not None else "—"
            table.add_row(
                str(r.get("run_id", ""))[:12],
                r.get("task_name", ""),
                r.get("model_name", ""),
                r.get("status", ""),
                sr_str,
                str(r.get("total_items", "")),
                r.get("timestamp", ""),
            )
        err_console.print(table)


# ── qym run get ─────────────────────────────────────────────


@run_app.command("get")
def run_get(
    run_id: str = typer.Argument(help="Run ID to retrieve"),
) -> None:
    """Get detailed data for a specific evaluation run."""
    client = PlatformAPIClient()

    try:
        data = client.get_run(run_id)
    except PlatformAPIError as exc:
        output_error(
            error_type="not_found" if exc.status_code == 404 else "failure",
            message=exc.detail,
            suggestion=exc.suggestion,
        )
        raise typer.Exit(code=exc.exit_code)

    # Platform may return 200 with {"error": "..."} for missing runs
    if "error" in data and "run" not in data:
        output_error("not_found", data["error"], suggestion="Use 'qym run list' to see available runs.")
        raise typer.Exit(code=ExitCode.NOT_FOUND)

    if is_json_mode():
        output(data)
    else:
        run_info = data.get("run", {})
        snapshot = data.get("snapshot", {})
        items = snapshot.get("items", [])
        metrics = snapshot.get("metrics", {})

        err_console.print(f"\n[bold]Run:[/bold] {run_info.get('run_name', run_id)}")
        err_console.print(f"[bold]Dataset:[/bold] {run_info.get('dataset_name', '—')}")
        err_console.print(f"[bold]Status:[/bold] {run_info.get('status', '—')}")
        err_console.print(f"[bold]Items:[/bold] {len(items)}")
        err_console.print(f"[bold]Metrics:[/bold] {', '.join(run_info.get('metric_names', []))}")

        # Metric averages from snapshot
        if metrics:
            for name, values in metrics.items():
                if isinstance(values, dict) and "average" in values:
                    err_console.print(f"[bold]{name}:[/bold] {values['average']:.3f}")
                elif isinstance(values, list) and values:
                    avg = sum(v for v in values if isinstance(v, (int, float))) / len(values)
                    err_console.print(f"[bold]{name}:[/bold] {avg:.3f}")


# ── qym run failed ──────────────────────────────────────────


@run_app.command("failed")
def run_failed(
    run_id: str = typer.Argument(help="Run ID to inspect"),
) -> None:
    """Get only failed/error items from a run."""
    client = PlatformAPIClient()

    try:
        data = client.get_run(run_id)
    except PlatformAPIError as exc:
        output_error(
            error_type="not_found" if exc.status_code == 404 else "failure",
            message=exc.detail,
            suggestion=exc.suggestion,
        )
        raise typer.Exit(code=exc.exit_code)

    if "error" in data and "run" not in data:
        output_error("not_found", data["error"], suggestion="Use 'qym run list' to see available runs.")
        raise typer.Exit(code=ExitCode.NOT_FOUND)

    snapshot = data.get("snapshot", {})
    items = snapshot.get("items", [])

    failed_items = []
    for item in items:
        has_error = bool(item.get("error"))
        # Also include items where any metric score is 0
        scores = item.get("scores", {})
        has_zero_score = any(
            isinstance(v, (int, float)) and v == 0
            for v in scores.values()
        )
        if has_error or has_zero_score:
            failed_items.append(item)

    if is_json_mode():
        output({"run_id": run_id, "failed_items": failed_items, "total_failed": len(failed_items)})
    else:
        if not failed_items:
            err_console.print("[green]No failed items in this run.[/green]")
            return

        err_console.print(f"[bold]{len(failed_items)} failed items in run {run_id}:[/bold]\n")
        from rich.table import Table

        table = Table()
        table.add_column("Item ID", style="cyan", max_width=20)
        table.add_column("Error", max_width=40)
        table.add_column("Input", max_width=40)
        table.add_column("Scores")

        for item in failed_items[:50]:  # Cap display at 50
            scores_str = ", ".join(f"{k}={v}" for k, v in (item.get("scores") or {}).items())
            table.add_row(
                str(item.get("item_id", ""))[:20],
                str(item.get("error", ""))[:40] or "—",
                str(item.get("input", ""))[:40],
                scores_str or "—",
            )
        err_console.print(table)
        if len(failed_items) > 50:
            err_console.print(f"[dim]...and {len(failed_items) - 50} more. Use --json for full output.[/dim]")


# ── qym run compare ─────────────────────────────────────────


@run_app.command("compare")
def run_compare(
    run_ids: List[str] = typer.Argument(help="Two or more run IDs to compare"),
) -> None:
    """Compare multiple evaluation runs side-by-side."""
    if len(run_ids) < 2:
        output_error("usage_error", "At least 2 run IDs are required for comparison.")
        raise typer.Exit(code=ExitCode.USAGE_ERROR)

    client = PlatformAPIClient()
    runs_data = []

    for rid in run_ids:
        try:
            data = client.get_run(rid)
            runs_data.append(data)
        except PlatformAPIError as exc:
            output_error(
                error_type="not_found" if exc.status_code == 404 else "failure",
                message=f"Run {rid}: {exc.detail}",
                suggestion=exc.suggestion,
            )
            raise typer.Exit(code=exc.exit_code)

    # Build comparison
    comparison = {
        "runs": [],
        "metrics": {},
    }

    for data in runs_data:
        run_info = data.get("run", {})
        summary = data.get("summary", {})
        comparison["runs"].append({
            "run_id": run_info.get("id", ""),
            "run_name": run_info.get("run_name", ""),
            "model": run_info.get("model_name", ""),
            "success_rate": summary.get("success_rate"),
            "total_items": summary.get("total_items"),
            "metric_averages": summary.get("metric_averages", {}),
        })

        for metric_name, avg in summary.get("metric_averages", {}).items():
            if metric_name not in comparison["metrics"]:
                comparison["metrics"][metric_name] = {}
            comparison["metrics"][metric_name][run_info.get("run_name", "")] = avg

    if is_json_mode():
        output(comparison)
    else:
        from rich.table import Table

        table = Table(title="Run Comparison")
        table.add_column("Metric", style="cyan")
        for run in comparison["runs"]:
            label = run.get("run_name", run.get("run_id", ""))[:20]
            table.add_column(label, justify="right")

        # Success rate row
        table.add_row(
            "Success Rate",
            *[
                f"{r['success_rate']:.1%}" if r.get("success_rate") is not None else "—"
                for r in comparison["runs"]
            ],
        )

        # Metric rows
        for metric_name in comparison["metrics"]:
            values = []
            for run in comparison["runs"]:
                val = run.get("metric_averages", {}).get(metric_name)
                values.append(f"{val:.3f}" if val is not None else "—")
            table.add_row(metric_name, *values)

        err_console.print(table)
