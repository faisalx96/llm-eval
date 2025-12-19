"""Custom exceptions for the evaluation framework."""

from __future__ import annotations


class LLMEvalError(Exception):
    """Base exception for all llm-eval errors."""
    pass


class LangfuseConnectionError(LLMEvalError):
    """Raised when connection to Langfuse fails."""
    pass


class DatasetNotFoundError(LLMEvalError):
    """Raised when dataset is not found in Langfuse."""
    pass


class CsvDatasetError(LLMEvalError):
    """Raised when loading or parsing a CSV dataset fails."""


class CsvDatasetSchemaError(CsvDatasetError):
    """Raised when a CSV dataset does not match the expected schema."""

    def __init__(self, message: str, *, file_path: str, row: "int | None" = None, column: "str | None" = None):
        parts = [message]
        loc = []
        if file_path:
            loc.append(f"file={file_path}")
        if row is not None:
            loc.append(f"row={row}")
        if column:
            loc.append(f"column={column}")
        if loc:
            parts.append(f"({', '.join(loc)})")
        super().__init__(" ".join(parts))


class MetricError(LLMEvalError):
    """Raised when metric computation fails."""
    pass


class TaskExecutionError(LLMEvalError):
    """Raised when task execution fails."""
    pass