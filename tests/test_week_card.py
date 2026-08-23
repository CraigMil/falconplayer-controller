"""The title card that lands in the intro's wake."""

import io

import pytest
from PIL import Image

from fpp.canvas import HEIGHT, WIDTH
from fpp.displays.nfl import render_week_card


def test_it_renders_a_panel_sized_frame():
    img = Image.open(io.BytesIO(render_week_card("WEEK 3").to_image_bytes()))
    assert img.size == (WIDTH, HEIGHT)


@pytest.mark.parametrize("label", ["WEEK 3", "WEEK 18", "PRE WK 3", "PRESEASON",
                                   "WILD CARD", "DIVISIONAL", "CONF CHAMP",
                                   "SUPER BOWL", "PLAYOFFS", "NFL"])
def test_every_label_fits_inside_the_panel(label):
    """"CONF CHAMP" is 10 characters and must not run off the edge.

    Measures the actual rendered ink, not a re-derivation of the size
    ladder — a hardcoded or reversed size would push the bbox to the
    panel edge and fail this.
    """
    bbox = _ink_bbox(label)
    assert bbox is not None
    left, _, right, _ = bbox
    assert left >= 2
    assert right <= WIDTH - 2


def _ink_bbox(label):
    """Bounding box of everything meaningfully lit on the rendered card."""
    img = Image.open(io.BytesIO(render_week_card(label).to_image_bytes(fmt="PNG"))).convert("L")
    return img.point(lambda v: 255 if v > 40 else 0).getbbox()


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
