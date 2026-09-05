import asyncio
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

import qym.core.evaluator as evaluator_module
import qym.core.otel as otel_module
from qym.core.evaluator import Evaluator
from qym.platform import client as client_module


@dataclass(frozen=True)
class _MemoryItem:
    id: str
    input: Dict[str, Any]
    expected_output: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class _MemoryDataset:
    def __init__(self, items: List[_MemoryItem], name: str = "overhead-breakdown") -> None:
        self._items = list(items)
        self.name = name
        self.dataset_name = name

    def get_items(self) -> List[_MemoryItem]:
        return list(self._items)


class _TimingHarness:
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


def _install_timing_wrappers(monkeypatch: pytest.MonkeyPatch, harness: _TimingHarness) -> None:
    def wrap_sync(target: Any, attr_name: str, metric_name: str) -> None:
        original = getattr(target, attr_name)

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                harness.record(metric_name, time.perf_counter() - started)

        monkeypatch.setattr(target, attr_name, wrapped)

    def wrap_async(target: Any, attr_name: str, metric_name: str) -> None:
        original = getattr(target, attr_name)

        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                return await original(*args, **kwargs)
            finally:
                harness.record(metric_name, time.perf_counter() - started)

        monkeypatch.setattr(target, attr_name, wrapped)

    wrap_async(Evaluator, "_execute_task", "evaluator.execute_task")
    wrap_async(Evaluator, "_compute_metrics", "evaluator.compute_metrics")
    wrap_async(Evaluator, "_emit_item_started", "evaluator.emit_item_started")
    wrap_sync(Evaluator, "_update_tracker", "evaluator.update_tracker")
    wrap_async(Evaluator, "_emit_item_completed", "evaluator.emit_item_completed")
    wrap_sync(client_module.PlatformClient, "create_run", "platform.create_run")
    wrap_sync(client_module.PlatformEventStream, "__init__", "platform.stream_init")
    wrap_async(client_module.PlatformEventStream, "aemit", "platform.emit")
    wrap_sync(client_module.PlatformEventStream, "close", "platform.close")


def _make_task_under_test(task_duration_s: float):
    async def _task_under_test(input_data: Dict[str, Any], model: Optional[str] = None) -> str:
        del model
        await asyncio.sleep(task_duration_s)
        return f"answer::{input_data['question']}"

    return _task_under_test


async def _measure_raw_task(items: List[_MemoryItem], *, task: Any, repeat_count: int) -> float:
    runs: List[float] = []
    for _ in range(repeat_count):
        started = time.perf_counter()
        for item in items:
            await task(item.input)
        runs.append(time.perf_counter() - started)
    return sum(runs) / len(runs)


