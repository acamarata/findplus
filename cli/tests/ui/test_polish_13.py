"""Dashboard 1.3 polish: one button look for legacy classes.

`.btn`, `.btn-primary`, `.btn-secondary`, `.btn-danger` and `.btn-tiny` are
aliases of `.fp-btn` and its variants, so every old call site renders the same.
"""

from __future__ import annotations

import pytest

from .conftest import set_theme

pytestmark = pytest.mark.asyncio(loop_scope="session")

PROPS = [
    "backgroundColor",
    "color",
    "borderTopColor",
    "borderRadius",
    "minHeight",
    "fontSize",
    "paddingLeft",
]

PAIRS = [
    ("btn", "fp-btn fp-btn--primary"),
    ("btn btn-primary", "fp-btn fp-btn--primary"),
    ("btn-secondary", "fp-btn fp-btn--secondary"),
    ("btn btn-secondary", "fp-btn fp-btn--secondary"),
    ("btn btn-danger", "fp-btn fp-btn--danger"),
    ("btn btn-tiny", "fp-btn fp-btn--secondary fp-btn--sm"),
    ("btn btn-tiny btn-secondary", "fp-btn fp-btn--secondary fp-btn--sm"),
    ("btn btn-tiny btn-danger", "fp-btn fp-btn--danger fp-btn--sm"),
]

JS = """([pairs, props]) => {
  const host = document.body;
  return pairs.map(([a, b]) => {
    const out = [];
    for (const cls of [a, b]) {
      const el = document.createElement("button");
      el.className = cls; el.textContent = "x"; host.appendChild(el);
      const cs = getComputedStyle(el);
      out.push(props.map((p) => cs[p]));
      el.remove();
    }
    return [a, out[0], out[1]];
  });
}"""


@pytest.mark.parametrize("theme", ["light", "dark"])
async def test_legacy_button_classes_match_fp_btn(page, base_url, theme):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#fp-appbar-actions .fp-btn")
    await set_theme(page, theme)
    rows = await page.evaluate(JS, [PAIRS, PROPS])
    for legacy, old, new in rows:
        assert old == new, (legacy, old, new)


async def test_alerts_buttons_use_fp_btn(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#fp-add-rule-btn", state="attached")
    classes = await page.evaluate(
        "() => [...document.querySelectorAll('#tab-alerts button, #fp-rule-dialog button')]"
        ".map((b) => b.className)"
    )
    assert classes
    for cls in classes:
        assert "fp-btn" in cls or "fp-tab" in cls or "fp-channel" in cls, cls
        assert "btn-secondary" not in cls and "btn-tiny" not in cls and "btn-danger" not in cls, cls
