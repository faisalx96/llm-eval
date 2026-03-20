"""Pre-built LLM-as-judge evaluators.

Each judge returns a :class:`~qym.metrics.result.MetricResult` with score,
label, and explanation.  They all use ``response_format={"type": "json_object"}``
with OpenAI-compatible APIs (including vLLM).
"""

from .base import create_judge, llm_judge, snap_to_rail
from .faithfulness import faithfulness_llm
from .relevance import relevance
from .toxicity import toxicity
from .correctness_llm import correctness_llm
from .conciseness import conciseness
from .hallucination import hallucination
from .tool_calling import tool_calling

__all__ = [
    "create_judge",
    "llm_judge",
    "snap_to_rail",
    "faithfulness_llm",
    "relevance",
    "toxicity",
    "correctness_llm",
    "conciseness",
    "hallucination",
    "tool_calling",
]
