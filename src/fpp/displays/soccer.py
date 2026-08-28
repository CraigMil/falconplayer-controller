"""Soccer scoreboard display — Premier League and Champions League via ESPN API.

Three things are on a card: who is playing (shields and club colours), the score
if the game is live or finished, and WHEN EACH OF THOSE TWO TEAMS PLAYS NEXT.

The last of those is the reason this module fetches twice. ESPN's per-team
schedule endpoint returns almost nothing at the start of a season — one event,
the game that has just been played — so next fixtures come from a DATE-RANGE
query against the league scoreboard instead, which returns the lot.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import httpx
from PIL import Image

from ..canvas import Color, Frame, dim

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

LEAGUES: dict[str, tuple[str, str]] = {
    "epl": ("eng.1",          "Premier League"),
    "ucl": ("uefa.champions", "Champions League"),
}

FIXTURE_DAYS = 35        # how far ahead to look for "next game"
LOOKBACK_DAYS = 14       # how far back to look for the last results

# The card list is a WEEK, not a day. Filtering results to the newest calendar
# date looked like "the last matchday" and is not one: a Premier League round is
# spread over two or three days (Jan 2026 ran Sat 3rd + Sun 4th, then Tue 6th +
# Wed 7th + Thu 8th), so a single date shows a slice of a round and leaves most
# of the league off the panel entirely. A seven-day block covers a whole round.
#
# BLOCK_ANCHOR is TUESDAY, and the day it starts on matters more than the length
# does. Measured over all 380 fixtures of 2025-26, counting clubs represented on
# every day of the season:
#
#     block starts   mean clubs   worst   all 20 on
#     Mon                  18.8      16     45% of days
#     Tue                  19.8      16     94% of days
#     Wed                  19.3      12     86% of days
#     Thu                  18.2       2     86% of days
#     Sun                  14.6       6     13% of days
#
# A Monday start splits Monday Night Football away from the weekend round it
# belongs to, so the block clips one game off that round and picks up an orphan
# from the next. Tue -> Mon holds a round whole: midweek Tuesday and Wednesday,
# the Saturday and Sunday programme, and MNF closing it out.
BLOCK_ANCHOR = 1         # 0 = Monday, so 1 = Tuesday
BLOCK_DAYS = 7


# ------------------------------------------------------------------ data fetch


def _hex(s: str) -> Color:
    h = (s or "").lstrip("#").strip()
    if len(h) == 6:
        try:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        except ValueError:
            pass
    return (40, 40, 40)


def _parse_date(iso: str) -> str:
    """Return short date string like 'Apr 15' from ISO timestamp."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%b %-d")
    except Exception:
        return ""


@lru_cache(maxsize=64)
def _fetch_logo(url: str) -> Image.Image | None:
    try:
        resp = httpx.get(url, timeout=5, follow_redirects=True)
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content)).convert("RGBA")
    except Exception:
        return None


def _team(competitor: dict) -> dict:
    return competitor.get("team", {})


def _kickoff(iso: str) -> datetime | None:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None


def _when(iso: str) -> str:
    """Short, human phrasing for a kickoff — the nearer it is, the more precise.

    "Sat 30 Aug" is the right answer for something a fortnight away and a
    useless one for something starting in two hours, so a fixture inside the
    next couple of days gives the time instead.
    """
    dt = _kickoff(iso)
    if dt is None:
        return ""
    local = dt.astimezone()
    today = datetime.now().astimezone().date()
    days = (local.date() - today).days
    if days == 0:
        return f"Today {local:%H:%M}"
    if days == 1:
        return f"Tmrw {local:%H:%M}"
    if days < 7:
        return f"{local:%a} {local:%H:%M}"
    return f"{local:%a} {local.day} {local:%b}"


def _scoreboard_json(slug: str, dates: str | None = None) -> dict:
    url = f"{ESPN_BASE}/{slug}/scoreboard"
    if dates:
        url += f"?dates={dates}"
    resp = httpx.get(url, timeout=15)
    resp.raise_for_status()
    return resp.json()


STANDINGS_BASE = "https://site.api.espn.com/apis/v2/sports/soccer"

# The table is split across two cards because ten rows is what fits legibly in
# 192px once the header and the key have taken their share.
TABLE_ROWS = 10


