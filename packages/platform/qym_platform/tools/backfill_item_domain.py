"""Backfill ``item_metadata.domain`` from the expected SQL.

Rewrites each ``run_items.item_metadata['domain']`` for the targeted runs so
that the domain reflects the actual tables referenced in the expected SQL,
rather than whatever was labelled upstream.

Normalization (per request):
  * strip ``estishraf_llm_`` prefix
  * strip ``_impala`` suffix

Output shape: keeps the existing *stringified* Python-list format, e.g.
``"['traffic_violation', 'university_graduates']"``.

The previous value is backed up into ``item_metadata['domain_legacy']``
(only the first time) so the change is reversible.

Usage (from repo root)::

    # dry-run against the three insightor runs (default)
    QYM_DATABASE_URL=postgresql+psycopg2://qym:qym@localhost:5432/qym \
      PYTHONPATH=packages/platform \
      python -m qym_platform.tools.backfill_item_domain

    # apply changes
    QYM_DATABASE_URL=... PYTHONPATH=packages/platform \
      python -m qym_platform.tools.backfill_item_domain --commit

    # pick specific runs
    python -m qym_platform.tools.backfill_item_domain \
      --external-run-id insightor_api_c14d843-...-1 \
      --external-run-id insightor_api_c14d843-...-2
"""

from __future__ import annotations

import argparse
import sys
from typing import Iterable, List, Optional, Sequence

import sqlglot
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from qym_platform.db.models import Project, Run, RunItem
from qym_platform.db.session import SessionLocal


DEFAULT_EXTERNAL_RUN_IDS: Sequence[str] = (
    "insightor_api_c14d843-Qwen_Qwen3.5-397b-a17b-T-260306-1817-1",
    "insightor_api_c14d843-Qwen_Qwen3.5-397b-a17b-T-260306-1817-2",
    "insightor_api_c14d843-Qwen_Qwen3.5-397b-a17b-T-260306-1817-3",
)

# sqlglot dialect used to parse the expected SQL. Backticks + Impala-ish
# constructs parse cleanly under the hive dialect.
SQL_DIALECT = "hive"

# Normalized table names to drop from the derived domain (utility/reference
# tables that should not be treated as a business domain).
EXCLUDED_TABLES: frozenset[str] = frozenset({
    "calendar_calendar_fixed_missing_hijridates",
})


def _normalize(table_name: str) -> str:
    """Normalize a physical table name to its canonical domain label.

    Rules (case-insensitive):
      * strip the ``estishraf_llm_`` prefix (repeatedly, to handle source typos
        like ``estishraf_llm_estishraf_llm_home_location``),
      * strip the ``_impala`` suffix (repeatedly),
      * lowercase the result so trivial casing differences collapse.
    """
    name = table_name.lower()
    prefix = "estishraf_llm_"
    suffix = "_impala"
    while name.startswith(prefix):
        name = name[len(prefix):]
    while name.endswith(suffix):
        name = name[: -len(suffix)]
    return name


def _extract_tables(sql: str) -> List[str]:
    """Return a sorted, deduped, normalized list of table names from *sql*.

    Only physical tables are returned; CTE aliases defined via ``WITH`` are
    filtered out. Raises ``sqlglot.errors.ParseError`` on malformed SQL.
    """
    parsed = sqlglot.parse_one(sql, read=SQL_DIALECT)

    # Collect CTE names so we can exclude them from the physical-tables set.
    cte_names = {
        cte.alias_or_name.lower()
        for cte in parsed.find_all(sqlglot.exp.CTE)
    }

    tables: set[str] = set()
    for table in parsed.find_all(sqlglot.exp.Table):
        raw = table.name  # final path component (e.g. the table, not the db)
        if not raw:
            continue
        if raw.lower() in cte_names:
            continue
        normalized = _normalize(raw)
        if normalized in EXCLUDED_TABLES:
            continue
        tables.add(normalized)

    return sorted(tables)


def _format_domain(tables: Iterable[str]) -> str:
    """Match the existing stringified Python-list shape, e.g. ``['a', 'b']``."""
    return str(list(tables))


def _resolve_runs(
    db: Session,
    *,
    run_ids: Sequence[str],
    external_run_ids: Sequence[str],
    project_slugs: Sequence[str],
) -> List[Run]:
    from sqlalchemy import or_

    filters = []
    if run_ids:
        filters.append(Run.id.in_(list(run_ids)))
    if external_run_ids:
        filters.append(Run.external_run_id.in_(list(external_run_ids)))
    if project_slugs:
        project_ids = [
            pid for (pid,) in db.query(Project.id)
            .filter(Project.slug.in_(list(project_slugs)))
            .all()
        ]
        if project_ids:
            filters.append(Run.project_id.in_(project_ids))
    if not filters:
        return []
    return (
        db.query(Run)
        .filter(Run.deleted_at.is_(None))
        .filter(or_(*filters))
        .order_by(Run.created_at)
        .all()
    )


