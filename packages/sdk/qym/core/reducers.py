"""Reducers: collapse per-item pass scores (samples=k runs) into group metrics.

Two families live here:

1. **Observed group metrics** (:func:`group_stats`) — the platform vocabulary
   (``Pass@k``, ``Pass^k``, ``Avg@k``, ``Max@k``, ``Consistency``,
   ``Reliability``) computed over the k passes actually run. Formulas mirror
   :func:`qym.core.group_analysis.analyze_group_runs` (platform-compatible
   semantics) — keep the two in sync; ``group_analysis`` itself is the
   post-hoc accessor over separate runs and is intentionally not imported.

2. **Unbiased estimators** (:func:`estimate_pass_at` /
   :func:`estimate_pass_hat`) — for ``k < n`` (fewer tries than sampled),
   the Codex/HumanEval combinatorial estimators computed from ``n`` stored
   passes with ``c`` successes. At ``k == n`` they coincide with the
   observed metrics.

All functions are pure and dependency-free (stdlib only).
"""

from __future__ import annotations

import math
import random
import statistics
from typing import Dict, List, Optional, Sequence

DEFAULT_THRESHOLD = 0.8


# ── per-item helpers ─────────────────────────────────────────────────


def _pass_count(scores: Sequence[float], threshold: float) -> int:
    return sum(1 for score in scores if score >= threshold)


def unbiased_pass_at_k(n: int, c: int, k: int) -> float:
    """P(at least one of k random draws from n samples with c correct passes).

    Numerically stable product form of ``1 - C(n-c, k) / C(n, k)``.
    """
    if k <= 0:
        raise ValueError("k must be >= 1")
    if k > n:
        raise ValueError(f"k ({k}) cannot exceed the number of samples ({n})")
    if n - c < k:
        return 1.0
    product = 1.0
    for i in range(n - c + 1, n + 1):
        product *= 1.0 - k / i
    return 1.0 - product


def unbiased_pass_hat_k(n: int, c: int, k: int) -> float:
    """P(all of k random draws from n samples with c correct pass).

    ``C(c, k) / C(n, k)`` — the reliability counterpart of pass@k.
    """
    if k <= 0:
        raise ValueError("k must be >= 1")
    if k > n:
        raise ValueError(f"k ({k}) cannot exceed the number of samples ({n})")
    if c < k:
        return 0.0
    return math.comb(c, k) / math.comb(n, k)


# ── dataset-level reducers (input: item_id -> list of per-pass scores) ──


def estimate_pass_at(
    items_scores: Dict[str, List[float]],
    k: int,
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> float:
    """Mean unbiased pass@k across items, from all stored passes per item."""
    values = [
        unbiased_pass_at_k(len(scores), _pass_count(scores, threshold), k)
        for scores in items_scores.values()
        if scores
    ]
    return sum(values) / len(values) if values else 0.0


def estimate_pass_hat(
    items_scores: Dict[str, List[float]],
    k: int,
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> float:
    """Mean unbiased pass^k across items, from all stored passes per item."""
    values = [
        unbiased_pass_hat_k(len(scores), _pass_count(scores, threshold), k)
        for scores in items_scores.values()
        if scores
    ]
    return sum(values) / len(values) if values else 0.0


def group_stats(
    items_scores: Dict[str, List[float]],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    k: Optional[int] = None,
) -> Dict[str, Optional[float]]:
    """Observed group metrics over the passes actually run.

    Returns the platform-compatible set: ``pass_at_k`` (any pass passed),
    ``pass_hat_k`` (all passes passed), ``avg_at_k`` (mean over all scores),
    ``max_at_k`` (mean of per-item best), ``consistency`` and ``reliability``
    (items with >1 pass only; ``None`` when undefined) plus ``k`` and
    ``total_items``. Key names match ``analyze_group_runs`` output.
    """
    pass_at_k_count = 0
    pass_hat_k_count = 0
    max_score_sum = 0.0
    total_score_sum = 0.0
    total_score_count = 0
    consistency_sum = 0.0
    items_with_multiple = 0
    reliability_sum = 0.0
    items_with_a_pass = 0
    total_items = 0

    for scores in items_scores.values():
        if not scores:
            continue
        total_items += 1
        pass_count = _pass_count(scores, threshold)
        score_count = len(scores)

        if pass_count > 0:
            pass_at_k_count += 1
        if pass_count == score_count:
            pass_hat_k_count += 1

        if score_count > 1:
            fail_count = score_count - pass_count
            consistency_sum += (2 * max(pass_count, fail_count) / score_count) - 1
            items_with_multiple += 1
            if pass_count > 0:
                reliability_sum += pass_count / score_count
                items_with_a_pass += 1

        max_score_sum += max(scores)
        total_score_sum += sum(scores)
        total_score_count += score_count

    resolved_k = k if k is not None else max(
        (len(scores) for scores in items_scores.values()), default=0
    )
    return {
        "k": resolved_k,
        "threshold": threshold,
        "total_items": total_items,
        "pass_at_k": pass_at_k_count / total_items if total_items else 0.0,
        "pass_hat_k": pass_hat_k_count / total_items if total_items else 0.0,
        "avg_at_k": total_score_sum / total_score_count if total_score_count else 0.0,
        "max_at_k": max_score_sum / total_items if total_items else 0.0,
        "consistency": (
            consistency_sum / items_with_multiple if items_with_multiple else None
        ),
        "reliability": (
            reliability_sum / items_with_a_pass if items_with_a_pass else None
        ),
    }


def mean_ci(
    values: Sequence[float],
    *,
    confidence: float = 0.95,
    iterations: int = 2000,
    seed: int = 0,
) -> Dict[str, float]:
    """Percentile-bootstrap confidence interval for the mean (stdlib only).

    Deterministic for a given ``seed`` so repeated renders don't jitter.
    """
    data = list(values)
    if not data:
        return {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0}
    mean = sum(data) / len(data)
    if len(data) == 1:
        return {"mean": mean, "ci_low": mean, "ci_high": mean}

    rng = random.Random(seed)
    n = len(data)
    boot_means = sorted(
        sum(rng.choice(data) for _ in range(n)) / n for _ in range(iterations)
    )
    alpha = (1.0 - confidence) / 2.0
    low_idx = max(0, min(iterations - 1, int(alpha * iterations)))
    high_idx = max(0, min(iterations - 1, int((1.0 - alpha) * iterations) - 1))
    return {
        "mean": mean,
        "ci_low": boot_means[low_idx],
        "ci_high": boot_means[high_idx],
    }


def stddev(values: Sequence[float]) -> float:
    data = list(values)
    if len(data) < 2:
        return 0.0
    return statistics.stdev(data)
