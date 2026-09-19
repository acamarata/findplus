#!/usr/bin/env python3
"""Generate the tray dot-state PNGs and the monochrome template icon.

Purpose    : Produce desktop/src-tauri/icons/dot-{green,amber,red,grey}.png
             (@1x 12px / @2x 24px) and tray-template.png (@1x 22px / @2x
             44px, white, iconAsTemplate=true so macOS auto-inverts it for
             dark/light menu bars). No external image library required —
             this is the same minimal RGBA PNG writer used for
             desktop/src-tauri/icons/dmg-background.png (T7).
Inputs     : none.
Outputs    : 10 PNG files under desktop/src-tauri/icons/.
Constraints: Generated 1.0 artwork; a designed icon set is a P2 item.
"""

from __future__ import annotations

import pathlib
import struct
import zlib


def make_png(w: int, h: int, r: int, g: int, b: int, a: int = 255) -> bytes:
    raw = b"".join(b"\x00" + bytes([r, g, b, a]) * w for _ in range(h))

    def chunk(name: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + name + data
        return c + struct.pack(">I", zlib.crc32(c[4:]) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    base = pathlib.Path("desktop/src-tauri/icons")
    base.mkdir(parents=True, exist_ok=True)

    dots = {
        "green": (0x34, 0xC7, 0x59),
        "amber": (0xFF, 0x9F, 0x0A),
        "red": (0xFF, 0x3B, 0x30),
        "grey": (0x8E, 0x8E, 0x93),
    }
    for name, (r, g, b) in dots.items():
        (base / f"dot-{name}.png").write_bytes(make_png(12, 12, r, g, b))
        (base / f"dot-{name}@2x.png").write_bytes(make_png(24, 24, r, g, b))

    (base / "tray-template.png").write_bytes(make_png(22, 22, 0xFF, 0xFF, 0xFF))
    (base / "tray-template@2x.png").write_bytes(make_png(44, 44, 0xFF, 0xFF, 0xFF))

    print("dot PNGs and tray-template icons written")


if __name__ == "__main__":
    main()
