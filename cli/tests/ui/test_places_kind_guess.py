"""A place kind Find+ guessed from the name asks to be confirmed (review r116 #8).

Upgraded places get their kind from the name ("Home" -> home) and a new place
added without a pick does too; either way the list card says it was a guess
and offers a one-tap confirm, which clears the flag.

Seed data (cli/tests/ui/conftest.py): place "Home" at (41.1, -80.1).
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_guessed_kind_row_confirms_in_one_tap(page, base_url):
    resp = await page.request.post(
        base_url + "/api/places",
        data=json.dumps(
            {
                "name": "Robin's School",
                "notify": False,
                "latitude": 41.11,
                "longitude": -80.12,
                "radius_meters": 80,
            }
        ),
        headers={"Content-Type": "application/json"},
    )
    assert resp.ok, await resp.text()
    place_id = (await resp.json())["id"]
    try:
        await page.goto(base_url + "/")
        await page.click('button[data-tab="places"]')
        card = page.locator(f'.fp-place-card[data-place-id="{place_id}"]')
        row = card.locator(".fp-place-kind-guess")
        await row.wait_for(state="visible")
        assert "School, guessed from the name" in await row.inner_text()
        await row.get_by_role("button", name="Confirm that Robin's School is School").click()
        await row.wait_for(state="detached")
        places = await (await page.request.get(base_url + "/api/places")).json()
        mine = next(p for p in places if p["id"] == place_id)
        assert (mine["kind"], mine["kind_guessed"]) == ("school", False)
    finally:
        await page.request.delete(f"{base_url}/api/places/{place_id}")
