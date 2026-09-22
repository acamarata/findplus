"""Shared PNG builders for the /api/icons/custom route tests, split out of
test_routes_icons.py (E13 stage 2, size cap).

Purpose    : URL and the hand-built PNG/APNG byte builders both
             test_routes_icons.py and test_routes_icons_delete.py need.
             Each file keeps its own small `client` fixture (importing a
             fixture used as a same-named test parameter trips ruff's F811).
Inputs     : n/a.
Outputs    : Valid/invalid PNG byte strings for upload tests.
Constraints: test-only; never imported by cli/src.
"""

from __future__ import annotations

import struct
import zlib

from findplus.config import get_settings

URL = "/api/icons/custom"


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data))
    )


def _make_png(width: int, height: int) -> bytes:
    """A real, valid grayscale PNG at the given dimensions."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00" * width for _ in range(height))
    idat = zlib.compress(raw)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


def _make_apng(size: int = 32) -> bytes:
    """A structurally valid PNG whose `acTL` chunk marks it animated."""
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 0, 0, 0, 0)
    actl = struct.pack(">II", 1, 0)  # num_frames=1, num_plays=0 (loop forever)
    raw = b"".join(b"\x00" + b"\x00" * size for _ in range(size))
    idat = zlib.compress(raw)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"acTL", actl)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


def _icons_on_disk() -> list:
    return list(get_settings().icons_dir.glob("*.png"))
