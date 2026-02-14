from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from qym.core.run_discovery import RunDiscovery  # legacy parser
from qym_platform.db.session import SessionLocal
from qym_platform.db.models import Run, RunItem, RunItemScore, RunWorkflowStatus, User, UserRole


def _flatten_index(index_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
    runs: List[Dict[str, Any]] = []
    tasks = index_dict.get("tasks") or {}
    for task_name, models in tasks.items():
        for model_name, run_list in (models or {}).items():
            for r in (run_list or []):
                rr = dict(r)
                rr["task_name"] = task_name
                rr["model_name"] = rr.get("model_name") or model_name
                runs.append(rr)
    return runs


def _ensure_owner(db: Session, email: str) -> User:
    email = email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user:
        return user
    user = User(email=email, display_name=email, role=UserRole.VP)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def main() -> None:
    parser = argparse.ArgumentParser(description="Import legacy qym_results into the platform DB")
    parser.add_argument("--results-dir", default="qym_results", help="Path to qym_results directory")
    parser.add_argument("--owner-email", required=True, help="Owner email to attach imported runs to")
    args = parser.parse_args()

    results_dir = Path(args.results_dir).resolve()
    if not results_dir.exists():
        raise SystemExit(f"Results dir not found: {results_dir}")

    discovery = RunDiscovery(results_dir=str(results_dir))
    index = discovery.scan().to_dict()
    runs = _flatten_index(index)

    db = SessionLocal()
    try:
        owner = _ensure_owner(db, args.owner_email)
        imported = 0

        for r in runs:
            file_path = r.get("file_path")
            if not file_path:
                continue
            data = discovery.get_run_data(file_path)
            if data.get("error"):
                continue

            run = Run(
                external_run_id=str(data.get("run", {}).get("run_name") or ""),
                created_by_user_id=owner.id,
                owner_user_id=owner.id,
                task=str(r.get("task_name") or "legacy"),
                dataset=str(data.get("run", {}).get("dataset_name") or ""),
                model=str(r.get("model_name") or "") or None,
                metrics=list(data.get("run", {}).get("metric_names") or []),
                run_metadata={"legacy_file_path": file_path, **(data.get("run", {}).get("metadata") or {})},
                run_config=data.get("run", {}).get("config") or {},
                status=RunWorkflowStatus.APPROVED,  # imported legacy runs treated as approved
            )
            db.add(run)
            db.commit()
            db.refresh(run)

            snap = data.get("snapshot") or {}
            rows = snap.get("rows") or []
            metric_names = list(snap.get("metric_names") or [])

            for row in rows:
                item_id = str(row.get("item_id") or row.get("index") or "")
                status = str(row.get("status") or "")
                is_error = status == "error"
                output_full = row.get("output_full") or row.get("output") or ""
                error_msg = ""
                if is_error and isinstance(output_full, str) and output_full.startswith("ERROR"):
                    error_msg = output_full

                item = RunItem(
                    run_id=run.id,
                    item_id=item_id,
                    index=int(row.get("index") or 0),
                    input=row.get("input_full") or row.get("input") or "",
                    expected=row.get("expected_full") or row.get("expected") or "",
                    output=None if is_error else (row.get("output_full") or row.get("output") or ""),
                    error=error_msg if is_error else None,
                    item_metadata=row.get("item_metadata") or {},
                    latency_ms=float(row.get("latency_ms") or 0.0),
                    trace_id=row.get("trace_id") or None,
                    trace_url=row.get("trace_url") or None,
                )
                db.add(item)

                metric_values = row.get("metric_values") or []
                metric_meta = row.get("metric_meta") or {}
                for idx_m, m in enumerate(metric_names):
                    raw_val = metric_values[idx_m] if idx_m < len(metric_values) else None
                    score_numeric = None
                    try:
                        if not is_error and raw_val not in (None, "", "N/A"):
                            score_numeric = float(raw_val)
                        elif is_error:
                            score_numeric = 0.0
                    except Exception:
                        score_numeric = None
                    db.add(
                        RunItemScore(
                            run_id=run.id,
                            item_id=item_id,
                            metric_name=str(m),
                            score_numeric=score_numeric,
                            score_raw=raw_val,
                            meta=(metric_meta.get(m) or {}) if isinstance(metric_meta, dict) else {},
                        )
                    )

            db.commit()
            imported += 1

        print(f"Imported {imported} run(s) into platform DB")
    finally:
        db.close()


if __name__ == "__main__":
    main()


