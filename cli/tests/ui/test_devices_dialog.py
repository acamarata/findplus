"""Playwright tests for the device edit dialog and the badge render paths.

Covers P2-E4-W3-S1-T1 (the dialog), T2 (the device-list row), T3 (map markers)
and T4 (the timeline track head). The boot/CI-regression tests at the bottom
moved in from test_places.py (T1, 2026-09-22): they exercise the same Devices
dialog and had no relation to Places.

Seed (cli/tests/ui/conftest.py): TAG-HOME carries label "Ali's Keys", icon
"lucide:key" and colour "#4f8cf7". `live_server` is session-scoped and shared
with every other file here, so the one test that edits the label puts it back.
"""

from __future__ import annotations

import contextlib
import json

import pytest

from .test_lock import PIN

pytestmark = pytest.mark.asyncio(loop_scope="session")

LABEL = "Ali's Keys"
JSON_HEADERS = {"Content-Type": "application/json"}


async def _open_devices(page, base_url):
    await page.goto(base_url + "/")
    # main.js wires #btn-devices during an async boot. Clicking before the map
    # is up lands on a button with no listener and the dialog never opens.
    await page.wait_for_selector("#map.leaflet-container")
    await page.wait_for_selector('button[data-tab="places"]')
    await page.click("#btn-devices")
    await page.wait_for_selector("#device-modal:not(.hidden)")
    await page.wait_for_selector(".device-row")


async def _open_edit_dialog(page, base_url):
    await _open_devices(page, base_url)
    await page.click('.device-row[data-device-id="TAG-HOME"] .fp-device-edit')
    await page.wait_for_selector("#fp-device-dialog[open]")


async def _set_label(page, base_url, label):
    resp = await page.request.patch(
        f"{base_url}/api/devices/TAG-HOME",
        data=json.dumps({"label": label}),
        headers=JSON_HEADERS,
    )
    assert resp.ok, await resp.text()


