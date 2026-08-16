"""Resolve reviewer-approved diagnoses for reporting and insight consumers."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Sequence

from qym_platform.db.models import CorrectionStatus, ReviewCorrection, RunItem
from qym_platform.services.root_cause_categories import (
    analysis_root_causes,
    normalize_root_causes,
)
from sqlalchemy.orm import Session

DiagnosisEntry = dict[str, Any]
DiagnosisScope = tuple[str, str, str | None]


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _correction_categories(correction: ReviewCorrection) -> list[str]:
    return normalize_root_causes(
        correction.human_root_causes
        or correction.human_root_cause
        or correction.ai_root_causes
        or correction.ai_root_cause
    )


def _correction_source(correction: ReviewCorrection) -> str:
    return (
        "human"
        if normalize_root_causes(
            correction.human_root_causes or correction.human_root_cause
        )
        else "ai"
    )


def _metadata_entries(item: RunItem) -> list[DiagnosisEntry]:
    """Return only metadata entries carrying an explicit approval marker.

    Most current approvals have a corresponding ``ReviewCorrection`` row. The
    marker fallback covers pass-scoped and older records that persist approval
    directly beside the diagnosis rather than in the correction table.
    """
    metadata = item.item_metadata if isinstance(item.item_metadata, dict) else {}
    entries: list[DiagnosisEntry] = []
    metric_analyses = metadata.get("metric_analyses")
    if isinstance(metric_analyses, dict) and metric_analyses:
        for raw_metric, raw_analysis in metric_analyses.items():
            if not isinstance(raw_analysis, dict):
                continue
            if _clean(raw_analysis.get("review_status")).lower() != "approved":
                continue
            categories = analysis_root_causes(raw_analysis)
            if raw_analysis.get("error") or not categories:
                continue
            entries.extend(
                {
                    "metric_name": _clean(raw_metric) or None,
                    "category": category,
                    "detail": _clean(raw_analysis.get("root_cause_detail")),
                    "note": _clean(raw_analysis.get("root_cause_note")),
                    "confidence": raw_analysis.get("confidence"),
                    "source": _clean(
                        raw_analysis.get("source")
                        or raw_analysis.get("root_cause_source")
                        or "unknown"
                    ).lower(),
                    "review_status": "approved",
                }
                for category in categories
            )
        return entries

    if _clean(metadata.get("review_status")).lower() != "approved":
        return []
    categories = analysis_root_causes(metadata)
    if not categories or _clean(metadata.get("analysis_error")):
        return []
    entries.extend(
        {
            "metric_name": None,
            "category": category,
            "detail": _clean(metadata.get("root_cause_detail")),
            "note": _clean(metadata.get("root_cause_note")),
            "confidence": metadata.get("root_cause_confidence"),
            "source": _clean(metadata.get("root_cause_source") or "unknown").lower(),
            "review_status": "approved",
        }
        for category in categories
    )
    return entries


def load_approved_diagnoses(
    db: Session,
    run_ids: Sequence[str] | Iterable[str],
    items: Sequence[RunItem] | None = None,
) -> dict[tuple[str, str], list[DiagnosisEntry]]:
    """Load the effective approved diagnosis entries grouped by run item.

    Active approved corrections are authoritative over item metadata. This is
    important because AI analyses remain in ``item_metadata`` while their
    review candidate is pending, and because an approved human correction can
    differ from the original AI label. Explicitly approved metadata is used
    only when no correction exists for the same metric scope.
    """
    normalized_run_ids = tuple(
        dict.fromkeys(_clean(run_id) for run_id in run_ids if _clean(run_id))
    )
    if not normalized_run_ids:
        return {}

    corrections = (
        db.query(ReviewCorrection)
        .filter(
            ReviewCorrection.run_id.in_(normalized_run_ids),
            ReviewCorrection.status == CorrectionStatus.APPROVED,
            ReviewCorrection.is_active.is_(True),
        )
        .order_by(ReviewCorrection.created_at.desc(), ReviewCorrection.id.desc())
        .all()
    )

    result: dict[tuple[str, str], list[DiagnosisEntry]] = defaultdict(list)
    approved_scopes: set[DiagnosisScope] = set()
    seen_scopes: set[DiagnosisScope] = set()
    for correction in corrections:
        scope: DiagnosisScope = (
            correction.run_id,
            correction.item_id,
            _clean(correction.metric_name) or None,
        )
        # Normally only one active row can exist for a scope. If old data has
        # more than one, the newest approved row is the effective diagnosis.
        if scope in seen_scopes:
            continue
        seen_scopes.add(scope)
        approved_scopes.add(scope)
        categories = _correction_categories(correction)
        if not categories:
            continue
        detail = _clean(
            correction.human_root_cause_detail or correction.ai_root_cause_detail
        )
        note = _clean(correction.human_root_cause_note or correction.ai_root_cause_note)
        source = _correction_source(correction)
        result[(correction.run_id, correction.item_id)].extend(
            {
                "metric_name": scope[2],
                "category": category,
                "detail": detail,
                "note": note,
                "confidence": correction.ai_confidence,
                "source": source,
                "review_status": "approved",
            }
            for category in categories
        )

    for item in items or ():
        key = (item.run_id, item.item_id)
        metadata_entries = _metadata_entries(item)
        for entry in metadata_entries:
            scope = (item.run_id, item.item_id, entry.get("metric_name"))
            if (
                scope in approved_scopes
                or (
                    item.run_id,
                    item.item_id,
                    None,
                )
                in approved_scopes
            ):
                continue
            result[key].append(entry)

    return dict(result)


__all__ = ["DiagnosisEntry", "DiagnosisScope", "load_approved_diagnoses"]