def _process_run(
    db: Session,
    run: Run,
    *,
    commit: bool,
    limit: Optional[int],
) -> dict:
    stats = {
        "run_id": run.id,
        "external_run_id": run.external_run_id,
        "total": 0,
        "updated": 0,
        "unchanged": 0,
        "no_expected": 0,
        "parse_error": 0,
        "no_tables": 0,
    }

    q = db.query(RunItem).filter(RunItem.run_id == run.id).order_by(RunItem.index)
    if limit is not None:
        q = q.limit(limit)

    for item in q:
        stats["total"] += 1
        expected = item.expected
        if not isinstance(expected, str) or not expected.strip():
            stats["no_expected"] += 1
            print(
                f"  [skip:no-sql] {item.item_id}",
                file=sys.stderr,
            )
            continue

        try:
            tables = _extract_tables(expected)
        except Exception as exc:  # sqlglot ParseError (and anything odd)
            stats["parse_error"] += 1
            print(
                f"  [skip:parse-error] {item.item_id}: {exc.__class__.__name__}: {exc}",
                file=sys.stderr,
            )
            continue

        if not tables:
            stats["no_tables"] += 1
            print(f"  [skip:no-tables] {item.item_id}", file=sys.stderr)
            continue

        new_domain = _format_domain(tables)
        meta = dict(item.item_metadata or {})
        old_domain = meta.get("domain")

        if old_domain == new_domain:
            stats["unchanged"] += 1
            continue

        print(
            f"  {item.item_id}: {old_domain!r} -> {new_domain!r}",
        )

        if commit:
            if "domain_legacy" not in meta and old_domain is not None:
                meta["domain_legacy"] = old_domain
            meta["domain"] = new_domain
            item.item_metadata = meta
            flag_modified(item, "item_metadata")

        stats["updated"] += 1

    return stats


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-id",
        action="append",
        default=[],
        help="Run UUID (repeatable).",
    )
    parser.add_argument(
        "--external-run-id",
        action="append",
        default=[],
        help="Run external_run_id (repeatable).",
    )
    parser.add_argument(
        "--project-slug",
        action="append",
        default=[],
        help="Project slug (repeatable). Selects all non-deleted runs in the project.",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Persist changes. Without this flag, nothing is written.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit items per run (useful for spot-checking).",
    )
    args = parser.parse_args(argv)

    # If nothing is specified, fall back to the three insightor 1817 runs.
    if not (args.run_id or args.external_run_id or args.project_slug):
        external_ids = list(DEFAULT_EXTERNAL_RUN_IDS)
    else:
        external_ids = args.external_run_id
    run_ids = args.run_id
    project_slugs = args.project_slug

    with SessionLocal() as db:
        runs = _resolve_runs(
            db,
            run_ids=run_ids,
            external_run_ids=external_ids,
            project_slugs=project_slugs,
        )
        if not runs:
            print("No matching runs found.", file=sys.stderr)
            return 3

        print(
            f"Target runs ({len(runs)}):"
            + "".join(f"\n  - {r.id}  {r.external_run_id}" for r in runs),
            file=sys.stderr,
        )
        print(
            f"Mode: {'COMMIT' if args.commit else 'DRY-RUN'}",
            file=sys.stderr,
        )

        totals = {"total": 0, "updated": 0, "unchanged": 0, "no_expected": 0, "parse_error": 0, "no_tables": 0}
        for run in runs:
            print(f"\n== {run.external_run_id or run.id} ==", file=sys.stderr)
            stats = _process_run(db, run, commit=args.commit, limit=args.limit)
            for k in totals:
                totals[k] += stats[k]
            print(
                f"  -> total={stats['total']} updated={stats['updated']} "
                f"unchanged={stats['unchanged']} no_expected={stats['no_expected']} "
                f"parse_error={stats['parse_error']} no_tables={stats['no_tables']}",
                file=sys.stderr,
            )

        if args.commit:
            db.commit()
            print("\nCommitted.", file=sys.stderr)
        else:
            db.rollback()
            print("\nDry-run: no changes written.", file=sys.stderr)

        print(
            "\nTOTAL: "
            f"total={totals['total']} updated={totals['updated']} "
            f"unchanged={totals['unchanged']} no_expected={totals['no_expected']} "
            f"parse_error={totals['parse_error']} no_tables={totals['no_tables']}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
