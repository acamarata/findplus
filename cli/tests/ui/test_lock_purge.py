"""Playwright browser tests: the app lock must DESTROY rendered location data,
not just hide it (P1-E10-W6-S1-T4/T5 continued).

Split out of test_lock.py (PRI rule 7, <=300 lines/file); PIN is imported from
there. `live_server` is session-scoped and shared with test_groups.py/
test_lock.py/test_places.py, so every test here restores the shared server to
"no PIN" before returning (best-effort in the finally blocks).
"""

from __future__ import annotations

import contextlib
import json

import pytest

from .test_lock import PIN

pytestmark = pytest.mark.asyncio(loop_scope="session")

LEAKED_STRINGS = ("Ali's Keys", "Away Tag", "Stale Tag", "Family", "Lock purge rule", "41.1")


async def _populate_places_groups_alerts(page, base_url):
    """Render the place circle, group presence panel/legend/select, the
    alerts rules table AND the timeline -- everything `purge()` must destroy
    on lock.

    The three tab waits below only prove places.js/groups.js/alerts.js have
    rendered; none of them waits on the timeline, which is a separate async
    chain inside main.js's bootDashboard() that starts running before this
    function's first click and can still be in flight once all three tabs
    have settled. "41.1" (the seeded "Home" fix's coordinates, in a
    `.tl-coords` title/text) comes only from that chain, so an explicit wait
    for it is required -- without it this coordinate is present about a
    second after the places circle on a quiet box, but a slower cold boot
    (CPU contention from a full parallel suite, or another file's earlier
    tests leaving rows in the DB for bootDashboard's fetches to churn
    through) can still be mid-render when the tab waits below are long done,
    which is what made this test order-dependent rather than reliably
    flaky-or-not on its own (findings-queue F1).
    """
    await page.click('button[data-tab="places"]')
    await page.wait_for_selector("#map svg path.leaflet-interactive")
    # "attached", not the default "visible": the timeline sits under a
    # different tab section, hidden (not removed) while "places" is active,
    # so a "visible" wait here would never resolve. Attached is exactly what
    # this function's own final check needs -- page.content() reads markup,
    # not paint state.
    await page.wait_for_selector(".tl-coords", state="attached")
    await page.click('button[data-tab="groups"]')
    await page.select_option("#fp-group-select", label="Family")
    await page.wait_for_selector("#fp-presence-panel .fp-verdict")
    await page.click('button[data-tab="alerts"]')
    await page.locator("#fp-rules-tbody tr", has_text="Lock purge rule").wait_for(state="visible")
    html = await page.content()
    for leaked in LEAKED_STRINGS:
        assert leaked in html, f"fixture setup did not render {leaked!r}"


async def _assert_dom_purged(page):
    assert await page.locator("#map svg path.leaflet-interactive").count() == 0
    assert (await page.locator("#fp-presence-panel").inner_text()).strip() == ""
    assert (await page.locator("#fp-group-legend").inner_text()).strip() == ""
    assert await page.locator("#fp-group-select option").count() == 0
    assert await page.locator("#fp-rules-tbody tr").count() == 0
    html = await page.content()
    for leaked in LEAKED_STRINGS:
        assert leaked not in html, f"{leaked!r} survived the lock"


async def _delete_rule_named(page, base_url, name):
    rules_resp = await page.request.get(base_url + "/api/alerts/rules")
    for rule in await rules_resp.json():
        if rule["name"] == name:
            await page.request.delete(f"{base_url}/api/alerts/rules/{rule['id']}")


async def _setup_purge_fixture(page, base_url):
    """Create the rule, set the PIN, and enable the lock so #btn-lock (hidden
    while lock_enabled is off) is clickable — locking through the API alone
    never triggers showLock() client-side; nothing on an already-loaded page
    polls lock status."""
    rule_resp = await page.request.post(
        base_url + "/api/alerts/rules",
        data=json.dumps(
            # "native" needs no configured credentials (UAT2 U11's
            # server-side check); this fixture only needs a rule to exist.
            {"name": "Lock purge rule", "device_id": "TAG-HOME", "channels": ["native"]}
        ),
        headers={"Content-Type": "application/json"},
    )
    assert rule_resp.ok, await rule_resp.text()
    set_resp = await page.request.post(
        base_url + "/api/settings/pin",
        data=json.dumps({"new_pin": PIN}),
        headers={"Content-Type": "application/json"},
    )
    assert set_resp.ok, await set_resp.text()
    enable_resp = await page.request.patch(
        base_url + "/api/settings",
        data=json.dumps({"lock_enabled": True}),
        headers={"Content-Type": "application/json"},
    )
    assert enable_resp.ok, await enable_resp.text()


async def _teardown_purge_fixture(page, base_url):
    """Best-effort unlock first: a failed assertion in the test can leave the
    shared live_server locked, which would 401 the PIN delete below and
    cascade into every test that runs after this file."""
    with contextlib.suppress(Exception):
        await page.request.post(
            f"{base_url}/api/lock/unlock",
            data=json.dumps({"pin": PIN}),
            headers={"Content-Type": "application/json"},
        )
    del_resp = await page.request.delete(
        f"{base_url}/api/settings/pin",
        data=json.dumps({"current_pin": PIN}),
        headers={"Content-Type": "application/json"},
    )
    assert del_resp.ok, await del_resp.text()
    await _delete_rule_named(page, base_url, "Lock purge rule")


