"""Playwright browser tests for the Groups tab (P1-E10-W6-S1-T2).

Seed data (cli/tests/ui/conftest.py): group "Family" with 3 members —
TAG-HOME and TAG-AWAY (both fresh fixes ~50m apart, well inside the
150m cluster radius: "together") and TAG-STALE (never reported: stale).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_group(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#fp-group-select")
    await page.select_option("#fp-group-select", label="Family")
    # #fp-presence-panel lives in the Groups tab panel; it stays populated
    # while hidden (loadGroups/selectGroup run regardless of the active
    # tab), but a "visible" wait needs the panel actually shown, same as a
    # real user clicking the tab.
    await page.click('button[data-tab="groups"]')
    await page.wait_for_selector("#fp-presence-panel .fp-verdict")


async def test_groups_tab_visible(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector('button[data-tab="groups"]')


async def test_group_selector_populated(page, base_url):
    await page.goto(base_url + "/")
    # <option> elements never report as "visible" to Playwright's
    # actionability check (no box outside an open native dropdown) —
    # "attached" is the correct wait state for option existence.
    await page.wait_for_selector('#fp-group-select option[value]:not([value=""])', state="attached")
    labels = await page.locator("#fp-group-select option").all_inner_texts()
    assert "Family" in labels


async def test_select_group_renders_overlay(page, base_url):
    await _open_group(page, base_url)
    # 3 members, 1 stale (no marker) -> exactly 2 overlay circles.
    await page.wait_for_function(
        "() => document.querySelectorAll('#map svg path.leaflet-interactive').length >= 2"
    )


async def test_presence_panel_shows_verdict(page, base_url):
    await _open_group(page, base_url)
    verdict = page.locator("#fp-presence-panel .fp-verdict")
    assert await verdict.inner_text() == "Together"


async def test_stale_member_no_marker(page, base_url):
    await _open_group(page, base_url)
    stale_items = page.locator("#fp-stale-list li")
    assert await stale_items.count() == 1
    assert "Stale Tag" in await stale_items.first.inner_text()


async def test_group_note_displayed(page, base_url):
    resp = await page.request.get(base_url + "/api/groups")
    groups = await resp.json()
    family_id = next(g["id"] for g in groups if g["name"] == "Family")
    presence_resp = await page.request.get(f"{base_url}/api/groups/{family_id}/presence?window=60")
    note = (await presence_resp.json())["note"]
    assert note  # the engine always produces one for a non-empty group

    await _open_group(page, base_url)
    panel_text = await page.locator("#fp-presence-panel").inner_text()
    assert note in panel_text
