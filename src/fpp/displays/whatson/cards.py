"""192x192 cards. The bottom strip is always the channel — that is the question
this display exists to answer.
"""

from __future__ import annotations

import re
from functools import lru_cache
from io import BytesIO

import httpx
from PIL import Image

from ...canvas import Frame

W = H = 192
STRIP_H = 26          # league / status
CHANNEL_H = 36        # the answer, along the bottom
FG = (255, 255, 255)
DIM = (150, 150, 150)
LIVE = (235, 60, 60)
AMBER = (235, 170, 45)
BG = (0, 0, 0)

LEAGUE_COLOURS = {
    "NFL": (20, 40, 90), "NCAAF": (90, 25, 30), "EPL": (55, 0, 60),
    "UCL": (10, 25, 90), "UEL": (60, 40, 0), "TENNIS": (20, 70, 40),
    "F1": (120, 20, 20), "MLB": (25, 45, 80), "MLS": (20, 60, 70),
    "NWSL": (70, 25, 70), "WNBA": (60, 30, 80), "NHL": (35, 35, 40),
    "ALSO ON": (50, 45, 20), "FA CUP": (40, 40, 55),
    # The wildcard sports. They head the card as ODDITY, but the colour still
    # follows the sport so two oddities on one board look different.
    "GOLF": (25, 65, 35), "LPGA": (60, 30, 60), "UFC": (95, 20, 20),
    "BOXING": (95, 45, 15), "LACROSSE": (30, 55, 75),
}


@lru_cache(maxsize=64)
def _logo(url: str):
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
    # colour_key lets a card show one thing and be coloured as another — a
    # tennis card says "US OPEN" but keeps the tennis green.
    frame.rect(0, 0, W, STRIP_H,
               LEAGUE_COLOURS.get(card.get("colour_key") or label, (40, 40, 40)))
    frame.text_fit(6, STRIP_H // 2, label, max_width=124, size=13, min_size=8,
                   color=FG, anchor="lm")
    colour = LIVE if card.get("state") == "live" else FG
    frame.text(W - 6, STRIP_H // 2, card.get("status_text", ""), size=12,
               color=colour, anchor="rm")


def _channel(frame: Frame, card: dict) -> None:
    y = H - CHANNEL_H
    payable = card.get("tier") == "payable"
    frame.rect(0, y, W, CHANNEL_H, (58, 40, 8) if payable else (22, 22, 22))
    text = card.get("channel", "")
    if payable:
        text = f"$ {text}"
    frame.text_fit(W // 2, y + CHANNEL_H // 2, text, max_width=W - 12,
                   size=20, color=AMBER if payable else FG, anchor="mm")


def _match(frame: Frame, card: dict) -> None:
    body_top, body_bot = STRIP_H, H - CHANNEL_H
    mid = (body_top + body_bot) // 2
    for side, cx in (((card.get("away") or {}), 52), ((card.get("home") or {}), 140)):
        img = _logo(side.get("logo", ""))
        if img is not None:
            frame.paste(img.resize((40, 40)), cx - 20, body_top + 6)
        label = side.get("abbr", "")
        if side.get("rank"):
            label = f"#{side['rank']} {label}"
        frame.text_fit(cx, mid + 22, label, max_width=86, size=17, color=FG, anchor="mm")
        frame.text(cx, mid + 40, side.get("record", ""), size=10, color=DIM, anchor="mm")
    score = card.get("score")
    if score:
        frame.text(52, mid + 2, str(score[0]), size=24, color=FG, anchor="mm")
        frame.text(140, mid + 2, str(score[1]), size=24, color=FG, anchor="mm")
    else:
        frame.text(96, mid + 2, "@", size=13, color=DIM, anchor="mm")


def _tennis(frame: Frame, card: dict) -> None:
    """Two players stacked. Names like "R. Carballes Baena" never fit the
    two-column team layout, so each gets its own full-width row."""
    body_top, body_bot = STRIP_H, H - CHANNEL_H
    rows = [body_top + 6, body_top + 56]
    players = card.get("players") or []
    for y, p in zip(rows, players):
        flag = _logo(p.get("flag", ""))
        x_text = 8
        if flag is not None:
            # 28x19 rather than 20x14 — at 192px a small flag is unreadable
            # from across the room, and the flag is half the identification.
            frame.paste(flag.resize((28, 19)), 6, y)
            x_text = 40
        label = p.get("name", "")
        if p.get("seed"):
            label = f"({p['seed']}) {label}"
        frame.text_fit(x_text + (W - x_text - 8) // 2, y + 9, label,
                       max_width=W - x_text - 10, size=16, min_size=8,
                       color=FG, anchor="mm")
        sets = p.get("sets") or []
        if sets:
            frame.text(W // 2, y + 28, "  ".join(str(s) for s in sets),
                       size=14, color=FG if p.get("winner") else DIM, anchor="mm")
    label = " · ".join(x for x in (card.get("detail", ""), card.get("subtitle", "")) if x)
    frame.text_fit(W // 2, body_bot - 8, label, max_width=W - 10, size=10,
                   min_size=7, color=DIM, anchor="mm")


