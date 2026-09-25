"""Browser tests for the Apple accessory-key control (CF-P2-19).

The happy path hits the real daemon with a fixture plist shaped exactly like
test_routes_apple_accessories.py's own ({"Private Key": <base64>}), so the
route, the parser and the on-disk write are all real. The error cases mock
the route instead (413/422/409): reproducing them for real would mean either
uploading a 64 KiB file through a browser input or pre-registering state, and
auth_accessories.js only cares that it renders whatever `detail` the server
sent, which a mocked response proves without either.
"""

from __future__ import annotations

import base64
import plistlib

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

URL_PATTERN = "**/api/apple/accessories"


def _key_b64() -> str:
    return base64.b64encode(b"k" * 28).decode()


async def _open_settings(page, base_url) -> None:
    """Go to the dashboard and open Settings.

    main() wires #btn-settings (wireControls() -> wireSettingsControls())
    synchronously, right after initMap() stamps Leaflet's "leaflet-container"
    class onto #map -- no `await` between the two. A click straight after
    page.goto() can land before that wiring exists: page.goto() only waits
    for the 'load' event, not for main()'s own async boot chain, so the
    click is silently a no-op and #fp-auth-accessory-add (inside the still-
    closed Settings dialog) never becomes visible (full-lane timeout,
    2026-09-23 bisection -- same class of race _alerts_helpers.open_alerts_tab
    closes for its own tab-switch click). Waiting for #map.leaflet-container
    first proves wireControls() already ran.
    """
    await page.goto(base_url + "/#dashboard")
    await page.wait_for_selector("#map.leaflet-container", state="attached")
    await page.click("#btn-settings")
    await page.wait_for_selector("#fp-auth-accessory-add")


async def _add(page, name: str, file_path) -> None:
    await page.fill("#fp-auth-accessory-name", name)
    await page.set_input_files("#fp-auth-accessory-file", str(file_path))
    await page.click("#fp-auth-accessory-add")


async def test_happy_path_registers_an_accessory_with_a_real_plist(page, base_url, tmp_path):
    plist_path = tmp_path / "tag.plist"
    plist_path.write_bytes(plistlib.dumps({"Private Key": _key_b64()}))

    await _open_settings(page, base_url)
    await _add(page, "Backpack Tag", plist_path)

    await page.wait_for_function(
        "() => document.getElementById('fp-auth-accessory-status')"
        ".textContent.includes('Backpack Tag')"
    )
    assert await page.locator("#fp-auth-accessory-name").input_value() == ""


async def test_a_413_renders_inline(page, base_url, tmp_path):
    oversized_path = tmp_path / "big.plist"
    oversized_path.write_bytes(b"x")  # content is irrelevant; the route is mocked

    async def reply_413(route):
        await route.fulfill(status=413, json={"detail": "plist too large"})

    await page.route(URL_PATTERN, reply_413)
    try:
        await _open_settings(page, base_url)
        await _add(page, "Too Big", oversized_path)
        await page.wait_for_function(
            "() => document.getElementById('fp-auth-accessory-status').textContent"
            " === 'plist too large'"
        )
    finally:
        await page.unroute(URL_PATTERN, reply_413)


async def test_a_422_renders_inline(page, base_url, tmp_path):
    """A .json file whose key does not decode: the server's 422 detail, verbatim."""
    key_path = tmp_path / "key.json"
    key_path.write_text('{"private_key_b64": "not-base64!"}')

    async def reply_422(route):
        # CR-C-m4: the real server message dropped its CLI-flag wording
        # ("--private-key: ...") so a web user never sees a flag they never
        # typed; the mock here matches what the route actually sends now.
        await route.fulfill(status=422, json={"detail": "invalid base64"})

    await page.route(URL_PATTERN, reply_422)
    try:
        await _open_settings(page, base_url)
        await _add(page, "Bad Key", key_path)
        await page.wait_for_function(
            "() => document.getElementById('fp-auth-accessory-status').textContent"
            " === 'invalid base64'"
        )
    finally:
        await page.unroute(URL_PATTERN, reply_422)


async def test_409_offers_replace_and_retries_with_allow_overwrite(page, base_url, tmp_path):
    plist_path = tmp_path / "dup.plist"
    plist_path.write_bytes(plistlib.dumps({"Private Key": _key_b64()}))
    call_count = 0

    async def conflict_then_ok(route):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            await route.fulfill(
                status=409, json={"detail": "accessory 'apple:aa' is already registered"}
            )
        else:
            await route.fulfill(
                status=201,
                json={
                    "device_id": "apple:aa",
                    "name": "Replaced",
                    "kind": "plist",
                    "added_at": "t",
                },
            )

    await page.route(URL_PATTERN, conflict_then_ok)
    try:
        await _open_settings(page, base_url)
        page.once("dialog", lambda d: d.accept())  # window.confirm() -> true
        await _add(page, "Replaced", plist_path)
        await page.wait_for_function(
            "() => document.getElementById('fp-auth-accessory-status')"
            ".textContent.includes('Replaced')"
        )
        assert call_count == 2, "expected the 409 followed by exactly one retry"
    finally:
        await page.unroute(URL_PATTERN, conflict_then_ok)


async def test_declining_replace_does_not_retry(page, base_url, tmp_path):
    plist_path = tmp_path / "dup2.plist"
    plist_path.write_bytes(plistlib.dumps({"Private Key": _key_b64()}))
    call_count = 0

    async def always_409(route):
        nonlocal call_count
        call_count += 1
        await route.fulfill(
            status=409, json={"detail": "accessory 'apple:bb' is already registered"}
        )

    await page.route(URL_PATTERN, always_409)
    try:
        await _open_settings(page, base_url)
        page.once("dialog", lambda d: d.dismiss())  # window.confirm() -> false
        await _add(page, "Declined", plist_path)
        await page.wait_for_function(
            "() => document.getElementById('fp-auth-accessory-status').textContent"
            " === \"accessory 'apple:bb' is already registered\""
        )
        assert call_count == 1, "declining the confirm must not retry"
    finally:
        await page.unroute(URL_PATTERN, always_409)


async def test_purge_on_lock_clears_the_form(page, base_url, tmp_path):
    plist_path = tmp_path / "purge.plist"
    plist_path.write_bytes(plistlib.dumps({"Private Key": _key_b64()}))

    await _open_settings(page, base_url)
    await page.fill("#fp-auth-accessory-name", "Not Yet Sent")
    await page.set_input_files("#fp-auth-accessory-file", str(plist_path))

    await page.evaluate(
        """async () => {
            const lock = await import('/static/app/lock.js');
            await lock.purgeRenderedData();
        }"""
    )

    assert await page.locator("#fp-auth-accessory-name").input_value() == ""
    files = await page.evaluate(
        "() => document.getElementById('fp-auth-accessory-file').files.length"
    )
    assert files == 0
    assert await page.locator("#fp-auth-accessory-status").inner_text() == ""
