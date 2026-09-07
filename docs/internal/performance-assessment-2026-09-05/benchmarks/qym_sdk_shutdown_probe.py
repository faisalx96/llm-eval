"""Mock-network probe showing synchronous stream shutdown blocking event loop."""
import asyncio, json, os, tempfile, time, warnings
from unittest.mock import patch
from qym.core.dataset import InMemoryDataset
from qym.core.evaluator import Evaluator
from qym.platform.client import PlatformRunHandle
warnings.simplefilter('ignore')
os.chdir(tempfile.mkdtemp(prefix='qym-shutdown-perf-'))
async def echo(input):
    await asyncio.sleep(0.02)
    return input
async def main():
    ticks=[]
    stop=False
    async def heartbeat():
        while not stop:
            ticks.append(time.perf_counter())
            await asyncio.sleep(0.01)
    def delayed_post(*args,**kwargs):
        time.sleep(0.15)
    with patch('qym.core.evaluator.PlatformClient.create_run',return_value=PlatformRunHandle('fake-run','http://127.0.0.1:9/r/fake-run')), patch('qym.platform.client._post_ndjson',delayed_post):
        ev=Evaluator(echo,InMemoryDataset([{'input':'hi','expected':'hi'}]),['exact_match'],config={'run_name':'shutdown-probe','otel_enabled':False,'live_mode':'platform','platform_url':'http://127.0.0.1:9','platform_api_key':'fake-key','checkpoint_enabled':False})
        hb=asyncio.create_task(heartbeat())
        await asyncio.sleep(0.03)
        started=time.perf_counter()
        await ev.arun(show_tui=False)
        duration=time.perf_counter()-started
        await asyncio.sleep(0.03)
        stop=True
        await hb
        print(json.dumps({'case':'single_item_platform_shutdown','seconds':round(duration,4),'mock_post_latency_seconds':0.15,'heartbeat_interval_seconds':0.01,'max_heartbeat_gap_seconds':round(max(b-a for a,b in zip(ticks,ticks[1:])),4)}))
asyncio.run(main())
