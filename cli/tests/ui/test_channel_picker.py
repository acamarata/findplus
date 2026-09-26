"""Browser tests for web/app/components/channel-picker.js.

Purpose    : Prove the render/read pair before E10/E11 build on it: it shows
             exactly the available channels, ticks exactly the selected ones,
             and reads back alphabetically whatever the DOM order was.
Inputs     : cli/tests/ui/conftest.py's `page` / `base_url` fixtures.
Constraints: The component is mounted into a scratch host, the same way
             test_icon_color_pickers.py mounts the icon picker.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

_MAKE_HOST = """() => {
    const old = document.getElementById('channel-host');
    if (old) old.remove();
    const host = document.createElement('div');
    host.id = 'channel-host';
    document.body.appendChild(host);
}"""


async def _mount(page, base_url, selected, available, labels=None, connected=None):
    await page.goto(base_url + "/")
    await page.evaluate(_MAKE_HOST)
    return await page.evaluate(
        """async ({selected, available, labels, connected}) => {
            const mod = await import('/static/app/components/channel-picker.js');
            const host = document.getElementById('channel-host');
            mod.renderChannelPicker(host, {
                selected, available, labels: labels || {},
                connected: connected ? new Set(connected) : null,
            });
            window.__readPicker = () => mod.readChannelPicker(host);
            const dcls = 'fp-channel-picker-option--disconnected';
            return Array.from(host.querySelectorAll('input[type=checkbox]')).map((el) => ({
                id: el.dataset.channel,
                checked: el.checked,
                disabled: el.disabled,
                disconnected: el.parentElement.classList.contains(dcls),
                label: el.parentElement.textContent.trim(),
            }));
        }""",
        {"selected": selected, "available": available, "labels": labels, "connected": connected},
    )


async def test_it_renders_one_checkbox_per_available_channel(page, base_url) -> None:
    rendered = await _mount(page, base_url, ["telegram"], ["telegram", "webhook", "whatsapp"])
    assert [r["id"] for r in rendered] == ["telegram", "webhook", "whatsapp"]


async def test_a_channel_absent_from_available_never_renders(page, base_url) -> None:
    rendered = await _mount(page, base_url, ["telegram"], ["telegram", "webhook", "whatsapp"])
    assert "native" not in [r["id"] for r in rendered]


async def test_exactly_the_selected_ids_are_checked(page, base_url) -> None:
    rendered = await _mount(
        page, base_url, ["webhook", "native"], ["telegram", "webhook", "whatsapp", "native"]
    )
    checked = {r["id"] for r in rendered if r["checked"]}
    assert checked == {"webhook", "native"}


async def test_read_returns_the_checked_ids_alphabetically(page, base_url) -> None:
    await _mount(
        page, base_url, ["webhook", "native"], ["telegram", "webhook", "whatsapp", "native"]
    )
    assert await page.evaluate("() => window.__readPicker()") == ["native", "webhook"]


async def test_read_returns_an_empty_list_when_nothing_is_checked(page, base_url) -> None:
    await _mount(page, base_url, [], ["telegram", "webhook"])
    assert await page.evaluate("() => window.__readPicker()") == []


async def test_the_caller_supplies_every_label(page, base_url) -> None:
    """The component imports no i18n and bakes in no English (D-P2-12)."""
    rendered = await _mount(
        page, base_url, [], ["telegram", "native"], {"telegram": "Telegrama", "native": "Mac"}
    )
    assert [r["label"] for r in rendered] == ["Telegrama", "Mac"]


async def test_an_unlabelled_channel_falls_back_to_its_id(page, base_url) -> None:
    rendered = await _mount(page, base_url, [], ["whatsapp"])
    assert rendered[0]["label"] == "whatsapp"


async def test_a_second_render_replaces_the_first(page, base_url) -> None:
    await _mount(page, base_url, ["telegram"], ["telegram", "webhook"])
    rendered = await _mount(page, base_url, ["webhook"], ["telegram", "webhook"])
    assert len(rendered) == 2
    assert [r["checked"] for r in rendered] == [False, True]


async def test_a_channel_absent_from_connected_is_flagged_and_disabled(page, base_url) -> None:
    """UAT U11 (disabling added UAT7 N05): a channel with no stored
    credentials is flagged (dimmed class + whatever "(not connected)" suffix
    the caller put in its label) AND disabled -- ticking it could only ever
    reach the server's own "at least one connected channel" refusal
    (routes_alerts_rules.py), so this prevents that round trip instead of
    letting a person reach it."""
    rendered = await _mount(
        page, base_url, ["telegram", "webhook"], ["telegram", "webhook"], connected=["webhook"]
    )
    telegram, webhook = rendered
    assert telegram["disabled"] is True
    assert telegram["checked"] is True, "flagged, not force-unticked"
    assert telegram["disconnected"] is True
    assert webhook["disabled"] is False
    assert webhook["checked"] is True
    assert webhook["disconnected"] is False


async def test_native_is_never_disabled_even_when_absent_from_connected(page, base_url) -> None:
    """native has no credential concept and is always deliverable -- it must
    never be disabled, even though `connected` (built from telegram/webhook/
    whatsapp credentials only) never actually lists it."""
    rendered = await _mount(
        page, base_url, ["native"], ["native", "webhook"], connected=["webhook"]
    )
    native, webhook = rendered
    assert native["disabled"] is False
    assert native["disconnected"] is False
    assert webhook["disabled"] is False


async def test_no_connected_set_means_nothing_is_flagged(page, base_url) -> None:
    """Backward compatibility: a caller that never learned about U11 (omits
    `connected`) gets the pre-U11 behaviour, nothing flagged."""
    rendered = await _mount(page, base_url, ["telegram"], ["telegram", "webhook"])
    assert all(r["disabled"] is False for r in rendered)
    assert all(r["disconnected"] is False for r in rendered)
