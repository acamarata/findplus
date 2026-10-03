"""honesty.UPDATE_CHECK, word for word: the one request automatic updates make.

Purpose    : The sentence the Settings > Updates section, README and wiki carry.
             Kept here (not in test_honesty_text.py, at its file cap), and that
             file's EXPECTED imports it, so /api/config is pinned exactly too.
"""

from __future__ import annotations

from findplus import honesty

UPDATE_CHECK_TEXT = (
    "Automatic updates ask GitHub's releases API for the newest Find+ about every six "
    "hours and download a new version from the same GitHub release. The request names "
    "only the Find+ version; nothing about you, your trackers or your history is sent, "
    "though GitHub sees this computer's IP address. Turn automatic updates off to stop "
    "these requests."
)


def test_the_update_sentence_is_exact() -> None:
    assert honesty.UPDATE_CHECK == UPDATE_CHECK_TEXT
    assert honesty.NOTICES["update_check"] is honesty.UPDATE_CHECK
