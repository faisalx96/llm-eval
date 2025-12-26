from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from queue import Queue, Empty
from typing import Any, Dict, Optional
from urllib import request


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _post_json(url: str, payload: Dict[str, Any], api_key: str) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else {}


def _post_ndjson(url: str, ndjson: str, api_key: str) -> None:
    data = ndjson.encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/x-ndjson",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=30) as resp:
        resp.read()


@dataclass
class PlatformRunHandle:
    run_id: str
    live_url: str


class PlatformEventStream:
    """Background NDJSON event streamer.

    Minimal, dependency-free implementation using stdlib urllib.
    """

    def __init__(self, platform_url: str, api_key: str, run_id: str) -> None:
        self.platform_url = platform_url.rstrip("/")
        self.api_key = api_key
        self.run_id = run_id
        self._seq = 0
        self._q: "Queue[dict[str, Any]]" = Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="llm-eval-platform-stream", daemon=True)
        self._thread.start()

    def next_sequence(self) -> int:
        self._seq += 1
        return self._seq

    def emit(self, type_: str, payload: Dict[str, Any]) -> None:
        evt = {
            "schema_version": 1,
            "event_id": str(uuid.uuid4()),
            "sequence": self.next_sequence(),
            "sent_at": _utc_now(),
            "type": type_,
            "run_id": self.run_id,
            "payload": payload,
        }
        self._q.put(evt)

    def close(self) -> None:
        self._stop.set()
        try:
            self._thread.join(timeout=2)
        except Exception:
            pass

    def _loop(self) -> None:
        batch: list[dict[str, Any]] = []
        last_flush = time.time()
        while not self._stop.is_set():
            try:
                evt = self._q.get(timeout=0.25)
                batch.append(evt)
            except Empty:
                pass
            now = time.time()
            should_flush = (len(batch) >= 25) or (batch and (now - last_flush) >= 1.0)
            if not should_flush:
                continue
            try:
                ndjson = "\n".join(json.dumps(e, ensure_ascii=False) for e in batch) + "\n"
                _post_ndjson(f"{self.platform_url}/v1/runs/{self.run_id}/events", ndjson, self.api_key)
                batch.clear()
                last_flush = now
            except Exception:
                # Best-effort; keep events for retry on next loop.
                time.sleep(0.5)


class PlatformClient:
    def __init__(self, platform_url: str, api_key: str) -> None:
        self.platform_url = platform_url.rstrip("/")
        self.api_key = api_key

    def create_run(
        self,
        *,
        external_run_id: Optional[str],
        task: str,
        dataset: str,
        model: Optional[str],
        metrics: list[str],
        run_metadata: Dict[str, Any],
        run_config: Dict[str, Any],
    ) -> PlatformRunHandle:
        payload = {
            "external_run_id": external_run_id,
            "task": task,
            "dataset": dataset,
            "model": model,
            "metrics": metrics,
            "run_metadata": run_metadata,
            "run_config": run_config,
        }
        data = _post_json(f"{self.platform_url}/v1/runs", payload, self.api_key)
        run_id = str(data.get("run_id") or "")
        live_url = str(data.get("live_url") or "")
        if not run_id or not live_url:
            raise RuntimeError(f"Platform did not return run_id/live_url: {data}")
        return PlatformRunHandle(run_id=run_id, live_url=live_url)


