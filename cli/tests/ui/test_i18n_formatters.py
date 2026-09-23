"""CF-P2-E9-1: state.js's unit-ladder formatters route through i18n, not
literal English.

Purpose    : fmtAgeMinutes/fmtDuration/fmtDistance and the clear-all confirm
             word used to build their strings by hand ("{n} min", "DELETE")
             outside t()/plural(). Now every piece comes from
             web/locales/en.json's `units`/`timeline` namespaces. The literal
             English assertions below prove the output is byte-identical to
             the pre-fix behaviour, so no existing screenshot/string
             assertion elsewhere in the suite needed to change -- but on
             their own they cannot prove the catalog wiring actually fires,
             since a formatter that silently fell back to a hardcoded
             literal (or to the bundled CATALOG_EN) would read identically
             in English (CR-C closeout m6). The last test below closes that
             gap: it serves a `/static/locales/en.json` with one `units` key
             replaced by a sentinel and asserts the formatter's OUTPUT
             contains it, so a fall-back-to-literal regression -- which
             would still emit the plain "5 min" -- goes red here.
Inputs     : cli/tests/ui/conftest.py's `page` / `base_url` fixtures; the
             sentinel test also reads the real web/locales/en.json to patch
             it in memory, same pattern as test_alerts_catalog_load.py.
Constraints: The formatters are pure functions with no DOM dependency, so
             they are called directly via a dynamic import in the page
             context (test_honesty_notices.py's established pattern) rather
             than driving the UI to trigger them indirectly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG = REPO_ROOT / "web" / "locales" / "en.json"


async def _open_dashboard(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map.leaflet-container")


async def test_fmt_age_minutes_matches_pre_fix_english(page, base_url):
    """90 minutes now reads "90 min", not "1 h" -- UAT4 N33 moved the
    minutes-to-hours switch from 60 to 120 minutes, so this one value changed
    from the pre-fix behaviour the test name still describes for the other
    three; the day-ladder switch at 48 h is untouched.
    """
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
    assert result == ["unknown", "5 min", "90 min", "2 d"]


async def test_fmt_age_minutes_stays_in_minutes_to_120_then_carries_the_remainder(page, base_url):
    """UAT4 N33: the Groups stale badge read "no fix for 1 h" at 94 minutes
    while the presence note beside it (server-formatted, always raw minutes)
    read "(81 min ago)" for another member -- two ages in the same panel that
    looked contradictory. fmtAgeMinutes() now stays in minutes to 120 (94 ->
    "94 min", matching the note's own convention) and carries a minute
    remainder once it does switch to hours (125 -> "2 h 5 min"), rather than
    flooring it away (the old 90 -> "1 h" behaviour).
    """
    await _open_dashboard(page, base_url)
    result = await page.evaluate(
        """async () => {
            const state = await import('/static/app/state.js');
            return [
                state.fmtAgeMinutes(94),
                state.fmtAgeMinutes(119),
                state.fmtAgeMinutes(120),
                state.fmtAgeMinutes(125),
                state.fmtAgeMinutes(300),
            ];
        }"""
    )
    assert result == ["94 min", "119 min", "2 h", "2 h 5 min", "5 h"]


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


async def test_fmt_age_minutes_reads_the_served_catalog_not_a_hardcoded_literal(page, base_url):
    """CR-C closeout m6: the four tests above read identically whether the
    catalog wiring works or a regression falls back to a hardcoded literal /
    the bundled CATALOG_EN, because the English text is the same either way.
    Patch one `units` key with a sentinel and prove `fmtAgeMinutes`'s output
    carries it, so a fall-back regression -- which would still print the
    plain "5 min" -- makes this go red.
    """
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    sentinel = "ZZZ-UNITS-SENTINEL-{n}-ZZZ"
    assert data["units"]["minutesShort"] != sentinel, "sentinel already in en.json?"
    data["units"]["minutesShort"] = sentinel
    body = json.dumps(data)

    async def serve_patched_catalog(route):
        await route.fulfill(status=200, content_type="application/json", body=body)

    await page.route("**/static/locales/en.json", serve_patched_catalog)
    try:
        await _open_dashboard(page, base_url)
        result = await page.evaluate(
            """async () => {
                const state = await import('/static/app/state.js');
                return state.fmtAgeMinutes(5);
            }"""
        )
    finally:
        await page.unroute("**/static/locales/en.json", serve_patched_catalog)

    assert result == "ZZZ-UNITS-SENTINEL-5-ZZZ"
