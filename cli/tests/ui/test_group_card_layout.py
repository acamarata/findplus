"""Groups tab: the card's Edit/Delete pair at phone width (UAT3 N24).

Purpose    : Edit and Delete stay together on one row at 375px, whatever the
             group, and do not move once the card's presence verdict fills in.
Inputs     : live_server (conftest.py), seeded groups "Home" and "Family".
Outputs    : none (assertions only).
Constraints: Moved out of test_responsive.py (300-line cap). The verdict pill
             is filled by fetchVerdict() after the card renders (groups_list.js),
             so every measurement waits for that settled state and reads both
             boxes in one evaluate(): two separate bounding_box() calls
             straddled the verdict arriving on the CI runner and saw Edit on
             one row and Delete on the next (run 35909159774).
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

PHONE_WIDTH = 375
PHONE_HEIGHT = 812

_ACTION_BOXES = """(groupId) => {
  const sel = groupId === null ? ".fp-group-card" : `.fp-group-card[data-group-id="${groupId}"]`;
  const card = document.querySelector(sel);
  const box = (cls) => card.querySelector(cls).getBoundingClientRect().toJSON();
  return { card: card.getBoundingClientRect().toJSON(), edit: box(".fp-card-edit"),
           del: box(".fp-card-delete") };
}"""

_VERDICTS_SETTLED = """() => {
  const cards = document.querySelectorAll(".fp-group-card");
  const settled = document.querySelectorAll(".fp-group-card .fp-verdict");
  return cards.length > 0 && settled.length === cards.length;
}"""


async def _open_groups_at_phone_width(page, base_url) -> None:
    await page.set_viewport_size({"width": PHONE_WIDTH, "height": PHONE_HEIGHT})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell:not(.hidden)")
    await page.click('.fp-tabbar [data-tabbar-tab="groups"]')
    await page.wait_for_selector("#tab-groups:not([hidden])")
    await page.wait_for_selector(".fp-group-card", state="visible")


def _assert_pair_on_one_row(boxes: dict) -> None:
    edit, delete, card = boxes["edit"], boxes["del"], boxes["card"]
    assert abs(edit["y"] - delete["y"]) < 2, f"Edit and Delete are on different rows: {boxes}"
    assert edit["x"] + edit["width"] <= delete["x"], boxes
    assert delete["x"] + delete["width"] <= card["x"] + card["width"] + 1, boxes


async def test_group_card_edit_and_delete_stay_on_one_row(page, base_url):
    """UAT3 N24: Edit and Delete were separate flex-wrap items on the group
    card, so a narrow card could wrap between them. One `.fp-card-actions`
    unit keeps the pair together, on one row, at phone width."""
    await _open_groups_at_phone_width(page, base_url)
    await page.wait_for_function(_VERDICTS_SETTLED, timeout=15000)
    _assert_pair_on_one_row(await page.evaluate(_ACTION_BOXES, None))


async def test_group_card_actions_do_not_move_when_the_verdict_arrives(page, base_url):
    """The verdict pill fills in after the card renders. At 375px it used to
    push the Edit/Delete pair down a row (1058 -> 1090 on the seeded "Home"
    card), moving the buttons out from under a tap already on its way."""
    release = asyncio.Event()

    async def hold_presence(route):
        await release.wait()
        await route.continue_()

    await page.route("**/api/groups/*/presence*", hold_presence)
    await _open_groups_at_phone_width(page, base_url)
    before = await page.evaluate(_ACTION_BOXES, None)
    release.set()
    await page.wait_for_function(_VERDICTS_SETTLED, timeout=15000)
    after = await page.evaluate(_ACTION_BOXES, None)
    assert after["edit"]["y"] == before["edit"]["y"], (before, after)
    assert after["del"]["y"] == before["del"]["y"], (before, after)
