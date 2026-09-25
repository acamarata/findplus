"""Playwright browser test for the Alerts tab's add-rule dialog's Edit flow
(UAT U13). Split out of test_alerts_rules.py at the PRI rule-7 300-line file
cap when this test grew CI-failure diagnostics (CI 36194968013,
FLAKE-EDITRULE) -- the same reason test_alerts_rule_channels.py split off
the dialog's channel-picker behaviour earlier.

`open_alerts_tab()` and `capture_alerts_network_and_console()` are shared
across every test_alerts_*.py file via `_alerts_helpers.py`.
"""

from __future__ import annotations

import json

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from ._alerts_helpers import capture_alerts_network_and_console, open_alerts_tab

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _save_rule_and_wait_for_close(page, network_events, console_events) -> None:
    """Click Save and wait for the dialog to close, gathering the dialog's own
    error text plus the request/console log on a timeout (CI 36194968013) so
    a future failure explains itself instead of a bare TimeoutError. Split
    out of the test below to keep it under the PRI rule-7 50-line cap."""
    await page.click("#fp-rule-save")
    try:
        await page.wait_for_function("() => !document.getElementById('fp-add-rule-dialog').open")
    except PlaywrightTimeoutError:
        error_text = await page.locator("#fp-rule-error").text_content()
        pytest.fail(
            "rule dialog never closed after Save; "
            f"dialog error={error_text!r} network={network_events!r} console={console_events!r}"
        )


async def test_edit_rule_prefills_and_updates_the_row(page, base_url):
    """UAT U13: Edit opens the same dialog pre-filled and PUTs, never re-POSTs
    a duplicate row; the target radios are locked since the API cannot
    retarget a rule (routes_alerts_rules.py's RuleUpdate).

    CI 36194968013 (FLAKE-EDITRULE): timed out at the wait_for_function below,
    dialog never closed, no evidence why. Root cause was product, not test:
    the first channel-picker render is keyed off BASE_CHANNELS (no "native"),
    so this rule's own "native" channel had no checkbox until the dialog's
    async load landed; Save clicked before that sent an empty channels list,
    the server 422s it, and the dialog stayed open on an error nothing read.
    alerts_rule_dialog.js now disables Save until that load lands
    (data-fp-ready="true"); network/console capture plus the dialog's own
    error text below cover any other cause a future failure hits here.
    """
    console_events, network_events = capture_alerts_network_and_console(page)
    create_resp = await page.request.post(
        base_url + "/api/alerts/rules",
        data=json.dumps(
            # "native" needs no configured credentials (UAT2 U11's
            # server-side check); this test only checks Edit prefills/PUTs.
            {"name": "U13 edit rule", "device_id": "TAG-HOME", "channels": ["native"]}
        ),
        headers={"Content-Type": "application/json"},
    )
    assert create_resp.ok, await create_resp.text()
    rule_id = (await create_resp.json())["id"]

    await open_alerts_tab(page, base_url)
    row = page.locator("#fp-rules-tbody tr", has_text="U13 edit rule")
    await row.wait_for(state="visible")
    await row.get_by_text("Edit", exact=True).click()
    await page.wait_for_selector("#fp-add-rule-dialog[open]")
    assert await page.input_value("#fp-rule-name") == "U13 edit rule"
    assert await page.is_disabled("#fp-rule-target-device") is True
    # data-fp-ready="true" is set once the picker's real render (rule.channels
    # against the true available/connected state) lands; Save is also
    # disabled until then, but waiting for the marker keeps this test's
    # timing intent explicit rather than implicit in a button attribute.
    await page.wait_for_selector('#fp-add-rule-dialog[data-fp-ready="true"]')

    await page.fill("#fp-rule-name", "U13 edit rule (renamed)")
    await _save_rule_and_wait_for_close(page, network_events, console_events)

    rules = await (await page.request.get(base_url + "/api/alerts/rules")).json()
    matching = [r for r in rules if r["id"] == rule_id]
    assert len(matching) == 1, "editing must PUT the existing row, never create a second one"
    assert matching[0]["name"] == "U13 edit rule (renamed)"
