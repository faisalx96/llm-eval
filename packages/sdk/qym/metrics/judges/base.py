"""Core infrastructure for LLM-as-judge metrics."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
from typing import Any, Callable, Dict, List, Optional

from ..judge_config import JudgeConfig, get_default_judge_config
from ..result import MetricResult
from ._client import borrow_judge_client

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "You are an expert evaluation judge. Evaluate the content according to the "
    "criteria given by the user. Respond ONLY with a JSON object containing two "
    'keys: "verdict" (one of the allowed labels) and "explanation" (a brief '
    "justification for your verdict). Do not include any other text."
)


class JudgeInputError(ValueError):
    """Raised when a judge prompt references unavailable input fields."""

    DOCS_ROUTE = "/docs-guide#get-started/datasets/multiple-input-columns"

    @classmethod
    def docs_url(cls) -> str:
        """Return the platform mapping-docs URL from the process environment."""
        base_url = (os.getenv("QYM_BASE_URL") or "http://localhost:8000").rstrip("/")
        return f"{base_url}{cls.DOCS_ROUTE}"

    def __init__(
        self,
        *,
        judge_name: str,
        missing_fields: List[str],
        received: str,
    ) -> None:
        self.judge_name = judge_name
        self.missing_fields = list(missing_fields)
        self.received = received
        missing = ", ".join(self.missing_fields)
        super().__init__(
            f"Judge metric '{judge_name}' is missing required input field(s): "
            f"{missing}. Received input fields/type: {received}. "
            "Ensure the dataset input contains the required field names, or map "
            "dataset columns with Evaluator(input_mapping={"
            "'<dataset_column>': '<required_field>'}). "
            f"See {self.docs_url()}."
        )

    def rich_message(self) -> str:
        """Return a colored, actionable representation for Rich consoles."""
        missing = ", ".join(self.missing_fields)
        return (
            f"\n\n[red]Judge input error: {self.judge_name}[/red]\n"
            f"[yellow]Expected:[/yellow] {missing}\n"
            f"[cyan]Received:[/cyan] {self.received}\n"
            "Ensure the dataset input contains the required field names, or use "
            "Evaluator(input_mapping={"
            "'<dataset_column>': '<required_field>'}).\n"
            f"Docs: [link={self.docs_url()}]"
            "Task with Multiple CSV Input Columns[/link]"
        )


def snap_to_rail(text: str, rails: List[str]) -> Optional[str]:
    """Fuzzy label extraction from free text using word boundary matching.

    Case-insensitive.  Longest rail first to avoid partial matches
    (e.g. ``"non-toxic"`` before ``"toxic"``).
    """
    sorted_rails = sorted(rails, key=len, reverse=True)
    for rail in sorted_rails:
        # Use word boundary for single words, substring for multi-word/hyphenated
        pattern = (
            r"\b" + re.escape(rail) + r"\b"
            if " " not in rail and "-" not in rail
            else re.escape(rail)
        )
        if re.search(pattern, text, re.IGNORECASE):
            return rail
    return None


async def _call_with_retry(
    client,
    *,
    model,
    messages,
    temperature,
    max_tokens,
    max_attempts=3,
    timeout: Optional[float] = None,
):
    """Call LLM with exponential backoff retry and a true wall-clock timeout.

    The ``timeout`` parameter is a hard wall-clock cap on each attempt, enforced via
    ``asyncio.wait_for``. This is essential because httpx's own ``timeout`` kwarg is
    a per-read timeout — slow-streaming providers (e.g. some OpenRouter upstreams)
    can keep a connection alive indefinitely by sending trickled chunks just inside
    the per-read window, which has caused 30+ minute hangs in practice.

    ``asyncio.wait_for`` cancels the inner task on timeout, which propagates through
    httpx's async transport and actually closes the underlying socket — the only
    reliable cancellation primitive Python gives us for this use case.
    """
    last_exc = None
    for attempt in range(max_attempts):
        try:
            create_coro = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            if timeout is not None:
                response = await asyncio.wait_for(create_coro, timeout=timeout)
            else:
                response = await create_coro
            return response
        except asyncio.TimeoutError as exc:
            # wall-clock cap hit; retriable
            last_exc = exc
            if attempt < max_attempts - 1:
                base_delay = min(2**attempt, 30)
                jitter = random.uniform(0, base_delay * 0.5)
                logger.warning(
                    "LLM judge call timed out after %.1fs (attempt %d/%d)",
                    timeout if timeout is not None else -1,
                    attempt + 1,
                    max_attempts,
                )
                await asyncio.sleep(base_delay + jitter)
        except Exception as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                base_delay = min(2**attempt, 30)
                jitter = random.uniform(0, base_delay * 0.5)
                logger.warning(
                    "LLM judge call failed (attempt %d/%d): %s",
                    attempt + 1,
                    max_attempts,
                    exc,
                )
                await asyncio.sleep(base_delay + jitter)
    raise last_exc


def _parse_verdict(raw_text: str, choices: Dict[str, float]):
    """Try to extract verdict and explanation from LLM response.

    Returns (verdict, explanation) where verdict is a key from choices,
    or (None, None) if parsing fails.
    """
    verdict: Optional[str] = None
    explanation: Optional[str] = None

    try:
        parsed = json.loads(raw_text)
        verdict = parsed.get("verdict")
        explanation = parsed.get("explanation")
    except (json.JSONDecodeError, TypeError):
        return None, None

    if not verdict:
        return None, explanation

    # Exact match
    if verdict in choices:
        return verdict, explanation

    # Case-insensitive match
    for key in choices:
        if key.lower() == verdict.lower():
            return key, explanation

    return None, explanation


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
            "Install it with: pip install openai"
        )

    cfg = config or get_default_judge_config()
    cfg.validate()

    async with borrow_judge_client(cfg) as client:
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
                timeout=cfg.timeout,
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
        verdict, explanation = _parse_verdict(raw_text, choices)

        if verdict is None:
            # JSON parse failed — retry once with a stricter nudge
            labels = ", ".join(f'"{k}"' for k in choices)
            try:
                retry_response = await _call_with_retry(
                    client,
                    model=cfg.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                        {"role": "assistant", "content": raw_text},
                        {
                            "role": "user",
                            "content": f'Your response was not valid JSON. Respond with ONLY a JSON object: {{"verdict": one of [{labels}], "explanation": "your reasoning"}}',
                        },
                    ],
                    temperature=cfg.temperature,
                    max_tokens=cfg.max_tokens,
                    max_attempts=1,
                    timeout=cfg.timeout,
                )
                retry_text = retry_response.choices[0].message.content or ""
                verdict, explanation = _parse_verdict(retry_text, choices)
            except Exception:
                pass  # Fall through to snap_to_rail

        if verdict is None:
            # Last resort: snap_to_rail on original raw text
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

        return MetricResult(
            score=choices[verdict],
            label=verdict,
            explanation=explanation,
            kind="llm",
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


def _required_prompt_fields(template: str) -> set[str]:
    """Return simple ``{field}`` placeholders referenced by a judge prompt.

    This deliberately mirrors the placeholder syntax supported by
    :func:`_safe_substitute`. Double-braced literals such as ``{{field}}`` are
    ignored.
    """
    return set(re.findall(r"(?<!\{)\{([A-Za-z_][A-Za-z0-9_]*)\}(?!\})", template))


def _validate_prompt_inputs(
    *,
    judge_name: str,
    template: str,
    substitutions: Dict[str, str],
    input_data: Any,
) -> None:
    """Raise an actionable error when a judge prompt cannot be rendered."""
    available_fields = {key for key in substitutions if isinstance(key, str)}
    missing_fields = sorted(_required_prompt_fields(template) - available_fields)
    if not missing_fields:
        return

    if isinstance(input_data, dict):
        received_fields = sorted(str(key) for key in input_data)
        received = ", ".join(received_fields) if received_fields else "<empty dict>"
    else:
        received = f"<{type(input_data).__name__}>"

    raise JudgeInputError(
        judge_name=judge_name,
        missing_fields=missing_fields,
        received=received,
    )


def _named_prompt_inputs(
    input_data: Any,
    input_fields: Dict[str, Any],
) -> Dict[str, Any]:
    """Collect dataset input aliases passed by the evaluator."""
    named: Dict[str, Any] = {}
    if isinstance(input_data, dict):
        named.update(input_data)
    for key, value in input_fields.items():
        if key not in {"task_metadata", "metadata", "item_metadata"}:
            named.setdefault(key, value)
    return named


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
                name,
                label,
                score,
            )

    sys_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    _cfg_overrides: Dict[str, Any] = {}
    if judge_model is not None:
        _cfg_overrides["model"] = judge_model
    if judge_base_url is not None:
        _cfg_overrides["base_url"] = judge_base_url
    if judge_api_key is not None:
        _cfg_overrides["api_key"] = judge_api_key

    async def _metric(
        output: Any,
        expected: Any = None,
        input_data: Any = None,
        **input_fields: Any,
    ) -> MetricResult:
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
        named_inputs = _named_prompt_inputs(input_data, input_fields)
        for k, v in named_inputs.items():
            subs.setdefault(k, str(v) if v is not None else "")

        _validate_prompt_inputs(
            judge_name=name,
            template=tpl,
            substitutions=subs,
            input_data=named_inputs or input_data,
        )
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


def create_pairwise_judge(
    name: str,
    prompt: str,
    *,
    system_prompt: Optional[str] = None,
    judge_model: Optional[str] = None,
    judge_base_url: Optional[str] = None,
    judge_api_key: Optional[str] = None,
) -> Callable:
    """Pairwise comparison judge factory.

    Instead of scoring a single output, compares two outputs (A vs B) and
    returns which is better. More reliable than absolute scoring per research.

    The *prompt* template uses ``{variable}`` syntax. In addition to the
    standard variables (``{expected}``, ``{input}``, and any key from
    *input_data*), two special variables are available:

    * ``{output_a}`` — the first output (from the item being evaluated)
    * ``{output_b}`` — the second output (from ``expected`` or ``input_data["output_b"]``)

    The judge is asked to return ``{"verdict": "A"|"B"|"tie", "explanation": "..."}``.

    Returns a metric function with signature
    ``(output, expected, input_data) -> MetricResult`` where:
    - score 1.0 = A wins, 0.5 = tie, 0.0 = B wins
    - label = "A", "B", or "tie"
    """
    PAIRWISE_SYSTEM = system_prompt or (
        "You are an expert evaluation judge. You will be shown two responses (A and B) "
        "to the same question. Compare them according to the criteria given by the user. "
        "Respond ONLY with a JSON object containing two keys: "
        '"verdict" (one of "A", "B", or "tie") and "explanation" '
        "(a brief justification for your choice). Do not include any other text."
    )

    pairwise_choices = {"A": 1.0, "B": 0.0, "tie": 0.5}

    _cfg_overrides: Dict[str, Any] = {}
    if judge_model is not None:
        _cfg_overrides["model"] = judge_model
    if judge_base_url is not None:
        _cfg_overrides["base_url"] = judge_base_url
    if judge_api_key is not None:
        _cfg_overrides["api_key"] = judge_api_key

    async def _metric(
        output: Any,
        expected: Any = None,
        input_data: Any = None,
        **input_fields: Any,
    ) -> MetricResult:
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

        named_inputs = _named_prompt_inputs(input_data, input_fields)

        # Resolve output_b from either its original or mapped input name.
        output_b = named_inputs.get("output_b")
        if output_b is None:
            output_b = expected

        # Build substitution dict
        subs: Dict[str, str] = {
            "output_a": str(output) if output is not None else "",
            "output_b": str(output_b) if output_b is not None else "",
            "expected": str(expected) if expected is not None else "",
            "input": str(input_data) if input_data is not None else "",
        }
        for k, v in named_inputs.items():
            subs.setdefault(k, str(v) if v is not None else "")

        _validate_prompt_inputs(
            judge_name=name,
            template=prompt,
            substitutions=subs,
            input_data=named_inputs or input_data,
        )
        user_prompt = _safe_substitute(prompt, subs)

        return await llm_judge(
            system_prompt=PAIRWISE_SYSTEM,
            user_prompt=user_prompt,
            choices=pairwise_choices,
            config=cfg,
        )

    _metric.__name__ = name
    _metric.__qualname__ = name
    return _metric


def _fetch_langfuse_prompt(prompt_name: str) -> str:
    """Langfuse prompt fetching has been removed from qym runtime dependencies."""
    raise RuntimeError(
        "Langfuse prompt fetching is no longer available in qym. "
        f"Inline the prompt template or load '{prompt_name}' before creating the judge."
    )
