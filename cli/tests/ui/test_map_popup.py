"""UAT2 N14: a map marker's popup names its tracker as the heading.

Seed (cli/tests/ui/conftest.py): TAG-HOME carries label "Ali's Keys"; its raw
provider name is "Home Tag". A new file rather than an addition to
test_devices_dialog.py, which is already at the size cap.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

LABEL = "Ali's Keys"


async def test_popup_heading_is_the_tracker_display_name(page, base_url):
    """The popup used to open on a bare "<time>" heading with the tracker's
    name (if shown at all) reading as a small subtitle underneath -- with
    more than one track on screen there was no way to tell whose fix a
    popup belonged to at a glance."""
    await page.goto(base_url + "/")
    await page.wait_for_selector(".marker-num-glyph svg")
    await page.locator(f'.leaflet-marker-icon[title^="{LABEL}"]').first.click()
    await page.wait_for_selector(".leaflet-popup-content")
    heading = page.locator(".leaflet-popup-content b").first
    assert await heading.inner_text() == LABEL
    # The old heading (a bare time) is still shown, just demoted to the
    # subtitle line right under the tracker's name.
    sub = page.locator(".leaflet-popup-content .fp-popup-sub").first
    assert await sub.inner_text() != ""
    assert LABEL not in await sub.inner_text()
