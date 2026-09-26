"""Browser tests for smaller Places-tab polish fixes (UAT6 N16, N26, N28).

Seed data (cli/tests/ui/conftest.py): place "Home" already exists, so the
"Add place" hint and the "next default colour" tests both start from a
non-empty install on purpose.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_places(page, base_url):
    await page.goto(base_url + "/")
    await page.click('button[data-tab="places"]')


async def test_add_place_hint_hides_once_a_place_exists(page, base_url):
    """N26: 'Use Add place to create a geofence.' only helps before any place
    exists; the seeded "Home" place means it must already be hidden."""
    await _open_places(page, base_url)
    await page.wait_for_selector("#fp-places-list .fp-place-card")
    assert await page.locator("#fp-places-tab-hint").is_hidden()


async def test_place_circle_shows_a_permanent_name_label(page, base_url):
    """N26: a circle used to say which place it was only through colour and
    a click-to-open popup; the name is now a permanent on-map label."""
    await _open_places(page, base_url)
    await page.wait_for_selector(".fp-place-tooltip")
    text = await page.locator(".fp-place-tooltip").first.inner_text()
    assert text  # the seeded place's real name, whatever it is


async def test_new_place_default_colour_differs_from_the_first_place(page, base_url):
    """N26: every new place used to start the same blue regardless of how
    many already existed."""
    resp = await page.request.get(base_url + "/api/places")
    existing = await resp.json()
    first_color = existing[0]["color"] if existing else None

    await _open_places(page, base_url)
    await page.click("#fp-add-place-btn")
    dialog = page.locator("#fp-place-dialog")
    await dialog.wait_for(state="visible")
    color = await dialog.locator("#fp-place-color").input_value()
    if first_color:
        assert color.lower() != first_color.lower()


async def test_empty_name_blocks_save_before_any_server_round_trip(page, base_url):
    """N16: reportValidity() must catch this before it ever reaches the
    server as a raw 422."""
    await _open_places(page, base_url)
    await page.click("#fp-add-place-btn")
    dialog = page.locator("#fp-place-dialog")
    await dialog.wait_for(state="visible")
    await dialog.get_by_text("Save", exact=True).click()
    assert await page.locator("#fp-place-dialog[open]").count() == 1
    assert await dialog.locator("#fp-place-dialog-error").inner_text() == ""


async def test_out_of_range_radius_maps_to_a_friendly_sentence(page, base_url):
    """N16: places/repo.py's own floor (20 m) sits below the dialog's slider
    floor (50 m), so the only way a real save still reaches this 422 is a
    client bypassing the slider -- exercised at the dialog_errors.js unit
    level instead, the same way duplicateNameMessage() is proven without a
    real 409 round trip."""
    await page.goto(base_url + "/")
    message = await page.evaluate(
        """async () => {
            const { placeValidationMessage } = await import('/static/app/dialog_errors.js');
            const err = new Error('radius_meters must be 20-5000');
            err.status = 422;
            return placeValidationMessage(err);
        }"""
    )
    assert message == "Radius must be between 20 and 5000 meters."
    assert "radius_meters" not in message


async def test_icon_picker_shows_category_headings(page, base_url):
    """N28: category boundaries used to be invisible, so uneven row lengths
    ("rows of 9, 8, 9, 9, 4…") read as a layout bug."""
    await page.goto(base_url + "/")
    await page.wait_for_selector("svg#fp-icon-sprite symbol[id='lucide-dog']", state="attached")
    headings = await page.evaluate(
        """async () => {
            const { createIconPicker } = await import('/static/app/components/icon-picker.js');
            const host = document.createElement('div');
            document.body.appendChild(host);
            createIconPicker(host, { value: 'letter' });
            return [...host.querySelectorAll('.fp-icon-group-heading')].map((el) => el.textContent);
        }"""
    )
    assert "Pets" in headings
    assert "Other" in headings
    assert len(headings) == len(set(headings)), "each category heading must be distinct"


async def test_custom_color_swatch_is_round(page, base_url):
    """N28: the custom swatch used to paint as a native rectangle beside 12
    round palette swatches."""
    await page.goto(base_url + "/")
    radius = await page.evaluate(
        """async () => {
            const { createColorPicker } = await import('/static/app/components/color-picker.js');
            const host = document.createElement('div');
            document.body.appendChild(host);
            createColorPicker(host, {});
            const el = host.querySelector('.fp-color-custom');
            return getComputedStyle(el).borderRadius;
        }"""
    )
    assert radius not in ("0px", ""), f"expected a round swatch, got border-radius {radius!r}"
