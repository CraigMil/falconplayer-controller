"""ESPN gives three different shapes of "event". Normalise all of them.

1. Match-shaped  (NFL, NCAAF, soccer) — one event is one game.
2. Tournament    (tennis)             — one event is a fortnight; 239 matches inside.
3. Session       (F1)                 — one event is a race weekend of sessions.
"""

from __future__ import annotations

from datetime import datetime

import httpx

from .channels import best_channel
from .window import bucket, clock

ESPN = "https://site.api.espn.com/apis/site/v2/sports"

SLUGS = {
    "nfl": "football/nfl",
    "ncaaf": "football/college-football",
    "epl": "soccer/eng.1",
    "ucl": "soccer/uefa.champions",
    "uel": "soccer/uefa.europa",
    "facup": "soccer/eng.fa",
    "libertadores": "soccer/conmebol.libertadores",
    "sudamericana": "soccer/conmebol.sudamericana",
    "concacaf": "soccer/concacaf.champions",
    "atp": "tennis/atp",
    "wta": "tennis/wta",
    "f1": "racing/f1",
    "mlb": "baseball/mlb",
    "nhl": "hockey/nhl",
    "mls": "soccer/usa.1",
    "nwsl": "soccer/usa.nwsl",
    "wnba": "basketball/wnba",
    "ncaab": "basketball/mens-college-basketball",
}

LABELS = {
    "nfl": "NFL", "ncaaf": "NCAAF", "epl": "EPL", "ucl": "UCL", "uel": "UEL",
    "facup": "FA CUP", "libertadores": "LIBERT", "sudamericana": "SUDAM",
    "concacaf": "CONCACAF", "atp": "TENNIS", "wta": "TENNIS", "f1": "F1",
    "mlb": "MLB", "nhl": "NHL", "mls": "MLS", "nwsl": "NWSL", "wnba": "WNBA",
    "ncaab": "NCAAB",
}

_CUPS = {"ucl", "uel", "facup", "libertadores", "sudamericana", "concacaf"}

# Round weight: a final outranks a group game whatever else is true.
_ROUNDS = {"final": 40, "semifinal": 30, "quarterfinal": 20, "round of 16": 10}


def fetch(slug: str, dates: str | None = None) -> dict:
    """The raw ESPN scoreboard payload. Network errors are the caller's problem."""
    url = f"{ESPN}/{slug}/scoreboard"
    params = {"dates": dates} if dates else {}
    with httpx.Client(timeout=20) as c:
        r = c.get(url, params=params)
        r.raise_for_status()
        return r.json()


