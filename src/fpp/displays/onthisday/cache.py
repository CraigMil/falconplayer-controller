"""One JSON per day, and the ladder the panel climbs down when it cannot build one.

The panel must never go blank, and it must never show yesterday's international
day as though it were today's. Those two rules are what shape the tiers:

  fresh      today's cache, built today
  rebuilt    built just now from Wikipedia + the model, and written
  stale      yesterday's cache, FACT ONLY — the observances are dropped,
             because a date-specific card that is one day wrong is worse than
             no card at all
  wikipedia  the raw Wikipedia extract, trimmed, no country and no observances
  static     a bare "ON THIS DAY" card

Every tier is logged by name, so a panel showing something odd can be explained
without guessing which half of the pipeline failed.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from . import brief, sources
from .window import today as _today
from .window import tomorrow as _tomorrow

CACHE_DIR = Path.home() / ".cache" / "fpp-onthisday"
KEEP_DAYS = 14


def _path(day: date) -> Path:
    return CACHE_DIR / f"{day.isoformat()}.json"


def read(day: date) -> dict | None:
    path = _path(day)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    # A file whose date does not match its name is a half-written or
    # hand-edited file; treat it as absent rather than trusting it.
    return data if data.get("date") == day.isoformat() else None


def write(day: date, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(data, date=day.isoformat(),
                   built_at=datetime.now().astimezone().isoformat(timespec="seconds"))
    # Write-then-rename: a refresh that dies mid-write must not leave a
    # truncated file that read() would reject for the rest of the day.
    tmp = _path(day).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(_path(day))
    _prune()


def _prune() -> None:
    cutoff = _today() - timedelta(days=KEEP_DAYS)
    for old in CACHE_DIR.glob("*.json"):
        try:
            if date.fromisoformat(old.stem) < cutoff:
                old.unlink()
        except ValueError:
            continue  # not one of ours


def _from_wikipedia(events: list[dict]) -> dict:
    """The no-model tier: Wikipedia's own words, mechanically trimmed.

    There is no country here — the feed has no such field, and guessing one
    from the text is exactly the kind of quiet wrongness this display should
    not put on a wall.
    """
    top = events[0]
    return {
        "fact": {
            "year": top["year"],
            "country": "",
            "country_code": "",
            "headline": "",
            "synopsis": brief._trim(top["text"], brief.SYNOPSIS_CHARS),
            "source_url": top.get("url", ""),
        },
        "today": {"name": "", "established": "", "source_url": ""},
        "tomorrow": {"name": "", "established": "", "source_url": ""},
    }


_STATIC = {
    "fact": {"year": 0, "country": "", "country_code": "", "headline": "",
             "synopsis": "", "source_url": ""},
    "today": {"name": "", "established": "", "source_url": ""},
    "tomorrow": {"name": "", "established": "", "source_url": ""},
}


def load(now: datetime | None = None, rebuild: bool = True) -> tuple[dict, str]:
    """Today's brief and the name of the tier it came from."""
    day = _today(now)

    cached = read(day)
    if cached:
        return dict(cached, fact_date=day.isoformat()), "fresh"

    events = sources.events(day)

    if rebuild:
        try:
            built = brief.compose(day, _tomorrow(now), events)
            write(day, built)
            return dict(built, date=day.isoformat(),
                        fact_date=day.isoformat()), "rebuilt"
        except Exception:
            pass

    yesterday = read(day - timedelta(days=1))
    if yesterday:
        # The fact survives a day late — it is dated by its own year, not by
        # today. The observances do not.
        return {
            "date": day.isoformat(),
            # The card prints this when it is not today, so a day-late fact
            # says so on the panel instead of pretending.
            "fact_date": (day - timedelta(days=1)).isoformat(),
            "fact": yesterday.get("fact", _STATIC["fact"]),
            "today": dict(_STATIC["today"]),
            "tomorrow": dict(_STATIC["tomorrow"]),
        }, "stale"

    if events:
        return dict(_from_wikipedia(events), date=day.isoformat(),
                    fact_date=day.isoformat()), "wikipedia"

    return dict(_STATIC, date=day.isoformat(), fact_date=day.isoformat()), "static"
