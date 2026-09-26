"""Deterministic reproduction of CI run 36262926438: relocking while an
unlock's own `bootDashboard()` is still mid-fetch must never let purged
data reappear.

These drive a real Chrome. They are skipped automatically when Playwright or
Chrome is unavailable, so the suite still runs on a bare machine.

Mechanism (confirmed against the un-patched source before this fix, by
running these tests against it): `hideLockAndRestore()` (web/app/lock.js)
awaits `bootDashboard()` (web/app/main.js) without cancelling it. If the user
locks again while that boot is still awaiting one of its own fetches, the
fetch can still resolve afterwards -- the fetch was already in flight, or the
caller crafts the response directly, as these tests do with `page.route()`
-- and the render that follows it used to write that data straight into the
DOM behind the lock screen, and (via `setup.js`'s unconditional
`closeSetup()`) could even reveal `#app-shell` again. The fix is a
`state.lockGeneration` counter, bumped by `showLock()`, that every async
renderer captures before its own fetch and checks again after it, plus a
`state.locked` guard in `closeSetup()` itself.

Three implementation notes this file's helpers exist for (each confirmed by
tracing the actual failure while writing this file, not guessed):

- `page.route()`'s handler is only ever actually invoked while the test's
  own thread is back inside a Playwright sync call (the sync API dispatches
  callbacks by switching into a greenlet that a blocking Playwright call
  yields to). A raw `threading.Event.wait()` on the test's own thread never
  yields, so a route registered with only a `threading.Event` to signal it
  never fires until the next `page.*` call. `_wait_for` below polls with
  `page.wait_for_timeout()` instead, which does yield.
- Registering `page.route()` right before the click it is meant to catch is
  itself a race: the sync API returns before Chromium confirms the
  interception is armed, so a request issued immediately after can still
  slip through unheld. `_arm_hold` registers the route up front and only
  starts holding once its caller flips `armed[0]`.
- `_unlock()`'s own successful boot keeps working in the background after it
  returns (`hideLockAndRestore()`'s `refreshTabsAfterUnlock()` -- places,
  groups, alerts, notices). Locking again before that settles makes several
  of those calls 401 at once, each one independently calling
  `showLock()` (api.js does this unconditionally on any 401), which clears
  `#lock-pin` every time it fires -- so a PIN typed right after that first
  lock can be wiped before the *second* unlock's own submit reads it,
  independently of anything this fix touches. Waiting for that first boot to
  go quiet before locking again avoids racing a different, older mechanism
  than the one under test.
- On the UN-patched source, the leaked data this suite checks for is
  ALSO self-correcting a moment later, for the same reason: once the stale
  fetch renders it, the rest of that `bootDashboard()` call (and its own
  `refreshTabsAfterUnlock()`) keep running against the now-really-locked
  server, and each of those 401s wipes the same DOM clean again within
  roughly a second. A single check after a fixed delay can land after that
  self-correction and miss the defect entirely. `_never_leaked` instead
  polls from immediately after the held fetch resolves, so it catches the
  leak at the moment it appears.

The `browser`, `server` and `page` fixtures come from this directory's
`conftest.py`.
"""

from __future__ import annotations

import json

from playwright.sync_api import Page, Route

from .conftest import PIN, _unlock


def _wait_for(page: Page, predicate, timeout_ms: int = 10000, step_ms: int = 50) -> None:
    """Poll `predicate` via `page.wait_for_timeout()` steps so pending
    `page.route()` callbacks actually get a chance to run (see module
    docstring) instead of blocking the test thread outside Playwright."""
    waited = 0
    while not predicate():
        if waited >= timeout_ms:
            raise AssertionError(f"condition not met within {timeout_ms}ms")
        page.wait_for_timeout(step_ms)
        waited += step_ms


def _never_leaked(
    page: Page, needles: list[str], window_ms: int = 1500, step_ms: int = 40
) -> str | None:
    """Poll `page.content()` for `window_ms`, returning the first needle seen
    or `None` if none ever appeared. See the module docstring: the defect
    this file reproduces is self-correcting, so a single delayed check is not
    enough -- this catches a leak at the moment it appears."""
    waited = 0
    while waited < window_ms:
        html = page.content()
        for needle in needles:
            if needle in html:
                return needle
        page.wait_for_timeout(step_ms)
        waited += step_ms
    return None


def _arm_hold(page: Page, url_glob: str) -> tuple[list[bool], list[Route]]:
    """Register `url_glob`'s route once, up front, and pass every request
    straight through (`route.continue_()`) until `armed[0]` is set True (see
    module docstring). Only the first request after arming is held, in
    `held`.
    """
    armed = [False]
    held: list[Route] = []

    def handler(route: Route) -> None:
        if armed[0] and not held:
            held.append(route)
        else:
            route.continue_()

    page.route(url_glob, handler)
    return armed, held


