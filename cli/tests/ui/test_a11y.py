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

import pytest
from axe_playwright_python.async_playwright import Axe

from .conftest import set_theme

pytestmark = pytest.mark.asyncio(loop_scope="session")

TABS = ("dashboard", "places", "groups", "alerts")
THEMES = ("dark", "light")
#: 1280 = desktop, 375 = the iPhone SE/Mini class width, inside the <600px tier.
WIDTHS = (1280, 375)

AXE_OPTIONS = {
    "resultTypes": ["violations"],
    "runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]},
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


DIALOGS = ("devices", "groups")


async def _open_dialog(page, base_url, dialog: str) -> None:
    """Open one dialog the way its own test file does (test_devices_dialog.py /
    test_groups_dialog.py), but drive the trigger with `.click()` via evaluate
    instead of a Playwright click: both triggers sit behind CSS that hides them
    under 600px (topbar-actions / .fp-tabs), the same reason
    test_groups_dialog.py dispatches its own #btn-lock click rather than
    performing one."""
    await page.goto(base_url + "/")
    if dialog == "devices":
        await page.wait_for_selector("#map")
        await page.evaluate("document.getElementById('btn-devices').click()")
        await page.wait_for_selector("#device-modal:not(.hidden)")
        await page.wait_for_selector(".device-row")
        await page.click('.device-row[data-device-id="TAG-HOME"] .fp-device-edit')
        await page.wait_for_selector("#fp-device-dialog[open]")
    else:
        await page.wait_for_selector("#fp-add-group-btn", state="attached")
        await page.evaluate("document.querySelector('.fp-tabs [data-tab=\"groups\"]').click()")
        await page.wait_for_selector(".fp-group-card, .fp-empty-state", state="attached")
        await page.click("#fp-add-group-btn")
        await page.wait_for_selector("#fp-group-dialog[open]")


@pytest.mark.parametrize("dialog", DIALOGS)
@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("width", WIDTHS)
async def test_no_serious_axe_violations_with_dialog_open(page, base_url, dialog, theme, width):
    await page.set_viewport_size({"width": width, "height": 800})
    await _open_dialog(page, base_url, dialog)
    await set_theme(page, theme)

    results = await Axe().run(page, options=AXE_OPTIONS)
    violations = results.response["violations"]

    for violation in violations:
        if violation.get("impact") not in BLOCKING:
            print(f"axe {_describe(violation, dialog, theme, width)}")

    blocking = [v for v in violations if v.get("impact") in BLOCKING]
    assert not blocking, "\n".join(_describe(v, dialog, theme, width) for v in blocking)
