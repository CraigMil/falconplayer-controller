"""The title card that lands in the intro's wake."""

import io

import pytest
from PIL import Image

from fpp.canvas import HEIGHT, WIDTH
from fpp.displays.nfl import render_week_card


def test_it_renders_a_panel_sized_frame():
    img = Image.open(io.BytesIO(render_week_card("WEEK 3").to_image_bytes()))
    assert img.size == (WIDTH, HEIGHT)


@pytest.mark.parametrize("label", ["WEEK 3", "WEEK 18", "PRE WK 1",
                                   "WILD CARD", "CONF CHAMP", "SUPER BOWL", "NFL"])
def test_every_label_fits_inside_the_panel(label):
    """"CONF CHAMP" is 10 characters and must not run off the edge."""
    frame = render_week_card(label)
    assert frame.text_width(label, size=_size_used(frame, label)) <= WIDTH - 8


def _size_used(frame, label):
    """The largest size the card would have chosen for this label."""
    from fpp.displays.nfl import WEEK_CARD_SIZES
    for size in WEEK_CARD_SIZES:
        if frame.text_width(label, size) <= WIDTH - 8:
            return size
    return WEEK_CARD_SIZES[-1]


def test_the_card_is_mostly_dark_so_it_reads_as_a_title_not_a_flash():
    """It follows a whiteout. A bright card here would extend the blowout."""
    img = Image.open(io.BytesIO(render_week_card("WEEK 3").to_image_bytes()))
    px = list(img.convert("L").getdata())
    lit = sum(1 for v in px if v > 40) / float(len(px))
    assert lit < 0.25


def test_it_draws_something():
    blank = Image.open(io.BytesIO(render_week_card("").to_image_bytes()))
    card = Image.open(io.BytesIO(render_week_card("WEEK 3").to_image_bytes()))
    assert list(blank.getdata()) != list(card.getdata())
