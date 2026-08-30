"""192x192 cards. The bottom strip is always the channel — that is the question
this display exists to answer.
"""

from __future__ import annotations

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
    frame.rect(0, 0, W, STRIP_H, LEAGUE_COLOURS.get(label, (40, 40, 40)))
    frame.text(6, STRIP_H // 2, label, size=13, color=FG, anchor="lm")
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


def _highlight(frame: Frame, card: dict) -> Frame:
    from .qr import qr_image

    frame.rect(0, 0, W, 22, (35, 35, 35))
    frame.text(6, 11, "HIGHLIGHTS", size=12, color=FG, anchor="lm")
    frame.text(W - 6, 11, card.get("age", ""), size=11, color=DIM, anchor="rm")
    frame.text_fit(W // 2, 33, card.get("title", ""), max_width=W - 12,
                   size=14, color=FG, anchor="mm")
    frame.text_fit(W // 2, 49, card.get("subtitle", ""), max_width=W - 12,
                   size=11, color=DIM, anchor="mm")
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
