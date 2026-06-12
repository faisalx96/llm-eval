"""qym analyze commands."""

from __future__ import annotations

from typing import Optional

import typer

from ._exit_codes import ExitCode
from ._output import is_json_mode, output, output_error, err_console
from ._platform_api import PlatformAPIClient, PlatformAPIError

analyze_app = typer.Typer(help="AI-powered root cause analysis.")


@analyze_app.command("run")
def analyze_run(
    run_id: str = typer.Argument(help="Run ID to analyze"),
    concurrency: int = typer.Option(20, help="Parallel analysis threads"),
) -> None:
    """Trigger AI root-cause analysis on a run's items."""
    client = PlatformAPIClient()

    # The platform caps analysis concurrency at 20 (AnalyzeRequest).
    concurrency = max(1, min(concurrency, 20))

    try:
        result = client.analyze_run(run_id, body={"concurrency": concurrency})
    except PlatformAPIError as exc:
        output_error(
            error_type="not_found" if exc.status_code == 404 else "failure",
            message=exc.detail,
            suggestion=exc.suggestion,
        )
        raise typer.Exit(code=exc.exit_code)

    if is_json_mode():
        output(result)
    else:
        analyzed = result.get("total_analyzed", 0)
        errors = result.get("errors", 0)
        summary = f"[green]Analysis complete:[/green] {analyzed} items analyzed"
        if errors:
            summary += f" ([red]{errors} errors[/red])"
        err_console.print(summary)

        # Derive a category summary from the per-item results
        categories: dict[str, int] = {}
        for item in result.get("results", []) or []:
            if item.get("error"):
                continue
            root_cause = item.get("root_cause")
            if root_cause:
                categories[root_cause] = categories.get(root_cause, 0) + 1
        if categories:
            from rich.table import Table

            table = Table(title="Root Cause Categories")
            table.add_column("Category", style="cyan")
            table.add_column("Count", justify="right")
            for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
                table.add_row(cat, str(count))
            err_console.print(table)


@analyze_app.command("summary")
def analyze_summary(
    run_id: str = typer.Argument(help="Run ID to summarize"),
) -> None:
    """Get aggregated root-cause analysis summary for a run."""
    client = PlatformAPIClient()

    try:
        run_data = client.get_run(run_id)
    except PlatformAPIError as exc:
        output_error(
            error_type="not_found" if exc.status_code == 404 else "failure",
            message=exc.detail,
            suggestion=exc.suggestion,
        )
        raise typer.Exit(code=exc.exit_code)

    # Aggregate root causes from items
    snapshot = run_data.get("snapshot", {})
    items = snapshot.get("items", [])
    categories: dict[str, int] = {}
    total_analyzed = 0

    for item in items:
        root_cause = None
        # Check corrections first, then item metadata
        corrections = item.get("corrections", [])
        if corrections:
            latest = corrections[-1]
            root_cause = latest.get("human_root_cause") or latest.get("ai_root_cause")
        if not root_cause:
            meta = item.get("item_metadata") or {}
            root_cause = meta.get("root_cause")

        if root_cause:
            total_analyzed += 1
            categories[root_cause] = categories.get(root_cause, 0) + 1

    summary = {
        "run_id": run_id,
        "total_items": len(items),
        "total_analyzed": total_analyzed,
        "categories": categories,
    }

    if is_json_mode():
        output(summary)
    else:
        err_console.print(f"[bold]Run:[/bold] {run_id}")
        err_console.print(f"[bold]Items:[/bold] {len(items)} total, {total_analyzed} analyzed")
        if categories:
            from rich.table import Table

            table = Table(title="Root Cause Categories")
            table.add_column("Category", style="cyan")
            table.add_column("Count", justify="right")
            table.add_column("Percentage", justify="right")
            for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
                pct = f"{count / total_analyzed * 100:.1f}%" if total_analyzed > 0 else "—"
                table.add_row(cat, str(count), pct)
            err_console.print(table)
        else:
            err_console.print("[dim]No root-cause analysis data found for this run.[/dim]")
