"""Playwright browser tests for the Places tab (P1-E10-W6-S1-T1..T4).

Seed data (cli/tests/ui/conftest.py): devices TAG-HOME/TAG-AWAY/TAG-STALE;
place "Home" at (41.1, -80.1) r=200m with TAG-HOME and TAG-AWAY both
inside it (so a presence chip is guaranteed on load); group "Family".
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

HOME_LAT, HOME_LON = 41.100000, -80.100000


async def _open_dashboard(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map")


async def _wait_for_popup_to_settle(page) -> None:
    """Block until the open popup has a real box, so a click lands where it looks.

    Leaflet auto-pans the map to fit a freshly opened popup. A click computed while
    that pan is still running resolves against a stale rectangle, and Playwright
    then reports whatever sits under the point as the receiver — which is how the
    browser job failed on CI run 35522235405 with `section.controls` named as the
    interceptor even though `.controls` sits entirely above `#map` and cannot
    overlap it. This is a state check, never a sleep.
    """
    await page.wait_for_function(
        """() => {
            const el = document.querySelector(".leaflet-popup");
            if (!el) return false;
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
        }""",
        timeout=3000,
    )


async def _close_open_popups(page) -> None:
    """Dismiss the open popup through Leaflet instead of clicking its close button.

    `closePopup()` needs no coordinates, so it cannot race the pan the way a pixel
    click on `.leaflet-popup-close-button` did.
    """
    await page.evaluate(
        """async () => {
            const { state } = await import("/static/app/state.js");
            if (state.map) state.map.closePopup();
        }"""
    )
    await page.wait_for_selector(".leaflet-popup", state="detached", timeout=3000)


async def _click_popup_button(page, place_name, button_text):
    """Click each rendered place circle until its popup names `place_name`.

    Two Leaflet quirks this works around: (1) a device's position marker
    sits in a pane above the SVG overlay pane, so a circle directly under a
    marker (e.g. the seeded "Home" place) can never itself be clicked — not
    an issue here since the test-created circles are offset away from any
    marker; (2) Escape does not close a Leaflet popup, so `.leaflet-popup-
    content` accumulates one element per prior click — `.last` always reads
    the most recently opened popup instead of hitting a strict-mode
    violation, and `_close_open_popups` dismisses it through Leaflet.
    """
    paths = page.locator("#map svg path.leaflet-interactive")
    count = await paths.count()
    for i in reversed(range(count)):
        try:
            await paths.nth(i).click(timeout=1500)
        except Exception:
            continue
        popup = page.locator(".leaflet-popup-content").last
        try:
            await popup.wait_for(state="visible", timeout=1500)
            await _wait_for_popup_to_settle(page)
        except Exception:
            continue
        if place_name in await popup.inner_text():
            await popup.get_by_text(button_text, exact=True).click()
            return
        await _close_open_popups(page)
    raise AssertionError(f"no popup found naming {place_name!r}")


async def test_places_tab_visible(page, base_url):
    await _open_dashboard(page, base_url)
    await page.wait_for_selector('button[data-tab="places"]')


async def test_add_place_dialog_opens(page, base_url):
    # U4/U10: "Add place" opens the dialog straight away, at the map's
    # current centre -- no map click involved at all any more.
    await _open_dashboard(page, base_url)
    await page.click('button[data-tab="places"]')
    await page.click("#fp-add-place-btn")
    await page.wait_for_selector("#fp-place-dialog[open]")


async def test_add_place_is_reachable_by_keyboard(page, base_url):
    """U10: 'Add place' then Enter used to do nothing -- a place could only
    be created by clicking the map. The button is now the whole affordance,
    so focusing it and pressing Enter must open the dialog on its own."""
    await _open_dashboard(page, base_url)
    await page.click('button[data-tab="places"]')
    await page.locator("#fp-add-place-btn").focus()
    await page.keyboard.press("Enter")
    await page.wait_for_selector("#fp-place-dialog[open]")


async def test_add_place_dialog_has_a_title_and_dialog_chrome(page, base_url):
    """U3: the dialog used to paint as an unstyled browser-default strip."""
    await _open_dashboard(page, base_url)
    await page.click('button[data-tab="places"]')
    await page.click("#fp-add-place-btn")
    dialog = page.locator("#fp-place-dialog")
    await dialog.wait_for(state="visible")
    # text_content(), not inner_text(): the shared `h2 { text-transform:
    # uppercase }` rule (also applied to the group/device dialog titles)
    # renders this visually as "ADD PLACE" -- a styling choice, not a typo.
    assert await page.locator("#fp-place-dialog-title").text_content() == "Add place"
    box = await dialog.bounding_box()
    assert box is not None and box["width"] > 250, "the dialog should have a real min-width"
    styles = await dialog.evaluate(
        """(el) => {
            const s = getComputedStyle(el);
            return { radius: s.borderRadius, bg: s.backgroundColor };
        }"""
    )
    assert styles["radius"] not in ("0px", ""), "U3: no border-radius at all"
    assert styles["bg"] not in ("rgba(0, 0, 0, 0)", "", "rgb(255, 255, 255)"), (
        "U3: the dialog painted as the browser default white box"
    )


async def test_add_place_saves(page, base_url):
    await _open_dashboard(page, base_url)
    await page.click('button[data-tab="places"]')
    await page.click("#fp-add-place-btn")
    dialog = page.locator("#fp-place-dialog")
    await dialog.wait_for(state="visible")
    # Not "Home" — that name is already taken by the seeded place and would
    # 409 without ever exercising the save path. `#fp-place-name`, not a bare
    # input[type="text"] selector: the dialog now also has a search input.
    await dialog.locator("#fp-place-name").fill("Office")
    await dialog.locator('input[type="range"]').fill("50")
    await dialog.get_by_text("Save", exact=True).click()
    await page.wait_for_function("() => !document.getElementById('fp-place-dialog').open")

    resp = await page.request.get(base_url + "/api/places")
    names = [p["name"] for p in await resp.json()]
    assert "Office" in names


async def test_use_tracker_location_fills_coordinates(page, base_url):
    """U4: 'Use a tracker's last location' calls the real /api/latest — no
    mock needed, the seeded devices have real fixes."""
    await _open_dashboard(page, base_url)
    await page.click('button[data-tab="places"]')
    await page.click("#fp-add-place-btn")
    dialog = page.locator("#fp-place-dialog")
    await dialog.wait_for(state="visible")

    # "Away Tag" (TAG-AWAY's plain name — TAG-HOME carries a label instead,
    # "Ali's Keys", which is what the select would show for it).
    await dialog.locator("#fp-place-tracker-select").select_option(label="Away Tag")
    await dialog.locator("#fp-place-use-tracker-btn").click()
    # Polls for the actual fix landing, not merely a change from zero: the
    # dialog can open at the world-view default centre (lat 20), which is
    # itself non-zero, so a bare "!== 0" check can pass before the async
    # /api/latest call this button fires has resolved.
    await page.wait_for_function(
        f"() => Math.abs(Number(document.getElementById('fp-place-lat').value) - {HOME_LAT}) < 1"
    )
    lat = await dialog.locator("#fp-place-lat").input_value()
    lon = await dialog.locator("#fp-place-lon").input_value()
    assert abs(float(lat) - HOME_LAT) < 1
    assert abs(float(lon) - HOME_LON) < 1


async def test_address_search_is_opt_in_and_mocked(page, base_url):
    """U4: search fires only on Search (or Enter), never on keystroke, and
    the daemon — not the browser — talks to Nominatim, so this test mocks
    /api/places/search rather than hitting the network (R-P2-30.2)."""
    await _open_dashboard(page, base_url)
    await page.click('button[data-tab="places"]')

    calls = []

    async def handle(route):
        calls.append(route.request.url)
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                [
                    {
                        "display_name": "1600 Amphitheatre Pkwy",
                        "latitude": 37.42,
                        "longitude": -122.08,
                    }
                ]
            ),
        )

    await page.route("**/api/places/search*", handle)

    await page.click("#fp-add-place-btn")
    dialog = page.locator("#fp-place-dialog")
    await dialog.wait_for(state="visible")

    search_input = dialog.locator("#fp-place-search-input")
    await search_input.fill("1600 Amphitheatre Pkwy")
    assert calls == [], "typing alone must never call the search API"

    await dialog.locator("#fp-place-search-btn").click()
    results = dialog.locator("#fp-place-search-results")
    await results.wait_for(state="visible")
    assert len(calls) == 1
    await results.get_by_text("1600 Amphitheatre Pkwy", exact=True).click()

    lat = await dialog.locator("#fp-place-lat").input_value()
    assert abs(float(lat) - 37.42) < 0.001


async def test_place_circle_renders(page, base_url):
    await _open_dashboard(page, base_url)
    await page.click('button[data-tab="places"]')
    await page.wait_for_selector("#map svg path.leaflet-interactive")


async def test_edit_place(page, base_url):
    # +0.004 lon (~330m east at this latitude), small 50m radius — clear of
    # "Home" (200m radius) and off the TAG-HOME/TAG-AWAY markers, so this
    # circle is never covered by another circle or a marker in the SVG.
    resp = await page.request.post(
        base_url + "/api/places",
        data=json.dumps(
            {
                "name": "Edit Me",
                "latitude": HOME_LAT,
                "longitude": HOME_LON + 0.004,
                "radius_meters": 50,
            }
        ),
        headers={"Content-Type": "application/json"},
    )
    assert resp.ok, await resp.text()

    await _open_dashboard(page, base_url)
    await page.click('button[data-tab="places"]')
    await page.wait_for_selector("#map svg path.leaflet-interactive")
    await _click_popup_button(page, "Edit Me", "Edit")

    dialog = page.locator("#fp-place-dialog")
    await dialog.wait_for(state="visible")
    name_input = dialog.locator("#fp-place-name")
    assert await name_input.input_value() == "Edit Me"
    radius_input = dialog.locator('input[type="range"]')
    assert await radius_input.input_value() == "50"


async def test_delete_place_confirm(page, base_url):
    # -0.004 lon (~330m west) — clear of "Home" and "Edit Me" (+0.004).
    resp = await page.request.post(
        base_url + "/api/places",
        data=json.dumps(
            {
                "name": "Delete Me",
                "latitude": HOME_LAT,
                "longitude": HOME_LON - 0.004,
                "radius_meters": 50,
            }
        ),
        headers={"Content-Type": "application/json"},
    )
    assert resp.ok, await resp.text()

    await _open_dashboard(page, base_url)
    await page.click('button[data-tab="places"]')
    await page.wait_for_selector("#map svg path.leaflet-interactive")
    page.once("dialog", lambda d: d.accept())  # window.confirm() -> true
    await _click_popup_button(page, "Delete Me", "Delete")

    await page.wait_for_function(
        """async () => {
            const r = await fetch('/api/places');
            const places = await r.json();
            return !places.some((p) => p.name === 'Delete Me');
        }"""
    )


async def test_presence_chip_appears(page, base_url):
    await _open_dashboard(page, base_url)
    await page.click("#btn-devices")
    await page.wait_for_selector('[data-device-id="TAG-HOME"]')
    chip = page.locator('[data-device-id="TAG-HOME"] .fp-presence-chip')
    await chip.wait_for(state="visible")
    assert "Home" in await chip.inner_text()


async def test_default_view_fits_the_tracked_devices_latest_fixes(page, base_url):
    """U4: the map used to open on a hardcoded US-centre view (Kansas) no
    matter what the account actually tracks. Calling setDefaultView()
    directly (rather than only trusting whatever the day's own fitBounds
    happens to do) pins the fix at its source."""
    await _open_dashboard(page, base_url)
    center = await page.evaluate(
        """async () => {
            const { setDefaultView } = await import('/static/app/map.js');
            const { state } = await import('/static/app/state.js');
            await setDefaultView();
            const c = state.map.getCenter();
            return { lat: c.lat, lng: c.lng };
        }"""
    )
    # The seeded devices/places sit near HOME_LAT/HOME_LON; the old default
    # was 39.5, -98.35 (Kansas) regardless of any seeded data.
    assert abs(center["lat"] - HOME_LAT) < 2
    assert abs(center["lng"] - HOME_LON) < 2


async def test_places_list_renders_the_seeded_place(page, base_url):
    """U5: the side panel used to show only 'Add place' and the hint, even
    with places saved -- an off-screen place could not be found, edited or
    deleted at all."""
    await _open_dashboard(page, base_url)
    await page.click('button[data-tab="places"]')
    row = page.locator("#fp-places-list [data-place-id]", has_text="Home")
    await row.wait_for(state="visible")
    text = await row.inner_text()
    assert "Home" in text
    assert "200" in text  # the seeded "Home" place's radius, in the metres meta


async def test_places_list_edit_opens_the_dialog_prefilled(page, base_url):
    await _open_dashboard(page, base_url)
    await page.click('button[data-tab="places"]')
    row = page.locator("#fp-places-list [data-place-id]", has_text="Home")
    await row.wait_for(state="visible")
    await row.get_by_text("Edit", exact=True).click()
    dialog = page.locator("#fp-place-dialog")
    await dialog.wait_for(state="visible")
    assert await dialog.locator("#fp-place-name").input_value() == "Home"


async def test_places_list_centre_click_pans_the_map(page, base_url):
    """Clicking the row body (not a button) centres the map on that place —
    U5's click-to-centre. The seeded default view is a world/local view far
    from a 0-zoom accident, so a real pan is distinguishable from a no-op."""
    await _open_dashboard(page, base_url)
    await page.click('button[data-tab="places"]')
    row = page.locator("#fp-places-list [data-place-id]", has_text="Home")
    await row.wait_for(state="visible")
    before = await page.evaluate(
        "async () => { const { state } = await import('/static/app/state.js'); "
        "state.map.setView([0, 0], 2); return state.map.getCenter(); }"
    )
    await row.click(position={"x": 5, "y": 5})  # the swatch corner, never a button
    after = await page.evaluate(
        "async () => { const { state } = await import('/static/app/state.js'); "
        "return state.map.getCenter(); }"
    )
    assert abs(after["lat"] - before["lat"]) > 1 or abs(after["lng"] - before["lng"]) > 1


async def test_places_list_delete_removes_the_row(page, base_url):
    resp = await page.request.post(
        base_url + "/api/places",
        data=json.dumps(
            {
                "name": "List Delete Me",
                "latitude": HOME_LAT,
                "longitude": HOME_LON + 0.01,
                "radius_meters": 60,
            }
        ),
        headers={"Content-Type": "application/json"},
    )
    assert resp.ok, await resp.text()

    await _open_dashboard(page, base_url)
    await page.click('button[data-tab="places"]')
    row = page.locator("#fp-places-list [data-place-id]", has_text="List Delete Me")
    await row.wait_for(state="visible")
    page.once("dialog", lambda d: d.accept())
    await row.get_by_text("Delete", exact=True).click()
    await row.wait_for(state="detached")


async def test_the_devices_dialog_opens_even_when_a_decoration_fails(page, base_url):
    """CI-2: the device rows rendered but the dialog stayed hidden.

    CI run 35530635344 timed out on `[data-device-id="TAG-HOME"]`: the element
    resolved but was HIDDEN through 61 retries. openDevices() removed `hidden`
    only after renderDeviceModal() returned, so anything that threw while
    filling the dialog left the rows in the DOM and invisible, with no error on
    screen either. The failure is simulated here by deleting the element
    updateModalRate() writes to, which is the same class of fault as whatever
    CI hit; the fix makes the symptom impossible whichever decoration fails.
    """
    await _open_dashboard(page, base_url)

    result = await page.evaluate(
        """async () => {
            const devices = await import('/static/app/devices.js');
            const rate = document.getElementById('device-rate');
            const parent = rate.parentNode;
            const next = rate.nextSibling;
            rate.remove();  // updateModalRate() now throws on a null element
            try {
                await devices.openDevices();
            } finally {
                parent.insertBefore(rate, next);
            }
            const modal = document.getElementById('device-modal');
            const row = document.querySelector('[data-device-id="TAG-HOME"]');
            return {
                hidden: modal.classList.contains('hidden'),
                rows: document.querySelectorAll('#device-list .device-row').length,
                rowVisible: row ? row.offsetParent !== null : false,
            };
        }"""
    )

    assert result["hidden"] is False, "the dialog must open even when a decoration throws"
    assert result["rows"] >= 1, "the rows themselves must still render"
    assert result["rowVisible"] is True, "a row in a hidden dialog is a row nobody can see"

    await page.click("#btn-close-devices")


async def test_booting_does_not_close_a_dialog_the_user_opened(page, base_url):
    """CI-2's actual cause: a click during boot was undone by boot.

    bootDashboard() awaits loadStatus() and loadDay() -- two network round
    trips -- and only then calls applyHashRoute(), which closed every modal
    when the URL carried no hash. The toolbar is live throughout, so a click on
    Devices during that window opened the dialog and boot closed it again,
    leaving the rows in the DOM and invisible. CI run 35530635344 hit it as
    "62 x locator resolved to hidden"; it reproduces locally in the full
    browser job, where the shared page makes the timing vary.
    """
    await _open_dashboard(page, base_url)

    state_after = await page.evaluate(
        """async () => {
            const [devices, main] = await Promise.all([
                import('/static/app/devices.js'),
                import('/static/app/main.js'),
            ]);
            await devices.openDevices();          // the user clicks Devices
            await main.applyHashRoute({ closeOthers: false });   // boot catches up
            const modal = document.getElementById('device-modal');
            const row = document.querySelector('[data-device-id="TAG-HOME"]');
            return {
                hidden: modal.classList.contains('hidden'),
                rowVisible: row ? row.offsetParent !== null : false,
            };
        }"""
    )

    assert state_after["hidden"] is False, "boot closed the dialog the user had opened"
    assert state_after["rowVisible"] is True

    # A real hashchange away from a dialog still closes it.
    closed = await page.evaluate(
        """async () => {
            const main = await import('/static/app/main.js');
            await main.applyHashRoute();
            return document.getElementById('device-modal').classList.contains('hidden');
        }"""
    )
    assert closed is True, "an explicit route change must still close the dialog"


async def test_the_devices_dialog_opens_normally(page, base_url):
    """The control: nothing failing, the dialog still opens with visible rows."""
    await _open_dashboard(page, base_url)
    await page.click("#btn-devices")
    await page.wait_for_selector('[data-device-id="TAG-HOME"]', state="visible")

    assert await page.locator("#device-modal").is_visible()
