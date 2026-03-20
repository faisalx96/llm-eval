"""Hallucination LLM judge — checks if a response is grounded or contains hallucinated content."""

from .base import create_judge

PROMPT = """\
Given the context and response below, determine if the response is grounded in the context or contains hallucinations.
A grounded response only states facts that are present in or directly inferable from the context. \
A hallucinated response introduces facts, claims, or details that are not supported by the context.

[Context]: {context}
[Response]: {output}

Is the response grounded or hallucinated?"""


def hallucination(*, judge_model=None, judge_base_url=None, judge_api_key=None):
    """Return a hallucination judge metric."""
    return create_judge(
        name="hallucination",
        prompt=PROMPT,
        choices={"grounded": 1.0, "hallucinated": 0.0},
        judge_model=judge_model,
        judge_base_url=judge_base_url,
        judge_api_key=judge_api_key,
    )


_default_metric = hallucination()
