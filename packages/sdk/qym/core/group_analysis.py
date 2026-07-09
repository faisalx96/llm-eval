"""Group run analysis utilities.

These helpers mirror the platform dashboard group metric semantics in Python so
SDK users can compute Pass@K, Avg@K, consistency, and reliability without
uploading runs to the platform.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from .results import EvaluationResult


@dataclass(frozen=True)
class _ScoreRow:
    item_id: str
    score: Optional[float]
    is_error: bool
    latency_ms: Optional[float]
    attempts: int
    metadata: Dict[str, Any]


@dataclass(frozen=True)
class _RunRows:
    run_name: str
    rows: Dict[str, _ScoreRow]


def parse_score_value(metric_value: Any) -> Optional[float]:
    """Parse a raw metric value using the platform dashboard's score rules."""
    if metric_value is None:
        return None

    if hasattr(metric_value, "score"):
        return parse_score_value(getattr(metric_value, "score"))

    if isinstance(metric_value, dict):
        if "error" in metric_value:
            return 0.0
        if "score" in metric_value:
            return parse_score_value(metric_value.get("score"))
        return None

    if isinstance(metric_value, bool):
        return 1.0 if metric_value else 0.0

    if isinstance(metric_value, (int, float)):
        value = float(metric_value)
        return value if math.isfinite(value) else None

    raw = str(metric_value).strip()
    if not raw:
        return None

    lowered = raw.lower()
    if lowered in {"n/a", "na", "none", "null"}:
        return None
    if raw == "\u2713" or lowered in {"true", "yes", "y"}:
        return 1.0
    if raw == "\u2717" or lowered in {"false", "no", "n"}:
        return 0.0

    if raw.endswith("%"):
        try:
            return float(raw[:-1].strip()) / 100.0
        except ValueError:
            return None

    try:
        score = float(raw)
    except ValueError:
        return None
    return score if math.isfinite(score) else None


def analyze_group_runs(
    results: Sequence[EvaluationResult],
    *,
    metric: str,
    threshold: float = 0.8,
    track_distribution: bool = False,
) -> Dict[str, Any]:
    """Analyze one group of runs using platform-compatible item-level metrics.

    This matches the platform item-level aggregation mode: item IDs are unioned
    across runs, and each item is evaluated with the scores that are present.
    Missing or null scores are excluded; error rows score as 0.
    """
    runs = [_rows_for_result(result, metric) for result in results]
    k = len(runs)
    distribution: Optional[List[int]] = [0] * (k + 1) if track_distribution else None

    item_ids = set()
    for run in runs:
        item_ids.update(run.rows.keys())

    pass_at_k_count = 0
    pass_hat_k_count = 0
    total_consistency_sum = 0.0
    items_with_multiple_runs = 0
    total_reliability_sum = 0.0
    items_with_at_least_one_pass = 0
    max_score_sum = 0.0
    total_score_sum = 0.0
    total_score_count = 0
    total_latency_sum = 0.0
    total_latency_count = 0
    latency_samples: List[float] = []
    all_scores: List[float] = []
    failed_count = 0
    items: List[Dict[str, Any]] = []

    for item_id in sorted(item_ids):
        scores: List[float] = []
        attempts: List[int] = []
        metadata: Dict[str, Any] = {}
        item_failed_count = 0

        for run in runs:
            row = run.rows.get(item_id)
            if row is None or row.score is None:
                continue

            scores.append(row.score)
            attempts.append(row.attempts)
            metadata = metadata or dict(row.metadata or {})
            total_score_sum += row.score
            total_score_count += 1
            all_scores.append(row.score)
            if row.is_error:
                failed_count += 1
                item_failed_count += 1
            if row.latency_ms is not None and row.latency_ms > 0:
                total_latency_sum += row.latency_ms
                total_latency_count += 1
                latency_samples.append(row.latency_ms)

        if not scores:
            continue

        max_score = max(scores)
        pass_count = sum(1 for score in scores if score >= threshold)
        score_count = len(scores)

        if distribution is not None:
            distribution[pass_count] += 1

        if pass_count > 0:
            pass_at_k_count += 1
        if pass_count == score_count and score_count > 0:
            pass_hat_k_count += 1

        consistency = None
        reliability = None
        if score_count > 1:
            fail_count = score_count - pass_count
            consistency = (2 * max(pass_count, fail_count) / score_count) - 1
            total_consistency_sum += consistency
            items_with_multiple_runs += 1
            if pass_count > 0:
                reliability = pass_count / score_count
                total_reliability_sum += reliability
                items_with_at_least_one_pass += 1

        max_score_sum += max_score
        items.append(
            {
                "item_id": item_id,
                "metadata": metadata,
                "scores": scores,
                "passes": [score >= threshold for score in scores],
                "attempts": attempts,
                "score_count": score_count,
                "pass_count": pass_count,
                "failed_count": item_failed_count,
                "max_score": max_score,
                "pass_at_k": pass_count > 0,
                "pass_hat_k": pass_count == score_count and score_count > 0,
                "consistency": consistency,
                "reliability": reliability,
            }
        )

    total_items = len(items)
    return {
        "metric": metric,
        "threshold": threshold,
        "k": k,
        "total_items": total_items,
        "total_score_count": total_score_count,
        "total_score_sum": total_score_sum,
        "failed_count": failed_count,
        "pass_at_k": pass_at_k_count / total_items if total_items else 0.0,
        "pass_hat_k": pass_hat_k_count / total_items if total_items else 0.0,
        "avg_at_k": total_score_sum / total_score_count if total_score_count else 0.0,
        "avg_score": total_score_sum / total_score_count if total_score_count else 0.0,
        "max_at_k": max_score_sum / total_items if total_items else 0.0,
        "consistency": (
            total_consistency_sum / items_with_multiple_runs
            if items_with_multiple_runs
            else None
        ),
        "reliability": (
            total_reliability_sum / items_with_at_least_one_pass
            if items_with_at_least_one_pass
            else None
        ),
        "avg_latency": (
            total_latency_sum / total_latency_count if total_latency_count else 0.0
        ),
        "median_latency": _median(latency_samples),
        "min_score": min(all_scores) if all_scores else 0.0,
        "stddev_score": _stddev(all_scores),
        "correct_distribution": distribution,
        "items": items,
    }


