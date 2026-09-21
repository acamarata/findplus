"""End-to-end browser tests of dashboard controls reached after unlocking.

These drive a real Chrome. They are skipped automatically when Playwright or
Chrome is unavailable, so the suite still runs on a bare machine.

Split out of test_ui_browser.py (E13 loop2 L2-14, size cap): this file keeps
Settings, Devices, theme, manual relock and day-selection persistence;
test_boot_lock.py covers the lock screen, test_boot_dashboard.py covers the
render-after-unlock and boot-health regressions. The `browser`, `server` and
`page` fixtures come from this directory's `conftest.py`.
"""

from __future__ import annotations

from playwright.sync_api import Page

from .conftest import _unlock

# ------------------------------------------------------------- unlocked state


def test_settings_dialog_works_after_unlocking(page: Page) -> None:
    """Regression: `state.config` was null, so opening Settings threw."""
    _unlock(page)
    page.click("#btn-settings")
    page.wait_for_timeout(1200)
    assert page.is_visible("#settings-modal")
    assert "polling every" in page.inner_text("#settings-about")


def test_devices_dialog_lists_trackers_with_checkboxes(page: Page) -> None:
    _unlock(page)
    page.click("#btn-devices")
    page.wait_for_timeout(1200)
    assert page.is_visible("#device-modal")
    assert page.locator("#device-list input[type=checkbox]").count() >= 1
    assert "Google requests per hour" in page.inner_text("#device-rate")


def test_theme_switches_live(page: Page) -> None:
    _unlock(page)
    page.click("#btn-settings")
    page.wait_for_timeout(1000)
    page.select_option("#setting-theme", "light")
    page.wait_for_timeout(900)
    assert page.get_attribute("html", "data-theme") == "light"
    page.select_option("#setting-theme", "dark")
    page.wait_for_timeout(900)
    assert page.get_attribute("html", "data-theme") == "dark"


def test_manual_lock_returns_to_the_lock_screen(page: Page) -> None:
    _unlock(page)
    page.click("#btn-lock")
    page.wait_for_selector("#lock-screen:visible", timeout=10000)
    assert not page.is_visible("#app-shell")
    assert "41.09" not in page.content()


def test_unlock_restores_the_previously_selected_day(page: Page) -> None:
    """Unlocking must return to the exact view, not reset to today."""
    _unlock(page)
    page.click("#btn-prev-day")
    page.wait_for_timeout(1200)
    previous_day = page.input_value("#day-picker")

    page.click("#btn-lock")
    page.wait_for_selector("#lock-screen:visible", timeout=10000)
    _unlock(page)

    assert page.input_value("#day-picker") == previous_day
