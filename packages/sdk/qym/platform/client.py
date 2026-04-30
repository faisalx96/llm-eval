from __future__ import annotations

import json
import math
import os
import sys
import threading
import time
import uuid
from dataclasses import asdict, is_dataclass
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timezone
from queue import Queue, Empty
from pathlib import Path
from typing import Any, Dict, Optional
from urllib import request

# Enable debug logging with QYM_PLATFORM_DEBUG=1 or QYM_PLATFORM_DEBUG=/path/to/file.log
_DEBUG = os.environ.get("QYM_PLATFORM_DEBUG", "")
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


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively coerce platform event payloads into JSON-safe values."""
    if obj is None or isinstance(obj, (str, int, bool)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, (datetime, date, dt_time)):
        return obj.isoformat()
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, Path):
        return str(obj)
    if is_dataclass(obj) and not isinstance(obj, type):
        return _sanitize_for_json(asdict(obj))
    if isinstance(obj, dict):
        return {str(k): _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_sanitize_for_json(v) for v in obj]
    if hasattr(obj, "model_dump"):
        try:
            return _sanitize_for_json(obj.model_dump(mode="json"))
        except Exception:
            try:
                return _sanitize_for_json(obj.model_dump())
            except Exception:
                pass
    if hasattr(obj, "dict"):
        try:
            return _sanitize_for_json(obj.dict())
        except Exception:
            pass
    return str(obj)


def _post_json(url: str, payload: Dict[str, Any], api_key: str, *, timeout: float = 30) -> Dict[str, Any]:
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
    with request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else {}


def _post_ndjson(url: str, ndjson: str, api_key: str, *, timeout: float = 30) -> None:
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
    with request.urlopen(req, timeout=timeout) as resp:
        resp.read()


@dataclass
class PlatformRunHandle:
    run_id: str
    live_url: str


class PlatformEventStream:
    """Background NDJSON event streamer.

    Minimal, dependency-free implementation using stdlib urllib.
    """

    # Raised from 2.0 to 15.0: on a clean shutdown with a slow platform API,
    # we'd rather wait a few extra seconds than silently drop metric scores.
    CLOSE_JOIN_TIMEOUT = 15.0
    SYNC_SEND_TIMEOUT = 2.0
    SYNC_SEND_RETRIES = 1
    HEARTBEAT_INTERVAL = 15.0
    # Default wall-clock budget for flush() barriers between items.
    FLUSH_TIMEOUT = 10.0

    def __init__(self, platform_url: str, api_key: str, run_id: str) -> None:
        self.platform_url = platform_url.rstrip("/")
        self.api_key = api_key
        self.run_id = run_id
        self._seq = 0
        self._seq_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._q: "Queue[dict[str, Any]]" = Queue()
        self._stop = threading.Event()
        self._closing = False
        self._closed = False
        # Daemonize so a stuck flush cannot pin the CLI after the run has finished.
        self._thread = threading.Thread(target=self._loop, name="qym-platform-stream", daemon=True)
        self._thread.start()

    def next_sequence(self) -> int:
        with self._seq_lock:
            self._seq += 1
            return self._seq

    def _build_event(self, type_: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "event_id": str(uuid.uuid4()),
            "sequence": self.next_sequence(),
            "sent_at": _utc_now(),
            "type": type_,
            "run_id": self.run_id,
            "payload": _sanitize_for_json(payload),
        }

    def _send_event_sync(self, evt: Dict[str, Any], *, reason: str) -> None:
        ndjson = json.dumps(evt, ensure_ascii=False) + "\n"
        _debug(f"direct emit ({reason}): {evt.get('type', '?')}")
        for attempt in range(self.SYNC_SEND_RETRIES):
            try:
                _post_ndjson(
                    f"{self.platform_url}/v1/runs/{self.run_id}/events",
                    ndjson,
                    self.api_key,
                    timeout=self.SYNC_SEND_TIMEOUT,
                )
                _debug(f"direct emit success: {evt.get('type', '?')}")
                return
            except Exception as e:
                _debug(
                    f"direct emit error (attempt {attempt + 1}/{self.SYNC_SEND_RETRIES}): {e}"
                )
                if attempt + 1 < self.SYNC_SEND_RETRIES:
                    time.sleep(0.5)
        _debug(
            f"direct emit FAILED after {self.SYNC_SEND_RETRIES} attempt(s): {evt.get('type', '?')}"
        )

    def emit(self, type_: str, payload: Dict[str, Any], *, sync: bool = False) -> None:
        evt = self._build_event(type_, payload)
        with self._state_lock:
            closing = self._closing or self._closed or not self._thread.is_alive()
        if sync or closing:
            # Send synchronously for critical events (e.g., run_completed) and
            # for any event emitted during/after shutdown.
            reason = "sync" if sync else "closing"
            self._send_event_sync(evt, reason=reason)
        else:
            self._q.put(evt)

    def flush(self, timeout: Optional[float] = None) -> bool:
        """Block until the background queue is empty (all events sent or dropped).

        Returns True if the queue was successfully drained within the timeout,
        False if the timeout elapsed first. Callers can use this between items
        to guarantee that metric emits are durable before the next item runs —
        this is what prevents the "phantom 100% score" class of bugs where a
        fast metric's emit is lost when an item is cancelled mid-flight.

        Uses ``Queue.join()`` semantics; the flush loop calls ``task_done()``
        for every event it dequeues and subsequently sends OR drops.
        """
        if timeout is None:
            timeout = self.FLUSH_TIMEOUT
        with self._state_lock:
            if self._closed or not self._thread.is_alive():
                return True  # nothing in flight
        # Queue.join() doesn't support a timeout natively, so wait in a helper
        # thread and gate on an Event we can poll with a wall-clock budget.
        done = threading.Event()

        def _waiter():
            try:
                self._q.join()
            finally:
                done.set()

        waiter = threading.Thread(target=_waiter, name="qym-platform-flush-waiter", daemon=True)
        waiter.start()
        return done.wait(timeout=timeout)

    def close(self) -> None:
        # Request stop and wait for a final flush.
        with self._state_lock:
            if self._closed or self._closing:
                return
            self._closing = True
        qsize = self._q.qsize()
        _debug(f"close() called, queue size={qsize}, seq={self._seq}")
        # Drain the queue first (best-effort) so we don't silently drop buffered
        # metric_scored events at shutdown.
        try:
            self.flush(timeout=self.CLOSE_JOIN_TIMEOUT)
        except Exception as e:
            _debug(f"close() flush exception: {e}")
        self._stop.set()
        try:
            # Bound shutdown so the CLI does not appear stuck after the run is done.
            self._thread.join(timeout=self.CLOSE_JOIN_TIMEOUT)
            if self._thread.is_alive():
                _debug(
                    f"WARNING: flush thread still alive after {self.CLOSE_JOIN_TIMEOUT}s timeout"
                )
            else:
                _debug("flush thread joined successfully")
        except Exception as e:
            _debug(f"close() exception: {e}")
        finally:
            with self._state_lock:
                self._closed = True

    def _loop(self) -> None:
        batch: list[dict[str, Any]] = []
        # Tracks how many events in `batch` came from the Queue (vs in-loop
        # heartbeats). We only call task_done() for queue-sourced events so
        # Queue.join() semantics work correctly in flush().
        queue_items_in_batch = 0
        last_flush = time.time()
        last_heartbeat = time.time()
        retry_count = 0
        max_retries = 10  # Maximum retries for a failed batch
        total_sent = 0
        total_dropped = 0
        _debug(f"flush loop started for run {self.run_id}")

        def _mark_batch_done():
            """Call task_done() once per queue-sourced event and reset the counter."""
            nonlocal queue_items_in_batch
            for _ in range(queue_items_in_batch):
                try:
                    self._q.task_done()
                except ValueError:
                    # task_done() called more times than items — shouldn't happen
                    # but don't crash the flush loop on a bookkeeping mistake.
                    break
            queue_items_in_batch = 0

        while True:
            try:
                evt = self._q.get(timeout=0.1)  # Check more frequently
                batch.append(evt)
                queue_items_in_batch += 1
            except Empty:
                pass
            now = time.time()
            if not self._stop.is_set() and (now - last_heartbeat) >= self.HEARTBEAT_INTERVAL:
                batch.append(self._build_event("run_heartbeat", {"heartbeat_at": _utc_now()}))
                last_heartbeat = now
            # Flush aggressively: every 5 events or 250ms for near real-time updates
            should_flush = (len(batch) >= 5) or (batch and (now - last_flush) >= 0.25)
            # If we're stopping, flush whatever we have (and drain the queue).
            if self._stop.is_set():
                try:
                    while True:
                        evt2 = self._q.get_nowait()
                        batch.append(evt2)
                        queue_items_in_batch += 1
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
                _mark_batch_done()
                batch.clear()
                last_flush = now
                last_heartbeat = now
                retry_count = 0
            except Exception as e:
                retry_count += 1
                _debug(f"flush error (attempt {retry_count}/{max_retries}): {e}")
                if retry_count >= 3 and len(batch) > 1:
                    # Batch keeps failing — send events individually so one
                    # bad event can't take down the rest (e.g. item_completed).
                    _debug(f"falling back to per-event send for {len(batch)} events")
                    for evt in batch:
                        try:
                            line = json.dumps(evt, ensure_ascii=False) + "\n"
                            _post_ndjson(f"{self.platform_url}/v1/runs/{self.run_id}/events", line, self.api_key)
                            total_sent += 1
                        except Exception as e2:
                            total_dropped += 1
                            _debug(f"dropped event {evt.get('type','?')} seq={evt.get('sequence','?')}: {e2}")
                    _mark_batch_done()
                    batch.clear()
                    retry_count = 0
                elif retry_count >= max_retries:
                    total_dropped += len(batch)
                    _debug(f"DROPPED {len(batch)} events after {max_retries} retries (total dropped: {total_dropped})")
                    _mark_batch_done()
                    batch.clear()
                    retry_count = 0
                else:
                    time.sleep(0.5)
            if self._stop.is_set() and not batch:
                try:
                    evt3 = self._q.get_nowait()
                except Empty:
                    _debug(f"flush loop exiting: sent={total_sent}, dropped={total_dropped}")
                    break
                else:
                    batch.append(evt3)
                    queue_items_in_batch += 1


class PlatformClient:
    CREATE_RUN_TIMEOUT = 5.0

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
        timeout: Optional[float] = None,
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
        data = _post_json(
            f"{self.platform_url}/v1/runs",
            payload,
            self.api_key,
            timeout=timeout if timeout is not None else self.CREATE_RUN_TIMEOUT,
        )
        run_id = str(data.get("run_id") or "")
        live_url = str(data.get("live_url") or "")
        if not run_id or not live_url:
            raise RuntimeError(f"Platform did not return run_id/live_url: {data}")
        return PlatformRunHandle(run_id=run_id, live_url=live_url)
