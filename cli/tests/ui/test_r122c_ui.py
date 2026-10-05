"""Patch round 1.2.2, batch C: place dialog at 720 px, suggestions wording, map popup
catalogue, person-named lanes (O22, O13)."""

# ruff: noqa: E501

from __future__ import annotations

import pathlib

import pytest

from ._person_helpers import ensure_person
from ._suggest_helpers import serve
from ._trips_helpers import open_day, show_legacy_story

pytestmark = pytest.mark.asyncio(loop_scope="session")

WEB_APP = pathlib.Path(__file__).resolve().parents[3] / "web" / "app"


async def test_place_dialog_fits_a_720px_viewport_with_save_in_view(trips_page, trips_server):
    p = trips_page
    await p.set_viewport_size({"width": 1280, "height": 720})
    await p.goto(trips_server["base"] + "/")
    await p.wait_for_selector("#app-shell[data-fp-ready]")
    await p.click('.fp-tabs [data-tab="places"]')
    await p.click("#fp-add-place-btn")
    await p.wait_for_selector("#fp-place-notify-line:not(:empty)")
    box = await p.evaluate(
        "() => { const d = document.getElementById('fp-place-dialog'); const r = d.getBoundingClientRect();"
        " const b = d.querySelector('footer button').getBoundingClientRect();"
        " return { top: r.top, bottom: r.bottom, height: r.height, saveBottom: b.bottom,"
        " saveTop: b.top, vh: innerHeight }; }"
    )
    assert box["top"] >= 0 and box["bottom"] <= box["vh"], box
    assert box["height"] <= 720, box
    assert box["saveTop"] >= 0 and box["saveBottom"] <= box["vh"], box


async def test_nothing_new_after_everyone_is_added_reads_as_success(trips_page, trips_server):
    ensure_person(trips_server)
    empty = {"suggestions": [], "unassigned": [], "new_device_ids": [], "dismissed_count": 0}
    await serve(trips_page, empty)
    p = trips_page
    await p.goto(trips_server["base"] + "/")
    await p.wait_for_selector("#app-shell[data-fp-ready]")
    await p.click('button[data-tab="people"]')
    await p.get_by_text("All suggested people added.").wait_for()
    assert "No new people found" not in await p.inner_text("#fp-people-suggest")


async def test_map_popup_text_comes_from_the_catalogue(trips_page, trips_server):
    p = trips_page
    await p.goto(trips_server["base"] + "/")
    await p.wait_for_selector("#app-shell[data-fp-ready]")
    html = await p.evaluate(
        """async () => {
          const { popupHtml } = await import('/static/app/map_popup.js');
          const i18n = await import('/static/app/i18n.js');
          const point = { observed_at_local: '2026-10-03T08:00:00+00:00', latitude: 1, longitude: 2,
            accuracy_meters: 120, seconds_since_previous: 300, meters_from_previous: 400,
            is_movement: false, source: 'crowd', fetched_at: '2026-10-03T08:05:00+00:00' };
          return { text: popupHtml(point, 'Tag'), keys: ['retrieved', 'report', 'sincePrevious',
            'fromPrevious', 'belowThreshold', 'accuracy', 'accuracyRough'].map((k) => i18n.t('map.popup.' + k)) };
        }"""
    )
    for text in ("Accuracy ~120 m (rough fix)", "since previous observation", "Report: crowd"):
        assert text in html["text"], html["text"]
    assert "Below movement threshold" in html["text"] and "Retrieved" in html["text"]
    assert all(not k.startswith("map.popup.") for k in html["keys"]), html["keys"]


async def test_map_sources_hold_no_english_popup_literals() -> None:
    popup = (WEB_APP / "map_popup.js").read_text()
    for literal in ("since previous observation", "Below movement", "Retrieved ", "Report: "):
        assert literal not in popup, literal
    assert "observed path;" not in (WEB_APP / "map.js").read_text()


async def test_day_story_lanes_name_the_person_not_the_tracker(trips_page, trips_server):
    ensure_person(trips_server)
    await open_day(trips_page, trips_server, "school", device="")
    await trips_page.wait_for_selector(
        "#fp-group-select option[value]:nth-child(2)", state="attached"
    )
    await trips_page.select_option("#fp-group-select", label="Family")
    await show_legacy_story(trips_page)
    await trips_page.wait_for_selector(".lane .strip-bar")
    await trips_page.wait_for_function(
        "() => [...document.querySelectorAll('.lane-name')].every((e) => e.textContent.startsWith('Sam ('))"
    )
    names = sorted(await trips_page.locator(".lane-name").all_inner_texts())
    assert names == ["Sam (bag)", "Sam (shoes)"], names
