"""Ingest a single CSV results file as a run with SQL-only outputs.

This is the CSV-based sibling of :mod:`duplicate_run_sql_only` — instead of
copying an existing run it creates one from a CSV file (same column layout
as ``upload_border_csvs.py``) and applies the SQL-only treatment up front:

* Each item's ``output`` becomes a JSON object ``{sql, llm_result,
  expected_result}`` so the two result tables render side-by-side in the
  dashboard.
* The ``accuracy`` metric metadata loses ``llm_result`` / ``expected_result``
  (they live on the output now) but keeps the scoring context
  (``llm_judge_reasoning`` etc.).

Run from the host. The CSV is fed in via stdin so you can point at any path
on your machine; the container does not need to mount the file::

    docker exec -i docker-api-1 python -m qym_platform.tools.upload_csv_sql_only \\
        --owner-email faisalx96@yahoo.com \\
        --project-slug insightor \\
        --commit \\
        < /path/to/results.csv

Or use the host wrapper (which does the docker exec + stdin plumbing for you)::

    tools/upload_sql_only.sh /path/to/results.csv --commit
"""

from __future__ import annotations

import argparse
import ast
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

RESULT_META_KEYS = ("llm_result", "expected_result")

_TRUTHY = {"true", "yes", "pass", "passed", "correct"}
_FALSY = {"false", "no", "fail", "failed", "incorrect"}


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def _strip_preprod(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    return value.replace("-preprod", "")


def _coerce_score(raw_val: Any, is_error: bool) -> Optional[float]:
    if is_error:
        return 0.0
    if raw_val is None:
        return None
    if isinstance(raw_val, bool):
        return 1.0 if raw_val else 0.0
    if isinstance(raw_val, (int, float)):
        return float(raw_val)
    s = str(raw_val).strip()
    if s == "" or s.upper() == "N/A":
        return None
    low = s.lower()
    if low in _TRUTHY:
        return 1.0
    if low in _FALSY:
        return 0.0
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _apply_or_rule(meta: Dict[str, Any], is_error: bool) -> Optional[float]:
    """OR(llm_judge, exact_match) accuracy when both components are present."""
    if is_error:
        return 0.0
    has_llm = "llm_judge_metric_result_score" in meta
    has_em = "exact_match_result_score" in meta
    if not (has_llm and has_em):
        return None
    llm_pass = _coerce_score(meta.get("llm_judge_metric_result_score"), False)
    em_pass = _coerce_score(meta.get("exact_match_result_score"), False)
    if llm_pass is None and em_pass is None:
        return None
    if (llm_pass or 0) >= 1 or (em_pass or 0) >= 1:
        return 1.0
    return 0.0


def _parse_python_dict(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort parse for the Python ``repr`` output stored in CSVs."""
    if not text:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _build_sql_only_output(raw_output: str, accuracy_meta: Dict[str, Any]) -> Dict[str, Any]:
    parsed = _parse_python_dict(raw_output) or {}
    sql = parsed.get("sql") if isinstance(parsed, dict) else ""
    output: Dict[str, Any] = {"sql": sql if isinstance(sql, str) else ""}
    for key in RESULT_META_KEYS:
        if key in accuracy_meta and accuracy_meta[key] is not None:
            output[key] = accuracy_meta[key]
    return output


def _strip_result_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
    clean = dict(meta or {})
    for key in RESULT_META_KEYS:
        clean.pop(key, None)
    return clean


def ingest_csv(
    db: Session,
    *,
    csv_text: str,
    project: Project,
    owner: User,
    external_run_id: Optional[str],
    align_item_id_from: str = "issue_key",
    apply_accuracy_or_rule: bool = True,
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

    raw_model = str(run_metadata.get("model") or "")
    model_name = _strip_preprod(raw_model) or ""
    if model_name:
        run_metadata["model"] = model_name
    task_name = str(run_metadata.get("task_name") or "insightor_api")

    run_metadata["sql_only_variant"] = True

    if not external_run_id:
        external_run_id = (first.get("run_name") or "").strip() or None
        if external_run_id:
            external_run_id = _strip_preprod(external_run_id) + " (sql-only)"

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
        model=model_name or None,
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

        aligned_id: Optional[str] = None
        if align_item_id_from:
            candidate = parsed_meta.get(align_item_id_from)
            if isinstance(candidate, str) and candidate.strip():
                aligned_id = candidate.strip()

        raw_item_id = str(row.get("item_id") or "").strip()
        if aligned_id:
            item_id = aligned_id
            if "original_item_id" not in parsed_meta:
                parsed_meta["original_item_id"] = raw_item_id or None
        elif raw_item_id and not looks_like_positional_item_id(raw_item_id):
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

        # Pre-parse accuracy meta for this row so we can promote llm_result /
        # expected_result into the item output.
        accuracy_meta: Dict[str, Any] = {}
        if "accuracy__meta__json" in fieldnames:
            raw_json = row.get("accuracy__meta__json") or ""
            if raw_json:
                try:
                    parsed = json.loads(raw_json)
                    if isinstance(parsed, dict):
                        accuracy_meta = _sanitize(parsed) or {}
                except (json.JSONDecodeError, TypeError):
                    accuracy_meta = {}

        new_output: Optional[Any]
        if is_error:
            new_output = None
        else:
            new_output = _build_sql_only_output(raw_output, accuracy_meta)

        db.add(
            RunItem(
                run_id=run.id,
                item_id=item_id,
                index=idx,
                input=row.get("input"),
                expected=row.get("expected_output"),
                output=new_output,
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
            score_numeric = _coerce_score(raw_val, is_error)

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

            if m == "accuracy":
                if apply_accuracy_or_rule:
                    final = _apply_or_rule(meta, is_error)
                    if final is not None and final != score_numeric:
                        score_numeric = final
                        raw_val = "True" if final >= 1 else "False"
                meta = _strip_result_meta(meta)

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
    parser.add_argument("--external-run-id", default=None, help="Override the duplicate-guard key (defaults to run_name from the CSV + ' (sql-only)')")
    parser.add_argument("--no-or-rule", dest="apply_or_rule", action="store_false", help="Skip OR(llm_judge, exact_match) recomputation for accuracy")
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
            apply_accuracy_or_rule=args.apply_or_rule,
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
        # Print just the run id on stdout for easy scripting
        print(stats["run_id"])

    return 0


if __name__ == "__main__":
    sys.exit(main())
