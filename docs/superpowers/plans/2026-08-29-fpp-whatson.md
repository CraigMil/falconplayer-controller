# What's On — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `fpp whatson`, a display service for the 192x192 LED panel that shows what sport worth watching is on today and tomorrow, what channel it is on, and what highlights have just been posted.

**Architecture:** A new package `src/fpp/displays/whatson/` with one responsibility per module: fetch and normalise ESPN events (three different event shapes), classify broadcasts into watchable/payable/unavailable, rank and cap into blocks, and render 192x192 cards. Highlights are a separate module reading YouTube RSS and rendering QR codes. A `whatson` CLI command drives the same upload-and-playlist loop the scoreboard already uses.

**Tech Stack:** Python 3.11, Click, Pillow, httpx (all already present). Two new dependencies: `PyYAML` for the editable config files and `segno` for QR rendering. Tests are pytest against committed fixtures — no network.

**Spec:** `docs/superpowers/specs/2026-08-29-fpp-whatson-design.md`

## Global Constraints

- **Timezone is `America/Los_Angeles` everywhere.** Day boundaries are PDT midnight; all displayed times are PDT. ESPN returns UTC.
- **Canvas is 192x192.** Use `fpp.canvas.Frame`; never assume other dimensions.
- **No network in tests.** Every test reads from `tests/fixtures/espn/`. Fixtures were captured 2026-08-29 — see `tests/fixtures/espn/README.md` for what each one pins down.
- **Follow existing display patterns**: `fetch_*() -> list[dict]`, `select_cards() -> tuple[list[dict], str]`, `render_*(card) -> Frame`. Cards are plain dicts, as in `soccer.py` and `nfl.py`.
- **Line length 100**, ruff lint `E,F,I`. Run `hatch run ruff check src tests` before every commit.
- **Caps:** NFL 3, NCAAF 3, EPL 3, cups 2 (combined), tennis 2, F1 2, oddity 1, home 4, highlights 3.
- **Dwell defaults:** `--interval 12`, `--cycle 210`, `--min-interval 6`. Highlight cards hold a 15s floor, exempt from shrink-to-fit.
- **Never display a foreign-only feed** (`Sportsnet`, `TVA`, `Universo` alone, `TUDN` alone).

---

## File Structure

| File | Responsibility |
|---|---|
| `src/fpp/displays/whatson/__init__.py` | Public API re-exports only |
| `src/fpp/displays/whatson/config.py` | Load the three YAML config files |
| `src/fpp/displays/whatson/channels.py` | Normalise broadcast names; classify into tiers; pick the best channel |
| `src/fpp/displays/whatson/window.py` | PDT day window: bounds, bucketing, time formatting |
| `src/fpp/displays/whatson/sources.py` | ESPN fetch + the three event-shape adapters |
| `src/fpp/displays/whatson/select.py` | Majorness, drama, ranking, caps, block assembly |
| `src/fpp/displays/whatson/cards.py` | Render day dividers, event cards, single-title cards, empty state |
| `src/fpp/displays/whatson/qr.py` | QR generation sized for the panel |
| `src/fpp/displays/whatson/highlights.py` | YouTube RSS fetch, title matching, highlight cards |
| `src/fpp/data/*.yaml` | `oddities.yaml`, `home_teams.yaml`, `highlight_sources.yaml` |
| `src/fpp/cli.py` | New `whatson` command (modify) |
| `device/*` | Unit file, sudoers, panel-ctl and control-server registration |

A package rather than the single `displays/<name>.py` the repo uses elsewhere: `soccer.py` is already 31KB and hard to hold in context, and this feature has strictly more moving parts. The public surface stays module-shaped via `__init__.py`, so `from .displays import whatson` reads the same as its neighbours.

### The card dict

Every producer emits this shape; `cards.py` is the only consumer. Defined once here because six tasks depend on it.

```python
{
    "kind": "event" | "divider" | "highlight" | "empty",
    "sport": "nfl",              # cap bucket key
    "league_label": "NCAAF",     # strip text, upper case
    "layout": "match" | "single",
    # match layout
    "away": {"abbr": "SJSU", "logo": "https://...", "record": "0-0", "rank": None},
    "home": {"abbr": "USC",  "logo": "https://...", "record": "0-0", "rank": 21},
    "score": (17, 21) | None,
    # single layout
    "title": "US OPEN",
    "subtitle": "Round of 16",
    "detail": "Men's & Women's",
    # common
    "start": datetime,           # timezone-aware, PDT
    "day": "today" | "tomorrow",
    "state": "pre" | "live" | "post",
    "status_text": "9:30a" | "LIVE Q3",
    "channel": "NBC",
    "tier": "watchable" | "payable",
    "major": bool,
    "home_team": bool,
    "drama": int,                # 0 unless live
    "round_weight": int,
    "dwell_floor": float | None, # 15.0 on highlight cards, else None
}
```

---

### Task 1: Channel classification

The heart of the feature: which events the user is allowed to see, and what the card says.

**Files:**
- Create: `src/fpp/displays/whatson/__init__.py`, `src/fpp/displays/whatson/channels.py`
- Test: `tests/test_whatson_channels.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `normalise(name: str) -> str`
  - `tier_of(name: str) -> str` — `"watchable" | "payable" | "unavailable"`
  - `best_channel(names: list[str]) -> tuple[str, str] | None` — `(display_name, tier)`, or `None` when nothing is showable

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_whatson_channels.py
"""Which broadcasts the user may see, and what the card prints."""

import pytest

from fpp.displays.whatson.channels import best_channel, normalise, tier_of


@pytest.mark.parametrize("raw,expected", [
    ("USA Net", "USA"),
    ("NBC Sports", "NBC"),
    ("Prime Video-Seattle", "Prime Video"),   # regional suffix strips to the parent
    ("ESPN+", "ESPN+"),
])
def test_normalise_known_variants(raw, expected):
    assert normalise(raw) == expected


@pytest.mark.parametrize("name,tier", [
    ("NBC", "watchable"),
    ("SEC Network", "watchable"),
    ("Peacock", "watchable"),
    ("Apple TV", "watchable"),
    ("Prime Video-Seattle", "watchable"),
    ("KOMO-TV", "watchable"),      # bare local call sign, free over the air
    ("Mariners.TV", "payable"),
    ("NWSL+", "payable"),
    ("DAZN", "payable"),
    ("Sportsnet", "unavailable"),  # Canadian
    ("TVA", "unavailable"),
])
def test_tier_of(name, tier):
    assert tier_of(name) == tier


def test_spanish_only_is_unavailable_but_paired_is_watchable():
    assert best_channel(["Universo"]) is None
    assert best_channel(["USA Net", "Universo"]) == ("USA", "watchable")


def test_prefers_watchable_over_payable_and_never_shows_foreign():
    # The real Mariners broadcast list, from tests/fixtures/espn/mlb_20260829.json
    assert best_channel(["MLB.TV", "Mariners.TV", "Sportsnet", "TVA"]) == ("Mariners.TV", "payable")


def test_no_broadcast_at_all_is_none():
    assert best_channel([]) is None
```

- [ ] **Step 2: Run and verify failure**

Run: `hatch run pytest tests/test_whatson_channels.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fpp.displays.whatson'`

- [ ] **Step 3: Implement**

```python
# src/fpp/displays/whatson/__init__.py
"""What's on today and tomorrow, and where to watch it."""
```

```python
# src/fpp/displays/whatson/channels.py
"""Broadcast names in, a tier and a display name out.

ESPN reports whatever the rights-holder calls itself that week, so everything
here is defensive: match on a normalised name, and treat anything unrecognised
as unavailable rather than guessing the user can watch it.
"""

import re

WATCHABLE = {
    # broadcast + cable
    "NBC", "CBS", "ABC", "FOX", "ESPN", "ESPN2", "ESPNU", "ESPNEWS", "FS1", "FS2",
    "USA", "TNT", "TBS", "truTV", "CNBC", "Golf Channel", "BTN", "SEC Network",
    "ACC Network", "Pac-12 Network", "NFL Network", "MLB Network", "NBA TV",
    "CBS Sports Network", "Spectrum Sports Net",
    # streaming the user has
    "Peacock", "Paramount+", "ESPN+", "Apple TV", "Prime Video", "Netflix", "Max",
    "Fox One", "Fox Sports App",
}

# Services the user could buy but does not have. Shown only for major events,
# and always marked with a "$".
PAYABLE = {
    "DAZN", "Fubo", "beIN Sports", "FloSports", "Victory+", "Willow", "WRC+",
    "MLB.TV", "Mariners.TV", "NWSL+", "NBA League Pass", "NHL Power Play",
}

# Never shown: no US rights, or a foreign-language-only feed.
UNAVAILABLE = {"Sportsnet", "TVA", "Universo", "TUDN", "Telemundo Deportes", "Sky Sports"}

_ALIASES = {
    "USA Net": "USA",
    "NBC Sports": "NBC",
    "CBS Sports Net": "CBS Sports Network",
    "Paramount Plus": "Paramount+",
    "Amazon Prime Video": "Prime Video",
    "HBO Max": "Max",
}

# A bare local call sign — KOMO-TV, KING 5, KIRO. These are free over the air,
# so the Storm on KOMO must not be marked as costing money.
_CALLSIGN = re.compile(r"^K[A-Z]{2,3}\b|^W[A-Z]{2,3}\b")

# ESPN suffixes a regional feed with its market: "Prime Video-Seattle".
_REGIONAL = re.compile(r"\s*[-–]\s*(Seattle|Portland|Bay Area|LA|Chicago|New York|Boston)$")


def normalise(name: str) -> str:
    """Canonical display name for a broadcast, before any tier decision."""
    n = (name or "").strip()
    n = _REGIONAL.sub("", n)
    return _ALIASES.get(n, n)


def tier_of(name: str) -> str:
    """One of "watchable", "payable", "unavailable"."""
    n = normalise(name)
    if n in UNAVAILABLE:
        return "unavailable"
    if n in WATCHABLE:
        return "watchable"
    if n in PAYABLE:
        return "payable"
    if _CALLSIGN.match(n):
        return "watchable"
    # Unrecognised. Assume the worst rather than promising a channel the user
    # may not have — an unknown name is far more often a niche service than a
    # cable channel we forgot.
    return "payable"


_ORDER = {"watchable": 0, "payable": 1}


def best_channel(names: list[str]) -> tuple[str, str] | None:
    """The best showable broadcast: (display name, tier), or None if there is none.

    Watchable beats payable; unavailable is never returned, so a Mariners game
    listing Sportsnet and TVA alongside Mariners.TV shows the one the user could
    actually buy.
    """
    scored = []
    for raw in names or []:
        n = normalise(raw)
        t = tier_of(n)
        if t == "unavailable":
            continue
        scored.append((_ORDER[t], n, t))
    if not scored:
        return None
    scored.sort(key=lambda s: s[0])
    return scored[0][1], scored[0][2]
```

