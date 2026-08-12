"""Bounded, in-process lifecycle management for background analyses.

Analysis work is deliberately isolated from the request event loop.  Each
executor worker owns the event loop used by its analyzer runner and the
SQLAlchemy session created by the runner.  The registry remains in memory for
the single-Uvicorn-worker deployment, but all registry state is protected by a
threading lock so progress updates and polling are safe across worker threads.
"""

from __future__ import annotations

import asyncio
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple
from uuid import uuid4

from qym_platform.datetime_utils import utc_now_naive


ACTIVE_JOB_STATUSES = frozenset({"queued", "running", "cancelling"})
TERMINAL_JOB_STATUSES = frozenset({"completed", "failed", "cancelled"})


@dataclass
class AnalysisJob:
    """Mutable state for one background run analysis."""

    run_id: str
    user_id: str
    auth_type: str
    request_payload: Dict[str, Any]
    job_id: str = field(default_factory=lambda: f"analysis_{uuid4().hex}")
    status: str = "queued"
    progress: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    cancel_requested: bool = False
    created_at: datetime = field(default_factory=utc_now_naive)
    updated_at: datetime = field(default_factory=utc_now_naive)
    completed_at: Optional[datetime] = None
    # Kept as a compatibility field for callers that inspected the old task.
    # It now refers to the task on the worker-owned loop, not the request loop.
    task: Optional[asyncio.Task[Any]] = field(default=None, repr=False)
    future: Optional[Future[Any]] = field(default=None, repr=False)
    worker_loop: Optional[asyncio.AbstractEventLoop] = field(default=None, repr=False)
    request_wakeup_task: Optional[asyncio.Task[Any]] = field(default=None, repr=False)

    def touch(self) -> None:
        self.updated_at = utc_now_naive()

    def snapshot(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "run_id": self.run_id,
            "status": self.status,
            "progress": dict(self.progress),
            "result": self.result,
            "error": self.error,
            "cancel_requested": self.cancel_requested,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }


AnalysisRunner = Callable[[AnalysisJob], Awaitable[Dict[str, Any]]]


def _configured_worker_count() -> int:
    try:
        return max(1, int(os.getenv("QYM_ANALYSIS_JOB_MAX_WORKERS", "2")))
    except (TypeError, ValueError):
        return 2


