"""Before/after tests for blocking-async detection (Fix #5).

Tests use a canary coroutine to measure event-loop starvation caused by
a blocking async task, proving the problem is real and the warning fires.
No auto-remediation — the fix is warn-only.
"""

import asyncio
import logging
import time

import pytest
from unittest.mock import MagicMock

from qym.adapters.base import FunctionAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_adapter(func):
    """Create a FunctionAdapter with a mock Langfuse client."""
    FunctionAdapter._blocking_warned = set()
    adapter = FunctionAdapter(func, client=MagicMock())
    return adapter


def _make_trace():
    trace = MagicMock()
    trace.trace_id = "test-trace-id"
    trace.id = "test-id"
    return trace


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------

class TestBlockingDetection:

    @pytest.mark.asyncio
    async def test_blocking_async_detected(self, caplog):
        """An async function with time.sleep must trigger a warning."""

        async def blocking_task(x):
            time.sleep(1.5)
            return f"result:{x}"

        adapter = _make_adapter(blocking_task)

        with caplog.at_level(logging.WARNING, logger="qym.adapters.base"):
            result = await adapter.arun("hello", _make_trace())

        assert result == "result:hello"
        warnings = [r for r in caplog.records if "block the event loop" in r.message]
        assert len(warnings) == 1

    @pytest.mark.asyncio
    async def test_wellbehaved_async_not_flagged(self, caplog):
        """A proper async function must NOT trigger a warning."""

        async def good_task(x):
            await asyncio.sleep(1.5)
            return f"result:{x}"

        adapter = _make_adapter(good_task)

        with caplog.at_level(logging.WARNING, logger="qym.adapters.base"):
            result = await adapter.arun("hello", _make_trace())

        assert result == "result:hello"
        warnings = [r for r in caplog.records if "block the event loop" in r.message]
        assert len(warnings) == 0

    @pytest.mark.asyncio
    async def test_fast_blocking_below_threshold(self, caplog):
        """Blocking under the 1s threshold must NOT trigger."""

        async def quick_block(x):
            time.sleep(0.3)
            return x

        adapter = _make_adapter(quick_block)

        with caplog.at_level(logging.WARNING, logger="qym.adapters.base"):
            await adapter.arun("test", _make_trace())

        warnings = [r for r in caplog.records if "block the event loop" in r.message]
        assert len(warnings) == 0

    @pytest.mark.asyncio
    async def test_warning_emitted_exactly_once(self, caplog):
        """Repeated calls to the same blocker produce exactly one warning."""

        async def blocking_task(x):
            time.sleep(1.5)
            return x

        adapter = _make_adapter(blocking_task)
        trace = _make_trace()

        with caplog.at_level(logging.WARNING, logger="qym.adapters.base"):
            await adapter.arun("a", trace)
            await adapter.arun("b", trace)

        warnings = [r for r in caplog.records if "block the event loop" in r.message]
        assert len(warnings) == 1

    @pytest.mark.asyncio
    async def test_detection_fires_when_task_raises(self, caplog):
        """A blocking task that also raises must still trigger the warning."""

        async def blocking_then_raise(x):
            time.sleep(1.5)
            raise ValueError("task failed")

        adapter = _make_adapter(blocking_then_raise)

        with caplog.at_level(logging.WARNING, logger="qym.adapters.base"):
            with pytest.raises(ValueError, match="task failed"):
                await adapter.arun("hello", _make_trace())

        warnings = [r for r in caplog.records if "block the event loop" in r.message]
        assert len(warnings) == 1, (
            "Detection must fire even when the task raises — "
            f"got {len(warnings)} warnings"
        )

    @pytest.mark.asyncio
    async def test_sync_function_not_affected(self, caplog):
        """Plain sync functions use run_in_executor — no detection needed."""

        def sync_task(x):
            time.sleep(0.5)
            return f"sync:{x}"

        adapter = _make_adapter(sync_task)

        with caplog.at_level(logging.WARNING, logger="qym.adapters.base"):
            result = await adapter.arun("hello", _make_trace())

        assert result == "sync:hello"
        warnings = [r for r in caplog.records if "block the event loop" in r.message]
        assert len(warnings) == 0

    @pytest.mark.asyncio
    async def test_heartbeat_skipped_after_clean_probes(self):
        """After _PROBE_INITIAL clean calls, heartbeat is skipped (until next periodic probe)."""

        async def fast_task(x):
            await asyncio.sleep(1.1)  # above 1s threshold but non-blocking
            return x

        adapter = _make_adapter(fast_task)
        trace = _make_trace()

        for i in range(FunctionAdapter._PROBE_INITIAL):
            await adapter.arun(f"call_{i}", trace)

        assert adapter._clean_streak >= FunctionAdapter._PROBE_INITIAL, (
            f"Clean streak {adapter._clean_streak} should have reached "
            f"{FunctionAdapter._PROBE_INITIAL} after clean calls"
        )

    @pytest.mark.asyncio
    async def test_blocking_resets_clean_streak(self):
        """A blocking call resets the clean streak so probing stays active."""

        call_idx = 0

        async def sometimes_blocking(x):
            nonlocal call_idx
            call_idx += 1
            if call_idx == 2:
                time.sleep(1.5)  # block on second call
            else:
                await asyncio.sleep(0.01)
            return x

        adapter = _make_adapter(sometimes_blocking)
        trace = _make_trace()

        await adapter.arun("1", trace)   # clean → streak=1
        assert adapter._clean_streak == 1

        await adapter.arun("2", trace)   # blocks → streak reset to 0
        assert adapter._clean_streak == 0

    @pytest.mark.asyncio
    async def test_periodic_reprobe_after_graduation(self):
        """After graduating, the adapter re-probes every _PROBE_INTERVAL calls."""

        probe_ran = False

        async def task_that_tracks(x):
            return x

        adapter = _make_adapter(task_that_tracks)
        trace = _make_trace()

        # Graduate past initial probes.
        for i in range(FunctionAdapter._PROBE_INITIAL):
            await adapter.arun(f"init_{i}", trace)
        assert adapter._clean_streak >= FunctionAdapter._PROBE_INITIAL

        # Run calls until just before the next periodic probe.
        calls_until_reprobe = FunctionAdapter._PROBE_INTERVAL - (adapter._call_count % FunctionAdapter._PROBE_INTERVAL)
        streak_before = adapter._clean_streak
        for i in range(calls_until_reprobe - 1):
            await adapter.arun(f"skip_{i}", trace)

        # The clean streak should not have changed (no probes ran).
        assert adapter._clean_streak == streak_before

        # The next call hits the periodic probe boundary.
        await adapter.arun("reprobe", trace)
        # Streak increments because the probe ran and was clean.
        assert adapter._clean_streak == streak_before + 1


