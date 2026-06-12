"""Structured score model for evaluation metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional


@dataclass
class MetricResult:
    """Structured result from any metric evaluation.

    Replaces loose dicts/floats with a formal model that carries score, label,
    explanation, and provenance metadata.  Backward-compatible — existing metrics
    that return plain floats or dicts are transparently wrapped via ``from_raw``.
    """

    score: float
    label: Optional[str] = None
    explanation: Optional[str] = None
    kind: Literal["llm", "code", "human"] = "code"
    direction: Literal["maximize", "minimize"] = "maximize"
    metadata: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_raw(raw: Any) -> "MetricResult":
        """Wrap a raw metric return value into a MetricResult."""
        if isinstance(raw, MetricResult):
            return raw

        if isinstance(raw, bool):
            return MetricResult(score=1.0 if raw else 0.0)

        if isinstance(raw, (int, float)):
            return MetricResult(score=float(raw))

        if isinstance(raw, dict):
            if "error" in raw:
                # Audit EI-1: keep score=0.0 for backward compatibility of
                # arithmetic, but PRESERVE the error marker (plus any sibling
                # metadata) in metadata so downstream exclusion logic
                # (qym.core.results.is_errored_metric_value) recognizes this
                # result as errored instead of averaging it in as 0.0.
                md = raw.get("metadata")
                md = dict(md) if isinstance(md, dict) else {}
                md["error"] = raw["error"]
                return MetricResult(
                    score=0.0,
                    label=raw.get("label"),
                    explanation=raw.get("explanation"),
                    metadata=md,
                )

            score_val = raw.get("score")
            if isinstance(score_val, bool):
                score_val = 1.0 if score_val else 0.0
            elif isinstance(score_val, (int, float)):
                score_val = float(score_val)
            else:
                score_val = 0.0

            md = raw.get("metadata", {})
            if not isinstance(md, dict):
                md = {}

            return MetricResult(
                score=score_val,
                label=raw.get("label"),
                explanation=raw.get("explanation"),
                metadata=md,
            )

        return MetricResult(score=0.0, metadata={"raw": raw})

    @property
    def is_errored(self) -> bool:
        """True when this result represents a failed metric evaluation.

        Shared convention (audit EI-1): errored iff metadata carries an
        ``'error'`` key or the score is ``None``. Errored results keep
        ``score=0.0`` for arithmetic backward compatibility but must be
        EXCLUDED from aggregation by callers.
        """
        if isinstance(self.metadata, dict) and "error" in self.metadata:
            return True
        return self.score is None

    def to_legacy_dict(self) -> Dict[str, Any]:
        """Convert to {"score": float, "metadata": dict} for backward compat."""
        md = dict(self.metadata)
        if self.label is not None:
            md["label"] = self.label
        if self.explanation is not None:
            md["explanation"] = self.explanation
        if self.kind != "code":
            md["kind"] = self.kind
        return {"score": self.score, "metadata": md}
