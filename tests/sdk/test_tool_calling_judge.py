"""EI-2 — tool_calling judge must evaluate the model OUTPUT, not the dataset input.

Previously the prompt's '[Tool Calls Made]' section was filled from the dataset
input's ``tool_calls`` key, so the verdict was independent of the system under
test. These tests assert the rendered prompt is built from the ``output``
argument. The LLM client is mocked (same pattern as tests/sdk/test_judges.py);
no real LLM calls are made.
"""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from qym.metrics.judges.tool_calling import PROMPT, tool_calling

_JUDGE_KW = {"judge_model": "test-judge-model", "judge_api_key": "test-judge-key"}

# Dataset input: identical for every call. Includes a 'tool_calls' key (as a
# real dataset input row would) carrying a sentinel that must NOT leak into
# the rendered prompt.
INPUT_TOOL_CALLS_SENTINEL = "INPUT_TOOL_CALLS_SENTINEL_DO_NOT_RENDER"
INPUT_DATA = {
    "question": "What is the weather in Paris?",
    "tool_definitions": '[{"name": "get_weather", "parameters": {"city": "string"}}]',
    "tool_calls": INPUT_TOOL_CALLS_SENTINEL,
}

OUTPUT_CORRECT = '[{"name": "get_weather", "arguments": {"city": "Paris"}}]'
OUTPUT_WRONG_TOOL = '[{"name": "send_email", "arguments": {"to": "paris@example.com"}}]'


def _make_mock_client(response_content: str):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=response_content))]
    mock_client = AsyncMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    return mock_client


async def _rendered_prompt_for(output: str) -> str:
    """Run the judge with a mocked LLM and return the rendered user prompt."""
    content = json.dumps({"verdict": "correct", "explanation": "ok"})
    mock_client = _make_mock_client(content)
    with patch("openai.AsyncOpenAI", new=lambda **kw: mock_client):
        judge = tool_calling(**_JUDGE_KW)
        await judge(output, None, dict(INPUT_DATA))
    call_args = mock_client.chat.completions.create.call_args
    return call_args.kwargs["messages"][1]["content"]


class TestPromptTemplate:
    def test_template_uses_output_placeholder(self):
        assert "{output}" in PROMPT

    def test_template_does_not_use_input_tool_calls_placeholder(self):
        assert "{tool_calls}" not in PROMPT

    def test_template_keeps_input_fields(self):
        assert "{question}" in PROMPT
        assert "{tool_definitions}" in PROMPT


class TestToolCallingJudgePrompt:
    @pytest.mark.asyncio
    async def test_prompt_contains_model_output_not_input_tool_calls(self):
        prompt = await _rendered_prompt_for(OUTPUT_CORRECT)
        assert OUTPUT_CORRECT in prompt
        assert INPUT_TOOL_CALLS_SENTINEL not in prompt

    @pytest.mark.asyncio
    async def test_different_outputs_produce_different_prompts(self):
        """Identical input, two different outputs => different rendered prompts."""
        prompt_correct = await _rendered_prompt_for(OUTPUT_CORRECT)
        prompt_wrong = await _rendered_prompt_for(OUTPUT_WRONG_TOOL)

        assert prompt_correct != prompt_wrong
        assert OUTPUT_CORRECT in prompt_correct
        assert OUTPUT_WRONG_TOOL in prompt_wrong
        # Neither prompt should contain the dataset input's tool_calls value
        assert INPUT_TOOL_CALLS_SENTINEL not in prompt_correct
        assert INPUT_TOOL_CALLS_SENTINEL not in prompt_wrong

    @pytest.mark.asyncio
    async def test_question_and_tool_definitions_come_from_input(self):
        prompt = await _rendered_prompt_for(OUTPUT_CORRECT)
        assert INPUT_DATA["question"] in prompt
        assert INPUT_DATA["tool_definitions"] in prompt

    @pytest.mark.asyncio
    async def test_output_lands_in_tool_calls_made_slot(self):
        prompt = await _rendered_prompt_for(OUTPUT_CORRECT)
        assert f"[Tool Calls Made]: {OUTPUT_CORRECT}" in prompt

    @pytest.mark.asyncio
    async def test_judge_returns_metric_result(self):
        content = json.dumps({"verdict": "incorrect", "explanation": "wrong tool"})
        mock_client = _make_mock_client(content)
        with patch("openai.AsyncOpenAI", new=lambda **kw: mock_client):
            judge = tool_calling(**_JUDGE_KW)
            result = await judge(OUTPUT_WRONG_TOOL, None, dict(INPUT_DATA))
        assert result.score == 0.0
        assert result.label == "incorrect"
        assert result.kind == "llm"
