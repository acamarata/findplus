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
Inputs     : cli/tests/ui/conftest.py's `page` / `base_url` fixtures; the
             real web/locales/en.json, patched in memory with one sentinel
             value before being route-served.
Constraints: Routes only `/static/locales/en.json` -- CATALOG_EN (the
             bundled fallback i18n.js falls through to) is a separate file
             never touched by this route, so a passing test proves the
             fetched catalog actually won the race, not that both happen to
             agree.
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
    assert data["alerts"]["telegramHeading"] != SENTINEL, "sentinel already in en.json?"
    data["alerts"]["telegramHeading"] = SENTINEL
    body = json.dumps(data)

    async def serve_patched_catalog(route):
        await route.fulfill(status=200, content_type="application/json", body=body)

    await page.route("**/static/locales/en.json", serve_patched_catalog)
    try:
        await open_alerts_tab(page, base_url)
        heading = await page.locator("#fp-telegram-section h3").text_content()
    finally:
        await page.unroute("**/static/locales/en.json", serve_patched_catalog)

    assert heading == SENTINEL
