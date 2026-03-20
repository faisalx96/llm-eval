"""Faithfulness LLM judge — checks if a response is grounded in the provided context."""

from .base import create_judge

PROMPT = """\
Given the context and response below, determine if the response is faithful to the context.
A faithful response only contains information that is supported by or directly inferable from the context. \
If the response introduces claims not present in the context, it is unfaithful.

[Context]: {context}
[Question]: {question}
[Response]: {output}

Is the response faithful or unfaithful to the context?"""


def faithfulness_llm(*, judge_model=None, judge_base_url=None, judge_api_key=None):
    """Return a faithfulness judge metric."""
    return create_judge(
        name="faithfulness_llm",
        prompt=PROMPT,
        choices={"faithful": 1.0, "unfaithful": 0.0},
        judge_model=judge_model,
        judge_base_url=judge_base_url,
        judge_api_key=judge_api_key,
    )
