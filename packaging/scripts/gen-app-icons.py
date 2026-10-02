#!/usr/bin/env python3
"""Generate the Find+ app icon: light-blue "F+" ligature on a black-to-navy square.

Purpose    : Write desktop/src-tauri/icons/{icon.svg,icon.png,32x32.png,64x64.png,
             128x128.png,128x128@2x.png,icon.ico,icon.icns} and web/icon.svg from one
             description, using the glyph rectangles in gen-tray-icons.py.
Inputs     : none (Pillow; `iconutil` on macOS for the .icns, skipped elsewhere).
Outputs    : the files above. Re-run after changing the glyph or colours.
Constraints: Pure rectangles and a gradient, no fonts, so every run is identical.
"""

from __future__ import annotations

import importlib.util
import pathlib
import shutil
import subprocess
import tempfile

from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parents[2]
ICONS = ROOT / "desktop" / "src-tauri" / "icons"
SIZE, RADIUS, CELL = 1024, 230, 36
BLACK, NAVY, GLYPH = (3, 5, 12), (10, 31, 92), (142, 203, 255)


def _rects() -> tuple[tuple[int, int, int, int], ...]:
    spec = importlib.util.spec_from_file_location(
        "tray", pathlib.Path(__file__).parent / "gen-tray-icons.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.GLYPH_RECTS


def _placed() -> list[tuple[int, int, int, int]]:
    rects = _rects()
    x_min, x_max = min(r[0] for r in rects), max(r[2] for r in rects) + 1
    y_min, y_max = min(r[1] for r in rects), max(r[3] for r in rects) + 1
    ox = (SIZE - (x_max - x_min) * CELL) // 2 - x_min * CELL
    oy = (SIZE - (y_max - y_min) * CELL) // 2 - y_min * CELL
    return [
        (ox + a * CELL, oy + b * CELL, ox + (c + 1) * CELL, oy + (d + 1) * CELL)
        for a, b, c, d in rects
    ]


def svg() -> str:
    body = "\n".join(
        f'  <rect x="{a}" y="{b}" width="{c - a}" height="{d - b}" fill="#8ecbff"/>'
        for a, b, c, d in _placed()
    )
    return (
        f'<svg width="1024" height="1024" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="Find+">\n'
        f'  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="#03050c"/><stop offset="1" stop-color="#0a1f5c"/></linearGradient></defs>\n'
        f'  <rect width="1024" height="1024" rx="{RADIUS}" fill="url(#g)"/>\n{body}\n</svg>\n'
    )


def raster() -> Image.Image:
    grad = Image.new("RGB", (SIZE, SIZE))
    px = grad.load()
    for y in range(SIZE):
        for x in range(SIZE):
            t = (x + y) / (2 * (SIZE - 1))
            px[x, y] = tuple(
                round(BLACK[i] + (NAVY[i] - BLACK[i]) * t) for i in range(3)
            )
    draw = ImageDraw.Draw(grad)
    for box in _placed():
        draw.rectangle((box[0], box[1], box[2] - 1, box[3] - 1), fill=GLYPH)
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), RADIUS, fill=255)
    out = grad.convert("RGBA")
    out.putalpha(mask)
    return out


def main() -> None:
    img = raster()
    (ICONS / "icon.svg").write_text(svg())
    (ROOT / "web" / "icon.svg").write_text(svg())
    for name, px in (
        ("icon.png", 512),
        ("32x32.png", 32),
        ("64x64.png", 64),
        ("128x128.png", 128),
        ("128x128@2x.png", 256),
    ):
        img.resize((px, px), Image.LANCZOS).save(ICONS / name, optimize=True)
    img.save(ICONS / "icon.ico", sizes=[(s, s) for s in (16, 32, 48, 64, 128, 256)])
    if shutil.which("iconutil"):
        with tempfile.TemporaryDirectory() as tmp:
            iset = pathlib.Path(tmp) / "icon.iconset"
            iset.mkdir()
            for base in (16, 32, 128, 256, 512):
                img.resize((base, base), Image.LANCZOS).save(
                    iset / f"icon_{base}x{base}.png"
                )
                img.resize((base * 2, base * 2), Image.LANCZOS).save(
                    iset / f"icon_{base}x{base}@2x.png"
                )
            subprocess.run(
                ["iconutil", "-c", "icns", str(iset), "-o", str(ICONS / "icon.icns")],
                check=True,
            )
    print("app icons written")


if __name__ == "__main__":
    main()
