"""DDP (Distributed Display Protocol) sender for pushing raw RGB frames to FPP."""

from __future__ import annotations

import socket
import struct

WIDTH = 192
HEIGHT = 192
PORT = 4048
CHUNK_SIZE = 1440  # 480 pixels × 3 bytes — standard DDP packet payload

# flags byte: version=1 (0x40) | push (0x02) | notlast (0x01)
_VER_PUSH    = 0x42  # last packet
_VER_PUSH_NL = 0x43  # more packets follow
_TYPE_RGB    = 0x03
_ID_DEFAULT  = 0x01


def send_frame(host: str, rgb_bytes: bytes, port: int = PORT) -> None:
    """Send a 192×192 RGB frame to FPP via DDP over UDP."""
    expected = WIDTH * HEIGHT * 3
    if len(rgb_bytes) != expected:
        raise ValueError(f"Frame must be {expected} bytes, got {len(rgb_bytes)}")

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        offset = 0
        total = len(rgb_bytes)
        while offset < total:
            chunk = rgb_bytes[offset : offset + CHUNK_SIZE]
            end = offset + len(chunk)
            flags = _VER_PUSH if end >= total else _VER_PUSH_NL
            header = struct.pack(">BBBBIH", flags, 0, _TYPE_RGB, _ID_DEFAULT, offset, len(chunk))
            sock.sendto(header + chunk, (host, port))
            offset = end
