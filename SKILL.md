---
name: qym
description: LLM evaluation framework - create, inspect, and analyze evaluation runs
version: 0.8.4
---

# qym CLI

Fast, async LLM evaluation framework with agent-native CLI.

## Quick Start

```bash
# List recent evaluation runs
qym run list --json

# Get details of a specific run
qym run get <run_id> --json

# See failed items in a run
qym run failed <run_id> --json

# Compare two runs side-by-side
qym run compare <run_id_1> <run_id_2> --json

# List available metrics
qym metric list --json

# Run AI root-cause analysis on a run
qym analyze run <run_id> --json

# Get analysis summary
qym analyze summary <run_id> --json

# Check platform connectivity
qym config check --json

# Show resolved config
qym config show --json
```

## Commands

### qym run list [--limit N] [--task TEXT] [--model TEXT] [--status TEXT]
List all evaluation runs. Returns JSON array of run summaries with run_id, task, model, status, success_rate, total_items, timestamp.

### qym run get <run_id>
Returns full run data including all items, scores, metadata, and summary stats.

### qym run failed <run_id>
Returns only failed/error items from a run. Items with errors or zero metric scores.

### qym run compare <id1> <id2> [<id3> ...]
Compares two or more runs with aligned metric averages and success rates.

### qym run create --task-file FILE --task-function NAME --dataset NAME --metrics LIST
Execute an evaluation. Supports --model for multi-model, --dataset-csv for local CSV, --runs-config for multi-run YAML/JSON.

### qym metric list
Lists all available evaluation metrics with descriptions.

### qym analyze run <run_id>
Triggers AI root-cause analysis on run items. Returns analysis results with categories.

### qym analyze summary <run_id>
Returns aggregated root-cause categories with counts and percentages.

### qym config show
Displays current platform URL, API key status, and Langfuse configuration.

### qym config check
Validates connectivity to the platform API. Returns status and auth info.

### qym dashboard
Opens the platform web dashboard in the browser.

### qym submit --file PATH --task NAME --dataset NAME
Uploads a saved results file (.csv or .json) to the platform.

## Environment Variables

- `QYM_PLATFORM_URL` - Platform base URL (default: http://localhost:8000)
- `QYM_API_KEY` - API key for platform authentication
- `LANGFUSE_PUBLIC_KEY` - Langfuse public key
- `LANGFUSE_SECRET_KEY` - Langfuse secret key
- `LANGFUSE_HOST` - Langfuse host URL

## Exit Codes

- 0: Success
- 1: General failure
- 2: Usage error / low success rate
- 3: Resource not found
- 4: Authentication denied
- 5: Conflict

## Output

All commands support `--json` for structured JSON output to stdout.
Human-readable output goes to stderr when `--json` is active.
Errors in JSON mode: `{"error": "type", "message": "...", "suggestion": "..."}`
