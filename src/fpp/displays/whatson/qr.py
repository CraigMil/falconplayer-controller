"""QR codes sized for a 192x192 LED panel.

Rendered DARK ON WHITE, which is backwards for this panel but necessary: phone
cameras meter badly against a bright emissive matrix, and an inverted QR is
substantially harder for them to lock onto.
"""

from __future__ import annotations

import io

import segno
from PIL import Image


def qr_image(url: str, module_px: int = 4, border: int = 4) -> Image.Image:
    """A scannable QR for `url`, at `module_px` LEDs per module."""
    code = segno.make(url, error="l")
    buf = io.BytesIO()
    code.save(buf, kind="png", scale=module_px, border=border,
              dark="#000000", light="#ffffff")
    buf.seek(0)
    return Image.open(buf).convert("RGB")
