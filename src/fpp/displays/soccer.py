"""Soccer scoreboard display — Premier League and Champions League via ESPN API."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from functools import lru_cache

import httpx
from PIL import Image, ImageDraw

from ..canvas import Color, Frame, contrast, dim

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

LEAGUES: dict[str, tuple[str, str]] = {
    "epl": ("eng.1",          "Premier League"),
    "ucl": ("uefa.champions", "Champions League"),
}


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


def fetch_games(league_key: str) -> list[dict]:
    slug, label = LEAGUES[league_key]
    resp = httpx.get(f"{ESPN_BASE}/{slug}/scoreboard", timeout=10)
    resp.raise_for_status()

    games: list[dict] = []
    for event in resp.json().get("events", []):
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


def fetch_all() -> list[dict]:
    games: list[dict] = []
    for key in LEAGUES:
        try:
            games.extend(fetch_games(key))
        except Exception:
            pass
    return games


# ------------------------------------------------------------------ rendering

LOGO_SIZE = 82
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


def render_scoreboard(game: dict) -> Frame:
    away_bg = dim(game["away_color"])
    home_bg = dim(game["home_color"])
    away_fg = contrast(*away_bg)
    home_fg = contrast(*home_bg)

    frame = Frame()

    # Team color halves (top 148px)
    frame.rect(0,  0, 96,  148, away_bg)
    frame.rect(96, 0, 96,  148, home_bg)
    frame.line(95, 0, 95, 147, color=(10, 10, 10), width=2)

    # Team names at top — above the disc
    frame.text(48,  20, game["away_abbr"], size=24, color=away_fg, anchor="mm")
    frame.text(144, 20, game["home_abbr"], size=24, color=home_fg, anchor="mm")
    frame.text(48,  36, game["away_name"], size=11, color=away_fg, anchor="mm")
    frame.text(144, 36, game["home_name"], size=11, color=home_fg, anchor="mm")

    # Logo disc centered lower, clearing the name text
    _place_logo(frame, game["away_logo"], cx=48,  cy=90, alt_color=game["away_alt_color"], bg_color=away_bg)
    _place_logo(frame, game["home_logo"], cx=144, cy=90, alt_color=game["home_alt_color"], bg_color=home_bg)

    # Scores or "vs"
    state = game["state"]
    if state == "pre":
        frame.text(96, 112, "vs", size=28, color=(160, 160, 160), anchor="mm")
    else:
        frame.text(48,  112, game["away_score"], size=44, color=away_fg, anchor="mm")
        frame.text(144, 112, game["home_score"], size=44, color=home_fg, anchor="mm")
        frame.text(96,  112, "–",  size=20, color=(120, 120, 120), anchor="mm")

    # Bottom info strip
    frame.rect(0, 148, 192, 44, (12, 12, 12))
    frame.line(0, 148, 191, 148, color=(35, 35, 35), width=1)

    # Line 1: status + date
    if state == "pre":
        clock_text = game["detail"][:30]
    elif state == "in":
        clock_text = f"{_half_period(game['period'])}  {game['clock']}"
    else:
        date_part = f"  •  {game['game_date']}" if game.get("game_date") else ""
        clock_text = game["short"] + date_part   # e.g. "FT  •  Apr 15"

    frame.text(96, 161, clock_text,          size=12, color=(210, 210, 210), anchor="mm")

    # Line 2: league + leg
    league_line = game["league_label"]
    if game["leg"]:
        league_line += f"  •  {game['leg']}"
    frame.text(96, 175, league_line,         size=11, color=(140, 140, 140), anchor="mm")

    # Line 3: aggregate or note
    if game["aggregate"]:
        frame.text(96, 188, game["aggregate"], size=10, color=(110, 110, 110), anchor="mm")
    elif game["note"]:
        frame.text(96, 188, game["note"][:32], size=9,  color=(100, 100, 100), anchor="mm")

    return frame


def render_no_games(league_key: str) -> Frame:
    _, label = LEAGUES.get(league_key, ("", league_key.upper()))
    frame = Frame(bg=(8, 8, 8))
    frame.text(96, 82,  label,      size=22, color=(70, 70, 70), anchor="mm")
    frame.text(96, 112, "No games", size=16, color=(50, 50, 50), anchor="mm")
    return frame