async def test_lock_purges_places_groups_and_alerts_from_the_dom(
    page, base_url, reset_alert_and_observation_state
):
    """reviewer-E10 finding: locking only added `.hidden` to #app-shell —
    place/group-member circles stayed in `.leaflet-overlay-pane`, the
    presence panel/legend/group-select kept names, and the alerts rules
    table kept place/device names. Fixed by places.js/groups.js/alerts.js
    each exporting `purge()`, called from lock.js's purgeRenderedData().

    This is a real cold boot (page.goto()), so it owns its fixture data the
    same way test_groups_dialog_purge.py's and test_lock.py's locked-boot
    tests do: `reset_alert_and_observation_state` clears the alert rules and
    deliveries earlier files in the session-scoped suite (test_alerts_*.py)
    create and never delete. Left in place, that accumulation slows the
    cold boot's alerts-tab fetch/render enough that this test's own wait for
    "Lock purge rule" can resolve before the *other* tabs' async renders
    (places/groups) have actually landed, so `_populate_places_groups_alerts`
    intermittently found the map circle and the "Family" verdict but not
    "41.1" (E13 loop3-shaped flake, same root cause, different symptom).
    """
    await _setup_purge_fixture(page, base_url)
    try:
        await page.goto(base_url + "/")
        await page.locator("#app-shell:not(.hidden)").wait_for(state="visible")
        await _populate_places_groups_alerts(page, base_url)

        # Lock via the real UI control, exercising the exact "user is looking
        # at live data and clicks Lock" path reviewer-E10 measured — an
        # api.js-side 401 or a reload would never have exposed this defect.
        await page.click("#btn-lock")
        await page.wait_for_selector("#lock-screen:not(.hidden)")
        await _assert_dom_purged(page)

        # Unlock and confirm everything comes back without a page reload.
        await page.fill("#lock-pin", PIN)
        await page.click("#lock-submit")
        await page.locator("#app-shell:not(.hidden)").wait_for(state="visible")
        await page.click('button[data-tab="places"]')
        await page.wait_for_selector("#map svg path.leaflet-interactive")
        await page.click('button[data-tab="alerts"]')
        row = page.locator("#fp-rules-tbody tr", has_text="Lock purge rule")
        await row.wait_for(state="visible")
    finally:
        await _teardown_purge_fixture(page, base_url)


async def _dialog_input_values(page) -> dict:
    """The place dialog's field values, read as DOM properties.

    `page.content()` serialises markup, and an input's `value` set as a
    property never appears there — which is why the purge test above, and the
    older `test_no_location_data_is_in_the_dom_while_locked` grep, both miss
    this residue entirely. DevTools does not miss it.
    """
    return await page.evaluate(
        """() => {
            const dlg = document.getElementById('fp-place-dialog');
            if (!dlg) return null;
            const inputs = [...dlg.querySelectorAll('input')];
            return {
                open: dlg.open,
                editId: dlg.dataset.editId || '',
                values: inputs.map((i) => i.value).join('|'),
                name: (dlg.querySelector('#fp-place-name') || {}).value || '',
                lat: (dlg.querySelector('#fp-place-lat') || {}).value || '',
            };
        }"""
    )


async def test_lock_purges_the_place_dialog_and_the_webhook_secret(page, base_url):
    """A closed <dialog> still holds the coordinates it was filled with.

    purgeRenderedData()'s contract is that locking DESTROYS rendered location
    data, not that it hides it. places.js only called `dialog.close()`, so the
    hidden lat/lon inputs kept the exact point the dialog opened at and the
    name input kept the place name — both readable from DevTools with the
    lock screen up. The webhook secret input had nothing clearing it at all.

    "Add place" opens the dialog directly at the map's current centre (U4/U10,
    commit eff581d) rather than arming a map-click crosshair, so the dialog is
    already open and modal by the time this test would otherwise click the
    map underneath it — no map click is needed to fill the coordinates.
    """
    await _setup_purge_fixture(page, base_url)
    try:
        await page.goto(base_url + "/")
        await page.locator("#app-shell:not(.hidden)").wait_for(state="visible")

        await page.click('button[data-tab="places"]')
        await page.click("#fp-add-place-btn")
        dialog = page.locator("#fp-place-dialog")
        await dialog.wait_for(state="visible")
        # #fp-place-name, not a bare input[type="text"]: place_locator.js's own
        # opt-in address-search box (U4/U10) is a second text input in this
        # dialog now, and a strict-mode locator rejects an ambiguous match.
        await dialog.locator("#fp-place-name").fill("Safe house")
        # Cancel, not Save: the point is that closing the dialog is not purging it.
        await dialog.get_by_text("Cancel", exact=True).click()
        await page.wait_for_function("() => !document.getElementById('fp-place-dialog').open")

        before = await _dialog_input_values(page)
        assert before["name"] == "Safe house", before
        assert before["lat"], "fixture did not fill the hidden coordinate inputs"

        await page.click('button[data-tab="alerts"]')
        await page.fill("#fp-webhook-secret", "hunter2-not-a-real-secret")

        await page.click("#btn-lock")
        await page.wait_for_selector("#lock-screen:not(.hidden)")

        after = await _dialog_input_values(page)
        assert after["open"] is False
        assert after["name"] == "", after
        assert after["lat"] == "", after
        assert after["editId"] == "", after
        assert "Safe house" not in after["values"], after
        assert await page.input_value("#fp-webhook-secret") == ""
    finally:
        await _teardown_purge_fixture(page, base_url)
