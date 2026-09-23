"""Playwright: upload -> assign -> render -> purge for a custom PNG icon.

Purpose : Prove the "Your icons" section (components/custom-icons.js, mounted
          inside components/icon-picker.js) works end to end through the real
          device dialog — upload a PNG, pick it, save, see it render on the
          device row's badge, then delete it once unassigned.
Constraints: `live_server` is session-scoped and shared with every other file
          in this directory (cli/tests/ui/conftest.py), so this test restores
          TAG-HOME's icon to the seeded "lucide:key" and deletes the icon it
          uploaded in a `finally` block, the same pattern test_devices_dialog.py
          uses for the label it edits. Bundled Chromium only (Test-run
          discipline, 2026-09-19) — never `channel="chrome"`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import struct
import zlib

import pytest
from axe_playwright_python.async_playwright import Axe

from .test_a11y import AXE_OPTIONS, BLOCKING
from .test_lock import PIN

pytestmark = pytest.mark.asyncio(loop_scope="session")

JSON_HEADERS = {"Content-Type": "application/json"}
SEEDED_ICON = "lucide:key"


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data))
    )


def _make_png(size: int = 32) -> bytes:
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 0, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xaa" * size for _ in range(size))
    idat = zlib.compress(raw)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


async def _open_edit_dialog(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("svg#fp-icon-sprite symbol[id='lucide-dog']", state="attached")
    await page.wait_for_selector("#map.leaflet-container")
    await page.click("#btn-devices")
    await page.wait_for_selector("#device-modal:not(.hidden)")
    await page.click('.device-row[data-device-id="TAG-HOME"] .fp-device-edit')
    await page.wait_for_selector("#fp-device-dialog[open]")
    await page.wait_for_selector(".fp-custom-icons .fp-icon-grid", state="attached")


async def _upload_icon(page, png_path) -> str:
    """Set the file input and return the new "custom:<id>".

    N10 (UAT2): choosing a file now starts the upload itself (no separate
    "Upload" click) -- set_input_files() fires the same native `change`
    event a real file picker would.
    """
    async with page.expect_response(
        lambda r: r.url.endswith("/api/icons/custom") and r.request.method == "POST"
    ) as resp_info:
        await page.set_input_files("#fp-device-dialog .fp-custom-icon-upload input", str(png_path))
    body = await (await resp_info.value).json()
    return body["id"]


async def _wait_selected(page, icon_id: str) -> None:
    """Wait until the dialog's hidden icon field holds `icon_id` -- what Save
    actually sends -- rather than trusting the upload's response alone."""
    await page.wait_for_function(
        "(id) => document.getElementById('fp-device-icon').value === id", arg=icon_id
    )


async def _restore_seeded_icon(page, base_url) -> None:
    resp = await page.request.patch(
        f"{base_url}/api/devices/TAG-HOME",
        data=json.dumps({"icon": SEEDED_ICON}),
        headers=JSON_HEADERS,
    )
    assert resp.ok, await resp.text()


