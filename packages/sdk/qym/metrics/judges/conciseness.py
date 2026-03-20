"""Conciseness LLM judge — checks if a response is concise and not unnecessarily verbose."""

from .base import create_judge

PROMPT = """\
Given the question and response below, determine if the response is concise.
A concise response directly answers the question without unnecessary repetition, filler, or irrelevant detail. \
A verbose response contains excessive explanation, redundant information, or padding that does not add value.

[Question]: {question}
[Response]: {output}

Is the response concise or verbose?"""


def conciseness(*, judge_model=None, judge_base_url=None, judge_api_key=None):
    """Return a conciseness judge metric."""
    return create_judge(
        name="conciseness",
        prompt=PROMPT,
        choices={"concise": 1.0, "verbose": 0.0},
        judge_model=judge_model,
        judge_base_url=judge_base_url,
        judge_api_key=judge_api_key,
    )


_default_metric = conciseness()
