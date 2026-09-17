"""The one model call: pick the day's fact, write it short, name the observances.

This runs at most once a day (see cache.py) and is the only place in the repo
that talks to Anthropic. It is given Wikipedia's verified event list and asked
to choose and compress — the history itself is not invented here.

The international days ARE model-named: no free API lists them, and the UN's
own list is a web page. Each one therefore comes back with a source_url so a
wrong day can be traced afterwards. That is traceability, not verification.
"""

from __future__ import annotations

import json
import os
from datetime import date

from .window import pretty

MODEL = "claude-opus-5"

# Panel-sized limits. The card renderer wraps and shrinks to fit, but it shrinks
# to a floor and then overflows, so the real fix is asking for text that fits.
#
# SYNOPSIS_CHARS is 155 because the model reliably writes ~145-150 and _trim
# then cut it mid-clause — a card ending "...across..." every day. Measured: the
# synopsis band takes six wrapped lines, about 165 characters, before it starts
# shrinking past legibility. Do not raise this without re-rendering a long one.
HEADLINE_CHARS = 30
SYNOPSIS_CHARS = 155
DAY_NAME_CHARS = 60

_SCHEMA = {
    "type": "object",
    "properties": {
        "fact": {
            "type": "object",
            "properties": {
                "year": {"type": "integer"},
                "country": {"type": "string"},
                "country_code": {"type": "string"},
                "headline": {"type": "string"},
                "synopsis": {"type": "string"},
                "source_url": {"type": "string"},
            },
            "required": ["year", "country", "country_code", "headline",
                         "synopsis", "source_url"],
            "additionalProperties": False,
        },
        "today": {"$ref": "#/$defs/observance"},
        "tomorrow": {"$ref": "#/$defs/observance"},
    },
    "required": ["fact", "today", "tomorrow"],
    "additionalProperties": False,
    "$defs": {
        "observance": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "established": {"type": "string"},
                "source_url": {"type": "string"},
            },
            "required": ["name", "established", "source_url"],
            "additionalProperties": False,
        },
    },
}

_SYSTEM = f"""You write cards for a 192x192 LED panel on a wall. Text longer \
than the limits below is shrunk until it overflows the panel and becomes \
unreadable, so the limits are hard.

You will be given Wikipedia's curated list of events for one calendar date.

Pick the ONE most globally meaningful event. Prefer events that changed \
something beyond their own borders — a treaty, an independence, a discovery, a \
first — over sports results, minor battles, and celebrity births or deaths. \
Do not default to the United States; this panel is meant to show the world.

For that event give:
- year: the year it happened
- country: the country where it happened, as it would be named TODAY, in \
English, upper case, at most 18 characters ("USSR" and "EAST GERMANY" are fine \
where the modern name would be misleading)
- country_code: that country's ISO 3166-1 alpha-2 code, lower case. Use the \
modern successor state's code for a country that no longer exists ("ru" for the \
USSR). Use "" if it genuinely happened nowhere in particular (in orbit, at sea).
- headline: at most {HEADLINE_CHARS} characters, upper case, naming the event
- synopsis: at most {SYNOPSIS_CHARS} characters, ONE or TWO plain sentences \
saying what happened and why it mattered. Write for someone glancing at a wall, \
not for an encyclopedia. No dates in the text — the card already shows the year.
- source_url: the Wikipedia URL you were given for that event, verbatim

Then name the international day observed on each of the two dates given. Prefer \
United Nations observances, then other widely recognised international days. \
Give the name at most {DAY_NAME_CHARS} characters and WITHOUT a leading \
"International Day of" where dropping it still reads clearly — the card already \
says INTERNATIONAL DAY. "established" is the year it was first observed, as a \
bare year, or "" if you are unsure. source_url should be the UN or Wikipedia \
page for it.

If a date genuinely has no international observance, return "" for its name \
rather than inventing one or stretching to a national holiday."""


def _prompt(today: date, tomorrow: date, events: list[dict]) -> str:
    lines = [f"Today is {pretty(today)}. Tomorrow is {pretty(tomorrow)}.", ""]
    lines.append(f"Wikipedia's selected events for {pretty(today)}:")
    for e in events:
        url = f"  [{e['url']}]" if e.get("url") else ""
        lines.append(f"- {e['year']}: {e['text']}{url}")
    lines += ["", "Pick the day's fact from that list, and name the "
              "international day for each of the two dates."]
    return "\n".join(lines)


def compose(today: date, tomorrow: date, events: list[dict]) -> dict:
    """One brief, or raise. Callers fall back down the tiers in cache.py."""
    import anthropic

    if not events:
        raise RuntimeError("no Wikipedia events to choose from")
    if not (os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise RuntimeError("no Anthropic credentials in the environment")

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=_SYSTEM,
        output_config={"effort": "medium",
                       "format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user", "content": _prompt(today, tomorrow, events)}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("model declined to write the brief")

    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        raise RuntimeError("empty response")
    return _clean(json.loads(text))


def _trim(value: str, limit: int) -> str:
    value = " ".join((value or "").split())
    if len(value) <= limit:
        return value
    # Cut on a word boundary — a half-word on a wall reads as a bug.
    cut = value[:limit].rsplit(" ", 1)[0]
    return (cut or value[:limit]).rstrip(" ,;:") + "..."


def _clean(data: dict) -> dict:
    """Belt and braces on the model's own limits, and normalise the codes."""
    fact = data.get("fact") or {}
    code = (fact.get("country_code") or "").strip().lower()
    out = {
        "fact": {
            "year": int(fact.get("year") or 0),
            "country": _trim((fact.get("country") or "").upper(), 18),
            "country_code": code if len(code) == 2 and code.isalpha() else "",
            "headline": _trim((fact.get("headline") or "").upper(), HEADLINE_CHARS),
            "synopsis": _trim(fact.get("synopsis") or "", SYNOPSIS_CHARS),
            "source_url": fact.get("source_url") or "",
        },
    }
    for key in ("today", "tomorrow"):
        day = data.get(key) or {}
        out[key] = {
            "name": _trim(day.get("name") or "", DAY_NAME_CHARS),
            "established": str(day.get("established") or "").strip(),
            "source_url": day.get("source_url") or "",
        }
    return out
