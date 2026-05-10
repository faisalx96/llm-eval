"""Main Typer application for the qym agent-native CLI."""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import webbrowser
from pathlib import Path
from typing import Optional

import typer

from ._exit_codes import ExitCode
from ._output import set_json_mode, is_json_mode, output, output_error, err_console, status
from .run import run_app
from .metric import metric_app
from .analyze import analyze_app
from .config_cmd import config_app
from ..utils.env import get_platform_url_env, load_cwd_dotenv

load_cwd_dotenv()

app = typer.Typer(
    name="qym",
    help="Agent-native CLI for LLM evaluation.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
app.add_typer(run_app, name="run")
app.add_typer(metric_app, name="metric")
app.add_typer(analyze_app, name="analyze")
app.add_typer(config_app, name="config")


@app.callback()
def main_callback(
    json_output: bool = typer.Option(False, "--json", help="Output JSON to stdout, human text to stderr"),
    no_color: bool = typer.Option(False, "--no-color", help="Disable Rich color output"),
) -> None:
    """Global options applied before any subcommand."""
    set_json_mode(json_output)
    if no_color:
        err_console.no_color = True


# ── Legacy top-level commands ───────────────────────────────


@app.command("dashboard")
def dashboard(
    platform_url: Optional[str] = typer.Option(None, "--platform-url", help="Platform URL"),
    no_open: bool = typer.Option(False, "--no-open", help="Do not open browser"),
) -> None:
    """Open the qym platform dashboard in your browser."""
    url = platform_url or get_platform_url_env()
    url = url.rstrip("/")

    if is_json_mode():
        output({"dashboard_url": url})
    else:
        err_console.print(f"[bold]qym Platform Dashboard:[/bold] {url}")

    if not no_open and not is_json_mode():
        try:
            webbrowser.open(url)
            err_console.print("[green]Opened in browser[/green]")
        except Exception as e:
            err_console.print(f"[yellow]Could not open browser: {e}[/yellow]")


@app.command("submit")
def submit(
    file: str = typer.Option(..., "--file", help="Path to results file (.csv or .json)"),
    task: str = typer.Option(..., "--task", help="Task name"),
    dataset: str = typer.Option(..., "--dataset", help="Dataset name"),
    model_name: str = typer.Option("", "--model", help="Model name"),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="Platform API key"),
) -> None:
    """Upload a saved results file to the platform."""
    from urllib import request as urlrequest
    from ._legacy import _encode_multipart_formdata

    key = api_key or os.getenv("QYM_API_KEY")
    if not key:
        output_error("auth_denied", "Missing API key. Provide --api-key or set QYM_API_KEY.")
        raise typer.Exit(code=ExitCode.AUTH_DENIED)

    file_path = Path(file)
    if not file_path.exists():
        output_error("not_found", f"File not found: {file_path}")
        raise typer.Exit(code=ExitCode.NOT_FOUND)

    raw = file_path.read_bytes()
    ctype = mimetypes.guess_type(str(file_path.name))[0] or "application/octet-stream"

    body, boundary = _encode_multipart_formdata(
        fields={"task": task, "dataset": dataset, "model": model_name or ""},
        files={"file": (file_path.name, raw, ctype)},
    )

    platform_url = get_platform_url_env()
    platform_url = platform_url.rstrip("/")
    url = platform_url + "/v1/runs:upload"

    req = urlrequest.Request(
        url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )

    try:
        with urlrequest.urlopen(req, timeout=60) as resp:
            resp_body = resp.read().decode("utf-8")
        data = json.loads(resp_body)
    except Exception as exc:
        output_error("failure", f"Upload failed: {exc}")
        raise typer.Exit(code=ExitCode.FAILURE)

    if is_json_mode():
        output(data)
    else:
        err_console.print(
            f"[bold]Uploaded[/bold] run_id={data.get('run_id')} live_url={data.get('live_url')}"
        )


# ── Backward compatibility argv rewriting ───────────────────


_NOUNS = {"run", "metric", "analyze", "config", "dashboard", "submit"}


def _rewrite_legacy_argv(argv: list[str]) -> list[str]:
    """Rewrite legacy CLI patterns to new noun-verb structure.

    - `qym --task-file ...` -> `qym run create --task-file ...`
    - `qym resume --run-file X` -> `qym run create --resume-from X`
    """
    if not argv:
        return argv

    first = argv[0]

    # `qym resume ...` -> `qym run create --resume-from ...`
    if first == "resume":
        status("Hint: use 'qym run create --resume-from ...' in new scripts")
        rest = argv[1:]
        # Rewrite --run-file to --resume-from if present
        rewritten = []
        for arg in rest:
            if arg == "--run-file":
                rewritten.append("--resume-from")
            else:
                rewritten.append(arg)
        return ["run", "create"] + rewritten

    # `qym --task-file ...` (no noun prefix) -> `qym run create --task-file ...`
    if first not in _NOUNS and any(a == "--task-file" for a in argv):
        status("Hint: use 'qym run create --task-file ...' in new scripts")
        return ["run", "create"] + argv

    return argv


def _hoist_global_flags(argv: list[str]) -> list[str]:
    """Move global flags (--json, --no-color) before the subcommand.

    Typer requires global options to appear before the subcommand name.
    Agents may place them anywhere, so we hoist them to the front.
    """
    global_flags = {"--json", "--no-color"}
    hoisted = [a for a in argv if a in global_flags]
    rest = [a for a in argv if a not in global_flags]
    return hoisted + rest


def main() -> None:
    """CLI entry point with backward-compatible argv rewriting."""
    argv = sys.argv[1:]
    argv = _hoist_global_flags(argv)
    argv = _rewrite_legacy_argv(argv)
    sys.argv = [sys.argv[0]] + argv
    app()
