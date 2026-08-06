"""Shared normalization for multi-category root-cause diagnoses."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Iterable


# The analyzer may return several independent explanations for one item/metric.
# Keep the default deliberately small so the labels stay useful and reviewable.
DEFAULT_MAX_ROOT_CAUSE_CATEGORIES = 3
MAX_CONFIGURABLE_ROOT_CAUSE_CATEGORIES = 10
MAX_CATEGORY_TAXONOMY_ENTRIES = 100
MAX_CATEGORY_TAXONOMY_FIELD_CHARS = 2_000


# These definitions are deliberately short enough to be useful in every
# analysis prompt.  Project/task-specific definitions can override them, and
# custom categories are expected to provide the same two fields when the LLM
# introduces them.
ROOT_CAUSE_TAXONOMY: dict[str, dict[str, str]] = {
    "Hallucination": {
        "description": "The response asserts facts, entities, values, or behavior that are not supported by the available evidence.",
        "when_to_use": "Use when the output contains fabricated or unsupported information and the primary failure is not simply missing content or incorrect formatting.",
    },
    "Incomplete Answer": {
        "description": "The response omits a required part of the requested answer or fails to complete the requested task.",
        "when_to_use": "Use when the response is materially incomplete even though the omitted information was available or the task was otherwise understood.",
    },
    "Wrong Format": {
        "description": "The response does not follow the required output structure, syntax, schema, or formatting contract.",
        "when_to_use": "Use when formatting or schema non-compliance is the main reason the selected metric failed.",
    },
    "Context Missing": {
        "description": "The model lacked, failed to retrieve, or failed to use context needed to produce the correct answer.",
        "when_to_use": "Use when the evidence shows that missing or unused input, retrieval, memory, or tool context caused the failure.",
    },
    "Reasoning Error": {
        "description": "The response uses an invalid inference, calculation, transformation, or logical step despite having sufficient relevant information.",
        "when_to_use": "Use when the model had the necessary facts but reached the wrong result because its reasoning or computation was incorrect.",
    },
    "Tool Use Error": {
        "description": "A tool was selected, invoked, parameterized, interpreted, or sequenced incorrectly.",
        "when_to_use": "Use when an incorrect tool action or tool-result handling is the direct cause of the failed metric.",
    },
    "Instruction Following": {
        "description": "The response violates an explicit instruction, constraint, policy, or requested behavior.",
        "when_to_use": "Use when the model understood or had access to the requirement but did not follow it, and the failure is not better explained by format alone.",
    },
    "Knowledge Gap": {
        "description": "The model cannot provide a correct answer because it lacks knowledge that was not supplied in the evaluation context.",
        "when_to_use": "Use when the failure depends on information absent from the model's available knowledge and context, without evidence of fabrication or reasoning error.",
    },
    "Dataset Issue": {
        "description": "The evaluation input, expected answer, metadata, or other dataset record is incorrect, ambiguous, or internally inconsistent.",
        "when_to_use": "Use when the record itself makes a correct evaluation or answer impossible, ambiguous, or misleading.",
    },
}

# Explicit aliases make the vocabulary discoverable to callers that use the
# older "default" naming convention.
DEFAULT_ROOT_CAUSE_TAXONOMY = ROOT_CAUSE_TAXONOMY
DEFAULT_CATEGORY_TAXONOMY = ROOT_CAUSE_TAXONOMY
CATEGORY_TAXONOMY = ROOT_CAUSE_TAXONOMY


def _taxonomy_text(value: Any) -> str:
    """Normalize one taxonomy field without allowing unbounded prompt data."""
    return " ".join(str(value or "").split()).strip()[:MAX_CATEGORY_TAXONOMY_FIELD_CHARS]


def _taxonomy_candidates(value: Any) -> list[tuple[str, Any]]:
    """Flatten map and list taxonomy shapes used by API clients and LLMs."""
    if value is None:
        return []
    if isinstance(value, Mapping):
        # A single entry is also accepted so the parser can handle a model that
        # returns one object instead of an array.
        if any(key in value for key in ("category", "name", "label", "root_cause")):
            return [("", value)]
        return [(str(key), raw_value) for key, raw_value in value.items()]
    if isinstance(value, (list, tuple, set)):
        return [("", raw_value) for raw_value in value]
    return []


def normalize_category_taxonomy(value: Any) -> dict[str, dict[str, str]]:
    """Return a bounded, case-insensitive category taxonomy map.

    The canonical shape is ``{category: {description, when_to_use}}``.  A list
    of ``{category, description, when_to_use}`` objects is accepted as an
    interchange shape because it is easier for an LLM to emit reliably.
    """
    taxonomy: dict[str, dict[str, str]] = {}
    key_by_fold: dict[str, str] = {}
    for map_key, raw_entry in _taxonomy_candidates(value):
        if isinstance(raw_entry, Mapping):
            label = _taxonomy_text(
                raw_entry.get("category")
                or raw_entry.get("name")
                or raw_entry.get("label")
                or raw_entry.get("root_cause")
                or map_key
            )
            description = _taxonomy_text(
                raw_entry.get("description") or raw_entry.get("definition")
            )
            when_to_use = _taxonomy_text(
                raw_entry.get("when_to_use")
                or raw_entry.get("use_when")
                or raw_entry.get("usage")
                or raw_entry.get("criteria")
            )
        else:
            label = _taxonomy_text(map_key)
            description = _taxonomy_text(raw_entry)
            when_to_use = ""
        if not label:
            continue
        folded = label.casefold()
        existing_label = key_by_fold.get(folded)
        if existing_label is None:
            if len(taxonomy) >= MAX_CATEGORY_TAXONOMY_ENTRIES:
                break
            existing_label = label
            key_by_fold[folded] = existing_label
            taxonomy[existing_label] = {}
        entry = taxonomy[existing_label]
        if description:
            entry["description"] = description
        if when_to_use:
            entry["when_to_use"] = when_to_use
    return taxonomy


def merge_category_taxonomies(*values: Any) -> dict[str, dict[str, str]]:
    """Merge taxonomy maps while preserving canonical label casing.

    Later non-empty fields win.  This lets project/task-specific definitions
    override built-ins without allowing an empty partial entry to erase them.
    """
    merged: dict[str, dict[str, str]] = {}
    key_by_fold: dict[str, str] = {}
    for value in values:
        for label, entry in normalize_category_taxonomy(value).items():
            folded = label.casefold()
            canonical = key_by_fold.get(folded)
            if canonical is None:
                if len(merged) >= MAX_CATEGORY_TAXONOMY_ENTRIES:
                    break
                canonical = label
                key_by_fold[folded] = canonical
                merged[canonical] = {}
            for field in ("description", "when_to_use"):
                text = _taxonomy_text(entry.get(field))
                if text:
                    merged[canonical][field] = text
    return merged


def category_taxonomy_for_categories(
    taxonomy: Any,
    categories: Iterable[Any],
) -> dict[str, dict[str, str]]:
    """Project a taxonomy map onto category labels in stable category order."""
    normalized = normalize_category_taxonomy(taxonomy)
    by_fold = {label.casefold(): entry for label, entry in normalized.items()}
    selected: dict[str, dict[str, str]] = {}
    seen: set[str] = set()
    for raw_category in categories:
        category = _taxonomy_text(raw_category)
        if not category or category.casefold() in seen:
            continue
        entry = by_fold.get(category.casefold())
        if entry:
            selected[category] = dict(entry)
            seen.add(category.casefold())
    return selected


def taxonomy_is_complete(value: Any) -> bool:
    """Return whether a taxonomy entry contains both required explanations."""
    if not isinstance(value, Mapping):
        return False
    entry_value = dict(value)
    entry_value.pop("category", None)
    entry_value.pop("name", None)
    entry_value.pop("label", None)
    entry_value.pop("root_cause", None)
    entry = normalize_category_taxonomy({"entry": entry_value}).get("entry", {})
    return bool(entry.get("description") and entry.get("when_to_use"))


def resolve_max_root_cause_categories(
    config: dict[str, Any] | None = None,
) -> int:
    """Resolve and bound the configured category count."""
    raw_value = (config or {}).get(
        "max_root_cause_categories",
        (config or {}).get("max_categories", DEFAULT_MAX_ROOT_CAUSE_CATEGORIES),
    )
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = DEFAULT_MAX_ROOT_CAUSE_CATEGORIES
    return max(1, min(value, MAX_CONFIGURABLE_ROOT_CAUSE_CATEGORIES))


def normalize_root_causes(
    value: Any,
    *,
    max_categories: int | None = None,
) -> list[str]:
    """Return unique, display-ready category labels in stable order.

    A string is treated as one category for compatibility with historical
    records. Lists are the new representation. ``max_categories`` is applied
    only when explicitly supplied so persisted legacy data is never silently
    truncated by a read-only conversion.
    """
    if value is None:
        return []
    raw_values: Iterable[Any]
    if isinstance(value, (list, tuple, set)):
        raw_values = value
    else:
        raw_values = (value,)

    categories: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        label = " ".join(str(raw_value or "").split()).strip()[:200]
        key = label.casefold()
        if not label or key in seen:
            continue
        seen.add(key)
        categories.append(label)
        if max_categories is not None and len(categories) >= max_categories:
            break
    return categories


def analysis_root_causes(
    analysis: dict[str, Any] | None,
    *,
    max_categories: int | None = None,
) -> list[str]:
    """Read plural or legacy singular categories from an analysis mapping."""
    if not isinstance(analysis, dict):
        return []
    if "root_causes" in analysis and analysis.get("root_causes") is not None:
        return normalize_root_causes(
            analysis.get("root_causes"), max_categories=max_categories
        )
    if (
        "root_cause_categories" in analysis
        and analysis.get("root_cause_categories") is not None
    ):
        return normalize_root_causes(
            analysis.get("root_cause_categories"), max_categories=max_categories
        )
    return normalize_root_causes(
        analysis.get("root_cause"), max_categories=max_categories
    )


def primary_root_cause(value: Any) -> str:
    """Return the first category for legacy singular fields."""
    return (normalize_root_causes(value, max_categories=1) or [""])[0]
