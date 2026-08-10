from __future__ import annotations

import asyncio

import pytest

from qym_platform.services.analysis_jobs import AnalysisJobManager


@pytest.mark.asyncio
async def test_analysis_job_continues_after_submit_and_can_be_cancelled() -> None:
    manager = AnalysisJobManager()
    started = asyncio.Event()
    release = asyncio.Event()

    async def runner(job):
        started.set()
        await release.wait()
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
    await started.wait()
    assert manager.active_for_run("run-1") is job
    assert job.status == "running"

    cancelled = manager.cancel(job.job_id)
    assert cancelled is job
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert job.status == "cancelled"
    assert manager.active_for_run("run-1") is None


@pytest.mark.asyncio
async def test_analysis_job_manager_reuses_one_active_job_per_run() -> None:
    manager = AnalysisJobManager()
    release = asyncio.Event()

    async def runner(job):
        await release.wait()
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
    await asyncio.sleep(0)
    await asyncio.sleep(0)