- [ ] **Step 4: Run and verify pass**

Run: `hatch run pytest tests/test_whatson_channels.py -v`
Expected: PASS, 16 tests

- [ ] **Step 5: Lint and commit**

```bash
hatch run ruff check src tests
git add src/fpp/displays/whatson tests/test_whatson_channels.py
git commit -m "whatson: classify broadcasts into watchable, payable and unavailable"
```

---

### Task 2: The PDT day window

**Files:**
- Create: `src/fpp/displays/whatson/window.py`
- Test: `tests/test_whatson_window.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `PACIFIC` — `ZoneInfo("America/Los_Angeles")`
  - `bounds(now: datetime) -> tuple[datetime, datetime]` — PDT midnight today to PDT midnight day-after-tomorrow
  - `date_range(now: datetime) -> str` — `"YYYYMMDD-YYYYMMDD"` for ESPN
  - `bucket(start: datetime, now: datetime) -> str | None` — `"today"`, `"tomorrow"`, or `None` if outside
  - `clock(start: datetime) -> str` — `"9:30a"`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_whatson_window.py
"""Day bucketing in Pacific time. This is where UTC arithmetic goes wrong."""

from datetime import datetime, timezone

from fpp.displays.whatson.window import PACIFIC, bucket, clock, date_range

NOW = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)  # 7am PDT, Sat 29 Aug


def test_date_range_covers_today_and_tomorrow_in_pacific():
    assert date_range(NOW) == "20260829-20260830"


def test_utc_evening_game_is_still_today_in_pacific():
    # 02:00 UTC Sun 30 Aug is 7pm PDT Sat 29 — today, not tomorrow.
    kickoff = datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc)
    assert bucket(kickoff, NOW) == "today"


def test_utc_next_day_morning_is_tomorrow():
    # 17:00 UTC Sun 30 Aug is 10am PDT Sunday.
    kickoff = datetime(2026, 8, 30, 17, 0, tzinfo=timezone.utc)
    assert bucket(kickoff, NOW) == "tomorrow"


def test_two_days_out_is_outside_the_window():
    kickoff = datetime(2026, 8, 31, 17, 0, tzinfo=timezone.utc)
    assert bucket(kickoff, NOW) is None


def test_clock_renders_pacific_lowercase_meridiem():
    # 16:30 UTC = 9:30am PDT — the ET lunchtime NFL window.
    assert clock(datetime(2026, 8, 29, 16, 30, tzinfo=timezone.utc)) == "9:30a"
    assert clock(datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc)) == "7:00p"


def test_bounds_are_pacific_midnight():
    from fpp.displays.whatson.window import bounds
    start, end = bounds(NOW)
    assert start.astimezone(PACIFIC).hour == 0
    assert (end - start).days == 2
```

- [ ] **Step 2: Run and verify failure**

Run: `hatch run pytest tests/test_whatson_window.py -v`
Expected: FAIL — `ModuleNotFoundError: fpp.displays.whatson.window`

- [ ] **Step 3: Implement**

```python
# src/fpp/displays/whatson/window.py
"""Today and tomorrow, in Pacific time.

Every day boundary in this feature is PDT midnight, not UTC midnight and not
the panel's local guess. A 7pm Saturday kickoff is 02:00 Sunday in UTC; bucket
it by UTC and half of Saturday's games move to Sunday.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


def _now(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(PACIFIC)


def bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """PDT midnight today, and PDT midnight the day after tomorrow."""
    here = _now(now)
    start = here.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=2)


def date_range(now: datetime | None = None) -> str:
    """The ESPN `dates=` parameter covering today and tomorrow."""
    start, end = bounds(now)
    return f"{start:%Y%m%d}-{(end - timedelta(days=1)):%Y%m%d}"


def bucket(start: datetime, now: datetime | None = None) -> str | None:
    """"today", "tomorrow", or None when the event falls outside the window."""
    day0, _ = bounds(now)
    local = start.astimezone(PACIFIC)
    delta = (local.date() - day0.date()).days
    return {0: "today", 1: "tomorrow"}.get(delta)


def clock(start: datetime) -> str:
    """A kickoff time as the panel prints it: "9:30a", "7:00p"."""
    local = start.astimezone(PACIFIC)
    return f"{local.strftime('%-I:%M')}{local.strftime('%p')[0].lower()}"
```

- [ ] **Step 4: Run and verify pass**

Run: `hatch run pytest tests/test_whatson_window.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Lint and commit**

```bash
hatch run ruff check src tests
git add src/fpp/displays/whatson/window.py tests/test_whatson_window.py
git commit -m "whatson: bucket events into today and tomorrow in Pacific time"
```

---

### Task 3: Config loading

**Files:**
- Create: `src/fpp/displays/whatson/config.py`, `src/fpp/data/home_teams.yaml`, `src/fpp/data/oddities.yaml`, `src/fpp/data/highlight_sources.yaml`
- Modify: `pyproject.toml` (add `PyYAML`)
- Test: `tests/test_whatson_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `home_teams() -> list[dict]`, `oddities() -> list[dict]`, `highlight_sources() -> list[dict]` — each returns parsed YAML, cached.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, add to `[project] dependencies`:

```toml
    "PyYAML>=6.0",
```

- [ ] **Step 2: Write the config files**

```yaml
# src/fpp/data/home_teams.yaml
# Always shown when they play, whatever the sport, channel or caps.
# Match is on the ESPN competitor displayName, so use the full club name.
- { slug: football/nfl,                        team: Seattle Seahawks }
- { slug: baseball/mlb,                        team: Seattle Mariners }
- { slug: hockey/nhl,                          team: Seattle Kraken }
- { slug: soccer/usa.1,                        team: Seattle Sounders FC }
- { slug: soccer/usa.nwsl,                     team: Seattle Reign FC }
- { slug: basketball/wnba,                     team: Seattle Storm }
- { slug: football/college-football,           team: Washington Huskies }
- { slug: basketball/mens-college-basketball,  team: Washington Huskies }
```

```yaml
# src/fpp/data/oddities.yaml
# Events ESPN does not carry. Dates more than a year out are approximate by
# nature; a stale entry fails safe by simply not matching today or tomorrow.
- name: PDC World Darts Championship
  subtitle: Alexandra Palace
  start: 2026-12-13
  end: 2027-01-03
  channel: ESPN+
  major_from: 2026-12-30
- name: World Snooker Championship
  subtitle: The Crucible
  start: 2027-04-17
  end: 2027-05-03
  channel: DAZN
  major_from: 2027-04-30
- name: Tour de France
  subtitle: Grand Tour
  start: 2027-07-03
  end: 2027-07-25
  channel: Peacock
  major: true
- name: Iditarod
  subtitle: Anchorage to Nome
  start: 2027-03-06
  end: 2027-03-15
  channel: ESPN+
- name: World Chess Championship
  subtitle: Title match
  start: 2026-11-20
  end: 2026-12-12
  channel: ESPN+
  major: true
- name: 24 Hours of Le Mans
  subtitle: Circuit de la Sarthe
  start: 2027-06-12
  end: 2027-06-13
  channel: Max
  major: true
- name: Isle of Man TT
  subtitle: Mountain Course
  start: 2027-05-29
  end: 2027-06-11
  channel: ESPN+
- name: WRC Rallye Monte-Carlo
  subtitle: Round 1
  start: 2027-01-21
  end: 2027-01-24
  channel: WRC+
  major: true
- name: WRC Safari Rally Kenya
  subtitle: Naivasha
  start: 2027-03-25
  end: 2027-03-28
  channel: WRC+
  major: true
```

```yaml
# src/fpp/data/highlight_sources.yaml
# YouTube channel RSS. Match on title patterns, never "newest video" — these
# channels post constant filler between events.
#
# NOTE: EPL highlights are frequently geo-restricted in the US and RSS gives no
# way to detect it, so an NBC Sports card can lead to a video that will not
# play. Kept deliberately; see the spec.
- name: Formula 1
  sport: f1
  channel_id: UCB_qr75-ydFVKSF9Dmo6izg
  patterns: ["Race Highlights", "Qualifying Highlights", "Sprint Highlights"]
- name: ATP Tour
  sport: tennis
  channel_id: UCK8ldTFhKB1M3prYh6BS0Tg
  patterns: ["Highlights"]
- name: WTA
  sport: tennis
  channel_id: UCq5wBH8v6Cd6mGeCFOFdKcA
  patterns: ["Highlights"]
- name: US Open Tennis
  sport: tennis
  channel_id: UCEVLKPqCPU6ZlS3Cnh_bMaQ
  patterns: ["Highlights"]
- name: Wimbledon
  sport: tennis
  channel_id: UCwFqQMuJlPRnRZI8fPvIVYw
  patterns: ["Highlights"]
- name: NFL
  sport: nfl
  channel_id: UCDVYQ4Zhbm3S2dlz7P1GBDg
  patterns: ["Highlights", "Game Highlights"]
- name: ESPN College Football
  sport: ncaaf
  channel_id: UC2XcdDIAWiA5gnHb0Ck9hhg
  patterns: ["Highlights"]
- name: NBC Sports Premier League
  sport: epl
  channel_id: UCqZQlzSHbVJrwrn5XvzrzcA
  patterns: ["Highlights"]
- name: CBS Sports Golazo
  sport: cup
  channel_id: UCbLfN8Cs7hZLKlKQPVQjJ9A
  patterns: ["Highlights", "Extended Highlights"]
```

