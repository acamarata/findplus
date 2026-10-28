"""Colours and icons for people (dashboard 1.3): the map ring, and avatars that open the editor.

Purpose    : A tracker that belongs to a person is ringed in that person's colour on the
             dashboard map (the tracker's own badge colour stays inside); every person
             avatar is a button that opens the person editor on the icon picker; and the
             editor shows the icon and colour rows without scrolling at 720 px height.
Inputs     : The trips fixture (TAG-SON "Sam" #e7663f, TAG-MOM "Mia" #4f8cf7).
Outputs    : none (assertions only).
Constraints: Sam's person owns TAG-SON only, so TAG-MOM is the un-ringed control.
"""

# ruff: noqa: E501
from __future__ import annotations

import httpx
import pytest

from ._person_helpers import open_person
from ._trips_helpers import open_day

pytestmark = pytest.mark.asyncio(loop_scope="session")

RING = "#d65f5f"
SON_BADGE = "#e7663f"


@pytest.fixture
def sam(trips_server):
    """Sam the person, owning only TAG-SON, in a known colour; removed again after the test."""
    base = trips_server["base"]
    for p in httpx.get(f"{base}/api/people").json():
        httpx.delete(f"{base}/api/people/{p['id']}")
    body = {"name": "Sam", "member_ids": ["TAG-SON"], "color": RING}
    resp = httpx.post(f"{base}/api/people", json=body)
    assert resp.status_code == 201, resp.text
    yield resp.json()["id"]
    httpx.delete(f"{base}/api/people/{resp.json()['id']}")


async def _ring_colours(page) -> set[str]:
    return set(
        await page.eval_on_selector_all(
            ".marker-num--ringed .marker-ring-person",
            "els => els.map(e => e.getAttribute('stroke'))",
        )
    )


async def test_person_trackers_get_a_ring_and_others_do_not(trips_page, trips_server, sam):
    p = trips_page
    await open_day(p, trips_server, "school", device=None)
    await p.wait_for_selector(".marker-num--ringed .marker-ring")
    assert await _ring_colours(p) == {RING}
    # tracker colour inside is untouched, and Mia (no person) has no ring at all
    inner = await p.eval_on_selector(
        ".marker-num--ringed .marker-num-glyph", "e => e.innerHTML.toLowerCase()"
    )
    assert SON_BADGE in inner and RING not in inner
    assert await p.locator(".marker-num:not(.marker-num--ringed)").count() > 0
    assert await p.locator(".marker-num:not(.marker-num--ringed) .marker-ring").count() == 0


async def test_ring_is_decoration_and_the_person_is_named(trips_page, trips_server, sam):
    p = trips_page
    await open_day(p, trips_server, "school", device=None)
    await p.wait_for_selector(".marker-num--ringed .marker-ring")
    assert (
        await p.locator(".marker-ring[aria-hidden=true]").count()
        == await p.locator(".marker-ring").count()
    )
    marker = p.locator(".leaflet-marker-icon:has(.marker-num--ringed)").first
    assert "belongs to Sam" in (await marker.get_attribute("title"))
    await marker.click(force=True)
    await p.wait_for_selector(".leaflet-popup-content:has-text('Belongs to Sam')")


async def test_ring_follows_a_colour_change(trips_page, trips_server, sam):
    p = trips_page
    await open_day(p, trips_server, "school", device=None)
    await p.wait_for_selector(".marker-num--ringed .marker-ring")
    httpx.patch(f"{trips_server['base']}/api/people/{sam}", json={"color": "#37c67a"})
    await p.evaluate("import('/static/app/person_colours.js').then(m => m.refreshPersonColours())")
    await p.wait_for_function(
        "() => [...document.querySelectorAll('.marker-ring-person')]"
        ".every(c => c.getAttribute('stroke') === '#37c67a')"
    )


async def test_person_page_avatar_opens_the_editor_on_the_icon_picker(
    trips_page, trips_server, sam
):
    p = trips_page
    await open_person(p, trips_server, sam)
    avatar = p.locator("#person-head button.person-avatar-btn")
    assert await avatar.get_attribute("aria-label") == "Change Sam's icon and colour"
    await avatar.click()
    await p.wait_for_selector("#fp-person-dialog[open]")
    assert await p.evaluate("document.activeElement.id") == "fp-person-icon-btn"
    # choose a new colour, save, and the header avatar follows
    await p.click("#fp-person-color-btn")
    await p.locator("#fp-person-color-popover .fp-color-swatch").nth(2).click()
    await p.locator("#fp-person-dialog footer").get_by_role("button", name="Save").click()
    await p.wait_for_selector("#fp-person-dialog", state="hidden")
    got = httpx.get(f"{trips_server['base']}/api/people/{sam}").json()
    assert got["color"] == "#37c67a"
    await p.wait_for_function(
        "c => document.querySelector('#person-head .person-avatar').innerHTML.toLowerCase().includes(c)",
        arg="#37c67a",
    )


