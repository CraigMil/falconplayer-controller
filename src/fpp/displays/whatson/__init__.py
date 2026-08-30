"""What's on today and tomorrow, and where to watch it.

Public surface is build_board(); everything else is an implementation detail of
this package.
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import cards, channels, config, highlights, select, sources, window
from .window import date_range

__all__ = ["build_board", "cards", "channels", "config", "highlights",
           "select", "sources", "window"]

# Which adapter each slug needs.
_MATCH = ["nfl", "ncaaf", "epl", "ucl", "uel", "facup", "libertadores",
          "sudamericana", "concacaf"]
_TOURNAMENT = ["atp", "wta"]
_SESSION = ["f1"]
_MULTIDAY = ["golf", "golf_lpga", "golf_eur", "golf_champions", "ufc",
             "boxing", "lacrosse"]
_HOME_ONLY = ["mlb", "nhl", "mls", "nwsl", "wnba", "ncaab"]


def build_board(now=None, include_practice: bool = False,
                with_highlights: bool = True):
    """The full slide list, plus a one-word reason for the log line."""
    now = now or datetime.now(timezone.utc)
    dates = date_range(now)

    def _events(slug_key: str, dated: bool = True):
        """Fetch one slug's events.

        `dated=False` for tennis and F1. Their scoreboards do NOT filter the way
        the match-shaped leagues do: asked for 29-30 Aug, tennis/atp returns
        Winston-Salem but NOT the US Open, and racing/f1 returns nothing at all
        during a live race weekend. Undated returns the current tournaments and
        the current GP, which the tournament and session adapters then window
        themselves.
        """
        slug = sources.SLUGS[slug_key]
        try:
            payload = sources.fetch(slug, dates if dated else None)
        except Exception:
            return []
        return payload.get("events", []) or []

    collected = []

    for key in _MATCH + _HOME_ONLY:
        for event in _events(key):
            card = sources.from_match(event, key, now)
            if card:
                collected.append(card)

    # The Slams appear on BOTH the ATP and WTA scoreboards under the same name,
    # and the card is deliberately combined ("Men's & Women's"), so take each
    # tournament once.
    seen_tournaments = set()
    seen_matches = set()
    for key in _TOURNAMENT:
        for event in _events(key, dated=False):
            # During a Slam the individual matches ARE the story, so they
            # replace the summary card. The ATP and WTA feeds both carry every
            # US Open match, hence the dedupe.
            matches = sources.tennis_matches(event, key, now)
            if matches:
                for m in matches:
                    if m["title"] in seen_matches:
                        continue
                    seen_matches.add(m["title"])
                    collected.append(m)
                seen_tournaments.add((event.get("name") or "").upper())
                continue
            # No play in the window (or a minor event): fall back to the
            # tournament card. require_major=False lets the minor tournaments
            # through as ALSO ON filler.
            card = sources.from_tournament(event, key, now, require_major=False)
            if card and card["title"] not in seen_tournaments:
                seen_tournaments.add(card["title"])
                collected.append(card)

    for key in _SESSION:
        for event in _events(key, dated=False):
            collected += sources.from_sessions(event, key, now, include_practice)

    # Undated for the same reason as tennis and F1: these are multi-day events,
    # and a date range hides one already under way.
    for key in _MULTIDAY:
        for event in _events(key, dated=False):
            card = sources.from_multiday(event, key, now)
            if card:
                collected.append(card)

    collected = select.mark_home(collected)
    collected += select.oddity_cards(now)

    home = [c for c in collected if c.get("home_team")]
    # Home-only leagues exist to find the user's teams; every other game in them
    # is discarded rather than competing for a slot.
    rest = [c for c in collected
            if not c.get("home_team") and c["sport"] not in _HOME_ONLY]

    # Payable events must be major to earn a slot. Home teams are exempt — they
    # were already separated out above.
    rest = [c for c in rest if c["tier"] == "watchable" or c.get("major")]

    picked = select.apply_caps(rest)
    picked = select.guarantee_oddity(picked, rest)
    hl = highlights.fetch_all(now) if with_highlights else []
    slides = select.assemble(home, picked, hl, now)

    if len(slides) == 1 and slides[0]["kind"] == "empty":
        return slides, "empty"
    reason = "live" if any(s.get("state") == "live" for s in slides) else "scheduled"
    return slides, reason
