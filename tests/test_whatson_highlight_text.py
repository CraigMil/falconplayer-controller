"""Highlight-card text: wrap before shrinking, and never run off the panel.

`text_fit` shrinks to a floor and then OVERFLOWS — it does not clip. The
matchup branch drew each competitor as one such line, so a long club name was
squeezed to 8px against a 15px opponent, and a longer one ran off both edges.
"""

import pytest

from fpp.canvas import Frame
from fpp.displays.whatson import cards

FG_ = (255, 255, 255)

W = cards.W

# Real titles, from the live feeds.
LONG_MATCHUP = "PITTSBURGH STEELERS VS. NEW ENGLAND PATRIOTS GAME HIGHLIGHTS"
SHORT_MATCHUP = "PEYTON STEARNS VS. IVA JOVIC"
COLON_MATCHUP = "JUVENTUS VS. PARMA: EXTENDED HIGHLIGHTS"
HEADLINE = "EVERY PREMIER LEAGUE GOAL FROM MATCHWEEK 5 (2026-27)"


# ------------------------------------------------------------------ wrapping


def test_short_text_stays_on_one_line_at_full_size():
    frame = Frame()
    lines, size = cards._fit_lines(frame, "IVA JOVIC", max_width=184, size=15)
    assert lines == ["IVA JOVIC"]
    assert size == 15


def test_text_that_does_not_fit_wraps_before_it_shrinks():
    """The bug: it shrank to the floor and overflowed instead of wrapping."""
    frame = Frame()
    lines, size = cards._fit_lines(frame, "NEW ENGLAND PATRIOTS",
                                   max_width=184, size=15, max_lines=2)
    assert len(lines) == 2
    assert size > 8, "wrapping should keep the text large, not shrink it"


def test_every_wrapped_line_actually_fits_the_width():
    frame = Frame()
    lines, size = cards._fit_lines(frame, LONG_MATCHUP, max_width=184,
                                   size=15, max_lines=3)
    for line in lines:
        assert frame.text_width(line, size) <= 184


def test_wrapping_never_exceeds_the_line_budget():
    frame = Frame()
    lines, _ = cards._fit_lines(frame, LONG_MATCHUP * 3, max_width=184,
                                size=15, max_lines=2)
    assert len(lines) <= 2


def test_text_too_long_even_at_the_floor_is_truncated_not_overflowed():
    """The invariant is that ink never crosses the panel edge. Cut it."""
    frame = Frame()
    lines, size = cards._fit_lines(frame, "SUPERCALIFRAGILISTIC " * 8,
                                   max_width=184, size=15, max_lines=2)
    assert len(lines) <= 2
    for line in lines:
        assert frame.text_width(line, size) <= 184


def test_a_single_word_wider_than_the_panel_is_cut():
    frame = Frame()
    lines, size = cards._fit_lines(frame, "A" * 60, max_width=184, size=15,
                                   max_lines=1)
    assert frame.text_width(lines[0], size) <= 184


# ------------------------------------------------------------------ descriptor


@pytest.mark.parametrize("raw,want", [
    ("NEW ENGLAND PATRIOTS GAME HIGHLIGHTS", "NEW ENGLAND PATRIOTS"),
    ("PARMA: EXTENDED HIGHLIGHTS", "PARMA"),
    ("ARSENAL HIGHLIGHTS", "ARSENAL"),
    ("IVA JOVIC", "IVA JOVIC"),
    # Not a descriptor — a real name that merely ends in a matching word.
    ("HIGHLIGHTS", "HIGHLIGHTS"),
])
def test_the_trailing_descriptor_comes_off_the_opponent(raw, want):
    assert cards._strip_descriptor(raw) == want


# ------------------------------------------------------------------ rendered


def _card(title: str, qr_px: int = 3) -> dict:
    return {"kind": "highlight", "title": title, "sport_label": "NFL",
            "colour_key": "NFL", "url": "https://youtu.be/abc", "age": "1h",
            "subtitle": "", "qr_px": qr_px}


def _ink_columns(img, top: int, bottom: int) -> tuple[int, int]:
    """Leftmost and rightmost inked column in a horizontal band."""
    band = img.convert("L").crop((0, top, W, bottom))
    bbox = band.getbbox()
    return (bbox[0], bbox[2]) if bbox else (W, 0)


@pytest.mark.parametrize("title", [
    LONG_MATCHUP, SHORT_MATCHUP, COLON_MATCHUP, HEADLINE,
    "WOLVERHAMPTON WANDERERS VS. BRIGHTON AND HOVE ALBION: EXTENDED HIGHLIGHTS",
    "BOROUGHMUIR THISTLE VS. STENHOUSEMUIR ATHLETIC FOOTBALL CLUB",
    "A" * 40,
    "SUPERCALIFRAGILISTICEXPIALIDOCIOUS VS. ANTIDISESTABLISHMENTARIANISM",
])
def test_no_card_draws_ink_to_the_panel_edge(title):
    """Overflow shows up as ink in column 0 or 191."""
    img = cards.render(_card(title))._img
    left, right = _ink_columns(img, 15, 104)
    assert left >= 2, f"ink runs off the left edge: {title}"
    assert right <= W - 2, f"ink runs off the right edge: {title}"


def _ink_runs(img, top: int, bottom: int):
    """Heights of each contiguous run of inked rows — one run per text line."""
    band = img.convert("L").crop((0, top, W, bottom))
    inked = [band.crop((0, y, W, y + 1)).getbbox() is not None
             for y in range(band.height)]
    runs, count = [], 0
    for on in inked + [False]:
        if on:
            count += 1
        elif count:
            runs.append(count)
            count = 0
    return runs


def test_the_two_competitors_are_rendered_at_the_same_size():
    """A 15px name above an 8px name is the bug as the eye sees it.

    Measured by the HEIGHT of each line's ink, not its width: the squeezed
    name spanned the full width precisely because it had been shrunk, so a
    width comparison cannot see the defect. The "vs" row is the shortest run
    by design and is excluded.
    """
    runs = sorted(_ink_runs(cards.render(_card(LONG_MATCHUP))._img, 15, 104))
    assert len(runs) >= 3, f"expected name/vs/name rows, got {runs}"
    names = runs[1:]            # drop the "vs", the smallest run
    assert min(names) > 0.6 * max(names), (
        f"one competitor is rendered much smaller than the other: {runs}")


# ------------------------------------------------------------------ vertical


LONG_BOTH = ("WOLVERHAMPTON WANDERERS VS. BRIGHTON AND HOVE ALBION: "
             "EXTENDED HIGHLIGHTS")


def test_the_block_height_is_reported_so_it_can_be_made_to_fit():
    frame = Frame()
    rows = [(["ONE", "TWO"], 14, FG_), (["vs"], 9, FG_), (["THREE"], 14, FG_)]
    assert cards._block_height(rows) == sum(round(s * 1.35) for lines, s, _
                                            in rows for _ in lines)


def test_two_long_names_do_not_overflow_the_band_into_the_qr():
    """Regression: "ALBION" was drawn on top of the QR code.

    Wrapping both names gives five rows where the layout assumed three, and
    nothing checked the stack still fitted between the header and the QR.
    """
    frame = Frame()
    top, bottom = 14, 105
    rows = cards._matchup_rows(frame, LONG_BOTH, W - 8, top, bottom)
    assert cards._block_height(rows) <= bottom - top
