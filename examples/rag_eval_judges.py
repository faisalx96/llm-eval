"""
RAG Evaluation with Built-in LLM Judges.

This example shows how to evaluate a RAG pipeline using qym's built-in
LLM-as-judge metrics.  Compare with rag_eval.py — the hand-rolled
llm_judge() function there is replaced by pre-built judges that return
structured MetricResult objects with score, label, and explanation.

Usage:
    # Upload the dataset first (see rag_eval.py)
    python upload_dataset.py

    # Run with built-in judges (uses OPENAI_API_KEY by default)
    python rag_eval_judges.py

    # Or point judges at a local vLLM / Ollama server
    QYM_JUDGE_BASE_URL=http://localhost:8080/v1 \
    QYM_JUDGE_MODEL=my-model \
    QYM_JUDGE_API_KEY=dummy \
    python rag_eval_judges.py
"""

import os
from dotenv import load_dotenv
from typing import Optional

from openai import AsyncOpenAI

from qym import Evaluator
from qym.metrics.judges import create_judge

load_dotenv()


# ---------------------------------------------------------------------------
# Task: RAG Question Answering (same as rag_eval.py)
# ---------------------------------------------------------------------------

client = AsyncOpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
)

SYSTEM_PROMPT = """You are a helpful assistant that answers questions based on the provided context.

Instructions:
- Answer the question using ONLY the information provided in the context
- If the context doesn't contain enough information to answer, say so
- Be concise and direct in your answers
- Do not make up information that is not in the context"""


async def rag_qa_task(
    question: str,
    context: str,
    model_name: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> str:
    """RAG QA task — generates an answer from context using an LLM."""
    model = model_name or "openai/gpt-4o-mini"

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}\n\nAnswer:"},
        ],
        temperature=0.0,
        max_tokens=512,
    )
    return response.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

# Built-in judges can be used by string name (like "faithfulness_llm") or by
# calling the factory function.  Strings are simpler; factories let you
# customize the model/endpoint per-metric:
#
#   from qym.metrics.judges import faithfulness_llm
#   faithfulness_llm(judge_model="my-model", judge_base_url="http://localhost:8080/v1")

# Custom judge — define your own prompt + verdict labels:
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

def main():
    evaluator = Evaluator(
        task=rag_qa_task,
        dataset="ragbench-100",
        metrics=[
            # Built-in code metric
            "correctness",

            # Built-in LLM judges (by string name — config via env vars)
            "faithfulness_llm",
            "correctness_llm",

            # Custom LLM judge defined above
            completeness_judge,
        ],
        model=["openai/gpt-4o-mini"],
        config={
            "max_concurrency": 10,
            "run_name": "ragbench-judges",
        },
    )

    results = evaluator.run()

    # The results now include label and explanation for each judge metric.
    # Check the CSV output — you'll see columns like:
    #   faithfulness_llm_score, faithfulness_llm_label, faithfulness_llm_explanation
    #   relevance_score, relevance_label, relevance_explanation
    #   correctness_llm_score, correctness_llm_label, correctness_llm_explanation
    #   completeness_score, completeness_label, completeness_explanation


if __name__ == "__main__":
    main()
