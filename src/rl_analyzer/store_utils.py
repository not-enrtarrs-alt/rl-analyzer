"""Shared storage errors and UTC timestamp formatting."""

from datetime import datetime, timezone


class StoreError(RuntimeError):
    """Storage is invalid or an unsafe state transition was requested."""


def utc_stamp(value: datetime) -> str:
    """Serialize an aware timestamp as fixed-width UTC for safe SQLite sorting."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise StoreError("Timestamp must have a timezone")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def now_stamp(value: datetime | None) -> str:
    """Format a supplied timestamp, or the current UTC time."""
    return utc_stamp(value if value is not None else datetime.now(timezone.utc))