class AnalysisJobManager:
    """Own analysis jobs independently from the request that started them."""

    def __init__(
        self,
        *,
        max_retained_jobs: int = 100,
        max_workers: Optional[int] = None,
    ) -> None:
        self._jobs: Dict[str, AnalysisJob] = {}
        self._max_retained_jobs = max(10, int(max_retained_jobs))
        self._max_workers = max(1, int(max_workers or _configured_worker_count()))
        self._lock = threading.RLock()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._shutdown = False

    def _ensure_executor(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._executor is None or self._shutdown:
                self._executor = ThreadPoolExecutor(
                    max_workers=self._max_workers,
                    thread_name_prefix="qym-analysis",
                )
                self._shutdown = False
            return self._executor

    def configure(self, *, max_workers: int) -> None:
        """Apply application settings before the executor is first used."""
        with self._lock:
            if self._executor is None:
                self._max_workers = max(1, int(max_workers))

    def get(self, job_id: str) -> Optional[AnalysisJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def active_for_run(self, run_id: str) -> Optional[AnalysisJob]:
        with self._lock:
            for job in reversed(list(self._jobs.values())):
                if job.run_id == run_id and job.status in ACTIVE_JOB_STATUSES:
                    return job
        return None

    async def submit(
        self,
        *,
        run_id: str,
        user_id: str,
        auth_type: str,
        request_payload: Dict[str, Any],
        progress: Optional[Dict[str, Any]],
        runner: AnalysisRunner,
    ) -> Tuple[AnalysisJob, bool]:
        """Create a job or return the existing active job for the run."""
        with self._lock:
            existing = next(
                (
                    job
                    for job in reversed(list(self._jobs.values()))
                    if job.run_id == run_id and job.status in ACTIVE_JOB_STATUSES
                ),
                None,
            )
            if existing is not None:
                return existing, False

            job = AnalysisJob(
                run_id=run_id,
                user_id=user_id,
                auth_type=auth_type,
                request_payload=dict(request_payload),
                progress=dict(progress or {}),
            )
            self._jobs[job.job_id] = job
            executor = self._ensure_executor()
            # A tiny caller-loop heartbeat makes thread-originated progress
            # and asyncio primitives observable immediately to the polling
            # request.  It also avoids relying on non-thread-safe Future wakeup
            # internals when a test/client callback signals from a worker.
            job.request_wakeup_task = asyncio.create_task(
                self._request_loop_heartbeat(job)
            )
            job.future = executor.submit(self._worker_entry, job, runner)
            self._prune_unlocked()
            return job, True

    async def _request_loop_heartbeat(self, job: AnalysisJob) -> None:
        try:
            while True:
                await asyncio.sleep(0.01)
                with self._lock:
                    if job.status in TERMINAL_JOB_STATUSES:
                        return
        except asyncio.CancelledError:
            return

    def _worker_entry(self, job: AnalysisJob, runner: AnalysisRunner) -> None:
        """Run one job with a loop owned exclusively by this executor thread."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        task = loop.create_task(self._run(job, runner))
        with self._lock:
            job.worker_loop = loop
            job.task = task
        try:
            loop.run_until_complete(task)
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for pending_task in pending:
                    pending_task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            finally:
                loop.close()
                with self._lock:
                    job.worker_loop = None
                    job.task = None

    async def _run(self, job: AnalysisJob, runner: AnalysisRunner) -> None:
        with self._lock:
            if job.cancel_requested:
                self._finish_cancelled_unlocked(job)
                return
            job.status = "running"
            job.progress["phase"] = "running"
            job.touch()
        try:
            result = await runner(job)
            with self._lock:
                if job.cancel_requested:
                    self._finish_cancelled_unlocked(job)
                else:
                    job.result = result
                    job.status = "completed"
        except asyncio.CancelledError:
            with self._lock:
                self._finish_cancelled_unlocked(job)
        except Exception as exc:  # pragma: no cover - runner-specific failures
            with self._lock:
                job.status = "failed"
                job.progress["phase"] = "failed"
                job.error = str(exc)
        finally:
            with self._lock:
                if job.completed_at is None:
                    job.completed_at = utc_now_naive()
                job.touch()
                self._prune_unlocked()

    @staticmethod
    def _finish_cancelled_unlocked(job: AnalysisJob) -> None:
        job.status = "cancelled"
        job.progress["phase"] = "cancelled"
        job.result = None

    def cancel(self, job_id: str) -> Optional[AnalysisJob]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in TERMINAL_JOB_STATUSES:
                return job
            job.cancel_requested = True
            # A queued Future can be removed without entering the worker.
            if job.status == "queued" and job.future is not None and job.future.cancel():
                self._finish_cancelled_unlocked(job)
                job.completed_at = utc_now_naive()
                job.touch()
                return job
            # Expose cancellation immediately to polling clients.  The worker
            # still receives ``cancel_requested`` and is interrupted at its
            # next await, so it cannot enter aggregation or persistence.
            job.status = "cancelled"
            job.progress["phase"] = "cancelled"
            job.result = None
            job.completed_at = utc_now_naive()
            job.touch()
            loop = job.worker_loop
            task = job.task
            if loop is not None and task is not None and not task.done():
                # Interrupt an in-flight await; the runner also checks the
                # cooperative flag before aggregation and persistence.
                loop.call_soon_threadsafe(task.cancel)
            return job

    def update_progress(self, job: AnalysisJob, **values: Any) -> None:
        with self._lock:
            job.progress.update(values)
            job.touch()

    def snapshot(self, job: Optional[AnalysisJob]) -> Optional[Dict[str, Any]]:
        with self._lock:
            return job.snapshot() if job is not None else None

    def clear(self) -> None:
        """Cancel and forget jobs; intended for application/test teardown."""
        with self._lock:
            job_ids = list(self._jobs)
        for job_id in job_ids:
            self.cancel(job_id)
        with self._lock:
            for job in self._jobs.values():
                heartbeat = job.request_wakeup_task
                if heartbeat is not None and not heartbeat.done():
                    heartbeat.cancel()
            self._jobs.clear()

    def shutdown(self, *, wait: bool = True) -> None:
        """Stop accepting work and release the bounded executor."""
        with self._lock:
            executor = self._executor
            self._shutdown = True
            job_ids = [
                job.job_id
                for job in self._jobs.values()
                if job.status not in TERMINAL_JOB_STATUSES
            ]
            self._executor = None
        for job_id in job_ids:
            self.cancel(job_id)
        if executor is not None:
            executor.shutdown(wait=wait, cancel_futures=True)

    def _prune_unlocked(self) -> None:
        if len(self._jobs) <= self._max_retained_jobs:
            return
        terminal = sorted(
            (
                job
                for job in self._jobs.values()
                if job.status in TERMINAL_JOB_STATUSES
            ),
            key=lambda job: job.updated_at,
        )
        for job in terminal[: max(0, len(self._jobs) - self._max_retained_jobs)]:
            self._jobs.pop(job.job_id, None)


analysis_job_manager = AnalysisJobManager()


__all__ = [
    "ACTIVE_JOB_STATUSES",
    "TERMINAL_JOB_STATUSES",
    "AnalysisJob",
    "AnalysisJobManager",
    "analysis_job_manager",
]
