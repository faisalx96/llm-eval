from __future__ import annotations

import asyncio
import ast
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import unquote

from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from qym_platform.db.models import CorrectionStatus, ReviewCorrection, RunItem, RunItemScore

logger = logging.getLogger(__name__)

ROOT_CAUSE_CATEGORIES = [
    "Hallucination",
    "Incomplete Answer",
    "Wrong Format",
    "Context Missing",
    "Reasoning Error",
    "Tool Use Error",
    "Instruction Following",
    "Knowledge Gap",
]

SOLUTION_CATEGORIES = [
    "Improve Retrieval Context",
    "Add Guardrails",
    "Refine Prompt Instructions",
    "Expand Training Data",
    "Fix Tool Configuration",
    "Add Output Validation",
    "Restructure Chain-of-Thought",
    "Update Knowledge Base",
]

DEFAULT_SYSTEM_PROMPT = (
    "You are an expert LLM evaluation analyst. Your job is to analyze evaluation results "
    "and determine the root cause of failures or low-quality outputs.\n\n"
    "Given an evaluation item with its input, expected output, actual output, and metric scores, "
    "classify the failure using two levels:\n\n"
    "1. root_cause — the broad failure category. Choose from:\n"
    "{categories}\n\n"
    "{details_section}"
    "You may suggest a custom value for either level if none of the above fit.\n\n"
    "Respond ONLY with valid JSON in this exact format:\n"
    "{{\n"
    '  "root_cause": "<broad category>",\n'
    '  "root_cause_detail": "<specific sub-issue>",\n'
    '  "confidence": <float 0.0-1.0>,\n'
    '  "root_cause_note": "<1-2 sentences: what went wrong and why>"\n'
    "}}\n\n"
    "Keep root_cause_note brief and direct — 1-2 sentences max. "
    "State the specific failure, not general observations."
)

# Default fields to include in item context
DEFAULT_INCLUDE_FIELDS = {
    "input": True,
    "expected": True,
    "output": True,
    "error": True,
    "scores": True,
    "metadata": True,
}


@dataclass
class AnalysisResult:
    item_id: str
    root_cause: str
    root_cause_note: str
    confidence: float
    root_cause_detail: str = ""
    solution: str = ""
    solution_note: str = ""
    error: Optional[str] = None


def build_client(llm_config: dict[str, Any]) -> AsyncOpenAI:
    """Build an AsyncOpenAI client from the user's llm_config."""
    return AsyncOpenAI(
        base_url=llm_config.get("llm_base_url", "https://api.openai.com/v1"),
        api_key=llm_config.get("llm_api_key", ""),
    )


def get_few_shot_examples(
    db: Session,
    task: str,
    limit: int | None = 5,
    correction_ids: list[int] | None = None,
) -> list[ReviewCorrection]:
    """Retrieve *approved* correction bank examples for a given task.

    Only corrections with status=APPROVED are used as few-shot examples.
    If correction_ids is provided, fetch those specific corrections (by ID)
    instead of the latest N — still restricted to approved ones.
    """
    if correction_ids is not None:
        return (
            db.query(ReviewCorrection)
            .filter(
                ReviewCorrection.task == task,
                ReviewCorrection.id.in_(correction_ids),
                ReviewCorrection.status == CorrectionStatus.APPROVED,
                ReviewCorrection.is_active.is_(True),
            )
            .order_by(ReviewCorrection.created_at.desc())
            .all()
        )
    query = (
        db.query(ReviewCorrection)
        .filter(
            ReviewCorrection.task == task,
            ReviewCorrection.status == CorrectionStatus.APPROVED,
            ReviewCorrection.is_active.is_(True),
        )
        .order_by(ReviewCorrection.created_at.desc())
    )
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def _resolve_source(
    item: RunItem,
    source: Any,
    scores: dict[str, RunItemScore] | None = None,
    metric_name: str | None = None,
) -> Any:
    """Resolve a source path, or a list of source paths, from the RunItem."""
    if isinstance(source, list):
        return _resolve_source_selection(item, source, scores=scores, metric_name=metric_name)
    if not isinstance(source, str):
        return None

    if source.startswith("metric_metadata:"):
        metric_source = source[len("metric_metadata:"):]
        if "." in metric_source:
            encoded_metric_name, nested_path = metric_source.split(".", 1)
            parts = ["metric_metadata", nested_path]
        else:
            encoded_metric_name = metric_source
            parts = ["metric_metadata"]
        source_metric_name = unquote(encoded_metric_name)
        metric_score = (scores or {}).get(source_metric_name)
        raw = metric_score.meta if metric_score and isinstance(metric_score.meta, dict) else None
        if len(parts) == 1:
            return raw
        return _resolve_nested_path(raw, parts[1].split("."))

    parts = source.split(".")
    field_name = parts[0]
    raw: Any = None
    if field_name == "metric_metadata":
        source_metric_name = metric_name
        if len(parts) > 1 and scores and parts[1] in scores:
            source_metric_name = parts[1]
            parts = [parts[0]] + parts[2:]
        metric_score = (scores or {}).get(source_metric_name or "") if source_metric_name else None
        raw = metric_score.meta if metric_score and isinstance(metric_score.meta, dict) else None
    else:
        raw = getattr(item, field_name, None)

    if isinstance(raw, str):
        stripped = raw.strip()
        if stripped and stripped[0] in ("{", "["):
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError:
                try:
                    parsed = ast.literal_eval(stripped)
                    if isinstance(parsed, (dict, list)):
                        raw = parsed
                except (SyntaxError, ValueError):
                    pass

    if len(parts) == 1:
        return raw
    return _resolve_nested_path(raw, parts[1:])


