"""End-to-end browser tests of the dashboard right after unlocking.

These drive a real Chrome. They are skipped automatically when Playwright or
Chrome is unavailable, so the suite still runs on a bare machine.

Why these exist: the "app starts locked" path is only reachable through a
browser, and it silently broke once already -- `main()` returned early on
the lock screen, so `loadConfig()` never ran. Unlocking then left
`state.config` null (the Settings dialog threw), the mandatory Find Hub
notice blank, and the auto-refresh timer never created for the rest of the
session. Nothing in the Python suite could see any of that.

Split out of test_ui_browser.py (E13 loop2 L2-14, size cap): this file keeps
the render-after-unlock and boot-health regressions; test_boot_lock.py
covers the pre-unlock lock screen, test_boot_controls.py covers Settings /
Devices / theme / relock / day-restore. The `browser`, `server` and `page`
fixtures come from this directory's `conftest.py`.
"""

from __future__ import annotations

import json

from playwright.sync_api import Page

from .conftest import PIN, _unlock

# ------------------------------------------------------------- unlocked state


def test_correct_pin_unlocks_and_renders_history(page: Page) -> None:
    _unlock(page)
    assert not page.is_visible("#lock-screen")
    assert page.locator(".tl-item").count() == 3
    assert page.locator(".marker-num").count() >= 3


def test_findhub_notice_is_present_after_unlocking(page: Page) -> None:
    """Regression: starting locked used to leave this mandatory notice blank."""
    _unlock(page)
    notice = page.inner_text("#findhub-notice")
    assert "should not be treated as real-time emergency" in notice


def test_dialogs_are_closed_on_a_normal_load(page: Page) -> None:
    """Regression: `.modal` beat `.hidden`, so Devices rendered open on load."""
    _unlock(page)
    assert not page.is_visible("#device-modal")
    assert not page.is_visible("#settings-modal")


def test_no_javascript_errors_and_no_broken_requests(page: Page, server: str) -> None:
    """Catches missing assets and uncaught exceptions across the whole flow."""
    errors: list[str] = []
    failures: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on(
        "response",
        lambda r: (
            failures.append(f"{r.status} {r.url}")
            # 401s are expected while locked; everything else is a defect.
            if r.status >= 400 and r.status != 401
            else None
        ),
    )

    page.reload(wait_until="networkidle")
    _unlock(page)
    page.click("#btn-settings")
    page.wait_for_timeout(900)
    page.click("#btn-close-settings")
    page.click("#btn-devices")
    page.wait_for_timeout(900)

    assert not errors, f"JavaScript errors: {errors}"
    assert not failures, f"broken requests: {failures}"


def test_dashboard_boots_past_alerts_init_with_no_error_banner(page: Page, server: str) -> None:
    """`main()` catches every rejection from its own await chain and turns it
    into the `#alert` banner, so a broken reference inside one tab's init()
    never shows as a `pageerror` -- it quietly aborts `bootDashboard()` and
    leaves `#tracks` empty. That's what happened when alerts.js called an
    un-exported local directly (loop1, findplus#238): `ReferenceError`,
    caught, banner shown, and the axe suite's `#tracks > *` wait was the only
    thing in CI that noticed, after a 30s timeout.

    Getting there through `_unlock()` sees neither symptom (confirmed by
    reintroducing the exact regression in a worktree): `main()` calls
    alerts.js's init() before it ever checks lock state, but while locked any
    concurrent 401 (notices.js's `/api/config` always 401s) fires `showLock()`
    -> `purgeRenderedData()`, which unconditionally clears `#alert` --
    regression or not. Unlocking afterwards doesn't help either: `lock.js`'s
    own handler calls `bootDashboard()` again on its own, independently of
    `main()`'s chain, so `#tracks` fills in either way. Authenticating via
    `POST /api/lock/unlock` before the page ever loads -- the session state a
    never-locked install boots into, which is what let the axe suite see the
    original failure -- avoids that purge and lets the banner show.

    This fixture's `_SEED_SCRIPT` never sets `onboarding.completed_at`, so the
    real `main()` chain (unlike `_unlock()`, which skips `checkOnboarding()`)
    detours into the first-run wizard, hiding `#app-shell` and `#tracks` for
    a reason that has nothing to do with alerts.js. Marking onboarding
    complete first (as `cli/tests/ui/conftest.py` does at the DB layer)
    avoids that detour.

    `server` runs with `--no-poller`, so `renderStatusAlert()` would
    legitimately show `common.serviceNotRunning` -- but only inside
    `bootDashboard()`, downstream of the check below. Only the boot chain's
    own `.catch()` banner (`common.apiUnreachable`) means what this test is
    for, checked by its fixed prefix, read from the live catalog rather than
    retyped (test_auth_panel.py's rule).
    """
    unlocked = page.request.post(
        server + "/api/lock/unlock",
        data=json.dumps({"pin": PIN}),
        headers={"Content-Type": "application/json"},
    )
    assert unlocked.ok, unlocked.text()
    onboarded = page.request.post(
        server + "/api/settings/onboarding.completed_at",
        data=json.dumps({"value": "2026-01-01T00:00:00Z"}),
        headers={"Content-Type": "application/json"},
    )
    assert onboarded.ok, onboarded.text()
    page.goto(server, wait_until="networkidle")
    page.wait_for_timeout(600)

    catalog = page.request.get(server + "/static/locales/en.json").json()
    api_unreachable_prefix = catalog["common"]["apiUnreachable"].split("{message}")[0]
    alert_text = page.text_content("#alert") or ""
    assert api_unreachable_prefix not in alert_text, f"boot-time error banner shown: {alert_text!r}"
    assert page.query_selector("#tracks > *") is not None, "#tracks never rendered a child"
