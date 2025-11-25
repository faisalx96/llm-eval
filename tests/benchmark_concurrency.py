"""
Concurrency Benchmark for LLM-Eval

Measures actual parallelism loss due to synchronous blocking in the evaluation pipeline.

Tests:
1. Single large evaluation run - baseline throughput
2. 3x concurrent evaluation runs - measures parallelism scaling
3. Instrumented runs - identifies blocking hotspots

Usage:
    python -m tests.benchmark_concurrency

Requires:
    - LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in environment
    - Access to "saudi-qa-verification-v1" dataset in Langfuse
"""

from __future__ import annotations

import asyncio
import functools
import os
import statistics
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

# ============================================================
# INSTRUMENTATION
# ============================================================

@dataclass
class TimingStats:
    """Accumulates timing measurements for a single call site."""
    name: str
    calls: int = 0
    total_time: float = 0.0
    min_time: float = float('inf')
    max_time: float = 0.0
    samples: List[float] = field(default_factory=list)

    def record(self, duration: float) -> None:
        self.calls += 1
        self.total_time += duration
        self.min_time = min(self.min_time, duration)
        self.max_time = max(self.max_time, duration)
        if len(self.samples) < 1000:  # Cap memory
            self.samples.append(duration)

    @property
    def avg_time(self) -> float:
        return self.total_time / self.calls if self.calls else 0.0

    @property
    def std_time(self) -> float:
        if len(self.samples) < 2:
            return 0.0
        return statistics.stdev(self.samples)

    def __repr__(self) -> str:
        return (f"{self.name}: {self.calls} calls, "
                f"total={self.total_time*1000:.1f}ms, "
                f"avg={self.avg_time*1000:.2f}ms, "
                f"std={self.std_time*1000:.2f}ms")


class InstrumentationContext:
    """Global context for collecting timing data."""

    def __init__(self):
        self.stats: Dict[str, TimingStats] = {}
        self.enabled = False
        self.event_loop_blocks: List[Tuple[float, str]] = []
        self._original_methods: Dict[str, Callable] = {}

    def reset(self) -> None:
        self.stats.clear()
        self.event_loop_blocks.clear()

    def get_or_create(self, name: str) -> TimingStats:
        if name not in self.stats:
            self.stats[name] = TimingStats(name=name)
        return self.stats[name]

    def record(self, name: str, duration: float) -> None:
        if self.enabled:
            self.get_or_create(name).record(duration)

    def record_block(self, duration: float, location: str) -> None:
        if self.enabled and duration > 0.001:  # > 1ms
            self.event_loop_blocks.append((duration, location))

    def summary(self) -> str:
        lines = ["=" * 60, "INSTRUMENTATION SUMMARY", "=" * 60]

        sorted_stats = sorted(
            self.stats.values(),
            key=lambda s: s.total_time,
            reverse=True
        )

        total_blocked = sum(s.total_time for s in sorted_stats)

        lines.append(f"\nTotal measured blocking time: {total_blocked*1000:.1f}ms\n")
        lines.append(f"{'Call Site':<40} {'Calls':>8} {'Total':>10} {'Avg':>10} {'Max':>10}")
        lines.append("-" * 80)

        for stat in sorted_stats[:15]:  # Top 15
            pct = (stat.total_time / total_blocked * 100) if total_blocked else 0
            lines.append(
                f"{stat.name:<40} {stat.calls:>8} "
                f"{stat.total_time*1000:>9.1f}ms "
                f"{stat.avg_time*1000:>9.2f}ms "
                f"{stat.max_time*1000:>9.2f}ms "
                f"({pct:>5.1f}%)"
            )

        if self.event_loop_blocks:
            lines.append(f"\nEvent loop blocks > 1ms: {len(self.event_loop_blocks)}")
            total_block_time = sum(b[0] for b in self.event_loop_blocks)
            lines.append(f"Total event loop block time: {total_block_time*1000:.1f}ms")

        return "\n".join(lines)


