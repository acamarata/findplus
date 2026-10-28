"""A stale member that is not tracked says so (UAT #12).

"Never Seen 12 has no fix yet" blamed the tracker when the real reason is that
Find+ is not polling it. The stale list now uses the same "not tracked" wording
as the Devices and group dialogs. A tracked member with no fix keeps "no fix yet".
"""

from __future__ import annotations

import pytest

from ._roster17 import forget_groups, roster17

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_untracked_member_reads_not_tracked(page, base_url, ui_db, ui_env):
    with roster17(ui_db, ui_env, tracked=10):
        try:
            made = await page.request.post(
                base_url + "/api/groups",
                data={"name": "T17 untracked", "member_ids": ["R17-05", "R17-12"]},
            )
            assert made.ok, await made.text()
            await page.goto(base_url + "/")
            await page.wait_for_selector("#app-shell[data-fp-ready='dashboard']")
            await page.select_option("#fp-group-select", label="T17 untracked")
            await page.click('button[data-tab="people"]')
            badges = page.locator("#fp-stale-list .fp-stale-badge")
            await badges.first.wait_for()
            texts = await badges.all_inner_texts()
            assert any(t == "Never Seen 12: not tracked, so Find+ is not polling it" for t in texts)
            assert any(t == "Tag 5: no fix yet" for t in texts)
        finally:
            forget_groups(ui_db, "T17 untracked")
