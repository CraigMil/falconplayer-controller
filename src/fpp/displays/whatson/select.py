"""What makes the panel, in what order.

Caps are per sport rather than global: a single NCAAF Saturday is fifty games,
and a global cap would let it crowd out everything else.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from .config import home_teams, oddities
from .window import PACIFIC

CAPS = {
    "nfl": 3, "ncaaf": 3, "epl": 3, "cup": 2, "tennis": 2, "f1": 2,
    "oddity": 1, "home": 4, "highlight": 3,
}

# Tomorrow is a PREVIEW, and it needs its own budget rather than sharing
# today's. Caps used to apply across the whole window, and because rank_key
# sorts today ahead of tomorrow, today consumed every slot of every sport —
# the TOMORROW block was empty on any day busy enough to fill a cap.
# Smaller than CAPS on purpose: tomorrow is "what is coming", not a second board.
TOMORROW_CAPS = {
    "nfl": 1, "ncaaf": 1, "epl": 2, "cup": 1, "tennis": 1, "f1": 1,
    "oddity": 0,
}

_DAY_ORDER = {"today": 0, "tomorrow": 1}
_STATE_ORDER = {"live": 0, "pre": 1, "post": 2}
_TIER_ORDER = {"watchable": 0, "payable": 1}

_FAR_FUTURE = datetime.max.replace(tzinfo=timezone.utc)


def _bucket_key(card: dict) -> str:
    if card.get("is_cup"):
        return "cup"
    if card["sport"] in ("atp", "wta"):
        return "tennis"
    return card["sport"]


def rank_key(card: dict):
    """Sort key, ascending. Lower sorts nearer the front of the panel."""
    rank = (card.get("home") or {}).get("rank") or (card.get("away") or {}).get("rank")
    return (
        _DAY_ORDER.get(card.get("day"), 9),
        _STATE_ORDER.get(card.get("state"), 9),
        -card.get("drama", 0),
        -card.get("round_weight", 0),
        rank if isinstance(rank, int) else 99,
        _TIER_ORDER.get(card.get("tier"), 9),
        card.get("start") or _FAR_FUTURE,
    )


def apply_caps(cards):
    """Keep the best N of each sport, PER DAY. Home games are exempt — see mark_home."""
    kept = []
    used = {}
    for card in sorted(cards, key=rank_key):
        if card.get("home_team"):
            continue
        key = _bucket_key(card)
        day = card.get("day", "today")
        if day == "tomorrow":
            cap = TOMORROW_CAPS.get(key, 1)
        else:
            cap = CAPS.get(key, 2)
        slot = (day, key)
        if used.get(slot, 0) >= cap:
            continue
        used[slot] = used.get(slot, 0) + 1
        kept.append(card)
    return kept


def mark_home(cards):
    """Flag any card featuring a configured home team."""
    names = {h["team"] for h in home_teams()}
    for card in cards:
        sides = ((card.get("away") or {}), (card.get("home") or {}))
        if any(s.get("name") in names for s in sides):
            card["home_team"] = True
    return cards


def _as_date(v) -> date:
    return v if isinstance(v, date) and not isinstance(v, datetime) else v.date()


def oddity_cards(now=None):
    """Curated events whose window covers today or tomorrow."""
    from .channels import tier_of

    here = (now or datetime.now(timezone.utc)).astimezone(PACIFIC)
    today = here.date()
    out = []
    for o in oddities():
        start, end = _as_date(o["start"]), _as_date(o["end"])
        if not (start <= today <= end):
            continue
        major = bool(o.get("major"))
        if not major and o.get("major_from"):
            major = today >= _as_date(o["major_from"])
        channel = o["channel"]
        out.append({
            "kind": "event", "sport": "oddity", "league_label": "ALSO ON",
            "layout": "single", "title": o["name"].upper(),
            "subtitle": o.get("subtitle", ""), "detail": "",
            "start": here, "day": "today", "state": "live",
            "status_text": "ALL DAY", "channel": channel,
            "tier": tier_of(channel), "major": major, "home_team": False,
            "drama": 0, "round_weight": 0, "dwell_floor": None,
            "is_cup": False, "score": None,
        })
    # Payable oddities need to be major to earn a slot, same rule as everything else.
    return [c for c in out if c["tier"] == "watchable" or c["major"]]


def divider(title: str, count: int, subtitle: str = "") -> dict:
    return {
        "kind": "divider", "title": title, "subtitle": subtitle,
        "count": count, "dwell_floor": None, "sport": "divider",
    }


def _day_subtitle(day: str, now=None) -> str:
    here = (now or datetime.now(timezone.utc)).astimezone(PACIFIC)
    when = here if day == "today" else here + timedelta(days=1)
    return when.strftime("%a · %b %-d").upper()


def assemble(home, events, highlights, now=None):
    """The full slide list: SEATTLE, TODAY, TOMORROW, AVAILABLE TO WATCH."""
    home = sorted(home, key=rank_key)[: CAPS["home"]]
    seen = {id(c) for c in home}
    events = [c for c in events if id(c) not in seen and not c.get("home_team")]

    slides = []
    if home:
        slides.append(divider("SEATTLE", len(home)))
        slides += home
    for day in ("today", "tomorrow"):
        block = [c for c in events if c.get("day") == day]
        if block:
            slides.append(divider(day.upper(), len(block), _day_subtitle(day, now)))
            slides += sorted(block, key=rank_key)
    if highlights:
        slides.append(divider("AVAILABLE TO WATCH", len(highlights)))
        slides += highlights[: CAPS["highlight"]]

    if not slides:
        return [{"kind": "empty", "sport": "empty", "title": "NOTHING ON",
                 "subtitle": "", "dwell_floor": None}]
    return slides
