"""Browser tests for web/app/components/confirm-dialog.js (UAT6-N21, WP-H).

Purpose    : Prove the shared confirm/alert dialog's contract before trusting
             every call site that now imports it: Confirm resolves true,
             Cancel and Escape both resolve false, focus returns to whatever
             opened it, `danger` starts focus on Cancel, an `input.
             requireText` gates Confirm until it matches, and alertDialog()
             renders with no Cancel button at all.
Inputs     : cli/tests/ui/conftest.py's `page` / `base_url` fixtures. The
             component is exercised directly (dynamic import), not through
             any one call site, the same way test_channel_picker.py and
             test_icon_color_pickers.py test their own components.
Constraints: confirmDialog()'s promise only resolves once this test (or a
             human) closes the dialog, so it is kicked off without an
             `await` inside page.evaluate() -- window.__confirmResult holds
             `{done, value}` once it lands, polled with wait_for_function.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

DIALOG_OPEN = "#fp-confirm-dialog[open]"
DONE = "() => window.__confirmResult && window.__confirmResult.done"


async def _open(page, base_url) -> None:
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map.leaflet-container")


async def _start_confirm(page, opts: dict) -> None:
    """Fire confirmDialog(opts) and wait for the dialog to actually open."""
    await page.evaluate(
        """async (opts) => {
            const mod = await import('/static/app/components/confirm-dialog.js');
            window.__confirmResult = { done: false, value: undefined };
            mod.confirmDialog(opts).then((value) => {
                window.__confirmResult = { done: true, value };
            });
        }""",
        opts,
    )
    await page.wait_for_selector(DIALOG_OPEN)


async def _resolved_value(page):
    await page.wait_for_function(DONE)
    result = await page.evaluate("() => window.__confirmResult")
    return result["value"]


async def test_clicking_confirm_resolves_true(page, base_url):
    await _open(page, base_url)
    await _start_confirm(page, {"title": "Delete?", "body": "Sure?"})
    await page.locator("#fp-confirm-dialog").get_by_role("button", name="Confirm").click()
    assert await _resolved_value(page) is True


async def test_clicking_cancel_resolves_false(page, base_url):
    await _open(page, base_url)
    await _start_confirm(page, {"title": "Delete?", "body": "Sure?"})
    await page.locator("#fp-confirm-dialog").get_by_role("button", name="Cancel").click()
    assert await _resolved_value(page) is False


async def test_escape_resolves_false(page, base_url):
    await _open(page, base_url)
    await _start_confirm(page, {"title": "Delete?", "body": "Sure?"})
    await page.keyboard.press("Escape")
    assert await _resolved_value(page) is False


async def test_focus_returns_to_the_opener(page, base_url):
    await _open(page, base_url)
    await page.evaluate("() => document.getElementById('btn-devices').focus()")
    await _start_confirm(page, {"title": "Delete?", "body": "Sure?"})
    await page.locator("#fp-confirm-dialog").get_by_role("button", name="Cancel").click()
    await _resolved_value(page)
    assert await page.evaluate("() => document.activeElement.id") == "btn-devices"


async def test_danger_starts_focus_on_cancel(page, base_url):
    await _open(page, base_url)
    await _start_confirm(page, {"title": "Delete?", "body": "Sure?", "danger": True})
    assert await page.evaluate("() => document.activeElement.id") == "fp-confirm-dialog-cancel"
    await page.locator("#fp-confirm-dialog").get_by_role("button", name="Cancel").click()
    await _resolved_value(page)


async def test_a_non_danger_dialog_starts_focus_on_confirm(page, base_url):
    await _open(page, base_url)
    await _start_confirm(page, {"title": "Continue?", "body": "Sure?"})
    assert await page.evaluate("() => document.activeElement.id") == "fp-confirm-dialog-confirm"
    await page.locator("#fp-confirm-dialog").get_by_role("button", name="Cancel").click()
    await _resolved_value(page)


async def test_require_text_gates_confirm_and_focuses_the_field(page, base_url):
    await _open(page, base_url)
    await _start_confirm(
        page,
        {
            "title": "Confirm",
            "body": "",
            "confirmLabel": "Delete",
            "danger": True,
            "input": {"requireText": "DELETE", "label": "Type DELETE"},
        },
    )
    assert await page.evaluate("() => document.activeElement.id") == "fp-confirm-dialog-input"
    confirm_btn = page.locator("#fp-confirm-dialog-confirm")
    assert await confirm_btn.is_disabled()
    await page.fill("#fp-confirm-dialog-input", "nope")
    assert await confirm_btn.is_disabled()
    await page.fill("#fp-confirm-dialog-input", "DELETE")
    assert not await confirm_btn.is_disabled()
    await confirm_btn.click()
    assert await _resolved_value(page) is True


async def test_repeated_verb_title_is_promoted_from_the_body(page, base_url):
    """UAT7-N16: most call sites still send the same generic verb as both
    `title` and `confirmLabel` ("Delete" title, "Delete" button) with the
    real question in `body` -- the title read as the button's own label
    repeated above itself. When that pattern is detected, `body` becomes the
    title and the body paragraph collapses empty."""
    await _open(page, base_url)
    opts = {
        "title": "Delete",
        "body": 'Delete place "Home"?',
        "confirmLabel": "Delete",
        "danger": True,
    }
    await _start_confirm(page, opts)
    title = await page.locator("#fp-confirm-dialog-title").inner_text()
    body = await page.locator("#fp-confirm-dialog-body").inner_text()
    assert title == 'Delete place "Home"?'
    assert body == ""
    await page.locator("#fp-confirm-dialog").get_by_role("button", name="Delete").click()
    assert await _resolved_value(page) is True


async def test_a_distinct_title_is_left_alone(page, base_url):
    """A caller that already sends its own title (an error dialog's "Error",
    distinct from its "OK" confirmLabel) keeps it -- nothing to promote."""
    await _open(page, base_url)
    await _start_confirm(page, {"title": "Error", "body": "Something broke", "confirmLabel": "OK"})
    title = await page.locator("#fp-confirm-dialog-title").inner_text()
    body = await page.locator("#fp-confirm-dialog-body").inner_text()
    assert title == "Error"
    assert body == "Something broke"
    await page.locator("#fp-confirm-dialog").get_by_role("button", name="OK").click()
    await _resolved_value(page)


async def test_cancel_button_uses_the_shared_secondary_style(page, base_url):
    """UAT7-N16: Cancel never got a class at all, so it painted as a bare
    browser-default button -- square-bordered and inconsistent between
    themes, unlike every other dialog's Cancel."""
    await _open(page, base_url)
    await _start_confirm(page, {"title": "Delete?", "body": "Sure?"})
    class_name = await page.locator("#fp-confirm-dialog-cancel").get_attribute("class")
    assert class_name == "btn btn-secondary"
    await page.locator("#fp-confirm-dialog").get_by_role("button", name="Cancel").click()
    await _resolved_value(page)


async def test_alert_dialog_has_no_cancel_button(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map.leaflet-container")
    await page.evaluate(
        """async () => {
            const mod = await import('/static/app/components/confirm-dialog.js');
            mod.alertDialog({ title: 'Error', body: 'Something broke' });
        }"""
    )
    await page.wait_for_selector(DIALOG_OPEN)
    assert await page.locator("#fp-confirm-dialog-cancel").is_hidden()
    await page.locator("#fp-confirm-dialog-confirm").click()