def _single(frame: Frame, card: dict) -> None:
    body_top, body_bot = STRIP_H, H - CHANNEL_H
    mid = (body_top + body_bot) // 2
    frame.text_fit(W // 2, mid - 24, card.get("title", ""), max_width=W - 12,
                   size=25, color=FG, anchor="mm")
    frame.text_fit(W // 2, mid + 4, card.get("subtitle", ""), max_width=W - 12,
                   size=16, color=FG, anchor="mm")
    frame.text_fit(W // 2, mid + 28, card.get("detail", ""), max_width=W - 12,
                   size=12, color=DIM, anchor="mm")


def _divider(frame: Frame, card: dict) -> Frame:
    frame.text_fit(W // 2, 74, card.get("title", ""), max_width=W - 16,
                   size=32, color=FG, anchor="mm")
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


# " Wolfpack vs. Virginia " and friends. Splitting the matchup across two lines
# is worth far more than a subtitle: one squeezed line truncated real names.
_VS = re.compile(r"\s+(?:vs\.?|v\.?|versus)\s+", re.I)


# "PARMA: EXTENDED HIGHLIGHTS", but also "NEW ENGLAND PATRIOTS GAME
# HIGHLIGHTS" — YouTube posts the descriptor with no separator at all, and
# glued to the opponent it inflates the name by half again. The word alone is
# left be: a card titled just "HIGHLIGHTS" would otherwise render empty.
_DESCRIPTOR = re.compile(
    r"\s*[:|]?\s*(?:GAME|EXTENDED|MATCH|FULL|CONDENSED)?\s*HIGHLIGHTS\s*$", re.I)


def _strip_descriptor(name: str) -> str:
    """Drop a trailing "... HIGHLIGHTS" from a competitor's name.

    Redundant on a card already headed "NFL HIGHLIGHTS", and it is the
    difference between a name that fits on one line and one that does not.
    """
    stripped = _DESCRIPTOR.sub("", name).strip()
    return stripped or name.strip()


def _greedy_lines(frame: Frame, text: str, max_width: int, size: int):
    """Break text into the fewest lines that each fit `max_width` at `size`."""
    out, cur = [], ""
    for word in text.split():
        candidate = f"{cur} {word}".strip()
        if cur and frame.text_width(candidate, size) > max_width:
            out.append(cur)
            cur = word
        else:
            cur = candidate
    if cur:
        out.append(cur)
    return out or [""]


def _clip(frame: Frame, text: str, max_width: int, size: int) -> str:
    """Cut text — mid-word if it must — until it fits. The last resort."""
    if frame.text_width(text, size) <= max_width:
        return text
    cut = text
    while cut and frame.text_width(cut + "\u2026", max_width and size) > max_width:
        cut = cut[:-1]
    return (cut + "\u2026") if cut else ""


def _fit_lines(frame: Frame, text: str, max_width: int, size: int,
               min_size: int = 7, max_lines: int = 2):
    """Lines that FIT, wrapping before shrinking. Returns (lines, size).

    text_fit does the opposite: it shrinks to its floor and then overflows,
    silently, because it never clips. That is how a long club name ended up
    8px tall next to a 15px opponent and still ran off both edges.

    Wrapping is tried first at the largest size, so the text stays as big as
    the line budget allows. Only when even `max_lines` will not hold it does
    the size come down, and only when the floor is reached is anything cut.
    """
    for trial in range(size, min_size - 1, -1):
        lines = _greedy_lines(frame, text, max_width, trial)
        if len(lines) <= max_lines and all(
                frame.text_width(ln, trial) <= max_width for ln in lines):
            return lines, trial
    lines = _greedy_lines(frame, text, max_width, min_size)[:max_lines]
    return [_clip(frame, ln, max_width, min_size) for ln in lines], min_size


def _block_height(rows) -> int:
    """Total pixel height of a stack of (lines, size, colour) groups."""
    return sum(round(size * 1.35) for lines, size, _ in rows for _ in lines)


