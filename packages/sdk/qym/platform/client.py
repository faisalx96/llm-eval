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

from .tls import urlopen

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
    with urlopen(req, timeout=timeout) as resp:
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
    with urlopen(req, timeout=timeout) as resp:
        resp.read()


def _is_poison_error(exc: BaseException) -> bool:
    """True when the server deterministically rejected the payload (4xx).

    Retrying such a request verbatim can never succeed, so the batch should
    be isolated per event instead. 408 (request timeout) and 429 (rate limit)
    are transient despite being 4xx.
    """
    code = getattr(exc, "code", None)
    return isinstance(code, int) and 400 <= code < 500 and code not in (408, 429)


@dataclass
class PlatformRunHandle:
    run_id: str
    live_url: str


class PlatformEventStream:
    """Background NDJSON event streamer.

    Minimal, dependency-free implementation using stdlib urllib.
    """

    # Overall close() budget: block until the queue drains or this elapses
    # (env override: QYM_PLATFORM_CLOSE_TIMEOUT). Deliberately generous —
    # abandoning the backlog silently loses run items on the platform.
    CLOSE_JOIN_TIMEOUT = 120.0
    # How often close() reports upload progress while draining.
    CLOSE_PROGRESS_INTERVAL = 2.0
    # During shutdown, give up on a dead endpoint after this many consecutive
    # send failures instead of burning the whole close budget.
    CLOSE_GIVEUP_FAILURES = 6
    SYNC_SEND_TIMEOUT = 10.0
    SYNC_SEND_RETRIES = 3
    HEARTBEAT_INTERVAL = 15.0
    # Default wall-clock budget for flush() barriers between items.
    FLUSH_TIMEOUT = 10.0
    # Batch caps per POST. Count keeps server-side work bounded; bytes keeps
    # requests under common reverse-proxy body limits.
    MAX_BATCH_EVENTS = 200
    MAX_BATCH_BYTES = 2_000_000
    # Cadence flush for near-real-time live views when the queue is quiet.
    FLUSH_INTERVAL = 0.25
    RETRY_BACKOFF_BASE = 0.5
    RETRY_BACKOFF_MAX = 10.0

    def __init__(self, platform_url: str, api_key: str, run_id: str) -> None:
        self.platform_url = platform_url.rstrip("/")
        self.api_key = api_key
        self.run_id = run_id
        # Delivery counters, updated by the flush thread; readable by callers
        # after close() to know whether the platform got everything.
        self.sent_events = 0
        self.dropped_events = 0
        self._consecutive_failures = 0
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

    def _close_timeout(self) -> float:
        raw = os.environ.get("QYM_PLATFORM_CLOSE_TIMEOUT", "")
        if raw:
            try:
                return max(0.0, float(raw))
            except ValueError:
                pass
        return float(self.CLOSE_JOIN_TIMEOUT)

    def close(self) -> None:
        """Block until the event backlog is uploaded (or the budget elapses).

        The eval workers never wait on this stream mid-run, so any queue
        backlog surfaces here, after the last item finished. Draining it is
        the difference between the platform showing the whole run and
        silently missing items — so we wait, show progress, and only give up
        after the (generous, env-tunable) budget with a loud warning.
        """
        with self._state_lock:
            if self._closed or self._closing:
                return
            self._closing = True
        timeout = self._close_timeout()
        _debug(f"close() called, queue size={self._q.qsize()}, seq={self._seq}")
        # Enter drain mode immediately: the flush loop ignores the send
        # cadence and ships batches back-to-back until the queue is empty.
        self._stop.set()
        deadline = time.time() + timeout
        printed_progress = False
        try:
            while self._thread.is_alive():
                slice_s = min(self.CLOSE_PROGRESS_INTERVAL, deadline - time.time())
                if slice_s <= 0:
                    break
                self._thread.join(timeout=slice_s)
                if self._thread.is_alive():
                    remaining = self._q.qsize()
                    if remaining:
                        printed_progress = True
                        print(
                            f"qym: uploading {remaining} remaining platform events...",
                            file=sys.stderr,
                        )
            if self._thread.is_alive():
                remaining = self._q.qsize()
                _debug(
                    f"WARNING: flush thread still alive after {timeout}s close budget"
                )
                print(
                    f"qym: WARNING: gave up waiting for the platform upload after {timeout:.0f}s; "
                    f"~{remaining} events were not delivered — the run page may be missing items. "
                    "Raise QYM_PLATFORM_CLOSE_TIMEOUT to wait longer.",
                    file=sys.stderr,
                )
            else:
                _debug("flush thread joined successfully")
                if self.dropped_events:
                    print(
                        f"qym: WARNING: {self.dropped_events} platform events failed to upload "
                        "and were dropped — the run page may be missing items. "
                        "Set QYM_PLATFORM_DEBUG=1 to log the failures.",
                        file=sys.stderr,
                    )
                elif printed_progress:
                    print("qym: platform upload complete.", file=sys.stderr)
        except Exception as e:
            _debug(f"close() exception: {e}")
        finally:
            with self._state_lock:
                self._closed = True

    def _send_events_individually(
        self, entries: "list[tuple[dict[str, Any], str, int, bool]]"
    ) -> None:
        """Poison-batch fallback: give every event its own verdict.

        Entered only after the server rejected the whole batch with a
        deterministic 4xx. Events that individually get a 4xx are dropped
        (they can never succeed); a transient blip gets one more attempt.
        """
        url = f"{self.platform_url}/v1/runs/{self.run_id}/events"
        _debug(f"falling back to per-event send for {len(entries)} events")
        for evt, line, _, _ in entries:
            for attempt in range(2):
                try:
                    _post_ndjson(url, line + "\n", self.api_key)
                    self.sent_events += 1
                    break
                except Exception as e2:
                    if _is_poison_error(e2) or attempt == 1:
                        self.dropped_events += 1
                        _debug(
                            f"dropped event {evt.get('type','?')} "
                            f"seq={evt.get('sequence','?')}: {e2}"
                        )
                        break
                    time.sleep(0.5)

    def _loop(self) -> None:
        # Each entry: (event, serialized line, encoded byte length, from_queue).
        # from_queue tells us whether to task_done() it — in-loop heartbeats
        # never went through the Queue, and Queue.join() semantics power flush().
        batch: list[tuple[dict[str, Any], str, int, bool]] = []
        batch_bytes = 0
        queue_items_in_batch = 0
        last_flush = time.time()
        last_heartbeat = time.time()
        retry_count = 0
        _debug(f"flush loop started for run {self.run_id}")

        def _append(evt: Dict[str, Any], from_queue: bool) -> None:
            nonlocal batch_bytes, queue_items_in_batch
            line = json.dumps(evt, ensure_ascii=False)
            batch.append((evt, line, len(line.encode("utf-8")), from_queue))
            batch_bytes += len(line.encode("utf-8")) + 1
            if from_queue:
                queue_items_in_batch += 1

        def _clear_batch() -> None:
            """task_done() every queue-sourced event, then reset the batch."""
            nonlocal batch_bytes, queue_items_in_batch
            for _ in range(queue_items_in_batch):
                try:
                    self._q.task_done()
                except ValueError:
                    # task_done() called more times than items — shouldn't happen
                    # but don't crash the flush loop on a bookkeeping mistake.
                    break
            queue_items_in_batch = 0
            batch.clear()
            batch_bytes = 0

        def _batch_full() -> bool:
            return (
                len(batch) >= self.MAX_BATCH_EVENTS
                or batch_bytes >= self.MAX_BATCH_BYTES
            )

        while True:
            if not _batch_full():
                try:
                    _append(self._q.get(timeout=0.1), True)
                except Empty:
                    pass
            now = time.time()
            if not self._stop.is_set() and (now - last_heartbeat) >= self.HEARTBEAT_INTERVAL:
                _append(self._build_event("run_heartbeat", {"heartbeat_at": _utc_now()}), False)
                last_heartbeat = now
            # Flush on a full batch or on cadence for near-real-time updates.
            should_flush = bool(batch) and (
                _batch_full() or (now - last_flush) >= self.FLUSH_INTERVAL
            )
            if self._stop.is_set():
                # Drain mode: fill up to the caps and ship without waiting.
                try:
                    while not _batch_full():
                        _append(self._q.get_nowait(), True)
                except Empty:
                    pass
                should_flush = bool(batch)
                if should_flush:
                    _debug(f"final flush: {len(batch)} events")
            if not should_flush and not self._stop.is_set():
                continue
            if should_flush:
                try:
                    ndjson = "\n".join(line for _, line, _, _ in batch) + "\n"
                    _post_ndjson(
                        f"{self.platform_url}/v1/runs/{self.run_id}/events",
                        ndjson,
                        self.api_key,
                        timeout=10 if self._stop.is_set() else 30,
                    )
                    self.sent_events += len(batch)
                    _debug(f"flushed {len(batch)} events (total sent: {self.sent_events})")
                    _clear_batch()
                    last_flush = time.time()
                    last_heartbeat = last_flush
                    retry_count = 0
                    self._consecutive_failures = 0
                except Exception as e:
                    retry_count += 1
                    self._consecutive_failures += 1
                    if _is_poison_error(e):
                        # Deterministic 4xx: retrying the batch verbatim can
                        # never succeed — isolate per event instead.
                        _debug(f"batch rejected ({e}); isolating per event")
                        self._send_events_individually(batch)
                        _clear_batch()
                        retry_count = 0
                    elif (
                        self._stop.is_set()
                        and self._consecutive_failures >= self.CLOSE_GIVEUP_FAILURES
                    ):
                        # Shutting down against an endpoint that keeps failing:
                        # stop burning the close budget, count the loss loudly.
                        self.dropped_events += len(batch)
                        _debug(
                            f"DROPPED {len(batch)} events during shutdown after "
                            f"{self._consecutive_failures} consecutive failures "
                            f"(total dropped: {self.dropped_events})"
                        )
                        _clear_batch()
                        retry_count = 0
                    else:
                        # Transient (network/5xx/429): retry with capped backoff.
                        # Never drop mid-run — the server dedups by event_id, so
                        # redelivery is always safe.
                        backoff = min(
                            self.RETRY_BACKOFF_BASE * (2 ** min(retry_count - 1, 5)),
                            self.RETRY_BACKOFF_MAX,
                        )
                        _debug(
                            f"flush error (attempt {retry_count}), retrying in "
                            f"{backoff:.1f}s: {e}"
                        )
                        time.sleep(backoff)
            if self._stop.is_set() and not batch:
                try:
                    _append(self._q.get_nowait(), True)
                except Empty:
                    _debug(
                        f"flush loop exiting: sent={self.sent_events}, "
                        f"dropped={self.dropped_events}"
                    )
                    break


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
        dataset_id: Optional[str] = None,
        dataset_version_id: Optional[str] = None,
        dataset_alias: Optional[str] = None,
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
            "dataset_id": dataset_id,
            "dataset_version_id": dataset_version_id,
            "dataset_alias": dataset_alias,
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

    def get_dataset_items(
        self,
        *,
        dataset: str,
        version: Optional[str] = None,
        alias: Optional[str] = None,
        project_slug: Optional[str] = None,
        limit: int = 1000,
    ) -> Dict[str, Any]:
        import urllib.parse

        ref = urllib.parse.quote(dataset, safe="")
        version_ref = urllib.parse.quote(version or alias or "production", safe="")
        params = {"limit": str(limit)}
        if project_slug:
            params["project_slug"] = project_slug
        url = (
            f"{self.platform_url}/v1/datasets/{ref}/versions/{version_ref}/items?"
            + urllib.parse.urlencode(params)
        )
        req = request.Request(url, headers={"Authorization": f"Bearer {self.api_key}"})
        with request.urlopen(req, timeout=self.CREATE_RUN_TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}

    def upload_dataset(
        self,
        *,
        path: str,
        name: str,
        version: str,
        publish: bool = False,
        set_alias: Optional[str] = None,
        input_col: str = "input",
        expected_col: str = "expected_output",
        id_col: Optional[str] = None,
        metadata_cols: Optional[str] = None,
        labels: Optional[str] = None,
        project_slug: Optional[str] = None,
    ) -> Dict[str, Any]:
        import mimetypes
        import urllib.request
        from pathlib import Path

        file_path = Path(path)
        boundary = "----qym-dataset-" + uuid.uuid4().hex
        fields = {
            "name": name,
            "version": version,
            "publish": "true" if publish else "false",
            "input_col": input_col,
            "expected_col": expected_col,
            "metadata_cols": metadata_cols or "",
            "labels": labels or "",
        }
        if project_slug:
            fields["project_slug"] = project_slug
        if id_col:
            fields["id_col"] = id_col
        if set_alias:
            fields["set_alias"] = set_alias
        lines: list[bytes] = []
        for key, value in fields.items():
            lines.extend([
                f"--{boundary}".encode(),
                f'Content-Disposition: form-data; name="{key}"'.encode(),
                b"",
                str(value).encode("utf-8"),
            ])
        raw = file_path.read_bytes()
        ctype = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        lines.extend([
            f"--{boundary}".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"'.encode(),
            f"Content-Type: {ctype}".encode(),
            b"",
            raw,
            f"--{boundary}--".encode(),
            b"",
        ])
        body = b"\r\n".join(lines)
        req = urllib.request.Request(
            f"{self.platform_url}/v1/datasets:upload",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = resp.read().decode("utf-8")
            return json.loads(payload) if payload else {}
