"""Settings: the save model, the cost of the polling interval, retention, backup, language.

Purpose    : Every Settings control saves as it changes, so each save says "Saved.";
             the interval shows its requests-per-hour cost before it is chosen;
             retention says what it deletes; the settings can be downloaded; the
             language row says English is the only one for now.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open(page, base_url) -> None:
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell[data-fp-ready='dashboard']")
    await page.click("#btn-settings")
    await page.wait_for_selector("#settings-modal[data-loaded='true']")


async def test_the_dialog_says_it_saves_by_itself_and_confirms_each_save(page, base_url):
    await _open(page, base_url)
    assert "no Save button" in await page.locator(".settings-intro").inner_text()
    assert await page.locator("#settings-saved").inner_text() == ""
    original = await page.input_value("#setting-theme")
    await page.select_option("#setting-theme", "light" if original != "light" else "dark")
    try:
        await page.locator("#settings-saved", has_text="Saved.").wait_for()
    finally:
        await page.select_option("#setting-theme", original)


async def test_the_interval_shows_its_requests_per_hour_before_it_is_saved(page, base_url):
    await _open(page, base_url)
    status = await (await page.request.get(base_url + "/api/status")).json()
    tracked = status["tracked_count"]
    assert tracked > 0
    await page.fill("#setting-poll-interval", "10")
    text = await page.locator("#setting-poll-rate").inner_text()
    assert f"about {tracked * 6} location requests an hour" in text
    await page.fill("#setting-poll-interval", "5")
    assert "Short intervals add up" in await page.locator("#setting-poll-rate").inner_text()
    await page.fill("#setting-poll-interval", "2")
    assert await page.locator("#setting-poll-rate").inner_text() == ""


async def test_retention_explains_itself_and_refuses_under_seven_days(page, base_url):
    await _open(page, base_url)
    await page.fill("#setting-retention-days", "")
    assert "kept" in await page.locator("#setting-retention-effect").inner_text()
    await page.fill("#setting-retention-days", "30")
    effect = await page.locator("#setting-retention-effect").inner_text()
    assert "older than 30 days" in effect
    assert "cannot be undone" in effect
    await page.fill("#setting-retention-days", "3")
    await page.dispatch_event("#setting-retention-days", "change")
    await page.locator("#setting-retention-error").wait_for(state="visible")
    assert await page.get_attribute("#setting-retention-days", "aria-invalid") == "true"
    settings = await (await page.request.get(base_url + "/api/settings")).json()
    assert settings["history.retention_days"] != 3


async def test_download_settings_gives_json_without_the_pin(page, base_url):
    await _open(page, base_url)
    async with page.expect_download() as info:
        await page.click("#btn-export-settings")
    download = await info.value
    assert download.suggested_filename.startswith("findplus-settings-")
    body = json.loads(Path(await download.path()).read_text())
    assert "theme" in body
    assert "pin_hash" not in body and "pin_salt" not in body


async def test_language_row_is_english_only_and_says_so(page, base_url):
    await _open(page, base_url)
    assert await page.locator("#setting-language").is_disabled()
    assert "English only for now" in await page.locator("#settings-modal").inner_text()
