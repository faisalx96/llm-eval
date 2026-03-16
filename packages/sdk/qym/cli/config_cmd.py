"""qym config commands."""

import os

import typer

from ._exit_codes import ExitCode
from ._output import is_json_mode, output, output_error, err_console
from ._platform_api import PlatformAPIClient, PlatformAPIError

config_app = typer.Typer(help="Platform configuration and connectivity.")


@config_app.command("show")
def config_show() -> None:
    """Show resolved platform configuration."""
    from ..platform.defaults import DEFAULT_PLATFORM_URL

    platform_url = os.getenv("QYM_PLATFORM_URL") or DEFAULT_PLATFORM_URL
    api_key = os.getenv("QYM_API_KEY")
    langfuse_host = os.getenv("LANGFUSE_HOST")
    langfuse_public = os.getenv("LANGFUSE_PUBLIC_KEY")

    data = {
        "platform_url": platform_url,
        "api_key_set": bool(api_key),
        "langfuse_host": langfuse_host or "(not set)",
        "langfuse_public_key_set": bool(langfuse_public),
    }

    if is_json_mode():
        output(data)
    else:
        err_console.print(f"[bold]Platform URL:[/bold]       {data['platform_url']}")
        err_console.print(f"[bold]API Key:[/bold]            {'set' if data['api_key_set'] else '[red]not set[/red]'}")
        err_console.print(f"[bold]Langfuse Host:[/bold]      {data['langfuse_host']}")
        err_console.print(f"[bold]Langfuse Key:[/bold]       {'set' if data['langfuse_public_key_set'] else '[red]not set[/red]'}")


@config_app.command("check")
def config_check() -> None:
    """Validate connectivity to the platform API."""
    client = PlatformAPIClient()

    try:
        result = client.check_connectivity()
    except PlatformAPIError as exc:
        output_error(
            error_type="connection_failed" if exc.status_code == 0 else "auth_denied",
            message=exc.detail,
            suggestion=exc.suggestion,
        )
        raise typer.Exit(code=exc.exit_code)

    if is_json_mode():
        output(result)
    else:
        err_console.print(f"[green]Connected[/green] to {result['platform_url']}")
        if not result["api_key_set"]:
            err_console.print("[yellow]Warning: QYM_API_KEY not set. Some endpoints may require it.[/yellow]")
