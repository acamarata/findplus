#!/usr/bin/env python3
"""Playwright driver: walk #/setup end to end at 1280 and 375 px.

Purpose    : Drive the real onboarding wizard against the fixture-fronted
             daemon (BASE_URL) exactly as a first-time user would, at both
             breakpoints D-P2-12 pins, screenshotting every step, and prove
             the labeled device and group actually land on the dashboard.
Inputs     : BASE_URL, OUT_DIR environment variables (rehearse-first-run.sh).
Outputs    : 16 PNGs (8 steps x 2 widths) in OUT_DIR; raises (non-zero exit)
             on any failed assertion.
Constraints: Screenshots BEFORE each step's forward action, so the image
             shows the step as the user reads it (not the state after moving
             on). Only the 1280-width pass verifies the dashboard afterward
             (specs/onboarding.md § 4; the 375-width pass only re-proves the
             wizard itself renders at the phone breakpoint).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx
from playwright.async_api import Page, async_playwright

BASE_URL = os.environ["BASE_URL"]
OUT_DIR = Path(os.environ["OUT_DIR"])
STEPS = ("welcome", "signin", "devices", "groups", "places", "notifications", "applock", "done")
SKIP_STEPS = {"places", "notifications", "applock"}
NEXT, SKIP = "#fp-wizard-next", "#fp-wizard-skip"


async def _welcome(page: Page) -> None:
    text = await page.locator("#setup-view").inner_text()
    assert "not affiliated with Apple or Google" in text, text


async def _signin(page: Page) -> None:
    wizard = page.locator("#setup-view")
    await wizard.get_by_role("button", name="Sign in with Google").click()
    await page.locator("#fp-setup-signin-status", has_text="test@example.invalid").wait_for(
        timeout=15000
    )


async def _devices(page: Page) -> None:
    rows = page.locator("#fp-setup-devices-list .fp-dialog-field")
    await rows.first.wait_for(timeout=15000)
    await page.locator("#setup-view").get_by_role("button", name="Edit").first.click()
    await page.fill("#fp-device-label", "Test Tag")
    await page.click('#fp-device-dialog .fp-icon-swatch[data-icon-id="lucide:key"]')
    await page.click('#fp-device-dialog .fp-color-swatch[data-color="#4f8cf7"]')
    await page.check("#fp-device-tracked")
    await page.click("#fp-device-dialog button.btn")
    # The row shows the provider name, not the label (dashboard's #device-list
    # shows d.label || d.name, per web/app/devices.js) -- the label only
    # round-trips through the row's own text input's value. Re-query by
    # selector on every poll: the dialog's onSaved callback rebuilds the row
    # (renderRows() clears and re-appends), so a handle captured before the
    # save points at a now-detached node that never changes.
    await page.wait_for_function(
        "sel => { const el = document.querySelector(sel); return !!el && el.value === 'Test Tag'; }",
        arg="#fp-setup-devices-list input[type=text]",
        timeout=15000,
    )


async def _groups(page: Page) -> None:
    await page.fill("#fp-setup-group-name", "Test Group")
    await page.click("#fp-setup-group-color-btn")
    await page.click('#fp-setup-group-color-popover .fp-color-swatch[data-color="#37c67a"]')
    await page.locator("#setup-view").get_by_role("button", name="Add", exact=True).click()
    await page.locator("#fp-setup-groups-list", has_text="Test Group").wait_for(timeout=15000)


async def _done(page: Page) -> None:
    await page.locator("#setup-view h2", has_text="You're set up").wait_for(timeout=15000)


STEP_ACTIONS = {"welcome": _welcome, "signin": _signin, "devices": _devices,
                "groups": _groups, "done": _done}


async def verify_dashboard(page: Page) -> None:
    # A bare reload first, THEN a hash change: navigating straight to
    # BASE_URL/#devices raced main()'s own boot chain on this rehearsal
    # (groups.js's dashboard init() never ran, #fp-groups-list stayed on its
    # static "No groups yet" markup) -- landing on "/" and changing the hash
    # afterward is also what a real user does (open the dashboard, then click
    # Devices) and is reliable. #device-list is the Devices dialog's own row
    # container (devices.js's renderDeviceModal(), populated only by
    # openDevices(), which the #devices hash triggers). #fp-groups-list is
    # populated at boot (groups.js's init()) but sits inside the inactive
    # Groups tab panel, so it exists without being "visible" -- state=
    # "attached" reads it without a tab click.
    await page.goto(BASE_URL)
    await page.locator("#fp-groups-list", has_text="Test Group").wait_for(
        state="attached", timeout=20000
    )
    await page.evaluate("location.hash = '#devices'")
    await page.locator("#device-list", has_text="Test Tag").wait_for(timeout=20000)
    html = await page.content()
    assert "lucide-key" in html, "device icon missing from dashboard DOM"
    assert "#4f8cf7" in html, "device colour missing from dashboard DOM"
    assert "#37c67a" in html, "group colour missing from dashboard DOM"
    async with httpx.AsyncClient() as client:
        settings = (await client.get(f"{BASE_URL}/api/settings", timeout=10)).json()
    assert settings["onboarding.completed_at"], settings


async def drive(page: Page, width: int, verify: bool) -> None:
    await page.goto(f"{BASE_URL}/#/setup")
    await page.locator("#setup-view").wait_for(timeout=20000)
    for step in STEPS:
        await page.locator(".fp-wizard-progress").wait_for(timeout=15000)
        action = STEP_ACTIONS.get(step)
        if action:
            await action(page)
        else:
            await page.wait_for_timeout(500)  # let onEnter's fetch settle
        await page.screenshot(path=str(OUT_DIR / f"{step}-{width}.png"))
        await page.click(SKIP if step in SKIP_STEPS else NEXT)
    if verify:
        await verify_dashboard(page)


async def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        for width, height in ((1280, 800), (375, 812)):
            context = await browser.new_context(viewport={"width": width, "height": height})
            page = await context.new_page()
            await drive(page, width, verify=(width == 1280))
            await context.close()
        await browser.close()
    print("rehearse-first-run-drive: 16 screenshots written")


if __name__ == "__main__":
    asyncio.run(main())
