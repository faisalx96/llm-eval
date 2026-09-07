"""Custom exceptions for the evaluation framework."""

from __future__ import annotations


class QymError(Exception):
    """Base exception for all قيِّم (qym) errors."""
    pass


# Backwards compatibility alias
LLMEvalError = QymError


class NonRetryableError(QymError):
    """Base class for user-raised errors that qym must not retry."""


class BusinessRuleError(NonRetryableError):
    """Raised when a task or metric cannot continue because of a business rule."""


class LangfuseConnectionError(QymError):
    """Raised when connection to Langfuse fails."""
    pass


class DatasetNotFoundError(QymError):
    """Raised when a dataset cannot be resolved locally or from qym platform."""
    pass


class CsvDatasetError(QymError):
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


class MetricError(QymError):
    """Raised when metric computation fails."""
    pass


class TaskExecutionError(QymError):
    """Raised when task execution fails."""
    pass
