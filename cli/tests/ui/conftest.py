"""Shared fixtures for the Playwright UI suite (Places, Groups, Lock).

Purpose    : Start one real `findplus serve --no-poller` process for the
             whole session against an env-isolated, migrated, seeded
             database, and hand each test a browser Page pointed at it.
Inputs     : None — seeding runs a subprocess against the same throwaway
             database before the server starts.
Outputs    : `live_server` (base URL), `browser_session`, `page`.
Constraints: FINDPLUS_DATABASE_PATH / FINDPLUS_STATE_DIR are the ONLY env
             vars findplus.config reads (env_prefix "FINDPLUS_"); the bare
             names silently target the real ~/.findplus (build-notes.md §
             E2) — deviation from this ticket's literal env dict, verified
             against cli/tests/ui/boot/conftest.py's proven fixture.

The subprocess seed script and the alerts-tab navigation helper moved to
`_seed_script.py` / `_alerts_helpers.py` (E13 stage 2, size cap) and are
re-imported below so `from .conftest import open_alerts_tab` etc. still work
for every file that already imports them that way.
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

pytest.importorskip("playwright", reason="playwright is not installed")
import pytest_asyncio
from playwright.async_api import async_playwright

from ._alerts_helpers import open_alerts_tab as open_alerts_tab
from ._offline_tiles import stub_osm_tiles
from ._seed_script import SEED_SCRIPT as _SEED_SCRIPT

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: What the seed stamps, and what every wizard test restores afterwards.
SEEDED_COMPLETED_AT = "2026-01-01T00:00:00Z"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def ui_env(tmp_path_factory: pytest.TempPathFactory) -> dict:
    state = tmp_path_factory.mktemp("ui-state")
    return dict(
        os.environ,
        FINDPLUS_DATABASE_PATH=str(state / "ui_test.sqlite"),
        FINDPLUS_STATE_DIR=str(state),
    )


@pytest.fixture(scope="session")
def ui_db(ui_env: dict) -> Path:
    result = subprocess.run(
        [sys.executable, "-c", _SEED_SCRIPT],
        check=True,
        capture_output=True,
        text=True,
        env=ui_env,
        cwd=PROJECT_ROOT,
    )
    assert result.returncode == 0, result.stderr
    return Path(ui_env["FINDPLUS_DATABASE_PATH"])


@pytest.fixture(scope="session")
def live_server(ui_db: Path, ui_env: dict):
    port = _free_port()  # dynamic; a fixed port collides across parallel runs
    env = dict(ui_env, PORT=str(port))
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "findplus.cli",
            "serve",
            "--no-poller",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        cwd=PROJECT_ROOT,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                httpx.get(f"{base}/api/health", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("live_server never became healthy")
        yield base
    finally:
        proc.terminate()
        proc.wait()


def pytest_collection_modifyitems(items) -> None:
    # Everything in this directory drives a real browser. CI runs the UI
    # suite as its own `-m browser` job and excludes it everywhere else, so
    # the marker has to be on the tests; marking the directory here keeps a
    # new file from silently escaping both selections.
    here = Path(__file__).parent
    for item in items:
        if here in Path(str(item.path)).parents:
            item.add_marker(pytest.mark.browser)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def browser_session(live_server: str):
    # A session-scoped async fixture needs a matching session-scoped event
    # loop (loop_scope="session"), or the tests that await it under their
    # own per-test loop deadlock waiting on a browser transport owned by a
    # loop that never runs again — every test/fixture in this module pins
    # loop_scope="session" to stay on the one loop that drives Chrome.
    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(f"Chrome unavailable: {exc}")
        yield browser, live_server
        await browser.close()


@pytest.fixture(scope="session")
def base_url(live_server: str) -> str:
    return live_server


@pytest_asyncio.fixture(loop_scope="session")
async def onboarding_incomplete(page, base_url: str):
    """Run one test against a never-onboarded install, then put the stamp back.

    `live_server` is session-scoped and shared with every other file in this
    directory, which all assume a finished setup. The restore is in a finally
    so a failing assertion cannot leak the unfinished state into whatever runs
    next (test_lock.py documents the same discipline for the PIN).
    """
    await _post_completed_at(page, base_url, None)
    try:
        yield
    finally:
        await _post_completed_at(page, base_url, SEEDED_COMPLETED_AT)


async def _post_completed_at(page, base_url: str, value):
    await page.request.post(
        base_url + "/api/settings/onboarding.completed_at",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


async def set_theme(page, theme: str) -> None:
    """Write `data-theme` on <html>, the same mechanism applyTheme() uses.

    A plain function, not a fixture: nothing here needs teardown, and a test
    that scans several themes on one page calls it more than once.
    """
    await page.evaluate("(t) => { document.documentElement.dataset.theme = t; }", theme)


async def assert_dialog_has_real_chrome(page, dialog_id: str) -> None:
    """Assert `#dialog_id`'s border-radius/background come from CSS, in both
    themes -- not by assuming one of them.

    5241821 made the default theme follow the OS ("system") instead of always
    dark, so a fresh install now renders light -- and light theme's own
    `--panel` token IS `#ffffff` (web/style.css), the exact value a dialog
    with NO styling at all (the original W3/U3 bug) also paints. Pinning both
    themes with set_theme() (the mechanism applyTheme() uses) proves the
    colour is CSS-driven either way, rather than weakening the check to allow
    white unconditionally.
    """
    dialog = page.locator(f"#{dialog_id}")

    async def styles():
        return await dialog.evaluate(
            "(el) => { const s = getComputedStyle(el);"
            " return { radius: s.borderRadius, bg: s.backgroundColor }; }"
        )

    await set_theme(page, "dark")
    dark = await styles()
    assert dark["radius"] not in ("0px", ""), "no border-radius at all"
    assert dark["bg"] not in ("rgba(0, 0, 0, 0)", "", "rgb(255, 255, 255)"), (
        "painted as the browser default white box"
    )
    await set_theme(page, "light")
    light = await styles()
    assert light["radius"] not in ("0px", ""), "no border-radius at all"
    assert light["bg"] not in ("rgba(0, 0, 0, 0)", ""), "painted with no background at all"


@pytest.fixture
def reset_alert_and_observation_state(ui_db: Path) -> None:
    """Delete accumulated alert_rules/alert_deliveries/location_observations
    rows before a real cold-boot test renders the dashboard.

    `live_server` is session-scoped; earlier files (test_alerts_rules.py,
    test_alerts_deliveries.py, test_alerts_whatsapp.py) create alert rules
    through the real API and never delete them, so a boot-heavy test later
    (test_groups_dialog_purge.py, test_lock.py) rendered rules/deliveries
    nothing in that test created, slowing its boot (E13 loop3 L3-3). Request
    explicitly, not autouse: most files here reuse what earlier tests left
    behind (e.g. the seeded "Family" group). Children (alert_deliveries)
    delete before their parent regardless of PRAGMA foreign_keys.
    """
    conn = sqlite3.connect(ui_db)
    try:
        conn.execute("DELETE FROM alert_deliveries")
        conn.execute("DELETE FROM alert_rules")
        conn.execute(
            "DELETE FROM location_observations WHERE device_id NOT IN ('TAG-HOME', 'TAG-AWAY')"
        )
        conn.commit()
    finally:
        conn.close()


@pytest_asyncio.fixture(loop_scope="session")
async def page(browser_session):
    # One BrowserContext per test. The dashboard persists UI state (open
    # tab, device selection, widget toggles) in localStorage, so a shared
    # context leaks that state between tests and makes them order
    # dependent; a reload inside a single test still sees its own writes.
    browser, _ = browser_session
    # bypass_csp: the dashboard's CSP has no 'unsafe-eval', and Playwright
    # evaluates string predicates (wait_for_function) via eval in the page.
    # The header itself is still asserted by the security tests.
    ctx = await browser.new_context(bypass_csp=True)
    await stub_osm_tiles(ctx)  # PRI rule 3: no real tile fetches
    pg = await ctx.new_page()
    yield pg
    await ctx.close()
