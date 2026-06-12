"""Tests for LLM judge infrastructure — mock AsyncOpenAI, test judges, JudgeConfig, create_judge."""

import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# `openai` is mocked by tests/conftest.py only when genuinely missing, so
# `patch("openai.AsyncOpenAI", ...)` below works in every environment.

from qym.metrics.result import MetricResult
from qym.metrics.judge_config import JudgeConfig, get_default_judge_config, set_default_judge_config
from qym.metrics.judges.base import snap_to_rail, create_judge

# Judge config is mandatory (no built-in defaults); the client is mocked so
# these values are never used for real calls.
_JUDGE_KW = {"judge_model": "test-judge-model", "judge_api_key": "test-judge-key"}


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
        """No built-in model default — judge configuration is mandatory."""
        with patch.dict(os.environ, {}, clear=True):
            cfg = JudgeConfig()
            assert cfg.model == ""
            assert cfg.base_url is None
            assert cfg.api_key is None
            assert cfg.temperature == 0.0
            with pytest.raises(RuntimeError, match="QYM_JUDGE_MODEL"):
                cfg.validate()

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
    @pytest.mark.asyncio
    async def test_basic_judge(self):
        content = json.dumps({"verdict": "faithful", "explanation": "The response is grounded."})
        mock_client = _make_mock_client(content)

        with patch("openai.AsyncOpenAI", new=lambda **kw: mock_client):
            judge = create_judge(
                name="test_judge",
                prompt="Is this faithful?\n\n{output}",
                choices={"faithful": 1.0, "unfaithful": 0.0},
                **_JUDGE_KW,
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

        with patch("openai.AsyncOpenAI", new=lambda **kw: mock_client):
            judge = create_judge(
                name="test_judge",
                prompt="{output}",
                choices={"faithful": 1.0, "unfaithful": 0.0},
                **_JUDGE_KW,
            )
            result = await judge("test output")

        assert result.score == 0.0
        assert result.label == "unfaithful"

    @pytest.mark.asyncio
    async def test_unparsable_response(self):
        mock_client = _make_mock_client("I cannot evaluate this")

        with patch("openai.AsyncOpenAI", new=lambda **kw: mock_client):
            judge = create_judge(
                name="test_judge",
                prompt="{output}",
                choices={"faithful": 1.0, "unfaithful": 0.0},
                **_JUDGE_KW,
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

        with patch("openai.AsyncOpenAI", new=lambda **kw: mock_client):
            judge = create_judge(
                name="test_judge",
                prompt="{output}",
                choices={"good": 1.0, "bad": 0.0},
                **_JUDGE_KW,
            )
            result = await judge("test output")

        assert result.score == 0.0
        assert "error" in result.metadata
        assert "timeout" in result.metadata["error"]

    @pytest.mark.asyncio
    async def test_input_data_substitution(self):
        content = json.dumps({"verdict": "relevant", "explanation": "On topic."})
        mock_client = _make_mock_client(content)

        with patch("openai.AsyncOpenAI", new=lambda **kw: mock_client):
            judge = create_judge(
                name="test_judge",
                prompt="Question: {question}\nContext: {context}\nResponse: {output}",
                choices={"relevant": 1.0, "irrelevant": 0.0},
                **_JUDGE_KW,
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
    async def test_case_insensitive_verdict(self):
        content = json.dumps({"verdict": "Faithful", "explanation": "Case mismatch."})
        mock_client = _make_mock_client(content)

        with patch("openai.AsyncOpenAI", new=lambda **kw: mock_client):
            judge = create_judge(
                name="test_judge",
                prompt="{output}",
                choices={"faithful": 1.0, "unfaithful": 0.0},
                **_JUDGE_KW,
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

        with patch("openai.AsyncOpenAI", new=mock_constructor):
            judge = create_judge(
                name="test_judge",
                prompt="{output}",
                choices={"good": 1.0, "bad": 0.0},
                judge_model="custom-model",
                judge_base_url="http://custom:8080/v1",
                judge_api_key="custom-key",
            )
            result = await judge("test output")

        # Verify custom config was used in the model call
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "custom-model"
