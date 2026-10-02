"""Group dialog: a member that was untracked after joining stays removable (r1 review #2)."""

from __future__ import annotations

import pytest

from .test_groups_dialog import (
    _open_edit_dialog_for,
    _save,
    _set_family_members,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_untracked_member_can_be_unticked_and_removed(page, base_url):
    # TAG-AIR is seeded untracked (cli/tests/ui/_seed_script.py).
    await _set_family_members(page, base_url, ["TAG-HOME", "TAG-AWAY", "TAG-STALE", "TAG-AIR"])
    try:
        await _open_edit_dialog_for(page, base_url, "Family")
        air = page.locator('#fp-group-dialog input[data-device-id="TAG-AIR"]')
        assert await air.is_checked()
        assert await air.is_enabled()
        assert "not tracked" in (await air.locator("xpath=..").inner_text())
        await air.uncheck()
        await _save(page)
        await page.wait_for_function("() => !document.getElementById('fp-group-dialog').open")
        resp = await page.request.get(base_url + "/api/groups")
        family = next(g for g in await resp.json() if g["name"] == "Family")
        assert "TAG-AIR" not in {m["device_id"] for m in family["members"]}
    finally:
        await _set_family_members(page, base_url, ["TAG-HOME", "TAG-AWAY", "TAG-STALE"])
