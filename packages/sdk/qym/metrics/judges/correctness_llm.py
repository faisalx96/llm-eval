"""Correctness LLM judge — checks if a response matches the expected output."""

from .base import create_judge

PROMPT = """\
Given the question, expected answer, and actual response below, determine if the response is correct.
A correct response conveys the same information or meaning as the expected answer, even if worded differently. \
An incorrect response contradicts, omits key information from, or is substantially different from the expected answer.

[Question]: {question}
[Expected Answer]: {expected}
[Actual Response]: {output}

Is the actual response correct or incorrect compared to the expected answer?"""


def correctness_llm(*, judge_model=None, judge_base_url=None, judge_api_key=None):
    """Return a correctness judge metric."""
    return create_judge(
        name="correctness_llm",
        prompt=PROMPT,
        choices={"correct": 1.0, "incorrect": 0.0},
        judge_model=judge_model,
        judge_base_url=judge_base_url,
        judge_api_key=judge_api_key,
    )


_default_metric = correctness_llm()
