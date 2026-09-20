"""Playwright browser tests for the group dialog and card grid (P2-E5-W3-S1-T4).

Seed data (cli/tests/ui/conftest.py): group "Family" with 3 members — TAG-HOME
and TAG-AWAY (fresh fixes ~50m apart) and TAG-STALE (never reported). Every
case here creates, edits or deletes through the UI and puts the shared
session-scoped server back the way it found it, because `live_server` is shared
with test_groups.py, test_lock*.py and test_places.py.
"""

from __future__ import annotations

import contextlib
import json

import pytest

from .test_lock import PIN
from .test_lock_purge import _setup_purge_fixture, _teardown_purge_fixture

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_groups_tab(page, base_url):
    await page.goto(base_url + "/")
    # #tab-groups is `hidden` until its tab is clicked, so everything inside it
    # is attached long before it is visible; waiting for visibility first can
    # never resolve (matches test_groups.py's own note about the panel).
    await page.wait_for_selector("#fp-add-group-btn", state="attached")
    await page.click('button[data-tab="groups"]')
    await page.wait_for_selector("#fp-add-group-btn", state="visible")
    await page.wait_for_selector(".fp-group-card, .fp-empty-state", state="attached")


async def _open_add_dialog(page, base_url):
    await _open_groups_tab(page, base_url)
    await page.click("#fp-add-group-btn")
    await page.wait_for_selector("#fp-group-dialog[open]")


async def _save(page):
    await page.locator("#fp-group-dialog").get_by_role("button", name="Save").click()


async def _delete_group_named(page, base_url, name):
    """Remove a group the API way, so one test's leftovers never reach the next."""
    resp = await page.request.get(base_url + "/api/groups")
    for group in await resp.json():
        if group["name"] == name:
            await page.request.delete(f"{base_url}/api/groups/{group['id']}")


async def _family_id(page, base_url) -> int:
    resp = await page.request.get(base_url + "/api/groups")
    return next(g["id"] for g in await resp.json() if g["name"] == "Family")


async def _set_family_members(page, base_url, member_ids):
    group_id = await _family_id(page, base_url)
    await page.request.put(
        f"{base_url}/api/groups/{group_id}/members",
        data=json.dumps({"member_ids": member_ids}),
        headers={"Content-Type": "application/json"},
    )


async def _open_edit_dialog_for(page, base_url, name):
    await _open_groups_tab(page, base_url)
    card = page.locator(".fp-group-card", has_text=name)
    await card.locator(".fp-card-edit").click()
    await page.wait_for_selector("#fp-group-dialog[open]")


async def test_add_group_button_opens_dialog(page, base_url):
    await _open_groups_tab(page, base_url)
    await page.click("#fp-add-group-btn")
    # showAddDialog() fetches the member list before it calls showModal(), so
    # the dialog opens a round trip after the click, never synchronously.
    await page.wait_for_selector("#fp-group-dialog[open]")
    assert await page.locator("#fp-group-dialog").get_attribute("open") is not None


async def test_create_group_appears_in_list_and_selector(page, base_url):
    """One fetched list, two renderings: the card grid and the selector agree."""
    try:
        await _open_add_dialog(page, base_url)
        await page.fill("#fp-group-name", "Weekend Trip")
        await _save(page)
        await page.locator(".fp-group-card", has_text="Weekend Trip").wait_for(state="visible")
        options = page.locator("#fp-group-select option", has_text="Weekend Trip")
        assert await options.count() == 1
    finally:
        await _delete_group_named(page, base_url, "Weekend Trip")


async def test_create_group_validation_error_shows_in_dialog(page, base_url):
    """Save is type="button", so `required` never fires — onSave's own check does."""
    await _open_add_dialog(page, base_url)
    await page.fill("#fp-group-name", "")
    await _save(page)
    error = page.locator("#fp-group-dialog-error")
    assert (await error.inner_text()).strip() == "Name is required."
    assert await page.locator("#fp-group-dialog").get_attribute("open") is not None


async def test_edit_group_prefills_fields(page, base_url):
    await _open_edit_dialog_for(page, base_url, "Family")
    assert await page.input_value("#fp-group-name") == "Family"
    assert await page.input_value("#fp-group-quorum") == "majority"


async def test_edit_group_saves_changes(page, base_url):
    try:
        await _open_edit_dialog_for(page, base_url, "Family")
        # A range input cannot be page.fill()ed; setting the property and
        # dispatching `input` is what a drag does as far as the page knows.
        await page.evaluate(
            """() => {
                const r = document.getElementById('fp-group-radius');
                r.value = '300';
                r.dispatchEvent(new Event('input', { bubbles: true }));
            }"""
        )
        await _save(page)
        await page.wait_for_function("() => !document.getElementById('fp-group-dialog').open")
        await _open_edit_dialog_for(page, base_url, "Family")
        assert await page.input_value("#fp-group-radius") == "300"
    finally:
        group_id = await _family_id(page, base_url)
        await page.request.put(
            f"{base_url}/api/groups/{group_id}",
            data=json.dumps({"cluster_radius_meters": 150}),
            headers={"Content-Type": "application/json"},
        )


async def test_add_remove_member_updates_presence_panel(page, base_url):
    try:
        await _open_edit_dialog_for(page, base_url, "Family")
        await page.uncheck('#fp-group-members input[data-device-id="TAG-AWAY"]')
        await _save(page)
        await page.wait_for_function("() => !document.getElementById('fp-group-dialog').open")
        await page.select_option("#fp-group-select", label="Family")
        await page.wait_for_selector("#fp-presence-panel .fp-verdict")
        panel = await page.locator("#fp-presence-panel").inner_text()
        assert "Away Tag" not in panel, panel
    finally:
        await _set_family_members(page, base_url, ["TAG-HOME", "TAG-AWAY", "TAG-STALE"])


