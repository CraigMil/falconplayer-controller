"""Today and tomorrow, in Pacific time.

The same reasoning as the what's-on board: every day boundary here is local
midnight, not UTC midnight. "On this day" asked in UTC flips over at 5pm
Pacific, so the panel would start showing tomorrow's history in the middle of
this evening.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


def local_now(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(PACIFIC)


def today(now: datetime | None = None) -> date:
    return local_now(now).date()


def tomorrow(now: datetime | None = None) -> date:
    return today(now) + timedelta(days=1)


def pretty(day: date) -> str:
    """The panel's date form: "16 SEPTEMBER"."""
    return f"{day.day} {day.strftime('%B').upper()}"