def _resolve_nested_path(value: Any, parts: list[str]) -> Any:
    """Resolve nested dict/list paths, including array wildcards like items[].name."""
    if value is None:
        return None
    if not parts:
        return value

    part = parts[0]
    rest = parts[1:]

    if part == "[]":
        if not isinstance(value, list):
            return None
        return [_resolve_nested_path(item, rest) for item in value]

    if part.endswith("[]"):
        key = part[:-2]
        if key:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
        if not isinstance(value, list):
            return None
        return [_resolve_nested_path(item, rest) for item in value]

    if isinstance(value, dict):
        return _resolve_nested_path(value.get(part), rest)
    if isinstance(value, list) and part.isdigit():
        index = int(part)
        if 0 <= index < len(value):
            return _resolve_nested_path(value[index], rest)
    return None


def _resolve_source_selection(
    item: RunItem,
    sources: list[Any],
    scores: dict[str, RunItemScore] | None = None,
    metric_name: str | None = None,
) -> Any:
    """Resolve multiple source paths into a compact object keyed by selected path."""
    projected: dict[str, Any] = {}
    for source in sources:
        if not isinstance(source, str):
            continue
        val = _resolve_source(item, source, scores=scores, metric_name=metric_name)
        if val is None:
            continue
        _assign_projection(projected, _source_selection_parts(source), val)
    return projected or None


def _resolve_correction_source(correction: ReviewCorrection, source: Any) -> Any:
    """Resolve a mapped source path from a correction snapshot."""
    if isinstance(source, list):
        return _resolve_correction_source_selection(correction, source)
    if not isinstance(source, str):
        return None

    snapshot_attrs = {
        "input": "input_snapshot",
        "expected": "expected_snapshot",
        "output": "output_snapshot",
    }
    parts = source.split(".")
    snapshot_attr = snapshot_attrs.get(parts[0])
    if snapshot_attr is None:
        return None

    raw = getattr(correction, snapshot_attr, None)
    if isinstance(raw, str):
        stripped = raw.strip()
        if stripped and stripped[0] in ("{", "["):
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError:
                try:
                    parsed = ast.literal_eval(stripped)
                    if isinstance(parsed, (dict, list)):
                        raw = parsed
                except (SyntaxError, ValueError):
                    pass

    if len(parts) == 1:
        return raw
    return _resolve_nested_path(raw, parts[1:])


def _resolve_correction_source_selection(
    correction: ReviewCorrection,
    sources: list[Any],
) -> Any:
    """Resolve multiple mapped source paths from correction snapshots."""
    projected: dict[str, Any] = {}
    for source in sources:
        if not isinstance(source, str):
            continue
        val = _resolve_correction_source(correction, source)
        if val is None:
            continue
        _assign_projection(projected, _source_selection_parts(source), val)
    return projected or None


