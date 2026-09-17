"""What the panel can verify: Wikipedia's curated events, and country flags.

Nothing in this module is generated. The historical facts come from Wikimedia's
"on this day" feed, which is the same hand-curated list that fronts Wikipedia's
date pages, and the flags come from flagcdn. brief.py is where a model gets
involved; keeping the two apart is what makes a wrong card traceable to one of
them.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from io import BytesIO

import httpx
from PIL import Image

from . import paths

# The public Wikimedia feed. No key, no quota, but it does want to know who is
# calling — an unset User-Agent gets 403s under load.
_FEED = "https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/selected/{month:02d}/{day:02d}"
_UA = "falconplayer-controller/onthisday (https://github.com/CraigMil/falconplayer-controller)"

# w80 is 80px wide; the card draws it at 44x29, and downscaling a larger source
# keeps the stripes and crescents from turning to mush.
_FLAG = "https://flagcdn.com/w80/{code}.png"

FLAG_CACHE = paths.base() / "flags"


def events(day: date) -> list[dict]:
    """Wikipedia's selected events for a calendar date, newest year first.

    Returns [] rather than raising: a dead feed must degrade to the next tier
    in the chain, not take the panel down.
    """
    url = _FEED.format(month=day.month, day=day.day)
    try:
        with httpx.Client(timeout=20, headers={"User-Agent": _UA}) as c:
            r = c.get(url)
            r.raise_for_status()
            payload = r.json()
    except Exception:
        return []

    out = []
    for item in payload.get("selected", []) or []:
        year = item.get("year")
        text = (item.get("text") or "").strip()
        if not year or not text:
            continue
        pages = item.get("pages") or []
        out.append({
            "year": int(year),
            "text": text,
            # The first linked page is the event itself often enough to be a
            # useful citation, and it is the only URL the feed offers.
            "url": (((pages[0] if pages else {}).get("content_urls") or {})
                    .get("desktop") or {}).get("page", ""),
        })
    out.sort(key=lambda e: e["year"], reverse=True)
    return out


@lru_cache(maxsize=64)
def flag(code: str):
    """An RGBA flag for an ISO 3166-1 alpha-2 code, or None.

    Cached on disk as well as in memory. The panel rebuilds its cards on every
    refresh, and re-fetching the same flag every ten minutes forever is rude to
    a free service that asks for nothing.
    """
    code = (code or "").strip().lower()
    if len(code) != 2 or not code.isalpha():
        return None

    path = FLAG_CACHE / f"{code}.png"
    if path.exists():
        try:
            return Image.open(path).convert("RGBA")
        except Exception:
            path.unlink(missing_ok=True)

    try:
        r = httpx.get(_FLAG.format(code=code), timeout=8, headers={"User-Agent": _UA})
        r.raise_for_status()
        img = Image.open(BytesIO(r.content)).convert("RGBA")
    except Exception:
        return None

    try:
        FLAG_CACHE.mkdir(parents=True, exist_ok=True)
        img.save(path)
    except Exception:
        pass  # An uncacheable flag still renders; it just costs a fetch next time.
    return img
