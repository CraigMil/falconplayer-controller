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
from PIL import Image, ImageDraw

from ..canvas import Color, Frame, contrast, dim

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

LEAGUES: dict[str, tuple[str, str]] = {
    "epl": ("eng.1",          "Premier League"),
    "ucl": ("uefa.champions", "Champions League"),
}

FIXTURE_DAYS = 35        # how far ahead to look for "next game"
LOOKBACK_DAYS = 14       # how far back to look for the last results


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


def _daterange(start: datetime, end: datetime) -> str:
    return f"{start:%Y%m%d}-{end:%Y%m%d}"


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


def select_cards(league_keys: list[str], max_cards: int = 12) -> tuple[list[dict], str]:
    """What the panel should show right now, and a one-word reason.

    Most of the time no match is in progress — a league plays for about six
    hours a week — so "live scores" alone would leave the panel blank almost
    always. The fallback is the last matchday's results followed by the next
    matchday's fixtures, which keeps it saying something useful at 3am on a
    Wednesday.
    """
    today: list[dict] = []
    for key in league_keys:
        try:
            today.extend(fetch_games(key))
        except Exception:
            pass

    live = [g for g in today if g["state"] == "in"]
    if live:
        rest = [g for g in today if g["state"] != "in"]
        return (live + rest)[:max_cards], "live"

    now = datetime.now(timezone.utc)
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

    # Only the MOST RECENT matchday, not a fortnight of them — otherwise a
    # midweek cycle runs for ten minutes and nothing on it is news.
    if recent:
        recent.sort(key=lambda g: g["kickoff"], reverse=True)
        newest = (_kickoff(recent[0]["kickoff"]) or now).date()
        recent = [g for g in recent
                  if (_kickoff(g["kickoff"]) or now).date() == newest]
        recent.reverse()
    if upcoming:
        upcoming.sort(key=lambda g: g["kickoff"])
        soonest = (_kickoff(upcoming[0]["kickoff"]) or now).date()
        upcoming = [g for g in upcoming
                    if (_kickoff(g["kickoff"]) or now).date() == soonest]

    if today and not recent and not upcoming:
        return today[:max_cards], "today"
    half = max(1, max_cards // 2)
    return (recent[:half] + upcoming[:max_cards - len(recent[:half])]), "idle"


# ------------------------------------------------------------------ rendering

# Vertical budget for a 192x192 card. The next-game strip costs 44px, so the
# match itself gets 126 rather than the 148 it used to have — shields and score
# both came down a size to pay for it.
TEAM_H = 126             # club-colour halves, 0..125
STATUS_Y, STATUS_H = 126, 22
NEXT_Y = 148             # two rows of 22px, 148..191

LOGO_SIZE = 58
LOGO_OPACITY = 0.55
DISC_OPACITY = 0.38


def _disc_color(alt_color: Color, bg_color: Color) -> Color:
    """Return alt_color, brightened if it's too similar to the background."""
    bg_lum = 0.299 * bg_color[0] + 0.587 * bg_color[1] + 0.114 * bg_color[2]
    alt_lum = 0.299 * alt_color[0] + 0.587 * alt_color[1] + 0.114 * alt_color[2]
    if abs(alt_lum - bg_lum) < 55:
        # Too close — blend alt_color toward its opposite brightness
        target = 230 if bg_lum < 128 else 25
        blend = 0.55
        return tuple(int(c * (1 - blend) + target * blend) for c in alt_color)  # type: ignore
    return alt_color


def _place_logo(frame: Frame, url: str, cx: int, cy: int, alt_color: Color, bg_color: Color) -> None:
    """Composite a logo centered at (cx, cy) with a contrasting disc behind it."""
    disc_r = LOGO_SIZE // 2 + 6
    disc_size = disc_r * 2
    fill = _disc_color(alt_color, bg_color) + (int(255 * DISC_OPACITY),)
    disc_img = Image.new("RGBA", (disc_size, disc_size), (0, 0, 0, 0))
    ImageDraw.Draw(disc_img).ellipse([0, 0, disc_size - 1, disc_size - 1], fill=fill)
    frame.paste(disc_img, cx - disc_r, cy - disc_r, opacity=1.0)

    if not url:
        return
    logo = _fetch_logo(url)
    if logo is None:
        return
    logo = logo.copy()
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


def render_scoreboard(game: dict) -> Frame:
    away_bg = dim(game["away_color"])
    home_bg = dim(game["home_color"])
    away_fg = contrast(*away_bg)
    home_fg = contrast(*home_bg)

    frame = Frame()

    # Club-colour halves
    frame.rect(0,  0, 96, TEAM_H, away_bg)
    frame.rect(96, 0, 96, TEAM_H, home_bg)
    frame.line(95, 0, 95, TEAM_H - 1, color=(10, 10, 10), width=2)

    # Names above the shield
    frame.text(48,  15, game["away_abbr"], size=21, color=away_fg, anchor="mm")
    frame.text(144, 15, game["home_abbr"], size=21, color=home_fg, anchor="mm")
    frame.text_fit(48,  29, game["away_name"], max_width=90, size=10, color=away_fg)
    frame.text_fit(144, 29, game["home_name"], max_width=90, size=10, color=home_fg)

    _place_logo(frame, game["away_logo"], cx=48,  cy=64,
                alt_color=game["away_alt_color"], bg_color=away_bg)
    _place_logo(frame, game["home_logo"], cx=144, cy=64,
                alt_color=game["home_alt_color"], bg_color=home_bg)

    state = game["state"]
    if state == "pre":
        # On its own the "vs" straddles the seam between two club colours and
        # disappears into whichever is lighter. Give it its own ground.
        frame.rect(78, 92, 36, 28, (12, 12, 12))
        frame.text(96, 106, "vs", size=22, color=(205, 205, 205), anchor="mm")
    else:
        frame.text(48,  106, game["away_score"], size=36, color=away_fg, anchor="mm")
        frame.text(144, 106, game["home_score"], size=36, color=home_fg, anchor="mm")
        frame.text(96,  106, "–", size=17, color=(120, 120, 120), anchor="mm")

    # Status bar
    frame.rect(0, STATUS_Y, 192, STATUS_H, (14, 14, 14))
    frame.line(0, STATUS_Y, 191, STATUS_Y, color=(38, 38, 38), width=1)

    if state == "pre":
        clock_text = _when(game.get("kickoff", "")) or game["detail"][:24]
        clock_col = (200, 200, 200)
    elif state == "in":
        clock_text = f"{_half_period(game['period'])}  {game['clock']}"
        clock_col = (120, 255, 140)      # live is the one thing worth a colour
    else:
        clock_text = game["short"]
        clock_col = (200, 200, 200)

    league_line = game["league_label"]
    if game["leg"]:
        league_line += f" · {game['leg']}"
    if state == "post" and game.get("game_date"):
        league_line += f" · {game['game_date']}"

    frame.text(6, STATUS_Y + 11, clock_text, size=12, color=clock_col, anchor="lm")
    frame.text_fit(140, STATUS_Y + 11, league_line, max_width=100, size=10,
                   color=(140, 140, 140))

    # Next-game strip
    frame.rect(0, NEXT_Y, 192, 192 - NEXT_Y, (9, 9, 9))
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


def render_no_games(league_key: str) -> Frame:
    _, label = LEAGUES.get(league_key, ("", league_key.upper()))
    frame = Frame(bg=(8, 8, 8))
    frame.text(96, 82,  label,      size=22, color=(70, 70, 70), anchor="mm")
    frame.text(96, 112, "No games", size=16, color=(50, 50, 50), anchor="mm")
    return frame
