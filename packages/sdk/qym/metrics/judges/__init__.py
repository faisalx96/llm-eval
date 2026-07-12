"""Pre-built LLM-as-judge evaluators.

Each judge returns a :class:`~qym.metrics.result.MetricResult` with score,
label, and explanation.  They all use ``response_format={"type": "json_object"}``
with OpenAI-compatible APIs (including vLLM).
"""

from .base import (
    JudgeInputError,
    create_judge,
    create_pairwise_judge,
    llm_judge,
    snap_to_rail,
)
from .faithfulness import faithfulness_llm
from .relevance import relevance
from .toxicity import toxicity
from .correctness_llm import correctness_llm
from .conciseness import conciseness
from .hallucination import hallucination
from .tool_calling import tool_calling

# Registry-compatible dict of default judge metric instances
judge_metrics = {
    "relevance": relevance(),
    "faithfulness_llm": faithfulness_llm(),
    "correctness_llm": correctness_llm(),
    "conciseness": conciseness(),
    "hallucination": hallucination(),
    "toxicity": toxicity(),
    "tool_calling": tool_calling(),
}

__all__ = [
    "create_judge",
    "create_pairwise_judge",
    "JudgeInputError",
    "llm_judge",
    "snap_to_rail",
    "judge_metrics",
    "faithfulness_llm",
    "relevance",
    "toxicity",
    "correctness_llm",
    "conciseness",
    "hallucination",
    "tool_calling",
]