- [ ] **Step 3: Write the failing test**

```python
# tests/test_whatson_config.py
"""The editable config files load and carry what the design expects."""

from fpp.displays.whatson.config import highlight_sources, home_teams, oddities


def test_home_teams_cover_every_seattle_sport():
    teams = {h["team"] for h in home_teams()}
    assert "Seattle Mariners" in teams
    assert "Seattle Sounders FC" in teams
    assert "Washington Huskies" in teams
    assert all("slug" in h for h in home_teams())


def test_oddities_carry_a_window_and_a_channel():
    for o in oddities():
        assert o["start"] and o["end"] and o["channel"]
        assert o["start"] <= o["end"]


def test_rally_is_major_and_payable_by_channel():
    rally = [o for o in oddities() if "WRC" in o["name"]]
    assert rally, "rally must be present"
    assert all(o["channel"] == "WRC+" and o.get("major") for o in rally)


def test_highlight_sources_all_have_patterns_and_channel_ids():
    for s in highlight_sources():
        assert s["channel_id"].startswith("UC")
        assert s["patterns"]
```

- [ ] **Step 4: Run and verify failure**

Run: `hatch run pytest tests/test_whatson_config.py -v`
Expected: FAIL — `ModuleNotFoundError: fpp.displays.whatson.config`

- [ ] **Step 5: Implement**

```python
# src/fpp/displays/whatson/config.py
"""The three editable YAML files, loaded once.

These live in src/fpp/data/ so they ship with the package and can be edited on
the device without a redeploy of code.
"""

from functools import lru_cache
from pathlib import Path

import yaml

_DATA = Path(__file__).resolve().parent.parent.parent / "data"


def _load(name: str) -> list[dict]:
    path = _DATA / name
    if not path.exists():
        return []
    return yaml.safe_load(path.read_text()) or []


@lru_cache(maxsize=1)
def home_teams() -> list[dict]:
    return _load("home_teams.yaml")


@lru_cache(maxsize=1)
def oddities() -> list[dict]:
    return _load("oddities.yaml")


@lru_cache(maxsize=1)
def highlight_sources() -> list[dict]:
    return _load("highlight_sources.yaml")
```

- [ ] **Step 6: Run and verify pass**

Run: `hatch run pytest tests/test_whatson_config.py -v`
Expected: PASS, 4 tests

- [ ] **Step 7: Lint and commit**

```bash
hatch run ruff check src tests
git add pyproject.toml src/fpp/data src/fpp/displays/whatson/config.py tests/test_whatson_config.py
git commit -m "whatson: editable config for home teams, oddities and highlight sources"
```

---

### Task 4: ESPN adapters — the three event shapes

**Files:**
- Create: `src/fpp/displays/whatson/sources.py`
- Test: `tests/test_whatson_sources.py`

**Interfaces:**
- Consumes: `channels.best_channel`, `window.bucket`, `window.clock`
- Produces:
  - `SLUGS: dict[str, str]` — sport key to ESPN slug
  - `from_match(event: dict, sport: str, now: datetime) -> dict | None`
  - `from_tournament(event: dict, sport: str, now: datetime) -> dict | None`
  - `from_sessions(event: dict, sport: str, now: datetime, include_practice: bool = False) -> list[dict]`
  - `fetch(slug: str, dates: str) -> dict` — the raw ESPN payload

Each `from_*` returns card dicts in the shape defined under File Structure, or `None`/`[]` when nothing survives filtering.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_whatson_sources.py
"""Three event shapes, one card dict. All against captured fixtures."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from fpp.displays.whatson.sources import from_match, from_sessions, from_tournament

FIX = Path(__file__).parent / "fixtures" / "espn"
NOW = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)


def load(name):
    return json.loads((FIX / f"{name}.json").read_text())


def test_match_shape_produces_a_match_card():
    ev = load("ncaaf_20260829")["events"][0]
    card = from_match(ev, "ncaaf", NOW)
    assert card["layout"] == "match"
    assert card["sport"] == "ncaaf"
    assert card["away"]["abbr"] and card["home"]["abbr"]
    assert card["channel"]
    assert card["tier"] in ("watchable", "payable")


def test_unwatchable_match_is_dropped():
    # A synthetic event whose only feed is Canadian.
    ev = load("mlb_20260829")["events"][0]
    ev["competitions"][0]["geoBroadcasts"] = [{"media": {"shortName": "Sportsnet"}}]
    assert from_match(ev, "mlb", NOW) is None


def test_mariners_show_the_payable_feed_not_the_canadian_one():
    ev = [e for e in load("mlb_20260829")["events"] if "Seattle" in e["name"]][0]
    card = from_match(ev, "mlb", NOW)
    assert card["channel"] == "Mariners.TV"
    assert card["tier"] == "payable"


def test_tournament_shape_collapses_to_one_card():
    us_open = [e for e in load("tennis_atp")["events"] if e["name"] == "US Open"][0]
    card = from_tournament(us_open, "tennis", NOW)
    assert card["layout"] == "single"
    assert card["title"] == "US OPEN"
    assert card["major"] is True


def test_non_major_tournament_is_dropped():
    minor = [e for e in load("tennis_atp")["events"] if e["name"] != "US Open"]
    if minor:
        assert from_tournament(minor[0], "tennis", NOW) is None


def test_f1_sessions_exclude_practice_by_default():
    ev = load("f1_monza")["events"][0]
    cards = from_sessions(ev, "f1", NOW, include_practice=False)
    labels = {c["subtitle"] for c in cards}
    assert "RACE" in labels or not cards        # Monza race may fall outside the window
    assert not any(lbl.startswith("FP") for lbl in labels)


def test_f1_practice_included_when_asked():
    ev = load("f1_monza")["events"][0]
    all_cards = from_sessions(ev, "f1", NOW, include_practice=True)
    lean_cards = from_sessions(ev, "f1", NOW, include_practice=False)
    assert len(all_cards) >= len(lean_cards)


def test_empty_league_yields_nothing():
    assert load("facup_empty")["events"] == []
```

- [ ] **Step 2: Run and verify failure**

Run: `hatch run pytest tests/test_whatson_sources.py -v`
Expected: FAIL — `ModuleNotFoundError: fpp.displays.whatson.sources`

- [ ] **Step 3: Implement**

```python
# src/fpp/displays/whatson/sources.py
"""ESPN gives three different shapes of "event". Normalise all of them.

