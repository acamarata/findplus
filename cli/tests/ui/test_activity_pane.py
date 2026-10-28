"""All Activity tab: one merged, newest-first feed for the selected day.

Purpose    : Pin ordering, line text, person dot and name, merged arrival and
             departure lines, the suspect style, paging at 200, filters, day
             changes, the focus event on a click, the error state and the lock
             purge.
Inputs     : live_server (conftest.py) with /api/timeline, /api/people and
             /api/groups/events stubbed by _activity_day.py / _many_tracks.py.
Outputs    : Assertions only.
Constraints: Headless Chromium; nothing reaches a real account.
"""

# ruff: noqa: E501  (inline JS snippets)
from __future__ import annotations

import re

import pytest

from ._activity_day import SAM, event_row, install_activity_day, today, yesterday
from ._many_tracks import busy_body

pytestmark = pytest.mark.asyncio(loop_scope="session")

LINES = "#tab-activity .fp-act-line"


async def _open(page, base_url, **kw):
    holder = await install_activity_day(page, **kw)
    await page.goto(base_url + "/#/activity")
    await page.wait_for_selector("#app-shell[data-fp-ready]", timeout=20000)
    await page.wait_for_selector("#tab-activity:not([hidden])")
    return holder


async def _texts(page):
    return await page.eval_on_selector_all(
        LINES, "els => els.map(e => e.innerText.replace(/\\s+/g, ' ').trim())"
    )


async def test_lines_are_newest_first_with_place_accuracy_and_rough_fix(page, base_url):
    await _open(page, base_url)
    await page.wait_for_selector(f"{LINES}[data-point-id]")
    texts = await _texts(page)
    assert len(texts) == 4
    assert re.search(r"10:00\s?AM · Busy Tag 1 · Accuracy unknown", texts[0])
    assert re.search(r"9:30\s?AM · Busy Tag 0 · Sam · ±250 m · rough fix", texts[1])
    assert "Jumped 40 km in a minute" in texts[2]
    assert re.search(r"9:00\s?AM · Busy Tag 0 · Sam · Home · ±40 m$", texts[3])


async def test_person_dot_and_name_on_their_tracker_only(page, base_url):
    await _open(page, base_url)
    await page.wait_for_selector(f"{LINES}[data-point-id]")
    sam = page.locator(f'{LINES}[data-device-id="BUSY-00"]').first
    assert await sam.locator(".fp-act-person-name").inner_text() == "Sam"
    dot = await sam.locator(".fp-act-dot").evaluate("e => getComputedStyle(e).backgroundColor")
    assert dot == "rgb(225, 29, 72)"
    assert await page.locator(f'{LINES}[data-device-id="BUSY-01"] .fp-act-person').count() == 0


async def test_person_events_merge_by_time(page, base_url):
    rows = [event_row(1, today(), 9, 20, "ENTER"), event_row(2, today(), 9, 45, "EXIT")]
    holder = await _open(page, base_url, events=rows)
    await page.wait_for_selector(f"{LINES}[data-kind=event]")
    texts = await _texts(page)
    assert len(texts) == 6
    assert "Sam left School" in texts[1]
    assert "Sam arrived at School" in texts[3]
    # An event for someone who owns no visible tracker is not shown.
    holder["events"].append(event_row(3, today(), 9, 50, "ENTER", group_id=999))
    await page.evaluate("window.dispatchEvent(new CustomEvent('findplus:data-refreshed'))")
    await page.wait_for_timeout(300)
    assert len(await _texts(page)) == 6


async def test_suspect_sighting_is_faint_with_its_note(page, base_url):
    await _open(page, base_url)
    li = page.locator(f"{LINES}.is-suspect")
    await li.wait_for()
    assert await li.count() == 1
    assert "Jumped 40 km in a minute" in await li.locator(".tl-suspect").inner_text()
    assert float(await li.evaluate("e => getComputedStyle(e).opacity")) < 1


