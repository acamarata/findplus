"""Delete-group confirm dialog states the truth about alert rules (UAT7-N16
remainder), the group-side twin of test_places_delete_rules.py.

AlertRule.group_id is `ondelete="CASCADE"` (db/models_alerts.py) too, so
deleting a group deletes every rule that targets it. Split out of
test_groups_dialog.py, already at the PRI rule-7 300-line cap.

Seed data (cli/tests/ui/conftest.py): group "Family" with 3 members. These
tests create their own throw-away groups so "Family" is never touched.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_groups_tab(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#fp-add-group-btn", state="attached")
    await page.click('button[data-tab="people"]')
    await page.wait_for_selector('[data-fp-ready="groups"]')


async def _create_group(page, base_url, name):
    resp = await page.request.post(
        base_url + "/api/groups",
        data=json.dumps({"name": name, "member_ids": ["TAG-HOME"]}),
        headers={"Content-Type": "application/json"},
    )
    assert resp.ok, await resp.text()
    return (await resp.json())["id"]


async def _create_rule(page, base_url, group_id, name):
    resp = await page.request.post(
        base_url + "/api/alerts/rules",
        data=json.dumps({"name": name, "group_id": group_id, "channels": ["native"]}),
        headers={"Content-Type": "application/json"},
    )
    assert resp.ok, await resp.text()
    return (await resp.json())["id"]


async def _open_delete_confirm(page, base_url, group_name):
    await _open_groups_tab(page, base_url)
    card = page.locator(".fp-group-card", has_text=group_name)
    await card.locator(".fp-card-delete").click()
    await page.wait_for_selector("#fp-confirm-dialog[open]")
    return card


async def test_delete_group_with_no_rules_states_nothing_extra(page, base_url):
    await _create_group(page, base_url, "No Rules Group")
    card = await _open_delete_confirm(page, base_url, "No Rules Group")
    body = await page.locator("#fp-confirm-dialog-body").inner_text()
    assert body == ""
    await page.locator("#fp-confirm-dialog").get_by_role("button", name="Delete").click()
    await card.wait_for(state="detached")


async def test_delete_group_with_rules_states_the_count(page, base_url):
    group_id = await _create_group(page, base_url, "Rules Group")
    rule_a = await _create_rule(page, base_url, group_id, "Group Rule A")
    rule_b = await _create_rule(page, base_url, group_id, "Group Rule B")
    card = await _open_delete_confirm(page, base_url, "Rules Group")
    body = await page.locator("#fp-confirm-dialog-body").inner_text()
    assert body == "Its 2 alert rules are deleted too."
    await page.locator("#fp-confirm-dialog").get_by_role("button", name="Delete").click()
    await card.wait_for(state="detached")

    rules = await (await page.request.get(base_url + "/api/alerts/rules")).json()
    remaining_ids = {r["id"] for r in rules}
    assert rule_a not in remaining_ids and rule_b not in remaining_ids
