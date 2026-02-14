from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from queue import Queue, Empty
from typing import Any, Dict, Optional
from urllib import request

# Enable debug logging with LLM_EVAL_PLATFORM_DEBUG=1 or LLM_EVAL_PLATFORM_DEBUG=/path/to/file.log
_DEBUG = os.environ.get("LLM_EVAL_PLATFORM_DEBUG", "")
_DEBUG_FILE = None
if _DEBUG and _DEBUG.lower() not in ("0", "false", "no", ""):
    if _DEBUG.lower() in ("1", "true", "yes"):
        _DEBUG_FILE = sys.stderr
    else:
        # Treat as file path
        try:
            _DEBUG_FILE = open(_DEBUG, "a", buffering=1)  # Line-buffered
        except Exception:
            _DEBUG_FILE = sys.stderr


def _debug(msg: str) -> None:
    if _DEBUG_FILE:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{ts}] [platform-stream] {msg}", file=_DEBUG_FILE, flush=True)


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
        # Non-daemon thread ensures events are flushed before program exits
        self._thread = threading.Thread(target=self._loop, name="llm-eval-platform-stream", daemon=False)
        self._thread.start()

    def next_sequence(self) -> int:
        self._seq += 1
        return self._seq

    def emit(self, type_: str, payload: Dict[str, Any], *, sync: bool = False) -> None:
        evt = {
            "schema_version": 1,
            "event_id": str(uuid.uuid4()),
            "sequence": self.next_sequence(),
            "sent_at": _utc_now(),
            "type": type_,
            "run_id": self.run_id,
            "payload": payload,
        }
        if sync:
            # Send synchronously for critical events (e.g., run_completed)
            _debug(f"sync emit: {type_}")
            ndjson = json.dumps(evt, ensure_ascii=False) + "\n"
            for attempt in range(3):
                try:
                    _post_ndjson(f"{self.platform_url}/v1/runs/{self.run_id}/events", ndjson, self.api_key)
                    _debug(f"sync emit success: {type_}")
                    return
                except Exception as e:
                    _debug(f"sync emit error (attempt {attempt + 1}/3): {e}")
                    time.sleep(0.5)
            _debug(f"sync emit FAILED after 3 attempts: {type_}")
        else:
            self._q.put(evt)

    def close(self) -> None:
        # Request stop and wait for a final flush.
        qsize = self._q.qsize()
        _debug(f"close() called, queue size={qsize}, seq={self._seq}")
        self._stop.set()
        try:
            # Wait up to 30 seconds for all events to be flushed
            self._thread.join(timeout=30)
            if self._thread.is_alive():
                _debug("WARNING: flush thread still alive after 30s timeout")
            else:
                _debug("flush thread joined successfully")
        except Exception as e:
            _debug(f"close() exception: {e}")

    def _loop(self) -> None:
        batch: list[dict[str, Any]] = []
        last_flush = time.time()
        retry_count = 0
        max_retries = 10  # Maximum retries for a failed batch
        total_sent = 0
        total_dropped = 0
        _debug(f"flush loop started for run {self.run_id}")
        while True:
            try:
                evt = self._q.get(timeout=0.1)  # Check more frequently
                batch.append(evt)
            except Empty:
                pass
            now = time.time()
            # Flush aggressively: every 5 events or 250ms for near real-time updates
            should_flush = (len(batch) >= 5) or (batch and (now - last_flush) >= 0.25)
            # If we're stopping, flush whatever we have (and drain the queue).
            if self._stop.is_set():
                try:
                    while True:
                        evt2 = self._q.get_nowait()
                        batch.append(evt2)
                except Empty:
                    pass
                should_flush = bool(batch)
                if should_flush:
                    _debug(f"final flush: {len(batch)} events")
            if not should_flush and not self._stop.is_set():
                continue
            try:
                ndjson = "\n".join(json.dumps(e, ensure_ascii=False) for e in batch) + "\n"
                _post_ndjson(f"{self.platform_url}/v1/runs/{self.run_id}/events", ndjson, self.api_key)
                total_sent += len(batch)
                _debug(f"flushed {len(batch)} events (total sent: {total_sent})")
                batch.clear()
                last_flush = now
                retry_count = 0  # Reset on success
            except Exception as e:
                retry_count += 1
                _debug(f"flush error (attempt {retry_count}/{max_retries}): {e}")
                if retry_count >= max_retries:
                    # Give up after max retries to prevent hanging
                    total_dropped += len(batch)
                    _debug(f"DROPPED {len(batch)} events after {max_retries} retries (total dropped: {total_dropped})")
                    batch.clear()
                    retry_count = 0
                else:
                    # Best-effort; keep events for retry on next loop.
                    time.sleep(0.5)
            if self._stop.is_set() and not batch:
                _debug(f"flush loop exiting: sent={total_sent}, dropped={total_dropped}")
                break


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
