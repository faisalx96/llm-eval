"""Read-only SDK microbenchmarks. Run with the repo's installed Python environment.
No external requests: eval runs offline, and judge network function is mocked.
The script creates temporary checkpoint files outside the repository.
"""
import asyncio
import contextlib
import io
import json
import logging
import os
import tempfile
import threading
import time
import warnings
from types import SimpleNamespace
from unittest.mock import patch
from qym.core.dataset import InMemoryDataset
from qym.core.evaluator import Evaluator
from qym.core.observers import ProgressCallbackObserver
from qym.metrics.judges.base import llm_judge
from qym.metrics.judge_config import JudgeConfig
from openai import AsyncOpenAI
warnings.simplefilter('ignore', DeprecationWarning)
logging.getLogger('qym').setLevel(logging.CRITICAL)
os.chdir(tempfile.mkdtemp(prefix='qym-sdk-perf-'))

def report(**data):
    print(json.dumps(data), flush=True)

async def echo(input):
    return input

async def run_eval(n, callback=False, checkpoint=False, metrics=None, metric_concurrency=1, item_concurrency=10):
    ds=InMemoryDataset([{'input':'hello', 'expected':'hello'} for _ in range(n)])
    ev=Evaluator(echo, ds, ['exact_match'] if metrics is None else metrics,
        config={'run_name':f'bench-{n}-{callback}-{checkpoint}', 'otel_enabled':False,
                'live_mode':'local', 'checkpoint_enabled':checkpoint,
                'max_metric_concurrency':metric_concurrency, 'max_concurrency':item_concurrency},
        progress_callback=(lambda snapshot:None) if callback else None)
    start=time.perf_counter()
    result=await ev.arun(show_tui=False)
    report(case='full_eval', items=n, callback=callback, checkpoint=checkpoint,
           metric_count=len(ev.metrics),metric_concurrency=metric_concurrency,
           seconds=round(time.perf_counter()-start,4), completed=len(result.results), errors=len(result.errors))

for n in [1000, 10000, 30000]:
    observer=ProgressCallbackObserver(lambda snapshot:None)
    observer.on_run_start('bench', {}, n, ['exact_match'])
    start=time.perf_counter()
    for i in range(n):
        observer.on_item_start('bench',i)
        observer.on_metric_result('bench',i,'exact_match',1.0)
        observer.on_item_complete('bench',i,{})
    report(case='progress_callback_only',items=n,seconds=round(time.perf_counter()-start,4))

for n in [1000,10000]:
    for callback in [False,True]:
        asyncio.run(run_eval(n,callback=callback))
for checkpoint in [False,True]:
    asyncio.run(run_eval(5000,checkpoint=checkpoint))

# Per-item async metric parallelism is opt-in, default is 1.
async def m1(output, expected):
    await asyncio.sleep(0.05)
    return 1.0
async def m2(output, expected):
    await asyncio.sleep(0.05)
    return 1.0
async def m3(output, expected):
    await asyncio.sleep(0.05)
    return 1.0
for concurrency in [1,3]:
    asyncio.run(run_eval(30, metrics=[m1,m2,m3], metric_concurrency=concurrency))

# Hold client references to inspect whether qym explicitly closes them.
# Close them ourselves immediately after the measurement.
clients=[]
def tracked_client(**kwargs):
    client=AsyncOpenAI(**kwargs)
    clients.append(client)
    return client
response=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"verdict":"yes","explanation":"ok"}'))])
async def fake_request(*args,**kwargs):
    return response
async def benchmark_judge():
    config=JudgeConfig(model='local-test', api_key='not-a-real-key', base_url='http://127.0.0.1:9/v1')
    with patch('openai.AsyncOpenAI',tracked_client), patch('qym.metrics.judges.base._call_with_retry',fake_request):
        start=time.perf_counter()
        for _ in range(100):
            await llm_judge(system_prompt='test',user_prompt='test',choices={'yes':1.0},config=config)
        report(case='judge_100_mocked_network',seconds=round(time.perf_counter()-start,4),
               created_clients=len(clients),unclosed_clients=sum(not c.is_closed() for c in clients))
    for client in clients:
        await client.close()
asyncio.run(benchmark_judge())

# Timeout cancellation of to_thread cannot stop the original synchronous function.
# With 2 item workers, retries execute another copy while the first is still active.
state={'active':0,'peak':0,'calls':0}
lock=threading.Lock()
def slow_sync(output, expected):
    with lock:
        state['active']+=1
        state['calls']+=1
        state['peak']=max(state['peak'],state['active'])
    time.sleep(0.15)
    with lock:
        state['active']-=1
    return 1.0
async def benchmark_timeout():
    ev=Evaluator(echo,InMemoryDataset([{'input':'hello','expected':'hello'}]),[slow_sync],
        config={'run_name':'sync-timeout','otel_enabled':False,'live_mode':'local','checkpoint_enabled':False,
                'max_concurrency':2,'metric_timeout':0.02,'metric_max_retries':2})
    start=time.perf_counter()
    await ev.arun(show_tui=False)
    report(case='sync_metric_timeout_before_thread_drain',seconds=round(time.perf_counter()-start,4),**state)
    await asyncio.sleep(0.2)
asyncio.run(benchmark_timeout())
