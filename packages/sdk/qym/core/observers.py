"""Observer hooks for Evaluator progress and metric updates."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Callable, Dict, List, Optional, Sequence, Set


class EvaluationObserver:
    """Base observer with no-op hooks for evaluation lifecycle events."""

    def on_run_matrix(
        self,
        matrix_id: str,
        runs: List[Dict[str, Any]],
        total_runs: int,
    ) -> None:
        """Called when a multi-run evaluation shape is known."""

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


@dataclass(frozen=True)
class ProgressSnapshot:
    """Structured progress update emitted by ProgressCallbackObserver."""

    run_id: str
    event: str
    total_items: int = 0
    completed: int = 0
    failed: int = 0
    in_progress: int = 0
    pending: int = 0
    metrics: List[str] = field(default_factory=list)
    item_index: Optional[int] = None
    metric_name: Optional[str] = None
    score: Any = None
    error: Optional[str] = None
    message: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    run_info: Optional[Dict[str, Any]] = None
    run_matrix: Optional[List[Dict[str, Any]]] = None
    total_runs: int = 0
    result_summary: Optional[Dict[str, Any]] = None

    @property
    def finished(self) -> int:
        """Number of items that have either completed or failed."""
        return self.completed + self.failed

    @property
    def percent_complete(self) -> float:
        """Completion percentage in the range 0.0 to 100.0."""
        if self.total_items <= 0:
            return 0.0
        return (self.finished / self.total_items) * 100.0


class ProgressCallbackObserver(EvaluationObserver):
    """Convert evaluator lifecycle hooks into progress snapshots.

    This observer is intended for wrappers that need first-class progress
    updates without reimplementing qym's item counting logic.
    """

    def __init__(self, callback: Callable[[ProgressSnapshot], None]) -> None:
        self.callback = callback
        self._lock = RLock()
        self._runs: Dict[str, Dict[str, Any]] = {}

    def _state_for(self, run_id: str) -> Dict[str, Any]:
        return self._runs.setdefault(
            run_id,
            {
                "total_items": 0,
                "metrics": [],
                "run_info": {},
                "completed_offset": 0,
                "failed_offset": 0,
                "in_progress": set(),
                "completed": set(),
                "failed": set(),
            },
        )

    def _snapshot(self, run_id: str, event: str, **extra: Any) -> ProgressSnapshot:
        with self._lock:
            state = self._state_for(run_id)
            total_items = int(state.get("total_items") or 0)
            completed_offset = int(state.get("completed_offset") or 0)
            failed_offset = int(state.get("failed_offset") or 0)
            in_progress: Set[int] = set(state.get("in_progress") or set())
            completed: Set[int] = set(state.get("completed") or set())
            failed: Set[int] = set(state.get("failed") or set())
            completed_count = completed_offset + len(completed)
            failed_count = failed_offset + len(failed)
            pending = max(
                total_items - completed_count - failed_count - len(in_progress), 0
            )

            return ProgressSnapshot(
                run_id=run_id,
                event=event,
                total_items=total_items,
                completed=completed_count,
                failed=failed_count,
                in_progress=len(in_progress),
                pending=pending,
                metrics=list(state.get("metrics") or []),
                run_info=dict(state.get("run_info") or {}),
                **extra,
            )

    def _emit(self, run_id: str, event: str, **extra: Any) -> None:
        self.callback(self._snapshot(run_id, event, **extra))

    def on_run_start(
        self,
        run_id: str,
        run_info: Dict[str, Any],
        total_items: int,
        metrics: List[str],
    ) -> None:
        try:
            completed_offset = int((run_info or {}).get("resume_completed") or 0)
            failed_offset = int((run_info or {}).get("resume_failed") or 0)
        except Exception:
            completed_offset = 0
            failed_offset = 0
        with self._lock:
            self._runs[run_id] = {
                "total_items": int(total_items),
                "metrics": list(metrics),
                "run_info": dict(run_info or {}),
                "completed_offset": completed_offset,
                "failed_offset": failed_offset,
                "in_progress": set(),
                "completed": set(),
                "failed": set(),
            }
        self._emit(run_id, "run_start")

    def on_run_matrix(
        self,
        matrix_id: str,
        runs: List[Dict[str, Any]],
        total_runs: int,
    ) -> None:
        self.callback(
            ProgressSnapshot(
                run_id=matrix_id,
                event="run_matrix",
                run_matrix=[dict(run) for run in runs],
                total_runs=int(total_runs),
            )
        )

    def on_item_start(
        self,
        run_id: str,
        item_index: int,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            state = self._state_for(run_id)
            state["completed"].discard(item_index)
            state["failed"].discard(item_index)
            state["in_progress"].add(item_index)
        self._emit(run_id, "item_start", item_index=item_index, payload=payload)

    def on_metric_result(
        self,
        run_id: str,
        item_index: int,
        metric_name: str,
        score: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._emit(
            run_id,
            "metric_result",
            item_index=item_index,
            metric_name=metric_name,
            score=score,
            metadata=metadata,
        )

    def on_item_complete(
        self,
        run_id: str,
        item_index: int,
        result: Dict[str, Any],
    ) -> None:
        with self._lock:
            state = self._state_for(run_id)
            state["in_progress"].discard(item_index)
            state["failed"].discard(item_index)
            state["completed"].add(item_index)
        self._emit(run_id, "item_complete", item_index=item_index, result=result)

    def on_item_error(
        self,
        run_id: str,
        item_index: int,
        error: str,
    ) -> None:
        with self._lock:
            state = self._state_for(run_id)
            state["in_progress"].discard(item_index)
            state["completed"].discard(item_index)
            state["failed"].add(item_index)
        self._emit(run_id, "item_error", item_index=item_index, error=error)

    def on_warning(
        self,
        run_id: str,
        message: str,
    ) -> None:
        self._emit(run_id, "warning", message=message)

    def on_run_complete(
        self,
        run_id: str,
        result_summary: Dict[str, Any],
    ) -> None:
        with self._lock:
            state = self._state_for(run_id)
            state["in_progress"].clear()
        self._emit(run_id, "run_complete", result_summary=result_summary)


class NullEvaluationObserver(EvaluationObserver):
    """Default observer that ignores all notifications."""

    pass


class CompositeEvaluationObserver(EvaluationObserver):
    """Fan-out observer that notifies multiple observers."""

    def __init__(
        self, observers: Optional[Sequence[EvaluationObserver]] = None
    ) -> None:
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

    def on_run_matrix(self, **kwargs: Any) -> None:
        self._call("on_run_matrix", **kwargs)

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


__all__ = [
    "EvaluationObserver",
    "ProgressSnapshot",
    "ProgressCallbackObserver",
    "NullEvaluationObserver",
    "CompositeEvaluationObserver",
]
