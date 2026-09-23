"""axe-core scan of every tab, in both themes, at desktop and phone width.

Purpose    : Automated verification of the WCAG 2.1 AA work in E9-T4/T5 —
             landmarks, labels, focus ring, contrast tokens, dialog roles and
             the phone-tier layout. 4 tabs x 2 themes x 2 widths = 16 scans,
             plus the Devices and Groups dialogs x 2 themes x 2 widths = 8
             more (CR-C-E4 CF-P2-E4-5, CR-C-E5 F8 — neither dialog was ever
             scanned before, which is how both badge/chip contrast failures
             stayed invisible).
Constraints: Only serious and critical violations fail the gate; moderate and
             minor are printed so they are visible in CI output without
             blocking. The tag set is the pinned WCAG 2.x A/AA one — a
             best-practice rule firing is not a WCAG failure.
             axe-playwright-python (and the axe-core engine it bundles) is
             MPL-2.0 and dev/test-only; nothing MPL ships in any artefact.
"""

from __future__ import annotations

import json

import pytest
from axe_playwright_python.async_playwright import Axe

from .conftest import SEEDED_COMPLETED_AT, set_theme

pytestmark = pytest.mark.asyncio(loop_scope="session")

TABS = ("dashboard", "places", "groups", "alerts")
THEMES = ("dark", "light")
#: 1280 = desktop, 375 = the iPhone SE/Mini class width, inside the <600px tier.
WIDTHS = (1280, 375)

AXE_OPTIONS = {
    "resultTypes": ["violations"],
    "runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]},
}

#: `region` is an axe best-practice rule (cat.keyboard), not WCAG-tagged, so
#: AXE_OPTIONS above never surfaces it even at "serious"/"critical" impact --
#: an untagged scan is the only way it was ever found (CF-P2-E9-2, 1 moderate
#: violation, 12 nodes: the cards/alert/filter block sat outside any
#: landmark). Scanning for it alone, rather than dropping the WCAG runOnly
#: filter entirely, keeps this gate from going red on unrelated
#: best-practice rules nothing has audited yet.
REGION_OPTIONS = {
    "resultTypes": ["violations"],
    "runOnly": {"type": "rule", "values": ["region"]},
}

BLOCKING = ("serious", "critical")


def _describe(violation: dict, tab: str, theme: str, width: int) -> str:
    targets = ", ".join(str(node.get("target")) for node in violation.get("nodes", [])[:3])
    return (
        f"{violation['impact']}: {violation['id']} on tab={tab} "
        f"theme={theme} width={width} -> {targets}"
    )


@pytest.mark.parametrize("tab", TABS)
@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("width", WIDTHS)
async def test_no_serious_axe_violations(page, base_url, tab, theme, width):
    await page.set_viewport_size({"width": width, "height": 800})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map")
    # The timeline pane only overflows once its rows are in, and "is this
    # scrollable region keyboard reachable" is one of the rules being scanned:
    # scanning before then made the verdict depend on load timing.
    await page.wait_for_selector("#tracks > *", state="attached")

    # Under 600px the top nav is hidden and the bottom tab bar drives the tabs,
    # so click whichever nav is actually on screen at this width. The bar uses
    # `data-tabbar-tab` so `button[data-tab=...]` stays unique to `.fp-tabs`.
    selector = (
        f'.fp-tabbar [data-tabbar-tab="{tab}"]' if width < 600 else f'.fp-tabs [data-tab="{tab}"]'
    )
    await page.wait_for_selector(selector, state="visible")
    await page.click(selector)

    await set_theme(page, theme)

    results = await Axe().run(page, options=AXE_OPTIONS)
    violations = results.response["violations"]

    for violation in violations:
        if violation.get("impact") not in BLOCKING:
            print(f"axe {_describe(violation, tab, theme, width)}")

    blocking = [v for v in violations if v.get("impact") in BLOCKING]
    assert not blocking, "\n".join(_describe(v, tab, theme, width) for v in blocking)


@pytest.mark.parametrize("width", WIDTHS)
async def test_no_region_violations_on_dashboard(page, base_url, width):
    """CF-P2-E9-2: the cards/alert/filter block now sits inside a named
    `role="region"` landmark (web/index.html's .status-region), closing the
    violation this rule alone (not the pinned WCAG tag scan above) can see.
    """
    await page.set_viewport_size({"width": width, "height": 800})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map")
    await page.wait_for_selector("#tracks > *", state="attached")

    results = await Axe().run(page, options=REGION_OPTIONS)
    violations = results.response["violations"]
    assert not violations, "\n".join(_describe(v, "dashboard", "n/a", width) for v in violations)


DIALOGS = ("devices", "groups")


