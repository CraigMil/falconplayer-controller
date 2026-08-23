"""NFL scoreboard display — every game of the current week, plus stat leaders.

The soccer module has to work out what "this week" means from a date range,
because a Premier League round is spread over three days and ESPN's payload
carries no round number. The NFL hands it over: the scoreboard endpoint called
with no arguments returns exactly the current week's games, with a real week
number and season type attached. So there is no block arithmetic here at all —
`fetch_games()` with no dates IS the week.

Cards are built in the same shape the soccer module renders, so the game card
itself is shared rather than written twice; see `render_game`.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import httpx

from ..canvas import Color, Frame
from .soccer import _hex, _kickoff, next_fixture
from .soccer import render_scoreboard as _render_card

SITE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"

LEAGUE_LABEL = "NFL"

# A team on a bye plays a fortnight after its last game, so a two-week window
# answers "when do they play next" with nothing at all for the teams that most
# need the answer. Three weeks always spans a bye.
FIXTURE_DAYS = 21

# Pull more candidates than the card shows. The pools are ranked by a DIFFERENT
# statistic from the one displayed — quarterbacks by passing yards, backs by
# rushing yards — so the top eight of the pool is not the top eight of the card,
# and the ones that get filtered out by position have to be replaced from
# somewhere.
LEADER_POOL = 18
LEADER_ROWS = 8

# Season stats change when games finish, not minute to minute, and resolving a
# pool costs a request per player. Half an hour is far finer than the data.
STAT_TTL = 1800


def _get(url: str) -> dict:
    resp = httpx.get(url, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ------------------------------------------------------------------ games


def _week_label(event: dict) -> str:
    """"WEEK 3", "PRE WK 3", "WILD CARD" — whatever this game belongs to."""
    num = (event.get("week") or {}).get("number")
    slug = (event.get("season") or {}).get("slug", "")
    if slug == "preseason":
        return f"PRE WK {num}" if num else "PRESEASON"
    if slug in ("post-season", "postseason"):
        return {1: "WILD CARD", 2: "DIVISIONAL", 3: "CONF CHAMP",
                5: "SUPER BOWL"}.get(num, "PLAYOFFS")
    return f"WEEK {num}" if num else "NFL"


def _period_label(period: int) -> str:
    """Q1..Q4, then OT. Halftime arrives as period 2 with a zero clock."""
    if not period:
        return ""
    if period > 4:
        return "OT" if period == 5 else f"OT{period - 4}"
    return f"Q{period}"


def _card_from_event(event: dict) -> dict | None:
    comp = (event.get("competitions") or [{}])[0]
    competitors = comp.get("competitors", [])
    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if not home or not away:
        return None

    status = comp.get("status", {})
    stype = status.get("type", {})
    state = stype.get("state", "pre")

    def side(c: dict, prefix: str) -> dict:
        team = c.get("team", {})
        return {
            f"{prefix}_id":         str(team.get("id", "")),
            f"{prefix}_abbr":       team.get("abbreviation", "???"),
            f"{prefix}_name":       team.get("shortDisplayName", ""),
            f"{prefix}_score":      c.get("score", "0"),
            f"{prefix}_color":      _hex(team.get("color", "")),
            f"{prefix}_alt_color":  _hex(team.get("alternateColor", "")),
            f"{prefix}_logo":       team.get("logo", ""),
        }

    card = {
        "event_id":     str(event.get("id", "")),
        "kickoff":      event.get("date", ""),
        "state":        state,
        "clock":        status.get("displayClock", ""),
        "period":       status.get("period", 0),
        "period_label": _period_label(status.get("period", 0)),
        "short":        stype.get("shortDetail", ""),
        "detail":       stype.get("detail", ""),
        "game_date":    _short_date(event.get("date", "")),
        "league_label": _week_label(event),
        "league_key":   "nfl",
        # Soccer-only fields the shared card renderer reads. Left empty rather
        # than deleted, because the renderer asks for them by name.
        "leg":          None,
        "aggregate":    None,
        "note":         "",
    }
    card.update(side(away, "away"))
    card.update(side(home, "home"))
    return card


def _short_date(iso: str) -> str:
    dt = _kickoff(iso)
    return dt.astimezone().strftime("%b %-d") if dt else ""


def fetch_games(dates: str | None = None) -> list[dict]:
    """Cards for a date range, or — with no argument — for the current week."""
    url = f"{SITE}/scoreboard" + (f"?dates={dates}" if dates else "")
    data = _get(url)
    out = []
    for event in data.get("events", []):
        card = _card_from_event(event)
        if card:
            out.append(card)
    out.sort(key=lambda c: c["kickoff"])
    return out


def fetch_fixtures(days: int = FIXTURE_DAYS) -> list[dict]:
    """Flat upcoming-fixture list, in the shape `next_fixture()` expects."""
    now = datetime.now(timezone.utc)
    span = f"{now:%Y%m%d}-{now + timedelta(days=days):%Y%m%d}"
    out = []
    for card in fetch_games(span):
        out.append({
            "event_id":  card["event_id"],
            "date":      card["kickoff"],
            "home_id":   card["home_id"],
            "away_id":   card["away_id"],
            "home_abbr": card["home_abbr"],
            "away_abbr": card["away_abbr"],
            "league":    LEAGUE_LABEL,
        })
    out.sort(key=lambda f: f["date"])
    return out


def attach_next(cards: list[dict], fixtures: list[dict]) -> list[dict]:
    for c in cards:
        c["home_next"] = next_fixture(fixtures, c["home_id"], c["event_id"])
        c["away_next"] = next_fixture(fixtures, c["away_id"], c["event_id"])
    return cards


def select_cards(max_cards: int = 24) -> tuple[list[dict], str]:
    """The current week's games, live first, then in kickoff order."""
    try:
        games = fetch_games()
    except Exception:
        return [], "idle"
    if not games:
        return [], "idle"
    live = [g for g in games if g["state"] == "in"]
    rest = [g for g in games if g["state"] != "in"]
    return (live + rest)[:max_cards], "week"


