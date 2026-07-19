"""Canonical repeat-performance curves and persistent uncertainty cache."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from sqlalchemy.orm import Session

from qym.core.reducers import mean_ci, unbiased_pass_at_k, unbiased_pass_hat_k
from qym_platform.db.models import RunMetricAnalysis


CONFIDENCE = 0.95
BOOTSTRAP_ITERATIONS = 2000
MIN_UNCERTAINTY_ITEMS = 20
METHOD_VERSION = 1


ScoreRow = Tuple[str, int, float]


def score_signature(rows: Iterable[ScoreRow]) -> str:
    """Stable digest used to invalidate cached curves after score edits."""

    digest = hashlib.sha256()
    for item_id, pass_number, score in rows:
        digest.update(str(item_id).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(int(pass_number)).encode("ascii"))
        digest.update(b"\0")
        digest.update(float(score).hex().encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _interval(values: Sequence[float], *, seed: int) -> Dict[str, float] | None:
    if len(values) < MIN_UNCERTAINTY_ITEMS:
        return None
    result = mean_ci(
        values,
        confidence=CONFIDENCE,
        iterations=BOOTSTRAP_ITERATIONS,
        seed=seed,
    )
    return {"low": result["ci_low"], "high": result["ci_high"]}


def build_repeat_analysis(
    items_scores: Dict[str, List[float]],
    *,
    threshold: float,
    samples: int,
) -> Dict[str, Any]:
    """Build Pass@k, Pass^k, and cumulative-average curves with item CIs."""

    max_k = max((len(scores) for scores in items_scores.values()), default=0)
    band: Dict[int, Dict[str, Any]] = {}
    for k in range(1, max_k + 1):
        eligible = [scores for scores in items_scores.values() if len(scores) >= k]
        pass_at_values: List[float] = []
        pass_hat_values: List[float] = []
        cumulative_values: List[float] = []
        for scores in eligible:
            correct = sum(1 for score in scores if score >= threshold)
            pass_at_values.append(unbiased_pass_at_k(len(scores), correct, k))
            pass_hat_values.append(unbiased_pass_hat_k(len(scores), correct, k))
            cumulative_values.append(sum(scores[:k]) / k)

        def average(values: Sequence[float]) -> float:
            return sum(values) / len(values) if values else 0.0

        seed = 1777 + k * 97
        band[k] = {
            "pass_at_k": average(pass_at_values),
            "pass_hat_k": average(pass_hat_values),
            "cumulative_avg": average(cumulative_values),
            "n_items": len(eligible),
            "uncertainty": {
                "pass_at_k": _interval(pass_at_values, seed=seed),
                "pass_hat_k": _interval(pass_hat_values, seed=seed),
                "cumulative_avg": _interval(cumulative_values, seed=seed),
            },
        }

    distribution = [0] * (samples + 1)
    for scores in items_scores.values():
        correct = sum(1 for score in scores if score >= threshold)
        distribution[min(correct, samples)] += 1

    return {
        "band": band,
        "distribution": distribution,
        "confidence": CONFIDENCE,
        "bootstrap_iterations": BOOTSTRAP_ITERATIONS,
        "minimum_uncertainty_items": MIN_UNCERTAINTY_ITEMS,
        "method": "item_bootstrap",
        "method_version": METHOD_VERSION,
    }


def cached_repeat_analysis(
    db: Session,
    *,
    run_id: str,
    metric_name: str,
    threshold: float,
    samples: int,
    rows: Sequence[ScoreRow],
    items_scores: Dict[str, List[float]],
) -> Dict[str, Any]:
    """Return a persisted curve, recomputing only when its score digest changes."""

    threshold_micros = round(float(threshold) * 1_000_000)
    signature = score_signature(rows)
    cached = (
        db.query(RunMetricAnalysis)
        .filter(
            RunMetricAnalysis.run_id == run_id,
            RunMetricAnalysis.metric_name == metric_name,
            RunMetricAnalysis.threshold_micros == threshold_micros,
            RunMetricAnalysis.method_version == METHOD_VERSION,
        )
        .first()
    )
    if cached and cached.source_signature == signature:
        payload = dict(cached.payload or {})
        payload["band"] = {
            int(k): value for k, value in (payload.get("band") or {}).items()
        }
        return payload

    payload = build_repeat_analysis(
        items_scores,
        threshold=threshold,
        samples=samples,
    )
    if cached:
        cached.source_signature = signature
        cached.payload = payload
    else:
        db.add(
            RunMetricAnalysis(
                run_id=run_id,
                metric_name=metric_name,
                threshold_micros=threshold_micros,
                method_version=METHOD_VERSION,
                source_signature=signature,
                payload=payload,
            )
        )
    db.commit()
    return payload