def _source_selection_parts(source: str) -> list[str]:
    """Return projection path parts while preserving encoded metric names."""
    if source.startswith("metric_metadata:"):
        metric_source = source[len("metric_metadata:"):]
        if "." not in metric_source:
            return [unquote(metric_source)]
        encoded_metric_name, path = metric_source.split(".", 1)
        return [unquote(encoded_metric_name)] + [p for p in path.split(".") if p]
    label = _source_selection_label(source)
    return [p for p in label.split(".") if p]


def _source_selection_label(source: str) -> str:
    """Return the label used inside a projected multi-source object."""
    if source.startswith("metric_metadata:"):
        metric_source = source[len("metric_metadata:"):]
        if "." not in metric_source:
            return unquote(metric_source)
        encoded_metric_name, path = metric_source.split(".", 1)
        return f"{unquote(encoded_metric_name)}.{path}"
    if "." not in source:
        return source
    return source.split(".", 1)[1] or source


def _assign_projection(target: dict[str, Any], path: str | list[str], value: Any) -> None:
    """Assign a selected path into a nested object when the path is object-only."""
    parts = path if isinstance(path, list) else [p for p in path.split(".") if p]
    if not parts:
        return
    if any("[]" in p for p in parts):
        target[".".join(parts)] = value
        return
    cur = target
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _format_item_context(
    item: RunItem,
    scores: dict[str, RunItemScore],
    include_fields: dict[str, bool] | None = None,
    field_mapping: dict[str, Any] | None = None,
    metric_name: str | None = None,
    metadata_fields: list[str] | None = None,
) -> str:
    """Format a single item's context for the LLM prompt."""
    fields = include_fields or DEFAULT_INCLUDE_FIELDS
    parts: list[str] = []

    def _dump(val: Any) -> str:
        if isinstance(val, (dict, list)):
            return json.dumps(val, indent=2, ensure_ascii=False)
        return str(val or "")

    if field_mapping:
        # Use custom field mapping for input/expected/output
        if "input" in field_mapping:
            val = _resolve_source(item, field_mapping["input"], scores=scores, metric_name=metric_name)
            if val is not None:
                parts.append(f"INPUT:\n{_dump(val)}")
        elif fields.get("input", True):
            parts.append(f"INPUT:\n{_dump(item.input)}")

        if "expected" in field_mapping:
            val = _resolve_source(item, field_mapping["expected"], scores=scores, metric_name=metric_name)
            if val is not None:
                parts.append(f"EXPECTED OUTPUT:\n{_dump(val)}")
        elif fields.get("expected", True) and item.expected is not None:
            parts.append(f"EXPECTED OUTPUT:\n{_dump(item.expected)}")

        if "output" in field_mapping:
            val = _resolve_source(item, field_mapping["output"], scores=scores, metric_name=metric_name)
            if val is not None:
                parts.append(f"ACTUAL OUTPUT:\n{_dump(val)}")
        elif fields.get("output", True) and item.output is not None:
            parts.append(f"ACTUAL OUTPUT:\n{_dump(item.output)}")
    else:
        if fields.get("input", True):
            parts.append(f"INPUT:\n{_dump(item.input)}")
        if fields.get("expected", True) and item.expected is not None:
            parts.append(f"EXPECTED OUTPUT:\n{_dump(item.expected)}")
        if fields.get("output", True) and item.output is not None:
            parts.append(f"ACTUAL OUTPUT:\n{_dump(item.output)}")
    if fields.get("error", True) and item.error:
        parts.append(f"ERROR:\n{item.error}")

    # Include metric scores
    if fields.get("scores", True):
        score_lines: list[str] = []
        for metric_name, score in scores.items():
            val = score.score_numeric if score.score_numeric is not None else score.score_raw
            score_lines.append(f"  {metric_name}: {val}")
            if score.meta:
                for k, v in score.meta.items():
                    if k in ("reason", "explanation", "feedback") and v:
                        score_lines.append(f"    {k}: {v}")
        if score_lines:
            parts.append("METRIC SCORES:\n" + "\n".join(score_lines))

    # Include metric metadata. By default this is all metrics; a picker selection
    # can narrow it to specific metric/path pairs.
    if fields.get("metadata", True):
        if metadata_fields is not None:
            metric_meta = _resolve_source(item, metadata_fields, scores=scores, metric_name=metric_name) or {}
        else:
            metric_meta = {
                name: score.meta
                for name, score in (scores or {}).items()
                if isinstance(score.meta, dict) and score.meta
            }
        if metric_meta:
            parts.append(
                "METRIC METADATA:\n"
                f"{json.dumps(metric_meta, indent=2, ensure_ascii=False)}"
            )

    return "\n\n".join(parts)