1. Match-shaped  (NFL, NCAAF, soccer) — one event is one game.
2. Tournament    (tennis)             — one event is a fortnight; 239 matches inside.
3. Session       (F1)                 — one event is a race weekend of sessions.
"""

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


def _iso(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _broadcasts(comp: dict) -> list[str]:
    return [g.get("media", {}).get("shortName", "") for g in comp.get("geoBroadcasts", [])]


def _round_weight(comp: dict) -> int:
    note = " ".join(n.get("headline", "") for n in comp.get("notes", [])).lower()
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
    late = period >= 4
    if margin <= 8 and late:
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


def _base(sport: str, start: datetime, day: str, comp: dict, channel, state: str) -> dict:
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
    }


def from_match(event: dict, sport: str, now: datetime | None = None) -> dict | None:
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
    sides = [_side(c) for c in comp.get("competitors", [])]
    away = next((s for s, c in zip(sides, comp["competitors"])
                 if c.get("homeAway") == "away"), sides[0] if sides else {})
    home = next((s for s, c in zip(sides, comp["competitors"])
                 if c.get("homeAway") == "home"), sides[-1] if sides else {})
    card.update({
        "layout": "match",
        "away": away,
        "home": home,
        "score": ((int(away.get("score") or 0), int(home.get("score") or 0))
                  if card["state"] in ("live", "post") else None),
        "title": f"{away.get('abbr','')} @ {home.get('abbr','')}",
    })
    card["major"] = card["round_weight"] >= 20
    return card


def from_tournament(event: dict, sport: str, now: datetime | None = None) -> dict | None:
    """A tennis tournament as one card. Only the majors qualify."""
    if not event.get("major"):
        return None
    start = _iso(event.get("date", ""))
    end = _iso(event.get("endDate", ""))
    if not start or not end:
        return None
    # A tournament spans a fortnight: it is "on today" if today falls inside it.
    day = bucket(start, now) or ("today" if start <= (now or datetime.now(start.tzinfo)) <= end
                                 else None)
    if day is None:
        return None
    comps = [c for g in event.get("groupings", []) for c in g.get("competitions", [])]
    names: list[str] = []
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


def from_sessions(event: dict, sport: str, now: datetime | None = None,
                  include_practice: bool = False) -> list[dict]:
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
        state = _state(comp)
        card = _base(sport, start, day, comp, channel, state)
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
```

- [ ] **Step 4: Run and verify pass**

Run: `hatch run pytest tests/test_whatson_sources.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Lint and commit**

```bash
hatch run ruff check src tests
git add src/fpp/displays/whatson/sources.py tests/test_whatson_sources.py
git commit -m "whatson: normalise ESPN's three event shapes into one card dict"
```

---

### Task 5: Selection — majorness, caps, ranking, blocks

**Files:**
- Create: `src/fpp/displays/whatson/select.py`
- Test: `tests/test_whatson_select.py`

**Interfaces:**
- Consumes: `sources`, `config.home_teams`, `config.oddities`, `window`
- Produces:
  - `CAPS: dict[str, int]`
  - `rank_key(card: dict) -> tuple` — sort key, ascending
  - `apply_caps(cards: list[dict]) -> list[dict]`
  - `oddity_cards(now: datetime) -> list[dict]`
  - `mark_home(cards: list[dict]) -> list[dict]`
  - `assemble(home: list[dict], events: list[dict], highlights: list[dict]) -> list[dict]` — the full slide list including dividers
  - `divider(day: str, count: int) -> dict`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_whatson_select.py
"""Caps, ranking, and how the blocks go together."""

from datetime import datetime, timedelta, timezone

from fpp.displays.whatson.select import (
    CAPS, apply_caps, assemble, mark_home, oddity_cards, rank_key,
)

NOW = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)


def card(**kw):
    base = dict(kind="event", sport="ncaaf", league_label="NCAAF", layout="match",
                start=NOW + timedelta(hours=3), day="today", state="pre",
                status_text="9:30a", channel="NBC", tier="watchable", major=False,
                home_team=False, drama=0, round_weight=0, dwell_floor=None,
                is_cup=False, title="A @ B", away={"abbr": "A"}, home={"abbr": "B"},
                score=None)
    base.update(kw)
    return base


def test_caps_are_per_sport():
    cards = [card(sport="ncaaf") for _ in range(10)] + [card(sport="nfl") for _ in range(10)]
    kept = apply_caps(cards)
    assert sum(1 for c in kept if c["sport"] == "ncaaf") == CAPS["ncaaf"]
    assert sum(1 for c in kept if c["sport"] == "nfl") == CAPS["nfl"]


def test_all_cup_slugs_share_one_cap():
    cards = [card(sport=s, is_cup=True) for s in ("ucl", "uel", "facup", "libertadores")]
    assert len(apply_caps(cards)) == CAPS["cup"]


def test_today_outranks_tomorrow():
    today, tomorrow = card(day="today"), card(day="tomorrow")
    assert rank_key(today) < rank_key(tomorrow)


def test_live_outranks_upcoming_and_drama_orders_the_live_ones():
    tight = card(state="live", drama=3)
    blowout = card(state="live", drama=1)
    upcoming = card(state="pre")
    assert rank_key(tight) < rank_key(blowout) < rank_key(upcoming)


def test_watchable_outranks_payable():
    assert rank_key(card(tier="watchable")) < rank_key(card(tier="payable"))


def test_ranked_teams_outrank_unranked():
    ranked = card(home={"abbr": "USC", "rank": 3})
    plain = card(home={"abbr": "USC", "rank": None})
    assert rank_key(ranked) < rank_key(plain)


def test_home_games_bypass_caps_and_leave_the_day_blocks():
    home = [card(sport="mlb", home_team=True) for _ in range(2)]
    others = [card(sport="ncaaf") for _ in range(10)]
    slides = assemble(home, apply_caps(others), [])
    kinds = [s["kind"] for s in slides]
    assert kinds[0] == "divider"
    assert slides[0]["title"] == "SEATTLE"
    assert sum(1 for s in slides if s.get("home_team")) == 2


def test_assemble_orders_the_blocks_and_inserts_dividers():
    slides = assemble([card(home_team=True)],
                      [card(day="today"), card(day="tomorrow")],
                      [dict(kind="highlight", title="X", dwell_floor=15.0)])
    titles = [s["title"] for s in slides if s["kind"] == "divider"]
    assert titles == ["SEATTLE", "TODAY", "TOMORROW", "AVAILABLE TO WATCH"]


def test_empty_everything_yields_a_single_empty_card():
    slides = assemble([], [], [])
    assert len(slides) == 1 and slides[0]["kind"] == "empty"


def test_oddity_matches_only_inside_its_window():
    during = datetime(2026, 12, 20, 20, 0, tzinfo=timezone.utc)   # darts is on
    outside = datetime(2026, 10, 1, 20, 0, tzinfo=timezone.utc)
    assert any("DARTS" in c["title"] for c in oddity_cards(during))
    assert not any("DARTS" in c["title"] for c in oddity_cards(outside))


def test_oddity_major_from_promotes_late_rounds():
    early = oddity_cards(datetime(2026, 12, 15, 20, 0, tzinfo=timezone.utc))
    late = oddity_cards(datetime(2026, 12, 31, 20, 0, tzinfo=timezone.utc))
    darts_early = [c for c in early if "DARTS" in c["title"]][0]
    darts_late = [c for c in late if "DARTS" in c["title"]][0]
    assert darts_early["major"] is False
    assert darts_late["major"] is True


def test_mark_home_flags_configured_teams_only():
    seattle = card(away={"abbr": "SEA", "name": "Seattle Mariners"},
                   home={"abbr": "TOR", "name": "Toronto Blue Jays"}, sport="mlb")
    other = card(away={"abbr": "NYY", "name": "New York Yankees"},
                 home={"abbr": "BOS", "name": "Boston Red Sox"}, sport="mlb")
    marked = mark_home([seattle, other])
    assert marked[0]["home_team"] is True
    assert marked[1]["home_team"] is False
```

- [ ] **Step 2: Run and verify failure**

Run: `hatch run pytest tests/test_whatson_select.py -v`
Expected: FAIL — `ModuleNotFoundError: fpp.displays.whatson.select`

- [ ] **Step 3: Implement**

```python
# src/fpp/displays/whatson/select.py
"""What makes the panel, in what order.

Caps are per sport rather than global: a single NCAAF Saturday is fifty games,
and a global cap would let it crowd out everything else.
"""

from datetime import date, datetime, timezone

from .config import home_teams, oddities
from .window import PACIFIC, bucket

CAPS = {
    "nfl": 3, "ncaaf": 3, "epl": 3, "cup": 2, "tennis": 2, "f1": 2,
    "oddity": 1, "home": 4, "highlight": 3,
}

_DAY_ORDER = {"today": 0, "tomorrow": 1}
_STATE_ORDER = {"live": 0, "pre": 1, "post": 2}
_TIER_ORDER = {"watchable": 0, "payable": 1}


def _bucket_key(card: dict) -> str:
    if card.get("is_cup"):
        return "cup"
    if card["sport"] in ("atp", "wta"):
        return "tennis"
    return card["sport"]


def rank_key(card: dict) -> tuple:
    """Sort key, ascending. Lower sorts nearer the front of the panel."""
    rank = (card.get("home") or {}).get("rank") or (card.get("away") or {}).get("rank")
    return (
        _DAY_ORDER.get(card.get("day"), 9),
        _STATE_ORDER.get(card.get("state"), 9),
        -card.get("drama", 0),
        -card.get("round_weight", 0),
        rank if isinstance(rank, int) else 99,
        _TIER_ORDER.get(card.get("tier"), 9),
        card.get("start") or datetime.max.replace(tzinfo=timezone.utc),
    )


def apply_caps(cards: list[dict]) -> list[dict]:
    """Keep the best N of each sport. Home games are exempt — see mark_home."""
    kept: list[dict] = []
    used: dict[str, int] = {}
    for card in sorted(cards, key=rank_key):
        if card.get("home_team"):
            continue
        key = _bucket_key(card)
        cap = CAPS.get(key, 2)
        if used.get(key, 0) >= cap:
            continue
        used[key] = used.get(key, 0) + 1
        kept.append(card)
    return kept


def mark_home(cards: list[dict]) -> list[dict]:
    """Flag any card featuring a configured home team."""
    names = {h["team"] for h in home_teams()}
    for card in cards:
        sides = (card.get("away") or {}), (card.get("home") or {})
        if any(s.get("name") in names for s in sides):
            card["home_team"] = True
    return cards


def _as_date(v) -> date:
    return v if isinstance(v, date) and not isinstance(v, datetime) else v.date()


def oddity_cards(now: datetime | None = None) -> list[dict]:
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


def _day_subtitle(day: str, now: datetime | None = None) -> str:
    from datetime import timedelta
    here = (now or datetime.now(timezone.utc)).astimezone(PACIFIC)
    when = here if day == "today" else here + timedelta(days=1)
    return when.strftime("%a · %b %-d").upper()


def assemble(home: list[dict], events: list[dict], highlights: list[dict],
             now: datetime | None = None) -> list[dict]:
    """The full slide list: SEATTLE, TODAY, TOMORROW, AVAILABLE TO WATCH."""
    home = sorted(home, key=rank_key)[: CAPS["home"]]
    seen = {id(c) for c in home}
    events = [c for c in events if id(c) not in seen and not c.get("home_team")]

    slides: list[dict] = []
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
```

- [ ] **Step 4: Run and verify pass**

Run: `hatch run pytest tests/test_whatson_select.py -v`
Expected: PASS, 12 tests

- [ ] **Step 5: Lint and commit**

```bash
hatch run ruff check src tests
git add src/fpp/displays/whatson/select.py tests/test_whatson_select.py
git commit -m "whatson: rank, cap and assemble the slide blocks"
```

---

### Task 6: QR codes — the gating physical test

**This task decides whether the highlights feature is viable at all.** Do it before Task 8. If a QR cannot be scanned off the panel, stop and report back rather than building the rest.

**Files:**
- Create: `src/fpp/displays/whatson/qr.py`
- Modify: `pyproject.toml` (add `segno`)
- Test: `tests/test_whatson_qr.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `qr_image(url: str, module_px: int = 4) -> PIL.Image.Image` — a square RGB image, dark-on-white.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, add to `[project] dependencies`:

```toml
    "segno>=1.6",
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_whatson_qr.py
"""QR sizing. The panel is 192px, so the geometry has no slack."""

import pytest

from fpp.displays.whatson.qr import qr_image

URL = "https://youtu.be/dQw4w9WgXcQ"


def test_a_youtube_url_fits_the_panel_with_room_for_a_title():
    img = qr_image(URL, module_px=4)
    assert img.width == img.height
    assert img.width <= 160, "QR must leave room for the title strip"


def test_it_is_dark_on_white_not_the_panel_default():
    img = qr_image(URL)
    corner = img.convert("RGB").getpixel((0, 0))
    assert corner == (255, 255, 255), "quiet zone must be white for camera contrast"


def test_a_long_url_still_fits_the_canvas():
    long_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1234567890"
    img = qr_image(long_url, module_px=3)
    assert img.width <= 192
```

- [ ] **Step 3: Run and verify failure**

Run: `hatch run pytest tests/test_whatson_qr.py -v`
Expected: FAIL — `ModuleNotFoundError: fpp.displays.whatson.qr`

- [ ] **Step 4: Implement**

```python
# src/fpp/displays/whatson/qr.py
"""QR codes sized for a 192x192 LED panel.