async def test_paging_shows_200_then_more(page, base_url):
    await install_activity_day(page, body_for=lambda d: busy_body(d, tracks=3, points=100))
    await page.goto(base_url + "/#/activity")
    await page.wait_for_selector(f"{LINES}")
    assert await page.locator(LINES).count() == 200
    await page.locator("#fp-act-more").click()
    assert await page.locator(LINES).count() == 300
    assert await page.locator("#fp-act-more").count() == 0


async def test_movement_only_and_group_filters_narrow_the_feed(page, base_url):
    await _open(page, base_url)
    await page.wait_for_selector(f"{LINES}[data-point-id]")
    await page.check("#toggle-movement")
    await page.wait_for_function(
        "document.querySelectorAll('#tab-activity .fp-act-line').length === 3"
    )
    await page.uncheck("#toggle-movement")
    await page.evaluate(
        "() => Promise.all([import('/static/app/state.js'), import('/static/app/track_blocks.js')]).then(([s, t]) => { s.state.groupMembers = new Set(['BUSY-00']); t.renderTracks(); })"
    )
    await page.wait_for_function(
        "document.querySelectorAll('#tab-activity .fp-act-line').length === 2"
    )
    assert await page.locator(f'{LINES}[data-device-id="BUSY-01"]').count() == 0


async def test_day_arrows_reload_the_feed_and_events(page, base_url):
    def body(day):
        return (
            busy_body(day, tracks=1, points=3)
            if day != today()
            else busy_body(day, tracks=2, points=3)
        )

    holder = await _open_with(page, base_url, body)
    await page.wait_for_function(
        "document.querySelectorAll('#tab-activity .fp-act-line').length === 6"
    )
    await page.click("#btn-prev-day")
    await page.wait_for_function(
        "document.querySelectorAll('#tab-activity .fp-act-line').length === 3"
    )
    assert yesterday() in await page.input_value("#day-picker")
    assert any("since=" in u and "until=" in u for u in holder["urls"])


async def _open_with(page, base_url, body_for):
    holder = await install_activity_day(page, body_for=body_for)
    await page.goto(base_url + "/#/activity")
    await page.wait_for_selector("#app-shell[data-fp-ready]", timeout=20000)
    return holder


async def test_a_line_click_dispatches_the_focus_event(page, base_url):
    await _open(page, base_url)
    await page.wait_for_selector(f"{LINES}[data-point-id]")
    await page.evaluate(
        "window.__focus = []; window.addEventListener('findplus:focus-tracker', (e) => window.__focus.push(e.detail))"
    )
    first = page.locator(f'{LINES}[data-device-id="BUSY-00"]').first
    pid = int(await first.get_attribute("data-point-id"))
    await first.locator("button").click()
    assert await page.evaluate("window.__focus") == [{"device_id": "BUSY-00", "point_id": pid}]


async def test_empty_day_is_one_plain_sentence(page, base_url):
    def body(day):
        empty = busy_body(day, tracks=0, points=0)
        return empty

    await _open_with(page, base_url, body)
    await page.wait_for_selector("#tab-activity .fp-act-empty")
    assert (
        await page.locator("#tab-activity .fp-act-empty").inner_text()
        == "No sightings on this day."
    )


async def test_failed_events_show_the_pane_error_with_retry(page, base_url):
    holder = await install_activity_day(page)
    holder["fail_events"] = True
    await page.goto(base_url + "/#/activity")
    await page.wait_for_selector("#tab-activity [data-pane-error]")
    assert await page.locator(LINES).count() == 4
    holder["fail_events"] = False
    await page.locator("#tab-activity [data-pane-error] button").first.click()
    await page.wait_for_selector("#tab-activity [data-pane-error]", state="detached")


async def test_lock_purge_clears_the_feed(page, base_url):
    await _open(page, base_url)
    await page.wait_for_selector(f"{LINES}[data-point-id]")
    await page.evaluate("() => import('/static/app/lock.js').then((m) => m.purgeRenderedData())")
    assert await page.locator(LINES).count() == 0
    assert (await page.locator("#tab-activity").inner_text()).strip() == ""
    assert SAM["name"] not in await page.locator("#tab-activity").inner_html()
