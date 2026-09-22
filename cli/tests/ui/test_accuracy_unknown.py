"""Browser test: the dashboard never shows a guessed accuracy (CF-P2-6).

Purpose    : `web/app/timeline.js` renders "Accuracy unknown" (catalog key
             `timeline.accuracyUnknown`) for any point whose accuracy_meters
             is null, instead of quietly omitting the line -- which is what
             every Apple Find My observation carries, since Apple gives no
             metre figure and Find+ no longer invents one. A Google fix with
             a real accuracy still shows the `±N m` reading, so this also
             guards against the two branches getting swapped.
Inputs     : None -- seeds its own throwaway, env-isolated database via a
             subprocess before starting a real `findplus serve --no-poller`.
Outputs    : Pass/fail against the rendered `.tl-meta` text on the seeded day.
Constraints: Self-contained (its own server/browser fixtures, own temp dir
             and port) rather than sharing `ui/conftest.py` or
             `ui/boot/conftest.py`'s module-scoped seed, so this file cannot
             perturb the device/observation counts other test_*.py files in
             this suite assert on. Uses bundled Playwright Chromium only,
             never a real browser channel.
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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PIN = "409217"

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

def obs(hour, minute, accuracy):
    return RawObservation(
        device_id="apple:cf-p2-6", device_name="Wallet Tag",
        latitude_e7=round(41.098 * 1e7), longitude_e7=round(-80.645 * 1e7),
        observed_at=datetime(day.year, day.month, day.day, hour, minute,
                             tzinfo=tz).astimezone(UTC),
        accuracy_meters=accuracy, source="apple-find-my", is_own_report=False,
    )

with session_scope() as session:
    upsert_device(session, "apple:cf-p2-6", "Wallet Tag")
    track_all(session)
    # The real shape: every Apple fix has accuracy_meters=None. A second
    # point WITH an accuracy proves the "unknown" branch is not just always on.
    ingest_observations(
        session, [obs(8, 3, None), obs(8, 20, 42.0)], fetched_at=datetime.now(UTC),
    )
"""


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
    """A real uvicorn process seeded with one Apple device: one point with no
    accuracy, one with a real accuracy, both on today's history.
    """
    tmp = tmp_path_factory.mktemp("accuracyui")
    port = _free_port()
    env = dict(
        os.environ,
        FINDPLUS_DATABASE_PATH=str(tmp / "ui.sqlite"),
        FINDPLUS_STATE_DIR=str(tmp / "state"),
        PORT=str(port),
    )
    python = sys.executable
    seed = subprocess.run(
        [python, "-c", _SEED_SCRIPT], env=env, capture_output=True, text=True, cwd=PROJECT_ROOT
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
    page.wait_for_timeout(1500)


def test_apple_point_with_no_accuracy_shows_unknown_not_a_guessed_number(page: Page) -> None:
    _unlock(page)
    items = page.locator(".tl-item")
    assert items.count() == 2
    metas = [items.nth(i).inner_text() for i in range(items.count())]
    joined = "\n".join(metas)
    assert "Accuracy unknown" in joined
    # Never a stand-in number for the unknown reading (the old invented
    # constants were 10, 30, 65 or 150 -- assert none of that family leaks in
    # disguised as a real accuracy for the null point).
    assert "±0 m" not in joined


def test_apple_point_with_a_real_accuracy_still_shows_the_figure(page: Page) -> None:
    """Guards against the unknown-accuracy branch swallowing every point."""
    _unlock(page)
    items = page.locator(".tl-item")
    metas = [items.nth(i).inner_text() for i in range(items.count())]
    assert any("±42 m" in m for m in metas)
