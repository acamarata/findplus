"""The group dialog guards the custom quorum (UAT #11).

A custom quorum above the number of ticked members can never fire, and a typed
50 used to reach the server as a raw 422. The number is clamped to 1-20 on
leaving the box, a warning shows while it exceeds the members, and Save refuses
an out-of-range number with a plain sentence.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

MEMBERS = "#fp-group-members"


async def _open_add(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#fp-add-group-btn", state="attached")
    await page.click('button[data-tab="groups"]')
    await page.wait_for_selector('[data-fp-ready="groups"]')
    await page.click("#fp-add-group-btn")
    await page.wait_for_selector("#fp-group-dialog[open]")
    await page.wait_for_selector(f"{MEMBERS} input[data-device-id]:not([disabled])")
    await page.click("#fp-group-advanced summary")


async def test_warns_when_quorum_exceeds_the_ticked_members(page, base_url):
    await _open_add(page, base_url)
    warning = page.locator("#fp-group-quorum-warning")
    assert await warning.is_hidden()
    await page.locator(f"{MEMBERS} input[data-device-id]:not([disabled])").first.check()
    await page.select_option("#fp-group-quorum", "custom")
    await page.fill("#fp-group-quorum-n", "5")
    await warning.wait_for(state="visible")
    text = await warning.inner_text()
    assert "5 members" in text and "only 1" in text and "never fire" in text
    await page.fill("#fp-group-quorum-n", "1")
    await warning.wait_for(state="hidden")


async def test_number_is_clamped_to_1_20_when_left(page, base_url):
    await _open_add(page, base_url)
    await page.select_option("#fp-group-quorum", "custom")
    await page.fill("#fp-group-quorum-n", "50")
    await page.locator("#fp-group-quorum-n").blur()
    assert await page.input_value("#fp-group-quorum-n") == "20"
    await page.fill("#fp-group-quorum-n", "0")
    await page.locator("#fp-group-quorum-n").blur()
    assert await page.input_value("#fp-group-quorum-n") == "1"


async def test_save_refuses_a_blank_custom_quorum_without_calling_the_server(page, base_url):
    await _open_add(page, base_url)
    calls = []

    async def record(route):
        calls.append(route.request.method)
        await route.continue_()

    await page.route("**/api/groups", record)
    await page.fill("#fp-group-name", "Quorum probe")
    await page.locator(f"{MEMBERS} input[data-device-id]:not([disabled])").first.check()
    await page.select_option("#fp-group-quorum", "custom")
    await page.fill("#fp-group-quorum-n", "")
    await page.locator("#fp-group-dialog").get_by_role("button", name="Save").click()
    await page.wait_for_function(
        "() => document.getElementById('fp-group-dialog-error').textContent.includes('whole')"
    )
    assert "POST" not in calls
