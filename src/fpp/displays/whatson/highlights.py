"""Recaps that have just been posted, as scannable QR cards.

YouTube per-channel RSS: no API key, no quota. The feed is a rolling window of
about fifteen videos, so this is a recency feature and not an archive. These
channels post constant filler between events, so selection is always on title
patterns and never on "the newest video".
"""

from __future__ import annotations

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


def matches(entry: dict, patterns) -> bool:
    title = (entry.get("title") or "").lower()
    return any(p.lower() in title for p in patterns)


def _age(published: datetime, now: datetime) -> str:
    hours = max(0, int((now - published).total_seconds() // 3600))
    return f"{hours}h" if hours < 48 else f"{hours // 24}d"


def select(entries_by_source, now: datetime, patterns_by_source):
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
        title = entry["title"]
        cards.append({
            "kind": "highlight", "sport": "highlight", "source": source,
            "title": title.split("|")[0].strip().upper()[:28],
            "subtitle": title.split("|")[-1].strip()[:24],
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