def _matchup_rows(frame: Frame, title: str, width: int, top: int, bottom: int):
    """The name / vs / name stack, sized to fit the band in BOTH directions.

    Width alone is not enough. Wrapping two long clubs gives five rows where
    the layout assumed three, and the stack then ran past the band and drew
    the tail of the second name straight over the QR code. So the size comes
    down until the block fits the height as well — and both names are always
    measured at the SAME size, or the card shows one club at 15px and its
    opponent at 8px.
    """
    names = [_strip_descriptor(part.strip())
             for part in _VS.split(title, maxsplit=1)]
    for trial in range(15, 7, -1):
        fitted = [_fit_lines(frame, name, width, trial, min_size=8, max_lines=2)
                  for name in names]
        size = min(sz for _, sz in fitted)
        lines = [_fit_lines(frame, name, width, size, min_size=8, max_lines=2)[0]
                 for name in names]
        rows = [(lines[0], size, FG), (["vs"], 9, DIM), (lines[1], size, FG)]
        if _block_height(rows) <= bottom - top:
            return rows
    return rows


def _draw_block(frame: Frame, rows, top: int, bottom: int) -> None:
    """Centre a stack of (lines, size, colour) groups in a vertical band.

    Positions come from the actual line count rather than fixed fractions of
    the band: a matchup that wraps to two lines a side is five rows where it
    used to be three, and fractions tuned for three put them on top of one
    another.
    """
    flat = [(line, size, colour)
            for lines, size, colour in rows for line in lines]
    heights = [round(size * 1.35) for _, size, _ in flat]
    y = top + max(0, (bottom - top - sum(heights)) // 2)
    for (line, size, colour), height in zip(flat, heights):
        frame.text(W // 2, y + height // 2, line, size=size, color=colour,
                   anchor="mm")
        y += height


def _wrap(text: str, lines: int = 2):
    """Split into at most `lines` balanced word-lines.

    text_fit shrinks to a floor and then simply overflows, so a long headline
    like "Newcastle upend Spurs; Hull City stun Coventry City" ran off both
    edges of the panel. Wrapping is the only thing that actually fits it.
    """
    words = text.split()
    if not words:
        return [""]
    if len(text) <= 18:            # "ITALIAN GP" belongs on one line
        return [text]
    target = max(1, len(text) // lines)
    out, cur = [], ""
    for word in words:
        candidate = f"{cur} {word}".strip()
        if cur and len(candidate) > target and len(out) < lines - 1:
            out.append(cur)
            cur = word
        else:
            cur = candidate
    out.append(cur)
    return out[:lines]


def _highlight(frame: Frame, card: dict) -> Frame:
    from .qr import qr_image

    # The QR scans reliably at 4px per module and must not shrink, so the space
    # for names is reclaimed from the header instead: a slim 14px bar rather
    # than a 22px one, and no separate subtitle line when there is a matchup.
    # Name the sport: "HIGHLIGHTS" alone left the viewer guessing what they were
    # about to scan.
    label = card.get("sport_label") or "HIGHLIGHTS"
    # Colour by SPORT, not by the displayed label: a tournament name like
    # "US OPEN" would never match the palette.
    colour = LEAGUE_COLOURS.get(card.get("colour_key") or label, (35, 35, 35))
    frame.rect(0, 0, W, 14, colour)
    text = f"{label} HIGHLIGHTS" if label != "HIGHLIGHTS" else label
    frame.text_fit(5, 7, text, max_width=132, size=9, min_size=7,
                   color=FG, anchor="lm")
    frame.text(W - 5, 7, card.get("age", ""), size=9, color=DIM, anchor="rm")

    # 4px per module is the proven-scannable default. Smaller frees space for
    # names but shrinks the target a phone camera has to lock onto.
    img = qr_image(card.get("url", ""), module_px=int(card.get("qr_px") or 4))
    qr_y = H - img.height
    frame.paste(img, (W - img.width) // 2, qr_y)

    title = card.get("title", "")
    parts = _VS.split(title, maxsplit=1)
    top, bottom = 14, qr_y
    width = W - 8

    if len(parts) == 2:
        # "Juventus vs. Parma: Extended Highlights" — the descriptor rides
        # along on the second name and has to come off, or the opponent reads
        # as "PARMA: EXTENDED HIGHLIGHTS".
        _draw_block(frame, _matchup_rows(frame, title, width, top, bottom),
                    top, bottom)
        return frame

    rows, size = _fit_lines(frame, title, width, 16, min_size=8, max_lines=3)
    if len(rows) == 1:
        _draw_block(frame, [(rows, size, FG),
                            ([card.get("subtitle", "")], 12, DIM)], top, bottom)
    else:
        # A wrapped headline takes the whole band; the subtitle would only
        # squeeze it further, and it says less.
        _draw_block(frame, [(rows, size, FG)], top, bottom)
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
    elif card.get("layout") == "tennis":
        _tennis(frame, card)
    else:
        _single(frame, card)
    _channel(frame, card)
    return frame