Rendered DARK ON WHITE, which is backwards for this panel but necessary: phone
cameras meter badly against a bright emissive matrix, and an inverted QR is
substantially harder for them to lock onto.
"""

import io

import segno
from PIL import Image


def qr_image(url: str, module_px: int = 4, border: int = 4) -> Image.Image:
    """A scannable QR for `url`, at `module_px` LEDs per module."""
    code = segno.make(url, error="l")
    buf = io.BytesIO()
    code.save(buf, kind="png", scale=module_px, border=border,
              dark="#000000", light="#ffffff")
    buf.seek(0)
    return Image.open(buf).convert("RGB")
```

- [ ] **Step 5: Run and verify pass**

Run: `hatch run pytest tests/test_whatson_qr.py -v`
Expected: PASS, 3 tests

- [ ] **Step 6: THE GATING PHYSICAL TEST**

Render a QR card to the real panel and try to scan it with a phone.

```bash
hatch run python - <<'EOF'
from fpp.canvas import Frame
from fpp.displays.whatson.qr import qr_image
f = Frame(bg=(0, 0, 0))
f.rect(0, 0, 192, 26, (30, 30, 30))
f.text(96, 13, "SCAN TEST", size=14, anchor="mm")
img = qr_image("https://youtu.be/dQw4w9WgXcQ", module_px=4)
f.paste(img, (192 - img.width) // 2, 30)
open("/tmp/qrtest.jpg", "wb").write(f.to_image_bytes())
EOF
fpp --host 192.168.1.66 upload /tmp/qrtest.jpg
```

Then display it and try to scan with a phone camera from normal viewing distance.

**Record the result in the commit message.** If it will not scan:
- try `module_px=5` (fits, but leaves ~30px for the title)
- try lowering panel brightness
- if it still will not scan, **STOP**. Report back — the highlights handoff needs redesigning, and Tasks 8 and 9 should not be built on it.

- [ ] **Step 7: Lint and commit**

```bash
hatch run ruff check src tests
git add pyproject.toml src/fpp/displays/whatson/qr.py tests/test_whatson_qr.py
git commit -m "whatson: QR codes sized and contrasted for the LED panel

Scanned off the real panel at module_px=N from M feet: <RESULT>."
```

---

### Task 7: Card rendering

**Files:**
- Create: `src/fpp/displays/whatson/cards.py`
- Test: `tests/test_whatson_cards.py`

**Interfaces:**
- Consumes: `fpp.canvas.Frame`, `qr.qr_image`
- Produces: `render(card: dict) -> Frame` — dispatches on `card["kind"]` and `card["layout"]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_whatson_cards.py
"""Every card kind renders. Smoke tests: no exceptions, right dimensions."""

from datetime import datetime, timezone

import pytest

from fpp.displays.whatson.cards import render

NOW = datetime(2026, 8, 29, 16, 30, tzinfo=timezone.utc)


def base(**kw):
    b = dict(kind="event", sport="ncaaf", league_label="NCAAF", layout="match",
             start=NOW, day="today", state="pre", status_text="9:30a",
             channel="NBC", tier="watchable", major=False, home_team=False,
             drama=0, round_weight=0, dwell_floor=None, is_cup=False,
             title="SJSU @ USC", subtitle="", detail="", score=None,
             away={"abbr": "SJSU", "logo": "", "record": "0-0", "rank": None},
             home={"abbr": "USC", "logo": "", "record": "0-0", "rank": 21})
    b.update(kw)
    return b


@pytest.mark.parametrize("card", [
    base(),
    base(state="live", status_text="LIVE Q3", score=(17, 21)),
    base(tier="payable", channel="Mariners.TV"),
    base(layout="single", title="US OPEN", subtitle="Round of 16", detail="Men's & Women's"),
    base(layout="single", title="ITALIAN GP", subtitle="RACE", detail="Monza", channel="Apple TV"),
    dict(kind="divider", title="TODAY", subtitle="SAT · AUG 29", count=6, sport="divider"),
    dict(kind="divider", title="SEATTLE", subtitle="", count=3, sport="divider"),
    dict(kind="empty", title="NOTHING ON", subtitle="next: EPL Sat 4:30a", sport="empty"),
])
def test_every_card_kind_renders_to_a_192_square(card):
    frame = render(card)
    data = frame.to_image_bytes()
    assert data[:2] == b"\xff\xd8", "JPEG magic"
    assert len(data) > 500


def test_highlight_card_renders_with_a_qr():
    card = dict(kind="highlight", sport="highlight", title="ITALIAN GP",
                subtitle="Race Highlights", age="2h",
                url="https://youtu.be/dQw4w9WgXcQ", dwell_floor=15.0)
    assert render(card).to_image_bytes()[:2] == b"\xff\xd8"
```

- [ ] **Step 2: Run and verify failure**

Run: `hatch run pytest tests/test_whatson_cards.py -v`
Expected: FAIL — `ModuleNotFoundError: fpp.displays.whatson.cards`

- [ ] **Step 3: Implement**

```python
# src/fpp/displays/whatson/cards.py
"""192x192 cards. The bottom strip is always the channel — that is the question
this display exists to answer.
"""

import httpx
from PIL import Image
from io import BytesIO
from functools import lru_cache

from ...canvas import Frame

W = H = 192
STRIP_H = 26          # league / status
CHANNEL_H = 36        # the answer, along the bottom
FG = (255, 255, 255)
DIM = (150, 150, 150)
LIVE = (235, 60, 60)
AMBER = (200, 140, 30)
BG = (0, 0, 0)

LEAGUE_COLOURS = {
    "NFL": (20, 40, 90), "NCAAF": (90, 25, 30), "EPL": (55, 0, 60),
    "UCL": (10, 25, 90), "TENNIS": (20, 70, 40), "F1": (120, 20, 20),
    "MLB": (25, 45, 80), "MLS": (20, 60, 70), "NWSL": (70, 25, 70),
    "WNBA": (60, 30, 80), "NHL": (35, 35, 40), "ALSO ON": (50, 45, 20),
}


@lru_cache(maxsize=64)
def _logo(url: str) -> Image.Image | None:
    if not url:
        return None
    try:
        r = httpx.get(url, timeout=8)
        r.raise_for_status()
        return Image.open(BytesIO(r.content)).convert("RGBA")
    except Exception:
        return None


def _strip(frame: Frame, card: dict) -> None:
    label = card.get("league_label", "")
    frame.rect(0, 0, W, STRIP_H, LEAGUE_COLOURS.get(label, (40, 40, 40)))
    frame.text(6, STRIP_H // 2, label, size=13, color=FG, anchor="lm")
    status = card.get("status_text", "")
    colour = LIVE if card.get("state") == "live" else FG
    frame.text(W - 6, STRIP_H // 2, status, size=12, color=colour, anchor="rm")


def _channel(frame: Frame, card: dict) -> None:
    y = H - CHANNEL_H
    payable = card.get("tier") == "payable"
    frame.rect(0, y, W, CHANNEL_H, (45, 32, 8) if payable else (22, 22, 22))
    text = card.get("channel", "")
    if payable:
        text = f"$ {text}"
    frame.text_fit(W // 2, y + CHANNEL_H // 2, text, max_width=W - 12,
                   size=20, color=AMBER if payable else FG, anchor="mm")


def _match(frame: Frame, card: dict) -> None:
    body_top, body_bot = STRIP_H, H - CHANNEL_H
    mid = (body_top + body_bot) // 2
    for side, cx in ((card.get("away") or {}), 52), ((card.get("home") or {}), 140):
        img = _logo(side.get("logo", ""))
        if img is not None:
            img = img.resize((44, 44))
            frame.paste(img, cx - 22, body_top + 8)
        label = side.get("abbr", "")
        if side.get("rank"):
            label = f"#{side['rank']} {label}"
        frame.text_fit(cx, mid + 26, label, max_width=84, size=18, color=FG, anchor="mm")
        frame.text(cx, mid + 44, side.get("record", ""), size=10, color=DIM, anchor="mm")
    score = card.get("score")
    if score:
        frame.text(52, mid + 6, str(score[0]), size=26, color=FG, anchor="mm")
        frame.text(140, mid + 6, str(score[1]), size=26, color=FG, anchor="mm")
    else:
        frame.text(96, mid + 4, "@", size=14, color=DIM, anchor="mm")


def _single(frame: Frame, card: dict) -> None:
    body_top, body_bot = STRIP_H, H - CHANNEL_H
    mid = (body_top + body_bot) // 2
    frame.text_fit(W // 2, mid - 22, card.get("title", ""), max_width=W - 12,
                   size=26, color=FG, anchor="mm")
    frame.text_fit(W // 2, mid + 6, card.get("subtitle", ""), max_width=W - 12,
                   size=16, color=FG, anchor="mm")
    frame.text_fit(W // 2, mid + 30, card.get("detail", ""), max_width=W - 12,
                   size=12, color=DIM, anchor="mm")


def _divider(frame: Frame, card: dict) -> Frame:
    frame.text_fit(W // 2, 72, card.get("title", ""), max_width=W - 16,
                   size=34, color=FG, anchor="mm")
    frame.text_fit(W // 2, 108, card.get("subtitle", ""), max_width=W - 16,
                   size=16, color=DIM, anchor="mm")
    n = card.get("count", 0)
    frame.text(W // 2, 140, f"{n} event{'s' if n != 1 else ''}", size=13,
               color=DIM, anchor="mm")
    return frame


def _empty(frame: Frame, card: dict) -> Frame:
    frame.text_fit(W // 2, 84, card.get("title", "NOTHING ON"), max_width=W - 16,
                   size=28, color=FG, anchor="mm")
    frame.text_fit(W // 2, 120, card.get("subtitle", ""), max_width=W - 16,
                   size=13, color=DIM, anchor="mm")
    return frame


def _highlight(frame: Frame, card: dict) -> Frame:
    from .qr import qr_image
    frame.rect(0, 0, W, 22, (35, 35, 35))
    frame.text(6, 11, "HIGHLIGHTS", size=12, color=FG, anchor="lm")
    frame.text(W - 6, 11, card.get("age", ""), size=11, color=DIM, anchor="rm")
    frame.text_fit(W // 2, 34, card.get("title", ""), max_width=W - 12,
                   size=14, color=FG, anchor="mm")
    frame.text_fit(W // 2, 50, card.get("subtitle", ""), max_width=W - 12,
                   size=12, color=DIM, anchor="mm")
    img = qr_image(card.get("url", ""), module_px=4)
    frame.paste(img, (W - img.width) // 2, min(58, H - img.height))
    return frame


def render(card: dict) -> Frame:
    """One card dict in, one 192x192 Frame out."""
    frame = Frame(bg=BG)
    kind = card.get("kind")
    if kind == "divider":
        return _divider(frame, card)
    if kind == "empty":
        return _empty(frame, card)
    if kind == "highlight":
        return _highlight(frame, card)
    _strip(frame, card)
    if card.get("layout") == "match":
        _match(frame, card)
    else:
        _single(frame, card)
    _channel(frame, card)
    return frame
```

- [ ] **Step 4: Run and verify pass**

Run: `hatch run pytest tests/test_whatson_cards.py -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Lint and commit**

```bash
hatch run ruff check src tests
git add src/fpp/displays/whatson/cards.py tests/test_whatson_cards.py
git commit -m "whatson: render dividers, match, single-title, highlight and empty cards"
```

---

### Task 8: Highlights from YouTube RSS

**Do not start until Task 6's physical scan test has passed.**

**Files:**
- Create: `src/fpp/displays/whatson/highlights.py`, `tests/fixtures/youtube/f1_feed.xml`
- Test: `tests/test_whatson_highlights.py`

**Interfaces:**
- Consumes: `config.highlight_sources`
- Produces:
  - `parse_feed(xml: str) -> list[dict]` — `{"title", "video_id", "published"}`
  - `matches(entry: dict, patterns: list[str]) -> bool`
  - `select(entries_by_source: dict[str, list[dict]], now: datetime, patterns_by_source: dict[str, list[str]]) -> list[dict]` — highlight cards
  - `fetch_all(now: datetime) -> list[dict]`

- [ ] **Step 1: Capture the fixture**

```bash
mkdir -p tests/fixtures/youtube
curl -s "https://www.youtube.com/feeds/videos.xml?channel_id=UCB_qr75-ydFVKSF9Dmo6izg" \
  > tests/fixtures/youtube/f1_feed.xml
```

Then hand-edit the fixture so it contains, with recent `<published>` dates: one `Race Highlights` entry, one `Qualifying Highlights` entry, one `Sprint Highlights` entry, and at least two filler entries (driver interviews, `Grid Games`). This makes the cap and pattern tests deterministic.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_whatson_highlights.py
"""YouTube RSS in, at most three QR cards out."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fpp.displays.whatson.highlights import matches, parse_feed, select

