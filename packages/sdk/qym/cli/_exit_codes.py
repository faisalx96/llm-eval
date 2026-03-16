"""Semantic exit codes for agent-native CLI."""

from enum import IntEnum


class ExitCode(IntEnum):
    SUCCESS = 0
    FAILURE = 1
    USAGE_ERROR = 2
    NOT_FOUND = 3
    AUTH_DENIED = 4
    CONFLICT = 5
