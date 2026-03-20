"""Core infrastructure for LLM-as-judge metrics."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from typing import Any, Callable, Dict, List, Optional

from ..judge_config import JudgeConfig, get_default_judge_config
from ..result import MetricResult

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "You are an expert evaluation judge. Evaluate the content according to the "
    "criteria given by the user. Respond ONLY with a JSON object containing two "
    'keys: "verdict" (one of the allowed labels) and "explanation" (a brief '
    "justification for your verdict). Do not include any other text."
)


def snap_to_rail(text: str, rails: List[str]) -> Optional[str]:
    """Fuzzy label extraction from free text using word boundary matching.

    Case-insensitive.  Longest rail first to avoid partial matches
    (e.g. ``"non-toxic"`` before ``"toxic"``).
    """
    sorted_rails = sorted(rails, key=len, reverse=True)
    for rail in sorted_rails:
        # Use word boundary for single words, substring for multi-word/hyphenated
        pattern = r'\b' + re.escape(rail) + r'\b' if ' ' not in rail and '-' not in rail else re.escape(rail)
        if re.search(pattern, text, re.IGNORECASE):
            return rail
    return None


async def _call_with_retry(client, *, model, messages, temperature, max_tokens, max_attempts=3):
    """Call LLM with exponential backoff retry."""
    last_exc = None
    for attempt in range(max_attempts):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            return response
        except Exception as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                base_delay = min(2 ** attempt, 30)
                jitter = random.uniform(0, base_delay * 0.5)
                logger.warning("LLM judge call failed (attempt %d/%d): %s", attempt + 1, max_attempts, exc)
                await asyncio.sleep(base_delay + jitter)
    raise last_exc


async def llm_judge(
    *,
    system_prompt: str,
    user_prompt: str,
    choices: Dict[str, float],
    config: Optional[JudgeConfig] = None,
) -> MetricResult:
    """Core LLM judge call.  All specific judges delegate here."""
    try:
        from openai import AsyncOpenAI
    except ImportError:
        raise ImportError(
            "The 'openai' package is required for LLM judge metrics. "
            "Install it with: pip install qym[judges]"
        )

    cfg = config or get_default_judge_config()
    cfg.validate()

    client = AsyncOpenAI(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        timeout=cfg.timeout,
    )

    try:
        response = await _call_with_retry(
            client,
            model=cfg.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
        )
        raw_text = response.choices[0].message.content or ""
    except Exception as exc:
        logger.warning("LLM judge call failed after retries: %s", exc)
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
        verdict = snap_to_rail(raw_text, list(choices.keys()))

    if verdict and verdict in choices:
        return MetricResult(
            score=choices[verdict],
            label=verdict,
            explanation=explanation,
            kind="llm",
        )

    # Case-insensitive match
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

    return MetricResult(
        score=0.0,
        kind="llm",
        metadata={"error": "Could not parse LLM verdict", "raw_response": raw_text},
    )


def _safe_substitute(template: str, subs: Dict[str, str]) -> str:
    """Replace {key} placeholders in template with values, escaping braces in values."""
    result = template
    for k, v in subs.items():
        # Escape any braces in the value to prevent accidental substitution
        safe_v = v.replace("{", "{{").replace("}", "}}")
        result = result.replace("{" + k + "}", safe_v)
    # Unescape double braces back to single
    result = result.replace("{{", "{").replace("}}", "}")
    return result


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
    from ``{output}``, ``{expected}``, ``{input}``, and any key from *input_data*.
    """
    # Validate score ranges
    for label, score in choices.items():
        if not (0.0 <= score <= 1.0):
            logger.warning(
                "Judge '%s': choice '%s' has score %.2f outside [0, 1] range. "
                "Scores should be between 0.0 and 1.0 for consistent metric behavior.",
                name, label, score,
            )

    sys_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    _cfg_overrides: Dict[str, Any] = {}
    if judge_model is not None:
        _cfg_overrides["model"] = judge_model
    if judge_base_url is not None:
        _cfg_overrides["base_url"] = judge_base_url
    if judge_api_key is not None:
        _cfg_overrides["api_key"] = judge_api_key

    async def _metric(output: Any, expected: Any = None, input_data: Any = None) -> MetricResult:
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
            try:
                tpl = _fetch_langfuse_prompt(langfuse_prompt)
            except Exception:
                logger.warning("Falling back to default prompt for judge '%s'", name)

        # Build substitution dict
        subs: Dict[str, str] = {
            "output": str(output) if output is not None else "",
            "expected": str(expected) if expected is not None else "",
            "input": str(input_data) if input_data is not None else "",
        }
        if isinstance(input_data, dict):
            for k, v in input_data.items():
                subs.setdefault(k, str(v) if v is not None else "")

        user_prompt = _safe_substitute(tpl, subs)

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
    from langfuse import Langfuse
    client = Langfuse()
    prompt_obj = client.get_prompt(prompt_name)
    return prompt_obj.prompt
