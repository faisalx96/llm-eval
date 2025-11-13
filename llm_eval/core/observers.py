"""Observer hooks for Evaluator progress and metric updates."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class EvaluationObserver:
    """Base observer with no-op hooks for evaluation lifecycle events."""

    def on_run_start(
        self,
        run_id: str,
        run_info: Dict[str, Any],
        total_items: int,
        metrics: List[str],
    ) -> None:
        """Called once when a run is about to start."""

    def on_item_start(
        self,
        run_id: str,
        item_index: int,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Called when an item begins processing."""

    def on_metric_result(
        self,
        run_id: str,
        item_index: int,
        metric_name: str,
        score: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Called when a metric finishes computing for an item."""

    def on_item_complete(
        self,
        run_id: str,
        item_index: int,
        result: Dict[str, Any],
    ) -> None:
        """Called when an item completes successfully."""

    def on_item_error(
        self,
        run_id: str,
        item_index: int,
        error: str,
    ) -> None:
        """Called when an item fails."""

    def on_run_complete(
        self,
        run_id: str,
        result_summary: Dict[str, Any],
    ) -> None:
        """Called after the entire run finishes."""


class NullEvaluationObserver(EvaluationObserver):
    """Default observer that ignores all notifications."""

    pass
