#!/usr/bin/env python
"""Seed the local qym platform with realistic demo data (dev + Playwright e2e).

Creates three demo projects and fills two of them with SDK-driven eval runs,
native dataset uploads, a FAILED ingest-API run, review lifecycle states
(submitted / approved / rejected + root-cause corrections) and backdated
timestamps so dashboards/charts look lived-in. The third project (sandbox)
is intentionally left empty.

The script is idempotent: projects are matched by slug and only created when
missing; a project that already contains runs is left untouched (logged).

Usage examples:
    python tools/seed_demo.py                       # seed missing demo data
    python tools/seed_demo.py --live                # also start a live RUNNING run
    python tools/seed_demo.py --reset               # archive/delete demo projects first (API)
    python tools/seed_demo.py --reset --hard        # REALLY delete demo rows via psql, then seed
    python tools/seed_demo.py --slug-suffix -e2e    # parallel-safe copies for tests

Notes:
* Requires the platform at --base-url with QYM_AUTH_MODE=none (every request
  acts as the dev@local admin).
* DELETE /v1/admin/projects/{id} only ARCHIVES a project once it has runs, so a
  plain --reset of a seeded project hides it but keeps rows around (and keeps
  the slug taken). A true reset needs --hard, which deletes the demo projects'
  rows directly in Postgres via `docker exec <pg-container> psql` (scoped
  DELETEs for those project ids only -- never a global TRUNCATE).
* API keys are created at runtime via POST /v1/projects/{id}/api-keys; tokens
  are never persisted anywhere.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

HERE = Path(__file__).resolve().parent
SEED_DATA_DIR = HERE / "seed_data"
SUPPORT_CSV = SEED_DATA_DIR / "support_qa.csv"
T2S_CSV = SEED_DATA_DIR / "text2sql.csv"

UUID_RE = re.compile(r"^[0-9a-fA-F-]{32,36}$")

# Statuses that mean "the run is still live" -- never backdated, never submittable.
LIVE_STATUSES = {"RUNNING", "PENDING"}

PROJECT_SPECS = [
    {
        "key": "support",
        "name": "Customer Support Copilot",
        "slug": "support-copilot",
        "description": "RAG copilot answering customer support tickets.",
    },
    {
        "key": "t2s",
        "name": "Text2SQL Bench",
        "slug": "text2sql",
        "description": "Natural language to SQL generation benchmark.",
    },
    {
        "key": "sandbox",
        "name": "Onboarding Sandbox",
        "slug": "sandbox",
        "description": "Empty playground for onboarding new users.",
    },
]

# Per-model quality: probability the model answers correctly.
MODEL_QUALITY = {
    "gpt-4o": 0.85,
    "claude-sonnet-4-6": 0.92,
    "llama-3.1-70b": 0.6,
    "gpt-4o-mini": 0.7,
}

rng = random.Random(42)

# Module-level switch flipped by --fast (skips simulated task latency).
FAST_MODE = False


def log(msg: str) -> None:
    print(f"[seed] {msg}", flush=True)


def _sleep(lo: float, hi: float) -> None:
    if not FAST_MODE:
        time.sleep(rng.uniform(lo, hi))


# ---------------------------------------------------------------------------
# API client (UI principal -- QYM_AUTH_MODE=none makes every request admin)
# ---------------------------------------------------------------------------


class Api:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.s = requests.Session()

    def _req(self, method: str, path: str, **kw) -> Any:
        resp = self.s.request(method, f"{self.base}{path}", timeout=60, **kw)
        if resp.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {resp.status_code}: {resp.text[:400]}")
        if resp.content:
            return resp.json()
        return None

    def get(self, path: str, **kw) -> Any:
        return self._req("GET", path, **kw)

    def post(self, path: str, **kw) -> Any:
        return self._req("POST", path, **kw)

    def patch(self, path: str, **kw) -> Any:
        return self._req("PATCH", path, **kw)

    def delete(self, path: str, **kw) -> Any:
        return self._req("DELETE", path, **kw)


# ---------------------------------------------------------------------------
# Projects / keys / datasets
# ---------------------------------------------------------------------------


def list_projects(api: Api) -> Dict[str, Dict[str, Any]]:
    payload = api.get("/v1/projects")
    return {p["slug"]: p for p in payload.get("projects", [])}


def ensure_projects(api: Api, suffix: str) -> Dict[str, Dict[str, Any]]:
    """Create missing demo projects (matched by slug); reactivate archived ones."""
    existing = list_projects(api)
    out: Dict[str, Dict[str, Any]] = {}
    for spec in PROJECT_SPECS:
        slug = spec["slug"] + suffix
        name = spec["name"] + (f" {suffix.strip('-')}" if suffix else "")
        proj = existing.get(slug)
        if proj is None:
            proj = api.post(
                "/v1/projects",
                json={"name": name, "slug": slug, "description": spec["description"]},
            )
            log(f"project created: {slug} ({proj['id']})")
        else:
            if proj.get("is_active") is False:
                proj = api.patch(f"/v1/admin/projects/{proj['id']}", json={"is_active": True})
                log(f"project reactivated (was archived): {slug}")
            else:
                log(f"project exists: {slug}")
        out[spec["key"]] = proj
    return out


def create_api_key(api: Api, project_id: str) -> str:
    payload = api.post(f"/v1/projects/{project_id}/api-keys", json={"name": "seed-key"})
    return payload["token"]


def project_run_count(api: Api, slug: str) -> int:
    payload = api.get(f"/api/runs?project_slug={slug}&limit=1")
    return int(payload.get("total_count") or 0)


def flatten_runs(api: Api, slug: str) -> List[Dict[str, Any]]:
    payload = api.get(f"/api/runs?project_slug={slug}&limit=500")
    runs: List[Dict[str, Any]] = []
    for models in (payload.get("tasks") or {}).values():
        for summaries in models.values():
            runs.extend(summaries)
    return runs


def upload_dataset_if_missing(
    api: Api,
    project_slug: str,
    name: str,
    csv_path: Path,
    input_col: str,
    expected_col: str,
    metadata_cols: str,
) -> None:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    payload = api.get(f"/v1/datasets?project_slug={project_slug}")
    if any(d.get("slug") == slug for d in payload.get("datasets", [])):
        log(f"dataset exists, skipping upload: {name} ({project_slug})")
        return
    with open(csv_path, "rb") as fh:
        api.post(
            "/v1/datasets:upload",
            data={
                "name": name,
                "project_slug": project_slug,
                "version": "v1",
                "description": f"Seeded from {csv_path.name}",
                "publish": "true",
                "set_alias": "production",
                "input_col": input_col,
                "expected_col": expected_col,
                "metadata_cols": metadata_cols,
            },
            files={"file": (csv_path.name, fh, "text/csv")},
        )
    log(f"dataset uploaded: {name} -> {project_slug}")


# ---------------------------------------------------------------------------
# SDK-driven eval runs (fake tasks + metrics, mirrors the original demo seeds)
# ---------------------------------------------------------------------------


def _load_answers(path: Path, value_col: str) -> Dict[str, str]:
    answers: Dict[str, str] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            answers[row["question"]] = row[value_col]
    return answers


_CORRECT = _load_answers(SUPPORT_CSV, "answer") if SUPPORT_CSV.exists() else {}
_SQL = _load_answers(T2S_CSV, "sql") if T2S_CSV.exists() else {}


def make_support_task(model_name: str, fail_rate: float = 0.0) -> Callable:
    quality = MODEL_QUALITY.get(model_name, 0.75)

    def support_task(question, model=None, trace_id=None):
        q = question.get("question") if isinstance(question, dict) else question
        _sleep(0.05, 0.3)
        if fail_rate and rng.random() < fail_rate:
            raise RuntimeError("Upstream LLM provider returned 503 (simulated outage)")
        if rng.random() < quality:
            return _CORRECT.get(str(q), f"Here is what you need to do: {q}")
        return (
            "I'm sorry, I don't have enough information to answer that. "
            "Please contact support@example.com."
        )

    return support_task


def make_sql_task(model_name: str) -> Callable:
    quality = MODEL_QUALITY.get(model_name, 0.75)

    def sql_task(question, model=None, trace_id=None):
        q = question.get("question") if isinstance(question, dict) else question
        _sleep(0.05, 0.4)
        if rng.random() < quality:
            return _SQL.get(str(q), "SELECT 1;")
        return f"SELECT * FROM unknown_table WHERE col LIKE '%{str(q)[:20]}%';"

    return sql_task


# --- metrics (names matter: the SDK reports the function __name__) ---------


def exact_match(output, expected):
    if expected is None:
        return 0.0
    return 1.0 if str(output).strip() == str(expected).strip() else 0.0


def answer_relevancy(output, expected):
    """Pseudo LLM-judge returning a dict score + metadata."""
    if not expected:
        return 0.0
    out_words = set(str(output).lower().split())
    exp_words = set(str(expected).lower().split())
    if not exp_words:
        return 0.0
    score = len(out_words & exp_words) / len(exp_words)
    return {
        "score": round(min(1.0, score + rng.uniform(0, 0.1)), 2),
        "metadata": {"judge": "word-overlap-v2", "expected_terms": len(exp_words)},
    }


def tone_compliance(output, expected=None):
    score = 1.0 if "sorry" not in str(output).lower() else rng.choice([0.5, 0.7])
    return {"score": score, "metadata": {"policy": "no-unnecessary-apology"}}


def sql_exact(output, expected):
    return 1.0 if str(output).strip() == str(expected).strip() else 0.0


def sql_keywords(output, expected):
    kws = ["select", "from"]
    o = str(output).lower()
    return sum(1 for k in kws if k in o) / len(kws)


def run_eval(
    base_url: str,
    api_key: str,
    task: Callable,
    dataset_path: Path,
    expected_col: str,
    metrics: List[Callable],
    run_name: str,
    task_name: str,
    model: str,
    meta_cols: List[str],
    max_concurrency: int = 4,
) -> None:
    # The SDK reads QYM_BASE_URL / QYM_API_KEY from the environment at run
    # time, so they must be (re)set before every Evaluator -- each project
    # streams with its own key.
    os.environ["QYM_BASE_URL"] = base_url
    os.environ["QYM_API_KEY"] = api_key
    from qym import CsvDataset, Evaluator  # imported lazily; venv has it editable

    ds = CsvDataset(
        str(dataset_path),
        input_col="question",
        expected_col=expected_col,
        metadata_cols=meta_cols,
    )
    ev = Evaluator(
        task=task,
        dataset=ds,
        metrics=metrics,
        config={"run_name": run_name, "task_name": task_name, "max_concurrency": max_concurrency},
        model=model,
    )
    try:
        ev.run()
        log(f"run ok: {run_name}")
    except Exception as e:  # noqa: BLE001 - a failed demo run should not kill seeding
        log(f"run ended with error: {run_name}: {e}")


def seed_support_runs(base_url: str, api_key: str) -> None:
    for model in ["gpt-4o", "claude-sonnet-4-6", "llama-3.1-70b"]:
        run_eval(
            base_url, api_key, make_support_task(model), SUPPORT_CSV, "answer",
            [exact_match, answer_relevancy, tone_compliance],
            f"support-rag-{model}", "support_rag", model, ["category", "difficulty"],
        )
    # a run with provider failures
    run_eval(
        base_url, api_key, make_support_task("gpt-4o-mini", fail_rate=0.55), SUPPORT_CSV, "answer",
        [exact_match, answer_relevancy],
        "support-rag-gpt-4o-mini (provider outage)", "support_rag", "gpt-4o-mini",
        ["category", "difficulty"],
    )
    # second task in the same project
    run_eval(
        base_url, api_key, make_support_task("claude-sonnet-4-6"), SUPPORT_CSV, "answer",
        [answer_relevancy],
        "ticket-summarizer-baseline", "ticket_summarizer", "claude-sonnet-4-6", ["category"],
    )


def seed_t2s_runs(base_url: str, api_key: str) -> None:
    for model in ["gpt-4o", "gpt-4o-mini", "claude-sonnet-4-6"]:
        run_eval(
            base_url, api_key, make_sql_task(model), T2S_CSV, "sql",
            [sql_exact, sql_keywords],
            f"text2sql-{model}", "text2sql", model, ["complexity", "domain"],
        )


# ---------------------------------------------------------------------------
# FAILED run via direct ingest API events
# ---------------------------------------------------------------------------


def seed_failed_run(base_url: str, api_key: str) -> str:
    headers = {"Authorization": f"Bearer {api_key}"}
    start = datetime.now(timezone.utc) - timedelta(hours=3)

    resp = requests.post(
        f"{base_url}/v1/runs",
        headers=headers,
        timeout=60,
        json={
            "task": "text2sql",
            "dataset": "Text2SQL Suite",
            "model": "llama-3.1-70b",
            "metrics": ["sql_exact", "sql_keywords"],
            "run_metadata": {"run_name": "text2sql-llama-3.1-70b (oom crash)"},
        },
    )
    resp.raise_for_status()
    run_id = resp.json()["run_id"]

    events: List[Dict[str, Any]] = []
    seq = 0

    def ev(etype: str, payload: Dict[str, Any]) -> None:
        nonlocal seq
        seq += 1
        events.append(
            {
                "schema_version": 1,
                "event_id": str(uuid.uuid4()),
                "sequence": seq,
                "sent_at": (start + timedelta(seconds=seq * 5)).isoformat(),
                "type": etype,
                "run_id": run_id,
                "payload": payload,
            }
        )

    ev(
        "run_started",
        {
            "task": "text2sql",
            "dataset": "Text2SQL Suite",
            "model": "llama-3.1-70b",
            "metrics": ["sql_exact", "sql_keywords"],
            "total_items": 10,
            "started_at": start.isoformat(),
            "run_metadata": {"run_name": "text2sql-llama-3.1-70b (oom crash)"},
        },
    )
    for i in range(3):
        iid = f"item_{i:04d}"
        ev("item_started", {"item_id": iid, "index": i, "input": f"benchmark query {i}", "expected": "SELECT ..."})
        ev(
            "item_attempt_started",
            {"item_id": iid, "attempt_number": 1, "started_at": (start + timedelta(seconds=seq * 5)).isoformat()},
        )
        if i < 2:
            ev(
                "item_attempt_finished",
                {"item_id": iid, "attempt_number": 1, "status": "completed", "latency_ms": 2300.0},
            )
            ev("metric_scored", {"item_id": iid, "metric_name": "sql_exact", "score_numeric": float(i % 2)})
            ev("item_completed", {"item_id": iid, "output": "SELECT id FROM orders;", "latency_ms": 2300.0})
        else:
            ev(
                "item_attempt_finished",
                {
                    "item_id": iid,
                    "attempt_number": 1,
                    "status": "failed",
                    "error": "CUDA out of memory: tried to allocate 2.4 GiB",
                    "latency_ms": 8100.0,
                    "is_last_attempt": True,
                },
            )
            ev("item_failed", {"item_id": iid, "error": "CUDA out of memory: tried to allocate 2.4 GiB"})

    ev(
        "run_completed",
        {
            "ended_at": (start + timedelta(minutes=5)).isoformat(),
            "final_status": "FAILED",
            "summary": {"error": "Worker crashed: CUDA out of memory"},
        },
    )

    nd = "\n".join(json.dumps(e) for e in events)
    resp2 = requests.post(
        f"{base_url}/v1/runs/{run_id}/events",
        headers={**headers, "Content-Type": "application/x-ndjson"},
        data=nd.encode("utf-8"),
        timeout=60,
    )
    resp2.raise_for_status()
    log(f"failed run ingested: {run_id}")
    return run_id


# ---------------------------------------------------------------------------
# Lifecycle states + root-cause corrections
# ---------------------------------------------------------------------------


def _find_run(
    api: Api, slug: str, task: str, model: str, name_prefix: str, attempts: int = 5
) -> Optional[Dict[str, Any]]:
    """Locate a seeded run by task + model + run-name prefix.

    The SDK appends ``-{model}-{timestamp}`` to the configured run_name
    (e.g. ``support-rag-gpt-4o`` becomes ``support-rag-gpt-4o-gpt-4o-260612-0011``),
    so exact run_name matching does not work.
    """
    for _ in range(attempts):
        for r in flatten_runs(api, slug):
            if (
                r.get("task_name") == task
                and r.get("model_name") == model
                and str(r.get("run_name", "")).startswith(name_prefix)
                and r.get("status") not in LIVE_STATUSES
            ):
                return r
        time.sleep(2)
    return None


def apply_support_lifecycle(api: Api, slug: str) -> None:
    claude = _find_run(api, slug, "support_rag", "claude-sonnet-4-6", "support-rag-claude-sonnet-4-6")
    if claude:
        api.post(f"/v1/runs/{claude['run_id']}/submit")
        api.post(
            f"/v1/runs/{claude['run_id']}/approve",
            json={"comment": "Clear win over gpt-4o baseline, ship it"},
        )
        log(f"approved: support-rag-claude-sonnet-4-6 ({claude['run_id']})")
    else:
        log("WARN: claude run not found for approve flow")

    llama = _find_run(api, slug, "support_rag", "llama-3.1-70b", "support-rag-llama-3.1-70b")
    if not llama:
        log("WARN: llama run not found for reject flow")
        return
    api.post(f"/v1/runs/{llama['run_id']}/submit")
    api.post(
        f"/v1/runs/{llama['run_id']}/reject",
        json={"comment": "Pass rate too low on hard tickets, investigate retrieval"},
    )
    log(f"rejected: support-rag-llama-3.1-70b ({llama['run_id']})")

    # Two root-cause corrections on items the llama run got wrong.
    data = api.get(f"/api/runs/{llama['run_id']}")
    snapshot = data.get("snapshot") or {}
    rows = snapshot.get("rows") or []
    metric_names = snapshot.get("metric_names") or []
    try:
        em_idx = metric_names.index("exact_match")
    except ValueError:
        em_idx = None
    bad_items: List[str] = []
    for row in rows:
        if row.get("status") != "completed":
            continue
        vals = row.get("metric_values") or []
        if em_idx is not None and em_idx < len(vals):
            try:
                if float(vals[em_idx]) == 0.0:
                    bad_items.append(row["item_id"])
            except (TypeError, ValueError):
                continue
    corrections = [
        {
            "root_cause": "retrieval_miss",
            "root_cause_detail": "Retriever surfaced refund policy doc instead of duplicate-charge doc",
            "root_cause_note": "Reviewed manually - billing corpus chunking too coarse",
        },
        {
            "root_cause": "hallucination",
            "root_cause_detail": "Model invented a non-existent Settings path",
            "root_cause_note": "Consistent across 3 reruns",
        },
    ]
    for item_id, patch in zip(bad_items[:2], corrections):
        api.post(
            "/api/runs/update_root_cause",
            json={"run_id": llama["run_id"], "item_id": item_id, **patch},
        )
        log(f"root cause set on item {item_id}: {patch['root_cause']}")
    if len(bad_items) < 2:
        log(f"WARN: only {len(bad_items)} failing items found for root-cause corrections")


def apply_t2s_lifecycle(api: Api, slug: str) -> None:
    gpt4o = _find_run(api, slug, "text2sql", "gpt-4o", "text2sql-gpt-4o-gpt-4o")
    if gpt4o:
        api.post(f"/v1/runs/{gpt4o['run_id']}/submit")
        log(f"submitted (pending review): text2sql-gpt-4o ({gpt4o['run_id']})")
    else:
        log("WARN: text2sql-gpt-4o run not found for submit flow")


# ---------------------------------------------------------------------------
# psql helpers (docker exec) -- backdating + hard reset
# ---------------------------------------------------------------------------


def docker_psql(container: str, sql: str, tuples: bool = False) -> str:
    cmd = ["docker", "exec", container, "psql", "-U", "qym", "-d", "qym", "-v", "ON_ERROR_STOP=1"]
    if tuples:
        cmd += ["-t", "-A", "-F", "|"]
    cmd += ["-c", sql]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"psql failed: {proc.stderr.strip()[:500]}")
    return proc.stdout


def _validate_uuids(ids: List[str]) -> List[str]:
    for value in ids:
        if not UUID_RE.match(value):
            raise ValueError(f"refusing to interpolate non-uuid id into SQL: {value!r}")
    return ids


def backdate_runs(container: str, project_ids: List[str]) -> None:
    """Spread terminal runs in the demo projects over the last ~4 weeks.

    Same approach as the original seeding session: direct UPDATEs on
    runs.created_at / started_at / ended_at via docker exec psql. Live
    (RUNNING/PENDING) runs are never touched.
    """
    ids_sql = ",".join(f"'{pid}'" for pid in _validate_uuids(project_ids))
    out = docker_psql(
        container,
        "SELECT id, status FROM runs "
        f"WHERE deleted_at IS NULL AND project_id IN ({ids_sql}) ORDER BY created_at;",
        tuples=True,
    )
    rows = [line.split("|") for line in out.strip().splitlines() if "|" in line]
    targets = [(rid, status) for rid, status in rows if status not in LIVE_STATUSES]
    n = len(targets)
    if n == 0:
        log("backdate: no terminal runs found, skipping")
        return
    _validate_uuids([rid for rid, _ in targets])
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    spacing_days = min(3.0, 28.0 / (n - 1)) if n > 1 else 0.0
    statements: List[str] = []
    for i, (rid, _status) in enumerate(targets):
        created = now - timedelta(days=spacing_days * (n - 1 - i), minutes=10)
        started = created - timedelta(minutes=8)
        ended = created + timedelta(minutes=10)
        statements.append(
            "UPDATE runs SET "
            f"created_at='{created.isoformat(sep=' ')}', "
            f"started_at='{started.isoformat(sep=' ')}', "
            f"ended_at='{ended.isoformat(sep=' ')}' "
            f"WHERE id='{rid}';"
        )
    docker_psql(container, " ".join(statements))
    log(f"backdated {n} runs across ~{spacing_days * max(n - 1, 1):.0f} days")


def hard_delete_projects(container: str, project_ids: List[str]) -> None:
    """Hard-delete demo project rows (children first, FK-safe order)."""
    ids_sql = ",".join(f"'{pid}'" for pid in _validate_uuids(project_ids))
    runs_sub = f"(SELECT id FROM runs WHERE project_id IN ({ids_sql}))"
    ds_sub = f"(SELECT id FROM datasets WHERE project_id IN ({ids_sql}))"
    dsv_sub = f"(SELECT id FROM dataset_versions WHERE dataset_id IN {ds_sub})"
    statements = [
        f"DELETE FROM review_corrections WHERE run_id IN {runs_sub};",
        f"DELETE FROM root_cause_revisions WHERE run_id IN {runs_sub};",
        f"DELETE FROM run_item_scores WHERE run_id IN {runs_sub};",
        f"DELETE FROM run_item_attempts WHERE run_id IN {runs_sub};",
        f"DELETE FROM run_events WHERE run_id IN {runs_sub};",
        f"DELETE FROM spans WHERE run_id IN {runs_sub};",
        f"DELETE FROM run_trace_aggregates WHERE run_id IN {runs_sub};",
        f"DELETE FROM approvals WHERE run_id IN {runs_sub};",
        f"DELETE FROM run_items WHERE run_id IN {runs_sub};",
        f"DELETE FROM runs WHERE project_id IN ({ids_sql});",
        f"DELETE FROM dataset_item_revisions WHERE dataset_version_id IN {dsv_sub};",
        f"DELETE FROM dataset_items WHERE dataset_version_id IN {dsv_sub};",
        f"DELETE FROM dataset_version_changes WHERE dataset_version_id IN {dsv_sub};",
        f"DELETE FROM dataset_aliases WHERE dataset_id IN {ds_sub};",
        f"DELETE FROM dataset_versions WHERE dataset_id IN {ds_sub};",
        f"DELETE FROM datasets WHERE project_id IN ({ids_sql});",
        f"DELETE FROM project_llm_connections WHERE project_id IN ({ids_sql});",
        f"DELETE FROM api_keys WHERE project_id IN ({ids_sql});",
        f"DELETE FROM project_memberships WHERE project_id IN ({ids_sql});",
        f"DELETE FROM projects WHERE id IN ({ids_sql});",
    ]
    docker_psql(container, " ".join(statements))
    log(f"hard-deleted {len(project_ids)} project(s) and all their rows")


def reset_demo(api: Api, args: argparse.Namespace) -> None:
    existing = list_projects(api)
    demo = [existing[s["slug"] + args.slug_suffix] for s in PROJECT_SPECS if s["slug"] + args.slug_suffix in existing]
    if not demo:
        log("reset: no demo projects found")
        return
    if args.hard:
        hard_delete_projects(args.pg_container, [p["id"] for p in demo])
        return
    for proj in demo:
        result = api.delete(f"/v1/admin/projects/{proj['id']}")
        verb = "deleted" if result.get("deleted") else "archived (has runs; use --hard for a true reset)"
        log(f"reset: {proj['slug']} {verb}")


# ---------------------------------------------------------------------------
# Live run (detached background process)
# ---------------------------------------------------------------------------


def spawn_live_run(args: argparse.Namespace) -> None:
    logpath = Path(tempfile.gettempdir()) / "qym_seed_live_run.log"
    cmd = [
        sys.executable, "-u", str(Path(__file__).resolve()),
        "--_live-worker",
        f"--base-url={args.base_url}",
        # '=' form: suffix values usually start with '-', which argparse would
        # otherwise treat as a new option.
        f"--slug-suffix={args.slug_suffix}",
    ]
    logfh = open(logpath, "ab")
    kwargs: Dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        cmd, stdout=logfh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kwargs
    )
    log(f"live run spawned detached (pid {proc.pid}, log: {logpath})")


def live_worker(args: argparse.Namespace) -> None:
    """Runs in the detached child: a slow eval so the dashboard shows RUNNING."""
    api = Api(args.base_url)
    projects = ensure_projects(api, args.slug_suffix)
    token = create_api_key(api, projects["support"]["id"])
    os.environ["QYM_BASE_URL"] = args.base_url
    os.environ["QYM_API_KEY"] = token
    from qym import CsvDataset, Evaluator

    slow_rng = random.Random(7)

    def slow_task(question, model=None, trace_id=None):
        time.sleep(slow_rng.uniform(90, 140))
        return "Working through the backlog of long-context regression checks..."

    def answer_relevancy(output, expected):  # noqa: F811 - intentional standalone metric
        return slow_rng.uniform(0.4, 0.95)

    ds = CsvDataset(
        str(SUPPORT_CSV),
        input_col="question",
        expected_col="answer",
        metadata_cols=["category", "difficulty"],
    )
    Evaluator(
        task=slow_task,
        dataset=ds,
        metrics=[answer_relevancy],
        config={
            "run_name": "nightly-regression-long-context",
            "task_name": "support_rag",
            "max_concurrency": 1,
        },
        model="gpt-4o",
    ).run()


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def print_summary(api: Api, suffix: str) -> None:
    print()
    print(f"{'PROJECT':<34} {'SLUG':<26} {'RUNS':>4}  {'STATUSES':<46} DATASETS")
    print("-" * 140)
    for spec in PROJECT_SPECS:
        slug = spec["slug"] + suffix
        try:
            runs = flatten_runs(api, slug)
        except RuntimeError:
            print(f"{spec['name']:<34} {slug:<26} {'-':>4}  {'(project missing)':<46}")
            continue
        counts: Dict[str, int] = {}
        for r in runs:
            counts[str(r.get("status"))] = counts.get(str(r.get("status")), 0) + 1
        statuses = " ".join(f"{k}:{v}" for k, v in sorted(counts.items())) or "-"
        try:
            ds_payload = api.get(f"/v1/datasets?project_slug={slug}")
            datasets = ", ".join(
                f"{d['name']} ({(d.get('latest_version') or {}).get('item_count', 0)} items)"
                for d in ds_payload.get("datasets", [])
            ) or "-"
        except RuntimeError:
            datasets = "?"
        print(f"{spec['name']:<34} {slug:<26} {len(runs):>4}  {statuses:<46} {datasets}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Reset semantics: --reset uses DELETE /v1/admin/projects/{id}, which only\n"
            "archives a project once it has runs (rows + slug remain). Add --hard to\n"
            "delete the demo projects' rows directly via docker-exec psql (scoped\n"
            "DELETEs for the demo project ids only), then reseed from scratch."
        ),
    )
    parser.add_argument("--base-url", default="http://localhost:8000", help="Platform base URL")
    parser.add_argument("--reset", action="store_true", help="Delete/archive demo projects via API before seeding")
    parser.add_argument("--hard", action="store_true", help="With --reset: hard-delete demo rows via psql (docker exec)")
    parser.add_argument("--reset-only", action="store_true", help="Reset (per --hard) and exit without seeding")
    parser.add_argument("--live", action="store_true", help="Also start a long-running live run (detached)")
    parser.add_argument("--fast", action="store_true", help="Skip simulated task latency sleeps")
    parser.add_argument(
        "--backdate", action=argparse.BooleanOptionalAction, default=True,
        help="Spread freshly seeded runs over ~4 weeks (psql UPDATE; default on)",
    )
    parser.add_argument(
        "--slug-suffix", default="",
        help="Suffix appended to demo project slugs (values starting with '-' need the = form, e.g. --slug-suffix=-e2e)",
    )
    parser.add_argument("--pg-container", default="qym-pg", help="Postgres docker container name")
    parser.add_argument("--_live-worker", dest="live_worker", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    global FAST_MODE
    args = parse_args(argv)
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - non-utf8 console is fine for logging
        pass
    FAST_MODE = args.fast

    if args.live_worker:
        live_worker(args)
        return 0

    if args.hard and not (args.reset or args.reset_only):
        log("--hard has no effect without --reset/--reset-only")

    api = Api(args.base_url)

    if args.reset or args.reset_only:
        reset_demo(api, args)
        if args.reset_only:
            return 0

    projects = ensure_projects(api, args.slug_suffix)
    support_slug = projects["support"]["slug"]
    t2s_slug = projects["t2s"]["slug"]

    # Native dataset uploads (idempotent by dataset slug).
    upload_dataset_if_missing(
        api, support_slug, "Support QA Golden Set", SUPPORT_CSV,
        input_col="question", expected_col="answer", metadata_cols="category,difficulty",
    )
    upload_dataset_if_missing(
        api, t2s_slug, "Text2SQL Suite", T2S_CSV,
        input_col="question", expected_col="sql", metadata_cols="complexity,domain",
    )

    freshly_seeded: List[str] = []

    if project_run_count(api, support_slug) > 0:
        log(f"runs already present in {support_slug}, skipping run seeding")
    else:
        token = create_api_key(api, projects["support"]["id"])
        log(f"api key created for {support_slug} (token captured at runtime)")
        seed_support_runs(args.base_url, token)
        apply_support_lifecycle(api, support_slug)
        freshly_seeded.append(projects["support"]["id"])

    if project_run_count(api, t2s_slug) > 0:
        log(f"runs already present in {t2s_slug}, skipping run seeding")
    else:
        token = create_api_key(api, projects["t2s"]["id"])
        log(f"api key created for {t2s_slug} (token captured at runtime)")
        seed_t2s_runs(args.base_url, token)
        seed_failed_run(args.base_url, token)
        apply_t2s_lifecycle(api, t2s_slug)
        freshly_seeded.append(projects["t2s"]["id"])

    log(f"{projects['sandbox']['slug']} intentionally left empty")

    if freshly_seeded and args.backdate:
        backdate_runs(args.pg_container, freshly_seeded)
    elif not freshly_seeded:
        log("nothing freshly seeded; backdate skipped")

    if args.live:
        spawn_live_run(args)

    print_summary(api, args.slug_suffix)
    return 0


if __name__ == "__main__":
    sys.exit(main())
