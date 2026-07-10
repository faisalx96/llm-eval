"""Seed deterministic eval runs that exercise the platform's analysis charts.

The script only owns runs whose IDs start with ``showcase-``. Re-running it is
safe: those runs are replaced in one transaction while all other data remains
untouched.
"""

from __future__ import annotations

import argparse
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any, Iterable

from sqlalchemy.orm import Session

from qym_platform.db.models import (
    Approval,
    Project,
    RootCauseRevision,
    Run,
    RunEvent,
    RunItem,
    RunItemAttempt,
    RunItemPassScore,
    RunItemScore,
    RunTraceAggregate,
    Span,
    ReviewCorrection,
    RunWorkflowStatus,
)
from qym_platform.db.session import SessionLocal


METRICS = ("accuracy", "faithfulness", "relevance", "conciseness")
DOMAINS = ("commerce", "finance", "operations", "support", "analytics")
COMPLEXITIES = (
    "easy",
    "easy",
    "medium",
    "medium",
    "medium",
    "hard",
    "hard",
    "expert",
)
SHOWCASE_PREFIX = "showcase-"


@dataclass(frozen=True)
class Profile:
    run_id: str
    external_run_id: str
    model: str
    samples: int
    quality_shift: float
    latency_base: float
    latency_quality_cost: float
    volatility: float
    story: str


PROFILES = (
    Profile(
        run_id="showcase-balanced-analysis",
        external_run_id="showcase-balanced-analysis-v1",
        model="showcase/nova-sql-balanced",
        samples=5,
        quality_shift=0.02,
        latency_base=760.0,
        latency_quality_cost=260.0,
        volatility=0.10,
        story="Clear metric clusters, correlated quality signals, and a few expensive outliers.",
    ),
    Profile(
        run_id="showcase-deliberate-quality",
        external_run_id="showcase-deliberate-quality-v1",
        model="showcase/nova-sql-deliberate",
        samples=4,
        quality_shift=0.12,
        latency_base=1120.0,
        latency_quality_cost=1150.0,
        volatility=0.045,
        story="The strongest quality run, with a visible latency cost and a clean Pareto frontier.",
    ),
    Profile(
        run_id="showcase-fast-stability",
        external_run_id="showcase-fast-stability-v1",
        model="showcase/nova-sql-fast",
        samples=6,
        quality_shift=-0.035,
        latency_base=430.0,
        latency_quality_cost=90.0,
        volatility=0.19,
        story="Fast responses with pass drift, flaky items, retries, and a late recovery.",
    ),
)


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _pass_adjustment(profile: Profile, pass_number: int, item_index: int) -> float:
    if profile.run_id == "showcase-balanced-analysis":
        trend = (-0.035, 0.015, 0.055, 0.025, 0.065)[pass_number - 1]
    elif profile.run_id == "showcase-deliberate-quality":
        trend = (0.0, 0.025, 0.05, 0.065)[pass_number - 1]
    else:
        trend = (0.065, 0.015, -0.055, -0.11, -0.035, 0.045)[pass_number - 1]

    # Stable cohorts, improving cohorts, degrading cohorts, and deliberately
    # flaky cohorts make the stability plot reveal structure rather than noise.
    cohort = item_index % 7
    if cohort == 0:
        trend += (pass_number - 1) * 0.025
    elif cohort == 1:
        trend -= (pass_number - 1) * 0.022
    elif cohort == 2:
        trend += (1 if pass_number % 2 else -1) * profile.volatility
    elif cohort == 3 and pass_number >= 3:
        trend += 0.07
    return trend


