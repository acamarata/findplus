"""Browser tests for the WhatsApp card, rule channels and delivery log (E10 T2-T4).

Everything here runs end to end against the real live_server, the way
test_alerts.py already does. The two honesty assertions import
findplus.honesty rather than retyping a sentence: a hand-typed copy drifts
silently from the real text and the test keeps passing (test_honesty_text.py's
rule). CallMeBot itself is never contacted — nothing in this file sends a test
message, and the autouse socket guard in cli/tests/conftest.py would block it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from findplus.honesty import ALERTS_LOCKED, WHATSAPP_RELAY, WHATSAPP_SETUP

pytestmark = pytest.mark.asyncio(loop_scope="session")

# E11's first-run check redirects a hash-less "/" to #/setup and hides
# #app-shell whenever onboarding.completed_at is null, which it always is in
# this suite's seeded state dir. A non-empty, inert hash (applyHashRoute only
# acts on #settings/#devices/#/setup) keeps the dashboard on screen; it stays
# correct once that precondition is seeded for the whole suite.
DASHBOARD = "/#dashboard"

FAKE_APIKEY = "fake-apikey-123"
FAKE_PHONE = "+34123123123"


@pytest.fixture
def configured_whatsapp(ui_env: dict):
    """Seed a configured WhatsApp channel by writing alerts.json directly.

    Mirrors test_alerts.py's configured_telegram: never through
    PUT /api/alerts/channels/whatsapp, and always restored, pass or fail.
    Yields the path so a test can read back what the browser actually stored.
    """
    path = Path(ui_env["FINDPLUS_STATE_DIR"]) / "alerts.json"
    path.write_text(
        json.dumps({"channels": {"whatsapp": {"phone": FAKE_PHONE, "apikey": FAKE_APIKEY}}})
    )
    try:
        yield path
    finally:
        path.write_text(json.dumps({"channels": {}}))


async def _open_alerts_tab(page, base_url) -> None:
    await page.goto(base_url + DASHBOARD)
    await page.click('button[data-tab="alerts"]')
    await page.wait_for_selector("#fp-whatsapp-section")


async def _open_add_rule_dialog(page, base_url) -> None:
    await _open_alerts_tab(page, base_url)
    await page.click("#fp-add-rule-btn")
    await page.wait_for_selector("#fp-add-rule-dialog[open]")
    # The dialog opens before its data lands (CF-P2-18), so wait for the
    # channel picker to mount rather than for the dialog element alone.
    await page.wait_for_selector("#fp-rule-channels input[type=checkbox]")


async def test_whatsapp_relay_honesty_text_present(page, base_url) -> None:
    await _open_alerts_tab(page, base_url)
    await page.wait_for_function(
        "() => document.getElementById('fp-wa-relay-notice').textContent.length > 0"
    )
    assert WHATSAPP_RELAY in await page.locator("#fp-wa-relay-notice").inner_text()


async def test_whatsapp_setup_instructions_present(page, base_url) -> None:
    await _open_alerts_tab(page, base_url)
    await page.wait_for_function(
        "() => document.getElementById('fp-wa-instructions').textContent.length > 0"
    )
    assert WHATSAPP_SETUP in await page.locator("#fp-wa-instructions").inner_text()


async def test_whatsapp_apikey_masked_and_clears_on_focus(
    page, base_url, configured_whatsapp
) -> None:
    await _open_alerts_tab(page, base_url)
    apikey = page.locator("#fp-wa-apikey")
    await page.wait_for_function("() => document.getElementById('fp-wa-apikey').value.length > 0")

    masked = await apikey.input_value()
    assert "•" in masked
    assert FAKE_APIKEY not in masked

    await apikey.focus()
    assert await apikey.input_value() == ""


async def test_whatsapp_phone_is_only_ever_shown_masked(
    page, base_url, configured_whatsapp
) -> None:
    """The masked number belongs in the connected line, never in the input.

    CR-C-E10 F2: prefilling `+34…23` into an editable phone field offered the
    user a value the PUT's E.164 check rejects, so Save answered a 422 to
    someone who had changed nothing about their number.
    """
    await _open_alerts_tab(page, base_url)
    await page.wait_for_function(
        "() => document.getElementById('fp-wa-connected').textContent.length > 0"
    )

    connected = await page.locator("#fp-wa-connected").inner_text()
    assert "…" in connected
    assert FAKE_PHONE not in connected
    assert await page.locator("#fp-wa-phone").input_value() == ""


async def test_saving_a_changed_phone_never_overwrites_the_stored_key(
    page, base_url, configured_whatsapp
) -> None:
    """CR-C-E10 F1: the bullets are a placeholder, not the API key.

    Editing only the number and pressing Save used to PUT the literal
    `••••••••` as the apikey — a working channel destroyed silently, with the
    card still reporting itself connected.
    """
    await _open_alerts_tab(page, base_url)
    await page.wait_for_function("() => document.getElementById('fp-wa-apikey').value.length > 0")

    await page.fill("#fp-wa-phone", "+34999888777")
    await page.click("#fp-wa-save")

    await page.wait_for_function("() => document.getElementById('fp-wa-apikey').value === ''")
    stored = json.loads(configured_whatsapp.read_text())["channels"]["whatsapp"]
    assert stored["apikey"] == FAKE_APIKEY
    assert stored["phone"] == FAKE_PHONE


async def test_saving_both_fields_stores_them(page, base_url, configured_whatsapp) -> None:
    """The guard above never blocks a real change: both fields filled, it saves.

    The apikey is alphanumeric-only: `store.is_valid_apikey` (318d2ae) rejects
    a hyphen, so a punctuated value here would 422 instead of exercising the
    save path this test is for.
    """
    await _open_alerts_tab(page, base_url)
    await page.wait_for_function("() => document.getElementById('fp-wa-apikey').value.length > 0")

    await page.fill("#fp-wa-phone", "+34999888777")
    await page.fill("#fp-wa-apikey", "secondapikey456")
    await page.click("#fp-wa-save")

    await page.wait_for_function(
        "() => document.getElementById('fp-wa-connected').textContent.includes('77')"
    )
    stored = json.loads(configured_whatsapp.read_text())["channels"]["whatsapp"]
    assert stored == {"phone": "+34999888777", "apikey": "secondapikey456"}


async def test_saving_an_invalid_apikey_shows_an_inline_error(
    page, base_url, configured_whatsapp
) -> None:
    """A shape `store.is_valid_apikey` rejects (318d2ae) must not fail silently.

    alerts_channels.js's saveWhatsapp() catch puts the server's 422 detail
    into #fp-wa-status, and the credential on disk must be left exactly as it
    was -- the guard runs before any write (routes_alerts_channels.py's
    put_whatsapp()).
    """
    await _open_alerts_tab(page, base_url)
    await page.wait_for_function("() => document.getElementById('fp-wa-apikey').value.length > 0")

    await page.fill("#fp-wa-phone", "+34999888777")
    await page.fill("#fp-wa-apikey", "second-apikey-456")  # hyphens: not [0-9A-Za-z]
    await page.click("#fp-wa-save")

    await page.wait_for_function(
        "() => document.getElementById('fp-wa-status').textContent.length > 0"
    )
    status = await page.locator("#fp-wa-status").inner_text()
    assert "apikey" in status.lower(), status

    stored = json.loads(configured_whatsapp.read_text())["channels"]["whatsapp"]
    assert stored == {"phone": FAKE_PHONE, "apikey": FAKE_APIKEY}


async def test_rule_dialog_channel_checkboxes_present(page, base_url) -> None:
    await _open_add_rule_dialog(page, base_url)
    picker = page.locator("#fp-rule-channels")

    for channel in ("telegram", "webhook", "whatsapp"):
        box = picker.locator(f"input[type=checkbox][value={channel}]")
        assert await box.count() == 1, channel
        assert await box.is_visible(), channel

    assert await picker.locator("input[type=checkbox][value=telegram]").is_checked()


async def test_the_alerts_locked_sentence_sits_beside_the_channel_choice(page, base_url) -> None:
    """Server-sourced through notices.js, never typed into the markup."""
    await _open_alerts_tab(page, base_url)
    await page.wait_for_function(
        "() => document.getElementById('fp-alerts-locked-notice').textContent.length > 0"
    )
    assert ALERTS_LOCKED in await page.locator("#fp-alerts-locked-notice").inner_text()


async def test_the_add_rule_dialog_is_not_browser_default_chrome(page, base_url) -> None:
    """W3 visual gate finding 1: an unstyled <dialog> paints a white box."""
    await _open_add_rule_dialog(page, base_url)
    background = await page.evaluate(
        """() => getComputedStyle(document.getElementById('fp-add-rule-dialog')).backgroundColor"""
    )
    assert background not in ("rgb(255, 255, 255)", "rgba(0, 0, 0, 0)"), background


async def test_the_target_radio_and_its_select_share_a_row(page, base_url) -> None:
    """W3 visual gate finding 4: they used to be two stacked, misaligned rows."""
    await page.set_viewport_size({"width": 1280, "height": 900})
    await _open_add_rule_dialog(page, base_url)

    radio = await page.locator("#fp-rule-target-device").bounding_box()
    select = await page.locator("#fp-rule-device").bounding_box()
    assert radio and select
    assert abs(radio["y"] - select["y"]) < radio["height"] + select["height"]


async def test_deliveries_table_renders_after_rule_fires(page, base_url) -> None:
    created = await page.request.post(
        base_url + "/api/alerts/rules",
        data=json.dumps(
            {
                "name": "WhatsApp delivery view rule",
                "device_id": "TAG-HOME",
                "channels": ["webhook"],
            }
        ),
        headers={"Content-Type": "application/json"},
    )
    assert created.ok, await created.text()

    await _open_alerts_tab(page, base_url)
    await page.wait_for_selector("#fp-deliveries-table")
    assert await page.locator("#fp-deliveries-table").is_visible()

    headers = await page.locator("#fp-deliveries-table thead th").all_text_contents()
    assert headers[3:5] == ["Text", "Body"]


async def test_the_rule_dialog_populates_its_selects_on_a_cold_page(page, base_url) -> None:
    """CF-P2-18: the dialog read state.devices with nothing awaiting the load.

    Opening Add rule before the boot's device fetch landed left #fp-rule-device
    empty, so a rule could not name a tracker. The dialog still opens at once;
    the selects carry a Loading… placeholder until their data arrives.
    """
    await _open_add_rule_dialog(page, base_url)

    for select_id in ("fp-rule-device", "fp-rule-place", "fp-rule-group"):
        await page.wait_for_function(
            "(id) => {"
            "  const el = document.getElementById(id);"
            "  return el.options.length > 0 && el.options[0].value !== '';"
            "}",
            arg=select_id,
        )

    devices = await page.locator("#fp-rule-device option").all_text_contents()
    assert "Home Tag" in devices, devices
