"""Landmark and contrast checks for UAT #17 and #18 (split from test_a11y.py, size cap)."""

from __future__ import annotations

import pytest
from axe_playwright_python.async_playwright import Axe

from .conftest import set_theme
from .test_a11y import THEMES, WIDTHS, _describe

pytestmark = pytest.mark.asyncio(loop_scope="session")


LANDMARK_OPTIONS = {
    "resultTypes": ["violations"],
    "runOnly": {"type": "rule", "values": ["landmark-unique"]},
}


@pytest.mark.parametrize("width", WIDTHS)
async def test_landmarks_are_unique(page, base_url, width):
    """UAT #18: at phone width the empty top "Sections" nav and the bottom bar
    both carried the name, so landmark-unique failed."""
    await page.set_viewport_size({"width": width, "height": 800})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map.leaflet-container", state="attached")
    await page.wait_for_selector("#tracks > *", state="attached")
    results = await Axe().run(page, options=LANDMARK_OPTIONS)
    violations = results.response["violations"]
    assert not violations, "\n".join(_describe(v, "dashboard", "n/a", width) for v in violations)


@pytest.mark.parametrize("theme", THEMES)
async def test_timeline_gap_text_has_enough_contrast(page, base_url, theme):
    """UAT #17: light-theme .tl-gap text was 4.49:1. A gap row is injected,
    since the seed day has none, and axe's color-contrast rule scans it."""
    await page.goto(base_url + "/")
    await page.wait_for_selector("#tracks > *", state="attached")
    await set_theme(page, theme)
    await page.evaluate(
        """() => { const li = document.createElement('div'); li.className = 'tl-gap';
        li.id = 'probe-gap'; li.textContent = 'NO NEW DETECTIONS FOR 2 HR';
        document.getElementById('tracks').prepend(li); }"""
    )
    options = {
        "resultTypes": ["violations"],
        "runOnly": {"type": "rule", "values": ["color-contrast"]},
    }
    results = await Axe().run(page, context="#probe-gap", options=options)
    assert not results.response["violations"], results.response["violations"]