def fetch_standings(league_key: str) -> list[dict]:
    """The league table, one row per club, in rank order.

    The qualification bands come from ESPN's own per-entry `note`, NOT from
    hard-coded positions. England's Champions League allocation is five places
    in some seasons and four in others — it depends on a UEFA coefficient
    settled during the season — and the Europa place moves whenever a cup
    winner has already qualified by league position. Anything written down here
    would be wrong within a year and wrong silently.

    Their colours arrive malformed: the Europa band is "##B5E7CE", with two
    hashes. `_hex()` strips them all, which is the only reason this works.
    """
    slug, _ = LEAGUES[league_key]
    resp = httpx.get(f"{STANDINGS_BASE}/{slug}/standings", timeout=15)
    resp.raise_for_status()
    data = resp.json()

    groups = data.get("children") or []
    entries = (groups[0].get("standings", {}) if groups else data.get("standings", {})).get("entries", [])

    rows: list[dict] = []
    for entry in entries:
        stat = {x.get("name"): x.get("displayValue", "") for x in entry.get("stats", [])}
        note = entry.get("note") or {}
        team = entry.get("team", {})
        rows.append({
            "rank":   int(stat.get("rank") or 0),
            "abbr":   team.get("abbreviation", "???"),
            "name":   team.get("shortDisplayName", ""),
            "played": stat.get("gamesPlayed", "0"),
            "gd":     stat.get("pointDifferential", "0"),
            "points": stat.get("points", "0"),
            "band":   note.get("description", ""),
            "band_color": _hex(note.get("color", "")) if note.get("color") else None,
        })
    rows.sort(key=lambda r: r["rank"])
    return rows


def table_cards(league_key: str) -> list[dict]:
    """The two table cards, or nothing at all if the standings cannot be had.

    Returning [] on failure rather than raising is deliberate: a table is a
    nice-to-have on a scoreboard, and an ESPN hiccup should cost you the table,
    not the scores.
    """
    try:
        rows = fetch_standings(league_key)
    except Exception:
        return []
    if not rows:
        return []
    _, label = LEAGUES[league_key]
    out = []
    for start in range(0, len(rows), TABLE_ROWS):
        chunk = rows[start:start + TABLE_ROWS]
        out.append({
            "kind":  "table",
            "league_label": label,
            "rows":  chunk,
            "range": f"{chunk[0]['rank']}-{chunk[-1]['rank']}",
            "bands": [r for r in rows if r["band"]],
        })
    return out


def _daterange(start: datetime, end: datetime) -> str:
    return f"{start:%Y%m%d}-{end:%Y%m%d}"


def _block_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """The Tue->Mon block containing `now`, as local midnight boundaries.

    Local, not UTC: a Monday night kickoff at 20:00 UK is Tuesday in UTC, and
    on a UTC boundary it would fall into the following week away from the round
    it belongs to — the exact failure BLOCK_ANCHOR exists to avoid.
    """
    local = (now or datetime.now(timezone.utc)).astimezone()
    back = (local.weekday() - BLOCK_ANCHOR) % 7
    start = (local - timedelta(days=back)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=BLOCK_DAYS)


def fetch_fixtures(league_keys: list[str], days: int = FIXTURE_DAYS) -> list[dict]:
    """Every upcoming fixture in the next `days`, flattened to what a card needs.

    ESPN's /teams/{id}/schedule endpoint is the obvious way to ask "when does
    this team play next" and it does not work early in a season — it returned a
    single event, the game just finished. A date range against the league
    scoreboard returns all 44 of the next five weeks' fixtures in one request,
    so that is what this uses.
    """
    now = datetime.now(timezone.utc)
    span = _daterange(now, now + timedelta(days=days))
    out: list[dict] = []
    for key in league_keys:
        slug, label = LEAGUES[key]
        try:
            data = _scoreboard_json(slug, span)
        except Exception:
            continue
        for event in data.get("events", []):
            comp = event["competitions"][0]
            competitors = comp.get("competitors", [])
            home = next((c for c in competitors if c.get("homeAway") == "home"), {})
            away = next((c for c in competitors if c.get("homeAway") == "away"), {})
            if not home or not away:
                continue
            out.append({
                "event_id":  str(event.get("id", "")),
                "date":      event.get("date", ""),
                "home_id":   str(_team(home).get("id", "")),
                "away_id":   str(_team(away).get("id", "")),
                "home_abbr": _team(home).get("abbreviation", "???"),
                "away_abbr": _team(away).get("abbreviation", "???"),
                "league":    label,
            })
    out.sort(key=lambda f: f["date"])
    return out


