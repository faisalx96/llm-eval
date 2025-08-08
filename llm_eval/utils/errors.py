"""Custom exceptions for the evaluation framework."""


class LLMEvalError(Exception):
    """Base exception for all llm-eval errors."""

    pass


class LangfuseConnectionError(LLMEvalError):
    """Raised when connection to Langfuse fails."""

    pass


class DatasetNotFoundError(LLMEvalError):
    """Raised when dataset is not found in Langfuse."""

    pass


class MetricError(LLMEvalError):
    """Raised when metric computation fails."""

    pass


class TaskExecutionError(LLMEvalError):
    """Raised when task execution fails."""

    pass
