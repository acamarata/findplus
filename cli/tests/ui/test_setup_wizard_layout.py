"""Browser tests for the wizard's presentation fixes (R-P2-28, visual gate W4).

Purpose    : Pins the six points of ruling R-P2-28: the wizard renders inside a
             bounded, centred card (point 1); the Groups step's icon/colour
             pickers are popover triggers, not a bare grid (point 2); the
             Notifications step offers WhatsApp inline (point 3); the Places
             step hides the dashboard's "Observed path" disclaimer while its
             map is borrowed (point 5). Point 4 (sign-in sub-headings) and
             point 6 (delivery-log Status column) are covered by
             test_setup_wizard_signin.py's fixtures being extended here rather
             than a new file, and by the alerts suite respectively — see the
             two tests at the bottom of this file.
Constraints: Own file, matching test_setup_wizard_native.py's reasoning: these
             are new coverage, not one of the six specs/onboarding.md § 10
             cases test_setup_wizard.py already owns. `live_server` is shared
             and assumes a finished setup, so every wizard test here restores
             the stamp in a `finally` the same way the sibling files do.
"""

from __future__ import annotations

import json

import pytest
from axe_playwright_python.async_playwright import Axe

from findplus.honesty import CHROME_REQUIRED, WHATSAPP_RELAY, WHATSAPP_SETUP