FEED = (Path(__file__).parent / "fixtures" / "youtube" / "f1_feed.xml").read_text()
NOW = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)

PATTERNS = ["Race Highlights", "Qualifying Highlights", "Sprint Highlights"]


def test_parse_feed_returns_titles_ids_and_dates():
    entries = parse_feed(FEED)
    assert entries
    e = entries[0]
    assert e["video_id"] and e["title"]
    assert e["published"].tzinfo is not None


def test_filler_videos_do_not_match():
    assert not matches({"title": "Can Valtteri & Sergio Complete These Challenges?!"}, PATTERNS)
    assert not matches({"title": "Lando Norris Ranks His Best F1 Moments!"}, PATTERNS)


def test_highlight_titles_match_case_insensitively():
    assert matches({"title": "Italian GP | RACE HIGHLIGHTS"}, PATTERNS)


def test_only_the_last_48_hours_qualify():
    fresh = {"title": "Race Highlights", "video_id": "a",
             "published": NOW - timedelta(hours=47)}
    stale = {"title": "Race Highlights", "video_id": "b",
             "published": NOW - timedelta(hours=49)}
    cards = select({"Formula 1": [fresh, stale]}, NOW, {"Formula 1": PATTERNS})
    assert [c["url"].endswith("a") for c in cards] == [True]


def test_one_card_per_source_even_when_a_weekend_posts_three():
    weekend = [
        {"title": "Race Highlights", "video_id": "r", "published": NOW - timedelta(hours=2)},
        {"title": "Qualifying Highlights", "video_id": "q", "published": NOW - timedelta(hours=20)},
        {"title": "Sprint Highlights", "video_id": "s", "published": NOW - timedelta(hours=30)},
    ]
    cards = select({"Formula 1": weekend}, NOW, {"Formula 1": PATTERNS})
    assert len(cards) == 1
    assert cards[0]["url"].endswith("r"), "most recent wins"


def test_cards_carry_the_dwell_floor_and_an_age():
    entry = {"title": "Race Highlights", "video_id": "r", "published": NOW - timedelta(hours=2)}
    card = select({"Formula 1": [entry]}, NOW, {"Formula 1": PATTERNS})[0]
    assert card["dwell_floor"] == 15.0
    assert card["age"] == "2h"
    assert card["kind"] == "highlight"


def test_a_malformed_feed_yields_nothing_rather_than_raising():
    assert parse_feed("<not-xml") == []
```

- [ ] **Step 3: Run and verify failure**

Run: `hatch run pytest tests/test_whatson_highlights.py -v`
Expected: FAIL — `ModuleNotFoundError: fpp.displays.whatson.highlights`

- [ ] **Step 4: Implement**

```python
# src/fpp/displays/whatson/highlights.py
"""Recaps that have just been posted, as scannable QR cards.

YouTube per-channel RSS: no API key, no quota. The feed is a rolling window of
about fifteen videos, so this is a recency feature and not an archive. These
channels post constant filler between events, so selection is always on title
patterns and never on "the newest video".
"""

from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

import httpx

from .config import highlight_sources

FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
WINDOW = timedelta(hours=48)
MAX_CARDS = 3
DWELL_FLOOR = 15.0        # a QR card must be noticed, then scanned

_NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}


def parse_feed(xml: str) -> list[dict]:
    """Entries as {"title", "video_id", "published"}. Never raises."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return []
    out = []
    for entry in root.findall("a:entry", _NS):
        title = (entry.findtext("a:title", default="", namespaces=_NS) or "").strip()
        vid = entry.findtext("yt:videoId", default="", namespaces=_NS)
        pub = entry.findtext("a:published", default="", namespaces=_NS)
        try:
            when = datetime.fromisoformat(pub.replace("Z", "+00:00"))
        except ValueError:
            continue
        if title and vid:
            out.append({"title": title, "video_id": vid, "published": when})
    return out


def matches(entry: dict, patterns: list[str]) -> bool:
    title = (entry.get("title") or "").lower()
    return any(p.lower() in title for p in patterns)


def _age(published: datetime, now: datetime) -> str:
    hours = max(0, int((now - published).total_seconds() // 3600))
    return f"{hours}h" if hours < 48 else f"{hours // 24}d"


def select(entries_by_source: dict[str, list[dict]], now: datetime,
           patterns_by_source: dict[str, list[str]]) -> list[dict]:
    """At most one card per source, at most three overall, most recent first."""
    picks = []
    for source, entries in entries_by_source.items():
        patterns = patterns_by_source.get(source, [])
        fresh = [e for e in entries
                 if matches(e, patterns) and (now - e["published"]) <= WINDOW]
        if not fresh:
            continue
        picks.append((source, max(fresh, key=lambda e: e["published"])))
    picks.sort(key=lambda p: p[1]["published"], reverse=True)

    cards = []
    for source, entry in picks[:MAX_CARDS]:
        cards.append({
            "kind": "highlight", "sport": "highlight", "source": source,
            "title": entry["title"].split("|")[0].strip().upper()[:28],
            "subtitle": entry["title"].split("|")[-1].strip()[:24],
            "url": f"https://youtu.be/{entry['video_id']}",
            "age": _age(entry["published"], now),
            "published": entry["published"],
            "dwell_floor": DWELL_FLOOR,
        })
    return cards


def fetch_all(now: datetime | None = None) -> list[dict]:
    """Every configured source. A dead feed is skipped, never fatal —
    a broken highlight channel must not cost the user the schedule board."""
    now = now or datetime.now(timezone.utc)
    entries: dict[str, list[dict]] = {}
    patterns: dict[str, list[str]] = {}
    for source in highlight_sources():
        name = source["name"]
        patterns[name] = source.get("patterns", [])
        try:
            with httpx.Client(timeout=10) as c:
                r = c.get(FEED.format(source["channel_id"]))
                r.raise_for_status()
            entries[name] = parse_feed(r.text)
        except Exception:
            entries[name] = []
    return select(entries, now, patterns)
```

- [ ] **Step 5: Run and verify pass**

Run: `hatch run pytest tests/test_whatson_highlights.py -v`
Expected: PASS, 7 tests

- [ ] **Step 6: Lint and commit**

```bash
hatch run ruff check src tests
git add src/fpp/displays/whatson/highlights.py tests/fixtures/youtube tests/test_whatson_highlights.py
git commit -m "whatson: discover freshly posted highlights from YouTube RSS"
```

---

### Task 9: The orchestrator

Ties the sources together into one slide list. This is the seam the CLI calls.

**Files:**
- Modify: `src/fpp/displays/whatson/__init__.py`
- Test: `tests/test_whatson_board.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `build_board(now=None, include_practice=False, with_highlights=True) -> tuple[list[dict], str]` — slides and a one-word reason, matching the `select_cards` convention in `soccer.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_whatson_board.py
"""The whole board, assembled from fixtures with no network."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from fpp.displays import whatson

FIX = Path(__file__).parent / "fixtures" / "espn"
NOW = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)

SLUG_FIXTURES = {
    "football/college-football": "ncaaf_20260829",
    "football/nfl": "nfl_20260829",
    "soccer/eng.1": "epl_20260829",
    "soccer/eng.fa": "facup_empty",
    "soccer/uefa.champions": "ucl_20260829",
    "tennis/atp": "tennis_atp",
    "tennis/wta": "tennis_wta",
    "racing/f1": "f1_monza",
    "baseball/mlb": "mlb_20260829",
    "hockey/nhl": "nhl_empty",
    "soccer/usa.1": "mls_20260829",
    "soccer/usa.nwsl": "nwsl_20260829",
    "basketball/wnba": "wnba_20260829",
}


@pytest.fixture
def offline(monkeypatch):
    def fake_fetch(slug, dates=None):
        name = SLUG_FIXTURES.get(slug)
        if not name:
            return {"events": []}
        return json.loads((FIX / f"{name}.json").read_text())
    monkeypatch.setattr("fpp.displays.whatson.sources.fetch", fake_fetch)
    monkeypatch.setattr("fpp.displays.whatson.highlights.fetch_all", lambda now=None: [])