def compare_group_runs(
    left_results: Sequence[EvaluationResult],
    right_results: Sequence[EvaluationResult],
    *,
    metric: str,
    threshold: float = 0.8,
) -> Dict[str, Any]:
    """Compare two groups using the platform's strict cohort semantics."""
    left_runs = [_rows_for_result(result, metric) for result in left_results]
    right_runs = [_rows_for_result(result, metric) for result in right_results]

    result: Dict[str, Any] = {
        "metric": metric,
        "threshold": threshold,
        "eligible_items": 0,
        "left_run_count": len(left_runs),
        "right_run_count": len(right_runs),
        "k": len(left_runs),
        "left": _finalize_compare_aggregate(_new_compare_aggregate(), 0),
        "right": _finalize_compare_aggregate(_new_compare_aggregate(), 0),
        "deltas": {
            "pass_at_k": 0.0,
            "pass_hat_k": 0.0,
            "avg_at_k": 0.0,
            "consistency": 0.0,
            "reliability": 0.0,
        },
        "summary": {
            "improved_count": 0,
            "regressed_count": 0,
            "unchanged_count": 0,
            "avg_attempts_delta": 0.0,
        },
        "items": [],
        "buckets": _empty_buckets(),
    }

    if not left_runs or not right_runs:
        return result

    item_ids = set()
    for run in [*left_runs, *right_runs]:
        item_ids.update(run.rows.keys())

    left_agg = _new_compare_aggregate()
    right_agg = _new_compare_aggregate()
    total_attempts_delta = 0.0

    for item_id in sorted(item_ids):
        left_values = _collect_group_values(left_runs, item_id)
        if left_values is None:
            continue
        right_values = _collect_group_values(right_runs, item_id)
        if right_values is None:
            continue

        result["eligible_items"] += 1
        _update_compare_aggregate(left_agg, left_values, threshold)
        _update_compare_aggregate(right_agg, right_values, threshold)

        left_passes = [score >= threshold for score in left_values["scores"]]
        right_passes = [score >= threshold for score in right_values["scores"]]
        left_pass_count = sum(1 for passed in left_passes if passed)
        right_pass_count = sum(1 for passed in right_passes if passed)
        move = right_pass_count - left_pass_count

        if move > 0:
            result["summary"]["improved_count"] += 1
        elif move < 0:
            result["summary"]["regressed_count"] += 1
        else:
            result["summary"]["unchanged_count"] += 1

        left_avg_attempts = _mean(left_values["attempts"])
        right_avg_attempts = _mean(right_values["attempts"])
        total_attempts_delta += right_avg_attempts - left_avg_attempts

        item = {
            "item_id": item_id,
            "metadata": left_values["metadata"] or right_values["metadata"] or {},
            "left_scores": left_values["scores"],
            "right_scores": right_values["scores"],
            "left_passes": left_passes,
            "right_passes": right_passes,
            "left_attempts": left_values["attempts"],
            "right_attempts": right_values["attempts"],
            "left_pass_count": left_pass_count,
            "right_pass_count": right_pass_count,
            "left_avg_attempts": left_avg_attempts,
            "right_avg_attempts": right_avg_attempts,
            "move": move,
            "bucket_key": None,
        }

        bucket_key = _bucket_key(left_passes, right_passes)
        if bucket_key is not None:
            item["bucket_key"] = bucket_key
            result["buckets"][bucket_key]["count"] += 1
            result["buckets"][bucket_key]["item_ids"].append(item_id)

        result["items"].append(item)

    eligible_items = result["eligible_items"]
    for bucket in result["buckets"].values():
        bucket["percentage"] = (
            bucket["count"] / eligible_items if eligible_items else 0.0
        )

    result["left"] = _finalize_compare_aggregate(left_agg, eligible_items)
    result["right"] = _finalize_compare_aggregate(right_agg, eligible_items)
    result["deltas"] = {
        "pass_at_k": result["right"]["pass_at_k"] - result["left"]["pass_at_k"],
        "pass_hat_k": result["right"]["pass_hat_k"] - result["left"]["pass_hat_k"],
        "avg_at_k": result["right"]["avg_at_k"] - result["left"]["avg_at_k"],
        "consistency": (result["right"]["consistency"] or 0.0)
        - (result["left"]["consistency"] or 0.0),
        "reliability": (result["right"]["reliability"] or 0.0)
        - (result["left"]["reliability"] or 0.0),
    }
    result["summary"]["avg_attempts_delta"] = (
        total_attempts_delta / eligible_items if eligible_items else 0.0
    )
    result["items"].sort(
        key=lambda item: (
            -item["move"],
            -item["right_pass_count"],
            item["left_pass_count"],
            str(item["item_id"]),
        )
    )
    return result


