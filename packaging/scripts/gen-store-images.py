#!/usr/bin/env python3
"""Generate the Chrome Web Store images for the Find+ helper.

Deterministic art (no browser): the 128x128 store icon and the 440x280 promo
tile, both an "F+" glyph on a solid Find+ blue, from the same glyph geometry as
gen-tray-icons.py. With --check nothing is written; it compares the committed
files and exits 1 on drift (the same gate shape as gen-tray-icons.py).

Screenshots (Playwright, headless bundled Chromium, no real Chrome): with
--screenshots it starts the daemon on a temp state dir, seeds it, and captures
1280x800 shots of the Find+ sign-in card and the localhost success page. Those
are not part of --check (they are captures, not reproducible byte-for-byte).
"""

from __future__ import annotations

import importlib.util
import pathlib
import struct
import sys
import zlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
IMAGES_DIR = REPO_ROOT / ".github" / "docs" / "chrome-web-store" / "images"
BG = (26, 115, 232)  # Find+ blue
GLYPH = (255, 255, 255)


def _f_plus_mask():
    spec = importlib.util.spec_from_file_location(
        "_gen_tray_icons", pathlib.Path(__file__).with_name("gen-tray-icons.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.f_plus_mask()


def _rgba_png(pixels: list[list[tuple[int, int, int, int]]]) -> bytes:
    height, width = len(pixels), len(pixels[0])
    raw = b"".join(b"\x00" + b"".join(bytes(px) for px in row) for row in pixels)

    def chunk(name: bytes, data: bytes) -> bytes:
        body = struct.pack(">I", len(data)) + name + data
        return body + struct.pack(">I", zlib.crc32(body[4:]) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _render(width: int, height: int) -> bytes:
    """A centred F+ glyph on a solid background, scaled to fit with a margin."""
    mask = _f_plus_mask()
    m = len(mask)  # 22
    scale = int(min(width, height) * 0.72) // m
    glyph_w, glyph_h = m * scale, m * scale
    ox, oy = (width - glyph_w) // 2, (height - glyph_h) // 2
    canvas = [[(*BG, 255) for _ in range(width)] for _ in range(height)]
    for gy in range(m):
        for gx in range(m):
            if not mask[gy][gx]:
                continue
            for dy in range(scale):
                for dx in range(scale):
                    canvas[oy + gy * scale + dy][ox + gx * scale + dx] = (*GLYPH, 255)
    return _rgba_png(canvas)


def render() -> dict[str, bytes]:
    return {"icon-128.png": _render(128, 128), "promo-440x280.png": _render(440, 280)}


def capture_screenshots(base_url: str, out_dir: pathlib.Path) -> list[pathlib.Path]:
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    shots = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport={"width": 1280, "height": 800}).new_page()
        page.goto(f"{base_url}/#dashboard")
        page.click("#btn-settings")
        page.wait_for_selector("#fp-auth-google-card", timeout=15000)
        shots.append(out_dir / "screenshot-signin-1280x800.png")
        page.screenshot(path=str(shots[-1]))
        page.goto(f"{base_url}/auth/google/success")
        page.wait_for_selector("main.fp-helper", timeout=15000)
        shots.append(out_dir / "screenshot-success-1280x800.png")
        page.screenshot(path=str(shots[-1]))
        browser.close()
    return shots


def main(argv: list[str]) -> int:
    outputs = render()
    if "--check" in argv:
        stale = [
            n
            for n, d in outputs.items()
            if not (IMAGES_DIR / n).exists() or (IMAGES_DIR / n).read_bytes() != d
        ]
        if stale:
            print(
                "store images are stale: run packaging/scripts/gen-store-images.py",
                file=sys.stderr,
            )
            print("\n".join(f"  {n}" for n in stale), file=sys.stderr)
            return 1
        return 0
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    for name, data in outputs.items():
        (IMAGES_DIR / name).write_bytes(data)
    print(f"wrote {len(outputs)} store images to {IMAGES_DIR}")
    if "--screenshots" in argv:
        base = argv[argv.index("--screenshots") + 1]
        for shot in capture_screenshots(base, IMAGES_DIR):
            print(f"captured {shot}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
