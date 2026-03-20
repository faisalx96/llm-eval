"""Tool calling LLM judge — checks if tool calls are correct given a question and tool definitions."""

from .base import create_judge

PROMPT = """\
Given the question, available tool definitions, and the actual tool calls made, determine if the tool calls are correct.
Correct tool calls use the right tool(s) with appropriate arguments to answer the question. \
Incorrect tool calls use the wrong tool, pass wrong arguments, or fail to call a necessary tool.

[Question]: {question}
[Tool Definitions]: {tool_definitions}
[Tool Calls Made]: {tool_calls}

Are the tool calls correct or incorrect?"""


def tool_calling(*, judge_model=None, judge_base_url=None, judge_api_key=None):
    """Return a tool calling judge metric."""
    return create_judge(
        name="tool_calling",
        prompt=PROMPT,
        choices={"correct": 1.0, "incorrect": 0.0},
        judge_model=judge_model,
        judge_base_url=judge_base_url,
        judge_api_key=judge_api_key,
    )