class GroupRunAnalysis:
    """Convenience wrapper around a group of ``EvaluationResult`` objects."""

    def __init__(self, results: Sequence[EvaluationResult]) -> None:
        self.results = list(results)

    def metric(
        self,
        metric: str,
        *,
        threshold: float = 0.8,
        track_distribution: bool = False,
    ) -> Dict[str, Any]:
        return analyze_group_runs(
            self.results,
            metric=metric,
            threshold=threshold,
            track_distribution=track_distribution,
        )

    def compare_to(
        self,
        other: Sequence[EvaluationResult],
        *,
        metric: str,
        threshold: float = 0.8,
    ) -> Dict[str, Any]:
        return compare_group_runs(
            self.results,
            other,
            metric=metric,
            threshold=threshold,
        )


def _item_metadata(result: EvaluationResult, item_id: str) -> Dict[str, Any]:
    # Item metadata comes from arbitrary dataset sources (JSONL, custom
    # datasets) and is not guaranteed to be a dict.
    metadata = (result.metadatas or {}).get(item_id)
    return dict(metadata) if isinstance(metadata, dict) else {}


def _rows_for_result(result: EvaluationResult, metric: str) -> _RunRows:
    rows: Dict[str, _ScoreRow] = {}
    metric_names = set(result.metrics or [])

    for item_id, item_result in (result.results or {}).items():
        scores = item_result.get("scores", {}) if isinstance(item_result, dict) else {}
        score = parse_score_value(scores.get(metric))
        rows[str(item_id)] = _ScoreRow(
            item_id=str(item_id),
            score=score,
            is_error=False,
            latency_ms=_latency_ms(item_result),
            attempts=_attempts(item_result),
            metadata=_item_metadata(result, item_id),
        )

    if metric in metric_names:
        for item_id, error_info in (result.errors or {}).items():
            if str(item_id) in rows:
                continue
            rows[str(item_id)] = _ScoreRow(
                item_id=str(item_id),
                score=0.0,
                is_error=True,
                latency_ms=_error_latency_ms(error_info),
                attempts=_error_attempts(error_info),
                metadata=_item_metadata(result, item_id),
            )

    return _RunRows(run_name=result.run_name, rows=rows)


def _latency_ms(item_result: Any) -> Optional[float]:
    if not isinstance(item_result, dict):
        return None
    for key in ("latency_ms", "task_time_ms", "total_time_ms", "item_time_ms"):
        value = item_result.get(key)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return float(value)
    seconds = item_result.get("time")
    if isinstance(seconds, (int, float)) and math.isfinite(float(seconds)):
        return float(seconds) * 1000.0
    return None


def _error_latency_ms(error_info: Any) -> Optional[float]:
    if not isinstance(error_info, dict):
        return None
    seconds = error_info.get("time")
    if isinstance(seconds, (int, float)) and math.isfinite(float(seconds)):
        return float(seconds) * 1000.0
    return None


def _attempts(item_result: Any) -> int:
    if not isinstance(item_result, dict):
        return 1
    retry_count = item_result.get("retry_count", 0)
    try:
        return max(1, int(retry_count) + 1)
    except Exception:
        return 1


def _error_attempts(error_info: Any) -> int:
    if not isinstance(error_info, dict):
        return 1
    retry_count = error_info.get("retry_count", 0)
    try:
        return max(1, int(retry_count) + 1)
    except Exception:
        return 1


