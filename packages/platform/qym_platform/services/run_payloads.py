"""Compact analytical rows and bounded hydration request validation.

The compact index preserves global numeric/category semantics. Text bodies are
loaded for displayed items, or searched on the server, rather than downloaded
twice for every item during initial navigation.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List

from fastapi import HTTPException

MAX_DETAIL_ITEMS = 100
MAX_SEARCH_CONDITIONS = 32


def text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def compact_attempt(attempt: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(attempt)
    output = result.pop("output", None)
    result["__has_output"] = output is not None
    result["__execution_error"] = output if result.get("status") == "error" else ""
    result["output_digest"] = text_digest(str(output or ""))
    return result


def _compact_metric_meta(metadata: Any) -> Any:
    if not isinstance(metadata, dict):
        return metadata
    # Keep keys for the metric-field chooser and all semantic/provenance flags.
    return {
        key: "" if key == "explanation" else value for key, value in metadata.items()
    }


def compact_row(row: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(row)
    output = result.get("output_full") or result.get("output")
    result["__has_output"] = output is not None
    result["__execution_error"] = output if result.get("status") == "error" else ""
    result["output_digest"] = text_digest(str(output or ""))
    for field in (
        "input",
        "input_full",
        "expected",
        "expected_full",
        "output",
        "output_full",
    ):
        result.pop(field, None)
    result["__details_loaded"] = False
    result["metric_meta"] = {
        metric: _compact_metric_meta(meta)
        for metric, meta in (result.get("metric_meta") or {}).items()
    }
    if result.get("pass_metric_meta"):
        result["pass_metric_meta"] = {
            metric: [_compact_metric_meta(meta) for meta in values]
            for metric, values in result["pass_metric_meta"].items()
        }
    if result.get("pass_attempts"):
        result["pass_attempts"] = [
            compact_attempt(attempt) if attempt else None
            for attempt in result["pass_attempts"]
        ]
    return result


def detail_item_ids(payload: Dict[str, Any]) -> List[str]:
    values = payload.get("item_ids")
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_DETAIL_ITEMS:
        raise HTTPException(422, f"item_ids must contain 1 to {MAX_DETAIL_ITEMS} IDs")
    if any(
        not isinstance(value, str) or not value or len(value) > 200 for value in values
    ):
        raise HTTPException(
            422, "Each item ID must be a non-empty string of at most 200 characters"
        )
    return list(dict.fromkeys(values))


def search_conditions(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    values = payload.get("conditions")
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_SEARCH_CONDITIONS:
        raise HTTPException(
            422, f"conditions must contain 1 to {MAX_SEARCH_CONDITIONS} entries"
        )
    result = []
    seen = set()
    for value in values:
        if not isinstance(value, dict):
            raise HTTPException(422, "Each search condition must be an object")
        ident, field, term = value.get("id"), value.get("field"), value.get("value")
        operator = value.get("operator", "contains")
        if not isinstance(ident, str) or not ident or len(ident) > 200 or ident in seen:
            raise HTTPException(
                422, "Search condition IDs must be unique non-empty strings"
            )
        if field not in {"all", "content", "output"} or operator != "contains":
            raise HTTPException(
                422, "Supported search fields are all/content/output with contains"
            )
        if not isinstance(term, str) or len(term) > 10000:
            raise HTTPException(
                422, "Search values must be strings of at most 10000 characters"
            )
        seen.add(ident)
        result.append({"id": ident, "field": field, "value": term.lower()})
    return result
