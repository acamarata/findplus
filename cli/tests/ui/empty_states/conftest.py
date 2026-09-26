"""Shared fixtures for the empty-state browser suite (test_empty_states.py).

Purpose    : One real `findplus serve --no-poller` process against a
             freshly migrated, onboarding-completed database that seeds
             NOTHING else -- zero devices, zero groups, zero places. That is
             exactly the state the gap audit's U12/U13/U14 rows describe
             (nothing tracked, no groups, no places), which the shared
             `cli/tests/ui/conftest.py` session server can never reach: its
             seed always has a tracked device, a group and a place.
Inputs     : None -- seeding runs a subprocess against a throwaway,
             env-isolated database before the server starts.
Outputs    : `browser` (module-scoped Chromium instance), `server`
             (module-scoped base URL), `page` (function-scoped Page).
Constraints: No PIN is ever set here, so `/api/lock/status` reports
             `lock_configured: false` and the app boots straight to
             `#app-shell` with no lock screen to get past -- one less step
             than `cli/tests/ui/boot/conftest.py`'s fixtures, which do set a
             PIN. Sync Playwright API, same shape as that file.
"""

from __future__ import annotations

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

from .._offline_tiles import stub_osm_tiles

PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: Migrate and stamp onboarding done; deliberately create no device, group or
#: place, so the dashboard, Groups tab and Places tab all render their empty
#: states the moment the page loads.
_SEED_SCRIPT = """
from findplus.db.migrate import upgrade_to_head
from findplus.db.session import session_scope
from findplus.state import set_setting

upgrade_to_head()
with session_scope() as session:
    set_setting(session, "onboarding.completed_at", "2026-01-01T00:00:00Z")
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


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
    """A real uvicorn process over an empty (but onboarded) database."""
    tmp = tmp_path_factory.mktemp("ui-empty-state")
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
        pytest.skip(f"could not seed the empty-state fixture: {seed.stderr[-400:]}")

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
        yield base
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture
def page(browser: Browser, server: str) -> Iterator[Page]:
    context = browser.new_context(viewport={"width": 1280, "height": 900}, bypass_csp=True)
    stub_osm_tiles(context)
    p = context.new_page()
    p.goto(server, wait_until="networkidle")
    # No PIN is ever configured in this fixture, so there is no lock screen
    # to wait out -- #app-shell is the very first thing that becomes visible.
    p.wait_for_selector("#app-shell:visible", timeout=20000)
    yield p
    context.close()
