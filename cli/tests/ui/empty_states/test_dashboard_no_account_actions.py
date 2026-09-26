"""Browser tests for UAT7-N14: no duplicate "Connect an account" CTA, and
Poll Now / Latest Location disabled with a reason, while nothing is tracked.

Fixture (this directory's conftest.py): a freshly migrated, onboarded
database with zero devices and no provider signed in, so the dashboard's
banner and both topbar buttons render for exactly the "nothing tracked, no
account connected" state this ticket is about.
"""

from __future__ import annotations

from playwright.sync_api import Page


def test_no_account_banner_has_no_duplicate_connect_button(page: Page) -> None:
    """The banner used to repeat the timeline empty state's own "Connect an
    account" button (test_empty_states.py's own
    test_dashboard_empty_state_has_one_message_and_working_buttons covers
    that one); it now just says nothing is connected, with no button of its
    own."""
    banner = page.locator("#alert")
    banner.wait_for(state="visible", timeout=10000)
    assert banner.inner_text().strip() == "No account is connected yet."
    assert page.locator("#alert .alert-action").count() == 0


def test_poll_and_latest_buttons_are_disabled_with_a_reason(page: Page) -> None:
    """Both buttons always failed with nothing tracked to poll; disabled now,
    with the same "nothing is tracked" wording common.pollerIdle already
    uses for the service dot -- no new copy invented for this reason."""
    page.locator("#alert").wait_for(state="visible", timeout=10000)
    poll = page.locator("#btn-poll")
    latest = page.locator("#btn-latest")
    assert poll.is_disabled()
    assert latest.is_disabled()
    assert (poll.get_attribute("title") or "") == "Nothing is tracked yet, so nothing is polled."
    assert (latest.get_attribute("title") or "") == "Nothing is tracked yet, so nothing is polled."
