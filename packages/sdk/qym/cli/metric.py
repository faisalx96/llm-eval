"""qym metric commands."""

import typer

from ._output import is_json_mode, output, err_console

metric_app = typer.Typer(help="Inspect available evaluation metrics.")


@metric_app.command("list")
def metric_list() -> None:
    """List all available evaluation metrics."""
    from ..metrics import builtin_metrics

    metrics_data = []
    for name, metric_func in sorted(builtin_metrics.items()):
        description = "No description available"
        if hasattr(metric_func, "__doc__") and metric_func.__doc__:
            description = metric_func.__doc__.strip().split("\n")[0]
        metrics_data.append({
            "name": name,
            "description": description,
        })

    if is_json_mode():
        output({
            "metrics": metrics_data,
            "total": len(metrics_data),
        })
    else:
        from rich.table import Table

        table = Table(title="Available Metrics")
        table.add_column("Name", style="cyan", no_wrap=True)
        table.add_column("Description")
        for m in metrics_data:
            table.add_row(m["name"], m["description"])
        err_console.print(table)
        err_console.print(f"\nTotal: {len(metrics_data)} metrics")
