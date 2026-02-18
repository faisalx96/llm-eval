"""Command-line interface for قيِّم (qym)."""

import argparse
import copy
import json
import os
import sys
import importlib.util
from pathlib import Path
from typing import Any, List, Optional, Union
import shlex
import asyncio
import mimetypes
import uuid
from urllib import request as urlrequest

from rich.console import Console
from .core.evaluator import Evaluator
from .core.multi_runner import MultiModelRunner
from .core.config import RunSpec
from .utils.text import arabic_display

from .core.dataset import CsvDataset
from .core.checkpoint import load_checkpoint_state

console = Console()
def _encode_multipart_formdata(fields: dict, files: dict) -> tuple[bytes, str]:
    boundary = "----qym-" + uuid.uuid4().hex
    crlf = "\r\n"
    lines: list[bytes] = []

    for name, value in (fields or {}).items():
        lines.append(f"--{boundary}".encode())
        lines.append(f'Content-Disposition: form-data; name="{name}"'.encode())
        lines.append(b"")
        lines.append(str(value).encode("utf-8"))

    for name, fileinfo in (files or {}).items():
        filename, content, content_type = fileinfo
        lines.append(f"--{boundary}".encode())
        lines.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"'.encode()
        )
        lines.append(f"Content-Type: {content_type}".encode())
        lines.append(b"")
        lines.append(content)

    lines.append(f"--{boundary}--".encode())
    lines.append(b"")
    body = crlf.encode().join(lines)
    return body, boundary


