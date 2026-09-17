"""192x192 cards: one historical fact, then today's and tomorrow's observance.

Three layout rules carried over from the what's-on board, all learned the hard
way: text_fit shrinks to a floor and then OVERFLOWS rather than clipping, so
anything that can be long must be wrapped first; a flag below about 28px wide
is unreadable across a room; and a card must say which day it is talking about,
because "TOMORROW" is not inferable from a date alone.
"""

from __future__ import annotations

from datetime import date

from ...canvas import Frame
from . import sources
from .window import pretty

W = H = 192
STRIP_H = 26

FG = (255, 255, 255)
DIM = (150, 150, 150)
FAINT = (105, 105, 105)
GOLD = (235, 185, 70)
BG = (0, 0, 0)

HEADER = {
    "fact": (34, 28, 86),        # deep indigo — the history card
    "today": (12, 74, 68),       # teal
    "tomorrow": (68, 34, 74),    # plum, so a glance tells the two apart
}


def _wrap(frame: Frame, text: str, max_width: int, size: int, lines: int) -> list[str]:
    """Greedy word wrap measured in PIXELS, capped at `lines`.

    Measured, not counted: "WWW" and "iii" are the same number of characters and
    nowhere near the same number of pixels, and a character-counted wrap put the
    long words of a synopsis off the edge of the panel.
    """
    words = (text or "").split()
    if not words:
        return []
    rows: list[str] = []
    cur = ""
    for word in words:
        candidate = f"{cur} {word}".strip()
        if cur and frame.text_width(candidate, size) > max_width:
            rows.append(cur)
            cur = word
            if len(rows) == lines:
                break
        else:
            cur = candidate
    if len(rows) < lines and cur:
        rows.append(cur)
    if len(rows) == lines and cur and rows[-1] != cur:
        # Whatever did not fit is signalled rather than silently dropped.
        rows[-1] = rows[-1].rstrip(" ,;:") + "..."
    return rows


def _block(frame: Frame, text: str, top: int, bottom: int, max_width: int,
           size: int, min_size: int, lines: int, color) -> int:
    """Wrap `text` into the band, shrinking the font until it fits. Returns the y below it."""
    s = size
    while s > min_size:
        rows = _wrap(frame, text, max_width, s, lines)
        if len(rows) * (s + 3) <= (bottom - top):
            break
        s -= 1
    rows = _wrap(frame, text, max_width, s, lines)
    if not rows:
        return top
    step = s + 3
    y = top + ((bottom - top) - len(rows) * step) // 2 + step // 2
    for row in rows:
        frame.text_fit(W // 2, y, row, max_width=max_width, size=s,
                       min_size=min_size, color=color, anchor="mm")
        y += step
    return y


def _strip(frame: Frame, kind: str, left: str, right: str) -> None:
    frame.rect(0, 0, W, STRIP_H, HEADER.get(kind, (40, 40, 40)))
    # The two labels must not touch: "INTERNATIONAL DAY" + "TOMORROW" is the
    # widest pair, and at 192px a missing gap reads as one run-on word.
    frame.text_fit(6, STRIP_H // 2, left, max_width=116, size=13, min_size=8,
                   color=FG, anchor="lm")
    frame.text_fit(W - 6, STRIP_H // 2, right, max_width=62, size=11, min_size=7,
                   color=FG, anchor="rm")


def _fact(frame: Frame, card: dict) -> None:
    year = card.get("year") or 0
    country = card.get("country") or ""
    code = card.get("country_code") or ""
    headline = card.get("headline") or ""
    synopsis = card.get("synopsis") or ""

    if not year and not synopsis:
        frame.text(W // 2, H // 2, "ON THIS DAY", size=20, color=DIM, anchor="mm")
        frame.text(W // 2, H // 2 + 22, "no fact today", size=11, color=FAINT, anchor="mm")
        return

    # The year is the hook — it is the first thing read from across the room.
    if year:
        frame.text_fit(W // 2, 46, str(year), max_width=W - 16, size=34,
                       min_size=20, color=GOLD, anchor="mm")

    row_y = 66
    if country or code:
        flag = sources.flag(code)
        x = 8
        if flag is not None:
            # 40x27 keeps a tricolour legible; smaller and every flag is a blur.
            frame.paste(flag.resize((40, 27)), x, row_y)
            x += 48
        if country:
            frame.text_fit(x + (W - x - 8) // 2, row_y + 13, country,
                           max_width=W - x - 8, size=15, min_size=9,
                           color=FG, anchor="mm")

    top = 100 if (country or code) else 74
    if headline:
        below = _block(frame, headline, top, top + 44, W - 12, 16, 9, 2, FG)
        _block(frame, synopsis, below + 2, H - 3, W - 10, 12, 8, 6, DIM)
    else:
        # The Wikipedia tier has no headline of its own; the extract takes the
        # whole band rather than leaving a hole where one would have been.
        _block(frame, synopsis, top, H - 4, W - 12, 14, 8, 6, FG)


def _observance(frame: Frame, card: dict) -> None:
    name = card.get("name") or ""
    if not name:
        frame.text(W // 2, H // 2 - 6, "NO INTERNATIONAL", size=14, color=FAINT, anchor="mm")
        frame.text(W // 2, H // 2 + 12, "DAY LISTED", size=14, color=FAINT, anchor="mm")
        return

    day = card.get("day")
    if day:
        frame.text_fit(W // 2, 44, pretty(day), max_width=W - 16, size=15,
                       min_size=9, color=GOLD, anchor="mm")

    bottom = H - (24 if card.get("established") else 6)
    _block(frame, name, 60, bottom, W - 12, 22, 10, 4, FG)

    if card.get("established"):
        frame.text(W // 2, H - 13, f"since {card['established']}", size=11,
                   color=FAINT, anchor="mm")


def render(card: dict) -> Frame:
    """One card dict in, one 192x192 Frame out."""
    frame = Frame(bg=BG)
    kind = card.get("kind")
    if kind == "fact":
        _strip(frame, "fact", "ON THIS DAY", card.get("date_label", ""))
        _fact(frame, card)
    else:
        when = "tomorrow" if kind == "tomorrow" else "today"
        _strip(frame, when, "INTERNATIONAL DAY", when.upper())
        _observance(frame, card)
    return frame


def date_label(day: date) -> str:
    """The strip's right-hand date: "16 SEP"."""
    return f"{day.day} {day.strftime('%b').upper()}"
