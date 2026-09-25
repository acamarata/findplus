"""Playwright browser tests for the onboarding wizard (P2-E11-W4-S1-T7).

Covers every bullet specs/onboarding.md § 10 lists for this file: the
fresh-state redirect, a Skip that saves nothing, Done completing onboarding,
resuming mid-wizard after a reload, Run-setup-again leaving completion alone,
and the unfinished-setup banner.

`live_server` is session-scoped and shared with test_alerts.py, test_groups.py,
test_lock.py, test_lock_purge.py and test_places.py, which all assume a
finished setup (conftest.py's seed stamps `onboarding.completed_at`). Every
test here therefore runs inside an autouse fixture that clears the stamp and
restores it in a `finally`, so a failing assertion cannot leak an unfinished
install into whichever module runs next. That discipline assumes sequential
execution within this session-scoped fixture; a parallel runner (xdist) would
have to stop sharing the server, not rewrite this file.

The Devices and Groups step tests live in test_setup_wizard_devices.py (T1,
2026-09-22, PRI rule-7 size caps).
"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio

from findplus.honesty import NOT_AFFILIATED

from .conftest import SEEDED_COMPLETED_AT

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _set_completed_at(page, base_url, value):
    return await page.request.post(
        base_url + "/api/settings/onboarding.completed_at",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


async def _set_last_step(page, base_url, value):
    return await page.request.post(
        base_url + "/api/settings/onboarding.last_step",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


async def _settings(page, base_url):
    return await (await page.request.get(base_url + "/api/settings")).json()


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _unfinished(page, base_url):
    """Run each test against a never-onboarded install, and always restore.

    `loop_scope="session"` is mandatory, not tidiness: `page` is driven by the
    one session-scoped loop that owns Chrome, and an async fixture left on the
    per-test loop deadlocks waiting on a transport that loop never runs
    (conftest.py's `browser_session` documents the same trap).
    """
    await _set_completed_at(page, base_url, None)
    await _set_last_step(page, base_url, None)
    try:
        yield
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_fresh_state_redirects_to_setup(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_function("() => window.location.hash === '#/setup'", timeout=15000)
    await page.wait_for_selector("#setup-view .fp-wizard-step", timeout=15000)
    assert NOT_AFFILIATED in await page.locator("#setup-view").inner_text()


async def test_optional_step_skip_makes_no_save_call(page, base_url):
    """Skipping App lock must not POST a PIN, and must not complete setup."""
    calls = []

    async def block(route):
        calls.append(route.request.url)
        await route.abort()

    await page.route("**/api/settings/pin", block)
    await _set_last_step(page, base_url, "applock")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#fp-setup-pin", timeout=15000)

    await page.click("#fp-wizard-skip")
    await page.wait_for_selector("#fp-setup-pin", state="detached", timeout=15000)

    assert calls == []
    assert (await _settings(page, base_url))["onboarding.completed_at"] is None


async def test_next_with_matching_pin_sets_it_and_advances(page, base_url):
    """E13 blind-cap S2: Next must set the PIN through the same call as the
    Set PIN button, not silently discard it, when both fields match.

    Fulfilled locally rather than let through to the live server: a real
    `POST /api/settings/pin` reissues the session and locks the app, which
    would leak into every later test sharing this session-scoped server.
    """
    calls = []

    async def fulfill(route):
        calls.append((route.request.url, route.request.post_data_json))
        await route.fulfill(status=200, content_type="application/json", body="{}")

    await page.route("**/api/settings/pin", fulfill)
    await _set_last_step(page, base_url, "applock")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#fp-setup-pin", timeout=15000)

    await page.fill("#fp-setup-pin", "123456")
    await page.fill("#fp-setup-pin-confirm", "123456")
    await page.click("#fp-wizard-next")

    await page.wait_for_selector("#fp-setup-pin", state="detached", timeout=15000)
    assert calls == [(base_url + "/api/settings/pin", {"new_pin": "123456"})]
    assert (await _settings(page, base_url))["onboarding.last_step"] == "done"


async def test_next_with_mismatched_pin_shows_inline_error_and_stays(page, base_url):
    """A mismatch must veto the transition, not advance with no PIN set.

    UAT4 N35: the field error moved from the status line under the button
    to #fp-setup-pin-error, right beside the New PIN field -- settings.js's
    own #setting-new-pin-error convention. GP-R5-5: the mismatch is about
    both fields, so #fp-setup-pin-confirm carries the same aria-invalid and
    aria-describedby as #fp-setup-pin, the wizard's twin of settings.js's
    #confirm-pin fix.
    """
    calls = []

    async def record(route):
        calls.append(route.request.url)
        await route.continue_()

    await page.route("**/api/settings/pin", record)
    await _set_last_step(page, base_url, "applock")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#fp-setup-pin", timeout=15000)

    assert (
        await page.get_attribute("#fp-setup-pin-confirm", "aria-describedby")
        == "fp-setup-pin-error"
    )

    await page.fill("#fp-setup-pin", "1234")
    await page.fill("#fp-setup-pin-confirm", "5678")
    await page.click("#fp-wizard-next")

    await page.wait_for_selector("#fp-setup-pin-error:not(.hidden)", timeout=15000)
    assert "do not match" in await page.locator("#fp-setup-pin-error").inner_text()
    invalid = await page.get_attribute("#fp-setup-pin", "aria-invalid")
    assert invalid == "true"
    confirm_invalid = await page.get_attribute("#fp-setup-pin-confirm", "aria-invalid")
    assert confirm_invalid == "true"
    assert calls == []
    assert await page.locator("#fp-setup-pin").is_visible()
    assert (await _settings(page, base_url))["onboarding.last_step"] == "applock"


async def test_next_with_too_short_pin_shows_inline_error_and_never_posts(page, base_url):
    """UAT4 N35/N44: a matching-but-too-short PIN (e.g. "2468") used to reach
    the server before failing, logging a 400 in the console. The 6-character
    minimum is now checked client-side, beside the New PIN field, and Next
    stays put with no request at all."""
    calls = []

    async def record(route):
        calls.append(route.request.url)
        await route.continue_()

    await page.route("**/api/settings/pin", record)
    await _set_last_step(page, base_url, "applock")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#fp-setup-pin", timeout=15000)

    await page.fill("#fp-setup-pin", "2468")
    await page.fill("#fp-setup-pin-confirm", "2468")
    await page.click("#fp-wizard-next")

    await page.wait_for_selector("#fp-setup-pin-error:not(.hidden)", timeout=15000)
    assert "at least 6" in await page.locator("#fp-setup-pin-error").inner_text()
    invalid = await page.get_attribute("#fp-setup-pin", "aria-invalid")
    assert invalid == "true"
    assert calls == [], "a too-short PIN must never reach the server"
    assert await page.locator("#fp-setup-pin").is_visible()
    assert (await _settings(page, base_url))["onboarding.last_step"] == "applock"


async def test_done_shows_the_servers_tracked_count_on_a_resumed_session(page, base_url):
    """UAT4 N29: resuming setup straight at Done (a reload past the Devices
    step, or a session where Devices was skipped) left ctx.state.devices
    empty, so the summary read "0 devices tracked" over six real tracked
    devices. done.js now asks the server directly, the same tracked_count
    the dashboard widget reads."""

    async def get_devices(route):
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"tracked_count": 6, "devices": []}),
        )

    await page.route("**/api/devices", get_devices)
    await _set_last_step(page, base_url, "done")
    await page.goto(base_url + "/#/setup")
    # done.js paints the heading synchronously but fills the count paragraph
    # after its own GET /api/devices settles (wizard.js fires onEnter without
    # awaiting it). data-ready="true" is done.js's own signal that the fetch
    # has landed, so the read below cannot race it.
    await page.wait_for_selector("#setup-view p[data-ready='true']", timeout=15000)
    summary = await page.locator("#setup-view p").first.inner_text()
    assert summary == "6 devices tracked."


async def test_done_completes_onboarding_and_returns_to_dashboard(page, base_url):
    await _set_last_step(page, base_url, "done")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#setup-view .fp-wizard-step", timeout=15000)

    await page.click("#fp-wizard-next")
    await page.wait_for_function(
        "() => document.getElementById('setup-view').hidden === true", timeout=15000
    )

    assert (await _settings(page, base_url))["onboarding.completed_at"] is not None
    assert await page.locator("#app-shell").is_visible()


async def test_reload_mid_wizard_resumes_on_same_step(page, base_url):
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#setup-view .fp-wizard-step", timeout=15000)

    # Welcome -> Sign in. The Next click writes onboarding.last_step first.
    await page.click("#fp-wizard-next")
    await page.wait_for_selector("#fp-setup-signin-status", timeout=15000)
    assert (await _settings(page, base_url))["onboarding.last_step"] == "signin"

    await page.reload()
    # A step-specific marker, not the hash: the hash never carries the step id.
    await page.wait_for_selector("#fp-setup-signin-status", timeout=15000)


async def test_rerun_setup_from_settings_does_not_reset_completion(page, base_url):
    stamp = "2026-05-05T05:05:05Z"
    await _set_completed_at(page, base_url, stamp)
    await page.goto(base_url + "/", wait_until="networkidle")
    # main() calls initTabbar()/wireSettingsControls() synchronously right
    # after initMap() stamps "leaflet-container" onto #map (same boot chain
    # _alerts_helpers.open_alerts_tab and test_auth_accessories._open_settings
    # wait on): a click that lands before that has run hits a button with no
    # handler yet. A fixed wait_for_timeout(1000) stood in for this before;
    # under CPU load the real wiring can still be unfinished after 1s, which
    # is one way this test flaked.
    await page.wait_for_selector("#map.leaflet-container", state="attached")
    await page.click("#btn-settings")
    # openSettings() unhides #settings-modal (and #btn-rerun-setup, static
    # markup inside it) before awaiting loadSettings()/health/mountAuthPanel;
    # mountAuthPanel fills #fp-settings-signin, which sits above
    # #btn-rerun-setup in settings.html, so those awaits can still be
    # shifting the button's position after it is merely visible. data-loaded
    # is set in openSettings()'s finally once every fill (including that
    # panel) has landed -- test_settings_errors.py already waits on it for
    # the same reason. Waiting for it here before the click, instead of just
    # for the button to appear, closes the same race under load.
    await page.wait_for_selector("#settings-modal[data-loaded='true']", timeout=15000)
    await page.click("#btn-rerun-setup")

    await page.wait_for_function("() => window.location.hash === '#/setup'", timeout=15000)
    await page.wait_for_selector("#setup-view .fp-wizard-step", timeout=15000)
    assert (await _settings(page, base_url))["onboarding.completed_at"] == stamp


async def test_banner_appears_when_incomplete_and_hash_nonempty(page, base_url):
    await page.goto(base_url + "/#settings")
    await page.wait_for_selector("#setup-banner", timeout=15000)
    # An explicit hash is never overridden: the wizard is offered, not forced.
    assert page.url.endswith("#settings")

    await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
    # A goto to the same URL only changes the fragment, so the document is not
    # re-parsed and main() never re-runs; reload is what re-renders the page.
    await page.reload()
    await page.wait_for_selector("#app-shell", timeout=15000)
    await page.wait_for_timeout(1000)
    assert await page.locator("#setup-banner").count() == 0
