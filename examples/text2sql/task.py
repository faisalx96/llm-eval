"""Text-to-SQL Task for evaluation.

This module defines the task function that takes a natural language question
and database schema, and returns a SQL query using an LLM.
"""

import os
from typing import Optional

SYSTEM_PROMPT = """You are a SQL expert. Given a natural language question and database schema, generate the SQL query that answers the question.

Instructions:
- Output ONLY the SQL query, nothing else
- Do not include any explanation or markdown formatting
- Use the exact table and column names from the schema
- The query should be valid SQL"""

_client = None


def _get_client():
    """Create the OpenRouter (OpenAI-compatible) client lazily.

    Built on first use so importing this module never requires an API key.
    """
    global _client
    if _client is None:
        from openai import AsyncOpenAI

        _client = AsyncOpenAI(
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url="https://openrouter.ai/api/v1",
        )
    return _client


async def text2sql_task(
    question: str,
    schema: str,
    model_name: Optional[str] = None,
) -> str:
    """Text-to-SQL task.

    ``question`` and ``schema`` are unpacked from the dataset item's input
    dict by qym's argument resolution; ``model_name`` is injected from the
    Evaluator's ``model=`` argument.

    Returns:
        Generated SQL query
    """
    model = model_name or "openai/gpt-4o-mini"

    user_message = f"""Schema:
{schema}

Question: {question}

SQL:"""

    response = await _get_client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.0,
        max_tokens=512,
    )

    return (response.choices[0].message.content or "").strip()