async def test_people_card_avatar_opens_the_editor_on_the_icon_picker(
    trips_page, trips_server, sam
):
    p = trips_page
    await p.goto(trips_server["base"] + "/")
    await p.wait_for_selector("#app-shell:not(.hidden)")
    await p.click('button.fp-tab[data-tab="people"]')
    avatar = p.locator(f".fp-group-card[data-group-id='{sam}'] button.person-avatar-btn")
    await avatar.wait_for()
    assert await avatar.get_attribute("aria-label") == "Change Sam's icon and colour"
    await avatar.focus()
    await p.keyboard.press("Enter")
    await p.wait_for_selector("#fp-person-dialog[open]")
    assert await p.evaluate("document.activeElement.id") == "fp-person-icon-btn"
    await p.keyboard.press("Escape")
    await p.wait_for_selector("#fp-person-dialog", state="hidden")


async def test_editor_icon_and_colour_rows_are_above_the_fold_at_720px(
    trips_page, trips_server, sam
):
    p = trips_page
    await p.set_viewport_size({"width": 1280, "height": 720})
    await open_person(p, trips_server, sam)
    await p.get_by_role("button", name="Edit person").click()
    await p.wait_for_selector("#fp-person-dialog[open]")
    for btn in ("#fp-person-icon-btn", "#fp-person-color-btn"):
        box = await p.locator(btn).bounding_box()
        assert box and box["y"] >= 0 and box["y"] + box["height"] <= 720, (btn, box)
    # and they sit before the person/pet radios and the tracker list
    order = await p.evaluate(
        "ids => ids.map(s => document.querySelector(s).getBoundingClientRect().top)",
        [
            "#fp-person-icon-btn",
            "#fp-person-color-btn",
            "#fp-person-dialog .pe-kind",
            "#fp-person-dialog .pe-row",
        ],
    )
    assert order == sorted(order)


async def test_ring_has_a_surface_gap_and_sighting_numbers_are_off_by_default(
    trips_page, trips_server, sam
):
    p = trips_page
    await open_day(p, trips_server, "school", device=None)
    await p.wait_for_selector(".marker-num--ringed .marker-ring")
    rings = await p.locator(".marker-ring").count()
    assert await p.locator(".marker-ring .marker-ring-gap").count() == rings
    assert await p.locator(".marker-num-seq").first.is_hidden()
    await p.evaluate(
        "import('/static/app/map_marker.js').then(m => import('/static/app/state.js')"
        ".then(s => m.setSightingNumbers(s.state.map, true)))"
    )
    assert await p.locator(".marker-num-seq").first.is_visible()


async def test_cluster_pin_names_itself(trips_page, trips_server):
    p = trips_page
    await p.goto(trips_server["base"] + "/")
    await p.wait_for_selector("#app-shell[data-fp-ready]")
    html = await p.evaluate(
        "import('/static/app/map_pins.js').then(m => m.countIcon(3).options.html)"
    )
    assert 'role="img"' in html and 'aria-label="3 trackers here"' in html


async def test_editor_uses_plain_words_and_big_swatches(trips_page, trips_server, sam):
    p = trips_page
    await open_person(p, trips_server, sam)
    await p.get_by_role("button", name="Edit person").click()
    await p.wait_for_selector("#fp-person-dialog[open]")
    row = p.locator("#fp-person-dialog .pe-row").filter(has_text="Sam")
    texts = await row.locator("option").all_inner_texts()
    assert "Fill in from the tracker name" in texts and "Usually carries it" in texts
    body = await p.locator("#fp-person-dialog").inner_text()
    assert "default weight" not in body and "Guess from the name" not in body
    await p.click("#fp-person-color-btn")
    box = await p.locator("#fp-person-color-popover .fp-color-swatch").first.bounding_box()
    assert box and box["width"] >= 40 and box["height"] >= 40, box
    trigger = await p.locator("#fp-person-color-btn").bounding_box()
    assert trigger and trigger["width"] >= 40 and trigger["height"] >= 40, trigger
