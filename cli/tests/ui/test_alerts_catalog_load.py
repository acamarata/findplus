"""E9-CRC-F5: the Alerts tab renders from the fetched catalog, not the
bundled English fallback.

Purpose    : alerts.js's init() runs from main.js's boot chain, after the
             awaited loadCatalog() -- not as a module-top-level call racing
             it (that was the original finding; loop 1 already moved the
             call site into the boot chain, verified by grep: alerts.js has
             no top-level `init()` call left, only the exported function and
             main.js's `await import("./alerts.js").then((m) => m.init())`).
             This test is the regression guard the finding asked for: if a
             future change reintroduces a top-level call, or reorders the
             boot chain so alerts.js runs before the catalog fetch lands,
             the served catalog's text stops showing up here and this test
             catches it -- rather than the gap staying invisible the way it
             did before, since the English fallback and the English catalog
             read identically.
Inputs     : cli/tests/ui/conftest.py's `page` / `base_url` fixtures (the
             device "TAG-HOME" they seed); the real web/locales/en.json,
             patched in memory with one sentinel value before being
             route-served.
Constraints: Routes only `/static/locales/en.json` -- CATALOG_EN (the
             bundled fallback i18n.js falls through to) is a separate file
             never touched by this route, so a passing test proves the
             fetched catalog actually won the race, not that both happen to
             agree.

CR-C closeout M3 (2026-09-22): the previous version of this test asserted
against `#fp-telegram-section h3`, which is static `data-i18n` markup
(partials/alerts.html) rendered by `applyStaticI18n()` in main.js's boot
chain -- a step that always runs, and always sits downstream of the awaited
`loadCatalog()`, well before `alerts.js` is even imported. That assertion
could not fail on the regression it claimed to guard, because the static
heading is translated on a code path the regression never touches.

This version instead asserts a table cell that `alerts.js`'s own
`init() -> refreshAll() -> loadRules() -> renderRulesTable()` chain renders
through `t()` (alerts_rules.js's `buildRuleRow`, the "On enter" cell) -- a
path that only runs once `alerts.js` has actually been imported and called,
which is exactly the code CR-C's finding is about. A rule is created via
the API first (same pattern as `test_delete_rule_removes_row` in
test_alerts_rules.py) so there is a row for that render to produce.

Reproduction (scratch git worktree, not this checkout): applied CR-C's
described mutation -- a bare top-level `init();` appended to alerts.js, and
main.js's `await import("./alerts.js").then((m) => m.init())` replaced with
an un-awaited `import("./alerts.js")` -- and reran this test. On this
machine's fast loopback dev server the catalog fetch (one small local JSON
request) resolves well before `alerts.js` needs it regardless of the
`await`, because `main()` still awaits two other dynamic imports
(places.js, groups.js) between `loadCatalog()` and the alerts.js line, so
the two-line mutation alone did not turn this test red here. Adding one
more change on top -- an artificial delay on the `/static/locales/en.json`
route response, forcing the fetch to lose the race it would otherwise win
by sheer local speed -- did turn it red, with a clean value mismatch on the
"On enter" cell (served sentinel vs. the bundled fallback's plain "yes").
That confirms this assertion target is genuinely downstream of the race
this test exists to catch; the two-line mutation not tripping it by itself
is a property of this dev server's timing, not of the assertion. The
worktree was restored to HEAD and this test reran green before being
copied back here unmutated; no mutation was ever applied to this checkout.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .conftest import open_alerts_tab

pytestmark = pytest.mark.asyncio(loop_scope="session")

REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG = REPO_ROOT / "web" / "locales" / "en.json"

SENTINEL = "ZZZ-SERVED-CATALOG-SENTINEL-ZZZ"


async def test_alerts_tab_shows_the_served_catalog_not_the_bundled_fallback(page, base_url):
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert data["common"]["yes"] != SENTINEL, "sentinel already in en.json?"
    data["common"]["yes"] = SENTINEL
    body = json.dumps(data)

    async def serve_patched_catalog(route):
        await route.fulfill(status=200, content_type="application/json", body=body)

    await page.route("**/static/locales/en.json", serve_patched_catalog)

    create_resp = await page.request.post(
        base_url + "/api/alerts/rules",
        data=json.dumps(
            {
                "name": "Catalog race rule",
                "device_id": "TAG-HOME",
                "channels": ["webhook"],
            }
        ),
        headers={"Content-Type": "application/json"},
    )
    assert create_resp.ok, await create_resp.text()

    try:
        await open_alerts_tab(page, base_url)
        row = page.locator("#fp-rules-tbody tr", has_text="Catalog race rule")
        await row.wait_for(state="visible")
        on_enter_cell = row.locator("td").nth(3)
        cell_text = await on_enter_cell.text_content()
    finally:
        await page.unroute("**/static/locales/en.json", serve_patched_catalog)

    assert cell_text == SENTINEL
