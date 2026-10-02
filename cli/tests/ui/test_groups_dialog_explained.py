"""Group dialog and cards, in plain words: live quorum sentence, Track this tracker,
card meta lines and named colour swatches (round 3)."""

from __future__ import annotations

import json

import pytest

from .test_groups_dialog import _open_add_dialog, _open_groups_tab

pytestmark = pytest.mark.asyncio(loop_scope="session")

MEMBERS = "#fp-group-members"
SENTENCE = "#fp-group-quorum-sentence"


async def test_the_sentence_follows_the_quorum_the_members_and_the_radius(page, base_url):
    await _open_add_dialog(page, base_url)
    sentence = page.locator(SENTENCE)
    assert "Tick members" in await sentence.inner_text()
    boxes = page.locator(f"{MEMBERS} input[data-device-id]:not([disabled])")
    for i in range(3):
        await boxes.nth(i).check()
    await page.select_option("#fp-group-quorum", "majority")
    text = await sentence.inner_text()
    assert "Alerts when 2 of 3 members reach the same place" in text
    assert "within 150 m" in text
    await page.select_option("#fp-group-quorum", "all")
    assert "3 of 3 members" in await sentence.inner_text()
    await page.select_option("#fp-group-quorum", "any")
    assert "1 of 3 members" in await sentence.inner_text()
    await page.select_option("#fp-group-quorum", "custom")
    await page.fill("#fp-group-quorum-n", "2")
    assert "2 of 3 members" in await sentence.inner_text()
    await page.fill("#fp-group-quorum-n", "9")  # more than ticked: the warning speaks, not this
    assert await sentence.is_hidden()
    await page.fill("#fp-group-quorum-n", "2")
    await page.locator("#fp-group-radius").evaluate(
        "(el) => { el.value = '300'; el.dispatchEvent(new Event('input', {bubbles: true})); }"
    )
    assert "within 300 m" in await sentence.inner_text()


async def test_track_this_tracker_states_the_cost_and_ticks_the_device(page, base_url):
    # TAG-AIR is seeded untracked (cli/tests/ui/_seed_script.py).
    try:
        await _open_add_dialog(page, base_url)
        note = await page.locator("#fp-members-untracked-note").inner_text()
        assert "location requests an hour" in note
        button = page.get_by_role("button", name="Track this tracker: AirTag")
        await button.click()
        box = page.locator(f'{MEMBERS} input[data-device-id="TAG-AIR"]')
        await box.wait_for()
        await page.wait_for_function(
            "() => { const b = document.querySelector('#fp-group-members "
            'input[data-device-id="TAG-AIR"]\'); return b && !b.disabled && b.checked; }'
        )
        resp = await page.request.get(base_url + "/api/devices")
        air = next(d for d in (await resp.json())["devices"] if d["device_id"] == "TAG-AIR")
        assert air["is_tracked"] is True
    finally:
        await page.request.patch(
            base_url + "/api/devices/TAG-AIR",
            data=json.dumps({"tracked": False}),
            headers={"Content-Type": "application/json"},
        )


async def test_a_card_says_how_many_members_and_when_it_alerts(page, base_url):
    await _open_groups_tab(page, base_url)
    meta = page.locator(".fp-group-card", has_text="Family").locator(".fp-card-meta")
    text = await meta.inner_text()
    assert "3 members" in text
    assert "alerts when most members arrive" in text


async def test_colour_swatches_have_names_and_a_group_label(page, base_url):
    await _open_add_dialog(page, base_url)
    await page.click("#fp-group-color-btn")
    popover = page.locator("#fp-group-color-popover")
    assert await popover.locator('[role="group"]').count() == 1
    labels = await popover.locator(".fp-color-swatch").evaluate_all(
        "(els) => els.map((e) => e.getAttribute('aria-label'))"
    )
    assert labels[:3] == ["Blue", "Orange", "Green"]
    assert not any(label.startswith("#") for label in labels)
