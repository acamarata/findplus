"""Browser tests for the Groups tab hint copy and the "Partial" pill tooltip
(UAT7-N07).

The hint under the group selector was only ever shown once a group existed
(groups.js's updateEmptyStateHint() hides it at zero groups), but its own
copy read "Once you have a group, use the selector..." -- future-tense advice
for a state the hint is never actually shown in. Its wording now matches the
state it is shown in.

The "Partial" pill's tooltip stayed "Diverged: ..." even once
groups_presence_render.js's own verdictLabel() (UAT6-N27) downgrades the pill
text itself to "Partial" for a diverged pair with a stale third member --
verdictTitle() must describe the same downgrade, not just the raw diverged
flag. Uses the same page.evaluate() + dynamic import pattern
test_groups_verdict_honesty.py already pins for verdictLabel().
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _verdict_title(page, base_url, presence: dict) -> str:
    await page.goto(base_url + "/")
    return await page.evaluate(
        """async (presence) => {
            const { verdictTitle } = await import('/static/app/groups_presence_render.js');
            return verdictTitle(presence);
        }""",
        presence,
    )


async def test_downgraded_partial_pill_tooltip_explains_partial_not_diverged(page, base_url):
    """Same shape test_groups_verdict_honesty.py's
    test_diverged_with_a_stale_member_reads_partial pins for the pill text
    itself -- the tooltip must follow that same downgrade."""
    title = await _verdict_title(
        page,
        base_url,
        {
            "verdict": "partial",
            "diverged": ["Away Tag"],
            "reporting_count": 2,
            "considered_count": 3,
        },
    )
    assert title == "Partial: some members have no recent fix."


async def test_real_divergence_tooltip_still_explains_diverged(page, base_url):
    """The control: with every member reporting, "Diverged" is not an
    overclaim, and neither is its tooltip."""
    title = await _verdict_title(
        page,
        base_url,
        {
            "verdict": "partial",
            "diverged": ["Away Tag"],
            "reporting_count": 2,
            "considered_count": 2,
        },
    )
    assert title == "Diverged: at least one member is not near the rest of the group."


async def test_plain_partial_with_no_divergence_has_no_tooltip(page, base_url):
    title = await _verdict_title(
        page,
        base_url,
        {"verdict": "partial", "diverged": [], "reporting_count": 1},
    )
    assert title == ""


async def test_all_together_verdict_has_no_tooltip(page, base_url):
    title = await _verdict_title(
        page,
        base_url,
        {"verdict": "all_together", "diverged": [], "reporting_count": 3, "considered_count": 3},
    )
    assert title == ""


async def test_tab_hint_reads_present_tense_while_a_group_exists(page, base_url):
    """Seed (cli/tests/ui/_seed_script.py) always has the "Family" group, so
    the hint is always the shown branch on this suite's install -- the wrong
    half of UAT7-N07 (future-tense copy on a per-group, present-tense hint)."""
    await page.goto(base_url + "/")
    await page.wait_for_selector('button[data-tab="groups"]')
    await page.click('button[data-tab="groups"]')
    hint = page.locator("#fp-groups-tab-hint")
    await hint.wait_for(state="visible")
    text = await hint.inner_text()
    assert text == "Pick a group in the selector above the map to see it."
    assert "Once you have" not in text


async def _empty_groups(route):
    await route.fulfill(status=200, content_type="application/json", body="[]")


async def test_tab_hint_hidden_with_zero_groups(page, base_url):
    """groups.js's updateEmptyStateHint() must still hide the hint at zero
    groups -- the copy fix (present-tense wording) must not touch that
    show/hide branch, which is what keeps the copy from ever being wrong."""
    await page.route("**/api/groups", _empty_groups)
    await page.goto(base_url + "/")
    await page.wait_for_selector('button[data-tab="groups"]')
    await page.evaluate(
        """async () => {
            const groups = await import('/static/app/groups.js');
            await groups.loadGroups();
        }"""
    )
    hint = page.locator("#fp-groups-tab-hint")
    assert await hint.is_hidden()
