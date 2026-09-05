"""Dashboard view calculations over streamed durable run summaries.

These reducers retain the existing browser definitions, including unweighted
run averages and exact medians. They never consume item bodies or source rows.
The browser applies its own locale collation to model labels.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Iterable

Row = dict[str, Any]


def _number(value: Any) -> float:
    try:
        number = float(value or 0)
        return number if math.isfinite(number) else 0.0
    except (TypeError, ValueError):
        return 0.0


def model_key(row: Row) -> str:
    if row.get("model_key"):
        return row["model_key"]
    trace = row.get("trace_stats") or {}
    reasoning = bool(row.get("model_has_reasoning")) or bool(
        isinstance(trace, dict)
        and (
            trace.get("has_reasoning")
            or trace.get("has_reasoning_tokens")
            or _number(trace.get("reasoning_tokens")) > 0
            or _number(trace.get("avg_reasoning_tokens")) > 0
        )
    )
    return str(row.get("raw_model_name") or row.get("model_name") or "") + (
        "|||reasoning" if reasoning else "|||plain"
    )


def _date(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return (
        result.replace(tzinfo=timezone.utc)
        if result.tzinfo is None
        else result.astimezone(timezone.utc)
    )


def _iso(value: datetime | None) -> str | None:
    return (
        value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if value
        else None
    )


def _metric_type(spec: Any, value: Any) -> str:
    if isinstance(spec, dict):
        kind = spec.get("score_type")
        if kind == "boolean":
            return "boolean"
        if kind == "percentage":
            return "score"
        if kind in {"count", "number"}:
            return "numeric"
    return "numeric" if _number(value) > 1 or _number(value) < 0 else "score"


def _utf16_key(value: str) -> bytes:
    return value.encode("utf-16-be", errors="surrogatepass")


def _global_data(rows: Iterable[Row], now: datetime) -> Row:
    agg = dict(
        totalRuns=0,
        totalTasks=0,
        totalModels=0,
        totalItems=0,
        avgSuccess=0.0,
        byModel={},
        byTask={},
        byDay={},
    )
    for offset in range(6, -1, -1):
        agg["byDay"][(now - timedelta(days=offset)).date().isoformat()] = {
            "runs": 0,
            "successSum": 0,
        }
    metrics, types = set(), {}
    total_success = 0.0
    has_trace = False
    specs = {}
    for row in rows:
        agg["totalRuns"] += 1
        items, success = row.get("total_items") or 0, row.get("success_rate") or 0
        agg["totalItems"] += items
        total_success += success
        for key, group in (
            (model_key(row), agg["byModel"]),
            (row.get("task_name") or "", agg["byTask"]),
        ):
            data = group.setdefault(key, {"runs": 0, "items": 0, "successSum": 0})
            data["runs"] += 1
            data["items"] += items
            data["successSum"] += success
        timestamp = _date(row.get("timestamp"))
        day = timestamp.date().isoformat() if timestamp else ""
        if day in agg["byDay"]:
            agg["byDay"][day]["runs"] += 1
            agg["byDay"][day]["successSum"] += success
        metrics.update(row.get("metrics") or [])
        averages, run_specs = (
            row.get("metric_averages") or {},
            row.get("metric_specs") or {},
        )
        for metric in set(averages) | set(run_specs) | set(row.get("metrics") or []):
            state = types.setdefault(
                metric, {"specified": None, "numeric": False, "done": False}
            )
            if state["done"]:
                continue
            value, spec = averages.get(metric), run_specs.get(metric)
            if isinstance(spec, dict) and spec.get("score_type") != "legacy":
                current = _metric_type(spec, value)
                previous = state["specified"] or current
                state["specified"] = previous if previous == current else "numeric"
                specs.setdefault(metric, spec)
            if value is not None and (_number(value) > 1 or _number(value) < 0):
                state["numeric"] = state["done"] = True
        # Empty dictionaries are truthy objects in the browser.
        has_trace |= isinstance(row.get("trace_stats"), dict) or bool(
            row.get("trace_stats")
        )
    agg["totalModels"], agg["totalTasks"] = len(agg["byModel"]), len(agg["byTask"])
    agg["avgSuccess"] = total_success / agg["totalRuns"] if agg["totalRuns"] else 0.0
    for group in (agg["byModel"], agg["byTask"]):
        for data in group.values():
            data["avgSuccess"] = data["successSum"] / data["runs"]
    return {
        "aggregations": agg,
        "all_models": list(agg["byModel"]),
        "all_metrics": sorted(metrics, key=_utf16_key),
        "metric_specs": specs,
        "metric_types": {
            name: types.get(name, {}).get("specified")
            or ("numeric" if types.get(name, {}).get("numeric") else "score")
            for name in metrics
        },
        "has_trace_stats": has_trace,
        "has_any_trace_stats": has_trace,
    }


def _chart_data(rows: Iterable[Row]) -> Row:
    combos, metrics, model_frequency = {}, {}, {}
    has_trace = False
    revision = hashlib.sha256()
    for row in rows:
        stamp = json.dumps(
            [row.get("run_id") or row.get("file_path"), row.get("_revision", 0)],
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        revision.update(stamp)
        revision.update(b"\n")
        task, dataset = row.get("task_name") or "", row.get("dataset_name") or ""
        combo = combos.setdefault(
            (task, dataset),
            {
                "task": task,
                "dataset": dataset,
                "models": {},
                "metrics": {},
                "totalRuns": 0,
                "_revision_hash": hashlib.sha256(),
            },
        )
        combo["_revision_hash"].update(stamp)
        combo["_revision_hash"].update(b"\n")
        model = model_key(row)
        values = combo["models"].setdefault(
            model,
            {
                "runs": 0,
                "runsList": [],
                "totalItems": 0,
                "latestTimestamp": None,
                "metricSums": {},
                "metricCounts": {},
                "latencySum": 0,
                "latencyCount": 0,
                "_medians": [],
            },
        )
        for metric in row.get("metrics") or []:
            combo["metrics"][metric] = None
            metrics[metric] = None
        values["runs"] += 1
        values["totalItems"] += row.get("total_items") or 0
        combo["totalRuns"] += 1
        model_frequency[model] = model_frequency.get(model, 0) + 1
        for metric, score in (row.get("metric_averages") or {}).items():
            # Preserve the shipped reducer's reset at a zero running sum.
            if not values["metricSums"].get(metric):
                values["metricSums"][metric] = 0
                values["metricCounts"][metric] = 0
            values["metricSums"][metric] += _number(score)
            values["metricCounts"][metric] += 1
        if row.get("avg_latency_ms"):
            values["latencySum"] += row["avg_latency_ms"]
            values["latencyCount"] += 1
        if row.get("median_latency_ms"):
            values["_medians"].append(row["median_latency_ms"])
        timestamp = _date(row.get("timestamp"))
        if timestamp and (
            not values["latestTimestamp"] or timestamp > values["latestTimestamp"]
        ):
            values["latestTimestamp"] = timestamp
        has_trace |= isinstance(row.get("trace_stats"), dict) or bool(
            row.get("trace_stats")
        )
    ordered = sorted(combos.values(), key=lambda combo: -combo["totalRuns"])
    tasks = {}
    for combo in ordered:
        combo["revision"] = combo.pop("_revision_hash").hexdigest()
        combo["metrics"] = list(combo["metrics"])
        for values in combo["models"].values():
            values["metricAverages"] = {
                name: value / (values["metricCounts"].get(name) or 1)
                for name, value in values["metricSums"].items()
            }
            values["avgLatencyMs"] = (
                values["latencySum"] / values["latencyCount"]
                if values["latencyCount"]
                else 0
            )
            values["medianLatencyMs"] = (
                median(values["_medians"]) if values["_medians"] else 0
            )
            del values["_medians"]
            values["latestTimestamp"] = _iso(values["latestTimestamp"])
        tasks.setdefault(combo["task"], {"task": combo["task"], "datasets": []})[
            "datasets"
        ].append(combo)
    models = sorted(model_frequency, key=lambda model: -model_frequency[model])
    return {
        "combos": ordered,
        "tasks": sorted(
            tasks.values(),
            key=lambda task: -sum(combo["totalRuns"] for combo in task["datasets"]),
        ),
        "models": models,
        "metrics": list(metrics),
        "modelIndex": {name: index for index, name in enumerate(models)},
        "model_frequency": model_frequency,
        "has_trace_stats": has_trace,
        "filtered_revision": revision.hexdigest(),
    }


def build_overview_data(
    unfiltered_rows: Iterable[Row],
    filtered_rows: Iterable[Row],
    *,
    now: datetime | None = None,
) -> Row:
    """Return global header facts and full-filter chart/column summaries."""
    current = _date(now or datetime.now(timezone.utc))
    data = _global_data(unfiltered_rows, current)
    chart = _chart_data(filtered_rows)
    data.update(
        chart_data=chart,
        filtered_revision=chart.pop("filtered_revision"),
        metrics=sorted(chart["metrics"], key=_utf16_key),
        total_count=data["aggregations"]["totalRuns"],
        total_runs=sum(combo["totalRuns"] for combo in chart["combos"]),
        has_trace_stats=chart.pop("has_trace_stats"),
    )
    return data
