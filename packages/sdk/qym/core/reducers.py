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
from typing import Dict, List, Optional, Sequence, Tuple

DEFAULT_THRESHOLD = 0.8

DEFAULT_CONFIDENCE = 0.95


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
    report_k: Optional[int] = None,
) -> Dict[str, Optional[float]]:
    """Group metrics over the passes actually run.

    Returns the platform-compatible set: ``pass_at_k``, ``pass_hat_k``,
    ``avg_at_k`` (mean over all scores), ``max_at_k`` (mean of per-item best),
    ``consistency`` and ``reliability`` (items with >1 pass only; ``None``
    when undefined) plus ``k`` and ``total_items``. Key names match
    ``analyze_group_runs`` output.

    ``report_k`` decouples the published pass@k from the number of passes
    run: with ``report_k=3`` over 9 stored passes, ``pass_at_k`` is the
    unbiased pass@3 estimator (the exact mean over all 3-pass subsets).
    When ``report_k`` is omitted it defaults to each item's own pass count,
    which makes the estimators coincide with the observed metrics — the
    historical behavior.
    """
    pass_at_k_sum = 0.0
    pass_hat_k_sum = 0.0
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

        k_eff = min(report_k, score_count) if report_k else score_count
        pass_at_k_sum += unbiased_pass_at_k(score_count, pass_count, k_eff)
        pass_hat_k_sum += unbiased_pass_hat_k(score_count, pass_count, k_eff)

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
        "report_k": report_k,
        "threshold": threshold,
        "total_items": total_items,
        "pass_at_k": pass_at_k_sum / total_items if total_items else 0.0,
        "pass_hat_k": pass_hat_k_sum / total_items if total_items else 0.0,
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


def clustered_mean_ci(
    groups: Sequence[Sequence[float]],
    *,
    confidence: float = DEFAULT_CONFIDENCE,
    iterations: int = 2000,
    seed: int = 0,
) -> Dict[str, float]:
    """Percentile-bootstrap CI for the mean of clustered values.

    ``groups`` is one sequence per item (its per-pass scores). Passes of the
    same item are correlated, so the bootstrap resamples whole items and keeps
    each item's passes together — a flat resample of individual passes would
    understate the interval. The point estimate stays the flat mean over all
    passes, matching what the UI displays.
    """
    data = [list(group) for group in groups if group]
    if not data:
        return {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0}
    flat_sum = sum(sum(group) for group in data)
    flat_count = sum(len(group) for group in data)
    mean = flat_sum / flat_count
    if len(data) == 1:
        return {"mean": mean, "ci_low": mean, "ci_high": mean}

    rng = random.Random(seed)
    n = len(data)
    sums = [sum(group) for group in data]
    counts = [len(group) for group in data]
    boot_means = []
    for _ in range(iterations):
        total = 0.0
        count = 0
        for _ in range(n):
            idx = rng.randrange(n)
            total += sums[idx]
            count += counts[idx]
        boot_means.append(total / count if count else 0.0)
    boot_means.sort()
    alpha = (1.0 - confidence) / 2.0
    low_idx = max(0, min(iterations - 1, int(alpha * iterations)))
    high_idx = max(0, min(iterations - 1, int((1.0 - alpha) * iterations) - 1))
    return {
        "mean": mean,
        "ci_low": boot_means[low_idx],
        "ci_high": boot_means[high_idx],
    }


# ── noise report: is a delta between two run groups beyond run luck? ──


def _binom_pmf(n: int, p: float) -> List[float]:
    """Exact Binomial(n, p) pmf over c = 0..n."""
    if p <= 0.0:
        return [1.0] + [0.0] * n
    if p >= 1.0:
        return [0.0] * n + [1.0]
    q = 1.0 - p
    return [math.comb(n, c) * (p**c) * (q ** (n - c)) for c in range(n + 1)]


def _lut_moments(lut: Sequence[float], pmf: Sequence[float]) -> Tuple[float, float]:
    """Mean and variance of ``lut[c]`` with ``c`` distributed per ``pmf``."""
    mean = sum(f * w for f, w in zip(lut, pmf))
    second = sum(f * f * w for f, w in zip(lut, pmf))
    return mean, max(0.0, second - mean * mean)


def _pass_metric_luts(n: int, k_eff: int) -> Dict[str, List[float]]:
    """Per-metric lookup tables over pass count c = 0..n."""
    luts: Dict[str, List[float]] = {
        "pass_at_k": [unbiased_pass_at_k(n, c, k_eff) for c in range(n + 1)],
        "pass_hat_k": [unbiased_pass_hat_k(n, c, k_eff) for c in range(n + 1)],
    }
    if n > 1:
        luts["consistency"] = [
            (2 * max(c, n - c) / n) - 1 for c in range(n + 1)
        ]
    return luts


