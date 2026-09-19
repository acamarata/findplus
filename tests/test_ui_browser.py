"""End-to-end browser tests of the lock screen and dashboard boot.

These drive a real Chrome. They are skipped automatically when Playwright or
Chrome is unavailable, so the suite still runs on a bare machine.

Why these exist: the "app starts locked" path is only reachable through a
browser, and it silently broke once already — `main()` returned early on the
lock screen, so `loadConfig()` never ran. Unlocking then left `state.config`
null (the Settings dialog threw), the mandatory Find Hub notice blank, and the
auto-refresh timer never created for the rest of the session. Nothing in the
Python suite could see any of that.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="playwright is not installed")
from playwright.sync_api import Browser, Page, sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIN = "8642"


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
                instance = pw.chromium.launch(channel="chrome", headless=True)
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
        DATABASE_PATH=str(tmp / "ui.sqlite"),
        STATE_DIR=str(tmp / "state"),
        PORT=str(port),
    )
    python = str(PROJECT_ROOT / ".venv" / "bin" / "python")

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
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    p = context.new_page()
    p.goto(server, wait_until="networkidle")
    p.wait_for_timeout(600)
    yield p
    context.close()


def _unlock(page: Page) -> None:
    page.fill("#lock-pin", PIN)
    page.click("#lock-submit")
    page.wait_for_selector("#app-shell:visible", timeout=20000)
    page.wait_for_timeout(1500)


# --------------------------------------------------------------- locked state
def test_app_opens_on_the_lock_screen(page: Page) -> None:
    assert page.is_visible("#lock-screen")
    assert not page.is_visible("#app-shell")


def test_no_location_data_is_in_the_dom_while_locked(page: Page) -> None:
    """A CSS overlay would still leave coordinates in the page source."""
    html = page.content()
    assert "41.09" not in html
    assert "41.10" not in html


def test_wrong_pin_stays_locked_and_reports_it(page: Page) -> None:
    page.fill("#lock-pin", "0000")
    page.click("#lock-submit")
    page.wait_for_timeout(1200)
    assert page.is_visible("#lock-screen")
    assert page.inner_text("#lock-error").strip()


# ------------------------------------------------------------- unlocked state
def test_correct_pin_unlocks_and_renders_history(page: Page) -> None:
    _unlock(page)
    assert not page.is_visible("#lock-screen")
    assert page.locator(".tl-item").count() == 3
    assert page.locator(".marker-num").count() >= 3


def test_findhub_notice_is_present_after_unlocking(page: Page) -> None:
    """Regression: starting locked used to leave this mandatory notice blank."""
    _unlock(page)
    notice = page.inner_text("#findhub-notice")
    assert "should not be treated as real-time emergency" in notice


def test_settings_dialog_works_after_unlocking(page: Page) -> None:
    """Regression: `state.config` was null, so opening Settings threw."""
    _unlock(page)
    page.click("#btn-settings")
    page.wait_for_timeout(1200)
    assert page.is_visible("#settings-modal")
    assert "polling every" in page.inner_text("#settings-about")


def test_devices_dialog_lists_trackers_with_checkboxes(page: Page) -> None:
    _unlock(page)
    page.click("#btn-devices")
    page.wait_for_timeout(1200)
    assert page.is_visible("#device-modal")
    assert page.locator("#device-list input[type=checkbox]").count() >= 1
    assert "Google requests per hour" in page.inner_text("#device-rate")


def test_dialogs_are_closed_on_a_normal_load(page: Page) -> None:
    """Regression: `.modal` beat `.hidden`, so Devices rendered open on load."""
    _unlock(page)
    assert not page.is_visible("#device-modal")
    assert not page.is_visible("#settings-modal")


def test_theme_switches_live(page: Page) -> None:
    _unlock(page)
    page.click("#btn-settings")
    page.wait_for_timeout(1000)
    page.select_option("#setting-theme", "light")
    page.wait_for_timeout(900)
    assert page.get_attribute("html", "data-theme") == "light"
    page.select_option("#setting-theme", "dark")
    page.wait_for_timeout(900)
    assert page.get_attribute("html", "data-theme") == "dark"


def test_manual_lock_returns_to_the_lock_screen(page: Page) -> None:
    _unlock(page)
    page.click("#btn-lock")
    page.wait_for_selector("#lock-screen:visible", timeout=10000)
    assert not page.is_visible("#app-shell")
    assert "41.09" not in page.content()


def test_unlock_restores_the_previously_selected_day(page: Page) -> None:
    """Unlocking must return to the exact view, not reset to today."""
    _unlock(page)
    page.click("#btn-prev-day")
    page.wait_for_timeout(1200)
    previous_day = page.input_value("#day-picker")

    page.click("#btn-lock")
    page.wait_for_selector("#lock-screen:visible", timeout=10000)
    _unlock(page)

    assert page.input_value("#day-picker") == previous_day


def test_no_javascript_errors_and_no_broken_requests(page: Page, server: str) -> None:
    """Catches missing assets and uncaught exceptions across the whole flow."""
    errors: list[str] = []
    failures: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on(
        "response",
        lambda r: (
            failures.append(f"{r.status} {r.url}")
            # 401s are expected while locked; everything else is a defect.
            if r.status >= 400 and r.status != 401
            else None
        ),
    )

    page.reload(wait_until="networkidle")
    _unlock(page)
    page.click("#btn-settings")
    page.wait_for_timeout(900)
    page.click("#btn-close-settings")
    page.click("#btn-devices")
    page.wait_for_timeout(900)

    assert not errors, f"JavaScript errors: {errors}"
    assert not failures, f"broken requests: {failures}"
