"""Ingest a single CSV results file as a run *verbatim* (no transformations).

This is the "as-is" sibling of :mod:`upload_csv_sql_only`. It mirrors the
platform's ``POST /runs:upload`` CSV path exactly:

* ``output`` is stored as the raw string from the CSV (or ``None`` + ``error``
  when the cell starts with ``ERROR:``). No ``{sql, llm_result, ...}`` rewrite.
* Metric scores are taken straight from the ``<metric>_score`` columns. No
  OR(llm_judge, exact_match) recomputation for accuracy.
* ``external_run_id`` defaults to the CSV ``run_name`` unchanged, so the
  dashboard's timestamp-based grouping (``YYMMDD-HHMM``) keeps repeated runs in
  a single group.
* ``item_id`` uses the CSV value when it is non-positional, otherwise an
  identity fingerprint — matching the API.

Run from the host; the CSV is fed in via stdin so the container does not need
to mount the file::

    docker exec -i docker-api-1 python -m qym_platform.tools.upload_csv_plain \\
        --owner-email faisalx96@yahoo.com \\
        --project-slug insightor \\
        --commit \\
        < /path/to/results.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from qym_platform.datetime_utils import utc_now_naive
from qym_platform.db.models import (
    Project,
    Run,
    RunItem,
    RunItemScore,
    RunWorkflowStatus,
    User,
)
from qym_platform.db.session import SessionLocal
from qym_platform.item_identity import (
    build_identity_fingerprint,
    looks_like_positional_item_id,
)

csv.field_size_limit(sys.maxsize)


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def ingest_csv(
    db: Session,
    *,
    csv_text: str,
    project: Project,
    owner: User,
    external_run_id: Optional[str],
) -> Dict[str, Any]:
    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = list(reader.fieldnames or [])
    metrics = [
        c.replace("_score", "")
        for c in fieldnames
        if c.endswith("_score") and "__meta__" not in c
    ]
    rows = list(reader)
    if not rows:
        raise SystemExit("CSV has no data rows")

    first = rows[0]
    dataset = first.get("dataset_name") or ""
    run_metadata = _sanitize(json.loads(first["run_metadata"])) if first.get("run_metadata") else {}
    run_config = _sanitize(json.loads(first["run_config"])) if first.get("run_config") else {}
    run_metadata = run_metadata or {}
    run_config = run_config or {}

    model_name = str(run_metadata.get("model") or "") or None
    task_name = str(run_metadata.get("task_name") or "insightor_api")

    if not external_run_id:
        external_run_id = (first.get("run_name") or "").strip() or None

    existing = (
        db.query(Run)
        .filter(Run.project_id == project.id, Run.external_run_id == external_run_id)
        .first()
    )
    if existing:
        raise SystemExit(
            f"Run already exists for external_run_id={external_run_id!r} -> {existing.id}. "
            "Pick a different --external-run-id or delete the existing run."
        )

    run = Run(
        project_id=project.id,
        external_run_id=external_run_id,
        created_by_user_id=owner.id,
        owner_user_id=owner.id,
        task=task_name,
        dataset=dataset,
        model=model_name,
        metrics=metrics,
        run_metadata=run_metadata,
        run_config=run_config,
        status=RunWorkflowStatus.COMPLETED,
        started_at=utc_now_naive(),
        ended_at=utc_now_naive(),
    )
    db.add(run)
    db.flush()

    fingerprint_counts: Dict[str, int] = {}
    items_count = 0
    scores_count = 0

    for idx, row in enumerate(rows):
        raw_meta = row.get("item_metadata") or ""
        try:
            parsed_meta = json.loads(raw_meta) if raw_meta else {}
        except (json.JSONDecodeError, TypeError):
            parsed_meta = {}
        if not isinstance(parsed_meta, dict):
            parsed_meta = {}

        raw_item_id = str(row.get("item_id") or "").strip()
        if raw_item_id and not looks_like_positional_item_id(raw_item_id):
            item_id = raw_item_id
        else:
            fp = build_identity_fingerprint(
                input_value=row.get("input") or "",
                expected_value=row.get("expected_output") or "",
                metadata=parsed_meta,
            )
            fingerprint_counts[fp] = fingerprint_counts.get(fp, 0) + 1
            item_id = f"csv_{fp}__{fingerprint_counts[fp]:04d}"

        raw_output = str(row.get("output") or "")
        is_error = raw_output.startswith("ERROR:")

        db.add(
            RunItem(
                run_id=run.id,
                item_id=item_id,
                index=idx,
                input=row.get("input"),
                expected=row.get("expected_output"),
                output=None if is_error else row.get("output"),
                error=(raw_output[6:].strip() if is_error else None),
                item_metadata=parsed_meta,
                latency_ms=(float(row.get("time") or 0.0) * 1000.0),
                trace_id=row.get("trace_id") or None,
                trace_url=None,
            )
        )
        items_count += 1

        for m in metrics:
            raw_val = row.get(f"{m}_score")
            score_numeric: Optional[float] = None
            try:
                if not is_error and raw_val not in (None, "", "N/A"):
                    score_numeric = float(raw_val)
                elif is_error:
                    score_numeric = 0.0
            except (TypeError, ValueError):
                score_numeric = None

            meta: Dict[str, Any] = {}
            for col in fieldnames:
                if col.startswith(f"{m}__meta__"):
                    k = col[len(f"{m}__meta__"):]
                    if k == "json":
                        raw_json = row.get(col, "")
                        if raw_json:
                            try:
                                parsed = json.loads(raw_json)
                                if isinstance(parsed, dict):
                                    meta.update(_sanitize(parsed))
                                else:
                                    meta[k] = raw_json
                            except (json.JSONDecodeError, TypeError):
                                meta[k] = raw_json
                    else:
                        meta[k] = row.get(col)

            db.add(
                RunItemScore(
                    run_id=run.id,
                    item_id=item_id,
                    metric_name=m,
                    score_numeric=score_numeric,
                    score_raw=raw_val,
                    meta=meta,
                )
            )
            scores_count += 1

    return {
        "run_id": run.id,
        "external_run_id": external_run_id,
        "items": items_count,
        "scores": scores_count,
        "metrics": metrics,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv-path", help="Path to the CSV inside the container; omit to read stdin")
    parser.add_argument("--project-slug", default="insightor", help="Project slug to ingest into")
    parser.add_argument("--owner-email", default="faisalx96@yahoo.com", help="Owner email")
    parser.add_argument("--external-run-id", default=None, help="Override the duplicate-guard key (defaults to run_name from the CSV)")
    parser.add_argument("--commit", action="store_true", help="Persist changes (default is dry-run)")
    args = parser.parse_args(argv)

    if args.csv_path:
        with open(args.csv_path, "r", encoding="utf-8") as fh:
            csv_text = fh.read()
    else:
        csv_text = sys.stdin.read()
    if not csv_text.strip():
        raise SystemExit("No CSV content received (empty stdin and no --csv-path)")

    with SessionLocal() as db:
        project = db.query(Project).filter(Project.slug == args.project_slug).one_or_none()
        if not project:
            raise SystemExit(f"Project not found: slug={args.project_slug!r}")
        owner = db.query(User).filter(User.email == args.owner_email).one_or_none()
        if not owner:
            raise SystemExit(f"Owner not found: email={args.owner_email!r}")

        print(f"Project: {project.name} ({project.id})", file=sys.stderr)
        print(f"Owner:   {owner.email} ({owner.id})", file=sys.stderr)
        print(f"Mode:    {'COMMIT' if args.commit else 'DRY-RUN'}", file=sys.stderr)

        stats = ingest_csv(
            db,
            csv_text=csv_text,
            project=project,
            owner=owner,
            external_run_id=args.external_run_id,
        )

        if args.commit:
            db.commit()
            print("Committed.", file=sys.stderr)
        else:
            db.rollback()
            print("Dry-run: no changes written.", file=sys.stderr)

        print(
            f"run_id={stats['run_id']} external_run_id={stats['external_run_id']!r} "
            f"items={stats['items']} scores={stats['scores']} metrics={stats['metrics']}",
            file=sys.stderr,
        )
        print(stats["run_id"])

    return 0


if __name__ == "__main__":
    sys.exit(main())