def _iso(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _broadcasts(comp: dict):
    return [g.get("media", {}).get("shortName", "") for g in comp.get("geoBroadcasts", [])]


def _round_weight(comp: dict) -> int:
    note = " ".join(n.get("headline", "") for n in comp.get("notes", []))
    text = (note + " " + str((comp.get("type") or {}).get("text", ""))).lower()
    for key, weight in _ROUNDS.items():
        if key in text:
            return weight
    return 0


def _state(comp: dict) -> str:
    return ((comp.get("status") or {}).get("type") or {}).get("state", "pre")


def _drama(comp: dict, state: str) -> int:
    """How much a live event deserves the front of the queue."""
    if state != "in":
        return 0
    status = comp.get("status") or {}
    period = status.get("period") or 0
    try:
        scores = [int(c.get("score") or 0) for c in comp.get("competitors", [])]
    except (TypeError, ValueError):
        return 1
    margin = abs(scores[0] - scores[1]) if len(scores) == 2 else 99
    if margin <= 8 and period >= 4:
        return 3
    if margin <= 8:
        return 2
    return 1


def _side(competitor: dict) -> dict:
    team = competitor.get("team") or {}
    rank = competitor.get("curatedRank") or {}
    pos = rank.get("current")
    records = competitor.get("records") or []
    return {
        "abbr": team.get("abbreviation") or team.get("shortDisplayName") or "",
        "name": team.get("displayName", ""),
        "logo": team.get("logo", ""),
        "record": (records[0].get("summary", "") if records else ""),
        "rank": pos if isinstance(pos, int) and pos <= 25 else None,
        "score": competitor.get("score"),
    }


def _status_text(state: str, comp: dict, start: datetime) -> str:
    if state == "in":
        detail = ((comp.get("status") or {}).get("type") or {}).get("shortDetail", "LIVE")
        return f"LIVE {detail.split('-')[-1].strip()}"[:12]
    if state == "post":
        return "FINAL"
    return clock(start)


def _base(sport, start, day, comp, channel, state) -> dict:
    name, tier = channel
    return {
        "kind": "event",
        "sport": sport,
        "league_label": LABELS.get(sport, sport.upper()),
        "start": start,
        "day": day,
        "state": {"in": "live", "post": "post"}.get(state, "pre"),
        "status_text": _status_text(state, comp, start),
        "channel": name,
        "tier": tier,
        "major": False,
        "home_team": False,
        "drama": _drama(comp, state),
        "round_weight": _round_weight(comp),
        "dwell_floor": None,
        "is_cup": sport in _CUPS,
        "title": "",
        "subtitle": "",
        "detail": "",
        "score": None,
    }


def from_match(event: dict, sport: str, now=None):
    """One game, one card. Returns None when it is unwatchable or out of window."""
    comps = event.get("competitions") or []
    if not comps:
        return None
    comp = comps[0]
    start = _iso(comp.get("date") or event.get("date", ""))
    if not start:
        return None
    day = bucket(start, now)
    if day is None:
        return None
    channel = best_channel(_broadcasts(comp))
    if channel is None:
        return None
    state = _state(comp)
    card = _base(sport, start, day, comp, channel, state)
    competitors = comp.get("competitors", [])
    sides = [_side(c) for c in competitors]
    away = next((s for s, c in zip(sides, competitors) if c.get("homeAway") == "away"),
                sides[0] if sides else {})
    home = next((s for s, c in zip(sides, competitors) if c.get("homeAway") == "home"),
                sides[-1] if sides else {})
    card.update({
        "layout": "match",
        "away": away,
        "home": home,
        "score": ((int(away.get("score") or 0), int(home.get("score") or 0))
                  if card["state"] in ("live", "post") else None),
        "title": f"{away.get('abbr', '')} @ {home.get('abbr', '')}",
    })
    card["major"] = card["round_weight"] >= 20
    return card


def from_tournament(event: dict, sport: str, now=None):
    """A tennis tournament as one card. Only the majors qualify."""
    if not event.get("major"):
        return None
    start = _iso(event.get("date", ""))
    end = _iso(event.get("endDate", ""))
    if not start or not end:
        return None
    # A tournament spans a fortnight: it is "on today" if today falls inside it.
    ref = now or datetime.now(start.tzinfo)
    day = bucket(start, now) or ("today" if start <= ref <= end else None)
    if day is None:
        return None
    comps = [c for g in event.get("groupings", []) for c in g.get("competitions", [])]
    names = []
    for c in comps:
        names += _broadcasts(c)
    channel = best_channel(names)
    if channel is None:
        return None
    comp = comps[0] if comps else {}
    card = _base(sport, start, day, comp, channel, "in" if comps else "pre")
    rounds = {str((c.get("round") or {}).get("displayName", "")) for c in comps}
    card.update({
        "layout": "single",
        "title": event.get("name", "").upper(),
        "subtitle": next((r for r in sorted(rounds) if r), "In progress"),
        "detail": "Men's & Women's",
        "status_text": "ALL DAY",
        "major": True,
        "score": None,
    })
    return card


_SESSION_NAMES = {"Race": "RACE", "Sprint": "SPRINT", "Qual": "QUALIFYING"}


def from_sessions(event: dict, sport: str, now=None, include_practice: bool = False):
    """An F1 weekend as one card per session in the window."""
    out = []
    for comp in event.get("competitions", []):
        abbr = str((comp.get("type") or {}).get("abbreviation", ""))
        if abbr.startswith("FP") and not include_practice:
            continue
        start = _iso(comp.get("date", ""))
        if not start:
            continue
        day = bucket(start, now)
        if day is None:
            continue
        channel = best_channel(_broadcasts(comp))
        if channel is None:
            continue
        card = _base(sport, start, day, comp, channel, _state(comp))
        card.update({
            "layout": "single",
            "title": event.get("shortName") or event.get("name", ""),
            "subtitle": _SESSION_NAMES.get(abbr, abbr.upper()),
            "detail": (event.get("circuit") or {}).get("shortName", ""),
            "score": None,
            # The Race and the Sprint are the sessions worth paying for.
            "major": abbr in ("Race", "Sprint"),
            "round_weight": {"Race": 30, "Sprint": 20, "Qual": 10}.get(abbr, 0),
        })
        out.append(card)
    return out
