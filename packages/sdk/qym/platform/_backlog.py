"""Bounded event FIFO with private, capped disk spill for synchronous producers."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from collections import deque
from queue import Empty, Full
from typing import Any, Deque, Dict, Optional


class EventBacklog:
    """Keep serialized events in memory, then spill FIFO records to a private file.

    The disk file is truncated when its queued records have been consumed. A full
    disk allowance applies backpressure until the consumer reaches that boundary.
    Capacity excludes the uploader's separately count/byte-bounded active batch.
    """

    def __init__(self, max_memory_bytes: int, max_disk_bytes: int) -> None:
        if max_memory_bytes <= 0 or max_disk_bytes <= 0:
            raise ValueError("Platform backlog byte limits must be positive")
        self.max_memory_bytes = max_memory_bytes
        self.max_disk_bytes = max_disk_bytes
        self.memory_bytes = 0
        self.disk_bytes = 0
        self.peak_memory_bytes = 0
        self.peak_disk_bytes = 0
        self.spilled_events = 0
        self.unfinished_tasks = 0
        self._memory: Deque[bytes] = deque()
        self._disk_count = 0
        self._read_offset = 0
        self._file: Optional[tempfile._TemporaryFileWrapper[bytes]] = None
        self.spool_path: Optional[str] = None
        self._cv = threading.Condition()
        self._disposed = False

    @staticmethod
    def serialize(event: Dict[str, Any]) -> bytes:
        return (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")

    def put(self, event: Dict[str, Any], block: bool = True, timeout=None) -> None:
        self.put_serialized(self.serialize(event), block=block, timeout=timeout)

    def put_serialized(self, data: bytes, block: bool = True, timeout=None) -> None:
        # Account for the byte object's and deque slot's fixed storage too.
        memory_size = len(data) + 64
        if memory_size > self.max_memory_bytes and len(data) > self.max_disk_bytes:
            raise ValueError("Platform event exceeds both backlog byte limits")
        deadline = None if timeout is None else time.monotonic() + timeout
        if not self._cv.acquire(blocking=block):
            raise Full
        try:
            while True:
                if self._disposed:
                    raise RuntimeError("Platform event backlog is closed")
                if (
                    not self._disk_count
                    and self.memory_bytes + memory_size <= self.max_memory_bytes
                ):
                    self._memory.append(data)
                    self.memory_bytes += memory_size
                    self.peak_memory_bytes = max(
                        self.peak_memory_bytes, self.memory_bytes
                    )
                    break
                if self.disk_bytes + len(data) <= self.max_disk_bytes:
                    # Nonblocking async producers never perform disk I/O. Their
                    # caller retries this path in a worker thread.
                    if not block:
                        raise Full
                    if self._file is None:
                        self._file = tempfile.NamedTemporaryFile(
                            prefix="qym-platform-events-",
                            suffix=".ndjson",
                            delete=False,
                        )
                        self.spool_path = self._file.name
                    self._file.seek(self.disk_bytes)
                    try:
                        self._file.write(data)
                        self._file.flush()
                    except Exception:
                        # Keep earlier accepted records readable after a partial
                        # append, without advancing counters for the failed one.
                        try:
                            self._file.seek(self.disk_bytes)
                            self._file.truncate(self.disk_bytes)
                        except Exception:
                            pass
                        raise
                    self.disk_bytes += len(data)
                    self._disk_count += 1
                    self.spilled_events += 1
                    self.peak_disk_bytes = max(self.peak_disk_bytes, self.disk_bytes)
                    break
                if not block:
                    raise Full
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise Full
                self._cv.wait(remaining)
            self.unfinished_tasks += 1
            self._cv.notify_all()
        finally:
            self._cv.release()

    def get(self, block: bool = True, timeout=None) -> Dict[str, Any]:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cv:
            while not self._memory and not self._disk_count:
                if not block:
                    raise Empty
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise Empty
                self._cv.wait(remaining)
            if self._memory:
                data = self._memory.popleft()
                self.memory_bytes -= len(data) + 64
            else:
                assert self._file is not None
                self._file.seek(self._read_offset)
                data = self._file.readline()
                self._read_offset += len(data)
                self._disk_count -= 1
                if not self._disk_count:
                    self._file.seek(0)
                    self._file.truncate(0)
                    self._file.flush()
                    self._read_offset = self.disk_bytes = 0
            self._cv.notify_all()
        return json.loads(data)

    def get_nowait(self):
        return self.get(block=False)

    def qsize(self) -> int:
        with self._cv:
            return len(self._memory) + self._disk_count

    def task_done(self) -> None:
        with self._cv:
            if self.unfinished_tasks <= 0:
                raise ValueError("task_done() called too many times")
            self.unfinished_tasks -= 1
            self._cv.notify_all()

    def wait_drained(self, timeout: Optional[float] = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cv:
            while self.unfinished_tasks:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._cv.wait(remaining)
            return True

    def join(self) -> None:
        self.wait_drained()

    def dispose(self) -> None:
        """Remove an empty spool only after every event has a delivery verdict."""
        with self._cv:
            if self.unfinished_tasks:
                return
            self._disposed = True
            if self._file is not None:
                assert self.spool_path is not None
                self._file.close()
                self._file = None
                os.unlink(self.spool_path)
                self.spool_path = None
            self._cv.notify_all()