def next_fixture(fixtures: list[dict], team_id: str, exclude_event: str = "") -> dict | None:
    """This team's next fixture, as {opponent, home, when, league}.

    `exclude_event` matters more than it looks. A card for a game that has not
    kicked off yet would otherwise report that same game as the team's next
    fixture — technically true, and useless on a card already showing it.
    """
    now = datetime.now(timezone.utc)
    for f in fixtures:
        if f["event_id"] and f["event_id"] == exclude_event:
            continue
        dt = _kickoff(f["date"])
        if dt is None or dt <= now:
            continue
        if f["home_id"] == team_id:
            return {"opponent": f["away_abbr"], "home": True,
                    "when": _when(f["date"]), "league": f["league"]}
        if f["away_id"] == team_id:
            return {"opponent": f["home_abbr"], "home": False,
                    "when": _when(f["date"]), "league": f["league"]}
    return None


def attach_next(games: list[dict], fixtures: list[dict]) -> list[dict]:
    """Hang each team's next fixture onto every game, in place."""
    for g in games:
        g["home_next"] = next_fixture(fixtures, g["home_id"], g["event_id"])
        g["away_next"] = next_fixture(fixtures, g["away_id"], g["event_id"])
    return games


def fetch_games(league_key: str, dates: str | None = None) -> list[dict]:
    slug, label = LEAGUES[league_key]
    data = _scoreboard_json(slug, dates)

    games: list[dict] = []
    for event in data.get("events", []):
        comp = event["competitions"][0]
        competitors = comp.get("competitors", [])
        home = next((c for c in competitors if c.get("homeAway") == "home"), {})
        away = next((c for c in competitors if c.get("homeAway") == "away"), {})
        status = comp.get("status", {})
        status_type = status.get("type", {})

        leg_label = comp.get("leg", {}).get("displayValue")
        note = (comp.get("notes") or [{}])[0].get("text", "")

        home_agg = home.get("aggregateScore")
        away_agg = away.get("aggregateScore")
        agg_str: str | None = None
        if home_agg is not None and away_agg is not None and leg_label:
            hi, ai = int(home_agg), int(away_agg)
            agg_str = (
                f"AGG  {_team(away).get('abbreviation','AWY')} {ai}"
                f" – {hi} {_team(home).get('abbreviation','HME')}"
            )

        games.append({
            "event_id":       str(event.get("id", "")),
            "kickoff":        event.get("date", ""),
            "home_id":        str(_team(home).get("id", "")),
            "away_id":        str(_team(away).get("id", "")),
            "home_abbr":      _team(home).get("abbreviation", "???"),
            "home_name":      _team(home).get("shortDisplayName", ""),
            "home_score":     home.get("score", "0"),
            "home_color":     _hex(_team(home).get("color", "")),
            "home_alt_color": _hex(_team(home).get("alternateColor", "")),
            "home_logo":      _team(home).get("logo", ""),
            "away_abbr":      _team(away).get("abbreviation", "???"),
            "away_name":      _team(away).get("shortDisplayName", ""),
            "away_score":     away.get("score", "0"),
            "away_color":     _hex(_team(away).get("color", "")),
            "away_alt_color": _hex(_team(away).get("alternateColor", "")),
            "away_logo":      _team(away).get("logo", ""),
            "state":          status_type.get("state", "pre"),
            "clock":          status.get("displayClock", ""),
            "period":         status.get("period", 0),
            "short":          status_type.get("shortDetail", ""),
            "detail":         status_type.get("detail", ""),
            "game_date":      _parse_date(event.get("date", "")),
            "leg":            leg_label,
            "aggregate":      agg_str,
            "note":           note,
            "league_label":   label,
            "league_key":     league_key,
        })
    return games


def fetch_all(dates: str | None = None) -> list[dict]:
    games: list[dict] = []
    for key in LEAGUES:
        try:
            games.extend(fetch_games(key, dates))
        except Exception:
            pass
    return games


