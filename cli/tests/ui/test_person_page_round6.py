"""Person page: header for past days, tab order, touch hint, distance after a flagged fix."""

from __future__ import annotations

import pytest

from ._person_helpers import ensure_person, open_person

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture
def pid(trips_server):
    return ensure_person(trips_server)


async def test_past_day_header_says_on_date_and_hides_now(trips_page, trips_server, pid):
    day = await open_person(trips_page, trips_server, pid)
    p = trips_page
    text = await p.inner_text("#person-now")
    assert text.startswith("On ") and "At Home from 3:40 PM" in text
    assert str(int(day[:4])) in text
    assert await p.locator("#tab-person .person-conf, #tab-person .person-seen").count() == 0


async def test_today_header_keeps_now(trips_page, trips_server, pid):
    await open_person(trips_page, trips_server, pid)
    p = trips_page
    await p.click("#person-today")
    await p.wait_for_selector("#tab-person .person-conf")
    assert not (await p.inner_text("#person-now")).startswith("On ")
    assert await p.locator(".person-seen").count() == 1


async def test_first_tab_stop_is_back_then_the_header_buttons_then_the_day_controls(
    trips_page, trips_server, pid
):
    await open_person(trips_page, trips_server, pid)
    p = trips_page
    assert await p.evaluate("document.activeElement.id") == "person-page"
    seen = []
    for _ in range(7):
        await p.keyboard.press("Tab")
        seen.append(await p.evaluate("document.activeElement.id || document.activeElement.tagName"))
    # Back, then the avatar button (opens the editor at the icon picker), then the header buttons.
    assert seen[:3] == ["person-back", "person-avatar", "person-send"], seen
    assert seen.index("person-prev") > seen.index("person-send"), seen
    assert "BODY" not in seen, seen


async def test_arrow_key_hint_is_hidden_on_touch_screens(browser_session, trips_server, pid):
    browser, _ = browser_session
    ctx = await browser.new_context(
        has_touch=True, is_mobile=True, viewport={"width": 375, "height": 800}, bypass_csp=True
    )
    page = await ctx.new_page()
    try:
        await open_person(page, trips_server, pid)
        assert not await page.locator(".person-keys-hint").is_visible()
    finally:
        await ctx.close()
