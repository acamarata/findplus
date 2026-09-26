"""Browser tests for the Groups verdict-honesty fix (UAT6 N27).

A group can have two members genuinely diverged from each other while a
third has simply never reported. The server's own verdict_label()
(findplus.groups.presence) still says "Diverged" for that combination --
true about the reporting pair, but a confident headline for a group Find+
only partly heard from (the UAT screenshot: "Diverged" as the pill, "...;
Stale Tag has no recent fix." only in the body underneath it).
groups_presence_render.js's own verdictLabel() downgrades that one
combination (a `partial` verdict, at least one stale/no-fix member, and a
non-empty diverged list) to "Partial" client-side; every other verdict
combination -- including plain divergence with nobody stale -- is
unchanged, per test_groups.py's own pinned
test_real_divergence_is_still_labelled_diverged.

Seed data (cli/tests/ui/conftest.py): group "Family" is used only to reach
the Groups tab and #fp-presence-panel; every scenario below is injected
directly through renderPresencePanel()/verdictLabel(), the same pattern
test_groups.py's own honesty tests use.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_group(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#fp-group-select")
    await page.select_option("#fp-group-select", label="Family")
    await page.click('button[data-tab="groups"]')
    await page.wait_for_selector("#fp-presence-panel .fp-verdict")


async def test_diverged_with_a_stale_member_reads_partial(page, base_url):
    await _open_group(page, base_url)

    label = await page.evaluate(
        """async () => {
            const groups = await import('/static/app/groups.js');
            groups.renderPresencePanel({
                verdict: 'partial',
                verdict_label: 'Diverged',
                together: ['Home Tag'],
                diverged: ['Away Tag'],
                stale: ['Backpack Tag'],
                reporting_count: 2,
                considered_count: 3,
                members: [],
                note: 'Away Tag is away from Home Tag (900 m apart); Backpack has no recent fix.',
            });
            return document.querySelector('#fp-presence-panel .fp-verdict').textContent;
        }"""
    )
    assert label == "Partial"


async def test_diverged_with_no_stale_member_still_reads_diverged(page, base_url):
    """The control: with every member reporting, "Diverged" is not an
    overclaim and must stay (matches test_groups.py's own
    test_real_divergence_is_still_labelled_diverged)."""
    await _open_group(page, base_url)

    label = await page.evaluate(
        """async () => {
            const groups = await import('/static/app/groups.js');
            groups.renderPresencePanel({
                verdict: 'partial',
                verdict_label: 'Diverged',
                together: ['Home Tag'],
                diverged: ['Away Tag'],
                stale: [],
                reporting_count: 2,
                considered_count: 2,
                members: [],
                note: 'Away Tag is away from Home Tag (900 m apart)',
            });
            return document.querySelector('#fp-presence-panel .fp-verdict').textContent;
        }"""
    )
    assert label == "Diverged"


async def test_group_card_badge_also_reads_partial(page, base_url):
    """groups_list.js's card badge calls the same verdictLabel() -- the fix
    must not land only on the presence-panel headline and leave the card
    pill confident (the exact split the UAT screenshot showed)."""
    await _open_group(page, base_url)

    label = await page.evaluate(
        """async () => {
            const { verdictLabel } = await import('/static/app/groups_presence_render.js');
            return verdictLabel({
                verdict: 'partial',
                verdict_label: 'Diverged',
                diverged: ['Away Tag'],
                reporting_count: 2,
                considered_count: 3,
            });
        }"""
    )
    assert label == "Partial"


async def test_one_reporting_member_with_no_considered_count_is_unaffected(page, base_url):
    """An older daemon's response (no considered_count field at all) must
    keep working exactly as test_groups.py's own
    test_one_reporting_member_is_not_labelled_diverged pins it -- the new
    stale-aware branch only fires when considered_count says how many
    members exist at all."""
    await _open_group(page, base_url)

    label = await page.evaluate(
        """async () => {
            const { verdictLabel } = await import('/static/app/groups_presence_render.js');
            return verdictLabel({
                verdict: 'partial',
                diverged: [],
                reporting_count: 1,
            });
        }"""
    )
    assert label == "Only 1 reporting"