def noise_report(
    left_items_scores: Dict[str, List[float]],
    right_items_scores: Dict[str, List[float]],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    report_k: Optional[int] = None,
    confidence: float = DEFAULT_CONFIDENCE,
) -> Dict[str, Optional[Dict[str, float]]]:
    """Judge each group-metric delta against run-to-run luck.

    For every metric this answers: *if nothing had truly changed, how far
    could the right-minus-left delta wander on re-run luck alone?* Items are
    paired by id (strict intersection). Under the no-change hypothesis each
    item's pass count is Binomial with the pooled pass rate, so the variance
    of the pass-metric deltas is computed exactly from the estimator lookup
    tables — no simulation, no dependencies. ``avg_at_k`` (continuous) uses
    each item's pooled within-item score variance instead.

    Returns per metric (``pass_at_k``, ``pass_hat_k``, ``avg_at_k``,
    ``consistency``)::

        {"delta": observed right-left delta,
         "half_width": 95% (or ``confidence``) luck band half-width,
         "p_value": two-sided normal p-value,
         "verdict": "improved" | "regressed" | "within_noise"}

    ``reliability`` is reported as ``None``: its per-item exclusion rule
    (items with zero passes drop out) makes the aggregate nonlinear, so it
    gets no band rather than a wrong one.
    """
    shared = [
        item_id
        for item_id in left_items_scores
        if left_items_scores[item_id] and right_items_scores.get(item_id)
    ]
    out: Dict[str, Optional[Dict[str, float]]] = {"reliability": None}
    metric_names = ("pass_at_k", "pass_hat_k", "avg_at_k", "consistency")
    if not shared:
        out.update({name: None for name in metric_names})
        return out

    normal = statistics.NormalDist()
    z_crit = normal.inv_cdf(0.5 + confidence / 2.0)

    # Per-metric accumulators: observed sums per side, delta variance, count.
    sums_left: Dict[str, float] = {}
    sums_right: Dict[str, float] = {}
    variances: Dict[str, float] = {}
    counts: Dict[str, int] = {}
    avg_df_items = 0
    lut_cache: Dict[Tuple[int, int], Dict[str, List[float]]] = {}

    for item_id in shared:
        left_scores = left_items_scores[item_id]
        right_scores = right_items_scores[item_id]
        n_left, n_right = len(left_scores), len(right_scores)
        c_left = _pass_count(left_scores, threshold)
        c_right = _pass_count(right_scores, threshold)
        pooled_p = (c_left + c_right) / (n_left + n_right)

        k_left = min(report_k, n_left) if report_k else n_left
        k_right = min(report_k, n_right) if report_k else n_right
        luts_left = lut_cache.setdefault(
            (n_left, k_left), _pass_metric_luts(n_left, k_left)
        )
        luts_right = lut_cache.setdefault(
            (n_right, k_right), _pass_metric_luts(n_right, k_right)
        )
        pmf_left = _binom_pmf(n_left, pooled_p)
        pmf_right = _binom_pmf(n_right, pooled_p)
        # A metric contributes only when defined on both sides (e.g.
        # consistency needs >1 pass per side).
        for name in luts_left.keys() & luts_right.keys():
            sums_left[name] = sums_left.get(name, 0.0) + luts_left[name][c_left]
            sums_right[name] = sums_right.get(name, 0.0) + luts_right[name][c_right]
            counts[name] = counts.get(name, 0) + 1
            _, var_left = _lut_moments(luts_left[name], pmf_left)
            _, var_right = _lut_moments(luts_right[name], pmf_right)
            variances[name] = variances.get(name, 0.0) + var_left + var_right

        # avg_at_k: continuous scores, pooled within-item variance.
        sums_left["avg_at_k"] = sums_left.get("avg_at_k", 0.0) + _mean_of(left_scores)
        sums_right["avg_at_k"] = sums_right.get("avg_at_k", 0.0) + _mean_of(
            right_scores
        )
        counts["avg_at_k"] = counts.get("avg_at_k", 0) + 1
        if n_left + n_right > 2:
            avg_df_items += 1
            pooled_var = _pooled_within_variance(left_scores, right_scores)
            variances["avg_at_k"] = variances.get("avg_at_k", 0.0) + pooled_var * (
                1.0 / n_left + 1.0 / n_right
            )

    for name in metric_names:
        n_items = counts.get(name, 0)
        if not n_items:
            out[name] = None
            continue
        # Single score per item per side: within-item variance is not
        # estimable, so avg gets no band rather than a false ±0.
        if name == "avg_at_k" and not avg_df_items:
            out[name] = None
            continue
        delta = (sums_right.get(name, 0.0) - sums_left.get(name, 0.0)) / n_items
        sd = math.sqrt(variances.get(name, 0.0)) / n_items
        half_width = z_crit * sd
        if sd > 0:
            p_value = 2.0 * (1.0 - normal.cdf(abs(delta) / sd))
        else:
            p_value = 1.0 if delta == 0 else 0.0
        if delta > half_width:
            verdict = "improved"
        elif delta < -half_width:
            verdict = "regressed"
        else:
            verdict = "within_noise"
        out[name] = {
            "delta": delta,
            "half_width": half_width,
            "p_value": p_value,
            "verdict": verdict,
        }
    return out


def _mean_of(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _pooled_within_variance(
    left: Sequence[float], right: Sequence[float]
) -> float:
    """Pooled within-side sample variance of one item's scores."""
    df = len(left) + len(right) - 2
    if df <= 0:
        return 0.0
    ss = 0.0
    for side in (left, right):
        mean = _mean_of(side)
        ss += sum((value - mean) ** 2 for value in side)
    return ss / df


def stddev(values: Sequence[float]) -> float:
    data = list(values)
    if len(data) < 2:
        return 0.0
    return statistics.stdev(data)
