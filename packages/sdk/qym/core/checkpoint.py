"""Checkpoint helpers for incremental evaluation results."""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


BASE_FIELDS = [
    "dataset_name",
    "run_name",
    "run_metadata",
    "run_config",
    "trace_id",
    "item_id",
    "input",
    "item_metadata",
    "output",
    "expected_output",
    "time",
    "task_started_at_ms",
]


def _is_error_row(row: Dict[str, Any], metrics: Sequence[str]) -> bool:
    output = str(row.get("output", "") or "")
    if output.startswith("ERROR:") or output.startswith("ERROR "):
        return True
    if metrics:
        score_str = str(row.get(f"{metrics[0]}_score", "") or "")
        if "ERROR" in score_str or score_str.strip().upper() == "N/A":
            return True
    return False


def _parse_metric_score(value: Any) -> Optional[float]:
    if value is None:
        return None
    raw = str(value).strip()
    if raw == "":
        return None
    lowered = raw.lower()
    if lowered in {"n/a", "na", "none"}:
        return None
    if raw in {"✓"} or lowered in {"true", "yes", "y"}:
        return 1.0
    if raw in {"✗"} or lowered in {"false", "no", "n"}:
        return 0.0
    if lowered in {"1", "1.0"}:
        return 1.0
    if lowered in {"0", "0.0"}:
        return 0.0
    if raw.endswith("%"):
        try:
            return float(raw[:-1].strip()) / 100.0
        except (ValueError, TypeError):
            return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


def parse_metric_score(value: Any) -> Optional[float]:
    """Public wrapper to parse numeric metric scores."""
    return _parse_metric_score(value)


def build_checkpoint_header(metrics: Sequence[str]) -> List[str]:
    header = list(BASE_FIELDS)
    for metric in metrics:
        header.append(f"{metric}_score")
        header.append(f"{metric}__meta__json")
    return header


def serialize_checkpoint_row(
    *,
    dataset_name: str,
    run_name: str,
    run_metadata: Dict[str, Any],
    run_config: Dict[str, Any],
    trace_id: str,
    item_id: str,
    item_input: Any,
    item_metadata: Any,
    output: Any,
    expected_output: Any,
    time_seconds: float,
    task_started_at_ms: Optional[int],
    scores: Dict[str, Any],
    metric_meta: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "dataset_name": dataset_name,
        "run_name": run_name,
        "run_metadata": json.dumps(run_metadata, ensure_ascii=False),
        "run_config": json.dumps(run_config, ensure_ascii=False),
        "trace_id": trace_id or "",
        "item_id": item_id,
        "input": item_input,
        "item_metadata": json.dumps(item_metadata, ensure_ascii=False)
        if isinstance(item_metadata, dict)
        else str(item_metadata),
        "output": output,
        "expected_output": expected_output,
        "time": time_seconds,
        "task_started_at_ms": task_started_at_ms if task_started_at_ms is not None else "",
    }

    metric_meta = metric_meta or {}
    for metric, score in scores.items():
        row[f"{metric}_score"] = score
        meta_val = metric_meta.get(metric, {})
        row[f"{metric}__meta__json"] = json.dumps(meta_val, ensure_ascii=False) if meta_val else ""
    return row


@dataclass
class CheckpointState:
    path: str
    dataset_name: Optional[str]
    run_name: Optional[str]
    metrics: List[str]
    completed_item_ids: Set[str]
    error_item_ids: Set[str]


class CheckpointWriter:
    def __init__(
        self,
        path: str,
        *,
        metrics: Sequence[str],
        flush_each_item: bool = True,
        fsync: bool = False,
    ) -> None:
        self.path = path
        self.metrics = list(metrics)
        self.flush_each_item = flush_each_item
        self.fsync = fsync
        self._file = None
        self._writer = None

    def open(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        file_exists = os.path.exists(self.path)
        self._file = open(self.path, "a", newline="", encoding="utf-8")
        header = build_checkpoint_header(self.metrics)
        self._writer = csv.DictWriter(self._file, fieldnames=header)
        if not file_exists or os.path.getsize(self.path) == 0:
            self._writer.writeheader()
            self._flush()

    def append_row(self, row: Dict[str, Any]) -> None:
        if not self._writer:
            raise RuntimeError("CheckpointWriter is not open")
        self._writer.writerow(row)
        self._flush()

    def _flush(self) -> None:
        if not self._file:
            return
        if self.flush_each_item:
            self._file.flush()
            if self.fsync:
                try:
                    os.fsync(self._file.fileno())
                except Exception:
                    pass

    def close(self) -> None:
        if self._file:
            try:
                self._file.flush()
                if self.fsync:
                    os.fsync(self._file.fileno())
            except Exception:
                pass
            try:
                self._file.close()
            except Exception:
                pass
        self._file = None
        self._writer = None


def load_checkpoint_state(path: str) -> Optional[CheckpointState]:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return None
        fieldnames = reader.fieldnames
        metrics = sorted(
            {
                name[:-6]
                for name in fieldnames
                if name.endswith("_score") and "__meta__" not in name
            }
        )
        completed: Set[str] = set()
        error_ids: Set[str] = set()
        dataset_name: Optional[str] = None
        run_name: Optional[str] = None
        for row in reader:
            if not row:
                continue
            if dataset_name is None:
                dataset_name = row.get("dataset_name") or None
            if run_name is None:
                run_name = row.get("run_name") or None
            item_id = str(row.get("item_id", "") or "")
            if not item_id:
                continue
            completed.add(item_id)
            if _is_error_row(row, metrics):
                error_ids.add(item_id)
        return CheckpointState(
            path=path,
            dataset_name=dataset_name,
            run_name=run_name,
            metrics=metrics,
            completed_item_ids=completed,
            error_item_ids=error_ids,
        )


def iter_checkpoint_rows(path: str) -> Iterable[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row:
                yield row


def parse_checkpoint_row(
    row: Dict[str, Any], metrics: Sequence[str]
) -> Tuple[str, Dict[str, Any], bool]:
    item_id = str(row.get("item_id", "") or "")
    is_error = _is_error_row(row, metrics)
    result: Dict[str, Any] = {
        "input": row.get("input", ""),
        "output": row.get("output", ""),
        "expected": row.get("expected_output", ""),
        "trace_id": row.get("trace_id", ""),
        "time": float(row.get("time") or 0.0),
    }
    raw_started = row.get("task_started_at_ms", "")
    try:
        result["task_started_at_ms"] = int(float(raw_started)) if raw_started not in (None, "") else None
    except (ValueError, TypeError):
        result["task_started_at_ms"] = None

    scores: Dict[str, Any] = {}
    metric_meta: Dict[str, Dict[str, Any]] = {}
    for metric in metrics:
        score_val = row.get(f"{metric}_score", "")
        score_num = _parse_metric_score(score_val)
        if score_num is not None:
            scores[metric] = score_num
        else:
            scores[metric] = score_val
        meta_raw = row.get(f"{metric}__meta__json", "")
        if meta_raw:
            try:
                parsed = json.loads(meta_raw)
                if isinstance(parsed, dict):
                    metric_meta[metric] = parsed
            except Exception:
                pass

    result["scores"] = scores
    if metric_meta:
        for metric, meta in metric_meta.items():
            if isinstance(scores.get(metric), dict):
                scores[metric]["metadata"] = meta
            else:
                scores[metric] = {"score": scores.get(metric), "metadata": meta}
    return item_id, result, is_error
