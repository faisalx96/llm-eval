"""Data structures used to organize insight occurrences."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar


OccurrenceData = dict[str, int]
MetricData = dict[str, dict[str, int]]


class _InsightDataHelpers:
    """Shared helpers for category-level and root-cause-level data."""

    _mapping_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "models",
            "datasets",
            "tasks",
            "metrics",
            "tools",
            "extra_data",
            "root_causes",
        }
    )

    extra_data: dict[str, Any]

    def add_extra_data(self, name: str, value: Any) -> None:
        """Add or replace an extra data value."""
        self.extra_data[name] = value

    def get(self, name: str, default: Any = None) -> Any:
        """Return a declared field, extra value, or root cause by name."""
        if name in self.__dataclass_fields__:
            return getattr(self, name)
        if name in self.extra_data:
            return self.extra_data[name]

        root_causes = getattr(self, "root_causes", None)
        if isinstance(root_causes, dict):
            return root_causes.get(name, default)
        return default

    def drop(self, name: str) -> Any:
        """Drop data by name and return the value that was removed.

        Declared mapping fields are reset to an empty dictionary so the
        dataclass keeps a stable schema. The category is reset to an empty
        string. Extra data and individual root causes are removed entirely.
        Missing names return ``None``.
        """
        if name in self._mapping_fields and name in self.__dataclass_fields__:
            value = getattr(self, name)
            setattr(self, name, {})
            return value
        if name == "category" and name in self.__dataclass_fields__:
            value = getattr(self, name)
            self.category = ""
            return value
        if name in self.extra_data:
            return self.extra_data.pop(name)

        root_causes = getattr(self, "root_causes", None)
        if isinstance(root_causes, dict):
            return root_causes.pop(name, None)
        return None


@dataclass
class RootCauseData(_InsightDataHelpers):
    """Occurrence data associated with one root cause."""

    models: OccurrenceData = field(default_factory=dict)
    datasets: OccurrenceData = field(default_factory=dict)
    tasks: OccurrenceData = field(default_factory=dict)
    metrics: MetricData = field(default_factory=dict)
    tools: OccurrenceData = field(default_factory=dict)
    extra_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class InsightData(_InsightDataHelpers):
    """Category-level occurrence data and its sibling root causes."""

    category: str
    models: OccurrenceData = field(default_factory=dict)
    datasets: OccurrenceData = field(default_factory=dict)
    tasks: OccurrenceData = field(default_factory=dict)
    metrics: MetricData = field(default_factory=dict)
    tools: OccurrenceData = field(default_factory=dict)
    extra_data: dict[str, Any] = field(default_factory=dict)
    root_causes: dict[str, RootCauseData] = field(default_factory=dict)


__all__ = ["InsightData", "MetricData", "OccurrenceData", "RootCauseData"]
