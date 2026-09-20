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
             against cli/tests/test_ui_browser.py's proven fixture.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

pytest.importorskip("playwright", reason="playwright is not installed")
import pytest_asyncio
from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_SEED_SCRIPT = """
from datetime import UTC, datetime, timedelta
from findplus.db.migrate import upgrade_to_head
from findplus.db.models import Device
from findplus.db.session import session_scope
from findplus.findhub.types import RawObservation
from findplus.groups.repo import create_group
from findplus.ingest import ingest_observations, upsert_device
from findplus.places.repo import create_place
from findplus.state import set_setting, track_devices

upgrade_to_head()

HOME_LAT, HOME_LON = 41.100000, -80.100000


def obs(device_id, device_name, lat, lon):
    return RawObservation(
        device_id=device_id, device_name=device_name,
        latitude_e7=round(lat * 1e7), longitude_e7=round(lon * 1e7),
        observed_at=datetime.now(UTC) - timedelta(minutes=1),
        accuracy_meters=15.0, source="crowdsourced", is_own_report=False,
    )


with session_scope() as session:
    upsert_device(session, "TAG-HOME", "Home Tag")
    upsert_device(session, "TAG-AWAY", "Away Tag")
    upsert_device(session, "TAG-STALE", "Stale Tag")
    # Untracked on purpose: it gives the footer an Apple tracker to notice
    # (test_honesty_notices.py) without changing tracked_count for any other test.
    upsert_device(session, "TAG-AIR", "AirTag", provider="apple-find-my")
    # One device carries a real label, icon and colour rather than the 0007
    # defaults, so the badge, dialog, map and timeline tests have something
    # specific to assert (P2-E4-W3-S1-T6). The raw name stays "Home Tag";
    # every existing selector that matches on it still matches.
    home = session.get(Device, "TAG-HOME")
    home.label = "Ali's Keys"
    home.icon = "lucide:key"
    home.color = "#4f8cf7"
    track_devices(session, ["TAG-HOME", "TAG-AWAY", "TAG-STALE"], exclusive=True)

# The place must exist BEFORE the observations are ingested: ingest.py's
# geofence hook only evaluates places already on disk at ingest time.
with session_scope() as session:
    create_place(
        session, name="Home", latitude_e7=round(HOME_LAT * 1e7),
        longitude_e7=round(HOME_LON * 1e7), radius_meters=200,
        color="#3b82f6", enter_confirmations=1, exit_confirmations=1,
    )

with session_scope() as session:
    ingest_observations(
        session,
        [
            obs("TAG-HOME", "Home Tag", HOME_LAT, HOME_LON),
            obs("TAG-AWAY", "Away Tag", HOME_LAT + 0.00045, HOME_LON),
        ],
        fetched_at=datetime.now(UTC),
    )

# TAG-STALE is a tracked group member with no observation ever ingested —
# member_status() treats "no fix" the same as a fix older than stale_after.
with session_scope() as session:
    create_group(
        session, name="Family", color="#27ae60", quorum="majority",
        cluster_radius_meters=150, stale_after_minutes=90,
        member_ids=["TAG-HOME", "TAG-AWAY", "TAG-STALE"],
    )

# This suite drives a COMPLETED install. Without the stamp, main.js's
# onboarding check redirects every `page.goto("/")` to #/setup and hides
# #app-shell, so every dashboard assertion in this directory fails on an
# element the wizard is covering (P2-E11-W4-S1-T4). The wizard's own tests
# clear it per test through the `onboarding_incomplete` fixture below.
with session_scope() as session:
    set_setting(session, "onboarding.completed_at", "2026-01-01T00:00:00Z")
"""

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
    pg = await ctx.new_page()
    yield pg
    await ctx.close()
