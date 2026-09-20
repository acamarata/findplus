"""Browser tests for the icon picker, the colour picker and the badge renderer.

Purpose    : Prove the three components of P2-E3 work before E4 and E5 wire
             them into the device and group dialogs, so a regression shows up
             here rather than deep inside a later epic's test failures.
Inputs     : cli/tests/ui/conftest.py's `page` / `base_url` fixtures (one real
             `findplus serve --no-poller` against a seeded throwaway database).
Outputs    : Assertions only.
Constraints: None of the three is mounted anywhere yet, so each test imports
             the module dynamically inside the page and mounts it into a
             scratch `#picker-host`. Anything that needs a Lucide symbol waits
             for the sprite's own DOM evidence, never a sleep -- the icon
             picker reads the sprite synchronously and does not retry. The
             sprite element is `display:none`, so the wait is for `attached`.
"""

from __future__ import annotations

import pytest

from findplus.labels import resolve_icon_letter

pytestmark = pytest.mark.asyncio(loop_scope="session")

SPRITE_READY = "svg#fp-icon-sprite symbol[id='lucide-dog']"

# The scratch host is pinned above the dashboard so a click on a swatch cannot
# be intercepted by the map or the footer it would otherwise land under.
_MAKE_HOST = """() => {
    const host = document.createElement('div');
    host.id = 'picker-host';
    host.style.position = 'fixed';
    host.style.inset = '0 auto auto 0';
    host.style.zIndex = '9999';
    host.style.background = 'var(--panel)';
    document.body.appendChild(host);
}"""


async def _open_with_host(page, base_url, *, sprite: bool = True) -> None:
    await page.goto(base_url + "/")
    if sprite:
        await page.wait_for_selector(SPRITE_READY, state="attached")
    await page.evaluate(_MAKE_HOST)


async def _mount_icon_picker(page) -> None:
    await page.evaluate(
        """async () => {
            const { createIconPicker } = await import('/static/app/components/icon-picker.js');
            window.__picker = createIconPicker(document.getElementById('picker-host'), {
                value: 'letter',
                onChange: (v) => { window.__lastValue = v; },
            });
        }"""
    )


async def test_icon_picker_renders_grouped_sections(page, base_url) -> None:
    await _open_with_host(page, base_url)
    await _mount_icon_picker(page)
    pets = page.locator("#picker-host section[data-group='pets'] button[data-icon-id='lucide:dog']")
    assert await pets.count() == 1
    other = page.locator("#picker-host section[data-group='other'] button[data-icon-id='letter']")
    assert await other.count() == 1
    assert await page.locator("#picker-host .fp-icon-swatch").count() == 50


async def test_icon_picker_css_lands(page, base_url) -> None:
    """CR-C-E3 F3: the grid, swatch and none-dot all get real computed styles."""
    await _open_with_host(page, base_url)
    await _mount_icon_picker(page)
    grid = page.locator("#picker-host .fp-icon-grid").first
    assert await grid.evaluate("(el) => getComputedStyle(el).display") == "flex"
    swatch = page.locator("#picker-host button[data-icon-id='lucide:dog']")
    box = await swatch.bounding_box()
    assert box["width"] > 0 and box["height"] > 0
    none_dot = page.locator("#picker-host .fp-icon-none-dot")
    dot_box = await none_dot.bounding_box()
    assert dot_box["width"] > 0 and dot_box["height"] > 0
    await page.locator("#picker-host button[data-icon-id='lucide:dog']").click()
    pressed_border = await swatch.evaluate("(el) => getComputedStyle(el).borderColor")
    unpressed = page.locator("#picker-host button[data-icon-id='lucide:cat']")
    unpressed_border = await unpressed.evaluate("(el) => getComputedStyle(el).borderColor")
    assert pressed_border != unpressed_border