def render_game(card: dict) -> Frame:
    """The two-team game card.

    Shared with soccer rather than reimplemented: the layout is two clubs,
    their colours, their marks, a score and a status strip, none of which is
    specific to a sport. The one thing that was specific — reading `period` as
    a football half — now comes from the card as `period_label`, which is why
    this is an import and not a copy.
    """
    return _render_card(card)


# ------------------------------------------------------------------ leaders


@lru_cache(maxsize=1)
def _teams() -> dict[str, str]:
    """Team id -> abbreviation, in one request rather than thirty-two."""
    data = _get(f"{SITE}/teams")
    out = {}
    for entry in data["sports"][0]["leagues"][0]["teams"]:
        team = entry["team"]
        out[str(team["id"])] = team.get("abbreviation", "???")
    return out


@lru_cache(maxsize=512)
def _athlete(ref: str) -> dict:
    """Name and position for a player. Immutable within a season, so cached hard."""
    return _get(ref)


@lru_cache(maxsize=512)
def _stats_cached(ref: str, bucket: int) -> dict:
    """Flattened season statistics, keyed by a coarse time bucket.

    `bucket` is what makes this expire: it is the clock divided by STAT_TTL, so
    a new key — and a new fetch — appears every half hour and the old entries
    fall out of the LRU. functools has no TTL cache and the alternative was a
    hand-rolled dict with timestamps.
    """
    data = _get(ref)
    flat: dict[str, float] = {}
    for cat in data.get("splits", {}).get("categories", []):
        for stat in cat.get("stats", []):
            value = stat.get("value")
            if value is not None:
                flat[f"{cat['name']}.{stat['name']}"] = value
    return flat


