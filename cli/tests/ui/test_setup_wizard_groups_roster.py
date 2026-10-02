"""Wizard Groups step with a real first-sign-in roster (17 devices, no fixes yet).

Purpose    : Same awkward data as test_groups_real_roster.py, but through the
             setup wizard's own member list and Add button: untracked devices,
             shared names, apostrophes, several groups added in a row.
Inputs     : live_server, ui_db / ui_env, `_roster17`.
Outputs    : none (assertions only).
Constraints: Runs against a never-onboarded install and restores the seeded
             completion afterwards, like the other wizard files. Groups made
             here start with "T17" and are removed by `roster17`.
"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio

from ._roster17 import NAMES, PREFIX, roster17
from .conftest import SEEDED_COMPLETED_AT

pytestmark = pytest.mark.asyncio(loop_scope="session")

MEMBERS = "#fp-setup-group-members"


async def _post(page, base_url, path, value):
    return await page.request.post(
        base_url + path, data=json.dumps(value), headers={"Content-Type": "application/json"}
    )


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _unfinished(page, base_url):
    await _post(page, base_url, "/api/settings/onboarding.completed_at", {"value": None})
    await _post(page, base_url, "/api/settings/onboarding.last_step", {"value": "groups"})
    try:
        yield
    finally:
        await _post(
            page, base_url, "/api/settings/onboarding.completed_at", {"value": SEEDED_COMPLETED_AT}
        )
        await _post(page, base_url, "/api/settings/onboarding.last_step", {"value": None})


async def _open_step(page, base_url):
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#fp-setup-group-name", timeout=15000)
    await page.wait_for_selector(f"{MEMBERS} .fp-member-row, {MEMBERS} .fp-members-hint")


async def test_untracked_devices_are_listed_disabled_with_the_reason(page, base_url, ui_db, ui_env):
    with roster17(ui_db, ui_env, tracked=10):
        await _open_step(page, base_url)
        assert await page.locator(f"{MEMBERS} input:not([disabled])").count() == 13
        assert await page.locator(f"{MEMBERS} input[disabled]").count() == 8
        note = await page.locator(f"{MEMBERS} .fp-members-hint").first.inner_text()
        assert "8 devices are not tracked" in note and "Devices" in note


async def test_nothing_tracked_names_the_count_and_the_way_forward(page, base_url, ui_db, ui_env):
    with roster17(ui_db, ui_env, tracked=0):
        await _post(page, base_url, "/api/devices/track", {"device_ids": []})
        try:
            await _open_step(page, base_url)
            text = await page.locator(MEMBERS).inner_text()
            assert f"None of your {len(NAMES) + 4} devices are tracked yet" in text
            assert "Go back to Devices" in text
        finally:
            await _post(
                page,
                base_url,
                "/api/devices/track",
                {"device_ids": ["TAG-HOME", "TAG-AWAY", "TAG-STALE"]},
            )


async def test_select_all_and_several_adds_in_a_row(page, base_url, ui_db, ui_env):
    with roster17(ui_db, ui_env, tracked=10):
        await _open_step(page, base_url)
        for n in (1, 2, 3):
            name = f"T17 Wizard {n}'s"
            await page.fill("#fp-setup-group-name", name)
            if n == 1:
                await page.click(f"{MEMBERS} .fp-members-all")
            else:
                await page.locator(f"{MEMBERS} input:not([disabled])").first.check()
            await page.click("#fp-setup-group-add")
            await page.locator("#fp-setup-groups-list", has_text=name).wait_for()
            # Add resets the form: name cleared, nothing left ticked.
            await page.wait_for_function(
                "() => document.getElementById('fp-setup-group-name').value === ''"
            )
            assert await page.locator(f"{MEMBERS} input:checked").count() == 0
        listed = await page.locator("#fp-setup-groups-list").inner_text()
        assert "13 devices" in listed and "1 device" in listed
        groups = await (await page.request.get(base_url + "/api/groups")).json()
        first = next(g for g in groups if g["name"] == "T17 Wizard 1's")
        assert len(first["members"]) == 13
        assert all(m["device_id"].startswith(("TAG-", PREFIX)) for m in first["members"])


async def test_duplicate_name_error_quotes_what_was_typed(page, base_url, ui_db, ui_env):
    with roster17(ui_db, ui_env, tracked=10):
        await _open_step(page, base_url)
        name = "T17 Ali's and Sam's"
        await page.fill("#fp-setup-group-name", name)
        await page.locator(f"{MEMBERS} input:not([disabled])").first.check()
        await page.click("#fp-setup-group-add")
        await page.locator("#fp-setup-groups-list", has_text=name).wait_for()
        await page.fill("#fp-setup-group-name", name.upper())
        await page.locator(f"{MEMBERS} input:not([disabled])").first.check()
        await page.click("#fp-setup-group-add")
        await page.wait_for_function(
            "() => document.getElementById('fp-setup-group-error').textContent.length > 0"
        )
        error = await page.locator("#fp-setup-group-error").inner_text()
        assert error == f"A group named {name.upper()} already exists.", error