# ---------------------------------------------------------------------------
# Starvation proof
# ---------------------------------------------------------------------------

class TestEventLoopStarvation:
    """Prove that a blocking async task starves concurrent coroutines."""

    @pytest.mark.asyncio
    async def test_blocking_async_starves_concurrent_canary(self):
        """A canary's 0.1s sleep takes much longer when the loop is frozen.

        The canary starts first (records t0, suspends at sleep(0.1)).
        Then the blocking task freezes the loop.  When the canary resumes,
        its wall-clock time includes the entire blocking period.
        """

        async def blocking_task(x):
            time.sleep(1.5)
            return x

        adapter = _make_adapter(blocking_task)
        trace = _make_trace()

        canary_wall_time = None
        canary_started = asyncio.Event()

        async def canary():
            nonlocal canary_wall_time
            canary_started.set()
            t0 = time.monotonic()
            await asyncio.sleep(0.1)
            canary_wall_time = time.monotonic() - t0

        # Start canary first — it records t0 and suspends at sleep(0.1).
        canary_task = asyncio.create_task(canary())
        await canary_started.wait()

        # Blocking task freezes the loop for 1.5s.
        blocking_start = time.monotonic()
        await adapter.arun("block", trace)
        blocking_time = time.monotonic() - blocking_start

        await canary_task

        # Canary's 0.1s sleep was inflated by the blocking period.
        # Assert relative to the blocking time, not an absolute threshold.
        assert canary_wall_time is not None
        assert canary_wall_time > blocking_time * 0.5, (
            f"Canary took {canary_wall_time:.2f}s but blocking task took "
            f"{blocking_time:.2f}s — canary should have been starved for "
            f"most of the blocking duration"
        )
