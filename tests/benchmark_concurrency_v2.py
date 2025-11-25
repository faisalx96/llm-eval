"""
Concurrency Benchmark V2 - Deep Dive into Langfuse overhead

The V1 benchmark showed observer/tracker overhead is negligible (<0.1%).
This version directly measures Langfuse SDK operations and trace context overhead.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()


# ============================================================
# TIMING ACCUMULATOR
# ============================================================

class TimingAccumulator:
    """Thread-safe timing accumulator."""

    def __init__(self):
        self.data: Dict[str, List[float]] = defaultdict(list)
        self._lock = asyncio.Lock() if True else None  # Will use sync for simplicity

    def record(self, name: str, duration: float):
        self.data[name].append(duration)

    def summary(self) -> str:
        lines = ["=" * 70, "TIMING BREAKDOWN", "=" * 70]

        sorted_items = sorted(
            self.data.items(),
            key=lambda x: sum(x[1]),
            reverse=True
        )

        total_all = sum(sum(v) for v in self.data.values())

        lines.append(f"\n{'Operation':<40} {'Calls':>8} {'Total':>12} {'Avg':>10} {'%':>8}")
        lines.append("-" * 80)

        for name, times in sorted_items:
            total = sum(times)
            avg = total / len(times) if times else 0
            pct = (total / total_all * 100) if total_all else 0
            lines.append(
                f"{name:<40} {len(times):>8} {total*1000:>11.1f}ms {avg*1000:>9.2f}ms {pct:>7.1f}%"
            )

        lines.append("-" * 80)
        lines.append(f"{'TOTAL':<40} {'':<8} {total_all*1000:>11.1f}ms")

        return "\n".join(lines)

    def reset(self):
        self.data.clear()


TIMINGS = TimingAccumulator()


# ============================================================
# INSTRUMENTED EVALUATION
# ============================================================

async def run_instrumented_evaluation(
    dataset_name: str,
    task_latency_ms: float = 100,
    max_concurrency: int = 10,
) -> Dict[str, Any]:
    """Run evaluation with fine-grained timing instrumentation."""

    from langfuse import Langfuse

    TIMINGS.reset()

    # --------------------------------------------------------
    # Phase 1: Langfuse client initialization
    # --------------------------------------------------------
    t0 = time.perf_counter()
    client = Langfuse()
    TIMINGS.record("1. Langfuse client init", time.perf_counter() - t0)

    # --------------------------------------------------------
    # Phase 2: Dataset loading
    # --------------------------------------------------------
    t0 = time.perf_counter()
    dataset = client.get_dataset(name=dataset_name)
    TIMINGS.record("2. Dataset fetch", time.perf_counter() - t0)

    t0 = time.perf_counter()
    items = list(dataset.items)
    TIMINGS.record("3. Dataset items list", time.perf_counter() - t0)

    num_items = len(items)
    print(f"   Dataset has {num_items} items")

    # --------------------------------------------------------
    # Phase 3: Evaluate items with detailed timing
    # --------------------------------------------------------
    results = []
    semaphore = asyncio.Semaphore(max_concurrency)

    async def evaluate_single_item(idx: int, item: Any) -> Dict[str, Any]:
        async with semaphore:
            item_timings = {}

            # Time: Create trace via item.run()
            t0 = time.perf_counter()
            run_context = item.run(
                run_name=f"benchmark-{datetime.now().strftime('%H%M%S')}",
                run_metadata={"item_index": idx}
            )
            item_timings["trace_context_create"] = time.perf_counter() - t0

            # Time: Enter context (this may do network I/O)
            t0 = time.perf_counter()
            trace = run_context.__enter__()
            item_timings["trace_context_enter"] = time.perf_counter() - t0

            try:
                # Time: trace.update(input=...)
                t0 = time.perf_counter()
                trace.update(input=item.input)
                item_timings["trace_update_input"] = time.perf_counter() - t0

                # Time: Actual task execution (simulated LLM call)
                t0 = time.perf_counter()
                await asyncio.sleep(task_latency_ms / 1000.0)
                output = f"Response to item {idx}"
                item_timings["task_execution"] = time.perf_counter() - t0

                # Time: trace.update(output=...)
                t0 = time.perf_counter()
                trace.update(output=output)
                item_timings["trace_update_output"] = time.perf_counter() - t0

                # Time: trace.score() calls (simulate 2 metrics)
                for metric_name in ["metric_1", "metric_2"]:
                    t0 = time.perf_counter()
                    trace.score(name=metric_name, value=1.0)
                    item_timings[f"trace_score_{metric_name}"] = time.perf_counter() - t0

            finally:
                # Time: Exit context (this may flush to Langfuse)
                t0 = time.perf_counter()
                run_context.__exit__(None, None, None)
                item_timings["trace_context_exit"] = time.perf_counter() - t0

            # Record all timings
            for name, duration in item_timings.items():
                TIMINGS.record(f"4. {name}", duration)

            return {"idx": idx, "output": output, "timings": item_timings}

    # Run all items concurrently
    t0 = time.perf_counter()
    tasks = [evaluate_single_item(i, item) for i, item in enumerate(items)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    total_eval_time = time.perf_counter() - t0

    TIMINGS.record("5. Total asyncio.gather", total_eval_time)

    # --------------------------------------------------------
    # Phase 4: Langfuse flush
    # --------------------------------------------------------
    t0 = time.perf_counter()
    client.flush()
    TIMINGS.record("6. Langfuse flush", time.perf_counter() - t0)

    return {
        "num_items": num_items,
        "results": results,
        "timings": TIMINGS.summary(),
    }


async def run_baseline_no_langfuse(
    num_items: int = 16,
    task_latency_ms: float = 100,
    max_concurrency: int = 10,
) -> Dict[str, Any]:
    """Run evaluation WITHOUT Langfuse to establish true baseline."""

    TIMINGS.reset()

    semaphore = asyncio.Semaphore(max_concurrency)

    async def evaluate_single_item(idx: int) -> str:
        async with semaphore:
            t0 = time.perf_counter()
            await asyncio.sleep(task_latency_ms / 1000.0)
            TIMINGS.record("task_execution_only", time.perf_counter() - t0)
            return f"Response to item {idx}"

    t0 = time.perf_counter()
    tasks = [evaluate_single_item(i) for i in range(num_items)]
    results = await asyncio.gather(*tasks)
    total_time = time.perf_counter() - t0

    TIMINGS.record("total_gather", total_time)

    return {
        "num_items": num_items,
        "wall_time": total_time,
        "throughput": num_items / total_time,
        "timings": TIMINGS.summary(),
    }


# ============================================================
# MAIN
# ============================================================

def print_header(text: str):
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)


async def main():
    dataset_name = "saudi-qa-verification-large"

    print_header("CONCURRENCY BENCHMARK V2 - DEEP DIVE")
    print(f"Dataset: {dataset_name}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # --------------------------------------------------------
    # Test 1: Pure async baseline (no Langfuse)
    # --------------------------------------------------------
    print_header("TEST 1: Pure Async Baseline (No Langfuse)")
    print("Running 100 items with 100ms simulated latency, no tracing...")

    t0 = time.perf_counter()
    baseline = await run_baseline_no_langfuse(
        num_items=100,
        task_latency_ms=100,
        max_concurrency=10,
    )
    baseline_wall = time.perf_counter() - t0

    print(f"\nWall time: {baseline_wall:.3f}s")
    print(f"Throughput: {baseline['throughput']:.1f} items/s")
    print(f"Theoretical min: {16/10 * 0.1:.3f}s")
    print(f"Overhead: {((baseline_wall - 0.16) / 0.16 * 100):.1f}%")
    print(baseline["timings"])

    # --------------------------------------------------------
    # Test 2: With Langfuse tracing
    # --------------------------------------------------------
    print_header("TEST 2: With Langfuse Tracing")
    print("Running same items with full Langfuse trace/score calls...")

    t0 = time.perf_counter()
    with_langfuse = await run_instrumented_evaluation(
        dataset_name=dataset_name,
        task_latency_ms=100,
        max_concurrency=10,
    )
    langfuse_wall = time.perf_counter() - t0

    print(f"\nWall time: {langfuse_wall:.3f}s")
    print(f"Throughput: {with_langfuse['num_items'] / langfuse_wall:.1f} items/s")
    print(with_langfuse["timings"])

    # --------------------------------------------------------
    # Test 3: Higher concurrency with Langfuse
    # --------------------------------------------------------
    print_header("TEST 3: Higher Concurrency (50) with Langfuse")

    t0 = time.perf_counter()
    high_conc = await run_instrumented_evaluation(
        dataset_name=dataset_name,
        task_latency_ms=100,
        max_concurrency=20,
    )
    high_conc_wall = time.perf_counter() - t0

    print(f"\nWall time: {high_conc_wall:.3f}s")
    print(f"Throughput: {high_conc['num_items'] / high_conc_wall:.1f} items/s")
    print(high_conc["timings"])

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------
    print_header("SUMMARY: LANGFUSE OVERHEAD ANALYSIS")

    langfuse_overhead = langfuse_wall - baseline_wall
    langfuse_overhead_pct = (langfuse_overhead / baseline_wall) * 100

    print(f"Baseline (no Langfuse):     {baseline_wall:.3f}s")
    print(f"With Langfuse:              {langfuse_wall:.3f}s")
    print(f"Langfuse overhead:          {langfuse_overhead:.3f}s ({langfuse_overhead_pct:.1f}%)")
    print(f"\nThis overhead comes from:")
    print(f"  - trace.update() calls")
    print(f"  - trace.score() calls")
    print(f"  - Context manager enter/exit")
    print(f"  - SDK batching/flushing")


if __name__ == "__main__":
    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
        print("ERROR: LANGFUSE_PUBLIC_KEY required")
        sys.exit(1)

    asyncio.run(main())
