"""Keep the browser suite off the network: stub every OpenStreetMap tile.

Purpose    : `web/app/map.js` points Leaflet at
             https://tile.openstreetmap.org/{z}/{x}/{y}.png, so every test
             that renders the map fetched real tiles (36 in one wizard Places
             test) -- PRI hard rule 3 says tests never touch the network, and
             `boot/conftest.py`'s goto(wait_until="networkidle") waited on
             them. `stub_osm_tiles()` answers each tile request locally with a
             1x1 transparent PNG, status 200, so Leaflet still sees a good
             image and no failed-request console error reaches the tests that
             assert a clean console (test_lock.py and friends).
Inputs     : A Playwright BrowserContext, sync or async API.
Outputs    : The context's route registration (awaitable on the async API,
             None on the sync one); every page the context opens inherits it.
Constraints: Call it on every browser.new_context() in cli/tests/ui/ before
             the first page loads. Routing at the context, not the page,
             covers pages a test opens later itself. The img-src CSP already
             allows this origin, so test_csp_enforced.py's CSP-on context
             accepts the stubbed image too.
"""

from __future__ import annotations

import base64

#: Glob Playwright matches against each request URL; the tile layer's only host.
OSM_TILE_ROUTE = "https://tile.openstreetmap.org/**"

#: A valid 68-byte 1x1 RGBA PNG, fully transparent.
BLANK_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNgAAIAAAUAAen63NgAAAAASUVORK5CYII="
)


def stub_osm_tiles(context):
    """Route every OSM tile request on `context` to BLANK_PNG.

    Works on both APIs: `await stub_osm_tiles(ctx)` for async_api contexts,
    a plain call for sync_api ones.
    """

    # A new function per call, never one module-level handler: Playwright
    # caches its API wrapper on the handler object itself, so a handler first
    # registered by a sync_api test (boot/) hands sync Route objects to every
    # async_api context after it, and each fulfill then dies on a missing
    # greenlet and leaves the tile request pending forever.
    def fulfill_tile(route):
        # route.fulfill() returns None on the sync API and a coroutine on the
        # async one, which Playwright awaits for a route handler.
        return route.fulfill(status=200, content_type="image/png", body=BLANK_PNG)

    return context.route(OSM_TILE_ROUTE, fulfill_tile)
