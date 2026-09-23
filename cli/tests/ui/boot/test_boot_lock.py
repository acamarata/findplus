"""End-to-end browser tests of the lock screen (locked state only).

These drive a real Chrome. They are skipped automatically when Playwright or
Chrome is unavailable, so the suite still runs on a bare machine.

Split out of test_ui_browser.py (E13 loop2 L2-14, size cap): this file keeps
only the pre-unlock assertions; test_boot_dashboard.py and
test_boot_controls.py cover what happens after `_unlock()`. The `browser`,
`server` and `page` fixtures come from this directory's `conftest.py`.
"""

from __future__ import annotations

from playwright.sync_api import Page


# --------------------------------------------------------------- locked state
def test_app_opens_on_the_lock_screen(page: Page) -> None:
    assert page.is_visible("#lock-screen")
    assert not page.is_visible("#app-shell")


def test_no_location_data_is_in_the_dom_while_locked(page: Page) -> None:
    """A CSS overlay would still leave coordinates in the page source."""
    html = page.content()
    assert "41.09" not in html
    assert "41.10" not in html


def test_wrong_pin_stays_locked_and_reports_it(page: Page) -> None:
    page.fill("#lock-pin", "000000")
    page.click("#lock-submit")
    page.wait_for_timeout(1200)
    assert page.is_visible("#lock-screen")
    # UAT U20: the generic 401 handler used to swallow the real reason and
    # show the bare word "Locked"; a wrong PIN now names itself and points at
    # the recovery command, not just "something failed".
    error_text = page.inner_text("#lock-error").strip()
    assert error_text != "Locked"
    assert "Wrong PIN" in error_text
    assert "findplus lock reset" in error_text
