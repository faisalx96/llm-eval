from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLATFORM_SRC = ROOT / "packages" / "platform"
if str(PLATFORM_SRC) not in sys.path:
    sys.path.insert(0, str(PLATFORM_SRC))

from qym_platform.datetime_utils import to_api_timestamp, to_storage_utc


def test_to_api_timestamp_marks_naive_datetimes_as_utc():
    value = datetime(2026, 4, 2, 12, 13, 0)

    assert to_api_timestamp(value) == "2026-04-02T12:13:00Z"


def test_to_storage_utc_converts_aware_datetimes_to_naive_utc():
    value = datetime(2026, 4, 2, 15, 13, 0, tzinfo=timezone.utc).astimezone(
        timezone.utc
    )

    stored = to_storage_utc(value)

    assert stored == datetime(2026, 4, 2, 15, 13, 0)
    assert stored.tzinfo is None


def test_to_storage_utc_normalizes_offset_datetimes():
    value = datetime.fromisoformat("2026-04-02T15:13:00+03:00")

    stored = to_storage_utc(value)

    assert stored == datetime(2026, 4, 2, 12, 13, 0)
    assert to_api_timestamp(stored) == "2026-04-02T12:13:00Z"
