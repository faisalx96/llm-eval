"""Core infrastructure for LLM-as-judge metrics."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional

from ..judge_config import JudgeConfig, get_default_judge_config
from ..result import MetricResult

logger = logging.getLogger(__name__)

# Default system prompt shared by all judges
DEFAULT_SYSTEM_PROMPT = (
    "You are an expert evaluation judge. Evaluate the content according to the "
    "criteria given by the user. Respond ONLY with a JSON object containing two "
    'keys: "verdict" (one of the allowed labels) and "explanation" (a brief '
    "justification for your verdict). Do not include any other text."
)


# ---------------------------------------------------------------------------
# snap_to_rail — fuzzy label extraction fallback
# ---------------------------------------------------------------------------


def snap_to_rail(text: str, rails: List[str]) -> Optional[str]:
    """Fuzzy label extraction from free text.

    Case-insensitive substring match.  Longest rail first to avoid partial
    matches (e.g. ``"non-toxic"`` before ``"toxic"``).

    Returns the longest matching rail.  Returns *None* if no rails match.
    """
    lowered = text.lower()
    # Sort longest first so "non-toxic" is checked before "toxic"
    sorted_rails = sorted(rails, key=len, reverse=True)
    for rail in sorted_rails:
        if rail.lower() in lowered:
            return rail
    return None


# ---------------------------------------------------------------------------
# llm_judge — core LLM call
# ---------------------------------------------------------------------------


async def llm_judge(
    *,
    system_prompt: str,
    user_prompt: str,
    choices: Dict[str, float],
    config: Optional[JudgeConfig] = None,
) -> MetricResult:
    """Core LLM judge call.  All specific judges delegate here.

    Response parsing pipeline:

    1. Call LLM with ``response_format={"type": "json_object"}``
    2. Parse JSON -> extract ``"verdict"`` and ``"explanation"``
    3. Map verdict to score via *choices* dict
    4. If JSON fails: fallback to ``snap_to_rail`` on raw text
    5. If all parsing fails: return ``score=0.0`` with error in metadata
    """
    try:
        from openai import AsyncOpenAI
    except ImportError:
        raise ImportError(
            "The 'openai' package is required for LLM judge metrics. "
            "Install it with: pip install qym[judges]"
        )

    cfg = config or get_default_judge_config()

    client = AsyncOpenAI(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        timeout=cfg.timeout,
    )

    try:
        response = await client.chat.completions.create(
            model=cfg.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            response_format={"type": "json_object"},
        )
        raw_text = response.choices[0].message.content or ""
    except Exception as exc:
        logger.warning("LLM judge call failed: %s", exc)
        return MetricResult(
            score=0.0,
            kind="llm",
            metadata={"error": str(exc)},
        )

    # --- Parse response ---
    verdict: Optional[str] = None
    explanation: Optional[str] = None

    try:
        parsed = json.loads(raw_text)
        verdict = parsed.get("verdict")
        explanation = parsed.get("explanation")
    except (json.JSONDecodeError, TypeError):
        # Fallback: snap_to_rail on the raw text
        verdict = snap_to_rail(raw_text, list(choices.keys()))

    if verdict and verdict in choices:
        return MetricResult(
            score=choices[verdict],
            label=verdict,
            explanation=explanation,
            kind="llm",
        )

    # Verdict not in choices — try case-insensitive match
    if verdict:
        for key in choices:
            if key.lower() == verdict.lower():
                return MetricResult(
                    score=choices[key],
                    label=key,
                    explanation=explanation,
                    kind="llm",
                )

    # Last resort: snap_to_rail on raw text
    snapped = snap_to_rail(raw_text, list(choices.keys()))
    if snapped:
        return MetricResult(
            score=choices[snapped],
            label=snapped,
            explanation=explanation,
            kind="llm",
        )

    # Unparsable
    return MetricResult(
        score=0.0,
        kind="llm",
        metadata={"error": "Could not parse LLM verdict", "raw_response": raw_text},
    )


# ---------------------------------------------------------------------------
# create_judge — generic factory
# ---------------------------------------------------------------------------


def create_judge(
    name: str,
    prompt: str,
    choices: Dict[str, float],
    *,
    langfuse_prompt: Optional[str] = None,
    system_prompt: Optional[str] = None,
    judge_model: Optional[str] = None,
    judge_base_url: Optional[str] = None,
    judge_api_key: Optional[str] = None,
) -> Callable:
    """Generic LLM judge factory.

    Returns an async metric function with signature
    ``(output, expected, input_data) -> MetricResult``.

    The *prompt* template uses ``{variable}`` syntax.  Variables are filled
    from:

    * ``{output}``   — task output
    * ``{expected}``  — expected output from dataset
    * ``{input}``     — raw input
    * Any key from *input_data* dict (e.g. ``{context}``, ``{question}``)

    If *langfuse_prompt* is set, the prompt is fetched from Langfuse prompt
    management instead of using the *prompt* parameter.
    """
    sys_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    # Build per-judge config override (only fields that were explicitly passed)
    _cfg_overrides: Dict[str, Any] = {}
    if judge_model is not None:
        _cfg_overrides["model"] = judge_model
    if judge_base_url is not None:
        _cfg_overrides["base_url"] = judge_base_url
    if judge_api_key is not None:
        _cfg_overrides["api_key"] = judge_api_key

    async def _metric(output: Any, expected: Any = None, input_data: Any = None) -> MetricResult:
        # Resolve config
        cfg = None
        if _cfg_overrides:
            base = get_default_judge_config()
            cfg = JudgeConfig(
                model=_cfg_overrides.get("model", base.model),
                base_url=_cfg_overrides.get("base_url", base.base_url),
                api_key=_cfg_overrides.get("api_key", base.api_key),
                temperature=base.temperature,
                max_tokens=base.max_tokens,
                timeout=base.timeout,
            )

        # Resolve prompt template
        tpl = prompt
        if langfuse_prompt:
            tpl = _fetch_langfuse_prompt(langfuse_prompt)

        # Build substitution dict
        subs: Dict[str, str] = {
            "output": str(output) if output is not None else "",
            "expected": str(expected) if expected is not None else "",
            "input": str(input_data) if input_data is not None else "",
        }
        if isinstance(input_data, dict):
            for k, v in input_data.items():
                subs.setdefault(k, str(v) if v is not None else "")

        # Safe format: only replace known keys, leave unknown {keys} intact
        user_prompt = tpl
        for k, v in subs.items():
            user_prompt = user_prompt.replace("{" + k + "}", v)

        return await llm_judge(
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            choices=choices,
            config=cfg,
        )

    _metric.__name__ = name
    _metric.__qualname__ = name
    return _metric


def _fetch_langfuse_prompt(prompt_name: str) -> str:
    """Fetch a prompt template from Langfuse prompt management."""
    try:
        from langfuse import Langfuse

        client = Langfuse()
        prompt_obj = client.get_prompt(prompt_name)
        return prompt_obj.prompt
    except Exception as exc:
        logger.warning("Failed to fetch Langfuse prompt '%s': %s", prompt_name, exc)
        raise
