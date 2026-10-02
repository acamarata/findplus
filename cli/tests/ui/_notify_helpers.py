"""Helpers for the place-dialog alert box tests: connect channels by writing alerts.json."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

WEBHOOK = {"url": "http://127.0.0.1:9/hook", "secret": None}
WHATSAPP = {"phone": "+34123123123", "apikey": "fake-apikey-123"}


@contextlib.contextmanager
def channels(ui_env: dict, **connected):
    """Write alerts.json with the given channels for the block, then empty it again."""
    path = Path(ui_env["FINDPLUS_STATE_DIR"]) / "alerts.json"
    path.write_text(json.dumps({"channels": connected}))
    try:
        yield path
    finally:
        path.write_text(json.dumps({"channels": {}}))


async def open_add_dialog(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell[data-fp-ready]")
    await page.click('button[data-tab="places"]')
    await page.click("#fp-add-place-btn")
    await page.wait_for_selector("#fp-place-dialog[open]")
    await page.wait_for_function(
        "() => document.getElementById('fp-place-notify-line')?.textContent.length > 0"
        " || document.getElementById('fp-place-notify-channel')?.options.length > 0"
    )


async def delete_places(page, base_url, *names):
    for place in await (await page.request.get(base_url + "/api/places")).json():
        if place["name"] in names:
            await page.request.delete(f"{base_url}/api/places/{place['id']}")