def _stats(ref: str) -> dict:
    return _stats_cached(ref, int(time.time() // STAT_TTL))


@lru_cache(maxsize=4)
def leaders_season(bucket: int = 0) -> tuple[int, str]:
    """(year, label) for the most recent season that actually has stats.

    Asked in August, the current year's regular season returns 404 "No stats
    found" — the games have not been played. Falling back a year and SAYING SO
    on the card beats three blank cards for the whole of the preseason.
    """
    year = datetime.now(timezone.utc).year
    for candidate, label in ((year, str(year)), (year - 1, f"{year - 1} FINAL")):
        try:
            _get(f"{CORE}/seasons/{candidate}/types/2/leaders")
            return candidate, label
        except Exception:
            continue
    return year - 1, f"{year - 1} FINAL"


def _resolve(entries: list[dict]) -> list[dict]:
    """Turn leader entries into players, resolving names and stats in parallel.

    Serially this is two requests per player and takes the best part of a
    minute for three pools; in parallel the whole set lands in about a second.
    """
    teams = _teams()
    with ThreadPoolExecutor(max_workers=12) as pool:
        athletes = list(pool.map(lambda e: _athlete(e["athlete"]["$ref"]), entries))
        stats = list(pool.map(lambda e: _stats(e["statistics"]["$ref"]), entries))

    out = []
    for entry, athlete, stat in zip(entries, athletes, stats):
        team_ref = (entry.get("team") or {}).get("$ref", "")
        match = re.search(r"/teams/(\d+)", team_ref)
        out.append({
            "name":  athlete.get("shortName") or athlete.get("displayName", "?"),
            "pos":   (athlete.get("position") or {}).get("abbreviation", ""),
            "team":  teams.get(match.group(1), "") if match else "",
            "stats": stat,
        })
    return out


def _pool(categories: dict, name: str) -> list[dict]:
    return _resolve(categories.get(name, [])[:LEADER_POOL])


def leader_cards() -> list[dict]:
    """Three cards: quarterbacks by Total QBR, backs by scrimmage yards, receivers.

    Each pool is ranked by ESPN's own leaderboard for a VOLUME statistic and
    then re-sorted by the statistic actually wanted. That ordering is the
    qualification filter: Total QBR on its own would be topped by a backup with
    four attempts in garbage time, and there is no minimum-attempts parameter
    on the endpoint. Coming at it through the passing-yards top eighteen means
    everyone on the card is a starter by construction.

    Returns [] on any failure. Leaders are a garnish on a scoreboard; an ESPN
    hiccup should cost you the garnish and not the scores.
    """
    try:
        year, label = leaders_season(int(time.time() // STAT_TTL))
        index = _get(f"{CORE}/seasons/{year}/types/2/leaders")
        categories = {c["name"]: c.get("leaders", []) for c in index.get("categories", [])}
    except Exception:
        return []

    def card(title: str, unit: str, rows: list[dict]) -> dict:
        return {"kind": "leaders", "league_label": LEAGUE_LABEL, "title": title,
                "unit": unit, "season": label, "rows": rows[:LEADER_ROWS]}

    cards = []
    try:
        qbs = [p for p in _pool(categories, "passingYards") if p["pos"] == "QB"]
        for p in qbs:
            p["value"] = p["stats"].get("passing.QBR")
        qbs = [p for p in qbs if p["value"] is not None]
        qbs.sort(key=lambda p: p["value"], reverse=True)
        cards.append(card("QUARTERBACKS", "QBR", qbs))
    except Exception:
        pass

    try:
        # "Total yards" for a back is yards from scrimmage — rushing plus
        # receiving. A back who catches eighty balls out of the backfield is
        # having a different season from one who does not, and rushing yards
        # alone does not show it.
        rbs = [p for p in _pool(categories, "rushingYards") if p["pos"] == "RB"]
        for p in rbs:
            p["value"] = ((p["stats"].get("rushing.rushingYards") or 0)
                          + (p["stats"].get("receiving.receivingYards") or 0))
        rbs.sort(key=lambda p: p["value"], reverse=True)
        cards.append(card("RUNNING BACKS", "SCRIMMAGE YDS", rbs))
    except Exception:
        pass

    try:
        # Wide receivers only. ESPN's receiving-yards board is positionless, so
        # tight ends place on it — a top-ten tight end outranks most receivers
        # and would take a row on a card that says WIDE RECEIVERS.
        wrs = [p for p in _pool(categories, "receivingYards") if p["pos"] == "WR"]
        for p in wrs:
            p["value"] = p["stats"].get("receiving.receivingYards") or 0
        wrs.sort(key=lambda p: p["value"], reverse=True)
        cards.append(card("WIDE RECEIVERS", "REC YDS", wrs))
    except Exception:
        pass

    return [c for c in cards if c["rows"]]


# --- leader card -------------------------------------------------------------
# 192px of height: 26 for the two-line header, 8 rows of 19, 14 of breathing
# room. Eight rows at 19px leaves the name column readable at size 11, which
# ten rows at 15px did not — "Smith-Njigba" is a lot longer than "ARS".
LDR_HEAD_H = 26
LDR_ROW_H = 19
LDR_X_RANK = 15
LDR_X_NAME = 21
LDR_X_TEAM = 120         # the value column needs 44px for "2,298" at size 12,
LDR_X_VALUE = 188        # so the team cannot sit any further right than this

# Gold, silver, bronze for the top three, then plain. The panel is seen from
# across a room, where the ordering is the only thing that survives the
# distance, so the first three rows are worth marking.
LDR_MEDALS: tuple[Color, ...] = ((255, 205, 80), (200, 205, 215), (205, 140, 85))


def render_leaders(card: dict) -> Frame:
    """One leaderboard: eight players, ranked, with the statistic on the right."""
    frame = Frame(bg=(8, 8, 8))

    frame.text(4, 9, card["title"], size=12, color=(240, 240, 240), anchor="lm")
    frame.text(188, 9, card["league_label"], size=9, color=(120, 120, 120), anchor="rm")
    frame.text(4, 20, card["season"], size=8, color=(110, 110, 110), anchor="lm")
    frame.text(188, 20, card["unit"], size=8, color=(150, 150, 150), anchor="rm")
    frame.line(0, LDR_HEAD_H - 1, 191, LDR_HEAD_H - 1, color=(45, 45, 45), width=1)

    for i, row in enumerate(card["rows"]):
        y = LDR_HEAD_H + i * LDR_ROW_H
        if i % 2 == 0:
            frame.rect(0, y, 192, LDR_ROW_H, (17, 17, 17))
        medal = LDR_MEDALS[i] if i < len(LDR_MEDALS) else None
        if medal:
            frame.rect(0, y, 3, LDR_ROW_H, medal)

        mid = y + LDR_ROW_H // 2
        frame.text(LDR_X_RANK, mid, str(i + 1), size=10,
                   color=medal or (125, 125, 125), anchor="rm")
        # text_fit, not text: "Smith-Njigba" and "St. Brown" overrun the name
        # column at size 11 and would otherwise run under the team.
        frame.text_fit(LDR_X_NAME, mid, row["name"],
                       max_width=LDR_X_TEAM - LDR_X_NAME - 3,
                       size=11, min_size=7, color=(255, 255, 255), anchor="lm")
        frame.text(LDR_X_TEAM, mid, row["team"], size=9, color=(135, 135, 135), anchor="lm")
        frame.text(LDR_X_VALUE, mid, _fmt(row["value"]), size=12,
                   color=(255, 255, 255), anchor="rm")
    return frame


def _fmt(value: float | None) -> str:
    """QBR wants a decimal; yardage does not."""
    if value is None:
        return "-"
    return f"{value:.1f}" if value < 200 else f"{value:,.0f}"


def render_no_games() -> Frame:
    frame = Frame(bg=(8, 8, 8))
    frame.text(96, 82, LEAGUE_LABEL, size=26, color=(70, 70, 70), anchor="mm")
    frame.text(96, 112, "No games", size=16, color=(50, 50, 50), anchor="mm")
    return frame
