"""Benchmark sql_eval/run_eval_v2 as:

1. Task alone
2. qym end-to-end evaluation

The qym pass is intended to mirror run_eval_v2 defaults as closely as possible.
It uses the real task, dataset, metrics, output_dir, timeout, retries, and any
env-driven qym behavior you already have configured.

Examples:
  python tests/profile_sql_eval_v2_overhead.py --limit 10
  python tests/profile_sql_eval_v2_overhead.py --model openai/gpt-5.4 --limit 20 --concurrency 10
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import functools
import importlib.util
import inspect
import json
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
SQL_EVAL_ROOT = REPO_ROOT.parent / "sql_eval"
SDK_ROOT = REPO_ROOT / "packages" / "sdk"
PLATFORM_ROOT = REPO_ROOT / "packages" / "platform"

for path in (str(SQL_EVAL_ROOT), str(SDK_ROOT), str(PLATFORM_ROOT), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from qym import Evaluator
from qym.core.dataset import CsvDataset


class MetricTiming:
    def __init__(self) -> None:
        self.total_s: Dict[str, float] = defaultdict(float)
        self.calls: Dict[str, int] = defaultdict(int)

    def record(self, name: str, duration_s: float) -> None:
        self.total_s[name] += duration_s
        self.calls[name] += 1


class TaskProbe:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: Dict[str, List[Dict[str, float]]] = defaultdict(list)

    @staticmethod
    def _key_from_mapping(mapping: Dict[str, Any]) -> str:
        return json.dumps(mapping, sort_keys=True, ensure_ascii=False, default=str)

    def wrap(self, task: Callable[..., Any]) -> Callable[..., Any]:
        task_signature = inspect.signature(task)

        @functools.wraps(task)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            bound = task_signature.bind_partial(*args, **kwargs)
            bound.apply_defaults()
            key_mapping = {
                k: v
                for k, v in bound.arguments.items()
                if k not in {"model", "model_name", "trace_id"}
            }
            key = self._key_from_mapping(key_mapping)
            started_perf = time.perf_counter()
            started_ms = time.time() * 1000.0
            try:
                return task(**kwargs)
            finally:
                record = {
                    "start_ms": started_ms,
                    "duration_s": time.perf_counter() - started_perf,
                }
                with self._lock:
                    self._records[key].append(record)

        wrapped.__signature__ = task_signature
        return wrapped

    def summarize_qym_result(self, result: Any) -> Dict[str, float]:
        with self._lock:
            buckets = {key: list(values) for key, values in self._records.items()}

        queue_wait_s_total = 0.0
        body_duration_s_total = 0.0
        queue_wait_samples = 0
        matched = 0
        missing = 0

        for item_id, item_result in result.results.items():
            input_data = result.inputs.get(item_id)
            if not isinstance(input_data, dict):
                missing += 1
                continue
            key = self._key_from_mapping(input_data)
            bucket = buckets.get(key)
            if not bucket:
                missing += 1
                continue
            record = bucket.pop(0)
            matched += 1
            body_duration_s_total += record["duration_s"]
            started_at_ms = item_result.get("task_started_at_ms")
            if started_at_ms is not None:
                queue_wait_s_total += max(0.0, (record["start_ms"] - float(started_at_ms)) / 1000.0)
                queue_wait_samples += 1

        return {
            "matched_items": float(matched),
            "missing_items": float(missing),
            "body_duration_s_total": body_duration_s_total,
            "body_duration_s_avg": (body_duration_s_total / matched) if matched else 0.0,
            "queue_wait_s_total": queue_wait_s_total,
            "queue_wait_s_avg": (queue_wait_s_total / queue_wait_samples) if queue_wait_samples else 0.0,
        }


def _load_run_eval_v2():
    module_path = SQL_EVAL_ROOT / "run_eval_v2.py"
    spec = importlib.util.spec_from_file_location("sql_eval_run_eval_v2", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _wrap_metrics(metrics: List[Callable[..., Any]], timing: MetricTiming) -> List[Callable[..., Any]]:
    wrapped = []
    for metric in metrics:
        name = getattr(metric, "__name__", repr(metric))

        def wrapper(output: Any, expected: Any, input_data: Any, _metric: Callable[..., Any] = metric, _name: str = name):
            started = time.perf_counter()
            try:
                return _metric(output, expected, input_data)
            finally:
                timing.record(_name, time.perf_counter() - started)

        wrapper.__name__ = name
        wrapped.append(wrapper)
    return wrapped


def _load_dataset(config_mod: Any, limit: int | None) -> CsvDataset:
    csv_path = Path(config_mod.DATA_DIR) / "bird_minidev_100.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Dataset CSV not found at {csv_path}. Run sql_eval/prepare_dataset.py first.")

    dataset = CsvDataset(
        csv_path,
        input_col="input",
        expected_col="expected",
        id_col="id",
        metadata_cols=["difficulty"],
    )
    if limit:
        dataset._items = dataset.get_items()[:limit]
    return dataset


async def _run_task_alone(
    items: List[Any],
    *,
    task: Callable[..., Any],
    model: str,
    concurrency: int,
) -> Dict[str, float]:
    semaphore = asyncio.Semaphore(concurrency)
    per_item_durations: List[float] = []

    async def run_one(item: Any) -> Any:
        async with semaphore:
            started = time.perf_counter()
            try:
                return await asyncio.to_thread(task, model_name=model, **dict(item.input))
            finally:
                per_item_durations.append(time.perf_counter() - started)

    run_started = time.perf_counter()
    await asyncio.gather(*(run_one(item) for item in items))
    wall_s = time.perf_counter() - run_started
    summed_item_s = sum(per_item_durations)
    return {
        "wall_s": wall_s,
        "summed_item_s": summed_item_s,
        "avg_item_s": (summed_item_s / len(items)) if items else 0.0,
    }


async def _run_qym_eval(
    dataset: CsvDataset,
    *,
    task: Callable[..., Any],
    metrics: List[Callable[..., Any]],
    model: str,
    run_name: str,
    output_dir: str,
    concurrency: int,
    task_timeout: float | None,
    max_retries: int,
) -> Tuple[Any, float]:
    evaluator = Evaluator(
        task=task,
        dataset=dataset,
        metrics=metrics,
        config={
            "max_concurrency": concurrency,
            "run_name": run_name,
            "output_dir": output_dir,
            "model": model,
            "timeout": task_timeout,
            "max_retries": max_retries,
        },
    )
    started = time.perf_counter()
    result = await evaluator.arun(show_tui=False, auto_save=True, save_format="csv")
    return result, (time.perf_counter() - started)


def _format_seconds_ms(seconds: float) -> str:
    return f"{seconds * 1000:.1f} ms"


def _format_seconds_s(seconds: float) -> str:
    return f"{seconds:.2f} s"


def _fmt(seconds: float) -> str:
    return _format_seconds_ms(seconds) if seconds < 1.0 else _format_seconds_s(seconds)


def _pct(part: float, whole: float) -> float:
    if whole <= 0:
        return 0.0
    return (part / whole) * 100.0


def _format_metric_lines(metric_timing: MetricTiming) -> List[str]:
    rows = sorted(metric_timing.total_s.items(), key=lambda item: item[1], reverse=True)
    return [
        f"  {name:<20} {_fmt(total_s):>10}  calls={metric_timing.calls[name]}"
        for name, total_s in rows
    ]


def _build_report(
    *,
    model: str,
    item_count: int,
    concurrency: int,
    task_only: Dict[str, float],
    qym_wall_s: float,
    qym_result: Any,
    qym_probe: Dict[str, float],
    metric_timing: MetricTiming,
) -> str:
    qym_sum_s = qym_result.get_timing_stats()["total"]
    qym_avg_s = qym_result.get_timing_stats()["mean"]
    qym_added_wall_s = qym_wall_s - task_only["wall_s"]
    metric_sum_s = sum(metric_timing.total_s.values())
    reported_body_gap_s = max(0.0, qym_sum_s - qym_probe["body_duration_s_total"])

    verdict = "not clearly observed"
    if qym_probe["queue_wait_s_total"] > 1.0 or qym_probe["queue_wait_s_avg"] > 0.01:
        verdict = "observed"

    lines = [
        "SQL Eval v2 Overhead",
        f"  Model: {model}",
        f"  Items: {item_count}",
        f"  Concurrency: {concurrency}",
        "",
        "Task alone:",
        f"  Run wall time         {_fmt(task_only['wall_s'])}",
        f"  Summed task time      {_fmt(task_only['summed_item_s'])}",
        f"  Avg task per item     {_fmt(task_only['avg_item_s'])}",
        "",
        "Qym exact eval:",
        f"  Eval wall time        {_fmt(qym_wall_s)}",
        f"  Reported task sum     {_fmt(qym_sum_s)}",
        f"  Actual body sum       {_fmt(qym_probe['body_duration_s_total'])}",
        f"  Avg task per item     {_fmt(qym_avg_s)}",
        f"  Direct queue wait     {_fmt(qym_probe['queue_wait_s_total'])} total / {_fmt(qym_probe['queue_wait_s_avg'])} avg",
        f"  Reported-body gap     {_fmt(reported_body_gap_s)}",
        f"  Success count         {len(qym_result.results)}",
        f"  Error count           {len(qym_result.errors)}",
        "",
        "Delta:",
        f"  Qym exact eval add    {_fmt(qym_added_wall_s)} ({_pct(qym_added_wall_s, task_only['wall_s']):.1f}%)",
        f"  Metric summed time    {_fmt(metric_sum_s)}",
        f"  Queue-wait verdict    {verdict}",
        "",
        "Metric breakdown:",
    ]
    lines.extend(_format_metric_lines(metric_timing))
    lines.append("")
    lines.append("Notes:")
    lines.append("  Direct queue wait compares qym task_started_at_ms to actual task-body start inside the worker.")
    lines.append("  Reported-body gap compares qym reported task time to actual task-body runtime.")
    lines.append("  Metric summed time is summed across items, not wall-clock time.")
    lines.append("  The qym pass uses run_eval_v2-style defaults, including auto-save/output_dir and your env-driven qym behavior.")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare sql_eval run_eval_v2 task-only vs qym end-to-end eval.")
    parser.add_argument("--model", type=str, default=None, help="Model ID. Defaults to the first model in sql_eval/config.py.")
    parser.add_argument("--limit", type=int, default=None, help="Number of dataset items to run. Default: all items in the CSV.")
    parser.add_argument("--concurrency", type=int, default=None, help="Max parallel task executions. Default: sql_eval/config.py MAX_CONCURRENCY.")
    parser.add_argument("--run-name", type=str, default="bird-minidev-overhead", help="Run name for the qym evaluator.")
    parser.add_argument("--task-timeout", type=float, default=None, help="Override qym task timeout. Default: sql_eval/config.py TASK_TIMEOUT.")
    parser.add_argument("--max-retries", type=int, default=3, help="qym max_retries for the eval run. Default: 3.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    run_eval_v2 = _load_run_eval_v2()
    config_mod = run_eval_v2.config

    model = args.model or config_mod.MODELS[0]
    concurrency = args.concurrency or config_mod.MAX_CONCURRENCY
    task_timeout = args.task_timeout if args.task_timeout is not None else config_mod.TASK_TIMEOUT

    dataset = _load_dataset(config_mod, args.limit)
    items = dataset.get_items()
    metric_timing = MetricTiming()
    wrapped_metrics = _wrap_metrics(list(run_eval_v2.ALL_METRICS), metric_timing)
    qym_probe = TaskProbe()

    loop = asyncio.get_running_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=concurrency)
    loop.set_default_executor(executor)
    loop._qym_executor_set = True

    try:
        task_only = await _run_task_alone(
            items,
            task=run_eval_v2.sql_agent_task,
            model=model,
            concurrency=concurrency,
        )
        qym_result, qym_wall_s = await _run_qym_eval(
            dataset,
            task=qym_probe.wrap(run_eval_v2.sql_agent_task),
            metrics=wrapped_metrics,
            model=model,
            run_name=args.run_name,
            output_dir=config_mod.RESULTS_DIR,
            concurrency=concurrency,
            task_timeout=task_timeout,
            max_retries=args.max_retries,
        )
    finally:
        executor.shutdown(wait=False)

    qym_probe_summary = qym_probe.summarize_qym_result(qym_result)

    print()
    print(_build_report(
        model=model,
        item_count=len(items),
        concurrency=concurrency,
        task_only=task_only,
        qym_wall_s=qym_wall_s,
        qym_result=qym_result,
        qym_probe=qym_probe_summary,
        metric_timing=metric_timing,
    ))


if __name__ == "__main__":
    asyncio.run(main())
