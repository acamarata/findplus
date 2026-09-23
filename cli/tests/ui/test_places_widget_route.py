"""`#places` hash route: the Places widget's tap target.

The macOS Places widget (`desktop/widget/`) opens `findplus://places`, which
`urlscheme.rs` maps to `windows::open_places` -> the dashboard window at
`/#places`. main.js's `applyHashRoute` must switch to the Places tab for
that hash, same as `#settings`/`#devices` already do for their own targets.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_places_hash_activates_the_places_tab(page, base_url):
    # `windows::open_places` builds a fresh window at ".../#places" when none
    # is open yet (windows.rs). main()'s own boot chain is still running when
    # the page first paints (build-notes.md's documented boot-race gotcha),
    # so this settles before asserting rather than racing it.
    await page.goto(base_url + "/#places")
    await page.wait_for_selector("#map.leaflet-container")
    await page.wait_for_timeout(1000)

    tab = page.locator('button[data-tab="places"]')
    await page.wait_for_function(
        """() => {
            const btn = document.querySelector('button[data-tab="places"]');
            return !!btn && btn.classList.contains('active');
        }""",
        timeout=10000,
    )
    assert await tab.get_attribute("class") == "fp-tab active"


async def test_places_hash_after_boot_still_switches_tabs(page, base_url):
    """A hashchange (not just the initial load) must route the same way."""
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map.leaflet-container")

    await page.evaluate("window.location.hash = '#places'")
    await page.wait_for_function(
        """() => {
            const btn = document.querySelector('button[data-tab="places"]');
            return !!btn && btn.classList.contains('active');
        }""",
        timeout=5000,
    )
