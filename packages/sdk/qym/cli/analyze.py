"""qym analyze commands."""

from __future__ import annotations

from typing import Optional

import typer

from ._exit_codes import ExitCode
from ._output import err_console, is_json_mode, output, output_error
from ._platform_api import PlatformAPIClient, PlatformAPIError

analyze_app = typer.Typer(help="AI-powered root cause analysis.")


@analyze_app.command("run")
def analyze_run(
    run_id: str = typer.Argument(help="Run ID to analyze"),
    concurrency: int = typer.Option(
        20, min=1, max=20, help="Parallel analysis requests"
    ),
) -> None:
    """Trigger AI root-cause analysis on a run's items."""
    client = PlatformAPIClient()

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
        err_console.print(
            f"[green]Analysis complete:[/green] {analyzed} item-metrics analyzed"
        )
        categories = result.get("categories", {})
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
    items = snapshot.get("rows", snapshot.get("items", []))
    categories: dict[str, int] = {}
    total_analyzed = 0

    for item in items:
        meta = item.get("item_metadata") or {}
        metric_analyses = meta.get("metric_analyses")
        metric_categories = []
        if isinstance(metric_analyses, dict):
            for analysis in metric_analyses.values():
                if not isinstance(analysis, dict) or analysis.get("error"):
                    continue
                issues = analysis.get("root_cause_issues")
                if isinstance(issues, list):
                    metric_categories.extend(
                        str(issue.get("category") or "").strip()
                        for issue in issues
                        if isinstance(issue, dict)
                    )
                    continue
                root_causes = analysis.get("root_causes")
                if isinstance(root_causes, list):
                    metric_categories.extend(
                        str(category or "").strip() for category in root_causes
                    )
                else:
                    metric_categories.append(
                        str(analysis.get("root_cause") or "").strip()
                    )
            metric_categories = [
                category for category in metric_categories if category
            ]

        if not metric_categories:
            issues = meta.get("root_cause_issues")
            if isinstance(issues, list):
                metric_categories = [
                    str(issue.get("category") or "").strip()
                    for issue in issues
                    if isinstance(issue, dict)
                    and str(issue.get("category") or "").strip()
                ]
            else:
                root_causes = meta.get("root_causes")
                if isinstance(root_causes, list):
                    metric_categories = [
                        str(category or "").strip()
                        for category in root_causes
                        if str(category or "").strip()
                    ]
                else:
                    root_cause = str(meta.get("root_cause") or "").strip()
                    if root_cause:
                        metric_categories = [root_cause]

        for root_cause in metric_categories:
            total_analyzed += 1
            categories[root_cause] = categories.get(root_cause, 0) + 1

    summary = {
        "run_id": run_id,
        "total_items": len(items),
        "total_item_metrics_analyzed": total_analyzed,
        "total_analyzed": total_analyzed,
        "categories": categories,
    }

    if is_json_mode():
        output(summary)
    else:
        err_console.print(f"[bold]Run:[/bold] {run_id}")
        err_console.print(
            f"[bold]Items:[/bold] {len(items)} total; "
            f"[bold]analyzed item-metrics:[/bold] {total_analyzed}"
        )
        if categories:
            from rich.table import Table

            table = Table(title="Root Cause Categories")
            table.add_column("Category", style="cyan")
            table.add_column("Count", justify="right")
            table.add_column("Percentage", justify="right")
            for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
                pct = (
                    f"{count / total_analyzed * 100:.1f}%"
                    if total_analyzed > 0
                    else "—"
                )
                table.add_row(cat, str(count), pct)
            err_console.print(table)
        else:
            err_console.print(
                "[dim]No root-cause analysis data found for this run.[/dim]"
            )
