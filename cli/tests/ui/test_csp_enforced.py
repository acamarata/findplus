"""The dashboard with the real Content-Security-Policy header ENFORCED.

Purpose    : cli/tests/ui/conftest.py's shared `page` fixture bypasses the
             CSP on every context it hands out (`bypass_csp=True`) --
             Playwright's own wait_for_function needs 'unsafe-eval', which the
             real policy does not grant, so every other file in this suite
             relies on that bypass. UAT2 N3 found 8 real CSP console errors on
             the Alerts tab alone (inline <col style="width:…">, dropped
             silently by style-src with no 'unsafe-inline') that nothing here
             was ever enforcing the policy to catch. This file opens its own
             context with the CSP left ON and walks every tab, so a future
             inline style="" or script="" regression fails a test instead of
             only showing up in a manual UAT screenshot pass.
Inputs     : `browser_session` (session-scoped Chromium, conftest.py's own
             fixture), `base_url`.
Outputs    : None -- assertion only.
Constraints: No wait_for_function/page.evaluate here (both need
             'unsafe-eval', which this file's CSP does not grant) -- plain
             selectors and clicks only, matching what a real CSP-locked
             browser actually allows.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")

#: Chromium's own console wording for a blocked style-src/script-src/etc.
#: directive ("Applying inline style violates the following Content Security
#: Policy directive: ..."); matching the phrase both directives share is
#: simpler than enumerating every directive name.
_CSP_VIOLATION_MARKER = "Content Security Policy"

_TABS = ("dashboard", "places", "groups", "alerts")

#: Leaflet's own vendored, unmodified code (web/vendor/leaflet/leaflet.js)
#: positions tiles and markers with `el.style.transform`/`.left`/`.top` --
#: a real, reproducible CSP violation (confirmed via ConsoleMessage.location,
#: 4/4 runs) with no fix available that doesn't mean hand-patching a vendored
#: third-party library or adding 'unsafe-inline' to the CSP. The latter is
#: closed off on purpose: test_security_guards_responses.py asserts
#: "unsafe-inline" not in CONTENT_SECURITY_POLICY as a hard security
#: invariant. This test still fails on any violation from anywhere else --
#: the app's own code, or a future dependency that isn't already an accepted
#: exception -- which is what UAT2 N3 asked this file to catch.
_KNOWN_VENDOR_VIOLATION = "/vendor/leaflet/leaflet.js"


@pytest_asyncio.fixture(loop_scope="session")
async def csp_page(browser_session):
    # @pytest_asyncio.fixture, not the plain @pytest.fixture this started
    # as: a bare @pytest.fixture wrapping an async generator never actually
    # ran under this session's asyncio loop, which hung every test that used
    # it instead of erroring -- conftest.py's own `page` fixture is the
    # working example this now matches exactly.
    browser, _ = browser_session
    # No bypass_csp: this is the one context in the suite that sees the
    # dashboard exactly as a real browser would.
    ctx = await browser.new_context()
    pg = await ctx.new_page()
    yield pg
    await ctx.close()


async def test_every_tab_loads_with_zero_csp_console_errors(csp_page, base_url) -> None:
    violations = []

    def on_console(msg):
        if msg.type != "error" or _CSP_VIOLATION_MARKER not in msg.text:
            return
        if _KNOWN_VENDOR_VIOLATION in (msg.location or {}).get("url", ""):
            return
        violations.append(msg.text)

    csp_page.on("console", on_console)

    await csp_page.goto(base_url + "/")
    await csp_page.wait_for_selector('button[data-tab="dashboard"]', state="attached")

    for tab in _TABS:
        await csp_page.click(f'button[data-tab="{tab}"]')
        # state="attached", not the default "visible": the panel's own box is
        # correct either way (confirmed against its `hidden` DOM property
        # directly), and "visible" additionally waits on a real paint, which
        # made this flake under a loaded machine for a reason unrelated to
        # what this test checks.
        await csp_page.wait_for_selector(f"#tab-{tab}:not([hidden])", state="attached")
        # A fixed pause, not eval-based waiting: gives any async render (the
        # deliveries/rules tables, the places/groups lists) a moment to
        # finish painting before moving to the next tab.
        await csp_page.wait_for_timeout(300)

    assert violations == [], "CSP violations:\n" + "\n".join(violations)