def _format_correction_example(
    correction: ReviewCorrection,
    include_fields: dict[str, bool] | None = None,
    field_mapping: dict[str, Any] | None = None,
) -> str:
    """Format a correction bank entry as a few-shot example."""
    fields = include_fields or DEFAULT_INCLUDE_FIELDS
    parts: list[str] = []

    def _dump(val: Any) -> str:
        if isinstance(val, (dict, list)):
            return json.dumps(val, indent=2, ensure_ascii=False)
        return str(val or "")

    def _append_context(label: str, key: str, snapshot_attr: str) -> None:
        if field_mapping and key in field_mapping:
            val = _resolve_correction_source(correction, field_mapping[key])
            if val is not None:
                parts.append(f"{label}:\n{_dump(val)}")
            return
        if not fields.get(key, True):
            return
        val = getattr(correction, snapshot_attr, None)
        if val is not None:
            parts.append(f"{label}:\n{_dump(val)}")

    _append_context("INPUT", "input", "input_snapshot")
    _append_context("EXPECTED OUTPUT", "expected", "expected_snapshot")
    _append_context("ACTUAL OUTPUT", "output", "output_snapshot")
    if fields.get("scores", True) and correction.scores_snapshot:
        score_lines = [f"  {k}: {v}" for k, v in correction.scores_snapshot.items()]
        parts.append("METRIC SCORES:\n" + "\n".join(score_lines))

    context = "\n\n".join(parts)

    # Build the answer section — only show the approved human labels
    answer_parts: list[str] = []
    answer_parts.append(f"CORRECT root_cause: {correction.human_root_cause}")
    human_detail = getattr(correction, "human_root_cause_detail", None)
    if human_detail:
        answer_parts.append(f"CORRECT root_cause_detail: {human_detail}")
    if correction.human_root_cause_note:
        answer_parts.append(f"CORRECT reasoning: {correction.human_root_cause_note}")

    return (
        f"--- Example ---\n"
        f"{context}\n\n"
        + "\n".join(answer_parts)
        + "\n--- End Example ---"
    )


def build_analysis_prompt(
    item: RunItem,
    scores: dict[str, RunItemScore],
    corrections: list[ReviewCorrection],
    config: dict[str, Any] | None = None,
    metric_name: str | None = None,
) -> list[dict[str, str]]:
    """Build the full chat messages for root cause analysis.

    config keys:
      - system_prompt: overrides DEFAULT_SYSTEM_PROMPT
      - root_cause_categories: overrides ROOT_CAUSE_CATEGORIES
      - include_fields: dict controlling which sections to include
      - correction_ids: filter which corrections to use by id
      - corrections_enabled: False to skip all corrections
    """
    cfg = config or {}

    categories = cfg.get("root_cause_categories") or ROOT_CAUSE_CATEGORIES
    categories_text = "\n".join(f"- {cat}" for cat in categories)

    cat_details_map: dict[str, list[str]] | None = cfg.get("category_details_map")
    flat_details: list[str] = cfg.get("root_cause_details") or []

    if cat_details_map is not None:
        # Build details section grouped by category
        lines: list[str] = [
            "2. root_cause_detail — the specific sub-issue. "
            "Use the known details for each category when applicable:"
        ]
        for cat in categories:
            dets = cat_details_map.get(cat, [])
            if dets:
                lines.append(f"  {cat}:")
                for d in dets:
                    lines.append(f"    - {d}")
        details_section = "\n".join(lines) + "\n\n"
    elif flat_details:
        details_section = (
            "2. root_cause_detail — the specific sub-issue. Prefer these known values when applicable:\n"
            + "\n".join(f"- {d}" for d in flat_details)
            + "\n\n"
        )
    else:
        details_section = (
            "2. root_cause_detail — the specific sub-issue within that category "
            "(e.g. root_cause='Context Missing', root_cause_detail='Out of Scope Query').\n\n"
        )

    raw_prompt = cfg.get("system_prompt") or DEFAULT_SYSTEM_PROMPT
    try:
        system_prompt = raw_prompt.format(
            categories=categories_text, details_section=details_section,
        )
    except (KeyError, IndexError):
        system_prompt = raw_prompt.replace("{categories}", categories_text)
        system_prompt = system_prompt.replace("{details_section}", details_section)

    # Append additional instructions (with variable resolution)
    additional = cfg.get("additional_instructions", "")
    if additional:
        custom_map = cfg.get("custom_variable_mapping") or {}
        resolved = additional
        for var_name, source in custom_map.items():
            val = _resolve_source(item, source, scores=scores, metric_name=metric_name)
            if val is not None:
                if isinstance(val, (dict, list)):
                    dump = json.dumps(val, indent=2, ensure_ascii=False)
                else:
                    dump = str(val)
            else:
                dump = "(not available)"
            resolved = resolved.replace("{" + var_name + "}", dump)
        system_prompt += "\n\nAdditional Instructions:\n" + resolved

    include_fields = cfg.get("include_fields")
    field_mapping = cfg.get("field_mapping")
    metadata_fields = cfg.get("metadata_fields")

    # Filter corrections
    corrections_enabled = cfg.get("corrections_enabled", True)
    if not corrections_enabled:
        active_corrections: list[ReviewCorrection] = []
    else:
        active_corrections = list(corrections)

    # Build few-shot examples section
    examples_section = ""
    if active_corrections:
        examples_section = (
            "\n\nHere are approved examples of how items should be classified. "
            "Follow the same patterns and reasoning:\n\n"
            + "\n\n".join(
                _format_correction_example(
                    c,
                    include_fields=include_fields,
                    field_mapping=field_mapping,
                )
                for c in active_corrections
            )
            + "\n\nApply the classification patterns from these examples to the item below."
        )

    item_context = _format_item_context(
        item,
        scores,
        include_fields,
        field_mapping,
        metric_name=metric_name,
        metadata_fields=metadata_fields if isinstance(metadata_fields, list) else None,
    )

    user_message = (
        f"{examples_section}\n\n"
        f"Now analyze this evaluation item:\n\n"
        f"{item_context}\n\n"
        f"Determine the root cause category. Provide your analysis as JSON."
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]


