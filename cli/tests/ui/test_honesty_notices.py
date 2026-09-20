"""The dashboard footer names the right provider (E1 honesty pass F1).

The footer rendered `honesty.FIND_HUB` unconditionally, so someone tracking only
Apple accessories read that their tags report through Google's Find Hub network.
Seed data (cli/tests/ui/conftest.py) includes the untracked Apple device TAG-AIR
so a loaded dashboard always has one provider of each kind.
"""

from __future__ import annotations

import pytest

from findplus import honesty

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_dashboard(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map")


async def test_footer_shows_the_apple_sentence_when_an_apple_tracker_is_present(page, base_url):
    """Both sentences render, each verbatim from /api/config.notices."""
    await _open_dashboard(page, base_url)

    await page.wait_for_function(
        "() => !document.getElementById('apple-notice').hidden",
        timeout=5000,
    )

    assert await page.locator("#apple-notice").text_content() == honesty.APPLE
    assert await page.locator("#findhub-notice").text_content() == honesty.FIND_HUB


async def test_footer_hides_the_apple_sentence_without_an_apple_tracker(page, base_url):
    """The notice is device-derived, not a constant: a Google-only list hides it."""
    await _open_dashboard(page, base_url)
    await page.wait_for_function(
        "() => !document.getElementById('apple-notice').hidden",
        timeout=5000,
    )

    hidden = await page.evaluate(
        """async () => {
            const [state, devices] = await Promise.all([
                import('/static/app/state.js'),
                import('/static/app/devices.js'),
            ]);
            state.state.devices = state.state.devices.filter(
                (d) => d.provider !== 'apple-find-my'
            );
            devices.syncProviderNotice();
            const el = document.getElementById('apple-notice');
            return el.hidden && el.textContent === '';
        }"""
    )
    assert hidden is True
