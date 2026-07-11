"""Metric definitions and score semantics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, Literal, Optional


ScoreType = Literal["boolean", "percentage", "count", "number", "legacy"]
Direction = Literal["maximize", "minimize"]
Reducer = Literal["mean", "sum", "min", "max"]


@dataclass(frozen=True)
class MetricSpec:
    """Immutable semantics used to validate, aggregate, and display a metric."""

    score_type: ScoreType
    direction: Direction = "maximize"
    pass_threshold: Optional[float] = None
    sample_reducer: Reducer = "mean"
    run_reducer: Reducer = "mean"
    unit: Optional[str] = None
    precision: Optional[int] = None

    def __post_init__(self) -> None:
        if self.score_type not in {
            "boolean",
            "percentage",
            "count",
            "number",
            "legacy",
        }:
            raise ValueError(f"Unsupported metric score_type: {self.score_type!r}")
        if self.direction not in {"maximize", "minimize"}:
            raise ValueError(f"Unsupported metric direction: {self.direction!r}")
        for field_name in ("sample_reducer", "run_reducer"):
            if getattr(self, field_name) not in {"mean", "sum", "min", "max"}:
                raise ValueError(
                    f"Unsupported {field_name}: {getattr(self, field_name)!r}"
                )
            if getattr(self, field_name) != "mean":
                raise ValueError(f"{field_name} currently supports only 'mean'")
        if self.pass_threshold is not None and not math.isfinite(
            float(self.pass_threshold)
        ):
            raise ValueError("pass_threshold must be finite")
        if self.score_type == "boolean" and self.pass_threshold is not None:
            raise ValueError(
                "boolean metrics use True as the pass condition; omit pass_threshold"
            )
        if self.score_type == "percentage" and self.pass_threshold is not None:
            if not 0.0 <= float(self.pass_threshold) <= 1.0:
                raise ValueError("percentage pass_threshold must be between 0 and 1")
        if self.precision is not None and not 0 <= self.precision <= 12:
            raise ValueError("precision must be between 0 and 12")

    def validate_score(self, value: Any) -> float:
        """Validate one observation and return its numeric aggregation value."""
        if self.score_type == "legacy":
            if isinstance(value, bool):
                return 1.0 if value else 0.0
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                return float(value)
            raise TypeError("legacy metric scores must be bool, int, or float")

        if self.score_type == "boolean":
            if isinstance(value, bool):
                return 1.0 if value else 0.0
            if isinstance(value, (int, float)) and float(value) in {0.0, 1.0}:
                return float(value)
            raise TypeError("boolean metric must return bool, 0, or 1")

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(
                f"{self.score_type} metric must return a number, got {type(value).__name__}"
            )
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"{self.score_type} metric must return a finite number")
        if self.score_type == "percentage" and not 0.0 <= numeric <= 1.0:
            raise ValueError("percentage metric must return a value between 0 and 1")
        if self.score_type == "count":
            if numeric < 0 or not numeric.is_integer():
                raise ValueError("count metric must return a non-negative integer")
        return numeric

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "score_type": self.score_type,
            "direction": self.direction,
            "pass_threshold": self.pass_threshold,
            "sample_reducer": self.sample_reducer,
            "run_reducer": self.run_reducer,
            "unit": self.unit,
            "precision": self.precision,
        }


@dataclass(frozen=True, init=False)
class Metric:
    """A metric callable paired with explicit score semantics."""

    fn: Callable[..., Any]
    name: str
    spec: MetricSpec

    def __init__(
        self,
        fn: Callable[..., Any],
        *,
        name: Optional[str] = None,
        spec: Optional[MetricSpec] = None,
        score_type: Optional[ScoreType] = None,
        direction: Direction = "maximize",
        pass_threshold: Optional[float] = None,
        sample_reducer: Reducer = "mean",
        run_reducer: Reducer = "mean",
        unit: Optional[str] = None,
        precision: Optional[int] = None,
    ) -> None:
        if not callable(fn):
            raise TypeError("Metric fn must be callable")
        if spec is not None and score_type is not None:
            raise ValueError("Pass either spec= or score_type=, not both")
        if spec is None:
            if score_type is None:
                raise ValueError("Metric requires score_type= or spec=")
            spec = MetricSpec(
                score_type=score_type,
                direction=direction,
                pass_threshold=pass_threshold,
                sample_reducer=sample_reducer,
                run_reducer=run_reducer,
                unit=unit,
                precision=precision,
            )
        metric_name = (name or getattr(fn, "__name__", "")).strip()
        if not metric_name:
            raise ValueError("Metric requires name= when the callable has no __name__")
        object.__setattr__(self, "fn", fn)
        object.__setattr__(self, "name", metric_name)
        object.__setattr__(self, "spec", spec)