def test_board_builds_and_starts_with_the_seattle_block(offline):
    slides, reason = whatson.build_board(now=NOW)
    assert slides
    assert slides[0]["kind"] == "divider"
    assert slides[0]["title"] == "SEATTLE"


def test_seattle_teams_all_appear_including_the_payable_ones(offline):
    slides, _ = whatson.build_board(now=NOW)
    home = [s for s in slides if s.get("home_team")]
    channels = {s["channel"] for s in home}
    assert "Apple TV" in channels          # Sounders
    assert any(c in channels for c in ("Mariners.TV", "NWSL+"))
    assert all(s["tier"] in ("watchable", "payable") for s in home)
    assert "Sportsnet" not in channels, "never show a Canadian-only feed"


def test_caps_are_respected_across_the_whole_board(offline):
    from fpp.displays.whatson.select import CAPS
    slides, _ = whatson.build_board(now=NOW)
    events = [s for s in slides if s["kind"] == "event" and not s.get("home_team")]
    ncaaf = [s for s in events if s["sport"] == "ncaaf"]
    assert len(ncaaf) <= CAPS["ncaaf"]


def test_no_unwatchable_event_reaches_the_board(offline):
    slides, _ = whatson.build_board(now=NOW)
    for s in slides:
        if s["kind"] == "event":
            assert s["tier"] in ("watchable", "payable")


def test_an_entirely_empty_day_yields_the_empty_card(monkeypatch):
    monkeypatch.setattr("fpp.displays.whatson.sources.fetch",
                        lambda slug, dates=None: {"events": []})
    monkeypatch.setattr("fpp.displays.whatson.highlights.fetch_all", lambda now=None: [])
    slides, reason = whatson.build_board(now=NOW)
    assert len(slides) == 1 and slides[0]["kind"] == "empty"
    assert reason == "empty"


def test_every_slide_the_board_produces_can_be_rendered(offline):
    from fpp.displays.whatson.cards import render
    slides, _ = whatson.build_board(now=NOW)
    for s in slides:
        assert render(s).to_image_bytes()[:2] == b"\xff\xd8"
```

- [ ] **Step 2: Run and verify failure**

Run: `hatch run pytest tests/test_whatson_board.py -v`
Expected: FAIL — `AttributeError: module 'fpp.displays.whatson' has no attribute 'build_board'`

- [ ] **Step 3: Implement**

```python
# src/fpp/displays/whatson/__init__.py
"""What's on today and tomorrow, and where to watch it.

Public surface is build_board(); everything else is an implementation detail of
this package.
"""

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
_HOME_ONLY = ["mlb", "nhl", "mls", "nwsl", "wnba", "ncaab"]


def build_board(now: datetime | None = None, include_practice: bool = False,
                with_highlights: bool = True) -> tuple[list[dict], str]:
    """The full slide list, plus a one-word reason for the log line."""
    now = now or datetime.now(timezone.utc)
    dates = date_range(now)

    def _events(slug_key: str) -> list[dict]:
        slug = sources.SLUGS[slug_key]
        try:
            payload = sources.fetch(slug, dates)
        except Exception:
            return []
        return payload.get("events", []) or []

    collected: list[dict] = []

    for key in _MATCH + _HOME_ONLY:
        for event in _events(key):
            card = sources.from_match(event, key, now)
            if card:
                collected.append(card)

    for key in _TOURNAMENT:
        for event in _events(key):
            card = sources.from_tournament(event, key, now)
            if card:
                collected.append(card)

    for key in _SESSION:
        for event in _events(key):
            collected += sources.from_sessions(event, key, now, include_practice)

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
    hl = highlights.fetch_all(now) if with_highlights else []
    slides = select.assemble(home, picked, hl, now)

    if len(slides) == 1 and slides[0]["kind"] == "empty":
        return slides, "empty"
    reason = "live" if any(s.get("state") == "live" for s in slides) else "scheduled"
    return slides, reason
```

- [ ] **Step 4: Run and verify pass**

Run: `hatch run pytest tests/test_whatson_board.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Run the whole suite**

Run: `hatch run pytest -v`
Expected: PASS — all whatson tests plus the pre-existing `test_leadin.py` and `test_week_card.py`

- [ ] **Step 6: Lint and commit**

```bash
hatch run ruff check src tests
git add src/fpp/displays/whatson/__init__.py tests/test_whatson_board.py
git commit -m "whatson: assemble the full board from every source"
```

---

### Task 10: The `whatson` CLI command

**Files:**
- Modify: `src/fpp/cli.py` (add after the `scoreboard` command, before `# --- world clock`)
- Test: `tests/test_whatson_dwell.py`

**Interfaces:**
- Consumes: `whatson.build_board`, `whatson.cards.render`, `_write_playlist_json`, `_client`
- Produces: `_whatson_dwell(slides, interval, cycle, min_interval) -> list[float]` — per-slide seconds

- [ ] **Step 1: Write the failing test**

```python
# tests/test_whatson_dwell.py
"""Per-card dwell. QR cards are the exception that drives the whole rule."""

from fpp.cli import _whatson_dwell


def ev(**kw):
    d = {"kind": "event", "dwell_floor": None}
    d.update(kw)
    return d


def test_quiet_board_uses_the_full_interval():
    dwells = _whatson_dwell([ev(), ev()], interval=12, cycle=210, min_interval=6)
    assert dwells == [12.0, 12.0]


def test_busy_board_shrinks_towards_the_floor():
    slides = [ev() for _ in range(30)]
    dwells = _whatson_dwell(slides, interval=12, cycle=210, min_interval=6)
    assert all(d == 6.0 for d in dwells)


def test_highlight_cards_keep_their_floor_when_everything_else_shrinks():
    slides = [ev() for _ in range(20)] + [ev(kind="highlight", dwell_floor=15.0)]
    dwells = _whatson_dwell(slides, interval=12, cycle=210, min_interval=6)
    assert dwells[-1] == 15.0
    assert dwells[0] < 15.0


def test_worst_case_lap_stays_near_the_cycle_budget():
    slides = ([ev() for _ in range(20)] + [ev(kind="divider")] * 4
              + [ev(kind="highlight", dwell_floor=15.0)] * 3)
    total = sum(_whatson_dwell(slides, interval=12, cycle=210, min_interval=6))
    assert total <= 230, f"lap ran to {total}s"
```

- [ ] **Step 2: Run and verify failure**

Run: `hatch run pytest tests/test_whatson_dwell.py -v`
Expected: FAIL — `ImportError: cannot import name '_whatson_dwell'`

- [ ] **Step 3: Implement**

Add to `src/fpp/cli.py`:

```python
# ------------------------------------------------------------------ what's on

_WHATSON_PLAYLIST = "fpp-whatson"


def _whatson_dwell(slides: list[dict], interval: float, cycle: float,
                   min_interval: float) -> list[float]:
    """Per-slide seconds.

    Everything shrinks to fit the cycle EXCEPT cards carrying a dwell_floor —
    the QR highlight cards. A card you glance at can take six seconds; a card
    you must notice, then scan with a phone, cannot.
    """
    floors = [s.get("dwell_floor") for s in slides]
    fixed = sum(f for f in floors if f)
    flexible = [i for i, f in enumerate(floors) if not f]
    if not flexible:
        return [f or interval for f in floors]
    share = (cycle - fixed) / len(flexible)
    each = max(min_interval, min(interval, share))
    return [f if f else each for f in floors]


@main.command()
@click.option("--interval", default=12.0, help="Per-card dwell when there is room.")
@click.option("--cycle", default=210.0, help="Target seconds for a full lap.")
@click.option("--min-interval", default=6.0, help="Never dwell less than this.")
@click.option("--refresh", default=600.0, help="Seconds between fetches when nothing is live.")
@click.option("--live-refresh", default=60.0, help="Seconds between fetches while something is live.")
@click.option("--practice", is_flag=True, help="Include F1 practice sessions.")
@click.option("--no-highlights", is_flag=True, help="Skip the YouTube highlight block.")
@click.option("--dry-run", is_flag=True, help="Write PNGs locally instead of touching the panel.")
@click.option("--out", default="/tmp/whatson", help="Where --dry-run writes its cards.")
@click.pass_context
def whatson(ctx: click.Context, interval: float, cycle: float, min_interval: float,
            refresh: float, live_refresh: float, practice: bool,
            no_highlights: bool, dry_run: bool, out: str) -> None:
    """Show what sport is on today and tomorrow, and where to watch it.

    A schedule board, not a scoreboard: it surveys the Premier League, the NFL,
    college football, the European and South American cups, the tennis majors,
    Formula 1 and a curated list of oddities, then shows only what can actually
    be watched in the USA — marking anything that would cost extra with a "$".

    Craig's Seattle teams always appear when they play, whatever the sport and
    whatever the channel, in their own block ahead of today.

    The lap ends with any highlights posted in the last 48 hours, as QR codes to
    scan with a phone.
    """
    import json as _json
    import os
    from pathlib import Path

    from .displays import whatson as _w
    from .displays.whatson.cards import render

    host = ctx.obj["host"]

    def _image_entry(filename: str) -> dict:
        return {"type": "image", "enabled": 1, "playOnce": 0, "imagePath": filename,
                "modelName": "LED Panels", "displayMode": "argsOnly"}

    def _pause_entry(secs: float) -> dict:
        return {"type": "pause", "enabled": 1, "playOnce": 0, "duration": secs,
                "displayMode": "argsOnly"}

    def _label(slide: dict) -> str:
        if slide["kind"] == "divider":
            return f"— {slide['title']} —"
        if slide["kind"] == "highlight":
            return f"QR {slide['title']}"
        mark = "$" if slide.get("tier") == "payable" else " "
        return f"{mark}{slide.get('title', slide.get('league_label', ''))} [{slide.get('channel','')}]"

    if dry_run:
        slides, reason = _w.build_board(include_practice=practice,
                                        with_highlights=not no_highlights)
        Path(out).mkdir(parents=True, exist_ok=True)
        for i, slide in enumerate(slides):
            path = os.path.join(out, f"{i:02d}.png")
            render(slide)._img.save(path)
            click.echo(f"  {path}  {_label(slide)}")
        click.echo(f"{len(slides)} cards [{reason}] -> {out}")
        return

    click.echo("Fetching what's on...")
    try:
        while True:
            slides, reason = _w.build_board(include_practice=practice,
                                            with_highlights=not no_highlights)
            dwells = _whatson_dwell(slides, interval, cycle, min_interval)
            entries: list[dict] = []
            with _client(host) as fpp:
                click.echo(f"Building board — {len(slides)} cards [{reason}]")
                for i, (slide, dwell) in enumerate(zip(slides, dwells)):
                    name = f"fpp-whatson-{i}.jpg"
                    fpp.upload_file("images", name, render(slide).to_image_bytes())
                    click.echo(f"  {_label(slide)}  ({dwell:.0f}s)")
                    entries += [_image_entry(name), _pause_entry(dwell)]
                playlist = {
                    "name": _WHATSON_PLAYLIST, "version": 4, "repeat": 1,
                    "loopCount": 0, "desc": "", "random": 0, "empty": False,
                    "leadIn": [], "mainPlaylist": entries, "leadOut": [],
                }
                _write_playlist_json(host, _WHATSON_PLAYLIST,
                                     _json.dumps(playlist, indent=4))
                fpp.start_playlist(_WHATSON_PLAYLIST, repeat=True)

            lap = sum(dwells)
            wait = max(lap, live_refresh if reason == "live" else refresh)
            click.echo(f"Playing — next refresh in {wait:.0f}s  (Ctrl+C to stop)")
            time.sleep(wait)
            click.echo("Refreshing...")
    except KeyboardInterrupt:
        click.echo("\nStopped.")
```

