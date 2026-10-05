"""UAT2 N11: the devices list Edit button and the device edit dialog title
use the label-first display name, in normal case.

Seed (cli/tests/ui/conftest.py): TAG-HOME carries label "Ali's Keys"; its raw
provider name is "Home Tag". Split out of test_devices_dialog.py (already at
the size cap) rather than appended there.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

LABEL = "Ali's Keys"


async def _open_devices(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map.leaflet-container")
    await page.wait_for_selector('button[data-tab="places"]')
    await page.click("#btn-devices")
    await page.wait_for_selector("#device-modal:not(.hidden)")
    await page.wait_for_selector(".device-row")


async def test_edit_button_aria_label_uses_the_display_name(page, base_url):
    """The button read "Edit Home Tag" (the raw provider name) even though
    the tag was labelled -- every other surface reads the label first."""
    await _open_devices(page, base_url)
    edit = page.locator('.device-row[data-device-id="TAG-HOME"] .fp-device-edit')
    await edit.wait_for(state="visible")
    aria_label = await edit.get_attribute("aria-label")
    assert aria_label == f"Edit {LABEL}", aria_label
    assert "Home Tag" not in aria_label


async def test_inline_editor_is_named_after_the_display_name(page, base_url):
    """The editor group was named after the raw provider name ("Edit Home Tag")
    even for a labelled tag. It must read the label, like every other surface,
    and the Edit button reports that it expanded the row."""
    await _open_devices(page, base_url)
    edit = page.locator('.device-row[data-device-id="TAG-HOME"] .fp-device-edit')
    assert await edit.get_attribute("aria-expanded") == "false"
    await edit.click()
    editor = page.locator(".device-row.is-editing .device-edit")
    await editor.wait_for(state="visible")
    assert await editor.get_attribute("aria-label") == f"Edit {LABEL}"
    assert await edit.get_attribute("aria-expanded") == "true"
