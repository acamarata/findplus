"""Places tab: the address-search privacy sentence is shown in the place dialog.

Invariant map (cli/tests/INVARIANTS.md, honesty `address_search`): the sentence
comes from honesty.py via the i18n catalog and must be on screen before the
user presses Search. Behaviour of the search itself: test_places.py.
"""

from __future__ import annotations

import pytest

from findplus.honesty import ADDRESS_SEARCH

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_the_place_dialog_states_where_address_search_sends_text(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map.leaflet-container")
    await page.click('button[data-tab="places"]')
    await page.click("#fp-add-place-btn")
    dialog = page.locator("#fp-place-dialog")
    await dialog.wait_for(state="visible")
    assert ADDRESS_SEARCH in await dialog.inner_text()