# Global instrumentation context
INSTRUMENT = InstrumentationContext()


def timed(name: str):
    """Decorator to time function calls."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                INSTRUMENT.record(name, time.perf_counter() - start)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return await func(*args, **kwargs)
            finally:
                INSTRUMENT.record(name, time.perf_counter() - start)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper
    return decorator


@contextmanager
def timed_block(name: str):
    """Context manager to time a block of code."""
    start = time.perf_counter()
    try:
        yield
    finally:
        INSTRUMENT.record(name, time.perf_counter() - start)


# ============================================================
# MONKEY PATCHING FOR INSTRUMENTATION
# ============================================================

def patch_evaluator_for_instrumentation():
    """Patch Evaluator methods to collect timing data."""
    from llm_eval.core.evaluator import Evaluator
    from llm_eval.core.progress import ProgressTracker
    from llm_eval.core.dashboard import RunDashboard

    # Patch _notify_observer
    original_notify = Evaluator._notify_observer
    def patched_notify(self, method: str, **payload):
        start = time.perf_counter()
        result = original_notify(self, method, **payload)
        INSTRUMENT.record(f"_notify_observer.{method}", time.perf_counter() - start)
        return result
    Evaluator._notify_observer = patched_notify
    INSTRUMENT._original_methods['_notify_observer'] = original_notify

    # Patch ProgressTracker methods
    for method_name in ['start_item', 'update_output', 'set_metric_computing',
                        'update_metric', 'complete_item', 'fail_item', 'get_snapshot']:
        if hasattr(ProgressTracker, method_name):
            original = getattr(ProgressTracker, method_name)
            def make_patched(orig, name):
                def patched(self, *args, **kwargs):
                    start = time.perf_counter()
                    result = orig(self, *args, **kwargs)
                    INSTRUMENT.record(f"tracker.{name}", time.perf_counter() - start)
                    return result
                return patched
            setattr(ProgressTracker, method_name, make_patched(original, method_name))
            INSTRUMENT._original_methods[f'tracker.{method_name}'] = original

    # Patch dashboard methods
    for method_name in ['record_item_start', 'record_item_complete', 'record_metric',
                        'refresh', 'render']:
        if hasattr(RunDashboard, method_name):
            original = getattr(RunDashboard, method_name)
            def make_patched(orig, name):
                def patched(self, *args, **kwargs):
                    start = time.perf_counter()
                    result = orig(self, *args, **kwargs)
                    INSTRUMENT.record(f"dashboard.{name}", time.perf_counter() - start)
                    return result
                return patched
            setattr(RunDashboard, method_name, make_patched(original, method_name))
            INSTRUMENT._original_methods[f'dashboard.{method_name}'] = original


def patch_langfuse_for_instrumentation():
    """Patch Langfuse trace methods to collect timing data."""
    try:
        from langfuse import Langfuse
        from langfuse.client import StatefulTraceClient, StatefulSpanClient

        # Patch trace.update
        for cls in [StatefulTraceClient, StatefulSpanClient]:
            if hasattr(cls, 'update'):
                original = cls.update
                def make_patched(orig):
                    def patched(self, *args, **kwargs):
                        start = time.perf_counter()
                        result = orig(self, *args, **kwargs)
                        INSTRUMENT.record("langfuse.trace.update", time.perf_counter() - start)
                        return result
                    return patched
                cls.update = make_patched(original)

            if hasattr(cls, 'score'):
                original = cls.score
                def make_patched(orig):
                    def patched(self, *args, **kwargs):
                        start = time.perf_counter()
                        result = orig(self, *args, **kwargs)
                        INSTRUMENT.record("langfuse.trace.score", time.perf_counter() - start)
                        return result
                    return patched
                cls.score = make_patched(original)
    except ImportError:
        print("Warning: Could not patch Langfuse for instrumentation")


# ============================================================
# BENCHMARK TASKS
# ============================================================

def create_test_task(latency_ms: float = 100, variance_ms: float = 20):
    """Create a test task with configurable latency."""
    import random

    def task(input_data: Any, model: Optional[str] = None) -> str:
        """Simulated LLM task with controlled latency."""
        # Simulate variable LLM response time
        actual_latency = latency_ms + random.uniform(-variance_ms, variance_ms)
        time.sleep(actual_latency / 1000.0)

        question = input_data.get('question', str(input_data)) if isinstance(input_data, dict) else str(input_data)
        model_tag = f"[{model}]" if model else "[default]"
        return f"{model_tag} Response to: {question[:50]}"

    return task


async def create_async_test_task(latency_ms: float = 100, variance_ms: float = 20):
    """Create an async test task with configurable latency."""
    import random

    async def task(input_data: Any, model: Optional[str] = None) -> str:
        """Async simulated LLM task with controlled latency."""
        actual_latency = latency_ms + random.uniform(-variance_ms, variance_ms)
        await asyncio.sleep(actual_latency / 1000.0)

        question = input_data.get('question', str(input_data)) if isinstance(input_data, dict) else str(input_data)
        model_tag = f"[{model}]" if model else "[default]"
        return f"{model_tag} Response to: {question[:50]}"

    return task


# ============================================================
# BENCHMARK RUNNERS
# ============================================================

@dataclass
class BenchmarkResult:
    """Results from a single benchmark run."""
    name: str
    wall_time: float
    items_processed: int
    throughput: float  # items/second
    theoretical_min: float  # best possible time
    overhead_pct: float  # (actual - theoretical) / theoretical * 100
    instrumentation: Optional[str] = None

    def __repr__(self) -> str:
        return (f"{self.name}: {self.wall_time:.2f}s, "
                f"{self.throughput:.1f} items/s, "
                f"overhead={self.overhead_pct:.1f}%")


def run_single_evaluation(
    dataset_name: str,
    task_latency_ms: float = 100,
    max_concurrency: int = 10,
    use_async_task: bool = False,
    instrument: bool = False,
    show_ui: bool = False,
) -> BenchmarkResult:
    """Run a single evaluation and measure performance."""
    from llm_eval import Evaluator

    # Reset instrumentation
    if instrument:
        INSTRUMENT.enabled = True
        INSTRUMENT.reset()

    # Create task
    if use_async_task:
        async def async_task(input_data, model=None):
            import random
            actual_latency = task_latency_ms + random.uniform(-20, 20)
            await asyncio.sleep(actual_latency / 1000.0)
            q = input_data.get('question', str(input_data)) if isinstance(input_data, dict) else str(input_data)
            return f"[{model or 'default'}] {q[:50]}"
        task = async_task
    else:
        task = create_test_task(latency_ms=task_latency_ms)

    # Simple metric
    def length_check(output, expected):
        return 1.0 if len(str(output)) > 0 else 0.0

    evaluator = Evaluator(
        task=task,
        dataset=dataset_name,
        metrics=[length_check, "exact_match"],
        config={
            "max_concurrency": max_concurrency,
            "run_name": f"benchmark-{datetime.now().strftime('%H%M%S')}",
        }
    )

    # Get item count
    num_items = len(evaluator.dataset.get_items())

    # Calculate theoretical minimum
    theoretical_min = (num_items / max_concurrency) * (task_latency_ms / 1000.0)

    # Run and measure
    start = time.perf_counter()
    result = evaluator.run(show_progress=show_ui, show_table=show_ui, auto_save=False)
    wall_time = time.perf_counter() - start

    throughput = num_items / wall_time
    overhead_pct = ((wall_time - theoretical_min) / theoretical_min) * 100

    instrumentation_summary = INSTRUMENT.summary() if instrument else None
    INSTRUMENT.enabled = False

    return BenchmarkResult(
        name="single_run",
        wall_time=wall_time,
        items_processed=num_items,
        throughput=throughput,
        theoretical_min=theoretical_min,
        overhead_pct=overhead_pct,
        instrumentation=instrumentation_summary,
    )


def run_concurrent_evaluations(
    dataset_name: str,
    num_concurrent: int = 3,
    task_latency_ms: float = 100,
    max_concurrency_per_run: int = 10,
    instrument: bool = False,
    show_ui: bool = False,
) -> BenchmarkResult:
    """Run N concurrent evaluations and measure total performance."""
    from llm_eval import Evaluator

    if instrument:
        INSTRUMENT.enabled = True
        INSTRUMENT.reset()

    # Create distinct tasks for each run
    def make_task(run_id: int):
        def task(input_data, model=None):
            import random
            actual_latency = task_latency_ms + random.uniform(-20, 20)
            time.sleep(actual_latency / 1000.0)
            q = input_data.get('question', str(input_data)) if isinstance(input_data, dict) else str(input_data)
            return f"[run{run_id}:{model or 'default'}] {q[:50]}"
        return task

    def length_check(output, expected):
        return 1.0 if len(str(output)) > 0 else 0.0

    runs = []
    for i in range(num_concurrent):
        runs.append({
            "name": f"concurrent-run-{i+1}",
            "task": make_task(i+1),
            "dataset": dataset_name,
            "metrics": [length_check, "exact_match"],
            "config": {
                "max_concurrency": max_concurrency_per_run,
            }
        })

    # Get item count from first run's dataset
    from llm_eval.core.dataset import LangfuseDataset
    from langfuse import Langfuse
    client = Langfuse()
    ds = LangfuseDataset(client, dataset_name)
    num_items_per_run = len(ds.get_items())
    total_items = num_items_per_run * num_concurrent

    # Theoretical minimum: all runs share the same wall time if truly parallel
    # Each run takes (items / concurrency) * latency
    # With concurrent runs, theoretical = single run time (they overlap)
    theoretical_min_single = (num_items_per_run / max_concurrency_per_run) * (task_latency_ms / 1000.0)
    theoretical_min = theoretical_min_single  # If truly parallel, same as single

    # Run and measure
    start = time.perf_counter()
    results = Evaluator.run_parallel(
        runs=runs,
        show_tui=show_ui,
        auto_save=False,
        print_summary=False,
    )
    wall_time = time.perf_counter() - start

    throughput = total_items / wall_time
    overhead_pct = ((wall_time - theoretical_min) / theoretical_min) * 100

    instrumentation_summary = INSTRUMENT.summary() if instrument else None
    INSTRUMENT.enabled = False

    return BenchmarkResult(
        name=f"concurrent_{num_concurrent}x",
        wall_time=wall_time,
        items_processed=total_items,
        throughput=throughput,
        theoretical_min=theoretical_min,
        overhead_pct=overhead_pct,
        instrumentation=instrumentation_summary,
    )


# ============================================================
# MAIN BENCHMARK SUITE
# ============================================================

def print_header(text: str):
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)


def print_result_table(results: List[BenchmarkResult]):
    """Print results as a formatted table."""
    print(f"\n{'Scenario':<25} {'Wall Time':>10} {'Items':>8} {'Throughput':>12} {'Overhead':>10}")
    print("-" * 70)
    for r in results:
        print(f"{r.name:<25} {r.wall_time:>9.2f}s {r.items_processed:>8} {r.throughput:>11.1f}/s {r.overhead_pct:>9.1f}%")


def run_full_benchmark(dataset_name: str = "saudi-qa-verification-v1"):
    """Run the complete benchmark suite."""

    print_header("LLM-EVAL CONCURRENCY BENCHMARK")
    print(f"Dataset: {dataset_name}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Apply instrumentation patches
    print("\nApplying instrumentation patches...")
    patch_evaluator_for_instrumentation()
    patch_langfuse_for_instrumentation()

    results: List[BenchmarkResult] = []

    # --------------------------------------------------------
    # Test 1: Single run baseline (sync task)
    # --------------------------------------------------------
    print_header("TEST 1: Single Run Baseline (Sync Task)")
    print("Running single evaluation with sync task function...")

    result_single_sync = run_single_evaluation(
        dataset_name=dataset_name,
        task_latency_ms=100,
        max_concurrency=10,
        use_async_task=False,
        instrument=True,
        show_ui=False,
    )
    results.append(result_single_sync)
    print(f"\nResult: {result_single_sync}")
    if result_single_sync.instrumentation:
        print(result_single_sync.instrumentation)

    # --------------------------------------------------------
    # Test 2: Single run baseline (async task)
    # --------------------------------------------------------
    print_header("TEST 2: Single Run Baseline (Async Task)")
    print("Running single evaluation with async task function...")

    result_single_async = run_single_evaluation(
        dataset_name=dataset_name,
        task_latency_ms=100,
        max_concurrency=10,
        use_async_task=True,
        instrument=True,
        show_ui=False,
    )
    results.append(result_single_async)
    print(f"\nResult: {result_single_async}")
    if result_single_async.instrumentation:
        print(result_single_async.instrumentation)

    # --------------------------------------------------------
    # Test 3: 3x Concurrent runs
    # --------------------------------------------------------
    print_header("TEST 3: 3x Concurrent Runs")
    print("Running 3 evaluations concurrently...")

    result_concurrent = run_concurrent_evaluations(
        dataset_name=dataset_name,
        num_concurrent=3,
        task_latency_ms=100,
        max_concurrency_per_run=10,
        instrument=True,
        show_ui=False,
    )
    results.append(result_concurrent)
    print(f"\nResult: {result_concurrent}")
    if result_concurrent.instrumentation:
        print(result_concurrent.instrumentation)

    # --------------------------------------------------------
    # Test 4: Scaling test - higher concurrency
    # --------------------------------------------------------
    print_header("TEST 4: High Concurrency Single Run")
    print("Running single evaluation with max_concurrency=50...")

    result_high_conc = run_single_evaluation(
        dataset_name=dataset_name,
        task_latency_ms=100,
        max_concurrency=50,
        use_async_task=True,
        instrument=True,
        show_ui=False,
    )
    results.append(result_high_conc)
    print(f"\nResult: {result_high_conc}")

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------
    print_header("BENCHMARK SUMMARY")
    print_result_table(results)

    # Calculate parallelism efficiency
    if len(results) >= 3:
        single_throughput = results[1].throughput  # async single
        concurrent_throughput = results[2].throughput

        # Ideal: 3x concurrent should have 3x throughput
        ideal_concurrent_throughput = single_throughput * 3
        parallelism_efficiency = (concurrent_throughput / ideal_concurrent_throughput) * 100

        print(f"\n{'='*70}")
        print("PARALLELISM ANALYSIS")
        print(f"{'='*70}")
        print(f"Single run throughput:      {single_throughput:.1f} items/s")
        print(f"3x concurrent throughput:   {concurrent_throughput:.1f} items/s")
        print(f"Ideal 3x throughput:        {ideal_concurrent_throughput:.1f} items/s")
        print(f"Parallelism efficiency:     {parallelism_efficiency:.1f}%")
        print(f"Parallelism loss:           {100 - parallelism_efficiency:.1f}%")

        if parallelism_efficiency < 80:
            print("\n[WARNING] Significant parallelism loss detected!")
            print("Primary suspects:")
            print("  - Synchronous observer callbacks blocking event loop")
            print("  - Synchronous Langfuse SDK calls")
            print("  - Synchronous tracker updates")

    print(f"\nBenchmark completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return results


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    # Check for required environment variables
    if not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY"):
        print("ERROR: LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must be set")
        print("Please set these environment variables or create a .env file")
        sys.exit(1)

    # Run benchmark
    run_full_benchmark()