async def test_icon_sprite_404_does_not_inject_parser_error(page, base_url) -> None:
    """CR-C-E3 F2: a missing sprite must never leak XML parser error text."""
    await page.route(
        "**/static/icons.svg",
        lambda route: route.fulfill(status=404, body="not found"),
    )
    await page.goto(base_url + "/")
    await page.wait_for_timeout(300)  # let the fire-and-forget fetch settle
    body_text = await page.locator("body").inner_text()
    assert "error on line" not in body_text
    assert "parsererror" not in body_text.lower()
    assert await page.locator("#fp-icon-sprite").count() == 0


async def test_icon_picker_click_emits_lucide_id(page, base_url) -> None:
    await _open_with_host(page, base_url)
    await _mount_icon_picker(page)
    await page.locator("#picker-host button[data-icon-id='lucide:cat']").click()
    assert await page.evaluate("window.__lastValue") == "lucide:cat"
    cat = page.locator("#picker-host button[data-icon-id='lucide:cat']")
    dog = page.locator("#picker-host button[data-icon-id='lucide:dog']")
    assert await cat.get_attribute("aria-pressed") == "true"
    assert await dog.get_attribute("aria-pressed") == "false"


async def test_icon_picker_letter_flow(page, base_url) -> None:
    await _open_with_host(page, base_url)
    await _mount_icon_picker(page)
    letter_input = page.locator("#picker-host .fp-icon-letter-input")
    assert not await letter_input.is_visible()
    await page.locator("#picker-host button[data-icon-id='letter']").click()
    assert await letter_input.is_visible()
    assert await letter_input.get_attribute("aria-label") == "Letter"
    await letter_input.fill("q")
    assert await page.evaluate("window.__lastValue") == "letter:Q"
    await letter_input.fill("")
    assert await page.evaluate("window.__lastValue") == "letter"


async def test_icon_picker_click_letter_swatch_emits_without_typing(page, base_url) -> None:
    """CR-C-E3 F1: bare "letter" is a complete value -- the click alone must emit."""
    await _open_with_host(page, base_url)
    await page.evaluate(
        """async () => {
            const { createIconPicker } = await import('/static/app/components/icon-picker.js');
            window.__picker = createIconPicker(document.getElementById('picker-host'), {
                value: 'lucide:dog',
                onChange: (v) => { window.__lastValue = v; },
            });
        }"""
    )
    letter_btn = page.locator("#picker-host button[data-icon-id='letter']")
    await letter_btn.click()
    assert await page.evaluate("window.__lastValue") == "letter"
    assert await page.evaluate("window.__picker.getValue()") == "letter"
    assert await letter_btn.get_attribute("aria-pressed") == "true"
    dog = page.locator("#picker-host button[data-icon-id='lucide:dog']")
    assert await dog.get_attribute("aria-pressed") == "false"


async def test_icon_picker_get_set_and_destroy(page, base_url) -> None:
    await _open_with_host(page, base_url)
    await _mount_icon_picker(page)
    await page.evaluate("window.__picker.setValue('lucide:dog')")
    assert await page.evaluate("window.__picker.getValue()") == "lucide:dog"
    dog = page.locator("#picker-host button[data-icon-id='lucide:dog']")
    assert await dog.get_attribute("aria-pressed") == "true"
    await page.evaluate("window.__picker.destroy()")
    assert await page.evaluate("document.getElementById('picker-host').innerHTML") == ""


async def test_icon_picker_set_value_prefills_the_pinned_letter(page, base_url) -> None:
    """Re-opening an edit dialog on a lettered device shows that character."""
    await _open_with_host(page, base_url)
    await _mount_icon_picker(page)
    await page.evaluate("window.__picker.setValue('letter:Q')")
    letter_swatch = page.locator("#picker-host button[data-icon-id='letter']")
    letter_input = page.locator("#picker-host .fp-icon-letter-input")
    assert await letter_swatch.get_attribute("aria-pressed") == "true"
    assert await letter_input.input_value() == "Q"
    assert await letter_input.is_visible()


