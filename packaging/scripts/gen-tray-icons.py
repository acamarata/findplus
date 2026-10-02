#!/usr/bin/env python3
"""Generate the Find+ menu-bar tray icon: a simple "F+" glyph.

Purpose    : Produce desktop/src-tauri/icons/tray-fplus{,-dim}.png (@1x 22px
             / @2x 44px), the two states the P2.1 menu-bar redesign uses in
             place of the old five-colour dot set (see gen-dot-pngs.py,
             removed): tray-fplus.png at full opacity for a healthy daemon,
             tray-fplus-dim.png at ~38% alpha for everything else (starting
             up, nothing signed in, stale data, locked, or erroring). Both
             are `iconAsTemplate` images -- black glyph, alpha-only shape --
             so macOS tints them for light/dark menu bars.
Inputs     : none. The glyph is drawn as plain filled rectangles on a pixel
             grid, never a system font: a font's hinting/metrics can differ
             across macOS versions and would break the byte-for-byte
             reproducibility this script (and its test,
             desktop/src-tauri/tests/tray_icon_pngs.rs) both rely on.
Outputs    : 4 PNG files under desktop/src-tauri/icons/. With --check,
             nothing is written: the script compares the freshly rendered
             bytes against the committed files and exits 1 on any mismatch
             (the CI drift gate, same shape as gen-icons.py).
Constraints: No external image library -- the same minimal RGBA PNG writer
             gen-dot-pngs.py used, extended to carry a per-pixel alpha mask
             instead of one flat colour.
"""

from __future__ import annotations

import pathlib
import struct
import sys
import zlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
ICONS_DIR = REPO_ROOT / "desktop" / "src-tauri" / "icons"

#: 38% of 255, inside the "~35-40% alpha" band the owner asked for.
DIM_ALPHA = 97

Grid = list[list[bool]]


#: Glyph rectangles (x0, y0, x1, y1 inclusive) on the 22px grid, shared with gen-app-icons.py.
#: The middle bar of the "F" runs on to the right and becomes the horizontal bar of the "+".
GLYPH_RECTS = (
    (2, 4, 4, 17),  # F stem
    (2, 4, 10, 6),  # F top bar
    (2, 9, 20, 11),  # F middle bar, continuing into the plus
    (15, 5, 17, 15),  # plus, vertical stroke (centred on the bar)
)


def f_plus_mask() -> Grid:
    """A 22x22 boolean grid: True where the glyph is drawn.

    One ligature, not two letters side by side: the F's middle bar carries on
    to the right and is also the "+" crossbar. The old tall "+" next to the
    "F" read as a Christian cross in the menu bar (owner, 2026-10-02).
    """
    grid = [[False] * 22 for _ in range(22)]
    for x0, y0, x1, y1 in GLYPH_RECTS:
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                grid[y][x] = True
    return grid


def scale2x(grid: Grid) -> Grid:
    """Nearest-neighbour 2x upscale: each source pixel becomes a 2x2 block,
    so @2x is always crisp and exactly consistent with @1x."""
    h, w = len(grid), len(grid[0])
    out = [[False] * (w * 2) for _ in range(h * 2)]
    for y in range(h):
        for x in range(w):
            v = grid[y][x]
            out[2 * y][2 * x] = v
            out[2 * y][2 * x + 1] = v
            out[2 * y + 1][2 * x] = v
            out[2 * y + 1][2 * x + 1] = v
    return out


def make_png(mask: Grid, alpha: int) -> bytes:
    """RGBA PNG from a boolean mask: black (0,0,0) where True at `alpha`,
    fully transparent elsewhere -- alpha-only, per macOS's template-image
    convention."""
    h, w = len(mask), len(mask[0])

    def pixel(v: bool) -> bytes:
        return bytes([0, 0, 0, alpha if v else 0])

    raw = b"".join(b"\x00" + b"".join(pixel(v) for v in row) for row in mask)

    def chunk(name: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + name + data
        return c + struct.pack(">I", zlib.crc32(c[4:]) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def render() -> dict[str, bytes]:
    mask_1x = f_plus_mask()
    mask_2x = scale2x(mask_1x)
    return {
        "tray-fplus.png": make_png(mask_1x, 255),
        "tray-fplus@2x.png": make_png(mask_2x, 255),
        "tray-fplus-dim.png": make_png(mask_1x, DIM_ALPHA),
        "tray-fplus-dim@2x.png": make_png(mask_2x, DIM_ALPHA),
    }


def main(check: bool) -> int:
    outputs = render()
    if check:
        stale = [
            name
            for name, data in outputs.items()
            if not (ICONS_DIR / name).exists()
            or (ICONS_DIR / name).read_bytes() != data
        ]
        if stale:
            print(
                "tray icon PNGs are stale: run packaging/scripts/gen-tray-icons.py\n"
                + "\n".join(f"  {name}" for name in stale),
                file=sys.stderr,
            )
            return 1
        return 0
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    for name, data in outputs.items():
        (ICONS_DIR / name).write_bytes(data)
    print(f"wrote {len(outputs)} tray icon PNGs to {ICONS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main(check="--check" in sys.argv[1:]))
