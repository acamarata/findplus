"""Temporary screenshot harness for the sdw batch (not committed)."""

from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.skipif(not os.environ.get("SDW_SHOTS"), reason="screenshots only"),
]
OUT = "/Volumes/D5/Sites/acamarata/findplus/.claude/temp/r13/shots"
SIZES = {"1400": (1400, 900), "375": (375, 812)}


async def _shot(page, base_url, name, action):
    for scheme in ("light", "dark"):
        for key, (w, h) in SIZES.items():
            await page.set_viewport_size({"width": w, "height": h})
            await page.emulate_media(color_scheme=scheme)
            await page.goto(base_url + "/")
            await page.wait_for_selector("#map.leaflet-container")
            await action(page)
            await page.screenshot(path=f"{OUT}/sdw-{name}-{scheme}-{key}.png")


async def test_settings_shots(page, base_url):
    async def act(p):
        await p.evaluate("document.getElementById('btn-settings').click()")
        await p.wait_for_selector("#settings-modal[data-loaded='true']")
        await p.wait_for_timeout(400)

    await _shot(page, base_url, "settings", act)

    async def act2(p):
        await act(p)
        await p.click("button[data-section='lock']")
        await p.wait_for_timeout(700)

    await _shot(page, base_url, "settings-lock", act2)


async def test_devices_shots(page, base_url):
    async def act(p):
        await p.evaluate("document.getElementById('btn-devices').click()")
        await p.wait_for_selector(".device-row")
        await p.wait_for_timeout(300)

    await _shot(page, base_url, "devices", act)

    async def act2(p):
        await act(p)
        await p.click('.device-row[data-device-id="TAG-HOME"] .fp-device-edit')
        await p.wait_for_selector(".device-edit")
        await p.wait_for_timeout(500)

    await _shot(page, base_url, "devices-edit", act2)


async def test_lock_shots(page, base_url):
    import json

    H = {"Content-Type": "application/json"}
    await page.request.post(base_url + "/api/settings/pin", data=json.dumps({"new_pin": "864213"}), headers=H)
    try:
        for theme, os_scheme in (("light", "dark"), ("dark", "light")):
            await page.request.post(
                base_url + "/api/lock/unlock", data=json.dumps({"pin": "864213"}), headers=H
            )
            await page.request.patch(base_url + "/api/settings", data=json.dumps({"theme": theme}), headers=H)
            await page.request.post(base_url + "/api/lock/lock", headers=H)
            for key, (w, h) in SIZES.items():
                await page.set_viewport_size({"width": w, "height": h})
                await page.emulate_media(color_scheme=os_scheme)
                # A fresh context has no cached theme: emulate that by clearing it.
                await page.goto(base_url + "/")
                await page.evaluate("try { localStorage.clear() } catch (e) {}")
                await page.goto(base_url + "/")
                await page.wait_for_selector("#lock-screen:not(.hidden)")
                await page.wait_for_timeout(300)
                attr = await page.evaluate("document.documentElement.getAttribute('data-theme')")
                print("LOCK", theme, os_scheme, key, "data-theme=", attr)
                await page.screenshot(path=f"{OUT}/sdw-lock-saved{theme}-os{os_scheme}-{key}.png")
    finally:
        await page.request.post(
            base_url + "/api/lock/unlock", data=json.dumps({"pin": "864213"}), headers=H
        )
        await page.request.delete(
            base_url + "/api/settings/pin", data=json.dumps({"current_pin": "864213"}), headers=H
        )
        await page.request.patch(base_url + "/api/settings", data=json.dumps({"theme": "system"}), headers=H)


async def test_wizard_shots(page, base_url):
    import json

    H = {"Content-Type": "application/json"}
    await page.request.post(
        base_url + "/api/settings/onboarding.completed_at", data=json.dumps({"value": None}), headers=H
    )
    for step in ("signin", "groups"):
        await page.request.post(
            base_url + "/api/settings/onboarding.last_step", data=json.dumps({"value": step}), headers=H
        )

        async def act(p, step=step):
            await p.goto(base_url + "/#/setup")
            await p.wait_for_selector("#setup-view .fp-wizard-step h2")
            await p.wait_for_timeout(700)

        await _shot(page, base_url, f"wizard-{step}", act)
    await page.request.post(
        base_url + "/api/settings/onboarding.last_step", data=json.dumps({"value": None}), headers=H
    )
    await page.request.post(
        base_url + "/api/settings/onboarding.completed_at",
        data=json.dumps({"value": "2026-01-01T00:00:00+00:00"}),
        headers=H,
    )
