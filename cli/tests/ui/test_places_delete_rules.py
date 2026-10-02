"""Delete-place confirm dialog states the truth about alert rules (UAT7-N16
remainder).

AlertRule.place_id is `ondelete="CASCADE"` (db/models_alerts.py), so deleting
a place really does delete every alert rule that targets it, not just orphan
them -- these tests pin the confirm dialog's body to that fact: the count
sentence when rules exist, nothing at all when they don't.

Seed data (cli/tests/ui/conftest.py): devices TAG-HOME/TAG-AWAY/TAG-STALE;
place "Home" at (41.1, -80.1) r=200m. Split out of test_places_list.py so
neither file crosses the PRI rule-7 300-line cap.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

HOME_LAT, HOME_LON = 41.100000, -80.100000


async def _open_places_tab(page, base_url):
    await page.goto(base_url + "/")
    await page.click('button[data-tab="places"]')


async def _create_place(page, base_url, name, lon_offset):
    resp = await page.request.post(
        base_url + "/api/places",
        data=json.dumps(
            {
                "name": name,
                "notify": False,
                "latitude": HOME_LAT,
                "longitude": HOME_LON + lon_offset,
                "radius_meters": 60,
            }
        ),
        headers={"Content-Type": "application/json"},
    )
    assert resp.ok, await resp.text()
    return (await resp.json())["id"]


async def _create_rule(page, base_url, place_id, device_id, name):
    resp = await page.request.post(
        base_url + "/api/alerts/rules",
        data=json.dumps(
            {"name": name, "place_id": place_id, "device_id": device_id, "channels": ["native"]}
        ),
        headers={"Content-Type": "application/json"},
    )
    assert resp.ok, await resp.text()
    return (await resp.json())["id"]


async def _open_delete_confirm(page, base_url, place_name):
    await _open_places_tab(page, base_url)
    row = page.locator("#fp-places-list [data-place-id]", has_text=place_name)
    await row.wait_for(state="visible")
    await row.get_by_text("Delete", exact=True).click()
    await page.wait_for_selector("#fp-confirm-dialog[open]")
    return row


async def test_delete_place_with_no_rules_states_nothing_extra(page, base_url):
    await _create_place(page, base_url, "No Rules Here", 0.02)
    row = await _open_delete_confirm(page, base_url, "No Rules Here")
    body = await page.locator("#fp-confirm-dialog-body").inner_text()
    assert body == ""
    await page.locator("#fp-confirm-dialog").get_by_role("button", name="Delete").click()
    await row.wait_for(state="detached")


async def test_delete_place_with_one_rule_uses_the_singular(page, base_url):
    place_id = await _create_place(page, base_url, "Singular Rule Place", 0.03)
    rule_id = await _create_rule(page, base_url, place_id, "TAG-HOME", "Singular rule")
    row = await _open_delete_confirm(page, base_url, "Singular Rule Place")
    body = await page.locator("#fp-confirm-dialog-body").inner_text()
    assert body == "Its 1 alert rule is deleted too."
    await page.locator("#fp-confirm-dialog").get_by_role("button", name="Delete").click()
    await row.wait_for(state="detached")

    rules = await (await page.request.get(base_url + "/api/alerts/rules")).json()
    assert rule_id not in {r["id"] for r in rules}, "the FK cascade must have removed it"


async def test_delete_place_with_two_rules_states_the_count(page, base_url):
    place_id = await _create_place(page, base_url, "Plural Rules Place", 0.04)
    rule_a = await _create_rule(page, base_url, place_id, "TAG-HOME", "Rule A")
    rule_b = await _create_rule(page, base_url, place_id, "TAG-AWAY", "Rule B")
    row = await _open_delete_confirm(page, base_url, "Plural Rules Place")
    body = await page.locator("#fp-confirm-dialog-body").inner_text()
    assert body == "Its 2 alert rules are deleted too."
    await page.locator("#fp-confirm-dialog").get_by_role("button", name="Delete").click()
    await row.wait_for(state="detached")

    rules = await (await page.request.get(base_url + "/api/alerts/rules")).json()
    remaining_ids = {r["id"] for r in rules}
    assert rule_a not in remaining_ids and rule_b not in remaining_ids