def select_cards(league_keys: list[str], max_cards: int = 24) -> tuple[list[dict], str]:
    """What the panel should show right now, and a one-word reason.

    One card per game in the current Tue->Mon block, in kickoff order, so the
    week reads forwards: results first, then what is still to come. Every club
    that plays this week gets a card, and each card carries both sides' next
    fixture, which is how a team that has already played is still told to you.

    Ordering is chronological with one exception — anything LIVE goes first.
    A game in progress is the only thing on the panel that changes while you
    watch it, and burying it behind Tuesday's result wastes it.

    The block is empty for about 35 days a season (international breaks). Then,
    and only then, it falls back to the last results plus the next fixtures, so
    the panel still says something useful during a fortnight with no football.
    """
    now = datetime.now(timezone.utc)
    start, end = _block_bounds(now)
    span = _daterange(start, end)

    block: list[dict] = []
    for key in league_keys:
        try:
            block.extend(fetch_games(key, span))
        except Exception:
            pass

    # ESPN answers a date range generously at the edges — it has returned games
    # from the day either side — so the window is re-applied here rather than
    # trusted. Without it a Monday-night game leaks in from the block just gone.
    block = [g for g in block
             if (k := _kickoff(g["kickoff"])) and start <= k.astimezone() < end]

    if block:
        block.sort(key=lambda g: g["kickoff"])
        live = [g for g in block if g["state"] == "in"]
        rest = [g for g in block if g["state"] != "in"]
        return (live + rest)[:max_cards], "week"

    past = _daterange(now - timedelta(days=LOOKBACK_DAYS), now)
    ahead = _daterange(now, now + timedelta(days=LOOKBACK_DAYS))

    recent: list[dict] = []
    upcoming: list[dict] = []
    for key in league_keys:
        try:
            recent += [g for g in fetch_games(key, past) if g["state"] == "post"]
        except Exception:
            pass
        try:
            upcoming += [g for g in fetch_games(key, ahead) if g["state"] == "pre"]
        except Exception:
            pass

    recent.sort(key=lambda g: g["kickoff"])
    upcoming.sort(key=lambda g: g["kickoff"])
    half = max(1, max_cards // 2)
    return (recent[-half:] + upcoming[:max_cards - half]), "idle"


# ------------------------------------------------------------------ rendering

# Vertical budget for a 192x192 card. The next-game strip costs 44px, so the
# match itself gets 126 rather than the 148 it used to have — shields and score
# both came down a size to pay for it.
TEAM_H = 126             # club-colour halves, 0..125
STATUS_Y, STATUS_H = 126, 22
NEXT_Y = 148             # two rows of 22px, 148..191

# The crest is sized by the CORRIDOR between the club name above it and the
# score below, because Premier League crests are tall and narrow — Spurs is
# 224x458 in its own file, so a square box binds on height and leaves two
# thirds of the 96px half-width unused. Measured ink: the name bottoms out at
# y=35 and the score tops at y=98, so 62 centred on 66 is the largest box that
# clears both. NFL marks are the opposite shape (462x206) and simply get wider.
LOGO_SIZE = 62
LOGO_CY = 66

# Was 106. The score moved down to the floor of the team area to give the
# crest that corridor: at size 36 its ink runs y=98..124, and the status bar
# starts at 126. Anything lower clips.
SCORE_Y = 111
# Full strength. It went 0.55 -> 0.75 when the disc behind the logo was
# removed, because the disc had been supplying the contrast that made a mark
# readable against its own club colour. The club colour is now gone too, and
# on black there is nothing left for a knocked-back logo to separate from —
# any opacity below 1.0 is just dimmer ink on the same ground.
LOGO_OPACITY = 1.0

# Cap on the per-logo brightness lift. 2.2 pulls a mark whose brightest ink
# sits around 116 up to full; past that the lift starts flattening a dark
# crest's internal shading into one block of colour, which reads as a
# silhouette rather than a badge.
LOGO_GAIN_MAX = 2.2


# Alpha below this is treated as empty when finding the mark's extent. A hard
# "any non-zero pixel" test is too eager: several crests carry a faint halo of
# 1-3 alpha from their original export, which reaches most of the way to the
# canvas edge and would defeat the crop entirely.
LOGO_INK_ALPHA = 16


def _crop_to_ink(logo: Image.Image) -> Image.Image:
    """Trim the transparent margin baked into the source PNG.

    thumbnail() fits the CANVAS, not the mark, so a crest exported with a
    margin renders smaller than one exported tight — Premier League crests
    carry about 8% and the row of them looked ragged as a result. Cropping
    first means the box is filled by ink in every case, which both enlarges
    the marks and makes them agree with each other.
    """
    bbox = logo.split()[3].point(lambda v: 255 if v > LOGO_INK_ALPHA else 0).getbbox()
    return logo.crop(bbox) if bbox else logo


def _brighten(logo: Image.Image) -> Image.Image:
    """Scale a logo's colour channels so its brightest ink reaches full.

    Team marks arrive at wildly different exposures — a navy-on-navy crest
    peaks near 90 where a white-on-red one is already at 255. Behind the
    club-colour half that spread was masked; on black the dark ones simply
    sink into the card.

    The peak is measured over OPAQUE pixels only. ESPN's PNGs carry arbitrary
    RGB under a zero alpha, and a single stray white transparent pixel would
    set the peak to 255 and silently disable the lift for that team.
    """
    black = Image.new("RGB", logo.size, (0, 0, 0))
    black.paste(logo, (0, 0), mask=logo.split()[3])
    peak = max(hi for _, hi in black.getextrema())
    if peak == 0:
        return logo

    gain = min(LOGO_GAIN_MAX, 255.0 / peak)
    if gain <= 1.01:
        return logo

    lut = [min(255, int(v * gain + 0.5)) for v in range(256)]
    r, g, b, a = logo.split()
    return Image.merge("RGBA", (r.point(lut), g.point(lut), b.point(lut), a))


def _place_logo(frame: Frame, url: str, cx: int, cy: int) -> None:
    """Composite a logo centered at (cx, cy), lifted to full brightness.

    There used to be a translucent disc behind the logo for contrast. It was
    removed because it collided with the team name: its radius was
    LOGO_SIZE // 2 + 6 = 35 about a centre at y=64, so its top edge landed on
    y=29 — exactly the row the full club name is drawn on. The overlap was
    geometric, not occasional.

    Crop and brighten BEFORE the thumbnail: LANCZOS mixes ink with the
    transparent surround, so resizing first would fold those
    RGB-under-zero-alpha pixels into the edge and shift the peak the gain is
    measured from, as well as leaving the source margin in the box.
    """
    if not url:
        return
    logo = _fetch_logo(url)
    if logo is None:
        return
    logo = _brighten(_crop_to_ink(logo.copy()))
    logo.thumbnail((LOGO_SIZE, LOGO_SIZE), Image.LANCZOS)
    lw, lh = logo.size
    frame.paste(logo, cx - lw // 2, cy - lh // 2, opacity=LOGO_OPACITY)


def _half_period(period: int) -> str:
    return {1: "1H", 2: "2H"}.get(period, "ET")


def _next_row(frame: Frame, y: int, abbr: str, colour: Color, nxt: dict | None) -> None:
    """One line of the next-game strip: colour chip, team, opponent, when.

    The chip is the club colour at full strength rather than the dimmed version
    used behind the shields — it is four pixels wide, and a dimmed four-pixel
    bar is just a dark smudge.
    """
    frame.rect(4, y + 4, 4, 14, colour)
    frame.text(14, y + 11, abbr, size=11, color=(215, 215, 215), anchor="lm")

    if not nxt:
        frame.text(50, y + 11, "no fixture scheduled", size=9,
                   color=(95, 95, 95), anchor="lm")
        return

    # Laid out from the MEASURED width of the abbreviation, not a fixed column.
    # Three-letter codes are not three equal widths — "MAN" ran into a separator
    # parked at x=48 while "SUN" cleared it easily.
    x = 14 + frame.text_width(abbr, 11) + 7
    # "v" for home, "@" for away — three characters of context for one glyph.
    sep = "v" if nxt["home"] else "@"
    frame.text(x, y + 11, sep, size=10, color=(120, 120, 120), anchor="lm")
    x += frame.text_width(sep, 10) + 7
    frame.text(x, y + 11, nxt["opponent"], size=11, color=(215, 215, 215), anchor="lm")
    frame.text(188, y + 11, nxt["when"], size=10, color=(150, 150, 150), anchor="rm")


# Every team's side of the card is now the same ground, so the text colour no
# longer depends on which club is on it. contrast() on black would return this
# for both halves; naming it once says the halves are gone on purpose.
CARD_FG = (255, 255, 255)


def render_scoreboard(game: dict) -> Frame:
    away_fg = home_fg = CARD_FG

    frame = Frame()

    # The club-colour halves are gone — the card is black behind both teams,
    # and the identity is carried by the logo and the abbreviation instead.
    # The seam still needs marking, but a 2px line that used to read as a
    # join between two colours has to be lighter than the ground now that it
    # is the only thing there.
    frame.line(95, 0, 95, TEAM_H - 1, color=(30, 30, 30), width=2)

    # Names above the shield
    frame.text(48,  15, game["away_abbr"], size=21, color=away_fg, anchor="mm")
    frame.text(144, 15, game["home_abbr"], size=21, color=home_fg, anchor="mm")
    frame.text_fit(48,  29, game["away_name"], max_width=90, size=10, color=away_fg)
    frame.text_fit(144, 29, game["home_name"], max_width=90, size=10, color=home_fg)

    _place_logo(frame, game["away_logo"], cx=48,  cy=LOGO_CY)
    _place_logo(frame, game["home_logo"], cx=144, cy=LOGO_CY)

    state = game["state"]
    if state == "pre":
        # The "vs" used to need its own dark patch, because it straddled the
        # seam between two club colours and vanished into whichever was
        # lighter. Both sides are black now, so the patch would be a black
        # rectangle on black.
        frame.text(96, SCORE_Y, "vs", size=22, color=(205, 205, 205), anchor="mm")
    else:
        frame.text(48,  SCORE_Y, game["away_score"], size=36, color=away_fg, anchor="mm")
        frame.text(144, SCORE_Y, game["home_score"], size=36, color=home_fg, anchor="mm")
        frame.text(96,  SCORE_Y, "–", size=17, color=(120, 120, 120), anchor="mm")

    # Status bar. Its ground is black like everything else, so the rule along
    # the top is now the whole of what separates it from the match above.
    frame.line(0, STATUS_Y, 191, STATUS_Y, color=(38, 38, 38), width=1)

    if state == "pre":
        clock_text = _when(game.get("kickoff", "")) or game["detail"][:24]
        clock_col = (200, 200, 200)
    elif state == "in":
        # period_label lets another sport supply its own reading of `period` —
        # the NFL module sends "Q3" where this would have said "2nd half".
        clock_text = f"{game.get('period_label') or _half_period(game['period'])}  {game['clock']}"
        clock_col = (120, 255, 140)      # live is the one thing worth a colour
    else:
        clock_text = game["short"]
        clock_col = (200, 200, 200)

    league_line = game["league_label"]
    if game.get("leg"):
        league_line += f" · {game['leg']}"
    if state == "post" and game.get("game_date"):
        league_line += f" · {game['game_date']}"

    frame.text(6, STATUS_Y + 11, clock_text, size=12, color=clock_col, anchor="lm")
    frame.text_fit(140, STATUS_Y + 11, league_line, max_width=100, size=10,
                   color=(140, 140, 140))

    # Next-game strip — same story as the status bar: rule only, no ground.
    frame.line(0, NEXT_Y, 191, NEXT_Y, color=(38, 38, 38), width=1)

    if game.get("aggregate"):
        # A two-legged tie says more than either team's next fixture does.
        frame.text(96, NEXT_Y + 13, game["aggregate"], size=11,
                   color=(190, 190, 190), anchor="mm")
        if game.get("note"):
            frame.text_fit(96, NEXT_Y + 32, game["note"], max_width=184, size=9,
                           color=(115, 115, 115))
    else:
        _next_row(frame, NEXT_Y + 0,  game["away_abbr"], game["away_color"],
                  game.get("away_next"))
        _next_row(frame, NEXT_Y + 22, game["home_abbr"], game["home_color"],
                  game.get("home_next"))

    return frame


# --- league table card -------------------------------------------------------
# 192px of height, spent: 17 header, 10 rows of 15, 25 for the key. Ten rows is
# the most that stays legible — at twelve the row is 12px and the abbreviation
# and the points column start to touch.
TBL_HEAD_H = 17
TBL_ROW_H = 15
TBL_KEY_H = 25
TBL_BAR_W = 3            # left edge colour bar marking a qualification band

# Column right edges, tuned so PTS never collides with GD on "-10" or "+10".
TBL_X_POS = 17           # position number, right-aligned
TBL_X_ABBR = 23          # club abbreviation, left-aligned
TBL_X_PL = 128           # played
TBL_X_GD = 158           # goal difference
TBL_X_PTS = 187          # points


def _band_kind(desc: str) -> str:
    """Collapse ESPN's wording to the three things a row can be."""
    d = (desc or "").lower()
    if "relegation" in d:
        return "rel"
    if "champions" in d:
        return "ucl"
    if "europa" in d or "conference" in d:
        return "uel"
    return ""


def render_table(card: dict) -> Frame:
    """One half of the league table.

    Relegation is a filled RED row, as the strongest signal on the card — going
    down is the thing you want to read at a glance from across a room. European
    qualification is a colour bar down the left edge plus a faint wash, which
    reads as "marked" without competing with it.

    The band colours below stay — they encode which zone a club is in, and
    are the point of the card. Only the card's own ground goes black.
    """
    frame = Frame()

    frame.text(4, 8, card["league_label"].upper(), size=9,
               color=(120, 120, 120), anchor="lm")
    frame.text(188, 8, card["range"], size=10, color=(200, 200, 200), anchor="rm")
    frame.line(0, TBL_HEAD_H - 1, 191, TBL_HEAD_H - 1, color=(45, 45, 45), width=1)

    for i, row in enumerate(card["rows"]):
        y = TBL_HEAD_H + i * TBL_ROW_H
        kind = _band_kind(row["band"])
        colour = row["band_color"] or (90, 90, 90)

        if kind == "rel":
            frame.rect(0, y, 192, TBL_ROW_H, dim(colour, 0.62, floor=40))
        elif i % 2 == 0:
            frame.rect(0, y, 192, TBL_ROW_H, (17, 17, 17))
        if kind in ("ucl", "uel"):
            frame.rect(0, y, 192, TBL_ROW_H, dim(colour, 0.16, floor=10))
            frame.rect(0, y, TBL_BAR_W, TBL_ROW_H, colour)

        mid = y + TBL_ROW_H // 2
        pos_col = (235, 235, 235) if kind == "rel" else (135, 135, 135)
        frame.text(TBL_X_POS, mid, str(row["rank"]), size=10, color=pos_col, anchor="rm")
        frame.text(TBL_X_ABBR, mid, row["abbr"], size=12, color=(255, 255, 255), anchor="lm")
        frame.text(TBL_X_PL, mid, str(row["played"]), size=9, color=(120, 120, 120), anchor="rm")
        frame.text(TBL_X_GD, mid, str(row["gd"]), size=9, color=(165, 165, 165), anchor="rm")
        frame.text(TBL_X_PTS, mid, str(row["points"]), size=12, color=(255, 255, 255), anchor="rm")

    # The key. Built from the bands actually present in THIS season's table, so
    # a year when England has five Champions League places, or no Conference
    # place at all, labels itself correctly with no edit here.
    ky = 192 - TBL_KEY_H
    frame.line(0, ky, 191, ky, color=(45, 45, 45), width=1)
    seen: dict[str, tuple] = {}
    for row in card["bands"]:
        k = _band_kind(row["band"])
        if k and k not in seen:
            seen[k] = (row["band_color"] or (90, 90, 90), _KEY_LABEL.get(k, k.upper()))

    if seen:
        slot = 192 // len(seen)
        for j, (k, (colour, label)) in enumerate(seen.items()):
            cx = j * slot + 4
            cy = ky + TBL_KEY_H // 2
            frame.rect(cx, cy - 4, 8, 8, colour)
            # text_fit, not text: "RELEGATION" overruns its slot at size 9 and
            # the last card in the cycle then reads "RELEGATIO".
            frame.text_fit(cx + 12, cy, label, max_width=slot - 17,
                           size=9, min_size=6, color=(185, 185, 185), anchor="lm")
    return frame


_KEY_LABEL = {"ucl": "UCL", "uel": "EUROPA", "rel": "RELEGATION"}


def render_no_games(league_key: str) -> Frame:
    _, label = LEAGUES.get(league_key, ("", league_key.upper()))
    frame = Frame()
    frame.text(96, 82,  label,      size=22, color=(70, 70, 70), anchor="mm")
    frame.text(96, 112, "No games", size=16, color=(50, 50, 50), anchor="mm")
    return frame
