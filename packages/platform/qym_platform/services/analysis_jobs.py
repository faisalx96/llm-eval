"""In-process lifecycle management for long-running run analyses.

The browser used to own the lifetime of an analysis through the streaming
response.  Keeping the task here lets the HTTP request disappear when a user
navigates away while the analysis continues on the platform worker.
"""

from __future__ import annotations

import asyncio
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
    task: Optional[asyncio.Task[Any]] = field(default=None, repr=False)

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


class AnalysisJobManager:
    """Own analysis tasks independently from the request that started them."""

    def __init__(self, *, max_retained_jobs: int = 100) -> None:
        self._jobs: Dict[str, AnalysisJob] = {}
        self._max_retained_jobs = max(10, int(max_retained_jobs))

    def get(self, job_id: str) -> Optional[AnalysisJob]:
        return self._jobs.get(job_id)

    def active_for_run(self, run_id: str) -> Optional[AnalysisJob]:
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
        """Create a job or return the existing active job for the run.

        The boolean indicates whether a new task was created.
        """
        existing = self.active_for_run(run_id)
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
        job.task = asyncio.create_task(self._run(job, runner))
        self._prune()
        return job, True

    async def _run(self, job: AnalysisJob, runner: AnalysisRunner) -> None:
        job.status = "running"
        job.progress["phase"] = "running"
        job.touch()
        try:
            job.result = await runner(job)
            if job.cancel_requested:
                job.status = "cancelled"
                job.progress["phase"] = "cancelled"
                job.result = None
            else:
                job.status = "completed"
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.progress["phase"] = "cancelled"
            job.result = None
        except Exception as exc:  # pragma: no cover - runner-specific failures
            job.status = "failed"
            job.progress["phase"] = "failed"
            job.error = str(exc)
        finally:
            job.completed_at = utc_now_naive()
            job.touch()
            self._prune()

    def cancel(self, job_id: str) -> Optional[AnalysisJob]:
        job = self.get(job_id)
        if job is None or job.status in TERMINAL_JOB_STATUSES:
            return job
        job.cancel_requested = True
        job.status = "cancelling"
        job.progress["phase"] = "cancelling"
        job.touch()
        if job.task is not None and not job.task.done():
            job.task.cancel()
        return job

    def update_progress(self, job: AnalysisJob, **values: Any) -> None:
        job.progress.update(values)
        job.touch()

    def snapshot(self, job: Optional[AnalysisJob]) -> Optional[Dict[str, Any]]:
        return job.snapshot() if job is not None else None

    def clear(self) -> None:
        """Cancel and forget jobs; intended for application/test teardown."""
        for job in self._jobs.values():
            if job.task is not None and not job.task.done():
                job.task.cancel()
        self._jobs.clear()

    def _prune(self) -> None:
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
