"""Shared fixtures for the boot/lock-screen browser suite (test_boot_*.py).

Purpose    : One real `findplus serve --no-poller` process seeded with a
             single tracked device ("Bike Tag") plus a PIN, and the sync
             Playwright plumbing (`browser`, `server`, `page`) every
             test_boot_*.py file in this directory receives as ordinary
             pytest fixtures.
Inputs     : None -- seeding runs a subprocess against a throwaway,
             env-isolated database before the server starts.
Outputs    : `browser` (module-scoped Chromium instance), `server`
             (module-scoped base URL), `page` (function-scoped Page),
             `_unlock()` helper, `PIN`.
Constraints: Uses the sync Playwright API and plain `@pytest.fixture`
             (not pytest_asyncio) -- deliberately separate from the parent
             `cli/tests/ui/conftest.py`'s session-scoped async
             `live_server`/`page`; the two fixture sets are not
             interchangeable and this conftest only applies under
             `cli/tests/ui/boot/`, so it cannot shadow those for any other
             file in `cli/tests/ui/`. The parent conftest's
             `pytest_collection_modifyitems` still auto-tags every test
             collected here with `@pytest.mark.browser`, since this
             directory is a descendant of `cli/tests/ui/`.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="playwright is not installed")
from playwright.sync_api import Browser, Page, sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PIN = "864213"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _post(url: str, payload: dict) -> None:
    request = urllib.request.Request(
        url,
        method="POST",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(request, timeout=10)


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    try:
        with sync_playwright() as pw:
            try:
                instance = pw.chromium.launch(headless=True)
            except Exception as exc:
                pytest.skip(f"Chrome unavailable: {exc}")
            yield instance
            instance.close()
    except Exception as exc:
        pytest.skip(f"Playwright unavailable: {exc}")


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """A real uvicorn process with seeded history and a PIN already set."""
    tmp = tmp_path_factory.mktemp("uiserver")
    port = _free_port()
    env = dict(
        os.environ,
        FINDPLUS_DATABASE_PATH=str(tmp / "ui.sqlite"),
        FINDPLUS_STATE_DIR=str(tmp / "state"),
        PORT=str(port),
    )
    python = sys.executable

    seed = subprocess.run(
        [python, "-c", _SEED_SCRIPT],
        env=env,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    if seed.returncode:
        pytest.skip(f"could not seed the UI fixture: {seed.stderr[-400:]}")

    proc = subprocess.Popen(
        [python, "-m", "findplus.cli", "serve", "--no-poller", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=PROJECT_ROOT,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"{base}/api/health", timeout=2)
                break
            except Exception:
                time.sleep(0.25)
        else:
            pytest.skip("the test server never came up")

        _post(f"{base}/api/settings/pin", {"new_pin": PIN})
        yield base
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


_SEED_SCRIPT = """
from datetime import UTC, datetime
from findplus.db.migrate import upgrade_to_head
from findplus.db.session import session_scope
from findplus.ingest import ingest_observations, upsert_device
from findplus.state import track_all
from findplus.findhub.types import RawObservation
from findplus.timeline import local_zone

upgrade_to_head()
tz = local_zone()
day = datetime.now(tz).date()

def obs(hour, minute, lat):
    return RawObservation(
        device_id="TAG-BIKE", device_name="Bike Tag",
        latitude_e7=round(lat * 1e7), longitude_e7=round(-80.645 * 1e7),
        observed_at=datetime(day.year, day.month, day.day, hour, minute,
                             tzinfo=tz).astimezone(UTC),
        accuracy_meters=30.0, source="crowdsourced", is_own_report=False,
    )

with session_scope() as session:
    upsert_device(session, "TAG-BIKE", "Bike Tag")
    track_all(session)
    ingest_observations(
        session, [obs(8, 3, 41.098), obs(8, 20, 41.104), obs(9, 10, 41.112)],
        fetched_at=datetime.now(UTC),
    )
"""


@pytest.fixture
def page(browser: Browser, server: str) -> Iterator[Page]:
    context = browser.new_context(viewport={"width": 1280, "height": 900}, bypass_csp=True)
    p = context.new_page()
    p.goto(server, wait_until="networkidle")
    p.wait_for_timeout(600)
    yield p
    context.close()


def _unlock(page: Page) -> None:
    page.fill("#lock-pin", PIN)
    page.click("#lock-submit")
    page.wait_for_selector("#app-shell:visible", timeout=20000)
    # lock.js's unlock handler kicks off its own bootDashboard() call --
    # loadConfig, loadSettings, loadDevices, setDefaultView, loadStatus,
    # loadDay, six sequential awaits -- independently of main()'s own chain.
    # A flat 1500ms sleep here raced that chain under load: #tracks (and the
    # map markers, rendered the line before it in the same synchronous
    # continuation) could still be empty when it elapsed.
    #
    # Neither "#tracks > *" nor ".tl-item" is a safe marker for "boot
    # finished": while still locked, refreshLockState() -> showLock() ->
    # purgeRenderedData() already calls groups.js's purge() -> clearGroup()
    # -> renderTracks(), which writes the "No devices tracked yet" empty-
    # state placeholder into #tracks well before this helper's click
    # (confirmed by tracing every #tracks.innerHTML write during a real
    # run) -- so "#tracks > *" resolves instantly on the wrong content. And
    # ".tl-item" never appears at all when the real post-unlock render lands
    # on a day with no observations (test_unlock_restores_the_previously_
    # selected_day locks/unlocks again on a previous day with none seeded).
    # The one thing that reliably tells the two states apart: this suite's
    # seed always tracks TAG-BIKE (track_all() in _SEED_SCRIPT), so a real
    # boot can only ever show the seeded points or timeline.emptyDay's "No
    # observations recorded for this day" -- never notices.dashboardEmpty's
    # "No devices tracked yet", which is unreachable once loadDevices() has
    # actually run. Waiting for that text to be gone works regardless of
    # which day is showing.
    page.wait_for_function(
        "() => !document.getElementById('tracks').textContent.includes('No devices tracked yet')",
        timeout=20000,
    )
