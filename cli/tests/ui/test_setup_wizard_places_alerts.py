"""The wizard Places step: kind and alert state per place, and the dialog alert box."""

from __future__ import annotations

import json

import pytest
import pytest_asyncio

from ._notify_helpers import channels
from .conftest import SEEDED_COMPLETED_AT

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _post(page, base_url, key, value):
    await page.request.post(
        f"{base_url}/api/settings/{key}",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _unfinished(page, base_url):
    await _post(page, base_url, "onboarding.completed_at", None)
    await _post(page, base_url, "onboarding.last_step", "places")
    try:
        yield
    finally:
        await _post(page, base_url, "onboarding.completed_at", SEEDED_COMPLETED_AT)
        await _post(page, base_url, "onboarding.last_step", None)


async def test_place_rows_show_kind_and_alert_state(page, base_url):
    await page.goto(base_url + "/#/setup")
    row = page.locator("#fp-setup-places-list .fp-dialog-field", has_text="Home")
    await row.first.wait_for(timeout=15000)
    text = await row.first.inner_text()
    assert "no alerts yet" in text and ("Home" in text or "Other" in text)


async def test_the_alert_box_points_to_the_notifications_step_when_nothing_is_connected(
    page, base_url, ui_env
):
    with channels(ui_env):
        await page.goto(base_url + "/#/setup")
        await page.wait_for_selector("#fp-setup-places-list", timeout=15000)
        await page.click(".fp-setup-places-add")
        await page.wait_for_selector("#fp-place-dialog[open]")
        line = page.locator("#fp-place-notify-line")
        await page.wait_for_function(
            "() => document.getElementById('fp-place-notify-line')?.textContent.length > 0"
        )
        text = await line.inner_text()
        assert "Connect Telegram on the Notifications step" in text
        assert await page.locator("#fp-place-notify").is_disabled()