async def _open_dashboard(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map.leaflet-container")


async def test_device_row_shows_badge_and_label(page, base_url):
    await _open_devices(page, base_url)
    row = page.locator('.device-row[data-device-id="TAG-HOME"]')
    await row.wait_for(state="visible")
    assert await row.locator(".fp-device-badge svg").count() == 1
    assert await row.locator('.fp-device-badge use[href="#lucide-key"]').count() == 1
    assert LABEL in await row.locator(".d-name").inner_text()
    # The provider's own name is not lost, it moves to the second line.
    assert "Home Tag" in await row.locator(".d-id").inner_text()


async def test_edit_button_opens_dialog_prefilled(page, base_url):
    await _open_edit_dialog(page, base_url)
    assert await page.input_value("#fp-device-label") == LABEL
    assert await page.input_value("#fp-device-icon") == "lucide:key"
    assert await page.input_value("#fp-device-color") == "#4f8cf7"
    assert await page.is_checked("#fp-device-tracked")


async def test_edit_label_saves_and_updates_row(page, base_url):
    await _open_edit_dialog(page, base_url)
    try:
        await page.fill("#fp-device-label", "Renamed Keys")
        await page.click("#fp-device-dialog button:has-text('Save')")
        # A closed <dialog> is display:none, so the default "visible" wait never
        # resolves; "attached" is the state that means "in the DOM, closed".
        await page.wait_for_selector("#fp-device-dialog:not([open])", state="attached")
        # onSave() (devices_dialog.js) closes the dialog as soon as the PATCH
        # resolves, then awaits its onSaved callback (loadDevices +
        # renderDeviceModal) -- so the row above can still read the OLD label
        # for a moment after the dialog is gone. A locator that already
        # matched the row before the save (by device id) proves nothing about
        # its text; has_text re-queries on every retry, the same pattern
        # test_edit_label_updates_the_dashboard_without_a_reload below uses,
        # so this actually waits for the re-render instead of racing it
        # (full-lane order-dependent failure, 2026-09-23 bisection).
        name = page.locator(
            '.device-row[data-device-id="TAG-HOME"] .d-name', has_text="Renamed Keys"
        )
        await name.wait_for(state="visible")
        assert "Renamed Keys" in await name.inner_text()
    finally:
        # The database is shared by every file in this directory.
        await _set_label(page, base_url, LABEL)


async def test_map_marker_embeds_device_icon(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector(".marker-num-glyph svg")
    glyph = page.locator('.marker-num-glyph svg use[href="#lucide-key"]')
    assert await glyph.count() >= 1
    # A jitter point keeps the flat grey disc and draws no badge.
    for marker in await page.locator(".marker-num.jitter").all():
        assert await marker.locator(".marker-num-glyph svg").count() == 0
    # D-P2-15: the marker shows the label too, not only the icon and colour.
    # The hover title is the only text a marker carries (CR-C-E4 F1).
    titles = await page.locator(".leaflet-marker-icon[title]").evaluate_all(
        "els => els.map((e) => e.title)"
    )
    assert any(t.startswith(LABEL) for t in titles), titles
    assert not any(t.startswith("Home Tag") for t in titles), titles


async def test_timeline_swatch_shows_icon_and_label(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector(".track-swatch svg")
    block = page.locator(".track-block", has_text=LABEL)
    assert await block.locator('.track-swatch use[href="#lucide-key"]').count() == 1
    assert LABEL in await block.locator(".track-name").first.inner_text()


async def test_map_marker_and_popup_render_with_no_csp_violation(page, base_url):
    """UAT U25: map.js used to build marker/popup HTML with inline style=""
    attributes, which the daemon's `default-src 'self'` CSP (no unsafe-inline
    for style-src) silently drops -- the ring colour and popup styling were
    gone and the console filled with violation warnings on every load."""
    console_events: list[str] = []
    page.on("console", lambda msg: console_events.append(f"{msg.type}: {msg.text}"))
    await page.goto(base_url + "/")
    await page.wait_for_selector(".marker-num-glyph svg")
    await page.locator(f'.leaflet-marker-icon[title^="{LABEL}"]').first.click()
    await page.wait_for_selector(".leaflet-popup-content")
    popup_text = await page.locator(".leaflet-popup-content").inner_text()
    assert LABEL in popup_text
    violations = [e for e in console_events if "Content Security Policy" in e]
    assert violations == [], f"CSP violations: {violations}"


async def test_edit_label_updates_the_dashboard_without_a_reload(page, base_url):
    """UAT U14: saving a new label/icon/colour in the Devices dialog used to
    leave the map, timeline and topbar showing the stale value until the
    user manually reloaded the page."""
    await _open_edit_dialog(page, base_url)
    try:
        await page.fill("#fp-device-label", "Sara's Keys")
        await page.click("#fp-device-dialog button:has-text('Save')")
        await page.wait_for_selector("#fp-device-dialog:not([open])", state="attached")
        # No page.reload() / page.goto() here: the dashboard behind the
        # dialog must have refreshed itself.
        track_name = page.locator(".track-block", has_text="Sara's Keys").locator(".track-name")
        await track_name.wait_for(state="visible")
        title = page.locator('.leaflet-marker-icon[title^="Sara\'s Keys"]')
        await title.first.wait_for(state="attached")
    finally:
        await _set_label(page, base_url, LABEL)


async def test_purge_on_lock_clears_the_dialog(page, base_url):
    """The dialog holds a device id and a label; a lock has to destroy both.

    `lockNow()` is invoked directly rather than through #btn-lock because an
    open native <dialog> puts the page in the top layer and its backdrop eats
    the click. It is the exact function the button is wired to (lock.js:245),
    not a synthetic event.
    """
    set_pin = await page.request.post(
        base_url + "/api/settings/pin", data=json.dumps({"new_pin": PIN}), headers=JSON_HEADERS
    )
    assert set_pin.ok, await set_pin.text()
    try:
        await _open_edit_dialog(page, base_url)
        await page.evaluate("import('/static/app/lock.js').then((m) => m.lockNow())")
        await page.wait_for_selector("#lock-screen:not(.hidden)")
        # A closed <dialog> is display:none, so the default "visible" wait never
        # resolves; "attached" is the state that means "in the DOM, closed".
        await page.wait_for_selector("#fp-device-dialog:not([open])", state="attached")
        assert await page.input_value("#fp-device-label") == ""
        assert await page.input_value("#fp-device-icon") == ""
        assert await page.evaluate(
            "document.getElementById('fp-device-dialog').dataset.editId === undefined"
        )
        assert LABEL not in await page.content()
    finally:
        with contextlib.suppress(Exception):
            await page.request.post(
                f"{base_url}/api/lock/unlock",
                data=json.dumps({"pin": PIN}),
                headers=JSON_HEADERS,
            )
        del_resp = await page.request.delete(
            f"{base_url}/api/settings/pin",
            data=json.dumps({"current_pin": PIN}),
            headers=JSON_HEADERS,
        )
        assert del_resp.ok, await del_resp.text()


async def test_the_devices_dialog_opens_even_when_a_decoration_fails(page, base_url):
    """CI-2: the device rows rendered but the dialog stayed hidden.

    CI run 35530635344 timed out on `[data-device-id="TAG-HOME"]`: the element
    resolved but was HIDDEN through 61 retries. openDevices() removed `hidden`
    only after renderDeviceModal() returned, so anything that threw while
    filling the dialog left the rows in the DOM and invisible, with no error on
    screen either. The failure is simulated here by deleting the element
    updateModalRate() writes to, which is the same class of fault as whatever
    CI hit; the fix makes the symptom impossible whichever decoration fails.
    """
    await _open_dashboard(page, base_url)

    result = await page.evaluate(
        """async () => {
            const devices = await import('/static/app/devices.js');
            const rate = document.getElementById('device-rate');
            const parent = rate.parentNode;
            const next = rate.nextSibling;
            rate.remove();  // updateModalRate() now throws on a null element
            try {
                await devices.openDevices();
            } finally {
                parent.insertBefore(rate, next);
            }
            const modal = document.getElementById('device-modal');
            const row = document.querySelector('[data-device-id="TAG-HOME"]');
            return {
                hidden: modal.classList.contains('hidden'),
                rows: document.querySelectorAll('#device-list .device-row').length,
                rowVisible: row ? row.offsetParent !== null : false,
            };
        }"""
    )

    assert result["hidden"] is False, "the dialog must open even when a decoration throws"
    assert result["rows"] >= 1, "the rows themselves must still render"
    assert result["rowVisible"] is True, "a row in a hidden dialog is a row nobody can see"

    await page.click("#btn-close-devices")


async def test_booting_does_not_close_a_dialog_the_user_opened(page, base_url):
    """CI-2's actual cause: a click during boot was undone by boot.

    bootDashboard() awaits loadStatus() and loadDay() -- two network round
    trips -- and only then calls applyHashRoute(), which closed every modal
    when the URL carried no hash. The toolbar is live throughout, so a click on
    Devices during that window opened the dialog and boot closed it again,
    leaving the rows in the DOM and invisible. CI run 35530635344 hit it as
    "62 x locator resolved to hidden"; it reproduces locally in the full
    browser job, where the shared page makes the timing vary.
    """
    await _open_dashboard(page, base_url)

    state_after = await page.evaluate(
        """async () => {
            const [devices, main] = await Promise.all([
                import('/static/app/devices.js'),
                import('/static/app/main.js'),
            ]);
            await devices.openDevices();          // the user clicks Devices
            await main.applyHashRoute({ closeOthers: false });   // boot catches up
            const modal = document.getElementById('device-modal');
            const row = document.querySelector('[data-device-id="TAG-HOME"]');
            return {
                hidden: modal.classList.contains('hidden'),
                rowVisible: row ? row.offsetParent !== null : false,
            };
        }"""
    )

    assert state_after["hidden"] is False, "boot closed the dialog the user had opened"
    assert state_after["rowVisible"] is True

    # A real hashchange away from a dialog still closes it.
    closed = await page.evaluate(
        """async () => {
            const main = await import('/static/app/main.js');
            await main.applyHashRoute();
            return document.getElementById('device-modal').classList.contains('hidden');
        }"""
    )
    assert closed is True, "an explicit route change must still close the dialog"


async def test_the_devices_dialog_opens_normally(page, base_url):
    """The control: nothing failing, the dialog still opens with visible rows."""
    await _open_dashboard(page, base_url)
    await page.click("#btn-devices")
    await page.wait_for_selector('[data-device-id="TAG-HOME"]', state="visible")

    assert await page.locator("#device-modal").is_visible()
