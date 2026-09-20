"""Playwright tests for the device edit dialog and the badge render paths.

Covers P2-E4-W3-S1-T1 (the dialog), T2 (the device-list row), T3 (map markers)
and T4 (the timeline track head).

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
    await page.wait_for_selector("#map")
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
        name = page.locator('.device-row[data-device-id="TAG-HOME"] .d-name')
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
