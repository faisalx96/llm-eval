"""Tests for LLM judge infrastructure — mock AsyncOpenAI, test judges, JudgeConfig, create_judge."""

import json
import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure openai mock is available for the judge imports
_mock_openai = MagicMock()
_mock_openai.__path__ = []
_mock_openai.AsyncOpenAI = MagicMock  # placeholder — overridden per test
sys.modules.setdefault("openai", _mock_openai)

from qym.metrics.result import MetricResult
from qym.metrics.judge_config import JudgeConfig, get_default_judge_config, set_default_judge_config
from qym.metrics.judges.base import (
    JudgeInputError,
    create_judge,
    create_pairwise_judge,
    snap_to_rail,
)


# ---------------------------------------------------------------------------
# snap_to_rail
# ---------------------------------------------------------------------------


class TestSnapToRail:
    def test_exact_match(self):
        assert snap_to_rail("faithful", ["faithful", "unfaithful"]) == "faithful"

    def test_case_insensitive(self):
        assert snap_to_rail("FAITHFUL", ["faithful", "unfaithful"]) == "faithful"

    def test_substring_match(self):
        assert snap_to_rail("the answer is faithful to the context", ["faithful", "unfaithful"]) == "faithful"

    def test_longest_first(self):
        # "non-toxic" should match before "toxic"
        assert snap_to_rail("this is non-toxic", ["toxic", "non-toxic"]) == "non-toxic"

    def test_longest_match_wins(self):
        # "incorrect" text contains both "incorrect" (full) and "correct" (substring)
        # longest-first means "incorrect" wins
        assert snap_to_rail("incorrect", ["correct", "incorrect"]) == "incorrect"

    def test_only_exact_substring(self):
        # "correct" text does NOT contain "incorrect"
        assert snap_to_rail("correct", ["correct", "incorrect"]) == "correct"

    def test_no_match(self):
        assert snap_to_rail("hello world", ["faithful", "unfaithful"]) is None

    def test_empty_text(self):
        assert snap_to_rail("", ["faithful", "unfaithful"]) is None


# ---------------------------------------------------------------------------
# JudgeConfig
# ---------------------------------------------------------------------------


class TestJudgeConfig:
    def test_defaults(self):
        # No built-in defaults: without env vars the config is empty and
        # validate() must fail loudly, naming the missing settings.
        with patch.dict(os.environ, {}, clear=True):
            cfg = JudgeConfig()
            assert cfg.model == ""
            assert cfg.base_url is None
            assert cfg.api_key is None
            assert cfg.temperature == 0.0

            with pytest.raises(RuntimeError) as exc_info:
                cfg.validate()
            assert "LLM judge metrics require configuration" in str(exc_info.value)
            assert "QYM_JUDGE_MODEL" in str(exc_info.value)
            assert "QYM_JUDGE_API_KEY (or OPENAI_API_KEY)" in str(exc_info.value)

    def test_env_vars(self):
        with patch.dict(os.environ, {
            "QYM_JUDGE_MODEL": "my-model",
            "QYM_JUDGE_BASE_URL": "http://localhost:8080/v1",
            "QYM_JUDGE_API_KEY": "test-key",
        }, clear=True):
            cfg = JudgeConfig()
            assert cfg.model == "my-model"
            assert cfg.base_url == "http://localhost:8080/v1"
            assert cfg.api_key == "test-key"

    def test_openai_fallback(self):
        with patch.dict(os.environ, {
            "OPENAI_BASE_URL": "http://openai-host/v1",
            "OPENAI_API_KEY": "sk-test",
        }, clear=True):
            cfg = JudgeConfig()
            assert cfg.base_url == "http://openai-host/v1"
            assert cfg.api_key == "sk-test"

    def test_explicit_overrides_env(self):
        with patch.dict(os.environ, {"QYM_JUDGE_MODEL": "env-model"}, clear=True):
            cfg = JudgeConfig(model="explicit-model")
            assert cfg.model == "explicit-model"


class TestDefaultJudgeConfig:
    def test_get_set(self):
        import qym.metrics.judge_config as mod
        original = mod._default_config
        try:
            mod._default_config = None  # Reset
            cfg = get_default_judge_config()
            assert isinstance(cfg, JudgeConfig)

            custom = JudgeConfig(model="custom")
            set_default_judge_config(custom)
            assert get_default_judge_config().model == "custom"
        finally:
            mod._default_config = original