def run_submit_command(argv: List[str]) -> None:
    parser = argparse.ArgumentParser(description="Submit an existing results file to the deployed platform")
    parser.add_argument("--file", required=True, help="Path to results file (.csv or .json)")
    parser.add_argument("--platform-url", required=False, default=None, help="Advanced: override platform base URL")
    parser.add_argument("--api-key", required=False, default=None, help="Platform API key (Bearer token). If omitted, uses QYM_API_KEY")
    parser.add_argument("--task", required=True, help="Task name")
    parser.add_argument("--dataset", required=True, help="Dataset name")
    parser.add_argument("--model", required=False, default="", help="Model name (optional)")
    args = parser.parse_args(argv)

    api_key = args.api_key or os.getenv("QYM_API_KEY")
    if not api_key:
        raise SystemExit("Missing API key. Provide --api-key or set QYM_API_KEY")

    file_path = Path(args.file)
    if not file_path.exists():
        raise SystemExit(f"File not found: {file_path}")

    raw = file_path.read_bytes()
    ctype = mimetypes.guess_type(str(file_path.name))[0] or "application/octet-stream"

    body, boundary = _encode_multipart_formdata(
        fields={
            "task": args.task,
            "dataset": args.dataset,
            "model": args.model or "",
        },
        files={
            "file": (file_path.name, raw, ctype),
        },
    )

    from .platform.defaults import DEFAULT_PLATFORM_URL
    platform_url = (args.platform_url or DEFAULT_PLATFORM_URL).rstrip("/")
    url = platform_url + "/v1/runs:upload"
    req = urlrequest.Request(
        url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urlrequest.urlopen(req, timeout=60) as resp:
        resp_body = resp.read().decode("utf-8")
    try:
        data = json.loads(resp_body)
    except Exception:
        data = {"raw": resp_body}
    console.print(f"[bold]Uploaded[/bold] run_id={data.get('run_id')} live_url={data.get('live_url')}")



def load_function_from_file(file_path: str, function_name: str):
    """Load a function from a Python file."""
    spec = importlib.util.spec_from_file_location("user_module", file_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load module from {file_path}")
    
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    if not hasattr(module, function_name):
        raise ValueError(f"Function '{function_name}' not found in {file_path}")
    
    return getattr(module, function_name)


def _load_runs_file(config_path: Path) -> Any:
    text = config_path.read_text(encoding="utf-8")
    suffix = config_path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ValueError("PyYAML is required to load YAML run configs") from exc
        return yaml.safe_load(text)
    return json.loads(text)


def load_multi_run_specs(config_path: Path) -> List[RunSpec]:
    """Parse a JSON/YAML config file into RunSpec objects."""
    data = _load_runs_file(config_path)
    if not isinstance(data, list):
        raise ValueError("Multi-run config must be a list of run definitions")

    specs: List[RunSpec] = []
    base_dir = config_path.parent

    for idx, entry in enumerate(data, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"Run #{idx} must be an object")
        try:
            task_file = Path(entry["task_file"])
            task_function = entry["task_function"]
            dataset = entry.get("dataset")
            dataset_csv = entry.get("dataset_csv")
            metrics_value = entry["metrics"]
        except KeyError as exc:
            raise ValueError(f"Run #{idx} is missing required field: {exc}") from exc

        if bool(dataset) == bool(dataset_csv):
            raise ValueError(f"Run #{idx} must set exactly one of 'dataset' or 'dataset_csv'")

        resolved_task_file = task_file if task_file.is_absolute() else (base_dir / task_file).resolve()
        task_callable = load_function_from_file(str(resolved_task_file), task_function)

        if isinstance(metrics_value, str):
            metrics = [m.strip() for m in metrics_value.split(",") if m.strip()]
        elif isinstance(metrics_value, list):
            metrics = [str(m).strip() for m in metrics_value if str(m).strip()]
        else:
            raise ValueError(f"Run #{idx} metrics must be a list or comma-separated string")

        config_template = dict(entry.get("config") or {})
        metadata_template = dict(entry.get("metadata") or {})
        # Resolve dataset object/name
        resolved_dataset: Any
        if dataset_csv:
            csv_path = Path(str(dataset_csv))
            resolved_csv = csv_path if csv_path.is_absolute() else (base_dir / csv_path).resolve()
            csv_input_col = entry.get("csv_input_col", "input")
            csv_expected_col = entry.get("csv_expected_col", "expected_output")
            csv_id_col = entry.get("csv_id_col")
            csv_md_cols = entry.get("csv_metadata_cols")
            md_cols = []
            if isinstance(csv_md_cols, str):
                md_cols = [c.strip() for c in csv_md_cols.split(",") if c.strip()]
            elif isinstance(csv_md_cols, list):
                md_cols = [str(c).strip() for c in csv_md_cols if str(c).strip()]
            resolved_dataset = CsvDataset(
                resolved_csv,
                input_col=str(csv_input_col),
                expected_col=str(csv_expected_col) if csv_expected_col else None,
                id_col=str(csv_id_col) if csv_id_col else None,
                metadata_cols=md_cols,
            )
        else:
            resolved_dataset = dataset


        model_values = entry.get("models")
        if model_values is None:
            model_values = entry.get("model")
        model_list = Evaluator._normalize_models(model_values) if model_values is not None else []
        if not model_list:
            model_list = [None]

        output_path = entry.get("output")
        resolved_output_template = None
        if output_path:
            out_path = Path(output_path)
            resolved_output_template = out_path if out_path.is_absolute() else (base_dir / out_path)

        for model_name in model_list:
            config = copy.deepcopy(config_template) if config_template else {}
            config.pop("models", None)
            metadata = dict(metadata_template)
            if model_name:
                metadata.setdefault("model", model_name)
                config["model"] = model_name
            if metadata:
                merged_meta = {**metadata, **dict(config.get("run_metadata") or {})}
                config["run_metadata"] = merged_meta

            base_name = entry.get("name") or config.get("run_name") or task_function
            run_id, display = Evaluator.build_run_identifiers(base_name, model_name)
            config["run_name"] = run_id

            resolved_output = resolved_output_template
            if resolved_output_template and model_name:
                resolved_output = resolved_output_template.with_stem(f"{resolved_output_template.stem}-{model_name}")

            specs.append(
                RunSpec(
                    name=run_id,
                    display_name=display,
                    task=task_callable,
                    dataset=resolved_dataset,
                    metrics=metrics,
                    task_file=str(resolved_task_file),
                    task_function=task_function,
                    config=config,
                    output_path=resolved_output,
                )
            )

    return specs


def run_dashboard_command(args: List[str]) -> None:
    """Run the dashboard subcommand."""
    import webbrowser
    from .platform.defaults import DEFAULT_PLATFORM_URL

    parser = argparse.ArgumentParser(
        prog="qym dashboard",
        description="Open the qym platform dashboard in your browser",
    )
    parser.add_argument(
        "--platform-url",
        default=None,
        help="Platform URL (defaults to QYM_PLATFORM_URL or built-in URL)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open browser automatically, just print URL",
    )

    parsed = parser.parse_args(args)
    platform_url = parsed.platform_url or os.getenv("QYM_PLATFORM_URL") or DEFAULT_PLATFORM_URL
    platform_url = platform_url.rstrip("/")
    
    console.print(f"[bold]qym Platform Dashboard:[/bold] {platform_url}")
    console.print("[dim]Note: Local dashboard server has been deprecated.[/dim]")
    console.print("[dim]Use the platform dashboard at the URL above.[/dim]")
    
    if not parsed.no_open:
        try:
            webbrowser.open(platform_url)
            console.print("[green]Opened in browser[/green]")
        except Exception as e:
            console.print(f"[yellow]Could not open browser: {e}[/yellow]")


def main():
    """Main CLI entry point."""
    # Check for dashboard subcommand first
    if len(sys.argv) > 1 and sys.argv[1] == "dashboard":
        run_dashboard_command(sys.argv[2:])
        return
    # Submit saved results to platform
    if len(sys.argv) > 1 and sys.argv[1] == "submit":
        run_submit_command(sys.argv[2:])
        return
    resume_mode = False
    argv = sys.argv[1:]
    if len(argv) > 0 and argv[0] == "resume":
        resume_mode = True
        argv = argv[1:]

    parser = argparse.ArgumentParser(
        # Use arabic_display() for proper RTL text rendering in terminals
        description=f"{arabic_display('أداة قيِّم')} - Evaluate LLM tasks using Langfuse datasets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Evaluate a function from a Python file
  qym --task-file my_bot.py --task-function ask_question \\
           --dataset qa-test-set --metrics exact_match,fuzzy_match

  # Use custom configuration
  qym --task-file bot.py --task-function chat \\
           --dataset conversations --metrics contains \\
           --config '{"max_concurrency": 5, "timeout": 10}'

  # Save results to file
  qym --task-file agent.py --task-function run \\
           --dataset test-cases --metrics exact_match \\
           --output results.json

  # Open dashboard to view historical runs
  qym dashboard
        """
    )
    
    # Required arguments
    parser.add_argument(
        "--task-file",
        required=False,
        help="Python file containing the task function"
    )
    parser.add_argument(
        "--task-function", 
        required=False,
        help="Name of the function to evaluate"
    )
    parser.add_argument(
        "--dataset",
        required=False, 
        help="Name of the Langfuse dataset"
    )
    parser.add_argument(
        "--dataset-csv",
        required=False,
        help="Path to a local CSV dataset file"
    )
    parser.add_argument(
        "--metrics",
        required=False,
        help="Comma-separated list of metrics (e.g., 'exact_match,fuzzy_match')"
    )
    # CSV dataset options
    parser.add_argument(
        "--csv-input-col",
        default="input",
        help="CSV column name to use as input (default: input)"
    )
    parser.add_argument(
        "--csv-expected-col",
        default="expected_output",
        help="CSV column name to use as expected output (default: expected_output). "
             "Use empty string to disable expected output."
    )
    parser.add_argument(
        "--csv-id-col",
        default=None,
        help="Optional CSV column name to use as item id"
    )
    parser.add_argument(
        "--csv-metadata-cols",
        default=None,
        help="Optional comma-separated list of CSV columns to copy into item metadata"
    )
    parser.add_argument(
        "--model",
        help="Model name or comma-separated list of models to evaluate"
    )
    parser.add_argument(
        "--task-name",
        default=None,
        help="Override the auto-derived task name for display and file paths"
    )
    
    # Optional arguments
    parser.add_argument(
        "--config",
        help="JSON configuration string for the evaluator"
    )
    parser.add_argument(
        "--no-ui",
        action="store_true",
        help="Disable starting the local web UI"
    )
    parser.add_argument(
        "--ui-port",
        type=int,
        default=0,
        help="Port for the local web UI (0 for auto)"
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the browser automatically"
    )
    parser.add_argument(
        "--output",
        help="File to save detailed results (JSON format)"
    )
    parser.add_argument(
        "--platform-url",
        required=False,
        help="Advanced: override platform base URL (normally built-in for internal deployments)"
    )
    parser.add_argument(
        "--platform-api-key",
        required=False,
        help="API key for the deployed platform (Bearer token)"
    )
    parser.add_argument(
        "--live-mode",
        required=False,
        choices=["auto", "local", "platform"],
        help="[DEPRECATED] Live mode is now always 'platform'. Use --no-ui to disable."
    )
    parser.add_argument(
        "--resume-from",
        "--run-file",
        dest="resume_from",
        help="Path to a checkpoint CSV to resume from"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Only show final summary, no progress"
    )
    parser.add_argument(
        "--no-progress",
        action="store_true", 
        help="Disable progress bar"
    )
    parser.add_argument(
        "--runs-config",
        help="Path to JSON/YAML file describing multiple runs to execute in parallel"
    )
    
    args = parser.parse_args(argv)
    is_multi_run = bool(args.runs_config)
    if resume_mode and not args.resume_from:
        parser.error("--run-file is required for resume")
    if is_multi_run and args.model:
        console.print("[yellow]⚠️  Ignoring --model because --runs-config is provided.[/yellow]")

    model_arg: Optional[Union[str, List[str]]] = None
    if args.model:
        parsed = Evaluator._normalize_models(args.model)
        if parsed:
            model_arg = parsed if len(parsed) > 1 else parsed[0]

    if is_multi_run:
        config_path = Path(args.runs_config).expanduser()
        if not config_path.exists():
            console.print(f"[red]Runs config not found: {config_path}[/red]")
            sys.exit(1)
        try:
            run_specs = load_multi_run_specs(config_path)
        except Exception as exc:
            console.print(f"[red]Failed to load runs config: {exc}[/red]")
            sys.exit(1)
        if not run_specs:
            console.print("[red]Runs config is empty[/red]")
            sys.exit(1)

        show_tui = not args.quiet and not args.no_progress and not args.no_ui
        runner = MultiModelRunner(run_specs, console=console)
        try:
            results = asyncio.run(
                runner.arun(
                    show_tui=show_tui,
                    auto_save=True,
                    save_format="csv",
                )
            )
        except RuntimeError as exc:
            console.print(f"[red]{exc}[/red]")
            sys.exit(1)

        runner.print_summary(results)
        runner.print_saved_paths(results)

        interrupted_runs = [res for res in results if getattr(res, "interrupted", False)]
        if interrupted_runs:
            for res in interrupted_runs:
                resume_path = getattr(res, "last_saved_path", None)
                if resume_path:
                    console.print(f"[yellow]Partial results saved to {resume_path}[/yellow]")
                    console.print(f"[yellow]Resume with: qym resume --run-file {resume_path} ...[/yellow]")
            sys.exit(1)

        for spec, result in zip(run_specs, results):
            if spec.output_path:
                output_path = spec.output_path
                output_path.parent.mkdir(parents=True, exist_ok=True)
                suffix = output_path.suffix.lower()
                format_hint = "json"
                if suffix == ".csv":
                    format_hint = "csv"
                saved_path = result.save(format=format_hint, filepath=str(output_path))
                console.print(f"[green]Saved {spec.run_name} results to {saved_path}[/green]")

        sys.exit(0)

    try:
        missing = {}
        if not is_multi_run:
            missing = {
                "--task-file": args.task_file,
                "--task-function": args.task_function,
                "--dataset/--dataset-csv": (args.dataset or args.dataset_csv),
                "--metrics": args.metrics,
            }
            missing_flags = [flag for flag, value in missing.items() if not value]
            if missing_flags:
                parser.error(f"Missing required arguments: {', '.join(missing_flags)}")

        if not is_multi_run and bool(args.dataset) == bool(args.dataset_csv):
            parser.error("Provide exactly one of --dataset (Langfuse) or --dataset-csv (CSV).")

        # Load the task function
        console.print(f"Loading task function '{args.task_function}' from {args.task_file}")
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
        if args.resume_from:
            config["resume_from"] = args.resume_from
            if "run_name" not in config:
                resume_state = load_checkpoint_state(args.resume_from)
                if resume_state and resume_state.run_name:
                    config["run_name"] = resume_state.run_name
        # Record CLI invocation for frontend run overview
        try:
            argv_str = ' '.join(shlex.quote(a) for a in sys.argv[1:])
            config['cli_invocation'] = f"qym {argv_str}".strip()
        except Exception:
            pass

        # UI preferences
        try:
            config['ui_port'] = int(args.ui_port)
        except Exception:
            config['ui_port'] = 0
        # #15: task_name override
        if args.task_name:
            config["task_name"] = args.task_name

        # Platform preferences
        if args.platform_url:
            config["platform_url"] = args.platform_url
        if args.platform_api_key:
            config["platform_api_key"] = args.platform_api_key
        if args.live_mode:
            config["live_mode"] = args.live_mode
        else:
            # Deprecation path: if platform is configured, prefer platform live mode.
            purl = args.platform_url or os.getenv("QYM_PLATFORM_URL")
            pkey = args.platform_api_key or os.getenv("QYM_API_KEY")
            if purl and pkey:
                config["live_mode"] = "auto"
        
        # Create evaluator
        dataset_obj: Any = args.dataset
        if args.dataset_csv:
            md_cols: List[str] = []
            if args.csv_metadata_cols:
                md_cols = [c.strip() for c in str(args.csv_metadata_cols).split(",") if c.strip()]
            expected_col = str(args.csv_expected_col) if args.csv_expected_col is not None else "expected_output"
            if expected_col.strip() == "":
                expected_col = None
            dataset_obj = CsvDataset(
                args.dataset_csv,
                input_col=str(args.csv_input_col),
                expected_col=expected_col,
                id_col=str(args.csv_id_col) if args.csv_id_col else None,
                metadata_cols=md_cols,
            )
        dataset_label = getattr(dataset_obj, "name", None) or str(dataset_obj)
        console.print(f"Setting up evaluation for dataset '{dataset_label}'")
        evaluator = Evaluator(
            task=task_function,
            dataset=dataset_obj,
            metrics=metrics,
            config=config,
            model=model_arg,
        )
        
        # Run evaluation
        console.print("Starting evaluation...")
        show_progress = not args.no_progress and not args.quiet
        show_table = not args.no_ui
        raw_results = evaluator.run(show_progress=show_progress, show_table=show_table)
        run_results = raw_results if isinstance(raw_results, list) else [raw_results]
        
        # Show results
        if args.quiet:
            for res in run_results:
                console.print(f"{res.run_name} Success Rate: {res.success_rate:.1%}")
                for metric in metrics:
                    stats = res.get_metric_stats(metric)
                    console.print(f"{res.run_name} {metric}: {stats['mean']:.3f}")
        else:
            for res in run_results:
                res.print_summary()
        
        # Save detailed results if requested
        if args.output:
            if len(run_results) > 1:
                console.print("[yellow]⚠️  --output supports only single-model runs. Use --runs-config or per-run outputs.[/yellow]")
            else:
                output_path = Path(args.output)
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(run_results[0].to_dict(), f, indent=2, default=str, ensure_ascii=False)
                console.print(f"Detailed results saved to {output_path}")
        
        # Print UI URL and optionally open browser (single run only)
        primary_result = run_results[0]
        if getattr(primary_result, "interrupted", False):
            resume_path = getattr(primary_result, "last_saved_path", None)
            if resume_path:
                console.print(f"[yellow]Partial results saved to {resume_path}[/yellow]")
                console.print(f"[yellow]Resume with: qym resume --run-file {resume_path} ...[/yellow]")
            sys.exit(1)
        try:
            if getattr(primary_result, 'html_url', None) and not args.no_open and not args.quiet:
                console.print(f"\n[blue]UI:[/blue] {primary_result.html_url}")
                import webbrowser
                webbrowser.open(primary_result.html_url)
        except Exception:
            pass

        # Exit with error code if success rate is too low
        low_success = [res for res in run_results if res.success_rate < 0.5]
        if low_success:
            names = ", ".join(res.run_name for res in low_success)
            console.print(f"[yellow]Warning: Success rate below 50% for runs: {names}[/yellow]")
            sys.exit(2)
            
    except KeyboardInterrupt:
        console.print("\n[yellow]Evaluation interrupted by user[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
