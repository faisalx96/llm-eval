"""
Text-to-SQL Task for evaluation.

This module defines the task function that takes a natural language question
and database schema, and returns a SQL query using an LLM.
"""

import os
from typing import Optional
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

# Initialize OpenRouter client
client = AsyncOpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

SYSTEM_PROMPT = """You are a SQL expert. Given a natural language question and database schema, generate the SQL query that answers the question.

Instructions:
- Output ONLY the SQL query, nothing else
- Do not include any explanation or markdown formatting
- Use the exact table and column names from the schema
- The query should be valid SQL"""


async def text2sql_task(
    question: str,
    schema: str,
    model_name: Optional[str] = None,
    trace_id: Optional[str] = None
) -> str:
    """
    Text-to-SQL task.

    Args:
        question: Natural language question
        schema: SQL CREATE TABLE statements defining the database schema
        model_name: The model to use (automatically passed by Evaluator)
        trace_id: Langfuse trace ID (automatically passed by Evaluator)

    Returns:
        Generated SQL query
    """
    model = model_name or "openai/gpt-4o-mini"

    user_message = f"""Schema:
{schema}

Question: {question}

SQL:"""

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ],
        temperature=0.0,
        max_tokens=512
    )

    return response.choices[0].message.content.strip()
