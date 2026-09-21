#!/usr/bin/env python3
"""Seed a demo database, drive the dashboard with Playwright, save screenshots.

Real (never mocked) README/wiki/app-store screenshots at 1280x800 and 375x812,
light and dark: 24 PNGs (6 shots x 2 schemes x 2 widths) in
.github/docs/screenshots/, each <=400 KB. Isolated via
FINDPLUS_DATABASE_PATH/FINDPLUS_STATE_DIR (the bare names are silently ignored:
env_prefix is "FINDPLUS_"), never the real ~/.findplus. `serve` takes no
database-path flag; `db upgrade` takes none. The demo rows live in
screenshots_seed.py.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from PIL import Image
from playwright.async_api import async_playwright
from screenshots_seed import DEMO_PIN, seed_demo_db

REPO_ROOT = Path(__file__).resolve().parents[2]
# (width, height) per pass. 1280 is the desktop wiki/README width; 375 is the
# phone breakpoint specs/layout-i18n-a11y.md pins. 1280-width files keep the
# unsuffixed name every existing markdown link already points at.
VIEWPORTS = ((1280, 800), (375, 812))
PHONE_MAX_WIDTH = 599  # web/responsive.css's phone tier


def find_free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def redirect_env(root: Path) -> dict:
    """Point later subprocesses AND this process's own findplus imports at a
    throwaway database/state dir. Never the real ~/.findplus."""
    os.environ.update(
        FINDPLUS_DATABASE_PATH=str(root / "demo.sqlite"),
        FINDPLUS_STATE_DIR=str(root / "state"),
    )
    return dict(os.environ)


def start_daemon(port: int, env: dict) -> subprocess.Popen:
    argv = ["-m", "findplus.cli", "serve", "--no-poller", "--host", "127.0.0.1"]
    proc = subprocess.Popen(
        [sys.executable, *argv, "--port", str(port)],
        env=env,
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(40):
        try:
            httpx.get(f"{base}/api/health", timeout=1)
            return proc
        except httpx.HTTPError:
            time.sleep(0.5)
    stop_daemon(proc)  # main()'s finally only covers a returned process
    raise RuntimeError("screenshots.py: findplus serve never became healthy")


def stop_daemon(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def save_png(path: Path, max_kb: int = 400) -> None:
    """optimize -> compress_level=9 -> 256-color palette (still PNG): a real
    Leaflet/OSM map view exceeds 400 KB losslessly at 1280x800."""
    img = Image.open(io.BytesIO(path.read_bytes()))
    img.save(path, "PNG", optimize=True)
    if path.stat().st_size > max_kb * 1024:
        img.save(path, "PNG", optimize=True, compress_level=9)
    if path.stat().st_size > max_kb * 1024:
        img.convert("RGB").quantize(colors=256).save(path, "PNG", optimize=True)


def _tab(width: int, tab: str) -> str:
    """Below the phone breakpoint the `.fp-tabs` row is display:none and
    components/tabbar.js's fixed bottom bar owns tab switching, under its own
    `data-tabbar-tab` attribute (web/responsive.css § phone tier)."""
    if width <= PHONE_MAX_WIDTH:
        return f'button[data-tabbar-tab="{tab}"]'
    return f'.fp-tab[data-tab="{tab}"]'


async def _shoot(page, out_dir: Path, name: str, scheme: str, width: int) -> None:
    suffix = "" if width == 1280 else f"-{width}"
    path = out_dir / f"{name}-{scheme}{suffix}.png"
    await page.screenshot(path=path)
    save_png(path)


async def _unlock(page, base_url: str, scheme: str) -> None:
    """Unlock through the real form, set the server-side theme, then reload.

    The reload is what makes the theme write take visual effect, because
    loadSettings() re-runs. The verb is PATCH, not PUT: D-P2-11 replaced the
    collection route's write verb and a PUT here answers 405.
    """
    await page.goto(base_url, wait_until="networkidle")
    await page.fill("#lock-pin", DEMO_PIN)
    await page.click("#lock-submit")
    await page.wait_for_selector("#app-shell:not(.hidden)")
    await page.request.patch(
        base_url + "/api/settings",
        data=json.dumps({"theme": scheme}),
        headers={"Content-Type": "application/json"},
    )
    await page.reload(wait_until="networkidle")
    await page.wait_for_selector("#app-shell:not(.hidden)")


async def _one_pass(page, out_dir: Path, scheme: str, width: int) -> None:
    """The six shots, in the order the README and wiki present them."""
    await _shoot(page, out_dir, "dashboard", scheme, width)

    await page.click("#btn-today")
    await page.wait_for_function("document.querySelectorAll('#tracks > *').length > 0")
    await _shoot(page, out_dir, "timeline", scheme, width)

    await page.click(_tab(width, "places"))
    await page.click("#fp-add-place-btn")
    # activateCrosshairMode() waits for a Leaflet map click before opening the
    # dialog. A raw mouse click, not page.click("#map"): at phone width the
    # seeded place's 200 m circle covers the whole map pane, and Playwright's
    # actionability check refuses a click it sees an SVG path intercept.
    # Leaflet propagates a path click up to the map, so the handler still runs.
    map_el = page.locator("#map")
    await map_el.scroll_into_view_if_needed()
    box = await map_el.bounding_box()
    await page.mouse.click(box["x"] + 12, box["y"] + 12)
    await page.wait_for_selector("#fp-place-dialog[open]")
    await _shoot(page, out_dir, "places-dialog", scheme, width)
    await page.keyboard.press("Escape")

    await page.click(_tab(width, "groups"))
    await page.select_option("#fp-group-select", label="Family")
    await page.wait_for_selector("#fp-presence-panel .fp-verdict")
    await _shoot(page, out_dir, "group-presence", scheme, width)

    await page.click(_tab(width, "alerts"))
    await page.wait_for_selector("#fp-telegram-section")
    await _shoot(page, out_dir, "alerts-settings", scheme, width)


async def take_screenshots(base_url: str, out_dir: Path) -> None:
    for width, height in VIEWPORTS:
        for scheme in ("light", "dark"):
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                ctx = await browser.new_context(
                    viewport={"width": width, "height": height}, color_scheme=scheme
                )
                page = await ctx.new_page()
                await _unlock(page, base_url, scheme)
                await _one_pass(page, out_dir, scheme, width)

                await page.evaluate("fetch('/api/lock/lock', {method:'POST'})")
                await page.reload(wait_until="networkidle")
                await page.wait_for_selector("#lock-screen:not(.hidden)")
                await _shoot(page, out_dir, "lock-screen", scheme, width)
                await browser.close()


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    env = redirect_env(tmp)
    try:
        subprocess.run(
            [sys.executable, "-m", "findplus.cli", "db", "upgrade"],
            check=True,
            env=env,
            cwd=REPO_ROOT,
        )
        seed_demo_db(tmp)
        port = find_free_port()
        proc = start_daemon(port, env)
        out = REPO_ROOT / ".github" / "docs" / "screenshots"
        out.mkdir(parents=True, exist_ok=True)
        try:
            asyncio.run(take_screenshots(f"http://127.0.0.1:{port}", out))
        finally:
            stop_daemon(proc)
        print(f"Saved {len(list(out.glob('*.png')))} screenshots to {out}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
