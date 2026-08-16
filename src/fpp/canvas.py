"""192×192 RGB frame canvas backed by Pillow."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH = 192
HEIGHT = 192

_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
]


@lru_cache(maxsize=32)
def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_PATHS:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


Color = tuple[int, int, int]


def contrast(r: int, g: int, b: int) -> Color:
    """Return black or white for readable contrast against the given RGB background."""
    brightness = 0.299 * r + 0.587 * g + 0.114 * b
    return (0, 0, 0) if brightness > 140 else (255, 255, 255)


def dim(color: Color, factor: float = 0.65, floor: int = 18) -> Color:
    """Darken a color by factor, with a minimum channel value."""
    return tuple(max(floor, int(c * factor)) for c in color)  # type: ignore[return-value]


class Frame:
    """A 192×192 RGB drawing canvas."""

    def __init__(self, bg: Color = (0, 0, 0)):
        self._img = Image.new("RGB", (WIDTH, HEIGHT), bg)
        self._draw = ImageDraw.Draw(self._img)

    def rect(self, x: int, y: int, w: int, h: int, color: Color) -> None:
        self._draw.rectangle([(x, y), (x + w - 1, y + h - 1)], fill=color)

    def line(self, x0: int, y0: int, x1: int, y1: int, color: Color = (60, 60, 60), width: int = 1) -> None:
        self._draw.line([(x0, y0), (x1, y1)], fill=color, width=width)

    def polygon(self, points: list[tuple[int, int]], color: Color, outline: Color | None = None) -> None:
        self._draw.polygon(points, fill=color, outline=outline)

    def ellipse(self, x: int, y: int, w: int, h: int, color: Color, outline: Color | None = None) -> None:
        self._draw.ellipse([(x, y), (x + w - 1, y + h - 1)], fill=color, outline=outline)

    def vgradient(self, x: int, y: int, w: int, h: int, top: Color, bottom: Color) -> None:
        """Fill a rectangle with a vertical linear gradient from top to bottom."""
        for i in range(h):
            t = i / max(h - 1, 1)
            row = tuple(int(top[c] + (bottom[c] - top[c]) * t) for c in range(3))
            self._draw.line([(x, y + i), (x + w - 1, y + i)], fill=row)

    def text(self, x: int, y: int, msg: str, size: int = 16, color: Color = (255, 255, 255), anchor: str = "lt") -> None:
        self._draw.text((x, y), msg, fill=color, font=_font(size), anchor=anchor)

    def text_width(self, msg: str, size: int) -> int:
        bbox = self._draw.textbbox((0, 0), msg, font=_font(size))
        return bbox[2] - bbox[0]

    def text_fit(
        self, x: int, y: int, msg: str, max_width: int,
        size: int = 16, min_size: int = 7, color: Color = (255, 255, 255), anchor: str = "mm",
    ) -> None:
        """Draw text, shrinking the font size until it fits within max_width."""
        s = size
        while s > min_size and self.text_width(msg, s) > max_width:
            s -= 1
        self.text(x, y, msg, size=s, color=color, anchor=anchor)

    def paste(self, img: "Image.Image", x: int, y: int, opacity: float = 1.0) -> None:
        """Composite an RGBA image onto the frame at (x, y) with given opacity."""
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        if opacity < 1.0:
            r, g, b, a = img.split()
            a = a.point(lambda p: int(p * opacity))
            img = Image.merge("RGBA", (r, g, b, a))
        self._img.paste(img, (x, y), mask=img.split()[3])

    def to_bytes(self) -> bytes:
        return self._img.tobytes()

    def to_image_bytes(self, fmt: str = "JPEG", quality: int = 92) -> bytes:
        import io
        buf = io.BytesIO()
        self._img.save(buf, format=fmt, quality=quality)
        return buf.getvalue()