def parse_llm_response(response_text: str, item_id: str) -> AnalysisResult:
    """Parse the LLM's JSON response into an AnalysisResult."""
    try:
        text = response_text.strip()
        # Handle markdown code blocks
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [line for line in lines if not line.strip().startswith("```")]
            text = "\n".join(lines).strip()

        # First try parsing as-is
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Strip control characters that some models inject and retry
            text = re.sub(r"[\x00-\x1f]", lambda m: m.group() if m.group() in ("\n", "\r", "\t") else " ", text)
            data = json.loads(text)
        if "root_cause" not in data or not str(data["root_cause"]).strip():
            return AnalysisResult(
                item_id=item_id,
                root_cause="Unknown",
                root_cause_note=f"LLM response missing root_cause field: {response_text[:500]}",
                confidence=0.0,
                error="missing_root_cause",
            )
        return AnalysisResult(
            item_id=item_id,
            root_cause=str(data["root_cause"]).strip(),
            root_cause_note=str(data.get("root_cause_note", "")),
            confidence=float(data.get("confidence", 0.5)),
            root_cause_detail=str(data.get("root_cause_detail", "")),
            solution=str(data.get("solution", "")),
            solution_note=str(data.get("solution_note", "")),
        )
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.warning("Failed to parse LLM response for item %s: %s", item_id, e)
        return AnalysisResult(
            item_id=item_id,
            root_cause="Unknown",
            root_cause_note=f"Failed to parse LLM response: {response_text[:500]}",
            confidence=0.0,
            error=str(e),
        )


def _extract_json_from_reasoning(reasoning: str, item_id: str) -> AnalysisResult | None:
    """Try to extract a root-cause JSON object from reasoning model thinking text."""
    # Look for JSON blocks in the reasoning text
    json_pattern = re.compile(
        r'\{[^{}]*"root_cause"\s*:\s*"[^"]+?"[^{}]*"root_cause_note"\s*:\s*"[^"]*?"[^{}]*\}',
        re.DOTALL,
    )
    match = json_pattern.search(reasoning)
    if match:
        result = parse_llm_response(match.group(0), item_id)
        if result.error is None:
            return result

    # Fallback: extract fields from the reasoning narrative
    rc_match = re.search(
        r"root[_ ]?cause[^:]*:\s*[\"']?([A-Z][A-Za-z /]+)", reasoning
    )
    if rc_match:
        root_cause = rc_match.group(1).strip().rstrip(".,;\"'")
        # Try to find confidence
        conf_match = re.search(r"confidence[^:]*:\s*(0\.\d+|1\.0)", reasoning)
        confidence = float(conf_match.group(1)) if conf_match else 0.6
        return AnalysisResult(
            item_id=item_id,
            root_cause=root_cause,
            root_cause_note=reasoning[-500:] if len(reasoning) > 500 else reasoning,
            confidence=confidence,
        )
    return None


