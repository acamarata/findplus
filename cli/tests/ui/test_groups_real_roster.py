"""Groups tab with a real first-sign-in roster: 17 devices, none located yet.

Purpose    : The owner reported trouble adding groups right after signing in:
             Google locations still locked, some devices tracked and some not,
             none with a single fix, several sharing a name. The happy-path
             tests use three tidy seeded devices; these use the awkward set in
             `_roster17.py` and assert the page explains every empty state.
Inputs     : live_server, ui_db / ui_env, the 17-device roster.
Outputs    : none (assertions only).
Constraints: Every group made here starts with "T17" so `forget_groups()` can
             remove it; the shared server is left as it was found.
"""

from __future__ import annotations

import json

import pytest

from ._roster17 import NAMES, PREFIX, roster17

pytestmark = pytest.mark.asyncio(loop_scope="session")

MEMBERS = "#fp-group-members"


async def _open_add(page, base_url, width=1280, height=900):
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#fp-add-group-btn", state="attached")
    tab = page.locator('button[data-tab="people"], .fp-tabbar [data-tabbar-tab="people"]')
    await tab.locator("visible=true").first.click()
    await page.wait_for_selector('[data-fp-ready="groups"]')
    await page.click("#fp-add-group-btn")
    await page.wait_for_selector("#fp-group-dialog[open]")
    await page.wait_for_selector(f"{MEMBERS} .fp-member-row, {MEMBERS} .fp-members-hint")


async def _save(page):
    await page.locator("#fp-group-dialog").get_by_role("button", name="Save").click()


async def _make_group(page, name):
    await page.fill("#fp-group-name", name)
    await page.locator(f"{MEMBERS} input[data-device-id]:not([disabled])").first.check()
    await _save(page)
    await page.locator(".fp-group-card", has_text=name).wait_for(state="visible")


async def test_nothing_tracked_yet_says_so_instead_of_an_empty_box(page, base_url, ui_db, ui_env):
    with roster17(ui_db, ui_env, tracked=0):
        # The seeded TAG-* devices are tracked; untrack them for this test only.
        await page.request.post(
            base_url + "/api/devices/track",
            data=json.dumps({"device_ids": []}),
            headers={"Content-Type": "application/json"},
        )
        try:
            await _open_add(page, base_url)
            text = await page.locator(MEMBERS).inner_text()
            assert "not tracked yet" in text.lower() or "none of your" in text.lower(), text
            rows = page.locator(f"{MEMBERS} .fp-member-row")
            assert await rows.count() == len(NAMES) + 4
            assert (
                await page.locator(f"{MEMBERS} input[data-device-id]:not([disabled])").count() == 0
            )
        finally:
            await page.request.post(
                base_url + "/api/devices/track",
                data=json.dumps({"device_ids": ["TAG-HOME", "TAG-AWAY", "TAG-STALE"]}),
                headers={"Content-Type": "application/json"},
            )


async def test_untracked_devices_are_listed_but_cannot_be_ticked(page, base_url, ui_db, ui_env):
    with roster17(ui_db, ui_env, tracked=10):
        await _open_add(page, base_url)
        enabled = page.locator(f"{MEMBERS} input[data-device-id]:not([disabled])")
        disabled = page.locator(f"{MEMBERS} input[data-device-id][disabled]")
        assert await enabled.count() == 10 + 3  # roster + the three seeded tracked tags
        assert await disabled.count() == 7 + 1  # roster + the seeded Apple AirTag
        note = await page.locator(f"{MEMBERS} .fp-members-hint").first.inner_text()
        assert "track" in note.lower()


async def test_same_named_devices_can_be_told_apart(page, base_url, ui_db, ui_env):
    with roster17(ui_db, ui_env, tracked=10):
        await _open_add(page, base_url)
        rows = await page.locator(f"{MEMBERS} .fp-member-row").all_inner_texts()
        pixel = [r for r in rows if "Ali Pixel 8a" in r]
        assert len(pixel) == 2 and len(set(pixel)) == 2, pixel
        assert any("Ali's Keys" in r and "☕" in r for r in rows)
        assert any('O\'Brien "Bag"' in r for r in rows)


async def test_select_all_then_save_keeps_every_tracked_device(page, base_url, ui_db, ui_env):
    with roster17(ui_db, ui_env, tracked=10):
        await _open_add(page, base_url)
        await page.fill("#fp-group-name", 'T17 Everyone\'s "Stuff"')
        await page.click(f"{MEMBERS} .fp-members-all")
        ticked = await page.locator(f"{MEMBERS} input:checked").count()
        assert ticked == 13
        await _save(page)
        card = page.locator(".fp-group-card", has_text="T17 Everyone")
        await card.wait_for(state="visible")
        groups = await (await page.request.get(base_url + "/api/groups")).json()
        made = next(g for g in groups if g["name"].startswith("T17 Everyone"))
        assert len(made["members"]) == 13
        assert all(m["device_id"].startswith(("TAG-", PREFIX)) for m in made["members"])


