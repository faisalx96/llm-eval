from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional


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
    """Return a deterministic representation for identity hashing."""
    if isinstance(value, str):
        return value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if isinstance(value, Mapping):
        normalized: Dict[str, Any] = {}
        for key in sorted(value.keys(), key=lambda item: str(item)):
            normalized[str(key)] = normalize_identity_value(value[key])
        return normalized
    if isinstance(value, (list, tuple)):
        return [normalize_identity_value(item) for item in value]
    return value


def immutable_identity_metadata(metadata: Any) -> Dict[str, Any]:
    """Filter metadata down to fields that should participate in dataset identity."""
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
    """Hash immutable dataset fields into a stable fingerprint."""
    payload = {
        "expected_output": normalize_identity_value(expected_value),
        "input": normalize_identity_value(input_value),
        "metadata": immutable_identity_metadata(metadata),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:20]


def build_generated_item_id(
    *, input_value: Any, expected_value: Any, metadata: Any, occurrence: int
) -> str:
    """Generate a deterministic item ID for CSV-backed rows without explicit IDs."""
    fingerprint = build_identity_fingerprint(
        input_value=input_value,
        expected_value=expected_value,
        metadata=metadata,
    )
    return f"csv_{fingerprint}__{occurrence:04d}"


def looks_like_positional_item_id(item_id: Any) -> bool:
    text = str(item_id or "").strip()
    if not text:
        return True
    return any(pattern.match(text) for pattern in POSITIONAL_ITEM_ID_PATTERNS)


def build_generated_item_ids(
    rows: Iterable[Mapping[str, Any]],
    *,
    input_key: str,
    expected_key: Optional[str],
    metadata_getter,
) -> List[str]:
    """Generate deterministic item IDs for a sequence of dataset rows."""
    counts: dict[str, int] = defaultdict(int)
    generated: List[str] = []
    for row in rows:
        metadata = metadata_getter(row)
        fingerprint = build_identity_fingerprint(
            input_value=row.get(input_key, ""),
            expected_value=row.get(expected_key, "") if expected_key else None,
            metadata=metadata,
        )
        counts[fingerprint] += 1
        generated.append(f"csv_{fingerprint}__{counts[fingerprint]:04d}")
    return generated
