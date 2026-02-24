"""Observer hooks for Evaluator progress and metric updates."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


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

    def on_warning(
        self,
        run_id: str,
        message: str,
    ) -> None:
        """Called when a performance warning is detected."""

    def on_run_complete(
        self,
        run_id: str,
        result_summary: Dict[str, Any],
    ) -> None:
        """Called after the entire run finishes."""


class NullEvaluationObserver(EvaluationObserver):
    """Default observer that ignores all notifications."""

    pass


class CompositeEvaluationObserver(EvaluationObserver):
    """Fan-out observer that notifies multiple observers."""

    def __init__(self, observers: Optional[Sequence[EvaluationObserver]] = None) -> None:
        self._observers: List[EvaluationObserver] = []
        if observers:
            for observer in observers:
                self.add_observer(observer)

    def add_observer(self, observer: Optional[EvaluationObserver]) -> None:
        if observer is None:
            return
        self._observers.append(observer)

    def _call(self, method: str, **kwargs: Any) -> None:
        for observer in list(self._observers):
            callback = getattr(observer, method, None)
            if callable(callback):
                try:
                    callback(**kwargs)
                except Exception:
                    continue

    def on_run_start(self, **kwargs: Any) -> None:
        self._call("on_run_start", **kwargs)

    def on_item_start(self, **kwargs: Any) -> None:
        self._call("on_item_start", **kwargs)

    def on_metric_result(self, **kwargs: Any) -> None:
        self._call("on_metric_result", **kwargs)

    def on_item_complete(self, **kwargs: Any) -> None:
        self._call("on_item_complete", **kwargs)

    def on_item_error(self, **kwargs: Any) -> None:
        self._call("on_item_error", **kwargs)

    def on_warning(self, **kwargs: Any) -> None:
        self._call("on_warning", **kwargs)

    def on_run_complete(self, **kwargs: Any) -> None:
        self._call("on_run_complete", **kwargs)
