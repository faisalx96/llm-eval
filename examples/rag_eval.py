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
from openai import AsyncOpenAI

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


def main():
    evaluator = Evaluator(
        task=rag_qa_task,
        dataset="ragbench-100",
        metrics=["correctness", "faithfulness"],  # Use metrics by name from registry
        model=["openai/gpt-oss-120b", "meta-llama/llama-4-maverick", "qwen/qwen3-235b-a22b-2507"],
        # model=["qwen/qwen3-235b-a22b-2507"]*2,
        # model=[ "qwen/qwen3-235b-a22b-2507",  "qwen/qwen3-235b-a22b-2507"],
        config={
            # "resume_from": "/Users/faisalbh/qym/qym_results/ragbench/gpt-oss-120b/2026-01-28/ragbench-ragbench-100-gpt-oss-120b-260128-1140.csv", 
            "max_concurrency": 5,
            "run_name": "ragbench",
        }
    )

    results = evaluator.run()


if __name__ == "__main__":
    main()
