from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from qym_platform.db.models import ReviewCorrection, RunItem, RunItemScore

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


@dataclass
class AnalysisResult:
    item_id: str
    root_cause: str
    root_cause_note: str
    confidence: float
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
    limit: int = 5,
) -> list[ReviewCorrection]:
    """Retrieve the most recent correction bank examples for a given task."""
    return (
        db.query(ReviewCorrection)
        .filter(ReviewCorrection.task == task)
        .order_by(ReviewCorrection.created_at.desc())
        .limit(limit)
        .all()
    )


def _format_item_context(
    item: RunItem,
    scores: dict[str, RunItemScore],
) -> str:
    """Format a single item's context for the LLM prompt."""
    parts: list[str] = []

    def _dump(val: Any) -> str:
        if isinstance(val, (dict, list)):
            return json.dumps(val, indent=2, ensure_ascii=False)
        return str(val or "")

    parts.append(f"INPUT:\n{_dump(item.input)}")
    if item.expected is not None:
        parts.append(f"EXPECTED OUTPUT:\n{_dump(item.expected)}")
    if item.output is not None:
        parts.append(f"ACTUAL OUTPUT:\n{_dump(item.output)}")
    if item.error:
        parts.append(f"ERROR:\n{item.error}")

    # Include metric scores
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

    # Include relevant item metadata (exclude root-cause fields)
    md = item.item_metadata if isinstance(item.item_metadata, dict) else {}
    skip_keys = {
        "task_started_at_ms",
        "root_cause",
        "root_cause_note",
        "root_cause_source",
        "root_cause_confidence",
    }
    relevant = {k: v for k, v in md.items() if k not in skip_keys}
    if relevant:
        parts.append(f"METADATA:\n{json.dumps(relevant, indent=2, ensure_ascii=False)}")

    return "\n\n".join(parts)


def _format_correction_example(correction: ReviewCorrection) -> str:
    """Format a correction bank entry as a few-shot example."""
    parts: list[str] = []

    def _dump(val: Any) -> str:
        if isinstance(val, (dict, list)):
            return json.dumps(val, indent=2, ensure_ascii=False)
        return str(val or "")

    if correction.input_snapshot is not None:
        parts.append(f"INPUT:\n{_dump(correction.input_snapshot)}")
    if correction.expected_snapshot is not None:
        parts.append(f"EXPECTED OUTPUT:\n{_dump(correction.expected_snapshot)}")
    if correction.output_snapshot is not None:
        parts.append(f"ACTUAL OUTPUT:\n{_dump(correction.output_snapshot)}")
    if correction.scores_snapshot:
        score_lines = [f"  {k}: {v}" for k, v in correction.scores_snapshot.items()]
        parts.append("METRIC SCORES:\n" + "\n".join(score_lines))

    context = "\n\n".join(parts)

    # Build the answer section — adapt based on whether there was a prior AI suggestion
    answer_parts: list[str] = []
    if correction.ai_root_cause and correction.ai_root_cause != "Unanalyzed":
        answer_parts.append(f"AI suggested: {correction.ai_root_cause}")
        if correction.ai_root_cause_note:
            answer_parts.append(f"AI reasoning: {correction.ai_root_cause_note}")
    answer_parts.append(f"CORRECT answer: {correction.human_root_cause}")
    if correction.human_root_cause_note:
        answer_parts.append(f"Human feedback: {correction.human_root_cause_note}")

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
) -> list[dict[str, str]]:
    """Build the full chat messages for root cause analysis."""

    system_prompt = (
        "You are an expert LLM evaluation analyst. Your job is to analyze evaluation results "
        "and determine the root cause of failures or low-quality outputs.\n\n"
        "Given an evaluation item with its input, expected output, actual output, and metric scores, "
        "determine the most likely root cause category and provide a detailed explanation.\n\n"
        "Available root cause categories:\n"
        + "\n".join(f"- {cat}" for cat in ROOT_CAUSE_CATEGORIES)
        + "\n\nYou may also suggest a custom category if none of the above fit.\n\n"
        "Respond ONLY with valid JSON in this exact format:\n"
        "{\n"
        '  "root_cause": "<category name>",\n'
        '  "confidence": <float 0.0-1.0>,\n'
        '  "root_cause_note": "<detailed explanation of why this root cause was identified>"\n'
        "}"
    )

    # Build few-shot examples section
    examples_section = ""
    if corrections:
        examples_section = (
            "\n\nHere are examples of past corrections where a human reviewer corrected "
            "the AI's initial assessment. Learn from these to improve your analysis:\n\n"
            + "\n\n".join(_format_correction_example(c) for c in corrections)
            + "\n\nPlease learn from the patterns in these corrections. "
            "Pay special attention to cases where the AI's initial judgment was wrong "
            "and understand why the human chose a different root cause."
        )

    item_context = _format_item_context(item, scores)

    user_message = (
        f"{examples_section}\n\n"
        f"Now analyze this evaluation item:\n\n"
        f"{item_context}\n\n"
        f"Determine the root cause category and provide your analysis as JSON."
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
        return AnalysisResult(
            item_id=item_id,
            root_cause=str(data.get("root_cause", "Unknown")),
            root_cause_note=str(data.get("root_cause_note", "")),
            confidence=float(data.get("confidence", 0.5)),
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
) -> AnalysisResult:
    """Analyze a single item using the LLM."""
    messages = build_analysis_prompt(item, scores, corrections)
    try:
        kwargs: dict[str, Any] = dict(
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=16384,
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
    concurrency: int = 5,
) -> list[AnalysisResult]:
    """Analyze multiple items with concurrency control."""
    semaphore = asyncio.Semaphore(concurrency)

    async def _bounded(item: RunItem, scores: dict[str, RunItemScore]) -> AnalysisResult:
        async with semaphore:
            return await analyze_single_item(client, model, item, scores, corrections)

    tasks = [_bounded(item, scores) for item, scores in items]
    return await asyncio.gather(*tasks)
