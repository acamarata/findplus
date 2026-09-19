#!/usr/bin/env python3
"""Seed a demo database, drive the dashboard with Playwright, save screenshots.

Real (never mocked) README/wiki/app-store screenshots at 1440x900, light and
dark: 12 PNGs (6 shots x 2 schemes) in .github/docs/screenshots/, each
<=400 KB. Isolated via FINDPLUS_DATABASE_PATH/FINDPLUS_STATE_DIR (the bare
names are silently ignored: env_prefix is "FINDPLUS_") — never the real
~/.findplus. `serve` takes no database-path flag; `db upgrade` takes none.
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
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from PIL import Image
from playwright.async_api import async_playwright
from sqlalchemy import create_engine, text

DEMO_PIN = "8642"
REPO_ROOT = Path(__file__).resolve().parents[2]
HOME_LAT, HOME_LON = 40.712800, -74.006000
DEMO_DEVICES = (("dev-google-1", "Moto Tag (car)"), ("dev-apple-1", "AirTag (keys)"))


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


def _obs(device_id: str, name: str, lat: float, lon: float, minutes_ago: int):
    from findplus.findhub.types import RawObservation

    return RawObservation(
        device_id=device_id,
        device_name=name,
        latitude_e7=round(lat * 1e7),
        longitude_e7=round(lon * 1e7),
        observed_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
        accuracy_meters=15.0,
        source="crowdsourced",
        is_own_report=False,
    )


def _seed_devices_and_place() -> int:
    """Devices, then the place: ingest.py's geofence hook only evaluates
    places that already exist when the fixes are ingested."""
    from findplus.db.session import session_scope
    from findplus.ingest import upsert_device
    from findplus.places.repo import create_place
    from findplus.state import track_devices

    with session_scope() as session:
        for device_id, name in DEMO_DEVICES:
            upsert_device(session, device_id, name)
        track_devices(session, [d for d, _ in DEMO_DEVICES], exclusive=True)

    with session_scope() as session:
        place = create_place(
            session,
            name="Home",
            latitude_e7=round(HOME_LAT * 1e7),
            longitude_e7=round(HOME_LON * 1e7),
            radius_meters=200,
            color="#3b82f6",
            enter_confirmations=1,
            exit_confirmations=2,
        )
        return place.id


def _seed_fixes() -> None:
    from findplus.db.session import session_scope
    from findplus.ingest import ingest_observations

    ages = (40, 20, 0)
    google, apple = DEMO_DEVICES
    fixes = [
        _obs(google[0], google[1], HOME_LAT + i * 0.00003, HOME_LON, age)
        for i, age in enumerate(ages)
    ] + [
        _obs(apple[0], apple[1], HOME_LAT, HOME_LON + i * 0.00003, age)
        for i, age in enumerate(ages)
    ]
    with session_scope() as session:
        ingest_observations(session, fixes, fetched_at=datetime.now(UTC))


def _seed_group_and_lock() -> None:
    from findplus.appsettings import save_pin, set_lock_enabled
    from findplus.db.session import session_scope
    from findplus.groups.repo import create_group
    from findplus.security import hash_pin

    with session_scope() as session:
        create_group(
            session,
            name="Family",
            color="#8b5cf6",
            quorum="majority",
            cluster_radius_meters=150,
            stale_after_minutes=90,
            member_ids=[d for d, _ in DEMO_DEVICES],
        )
    with session_scope() as session:
        salt, digest = hash_pin(DEMO_PIN)
        save_pin(session, salt, digest)
        set_lock_enabled(session, True)


def seed_demo_db(root: Path) -> None:
    place_id = _seed_devices_and_place()
    _seed_fixes()
    _seed_group_and_lock()
    _seed_alert_rule(root, place_id)

    engine = create_engine(f"sqlite+pysqlite:///{root / 'demo.sqlite'}")
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM devices")).scalar()
    assert count and count > 0, "seed_demo_db: devices table empty after seeding"


def _seed_alert_rule(root: Path, place_id: int) -> None:
    """Direct ORM insert — no alert-rule repo module exists yet."""
    from findplus.db.models_alerts import AlertRule
    from findplus.db.session import session_scope

    with session_scope() as session:
        session.add(
            AlertRule(
                name="Home arrival",
                place_id=place_id,
                device_id="dev-google-1",
                on_enter=True,
                on_exit=False,
                channel="webhook",
                cooldown_minutes=60,
                enabled=True,
                created_at=datetime.now(UTC),
            )
        )


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
    Leaflet/OSM map view exceeds 400 KB losslessly at 1440x900."""
    img = Image.open(io.BytesIO(path.read_bytes()))
    img.save(path, "PNG", optimize=True)
    if path.stat().st_size > max_kb * 1024:
        img.save(path, "PNG", optimize=True, compress_level=9)
    if path.stat().st_size > max_kb * 1024:
        img.convert("RGB").quantize(colors=256).save(path, "PNG", optimize=True)


async def _shoot(page, out_dir: Path, name: str, scheme: str) -> None:
    path = out_dir / f"{name}-{scheme}.png"
    await page.screenshot(path=path)
    save_png(path)


async def _unlock(page, base_url: str, scheme: str) -> None:
    """Unlock through the real form, set the server-side theme, then reload.

    The reload is what makes the theme PUT take visual effect (loadSettings()
    re-runs) and, until the E10-S2 fix loop lands, what repopulates the
    places/groups tabs after a locked boot (build-notes.md § E10-S2).
    """
    await page.goto(base_url, wait_until="networkidle")
    await page.fill("#lock-pin", DEMO_PIN)
    await page.click("#lock-submit")
    await page.wait_for_selector("#app-shell:not(.hidden)")
    await page.request.put(
        base_url + "/api/settings",
        data=json.dumps({"theme": scheme}),
        headers={"Content-Type": "application/json"},
    )
    await page.reload(wait_until="networkidle")
    await page.wait_for_selector("#app-shell:not(.hidden)")


async def take_screenshots(base_url: str, out_dir: Path) -> None:
    for scheme in ("light", "dark"):
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                viewport={"width": 1440, "height": 900}, color_scheme=scheme
            )
            page = await ctx.new_page()
            await _unlock(page, base_url, scheme)
            await _shoot(page, out_dir, "dashboard", scheme)

            await page.click("#btn-today")
            await page.wait_for_function(
                "document.querySelectorAll('#tracks > *').length > 0"
            )
            await _shoot(page, out_dir, "timeline", scheme)

            await page.click('.fp-tab[data-tab="places"]')
            await page.click("#fp-add-place-btn")
            # activateCrosshairMode() waits for a map click before opening the
            # dialog (same pattern as cli/tests/ui/test_places.py).
            await page.click("#map", position={"x": 10, "y": 10})
            await page.wait_for_selector("#fp-place-dialog[open]")
            await _shoot(page, out_dir, "places-dialog", scheme)
            await page.keyboard.press("Escape")

            await page.click('.fp-tab[data-tab="groups"]')
            await page.select_option("#fp-group-select", label="Family")
            await page.wait_for_selector("#fp-presence-panel .fp-verdict")
            await _shoot(page, out_dir, "group-presence", scheme)

            await page.click('.fp-tab[data-tab="alerts"]')
            await page.wait_for_selector("#fp-telegram-section")
            await _shoot(page, out_dir, "alerts-settings", scheme)

            await page.evaluate("fetch('/api/lock/lock', {method:'POST'})")
            await page.reload(wait_until="networkidle")
            await page.wait_for_selector("#lock-screen:not(.hidden)")
            await _shoot(page, out_dir, "lock-screen", scheme)
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
