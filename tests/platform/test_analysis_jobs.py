from __future__ import annotations

import asyncio
from typing import Iterator

import pytest

from qym_platform.services.analysis_jobs import AnalysisJob, AnalysisJobManager


@pytest.fixture
def manager() -> Iterator[AnalysisJobManager]:
    instance = AnalysisJobManager()
    try:
        yield instance
    finally:
        instance.clear()
        instance.shutdown(wait=True)


async def _wait_for_workers(*jobs: AnalysisJob) -> None:
    await asyncio.wait_for(
        asyncio.gather(
            *(asyncio.wrap_future(job.future) for job in jobs),
            return_exceptions=True,
        ),
        timeout=5,
    )


@pytest.mark.asyncio
async def test_analysis_job_continues_after_submit_and_can_be_cancelled(
    manager: AnalysisJobManager,
) -> None:
    caller_loop = asyncio.get_running_loop()
    started = asyncio.Event()

    async def runner(job):
        caller_loop.call_soon_threadsafe(started.set)
        # The wait belongs to the worker loop, including on Python 3.9.
        await asyncio.Event().wait()
        return {"total_analyzed": 1}

    job, created = await manager.submit(
        run_id="run-1",
        user_id="user-1",
        auth_type="proxy_headers",
        request_payload={"item_filter": "failed"},
        progress={"total": 1, "completed": 0},
        runner=runner,
    )
    assert created is True
    await asyncio.wait_for(started.wait(), timeout=5)
    assert manager.active_for_run("run-1") is job
    assert job.status == "running"

    cancelled = manager.cancel(job.job_id)
    assert cancelled is job
    await _wait_for_workers(job)
    assert job.status == "cancelled"
    assert job.error is None
    assert manager.active_for_run("run-1") is None


@pytest.mark.asyncio
async def test_analysis_job_manager_reuses_one_active_job_per_run(
    manager: AnalysisJobManager,
) -> None:
    async def runner(job):
        await asyncio.Event().wait()
        return {}

    first, first_created = await manager.submit(
        run_id="run-1",
        user_id="user-1",
        auth_type="none",
        request_payload={},
        progress={},
        runner=runner,
    )
    second, second_created = await manager.submit(
        run_id="run-1",
        user_id="user-2",
        auth_type="none",
        request_payload={"different": True},
        progress={"total": 20},
        runner=runner,
    )

    assert first_created is True
    assert second_created is False
    assert second is first
    manager.cancel(first.job_id)
    await _wait_for_workers(first)
    assert first.status == "cancelled"
    assert first.error is None


@pytest.mark.asyncio
async def test_analysis_job_manager_scopes_active_jobs_by_pass(
    manager: AnalysisJobManager,
) -> None:
    async def runner(job):
        await asyncio.Event().wait()
        return {}

    first, first_created = await manager.submit(
        run_id="run-1",
        user_id="user-1",
        auth_type="none",
        request_payload={"pass_number": 1},
        progress={},
        runner=runner,
    )
    same_pass, same_pass_created = await manager.submit(
        run_id="run-1",
        user_id="user-2",
        auth_type="none",
        request_payload={"pass_number": 1},
        progress={},
        runner=runner,
    )
    other_pass, other_pass_created = await manager.submit(
        run_id="run-1",
        user_id="user-2",
        auth_type="none",
        request_payload={"pass_number": 2},
        progress={},
        runner=runner,
    )

    assert first_created is True
    assert same_pass_created is False
    assert same_pass is first
    assert other_pass_created is True
    assert other_pass is not first
    assert manager.active_for_run("run-1", 1) is first
    assert manager.active_for_run("run-1", 2) is other_pass

    manager.cancel(first.job_id)
    manager.cancel(other_pass.job_id)
    await _wait_for_workers(first, other_pass)
    assert first.status == other_pass.status == "cancelled"
    assert first.error is other_pass.error is None
