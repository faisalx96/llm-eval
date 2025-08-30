"""Command-line interface for llm-eval."""

import argparse
import json
import sys
import importlib.util
from pathlib import Path
from typing import Dict, Any
import shlex

from rich.console import Console
from .core.evaluator import Evaluator


console = Console()


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
        """
    )
    
    # Required arguments
    parser.add_argument(
        "--task-file",
        required=True,
        help="Python file containing the task function"
    )
    parser.add_argument(
        "--task-function", 
        required=True,
        help="Name of the function to evaluate"
    )
    parser.add_argument(
        "--dataset",
        required=True, 
        help="Name of the Langfuse dataset"
    )
    parser.add_argument(
        "--metrics",
        required=True,
        help="Comma-separated list of metrics (e.g., 'exact_match,fuzzy_match')"
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
        "--quiet", "-q",
        action="store_true",
        help="Only show final summary, no progress"
    )
    parser.add_argument(
        "--no-progress",
        action="store_true", 
        help="Disable progress bar"
    )
    
    args = parser.parse_args()
    
    try:
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
        # Record CLI invocation for frontend run overview
        try:
            argv_str = ' '.join(shlex.quote(a) for a in sys.argv[1:])
            config['cli_invocation'] = f"llm-eval {argv_str}".strip()
        except Exception:
            pass

        # UI preferences
        try:
            config['ui_port'] = int(args.ui_port)
        except Exception:
            config['ui_port'] = 0
        
        # Create evaluator
        console.print(f"Setting up evaluation for dataset '{args.dataset}'")
        evaluator = Evaluator(
            task=task_function,
            dataset=args.dataset,
            metrics=metrics,
            config=config
        )
        
        # Run evaluation
        console.print("Starting evaluation...")
        show_progress = not args.no_progress and not args.quiet
        show_table = not args.no_ui
        results = evaluator.run(show_progress=show_progress, show_table=show_table)
        
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
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(results.to_dict(), f, indent=2, default=str, ensure_ascii=False)
            console.print(f"Detailed results saved to {output_path}")
        
        # Print UI URL and optionally open browser
        try:
            if getattr(results, 'html_url', None) and not args.no_open and not args.quiet:
                console.print(f"\n[blue]UI:[/blue] {results.html_url}")
                import webbrowser
                webbrowser.open(results.html_url)
        except Exception:
            pass

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


if __name__ == "__main__":
    main()
