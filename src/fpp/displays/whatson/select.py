"""What makes the panel, in what order.

Caps are per sport rather than global: a single NCAAF Saturday is fifty games,
and a global cap would let it crowd out everything else.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from .config import home_teams, oddities
from .window import PACIFIC

CAPS = {
    "nfl": 3, "ncaaf": 3, "epl": 3, "cup": 2, "tennis": 4, "f1": 2,
    "oddity": 2, "home": 4, "highlight": 3,
}

# Tomorrow is a PREVIEW, and it needs its own budget rather than sharing
# today's. Caps used to apply across the whole window, and because rank_key
# sorts today ahead of tomorrow, today consumed every slot of every sport —
# the TOMORROW block was empty on any day busy enough to fill a cap.
# Smaller than CAPS on purpose: tomorrow is "what is coming", not a second board.
TOMORROW_CAPS = {
    "nfl": 2, "ncaaf": 2, "epl": 3, "cup": 1, "tennis": 2, "f1": 1,
    "oddity": 0,
}

_DAY_ORDER = {"today": 0, "tomorrow": 1}
_STATE_ORDER = {"live": 0, "pre": 1, "post": 2}
_TIER_ORDER = {"watchable": 0, "payable": 1}

# Craig's order of interest. Only affects the ORDER cards appear in within a
# day — the per-sport caps decide which ones get in at all.
COMPETITION_RANK = {
    "epl": 0, "ucl": 1, "facup": 2, "uel": 3,
    "nfl": 4, "ncaaf": 5,
    "atp": 6, "wta": 6, "f1": 7,
    "libertadores": 8, "sudamericana": 9, "concacaf": 10,
    "oddity": 20,
}

_FAR_FUTURE = datetime.max.replace(tzinfo=timezone.utc)


_ALSO_ON = {"golf", "ufc", "boxing"}


def _bucket_key(card: dict) -> str:
    # An explicit override wins: minor tennis, golf, UFC and boxing all belong
    # in the ALSO ON slot regardless of what sport they nominally are.
    if card.get("bucket"):
        return card["bucket"]
    if card.get("is_cup"):
        return "cup"
    # Golf, UFC and boxing share the ALSO ON slot with the curated oddities:
    # they are the same thing to the viewer — something fun that is on tonight.
    if card["sport"] in _ALSO_ON:
        return "oddity"
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
        COMPETITION_RANK.get(card.get("sport"), 15),
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


def _mark_oddities(cards):
    """Head the wildcard cards with ODDITY.

    Whatever the slot is filled by — a golf tour, a UFC card, a minor ATP
    tournament, an entry from the curated calendar — it is the same thing to
    the viewer: the one fun wildcard on the board. The sport still sets the
    colour, and the card body still names the event.
    """
    for c in cards:
        if c.get("kind") == "event" and _bucket_key(c) == "oddity":
            c.setdefault("colour_key", c.get("league_label", ""))
            c["league_label"] = "ODDITY"
    return cards


def assemble(home, events, highlights, now=None):
    """The full slide list: MY TEAMS, TODAY, TOMORROW, AVAILABLE TO WATCH."""
    home = sorted(home, key=rank_key)[: CAPS["home"]]
    seen = {id(c) for c in home}
    events = [c for c in events if id(c) not in seen and not c.get("home_team")]

    _mark_oddities(events)

    slides = []
    if home:
        # MY TEAMS spans both days, so these cards have no TODAY/TOMORROW
        # divider above them to borrow the day from — a bare "12:00p" could be
        # either. Only tomorrow needs marking; a plain clock means today.
        for c in home:
            if c.get("day") == "tomorrow" and c.get("state") == "pre":
                text = c.get("status_text", "")
                if not text.startswith("TMW"):
                    c["status_text"] = f"TMW {text}".strip()
        slides.append(divider("MY TEAMS", len(home)))
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


def guarantee_oddity(picked, pool):
    """Make sure something fun is always on the board.

    Craig wants at least one ALSO ON card every day. The pool is deep — four
    golf tours, UFC, boxing, the curated calendar, and every minor ATP/WTA
    tournament — but it can still come up empty on a quiet Tuesday. Rather than
    show nothing, promote the best leftover event from a sport the board is not
    already showing, so the slot is filled with variety rather than a fourth
    college football game.
    """
    if any(_bucket_key(c) == "oddity" for c in picked):
        return picked
    chosen = {id(c) for c in picked}
    shown = {c.get("sport") for c in picked}
    # Only a sport the board is NOT already showing. Promoting a leftover from
    # a league already on the board just relabels a fourth Premier League game
    # as "the oddity" — it reads as more of the same, which is the opposite of
    # the point. Better to show no ALSO ON card than a fake one.
    fresh = [c for c in pool
             if id(c) not in chosen and c.get("sport") not in shown]
    if not fresh:
        return picked
    best = dict(sorted(fresh, key=rank_key)[0])
    best["bucket"] = "oddity"
    return picked + [best]
