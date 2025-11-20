# Codebase Context & Architecture

> **Purpose**: This document serves as a "brain dump" for the `llm-eval` codebase. It explains the architecture, core flows, and design decisions to allow an expert to immediately understand the system.

## 1. System Overview

`llm-eval` is a Python library for evaluating LLM applications. It integrates with **Langfuse** for dataset management and tracing, and uses **Rich** for terminal UI. It supports both synchronous single-model runs and asynchronous parallel multi-model evaluations.

## 2. Core Architecture

The system is built around a few key components:

### 2.1. `Evaluator` (`llm_eval/core/evaluator.py`)
The central entry point. It handles:
- **Configuration**: Parsing user config, loading datasets, preparing metrics.
- **Execution Strategy**: Decides whether to run a single evaluation or delegate to `MultiModelRunner`.
- **Single-Run Logic**: The `arun` method orchestrates the evaluation of a dataset against a single model.
- **Refactoring Note**: UI state management was extracted to `ProgressTracker` to avoid "God Object" anti-patterns.

### 2.2. `MultiModelRunner` (`llm_eval/core/multi_runner.py`)
Handles the "Fan-Out" for parallel evaluations.
- **Responsibility**: Takes a list of run configurations, creates multiple `Evaluator` instances, and runs them concurrently.
- **UI**: Manages the "Multi-Run Progress" dashboard using `rich.live`.
- **Delegation**: `Evaluator.run_parallel` is now a thin wrapper around this class.

### 2.3. `ProgressTracker` (`llm_eval/core/progress.py`)
Encapsulates all UI state logic.
- **Protocol**: Implements `ProgressObserver` protocol to decouple UI from logic.
- **State**: Keeps track of `item_statuses` (pending, running, completed, failed).
- **Snapshots**: Generates data snapshots for the local Web UI (`server/app.py`).
- **Separation**: Allows `Evaluator` to focus on logic, not presentation.

### 2.4. `TaskAdapter` (`llm_eval/adapters/base.py`)
Abstracts the "Thing being evaluated".
- **Auto-Detection**: `auto_detect_task` wraps functions, LangChain chains, or Pydantic AI agents into a unified interface.
- **Tracing**: Ensures Langfuse tracing context is propagated correctly.

## 3. Critical Execution Flows

### 3.1. The "Fan-Out" (Multi-Model Execution)
When `Evaluator` is initialized with `model=["a", "b"]`:
1.  `Evaluator.run()` detects multiple models.
2.  Calls `_run_multi_model()`, which expands the config into N distinct run dictionaries.
3.  Delegates to `Evaluator.run_parallel(runs)`.
4.  `run_parallel` calls `MultiModelRunner.from_runs(runs)`.
5.  `MultiModelRunner` creates N `Evaluator` instances and runs them via `asyncio.gather`.

### 3.2. The Evaluation Loop (`Evaluator.arun`)
For a single run:
1.  **Setup**: Initializes `ProgressTracker`, `LangfuseDataset`, and `UIServer` (if enabled).
2.  **Concurrency**: Creates an `asyncio.Semaphore` to limit parallelism.
3.  **Execution**: Iterates over items and spawns `_evaluate_item` tasks.
4.  **UI Loop**: A separate background task (`update_html`) polls `ProgressTracker` to update the Web UI.
5.  **Aggregation**: Collects results, calculates stats, and saves to CSV/JSON.

### 3.3. Item Evaluation (`_evaluate_item`)
The atomic unit of work:
1.  **Acquire Semaphore**: Respects `max_concurrency`.
2.  **Start Trace**: Enters `item.run()` context (Langfuse).
3.  **Run Task**: Awaits `task_adapter.arun(input)`.
4.  **Compute Metrics**:
    -   Collects all metric functions.
    -   Uses `asyncio.gather` to execute them **concurrently** (parallelized).
    -   Updates `ProgressObserver` with individual metric results as they finish.
5.  **Log Scores**: Sends scores to Langfuse.
6.  **Update Tracker**: Notifies `ProgressObserver` of success/failure.

## 4. Key Data Structures

-   **`EvaluatorConfig`** (`config.py`): Pydantic model for validating and typing evaluator configuration.
-   **`RunSpec`** (`config.py`): Pydantic model for a single run's specification (name, model, dataset, metrics, output_dir).
-   **`EvaluationResult`** (`results.py`): Container for all outputs. Handles stat calculation (P50/P90 latency, success rate) and file persistence (defaults to `results/` directory).

## 5. Gotchas & Implementation Details

-   **Asyncio Hygiene**:
    -   We use `nest_asyncio` to support running inside Jupyter notebooks.
    -   On Windows, we explicitly set `WindowsSelectorEventLoopPolicy` to avoid `ProactorEventLoop` issues with subprocesses/pipes.
-   **Dependency Injection**: `langfuse` and `rich` are heavy dependencies. We mock them extensively in verification scripts (`verify_refactor_*.py`) to test logic in isolation.
-   **UI Threading**: The Web UI (`UIServer`) runs in a separate thread/process context, while the TUI runs in the main loop. `ProgressTracker` bridges the gap by providing thread-safe snapshots.

## 6. Recent Refactorings (Nov 2025)

-   **Consolidation**: `_evaluate_item` and `_evaluate_item_with_status` were merged. The `arun` method no longer branches based on `show_table`; it always uses the unified logic.
-   **Delegation**: `Evaluator.run_parallel` logic was moved to `MultiModelRunner` to enforce Single Responsibility Principle.
-   **Cleanup**: `llm_eval/utils/frontend.py` was deleted (dead code).
-   **Pydantic Adoption**: Replaced ad-hoc dictionary config with `EvaluatorConfig` and `RunSpec` Pydantic models for validation.
-   **Parallel Metrics**: `_evaluate_item` now runs metrics concurrently using `asyncio.gather`.
-   **TUI Decoupling**: Introduced `ProgressObserver` protocol; `Evaluator` no longer depends on `ProgressTracker` concrete class.
-   **Clean Output**: Results are now saved to `results/` by default.

## 7. Future Roadmap Ideas
-   **Metric Parallelism**: Implemented in Nov 2025.
-   **Remote Execution**: The architecture supports swapping `TaskAdapter` for a remote runner.
