"""Structured input for multi-model evaluation runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union


MetricDef = Union[str, Callable[..., Any]]


@dataclass
class RunSpec:
    """Full description of a single evaluation run."""

    name: str
    task: Any
    dataset: str
    metrics: List[MetricDef]
    task_file: str = "<python-callable>"
    task_function: str = "<callable>"
    config: Dict[str, Any] = field(default_factory=dict)
    output_path: Optional[Path] = None

    @property
    def run_name(self) -> str:
        """Derived run name for display and evaluator config."""
        return self.config.get("run_name") or self.name
