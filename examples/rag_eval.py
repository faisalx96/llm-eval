"""
Run RAGBench Evaluation.

This script runs the evaluation using:
- Dataset: ragbench-100 (uploaded to Langfuse)
- Task: RAG QA using OpenAI
- Metrics:
  1. Correctness (F1 Score): Is the answer correct?
  2. Faithfulness (HHEM): Is the answer grounded in context?

Usage:
    # First, upload the dataset
    python upload_dataset.py

    # Then run the evaluation
    python run_eval.py
"""
import os
from dotenv import load_dotenv
from qym import Evaluator
from typing import Optional
from openai import AsyncOpenAI, OpenAI

load_dotenv()



# Initialize OpenRouter client (OpenAI-compatible API)
client = AsyncOpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

# System prompt for RAG QA
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
    trace_id: Optional[str] = None
) -> str:
    """
    RAG Question Answering task.

    This function takes a question and context documents, and uses an LLM
    to generate an answer based on the provided context.

    Args:
        question: The user's question
        context: The retrieved context documents (joined as text)
        model_name: The model to use (automatically passed by Evaluator)
        trace_id: Langfuse trace ID (automatically passed by Evaluator)

    Returns:
        The generated answer
    """
    # Default model if not specified (OpenRouter model format)
    model = model_name or "openai/gpt-4o-mini"

    # Create the user message with context and question
    user_message = f"""Context:
{context}

Question: {question}

Answer:"""

    # Call the LLM
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ],
        temperature=0.0,  # Deterministic for evaluation
        max_tokens=512
    )

    return response.choices[0].message.content.strip()


judge_client = AsyncOpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

async def llm_judge(output, expected, input_data):
    """LLM-as-judge metric: scores answer quality on a 0-1 scale."""
    question = input_data.get("question", "") if isinstance(input_data, dict) else str(input_data)
    context = input_data.get("context", "") if isinstance(input_data, dict) else ""

    prompt = f"""You are an expert evaluator for a RAG system. Score the answer on a scale of 0 to 1.

Question: {question}
Context: {context}
Expected Answer: {expected}
Actual Answer: {output}

Evaluate based on:
1. Correctness: Does the answer match the expected answer in meaning?
2. Completeness: Does it cover all key points?
3. Faithfulness: Is it grounded in the provided context?

Respond with ONLY a JSON object: {{"score": <float 0-1>, "reason": "<brief explanation>"}}"""

    response = await judge_client.chat.completions.create(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=150,
    )

    import json
    try:
        result = json.loads(response.choices[0].message.content.strip())
        return {"score": float(result["score"]), "metadata": {"reason": result.get("reason", "")}}
    except (json.JSONDecodeError, KeyError, ValueError):
        return {"score": 0.5, "metadata": {"reason": "Failed to parse judge response"}}


def main():
    evaluator = Evaluator(
        task=rag_qa_task,
        dataset="ragbench-100",
        metrics=["correctness", "faithfulness", llm_judge],
        model=["qwen/qwen3-coder-next"], #["z-ai/glm-5", "anthropic/claude-opus-4.6", "qwen/qwen3.5-397b-a17b", "google/gemini-3.1-pro-preview", "anthropic/claude-sonnet-4.6"],
        # model=["qwen/qwen3-235b-a22b-2507"]*2,
        # model=[ "qwen/qwen3-235b-a22b-2507",  "qwen/qwen3-235b-a22b-2507"],
        config={
            # "resume_from": "/Users/faisalbh/qym/qym_results/rag_qa_task/gpt-oss-120b/2026-01-28/ragbench-rag_qa_task-ragbench-100-gpt-oss-120b-260128-1140.csv",
            "max_concurrency": 10,
            "run_name": "ragbench",
        }
    )

    results = evaluator.run()


if __name__ == "__main__":
    main()
