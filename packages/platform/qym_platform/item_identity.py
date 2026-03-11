from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Mapping


MUTABLE_METADATA_KEYS = {
    "review_correction_id",
    "review_correction_status",
    "root_cause",
    "root_cause_confidence",
    "root_cause_detail",
    "root_cause_note",
    "root_cause_source",
    "solution",
    "solution_note",
    "solution_source",
    "task_started_at_ms",
}

POSITIONAL_ITEM_ID_PATTERNS = (
    re.compile(r"^\d+$"),
    re.compile(r"^item_\d+$"),
    re.compile(r"^row_\d+$"),
)


def normalize_identity_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if isinstance(value, Mapping):
        return {
            str(key): normalize_identity_value(value[key])
            for key in sorted(value.keys(), key=lambda item: str(item))
        }
    if isinstance(value, (list, tuple)):
        return [normalize_identity_value(item) for item in value]
    return value


def immutable_identity_metadata(metadata: Any) -> Dict[str, Any]:
    if not isinstance(metadata, Mapping):
        return {}
    filtered: Dict[str, Any] = {}
    for key, value in metadata.items():
        key_str = str(key)
        if key_str in MUTABLE_METADATA_KEYS:
            continue
        filtered[key_str] = normalize_identity_value(value)
    return filtered


def build_identity_fingerprint(*, input_value: Any, expected_value: Any, metadata: Any) -> str:
    payload = {
        "expected_output": normalize_identity_value(expected_value),
        "input": normalize_identity_value(input_value),
        "metadata": immutable_identity_metadata(metadata),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:20]


def looks_like_positional_item_id(item_id: Any) -> bool:
    text = str(item_id or "").strip()
    if not text:
        return True
    return any(pattern.match(text) for pattern in POSITIONAL_ITEM_ID_PATTERNS)


def build_generated_item_id(
    *, input_value: Any, expected_value: Any, metadata: Any, occurrence: int
) -> str:
    fingerprint = build_identity_fingerprint(
        input_value=input_value,
        expected_value=expected_value,
        metadata=metadata,
    )
    return f"csv_{fingerprint}__{occurrence:04d}"


def finalize_compare_alignment(run_payload: Dict[str, Any]) -> Dict[str, Any]:
    rows = ((run_payload.get("snapshot") or {}).get("rows") or [])
    seen: set[str] = set()
    issues: List[str] = []
    status = "aligned"
    for row in rows:
        compare_item_id = str(row.get("compare_item_id") or "").strip()
        if not compare_item_id:
            status = "unalignable"
            issues.append("missing compare_item_id")
            continue
        if compare_item_id in seen:
            status = "unalignable"
            issues.append(f"duplicate compare_item_id: {compare_item_id}")
            continue
        seen.add(compare_item_id)
    run_payload.setdefault("run", {})
    run_payload["run"]["compare_alignment_status"] = status
    run_payload["run"]["compare_alignment_issues"] = issues
    return run_payload


def build_compare_identity(
    *,
    item_id: Any,
    input_value: Any,
    expected_value: Any,
    metadata: Any,
    duplicate_counts: Dict[str, int],
) -> Dict[str, str]:
    raw_item_id = str(item_id or "").strip()
    if raw_item_id and not looks_like_positional_item_id(raw_item_id):
        return {"compare_item_id": raw_item_id, "compare_alignment_source": "item_id"}

    fingerprint = build_identity_fingerprint(
        input_value=input_value,
        expected_value=expected_value,
        metadata=metadata,
    )
    duplicate_counts[fingerprint] = duplicate_counts.get(fingerprint, 0) + 1
    return {
        "compare_item_id": f"csv_{fingerprint}__{duplicate_counts[fingerprint]:04d}",
        "compare_alignment_source": "fingerprint",
    }
