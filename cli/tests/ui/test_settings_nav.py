"""Settings dialog 1.3 (U9, U34): a section list, a logical order, one Backups
section, and the danger zone last."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

ORDER = ["general", "signin", "people", "alerts", "lock", "updates", "backups", "about", "danger"]


async def _open(page, base_url, width=1400, height=900):
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map.leaflet-container", state="attached")
    await page.evaluate("document.getElementById('btn-settings').click()")
    await page.wait_for_selector("#settings-modal[data-loaded='true']")
    await page.wait_for_selector("#person-backup-line:not(:empty)")


async def test_sections_are_in_the_documented_order_with_danger_last(page, base_url):
    await _open(page, base_url)
    ids = await page.evaluate(
        "[...document.querySelectorAll('#settings-body > .settings-section')]"
        ".map(s => s.id.slice(13))"
    )
    assert ids == ORDER
    nav = await page.locator("#settings-nav button").evaluate_all(
        "els => els.map(e => e.dataset.section)"
    )
    assert nav == ORDER
    assert await page.locator("#settings-sec-danger #btn-clear-all").count() == 1


async def test_the_two_backups_live_in_one_section(page, base_url):
    await _open(page, base_url)
    section = page.locator("#settings-sec-backups")
    assert await section.locator("#btn-export-settings").count() == 1
    assert await section.locator("#person-backup-now").count() == 1
    assert await page.locator("#settings-sec-people #person-backup-now").count() == 0


async def test_choosing_a_section_scrolls_to_it_and_marks_it(page, base_url):
    await _open(page, base_url)
    await page.click("#settings-nav button[data-section='lock']")
    await page.wait_for_function(
        "() => { const b = document.getElementById('settings-body').getBoundingClientRect();"
        " const s = document.getElementById('settings-sec-lock').getBoundingClientRect();"
        " return Math.abs(s.top - b.top) < 40; }"
    )
    pressed = page.locator("#settings-nav button[aria-current='true']")
    assert await pressed.get_attribute("data-section") == "lock"


async def test_the_honesty_sentences_appear_once_in_the_dialog(page, base_url):
    await _open(page, base_url)
    text = await page.inner_text("#settings-modal")
    assert text.count("Alerts inherit the network's delay.") == 1
    assert text.count("A tag with no recent fix is stale") == 1


async def test_phone_nav_is_a_chip_row_and_the_page_does_not_scroll_sideways(page, base_url):
    await _open(page, base_url, 375, 812)
    nav = await page.locator("#settings-nav").bounding_box()
    body = await page.locator("#settings-body").bounding_box()
    assert nav["y"] < body["y"], "the chip row sits above the form"
    assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    first = await page.locator("#settings-nav button").first.bounding_box()
    assert first["height"] >= 44
