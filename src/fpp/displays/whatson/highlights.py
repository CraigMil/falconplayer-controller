"""Recaps that have just been posted, as scannable QR cards.

YouTube per-channel RSS: no API key, no quota. The feed is a rolling window of
about fifteen videos, so this is a recency feature and not an archive. These
channels post constant filler between events, so selection is always on title
patterns and never on "the newest video".
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

import httpx

from .config import highlight_sources

FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
WINDOW = timedelta(hours=48)
MAX_CARDS = 3
DWELL_FLOOR = 15.0        # a QR card must be noticed, then scanned

_NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}


def parse_feed(xml: str):
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
            when = datetime.fromisoformat((pub or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if title and vid:
            out.append({"title": title, "video_id": vid, "published": when})
    return out


# Real tennis titles look like:
#   "Lumsden/Kozyreva vs. Joint/Xu | 2026 Monterrey Doubles Final | WTA Match Highlights"
#   "Arthur Fery vs James Duckworth Highlights | 2026 Winston-Salem Semi-finals"
#   "Bencic/Cobolli vs. Muchova/Mensik Full Match | 2026 US Open Final"
# The tournament is the middle segment, behind a year and ahead of a round.
_YEAR = re.compile(r"^\s*(19|20)\d{2}\s*")
# Wimbledon puts the year at the END ("Wimbledon 2026") rather than the front.
_YEAR_TAIL = re.compile(r"\s*(19|20)\d{2}\s*$")
_ROUND_TAIL = re.compile(
    r"\s*(?:men'?s|women'?s|mixed|doubles|singles|"
    r"semi[\s-]?finals?|quarter[\s-]?finals?|finals?|"
    r"round\s+of\s+\d+|r\d+|match\s+highlights?|full\s+match|highlights?)\s*$",
    re.I)


def tournament_label(title: str):
    """The tournament from a tennis highlight title, or None if it is not there."""
    parts = [p.strip() for p in title.split("|") if p.strip()]
    if len(parts) < 2:
        return None
    seg = _YEAR_TAIL.sub("", _YEAR.sub("", parts[1]))
    prev = None
    while prev != seg:                      # peel round words off the end
        prev = seg
        seg = _ROUND_TAIL.sub("", seg).strip(" -–")
    seg = re.sub(r"\s*-\s*", "-", seg).strip()
    return seg.upper() or None


def matches(entry: dict, patterns) -> bool:
    title = (entry.get("title") or "").lower()
    return any(p.lower() in title for p in patterns)


def _age(published: datetime, now: datetime) -> str:
    hours = max(0, int((now - published).total_seconds() // 3600))
    return f"{hours}h" if hours < 48 else f"{hours // 24}d"


def select(entries_by_source, now: datetime, patterns_by_source, sports_by_source=None):
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
    seen_titles = set()
    for source, entry in picks:
        if len(cards) >= MAX_CARDS:
            break
        # Two channels frequently post the same game (ESPN and a conference
        # feed). One card per event, not one per channel.
        key = "".join(ch for ch in entry["title"].lower() if ch.isalnum())[:36]
        if key in seen_titles:
            continue
        seen_titles.add(key)
        # Channels are inconsistent: F1 posts "Italian GP | Race Highlights",
        # while ESPN and the tennis tours post a bare "A vs. B". Splitting on the
        # pipe unconditionally makes the title and subtitle the same string.
        raw = entry["title"]
        base_label = (sports_by_source or {}).get(source, "").upper() or "HIGHLIGHTS"
        if "|" in raw:
            head, tail = raw.split("|", 1)
        else:
            head, tail = raw, source
        cards.append({
            "kind": "highlight", "sport": "highlight", "source": source,
            # Tennis names the tournament rather than the sport — "US OPEN
            # HIGHLIGHTS" beats "TENNIS HIGHLIGHTS" when the tournament is
            # right there in the title.
            "sport_label": (tournament_label(raw) if base_label == "TENNIS" else None)
                           or base_label,
            "colour_key": base_label,
            # Generous: the card now shrinks text to fit across two lines, so
            # clipping here only ever loses a real competitor's name.
            "title": head.strip().upper()[:60],
            "subtitle": tail.strip()[:26],
            "url": f"https://youtu.be/{entry['video_id']}",
            "age": _age(entry["published"], now),
            "published": entry["published"],
            "dwell_floor": DWELL_FLOOR,
        })
    return cards


def fetch_all(now=None):
    """Every configured source. A dead feed is skipped, never fatal —
    a broken highlight channel must not cost the user the schedule board."""
    now = now or datetime.now(timezone.utc)
    entries = {}
    patterns = {}
    sports = {}
    for source in highlight_sources():
        name = source["name"]
        patterns[name] = source.get("patterns", [])
        sports[name] = source.get("label") or source.get("sport", "")
        try:
            with httpx.Client(timeout=10) as c:
                r = c.get(FEED.format(source["channel_id"]))
                r.raise_for_status()
            entries[name] = parse_feed(r.text)
        except Exception:
            entries[name] = []
    return select(entries, now, patterns, sports)