async def analyze_single_item(
    client: AsyncOpenAI,
    model: str,
    item: RunItem,
    scores: dict[str, RunItemScore],
    corrections: list[ReviewCorrection],
    config: dict[str, Any] | None = None,
    metric_name: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> AnalysisResult:
    """Analyze a single item using the LLM."""
    messages = build_analysis_prompt(item, scores, corrections, config=config, metric_name=metric_name)
    try:
        kwargs: dict[str, Any] = dict(
            model=model,
            messages=messages,
            temperature=temperature if temperature is not None else 0.2,
        )
        # Use JSON response format when supported (OpenAI, compatible providers)
        try:
            kwargs["response_format"] = {"type": "json_object"}
        except Exception:
            pass

        response = await client.chat.completions.create(**kwargs)
        choice = response.choices[0] if response.choices else None
        if not choice:
            logger.warning("No choices in LLM response for item %s", item.item_id)
            return AnalysisResult(
                item_id=item.item_id,
                root_cause="Unknown",
                root_cause_note="LLM returned no choices",
                confidence=0.0,
                error="empty_choices",
            )

        content = choice.message.content or ""
        finish = choice.finish_reason or ""

        # For reasoning models (e.g. kimi-k2.5, DeepSeek-R1), the analysis may
        # be in a `reasoning` field while `content` holds just the JSON answer.
        # If content is empty but reasoning exists, extract from reasoning.
        if not content.strip():
            reasoning = getattr(choice.message, "reasoning", None) or ""
            if reasoning:
                logger.info(
                    "Empty content for item %s but found reasoning (%d chars), "
                    "extracting from reasoning field",
                    item.item_id,
                    len(reasoning),
                )
                result = _extract_json_from_reasoning(reasoning, item.item_id)
                if result:
                    return result

            logger.warning(
                "Empty LLM content for item %s (finish_reason=%s, reasoning=%d chars)",
                item.item_id,
                finish,
                len(reasoning),
            )
            return AnalysisResult(
                item_id=item.item_id,
                root_cause="Unknown",
                root_cause_note=f"LLM returned empty response (finish_reason={finish})",
                confidence=0.0,
                error=f"empty_content:{finish}",
            )

        return parse_llm_response(content, item.item_id)
    except Exception as e:
        logger.error("LLM API error for item %s: %s", item.item_id, e, exc_info=True)
        return AnalysisResult(
            item_id=item.item_id,
            root_cause="Unknown",
            root_cause_note=f"LLM API error: {e}",
            confidence=0.0,
            error=str(e),
        )


async def analyze_items_batch(
    client: AsyncOpenAI,
    model: str,
    items: list[tuple[RunItem, dict[str, RunItemScore]]],
    corrections: list[ReviewCorrection],
    concurrency: int = 20,
    config: dict[str, Any] | None = None,
    metric_name: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    progress_callback: Callable[[AnalysisResult, int, int], Awaitable[None] | None] | None = None,
) -> list[AnalysisResult]:
    """Analyze multiple items with concurrency control."""
    semaphore = asyncio.Semaphore(concurrency)
    progress_lock = asyncio.Lock()
    completed = 0
    total = len(items)

    async def _bounded(item: RunItem, scores: dict[str, RunItemScore]) -> AnalysisResult:
        nonlocal completed
        async with semaphore:
            result = await analyze_single_item(
                client, model, item, scores, corrections,
                config=config, metric_name=metric_name, temperature=temperature, max_tokens=max_tokens,
            )
        if progress_callback is not None:
            async with progress_lock:
                completed += 1
                current = completed
            callback_result = progress_callback(result, current, total)
            if asyncio.iscoroutine(callback_result):
                await callback_result
        return result

    tasks = [_bounded(item, scores) for item, scores in items]
    return await asyncio.gather(*tasks)
