"""Summary cards explain themselves; the header says how often Find+ asks.

Round 3 (dash3): "Retrieved by this computer" had no explanation, the header
chip printed a request rate ("~144/hr"), and the first card label flipped
between "Last observed by Find Hub" and "by your providers" with the tracked
count.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _boot(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell[data-fp-ready='dashboard']")


async def test_cards_help_explains_retrieved_by_this_computer(page, base_url):
    await _boot(page, base_url)
    help_ = page.locator("#cards-help")
    assert not await help_.evaluate("(el) => el.open")
    await help_.locator("summary").click()
    text = await help_.inner_text()
    assert "Retrieved by this computer" in text
    assert "downloaded that location" in text


async def test_header_names_trackers_and_interval_not_a_rate(page, base_url):
    await _boot(page, base_url)
    text = await page.locator("#device-name").inner_text()
    assert "trackers" in text and "checked every" in text
    assert "/hr" not in text


async def test_observed_label_stays_put_when_nothing_is_tracked(page, base_url):
    await _boot(page, base_url)
    before = await page.locator("#card-observed-label").inner_text()
    await page.evaluate(
        "() => import('/static/app/state.js').then((m) => {"
        " m.state.devices.forEach((d) => { d.is_tracked = false; });"
        " return import('/static/app/provider_chrome.js').then((p) => p.syncProviderChrome()); })"
    )
    after = await page.locator("#card-observed-label").inner_text()
    assert before == after
    assert "your providers" not in after
