"""Standalone overhead benchmark for task vs qym vs qym+platform coupling.

Run from the repo root:

    python tests/profile_overhead_breakdown.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from collections import defaultdict
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = REPO_ROOT / "packages" / "sdk"
PLATFORM_ROOT = REPO_ROOT / "packages" / "platform"
for _path in (str(SDK_ROOT), str(PLATFORM_ROOT), str(REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import qym.core.evaluator as evaluator_module
import qym.core.otel as otel_module
from qym.core.evaluator import Evaluator
from qym.platform import client as client_module


@dataclass(frozen=True)
class MemoryItem:
    id: str
    input: Dict[str, Any]
    expected_output: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class MemoryDataset:
    def __init__(self, items: List[MemoryItem], name: str = "overhead-breakdown") -> None:
        self._items = list(items)
        self.name = name
        self.dataset_name = name

    def get_items(self) -> List[MemoryItem]:
        return list(self._items)


class TimingHarness:
    def __init__(self) -> None:
        self._active_phase: Optional[str] = None
        self.totals: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def set_phase(self, phase: Optional[str]) -> None:
        self._active_phase = phase

    def record(self, key: str, duration: float) -> None:
        phase = self._active_phase
        if phase is None:
            return
        self.totals[phase][key] += duration
        self.counts[phase][key] += 1

    def per_run_total(self, phase: str, key: str, repeat_count: int) -> float:
        return self.totals[phase].get(key, 0.0) / float(repeat_count)

    def total_count(self, phase: str, key: str) -> int:
        return self.counts[phase].get(key, 0)


def install_timing_wrappers(stack: ExitStack, harness: TimingHarness) -> None:
    def wrap_sync(target: Any, attr_name: str, metric_name: str) -> None:
        original = getattr(target, attr_name)

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                harness.record(metric_name, time.perf_counter() - started)

        stack.enter_context(patch.object(target, attr_name, wrapped))

    def wrap_async(target: Any, attr_name: str, metric_name: str) -> None:
        original = getattr(target, attr_name)

        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                return await original(*args, **kwargs)
            finally:
                harness.record(metric_name, time.perf_counter() - started)

        stack.enter_context(patch.object(target, attr_name, wrapped))

    wrap_async(Evaluator, "_execute_task", "evaluator.execute_task")
    wrap_async(Evaluator, "_compute_metrics", "evaluator.compute_metrics")
    wrap_async(Evaluator, "_emit_item_started", "evaluator.emit_item_started")
    wrap_sync(Evaluator, "_update_tracker", "evaluator.update_tracker")
    wrap_async(Evaluator, "_emit_item_completed", "evaluator.emit_item_completed")
    wrap_sync(client_module.PlatformClient, "create_run", "platform.create_run")
    wrap_sync(client_module.PlatformEventStream, "__init__", "platform.stream_init")
    wrap_async(client_module.PlatformEventStream, "aemit", "platform.emit")
    wrap_sync(client_module.PlatformEventStream, "close", "platform.close")


def make_task_under_test(task_duration_s: float):
    async def task_under_test(input_data: Dict[str, Any], model: Optional[str] = None) -> str:
        del model
        await asyncio.sleep(task_duration_s)
        return f"answer::{input_data['question']}"

    return task_under_test


async def measure_raw_task(
    items: List[MemoryItem],
    *,
    task: Any,
    repeat_count: int,
    concurrency: int,
) -> Dict[str, float]:
    wall_runs: List[float] = []
    summed_item_runs: List[float] = []

    async def run_one_pass() -> float:
        semaphore = asyncio.Semaphore(concurrency)
        item_durations: List[float] = []

        async def run_item(item: MemoryItem) -> str:
            async with semaphore:
                item_started = time.perf_counter()
                try:
                    return await task(item.input)
                finally:
                    item_durations.append(time.perf_counter() - item_started)

        await asyncio.gather(*(run_item(item) for item in items))
        return sum(item_durations)

    for _ in range(repeat_count):
        started = time.perf_counter()
        summed_item_runs.append(await run_one_pass())
        wall_runs.append(time.perf_counter() - started)
    return {
        "wall_time_s": sum(wall_runs) / len(wall_runs),
        "summed_item_time_s": sum(summed_item_runs) / len(summed_item_runs),
    }


async def run_qym_case(
    dataset: MemoryDataset,
    *,
    task: Any,
    repeat_count: int,
    concurrency: int,
    with_platform: bool,
    phase_name: str,
    harness: TimingHarness,
) -> Dict[str, Any]:
    wall_times: List[float] = []
    results = []

    for run_idx in range(repeat_count):
        config = {
            "run_name": f"overhead-{('platform' if with_platform else 'sdk')}-{run_idx}",
            "max_concurrency": concurrency,
            "max_metric_concurrency": 1,
            "max_retries": 0,
            "checkpoint_enabled": False,
            "otel_enabled": False,
        }
        if with_platform:
            config["platform_api_key"] = "test-api-key"
            config["platform_url"] = "https://platform.example"

        evaluator = Evaluator(
            task=task,
            dataset=dataset,
            metrics=[],
            config=config,
            langfuse_client=None,
        )
        evaluator.total_items = len(dataset.get_items())

        harness.set_phase(phase_name)
        started = time.perf_counter()
        result = await evaluator.arun(show_tui=False, auto_save=False)
        wall_times.append(time.perf_counter() - started)
        harness.set_phase(None)
        results.append(result)

    return {
        "wall_time_s": sum(wall_times) / len(wall_times),
        "results": results,
    }


def pct(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return (numerator / denominator) * 100.0


def ms_label(seconds: float) -> str:
    return f"{seconds * 1000:.0f}ms"


def format_breakdown_lines(breakdown: Dict[str, float], *, indent: str = "  ") -> List[str]:
    rows = sorted(breakdown.items(), key=lambda item: item[1], reverse=True)
    return [f"{indent}{name:<24} {value * 1000:.1f} ms" for name, value in rows]


def format_report(report: Dict[str, Any]) -> str:
    lines = [
        "Summary by task duration:",
        f"  Concurrency: {report['concurrency']}  Items: {report['items_count']}",
        "  Run columns are wall-clock time for the whole batch.",
        "  Task/item columns are average per-item execution time, not batch wall time divided by item count.",
        "",
        "  Task      Raw run      Raw task/item  SDK run      SDK task/item  Plat run     SDK add      Plat delta",
        "  --------  -----------  -------------  -----------  -------------  -----------  -----------  -----------",
    ]
    for case in report["cases"]:
        lines.append(
            "  "
            f"{ms_label(case['task_duration_s']):<8}  "
            f"{case['raw_task_wall_s'] * 1000:>9.1f} ms  "
            f"{case['raw_task_avg_item_s'] * 1000:>11.1f} ms  "
            f"{case['qym_sdk_wall_s'] * 1000:>7.1f} ms  "
            f"{case['qym_sdk_task_avg_item_s'] * 1000:>11.1f} ms  "
            f"{case['qym_platform_wall_s'] * 1000:>8.1f} ms  "
            f"{case['sdk_overhead_s'] * 1000:>6.1f} ms ({case['sdk_overhead_pct_of_raw']:>5.1f}%)  "
            f"{case['platform_overhead_s'] * 1000:>7.1f} ms ({case['platform_overhead_pct_of_raw']:>5.1f}%)"
        )

    if any(case["platform_overhead_s"] < 0 for case in report["cases"]):
        lines.append("")
        lines.append("Note: a negative platform delta on one row means wall-clock jitter.")
        lines.append("Use the per-duration platform breakdown below to see actual coupling work.")

    lines.append("")
    lines.append("Breakdown by duration:")
    for case in report["cases"]:
        lines.append(
            f"  {ms_label(case['task_duration_s'])} task "
            f"(items={case['item_count']}, repeats={case['repeat_count']}):"
        )
        lines.append("    SDK avg per item:")
        lines.extend(format_breakdown_lines(case["sdk_breakdown"], indent="      "))
        lines.append("    Platform per run:")
        lines.extend(format_breakdown_lines(case["platform_breakdown"], indent="      "))
    return "\n".join(lines)


def build_duration_plan(duration_ms_values: List[float]) -> List[Dict[str, float]]:
    plan = []
    for value_ms in duration_ms_values:
        if value_ms <= 10:
            repeat_count = 3
        elif value_ms <= 50:
            repeat_count = 2
        else:
            repeat_count = 1
        plan.append({"task_duration_s": value_ms / 1000.0, "repeat_count": repeat_count})
    return plan


async def run_benchmark(items_count: int, duration_ms_values: List[float], concurrency: int) -> Dict[str, Any]:
    items = [
        MemoryItem(
            id=f"item-{idx}",
            input={"question": f"question {idx}"},
            expected_output=f"answer::question {idx}",
            metadata={"bucket": idx % 3},
        )
        for idx in range(items_count)
    ]
    dataset = MemoryDataset(items)
    duration_plan = build_duration_plan(duration_ms_values)

    reports = []
    harness = TimingHarness()

    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {}, clear=False))
        os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
        os.environ.pop("LANGFUSE_SECRET_KEY", None)
        os.environ.pop("QYM_API_KEY", None)
        stack.enter_context(
            patch.object(
                otel_module,
                "create_otel_manager",
                lambda config: otel_module.NullOtelManager(),
            )
        )
        stack.enter_context(
            patch.object(
                evaluator_module,
                "_detect_git_info",
                lambda config=None: {"git_branch": None, "git_commit": None},
            )
        )
        stack.enter_context(
            patch.object(
                client_module,
                "_post_json",
                lambda url, payload, api_key, timeout=30: {
                    "run_id": "platform-run-1",
                    "live_url": "https://platform.example/runs/platform-run-1",
                },
            )
        )
        stack.enter_context(
            patch.object(
                client_module,
                "_post_ndjson",
                lambda url, ndjson, api_key, timeout=30: None,
            )
        )
        install_timing_wrappers(stack, harness)

        for plan in duration_plan:
            repeat_count = int(plan["repeat_count"])
            task_duration_s = float(plan["task_duration_s"])
            task = make_task_under_test(task_duration_s)
            sdk_phase = f"sdk:{task_duration_s}"
            platform_phase = f"platform:{task_duration_s}"

            raw_task = await measure_raw_task(
                items,
                task=task,
                repeat_count=repeat_count,
                concurrency=concurrency,
            )
            raw_task_wall_s = raw_task["wall_time_s"]
            raw_task_summed_item_s = raw_task["summed_item_time_s"]
            sdk_case = await run_qym_case(
                dataset,
                task=task,
                repeat_count=repeat_count,
                concurrency=concurrency,
                with_platform=False,
                phase_name=sdk_phase,
                harness=harness,
            )
            platform_case = await run_qym_case(
                dataset,
                task=task,
                repeat_count=repeat_count,
                concurrency=concurrency,
                with_platform=True,
                phase_name=platform_phase,
                harness=harness,
            )

            for result in sdk_case["results"] + platform_case["results"]:
                if result.total_items != len(items):
                    raise RuntimeError(f"Unexpected total_items: {result.total_items} != {len(items)}")
                if result.errors:
                    raise RuntimeError(f"Run contained errors: {result.errors}")
                if len(result.results) != len(items):
                    raise RuntimeError(f"Unexpected result count: {len(result.results)} != {len(items)}")

            sdk_wall_s = sdk_case["wall_time_s"]
            platform_wall_s = platform_case["wall_time_s"]
            sdk_overhead_s = sdk_wall_s - raw_task_wall_s
            platform_overhead_s = platform_wall_s - sdk_wall_s

            sdk_emit_started_s = harness.per_run_total(sdk_phase, "evaluator.emit_item_started", repeat_count)
            sdk_execute_task_s = harness.per_run_total(sdk_phase, "evaluator.execute_task", repeat_count)
            sdk_compute_metrics_s = harness.per_run_total(sdk_phase, "evaluator.compute_metrics", repeat_count)
            sdk_update_tracker_s = harness.per_run_total(sdk_phase, "evaluator.update_tracker", repeat_count)
            sdk_emit_completed_s = harness.per_run_total(sdk_phase, "evaluator.emit_item_completed", repeat_count)

            sdk_breakdown = {
                "task_wrapper_overhead_per_item_s": max(0.0, sdk_execute_task_s - raw_task_summed_item_s) / len(items),
                "tracker_overhead_per_item_s": sdk_update_tracker_s / len(items),
                "item_start_overhead_per_item_s": sdk_emit_started_s / len(items),
                "item_complete_overhead_per_item_s": sdk_emit_completed_s / len(items),
                "metrics_overhead_per_item_s": sdk_compute_metrics_s / len(items),
            }

            platform_create_run_s = harness.per_run_total(platform_phase, "platform.create_run", repeat_count)
            platform_stream_init_s = harness.per_run_total(platform_phase, "platform.stream_init", repeat_count)
            platform_emit_s = harness.per_run_total(platform_phase, "platform.emit", repeat_count)
            platform_close_s = harness.per_run_total(platform_phase, "platform.close", repeat_count)

            platform_breakdown = {
                "event_emit_s": platform_emit_s,
                "create_run_s": platform_create_run_s,
                "stream_close_s": platform_close_s,
                "stream_init_s": platform_stream_init_s,
            }
            platform_breakdown["run_residual_s"] = platform_overhead_s - sum(platform_breakdown.values())

            expected_emit_calls = repeat_count * ((4 * len(items)) + 2)
            actual_emit_calls = harness.total_count(platform_phase, "platform.emit")
            if actual_emit_calls != expected_emit_calls:
                raise RuntimeError(
                    f"Unexpected platform emit count for {task_duration_s}s: "
                    f"{actual_emit_calls} != {expected_emit_calls}"
                )

            reports.append(
                {
                    "task_duration_s": task_duration_s,
                    "repeat_count": repeat_count,
                    "item_count": len(items),
                    "raw_task_wall_s": raw_task_wall_s,
                    "raw_task_summed_item_s": raw_task_summed_item_s,
                    "raw_task_avg_item_s": raw_task_summed_item_s / len(items),
                    "qym_sdk_wall_s": sdk_wall_s,
                    "qym_sdk_task_avg_item_s": sdk_execute_task_s / len(items),
                    "qym_platform_wall_s": platform_wall_s,
                    "sdk_overhead_s": sdk_overhead_s,
                    "platform_overhead_s": platform_overhead_s,
                    "sdk_overhead_pct_of_raw": pct(sdk_overhead_s, raw_task_wall_s),
                    "platform_overhead_pct_of_raw": pct(platform_overhead_s, raw_task_wall_s),
                    "sdk_breakdown": sdk_breakdown,
                    "platform_breakdown": platform_breakdown,
                    "platform_emit_calls": actual_emit_calls,
                }
            )

    return {"cases": reports, "concurrency": concurrency, "items_count": items_count}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure qym SDK/platform overhead across task durations.")
    parser.add_argument(
        "--items",
        type=int,
        default=4,
        help="Number of synthetic dataset items to run for each duration.",
    )
    parser.add_argument(
        "--durations-ms",
        type=str,
        default="1,10,50,200,1000",
        help="Comma-separated synthetic task durations in milliseconds.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Task concurrency for both the raw baseline and qym runs.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    duration_ms_values = [float(part.strip()) for part in args.durations_ms.split(",") if part.strip()]
    report = await run_benchmark(
        items_count=args.items,
        duration_ms_values=duration_ms_values,
        concurrency=args.concurrency,
    )
    print()
    print("OVERHEAD BREAKDOWN")
    print(format_report(report))


if __name__ == "__main__":
    asyncio.run(main())
