"""A historical fact from anywhere in the world, and the international days.

Public surface is build_board(); everything else is an implementation detail of
this package.

The split that matters: sources.py fetches what can be verified (Wikipedia's
curated events, flags), brief.py is the single model call that chooses and
compresses, and cache.py owns the once-a-day rule and the ladder down when the
call cannot be made. cards.py only draws what it is handed.
"""

from __future__ import annotations

from datetime import date, datetime

from . import brief, cache, cards, sources, window
from .window import today as _today
from .window import tomorrow as _tomorrow

__all__ = ["build_board", "brief", "cache", "cards", "sources", "window"]


def build_board(now: datetime | None = None,
                rebuild: bool = True) -> tuple[list[dict], str]:
    """The three slides, plus the tier name they were built from."""
    data, tier = cache.load(now, rebuild=rebuild)

    fact = data.get("fact") or {}
    try:
        shown = date.fromisoformat(data.get("fact_date") or "")
    except ValueError:
        shown = _today(now)

    slides = [{
        "kind": "fact",
        "date_label": cards.date_label(shown),
        "year": fact.get("year") or 0,
        "country": fact.get("country") or "",
        "country_code": fact.get("country_code") or "",
        "headline": fact.get("headline") or "",
        "synopsis": fact.get("synopsis") or "",
        "source_url": fact.get("source_url") or "",
    }]

    for kind, day in (("today", _today(now)), ("tomorrow", _tomorrow(now))):
        entry = data.get(kind) or {}
        slides.append({
            "kind": kind,
            "day": day,
            "name": entry.get("name") or "",
            "established": entry.get("established") or "",
            "source_url": entry.get("source_url") or "",
        })

    return slides, tier
