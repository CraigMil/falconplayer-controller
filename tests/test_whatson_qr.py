"""QR sizing. The panel is 192px, so the geometry has no slack."""

from fpp.displays.whatson.qr import qr_image

URL = "https://youtu.be/dQw4w9WgXcQ"


def test_a_youtube_url_fits_the_panel_with_room_for_a_title():
    img = qr_image(URL, module_px=4)
    assert img.width == img.height
    assert img.width <= 160, "QR must leave room for the title strip"


def test_it_is_dark_on_white_not_the_panel_default():
    img = qr_image(URL)
    assert img.getpixel((0, 0)) == (255, 255, 255), "quiet zone must be white"


def test_a_long_url_still_fits_the_canvas():
    long_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1234567890"
    assert qr_image(long_url, module_px=3).width <= 192
