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
    "golf": "golf/pga",
    "golf_lpga": "golf/lpga",
    "golf_eur": "golf/eur",
    "golf_champions": "golf/champions-tour",
    "ufc": "mma/ufc",
    "boxing": "boxing",
}

LABELS = {
    "nfl": "NFL", "ncaaf": "NCAAF", "epl": "EPL", "ucl": "UCL", "uel": "UEL",
    "facup": "FA CUP", "libertadores": "LIBERT", "sudamericana": "SUDAM",
    "concacaf": "CONCACAF", "atp": "TENNIS", "wta": "TENNIS", "f1": "F1",
    "mlb": "MLB", "nhl": "NHL", "mls": "MLS", "nwsl": "NWSL", "wnba": "WNBA",
    "ncaab": "NCAAB", "golf": "GOLF", "golf_lpga": "LPGA", "golf_eur": "GOLF",
    "golf_champions": "GOLF", "ufc": "UFC", "boxing": "BOXING",
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


def from_tournament(event: dict, sport: str, now=None, require_major: bool = True):
    """A tennis tournament as one card.

    Majors earn a place in the tennis block on their own merit. With
    require_major=False the minor tournaments come back too, tagged for the
    ALSO ON slot — the ATP and WTA run something almost every week of the year,
    which is what makes a daily oddity possible at all.
    """
    is_major = bool(event.get("major"))
    if require_major and not is_major:
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
    # The round being played TODAY. Two wrong answers to avoid: sorting the
    # names alphabetically puts "Final" ahead of "Round of 32", and counting
    # every match in the tournament is dominated by the completed early rounds —
    # on day six of the US Open both gave the wrong round.
    from collections import Counter

    # A Slam's payload is the whole bracket, including future placeholder
    # matches, so prefer what is on today or tomorrow. When neither has any —
    # ESPN dates a session by its start, and a night session lands on the next
    # UTC day — fall back to the earliest matches not yet played.
    windowed = [c for c in comps if bucket(_iso(c.get("date", "")) or start, now)]
    if not windowed:
        upcoming = [c for c in comps
                    if _state(c) == "pre" and _iso(c.get("date", "")) is not None]
        if upcoming:
            soonest = min(_iso(c["date"]) for c in upcoming)
            windowed = [c for c in upcoming
                        if (_iso(c["date"]) - soonest).days == 0]
    tally = Counter(str((c.get("round") or {}).get("displayName", ""))
                    for c in (windowed or comps))
    tally.pop("", None)
    card.update({
        "layout": "single",
        "title": event.get("name", "").upper(),
        "subtitle": tally.most_common(1)[0][0] if tally else "In progress",
        "detail": "Men's & Women's",
        "status_text": "ALL DAY",
        "major": is_major,
        "score": None,
    })
    if not is_major:
        card["bucket"] = "oddity"
        card["detail"] = "ATP / WTA"
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


def from_multiday(event: dict, sport: str, now=None):
    """A whole-event card for sports ESPN models as one multi-day happening:
    a golf tournament, a UFC fight card, a boxing bill.

    Distinct from from_tournament, which is tennis-specific and insists on a
    major. These fill the ALSO ON slot, so they have no majorness requirement —
    the point is that something fun is on tonight.
    """
    comps = event.get("competitions") or []
    if not comps:
        return None
    start = _iso(event.get("date", ""))
    if not start:
        return None
    end = _iso(event.get("endDate", "")) or start
    ref = now or datetime.now(start.tzinfo)
    day = bucket(start, now) or bucket(end, now)
    if day is None:
        # A tournament already under way spans the window without starting in it.
        day = "today" if start <= ref <= end else None
    if day is None:
        return None

    names = []
    for c in comps:
        names += _broadcasts(c)
    channel = best_channel(names)
    if channel is None:
        return None

    comp = comps[0]
    card = _base(sport, start, day, comp, channel, _state(comp))
    headline = ""
    if sport in ("ufc", "boxing"):
        # The main event is the draw, and it is in the event name after the colon.
        headline = event.get("name", "").split(":", 1)[-1].strip()
    else:
        # Golf. "FINAL" read as "the tournament final"; the round is what the
        # viewer actually wants. ESPN spells it "Round 3 - Play Complete".
        detail = ((comp.get("status") or {}).get("type") or {}).get("shortDetail", "")
        headline = detail.replace(" - ", " · ")[:26]
    card.update({
        "layout": "single",
        "title": (event.get("shortName") or event.get("name", "")).split(":")[0].strip().upper(),
        "subtitle": headline or _status_text(_state(comp), comp, start),
        "detail": (event.get("venue") or {}).get("fullName", "")[:28],
        "score": None,
        "status_text": "ALL DAY" if _state(comp) != "in" else card["status_text"],
        "bucket": "oddity",
    })
    return card


def _seed(competitor: dict):
    """A player's seed, or None. ESPN carries it as curatedRank on seeded
    players only — there is no `seed` field anywhere in the payload."""
    cur = (competitor.get("curatedRank") or {}).get("current")
    return cur if isinstance(cur, int) and 0 < cur <= 40 else None


def _player(competitor: dict) -> dict:
    ath = competitor.get("athlete") or {}
    sets = [ls.get("value") for ls in competitor.get("linescores") or []]
    return {
        "name": (ath.get("shortName") or ath.get("displayName") or "").upper(),
        "seed": _seed(competitor),
        "flag": (ath.get("flag") or {}).get("href", ""),
        "sets": [int(v) for v in sets if isinstance(v, (int, float))],
        "winner": bool(competitor.get("winner")),
    }


def tennis_matches(event: dict, sport: str, now=None, limit: int = 4):
    """Up to `limit` match cards from a major, best first.

    Replaces the single tournament card during a Slam. Ordering: live matches
    first (a deciding set outranks a routine one), then by the BEST SEED in the
    match, then by start time — so a 4-vs-18 outranks two unseeded players.
    """
    if not event.get("major"):
        return []
    comps = [c for g in event.get("groupings", []) for c in g.get("competitions", [])]
    out = []
    for comp in comps:
        start = _iso(comp.get("date", ""))
        if not start:
            continue
        if bucket(start, now) is None:
            continue
        state = _state(comp)
        if state == "post":
            continue
        channel = best_channel(_broadcasts(comp))
        if channel is None:
            continue
        players = [_player(c) for c in comp.get("competitors", [])]
        if len(players) != 2 or not all(p["name"] for p in players):
            continue
        card = _base(sport, start, bucket(start, now), comp, channel, state)
        seeds = [p["seed"] for p in players if p["seed"]]
        best_seed = min(seeds) if seeds else 99
        rnd = str((comp.get("round") or {}).get("displayName", ""))
        sets_played = max((len(p["sets"]) for p in players), default=0)
        card.update({
            "layout": "tennis",
            "players": players,
            "title": " v ".join(p["name"] for p in players),
            "subtitle": rnd,
            "detail": event.get("shortName") or event.get("name", ""),
            "best_seed": best_seed,
            "major": True,
            "score": None,
        })
        if state == "in":
            # A deciding set is the whole reason to look up.
            deciding = sets_played >= 5 or (sets_played >= 3 and len(comps) and
                                            all(len(p["sets"]) >= 3 for p in players))
            card["drama"] = 3 if deciding else 2
            card["status_text"] = f"LIVE {sets_played}{'th' if sets_played > 3 else 'rd'}"[:12]
        out.append(card)

    out.sort(key=lambda c: (0 if c["state"] == "live" else 1, -c["drama"],
                            c["best_seed"], c["start"]))
    return out[:limit]