async def test_upload_assign_render_and_purge(page, base_url, tmp_path):
    png_path = tmp_path / "icon.png"
    png_path.write_bytes(_make_png())

    await _open_edit_dialog(page, base_url)
    icon_id = await _upload_icon(page, png_path)
    short = icon_id.split(":", 1)[1]

    try:
        # Assign: the upload auto-selects the new icon (custom-icons.js).
        swatch = page.locator(f'#fp-device-dialog [data-icon-id="{icon_id}"]')
        await swatch.wait_for(state="visible")
        assert await swatch.get_attribute("aria-pressed") == "true"
        assert await page.input_value("#fp-device-icon") == icon_id

        # Save, then reopen to prove the assignment persisted.
        await page.click("#fp-device-dialog button:has-text('Save')")
        await page.wait_for_selector("#fp-device-dialog:not([open])", state="attached")
        await _open_edit_dialog(page, base_url)
        assert await page.input_value("#fp-device-icon") == icon_id

        # Render: the device row's badge draws the uploaded PNG, clipped.
        await page.click("#fp-device-dialog button:has-text('Cancel')")
        await page.wait_for_selector("#fp-device-dialog:not([open])", state="attached")
        row = page.locator('.device-row[data-device-id="TAG-HOME"]')
        image = row.locator(f'.fp-device-badge image[href="/api/icons/custom/{short}.png"]')
        assert await image.count() == 1

        # Purge: unassign first (an in-use icon refuses to delete, 409), then
        # delete it through the picker's own "x" button -- a sibling of the
        # select button inside the wrapper span, not nested inside it
        # (nested-interactive fix, 2026-09-23), hence the `+` combinator.
        await _restore_seeded_icon(page, base_url)
        await _open_edit_dialog(page, base_url)
        page.on("dialog", lambda d: d.accept())
        await page.click(f'#fp-device-dialog [data-icon-id="{icon_id}"] + .fp-icon-delete')
        await page.locator(f'#fp-device-dialog [data-icon-id="{icon_id}"]').wait_for(
            state="detached"
        )
        listed = await page.request.get(f"{base_url}/api/icons/custom")
        assert icon_id not in await listed.json()
    finally:
        with contextlib.suppress(Exception):
            await _restore_seeded_icon(page, base_url)
        with contextlib.suppress(Exception):
            await page.request.delete(f"{base_url}/api/icons/custom/{short}")


async def test_lock_purges_every_custom_icon_thumbnail(page, base_url, tmp_path):
    """N1 (review, 2026-09-22): `purgeDialog()` used to call `iconPicker.
    setValue()`, which only changes which swatch is pressed — the "Your
    icons" section's `<img>` thumbnails (and the device row's own badge
    `<image>`) survived a lock, readable from DevTools behind the lock
    screen. `devices_dialog.js` now destroys the pickers on purge instead;
    this proves no `/api/icons/custom/` reference remains anywhere in the
    DOM once locked, not only inside the dialog.
    """
    png_path = tmp_path / "icon.png"
    png_path.write_bytes(_make_png())

    await _open_edit_dialog(page, base_url)
    icon_id = await _upload_icon(page, png_path)
    short = icon_id.split(":", 1)[1]
    try:
        await _wait_selected(page, icon_id)
        await page.click("#fp-device-dialog button:has-text('Save')")
        await page.wait_for_selector("#fp-device-dialog:not([open])", state="attached")

        set_pin = await page.request.post(
            base_url + "/api/settings/pin",
            data=json.dumps({"new_pin": PIN}),
            headers=JSON_HEADERS,
        )
        assert set_pin.ok, await set_pin.text()
        # Reopen so the picker's own uploaded-thumbnail img is on screen too,
        # not just the device row's badge image.
        await _open_edit_dialog(page, base_url)
        await page.locator(f'[data-icon-id="{icon_id}"] img').wait_for(state="visible")
        row_image = page.locator(f'.fp-device-badge image[href="/api/icons/custom/{short}.png"]')
        assert await row_image.count() >= 1

        await page.evaluate("import('/static/app/lock.js').then((m) => m.lockNow())")
        await page.wait_for_selector("#lock-screen:not(.hidden)")
        await page.wait_for_selector("#fp-device-dialog:not([open])", state="attached")

        assert await page.locator('img[src^="/api/icons/custom/"]').count() == 0
        assert await page.locator('image[href^="/api/icons/custom/"]').count() == 0
        assert "/api/icons/custom/" not in await page.content()
    finally:
        await _unlock_remove_pin_and_cleanup_icon(page, base_url, short)


async def _unlock_remove_pin_and_cleanup_icon(page, base_url, short: str) -> None:
    """Teardown for test_lock_purges_every_custom_icon_thumbnail: unlock with
    the PIN it set, remove that PIN, then restore the seeded icon and delete
    the uploaded one -- every step best-effort, so an earlier failure inside
    it never masks the test's own assertion failure."""
    with contextlib.suppress(Exception):
        await page.request.post(
            f"{base_url}/api/lock/unlock",
            data=json.dumps({"pin": PIN}),
            headers=JSON_HEADERS,
        )
    with contextlib.suppress(Exception):
        del_resp = await page.request.delete(
            f"{base_url}/api/settings/pin",
            data=json.dumps({"current_pin": PIN}),
            headers=JSON_HEADERS,
        )
        assert del_resp.ok, await del_resp.text()
    with contextlib.suppress(Exception):
        await _restore_seeded_icon(page, base_url)
    with contextlib.suppress(Exception):
        await page.request.delete(f"{base_url}/api/icons/custom/{short}")


