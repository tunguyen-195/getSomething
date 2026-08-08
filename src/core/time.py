"""Timestamp normalization for API metadata."""
from datetime import datetime, timezone, tzinfo
import os
from zoneinfo import ZoneInfo


UTC = timezone.utc
LEGACY_DATABASE_TIMEZONE = ZoneInfo(
    os.getenv("LEGACY_DATABASE_TIMEZONE", "Asia/Bangkok")
)


def utc_isoformat(
    value: datetime | str | None,
    *,
    naive_timezone: tzinfo = UTC,
) -> str | None:
    """Serialize a timestamp as an explicit-offset UTC ISO-8601 value."""
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=naive_timezone)
    return value.astimezone(UTC).isoformat()