from .conftest import SEEDED_COMPLETED_AT, set_theme
from .test_a11y import AXE_OPTIONS, BLOCKING, _describe

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _set_completed_at(page, base_url, value):
    await page.request.post(
        base_url + "/api/settings/onboarding.completed_at",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


async def _set_last_step(page, base_url, value):
    await page.request.post(
        base_url + "/api/settings/onboarding.last_step",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


async def _open_step(page, base_url, step):
    await _set_completed_at(page, base_url, None)
    await _set_last_step(page, base_url, step)
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#setup-view .fp-wizard-step", timeout=15000)


@pytest.mark.parametrize("step", ["welcome", "groups", "notifications", "applock"])
async def test_wizard_card_is_bounded_and_centred_at_1280(page, base_url, step):
    """R-P2-28 point 1: max-width 720px, centred, not edge-to-edge."""
    await page.set_viewport_size({"width": 1280, "height": 900})
    try:
        await _open_step(page, base_url, step)
        box = await page.locator("#setup-view").bounding_box()
        assert box is not None
        assert box["width"] <= 760, box
        # Centred: roughly equal space on both sides of the 1280px viewport.
        left_gutter = box["x"]
        right_gutter = 1280 - (box["x"] + box["width"])
        assert abs(left_gutter - right_gutter) < 5, (left_gutter, right_gutter)

        # Every footer control stays inside the card, not spilling past it.
        next_box = await page.locator("#fp-wizard-next").bounding_box()
        assert next_box["x"] + next_box["width"] <= box["x"] + box["width"] + 1
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


@pytest.mark.parametrize("step", ["welcome", "groups", "notifications", "applock"])
async def test_wizard_has_no_horizontal_overflow_at_375(page, base_url, step):
    """R-P2-28 point 1: full-width with 16px gutters below 600px, never wider
    than the viewport (F1/F2 both only reproduced with real content on screen,
    so this walks the same four steps the 1280px check does)."""
    await page.set_viewport_size({"width": 375, "height": 800})
    try:
        await _open_step(page, base_url, step)
        overflow = await page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 1, f"{step}: {overflow}px of horizontal overflow"
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_groups_step_uses_popover_pickers_not_a_bare_grid(page, base_url):
    """R-P2-28 point 2 / F1: the icon and colour grids sit behind trigger
    buttons, like the group dialog's own fields, closed until clicked."""
    try:
        await _open_step(page, base_url, "groups")
        await page.wait_for_selector("#fp-setup-group-icon-btn", timeout=15000)

        assert await page.locator("#fp-setup-group-icon-popover").is_hidden()
        assert await page.locator("#fp-setup-group-color-popover").is_hidden()
        # The member checklist row uses the dialog's own class, not the wide
        # settings row (F1's root cause).
        await page.wait_for_selector(".fp-member-row", timeout=15000)
        assert await page.locator(".fp-member-row").count() >= 1

        await page.click("#fp-setup-group-icon-btn")
        await page.wait_for_selector("#fp-setup-group-icon-popover:not([hidden])", timeout=5000)
        assert await page.locator("#fp-setup-group-color-popover").is_hidden()

        # An open popover overlays whatever sits below it (real dropdown
        # behaviour), so a real user closes it — outside click, same path the
        # group dialog's own popovers use — before reaching the next trigger.
        await page.click("#fp-setup-groups-list")
        await page.wait_for_selector("#fp-setup-group-icon-popover", state="hidden", timeout=5000)

        await page.click("#fp-setup-group-color-btn")
        await page.wait_for_selector("#fp-setup-group-color-popover:not([hidden])", timeout=5000)
        assert await page.locator("#fp-setup-group-icon-popover").is_hidden()

        # Outside click closes whichever popover is open.
        await page.click("#fp-setup-groups-list")
        await page.wait_for_selector("#fp-setup-group-color-popover", state="hidden", timeout=5000)
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_notifications_step_whatsapp_save_and_test(page, base_url):
    """R-P2-28 point 3 / F4: WhatsApp gets inline phone/API-key/Save/Test,
    exactly like Telegram, instead of only a "configure later" link."""
    saved = {}
    tested = {}

    async def save_route(route):
        saved["body"] = json.loads(route.request.post_data)
        await route.fulfill(
            status=200, content_type="application/json", body=json.dumps({"ok": True})
        )

    async def test_route(route):
        tested["body"] = json.loads(route.request.post_data)
        await route.fulfill(
            status=200, content_type="application/json", body=json.dumps({"status": "sent"})
        )

    try:
        await page.route("**/api/alerts/channels/whatsapp", save_route)
        await page.route("**/api/alerts/test", test_route)
        await _open_step(page, base_url, "notifications")
        await page.wait_for_selector("[data-channel='whatsapp']", timeout=15000)

        assert await page.locator("#fp-setup-wa-phone").count() == 1
        assert await page.locator("#fp-setup-wa-apikey").count() == 1

        # T0 addendum B3: both honesty sentences render above the fields.
        section_text = await page.locator("[data-channel='whatsapp']").inner_text()
        assert WHATSAPP_RELAY in section_text
        assert WHATSAPP_SETUP in section_text

        await page.fill("#fp-setup-wa-phone", "+34999888777")
        await page.fill("#fp-setup-wa-apikey", "wizard-test-key")
        await page.click("#fp-setup-wa-save")
        await page.wait_for_timeout(300)
        assert saved["body"] == {"phone": "+34999888777", "apikey": "wizard-test-key"}

        await page.click("#fp-setup-wa-test")
        await page.wait_for_timeout(200)
        assert tested["body"] == {"channel": "whatsapp"}

        # Webhook still only offers the "configure later" link, styled with
        # the app's link token rather than the browser default blue (F5).
        link = page.locator("[data-channel='webhook'] a")
        color = await link.evaluate("(el) => getComputedStyle(el).color")
        assert color not in ("rgb(0, 0, 238)", ""), color
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_places_step_hides_the_observed_path_disclaimer(page, base_url):
    """R-P2-28 point 5 / F3: a first-run, near-empty map has no observed path
    for the dashboard's disclaimer to describe."""
    try:
        await _open_step(page, base_url, "places")
        await page.wait_for_selector("#fp-setup-map-host #map", timeout=15000)
        assert await page.locator("#path-disclaimer").is_hidden()
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_places_step_restores_the_disclaimer_on_leaving(page, base_url):
    try:
        await _open_step(page, base_url, "places")
        await page.wait_for_selector("#fp-setup-map-host #map", timeout=15000)
        await page.evaluate("() => { window.location.hash = ''; }")
        await page.wait_for_function(
            "() => document.getElementById('setup-view').hidden === true", timeout=15000
        )
        assert await page.locator("#path-disclaimer").is_visible()
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_deliveries_status_column_visible_at_1280_without_horizontal_scroll(page, base_url):
    """R-P2-28 point 6 / F6: Status (7th of 8 columns) used to sit past the
    380px side pane's edge, reachable only by scrolling the whole page.

    The headers are enough to pin the layout: this suite's seed data carries
    no alert_deliveries rows (nothing here runs the poll/evaluate loop that
    would create one), and test_alerts_whatsapp.py's own delivery-log test
    makes the same choice — it waits for the table, not for a row.
    """
    await page.set_viewport_size({"width": 1280, "height": 900})
    await page.goto(base_url + "/#dashboard")
    await page.wait_for_selector("#map")
    await page.click('button[data-tab="alerts"]')
    await page.wait_for_selector("#fp-deliveries-table", timeout=15000)

    status_header = page.locator("#fp-deliveries-table thead th").nth(6)
    assert await status_header.text_content() == "Status"
    box = await status_header.bounding_box()
    pane = await page.locator(".timeline-pane").bounding_box()
    assert box is not None and pane is not None
    assert box["x"] + box["width"] <= pane["x"] + pane["width"] + 1, (box, pane)

    page_overflow = await page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert page_overflow <= 1, page_overflow


async def test_signin_step_shows_chrome_notice_before_any_click(page, base_url):
    """T0 addendum B5: GET /api/auth/status's `needs: ["chrome"]` (already
    computed by providers/auth_status.py) is read on entry, not only after a
    failed click, and the Google button is disabled while it applies."""

    async def status_route(route):
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "providers": [
                        {
                            "id": "google-find-hub",
                            "signed_in": False,
                            "account": None,
                            "needs": ["chrome"],
                        }
                    ]
                }
            ),
        )

    try:
        await page.route("**/api/auth/status", status_route)
        await _open_step(page, base_url, "signin")
        await page.wait_for_selector("#fp-setup-chrome-notice:not([hidden])", timeout=15000)
        assert await page.locator("#fp-setup-chrome-notice").inner_text() == CHROME_REQUIRED
        assert await page.get_by_role("button", name="Sign in with Google").is_disabled()
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_signin_step_maps_a_400_to_the_honesty_sentence_not_raw_text(page, base_url):
    """T0 addendum B5: the route's only 400 is ChromeNotFoundError, but this
    never trusts the thrown message's text — it renders the live notice."""

    async def start_route(route):
        # Deliberately NOT honesty.CHROME_REQUIRED's text, to prove the UI
        # does not just echo whatever the 400 body happens to say.
        await route.fulfill(
            status=400,
            content_type="application/json",
            body=json.dumps({"detail": "ChromeNotFoundError: no chrome binary on PATH"}),
        )

    try:
        await _open_step(page, base_url, "signin")
        await page.route("**/api/auth/google/start", start_route)
        await page.get_by_role("button", name="Sign in with Google").click()
        await page.wait_for_selector("#fp-setup-chrome-notice:not([hidden])", timeout=15000)
        notice = await page.locator("#fp-setup-chrome-notice").inner_text()
        assert notice == CHROME_REQUIRED
        assert "ChromeNotFoundError" not in notice
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_notifications_step_telegram_help_lines(page, base_url):
    """T0 addendum B6: where the token comes from, and how Find+ finds the
    chat id — the same two things `findplus alerts telegram-setup` explains."""
    try:
        await _open_step(page, base_url, "notifications")
        await page.wait_for_selector("[data-channel='telegram']", timeout=15000)
        section_text = await page.locator("[data-channel='telegram']").inner_text()
        assert "BotFather" in section_text
        assert "chat id" in section_text
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


#: The four steps R-P2-28 changed the layout/markup of.
WIZARD_AXE_STEPS = ("welcome", "groups", "notifications", "applock")


@pytest.mark.parametrize("theme", ("dark", "light"))
@pytest.mark.parametrize("step", WIZARD_AXE_STEPS)
async def test_no_serious_axe_violations_on_touched_wizard_steps(page, base_url, step, theme):
    """R-P2-28 build brief: keep the axe matrix at 0 serious including the
    wizard steps this ticket touched (the full wizard axe matrix, every step,
    is R-P2-26's E13-T1 — this covers only what changed here)."""
    try:
        await _open_step(page, base_url, step)
        await set_theme(page, theme)

        results = await Axe().run(page, options=AXE_OPTIONS)
        violations = results.response["violations"]
        for violation in violations:
            if violation.get("impact") not in BLOCKING:
                print(f"axe {_describe(violation, step, theme, 1280)}")
        blocking = [v for v in violations if v.get("impact") in BLOCKING]
        assert not blocking, "\n".join(_describe(v, step, theme, 1280) for v in blocking)
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)