async def test_color_picker_renders_twelve_swatches_and_emits(page, base_url) -> None:
    await _open_with_host(page, base_url, sprite=False)
    third = await page.evaluate(
        """async () => {
            const mod = await import('/static/app/components/color-picker.js');
            window.__picker = mod.createColorPicker(document.getElementById('picker-host'), {
                onChange: (v) => { window.__lastValue = v; },
            });
            // Read the palette back off the rendered swatches, so this test can
            // never disagree with color-picker.js's own constant.
            return document.querySelectorAll('#picker-host .fp-color-swatch')[2].dataset.color;
        }"""
    )
    assert await page.locator("#picker-host .fp-color-swatch").count() == 12
    assert await page.locator("#picker-host input[type='color']").count() == 1
    custom = page.locator("#picker-host .fp-color-custom")
    assert await custom.get_attribute("aria-label") == "Custom colour"
    await page.locator("#picker-host .fp-color-swatch").nth(2).click()
    emitted = await page.evaluate("window.__lastValue")
    assert emitted == third
    assert emitted.startswith("#") and emitted == emitted.lower() and len(emitted) == 7


async def test_color_picker_set_value_lowercases(page, base_url) -> None:
    await _open_with_host(page, base_url, sprite=False)
    value = await page.evaluate(
        """async () => {
            const mod = await import('/static/app/components/color-picker.js');
            const picker = mod.createColorPicker(document.getElementById('picker-host'), {});
            picker.setValue('#E7663F');
            return picker.getValue();
        }"""
    )
    assert value == "#e7663f"


async def test_badge_render_badge_lucide_letter_and_none(page, base_url) -> None:
    await _open_with_host(page, base_url)
    result = await page.evaluate(
        """async () => {
            const mod = await import('/static/app/components/badge.js');
            const html = (icon, color, label, name) =>
                mod.renderBadge({ icon, color, label, name }).outerHTML;
            const el = mod.renderBadge({
                icon: 'lucide:dog', color: '#4f8cf7', label: null, name: 'Rex',
            });
            return {
                isSvgElement: el instanceof SVGElement,
                lucide: el.outerHTML,
                letter: html('letter', '#37c67a', null, 'fido'),
                pinned: html('letter:Z', '#e7663f', 'anything', 'anything'),
                none: html('none', '#c77ae6', null, 'x'),
                fallback: html('letter', '#000', null, ''),
            };
        }"""
    )
    assert result["isSvgElement"] is True
    assert 'href="#lucide-dog"' in result["lucide"]
    assert 'fill="#4f8cf7"' in result["lucide"]
    assert ">F<" in result["letter"]
    assert ">Z<" in result["pinned"]
    assert "<use" not in result["none"] and "<text" not in result["none"]
    assert ">?<" in result["fallback"]


async def test_badge_ring(page, base_url) -> None:
    """R-P2-2: the disc carries a 2 px ring in the page background token."""
    await _open_with_host(page, base_url, sprite=False)
    circle = await page.evaluate(
        """async () => {
            const { renderBadge } = await import('/static/app/components/badge.js');
            const el = renderBadge({ icon: 'none', color: '#4f8cf7', label: null, name: 'Rex' });
            const c = el.querySelector('circle');
            return { stroke: c.getAttribute('stroke'), width: c.getAttribute('stroke-width') };
        }"""
    )
    assert circle == {"stroke": "var(--bg)", "width": "2"}


@pytest.mark.parametrize(
    ("icon", "label", "name", "expected"),
    [
        ("letter:Z", None, "anything", "Z"),
        ("letter", "Jo", "ignored", "J"),
        ("letter", None, "fido", "F"),
        ("lucide:dog", "x", "y", None),
        ("none", "x", "y", None),
    ],
)
async def test_badge_resolve_icon_letter_matches_python(
    page, base_url, icon, label, name, expected
) -> None:
    await _open_with_host(page, base_url, sprite=False)
    from_js = await page.evaluate(
        """async ({ icon, label, name }) => {
            const { resolveIconLetter } = await import('/static/app/components/badge.js');
            return resolveIconLetter(icon, label, name);
        }""",
        {"icon": icon, "label": label, "name": name},
    )
    assert from_js == expected
    assert resolve_icon_letter(icon, label, name) == expected