- [ ] **Step 4: Run and verify pass**

Run: `hatch run pytest tests/test_whatson_dwell.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Eyeball a real day**

```bash
hatch run fpp whatson --dry-run --out /tmp/whatson
open /tmp/whatson
```

Check by eye: the SEATTLE block leads; payable cards show `$` on amber; no card is unreadable; the channel strip is legible at a glance.

- [ ] **Step 6: Lint and commit**

```bash
hatch run ruff check src tests
git add src/fpp/cli.py tests/test_whatson_dwell.py
git commit -m "whatson: CLI command, per-card dwell and the QR dwell floor"
```

---

### Task 11: Device registration

**Files:**
- Create: `device/fpp-whatson.service`, `device/sudoers-fpp-whatson`
- Modify: `device/fpp-panel-ctl.sh`, `device/panel-control-server.py`, `device/README.md`

- [ ] **Step 1: Write the unit file**

```ini
# device/fpp-whatson.service
[Unit]
Description=Falcon Player What's On board
After=network-online.target fpp.service
Wants=network-online.target

[Service]
Type=simple
User=fpp
Environment=FPP_HOST=127.0.0.1
ExecStart=/home/fpp/fpp-worldclock-venv/bin/fpp --host 127.0.0.1 whatson --interval 12 --cycle 210
Restart=on-failure
RestartSec=15

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Write the sudoers file**

```
# device/sudoers-fpp-whatson
fpp ALL=(root) NOPASSWD: /usr/bin/systemctl start fpp-whatson.service, /usr/bin/systemctl stop fpp-whatson.service, /usr/bin/systemctl restart fpp-whatson.service, /usr/bin/systemctl enable fpp-whatson.service, /usr/bin/systemctl disable fpp-whatson.service, /usr/bin/systemctl is-active fpp-whatson.service
```

- [ ] **Step 3: Register in `device/fpp-panel-ctl.sh`**

Three edits. **The `DISPLAY_SERVICES` line is the load-bearing one** — without it `stand_down_others()` will not stop whatson, and two services will fight over the panel.

```bash
# line 18 — add the new unit
DISPLAY_SERVICES="fpp-worldclock.service fpp-scoreboard.service fpp-nfl.service fpp-whatson.service"
```

```bash
# in the SVCKEY case (~line 67), add:
  whatson)    SVC=fpp-whatson.service ;;
```

```bash
# both usage strings (~lines 23 and 127) — add whatson:
  *) echo "usage: $0 [worldclock|scoreboard|nfl|whatson|current] {start|stop|restart|enable|disable|status}" >&2; exit 1 ;;
```

- [ ] **Step 4: Register in `device/panel-control-server.py`**

```python
# line 32
_SERVICES = {"worldclock", "scoreboard", "nfl", "whatson", "current"}
```

- [ ] **Step 5: Document in `device/README.md`**

Add whatson alongside the other display services, noting it is not enabled at boot (matching worldclock, scoreboard and nfl).

- [ ] **Step 6: Deploy and verify on the device**

```bash
scp device/fpp-whatson.service fpp@192.168.1.66:/tmp/
scp device/fpp-panel-ctl.sh device/panel-control-server.py fpp@192.168.1.66:/home/fpp/
ssh fpp@192.168.1.66 'sudo mv /tmp/fpp-whatson.service /etc/systemd/system/ && sudo systemctl daemon-reload'
scp device/sudoers-fpp-whatson fpp@192.168.1.66:/tmp/
ssh fpp@192.168.1.66 'sudo install -m 440 /tmp/sudoers-fpp-whatson /etc/sudoers.d/fpp-whatson && sudo visudo -c'
```

Install the package into the device venv, then verify mutual exclusion actually works:

```bash
ssh fpp@192.168.1.66 '/home/fpp/fpp-worldclock-venv/bin/pip install -e /home/fpp/falconplayer-controller'
ssh fpp@192.168.1.66 '/home/fpp/fpp-panel-ctl.sh whatson start && sleep 20 && /home/fpp/fpp-panel-ctl.sh whatson status'
# Now confirm starting another display STOPS whatson:
ssh fpp@192.168.1.66 '/home/fpp/fpp-panel-ctl.sh worldclock start && sleep 5 && systemctl is-active fpp-whatson.service'
# Expected: "inactive"
```

- [ ] **Step 7: Commit**

```bash
git add device/
git commit -m "whatson: register the display service on the device

Verified mutual exclusion: starting worldclock stops whatson, so the two
never fight over the panel."
```

---

### Task 12: Home Assistant wiring

A display service that exists only on the Falcon Player is unreachable in practice, and HA's scripts stop display services **by name** — a service HA does not know about will not be stopped when an animation plays.

**Files (in `~/Coding/HomeAssistant`):**
- Modify: `config/configuration.yaml`, `config/scripts.yaml`, `config/dashboards/worldclock.yaml`

- [ ] **Step 1: `config/configuration.yaml`**

Add `rest_command.whatson_start` and `whatson_stop` following the existing `scoreboard_*` pattern exactly (same bearer token via `!secret worldclock_auth_header`, pointing at `http://192.168.1.66:8090/whatson/start` and `/stop`).

Add a `rest:` sensor polling `http://192.168.1.66:8090/whatson/status`, modelled on the scoreboard sensor.

Add a `whatson` branch to the `FPP Panel Show` template sensor so the dashboard names it properly.

- [ ] **Step 2: `config/scripts.yaml`**

- Add a `fpp_whatson_start` script mirroring `fpp_scoreboard_start`.
- **Add the whatson stop call to `fpp_play_animation`** — required, or an animation will be taken back by whatson.
- **Add the whatson stop call to `fpp_panel_stop`.**
- Add the new sensor to `fpp_refresh_status`.

- [ ] **Step 3: `config/dashboards/worldclock.yaml`**

Add a button calling `script.fpp_whatson_start`, and a status row for the new sensor, matching the existing rows.

- [ ] **Step 4: Validate before deploying**

```bash
cd ~/Coding/HomeAssistant && ./scripts/validate.sh   # or the repo's documented check
```

- [ ] **Step 5: Deploy config, then push the dashboard separately**

The dashboard is storage-mode — editing the YAML alone does nothing.

```bash
python scripts/push_dashboard.py config/dashboards/worldclock.yaml
```

- [ ] **Step 6: Reload without restarting, then test end to end**

From the HA dashboard: press the What's On button, confirm the panel changes and the status row updates. Then press an animation button and confirm whatson stops rather than reclaiming the panel a few seconds later.

- [ ] **Step 7: Commit (in the HomeAssistant repo)**

```bash
git add config/
git commit -m "fpp: add the What's On display service to the panel dashboard"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| Data sources, three event shapes | 4 |
| Timezone (PDT) | 2 |
| Channel filtering, three tiers | 1 |
| Definition of "major" (incl. F1 Sprint) | 4 (per-event), 5 (oddities) |
| Home teams | 3 (config), 5 (`mark_home`, block), 9 (routing) |
| Caps and ranking | 5 |
| Slides / all card types | 7 |
| Payable marking | 7 |
| Empty state | 5, 7 |
| Refresh and dwell (cycle 210, QR floor) | 10 |
| oddities.yaml | 3, 5 |
| Highlights, QR, dwell exception | 6, 8 |
| Device integration | 11 |
| Home Assistant integration | 12 |
| Testing | throughout; fixtures already committed |

No gaps.

**Placeholder scan:** none. Every code step carries real code. Task 12 describes edits to files in another repo rather than quoting them, because the existing `scoreboard_*` blocks there are the pattern to copy and the plan cannot see that repo's current contents — the instruction names the exact keys and the exact files.

**Type consistency:** the card dict is defined once under File Structure and used unchanged in Tasks 4, 5, 7, 9, 10. `best_channel` returns `tuple[str, str] | None` in Task 1 and is consumed that way in Task 4. `dwell_floor` is set in Task 8 and read in Task 10. `build_board` returns `(slides, reason)`, matching the `select_cards` convention.

**Known risks, carried forward from the spec:**

1. **The QR physical scan (Task 6) can fail**, which would invalidate the highlights handoff. It is deliberately sequenced before Tasks 8 and 9 and says to stop rather than build on it.
2. **NHL and NCAAB are specified but unexercised** — both were out of season on the fixture date, so the Kraken and Huskies-basketball paths have no live data behind them. First real game is where a surprise would appear.
3. **Unrecognised channel names default to `payable`** (Task 1), which is the safe direction — it hides a game rather than promising one the user cannot watch — but it means a newly-renamed cable channel will silently drop out of the watchable tier until its name is added.