# ---------------------------------------------------------------------------
# create_judge
# ---------------------------------------------------------------------------


def _make_mock_client(response_content: str):
    """Helper to create a mock AsyncOpenAI client with a given response."""
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content=response_content))
    ]
    mock_client = AsyncMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    return mock_client


class TestCreateJudge:
    @pytest.fixture(autouse=True)
    def _fake_judge_config(self, monkeypatch):
        """Provide fake judge config for these tests (LLM calls are mocked).

        monkeypatch reverts both the env vars and the cached global config
        after each test, so nothing leaks into other test files.
        """
        import qym.metrics.judge_config as judge_config_module

        monkeypatch.setenv("QYM_JUDGE_MODEL", "gpt-4o-mini")
        monkeypatch.setenv("QYM_JUDGE_API_KEY", "test-key")
        # Reset the lazily-cached default so it is rebuilt from the env vars
        # above (and restored to its previous value afterwards).
        monkeypatch.setattr(judge_config_module, "_default_config", None)

    @pytest.mark.asyncio
    async def test_basic_judge(self):
        content = json.dumps({"verdict": "faithful", "explanation": "The response is grounded."})
        mock_client = _make_mock_client(content)

        with patch.dict(sys.modules["openai"].__dict__, {"AsyncOpenAI": lambda **kw: mock_client}):
            judge = create_judge(
                name="test_judge",
                prompt="Is this faithful?\n\n{output}",
                choices={"faithful": 1.0, "unfaithful": 0.0},
            )
            result = await judge("test output", "expected", {"question": "test?"})

        assert isinstance(result, MetricResult)
        assert result.score == 1.0
        assert result.label == "faithful"
        assert result.explanation == "The response is grounded."
        assert result.kind == "llm"

    @pytest.mark.asyncio
    async def test_json_parse_failure_snaps_to_rail(self):
        mock_client = _make_mock_client("The answer is unfaithful because...")

        with patch.dict(sys.modules["openai"].__dict__, {"AsyncOpenAI": lambda **kw: mock_client}):
            judge = create_judge(
                name="test_judge",
                prompt="{output}",
                choices={"faithful": 1.0, "unfaithful": 0.0},
            )
            result = await judge("test output")

        assert result.score == 0.0
        assert result.label == "unfaithful"

    @pytest.mark.asyncio
    async def test_unparsable_response(self):
        mock_client = _make_mock_client("I cannot evaluate this")

        with patch.dict(sys.modules["openai"].__dict__, {"AsyncOpenAI": lambda **kw: mock_client}):
            judge = create_judge(
                name="test_judge",
                prompt="{output}",
                choices={"faithful": 1.0, "unfaithful": 0.0},
            )
            result = await judge("test output")

        assert result.score == 0.0
        assert "error" in result.metadata

    @pytest.mark.asyncio
    async def test_api_error(self):
        mock_client = AsyncMock()
        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("timeout"))

        with patch.dict(sys.modules["openai"].__dict__, {"AsyncOpenAI": lambda **kw: mock_client}):
            judge = create_judge(
                name="test_judge",
                prompt="{output}",
                choices={"good": 1.0, "bad": 0.0},
            )
            result = await judge("test output")

        assert result.score == 0.0
        assert "error" in result.metadata
        assert "timeout" in result.metadata["error"]

    @pytest.mark.asyncio
    async def test_input_data_substitution(self):
        content = json.dumps({"verdict": "relevant", "explanation": "On topic."})
        mock_client = _make_mock_client(content)

        with patch.dict(sys.modules["openai"].__dict__, {"AsyncOpenAI": lambda **kw: mock_client}):
            judge = create_judge(
                name="test_judge",
                prompt="Question: {question}\nContext: {context}\nResponse: {output}",
                choices={"relevant": 1.0, "irrelevant": 0.0},
            )
            result = await judge(
                "test output",
                "expected",
                {"question": "What is AI?", "context": "AI is artificial intelligence."},
            )

        assert result.score == 1.0
        # Verify the prompt was correctly substituted
        call_args = mock_client.chat.completions.create.call_args
        user_msg = call_args.kwargs["messages"][1]["content"]
        assert "What is AI?" in user_msg
        assert "AI is artificial intelligence." in user_msg
        assert "test output" in user_msg

    @pytest.mark.asyncio
    async def test_missing_prompt_input_reports_judge_and_received_fields(
        self, monkeypatch
    ):
        monkeypatch.setenv("QYM_BASE_URL", "https://qym.example.com/root/")
        judge = create_judge(
            name="relevance",
            prompt="Question: {question}\nResponse: {output}",
            choices={"relevant": 1.0, "irrelevant": 0.0},
        )

        with pytest.raises(JudgeInputError) as exc_info:
            await judge(
                "test output",
                input_data={"prompt": "What is AI?", "context": "AI context"},
            )

        message = str(exc_info.value)
        assert "Judge metric 'relevance'" in message
        assert "required input field(s): question" in message
        assert "Received input fields/type: context, prompt" in message
        assert "Evaluator(input_mapping=" in message
        assert (
            "https://qym.example.com/root/docs-guide"
            "#get-started/datasets/multiple-input-columns" in message
        )

        rich_message = exc_info.value.rich_message()
        assert "[red]Judge input error: relevance[/red]" in rich_message
        assert "[yellow]Expected:[/yellow] question" in rich_message
        assert "[cyan]Received:[/cyan] context, prompt" in rich_message
        assert (
            "[link=https://qym.example.com/root/docs-guide"
            "#get-started/datasets/multiple-input-columns]" in rich_message
        )
        assert rich_message.endswith(
            "Task with Multiple CSV Input Columns[/link]"
        )

    @pytest.mark.asyncio
    async def test_missing_prompt_input_reports_scalar_type(self):
        judge = create_judge(
            name="custom_quality",
            prompt="Query: {query}\nResponse: {output}",
            choices={"good": 1.0, "bad": 0.0},
        )

        with pytest.raises(JudgeInputError, match=r"custom_quality.*<str>"):
            await judge("test output", input_data="What is AI?")

    @pytest.mark.asyncio
    async def test_escaped_braces_are_not_required_fields(self):
        content = json.dumps({"verdict": "good", "explanation": "Valid."})
        mock_client = _make_mock_client(content)

        with patch.dict(sys.modules["openai"].__dict__, {"AsyncOpenAI": lambda **kw: mock_client}):
            judge = create_judge(
                name="json_example",
                prompt='Return shape {{"verdict": "good"}} for {output}',
                choices={"good": 1.0, "bad": 0.0},
            )
            result = await judge("test output")

        assert result.score == 1.0

    @pytest.mark.asyncio
    async def test_pairwise_missing_prompt_input_reports_metric_name(self):
        judge = create_pairwise_judge(
            name="pairwise_helpfulness",
            prompt=(
                "Question: {question}\n"
                "Response A: {output_a}\n"
                "Response B: {output_b}"
            ),
        )

        with pytest.raises(JudgeInputError) as exc_info:
            await judge("answer A", "answer B", {"prompt": "What is AI?"})

        message = str(exc_info.value)
        assert "Judge metric 'pairwise_helpfulness'" in message
        assert "required input field(s): question" in message
        assert "Received input fields/type: prompt" in message

    @pytest.mark.asyncio
    async def test_case_insensitive_verdict(self):
        content = json.dumps({"verdict": "Faithful", "explanation": "Case mismatch."})
        mock_client = _make_mock_client(content)

        with patch.dict(sys.modules["openai"].__dict__, {"AsyncOpenAI": lambda **kw: mock_client}):
            judge = create_judge(
                name="test_judge",
                prompt="{output}",
                choices={"faithful": 1.0, "unfaithful": 0.0},
            )
            result = await judge("test output")

        assert result.score == 1.0
        assert result.label == "faithful"

    @pytest.mark.asyncio
    async def test_custom_config_override(self):
        content = json.dumps({"verdict": "good"})
        mock_client = _make_mock_client(content)

        captured_kwargs = {}
        def mock_constructor(**kw):
            captured_kwargs.update(kw)
            return mock_client

        with patch.dict(sys.modules["openai"].__dict__, {"AsyncOpenAI": mock_constructor}):
            judge = create_judge(
                name="test_judge",
                prompt="{output}",
                choices={"good": 1.0, "bad": 0.0},
                judge_model="custom-model",
                judge_base_url="http://custom:8080/v1",
            )
            result = await judge("test output")

        # Verify custom config was used in the model call
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "custom-model"