def _item_shape(index: int) -> dict[str, Any]:
    complexity = COMPLEXITIES[index % len(COMPLEXITIES)]
    domain = DOMAINS[(index * 3 + index // 5) % len(DOMAINS)]
    difficulty = {"easy": 0.12, "medium": 0.38, "hard": 0.64, "expert": 0.84}[complexity]
    difficulty = _clip(difficulty + 0.055 * math.sin(index * 1.73), 0.06, 0.94)
    pattern = ("aggregation", "multi-table join", "date logic", "ranking", "nested filter")[index % 5]
    return {
        "item_id": f"sql-{index + 1:03d}",
        "complexity": complexity,
        "domain": domain,
        "difficulty": difficulty,
        "pattern": pattern,
    }


def _metric_values(
    profile: Profile,
    item: dict[str, Any],
    item_index: int,
    pass_number: int,
    rng: random.Random,
) -> dict[str, float]:
    difficulty = float(item["difficulty"])
    domain_bonus = {"commerce": 0.025, "finance": -0.02, "operations": 0.0, "support": 0.04, "analytics": -0.045}[item["domain"]]
    latent = 0.95 - 0.63 * difficulty + profile.quality_shift + domain_bonus
    latent += _pass_adjustment(profile, pass_number, item_index)
    latent += 0.045 * math.sin(item_index * 0.81 + pass_number * 1.17)
    latent = _clip(latent, 0.03, 0.99)

    # Accuracy stays binary so pass@k and the correct-count distribution remain
    # meaningful. The other metrics keep enough resolution for correlations.
    success_draw = rng.random()
    accuracy = 1.0 if success_draw < latent else 0.0
    shared_noise = rng.uniform(-0.035, 0.035)
    faithfulness = _clip(latent + 0.035 + shared_noise)
    relevance = _clip(latent + 0.015 + shared_noise * 0.82 + rng.uniform(-0.025, 0.025))
    # Conciseness intentionally creates a mild quality tension on complex items.
    conciseness = _clip(0.92 - 0.31 * latent - 0.12 * difficulty + rng.uniform(-0.055, 0.055))
    return {
        "accuracy": accuracy,
        "faithfulness": round(faithfulness, 4),
        "relevance": round(relevance, 4),
        "conciseness": round(conciseness, 4),
    }


def _latency_ms(
    profile: Profile,
    item: dict[str, Any],
    item_index: int,
    pass_number: int,
    quality: float,
    rng: random.Random,
) -> float:
    difficulty = float(item["difficulty"])
    latency = profile.latency_base + difficulty * 1250
    latency += profile.latency_quality_cost * quality
    latency += 110 * math.sin(item_index * 1.31 + pass_number)
    latency += rng.uniform(-95, 125)
    if item_index in (7, 19, 31):
        latency += 2100 + item_index * 24
    if profile.run_id == "showcase-fast-stability" and item_index % 9 == 4:
        latency += 900
    return round(max(180.0, latency), 1)


def _trace_stats(profile: Profile) -> dict[str, Any]:
    deliberate = profile.run_id == "showcase-deliberate-quality"
    fast = profile.run_id == "showcase-fast-stability"
    return {
        "has_spans": True,
        "avg_tokens": 2140 if deliberate else (980 if fast else 1510),
        "avg_llm_calls": 2.8 if deliberate else (1.4 if fast else 2.1),
        "avg_tool_calls": 3.2 if deliberate else (1.7 if fast else 2.4),
        "tool_success_rate": 0.968 if deliberate else (0.902 if fast else 0.941),
        "total_malformed_tool_calls": 1 if deliberate else (5 if fast else 2),
        "total_noisy_reasoning": 2 if deliberate else (7 if fast else 3),
        "total_provider_errors": 0 if deliberate else (3 if fast else 1),
        "has_reasoning": True,
        "has_reasoning_tokens": True,
        "avg_reasoning_tokens": 810 if deliberate else (245 if fast else 520),
        "avg_llm_ms": 1780 if deliberate else (610 if fast else 1040),
        "avg_tool_ms": 690 if deliberate else (330 if fast else 470),
        "avg_retriever_ms": 230 if deliberate else (135 if fast else 180),
        "avg_top_level_chain_ms": 3180 if deliberate else (1280 if fast else 2110),
        "avg_evaluator_ms": 390 if deliberate else (275 if fast else 320),
        "outer_scope_parent_spans": [
            {"name": "SQL agent", "avg_ms": 2570 if deliberate else (960 if fast else 1660)},
            {"name": "Schema planner", "avg_ms": 610 if deliberate else (320 if fast else 450)},
        ],
    }


def _root_cause(item_index: int) -> tuple[str, str, str]:
    options = (
        ("Schema ambiguity", "Wrong join path", "Add schema relationship hints"),
        ("Model reasoning", "Aggregation grain mismatch", "Add a query-plan verification step"),
        ("Prompt issue", "Date boundary omitted", "Clarify temporal constraints in the prompt"),
        ("Tool failure", "Schema lookup timed out", "Retry schema lookup with a bounded cache"),
    )
    return options[item_index % len(options)]


def build_showcase(profile: Profile, item_count: int = 42) -> list[dict[str, Any]]:
    """Return a deterministic, database-independent description of one run."""
    rng = random.Random(f"qym-chart-showcase::{profile.run_id}")
    rows: list[dict[str, Any]] = []
    for index in range(item_count):
        item = _item_shape(index)
        passes: list[dict[str, Any]] = []
        for pass_number in range(1, profile.samples + 1):
            scores = _metric_values(profile, item, index, pass_number, rng)
            quality = mean(scores[metric] for metric in ("faithfulness", "relevance"))
            latency = _latency_ms(profile, item, index, pass_number, quality, rng)
            retry = (
                (index + pass_number * 3) % (11 if profile.run_id == "showcase-fast-stability" else 17) == 0
                or (index in (7, 31) and pass_number == 2)
            )
            passes.append(
                {
                    "pass_number": pass_number,
                    "scores": scores,
                    "latency_ms": latency,
                    "retry": retry,
                }
            )
        rows.append({**item, "passes": passes})
    return rows


def _delete_owned_runs(db: Session, run_ids: Iterable[str]) -> None:
    ids = tuple(run_ids)
    if not ids:
        return
    for model in (
        ReviewCorrection,
        RootCauseRevision,
        RunTraceAggregate,
        Span,
        RunEvent,
        Approval,
        RunItemPassScore,
        RunItemScore,
        RunItemAttempt,
        RunItem,
    ):
        db.query(model).filter(model.run_id.in_(ids)).delete(synchronize_session=False)
    db.query(Run).filter(Run.id.in_(ids)).delete(synchronize_session=False)


def _seed_profile(
    db: Session,
    project: Project,
    profile: Profile,
    created_at: datetime,
) -> None:
    rows = build_showcase(profile)
    owner_id = project.created_by_user_id
    ended_at = created_at + timedelta(minutes=8 + profile.samples)
    run = Run(
        id=profile.run_id,
        project_id=project.id,
        external_run_id=profile.external_run_id,
        created_by_user_id=owner_id,
        owner_user_id=owner_id,
        task="text2sql",
        dataset="text2sql-chart-showcase-v1",
        model=profile.model,
        metrics=list(METRICS),
        samples=profile.samples,
        status=RunWorkflowStatus.COMPLETED,
        started_at=created_at,
        ended_at=ended_at,
        last_event_at=ended_at,
        created_at=created_at,
        updated_at=ended_at,
        run_config={
            "samples": profile.samples,
            "max_retries": 2,
            "showcase": True,
            "temperature": 0.2 if profile.run_id != "showcase-fast-stability" else 0.65,
        },
        run_metadata={
            "showcase": True,
            "showcase_story": profile.story,
            "total_items": len(rows),
            "last_completed_pass": profile.samples,
            "trace_stats": _trace_stats(profile),
        },
    )
    db.add(run)
    db.flush()

    run_start_ms = int(created_at.timestamp() * 1000)
    for index, row in enumerate(rows):
        item_id = row["item_id"]
        pass_rows = row["passes"]
        averages = {
            metric: mean(float(pass_row["scores"][metric]) for pass_row in pass_rows)
            for metric in METRICS
        }
        retries = sum(1 for pass_row in pass_rows if pass_row["retry"])
        latencies = [float(pass_row["latency_ms"]) for pass_row in pass_rows]
        is_terminal_error = index in (28, 39) and profile.run_id != "showcase-deliberate-quality"
        root_cause, root_detail, solution = _root_cause(index)
        needs_diagnosis = averages["accuracy"] < 0.6 or row["complexity"] == "expert"
        trace_stats = {
            "tokens": round(_trace_stats(profile)["avg_tokens"] * (0.74 + row["difficulty"] * 0.55)),
            "llm_calls": 3 if row["complexity"] in ("hard", "expert") else 2,
            "tool_calls": 4 if row["complexity"] == "expert" else 2,
            "tool_errors": 1 if retries else 0,
            "reasoning_tokens": round(_trace_stats(profile)["avg_reasoning_tokens"] * (0.8 + row["difficulty"] * 0.4)),
            "has_reasoning": True,
        }
        metadata: dict[str, Any] = {
            "complexity": row["complexity"],
            "domain": [row["domain"], "cross-domain"] if index % 10 == 0 else row["domain"],
            "patterns": [row["pattern"], "schema-linking"],
            "difficulty": round(float(row["difficulty"]), 3),
            "task_started_at_ms": run_start_ms + index * 1500,
            "retry_count": retries,
            "trace_stats": trace_stats,
        }
        if needs_diagnosis:
            metadata.update(
                {
                    "root_cause": root_cause,
                    "root_cause_detail": root_detail,
                    "root_cause_source": "ai",
                    "root_cause_confidence": round(0.68 + (index % 5) * 0.055, 2),
                    "solution": solution,
                    "solution_source": "ai",
                }
            )

        question = (
            f"[{row['domain']}] Write a {row['pattern']} query for benchmark item {index + 1} "
            f"at {row['complexity']} complexity."
        )
        expected = f"SELECT expected_result_{index + 1} FROM benchmark_schema;"
        output = None if is_terminal_error else f"SELECT model_result_{index + 1} FROM benchmark_schema;"
        error = "Provider timeout after final retry" if is_terminal_error else None
        db.add(
            RunItem(
                run_id=profile.run_id,
                item_id=item_id,
                index=index,
                input={"question": question, "schema": f"showcase_{row['domain']}"},
                expected=expected,
                output=output,
                error=error,
                item_metadata=metadata,
                latency_ms=round(mean(latencies), 1),
                retry_count=retries,
                trace_id=f"{profile.run_id[-12:]}-{index + 1:03d}",
                trace_url=None,
            )
        )

        for metric in METRICS:
            value = round(averages[metric], 4)
            db.add(
                RunItemScore(
                    run_id=profile.run_id,
                    item_id=item_id,
                    metric_name=metric,
                    score_numeric=value,
                    score_raw=value,
                    meta={"aggregation": "mean", "passes": profile.samples, "showcase": True},
                    label="pass" if value >= (0.5 if metric == "accuracy" else 0.7) else "fail",
                    explanation=f"Mean {metric} across {profile.samples} evaluation passes.",
                )
            )

        for pass_row in pass_rows:
            pass_number = int(pass_row["pass_number"])
            for metric in METRICS:
                value = float(pass_row["scores"][metric])
                db.add(
                    RunItemPassScore(
                        run_id=profile.run_id,
                        item_id=item_id,
                        metric_name=metric,
                        pass_number=pass_number,
                        score_numeric=value,
                        label="pass" if value >= (0.5 if metric == "accuracy" else 0.7) else "fail",
                    )
                )

            task_started_ms = run_start_ms + (pass_number - 1) * 90_000 + index * 1500
            if pass_row["retry"]:
                db.add(
                    RunItemAttempt(
                        run_id=profile.run_id,
                        item_id=item_id,
                        pass_number=pass_number,
                        attempt_number=1,
                        status="FAILED",
                        latency_ms=round(float(pass_row["latency_ms"]) * 0.34, 1),
                        task_started_at_ms=task_started_ms,
                        error="Transient schema tool timeout",
                        is_last_attempt=False,
                        output=None,
                    )
                )
                attempt_number = 2
            else:
                attempt_number = 1
            final_failed = is_terminal_error and pass_number == profile.samples
            db.add(
                RunItemAttempt(
                    run_id=profile.run_id,
                    item_id=item_id,
                    pass_number=pass_number,
                    attempt_number=attempt_number,
                    status="FAILED" if final_failed else "COMPLETED",
                    latency_ms=float(pass_row["latency_ms"]),
                    task_started_at_ms=task_started_ms,
                    error=error if final_failed else None,
                    is_last_attempt=True,
                    output=None if final_failed else output,
                )
            )


def seed(project_slug: str) -> list[Profile]:
    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.slug == project_slug).first()
        if project is None:
            raise SystemExit(f"Project not found: {project_slug}")

        run_ids = [profile.run_id for profile in PROFILES]
        _delete_owned_runs(db, run_ids)
        base_time = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) - timedelta(
            minutes=50
        )
        for offset, profile in enumerate(PROFILES):
            _seed_profile(db, project, profile, base_time + timedelta(minutes=offset * 18))
        db.commit()
        return list(PROFILES)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def remove() -> None:
    """Remove only the showcase runs created by this script."""
    db = SessionLocal()
    try:
        _delete_owned_runs(db, (profile.run_id for profile in PROFILES))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create deterministic runs that showcase run-detail and compare charts."
    )
    parser.add_argument("--project", default="text2sql", help="Target project slug")
    parser.add_argument(
        "--remove",
        action="store_true",
        help="Remove the showcase runs without replacing them",
    )
    args = parser.parse_args()
    if args.remove:
        remove()
        print("Removed chart showcase runs.")
        return
    profiles = seed(args.project)
    print(f"Seeded {len(profiles)} chart showcase runs in project {args.project}:")
    for profile in profiles:
        print(f"  {profile.run_id}: {profile.story}")


if __name__ == "__main__":
    main()
