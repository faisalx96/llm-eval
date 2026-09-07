import asyncio
import json
from qym_platform.services.analysis_jobs import AnalysisJobManager

async def main():
    manager = AnalysisJobManager(max_retained_jobs=10, max_workers=2)
    async def runner(job):
        await asyncio.sleep(60)
        return {}
    try:
        for i in range(250):
            await manager.submit(run_id=str(i), user_id='synthetic', auth_type='test', request_payload={}, progress={}, runner=runner)
        await asyncio.sleep(.05)
        jobs = list(manager._jobs.values())
        result = {
            'submitted': 250,
            'retention_limit': 10,
            'max_workers': 2,
            'retained': len(jobs),
            'running': sum(j.status == 'running' for j in jobs),
            'queued': sum(j.status == 'queued' for j in jobs),
            'request_loop_heartbeat_tasks': sum(j.request_wakeup_task is not None and not j.request_wakeup_task.done() for j in jobs),
        }
        print(json.dumps(result, indent=2))
    finally:
        manager.clear()
        manager.shutdown(wait=True)

asyncio.run(main())
