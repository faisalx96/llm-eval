"""Cleanup helpers for run-scoped root-cause analysis data."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from qym_platform.db.models import AuditLog, ReviewCorrection, RootCauseRevision, RunItem


# These fields are maintained by ``root_cause_changes``.  They must be removed
# together so deleting a run cannot leave a diagnosis in its item metadata.
_MANAGED_METADATA_KEYS = frozenset(
    {
        "root_cause",
        "root_cause_detail",
        "root_cause_note",
        "root_cause_source",
        "root_cause_confidence",
        "root_cause_metric_name",
        "solution",
        "solution_note",
        "solution_source",
        "metric_analyses",
    }
)


def purge_run_root_cause_analysis(db: Session, run_id: str) -> dict[str, int]:
    """Remove all run-scoped root-cause analysis while retaining run results.

    Runs are soft-deleted so their evaluation data remains recoverable.  Root
    causes and review candidates are intentionally not recoverable: keeping
    them would make the review queue reference a run that cannot be edited.
    The caller owns the surrounding transaction.
    """

    revisions = (
        db.query(RootCauseRevision.id)
        .filter(RootCauseRevision.run_id == run_id)
        .all()
    )
    revision_ids = [row[0] for row in revisions]

    # Review corrections reference revisions, so delete them first.
    deleted_corrections = (
        db.query(ReviewCorrection)
        .filter(ReviewCorrection.run_id == run_id)
        .delete(synchronize_session=False)
    )
    deleted_revisions = (
        db.query(RootCauseRevision)
        .filter(RootCauseRevision.run_id == run_id)
        .delete(synchronize_session=False)
    )

    # Root-cause changes are also represented in audit rows.  Remove only the
    # analysis audit entries; run lifecycle/audit records remain intact.
    deleted_audit_rows = 0
    if revision_ids:
        deleted_audit_rows += (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_type == "root_cause_revision",
                AuditLog.entity_id.in_([str(value) for value in revision_ids]),
            )
            .delete(synchronize_session=False)
        )
    deleted_audit_rows += (
        db.query(AuditLog)
        .filter(
            AuditLog.entity_type == "run_item_metric_analysis",
            AuditLog.entity_id.like(f"{run_id}:%"),
        )
        .delete(synchronize_session=False)
    )

    cleared_items = 0
    items = db.query(RunItem).filter(RunItem.run_id == run_id).all()
    for item in items:
        metadata: dict[str, Any]
        if isinstance(item.item_metadata, dict):
            metadata = item.item_metadata
        else:
            metadata = {}
        cleaned = {
            key: value
            for key, value in metadata.items()
            if key not in _MANAGED_METADATA_KEYS
        }
        if cleaned != metadata:
            item.item_metadata = cleaned
            cleared_items += 1

    return {
        "review_corrections": int(deleted_corrections or 0),
        "root_cause_revisions": int(deleted_revisions or 0),
        "analysis_audit_logs": int(deleted_audit_rows or 0),
        "items_cleared": cleared_items,
    }
