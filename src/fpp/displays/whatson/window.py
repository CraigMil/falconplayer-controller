"""Today and tomorrow, in Pacific time.

Every day boundary in this feature is PDT midnight, not UTC midnight and not
the panel's local guess. A 7pm Saturday kickoff is 02:00 Sunday in UTC; bucket
it by UTC and half of Saturday's games move to Sunday.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


def _now(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(PACIFIC)


def bounds(now: datetime | None = None):
    """PDT midnight today, and PDT midnight the day after tomorrow."""
    here = _now(now)
    start = here.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=2)


def date_range(now: datetime | None = None) -> str:
    """The ESPN `dates=` parameter covering today and tomorrow."""
    start, end = bounds(now)
    return f"{start:%Y%m%d}-{(end - timedelta(days=1)):%Y%m%d}"


def bucket(start: datetime, now: datetime | None = None):
    """"today", "tomorrow", or None when the event falls outside the window."""
    day0, _ = bounds(now)
    local = start.astimezone(PACIFIC)
    delta = (local.date() - day0.date()).days
    return {0: "today", 1: "tomorrow"}.get(delta)


def clock(start: datetime) -> str:
    """A kickoff time as the panel prints it: "9:30a", "7:00p"."""
    local = start.astimezone(PACIFIC)
    return f"{local.strftime('%-I:%M')}{local.strftime('%p')[0].lower()}"
