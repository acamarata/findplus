"""Browser tests for leaving the onboarding wizard (CR-C-E11 F1, F2, F4).

Three holes the review found, one test each: a lock left every field the
wizard had rendered in the document, `#/setup` could be entered but never
left, and "Run setup again" on a finished install opened on the Done step.

Own file rather than extra cases in test_setup_wizard.py, which pins exactly
the six cases specs/onboarding.md § 10 lists (the same reason
test_setup_wizard_native.py exists). `live_server` is shared and assumes a
finished setup, so the autouse fixture restores the stamp in a `finally`.
"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio

from .conftest import SEEDED_COMPLETED_AT

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _post(page, base_url, key, value):
    return await page.request.post(
        f"{base_url}/api/settings/{key}",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _restore(page, base_url):
    try:
        yield
    finally:
        await _post(page, base_url, "onboarding.completed_at", SEEDED_COMPLETED_AT)
        await _post(page, base_url, "onboarding.last_step", None)


async def _open_wizard_at(page, base_url, step):
    await _post(page, base_url, "onboarding.completed_at", None)
    await _post(page, base_url, "onboarding.last_step", step)
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#setup-view .fp-wizard-step", timeout=15000)


async def test_setup_view_collapses_to_zero_height_when_hidden(page, base_url):
    """UAT6 N01: `#setup-view { display: grid }` is a plain id selector, which
    beat the UA `[hidden] { display: none }` rule on specificity alone;
    `#setup-view [hidden]` (a descendant combinator) only ever matched
    something INSIDE the card, never the hidden attribute on the card itself.
    A finished install showed an empty ~48px card above the topbar on every
    load. This walks a normal boot (the seeded install has already completed
    setup) and asserts the card takes up no space at all.
    """
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell:not(.hidden)", timeout=15000)
    display = await page.locator("#setup-view").evaluate("(el) => getComputedStyle(el).display")
    assert display == "none", display
    box = await page.locator("#setup-view").bounding_box()
    assert box is None, box


async def test_the_lock_purge_destroys_the_wizard(page, base_url):
    """#setup-view is a SIBLING of #app-shell, so hiding the shell never hid it.

    Driven through purgeRenderedData(), so what this asserts is the
    registration in lock.js's purgeTabModules(), not setup.purge() in isolation.
    """
    await _open_wizard_at(page, base_url, "applock")
    await page.fill("#fp-setup-pin", "123456")
    await page.fill("#fp-setup-pin-confirm", "123456")

    await page.evaluate(
        """async () => {
            const lock = await import('/static/app/lock.js');
            await lock.purgeRenderedData();
        }"""
    )

    assert await page.locator("#fp-setup-pin").count() == 0
    assert (await page.locator("#setup-view").inner_text()).strip() == ""
    assert "123456" not in await page.content()


async def test_leaving_the_hash_closes_the_wizard(page, base_url):
    """Browser Back, or any link that changes the hash, must leave the route."""
    await _open_wizard_at(page, base_url, "welcome")
    assert await page.locator("#app-shell").is_hidden()

    await page.evaluate("() => { window.location.hash = ''; }")
    await page.wait_for_function(
        "() => document.getElementById('setup-view').hidden === true", timeout=15000
    )
    assert await page.locator("#app-shell").is_visible()
    assert await page.locator("#setup-view .fp-wizard-step").count() == 0


async def test_run_setup_again_on_a_finished_install_starts_at_step_one(page, base_url):
    """`onboarding.last_step` is "done" after a completed run.

    Honouring it on a re-entry opened the summary with nothing to do, which is
    the one screen a user clicking "Run setup again" does not want.
    """
    await _post(page, base_url, "onboarding.completed_at", "2026-05-05T05:05:05Z")
    await _post(page, base_url, "onboarding.last_step", "done")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#setup-view .fp-wizard-step", timeout=15000)

    progress = await page.locator(".fp-wizard-progress-text").inner_text()
    assert progress.strip().startswith("1"), progress
    assert await page.locator("#fp-wizard-back").is_hidden()


async def test_the_wizard_can_be_walked_on_the_keyboard(page, base_url):
    """Next is disabled for the length of a transition (CR-C-E11 F8).

    Disabling the focused button drops focus to <body>, so the guard puts it
    back; without that a keyboard user restarts the Tab cycle on every step.
    """
    await _open_wizard_at(page, base_url, "welcome")
    await page.focus("#fp-wizard-next")
    await page.keyboard.press("Enter")
    await page.wait_for_selector("#fp-setup-signin-status", timeout=15000)
    await page.wait_for_function(
        "() => !document.getElementById('fp-wizard-next').disabled", timeout=15000
    )
    assert await page.evaluate("() => document.activeElement.id") == "fp-wizard-next"
