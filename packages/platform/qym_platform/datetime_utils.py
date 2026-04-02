from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


UTC = timezone.utc


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_storage_utc(dt: Optional[datetime]) -> Optional[datetime]:
    normalized = ensure_utc(dt)
    if normalized is None:
        return None
    return normalized.replace(tzinfo=None)


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_naive() -> datetime:
    return utc_now().replace(tzinfo=None)


def to_api_timestamp(dt: Optional[datetime]) -> Optional[str]:
    normalized = ensure_utc(dt)
    if normalized is None:
        return None
    return normalized.isoformat().replace("+00:00", "Z")