async def _open_dialog(page, base_url, dialog: str, width: int) -> None:
    """Open one dialog through the real control for this viewport width --
    the same paths `test_no_serious_axe_violations` above, test_responsive.py's
    `_open_tab`/`_open_settings` and test_alerts.py already use: the desktop
    nav directly, or the phone-tier bottom bar / "More" overflow menu. A
    Playwright `.click()` on a control CSS hides under 600px (the old
    `.fp-tabs`-via-`evaluate()` route this replaced) auto-waits for
    visibility and can time out under CI load even when the element is
    reachable -- the real user path is a visible control at every width, so
    drive that instead of reaching around it.

    The icon/colour pickers read the sprite symbols from the DOM synchronously
    the first time a dialog is built (components/icon-picker.js) and never
    retry (test_icon_color_pickers.py's own note on this); wait for the
    sprite's DOM evidence before opening either dialog so a slow
    /static/icons.svg fetch under CI load cannot leave a picker permanently
    empty for the rest of the page's life.
    """
    await page.goto(base_url + "/")
    await page.wait_for_selector("svg#fp-icon-sprite symbol[id='lucide-dog']", state="attached")
    if dialog == "devices":
        await page.wait_for_selector("#map")
        if width < 600:
            # #btn-devices lives in .topbar-actions, CSS-hidden below 600px;
            # the phone tier's own path is the "More" menu, whose relay
            # handler clicks the real button itself (components/tabbar.js).
            await page.click("#btn-more")
            await page.click('[data-relays-to="btn-devices"]')
        else:
            await page.click("#btn-devices")
        await page.wait_for_selector("#device-modal:not(.hidden)")
        await page.wait_for_selector(".device-row")
        await page.click('.device-row[data-device-id="TAG-HOME"] .fp-device-edit')
        await page.wait_for_selector("#fp-device-dialog[open]")
        await page.wait_for_selector("#fp-device-label", state="visible")
    else:
        tab_selector = (
            '.fp-tabbar [data-tabbar-tab="groups"]'
            if width < 600
            else '.fp-tabs [data-tab="groups"]'
        )
        await page.wait_for_selector("#fp-add-group-btn", state="attached")
        await page.click(tab_selector)
        await page.wait_for_selector("#tab-groups:not([hidden])")
        await page.wait_for_selector(".fp-group-card, .fp-empty-state", state="attached")
        await page.click("#fp-add-group-btn")
        await page.wait_for_selector("#fp-group-dialog[open]")
        await page.wait_for_selector("#fp-group-name", state="visible")


@pytest.mark.parametrize("dialog", DIALOGS)
@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("width", WIDTHS)
async def test_no_serious_axe_violations_with_dialog_open(page, base_url, dialog, theme, width):
    await page.set_viewport_size({"width": width, "height": 800})
    await _open_dialog(page, base_url, dialog, width)
    await set_theme(page, theme)

    results = await Axe().run(page, options=AXE_OPTIONS)
    violations = results.response["violations"]

    for violation in violations:
        if violation.get("impact") not in BLOCKING:
            print(f"axe {_describe(violation, dialog, theme, width)}")

    blocking = [v for v in violations if v.get("impact") in BLOCKING]
    assert not blocking, "\n".join(_describe(v, dialog, theme, width) for v in blocking)


#: The two steps UAT3 N26 found placeholder-only inputs on: device label
#: (devices) and token/phone/apikey (notifications, Telegram + WhatsApp).
WIZARD_STEPS = {
    "devices": ".fp-setup-device-row",
    "notifications": "#fp-setup-wa-phone",
}


async def _set_completed_at(page, base_url, value):
    return await page.request.post(
        base_url + "/api/settings/onboarding.completed_at",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


async def _set_last_step(page, base_url, value):
    return await page.request.post(
        base_url + "/api/settings/onboarding.last_step",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


@pytest.mark.parametrize("step", sorted(WIZARD_STEPS))
async def test_no_serious_axe_violations_in_the_wizard(page, base_url, step):
    """UAT3 N26: the Devices and Notifications steps had placeholder-only
    inputs with no accessible name (device label; Telegram token; WhatsApp
    phone/API key) -- axe's `label`/`aria-input-field-name` rules catch a
    regression here. `onboarding.last_step` lands directly on the step under
    test, the same technique test_setup_wizard_signin.py uses, rather than
    clicking Next through the whole wizard once per parametrize case."""
    await page.set_viewport_size({"width": 1280, "height": 800})
    await _set_completed_at(page, base_url, None)
    try:
        await _set_last_step(page, base_url, step)
        await page.goto(base_url + "/#/setup")
        await page.wait_for_selector(WIZARD_STEPS[step], timeout=15000)

        results = await Axe().run(page, options=AXE_OPTIONS)
        violations = results.response["violations"]

        for violation in violations:
            if violation.get("impact") not in BLOCKING:
                print(f"axe {_describe(violation, f'wizard:{step}', 'dark', 1280)}")

        blocking = [v for v in violations if v.get("impact") in BLOCKING]
        assert not blocking, "\n".join(
            _describe(v, f"wizard:{step}", "dark", 1280) for v in blocking
        )
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)
