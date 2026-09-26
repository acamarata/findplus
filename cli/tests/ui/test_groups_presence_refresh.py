"""Playwright browser tests for the Groups presence panel staying in sync
with a save or a delete of the selected group (UAT4 N31).

Purpose    : Before this fix, groups_dialog.js's onSaved callback (wired to
             loadGroups()) only refreshed the group selector and the card
             grid. A stale-after edit saved on the group currently shown in
             `#fp-presence-panel` left that panel showing the pre-edit
             verdict and note until the group was reselected or the page
             reloaded. Deleting the selected group had the same gap:
             groups_list.js's onDelete() never checked whether the group it
             just removed was the one the panel was drawn from.
Inputs     : live_server (conftest.py, shared with test_groups.py/
             test_groups_dialog.py); the seeded "Family" group and its
             members (TAG-HOME, TAG-AWAY, TAG-STALE).
Constraints: Split out of test_groups_dialog.py rather than added to it
             (PRI rule 7, 300-line file cap already nearly full there);
             reuses its dialog helpers instead of duplicating them, the same
             pattern test_groups_dialog_purge.py already established.
"""

from __future__ import annotations

import json

import pytest

from .test_groups import _open_group
from .test_groups_dialog import _delete_group_named, _family_id, _open_add_dialog, _save

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_stale_after_edit_refreshes_presence_panel_without_reselect(page, base_url):
    """The seed's TAG-HOME/TAG-AWAY are always fresh and TAG-STALE has never
    reported, so a stale-after edit alone would not change Family's verdict
    text either way -- pinning specific wording would not actually prove the
    panel refreshed. What N31 broke is the wiring: saving the dialog used to
    fire no second presence fetch at all for the selected group. Proven here
    at the network layer instead.
    """
    await _open_group(page, base_url)  # selects "Family" via the dropdown
    family_id = await _family_id(page, base_url)

    card = page.locator(".fp-group-card", has_text="Family")
    await card.locator(".fp-card-edit").click()
    await page.wait_for_selector("#fp-group-dialog[open]")
    try:
        await page.fill("#fp-group-stale", "75")
        async with page.expect_response(
            lambda r: f"/api/groups/{family_id}/presence" in r.url and r.request.method == "GET"
        ):
            await _save(page)
        await page.wait_for_function("() => !document.getElementById('fp-group-dialog').open")
    finally:
        await page.request.put(
            f"{base_url}/api/groups/{family_id}",
            data=json.dumps({"stale_after_minutes": 90}),
            headers={"Content-Type": "application/json"},
        )


async def test_delete_selected_group_clears_presence_panel(page, base_url):
    """Deleting the group the panel is currently showing must clear it, not
    leave the deleted group's verdict/stale list on screen with no group left
    behind it to reselect."""
    await _open_add_dialog(page, base_url)
    await page.fill("#fp-group-name", "Doomed Group")
    await page.check('#fp-group-members input[data-device-id="TAG-HOME"]')
    await _save(page)
    await page.locator(".fp-group-card", has_text="Doomed Group").wait_for(state="visible")

    await page.select_option("#fp-group-select", label="Doomed Group")
    await page.wait_for_selector("#fp-presence-panel .fp-verdict")

    # 108c1cd replaced window.confirm() with the shared #fp-confirm-dialog.
    try:
        card = page.locator(".fp-group-card", has_text="Doomed Group")
        await card.locator(".fp-card-delete").click()
        await page.wait_for_selector("#fp-confirm-dialog[open]")
        await page.locator("#fp-confirm-dialog").get_by_role("button", name="Delete").click()
        await page.locator(".fp-group-card", has_text="Doomed Group").wait_for(state="detached")
        await page.wait_for_function(
            "() => document.getElementById('fp-presence-panel').children.length === 0"
        )
        assert await page.locator("#fp-group-select").input_value() == ""
    finally:
        await _delete_group_named(page, base_url, "Doomed Group")