async def test_group_of_unlocated_devices_says_no_location_not_just_unknown(
    page, base_url, ui_db, ui_env
):
    with roster17(ui_db, ui_env, tracked=10):
        await _open_add(page, base_url)
        await page.fill("#fp-group-name", "T17 Silent")
        for i in (0, 1, 2):
            await page.check(f'{MEMBERS} input[data-device-id="{PREFIX}{i:02d}"]')
        await _save(page)
        card = page.locator(".fp-group-card", has_text="T17 Silent")
        pill = card.locator(".fp-card-verdict")
        await page.wait_for_function(
            "(el) => el.textContent.length > 0", arg=await pill.element_handle()
        )
        text = (await pill.inner_text()).strip()
        assert text == "No location yet", text
        assert "not reported" in (await pill.get_attribute("title") or "")


async def test_several_groups_in_a_row_each_start_clean(page, base_url, ui_db, ui_env):
    with roster17(ui_db, ui_env, tracked=10):
        await _open_add(page, base_url)
        for n in (1, 2, 3):
            if n > 1:
                await page.click("#fp-add-group-btn")
                await page.wait_for_selector("#fp-group-dialog[open]")
                assert await page.input_value("#fp-group-name") == ""
                assert await page.locator(f"{MEMBERS} input:checked").count() == 0
                assert (await page.locator("#fp-group-dialog-error").inner_text()) == ""
            await _make_group(page, f"T17 Batch {n}")
        cards = page.locator(".fp-group-card", has_text="T17 Batch")
        assert await cards.count() == 3
        options = page.locator("#fp-group-select option", has_text="T17 Batch")
        assert await options.count() == 3


async def test_duplicate_name_with_apostrophes_is_quoted_correctly(page, base_url, ui_db, ui_env):
    name = "T17 Ali's and Sam's"
    with roster17(ui_db, ui_env, tracked=10):
        await _open_add(page, base_url)
        await _make_group(page, name)
        await page.click("#fp-add-group-btn")
        await page.wait_for_selector("#fp-group-dialog[open]")
        await page.fill("#fp-group-name", name.lower())
        await page.locator(f"{MEMBERS} input[data-device-id]:not([disabled])").first.check()
        await _save(page)
        await page.wait_for_function(
            "() => document.getElementById('fp-group-dialog-error').textContent.length > 0"
        )
        error = await page.locator("#fp-group-dialog-error").inner_text()
        assert error == f"A group named {name.lower()} already exists.", error
        assert await page.locator("#fp-group-dialog").get_attribute("open") is not None


async def test_edit_swaps_members_and_delete_removes_the_card(page, base_url, ui_db, ui_env):
    with roster17(ui_db, ui_env, tracked=10):
        await _open_add(page, base_url)
        await _make_group(page, "T17 Editable")
        card = page.locator(".fp-group-card", has_text="T17 Editable")
        await card.locator(".fp-card-edit").click()
        await page.wait_for_selector("#fp-group-dialog[open]")
        assert await page.locator(f"{MEMBERS} input:checked").count() == 1
        await page.click(f"{MEMBERS} .fp-members-all")
        await _save(page)
        await page.wait_for_selector("#fp-group-dialog:not([open])", state="attached")
        groups = await (await page.request.get(base_url + "/api/groups")).json()
        edited = next(g for g in groups if g["name"] == "T17 Editable")
        assert len(edited["members"]) == 13
        await card.locator(".fp-card-delete").click()
        await page.get_by_role("button", name="Delete", exact=True).last.click()
        await page.wait_for_function(
            "() => ![...document.querySelectorAll('.fp-group-card')]"
            ".some((c) => c.textContent.includes('T17 Editable'))"
        )


async def test_dialog_fits_a_phone_with_seventeen_members(page, base_url, ui_db, ui_env):
    with roster17(ui_db, ui_env, tracked=10):
        await _open_add(page, base_url, width=375, height=640)
        box = await page.evaluate(
            """() => {
                const d = document.getElementById('fp-group-dialog').getBoundingClientRect();
                const save = [...document.querySelectorAll('#fp-group-dialog button')]
                  .find((b) => b.textContent.trim() === 'Save').getBoundingClientRect();
                return { left: d.left, right: d.right, top: d.top, bottom: d.bottom,
                         saveBottom: save.bottom, vw: innerWidth, vh: innerHeight,
                         scrollW: document.documentElement.scrollWidth };
            }"""
        )
        assert box["left"] >= 0 and box["right"] <= box["vw"], box
        assert box["scrollW"] <= box["vw"], box
        # Save is on screen, or the dialog itself scrolls to reach it.
        reachable = await page.evaluate(
            "() => { const d = document.getElementById('fp-group-dialog');"
            " return d.scrollHeight <= d.clientHeight"
            " || getComputedStyle(d).overflowY !== 'hidden'; }"
        )
        assert box["saveBottom"] <= box["vh"] or reachable, box
