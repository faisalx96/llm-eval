import asyncio, json, os, tempfile, time, warnings
from types import SimpleNamespace
from unittest.mock import patch
from openai import AsyncOpenAI
from qym.core.dataset import InMemoryDataset
from qym.core.evaluator import Evaluator
from qym.metrics.judge_config import JudgeConfig
from qym.metrics.judges.base import llm_judge

warnings.simplefilter("ignore")
os.chdir(tempfile.mkdtemp(prefix="qym-p1-client-bench-"))
clients = []


def track(**kwargs):
    client = AsyncOpenAI(**kwargs)
    clients.append(client)
    return client


async def fake_request(*args, **kwargs):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content='{"verdict":"yes","explanation":"ok"}')
            )
        ]
    )


async def task(input):
    return input


async def metric(output, expected):
    return await llm_judge(
        system_prompt="test",
        user_prompt="test",
        choices={"yes": 1.0},
        config=JudgeConfig(
            model="test", api_key="not-real", base_url="http://127.0.0.1:9/v1"
        ),
    )


async def main():
    with patch("openai.AsyncOpenAI", track), patch(
        "qym.metrics.judges.base._call_with_retry", fake_request
    ):
        ev = Evaluator(
            task,
            InMemoryDataset([{"input": "hi", "expected": "hi"} for _ in range(100)]),
            [metric],
            config={
                "otel_enabled": False,
                "live_mode": "local",
                "checkpoint_enabled": False,
            },
        )
        start = time.perf_counter()
        result = await ev.arun(show_tui=False)
        print(
            json.dumps(
                {
                    "seconds": round(time.perf_counter() - start, 6),
                    "created_clients": len(clients),
                    "unclosed_clients": sum(not c.is_closed() for c in clients),
                    "results": len(result.results),
                    "errors": len(result.errors),
                }
            )
        )
    for client in clients:
        await client.close()


asyncio.run(main())
