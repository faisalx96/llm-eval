"""Duplicate a run with SQL-only output and promote accuracy result tables.

The source run stores each item's ``output`` as a Python ``repr`` of a dict
containing ``sql``/``agent_response``/``langfuse_url``. The ``accuracy`` metric
score keeps ``llm_result`` and ``expected_result`` tables inside its metadata.

The duplicate run restructures each item so:

* ``output`` is a proper JSON object with ``sql``, ``llm_result`` and
  ``expected_result`` keys so the two result tables render next to the SQL.
* The ``accuracy`` metric metadata no longer repeats the two result tables.

Run inside the platform container (matches ``import_local_results.py`` style)::

    docker exec -i docker-api-1 python -m qym_platform.tools.duplicate_run_sql_only \\
        --source-run-id df73cf63-8f2b-4ef4-81ef-e40926e24bf3
"""

from __future__ import annotations

import argparse
import ast
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from qym_platform.db.models import Run, RunItem, RunItemScore
from qym_platform.db.session import SessionLocal

RESULT_META_KEYS = ("llm_result", "expected_result")


def _parse_output(value: Any) -> Optional[Dict[str, Any]]:
    """Turn the stored output into a dict, supporting both Python reprs and JSON."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    return None


def _new_output(parsed: Optional[Dict[str, Any]], accuracy_meta: Dict[str, Any]) -> Dict[str, Any]:
    """Build the new item output with only the SQL + the two result tables."""
    sql = ""
    if isinstance(parsed, dict):
        raw_sql = parsed.get("sql")
        if isinstance(raw_sql, str):
            sql = raw_sql

    output: Dict[str, Any] = {"sql": sql}
    for key in RESULT_META_KEYS:
        if key in accuracy_meta and accuracy_meta[key] is not None:
            output[key] = accuracy_meta[key]
    return output


def _strip_result_meta(meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    clean = dict(meta or {})
    for key in RESULT_META_KEYS:
        clean.pop(key, None)
    return clean


def duplicate_run(db: Session, source_run_id: str, new_task_suffix: str = " (sql-only)") -> str:
    src = db.query(Run).filter(Run.id == source_run_id).first()
    if not src:
        raise SystemExit(f"Source run {source_run_id} not found")

    new_id = str(uuid4())
    now = datetime.utcnow()
    run_metadata = dict(src.run_metadata or {})
    run_metadata["duplicated_from"] = source_run_id
    run_metadata["duplicate_variant"] = "sql_only_with_result_tables"
    run_config = dict(src.run_config or {})
    existing_name = run_config.get("run_name", "")
    run_config["run_name"] = (existing_name + new_task_suffix).strip() if existing_name else f"{src.task}{new_task_suffix}"

    new_run = Run(
        id=new_id,
        project_id=src.project_id,
        external_run_id=None,
        created_by_user_id=src.created_by_user_id,
        owner_user_id=src.owner_user_id,
        task=src.task,
        dataset=src.dataset,
        model=src.model,
        metrics=list(src.metrics or []),
        run_metadata=run_metadata,
        run_config=run_config,
        status=src.status,
        started_at=src.started_at,
        ended_at=src.ended_at,
        last_event_at=src.last_event_at,
        created_at=now,
        updated_at=now,
    )
    db.add(new_run)
    db.flush()

    items = (
        db.query(RunItem)
        .filter(RunItem.run_id == source_run_id)
        .order_by(RunItem.index.asc())
        .all()
    )
    scores = db.query(RunItemScore).filter(RunItemScore.run_id == source_run_id).all()
    scores_by_item: Dict[str, list[RunItemScore]] = {}
    for score in scores:
        scores_by_item.setdefault(score.item_id, []).append(score)

    for item in items:
        parsed = _parse_output(item.output)
        accuracy_meta: Dict[str, Any] = {}
        for score in scores_by_item.get(item.item_id, []):
            if score.metric_name == "accuracy":
                accuracy_meta = dict(score.meta or {})
                break

        new_output = _new_output(parsed, accuracy_meta)

        db.add(
            RunItem(
                run_id=new_id,
                item_id=item.item_id,
                index=item.index,
                input=item.input,
                expected=item.expected,
                output=new_output,
                error=item.error,
                item_metadata=dict(item.item_metadata or {}),
                latency_ms=item.latency_ms,
                retry_count=item.retry_count,
                trace_id=item.trace_id,
                trace_url=item.trace_url,
            )
        )

        for score in scores_by_item.get(item.item_id, []):
            meta = _strip_result_meta(score.meta) if score.metric_name == "accuracy" else dict(score.meta or {})
            db.add(
                RunItemScore(
                    run_id=new_id,
                    item_id=score.item_id,
                    metric_name=score.metric_name,
                    score_numeric=score.score_numeric,
                    score_raw=score.score_raw,
                    meta=meta,
                    label=score.label,
                    explanation=score.explanation,
                )
            )

    db.commit()
    return new_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run-id", required=True, help="Source run id to duplicate")
    parser.add_argument(
        "--suffix",
        default=" (sql-only)",
        help="Suffix appended to the duplicate's run_name",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        new_id = duplicate_run(db, args.source_run_id, new_task_suffix=args.suffix)
    print(new_id)


if __name__ == "__main__":
    main()