async def _run_qym_case(
    dataset: _MemoryDataset,
    *,
    task: Any,
    repeat_count: int,
    with_platform: bool,
    phase_name: str,
    harness: _TimingHarness,
) -> Dict[str, Any]:
    wall_times: List[float] = []
    results = []

    for run_idx in range(repeat_count):
        config = {
            "run_name": f"overhead-{('platform' if with_platform else 'sdk')}-{run_idx}",
            "max_concurrency": 1,
            "max_metric_concurrency": 1,
            "max_retries": 0,
            "timeout": 5,
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


async def _run_overhead_breakdown_test(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("QYM_API_KEY", raising=False)
    monkeypatch.setattr(
        otel_module,
        "create_otel_manager",
        lambda config: otel_module.NullOtelManager(),
    )
    monkeypatch.setattr(
        evaluator_module,
        "_detect_git_info",
        lambda config=None: {"git_branch": None, "git_commit": None},
    )
    monkeypatch.setattr(
        client_module,
        "_post_json",
        lambda url, payload, api_key, timeout=30: {
            "run_id": "platform-run-1",
            "live_url": "https://platform.example/runs/platform-run-1",
        },
    )
    monkeypatch.setattr(
        client_module,
        "_post_ndjson",
        lambda url, ndjson, api_key, timeout=30: None,
    )

    items = [
        _MemoryItem(
            id=f"item-{idx}",
            input={"question": f"question {idx}"},
            expected_output=f"answer::question {idx}",
            metadata={"bucket": idx % 3},
        )
        for idx in range(4)
    ]
    dataset = _MemoryDataset(items)
    duration_plan = [
        {"task_duration_s": 0.001, "repeat_count": 3},
        {"task_duration_s": 0.010, "repeat_count": 3},
        {"task_duration_s": 0.050, "repeat_count": 2},
        {"task_duration_s": 0.200, "repeat_count": 1},
        {"task_duration_s": 1.000, "repeat_count": 1},
    ]

    reports = []
    harness = _TimingHarness()
    _install_timing_wrappers(monkeypatch, harness)
    for plan in duration_plan:
        repeat_count = int(plan["repeat_count"])
        task_duration_s = float(plan["task_duration_s"])
        task = _make_task_under_test(task_duration_s)
        sdk_phase = f"sdk:{task_duration_s}"
        platform_phase = f"platform:{task_duration_s}"

        raw_task_wall_s = await _measure_raw_task(
            items,
            task=task,
            repeat_count=repeat_count,
        )
        sdk_case = await _run_qym_case(
            dataset,
            task=task,
            repeat_count=repeat_count,
            with_platform=False,
            phase_name=sdk_phase,
            harness=harness,
        )
        platform_case = await _run_qym_case(
            dataset,
            task=task,
            repeat_count=repeat_count,
            with_platform=True,
            phase_name=platform_phase,
            harness=harness,
        )

        for result in sdk_case["results"] + platform_case["results"]:
            assert result.total_items == len(items)
            assert not result.errors
            assert len(result.results) == len(items)

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
            "task_wrapper_overhead_s": max(0.0, sdk_execute_task_s - raw_task_wall_s),
            "tracker_overhead_s": sdk_update_tracker_s,
            "item_start_overhead_s": sdk_emit_started_s,
            "item_complete_overhead_s": sdk_emit_completed_s,
            "metrics_overhead_s": sdk_compute_metrics_s,
        }
        sdk_breakdown["run_residual_s"] = sdk_overhead_s - sum(sdk_breakdown.values())

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

        report = {
            "task_duration_s": task_duration_s,
            "repeat_count": repeat_count,
            "item_count": len(items),
            "raw_task_wall_s": raw_task_wall_s,
            "qym_sdk_wall_s": sdk_wall_s,
            "qym_platform_wall_s": platform_wall_s,
            "sdk_overhead_s": sdk_overhead_s,
            "platform_overhead_s": platform_overhead_s,
            "sdk_overhead_pct_of_raw": _pct(sdk_overhead_s, raw_task_wall_s),
            "platform_overhead_pct_of_raw": _pct(platform_overhead_s, raw_task_wall_s),
            "sdk_breakdown": sdk_breakdown,
            "platform_breakdown": platform_breakdown,
            "platform_emit_calls": harness.total_count(platform_phase, "platform.emit"),
        }

        assert raw_task_wall_s > 0.0, report
        # Independent timing samples contain scheduler jitter. The measured
        # difference may be negative; preserve it rather than assert/clamp it.
        assert sdk_wall_s > 0.0 and math.isfinite(sdk_overhead_s), report
        assert platform_wall_s > 0.0, report
        assert sdk_breakdown["task_wrapper_overhead_s"] >= 0.0, report
        assert platform_breakdown["create_run_s"] > 0.0, report
        assert platform_breakdown["stream_init_s"] > 0.0, report
        assert platform_breakdown["event_emit_s"] > 0.0, report
        assert platform_breakdown["stream_close_s"] > 0.0, report
        # Per run: run_started + run_completed, plus 4 events per item
        # (item_started, item_attempt_started, item_attempt_finished,
        # item_completed) with zero metrics and no retries.
        assert harness.total_count(platform_phase, "platform.emit") == repeat_count * ((4 * len(items)) + 2), report
        reports.append(report)

    return {"cases": reports}


def test_overhead_breakdown_attributes_sdk_and_platform_coupling(monkeypatch: pytest.MonkeyPatch):
    report = asyncio.run(_run_overhead_breakdown_test(monkeypatch))
    print("\nOVERHEAD BREAKDOWN")
    print(_format_report(report))


def _format_report(report: Dict[str, Any]) -> str:
    lines = [
        "Summary by task duration:",
        "  Task      Raw task     Qym SDK    Qym+plat    SDK add      Plat delta",
        "  --------  -----------  ---------  ----------  -----------  -----------",
    ]
    for case in report["cases"]:
        lines.append(
            "  "
            f"{_ms_label(case['task_duration_s']):<8}  "
            f"{case['raw_task_wall_s'] * 1000:>9.1f} ms  "
            f"{case['qym_sdk_wall_s'] * 1000:>7.1f} ms  "
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
            f"  { _ms_label(case['task_duration_s']) } task "
            f"(items={case['item_count']}, repeats={case['repeat_count']}):"
        )
        lines.append("    SDK:")
        lines.extend(_format_breakdown_lines(case["sdk_breakdown"], indent="      "))
        lines.append("    Platform:")
        lines.extend(_format_breakdown_lines(case["platform_breakdown"], indent="      "))
    return "\n".join(lines)


def _format_breakdown_lines(breakdown: Dict[str, float], *, indent: str = "  ") -> List[str]:
    rows = sorted(breakdown.items(), key=lambda item: item[1], reverse=True)
    return [f"{indent}{name:<24} {value * 1000:.1f} ms" for name, value in rows]


def _pct(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return (numerator / denominator) * 100.0


def _ms_label(seconds: float) -> str:
    return f"{seconds * 1000:.0f}ms"
