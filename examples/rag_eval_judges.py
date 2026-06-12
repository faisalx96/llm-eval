"""RAG evaluation with built-in LLM judges.

Evaluates a small, self-contained RAG-style dataset (question + context)
using qym's built-in LLM-as-judge metrics plus a custom judge built with
``create_judge``. Judges return structured results with score, label, and
explanation columns.

Requirements (this example calls a real LLM):
    pip install openai

    # Answer model — an OpenAI-compatible endpoint:
    export OPENROUTER_API_KEY=...   # or OPENAI_API_KEY

    # Judge model — configured via env vars (defaults to OPENAI_API_KEY):
    export QYM_JUDGE_MODEL=gpt-4o-mini
    export QYM_JUDGE_API_KEY=...            # falls back to OPENAI_API_KEY
    export QYM_JUDGE_BASE_URL=...           # optional: vLLM / Ollama / OpenRouter

Usage:
    python examples/rag_eval_judges.py

Without an API key the script prints a skip message and exits cleanly.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from qym import Evaluator, InMemoryDataset
from qym.metrics.judges import create_judge

SYSTEM_PROMPT = """You are a helpful assistant that answers questions based on the provided context.

Instructions:
- Answer the question using ONLY the information provided in the context
- If the context doesn't contain enough information to answer, say so
- Be concise and direct in your answers
- Do not make up information that is not in the context"""

# ---------------------------------------------------------------------------
# Dataset: small in-memory RAG samples (question + retrieved context)
# ---------------------------------------------------------------------------

DATASET = InMemoryDataset(
    [
        {
            "input": {
                "question": "What is the capital of France?",
                "context": "France is a country in Western Europe. Its capital and largest city is Paris.",
            },
            "expected_output": "Paris",
        },
        {
            "input": {
                "question": "When was the Eiffel Tower completed?",
                "context": "The Eiffel Tower was completed in 1889 as the entrance arch to the World's Fair.",
            },
            "expected_output": "1889",
        },
        {
            "input": {
                "question": "Who designed the Sydney Opera House?",
                "context": "The Sydney Opera House was designed by Danish architect Jorn Utzon and opened in 1973.",
            },
            "expected_output": "Jorn Utzon",
        },
    ],
    name="rag-judges-demo",
)


# ---------------------------------------------------------------------------
# Task: RAG question answering. ``question`` and ``context`` are unpacked
# from the dataset item's input dict; ``model_name`` is injected by qym.
# ---------------------------------------------------------------------------

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import AsyncOpenAI

        if os.getenv("OPENROUTER_API_KEY"):
            _client = AsyncOpenAI(
                api_key=os.environ["OPENROUTER_API_KEY"],
                base_url="https://openrouter.ai/api/v1",
            )
        else:
            _client = AsyncOpenAI()  # uses OPENAI_API_KEY / OPENAI_BASE_URL
    return _client


async def rag_qa_task(
    question: str,
    context: str,
    model_name: Optional[str] = None,
) -> str:
    """RAG QA task — generates an answer from context using an LLM."""
    model = model_name or "openai/gpt-4o-mini"
    response = await _get_client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}\n\nAnswer:"},
        ],
        temperature=0.0,
        max_tokens=256,
    )
    return (response.choices[0].message.content or "").strip()


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

# Built-in judges can be used by string name ("faithfulness_llm",
# "correctness_llm") — they read their model/endpoint from QYM_JUDGE_* env
# vars. ``create_judge`` builds a custom judge from a prompt + verdict labels:
completeness_judge = create_judge(
    name="completeness",
    prompt="""\
Given the question, expected answer, and actual response, determine if the
response covers all the key points from the expected answer.

[Question]: {question}
[Expected Answer]: {expected}
[Actual Response]: {output}

Is the response complete or incomplete?""",
    choices={"complete": 1.0, "incomplete": 0.0},
)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def main() -> None:
    if not (os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")):
        print(
            "[skip] rag_eval_judges.py needs an LLM API key.\n"
            "       Set OPENROUTER_API_KEY (or OPENAI_API_KEY) for the answer model\n"
            "       and QYM_JUDGE_MODEL / QYM_JUDGE_API_KEY for the judges, then re-run."
        )
        sys.exit(0)

    model = "openai/gpt-4o-mini" if os.getenv("OPENROUTER_API_KEY") else "gpt-4o-mini"

    evaluator = Evaluator(
        task=rag_qa_task,
        dataset=DATASET,
        metrics=[
            "correctness",        # built-in code metric (token F1)
            "faithfulness_llm",   # built-in LLM judge (by string name)
            "correctness_llm",    # built-in LLM judge (by string name)
            completeness_judge,   # custom LLM judge defined above
        ],
        model=[model],
        config={
            "max_concurrency": 3,
            "run_name": "rag-judges-demo",
        },
    )

    evaluator.run(auto_save=False)

    # Judge metrics produce structured outputs: the saved results include
    # columns like faithfulness_llm_score / _label / _explanation.


if __name__ == "__main__":
    main()
