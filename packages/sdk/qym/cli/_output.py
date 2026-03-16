"""JSON/Rich output routing for agent-native CLI."""

import json
import sys
from contextvars import ContextVar
from typing import Any, Iterable

from rich.console import Console

_json_mode: ContextVar[bool] = ContextVar("_json_mode", default=False)

# Human-readable output always goes to stderr (so stdout is clean JSON when --json)
err_console = Console(stderr=True)


def set_json_mode(enabled: bool) -> None:
    _json_mode.set(enabled)


def is_json_mode() -> bool:
    return _json_mode.get()


def output(data: Any) -> None:
    """Write structured data. JSON to stdout if --json, Rich to stderr otherwise."""
    if is_json_mode():
        json.dump(data, sys.stdout, indent=2, default=str, ensure_ascii=False)
        sys.stdout.write("\n")
        sys.stdout.flush()
    else:
        err_console.print(data)


def output_ndjson(items: Iterable[Any]) -> None:
    """Write items as newline-delimited JSON to stdout."""
    for item in items:
        json.dump(item, sys.stdout, default=str, ensure_ascii=False)
        sys.stdout.write("\n")
    sys.stdout.flush()


def output_error(error_type: str, message: str, suggestion: str | None = None) -> None:
    """Write a structured error. JSON to stdout if --json, Rich to stderr otherwise."""
    if is_json_mode():
        err: dict[str, Any] = {"error": error_type, "message": message}
        if suggestion:
            err["suggestion"] = suggestion
        json.dump(err, sys.stdout, default=str, ensure_ascii=False)
        sys.stdout.write("\n")
        sys.stdout.flush()
    else:
        err_console.print(f"[red]Error: {message}[/red]")
        if suggestion:
            err_console.print(f"[dim]{suggestion}[/dim]")


def status(msg: str) -> None:
    """Human-readable status message. Always goes to stderr."""
    err_console.print(msg, style="dim")
