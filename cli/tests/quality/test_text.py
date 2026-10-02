"""Plain-words reasons: the API text and web/locales/en.json say the same thing."""

from __future__ import annotations

import json
from pathlib import Path

from findplus.quality import rules as r
from findplus.quality.text import REASON_TEXT, reason_text

CATALOG = Path(__file__).parents[3] / "web" / "locales" / "en.json"


def test_every_reason_code_has_a_sentence_in_the_catalog() -> None:
    reasons = json.loads(CATALOG.read_text(encoding="utf-8"))["quality"]["reason"]
    assert set(reasons) == set(r.REASON_CODES) == set(REASON_TEXT)
    assert reasons == REASON_TEXT


def test_reason_text_picks_the_most_serious_code() -> None:
    both = [r.LOW_ACCURACY, r.ABA_TELEPORT]
    assert reason_text(both) == REASON_TEXT[r.ABA_TELEPORT]
    assert reason_text([]) is None


def test_sentences_name_what_happens_and_use_no_dashes_as_connectors() -> None:
    for code in (r.ABA_TELEPORT, r.IMPOSSIBLE_SPEED, r.EDGE_STRAY, r.SIBLING_DISAGREE):
        assert REASON_TEXT[code].endswith("Left out of stays, trips and alerts.")
    assert not any(chr(0x2014) in t or chr(0x2013) in t for t in REASON_TEXT.values())
