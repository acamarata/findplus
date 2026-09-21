"""Playwright browser tests for the group dialog on lock.

Purpose    : Split out of test_groups_dialog.py at the PRI 300-line file cap
             (added alongside its W3-gate async-guard/icon-preview cases).
             Purge-on-lock is a distinct concern from the dialog's own
             CRUD/validation behaviour, which still owns the shared fixtures
             (conftest.py) and the `_open_edit_dialog_for` helper these two
             tests reuse rather than duplicate.
"""

from __future__ import annotations

import contextlib

import pytest

from .test_groups_dialog import _open_edit_dialog_for
from .test_lock import PIN
from .test_lock_purge import _setup_purge_fixture, _teardown_purge_fixture

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _group_dialog_state(page) -> dict:
    """The dialog's live field values, which page.content() never serialises."""
    return await page.evaluate(
        """() => {
            const dlg = document.getElementById('fp-group-dialog');
            if (!dlg) return null;
            return {
                open: dlg.open,
                editId: dlg.dataset.editId || '',
                name: document.getElementById('fp-group-name').value,
                texts: [...dlg.querySelectorAll('input[type=text]')].map((i) => i.value).join('|'),
                members: dlg.querySelectorAll('#fp-group-members input').length,
            };
        }"""
    )


async def test_purge_on_lock_clears_dialog_and_cards(page, base_url):
    """A closed dialog still holds the group name and every member's name."""
    await _setup_purge_fixture(page, base_url)
    try:
        await _open_edit_dialog_for(page, base_url, "Family")
        before = await _group_dialog_state(page)
        assert before["name"] == "Family", before
        assert before["members"] >= 3, before
        assert await page.locator(".fp-group-card").count() >= 1

        # The dialog is deliberately left open, and a modal <dialog> swallows
        # pointer events aimed at anything behind it, so the click is
        # dispatched rather than performed. It still runs lock.js's own
        # handler, which is what this test is about.
        await page.locator("#btn-lock").dispatch_event("click")
        await page.wait_for_selector("#lock-screen:not(.hidden)")

        after = await _group_dialog_state(page)
        assert after["open"] is False, after
        assert after["name"] == "", after
        assert after["texts"] == "", after
        assert after["editId"] == "", after
        assert after["members"] == 0, after
        assert await page.locator("#fp-groups-list .fp-group-card").count() == 0
        assert "Family" not in await page.content()
    finally:
        with contextlib.suppress(Exception):
            await page.fill("#lock-pin", PIN)
            await page.click("#lock-submit")
        await _teardown_purge_fixture(page, base_url)


async def test_purge_on_a_locked_boot_does_not_throw(
    page, base_url, reset_alert_and_observation_state
):
    """clearGroup() runs before groups.js has a map, so overlayLayer is null.

    T0's wave-2 visual gate caught `Cannot read properties of null (reading
    'clearLayers')` on the lock path — the one path that must never throw,
    because everything after it in purgeRenderedData() stops running.
    """
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on(
        "console",
        lambda msg: errors.append(msg.text) if msg.type == "error" else None,
    )
    await _setup_purge_fixture(page, base_url)
    try:
        await page.request.post(base_url + "/api/lock/lock")
        await page.goto(base_url + "/")
        await page.wait_for_selector("#lock-screen:not(.hidden)")
        assert not [e for e in errors if "clearLayers" in e or "of null" in e], errors
        await page.fill("#lock-pin", PIN)
        await page.click("#lock-submit")
        # A locked cold boot means hideLockAndRestore() is running
        # bootDashboard() for the first time this session (config, settings,
        # devices, status and day all sequentially awaited against the real
        # live_server), on top of the extra alert rule _setup_purge_fixture
        # just created. This used to also render every alert rule/delivery
        # every earlier file in the session-scoped suite had created and
        # never cleaned up (test_alerts_rules.py, test_alerts_deliveries.py,
        # test_alerts_whatsapp.py), which doubled the boot's wall time on
        # CI's slower/shared runner and needed a 60s wait even though
        # nothing was actually stuck. reset_alert_and_observation_state
        # (requested above) clears that accumulated state before this test
        # runs, so the default wait_for timeout is enough again (E13 loop3
        # L3-3).
        await page.locator("#app-shell:not(.hidden)").wait_for(state="visible")
    finally:
        await _teardown_purge_fixture(page, base_url)
