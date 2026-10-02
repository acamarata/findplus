"""The Apple 2FA step: SMS-aware wording, a format check, Enter to verify, Start over."""

from __future__ import annotations

import pytest

from ._signin_helpers import open_wizard_signin, reply, restore_onboarding, wait_text
from .test_signin_states_apple import ERROR, _to_code_step

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_the_prompt_names_the_trusted_device_and_offers_a_text(page, base_url):
    try:
        await open_wizard_signin(page, base_url)
        await _to_code_step(page)
        text = await page.locator("#fp-setup-apple-2fa").inner_text()
        assert "iPhone, iPad or Mac" in text
        assert await page.get_by_role("button", name="Use a text message instead").is_visible()
    finally:
        await restore_onboarding(page, base_url)


async def test_a_code_that_is_not_six_digits_is_refused_before_it_is_sent(page, base_url):
    sent: list[str] = []
    try:
        await open_wizard_signin(page, base_url)
        await _to_code_step(page)
        await page.route("**/api/auth/apple/code", reply({}, 200, sent))
        await page.fill("#fp-setup-apple-code", "12ab")
        await page.get_by_role("button", name="Verify code").click()
        await wait_text(page, ERROR, "6 digits")
        assert sent == []
        # Spaces are fine: "123 456" is sent as 123456.
        await page.fill("#fp-setup-apple-code", "123 456")
        await page.press("#fp-setup-apple-code", "Enter")
        await page.wait_for_timeout(300)
        assert len(sent) == 1
    finally:
        await restore_onboarding(page, base_url)


async def test_start_over_returns_to_the_apple_id_form(page, base_url):
    try:
        await open_wizard_signin(page, base_url)
        await _to_code_step(page)
        await page.get_by_role("button", name="Start over").click()
        assert await page.locator("#fp-setup-apple-2fa").is_hidden()
        assert await page.locator("#fp-setup-apple-form").is_visible()
    finally:
        await restore_onboarding(page, base_url)
