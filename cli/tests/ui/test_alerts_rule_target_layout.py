"""Browser test for the add-rule dialog's Device/Group target row layout
(UAT7 N13, UAT6 N25 residue). Split into its own small file rather than
folding into test_alerts_rule_channels.py, which is about the channel
picker, not the target selects.
"""

from __future__ import annotations

import pytest

from .conftest import open_alerts_tab

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_group_select_renders_disabled_without_moving_the_row(page, base_url):
    """UAT7 N13: the Group select is disabled, not hidden, until its radio is
    picked -- both target rows are laid out identically from the dialog's
    first paint, so picking Group only enables the existing control instead
    of growing one into existence (the "layout jump" UAT6 N25 left behind).
    """
    put_resp = await page.request.put(
        base_url + "/api/alerts/channels/webhook",
        data='{"url": "https://example.com/hook"}',
        headers={"Content-Type": "application/json"},
    )
    assert put_resp.ok, await put_resp.text()
    try:
        await open_alerts_tab(page, base_url)
        await page.click("#fp-add-rule-btn")
        await page.wait_for_selector("#fp-add-rule-dialog[open]")
        await page.wait_for_function(
            "document.querySelector("
            "'#fp-rule-channels input[data-channel=webhook]')?.checked === true"
        )

        group_select = page.locator("#fp-rule-group")
        device_select = page.locator("#fp-rule-device")
        # Rendered and laid out (never `hidden`) from the first paint, only
        # disabled -- the row's own box is the same box the row will have
        # once Group is picked.
        assert await group_select.is_visible()
        assert await group_select.is_disabled()
        assert await device_select.is_enabled()
        row = page.locator(".fp-rule-target-row:has(#fp-rule-group)")
        box_before = await row.bounding_box()

        await page.check("#fp-rule-target-group")
        box_after = await row.bounding_box()

        assert await group_select.is_enabled()
        assert await device_select.is_disabled()
        assert box_before == box_after, "the Group row's own box moved when it was picked"
    finally:
        await page.request.delete(base_url + "/api/alerts/channels/webhook")
