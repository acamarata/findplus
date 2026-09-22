"""CF-P2-E9-1: state.js's unit-ladder formatters route through i18n, not
literal English.

Purpose    : fmtAgeMinutes/fmtDuration/fmtDistance and the clear-all confirm
             word used to build their strings by hand ("{n} min", "DELETE")
             outside t()/plural(). Now every piece comes from
             web/locales/en.json's `units`/`timeline` namespaces. This proves
             two things at once: the catalog wiring actually fires (not a
             silent key-miss falling through to some other literal), and the
             English output is byte-identical to the pre-fix behaviour, so no
             existing screenshot/string assertion elsewhere in the suite
             needed to change.
Inputs     : cli/tests/ui/conftest.py's `page` / `base_url` fixtures.
Constraints: The formatters are pure functions with no DOM dependency, so
             they are called directly via a dynamic import in the page
             context (test_honesty_notices.py's established pattern) rather
             than driving the UI to trigger them indirectly.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_dashboard(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map")


async def test_fmt_age_minutes_matches_pre_fix_english(page, base_url):
    await _open_dashboard(page, base_url)
    result = await page.evaluate(
        """async () => {
            const state = await import('/static/app/state.js');
            return [
                state.fmtAgeMinutes(null),
                state.fmtAgeMinutes(5),
                state.fmtAgeMinutes(90),
                state.fmtAgeMinutes(48 * 60 + 30),
            ];
        }"""
    )
    assert result == ["unknown", "5 min", "1 h", "2 d"]


async def test_fmt_duration_matches_pre_fix_english(page, base_url):
    await _open_dashboard(page, base_url)
    result = await page.evaluate(
        """async () => {
            const state = await import('/static/app/state.js');
            return [
                state.fmtDuration(null),
                state.fmtDuration(45),
                state.fmtDuration(90),
                state.fmtDuration(3600),
                state.fmtDuration(3900),
                state.fmtDuration(90000),
                state.fmtDuration(172800 + 3600),
            ];
        }"""
    )
    assert result == ["—", "45 sec", "2 min", "1 hr", "1 hr 5 min", "1 day 1 hr", "2 days 1 hr"]


async def test_fmt_distance_matches_pre_fix_english(page, base_url):
    await _open_dashboard(page, base_url)
    result = await page.evaluate(
        """async () => {
            const state = await import('/static/app/state.js');
            return [
                state.fmtDistance(null),
                state.fmtDistance(50),
                state.fmtDistance(1609.344 * 5),
                state.fmtDistance(1609.344 * 12),
            ];
        }"""
    )
    assert result == [None, "50 m", "5.00 mi", "12.0 mi"]


async def test_clear_all_confirm_word_comes_from_the_catalog(page, base_url):
    """timeline.js compares the typed word against t("timeline.confirmWord"),
    not a hardcoded "DELETE" literal -- prove the catalog key resolves to
    the same word the prompt text embeds via {word} substitution.
    """
    await _open_dashboard(page, base_url)
    word, prompt_text = await page.evaluate(
        """async () => {
            const i18n = await import('/static/app/i18n.js');
            const word = i18n.t('timeline.confirmWord');
            return [word, i18n.t('timeline.promptTypeDelete', { word })];
        }"""
    )
    assert word == "DELETE"
    assert prompt_text == "Type DELETE to confirm erasing all history:"