def _median(values: Sequence[float]) -> float:
    clean = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not clean:
        return 0.0
    mid = len(clean) // 2
    if len(clean) % 2 == 0:
        return (clean[mid - 1] + clean[mid]) / 2.0
    return clean[mid]


def _stddev(values: Sequence[float]) -> float:
    if len(values) <= 1:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _collect_group_values(
    runs: Sequence[_RunRows], item_id: str
) -> Optional[Dict[str, Any]]:
    scores: List[float] = []
    attempts: List[int] = []
    metadata: Dict[str, Any] = {}
    for run in runs:
        row = run.rows.get(item_id)
        if row is None or row.score is None:
            return None
        scores.append(row.score)
        attempts.append(row.attempts)
        metadata = metadata or dict(row.metadata or {})
    return {"scores": scores, "attempts": attempts, "metadata": metadata}


def _new_compare_aggregate() -> Dict[str, Any]:
    return {
        "pass_at_k_count": 0,
        "pass_hat_k_count": 0,
        "total_consistency_sum": 0.0,
        "items_with_multiple_runs": 0,
        "total_reliability_sum": 0.0,
        "items_with_at_least_one_pass": 0,
        "total_score_sum": 0.0,
        "total_score_count": 0,
        "total_attempts_sum": 0.0,
        "total_attempts_count": 0,
    }


def _update_compare_aggregate(
    aggregate: Dict[str, Any], group_values: Dict[str, Any], threshold: float
) -> None:
    scores = group_values["scores"]
    attempts = group_values["attempts"]
    pass_count = sum(1 for score in scores if score >= threshold)
    score_count = len(scores)

    aggregate["total_score_sum"] += sum(scores)
    aggregate["total_score_count"] += score_count
    aggregate["total_attempts_sum"] += sum(attempts)
    aggregate["total_attempts_count"] += len(attempts)

    if pass_count > 0:
        aggregate["pass_at_k_count"] += 1
    if pass_count == score_count and score_count > 0:
        aggregate["pass_hat_k_count"] += 1
    if score_count > 1:
        fail_count = score_count - pass_count
        aggregate["total_consistency_sum"] += (
            2 * max(pass_count, fail_count) / score_count
        ) - 1
        aggregate["items_with_multiple_runs"] += 1
        if pass_count > 0:
            aggregate["total_reliability_sum"] += pass_count / score_count
            aggregate["items_with_at_least_one_pass"] += 1


def _finalize_compare_aggregate(
    aggregate: Dict[str, Any], eligible_items: int
) -> Dict[str, Any]:
    return {
        "pass_at_k": (
            aggregate["pass_at_k_count"] / eligible_items if eligible_items else 0.0
        ),
        "pass_hat_k": (
            aggregate["pass_hat_k_count"] / eligible_items if eligible_items else 0.0
        ),
        "avg_at_k": (
            aggregate["total_score_sum"] / aggregate["total_score_count"]
            if aggregate["total_score_count"]
            else 0.0
        ),
        "consistency": (
            aggregate["total_consistency_sum"] / aggregate["items_with_multiple_runs"]
            if aggregate["items_with_multiple_runs"]
            else None
        ),
        "reliability": (
            aggregate["total_reliability_sum"]
            / aggregate["items_with_at_least_one_pass"]
            if aggregate["items_with_at_least_one_pass"]
            else None
        ),
        "avg_attempts": (
            aggregate["total_attempts_sum"] / aggregate["total_attempts_count"]
            if aggregate["total_attempts_count"]
            else 0.0
        ),
    }


def _empty_buckets() -> Dict[str, Dict[str, Any]]:
    return {
        "a_sweeps_b": {"count": 0, "percentage": 0.0, "item_ids": []},
        "b_sweeps_a": {"count": 0, "percentage": 0.0, "item_ids": []},
        "both_pass": {"count": 0, "percentage": 0.0, "item_ids": []},
        "both_fail": {"count": 0, "percentage": 0.0, "item_ids": []},
    }


def _bucket_key(
    left_passes: Sequence[bool], right_passes: Sequence[bool]
) -> Optional[str]:
    left_all_pass = all(left_passes)
    left_all_fail = all(not value for value in left_passes)
    right_all_pass = all(right_passes)
    right_all_fail = all(not value for value in right_passes)

    if left_all_pass and right_all_fail:
        return "a_sweeps_b"
    if left_all_fail and right_all_pass:
        return "b_sweeps_a"
    if left_all_pass and right_all_pass:
        return "both_pass"
    if left_all_fail and right_all_fail:
        return "both_fail"
    return None


__all__ = [
    "GroupRunAnalysis",
    "analyze_group_runs",
    "compare_group_runs",
    "parse_score_value",
]
