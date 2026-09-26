"""Browser tests for the dashboard/Groups/Places empty states (gap audit
U12, U13, U14).

Fixture (this directory's conftest.py): a freshly migrated, onboarded
database with zero devices, zero groups and zero places, so all three tabs
render their empty state on the very first load -- no setup/teardown needed
for the "still empty" tests. `test_groups_tab_hint_appears_once_a_group_exists`
adds and then removes its own group through the API, so it stays safe to run
in any order and to repeat.
"""

from __future__ import annotations

import json

from playwright.sync_api import Page


def _empty_state_buttons(page: Page):
    page.wait_for_selector("#tracks .empty-actions[data-ready]", timeout=10000)
    buttons = page.locator("#tracks .empty-actions button")
    assert buttons.count() == 2
    return buttons


def test_dashboard_empty_state_has_one_message_and_working_buttons(page: Page) -> None:
    """U13: the old copy was "Devices to choose one" (no verb) with the two
    actions named as plain text. UAT6-N32: with no account signed in (this
    fixture never signs in) the primary action is "Connect an account", and
    it opens Settings on its Sign-in section."""
    tracks = page.locator("#tracks")
    assert tracks.locator("p", has_text="No devices tracked yet.").count() == 1

    buttons = _empty_state_buttons(page)
    labels = [buttons.nth(i).inner_text() for i in range(2)]
    assert labels == ["Connect an account", "Run setup again"]
    assert "btn-secondary" not in (buttons.nth(0).get_attribute("class") or "")

    buttons.nth(0).click()
    page.wait_for_selector("#settings-modal:not(.hidden)", timeout=10000)


def test_dashboard_empty_state_offers_devices_once_signed_in(page: Page) -> None:
    """UAT6-N32: signed in with nothing tracked, the primary action is Devices."""
    page.route(
        "**/api/auth/status",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"providers": [{"id": "google-find-hub", "signed_in": True}]}),
        ),
    )
    page.reload()
    buttons = _empty_state_buttons(page)
    assert buttons.nth(0).inner_text() == "Choose devices"
    buttons.nth(0).click()
    page.wait_for_selector("#device-modal:not(.hidden)", timeout=10000)


def test_dashboard_empty_state_run_setup_button_navigates(page: Page) -> None:
    """#setup-view keeps CSS grid layout even while its `hidden` attribute is
    set (web/setup.css's `#setup-view` rule has no `[hidden]` exception, an
    existing quirk outside this ticket's scope), so Playwright's `:visible`
    pseudo-class is true for it even before the wizard mounts. Wait on the
    real signal instead: `#app-shell` gaining the "hidden" class, and the
    wizard actually rendering a step into `#setup-view`."""
    page.locator("#tracks button", has_text="Run setup again").click()
    page.wait_for_function(
        "() => document.getElementById('app-shell').classList.contains('hidden')",
        timeout=10000,
    )
    page.wait_for_selector("#setup-view > *", timeout=10000)


def test_groups_empty_state_has_one_message_pointing_at_add_group(page: Page) -> None:
    """U12: up to three overlapping messages used to show at once. With zero
    groups there must be exactly one, and it has to mention the Add group
    button that sits right there."""
    page.click("#fp-tab-groups")
    page.wait_for_selector("#tab-groups:not([hidden])")
    page.wait_for_selector(".fp-empty-state", timeout=10000)

    assert page.locator("#fp-groups-list .fp-empty-state").count() == 1
    empty_text = page.inner_text("#fp-groups-list .fp-empty-state")
    assert "Add group" in empty_text

    # The "use the selector" hint only helps once something is selectable;
    # with zero groups it must stay hidden so it cannot overlap the message
    # above.
    assert not page.is_visible("#fp-groups-tab-hint")


def test_groups_tab_hint_appears_once_a_group_exists(page: Page, server: str) -> None:
    created = page.request.post(
        server + "/api/groups",
        data=json.dumps({"name": "Household", "member_ids": []}),
        headers={"Content-Type": "application/json"},
    )
    assert created.ok, created.text()
    group_id = created.json()["id"]
    try:
        # groups.js only fetches /api/groups on boot; a group added straight
        # through the API (bypassing the Add group dialog's own reload) needs
        # a fresh load before the selector and card grid know about it.
        page.reload(wait_until="networkidle")
        page.wait_for_selector("#app-shell:visible", timeout=20000)
        page.click("#fp-tab-groups")
        page.wait_for_selector(".fp-group-card", timeout=10000)
        assert page.is_visible("#fp-groups-tab-hint")
        assert page.locator("#fp-groups-list .fp-empty-state").count() == 0
    finally:
        page.request.delete(f"{server}/api/groups/{group_id}")


def test_places_empty_state_has_one_message(page: Page) -> None:
    """U14: places.tabHint and places.list.empty used to show together.
    Only the tab hint remains; the list adds nothing when it is empty."""
    page.click("#fp-tab-places")
    page.wait_for_selector("#tab-places:not([hidden])")

    hint = page.locator("#tab-places .fp-tab-hint")
    assert hint.count() == 1
    assert hint.is_visible()
    assert page.locator("#fp-places-list .fp-empty-state").count() == 0
    assert page.locator("#fp-places-list").inner_text().strip() == ""