async def test_upload_rejects_a_non_png_file(page, base_url, tmp_path):
    bad_path = tmp_path / "icon.svg"
    bad_path.write_bytes(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>")

    await _open_edit_dialog(page, base_url)
    status = page.locator("#fp-device-dialog .fp-custom-icon-status")
    async with page.expect_response(
        lambda r: r.url.endswith("/api/icons/custom") and r.request.method == "POST"
    ):
        await page.set_input_files("#fp-device-dialog .fp-custom-icon-upload input", str(bad_path))
    await page.wait_for_function(
        "el => el.textContent.trim() !== ''", arg=await status.element_handle()
    )
    assert (await status.inner_text()).strip() != ""
    await page.click("#fp-device-dialog button:has-text('Cancel')")


async def test_save_right_after_upload_sends_the_uploaded_icon(page, base_url, tmp_path):
    """CI run 35909159774: the upload only selected the new icon after a
    second GET /api/icons/custom came back, so a Save in that window PATCHed
    the old icon. Hold that GET open and prove Save still sends the upload."""
    png_path = tmp_path / "icon.png"
    png_path.write_bytes(_make_png())
    release = asyncio.Event()
    gets = {"n": 0}

    async def hold_second_list(route):
        if route.request.method == "GET":
            gets["n"] += 1
            if gets["n"] >= 2:
                await release.wait()
        await route.continue_()

    await page.route("**/api/icons/custom", hold_second_list)
    await _open_edit_dialog(page, base_url)
    icon_id = await _upload_icon(page, png_path)
    try:
        await _wait_selected(page, icon_id)
        # The response, not just the request: the restore in `finally` must
        # land after this PATCH, or TAG-HOME keeps the upload and the icon
        # delete below 409s as in use, leaking both into later files.
        async with page.expect_response(lambda r: r.request.method == "PATCH") as patch_info:
            await page.click("#fp-device-dialog button:has-text('Save')")
        patch = await patch_info.value
        assert patch.ok, await patch.text()
        assert json.loads(patch.request.post_data)["icon"] == icon_id
    finally:
        release.set()
        with contextlib.suppress(Exception):
            await _restore_seeded_icon(page, base_url)
        with contextlib.suppress(Exception):
            await page.request.delete(f"{base_url}/api/icons/custom/{icon_id.split(':', 1)[1]}")


async def test_no_serious_axe_violations_with_a_custom_icon(page, base_url, tmp_path):
    """A custom icon's delete "x" used to sit inside the select button itself
    -- a serious `nested-interactive` violation axe never had a custom icon
    on screen to catch before (custom-icons.js's swatch/delete restructure,
    2026-09-23). Upload one, scan the picker with it visible, delete it in a
    `finally` (test_a11y.py's dialog-scan pattern, applied here since it is
    this file's fixture that gets a custom icon onto the page)."""
    png_path = tmp_path / "icon.png"
    png_path.write_bytes(_make_png())
    await _open_edit_dialog(page, base_url)
    icon_id = await _upload_icon(page, png_path)
    short = icon_id.split(":", 1)[1]
    try:
        await _wait_selected(page, icon_id)
        results = await Axe().run(page, options=AXE_OPTIONS)
        violations = [v for v in results.response["violations"] if v.get("impact") in BLOCKING]
        assert not violations, "\n".join(
            f"{v['impact']}: {v['id']} -> "
            + ", ".join(str(n.get("target")) for n in v.get("nodes", [])[:3])
            for v in violations
        )
    finally:
        with contextlib.suppress(Exception):
            await _restore_seeded_icon(page, base_url)
        with contextlib.suppress(Exception):
            await page.request.delete(f"{base_url}/api/icons/custom/{short}")