def _relock_after_settling(page: Page) -> None:
    """The first `#btn-lock` click of each test below, after letting the
    prior unlock's own background refreshes finish first (see module
    docstring's third note)."""
    page.wait_for_timeout(2000)
    page.click("#btn-lock")
    page.wait_for_selector("#lock-screen:visible", timeout=10000)


def test_relock_during_inflight_unlock_boot_hides_device_names(page: Page) -> None:
    """Holds /api/devices (loadDevices(), devices.js) across a second lock."""
    armed, held = _arm_hold(page, "**/api/devices")
    _unlock(page)
    _relock_after_settling(page)

    armed[0] = True
    page.fill("#lock-pin", PIN)
    page.click("#lock-submit")
    _wait_for(page, lambda: held, timeout_ms=10000)

    # Lock again while that boot is stuck awaiting the held /api/devices --
    # the exact race CI run 36262926438 caught.
    page.click("#btn-lock")
    page.wait_for_selector("#lock-screen:visible", timeout=10000)

    # Now let the stale fetch resolve, with real device data, as if it had
    # been in flight since before the relock.
    held[0].fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(
            {
                "devices": [
                    {
                        "device_id": "TAG-BIKE",
                        "name": "Bike Tag",
                        "label": None,
                        "is_tracked": True,
                        "observation_count": 3,
                        "provider": "google-find-hub",
                        "icon": "letter",
                        "color": "#4f8cf7",
                    }
                ]
            }
        ),
    )

    leaked = _never_leaked(page, ["Bike Tag", "TAG-BIKE"])
    assert leaked is None, f"{leaked!r} leaked into the DOM after a relock mid-boot"
    assert not page.is_visible("#app-shell"), "the dashboard reappeared behind the lock screen"
    assert page.is_visible("#lock-screen")
    page.unroute("**/api/devices")


def test_relock_during_inflight_unlock_boot_hides_coordinates(page: Page, server: str) -> None:
    """Holds /api/timeline (loadDay(), timeline.js) across a second lock.

    Reuses a REAL /api/timeline response (fetched while genuinely unlocked)
    as the held fetch's answer, so the fixture's own seeded coordinates are
    exactly what a real in-flight request would have returned -- the test
    does not invent a response shape that could drift from the API's own.
    """
    armed, held = _arm_hold(page, "**/api/timeline*")
    _unlock(page)
    day = page.input_value("#day-picker")
    real_timeline = page.request.get(f"{server}/api/timeline?day={day}")
    assert real_timeline.ok, real_timeline.text()
    body = real_timeline.text()
    seeded = "41.09" in body or "41.10" in body or "41.11" in body
    assert seeded, "fixture seed missing from timeline"

    _relock_after_settling(page)

    armed[0] = True
    page.fill("#lock-pin", PIN)
    page.click("#lock-submit")
    _wait_for(page, lambda: held, timeout_ms=10000)

    # Lock again while that boot is stuck awaiting the held /api/timeline --
    # same race as the devices test above, at the render that draws
    # coordinates (renderMap()/renderTracks()) rather than the device list.
    page.click("#btn-lock")
    page.wait_for_selector("#lock-screen:visible", timeout=10000)

    held[0].fulfill(status=200, content_type="application/json", body=body)

    leaked = _never_leaked(page, ["41.09", "41.10", "41.11"])
    assert leaked is None, f"{leaked!r} (a seeded coordinate) leaked after a relock mid-boot"
    assert not page.is_visible("#app-shell"), "the dashboard reappeared behind the lock screen"
    assert page.is_visible("#lock-screen")
    page.unroute("**/api/timeline*")


def test_close_setup_never_unhides_app_shell_while_locked(page: Page) -> None:
    """closeSetup() (web/app/setup.js) is called unconditionally on every
    lock (purgeRenderedData() -> purge() -> closeSetup()) and by any routing
    code that resolves after one. It must never be the thing that undoes
    showLock()'s hide, whether or not the wizard was ever open.
    """
    result = page.evaluate(
        """async () => {
            const stateMod = await import('/static/app/state.js');
            const setupMod = await import('/static/app/setup.js');
            const shell = document.getElementById('app-shell');

            // Simulate exactly the moment this fix targets: locked, and the
            // shell already hidden by showLock().
            stateMod.state.locked = true;
            shell.classList.add('hidden');
            setupMod.closeSetup();
            const stillHiddenWhileLocked = shell.classList.contains('hidden');

            // The normal case must still work: an unlocked closeSetup() (a
            // real "leave the wizard" navigation) does give the shell back.
            stateMod.state.locked = false;
            setupMod.closeSetup();
            const shownWhenUnlocked = !shell.classList.contains('hidden');

            return { stillHiddenWhileLocked, shownWhenUnlocked };
        }"""
    )
    assert result["stillHiddenWhileLocked"], "closeSetup() revealed #app-shell while locked"
    assert result["shownWhenUnlocked"], "closeSetup() regressed the normal (unlocked) reveal path"
