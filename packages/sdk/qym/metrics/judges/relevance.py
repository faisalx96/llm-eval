"""Relevance LLM judge — checks if a response is relevant to the question."""

from .base import create_judge

PROMPT = """\
Given the question and response below, determine if the response is relevant to the question.
A relevant response directly addresses the question and provides useful information. \
An irrelevant response is off-topic, does not address the question, or provides no useful information.

[Question]: {question}
[Response]: {output}

Is the response relevant or irrelevant to the question?"""


def relevance(*, judge_model=None, judge_base_url=None, judge_api_key=None):
    """Return a relevance judge metric."""
    return create_judge(
        name="relevance",
        prompt=PROMPT,
        choices={"relevant": 1.0, "irrelevant": 0.0},
        judge_model=judge_model,
        judge_base_url=judge_base_url,
        judge_api_key=judge_api_key,
    )


_default_metric = relevance()
