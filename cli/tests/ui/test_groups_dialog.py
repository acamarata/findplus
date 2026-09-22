"""Playwright browser tests for the group dialog and card grid (P2-E5-W3-S1-T4).

Seed data (cli/tests/ui/conftest.py): group "Family" with 3 members — TAG-HOME
and TAG-AWAY (fresh fixes ~50m apart) and TAG-STALE (never reported). Every
case here creates, edits or deletes through the UI and puts the shared
session-scoped server back the way it found it, because `live_server` is shared
with test_groups.py, test_lock*.py and test_places.py. The purge-on-lock cases
moved to test_groups_dialog_purge.py at the 300-line file cap; it imports
`_open_edit_dialog_for` from here.
"""

from __future__ import annotations

import json

import pytest

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
        await page.check('#fp-group-members input[data-device-id="TAG-HOME"]')
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


async def test_create_group_with_no_members_blocks_save(page, base_url):
    """UAT U16: a zero-member group used to save silently and then show
    "Unknown" in the list. Save must refuse and explain why."""
    await _open_add_dialog(page, base_url)
    await page.fill("#fp-group-name", "No Members")
    await _save(page)
    error = page.locator("#fp-group-dialog-error")
    assert (await error.inner_text()).strip() == "Select at least one member."
    assert await page.locator("#fp-group-dialog").get_attribute("open") is not None
    assert await page.locator(".fp-group-card", has_text="No Members").count() == 0


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
    await page.check('#fp-group-members input[data-device-id="TAG-HOME"]')
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
    await page.check('#fp-group-members input[data-device-id="TAG-HOME"]')
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


async def test_dialog_async_guard_and_live_icon_preview(page, base_url):
    """CR-C-E5 F6/F7, one dialog session: fillDialog() rejecting (the devices
    fetch fails) must not be an unhandled rejection, and once it recovers the
    letter badge must track the name field as it is typed."""
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    await _open_groups_tab(page, base_url)
    await page.route("**/api/devices", lambda route: route.abort())
    await page.click("#fp-add-group-btn")
    await page.wait_for_selector("#fp-group-dialog[open]")
    error = page.locator("#fp-group-dialog-error")
    await error.wait_for(state="visible")
    assert (await error.inner_text()).strip()
    assert not errors, errors
    await page.unroute("**/api/devices")

    await page.click("#fp-group-icon-btn")
    await page.click('#fp-group-icon-popover [data-icon-id="letter"]')
    await page.fill("#fp-group-name", "Weekend Trip")
    # An SVG <text> is not an HTMLElement, so inner_text() rejects it.
    assert await page.locator("#fp-group-icon-btn svg text").text_content() == "W"


async def test_dialog_closes_on_escape(page, base_url):
    await _open_add_dialog(page, base_url)
    await page.keyboard.press("Escape")
    await page.wait_for_function("() => !document.getElementById('fp-group-dialog').open")
    assert await page.locator("#fp-group-dialog").get_attribute("open") is None


async def test_icon_and_color_pickers_populate_on_a_cold_open(page, base_url):
    """Visual gate W3 finding 1: the closed colour button had no content at
    all (build-notes.md § W3 gate fixes), and nothing exercised the colour
    popover before. This is a fresh page (no dialog opened earlier in the
    test), so ensurePickers() runs for the first time here — the "cold page,
    no prior sprite fetch" case the fix's root-cause note calls out."""
    await _open_groups_tab(page, base_url)
    await page.click("#fp-add-group-btn")
    await page.wait_for_selector("#fp-group-dialog[open]")

    # Closed state: both trigger buttons show a swatch, not an empty pill.
    icon_html = await page.locator("#fp-group-icon-btn").inner_html()
    color_bg = await page.locator("#fp-group-color-btn").evaluate(
        "el => getComputedStyle(el).backgroundColor"
    )
    assert icon_html.strip()
    assert color_bg not in ("rgba(0, 0, 0, 0)", "transparent")

    await page.click("#fp-group-icon-btn")
    icon_count = await page.locator("#fp-group-icon-popover .fp-icon-swatch").count()
    assert icon_count >= 40, icon_count
    # The icon grid is tall enough to sit over the colour row below it; close
    # it the same way a user would (re-click its own trigger) before opening
    # the colour popover, rather than clicking through it.
    await page.click("#fp-group-icon-btn")
    await page.wait_for_selector("#fp-group-icon-popover", state="hidden")

    await page.click("#fp-group-color-btn")
    color_count = await page.locator("#fp-group-color-popover .fp-color-swatch").count()
    assert color_count == 12, color_count