async def test_delete_group_confirm_cancel_keeps_group(page, base_url):
    await _open_groups_tab(page, base_url)

    def dismiss(dialog):
        return dialog.dismiss()

    # Registered BEFORE the click: a handler attached afterwards races the
    # confirm() and Playwright's auto-dismiss would pass the test for the
    # wrong reason.
    page.on("dialog", dismiss)
    try:
        card = page.locator(".fp-group-card", has_text="Family")
        await card.locator(".fp-card-delete").click()
        await page.wait_for_timeout(200)
        assert await page.locator(".fp-group-card", has_text="Family").count() == 1
    finally:
        page.remove_listener("dialog", dismiss)


async def test_delete_group_confirm_removes_from_list_and_selector(page, base_url):
    await _open_add_dialog(page, base_url)
    await page.fill("#fp-group-name", "Temp Group")
    await _save(page)
    await page.locator(".fp-group-card", has_text="Temp Group").wait_for(state="visible")

    def accept(dialog):
        return dialog.accept()

    page.on("dialog", accept)
    try:
        card = page.locator(".fp-group-card", has_text="Temp Group")
        await card.locator(".fp-card-delete").click()
        await page.locator(".fp-group-card", has_text="Temp Group").wait_for(state="detached")
        assert await page.locator("#fp-group-select option", has_text="Temp Group").count() == 0
    finally:
        page.remove_listener("dialog", accept)
        await _delete_group_named(page, base_url, "Temp Group")


async def test_duplicate_name_shows_409_on_name_field(page, base_url):
    """The server's own words, in the dialog, with the dialog still open."""
    await _open_add_dialog(page, base_url)
    await page.fill("#fp-group-name", "Family")
    await _save(page)
    error = page.locator("#fp-group-dialog-error")
    await error.wait_for(state="visible")
    assert "already exists" in await error.inner_text()
    assert await page.locator("#fp-group-dialog").get_attribute("open") is not None


async def test_quorum_custom_reveals_number_input(page, base_url):
    await _open_add_dialog(page, base_url)
    assert await page.locator("#fp-group-quorum-n").get_attribute("hidden") is not None
    await page.select_option("#fp-group-quorum", "custom")
    assert await page.locator("#fp-group-quorum-n").get_attribute("hidden") is None


async def test_dialog_closes_on_escape(page, base_url):
    await _open_add_dialog(page, base_url)
    await page.keyboard.press("Escape")
    await page.wait_for_function("() => !document.getElementById('fp-group-dialog').open")
    assert await page.locator("#fp-group-dialog").get_attribute("open") is None


async def _group_dialog_state(page) -> dict:
    """The dialog's live field values, which page.content() never serialises."""
    return await page.evaluate(
        """() => {
            const dlg = document.getElementById('fp-group-dialog');
            if (!dlg) return null;
            return {
                open: dlg.open,
                editId: dlg.dataset.editId || '',
                name: document.getElementById('fp-group-name').value,
                texts: [...dlg.querySelectorAll('input[type=text]')].map((i) => i.value).join('|'),
                members: dlg.querySelectorAll('#fp-group-members input').length,
            };
        }"""
    )


async def test_purge_on_lock_clears_dialog_and_cards(page, base_url):
    """A closed dialog still holds the group name and every member's name."""
    await _setup_purge_fixture(page, base_url)
    try:
        await _open_edit_dialog_for(page, base_url, "Family")
        before = await _group_dialog_state(page)
        assert before["name"] == "Family", before
        assert before["members"] >= 3, before
        assert await page.locator(".fp-group-card").count() >= 1

        # The dialog is deliberately left open, and a modal <dialog> swallows
        # pointer events aimed at anything behind it, so the click is
        # dispatched rather than performed. It still runs lock.js's own
        # handler, which is what this test is about.
        await page.locator("#btn-lock").dispatch_event("click")
        await page.wait_for_selector("#lock-screen:not(.hidden)")

        after = await _group_dialog_state(page)
        assert after["open"] is False, after
        assert after["name"] == "", after
        assert after["texts"] == "", after
        assert after["editId"] == "", after
        assert after["members"] == 0, after
        assert await page.locator("#fp-groups-list .fp-group-card").count() == 0
        assert "Family" not in await page.content()
    finally:
        with contextlib.suppress(Exception):
            await page.fill("#lock-pin", PIN)
            await page.click("#lock-submit")
        await _teardown_purge_fixture(page, base_url)


async def test_purge_on_a_locked_boot_does_not_throw(page, base_url):
    """clearGroup() runs before groups.js has a map, so overlayLayer is null.

    T0's wave-2 visual gate caught `Cannot read properties of null (reading
    'clearLayers')` on the lock path — the one path that must never throw,
    because everything after it in purgeRenderedData() stops running.
    """
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on(
        "console",
        lambda msg: errors.append(msg.text) if msg.type == "error" else None,
    )
    await _setup_purge_fixture(page, base_url)
    try:
        await page.request.post(base_url + "/api/lock/lock")
        await page.goto(base_url + "/")
        await page.wait_for_selector("#lock-screen:not(.hidden)")
        assert not [e for e in errors if "clearLayers" in e or "of null" in e], errors
        await page.fill("#lock-pin", PIN)
        await page.click("#lock-submit")
        await page.locator("#app-shell:not(.hidden)").wait_for(state="visible")
    finally:
        await _teardown_purge_fixture(page, base_url)
